# SPDX-License-Identifier: Apache-2.0
"""Tests of the hypothesis contracts, the fixed mechanism catalog and the deterministic probe loop (F04)."""
from copy import deepcopy
from importlib.resources import files
import json
import unittest

from jsonschema import Draft202012Validator
from referencing.exceptions import Unresolvable

from aegisflow_dr import hypotheses as hy
from aegisflow_dr.pipeline import InputRejected

SHA = "a" * 64


def finding(check, column=None, **detail):
    return {"check": check, "column": column, "detail": detail}


def comparison(*findings):
    return {"source_sha256": SHA, "findings": list(findings), "not_evaluated": [], "measurements": {}}


def profile(*checks):
    return {"source_sha256": SHA, "findings": [{"check": c, "column": col, "count": 1, "records": [1], "detail": {}}
                                               for c, col in checks]}


def observation(**over):
    value = {"id": "obs-1", "source": "baseline", "check": "distribution_shift", "column": "v", "direction": None,
             "evidence_sha256": SHA}
    value.update(over)
    return value


def hypothesis(**over):
    value = {"id": "hyp-1", "mechanism": "unit_change", "column": "v", "explains": ["obs-1"], "competitors": [],
             "status": "open", "supporting": [], "refuting": []}
    value.update(over)
    return value


def probe_result(**over):
    value = {"id": "prb-1", "probe": "scale_ratio", "column": "v", "round": 1, "measured": {"r": 10.0, "sd_ratio": None},
             "outcomes": {"hyp-1": "supports"}}
    value.update(over)
    return value


def investigation(**over):
    value = {"format_version": "1", "engine": "deterministic-hypotheses-v1", "catalog_version": "1",
             "observations": [observation()], "hypotheses": [hypothesis()], "probes": [probe_result()],
             "budget": {"max_probes": 6, "used": 1}, "stop_reason": "resolved", "ranking": ["hyp-1"],
             "verdict": "single_supported", "statement": hy.STATEMENT}
    value.update(over)
    value["trace_sha256"] = hy.trace_digest(value)
    return value


EXAMPLES = {"observation": (observation, "source"), "hypothesis": (hypothesis, "status"),
            "probe_result": (probe_result, "probe"), "investigation": (investigation, "verdict")}


class ConstantTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((hy.FORMAT, hy.ENGINE, hy.CATALOG_VERSION), ("1", "deterministic-hypotheses-v1", "1"))
        self.assertEqual((hy.MAX_PROBES_DEFAULT, hy.MAX_PROBES_LIMIT), (6, 20))
        self.assertEqual(hy.MECHANISMS, ("unit_change", "calibration_offset", "noise_increase", "stuck_sensor", "genuine_change",
                                         "sampling_config_change", "partial_load", "duplicate_delivery", "delivery_delay",
                                         "source_outage", "field_outage", "intermittent_loss"))
        self.assertEqual(hy.PROBES, ("scale_ratio", "spread_ratio", "flat_share", "interval_regularity", "span_ratio",
                                     "freshness_lag", "duplicate_share", "empty_runs"))
        self.assertEqual(hy.STATEMENT, "Candidate mechanisms consistent with fixed probes on these measurements. "
                                       "Not a root-cause determination.")


