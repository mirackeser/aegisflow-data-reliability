# SPDX-License-Identifier: Apache-2.0
"""Tests of the simulated-scenario evaluation of the hypothesis loop; they score development and validation only."""
import contextlib
from datetime import datetime, timedelta
import itertools
import math
import statistics
import unittest
from unittest import mock

from aegisflow_dr import baseline_eval as be, hypotheses, hypotheses_eval as he

MODELLED = ("unit_change", "calibration_offset", "noise_increase", "stuck_sensor", "sampling_config_change", "partial_load",
            "duplicate_delivery", "delivery_delay", "source_outage", "field_outage", "intermittent_loss")


def cells(payload):
    return [line.split(",") for line in payload.decode().strip().split("\n")]


def development_groups():
    return [g for g in he.GROUPS if he.split_of(g) == "development"]


def investigation(*supported_refuted_open):
    """A minimal investigation record: hypotheses from (mechanism, column, status) triples."""
    return {"hypotheses": [{"mechanism": m, "column": c, "status": s} for m, c, s in supported_refuted_open],
            "verdict": "single_supported", "stop_reason": "resolved", "budget": {"max_probes": 6, "used": 2}}


class SplitTests(unittest.TestCase):
    def test_split_assignment_is_stable_and_pinned(self):
        names = [he.split_of(g) for g in he.GROUPS]
        self.assertEqual(names, [he.split_of(g) for g in he.GROUPS])
        self.assertEqual(he.GROUPS, range(60, 120))
        self.assertEqual(he.SPLITS, ("development", "validation", "heldout"))
        # Realized counts only; the held-out split is never scored here.
        self.assertEqual({name: names.count(name) for name in he.SPLITS}, {"development": 30, "validation": 18, "heldout": 12})
        self.assertEqual(names[:8], ["development", "validation", "heldout", "validation", "validation", "heldout",
                                     "validation", "development"])

    def test_groups_are_disjoint_from_the_baseline_evaluation(self):
        # The observation layer (baseline.compare) was developed on baseline_eval's groups 0-59, so none is reused here.
        self.assertEqual(len(he.GROUPS), 60)
        self.assertFalse(set(he.GROUPS) & set(range(be.GROUPS)))

    def test_no_payload_is_shared_with_the_baseline_evaluation(self):
        ours, theirs = set(), set()
        for group in (he.GROUPS[0], he.GROUPS[1], he.GROUPS[-1]):
            for name in he.SCENARIOS:
                references, current, _, _ = he.scenario(group, name)
                ours.update(references)
                ours.add(current)
        for group in (0, 1, be.GROUPS - 1):
            for variant in be.VARIANTS:
                references, current, _, _ = be.generate(group, variant)
                theirs.update(references)
                theirs.add(current)
        self.assertGreater(len(ours), 3 * len(he.SCENARIOS))
        self.assertFalse(ours & theirs)

    def test_split_salt_differs_from_the_baseline_evaluation(self):
        self.assertNotEqual([he.split_of(g) for g in he.GROUPS], [be.split_of(g) for g in he.GROUPS])

    def test_scenarios_in_spec_order(self):
        self.assertEqual(he.SCENARIOS, MODELLED + ("clean", "unmodelled_sign_flip", "unmodelled_amplitude"))
        self.assertEqual(set(he.TRUTH), set(he.SCENARIOS))
        self.assertEqual(set(he.INJECTION), set(he.SCENARIOS))
        for name in MODELLED:
            self.assertEqual(he.TRUTH[name][0], name)
            self.assertIn(name, hypotheses.MECHANISMS)
        for name in ("clean", "unmodelled_sign_flip", "unmodelled_amplitude"):
            self.assertIsNone(he.TRUTH[name])


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group = development_groups()[0]
        cls.clean_refs, clean, cls.clean_as_of, _ = be.generate(cls.group, "clean")
        cls.clean = cells(clean)[1:]
        cls.latest = datetime.fromisoformat(cls.clean[-1][0])

    def table(self, name, group=None):
        references, current, as_of, truth = he.scenario(self.group if group is None else group, name)
        rows = cells(current)
        self.assertEqual(rows[0], ["ts", "temp_c", "pressure_kpa", "flow_lpm"])
        return rows[1:], datetime.fromisoformat(as_of), truth

    def test_unknown_scenario_is_refused(self):
        with self.assertRaises(ValueError):
            he.scenario(0, "nonsense")

    def test_every_scenario_is_deterministic_and_shares_the_references(self):
        for name in he.SCENARIOS:
            self.assertEqual(he.scenario(self.group, name), he.scenario(self.group, name), name)
            self.assertEqual(he.scenario(self.group, name)[0], self.clean_refs, name)
            self.assertEqual(he.scenario(self.group, name)[3], he.TRUTH[name] and he.TRUTH[name][0])

    def test_reused_baseline_variants(self):
        for name, variant in (("clean", "clean"), ("unit_change", "unit_change"), ("calibration_offset", "mean_shift_large"),
                              ("sampling_config_change", "sampling_slow"), ("delivery_delay", "stale")):
            self.assertEqual(he.scenario(self.group, name)[:3], be.generate(self.group, variant)[:3], name)
        rows, as_of, truth = self.table("delivery_delay")
        self.assertEqual((rows, as_of - self.latest, truth), (self.clean, timedelta(seconds=1800), "delivery_delay"))
        rows, _, _ = self.table("unit_change")
        self.assertTrue(all(abs(float(r[2]) - 10 * float(c[2])) < 1e-6 for r, c in zip(rows, self.clean)))
        rows, _, _ = self.table("calibration_offset")
        sd = statistics.pstdev([float(r[1]) for ref in self.clean_refs for r in cells(ref)[1:]])
        self.assertTrue(all(abs(float(r[1]) - float(c[1]) - 1.5 * sd) < 0.0011 for r, c in zip(rows, self.clean)))
        rows, as_of, _ = self.table("sampling_config_change")
        stamps = [datetime.fromisoformat(r[0]) for r in rows]
        self.assertEqual((len(rows), {(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])}), (400, {120}))
        self.assertEqual(as_of - stamps[-1], timedelta(seconds=60))

    def test_clean_as_of_is_latest_plus_60_s(self):
        rows, as_of, truth = self.table("clean")
        self.assertEqual((rows, as_of - self.latest, truth), (self.clean, timedelta(seconds=60), None))

    def test_noise_increase(self):
        rows, as_of, _ = self.table("noise_increase")
        pressures = [float(r[2]) for r in rows]
        self.assertTrue(2.4 < statistics.pstdev(pressures) < 3.6)
        self.assertLess(abs(statistics.fmean(pressures) - 100), 0.6)
        self.assertTrue(all(r[2] == "%.3f" % float(r[2]) for r in rows))
        self.assertEqual([[r[0], r[1], r[3]] for r in rows], [[c[0], c[1], c[3]] for c in self.clean])
        self.assertEqual(as_of, datetime.fromisoformat(self.clean_as_of))
        self.assertNotEqual(he.scenario(self.group, "noise_increase")[1], he.scenario(self.group + 1, "noise_increase")[1])

    def test_stuck_sensor(self):
        rows, _, _ = self.table("stuck_sensor")
        self.assertEqual(rows[:150], self.clean[:150])
        self.assertEqual({r[1] for r in rows[150:]}, {self.clean[150][1]})
        self.assertEqual([[r[0]] + r[2:] for r in rows], [[c[0]] + c[2:] for c in self.clean])

    def test_partial_load(self):
        rows, as_of, _ = self.table("partial_load")
        self.assertEqual(rows, self.clean[-160:])
        self.assertEqual(as_of - self.latest, timedelta(seconds=60))

    def test_duplicate_delivery(self):
        rows, as_of, _ = self.table("duplicate_delivery")
        self.assertEqual(rows, self.clean + self.clean[:300])
        self.assertEqual(as_of - self.latest, timedelta(seconds=60))

    def test_source_outage(self):
        rows, as_of, _ = self.table("source_outage")
        self.assertEqual(rows, self.clean[:160])
        # The timestamp the 400th record would have had, plus 60 s.
        self.assertEqual(as_of, datetime(2026, 1, 1) + timedelta(seconds=60 * (1200 + 399) + 60))

    def test_field_outage(self):
        starts = set()
        for group in development_groups()[:6]:
            rows, _, _ = self.table("field_outage", group)
            clean = cells(be.generate(group, "clean")[1])[1:]
            empty = [i for i, r in enumerate(rows) if r[3] == ""]
            self.assertEqual(len(empty), 100)
            self.assertEqual(empty, list(range(empty[0], empty[0] + 100)))
            self.assertTrue(50 <= empty[0] <= 250)
            starts.add(empty[0])
            self.assertEqual([r for i, r in enumerate(rows) if i not in empty], [c for i, c in enumerate(clean) if i not in empty])
            self.assertEqual([r[:3] for r in rows], [c[:3] for c in clean])
        self.assertGreater(len(starts), 1)

    def test_intermittent_loss(self):
        rows, _, _ = self.table("intermittent_loss")
        empty = [i for i, r in enumerate(rows) if r[3] == ""]
        self.assertEqual(len(empty), 100)
        longest = max(len(list(run)) for missing, run in itertools.groupby(range(400), key=lambda i: i in empty) if missing)
        self.assertLess(longest, 30)
        self.assertEqual([r[:3] for r in rows], [c[:3] for c in self.clean])
        self.assertEqual([r for i, r in enumerate(rows) if i not in empty],
                         [c for i, c in enumerate(self.clean) if i not in empty])

    def test_unmodelled_sign_flip(self):
        rows, _, truth = self.table("unmodelled_sign_flip")
        self.assertTrue(all(abs(float(r[2]) + float(c[2])) < 1e-9 for r, c in zip(rows, self.clean)))
        self.assertEqual([[r[0], r[1], r[3]] for r in rows], [[c[0], c[1], c[3]] for c in self.clean])
        self.assertIsNone(truth)

    def test_parameters_match_the_baseline_generator(self):
        for group in (0, 1, 7, 59, 60, 119):
            record = be._process(group)
            amplitude, _, phase = he._parameters(group)
            noise = he._temp_noise(group)
            for i in (0, 399, 1200, 1599):
                expected = "%.3f" % (20 + amplitude * math.sin(2 * math.pi * i / be.PERIOD + phase) + noise[i])
                self.assertEqual(record(i)[1], expected, (group, i))

    def test_unmodelled_amplitude(self):
        seen = set()
        for group in development_groups()[:8]:
            amplitude, _, phase = he._parameters(group)
            seen.add(amplitude)
            rows, _, truth = self.table("unmodelled_amplitude", group)
            clean = cells(be.generate(group, "clean")[1])[1:]
            self.assertIsNone(truth)
            swapped = 3.0 if amplitude == 1.0 else 1.0
            for j in (0, 25, 399):
                i = 1200 + j
                delta = (swapped - amplitude) * math.sin(2 * math.pi * i / be.PERIOD + phase)
                self.assertLess(abs(float(rows[j][1]) - float(clean[j][1]) - delta), 0.0011)
            self.assertEqual([[r[0]] + r[2:] for r in rows], [[c[0]] + c[2:] for c in clean])
        self.assertEqual(seen, {1.0, 3.0})


