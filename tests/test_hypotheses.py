# SPDX-License-Identifier: Apache-2.0
"""Tests of the hypothesis contracts, the fixed mechanism catalog and the deterministic probe loop (F04)."""
from copy import deepcopy
from datetime import datetime, timedelta
from importlib.resources import files
import json
import math
import unittest

from jsonschema import Draft202012Validator
from referencing.exceptions import Unresolvable

from aegisflow_dr import baseline as bl, baseline_eval as be, hypotheses as hy, profiling
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


START = datetime(2026, 1, 1)
NEUTRAL = "neutral"


class ScaleRuleTests(unittest.TestCase):
    def check(self, r, sd_ratio, expected):
        self.assertEqual(hy._scale_ratio_rules({"r": r, "sd_ratio": sd_ratio}), {"unit_change": expected}, (r, sd_ratio))

    def test_boundaries(self):
        self.check(10.0, 10.0, "supports")
        self.check(0.1, 0.1, "supports")
        self.check(1000.0, 1000.0 * 10 ** 0.0999, "supports")
        self.check(10 ** 0.951, 10 ** 0.951, "supports")
        self.check(10 ** 0.949, 10 ** 0.949, NEUTRAL)
        self.check(10.0, 1.0, NEUTRAL)
        self.check(10.0, 10 ** 1.11, NEUTRAL)
        self.check(10 ** 0.89, 10 ** 0.89, NEUTRAL)
        self.check(10 ** 1.06, 10 ** 1.06, NEUTRAL)
        self.check(10.0, None, NEUTRAL)
        self.check(10.0, 0.0, NEUTRAL)
        for r in (1.9, 2.0, 0.5, 1.0, -1.0, 0.0, -10.0, -0.5):
            self.check(r, 1.0, "refutes")
        self.check(2.01, 2.01, NEUTRAL)
        self.check(0.49, 0.49, NEUTRAL)
        self.check(None, 10.0, NEUTRAL)


class SpreadRuleTests(unittest.TestCase):
    def check(self, sd_ratio, shift, calibration, noise):
        self.assertEqual(hy._spread_ratio_rules({"sd_ratio": sd_ratio, "mean_shift_sd": shift}),
                         {"calibration_offset": calibration, "noise_increase": noise}, (sd_ratio, shift))

    def test_boundaries(self):
        self.check(1.0, 1.5, "supports", "refutes")
        self.check(0.8, -0.5, "supports", "refutes")
        self.check(1.25, 0.5, "supports", NEUTRAL)
        self.check(0.79, 0.6, NEUTRAL, "refutes")
        self.check(1.26, 0.6, NEUTRAL, NEUTRAL)
        self.check(1.0, 0.49, NEUTRAL, "refutes")
        self.check(0.66, 0.0, "refutes", "refutes")
        self.check(0.67, 0.0, NEUTRAL, "refutes")
        self.check(1.51, 0.0, "refutes", "supports")
        self.check(1.5, 0.49, NEUTRAL, "supports")
        self.check(1.5, -0.5, NEUTRAL, NEUTRAL)
        self.check(3.0, 1.0, "refutes", "refutes")
        self.check(3.0, -0.99, "refutes", NEUTRAL)
        self.check(None, None, NEUTRAL, NEUTRAL)


