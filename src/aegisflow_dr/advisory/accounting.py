# SPDX-License-Identifier: Apache-2.0
"""Validate persisted accounting before it can authorize or describe spending.

Consistency checks are not a signature or an independent provider receipt. A
privileged writer can still replace an internally consistent database.
"""
from collections import defaultdict
import re

from .contracts import AdvisoryError

MAX_RECORDS = 100_000
HELD = ('RESERVED', 'IN_FLIGHT', 'UNKNOWN')


def bounded(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AdvisoryError('Stored usage accounting rejected')


def audit_rows(rows, policy, operation):
    """Validate bounded rows, exact integer arithmetic, state and budget invariants."""
    bounded(len(rows), 0, policy.max_total_attempts or MAX_RECORDS)
    requests = defaultdict(list)
    for row in rows:
        for field in ('key_sha256', 'request_sha256', 'input_sha256', 'quote_sha256'):
            if type(row[field]) is not str or re.fullmatch('[0-9a-f]{64}', row[field]) is None:
                raise AdvisoryError('Stored usage identity rejected')
        if (type(row['model_id']) is not str or
                re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', row['model_id']) is None):
            raise AdvisoryError('Stored usage model rejected')
        bounded(row['deadline_ms'], 0, 10**18)
        for field in ('input_cap', 'output_cap'):
            bounded(row[field], 1, 10**6)
        for field in ('input_rate', 'output_rate'):
            bounded(row[field], 0, 10**9)
        for field in ('reserved_tokens', 'reserved_cost_nusd', 'charged_tokens', 'charged_cost_nusd'):
            bounded(row[field], 0, 10**18)
        if (row['reserved_tokens'] != row['input_cap'] + row['output_cap'] or
                row['reserved_cost_nusd'] != row['input_cap'] * row['input_rate'] +
                row['output_cap'] * row['output_rate']):
            raise AdvisoryError('Stored usage reservation rejected')
        if row['status'] == 'SETTLED':
            bounded(row['actual_input'], 0, row['input_cap'])
            bounded(row['actual_output'], 0, row['output_cap'])
            if (row['charged_tokens'] != row['actual_input'] + row['actual_output'] or
                    row['charged_cost_nusd'] != row['actual_input'] * row['input_rate'] +
                    row['actual_output'] * row['output_rate']):
                raise AdvisoryError('Stored usage settlement rejected')
        elif (row['status'] not in (*HELD, 'CANCELLED') or
              (row['actual_input'], row['actual_output'], row['charged_tokens'], row['charged_cost_nusd'])
              != (None, None, 0, 0)):
            raise AdvisoryError('Stored usage state rejected')
        if operation is not None and (row['deadline_ms'] != operation['deadline_ms'] or
                                      row['model_id'] not in operation['allowed_models']):
            raise AdvisoryError('Stored usage operation rejected')
        requests[row['request_sha256']].append(row)
    for group in requests.values():
        if (len(group) > policy.max_attempts or sum(row['status'] in HELD for row in group) > 1 or
                len({(row['deadline_ms'], row['input_sha256'], row['model_id']) for row in group}) != 1):
            raise AdvisoryError('Stored usage request history rejected')
    held = [row for row in rows if row['status'] in HELD]
    if policy.max_total_attempts is not None and (
            len(held) > 1 or len({row['deadline_ms'] for row in rows}) > 1):
        raise AdvisoryError('Stored shared usage rejected')
    totals = {'held_tokens': sum(row['reserved_tokens'] for row in held),
              'held_cost_nusd': sum(row['reserved_cost_nusd'] for row in held),
              'charged_tokens': sum(row['charged_tokens'] for row in rows),
              'charged_cost_nusd': sum(row['charged_cost_nusd'] for row in rows),
              'attempts': len(rows)}
    if (totals['held_tokens'] + totals['charged_tokens'] > policy.max_tokens or
            totals['held_cost_nusd'] + totals['charged_cost_nusd'] > policy.max_cost_nusd):
        raise AdvisoryError('Stored usage budget rejected')
    return totals
