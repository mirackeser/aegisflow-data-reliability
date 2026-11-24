# SPDX-License-Identifier: Apache-2.0
"""A loopback-only adapter for a local Ollama model with JSON-schema constrained, deterministic requests.

Each request asks for output in the caller's JSON Schema with temperature 0, a fixed seed and thinking off, and
the reply is accepted only if it parses as strict JSON and validates against that schema. Failures are typed
(MODEL_UNAVAILABLE, INVALID_OUTPUT, TIMEOUT) and never replaced with simulated output. Model output is advisory;
callers pass it through the Judge. The optional context cache (CAG) stores only validated results, keyed by the
caller's exact cache identity; a hit made no model call and reports zero tokens. The cache builder runs under the
cache lock, so concurrent requests sharing one cache wait for an in-flight model call.
"""
from dataclasses import dataclass, replace
from hashlib import sha256
from http.client import HTTPException
import json
import re
from time import perf_counter
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

from ..advisory.context_cache import CacheIdentity, ContextCache
from ..advisory.contracts import AdvisoryError
from ..pipeline import InputRejected

PROVIDER, TEMPERATURE, SEED = "ollama", 0, 7
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_OUTPUT_TOKENS, MAX_TIMEOUT_S = 512, 30.0
MAX_PROMPT_CHARS, MAX_RESPONSE_BYTES = 32_000, 1_000_000
MODEL_UNAVAILABLE, INVALID_OUTPUT, TIMEOUT = "MODEL_UNAVAILABLE", "INVALID_OUTPUT", "TIMEOUT"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    data: object
    error_code: object  # None, MODEL_UNAVAILABLE, INVALID_OUTPUT or TIMEOUT
    model: str
    prompt_sha256: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cache: str = "none"  # "hit", "miss" or "none" (no cache used)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect could leave loopback; urllib then raises HTTPError


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _urllib_transport(url, body, timeout):
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with _OPENER.open(request, timeout=timeout) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def prompt_sha256(system, user, schema):
    """SHA-256 of the canonical JSON of the system prompt, user prompt and output schema."""
    return sha256(_canonical({"system": system, "user": user, "schema": schema})).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite")


def _strict_json(text):
    return json.loads(text, object_pairs_hook=_unique, parse_constant=_reject_constant)


def _offline(uri):
    raise NoSuchResource(ref=uri)


def _local_refs_only(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("$ref", "$dynamicRef") and not (type(item) is str and item.startswith("#")):
                raise ValueError("remote reference")
            _local_refs_only(item)
    elif isinstance(value, list):
        for item in value:
            _local_refs_only(item)


def _count(value):
    return value if type(value) is int and value >= 0 else 0


class _Uncached(Exception):
    def __init__(self, result):
        super().__init__()
        self.result = result


class LocalModel:
    def __init__(self, model="qwen3:4b", host="127.0.0.1", port=11434, transport=None, timeout=MAX_TIMEOUT_S):
        if type(host) is not str or host not in LOOPBACK_HOSTS:
            raise InputRejected("Local model host must be loopback")
        if (type(model) is not str or not _MODEL.fullmatch(model) or type(port) is not int or not 1 <= port <= 65535
                or type(timeout) not in (int, float) or not 0 < timeout <= MAX_TIMEOUT_S
                or (transport is not None and not callable(transport))):
            raise InputRejected("Invalid local model settings")
        self.model, self._timeout = model, float(timeout)
        self._url = "http://%s:%d/api/chat" % ("[::1]" if host == "::1" else host, port)
        self._transport = transport or _urllib_transport

    def complete(self, system, user, schema, *, max_tokens=MAX_OUTPUT_TOKENS, cache=None, identity=None):
        """Return an LLMResult for one schema-constrained chat request; never raises for model-side failures."""
        for text in (system, user):
            if type(text) is not str or not 1 <= len(text) <= MAX_PROMPT_CHARS:
                raise InputRejected("Invalid model prompt")
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise InputRejected("Invalid model output budget")
        try:
            if type(schema) is not dict:
                raise TypeError("schema")
            Draft202012Validator.check_schema(schema)
            _local_refs_only(schema)
            digest = prompt_sha256(system, user, schema)
        except (SchemaError, TypeError, ValueError, RecursionError):
            raise InputRejected("Invalid model output schema") from None
        if (cache is None) != (identity is None):
            raise InputRejected("Cache and cache identity go together")
        if cache is None:
            return self._call(system, user, schema, max_tokens, digest)
        if type(cache) is not ContextCache or type(identity) is not CacheIdentity:
            raise InputRejected("Invalid model cache")
        return self._cached(system, user, schema, max_tokens, digest, cache, identity)

    def _cached(self, system, user, schema, max_tokens, digest, cache, identity):
        built = []
        started = perf_counter()

        def builder():
            result = replace(self._call(system, user, schema, max_tokens, digest), cache="miss")
            if not result.ok:
                raise _Uncached(result)
            built.append(result)
            return _canonical({"model": self.model, "prompt_sha256": digest, "data": result.data})

        try:
            stored = json.loads(cache.get_or_build(identity, builder))
        except _Uncached as uncached:
            return uncached.result
        except AdvisoryError:
            if built:
                return built[0]  # valid, but too large to store
            raise
        if built:
            return built[0]
        if stored["model"] != self.model or stored["prompt_sha256"] != digest:
            raise InputRejected("Cache identity does not match this prompt")
        return LLMResult(True, stored["data"], None, self.model, digest, 0, 0,
                         round((perf_counter() - started) * 1000), "hit")

    def _call(self, system, user, schema, max_tokens, digest):
        body = _canonical({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "options": {"temperature": TEMPERATURE, "seed": SEED, "num_predict": max_tokens},
            "think": False,
            "stream": False,
        })
        started = perf_counter()

        def result(ok, data, error, tokens_in=0, tokens_out=0):
            return LLMResult(ok, data, error, self.model, digest, tokens_in, tokens_out,
                             round((perf_counter() - started) * 1000))

        try:
            raw = self._transport(self._url, body, self._timeout)
        except (OSError, HTTPException) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
            return result(False, None, TIMEOUT if timed_out else MODEL_UNAVAILABLE)
        try:
            if type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response")
            reply = _strict_json(raw.decode("utf-8"))
            content = reply["message"]["content"]
            if type(content) is not str:
                raise ValueError("content")
        except (ValueError, TypeError, KeyError, RecursionError):
            return result(False, None, INVALID_OUTPUT)
        tokens_in, tokens_out = _count(reply.get("prompt_eval_count")), _count(reply.get("eval_count"))
        try:
            data = _strict_json(content)
            Draft202012Validator(schema, registry=Registry(retrieve=_offline)).validate(data)
        except (ValueError, RecursionError, ValidationError):
            return result(False, None, INVALID_OUTPUT, tokens_in, tokens_out)
        return result(True, data, None, tokens_in, tokens_out)
