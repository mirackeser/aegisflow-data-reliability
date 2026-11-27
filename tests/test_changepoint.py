# SPDX-License-Identifier: Apache-2.0
import math
from random import Random
import unittest

from aegisflow_dr import changepoint as cp


def wave(n, period=100.0, amplitude=3.0, noise=0.5, seed=1, mean=20.0):
    rng = Random(seed)
    ts = list(range(n))
    return ts, [mean + amplitude * math.sin(2 * math.pi * t / period) + rng.gauss(0, noise) for t in ts]


class HarmonicTests(unittest.TestCase):
    def test_fit_recovers_a_clean_harmonic(self):
        ts = list(range(300))
        xs = [5 + 2 * math.sin(2 * math.pi * t / 50) - math.cos(2 * math.pi * t / 50) for t in ts]
        a, b, c, sse = cp.harmonic_fit(ts, xs, 50)
        self.assertAlmostEqual(a, 5, places=6)
        self.assertAlmostEqual(b, 2, places=6)
        self.assertAlmostEqual(c, -1, places=6)
        self.assertLess(sse, 1e-9)

    def test_fit_is_none_when_the_basis_is_singular(self):
        self.assertIsNone(cp.harmonic_fit([3] * 10, list(range(10)), 40))
        self.assertIsNone(cp.harmonic_fit([20 * k for k in range(10)], list(range(10)), 20))  # sin(wt) is always 0

    def test_seasonal_period_of_a_wave_and_of_noise(self):
        ts, xs = wave(600)
        found = cp.seasonal_period(ts, xs)
        self.assertAlmostEqual(found["period"], 100, delta=0.5)
        self.assertGreater(found["r2"], 0.9)
        rng = Random(2)
        flat = cp.seasonal_period(ts, [rng.gauss(0, 1) for _ in ts])
        self.assertIsNone(flat["period"])
        self.assertLess(flat["r2"], cp.SEASONAL_R2)

    def test_seasonal_period_refuses_short_constant_or_spanless_series(self):
        self.assertEqual(cp.seasonal_period(list(range(59)), [float(t % 7) for t in range(59)]), {"period": None, "r2": None})
        self.assertEqual(cp.seasonal_period(list(range(80)), [1.0] * 80), {"period": None, "r2": None})
        self.assertEqual(cp.seasonal_period([0] * 80, [float(k % 5) for k in range(80)]), {"period": None, "r2": None})
        self.assertEqual(cp.seasonal_period([1, 2], [1.0] * 3), {"period": None, "r2": None})

    def test_seasonal_period_skips_singular_periods(self):
        ts = [20 * k for k in range(60)]
        xs = [math.sin(2 * math.pi * t / 120) for t in ts]
        self.assertAlmostEqual(cp.seasonal_period(ts, xs)["period"], 120, delta=0.1)


class ChangePointTests(unittest.TestCase):
    def test_mean_shift_is_located(self):
        rng = Random(3)
        xs = [rng.gauss(0, 1) for _ in range(200)] + [rng.gauss(3, 1) for _ in range(150)]
        found = cp.change_point(xs)
        self.assertLessEqual(abs(found["index"] - 200), 3)
        self.assertTrue(found["clear"])
        self.assertGreater(found["statistic"], cp.CLEAR_STATISTIC)

    def test_variance_change_and_a_flat_segment(self):
        rng = Random(4)
        noisy = [rng.gauss(0, 1) for _ in range(200)] + [rng.gauss(0, 3) for _ in range(200)]
        self.assertLessEqual(abs(cp.change_point(noisy)["index"] - 200), 10)
        stuck = [rng.gauss(0, 1) for _ in range(100)] + [0.25] * 60
        self.assertEqual(cp.change_point(stuck)["index"], 100)

    def test_no_change_is_not_clear(self):
        rng = Random(5)
        found = cp.change_point([rng.gauss(0, 1) for _ in range(400)])
        self.assertFalse(found["clear"])
        self.assertGreaterEqual(found["statistic"], 0)

    def test_seasonal_series_with_per_segment_harmonics(self):
        ts, xs = wave(400, seed=6)
        stuck = xs[:250] + [xs[249]] * 150
        found = cp.change_point(stuck, times=ts, period=100)
        self.assertLessEqual(abs(found["index"] - 250), 1)
        self.assertTrue(found["clear"])
        shifted = xs[:200] + [x + 3.3 for x in xs[200:]]
        self.assertLessEqual(abs(cp.change_point(shifted, times=ts, period=100)["index"] - 200), 3)
        self.assertFalse(cp.change_point(xs, times=ts, period=100)["clear"])

    def test_a_seasonal_split_needs_matching_times(self):
        with self.assertRaises(ValueError):
            cp.change_point([1.0] * 30, period=100)
        with self.assertRaises(ValueError):
            cp.change_point([1.0] * 30, times=list(range(29)), period=100)

    def test_singular_fits_are_skipped(self):
        ts = [20 * k for k in range(30)]  # sin(2 pi t / 20) is always 0: every harmonic fit is singular
        self.assertIsNone(cp.change_point([float(k % 3) for k in range(30)], times=ts, period=20))
        ts = [0] * 12 + list(range(12, 40))  # the first segments are singular, later ones are not
        found = cp.change_point([0.0] * 20 + [5.0] * 20, times=ts, period=50)
        self.assertGreaterEqual(found["index"], 12)

    def test_constant_series_ties_to_the_earliest_split_and_short_series(self):
        self.assertEqual(cp.change_point([1.0] * 30), {"index": cp.MIN_SEGMENT, "statistic": 0.0, "clear": False})
        self.assertIsNone(cp.change_point([1.0] * (2 * cp.MIN_SEGMENT - 1)))
        self.assertEqual(cp.change_point([0.0] * 4 + [9.0] * 4, min_segment=2)["index"], 4)
