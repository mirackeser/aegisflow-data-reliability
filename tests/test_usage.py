# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, UsageQuote, initialize_usage
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / 'evidence.db'
        initialize(self.evidence)
        store = IncidentStore(self.evidence)
        source = store.record(generate_orders(), request_key='usage-source')
        self.runs = InvestigationRuns(store)
        self.record = self.runs.execute(source['incident_id'], default_policy(), request_key='usage-run')
        self.prepared = PreparedAdvisory(self.runs, self.record['run_id'], model_id='offline/test')
        self.quote = UsageQuote(self.prepared.manifest['input_sha256'], 'offline/test', 'fixture/tokenizer-price-v1', 10, 5, 2, 3)
        self.now = 1000
        self.path = self.root / 'usage.db'
        initialize_usage(self.path, UsagePolicy(max_tokens=30, max_cost_nusd=70))
        self.ledger = UsageLedger(self.path, clock_ms=lambda: self.now)

    def reserve(self, key='first', **changes):
        values = dict(attempt_key=key, deadline_ms=2000)
        values.update(changes)
        return self.ledger.reserve(self.prepared, self.quote, **values)

    def start(self):
        row = self.reserve()
        self.ledger.transition(row['attempt_id'], 'start')
        return row['attempt_id']

    def test_reserve_restart_exact_input_quote_and_no_evidence_mutation(self):
        before = self.evidence.read_bytes()
        row = self.reserve()
        self.assertEqual(row['reserved_tokens'], 15)
        self.assertEqual(row['reserved_cost_nusd'], 35)
        self.assertEqual(row['input_sha256'], self.prepared.manifest['input_sha256'])
        self.assertNotIn('first', json.dumps(row))
        reopened = UsageLedger(self.path, clock_ms=lambda: self.now)
        self.assertEqual(reopened.snapshot(), self.ledger.snapshot())
        self.assertEqual(self.evidence.read_bytes(), before)

    def test_policy_invalid_types_and_ranges(self):
        for field, values in {'max_tokens': [True, 0, 10**9 + 1], 'max_cost_nusd': [-1, 10**18 + 1, 1.1],
                'max_attempts': [False, 0, 9], 'max_duration_ms': [0, 600001, '10']}.items():
            for value in values:
                with self.assertRaises(AdvisoryError): UsagePolicy(**{field: value})
        with self.assertRaises(AdvisoryError): initialize_usage(self.root / 'bad.db', {})

    def test_quote_invalid_identity_types_and_numeric_bounds(self):
        for field, values in {'input_sha256': [None, 'x', 'A' * 64], 'model_id': [None, ' bad', 'a\nb'],
                'adapter_id': [None, '', 'a' * 129], 'input_tokens': [False, 0, 1000001],
                'output_limit': [-1, float('nan')], 'input_rate_nusd': [-1, 1000000001],
                'output_rate_nusd': [True, float('inf')]}.items():
            for value in values:
                with self.assertRaises(AdvisoryError): replace(self.quote, **{field: value})

    def test_initializer_preserves_existing_ledger_and_evidence(self):
        for path in (self.path, self.evidence):
            before = path.read_bytes()
            with self.assertRaises(AdvisoryError): initialize_usage(path)
            self.assertEqual(path.read_bytes(), before)

    def test_missing_malformed_and_unsupported_database_fail_sanitized(self):
        for path in (self.root / 'missing.db', self.root / 'bad.db'):
            with self.assertRaisesRegex(AdvisoryError, '^Usage ledger unavailable$'): UsageLedger(path)
        path = self.root / 'bad.db'
        path.write_bytes(b'private-marker-not-sqlite')
        with self.assertRaisesRegex(AdvisoryError, '^Usage ledger unavailable$'): UsageLedger(path)
        for statement in ('UPDATE metadata SET version=2', 'DELETE FROM metadata'):
            other = self.root / ('case-' + str(len(statement)) + '.db')
            initialize_usage(other)
            with sqlite3.connect(other) as connection: connection.execute(statement)
            with self.assertRaisesRegex(AdvisoryError, 'Unsupported usage ledger'): UsageLedger(other)

    def test_malformed_stored_policy_fails_closed(self):
        for value in (b'not-json', b'[]', b'{"unknown": 1}', b'{"max_tokens": false}'):
            with sqlite3.connect(self.path) as connection: connection.execute('UPDATE metadata SET policy=?', (value,))
            with self.assertRaises(AdvisoryError): UsageLedger(self.path)

    def test_system_clock_default_is_available(self):
        other = UsageLedger(self.path)
        self.assertGreater(other.clock_ms(), 0)

    def test_host_object_key_deadline_and_quote_binding_rejection(self):
        for prepared, quote in (({}, self.quote), (self.prepared, {})):
            with self.assertRaises(AdvisoryError): self.ledger.reserve(prepared, quote, attempt_key='x', deadline_ms=2000)
        for key in (None, '', 'x' * 65, 'private key', 'x\ny'):
            with self.assertRaises(AdvisoryError): self.reserve(key)
        for deadline in (True, -1, 10**18 + 1):
            with self.assertRaises(AdvisoryError): self.reserve(deadline_ms=deadline)
        for quote in (replace(self.quote, input_sha256='0' * 64), replace(self.quote, model_id='other/model')):
            with self.assertRaises(AdvisoryError): self.ledger.reserve(self.prepared, quote, attempt_key='x', deadline_ms=2000)

    def test_idempotent_reservation_and_conflicts(self):
        row = self.reserve()
        self.assertEqual(self.reserve(), row)
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)
        for quote, deadline in ((replace(self.quote, output_limit=4), 2000), (self.quote, 2001)):
            with self.assertRaises(AdvisoryError): self.ledger.reserve(self.prepared, quote, attempt_key='first', deadline_ms=deadline)
        prepared = PreparedAdvisory(self.runs, self.record['run_id'], model_id='offline/test')
        quote = replace(self.quote, input_sha256=prepared.manifest['input_sha256'])
        with self.assertRaises(AdvisoryError): self.ledger.reserve(prepared, quote, attempt_key='first', deadline_ms=2000)

    def test_parallel_attempt_for_same_request_denied(self):
        self.reserve()
        with self.assertRaises(AdvisoryError): self.reserve('second')

    def test_mutated_prepared_message_snapshot_rejected_before_reservation(self):
        with patch.object(PreparedAdvisory, 'messages', new_callable=PropertyMock, return_value=[]):
            with self.assertRaises(AdvisoryError): self.reserve()
        self.assertEqual(self.ledger.snapshot()['attempts'], 0)

    def test_concurrent_start_is_one_shot_even_with_same_idempotency_key(self):
        row = self.reserve()
        def start(_):
            try:
                return UsageLedger(self.path, clock_ms=lambda: 1000).transition(row['attempt_id'], 'start')['status']
            except AdvisoryError:
                return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(start, (0, 1))), ['DENIED', 'IN_FLIGHT'])
        self.assertEqual(self.reserve()['status'], 'IN_FLIGHT')

    def test_deadline_expired_too_long_and_inclusive_limit(self):
        for deadline in (1000, 999, 11001):
            with self.assertRaises(AdvisoryError): self.reserve(deadline_ms=deadline)
        row = self.reserve(deadline_ms=11000)
        self.assertEqual(row['deadline_ms'], 11000)

    def test_clock_rollback_and_invalid_clock_deny_without_mutation(self):
        row = self.reserve()
        before = self.path.read_bytes()
        for value in (999, True, -1, 10**18):
            self.now = value
            with self.assertRaises(AdvisoryError): self.ledger.transition(row['attempt_id'], 'start')
            self.assertEqual(before, self.path.read_bytes())

    def test_start_once_and_expired_reservation_needs_explicit_cancel(self):
        row = self.reserve()
        self.now = 2000
        with self.assertRaises(AdvisoryError): self.ledger.transition(row['attempt_id'], 'start')
        self.assertEqual(self.ledger.snapshot()['held_tokens'], 15)
        self.ledger.transition(row['attempt_id'], 'cancel')
        self.assertEqual(self.ledger.snapshot()['held_tokens'], 0)
        self.now = 2001
        with self.assertRaises(AdvisoryError): self.reserve('second')

    def test_settlement_releases_unused_budget_and_charges_exact_integer_usage(self):
        attempt = self.start()
        with self.assertRaises(AdvisoryError): self.ledger.transition(attempt, 'start')
        row = self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=2)
        self.assertEqual(row['charged_cost_nusd'], 22)
        totals = self.ledger.snapshot()
        self.assertEqual((totals['held_tokens'], totals['charged_tokens'], totals['charged_cost_nusd']), (0, 10, 22))
        self.assertEqual(self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=2), row)
        with self.assertRaises(AdvisoryError): self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=3)
        self.assertEqual(self.ledger.snapshot(), totals)

    def test_full_cap_and_zero_usage_settlement(self):
        attempt = self.start()
        self.ledger.transition(attempt, 'settle', input_tokens=10, output_tokens=5)
        row = self.reserve('second')
        self.ledger.transition(row['attempt_id'], 'start')
        self.ledger.transition(row['attempt_id'], 'settle', input_tokens=0, output_tokens=0)
        self.assertEqual(self.ledger.snapshot()['charged_cost_nusd'], 35)
        self.assertEqual(self.ledger.snapshot()['charged_tokens'], 15)

    def test_oversized_usage_never_refunds_or_erases_hold(self):
        attempt = self.start()
        before = self.ledger.snapshot()
        for input_tokens, output_tokens in ((11, 0), (0, 6), (False, 0), (None, 1), (10**6 + 1, 0), (1, -1)):
            with self.assertRaises(AdvisoryError): self.ledger.transition(attempt, 'settle', input_tokens=input_tokens, output_tokens=output_tokens)
        self.assertEqual(self.ledger.snapshot(), before)

    def test_unknown_usage_survives_restart_and_prevents_retry_or_refund(self):
        attempt = self.start()
        self.now = 3000
        row = self.ledger.transition(attempt, 'unknown')
        self.assertEqual(self.ledger.transition(attempt, 'unknown'), row)
        self.ledger = UsageLedger(self.path, clock_ms=lambda: self.now)
        self.assertEqual(self.ledger.snapshot()['held_tokens'], 15)
        for action in ('cancel', 'start', 'settle'):
            kwargs = {'input_tokens': 0, 'output_tokens': 0} if action == 'settle' else {}
            with self.assertRaises(AdvisoryError): self.ledger.transition(attempt, action, **kwargs)
        with self.assertRaises(AdvisoryError): self.reserve('second', deadline_ms=4000)

    def test_late_known_usage_is_charged(self):
        attempt = self.start()
        self.now = 3000
        self.assertEqual(self.ledger.transition(attempt, 'settle', input_tokens=10, output_tokens=5)['status'], 'SETTLED')

    def test_cancel_idempotent_but_never_allowed_after_dispatch(self):
        row = self.reserve()
        cancelled = self.ledger.transition(row['attempt_id'], 'cancel')
        self.assertEqual(self.ledger.transition(row['attempt_id'], 'cancel'), cancelled)
        row = self.reserve('second')
        self.ledger.transition(row['attempt_id'], 'start')
        with self.assertRaises(AdvisoryError): self.ledger.transition(row['attempt_id'], 'cancel')

    def test_retry_preserves_deadline_and_caps_total_attempts(self):
        first = self.reserve()
        self.ledger.transition(first['attempt_id'], 'cancel')
        self.now = 1500
        with self.assertRaises(AdvisoryError): self.reserve('second', deadline_ms=2100)
        second = self.reserve('second')
        self.ledger.transition(second['attempt_id'], 'cancel')
        with self.assertRaises(AdvisoryError): self.reserve('third')

    def test_budget_exact_boundaries_and_independent_token_cost_denials(self):
        for index, policy in enumerate((UsagePolicy(max_tokens=14), UsagePolicy(max_cost_nusd=34))):
            path = self.root / f'limit-{index}.db'
            initialize_usage(path, policy)
            ledger = UsageLedger(path, clock_ms=lambda: self.now)
            with self.assertRaises(AdvisoryError): ledger.reserve(self.prepared, self.quote, attempt_key='x', deadline_ms=2000)
            self.assertEqual(ledger.snapshot()['attempts'], 0)
        path = self.root / 'exact.db'
        initialize_usage(path, UsagePolicy(max_tokens=15, max_cost_nusd=35))
        self.assertEqual(UsageLedger(path, clock_ms=lambda: self.now).reserve(self.prepared, self.quote, attempt_key='x', deadline_ms=2000)['status'], 'RESERVED')

    def test_charged_usage_counts_towards_future_admission(self):
        attempt = self.start()
        self.ledger.transition(attempt, 'settle', input_tokens=10, output_tokens=5)
        path = self.root / 'small.db'
        initialize_usage(path, UsagePolicy(max_tokens=29, max_cost_nusd=69))
        self.ledger = UsageLedger(path, clock_ms=lambda: self.now)
        attempt = self.start()
        self.ledger.transition(attempt, 'settle', input_tokens=10, output_tokens=5)
        with self.assertRaises(AdvisoryError): self.reserve('second')

    def test_concurrent_connections_cannot_oversubscribe_shared_budget(self):
        path = self.root / 'concurrent.db'
        initialize_usage(path, UsagePolicy(max_tokens=15, max_cost_nusd=35))
        prepared = [self.prepared, PreparedAdvisory(self.runs, self.record['run_id'], model_id='offline/test')]
        def reserve(index):
            item = prepared[index]
            quote = replace(self.quote, input_sha256=item.manifest['input_sha256'])
            try:
                return UsageLedger(path, clock_ms=lambda: 1000).reserve(item, quote, attempt_key=f'parallel-{index}', deadline_ms=2000)['status']
            except AdvisoryError:
                return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(reserve, (0, 1))), ['DENIED', 'RESERVED'])
        self.assertEqual(UsageLedger(path).snapshot()['held_tokens'], 15)

    def test_transitions_invalid_unknown_and_out_of_order(self):
        for attempt, action in ((None, 'start'), ('x', 'invalid'), ('x', 'start')):
            with self.assertRaises(AdvisoryError): self.ledger.transition(attempt, action)
        row = self.reserve()
        for action in ('settle', 'unknown'):
            kwargs = {'input_tokens': 0, 'output_tokens': 0} if action == 'settle' else {}
            with self.assertRaises(AdvisoryError): self.ledger.transition(row['attempt_id'], action, **kwargs)
        for field in ('input_tokens', 'output_tokens'):
            with self.assertRaises(AdvisoryError): self.ledger.transition(row['attempt_id'], 'start', **{field: 1})

    def test_zero_price_still_reserves_tokens(self):
        quote = replace(self.quote, input_rate_nusd=0, output_rate_nusd=0)
        row = self.ledger.reserve(self.prepared, quote, attempt_key='free', deadline_ms=2000)
        self.assertEqual(row['reserved_cost_nusd'], 0)
        self.assertEqual(row['reserved_tokens'], 15)

    def test_accounting_never_overrides_deterministic_judge(self):
        attempt = self.start()
        metadata = decode('request', self.prepared.request)
        response = encode('response', {'version': '1', 'request_sha256': sha(self.prepared.request),
            'decision': 'PROPOSE', 'assessment': 'SOURCE_QUALITY_FAILURE', 'evidence_sha256': metadata['evidence_sha256']})
        self.assertEqual(self.prepared.review_response(response)['status'], 'REJECTED_ADVISORY')
        self.ledger.transition(attempt, 'settle', input_tokens=10, output_tokens=5)
        self.assertEqual(self.ledger.snapshot()['charged_tokens'], 15)
        self.assertEqual(self.prepared.review_response(response)['status'], 'REJECTED_ADVISORY')
