# SPDX-License-Identifier: Apache-2.0
"""Agent transports: the plan, the real local MCP path and the real A2A exchange over ephemeral mutual TLS.

The mcp, a2a and cryptography extras are installed in CI and in the local .venv, so the real paths run here; the
fallbacks are exercised by patching availability, never by skipping.
"""
from dataclasses import replace
import os
import stat
import unittest
from unittest import mock

from aegisflow_dr.agents import transport as T
from aegisflow_dr.agents.context import PolicyDenied
from aegisflow_dr.batch import downstream, run_batch
from aegisflow_dr.coordination.contracts import MAX_MESSAGE_BYTES
from aegisflow_dr.integration.a2a_profile import SEND_PATH, VERSION, ProtocolError
from aegisflow_dr.integration.secure_review import TransportError, post_json
from aegisflow_dr.pipeline import InputRejected, diagnose_csv, generate_orders
from aegisflow_dr.profiling import profile_csv
from aegisflow_dr.security.policy import EgressPolicy

ORDERS = generate_orders(rows=24, fault="null_total")
TASK = {"task_id": "run-1.a27", "run_id": "run-1", "agent_id": "A27", "budget": {"max_tool_calls": 0}}


class Plan(unittest.TestCase):
    def test_requests_and_availability(self):
        self.assertTrue(T.mcp_available() and T.a2a_available())
        self.assertFalse(T._importable("json", "aegisflow_dr_missing_module"))
        self.assertEqual(T.plan("auto")["tools"], {"mode": "mcp_local", "reason": None})
        self.assertEqual(T.plan("auto")["judge"], {"mode": "a2a_mtls", "reason": None})
        self.assertEqual(T.plan("mcp")["judge"], {"mode": "in_process", "reason": "a2a_not_requested"})
        self.assertEqual(T.plan("a2a")["tools"], {"mode": "in_process", "reason": "mcp_not_requested"})
        self.assertEqual(T.plan("in_process")["requested"], "in_process")
        with mock.patch.object(T, "_importable", return_value=False):
            self.assertEqual(T.plan("mcp")["tools"], {"mode": "in_process", "reason": "mcp_extra_unavailable"})
            self.assertEqual(T.plan("a2a")["judge"], {"mode": "in_process", "reason": "a2a_extra_unavailable"})
        with self.assertRaises(InputRejected):
            T.plan("smoke-signals")


class Mcp(unittest.TestCase):
    def setUp(self):
        self.tools = T.McpTools()

    def test_profile_tools_round_trip_through_the_official_client(self):
        for name, fn, args in (("diagnose_csv", diagnose_csv, (ORDERS,)), ("run_batch", run_batch, (ORDERS,)),
                               ("query_lineage", downstream, ("source_orders",))):
            with self.subTest(name):
                arguments, reason = self.tools.route(name, fn, args, {})
                self.assertIsNone(reason)
                value, transport, why = self.tools.invoke(name, arguments, fn, args)
                self.assertEqual((value, transport, why), (fn(*args), "mcp_local", None))

    def test_calls_the_profile_cannot_carry_stay_in_process_with_a_reason(self):
        big = b"order_id,total\n" + b"".join(b"%d,1.00\n" % n for n in range(3000))
        cases = (("profile_csv", profile_csv, (ORDERS,), {}, "tool_not_in_mcp_profile"),
                 ("diagnose_csv", profile_csv, (ORDERS,), {}, "unsupported_call"),
                 ("run_batch", run_batch, (ORDERS,), {"transform": "clean"}, "unsupported_call"),
                 ("diagnose_csv", diagnose_csv, ("text",), {}, "unsupported_call"),
                 ("diagnose_csv", diagnose_csv, (b"\xff\xfe",), {}, "payload_not_utf8"),
                 ("diagnose_csv", diagnose_csv, (big,), {}, "payload_exceeds_mcp_limit"),
                 ("query_lineage", downstream, ("customer_sales",), {}, "unsupported_call"))
        for name, fn, args, kwargs, reason in cases:
            with self.subTest(reason=reason, name=name):
                self.assertEqual(self.tools.route(name, fn, args, kwargs), (None, reason))

    def test_gateway_outcomes_are_typed(self):
        arguments = {"dataset": "source_orders", "csv_text": ORDERS.decode()}

        def outcome(value):
            return mock.patch.object(T.McpTools, "_exchange", new=mock.AsyncMock(
                return_value={"outcome": value, "report": None}))

        # The OK path without the real client too: on Python 3.11/3.12 line tracing does not survive the official
        # client's event loop, so the round-trip test alone does not show this branch as covered there.
        converted = (lambda report: ("converted", report),)
        with outcome("OK"), mock.patch.dict(T.MCP_TOOLS, {"diagnose_csv": T.MCP_TOOLS["diagnose_csv"][:2] + converted}):
            self.assertEqual(self.tools.invoke("diagnose_csv", arguments, diagnose_csv, (ORDERS,)),
                             (("converted", None), "mcp_local", None))
        with outcome("OUTPUT_REJECTED"):
            self.assertEqual(self.tools.invoke("diagnose_csv", arguments, diagnose_csv, (ORDERS,)),
                             (diagnose_csv(ORDERS), "in_process", "mcp_output_limit"))
        with outcome("INPUT_REJECTED"), self.assertRaises(InputRejected):
            self.tools.invoke("diagnose_csv", arguments, diagnose_csv, (ORDERS,))
        with outcome("DENIED"), self.assertRaises(PolicyDenied):
            self.tools.invoke("diagnose_csv", arguments, diagnose_csv, (ORDERS,))
        with outcome("TOOL_ERROR"), self.assertRaisesRegex(RuntimeError, "TOOL_ERROR"):
            self.tools.invoke("diagnose_csv", arguments, diagnose_csv, (ORDERS,))
        oversize = {"dataset": "source_orders", "csv_text": "x" * 20_000}  # the real profile's schema refuses it
        with self.assertRaisesRegex(RuntimeError, "INVALID_REQUEST"):
            self.tools.invoke("diagnose_csv", oversize, diagnose_csv, (b"x",))