class OtherRuleTests(unittest.TestCase):
    def test_flat_share(self):
        for share, expected in ((0.3, "supports"), (1.0, "supports"), (0.29, NEUTRAL), (0.05, NEUTRAL), (0.049, "refutes"),
                                (0.0, "refutes"), (None, NEUTRAL)):
            self.assertEqual(hy._flat_share_rules({"share": share}), {"stuck_sensor": expected}, share)

    def test_interval_regularity(self):
        cases = ((2.0, 0.1, "supports", "refutes"), (2.0, 0.25, NEUTRAL, "refutes"), (2.0, None, NEUTRAL, "refutes"),
                 (0.5, 0.0, "supports", "refutes"), (1.51, 0.0, "supports", "refutes"), (1.5, 0.0, NEUTRAL, NEUTRAL),
                 (1 / 1.5, 0.0, NEUTRAL, NEUTRAL), (1.2, 0.0, NEUTRAL, NEUTRAL), (1.1, 0.0, "refutes", NEUTRAL),
                 (1 / 1.1, 0.5, "refutes", NEUTRAL), (1.0, None, "refutes", NEUTRAL), (None, 0.0, NEUTRAL, NEUTRAL))
        for ratio, cv, sampling, partial in cases:
            self.assertEqual(hy._interval_regularity_rules({"ratio": ratio, "cv": cv}),
                             {"sampling_config_change": sampling, "partial_load": partial}, (ratio, cv))

    def test_span_ratio(self):
        cases = ((0.5, "supports", "refutes"), (0.66, "supports", "refutes"), (1 / 1.5, NEUTRAL, NEUTRAL),
                 (0.8, NEUTRAL, NEUTRAL), (1 / 1.1, "refutes", "supports"), (2.0, "refutes", "supports"),
                 (None, NEUTRAL, NEUTRAL))
        for ratio, loss, delay in cases:
            self.assertEqual(hy._span_ratio_rules({"ratio": ratio}),
                             {"partial_load": loss, "source_outage": loss, "delivery_delay": delay,
                              "sampling_config_change": NEUTRAL}, ratio)

    def test_freshness_lag(self):
        for lag, outage, partial in ((2.0, "supports", "refutes"), (1.0001, "supports", "refutes"), (1.0, "refutes", NEUTRAL),
                                     (0.0, "refutes", NEUTRAL), (None, NEUTRAL, NEUTRAL)):
            self.assertEqual(hy._freshness_lag_rules({"lag_ratio": lag}), {"source_outage": outage, "partial_load": partial}, lag)

    def test_duplicate_share(self):
        for share, expected in ((0.2, "supports"), (0.75, "supports"), (0.19, NEUTRAL), (0.001, NEUTRAL), (0.0, "refutes"),
                                (None, NEUTRAL)):
            self.assertEqual(hy._duplicate_share_rules({"share": share}), {"duplicate_delivery": expected}, share)

    def test_empty_runs(self):
        for share, field, scattered in ((0.8, "supports", "refutes"), (1.0, "supports", "refutes"), (0.79, NEUTRAL, NEUTRAL),
                                        (0.3, NEUTRAL, NEUTRAL), (0.29, "refutes", "supports"), (None, NEUTRAL, NEUTRAL)):
            self.assertEqual(hy._empty_runs_rules({"longest_run_share": share}),
                             {"field_outage": field, "intermittent_loss": scattered}, share)

    def test_no_probe_concerns_genuine_change(self):
        self.assertEqual(tuple(hy.PROBE_MECHANISMS), hy.PROBES)
        for probe, mechanisms in hy.PROBE_MECHANISMS.items():
            self.assertNotIn("genuine_change", mechanisms)
            self.assertTrue(set(mechanisms) <= set(hy.MECHANISMS))


def numeric_base(median=1.0, mean=1.0, sd=1.0, column="v"):
    return {"numeric": {column: {"count": 10, "mean": mean, "sd": sd, "median": median, "edges": None, "counts": None}},
            "references": []}


def view(base, header, rows, measurements=None, stamps=None):
    return hy._Current(base, measurements or {}, header, rows, stamps if stamps is not None else [None] * len(rows))


