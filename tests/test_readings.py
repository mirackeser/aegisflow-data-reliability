# SPDX-License-Identifier: Apache-2.0
"""Qualitative readings: fixed words from aggregates only, at the documented thresholds."""
import unittest

from aegisflow_dr import baseline, hypotheses, hypotheses_eval as he, readings as rd
from aegisflow_dr.profiling import profile_csv


def shift(base_mean=100.0, current_mean=100.0, base_sd=1.0, current_sd=1.0):
    return {"check": "distribution_shift", "column": "x",
            "detail": {"baseline_mean": base_mean, "current_mean": current_mean, "baseline_sd": base_sd,
                       "current_sd": current_sd, "psi": 1.0, "threshold": 0.25}}


class ReadingTests(unittest.TestCase):
    def test_distribution_shift_words(self):
        cases = [((100, 1000, 1, 10), ("scaled_power_of_ten", "wider")),
                 ((100, 1, 1, 0.01), ("scaled_power_of_ten", "narrower")),
                 ((100, 500, 1, 1), ("shifted_up", "unchanged")),     # ratio 5 is not a power of ten
                 ((100, -100, 1, 1), ("sign_reversed", "unchanged")),
                 ((100, 100.6, 1, 1), ("shifted_up", "unchanged")),
                 ((100, 99.4, 1, 1), ("shifted_down", "unchanged")),
                 ((100, 100.4, 1, 1.6), ("unchanged", "wider")),
                 ((100, 100.0, 1, 0.7), ("unchanged", "narrower")),
                 ((0, 5, 0, 2), ("unchanged", "unchanged")),        # a zero baseline mean and spread: no ratio
                 ((100, 0, 1, 1), ("shifted_down", "unchanged"))]   # a zero current mean is not a scale
        for (bm, cm, bs, cs), (mean, spread) in cases:
            with self.subTest(values=(bm, cm, bs, cs)):
                self.assertEqual(rd.reading(shift(bm, cm, bs, cs), {}), {"mean": mean, "spread": spread})

    def test_other_checks(self):
        self.assertEqual(rd.reading({"check": "volume_change", "column": None, "detail": {"direction": "drop"}}, {}),
                         {"rows": "drop"})
        self.assertEqual(rd.reading({"check": "freshness", "column": "ts", "detail": {"lag_seconds": 9}}, {}),
                         {"data": "late"})
        for current, word in ((120, "longer"), (30, "shorter")):
            finding = {"check": "sampling_interval_change", "column": "ts",
                       "detail": {"baseline_seconds": 60, "current_seconds": current}}
            self.assertEqual(rd.reading(finding, {}), {"interval": word})
        empty = {"check": "empty_rate_change", "column": "f", "detail": {"baseline": 0.0, "current": 0.2}}
        self.assertEqual(rd.reading(empty, {"f": "contiguous"}), {"empty_values": "more", "empty_pattern": "contiguous"})
        fewer = dict(empty, detail={"baseline": 0.2, "current": 0.0})
        self.assertEqual(rd.reading(fewer, {}), {"empty_values": "fewer", "empty_pattern": "scattered"})
        self.assertEqual(rd.reading({"check": "column_added", "column": "y", "detail": {}}, {}), {})

    def test_empty_patterns(self):
        payload = b"a,b,c\n" + b"".join(b"1,%s,3\n" % (b"" if 2 <= i < 7 else b"2") for i in range(10)) + b"1,,3\n"
        self.assertEqual(rd.empty_patterns(payload), {"b": "contiguous"})  # 5 of 6 empty cells in one run
        self.assertEqual(rd.empty_patterns(b"a,b\n1,\n2,2\n3,\n4,4\n"), {"b": "scattered"})
        self.assertTrue(set(rd.WORDS) >= {"contiguous", "scattered"})

    def test_simulated_scenarios_read_as_their_signature(self):
        expected = {"unit_change": [{"mean": "scaled_power_of_ten", "spread": "wider"}],
                    "calibration_offset": [{"mean": "shifted_up", "spread": "unchanged"}],
                    "noise_increase": [{"mean": "unchanged", "spread": "wider"}],
                    "partial_load": [{"rows": "drop"}],
                    "delivery_delay": [{"data": "late"}],
                    "field_outage": [{"empty_values": "more", "empty_pattern": "contiguous"}],
                    "intermittent_loss": [{"empty_values": "more", "empty_pattern": "scattered"}],
                    "unmodelled_sign_flip": [{"mean": "sign_reversed", "spread": "unchanged"}]}
        group = he.GROUPS[0]
        for name, wanted in expected.items():
            with self.subTest(name=name):
                references, current, as_of, _ = he.scenario(group, name)
                comparison = baseline.compare(baseline.build_baseline(references), current, as_of=as_of)
                profile = profile_csv(current)
                found = rd.observation_readings(comparison, profile, current)
                self.assertEqual(len(found), len(hypotheses.observations_from(comparison, profile)))
                self.assertEqual(found[:len(wanted)], wanted)
                self.assertTrue(all(v in rd.WORDS and k in rd.KEYS for r in found for k, v in r.items()))


if __name__ == "__main__":
    unittest.main()