class ScoringTests(unittest.TestCase):
    def test_rates_without_denominator_are_none(self):
        self.assertEqual(he._show(he._rate(0, 0)), "n/a")
        self.assertEqual(he._show(None), "n/a")
        self.assertEqual(he._show(he._rate(2, 4)), "2/4 = 50.0% [15.0–85.0]")

    def test_score_case_arithmetic(self):
        row = he._empty_row()
        he.score_case(row, "unit_change", investigation(("unit_change", "pressure_kpa", "supported"),
                                                        ("genuine_change", "pressure_kpa", "open"),
                                                        ("calibration_offset", "pressure_kpa", "refuted")))
        he.score_case(row, "unit_change", investigation(("unit_change", "pressure_kpa", "supported"),
                                                        ("noise_increase", "pressure_kpa", "supported")))
        he.score_case(row, "unit_change", investigation(("unit_change", "temp_c", "supported"),
                                                        ("unit_change", "pressure_kpa", "refuted")))
        record = investigation()
        record.update(verdict="no_observations", stop_reason="no_observations", budget={"max_probes": 6, "used": 0})
        he.score_case(row, "unit_change", record)
        self.assertEqual({k: row[k] for k in he.COUNTS},
                         {"cases": 4, "truth_supported": 2, "truth_sole_supported": 1, "truth_refuted": 1, "other_supported": 2,
                          "any_hypothesis": 3})
        self.assertEqual(row["verdicts"], {"single_supported": 3, "no_observations": 1})
        self.assertEqual(row["stop_reasons"], {"resolved": 3, "no_observations": 1})
        self.assertEqual((row["probes_used"], row["probes_max"]), (6, 2))
        self.assertEqual(row["other_mechanisms"], {"noise_increase/pressure_kpa": 1, "unit_change/temp_c": 1})
        he.score_case(row, "clean", investigation(("partial_load", None, "supported"), ("genuine_change", "temp_c", "open")))
        self.assertEqual(row["other_mechanisms"]["partial_load/(no column)"], 1)

    def test_finalize_applies_metrics_by_scenario_kind(self):
        rows = {name: he._empty_row() for name in ("unit_change", "clean", "unmodelled_sign_flip")}
        he.score_case(rows["unit_change"], "unit_change", investigation(("unit_change", "pressure_kpa", "supported")))
        he.score_case(rows["clean"], "clean", investigation(("partial_load", None, "supported")))
        he.score_case(rows["clean"], "clean", investigation())
        he.score_case(rows["unmodelled_sign_flip"], "unmodelled_sign_flip",
                      investigation(("genuine_change", "pressure_kpa", "open"), ("unit_change", "pressure_kpa", "refuted")))
        for name, row in rows.items():
            he._finalize(name, row)
        unit, clean, flip = rows["unit_change"]["rates"], rows["clean"]["rates"], rows["unmodelled_sign_flip"]["rates"]
        self.assertEqual(unit["truth_supported"]["rate"], 1.0)
        self.assertEqual(unit["other_supported"]["rate"], 0.0)
        self.assertIsNone(unit["any_hypothesis"])
        self.assertIsNone(unit["misattributed"])
        self.assertIsNone(clean["truth_supported"])
        self.assertEqual((clean["any_hypothesis"]["successes"], clean["any_hypothesis"]["trials"]), (1, 2))
        self.assertEqual((clean["misattributed"]["successes"], clean["misattributed"]["trials"]), (1, 2))
        self.assertEqual(flip["misattributed"]["rate"], 0.0)
        self.assertEqual(flip["any_hypothesis"]["rate"], 1.0)
        self.assertEqual(rows["clean"]["probes_mean"], 2.0)
        empty = he._empty_row()
        he._finalize("unit_change", empty)
        self.assertIsNone(empty["probes_mean"])
        self.assertEqual(he._show(empty["rates"]["truth_supported"]), "n/a")

    def test_render_shows_n_a_for_empty_split(self):
        report = {"version": he.VERSION, "scope": he.SCOPE, "groups": len(he.GROUPS),
                  "splits": {"development": he._empty_bucket(he.SCENARIOS)}}
        for name, row in report["splits"]["development"]["scenarios"].items():
            he._finalize(name, row)
        text = he.render_markdown(report)
        self.assertIn("| unit_change | n/a | n/a | n/a | n/a | n/a | n/a |", text)
        self.assertIn("| unit_change | 0 | n/a | 0 |", text)


class MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = he.evaluate()
        cls.text = he.render_markdown(cls.report)

    def test_heldout_not_scored_by_default(self):
        self.assertEqual(set(self.report["splits"]), {"development", "validation"})

    def test_every_case_is_counted(self):
        for name, bucket in self.report["splits"].items():
            groups = sum(he.split_of(g) == name for g in he.GROUPS)
            self.assertEqual(bucket["groups"], groups)
            for scenario, row in bucket["scenarios"].items():
                self.assertEqual(row["cases"], groups, scenario)
                self.assertEqual(sum(row["verdicts"].values()), groups)
                self.assertEqual(sum(row["stop_reasons"].values()), groups)
                self.assertTrue(0 <= row["probes_max"] <= hypotheses.MAX_PROBES_DEFAULT)

    def test_report_text(self):
        self.assertIn("## Split: development (30 groups)", self.text)
        self.assertIn("## Split: validation (18 groups)", self.text)
        self.assertNotIn("Split: heldout", self.text)
        for phrase in ("Simulated mechanisms only", "written by the same authors as the catalog", "internal consistency",
                       "misattribution", "`genuine_change`", "cannot be tested from these data", "no root cause", "no model",
                       "no live agent", "not changed after the held-out split is scored", "n/a",
                       "docs/superpowers/specs/2026-11-24-hypothesis-contracts-design.md",
                       "development 30, validation 18 and held-out 12 groups",
                       "groups 60-119", "disjoint from the baseline comparison evaluation (D05c, groups 0-59)",
                       "An earlier draft of this evaluation reused groups 0-59",
                       "corrected before the held-out split was scored",
                       "a perfect 12/12 has a Wilson 95% lower bound of 75.8%", "Not a root-cause determination"):
            self.assertIn(phrase, self.text)
        for word in ("confirmed", "root cause found", "accuracy"):
            self.assertNotIn(word, self.text)
        self.assertIn("These are limits of the fixed probes, not tuned away.", self.text)
        for phrase in ("does not mean the supported hypothesis is correct",
                       "the unmodelled sign flip ends `resolved` with `calibration_offset` as the only supported hypothesis",
                       "`clean` produces no observations at all", "clean never tests false support of a hypothesis",
                       "Replanning adds nothing measurable on this corpus", "no scenario used more than 3 of the 6 probes",
                       "same truth and wrong-support results, only with more probes",
                       "exposed only because it also removes status updates",
                       "`stuck_sensor` co-supports `calibration_offset` on `temp_c` in some development and validation cases",
                       "the stuck run moves the mean", "stays inside the offset band"):
            self.assertIn(phrase, self.text)
        # Generality of the numbers (final review I3, I5).
        for phrase in ("misattribution for these two changes only",
                       "it is not a misattribution rate for unmodelled changes in general",
                       "Intervals cover variation between generated groups only",
                       "Injection sizes are fixed and far from every threshold (no magnitude sweep)",
                       "the sign-flip misattribution is structural: it follows from the probe rules and would hold for any "
                       "group, so it is not a sampling estimate",
                       "Probes assume one mechanism acts on a column at a time",
                       "Combined changes (for example an offset plus extra noise) can refute every candidate",
                       "the default budget of 6 can be spent before every column is probed",
                       "None of this is measured here"):
            self.assertIn(phrase, self.text)
        self.assertNotIn("how often the loop supports a catalog mechanism for a change it does not model", self.text)
        self.assertIn("(development and validation; `--include-heldout` adds the held-out split)", self.text)

    def test_prose_claims_hold_on_the_scored_splits(self):
        for bucket in self.report["splits"].values():
            rows = bucket["scenarios"]
            self.assertTrue(all(row["probes_max"] <= 3 for row in rows.values()))
            self.assertEqual(rows["clean"]["stop_reasons"], {"no_observations": rows["clean"]["cases"]})
            flip = rows["unmodelled_sign_flip"]
            self.assertEqual(flip["stop_reasons"], {"resolved": flip["cases"]})
            self.assertEqual(flip["other_mechanisms"], {"calibration_offset/pressure_kpa": flip["cases"]})
        for bucket in self.report["splits"].values():
            self.assertGreater(bucket["scenarios"]["stuck_sensor"]["other_mechanisms"]["calibration_offset/temp_c"], 0)

    def test_header_names_heldout_when_it_is_scored(self):
        report = {"version": he.VERSION, "scope": he.SCOPE, "groups": len(he.GROUPS),
                  "splits": {name: he._empty_bucket(he.SCENARIOS) for name in he.SPLITS}}
        for bucket in report["splits"].values():
            for name, row in bucket["scenarios"].items():
                he._finalize(name, row)
        text = he.render_markdown(report)
        self.assertIn("(development, validation and held-out (`--include-heldout`)).", text)
        self.assertNotIn("development and validation;", text)

    def test_other_supported_breakdown_matches_its_count(self):
        for bucket in self.report["splits"].values():
            for scenario, row in bucket["scenarios"].items():
                self.assertGreaterEqual(sum(row["other_mechanisms"].values()), row["other_supported"], scenario)
                self.assertEqual(bool(row["other_mechanisms"]), bool(row["other_supported"]), scenario)
                self.assertFalse(any(label.startswith("genuine_change/") for label in row["other_mechanisms"]))