class ProbeMeasurementTests(unittest.TestCase):
    def test_scale_and_spread_measure_current_values(self):
        rows = [[x] for x in ("0", "20", "", "x")]
        measured, outcomes = hy._scale_ratio(view(numeric_base(), ["v"], rows), "v")
        self.assertEqual(measured, {"r": 10.0, "sd_ratio": 10.0})
        self.assertEqual(outcomes, {"unit_change": "supports"})
        measured, outcomes = hy._spread_ratio(view(numeric_base(mean=8.0, sd=10.0), ["v"], rows), "v")
        self.assertEqual(measured, {"sd_ratio": 1.0, "mean_shift_sd": 0.2})
        self.assertEqual(outcomes, {"calibration_offset": NEUTRAL, "noise_increase": "refutes"})

    def test_undefined_inputs_give_null_and_neutral(self):
        rows = [["1"], ["3"]]
        measured, outcomes = hy._scale_ratio(view(numeric_base(median=0.0, sd=0.0), ["v"], rows), "v")
        self.assertEqual(measured, {"r": None, "sd_ratio": None})
        self.assertEqual(outcomes, {"unit_change": NEUTRAL})
        measured, outcomes = hy._spread_ratio(view(numeric_base(sd=0.0), ["v"], rows), "v")
        self.assertEqual(measured, {"sd_ratio": None, "mean_shift_sd": None})
        self.assertEqual(set(outcomes.values()), {NEUTRAL})
        for probe in (hy._scale_ratio, hy._spread_ratio):
            for header, cells in ((["v"], [[""], ["x"]]), (["w"], [["1"], ["2"]])):
                measured, outcomes = probe(view(numeric_base(), header, cells), "v")
                self.assertEqual(set(measured.values()), {None})
                self.assertEqual(set(outcomes.values()), {NEUTRAL})
        measured, outcomes = hy._scale_ratio(view({"numeric": {}, "references": []}, ["v"], rows), "v")
        self.assertEqual(measured, {"r": None, "sd_ratio": None})
        measured, outcomes = hy._spread_ratio(view({"numeric": {}, "references": []}, ["v"], rows), "v")
        self.assertEqual(measured, {"sd_ratio": None, "mean_shift_sd": None})
        measured, _ = hy._flat_share(view(numeric_base(), ["v"], [[""], ["a"]]), "v")
        self.assertEqual(measured, {"share": None})
        measured, _ = hy._empty_runs(view(numeric_base(), ["v"], [["1"]]), "v")
        self.assertEqual(measured, {"longest_run_share": None})
        measured, _ = hy._empty_runs(view(numeric_base(), ["w"], [[""]]), "v")
        self.assertEqual(measured, {"longest_run_share": None})
        measured, _ = hy._flat_share(view(numeric_base(), ["w"], [["1"]]), "v")
        self.assertEqual(measured, {"share": None})
        measured, outcomes = hy._freshness_lag(view({}, ["v"], rows, {"freshness": {"sla_seconds": 180, "latest": None,
                                                                                     "lag_seconds": None}}), None)
        self.assertEqual((measured, outcomes), ({"lag_ratio": None}, {"source_outage": NEUTRAL, "partial_load": NEUTRAL}))
        measured, _ = hy._freshness_lag(view({}, ["v"], rows, {"freshness": {"sla_seconds": None, "latest": None,
                                                                              "lag_seconds": 30.0}}), None)
        self.assertEqual(measured, {"lag_ratio": None})
        measured, _ = hy._interval_regularity(view({}, ["v"], rows, {"sampling_interval": {"baseline_seconds": None,
                                                                                            "current_seconds": 60}}), None)
        self.assertEqual(measured, {"ratio": None, "cv": None})
        measured, _ = hy._duplicate_share(view({}, ["v"], rows), None)
        self.assertEqual(measured, {"share": None})

    def test_flat_share_counts_runs_of_eight_on_consecutive_records(self):
        cells = ["5"] * 8 + ["1", "2"] + ["7"] * 7 + ["3"] + ["4"] * 4 + [""] + ["4"] * 4
        measured, outcomes = hy._flat_share(view(numeric_base(), ["v"], [[c] for c in cells]), "v")
        self.assertEqual(measured, {"share": round(8 / 26, 6)})
        self.assertEqual(outcomes, {"stuck_sensor": "supports"})
        measured, _ = hy._flat_share(view(numeric_base(), ["v"], [[c] for c in ["2"] * 9 + ["1"]]), "v")
        self.assertEqual(measured, {"share": 0.9})

    def test_empty_runs_longest_share(self):
        cells = ["1", "", "", "", "2", "", "3", " ", ""]
        measured, outcomes = hy._empty_runs(view(numeric_base(), ["f"], [[c] for c in cells]), "f")
        self.assertEqual(measured, {"longest_run_share": 0.5})
        self.assertEqual(outcomes, {"field_outage": NEUTRAL, "intermittent_loss": NEUTRAL})

    def test_time_probes(self):
        stamps = [START + timedelta(seconds=60 * i) for i in range(12)] + [START, None, START + timedelta(seconds=60)]
        base = {"references": [{"first": START.isoformat(), "last": (START + timedelta(seconds=1100)).isoformat()},
                               {"first": START.isoformat(), "last": (START + timedelta(seconds=1320)).isoformat()},
                               {"first": None, "last": None}]}
        current = view(base, ["ts"], [["x"]] * len(stamps), {"sampling_interval": {"baseline_seconds": 30, "current_seconds": 60},
                                                             "freshness": {"sla_seconds": 100, "latest": "x", "lag_seconds": 250}},
                       stamps)
        measured, outcomes = hy._interval_regularity(current, None)
        self.assertEqual(measured, {"ratio": 2.0, "cv": 0.0})
        self.assertEqual(outcomes, {"sampling_config_change": "supports", "partial_load": "refutes"})
        measured, outcomes = hy._span_ratio(current, None)
        self.assertEqual(measured, {"ratio": 0.545455})
        self.assertEqual(outcomes["partial_load"], "supports")
        measured, outcomes = hy._freshness_lag(current, None)
        self.assertEqual((measured, outcomes), ({"lag_ratio": 2.5}, {"source_outage": "supports", "partial_load": "refutes"}))
        measured, outcomes = hy._duplicate_share(current, None)
        self.assertEqual((measured, outcomes), ({"share": 0.133333}, {"duplicate_delivery": NEUTRAL}))
        uneven = [START + timedelta(seconds=s) for s in (0, 10, 30, 40, 60, 70, 90, 100, 120, 130, 150)]
        measured, _ = hy._interval_regularity(view({}, ["ts"], [["x"]] * 11, {"sampling_interval": {
            "baseline_seconds": 15, "current_seconds": 10}}, uneven), None)
        self.assertEqual(measured["ratio"], 0.666667)
        gaps = [10, 20, 10, 20, 10, 20, 10, 20, 10, 20]
        mean = sum(gaps) / 10
        self.assertEqual(measured["cv"], round(math.sqrt(sum((g - mean) ** 2 for g in gaps) / 10) / mean, 6))
        few = view(base, ["ts"], [["x"]] * 3, {"sampling_interval": {"baseline_seconds": 60, "current_seconds": None}},
                   [START, START, None])
        self.assertEqual(hy._interval_regularity(few, None)[0], {"ratio": None, "cv": None})
        self.assertEqual(hy._span_ratio(few, None)[0], {"ratio": 0.0})
        single = view(base, ["ts"], [["x"]] * 2, {}, [START, None])
        self.assertEqual(hy._span_ratio(single, None)[0], {"ratio": None})
        self.assertEqual(hy._duplicate_share(few, None)[0], {"share": 0.333333})
        flat = view({"references": [{"first": START.isoformat(), "last": START.isoformat()}]}, ["ts"], [["x"]] * 2, {},
                    [START, START + timedelta(seconds=5)])
        self.assertEqual(hy._span_ratio(flat, None)[0], {"ratio": None})
        unique = view(base, ["ts"], [["x"]] * 2, {}, [START, START + timedelta(seconds=5)])
        self.assertEqual(hy._duplicate_share(unique, None), ({"share": 0.0}, {"duplicate_delivery": "refutes"}))


