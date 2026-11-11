# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
import test_routing
from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.advisory.routing import execute_route, plan_route
from aegisflow_dr.storage.store import canonical, sha


class RecoveryTests(unittest.TestCase):
    setUp=test_routing.RoutingTests.setUp
    bind=test_routing.RoutingTests.bind
    reopen=test_routing.RoutingTests.reopen
    open_route=test_routing.RoutingTests.open_route
    candidate=test_routing.RoutingTests.candidate
    claim_dispatch=test_routing.RoutingTests.claim_dispatch

    def sql(self,statement,args=()):
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute(statement,args)

    def assessment(self):
        result=assess_recovery(self.route)
        self.assertEqual(result['assessment_sha256'],sha(canonical(result['assessment'])))
        self.assertFalse(result['assessment']['automatic_resend_allowed'])
        self.assertFalse(result['assessment']['automatic_refund_allowed'])
        return result['assessment']

    def test_unclaimed_snapshot_is_stable_and_read_only(self):
        before=self.route_path.read_bytes()
        first=self.assessment()
        self.assertEqual(first,self.assessment())
        self.assertEqual(first['decision'],'NO_RECOVERY_INDICATED')
        self.assertEqual(before,self.route_path.read_bytes())

    def test_completed_reopened_route_preserves_accounting(self):
        execute_route(self.route,self.candidates)
        value=self.assessment()
        self.assertEqual(value['decision'],'NO_RECOVERY_INDICATED')
        self.assertEqual(value['usage']['charged_tokens'],12)
        self.assertEqual(assess_recovery(self.open_route())['assessment'],value)
        self.assertEqual(len(self.calls),2)

    def test_running_route_is_not_declared_dead_or_resumable(self):
        self.journal.claim(plan_route(self.route,self.candidates))
        self.assertEqual(self.assessment()['reasons'],['ROUTE_NOT_FINALIZED'])
        with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates)
        self.assertEqual(self.calls,[])

    def test_unjournaled_known_settlement_is_visible(self):
        self.claim_dispatch()
        value=self.assessment()
        self.assertEqual(value['unrecorded_settlements'],1)
        self.assertIn('RESULT_NOT_JOURNALED',value['reasons'])
        self.assertEqual(value['usage']['charged_tokens'],2)

    def test_unknown_usage_never_releases_hold(self):
        execute_route(self.route,(self.candidate('offline/test','unknown'),))
        before=self.route_path.read_bytes()
        value=self.assessment()
        self.assertEqual(value['reasons'],['USAGE_UNRESOLVED'])
        self.assertEqual(value['usage']['held_tokens'],15)
        self.assertEqual(before,self.route_path.read_bytes())

    def test_reserved_and_inflight_have_separate_reasons(self):
        token=self.journal.claim(plan_route(self.route,self.candidates))
        first=self.candidates[0]
        row=self.route.reserve(first.prepared,first.quote,attempt_key='reserved',deadline_ms=2000,route_token=token)
        self.assertIn('RESERVATION_HELD',self.assessment()['reasons'])
        self.route.transition(row['attempt_id'],'start')
        self.assertIn('USAGE_UNRESOLVED',self.assessment()['reasons'])

    def test_state_change_changes_snapshot_digest(self):
        before=self.assessment()['snapshot_sha256']
        execute_route(self.route,self.candidates)
        self.assertNotEqual(before,self.assessment()['snapshot_sha256'])

    def test_wrong_profile_scope_and_missing_storage_are_sanitized(self):
        for ledger in ({},self.bound):
            with self.assertRaises(AdvisoryError):assess_recovery(ledger)
        self.sql('UPDATE metadata SET version=2')
        with self.assertRaises(AdvisoryError):self.assessment()
        self.route_path.unlink()
        with self.assertRaisesRegex(AdvisoryError,'^Recovery assessment unavailable$'):self.assessment()
        self.assertFalse(self.route_path.exists())

    def test_invalid_attempt_status_final_status_and_plan_rejected(self):
        self.claim_dispatch()
        self.sql("UPDATE attempts SET status='invented'")
        with self.assertRaises(AdvisoryError):self.assessment()
        self.sql("UPDATE attempts SET status='SETTLED'")
        self.sql("UPDATE route SET final_status='invented'")
        with self.assertRaises(AdvisoryError):self.assessment()
        self.sql('UPDATE route SET final_status=NULL')
        with closing(sqlite3.connect(self.route_path)) as connection:
            plan=decode('route-plan',connection.execute('SELECT plan FROM route').fetchone()[0])
        plan['operation_sha256']='0'*64
        self.sql('UPDATE route SET plan=?',(encode('route-plan',plan),))
        with self.assertRaises(AdvisoryError):self.assessment()

    def test_orphan_duplicate_and_out_of_order_events_are_rejected(self):
        execute_route(self.route,self.candidates)
        with closing(sqlite3.connect(self.route_path)) as connection:
            events=[decode('route-event',r[0]) for r in connection.execute('SELECT event FROM route_events ORDER BY position')]
        altered={**events[1],'attempt_id':events[0]['attempt_id']}
        self.sql('UPDATE route_events SET event=? WHERE position=1',(encode('route-event',altered),))
        with self.assertRaises(AdvisoryError):self.assessment()
        self.sql('UPDATE route_events SET event=? WHERE position=1',(encode('route-event',{**events[1],'index':0}),))
        with self.assertRaises(AdvisoryError):self.assessment()
        self.sql('UPDATE route_events SET event=? WHERE position=1',(encode('route-event',events[1]),))
        self.sql('DELETE FROM attempts')
        with self.assertRaises(AdvisoryError):self.assessment()

    def test_missing_route_with_attempts_is_rejected(self):
        self.claim_dispatch()
        self.sql('DELETE FROM route')
        with self.assertRaises(AdvisoryError):self.assessment()

    def test_hashing_failure_does_not_expose_details(self):
        with patch('aegisflow_dr.advisory.recovery.canonical',side_effect=ValueError('private detail')):
            with self.assertRaisesRegex(AdvisoryError,'^Recovery assessment unavailable$'):self.assessment()