def fixed_order_loop(update_at_end):
    """``hypotheses._loop`` with replanning disabled: pairs ordered once from the initial counts and run in that order.

    Statuses are not updated while probes run; with ``update_at_end`` they are settled once after the last probe.
    """
    def loop(observations, hyps, run_probe, max_probes):
        if not observations:
            return [], "no_observations"
        pending = hypotheses._candidates(hyps)
        order = [pair for pair in sorted(pending, key=lambda p: (-len(hypotheses._concerned(hyps, *p)), pending.index(p)))
                 if hypotheses._concerned(hyps, *pair)]
        results = []
        for pair in order[:max_probes]:
            concerned = hypotheses._concerned(hyps, *pair)
            measured, by_mechanism = run_probe(*pair)
            probe_id = "prb-%d" % (len(results) + 1)
            outcomes = {h["id"]: by_mechanism[h["mechanism"]] for h in concerned}
            for h in concerned:
                if outcomes[h["id"]] != "neutral":
                    h["supporting" if outcomes[h["id"]] == "supports" else "refuting"].append(probe_id)
            results.append({"id": probe_id, "probe": pair[0], "column": pair[1], "round": len(results) + 1,
                            "measured": measured, "outcomes": outcomes})
        if update_at_end:
            for h in hyps:
                h["status"] = "refuted" if h["refuting"] else "supported" if h["supporting"] else "open"
        return results, "probe_budget_exhausted" if len(order) > max_probes else "no_informative_probe"
    return loop