def runner(table, calls):
    """A fake probe runner returning fixed outcomes per (probe, column); unspecified mechanisms are neutral."""
    def run(probe, column):
        calls.append((probe, column))
        fixed = table.get((probe, column), {})
        return {"x": 1.0}, {m: fixed.get(m, NEUTRAL) for m in hy.PROBE_MECHANISMS[probe]}
    return run


def observed(*findings, checks=()):
    obs = hy.observations_from(comparison(*findings), profile(*checks))
    return obs, hy.generate(obs)


class LoopTests(unittest.TestCase):
    def loop(self, obs, hyps, table, max_probes=6):
        calls = []
        result = hy._loop(obs, hyps, runner(table, calls), max_probes)
        return result, calls

    def test_selection_order_most_unrefuted_then_probe_order_then_column(self):
        obs, hyps = observed(finding("distribution_shift", "b"), finding("distribution_shift", "a"))
        (probes, stop), calls = self.loop(obs, hyps, {}, max_probes=20)
        self.assertEqual(calls, [("spread_ratio", "a"), ("spread_ratio", "b"), ("scale_ratio", "a"), ("scale_ratio", "b"),
                                 ("flat_share", "a"), ("flat_share", "b")])
        self.assertEqual(stop, "no_informative_probe")
        self.assertEqual([p["round"] for p in probes], [1, 2, 3, 4, 5, 6])
        self.assertEqual([p["id"] for p in probes], ["prb-%d" % i for i in range(1, 7)])

    def test_replanning_uses_updated_statuses(self):
        obs, hyps = observed(finding("volume_change", None, direction="drop"))
        (probes, stop), calls = self.loop(obs, hyps, {("span_ratio", None): {"partial_load": "refutes",
                                                                             "source_outage": "refutes"}})
        self.assertEqual(calls, [("span_ratio", None), ("interval_regularity", None)])
        self.assertEqual(probes[1]["outcomes"], {"hyp-1": NEUTRAL})
        self.assertEqual(stop, "no_informative_probe")
        self.assertEqual([h["status"] for h in hyps], ["open", "refuted", "refuted"])
        self.assertEqual(probes[0]["outcomes"], {"hyp-1": NEUTRAL, "hyp-2": "refutes", "hyp-3": "refutes"})

    def test_order_changes_after_a_status_update(self):
        # Initial counts: span 3; spread(a), interval, freshness 2; scale(a), flat(a) 1. Once span refutes partial_load
        # and source_outage, interval concerns 1 and freshness 0, so interval must yield to scale and flat by probe order.
        obs, hyps = observed(finding("volume_change", None, direction="drop"), finding("distribution_shift", "a"))
        (probes, stop), calls = self.loop(obs, hyps, {("span_ratio", None): {"partial_load": "refutes",
                                                                             "source_outage": "refutes"}}, max_probes=20)
        self.assertEqual(calls, [("span_ratio", None), ("spread_ratio", "a"), ("scale_ratio", "a"), ("flat_share", "a"),
                                 ("interval_regularity", None)])
        self.assertEqual(stop, "no_informative_probe")

    def test_status_rules(self):
        obs, hyps = observed(finding("volume_change", None, direction="drop"))
        table = {("span_ratio", None): {"partial_load": "supports", "source_outage": "supports"},
                 ("freshness_lag", None): {"source_outage": "refutes"},
                 ("interval_regularity", None): {"sampling_config_change": "supports"}}
        (probes, stop), calls = self.loop(obs, hyps, table)
        sampling, partial, outage = hyps
        self.assertEqual((sampling["status"], sampling["supporting"], sampling["refuting"]), ("supported", ["prb-2"], []))
        self.assertEqual((partial["status"], partial["supporting"]), ("supported", ["prb-1"]))
        self.assertEqual((outage["status"], outage["supporting"], outage["refuting"]), ("refuted", ["prb-1"], ["prb-3"]))
        self.assertEqual(stop, "no_informative_probe")
        self.assertEqual(probes[2]["outcomes"], {"hyp-2": NEUTRAL, "hyp-3": "refutes"})

    def test_resolved_needs_competitors_refuted_or_genuine(self):
        obs, hyps = observed(finding("column_added", "extra"), finding("distribution_shift", "v"))
        table = {("spread_ratio", "v"): {"calibration_offset": "refutes", "noise_increase": "refutes"},
                 ("scale_ratio", "v"): {"unit_change": "supports"}}
        (probes, stop), calls = self.loop(obs, hyps, table)
        self.assertEqual(calls, [("spread_ratio", "v"), ("scale_ratio", "v"), ("flat_share", "v")])
        self.assertEqual(stop, "no_informative_probe")
        table[("flat_share", "v")] = {"stuck_sensor": "refutes"}
        obs, hyps = observed(finding("column_added", "extra"), finding("distribution_shift", "v"))
        (probes, stop), calls = self.loop(obs, hyps, table)
        self.assertEqual(stop, "resolved")
        self.assertEqual(len(probes), 3)
        self.assertEqual(next(h for h in hyps if h["mechanism"] == "genuine_change")["status"], "open")

    def test_two_supported_on_one_observation_do_not_resolve(self):
        obs, hyps = observed(finding("distribution_shift", "v"))
        table = {("spread_ratio", "v"): {"calibration_offset": "supports", "noise_increase": "supports"},
                 ("scale_ratio", "v"): {"unit_change": "refutes"}, ("flat_share", "v"): {"stuck_sensor": "refutes"}}
        (probes, stop), _ = self.loop(obs, hyps, table)
        self.assertEqual((len(probes), stop), (3, "no_informative_probe"))

    def test_budget_exhausted_and_stop_precedence(self):
        obs, hyps = observed(finding("distribution_shift", "v"))
        (probes, stop), calls = self.loop(obs, hyps, {}, max_probes=1)
        self.assertEqual((len(probes), stop), (1, "probe_budget_exhausted"))
        obs, hyps = observed(finding("distribution_shift", "v"))
        (probes, stop), _ = self.loop(obs, hyps, {}, max_probes=3)
        self.assertEqual(stop, "no_informative_probe")
        obs, hyps = observed(finding("distribution_shift", "v"))
        table = {("spread_ratio", "v"): {"calibration_offset": "refutes", "noise_increase": "refutes"},
                 ("scale_ratio", "v"): {"unit_change": "supports"}, ("flat_share", "v"): {"stuck_sensor": "refutes"}}
        (probes, stop), _ = self.loop(obs, hyps, table, max_probes=3)
        self.assertEqual(stop, "resolved")

    def test_no_observations_and_no_hypotheses(self):
        (probes, stop), calls = self.loop([], [], {})
        self.assertEqual((probes, stop, calls), ([], "no_observations", []))
        obs, hyps = observed(finding("column_added", "extra"))
        (probes, stop), calls = self.loop(obs, hyps, {})
        self.assertEqual((probes, stop, calls), ([], "no_informative_probe", []))


