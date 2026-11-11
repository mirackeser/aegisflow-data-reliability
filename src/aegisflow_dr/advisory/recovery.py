# SPDX-License-Identifier: Apache-2.0
"""Consistent read-only recovery evidence; no delivery inference or resend authority."""
from contextlib import closing
import sqlite3

from ..storage.store import canonical, sha
from .contracts import AdvisoryError, decode, encode
from .route_store import state
from .usage import UsageLedger

STATUSES = ('RESERVED', 'IN_FLIGHT', 'UNKNOWN', 'SETTLED', 'CANCELLED')
FINALS = ('EXHAUSTED', 'DEADLINE_EXCEEDED', 'ADMISSION_DENIED', 'KNOWN_TERMINAL_FAILURE',
          'USAGE_UNKNOWN', 'RESPONSE_REJECTED', 'VERIFIED_ADVISORY', 'REJECTED_ADVISORY', 'ABSTAIN')


def validate_event_bindings(plan, events, attempts):
    by_id = {item['attempt_id']: item for item in attempts}
    if events and (plan is None or len(events) > len(plan['steps'])):
        raise AdvisoryError('Recovery event plan rejected')
    for index, event in enumerate(events):
        step, attempt = plan['steps'][index], by_id[event['attempt_id']]
        if (event['model_id'] != step['model_id'] or event['request_sha256'] != step['request_sha256']
                or any(attempt[key] != step[key] for key in
                       ('model_id', 'request_sha256', 'input_sha256', 'quote_sha256'))):
            raise AdvisoryError('Recovery event binding rejected')
        if (event['status'] in ('REVIEWED', 'RESPONSE_REJECTED', 'KNOWN_RETRYABLE_FAILURE', 'KNOWN_TERMINAL_FAILURE')
                and attempt['status'] != 'SETTLED'):
            raise AdvisoryError('Recovery event usage rejected')
        if event['status'] == 'USAGE_UNKNOWN' and attempt['status'] not in ('UNKNOWN', 'IN_FLIGHT'):
            raise AdvisoryError('Recovery unknown usage rejected')
        if index + 1 < len(events) and event['status'] != 'KNOWN_RETRYABLE_FAILURE':
            raise AdvisoryError('Recovery progression rejected')


def assess_recovery(ledger):
    """Export historical evidence, including running routes that may still be active.

    The digest detects snapshot changes, not malicious host modification. No
    stale-worker inference, usage attestation, refund or state mutation is supplied.
    """
    if type(ledger) is not UsageLedger or ledger.version != 3:
        raise AdvisoryError('Routing ledger required for recovery assessment')
    try:
        with closing(sqlite3.connect(ledger.path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('BEGIN')
            metadata = connection.execute('SELECT * FROM metadata').fetchall()
            if (len(metadata) != 1 or metadata[0]['version'] != 3
                    or metadata[0]['operation'] != ledger.operation.payload):
                raise AdvisoryError('Recovery scope changed')
            row, plan, events = state(connection)
            attempts = [dict(item) for item in connection.execute('SELECT * FROM attempts ORDER BY attempt_id')]
            if (any(item['status'] not in STATUSES for item in attempts)
                    or (row is not None and row['final_status'] not in (None, *FINALS))
                    or (plan is not None and plan['operation_sha256'] != sha(ledger.operation.payload))):
                raise AdvisoryError('Recovery state rejected')
            ids = {item['attempt_id'] for item in attempts}
            recorded = {event['attempt_id'] for event in events}
            if (not recorded <= ids or len(recorded) != len(events)
                    or [event['index'] for event in events] != list(range(len(events)))
                    or (row is None and attempts)):
                raise AdvisoryError('Recovery history rejected')
            validate_event_bindings(plan, events, attempts)
            counts = {status: sum(item['status'] == status for item in attempts) for status in STATUSES}
            route_status = 'UNCLAIMED' if row is None else (row['final_status'] or 'RUNNING')
            unrecorded = sum(item['status'] == 'SETTLED' and item['attempt_id'] not in recorded for item in attempts)
            reasons = []
            if route_status == 'RUNNING': reasons.append('ROUTE_NOT_FINALIZED')
            if counts['IN_FLIGHT'] + counts['UNKNOWN']: reasons.append('USAGE_UNRESOLVED')
            if counts['RESERVED']: reasons.append('RESERVATION_HELD')
            if unrecorded: reasons.append('RESULT_NOT_JOURNALED')
            # Ownership tokens, prompts and source data are excluded from the projection.
            snapshot = {'operation_sha256': sha(ledger.operation.payload),
                        'policy_sha256': sha(metadata[0]['policy']), 'observed_ms': metadata[0]['observed_ms'],
                        'plan': plan, 'status': route_status, 'events': events, 'attempts': attempts}
            assessment = {'version': '1', 'operation_sha256': sha(ledger.operation.payload),
                'snapshot_sha256': sha(canonical(snapshot)), 'route_status': route_status,
                'attempt_counts': counts, 'unrecorded_settlements': unrecorded, 'usage': ledger._totals(connection),
                'decision': 'REVIEW_BEFORE_RECOVERY' if reasons else 'NO_RECOVERY_INDICATED',
                'reasons': reasons, 'automatic_resend_allowed': False, 'automatic_refund_allowed': False}
            return {'assessment': assessment, 'assessment_sha256': sha(canonical(assessment))}
    except AdvisoryError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        raise AdvisoryError('Recovery assessment unavailable') from None


def prepare_recovery_review(ledger, *, review_id, operator_id, action):
    """Bind an advisory review request to current evidence; identity is host supplied."""
    report = assess_recovery(ledger)
    assessment = report['assessment']
    if assessment['decision'] != 'REVIEW_BEFORE_RECOVERY':
        raise AdvisoryError('Recovery review not indicated')
    return encode('recovery-review', {'version': '1', 'review_id': review_id, 'operator_id': operator_id,
        'operation_sha256': assessment['operation_sha256'], 'snapshot_sha256': assessment['snapshot_sha256'],
        'assessment_sha256': report['assessment_sha256'], 'action': action})


def verify_recovery_review(ledger, payload):
    """Check freshness only; this grants no authentication or mutation authority."""
    packet = decode('recovery-review', payload)
    report = assess_recovery(ledger)
    expected = {**report['assessment'], 'assessment_sha256': report['assessment_sha256']}
    if any(packet[key] != expected[key] for key in
           ('operation_sha256', 'snapshot_sha256', 'assessment_sha256')):
        raise AdvisoryError('Stale or mismatched recovery review')
    return packet
