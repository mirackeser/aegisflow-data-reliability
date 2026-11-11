# SPDX-License-Identifier: Apache-2.0
"""Bounded, ordered failover only after a settled retryable technical failure."""
from dataclasses import asdict, dataclass
import math
from time import monotonic

from ..storage.store import canonical, sha
from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode, encode
from .dispatch import Adapter, dispatch
from .route_store import RouteJournal
from .usage import UsageLedger, UsageQuote, LIMIT, integer


@dataclass(frozen=True)
class RouteCandidate:
    prepared: PreparedAdvisory
    quote: UsageQuote
    adapter: Adapter


def plan_route(ledger, candidates):
    if (type(ledger) is not UsageLedger or ledger.version != 3 or type(candidates) is not tuple
            or not 1 <= len(candidates) <= min(8, ledger.policy.max_total_attempts)):
        raise AdvisoryError('Bounded routing configuration required')
    deadline = decode('operation', ledger.operation.payload)['deadline_ms']
    steps = []
    for item in candidates:
        if (type(item) is not RouteCandidate or type(item.prepared) is not PreparedAdvisory
                or type(item.quote) is not UsageQuote or type(item.adapter) is not Adapter
                or item.adapter.revision != item.quote.adapter_id or not callable(item.adapter.send)):
            raise AdvisoryError('Trusted routing candidate required')
        ledger.operation.admit(item.prepared, deadline)
        request = decode('request', item.prepared.request)
        if (item.quote.model_id != request['model_id']
                or item.quote.input_sha256 != sha(canonical(item.prepared.messages))
                or item.quote.input_sha256 != item.prepared.manifest['input_sha256']):
            raise AdvisoryError('Routing quote mismatch')
        steps.append({'model_id': item.quote.model_id, 'request_sha256': sha(item.prepared.request),
                      'input_sha256': item.quote.input_sha256, 'quote_sha256': sha(canonical(asdict(item.quote)))})
    if len({step['model_id'] for step in steps}) != len(steps):
        raise AdvisoryError('Repeated model in route')
    return encode('route-plan', {'version': '1', 'operation_sha256': sha(ledger.operation.payload), 'steps': steps})


def execute_route(ledger, candidates, *, clock=monotonic):
    """Claim once; never resume interrupted routes or seek a different Judge verdict.

    Completed replays are historical summaries, not fresh evidence verification.
    Host adapters must cooperate with deadlines; no hard process preemption.
    """
    plan = plan_route(ledger, candidates)
    journal = RouteJournal(ledger)
    deadline = decode('operation', ledger.operation.payload)['deadline_ms']
    wall_start = ledger.clock_ms()
    integer(wall_start, 0, LIMIT)
    started = clock()
    if type(started) not in (int, float) or not math.isfinite(started):
        raise AdvisoryError('Invalid routing clock')
    previous = started

    def expired():
        nonlocal previous
        now, wall = clock(), ledger.clock_ms()
        integer(wall, wall_start, LIMIT)
        if type(now) not in (int, float) or not math.isfinite(now) or now < previous:
            raise AdvisoryError('Invalid routing clock')
        previous = now
        return wall >= deadline or (now - started) * 1000 >= deadline - wall_start

    token = journal.claim(plan)
    if token is None:
        return {**journal.snapshot(), 'replayed': True}
    index = 0
    while True:
        item = candidates[index]
        if expired():
            journal.stop(token, 'DEADLINE_EXCEEDED')
            break
        try:
            result = dispatch(item.prepared, item.quote, ledger, item.adapter,
                attempt_key=sha(canonical([sha(plan), index])), deadline_ms=deadline,
                clock=clock, route_token=token)
        except AdvisoryError:
            journal.stop(token, 'ADMISSION_DENIED')
            break
        event = {'index': index, 'model_id': item.quote.model_id,
                 'request_sha256': result['request_sha256'], 'attempt_id': result['attempt_id'],
                 'status': result['status'],
                 'review_status': result['review']['status'] if result['review'] else None}
        journal.record(token, event, expired=expired())
        if journal.snapshot()['status'] != 'RUNNING':
            break
        index += 1
    return {**journal.snapshot(), 'replayed': False}