class RankingTests(unittest.TestCase):
    def test_supported_by_count_then_open_then_refuted_with_catalog_and_column_ties(self):
        def h(id_, mechanism, column, status, supporting=0):
            return {"id": id_, "mechanism": mechanism, "column": column, "status": status,
                    "supporting": ["prb-%d" % i for i in range(1, supporting + 1)]}
        hyps = [h("hyp-1", "genuine_change", "v", "open"), h("hyp-2", "noise_increase", "v", "refuted", 1),
                h("hyp-3", "unit_change", "v", "supported", 1), h("hyp-4", "source_outage", None, "supported", 2),
                h("hyp-5", "unit_change", "a", "supported", 1), h("hyp-6", "partial_load", None, "open"),
                h("hyp-7", "unit_change", "b", "open"), h("hyp-8", "calibration_offset", "v", "refuted")]
        self.assertEqual(hy._rank(hyps), ["hyp-4", "hyp-5", "hyp-3", "hyp-7", "hyp-1", "hyp-6", "hyp-8", "hyp-2"])

    def test_verdicts(self):
        self.assertEqual(hy._verdict([], []), "no_observations")
        obs = [observation()]
        self.assertEqual(hy._verdict(obs, [hypothesis()]), "none_supported")
        self.assertEqual(hy._verdict(obs, [hypothesis(status="supported")]), "single_supported")
        self.assertEqual(hy._verdict(obs, [hypothesis(status="supported")] * 2), "multiple_supported")


