# SPDX-License-Identifier: Apache-2.0
from hashlib import sha256
from http.client import IncompleteRead
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from aegisflow_dr.advisory.context_cache import CacheIdentity, ContextCache
from aegisflow_dr.agents import llm
from aegisflow_dr.agents.llm import LLMResult, LocalModel
from aegisflow_dr.pipeline import InputRejected
from referencing.exceptions import NoSuchResource

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["mechanisms"],
          "properties": {"mechanisms": {"type": "array", "maxItems": 3,
                                        "items": {"enum": ["partial_load", "duplicate_delivery"]}}}}
IDENTITY = CacheIdentity("local", "a23", "p1", sha256(b"evidence").hexdigest())


def envelope(content, prompt=31, output=9, **extra):
    return json.dumps({"model": "qwen3:4b", "message": {"role": "assistant", "content": content}, "done": True,
                       "prompt_eval_count": prompt, "eval_count": output, **extra}).encode()


class Fake:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, body, timeout):
        self.calls.append((url, json.loads(body), timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def model(*responses, **kwargs):
    fake = Fake(*responses)
    return LocalModel(transport=fake, **kwargs), fake


class Construction(unittest.TestCase):
    def test_loopback_hosts_only(self):
        for host in ("127.0.0.1", "::1"):
            LocalModel(host=host, transport=Fake())
        # A name goes through the resolver and the hosts file, so only the literal loopback addresses are accepted.
        for host in ("localhost", "LOCALHOST", "[::1]", "0.0.0.0", "10.0.0.5", "example.com", "127.0.0.2",
                     "localhost.example.com", "", None, "::"):
            with self.subTest(host=host), self.assertRaisesRegex(InputRejected, "^Local model host must be loopback$"):
                LocalModel(host=host)

    def test_rejects_invalid_settings(self):
        for kwargs in ({"port": 0}, {"port": 65536}, {"port": True}, {"port": "11434"}, {"timeout": 0},
                       {"timeout": 30.5}, {"timeout": True}, {"timeout": "30"}, {"model": ""},
                       {"model": "qwen3 4b"}, {"model": None}, {"transport": "urllib"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(InputRejected, "^Invalid local model settings$"):
                LocalModel(**kwargs)

    def test_url_brackets_ipv6(self):
        _, fake = model(envelope('{"mechanisms": []}'), host="::1", port=8080)
        LocalModel(host="::1", port=8080, transport=fake).complete("s", "u", SCHEMA)
        self.assertEqual(fake.calls[0][0], "http://[::1]:8080/api/chat")


class Complete(unittest.TestCase):
    def test_valid_output_and_request_shape(self):
        local, fake = model(envelope('{"mechanisms": ["partial_load"]}'))
        result = local.complete("system text", "user text", SCHEMA, max_tokens=128)
        self.assertIsInstance(result, LLMResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"mechanisms": ["partial_load"]})
        self.assertIsNone(result.error_code)
        self.assertEqual((result.model, result.tokens_in, result.tokens_out, result.cache), ("qwen3:4b", 31, 9, "none"))
        self.assertIs(type(result.latency_ms), int)
        self.assertGreaterEqual(result.latency_ms, 0)
        url, body, timeout = fake.calls[0]
        self.assertEqual((url, timeout), ("http://127.0.0.1:11434/api/chat", 30.0))
        self.assertEqual(body, {
            "model": "qwen3:4b",
            "messages": [{"role": "system", "content": "system text"}, {"role": "user", "content": "user text"}],
            "format": SCHEMA, "options": {"temperature": 0, "seed": 7, "num_predict": 128},
            "think": False, "stream": False})

    def test_prompt_hash_is_the_canonical_request_and_stable(self):
        first, fake = model(envelope('{"mechanisms": []}'))
        second, _ = model(envelope("not json"))
        digest = first.complete("s", "u", SCHEMA).prompt_sha256
        sent = json.dumps(fake.calls[0][1], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        self.assertEqual(digest, sha256(sent).hexdigest())
        reordered = dict(reversed(list(SCHEMA.items())))
        self.assertEqual(second.complete("s", "u", reordered).prompt_sha256, digest)
        self.assertEqual(llm.prompt_sha256("s", "u", SCHEMA, model="qwen3:4b", max_tokens=512), digest)
        for changed in ({"model": "qwen3:8b", "max_tokens": 512}, {"model": "qwen3:4b", "max_tokens": 128}):
            self.assertNotEqual(llm.prompt_sha256("s", "u", SCHEMA, **changed), digest)
        self.assertNotEqual(llm.prompt_sha256("s", "u2", SCHEMA, model="qwen3:4b", max_tokens=512), digest)

    def test_unencodable_reply_text_is_invalid_output(self):
        local, _ = model(envelope('{"mechanisms": [], "note": "\\ud800"}'))
        schema = {**SCHEMA, "properties": {**SCHEMA["properties"], "note": {"type": "string"}}}
        result = local.complete("s", "u", schema)
        self.assertEqual((result.ok, result.data, result.error_code), (False, None, "INVALID_OUTPUT"))

    def test_schema_invalid_or_malformed_output_is_invalid_output(self):
        cases = [
            envelope('{"mechanisms": ["root_cause_found"]}'),
            envelope('{"mechanisms": [], "extra": 1}'),
            envelope("not json"),
            envelope('{"mechanisms": [], "mechanisms": []}'),
            envelope('{"mechanisms": [NaN]}'),
            envelope('{"mechanisms": []}', prompt=True, output=-1)[:-1],
            b"not an envelope",
            json.dumps({"message": "flat"}).encode(),
            json.dumps({"message": {"content": 5}}).encode(),
            json.dumps([1]).encode(),
            b"\xff\xfe",
            b"{" + b" " * llm.MAX_RESPONSE_BYTES + b"}",
            "text, not bytes",
        ]
        for response in cases:
            local, _ = model(response)
            with self.subTest(response=response[:60]):
                result = local.complete("s", "u", SCHEMA)
                self.assertFalse(result.ok)
                self.assertIsNone(result.data)
                self.assertEqual(result.error_code, "INVALID_OUTPUT")

    def test_invalid_output_keeps_reported_token_usage(self):
        local, _ = model(envelope('{"mechanisms": "x"}', prompt=40, output=12))
        result = local.complete("s", "u", SCHEMA)
        self.assertEqual((result.error_code, result.tokens_in, result.tokens_out), ("INVALID_OUTPUT", 40, 12))
        local, _ = model(envelope('{"mechanisms": []}', prompt=True, output=-1))
        result = local.complete("s", "u", SCHEMA)
        self.assertTrue(result.ok)
        self.assertEqual((result.tokens_in, result.tokens_out), (0, 0))

    def test_transport_errors_are_model_unavailable(self):
        for error in (ConnectionRefusedError(61, "refused"), URLError(ConnectionRefusedError(61, "refused")),
                      HTTPError("http://127.0.0.1:11434/api/chat", 404, "not found", {}, None),
                      IncompleteRead(b""), OSError("down"), ValueError("bad transport"), RuntimeError("bug")):
            local, _ = model(error)
            with self.subTest(error=type(error).__name__):
                result = local.complete("s", "u", SCHEMA)
                self.assertEqual((result.ok, result.error_code, result.data), (False, "MODEL_UNAVAILABLE", None))
                self.assertEqual((result.tokens_in, result.tokens_out), (0, 0))

    def test_timeouts_are_timeout(self):
        for error in (TimeoutError("timed out"), URLError(TimeoutError("timed out"))):
            local, _ = model(error)
            with self.subTest(error=error):
                self.assertEqual(local.complete("s", "u", SCHEMA).error_code, "TIMEOUT")

    def test_a_call_timeout_bounds_the_request_and_never_exceeds_the_model_limit(self):
        local, fake = model(envelope('{"mechanisms": []}'), envelope('{"mechanisms": []}'),
                            envelope('{"mechanisms": []}'), timeout=20)
        local.complete("s", "u", SCHEMA, timeout=2.5)
        local.complete("s", "u", SCHEMA, timeout=45)
        local.complete("s", "u", SCHEMA, cache=ContextCache(), identity=IDENTITY, agent_id="A23", timeout=0.25)
        self.assertEqual([call[2] for call in fake.calls], [2.5, 20.0, 0.25])
        for bad in (0, -1, float("nan"), float("inf"), True, "5"):
            with self.subTest(timeout=bad), self.assertRaisesRegex(InputRejected, "^Invalid model call timeout$"):
                local.complete("s", "u", SCHEMA, timeout=bad)

    def test_rejects_invalid_requests_before_any_call(self):
        local, fake = model()
        bad = [
            (("", "u", SCHEMA), {}), (("s", "", SCHEMA), {}), ((None, "u", SCHEMA), {}), (("s", 5, SCHEMA), {}),
            (("s" * (llm.MAX_PROMPT_CHARS + 1), "u", SCHEMA), {}),
            (("s", "u", "schema"), {}), (("s", "u", {"type": "nonsense"}), {}),
            (("s", "u", {"const": float("nan")}), {}),
            (("s", "u", {"$ref": "https://example.invalid/schema"}), {}),
            (("s", "u", {"anyOf": [{"$dynamicRef": "urn:x"}]}), {}),
            (("s", "u", {"properties": {"m": {"$ref": "#/nope"}}}), {}),
            (("s", "u", {"$defs": {"a": {"$anchor": "a"}}, "properties": {"m": {"$ref": "#a"}}}), {}),
            (("s", "u", {"$id": "urn:other", "properties": {"m": {"$ref": "#"}}}), {}),
            (("s", "u", {"$ref": "#/$defs/m/x", "$defs": {"m": {}}}), {}),
            (("s", "\ud800", SCHEMA), {}),
            (("s", "u", SCHEMA), {"max_tokens": 0}), (("s", "u", SCHEMA), {"max_tokens": 513}),
            (("s", "u", SCHEMA), {"max_tokens": True}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "agent_id": "A23"}),
            (("s", "u", SCHEMA), {"identity": IDENTITY, "agent_id": "A23"}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "identity": IDENTITY}),
            (("s", "u", SCHEMA), {"agent_id": "A23"}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "identity": ("local", "a23"), "agent_id": "A23"}),
            (("s", "u", SCHEMA), {"cache": {}, "identity": IDENTITY, "agent_id": "A23"}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "identity": IDENTITY, "agent_id": "A29"}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "identity": IDENTITY, "agent_id": "A99"}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "agent_id": "A10",
                                  "identity": CacheIdentity("local", "a10", "p1", IDENTITY.evidence_sha256)}),
        ]
        for args, kwargs in bad:
            with self.subTest(args=str(args)[:40], kwargs=kwargs), self.assertRaises(InputRejected):
                local.complete(*args, **kwargs)
        self.assertEqual(fake.calls, [])


