# SPDX-License-Identifier: Apache-2.0
"""Trusted-host, durable admission accounting. No provider transport or billing claims."""
from contextlib import contextmanager, closing
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from ..storage.store import canonical, sha
from .accounting import MAX_RECORDS, audit_rows
from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode
from .operation import OperationBinding

LIMIT = 10**18


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AdvisoryError('Invalid usage limit')


@dataclass(frozen=True)
class UsagePolicy:
    max_tokens: int = 100_000
    max_cost_nusd: int = 1_000_000_000
    max_attempts: int = 2
    max_duration_ms: int = 10_000
    max_total_attempts: int | None = None

    def __post_init__(self):
        integer(self.max_tokens, 1, 10**9)
        integer(self.max_cost_nusd, 0, LIMIT)
        integer(self.max_attempts, 1, 8)
        integer(self.max_duration_ms, 1, 600_000)
        if self.max_total_attempts is not None:
            integer(self.max_total_attempts, 1, 100_000)


@dataclass(frozen=True)
class UsageQuote:
    """Host-approved full-input token count and provider output cap/rates.

    Rates are integer nano-US dollars per token (one USD = 10**9 nUSD).
    Adapter identity covers tokenizer, pricing revision and framing assumptions.
    No automatic tokenizer or provider price discovery is supplied.
    """
    input_sha256: str
    model_id: str
    adapter_id: str
    input_tokens: int
    output_limit: int
    input_rate_nusd: int
    output_rate_nusd: int

    def __post_init__(self):
        if (type(self.input_sha256) is not str or re.fullmatch('[0-9a-f]{64}', self.input_sha256) is None
                or type(self.model_id) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', self.model_id) is None
                or type(self.adapter_id) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', self.adapter_id) is None):
            raise AdvisoryError('Invalid usage quote identity')
        integer(self.input_tokens, 1, 10**6)
        integer(self.output_limit, 1, 10**6)
        integer(self.input_rate_nusd, 0, 10**9)
        integer(self.output_rate_nusd, 0, 10**9)

    @property
    def tokens(self):
        return self.input_tokens + self.output_limit

    @property
    def cost(self):
        return self.input_tokens * self.input_rate_nusd + self.output_limit * self.output_rate_nusd


SCHEMA = (
    'CREATE TABLE metadata (version INTEGER NOT NULL, policy BLOB NOT NULL, observed_ms INTEGER NOT NULL)',
    '''CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, key_sha256 TEXT UNIQUE NOT NULL,
       request_sha256 TEXT NOT NULL, input_sha256 TEXT NOT NULL, model_id TEXT NOT NULL,
       quote_sha256 TEXT NOT NULL, deadline_ms INTEGER NOT NULL, status TEXT NOT NULL,
       input_cap INTEGER NOT NULL, output_cap INTEGER NOT NULL, input_rate INTEGER NOT NULL,
       output_rate INTEGER NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost_nusd INTEGER NOT NULL,
       actual_input INTEGER, actual_output INTEGER, charged_tokens INTEGER NOT NULL DEFAULT 0,
       charged_cost_nusd INTEGER NOT NULL DEFAULT 0)''',
)


@contextmanager
def database(path, *, create=False):
    try:
        uri = Path(path).resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw')
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                yield connection
    except AdvisoryError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError, IndexError):
        raise AdvisoryError('Usage ledger unavailable') from None


def initialize_usage(path, policy=UsagePolicy(), *, operation=None, routing=False):
    """Explicitly initialize an empty, separate local database; never migrate evidence."""
    if type(policy) is not UsagePolicy:
        raise AdvisoryError('Trusted usage policy required')
    if operation is not None and (type(operation) is not OperationBinding or policy.max_total_attempts is None):
        raise AdvisoryError('Bound operation requires a total attempt limit')
    if type(routing) is not bool or (routing and operation is None):
        raise AdvisoryError('Routing requires a bound operation')
    with database(path, create=True) as connection:
        if connection.execute('SELECT name FROM sqlite_master').fetchone() is not None:
            raise AdvisoryError('Empty usage database required')
        for statement in SCHEMA:
            connection.execute(statement)
        if operation is None:
            connection.execute('INSERT INTO metadata VALUES (1, ?, 0)', (canonical(asdict(policy)),))
        else:
            connection.execute('ALTER TABLE metadata ADD COLUMN operation BLOB NOT NULL DEFAULT X\'\'')
            connection.execute('INSERT INTO metadata VALUES (?, ?, 0, ?)',
                               (3 if routing else 2, canonical(asdict(policy)), operation.payload))
        if routing:
            from .route_store import SCHEMA as ROUTING_SCHEMA
            for statement in ROUTING_SCHEMA:
                connection.execute(statement)