def generated_case(variant, group=None):
    group = next(g for g in range(be.GROUPS) if be.split_of(g) == "development") if group is None else group
    references, current, as_of, _ = be.generate(group, variant)
    return bl.build_baseline(references), current, as_of


def last_records(payload, keep):
    lines = payload.decode().strip().split("\n")
    return ("\n".join([lines[0]] + lines[-keep:]) + "\n").encode()


def statuses(record):
    return {(h["mechanism"], h["column"]): h["status"] for h in record["hypotheses"]}


class InvestigateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = generated_case("unit_change")
        cls.unit_record = hy.investigate(cls.unit[0], cls.unit[1], as_of=cls.unit[2])

    def test_max_probes_validated_before_any_work(self):
        base, current, as_of = self.unit
        for bad in (0, 21, True, False, 6.0, "6", None, -1):
            with self.assertRaisesRegex(InputRejected, "max_probes", msg=repr(bad)):
                hy.investigate({"not": "a baseline"}, b"", max_probes=bad)
        for good in (1, 20):
            self.assertEqual(hy.investigate(base, current, as_of=as_of, max_probes=good)["budget"]["max_probes"], good)

    def test_bad_baseline_rejected_before_payload(self):
        with self.assertRaises(InputRejected) as caught:
            hy.investigate({"not": "a baseline"}, b"\xff")
        self.assertIn("Baseline", str(caught.exception))
        with self.assertRaises(InputRejected):
            hy.investigate(self.unit[0], b"\xff")

    def test_unit_change_is_sole_supported_and_resolved(self):
        record = self.unit_record
        self.assertIs(hy.verify_investigation(record), record)
        self.assertEqual([(o["check"], o["column"]) for o in record["observations"]], [("distribution_shift", "pressure_kpa")])
        self.assertEqual(statuses(record), {
            ("unit_change", "pressure_kpa"): "supported", ("calibration_offset", "pressure_kpa"): "refuted",
            ("noise_increase", "pressure_kpa"): "refuted", ("stuck_sensor", "pressure_kpa"): "refuted",
            ("genuine_change", "pressure_kpa"): "open"})
        self.assertEqual((record["stop_reason"], record["verdict"]), ("resolved", "single_supported"))
        self.assertEqual(record["ranking"][0], "hyp-1")
        self.assertEqual(record["budget"], {"max_probes": 6, "used": len(record["probes"])})
        self.assertEqual(record["statement"], hy.STATEMENT)
        for probe in record["probes"]:
            for value in probe["measured"].values():
                self.assertTrue(value is None or round(value, 6) == value)

    def test_calibration_offset_from_mean_shift(self):
        base, current, as_of = generated_case("mean_shift_large")
        record = hy.investigate(base, current, as_of=as_of)
        result = statuses(record)
        self.assertEqual(result[("calibration_offset", "temp_c")], "supported")
        self.assertEqual(result[("noise_increase", "temp_c")], "refuted")
        self.assertEqual(result[("unit_change", "temp_c")], "refuted")
        self.assertEqual(result[("genuine_change", "temp_c")], "open")
        hy.verify_investigation(record)

    def test_partial_load_supported_and_source_outage_refuted_by_freshness(self):
        base, current, as_of = generated_case("clean")
        record = hy.investigate(base, last_records(current, 160), as_of=as_of)
        result = statuses(record)
        self.assertEqual(result[("partial_load", None)], "supported")
        self.assertEqual(result[("source_outage", None)], "refuted")
        outage = next(h for h in record["hypotheses"] if h["mechanism"] == "source_outage")
        refuters = [p for p in record["probes"] if p["id"] in outage["refuting"]]
        self.assertEqual([p["probe"] for p in refuters], ["freshness_lag"])
        hy.verify_investigation(record)

    def test_clean_batch_has_no_observations(self):
        base, current, as_of = generated_case("clean")
        record = hy.investigate(base, current, as_of=as_of)
        self.assertEqual((record["observations"], record["hypotheses"], record["probes"]), ([], [], []))
        self.assertEqual((record["stop_reason"], record["verdict"], record["budget"]["used"]),
                         ("no_observations", "no_observations", 0))
        hy.verify_investigation(record)

    def test_budget_of_one(self):
        base, current, as_of = self.unit
        record = hy.investigate(base, current, as_of=as_of, max_probes=1)
        self.assertEqual((record["stop_reason"], record["budget"]), ("probe_budget_exhausted", {"max_probes": 1, "used": 1}))
        self.assertEqual(record["verdict"], "none_supported")

    def test_deterministic_and_edit_detected(self):
        base, current, as_of = self.unit
        again = hy.investigate(base, current, as_of=as_of)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.unit_record, sort_keys=True))
        edited = deepcopy(again)
        edited["verdict"] = "multiple_supported"
        with self.assertRaises(InputRejected):
            hy.verify_investigation(edited)

    def test_genuine_change_never_supported_or_refuted(self):
        for record in (self.unit_record, hy.investigate(*generated_case("mean_shift_large")[:2])):
            for hyp in record["hypotheses"]:
                if hyp["mechanism"] == "genuine_change":
                    self.assertEqual((hyp["status"], hyp["supporting"], hyp["refuting"]), ("open", [], []))
                    self.assertFalse(any(hyp["id"] in p["outcomes"] for p in record["probes"]))

    def test_unexplained_only_observation(self):
        base, current, as_of = self.unit
        lines = current.decode().strip().split("\n")
        extra = ("\n".join([lines[0] + ",note"] + [line + ",x" for line in lines[1:]]) + "\n").encode()
        base2, plain, as_of2 = generated_case("clean")
        lines = plain.decode().strip().split("\n")
        added = ("\n".join([lines[0] + ",note"] + [line + ",x" for line in lines[1:]]) + "\n").encode()
        record = hy.investigate(base2, added, as_of=as_of2)
        self.assertEqual([o["check"] for o in record["observations"]], ["column_added"])
        self.assertEqual((record["hypotheses"], record["stop_reason"], record["verdict"]),
                         ([], "no_informative_probe", "none_supported"))
        record = hy.investigate(base, extra, as_of=as_of)
        self.assertEqual((record["stop_reason"], record["verdict"]), ("resolved", "single_supported"))

    def test_mismatched_awareness_gives_null_duplicate_share(self):
        def rows(start, n, suffix):
            return ["%s%s,%d" % ((START + timedelta(seconds=60 * i)).isoformat(), suffix, i % 13)
                    for i in range(start, start + n)]
        base = bl.build_baseline([("ts,v\n" + "\n".join(rows(400 * k, 400, "")) + "\n").encode() for k in range(3)])
        current = rows(1200, 400, "Z")
        record = hy.investigate(base, ("ts,v\n" + "\n".join(current + current[:300]) + "\n").encode())
        self.assertEqual([o["check"] for o in record["observations"]],
                         ["volume_change", "duplicate_rows", "timestamp_duplicate"])
        probe = next(p for p in record["probes"] if p["probe"] == "duplicate_share")
        self.assertEqual(probe["measured"], {"share": None})
        self.assertEqual(set(probe["outcomes"].values()), {NEUTRAL})
        self.assertEqual(statuses(record)[("duplicate_delivery", None)], "open")
        hy.verify_investigation(record)

    def test_stamp_filter_matches_the_comparison(self):
        for variant in ("clean", "sampling_slow", "clean_jitter", "duplicate"):
            base, current, as_of = generated_case("clean" if variant == "duplicate" else variant)
            if variant == "duplicate":
                lines = current.decode().strip().split("\n")
                current = ("\n".join(lines + lines[1:200]) + "\n").encode()
            comparison = bl.compare(base, current, as_of=as_of)
            view_ = hy._current_view(base, comparison, profiling.profile_csv(current), *profiling.read_table(current))
            self.assertEqual(bl.interval_median([ts for ts in view_.stamps if ts is not None]),
                             comparison["measurements"]["sampling_interval"]["current_seconds"], variant)

    def test_untimed_baseline_gives_null_time_measurements(self):
        def table(n, scale=1):
            return ("a,b\n" + "".join("%d,%d\n" % (i % 50 * scale, i % 7) for i in range(n))).encode()
        base = bl.build_baseline([table(300), table(300)])
        record = hy.investigate(base, table(120))
        self.assertEqual([(o["check"], o["direction"]) for o in record["observations"]], [("volume_change", "drop")])
        self.assertEqual([p["probe"] for p in record["probes"]], ["span_ratio", "interval_regularity", "freshness_lag"])
        self.assertTrue(all(set(p["measured"].values()) == {None} for p in record["probes"]))
        self.assertTrue(all(set(p["outcomes"].values()) == {NEUTRAL} for p in record["probes"]))
        self.assertEqual((record["stop_reason"], record["verdict"]), ("no_informative_probe", "none_supported"))

    def test_aware_duplicate_delivery(self):
        def rows(start, n):
            return ["%sZ,%d" % ((START + timedelta(seconds=60 * i)).isoformat(), i % 13) for i in range(start, start + n)]
        base = bl.build_baseline([("ts,v\n" + "\n".join(rows(400 * k, 400)) + "\n").encode() for k in range(3)])
        current = rows(1200, 400)
        payload = ("ts,v\n" + "\n".join(current + current[:300]) + "\n").encode()
        record = hy.investigate(base, payload, as_of=(START + timedelta(seconds=60 * 1600)).isoformat() + "Z")
        result = statuses(record)
        self.assertEqual(result[("duplicate_delivery", None)], "supported")
        share = next(p for p in record["probes"] if p["probe"] == "duplicate_share")["measured"]["share"]
        self.assertEqual(share, round(300 / 700, 6))
        hy.verify_investigation(record)