class Cache(unittest.TestCase):
    def test_miss_then_hit_without_a_second_call(self):
        cache = ContextCache()
        local, fake = model(envelope('{"mechanisms": ["duplicate_delivery"]}'))
        first = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        second = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual((first.ok, first.cache, first.tokens_in), (True, "miss", 31))
        self.assertEqual((second.ok, second.cache, second.data), (True, "hit", first.data))
        self.assertEqual((second.tokens_in, second.tokens_out, second.prompt_sha256),
                         (0, 0, first.prompt_sha256))
        self.assertEqual(cache.stats()["hits"], 1)

    def test_only_validated_results_are_stored(self):
        cache = ContextCache()
        local, fake = model(envelope('{"mechanisms": ["x"]}'), ConnectionRefusedError(61, "refused"),
                            envelope('{"mechanisms": []}'))
        self.assertEqual(local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23").error_code, "INVALID_OUTPUT")
        self.assertEqual(local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23").error_code,
                         "MODEL_UNAVAILABLE")
        self.assertEqual(cache.stats()["entries"], 0)
        third = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((third.ok, third.cache), (True, "miss"))
        self.assertEqual(len(fake.calls), 3)

    def test_failed_calls_report_miss(self):
        local, _ = model(TimeoutError("slow"))
        result = local.complete("s", "u", SCHEMA, cache=ContextCache(), identity=IDENTITY, agent_id="A23")
        self.assertEqual((result.error_code, result.cache), ("TIMEOUT", "miss"))

    def test_identity_reused_for_another_request_rebuilds(self):
        cache = ContextCache()
        local, fake = model(envelope('{"mechanisms": []}'), envelope('{"mechanisms": ["partial_load"]}'),
                            envelope('{"mechanisms": ["duplicate_delivery"]}'))
        local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        changed = local.complete("s", "other", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((changed.cache, changed.data), ("miss", {"mechanisms": ["partial_load"]}))
        budget = local.complete("s", "other", SCHEMA, max_tokens=64, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((budget.cache, budget.data), ("miss", {"mechanisms": ["duplicate_delivery"]}))
        again = local.complete("s", "other", SCHEMA, max_tokens=64, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((again.cache, again.data, len(fake.calls)), ("hit", budget.data, 3))
        other = LocalModel(model="qwen3:8b", transport=Fake(envelope('{"mechanisms": []}')))
        self.assertEqual(other.complete("s", "other", SCHEMA, max_tokens=64, cache=cache, identity=IDENTITY,
                                        agent_id="A23").cache, "miss")

    def test_a_persistently_mismatched_entry_falls_back_to_an_unstored_call(self):
        cache = ContextCache()
        local, fake = model(envelope('{"mechanisms": []}'), envelope('{"mechanisms": ["partial_load"]}'))
        local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        with mock.patch.object(ContextCache, "invalidate", return_value=0):
            result = local.complete("s", "other", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((result.ok, result.cache, result.data), (True, "miss", {"mechanisms": ["partial_load"]}))
        self.assertEqual(len(fake.calls), 2)

    def test_unencodable_reply_is_not_cached(self):
        cache = ContextCache()
        schema = {**SCHEMA, "properties": {**SCHEMA["properties"], "note": {"type": "string"}}}
        local, _ = model(envelope('{"mechanisms": [], "note": "\\ud800"}'))
        result = local.complete("s", "u", schema, cache=cache, identity=IDENTITY, agent_id="A23")
        self.assertEqual((result.error_code, result.cache), ("INVALID_OUTPUT", "miss"))
        self.assertEqual(cache.stats()["entries"], 0)

    def test_hybrid_roles_may_use_the_cache(self):
        identity = CacheIdentity("local", "a22", "p1", IDENTITY.evidence_sha256)
        local, _ = model(envelope('{"mechanisms": []}'))
        self.assertEqual(local.complete("s", "u", SCHEMA, cache=ContextCache(), identity=identity,
                                        agent_id="A22").cache, "miss")

    def test_oversized_valid_result_is_returned_but_not_stored(self):
        cache = ContextCache(max_entry_bytes=16, max_total_bytes=16)
        local, fake = model(envelope('{"mechanisms": []}'), envelope('{"mechanisms": []}'))
        for _ in range(2):
            result = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY, agent_id="A23")
            self.assertEqual((result.ok, result.cache), (True, "miss"))
        self.assertEqual(len(fake.calls), 2)

    def test_cache_errors_before_the_call_are_rejected(self):
        local, fake = model()
        with self.assertRaisesRegex(InputRejected, "^Model cache failed$"):
            local.complete("s", "u", SCHEMA, cache=ContextCache(clock=lambda: -1), identity=IDENTITY,
                           agent_id="A23")
        self.assertEqual(fake.calls, [])


class LocalReferences(unittest.TestCase):
    def test_local_references_are_allowed_and_resolution_stays_offline(self):
        schema = {"$defs": {"m": {"enum": ["partial_load"]}}, "type": "object", "additionalProperties": False,
                  "required": ["m"], "properties": {"m": {"$ref": "#/$defs/m"}}}
        local, _ = model(envelope('{"m": "partial_load"}'), envelope('{"m": "other"}'))
        self.assertTrue(local.complete("s", "u", schema).ok)
        self.assertEqual(local.complete("s", "u", schema).error_code, "INVALID_OUTPUT")
        with self.assertRaises(NoSuchResource):
            llm._offline("https://example.invalid/schema")

    def test_reference_errors_after_the_call_are_invalid_output(self):
        local, fake = model(envelope('{"m": 1}'))
        with mock.patch.object(llm, "_check_references", lambda schema: None):
            result = local.complete("s", "u", {"properties": {"m": {"$ref": "#/nope"}}})
        self.assertEqual((result.error_code, len(fake.calls)), ("INVALID_OUTPUT", 1))


class DefaultTransport(unittest.TestCase):
    def test_posts_json_without_proxies_and_bounds_the_read(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(llm, "_OPENER", opener):
            self.assertEqual(llm._urllib_transport("http://127.0.0.1:11434/api/chat", b"{}", 30.0), b"{}")
        request = opener.open.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method(), request.data), (
            "http://127.0.0.1:11434/api/chat", "POST", b"{}"))
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 30.0})
        response.__enter__.return_value.read.assert_called_once_with(llm.MAX_RESPONSE_BYTES + 1)
        self.assertIs(LocalModel()._transport, llm._urllib_transport)

    def test_opener_ignores_proxies_and_refuses_redirects(self):
        # An empty ProxyHandler suppresses the default (environment) one and registers no proxy route itself.
        handlers = {type(handler).__name__: handler for handler in llm._OPENER.handlers}
        self.assertNotIn("ProxyHandler", handlers)
        self.assertIsNone(handlers["_NoRedirect"].redirect_request(None, None, 302, "Found", {}, "http://x/"))


if __name__ == "__main__":
    unittest.main()
