# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from dataclasses import asdict, replace
import sqlite3
import unittest
from unittest.mock import patch

import test_usage
import test_routing
from aegisflow_dr.advisory.accounting import audit_rows
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.advisory.route_store import RouteJournal
from aegisflow_dr.advisory.routing import execute_route, plan_route
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy
from aegisflow_dr.storage.store import canonical


class AccountingTests(unittest.TestCase):
    setUp = test_usage.UsageTests.setUp
    reserve = test_usage.UsageTests.reserve
    start = test_usage.UsageTests.start

    def write(self, statement, args=()):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(statement, args)

    def test_corrupt_negative_charge_cannot_increase_available_budget(self):
        attempt = self.start()
        self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=2)
        self.write('UPDATE attempts SET charged_cost_nusd=-1000')
        before = self.path.read_bytes()
        for action in (self.ledger.snapshot, lambda: self.reserve('next'),
                       lambda: self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=2),
                       lambda: UsageLedger(self.path)):
            with self.assertRaises(AdvisoryError): action()
            self.assertEqual(before, self.path.read_bytes())

    def test_stored_numeric_types_bounds_and_identity_are_strict(self):
        row = self.reserve()
        cases = {'input_cap': (0, 1000001, 1.5), 'output_cap': (0, 1000001),
                 'input_rate': (-1, 1000000001), 'output_rate': (-1, 'bad'),
                 'deadline_ms': (-1, 10**18+1), 'reserved_tokens': (-1, 14),
                 'reserved_cost_nusd': (0, 34), 'charged_tokens': (1,),
                 'charged_cost_nusd': (1,), 'actual_input': (0,), 'actual_output': (0,),
                 'status': ('bogus',), 'input_sha256': ('g'*64,), 'key_sha256': ('short',),
                 'request_sha256': (b'0'*64,), 'quote_sha256': ('A'*64,),
                 'model_id': ('not allowed', b'model')}
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.write(f'UPDATE attempts SET {field}=?', (value,))
                    with self.assertRaises(AdvisoryError): self.ledger.snapshot()
                    self.write(f'UPDATE attempts SET {field}=?', (row[field],))
        self.assertEqual(self.ledger.snapshot()['held_tokens'], 15)

    def test_settlement_is_recomputed_and_zero_usage_remains_valid(self):
        attempt = self.start()
        row = self.ledger.transition(attempt, 'settle', input_tokens=8, output_tokens=2)
        for field, value in (('actual_input', None), ('actual_output', 6),
                             ('charged_tokens', 9), ('charged_cost_nusd', 21)):
            self.write(f'UPDATE attempts SET {field}=?', (value,))
            with self.assertRaises(AdvisoryError): self.ledger.snapshot()
            self.write(f'UPDATE attempts SET {field}=?', (row[field],))
        self.assertEqual(self.ledger.snapshot()['charged_cost_nusd'], 22)
        second = self.reserve('second')
        self.ledger.transition(second['attempt_id'], 'start')
        self.ledger.transition(second['attempt_id'], 'settle', input_tokens=0, output_tokens=0)
        self.assertEqual(self.ledger.snapshot()['charged_tokens'], 10)

    def test_changed_authority_or_observation_cannot_use_cached_policy(self):
        self.reserve()
        original = canonical(asdict(self.ledger.policy))
        for field, value, restore in (('policy', canonical(asdict(UsagePolicy())), original),
                ('version', 2, 1), ('observed_ms', -1, 1000)):
            self.write(f'UPDATE metadata SET {field}=?', (value,))
            with self.assertRaises(AdvisoryError): self.ledger.snapshot()
            self.write(f'UPDATE metadata SET {field}=?', (restore,))
        self.write('INSERT INTO metadata SELECT * FROM metadata')
        with self.assertRaises(AdvisoryError): self.ledger.snapshot()
        self.write('DELETE FROM metadata')
        with self.assertRaises(AdvisoryError): self.ledger.snapshot()

    def test_shared_and_request_history_limits_are_validated(self):
        row = self.reserve()
        second = {**row, 'attempt_id':'another', 'key_sha256':'1'*64}
        for other, policy in ((second, self.ledger.policy),
                ({**second, 'request_sha256':'2'*64}, UsagePolicy(max_total_attempts=2)),
                ({**second, 'status':'CANCELLED', 'deadline_ms':2001}, self.ledger.policy),
                ({**second, 'status':'CANCELLED', 'input_sha256':'2'*64}, self.ledger.policy),
                ({**second, 'status':'CANCELLED'}, UsagePolicy(max_attempts=1)),
                ({**second, 'status':'CANCELLED', 'request_sha256':'2'*64, 'deadline_ms':2001},
                 UsagePolicy(max_total_attempts=2))):
            with self.assertRaises(AdvisoryError): audit_rows([row, other], policy, None)
        with self.assertRaises(AdvisoryError): audit_rows([row, second], UsagePolicy(max_total_attempts=1), None)

    def test_recomputed_tokens_and_cost_cannot_exceed_policy(self):
        row = self.reserve()
        for policy in (UsagePolicy(max_tokens=14), UsagePolicy(max_cost_nusd=34)):
            with self.assertRaises(AdvisoryError): audit_rows([row], policy, None)
        self.assertEqual(audit_rows([row], self.ledger.policy, None)['held_cost_nusd'], 35)

    def test_capacity_is_bounded_before_new_reservation(self):
        row = self.reserve()
        self.ledger.transition(row['attempt_id'], 'cancel')
        with patch('aegisflow_dr.advisory.usage.MAX_RECORDS', 1):
            with self.assertRaisesRegex(AdvisoryError, 'capacity'): self.reserve('next')
        with patch('aegisflow_dr.advisory.accounting.MAX_RECORDS', 0):
            with self.assertRaises(AdvisoryError): self.ledger.snapshot()
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)

    def test_cancelled_unknown_and_inflight_cannot_carry_charges(self):
        row = self.reserve()
        for status in ('CANCELLED','UNKNOWN','IN_FLIGHT'):
            with self.assertRaises(AdvisoryError):
                audit_rows([{**row, 'status':status, 'charged_cost_nusd':1}], self.ledger.policy, None)


