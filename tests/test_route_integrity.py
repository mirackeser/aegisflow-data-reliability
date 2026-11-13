# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

import test_routing
from aegisflow_dr.advisory.contracts import AdvisoryError,decode,encode
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.advisory.routing import execute_route,plan_route


class RouteIntegrityTests(unittest.TestCase):
    setUp=test_routing.RoutingTests.setUp
    bind=test_routing.RoutingTests.bind
    reopen=test_routing.RoutingTests.reopen
    open_route=test_routing.RoutingTests.open_route
    candidate=test_routing.RoutingTests.candidate
    claim_dispatch=test_routing.RoutingTests.claim_dispatch
    event=test_routing.RoutingTests.event

    def sql(self,statement,args=()):
        with closing(sqlite3.connect(self.route_path)) as c,c:c.execute(statement,args)

    def denied(self):
        before=self.route_path.read_bytes();count=len(self.calls)
        for action in (self.journal.snapshot,lambda:execute_route(self.route,self.candidates),
                       lambda:assess_recovery(self.route)):
            with self.assertRaises(AdvisoryError):action()
            self.assertEqual(before,self.route_path.read_bytes())
            self.assertEqual(count,len(self.calls))

    def test_success_without_events_cannot_replay_or_report_clean(self):
        self.journal.claim(plan_route(self.route,self.candidates))
        for status in ('VERIFIED_ADVISORY','ABSTAIN','EXHAUSTED','invented'):
            self.sql('UPDATE route SET final_status=?',(status,));self.denied()

    def test_success_cannot_replace_known_failure(self):
        execute_route(self.route,(self.candidate('offline/test','terminal'),))
        self.sql("UPDATE route SET final_status='VERIFIED_ADVISORY'");self.denied()

    def test_terminal_outcome_cannot_be_reset_to_running(self):
        execute_route(self.route,self.candidates)
        self.sql('UPDATE route SET final_status=NULL');self.denied()

    def test_verified_outcome_cannot_claim_admission_failure(self):
        execute_route(self.route,self.candidates)
        self.sql("UPDATE route SET final_status='ADMISSION_DENIED'");self.denied()

    def test_physical_event_positions_are_checked(self):
        execute_route(self.route,self.candidates)
        self.sql('UPDATE route_events SET position=7 WHERE position=1');self.denied()

    def test_orphan_events_reject_all_read_paths(self):
        execute_route(self.route,self.candidates)
        self.sql('DELETE FROM route');self.denied()

    def test_event_flood_is_bounded_and_rejected(self):
        token,result=self.claim_dispatch();event=self.event(result)
        for index in range(9):
            self.sql('INSERT INTO route_events VALUES (?,?)',(index,encode('route-event',event)))
        self.denied()

    def test_reviewed_event_requires_settled_attempt_before_commit(self):
        token=self.journal.claim(plan_route(self.route,self.candidates));first=self.candidates[0]
        row=self.route.reserve(first.prepared,first.quote,attempt_key='not-sent',deadline_ms=2000,route_token=token)
        event={'index':0,'model_id':first.quote.model_id,'request_sha256':row['request_sha256'],
               'attempt_id':row['attempt_id'],'status':'REVIEWED','review_status':'VERIFIED_ADVISORY'}
        before=self.route_path.read_bytes()
        with self.assertRaises(AdvisoryError):self.journal.record(token,event)
        self.assertEqual(before,self.route_path.read_bytes())
        self.assertEqual(self.calls,[])

    def test_uncertain_event_cannot_replace_settled_usage(self):
        token,result=self.claim_dispatch();event={**self.event(result),'status':'USAGE_UNKNOWN'}
        with self.assertRaises(AdvisoryError):self.journal.record(token,event)
        self.assertEqual(self.journal.snapshot()['events'],[])

    def test_exact_replay_and_deadline_override_remain_valid(self):
        execute_route(self.route,self.candidates)
        self.sql("UPDATE route SET final_status='DEADLINE_EXCEEDED'")
        self.assertEqual(self.journal.snapshot()['status'],'DEADLINE_EXCEEDED')
        self.assertTrue(execute_route(self.route,self.candidates)['replayed'])
        self.assertEqual(len(self.calls),2)

    def test_route_identity_and_extra_rows_are_rejected(self):
        self.journal.claim(plan_route(self.route,self.candidates))
        self.sql('PRAGMA ignore_check_constraints=ON')
        with closing(sqlite3.connect(self.route_path)) as c,c:
            c.execute('PRAGMA ignore_check_constraints=ON');c.execute('UPDATE route SET id=2')
        self.denied()
        with closing(sqlite3.connect(self.route_path)) as c,c:
            c.execute('PRAGMA ignore_check_constraints=ON');c.execute('INSERT INTO route SELECT 1,plan,token,final_status FROM route')
        self.denied()

    def test_admission_retains_secondary_progression_guard(self):
        from aegisflow_dr.advisory.route_store import admit_route
        # Isolate the downstream guard: even an erroneously admitted owner must
        # not index past the plan or progress after a terminal event.
        plan={'steps':[{}]}
        for events in ([{'status':'KNOWN_RETRYABLE_FAILURE'}], [{'status':'REVIEWED'}]):
            with patch('aegisflow_dr.advisory.route_store.owned',return_value=(None,plan,events)):
                with self.assertRaisesRegex(AdvisoryError,'Route progression denied'):
                    admit_route(None,'owner','0'*64,'0'*64)