class SingleMechanismLimitTests(unittest.TestCase):
    """Known limits stated in the UI, the report and the design: probes assume one mechanism per column at a time."""

    @staticmethod
    def table(batch, columns, scale=1.0, shift=0.0, sd=1.0):
        from random import Random
        rng = Random("limit:%d:%d" % (batch, columns))
        lines = ["ts," + ",".join("c%d" % c for c in range(columns))]
        for j in range(400):
            stamp = (START + timedelta(seconds=60 * (400 * batch + j))).isoformat()
            lines.append(stamp + "," + ",".join("%.3f" % ((100 + 10 * c + rng.gauss(0, sd)) * scale + shift)
                                                for c in range(columns)))
        return ("\n".join(lines) + "\n").encode()

    def test_offset_plus_noise_refutes_both_true_mechanisms(self):
        base = bl.build_baseline([self.table(k, 1) for k in range(3)])
        record = hy.investigate(base, self.table(3, 1, shift=1.5, sd=3.0))
        result = statuses(record)
        self.assertEqual((result[("calibration_offset", "c0")], result[("noise_increase", "c0")]), ("refuted", "refuted"))
        self.assertEqual(record["verdict"], "none_supported")

    def test_unit_change_across_six_columns_spends_the_default_budget(self):
        base = bl.build_baseline([self.table(k, 6) for k in range(3)])
        record = hy.investigate(base, self.table(3, 6, scale=10.0))
        self.assertEqual(hy.MAX_PROBES_DEFAULT, 6)
        self.assertEqual([p["probe"] for p in record["probes"]], ["spread_ratio"] * 6)
        self.assertEqual((record["stop_reason"], record["verdict"]), ("probe_budget_exhausted", "none_supported"))