class RoutingAccountingTests(unittest.TestCase):
    setUp = test_routing.RoutingTests.setUp
    bind = test_routing.RoutingTests.bind
    reopen = test_routing.RoutingTests.reopen
    open_route = test_routing.RoutingTests.open_route
    candidate = test_routing.RoutingTests.candidate

    def write(self, statement, args=()):
        with closing(sqlite3.connect(self.route_path)) as connection, connection:
            connection.execute(statement, args)

    def test_corrupt_reopened_recovery_and_replay_fail_without_dispatch(self):
        execute_route(self.route, self.candidates)
        self.write('UPDATE attempts SET charged_tokens=0')
        before = self.route_path.read_bytes()
        for action in (lambda: assess_recovery(self.route),
                       lambda: execute_route(self.route,self.candidates), self.open_route,
                       lambda: RouteJournal(self.route).snapshot()):
            with self.assertRaises(AdvisoryError): action()
            self.assertEqual(len(self.calls),2)
            self.assertEqual(before,self.route_path.read_bytes())

    def test_attempt_model_deadline_and_operation_cannot_change(self):
        token = self.journal.claim(plan_route(self.route, self.candidates))
        first = self.candidates[0]
        row = self.route.reserve(first.prepared, first.quote, attempt_key='held',
                                 deadline_ms=2000, route_token=token)
        for field,value in (('model_id','other/model'),('deadline_ms',2001)):
            self.write(f'UPDATE attempts SET {field}=?',(value,))
            with self.assertRaises(AdvisoryError): assess_recovery(self.route)
            self.write(f'UPDATE attempts SET {field}=?',(row[field],))
        self.write('UPDATE metadata SET operation=?',(b'{}',))
        with self.assertRaises(AdvisoryError): self.route.snapshot()
