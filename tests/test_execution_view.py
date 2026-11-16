# SPDX-License-Identifier: Apache-2.0
import unittest

from aegisflow_dr.execution_view import STATUSES, build_plan

ALL = frozenset({"diagnose_csv", "run_batch", "query_lineage"})


def plan(**changes):
    base = dict(tools_run=ALL, source_failed=False, profiled=True, has_actions=False,
                judge_decision="ACCEPT", retained=True)
    return {s["id"]: s for s in build_plan(**{**base, **changes})}


class ExecutionPlanTests(unittest.TestCase):
    def test_dependencies_reference_earlier_steps_only(self):
        steps = build_plan(tools_run=ALL, source_failed=False, profiled=True, has_actions=True,
                           judge_decision="ACCEPT", retained=True)
        seen = set()
        for step in steps:
            self.assertTrue(set(step["depends_on"]) <= seen, step["id"])
            seen.add(step["id"])

    def test_unavailable_capabilities_are_never_reported_as_run(self):
        result = plan(has_actions=True)
        for key, reason in (("root_cause", "NO_MODEL_CONFIGURED"), ("remediation", "READ_ONLY_POLICY")):
            self.assertEqual(result[key]["reason"], reason)
            self.assertNotEqual(result[key]["status"], "completed")
            self.assertEqual(result[key]["mode"], "planned")

    def test_skip_reasons_follow_the_executed_trace(self):
        result = plan(tools_run=frozenset({"diagnose_csv", "query_lineage"}), source_failed=True)
        self.assertEqual(result["reconciliation"]["reason"], "SOURCE_QUALITY_FAILURE")
        self.assertEqual(plan(tools_run=frozenset())["contract_check"]["reason"], "NOT_EXECUTED")
        self.assertEqual(plan(profiled=False)["profiling"]["reason"], "NO_FILE_PROFILE_FOR_EXAMPLE")

    def test_rejected_or_missing_verification_is_not_completed(self):
        self.assertEqual(plan(judge_decision="REJECT")["verification"]["status"], "rejected")
        self.assertEqual(plan(judge_decision=None)["verification"]["status"], "skipped")

    def test_every_emitted_status_is_a_documented_status(self):
        seen = set()
        for source_failed in (False, True):
            for judge in ("ACCEPT", "REJECT", None):
                for has_actions in (False, True):
                    for tools in (ALL, frozenset()):
                        seen |= {s["status"] for s in build_plan(
                            tools_run=tools, source_failed=source_failed, profiled=not source_failed,
                            has_actions=has_actions, judge_decision=judge, retained=not source_failed)}
        self.assertLessEqual(seen, set(STATUSES))
        self.assertEqual(seen, set(STATUSES))

    def test_role_names_come_from_the_packaged_catalog(self):
        result = plan()
        self.assertEqual(result["contract_check"]["role_name"], "Data Contract Inspector")
        self.assertEqual(result["verification"]["role_name"], "Evidence Verification Agent")


if __name__ == "__main__":
    unittest.main()