class UsageLedger:
    """One local budget scope. Transactions serialize reservations across processes.

    RESERVED -> IN_FLIGHT -> SETTLED or UNKNOWN; RESERVED -> CANCELLED.
    UNKNOWN retains its full reservation and blocks retry for that request.
    Receipts are accounting records, not reusable dispatch authorizations.
    """
    def __init__(self, path, *, clock_ms=None, operation_id=None):
        self.path = Path(path)
        self.clock_ms = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000
        with database(self.path) as connection:
            rows = connection.execute('SELECT * FROM metadata').fetchall()
            if (len(rows) != 1 or rows[0]['version'] not in (1, 2, 3)
                    or ('operation' in rows[0].keys()) != (rows[0]['version'] >= 2)):
                raise AdvisoryError('Unsupported usage ledger')
            try:
                self.policy = UsagePolicy(**json.loads(rows[0]['policy']))
            except (TypeError, ValueError):
                raise AdvisoryError('Invalid stored usage policy') from None
            self._policy_payload = rows[0]['policy']
            self.version = rows[0]['version']
            self.operation = None
            if self.version >= 2:
                self.operation = OperationBinding(rows[0]['operation'])
                if (operation_id != decode('operation', self.operation.payload)['operation_id']
                        or self.policy.max_total_attempts is None):
                    raise AdvisoryError('Operation identity or total limit rejected')
            elif operation_id is not None:
                raise AdvisoryError('Unbound ledger cannot authorize an operation')
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('route', 'route_events')")}
            if tables != ({'route', 'route_events'} if self.version == 3 else set()):
                raise AdvisoryError('Unsupported routing ledger schema')
            self._validate(connection)

    def _now(self, connection):
        now = self.clock_ms()
        integer(now, 0, LIMIT - 600_000)
        previous = connection.execute('SELECT observed_ms FROM metadata').fetchone()[0]
        if now < previous:
            raise AdvisoryError('Usage clock moved backwards')
        connection.execute('UPDATE metadata SET observed_ms = ?', (now,))
        return now

    def _validate(self, connection):
        rows = connection.execute('SELECT * FROM metadata LIMIT 2').fetchall()
        if (len(rows) != 1 or rows[0]['version'] != self.version or
                rows[0]['policy'] != self._policy_payload or
                (rows[0]['operation'] if self.version >= 2 else None) !=
                (self.operation.payload if self.operation is not None else None)):
            raise AdvisoryError('Usage authority changed')
        integer(rows[0]['observed_ms'], 0, LIMIT - 600_000)
        return self._totals(connection)

    def _totals(self, connection):
        rows = connection.execute('SELECT * FROM attempts LIMIT ?', (MAX_RECORDS + 1,)).fetchall()
        operation = None if self.operation is None else decode('operation', self.operation.payload)
        return audit_rows(rows, self.policy, operation)

    def snapshot(self):
        with database(self.path) as connection:
            return {'version': str(self.version),
                    'policy': asdict(self.policy), **self._validate(connection)}

    def reserve(self, prepared, quote, *, attempt_key, deadline_ms, route_token=None):
        if type(prepared) is not PreparedAdvisory or type(quote) is not UsageQuote:
            raise AdvisoryError('Trusted prepared input and quote required')
        if type(attempt_key) is not str or re.fullmatch('[A-Za-z0-9_-]{1,64}', attempt_key) is None:
            raise AdvisoryError('Invalid attempt key')
        integer(deadline_ms, 0, LIMIT)
        manifest = prepared.manifest
        request = decode('request', prepared.request)
        if (quote.input_sha256 != manifest['input_sha256'] or quote.model_id != request['model_id']
                or sha(canonical(prepared.messages)) != quote.input_sha256):
            raise AdvisoryError('Usage quote does not match prepared input')
        key = sha(attempt_key.encode())
        digest = sha(canonical(asdict(quote)))
        with database(self.path) as connection:
            self._validate(connection)
            if self.operation is not None:
                self.operation.admit(prepared, deadline_ms)
            if self.version == 3:
                from .route_store import admit_route
                admit_route(connection, route_token, manifest['request_sha256'], digest)
            elif route_token is not None:
                raise AdvisoryError('Route token requires routing ledger')
            now = self._now(connection)
            old = connection.execute('SELECT * FROM attempts WHERE key_sha256 = ?', (key,)).fetchone()
            if old is not None:
                if (old['request_sha256'], old['quote_sha256'], old['deadline_ms']) != (manifest['request_sha256'], digest, deadline_ms):
                    raise AdvisoryError('Attempt key conflict')
                return dict(old)
            prior = connection.execute('SELECT * FROM attempts WHERE request_sha256 = ?',
                                       (manifest['request_sha256'],)).fetchall()
            if len(prior) >= self.policy.max_attempts or any(row['status'] in ('RESERVED', 'IN_FLIGHT', 'UNKNOWN') for row in prior):
                raise AdvisoryError('Request attempt admission denied')
            if (not now < deadline_ms <= now + self.policy.max_duration_ms
                    or any(row['deadline_ms'] != deadline_ms for row in prior)):
                raise AdvisoryError('Request deadline rejected')
            totals = self._totals(connection)
            if totals['attempts'] >= MAX_RECORDS:
                raise AdvisoryError('Usage record capacity reached')
            if self.policy.max_total_attempts is not None:
                scope = connection.execute('SELECT deadline_ms,status FROM attempts').fetchall()
                if (totals['attempts'] >= self.policy.max_total_attempts
                        or any(row['deadline_ms'] != deadline_ms or row['status'] in
                               ('RESERVED', 'IN_FLIGHT', 'UNKNOWN') for row in scope)):
                    raise AdvisoryError('Shared operation admission denied')
            if (totals['held_tokens'] + totals['charged_tokens'] + quote.tokens > self.policy.max_tokens
                    or totals['held_cost_nusd'] + totals['charged_cost_nusd'] + quote.cost > self.policy.max_cost_nusd):
                raise AdvisoryError('Usage budget exceeded')
            attempt = str(uuid4())
            connection.execute('''INSERT INTO attempts (attempt_id, key_sha256, request_sha256, input_sha256,
                model_id, quote_sha256, deadline_ms, status, input_cap, output_cap, input_rate, output_rate,
                reserved_tokens, reserved_cost_nusd) VALUES (?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?, ?, ?, ?)''',
                (attempt, key, manifest['request_sha256'], quote.input_sha256, quote.model_id, digest, deadline_ms,
                 quote.input_tokens, quote.output_limit, quote.input_rate_nusd, quote.output_rate_nusd, quote.tokens, quote.cost))
            return dict(connection.execute('SELECT * FROM attempts WHERE attempt_id = ?', (attempt,)).fetchone())

    def transition(self, attempt_id, action, *, input_tokens=None, output_tokens=None):
        """Trusted adapter reports usage, never model-supplied response metadata.

        start is one-shot; network ambiguity must use unknown, never cancel/refund.
        Late known settlement is allowed. No automatic retry, expiration refund or reconciliation.
        """
        if type(attempt_id) is not str or action not in ('start', 'cancel', 'settle', 'unknown'):
            raise AdvisoryError('Invalid usage transition')
        if action == 'settle':
            integer(input_tokens, 0, 10**6)
            integer(output_tokens, 0, 10**6)
        elif input_tokens is not None or output_tokens is not None:
            raise AdvisoryError('Unexpected usage fields')
        with database(self.path) as connection:
            self._validate(connection)
            now = self._now(connection)
            row = connection.execute('SELECT * FROM attempts WHERE attempt_id = ?', (attempt_id,)).fetchone()
            if row is None:
                raise AdvisoryError('Unknown usage attempt')
            target = {'start': 'IN_FLIGHT', 'cancel': 'CANCELLED', 'settle': 'SETTLED', 'unknown': 'UNKNOWN'}[action]
            if action == 'settle' and row['status'] == 'SETTLED':
                if (row['actual_input'], row['actual_output']) != (input_tokens, output_tokens):
                    raise AdvisoryError('Usage settlement conflict')
                return dict(row)
            if action in ('cancel', 'unknown') and row['status'] == target:
                return dict(row)
            expected = 'RESERVED' if action in ('start', 'cancel') else 'IN_FLIGHT'
            if row['status'] != expected or (action == 'start' and now >= row['deadline_ms']):
                raise AdvisoryError('Usage transition denied')
            charged_tokens = charged_cost = 0
            if action == 'settle':
                if input_tokens > row['input_cap'] or output_tokens > row['output_cap']:
                    raise AdvisoryError('Usage exceeds reserved limits')
                charged_tokens = input_tokens + output_tokens
                charged_cost = input_tokens * row['input_rate'] + output_tokens * row['output_rate']
            connection.execute('''UPDATE attempts SET status = ?, actual_input = ?, actual_output = ?,
                charged_tokens = ?, charged_cost_nusd = ? WHERE attempt_id = ?''',
                (target, input_tokens, output_tokens, charged_tokens, charged_cost, attempt_id))
            return dict(connection.execute('SELECT * FROM attempts WHERE attempt_id = ?', (attempt_id,)).fetchone())
