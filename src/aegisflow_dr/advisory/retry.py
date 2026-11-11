# SPDX-License-Identifier: Apache-2.0
"""Trusted synchronous bounded retry; never resumes ambiguous or prior operations."""
from dataclasses import dataclass
import math
import re
from time import monotonic, sleep

from ..storage.store import canonical, sha
from .context import PreparedAdvisory
from .contracts import AdvisoryError
from .dispatch import Adapter, dispatch
from .usage import UsageLedger, UsageQuote, LIMIT, integer


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_ms: int = 100
    max_delay_ms: int = 1000

    def __post_init__(self):
        integer(self.max_attempts, 1, 8)
        integer(self.base_delay_ms, 1, 60_000)
        integer(self.max_delay_ms, self.base_delay_ms, 60_000)


def retry_dispatch(prepared, quote, ledger, adapter, *, operation_key, deadline_ms,
                   policy=RetryPolicy(), clock=monotonic, wait=sleep):
    """Retry only settled KNOWN_RETRYABLE_FAILURE, preserving input/model/deadline.

    Keys must be persisted/reused by the trusted caller. Reopening/repeating an
    operation stops at its already-started first attempt; no automatic resume.
    Waiting and adapters must cooperate; this is not hard process preemption.
    """
    if (type(prepared) is not PreparedAdvisory or type(quote) is not UsageQuote
            or type(ledger) is not UsageLedger or type(adapter) is not Adapter
            or type(policy) is not RetryPolicy or not callable(clock) or not callable(wait)):
        raise AdvisoryError('Trusted retry configuration required')
    if type(operation_key) is not str or re.fullmatch('[A-Za-z0-9_-]{1,64}', operation_key) is None:
        raise AdvisoryError('Invalid operation key')
    integer(deadline_ms, 0, LIMIT)
    if policy.max_attempts > ledger.policy.max_attempts:
        raise AdvisoryError('Retry attempts exceed ledger policy')
    initial_wall = ledger.clock_ms()
    integer(initial_wall, 0, LIMIT)
    started = clock()
    if type(started) not in (int, float) or not math.isfinite(started):
        raise AdvisoryError('Invalid retry clock')
    previous = started
    last = None
    calls = 0

    def result(status):
        return {'version': '1', 'status': status, 'attempts_started': calls, 'last_result': last}

    def remaining():
        nonlocal previous
        now = clock()
        wall = ledger.clock_ms()
        integer(wall, initial_wall, LIMIT)
        if type(now) not in (int, float) or not math.isfinite(now) or now < previous:
            raise AdvisoryError('Invalid retry clock')
        previous = now
        return min(deadline_ms - wall, deadline_ms - initial_wall - (now - started) * 1000)

    index = 0
    while True:
        if remaining() <= 0:
            return result('DEADLINE_EXCEEDED')
        key = sha(canonical([operation_key, sha(prepared.request), index]))
        try:
            last = dispatch(prepared, quote, ledger, adapter, attempt_key=key,
                            deadline_ms=deadline_ms, clock=clock)
        except AdvisoryError:
            return result('ADMISSION_DENIED')
        calls += 1
        if remaining() <= 0:
            return result('DEADLINE_EXCEEDED')
        if last['status'] != 'KNOWN_RETRYABLE_FAILURE':
            return result('FINISHED')
        if index + 1 == policy.max_attempts:
            return result('ATTEMPT_LIMIT')
        delay = min(policy.base_delay_ms * 2**index, policy.max_delay_ms)
        if delay >= remaining():
            return result('DEADLINE_EXCEEDED')
        wait(delay / 1000)
        index += 1
