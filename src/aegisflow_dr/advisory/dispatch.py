# SPDX-License-Identifier: Apache-2.0
"""One-shot trusted synchronous adapter boundary; no live provider is configured."""
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from ..storage.store import canonical, sha
from .contracts import AdvisoryError, MAX_BYTES
from .context import PreparedAdvisory
from .usage import UsageLedger, UsageQuote, integer


@dataclass(frozen=True)
class AdapterRequest:
    messages: bytes
    request_sha256: str
    model_id: str
    remaining_ms: int
    output_limit: int
    max_response_bytes: int


@dataclass(frozen=True)
class AdapterResult:
    """Usage is supplied by trusted adapter code, never decoded from model text."""
    payload: bytes
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class AdapterFailure:
    """Trusted adapter attestation of known usage; never inferred from HTTP status alone."""
    kind: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Adapter:
    revision: str
    send: Callable[[AdapterRequest], AdapterResult | AdapterFailure]


def dispatch(prepared, quote, ledger, adapter, *, attempt_key, deadline_ms, clock=monotonic, route_token=None):
    """Reserve/start once, settle known usage, then independently review advice.

    The synchronous host adapter must enforce streaming/transport caps. This wrapper
    rejects late/oversized returned results but cannot preempt arbitrary Python code.
    Repeated keys cannot redispatch, including after settlement or process restart.
    """
    if (type(prepared) is not PreparedAdvisory or type(quote) is not UsageQuote
            or type(ledger) is not UsageLedger or type(adapter) is not Adapter
            or adapter.revision != quote.adapter_id or not callable(adapter.send)):
        raise AdvisoryError('Trusted matching dispatch configuration required')
    messages = canonical(prepared.messages)
    if sha(messages) != quote.input_sha256:
        raise AdvisoryError('Dispatch input changed')
    row = ledger.reserve(prepared, quote, attempt_key=attempt_key, deadline_ms=deadline_ms, route_token=route_token)
    attempt = row['attempt_id']
    ledger.transition(attempt, 'start')

    def outcome(status, review=None):
        return {'version': '1', 'attempt_id': attempt, 'request_sha256': row['request_sha256'],
                'status': status, 'review': review}

    def unknown():
        try:
            ledger.transition(attempt, 'unknown')
        except AdvisoryError:
            # IN_FLIGHT also retains the full hold if storage or clock recovery is needed.
            pass

    try:
        now = ledger.clock_ms()
        integer(now, 0, deadline_ms)
        remaining = deadline_ms - now
        if remaining <= 0:
            unknown()
            return outcome('DEADLINE_EXCEEDED')
        started = clock()
        request = AdapterRequest(messages, row['request_sha256'], quote.model_id,
                                 remaining, quote.output_limit, MAX_BYTES)
        result = adapter.send(request)
        elapsed = clock() - started
        late = elapsed < 0 or not elapsed < remaining / 1000 or ledger.clock_ms() >= deadline_ms
        if (type(result) not in (AdapterResult, AdapterFailure)
                or (type(result) is AdapterFailure and result.kind not in ('RETRYABLE', 'TERMINAL'))):
            unknown()
            return outcome('USAGE_UNKNOWN')
        try:
            ledger.transition(attempt, 'settle', input_tokens=result.input_tokens, output_tokens=result.output_tokens)
        except AdvisoryError:
            unknown()
            return outcome('USAGE_UNKNOWN')
    except Exception:
        unknown()
        return outcome('USAGE_UNKNOWN')
    except BaseException:
        unknown()
        raise
    if late:
        return outcome('DEADLINE_EXCEEDED')
    if type(result) is AdapterFailure:
        return outcome('KNOWN_' + result.kind + '_FAILURE')
    if type(result.payload) is not bytes or len(result.payload) > MAX_BYTES:
        return outcome('RESPONSE_REJECTED')
    try:
        review = prepared.review_response(result.payload)
    except AdvisoryError:
        return outcome('RESPONSE_REJECTED')
    return outcome('REVIEWED', review)