class SchemaTests(unittest.TestCase):
    def test_schema_file_is_draft_2020_12_and_offline(self):
        schema = json.loads(files("aegisflow_dr").joinpath("data", "hypothesis-contracts-v1.json").read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(set(schema["$defs"]) >= {"observation", "hypothesis", "probe_result", "investigation"}, True)
        self.assertNotIn("http", json.dumps(schema).replace(schema["$schema"], ""))
        mechanisms = schema["$defs"]["mechanism"]["enum"]
        self.assertEqual(tuple(mechanisms), hy.MECHANISMS)
        self.assertEqual(tuple(schema["$defs"]["probe"]["enum"]), hy.PROBES)

    def test_remote_references_are_refused(self):
        remote = hy._validator("observation").evolve(schema={"$ref": "https://example.invalid/schema.json"})
        with self.assertRaises(Unresolvable) as caught:
            remote.validate({})
        self.assertIn("example.invalid", str(caught.exception))

    def test_every_kind_accepts_minimal_and_rejects_extra_key_and_wrong_enum(self):
        for kind, (make, enum_key) in EXAMPLES.items():
            with self.subTest(kind=kind):
                value = make()
                self.assertIs(hy.validate(kind, value), value)
                extra = deepcopy(value)
                extra["unexpected"] = 1
                with self.assertRaises(InputRejected):
                    hy.validate(kind, extra)
                wrong = deepcopy(value)
                wrong[enum_key] = "not-an-option"
                with self.assertRaises(InputRejected):
                    hy.validate(kind, wrong)

    def test_nested_and_pattern_rules(self):
        for bad in (observation(direction="sideways"), observation(evidence_sha256="A" * 64),
                    observation(evidence_sha256="a" * 63 + "\n"), observation(id="obs-0"), observation(column=""),
                    observation(check="outlier")):
            with self.assertRaises(InputRejected):
                hy.validate("observation", bad)
        for bad in (hypothesis(explains=[]), hypothesis(mechanism="root_cause"), hypothesis(competitors=["hyp-1", "hyp-1"])):
            with self.assertRaises(InputRejected):
                hy.validate("hypothesis", bad)
        for bad in (probe_result(round=0), probe_result(measured={"r": "10"}), probe_result(outcomes={"hyp-1": "confirms"}),
                    probe_result(outcomes={"x": "supports"}), probe_result(round=True)):
            with self.assertRaises(InputRejected):
                hy.validate("probe_result", bad)
        self.assertEqual(hy.validate("observation", observation(source="profile", check="flatline"))["source"], "profile")

    def test_unknown_kind_and_non_dict(self):
        for kind in ("verdict", None, 3):
            with self.assertRaises(InputRejected):
                hy.validate(kind, observation())
        with self.assertRaises(InputRejected):
            hy.validate("observation", [observation()])


class TraceTests(unittest.TestCase):
    def test_digest_is_canonical_and_ignores_itself(self):
        record = investigation()
        self.assertEqual(hy.trace_digest({**record, "trace_sha256": "0" * 64}), record["trace_sha256"])
        reordered = dict(reversed(list(record.items())))
        self.assertEqual(hy.trace_digest(reordered), record["trace_sha256"])
        self.assertEqual(len(record["trace_sha256"]), 64)

    def test_verify_accepts_untouched_and_rejects_edits(self):
        record = investigation()
        self.assertIs(hy.verify_investigation(record), record)
        edited = deepcopy(record)
        edited["hypotheses"][0]["status"] = "refuted"
        hy.validate("investigation", edited)  # still schema-valid
        with self.assertRaises(InputRejected):
            hy.verify_investigation(edited)
        broken = deepcopy(record)
        del broken["statement"]
        with self.assertRaises(InputRejected):
            hy.verify_investigation(broken)
        with self.assertRaises(InputRejected):
            hy.verify_investigation({**record, "statement": "Root cause found."})


class ObservationTests(unittest.TestCase):
    def test_maps_baseline_findings_then_three_profile_checks(self):
        comp = comparison(finding("column_missing", "gone"), finding("sampling_interval_change", "ts"),
                          finding("volume_change", None, direction="drop"), finding("freshness", "ts"),
                          finding("empty_rate_change", "f"), finding("distribution_shift", "v"))
        prof = profile(("empty_rate", "f"), ("outlier", "v"), ("flatline", "v"), ("timestamp_gap", "ts"),
                       ("duplicate_rows", None), ("timestamp_duplicate", "ts"))
        obs = hy.observations_from(comp, prof)
        self.assertEqual([(o["id"], o["source"], o["check"], o["column"], o["direction"]) for o in obs], [
            ("obs-1", "baseline", "column_missing", "gone", None),
            ("obs-2", "baseline", "sampling_interval_change", "ts", None),
            ("obs-3", "baseline", "volume_change", None, "drop"),
            ("obs-4", "baseline", "freshness", "ts", None),
            ("obs-5", "baseline", "empty_rate_change", "f", None),
            ("obs-6", "baseline", "distribution_shift", "v", None),
            ("obs-7", "profile", "flatline", "v", None),
            ("obs-8", "profile", "duplicate_rows", None, None),
            ("obs-9", "profile", "timestamp_duplicate", "ts", None)])
        self.assertTrue(all(o["evidence_sha256"] == SHA for o in obs))
        for o in obs:
            hy.validate("observation", o)

    def test_empty_inputs_give_no_observations(self):
        self.assertEqual(hy.observations_from(comparison(), profile()), [])


def mechanisms(hyps):
    return [(h["mechanism"], h["column"]) for h in hyps]


class GenerateTests(unittest.TestCase):
    def generated(self, *findings, checks=()):
        obs = hy.observations_from(comparison(*findings), profile(*checks))
        return obs, hy.generate(obs)

    def test_volume_drop_and_increase_route_by_direction(self):
        _, drop = self.generated(finding("volume_change", None, direction="drop"))
        self.assertEqual(mechanisms(drop), [("sampling_config_change", None), ("partial_load", None), ("source_outage", None)])
        _, rise = self.generated(finding("volume_change", None, direction="increase"))
        self.assertEqual(mechanisms(rise), [("sampling_config_change", None), ("duplicate_delivery", None)])

    def test_per_column_mechanisms_and_genuine_change_per_shifted_column(self):
        obs, hyps = self.generated(finding("distribution_shift", "a"), finding("distribution_shift", "b"))
        per = ["unit_change", "calibration_offset", "noise_increase", "stuck_sensor", "genuine_change"]
        self.assertEqual(mechanisms(hyps), [(m, "a") for m in per] + [(m, "b") for m in per])
        self.assertEqual([h["id"] for h in hyps], ["hyp-%d" % i for i in range(1, 11)])
        self.assertTrue(all(h["explains"] == ["obs-1"] for h in hyps[:5]))
        self.assertTrue(all(h["explains"] == ["obs-2"] for h in hyps[5:]))
        self.assertEqual(hyps[0]["competitors"], ["hyp-2", "hyp-3", "hyp-4", "hyp-5"])
        self.assertTrue(all(h["status"] == "open" and h["supporting"] == [] == h["refuting"] for h in hyps))

    def test_shared_mechanism_lists_every_observation_it_explains(self):
        obs, hyps = self.generated(finding("volume_change", None, direction="increase"), finding("distribution_shift", "v"),
                                   checks=(("flatline", "v"), ("duplicate_rows", None), ("timestamp_duplicate", "ts")))
        by_key = {(h["mechanism"], h["column"]): h for h in hyps}
        self.assertEqual(by_key[("duplicate_delivery", None)]["explains"], ["obs-1", "obs-4", "obs-5"])
        self.assertEqual(by_key[("stuck_sensor", "v")]["explains"], ["obs-2", "obs-3"])
        self.assertEqual(len(by_key), len(hyps))

    def test_freshness_empty_rate_and_sampling(self):
        _, hyps = self.generated(finding("sampling_interval_change", "ts"), finding("freshness", "ts"),
                                 finding("empty_rate_change", "f"))
        self.assertEqual(mechanisms(hyps), [("sampling_config_change", None), ("delivery_delay", None), ("source_outage", None),
                                            ("field_outage", "f"), ("intermittent_loss", "f")])

    def test_competitors_symmetric_and_exclude_self(self):
        _, hyps = self.generated(finding("sampling_interval_change", "ts"), finding("volume_change", None, direction="drop"),
                                 finding("freshness", "ts"), finding("distribution_shift", "v"),
                                 finding("empty_rate_change", "f"), checks=(("flatline", "v"), ("duplicate_rows", None)))
        ids = {h["id"]: h for h in hyps}
        for h in hyps:
            self.assertNotIn(h["id"], h["competitors"])
            self.assertEqual(h["competitors"], sorted(h["competitors"], key=lambda i: int(i[4:])))
            for other in h["competitors"]:
                self.assertIn(h["id"], ids[other]["competitors"])
                self.assertTrue(set(h["explains"]) & set(ids[other]["explains"]))
            for other in set(ids) - set(h["competitors"]) - {h["id"]}:
                self.assertFalse(set(h["explains"]) & set(ids[other]["explains"]))
            hy.validate("hypothesis", h)
        lone = next(h for h in hyps if h["mechanism"] == "duplicate_delivery")
        self.assertEqual(lone["competitors"], [])

    def test_unexplained_observation_gives_no_hypothesis(self):
        obs, hyps = self.generated(finding("column_added", "extra"))
        self.assertEqual(len(obs), 1)
        self.assertEqual(hyps, [])


if __name__ == "__main__":
    unittest.main()