class Certificates(unittest.TestCase):
    def test_private_directory_and_keys_are_removed(self):
        with T.ephemeral_pki() as pki:
            root = pki.root
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)
            for files in (pki.server, pki.client):
                self.assertEqual(stat.S_IMODE(os.stat(files.private_key_file).st_mode), 0o600)
                self.assertTrue(files.private_key_file.is_relative_to(root))
            self.assertEqual(len({pki.ca_sha256, pki.server_sha256, pki.client_sha256}), 3)
            self.assertEqual(set(pki.fingerprints()), {"ca_sha256", "server_sha256", "client_sha256"})
        self.assertFalse(root.exists())
        with self.assertRaises(RuntimeError):
            with T.ephemeral_pki() as pki:
                root = pki.root
                raise RuntimeError("run failed")
        self.assertFalse(root.exists())


class A2A(unittest.TestCase):
    def test_real_mutual_tls_exchange(self):
        seen = []

        def review(task):
            seen.append(task)
            return {"task_id": task["task_id"], "claims": [{"count": 3, "share": 0.5}]}

        with T.ephemeral_pki() as pki:
            reply = T.a2a_review(TASK, review, pki=pki)
        self.assertEqual(seen, [TASK])
        self.assertEqual(reply, {"task_id": "run-1.a27", "claims": [{"count": 3, "share": 0.5}]})
        self.assertIs(type(reply["claims"][0]["count"]), int)

    def test_unpinned_client_and_foreign_ca_are_refused(self):
        with T.ephemeral_pki() as pki, T.ephemeral_pki() as other:
            for material in (replace(pki, client_sha256="0" * 64), replace(pki, client=other.client)):
                with self.subTest(material is None), self.assertRaises(TransportError):
                    T.a2a_review(TASK, lambda task: {"ok": True}, pki=material)

    def test_profile_violations_are_refused(self):
        from a2a.types import a2a_pb2 as pb
        from aegisflow_dr.integration.a2a_profile import wire

        def request(task, role=pb.ROLE_USER):
            return wire(pb.SendMessageRequest(message=T._message(pb, role, T._context_id(task), "task", task)))

        with T.ephemeral_pki() as pki:
            server, thread = T._serve(pki, TASK, lambda task: {"ok": True})
            try:
                endpoint = EgressPolicy("localhost", server.server_port, "127.0.0.1", pki.server_sha256,
                                        path=SEND_PATH, allow_loopback=True)
                for body, version in ((request({**TASK, "task_id": "run-1.a10"}), VERSION),  # another task
                                      (request(TASK, pb.ROLE_AGENT), VERSION),  # wrong role
                                      (request(TASK), None)):  # no A2A-Version header
                    with self.subTest(version=version), self.assertRaises(TransportError):
                        post_json(body, endpoint=endpoint, material=pki.client, a2a_version=version)
                ok = post_json(request(TASK), endpoint=endpoint, material=pki.client, a2a_version=VERSION)
                self.assertEqual(T._unwrap(ok, pb.SendMessageResponse(), "ROLE_AGENT", T._context_id(TASK), "result"),
                                 {"ok": True})
                with self.assertRaises(ProtocolError):
                    T._unwrap(ok, pb.SendMessageResponse(), "ROLE_AGENT", T._context_id({"run_id": "x"}), "result")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
        self.assertLess(len(request(TASK)), MAX_MESSAGE_BYTES)

    def test_a_failing_review_closes_the_exchange(self):
        def broken(task):
            raise RuntimeError("judge crashed")

        with T.ephemeral_pki() as pki, self.assertRaises(TransportError):
            T.a2a_review(TASK, broken, pki=pki)

    def test_struct_numbers_are_restored_to_integers(self):
        self.assertEqual(T._integral({"a": [1.0, 2.5, True, None, "x"], "b": {"c": 3.0}}),
                         {"a": [1, 2.5, True, None, "x"], "b": {"c": 3}})


if __name__ == "__main__":
    unittest.main()
