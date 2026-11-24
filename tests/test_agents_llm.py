# SPDX-License-Identifier: Apache-2.0
from hashlib import sha256
from http.client import IncompleteRead
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from aegisflow_dr.advisory.context_cache import CacheIdentity, ContextCache
from aegisflow_dr.advisory.contracts import AdvisoryError
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
        for host in ("127.0.0.1", "localhost", "::1"):
            LocalModel(host=host, transport=Fake())
        for host in ("0.0.0.0", "10.0.0.5", "example.com", "127.0.0.2", "localhost.example.com", "", None, "::"):
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

    def test_prompt_hash_is_stable_and_canonical(self):
        expected = sha256(json.dumps({"schema": SCHEMA, "system": "s", "user": "u"}, sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        reordered = dict(reversed(list(SCHEMA.items())))
        first, _ = model(envelope('{"mechanisms": []}'))
        second, _ = model(envelope("not json"))
        self.assertEqual(first.complete("s", "u", SCHEMA).prompt_sha256, expected)
        self.assertEqual(second.complete("s", "u", reordered).prompt_sha256, expected)
        self.assertEqual(llm.prompt_sha256("s", "u", SCHEMA), expected)
        self.assertNotEqual(llm.prompt_sha256("s", "u2", SCHEMA), expected)

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
                      IncompleteRead(b""), OSError("down")):
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

    def test_rejects_invalid_requests_before_any_call(self):
        local, fake = model()
        bad = [
            (("", "u", SCHEMA), {}), (("s", "", SCHEMA), {}), ((None, "u", SCHEMA), {}), (("s", 5, SCHEMA), {}),
            (("s" * (llm.MAX_PROMPT_CHARS + 1), "u", SCHEMA), {}),
            (("s", "u", "schema"), {}), (("s", "u", {"type": "nonsense"}), {}),
            (("s", "u", {"const": float("nan")}), {}),
            (("s", "u", {"$ref": "https://example.invalid/schema"}), {}),
            (("s", "u", {"anyOf": [{"$dynamicRef": "urn:x"}]}), {}),
            (("s", "u", SCHEMA), {"max_tokens": 0}), (("s", "u", SCHEMA), {"max_tokens": 513}),
            (("s", "u", SCHEMA), {"max_tokens": True}),
            (("s", "u", SCHEMA), {"cache": ContextCache()}),
            (("s", "u", SCHEMA), {"identity": IDENTITY}),
            (("s", "u", SCHEMA), {"cache": ContextCache(), "identity": ("local", "a23")}),
            (("s", "u", SCHEMA), {"cache": {}, "identity": IDENTITY}),
        ]
        for args, kwargs in bad:
            with self.subTest(args=str(args)[:40], kwargs=kwargs), self.assertRaises(InputRejected):
                local.complete(*args, **kwargs)
        self.assertEqual(fake.calls, [])


class Cache(unittest.TestCase):
    def test_miss_then_hit_without_a_second_call(self):
        cache = ContextCache()
        local, fake = model(envelope('{"mechanisms": ["duplicate_delivery"]}'))
        first = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)
        second = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)
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
        self.assertEqual(local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY).error_code, "INVALID_OUTPUT")
        self.assertEqual(local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY).error_code,
                         "MODEL_UNAVAILABLE")
        self.assertEqual(cache.stats()["entries"], 0)
        third = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)
        self.assertEqual((third.ok, third.cache), (True, "miss"))
        self.assertEqual(len(fake.calls), 3)

    def test_failed_calls_report_miss(self):
        local, _ = model(TimeoutError("slow"))
        result = local.complete("s", "u", SCHEMA, cache=ContextCache(), identity=IDENTITY)
        self.assertEqual((result.error_code, result.cache), ("TIMEOUT", "miss"))

    def test_identity_reused_for_another_prompt_or_model_is_rejected(self):
        cache = ContextCache()
        local, _ = model(envelope('{"mechanisms": []}'))
        local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)
        with self.assertRaisesRegex(InputRejected, "^Cache identity does not match this prompt$"):
            local.complete("s", "other", SCHEMA, cache=cache, identity=IDENTITY)
        other = LocalModel(model="qwen3:8b", transport=Fake())
        with self.assertRaisesRegex(InputRejected, "^Cache identity does not match this prompt$"):
            other.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)

    def test_oversized_valid_result_is_returned_but_not_stored(self):
        cache = ContextCache(max_entry_bytes=16, max_total_bytes=16)
        local, fake = model(envelope('{"mechanisms": []}'), envelope('{"mechanisms": []}'))
        for _ in range(2):
            result = local.complete("s", "u", SCHEMA, cache=cache, identity=IDENTITY)
            self.assertEqual((result.ok, result.cache), (True, "miss"))
        self.assertEqual(len(fake.calls), 2)

    def test_cache_errors_before_the_call_propagate(self):
        local, fake = model()
        with self.assertRaises(AdvisoryError):
            local.complete("s", "u", SCHEMA, cache=ContextCache(clock=lambda: -1), identity=IDENTITY)
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