class MutantTests(unittest.TestCase):
    """Each deliberately broken part of the loop from the design must show up in the development numbers."""

    @classmethod
    def setUpClass(cls):
        cls.unbroken = he.evaluate(splits=("development",))["splits"]["development"]["scenarios"]

    def broken(self, scenarios, *patches):
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return he.evaluate(splits=("development",), scenarios=scenarios)["splits"]["development"]["scenarios"]

    def assertTruthDrops(self, rows, name):
        self.assertLess(rows[name]["truth_supported"], self.unbroken[name]["truth_supported"], name)

    def assertWrongSupportRises(self, rows, name):
        self.assertGreater(rows[name]["other_supported"], self.unbroken[name]["other_supported"], name)

    def test_unbroken_development_baseline(self):
        for name in ("unit_change", "calibration_offset", "noise_increase", "partial_load", "delivery_delay", "source_outage",
                     "duplicate_delivery"):
            row = self.unbroken[name]
            self.assertEqual((row["truth_supported"], row["other_supported"]), (row["cases"], 0), name)

    def test_disabled_scale_ratio_is_exposed(self):
        rows = self.broken(("unit_change",),
                           mock.patch.object(hypotheses, "_scale_ratio_rules", lambda m: {"unit_change": "neutral"}))
        self.assertEqual(rows["unit_change"]["truth_supported"], 0)
        self.assertTruthDrops(rows, "unit_change")

    def test_swapped_spread_thresholds_are_exposed(self):
        original = hypotheses._spread_ratio_rules

        def swapped(m):
            out = original(m)
            return {"calibration_offset": out["noise_increase"], "noise_increase": out["calibration_offset"]}

        rows = self.broken(("calibration_offset", "noise_increase"),
                           mock.patch.object(hypotheses, "_spread_ratio_rules", swapped))
        for name in ("calibration_offset", "noise_increase"):
            self.assertTruthDrops(rows, name)
            self.assertWrongSupportRises(rows, name)

    def test_inverted_span_probe_is_exposed(self):
        original = hypotheses._span_ratio_rules
        flip = {"supports": "refutes", "refutes": "supports", "neutral": "neutral"}
        rows = self.broken(("partial_load", "delivery_delay", "source_outage"),
                           mock.patch.object(hypotheses, "_span_ratio_rules",
                                             lambda m: {k: flip[v] for k, v in original(m).items()}))
        for name in ("partial_load", "delivery_delay", "source_outage"):
            self.assertTruthDrops(rows, name)
        self.assertWrongSupportRises(rows, "delivery_delay")

    def test_probe_budget_of_one_is_exposed(self):
        rows = self.broken(("unit_change", "partial_load", "source_outage"),
                           mock.patch.object(hypotheses, "MAX_PROBES_DEFAULT", 1))
        self.assertTruthDrops(rows, "unit_change")
        for name in ("partial_load", "source_outage"):
            self.assertWrongSupportRises(rows, name)
            self.assertEqual(rows[name]["truth_sole_supported"], 0)
            self.assertEqual(rows[name]["probes_max"], 1)

    def test_disabled_replanning_is_exposed(self):
        rows = self.broken(MODELLED, mock.patch.object(hypotheses, "_loop", fixed_order_loop(update_at_end=False)))
        for name in MODELLED:
            self.assertEqual(rows[name]["truth_supported"], 0, name)
            self.assertTruthDrops(rows, name)

    def test_fixed_order_settled_at_the_end_only_costs_probes_on_this_corpus(self):
        # A known limit, pinned so the report of it stays true: with a budget of 6 and at most a few candidate pairs per
        # scenario, a fixed order reaches the same statuses; replanning only saves probes here.
        names = ("sampling_config_change", "duplicate_delivery", "delivery_delay", "partial_load", "stuck_sensor")
        rows = self.broken(names, mock.patch.object(hypotheses, "_loop", fixed_order_loop(update_at_end=True)))
        for name in names:
            for key in ("truth_supported", "truth_sole_supported", "truth_refuted", "other_supported"):
                self.assertEqual(rows[name][key], self.unbroken[name][key], (name, key))
        for name in ("sampling_config_change", "duplicate_delivery", "delivery_delay"):
            self.assertGreater(rows[name]["probes_used"], self.unbroken[name]["probes_used"], name)


class MainTests(unittest.TestCase):
    def test_include_heldout_flag_requests_the_heldout_split(self):
        with mock.patch.object(he, "evaluate", return_value="report") as evaluate, \
                mock.patch.object(he, "render_markdown", return_value="text") as render:
            self.assertEqual(he.main(["--include-heldout"]), "text")
            evaluate.assert_called_once_with(splits=("development", "validation", "heldout"))
            render.assert_called_once_with("report")
            he.main([])
            evaluate.assert_called_with(splits=("development", "validation"))
            self.assertEqual(he.main(), "text")


if __name__ == "__main__":
    unittest.main()
