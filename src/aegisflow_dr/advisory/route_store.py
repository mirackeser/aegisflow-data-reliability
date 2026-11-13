# SPDX-License-Identifier: Apache-2.0
"""Single-owner route journal in the same transaction domain as usage admission."""
from uuid import uuid4

from ..storage.store import sha

from .contracts import AdvisoryError, decode, encode
from .usage import UsageLedger, database

SCHEMA = (
    "CREATE TABLE route (id INTEGER PRIMARY KEY CHECK(id=1), plan BLOB NOT NULL, token TEXT NOT NULL, final_status TEXT)",
    "CREATE TABLE route_events (position INTEGER PRIMARY KEY, event BLOB NOT NULL)",
)


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


def state(connection):
    rows = connection.execute('SELECT * FROM route LIMIT 2').fetchall()
    stored = connection.execute('SELECT position,event FROM route_events ORDER BY position LIMIT 9').fetchall()
    if len(rows) > 1 or len(stored) > 8 or (not rows and stored):
        raise AdvisoryError('Route history rejected')
    events = [decode('route-event', item['event']) for item in stored]
    if any(item['position'] != index or events[index]['index'] != index
           for index, item in enumerate(stored)):
        raise AdvisoryError('Route event positions rejected')
    if not rows:
        return None, None, events
    row = rows[0]
    if row['id'] != 1:
        raise AdvisoryError('Route identity rejected')
    plan = decode('route-plan', row['plan'])
    attempts = [dict(item) for item in connection.execute('SELECT * FROM attempts LIMIT 100001')]
    ids = {item['attempt_id'] for item in attempts}
    recorded = [event['attempt_id'] for event in events]
    if not set(recorded) <= ids or len(set(recorded)) != len(recorded):
        raise AdvisoryError('Route attempt history rejected')
    validate_event_bindings(plan, events, attempts)
    final = None
    if events:
        last = events[-1]
        final = last['review_status'] if last['status'] == 'REVIEWED' else last['status']
        if final == 'KNOWN_RETRYABLE_FAILURE':
            final = 'EXHAUSTED' if len(events) == len(plan['steps']) else None
    allowed = {final, 'DEADLINE_EXCEEDED'}
    if final is None:
        allowed.add('ADMISSION_DENIED')
    if row['final_status'] not in allowed:
        raise AdvisoryError('Route final outcome rejected')
    return row, plan, events


def owned(connection, token):
    row, plan, events = state(connection)
    if row is None or row['token'] != token or row['final_status'] is not None:
        raise AdvisoryError('Route ownership denied')
    return row, plan, events


def admit_route(connection, token, request_sha256, quote_sha256):
    _, plan, events = owned(connection, token)
    if (len(events) >= len(plan['steps']) or
            (events and events[-1]['status'] != 'KNOWN_RETRYABLE_FAILURE')):
        raise AdvisoryError('Route progression denied')
    step = plan['steps'][len(events)]
    if (step['request_sha256'], step['quote_sha256']) != (request_sha256, quote_sha256):
        raise AdvisoryError('Route candidate mismatch')


class RouteJournal:
    def __init__(self, ledger):
        if type(ledger) is not UsageLedger or ledger.version != 3:
            raise AdvisoryError('Routing ledger required')
        self.ledger = ledger

    def snapshot(self):
        with database(self.ledger.path) as connection:
            self.ledger._validate(connection)
            row, _, events = state(connection)
            return {'version': '1', 'status': 'UNCLAIMED' if row is None else
                    (row['final_status'] or 'RUNNING'), 'events': events}

    def claim(self, payload):
        plan = decode('route-plan', payload)
        if plan['operation_sha256'] != sha(self.ledger.operation.payload):
            raise AdvisoryError('Route operation mismatch')
        with database(self.ledger.path) as connection:
            self.ledger._validate(connection)
            row, _, _ = state(connection)
            if row is not None:
                if row['plan'] != payload or row['final_status'] is None:
                    raise AdvisoryError('Route conflict or recovery required')
                return None
            if connection.execute('SELECT 1 FROM attempts LIMIT 1').fetchone() is not None:
                raise AdvisoryError('Pristine routing ledger required')
            token = str(uuid4())
            connection.execute('INSERT INTO route VALUES (1, ?, ?, NULL)', (payload, token))
            return token

    def stop(self, token, status):
        if status not in ('DEADLINE_EXCEEDED', 'ADMISSION_DENIED'):
            raise AdvisoryError('Invalid route stop')
        with database(self.ledger.path) as connection:
            self.ledger._validate(connection)
            owned(connection, token)
            connection.execute('UPDATE route SET final_status=? WHERE id=1', (status,))

    def record(self, token, event, *, expired=False):
        payload = encode('route-event', event)
        with database(self.ledger.path) as connection:
            self.ledger._validate(connection)
            _, plan, events = owned(connection, token)
            position = len(events)
            if position >= len(plan['steps']) or event['index'] != position:
                raise AdvisoryError('Route event order rejected')
            step = plan['steps'][position]
            attempt = connection.execute('SELECT * FROM attempts WHERE attempt_id=?',
                                         (event['attempt_id'],)).fetchone()
            if (event['model_id'] != step['model_id'] or event['request_sha256'] != step['request_sha256']
                    or attempt is None or attempt['request_sha256'] != step['request_sha256']
                    or (event['status'] == 'KNOWN_RETRYABLE_FAILURE' and attempt['status'] != 'SETTLED')):
                raise AdvisoryError('Route event binding rejected')
            validate_event_bindings(plan, [*events, event],
                                    [dict(item) for item in connection.execute('SELECT * FROM attempts LIMIT 100001')])
            final = event['review_status'] if event['status'] == 'REVIEWED' else event['status']
            if final == 'KNOWN_RETRYABLE_FAILURE':
                final = 'EXHAUSTED' if position + 1 == len(plan['steps']) else None
            if expired:
                final = 'DEADLINE_EXCEEDED'
            connection.execute('INSERT INTO route_events VALUES (?, ?)', (position, payload))
            connection.execute('UPDATE route SET final_status=? WHERE id=1', (final,))
