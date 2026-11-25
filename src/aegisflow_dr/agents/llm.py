# SPDX-License-Identifier: Apache-2.0
"""A loopback-only adapter for a local Ollama model with JSON-schema constrained, deterministic requests.

Each request asks for output in the caller's JSON Schema with temperature 0, a fixed seed and thinking off, and
the reply is accepted only if it parses as strict JSON and validates against that schema. Failures are typed
(MODEL_UNAVAILABLE, INVALID_OUTPUT, TIMEOUT) and never replaced with simulated output. Model output is advisory;
callers pass it through the Judge. ``prompt_sha256`` is the SHA-256 of the exact canonical request (model, messages,
schema, options), so it changes with the model and the output budget. Output schemas may use only local JSON-pointer
references, which are resolved before any call. The optional context cache (CAG) stores only validated results under
a cache identity whose kind is the calling agent (for example ``a23``); an entry made for a different request is
invalidated and rebuilt, and a hit made no model call and reports zero tokens. The cache builder runs under the cache
lock, so concurrent requests sharing one cache wait for an in-flight model call.
"""
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from time import perf_counter
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from ..advisory.context_cache import CacheIdentity, ContextCache
from ..advisory.contracts import AdvisoryError
from ..pipeline import InputRejected
from .registry import role

PROVIDER, TEMPERATURE, SEED = "ollama", 0, 7
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})  # literal addresses only: a name goes through the resolver
MAX_OUTPUT_TOKENS, MAX_TIMEOUT_S = 512, 30.0
MAX_PROMPT_CHARS, MAX_RESPONSE_BYTES = 32_000, 1_000_000
MODEL_UNAVAILABLE, INVALID_OUTPUT, TIMEOUT = "MODEL_UNAVAILABLE", "INVALID_OUTPUT", "TIMEOUT"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_IDENTIFYING = frozenset({"$id", "$anchor", "$dynamicAnchor", "$dynamicRef", "$recursiveAnchor", "$recursiveRef"})


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


def _request(model, system, user, schema, max_tokens):
    return _canonical({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "options": {"temperature": TEMPERATURE, "seed": SEED, "num_predict": max_tokens},
        "think": False,
        "stream": False,
    })


def prompt_sha256(system, user, schema, *, model, max_tokens):
    """SHA-256 of the canonical request body sent to the model (model, messages, schema and options)."""
    return sha256(_request(model, system, user, schema, max_tokens)).hexdigest()


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


def _references(value, found):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _IDENTIFYING:
                raise ValueError("schema identifiers and dynamic references are not supported")
            if key == "$ref":
                if type(item) is not str or not (item == "#" or item.startswith("#/")):
                    raise ValueError("only local JSON-pointer references are supported")
                found.append(item)
            _references(item, found)
    elif isinstance(value, list):
        for item in value:
            _references(item, found)


def _check_references(schema):
    """Resolve every reference before any call; raises ValueError or referencing's Unresolvable."""
    found = []
    _references(schema, found)
    resolver = Registry(retrieve=_offline).resolver_with_root(DRAFT202012.create_resource(schema))
    for reference in found:
        resolver.lookup(reference)


def _encodable(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


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

    def complete(self, system, user, schema, *, max_tokens=MAX_OUTPUT_TOKENS, cache=None, identity=None,
                 agent_id=None, timeout=None):
        """Return an LLMResult for one schema-constrained chat request.

        Model-side failures are returned as typed results; invalid requests raise InputRejected before any call.
        Caching needs all of ``cache``, ``identity`` and ``agent_id``; the identity's kind must be the agent id in
        lower case and the agent must be a model-using role. ``timeout`` (seconds) bounds this call further, for
        example to a task's remaining deadline; the model's own timeout (at most 30 s) is never exceeded.
        """
        if timeout is not None and (type(timeout) not in (int, float) or not 0 < timeout < float("inf")):
            raise InputRejected("Invalid model call timeout")
        limit = self._timeout if timeout is None else min(self._timeout, float(timeout))
        for text in (system, user):
            if type(text) is not str or not 1 <= len(text) <= MAX_PROMPT_CHARS or not _encodable(text):
                raise InputRejected("Invalid model prompt")
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise InputRejected("Invalid model output budget")
        try:
            if type(schema) is not dict:
                raise TypeError("schema")
            Draft202012Validator.check_schema(schema)
            _check_references(schema)
            body = _request(self.model, system, user, schema, max_tokens)
        except (SchemaError, TypeError, ValueError, RecursionError, Unresolvable):
            raise InputRejected("Invalid model output schema") from None
        digest = sha256(body).hexdigest()
        if cache is None and identity is None and agent_id is None:
            return self._call(body, digest, schema, limit)
        if type(cache) is not ContextCache or type(identity) is not CacheIdentity:
            raise InputRejected("Invalid model cache")
        if "local_llm" not in role(agent_id).allowed_tools or identity.kind != agent_id.lower():
            raise InputRejected("Cache identity must bind a model-using agent")
        return self._cached(body, digest, schema, cache, identity, limit)

    def _cached(self, body, digest, schema, cache, identity, limit):
        started = perf_counter()
        for _ in range(2):
            built = []

            def builder():
                result = replace(self._call(body, digest, schema, limit), cache="miss")
                if not result.ok:
                    raise _Uncached(result)
                built.append(result)
                return _canonical({"prompt_sha256": digest, "data": result.data})

            try:
                stored = json.loads(cache.get_or_build(identity, builder))
            except _Uncached as uncached:
                return uncached.result
            except AdvisoryError:
                if built:
                    return built[0]  # valid, but too large to store
                raise InputRejected("Model cache failed") from None
            if built:
                return built[0]
            if stored["prompt_sha256"] == digest:  # the digest covers model, prompts, schema and options
                return LLMResult(True, stored["data"], None, self.model, digest, 0, 0,
                                 round((perf_counter() - started) * 1000), "hit")
            cache.invalidate(tenant=identity.tenant, kind=identity.kind, version=identity.version,
                             evidence_sha256=identity.evidence_sha256)
        return replace(self._call(body, digest, schema, limit), cache="miss")  # entry kept reappearing; do not store

    def _call(self, body, digest, schema, limit):
        started = perf_counter()

        def result(ok, data, error, tokens_in=0, tokens_out=0):
            return LLMResult(ok, data, error, self.model, digest, tokens_in, tokens_out,
                             round((perf_counter() - started) * 1000))

        try:
            raw = self._transport(self._url, body, limit)
        except Exception as error:  # any transport failure, including injected transports, is a typed outcome
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
            _canonical(data)  # lone surrogates parse but cannot be encoded, stored or reported
        except (ValueError, RecursionError, ValidationError, Unresolvable):
            return result(False, None, INVALID_OUTPUT, tokens_in, tokens_out)
        return result(True, data, None, tokens_in, tokens_out)
