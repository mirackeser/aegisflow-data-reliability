# SPDX-License-Identifier: Apache-2.0
"""Change-onset estimation for monitored series: seasonal adjustment and a single mean/variance change point.

Deterministic and dependency-free. Thresholds are fixed in the design (docs/superpowers/specs/
2026-11-28-incident-investigation-design.md) from development data only:

* A series is *seasonal* when a single harmonic explains at least ``SEASONAL_R2`` of its variance. The period is
  searched on a 1 s grid from ``MIN_PERIOD`` to ``MAX_PERIOD`` and refined to ``PERIOD_STEP``.
* The change point is the maximum-likelihood split of a Gaussian series into two segments, each with its own mean,
  variance and (for a seasonal series) its own harmonic. Its statistic is twice the log-likelihood ratio against one
  segment; an estimate is *clear* at or above ``CLEAR_STATISTIC``. On clean development data (seeds 1-10, 90 windows
  of 400 s per sensor) the largest value was 17 for the non-seasonal sensors and 26 for the seasonal one.

An estimate says *when* the series changed, never *why*.
"""
import math

MIN_PERIOD, MAX_PERIOD, PERIOD_STEP, REFINE_SPAN = 20, 200, 0.05, 1.0
SEASONAL_R2 = 0.5
MIN_SEGMENT = 10
CLEAR_STATISTIC = 30.0
# Readings carry three decimals; the variance of a rounding error of 0.001 is the floor of any segment variance.
VARIANCE_FLOOR = 0.001 ** 2 / 12


def _solve3(m, v):
    """Solve the 3x3 system ``m x = v`` by Gaussian elimination with partial pivoting; None when singular."""
    a = [row[:] + [rhs] for row, rhs in zip(m, v)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, 3):
            factor = a[row][col] / a[col][col]
            a[row] = [x - factor * y for x, y in zip(a[row], a[col])]
    solution = [0.0, 0.0, 0.0]
    for row in (2, 1, 0):
        solution[row] = (a[row][3] - sum(a[row][k] * solution[k] for k in range(row + 1, 3))) / a[row][row]
    return solution


def harmonic_fit(ts, xs, period):
    """Least squares of ``x = a + b sin(wt) + c cos(wt)`` with ``w = 2 pi / period``; returns (a, b, c, sse) or None."""
    w = 2 * math.pi / period
    basis = [(1.0, math.sin(w * t), math.cos(w * t)) for t in ts]
    gram = [[sum(f[i] * f[j] for f in basis) for j in range(3)] for i in range(3)]
    moment = [sum(f[i] * x for f, x in zip(basis, xs)) for i in range(3)]
    coefficients = _solve3(gram, moment)
    if coefficients is None:
        return None
    a, b, c = coefficients
    sse = sum((x - a - b * f[1] - c * f[2]) ** 2 for f, x in zip(basis, xs))
    return a, b, c, sse


def seasonal_period(ts, xs):
    """``{"period": seconds or None, "r2": share explained}`` of the best single harmonic of the series.

    ``period`` is None (not seasonal) when the series is too short for three cycles of ``MIN_PERIOD``, is constant, or
    the best harmonic explains less than ``SEASONAL_R2`` of the variance.
    """
    if len(xs) != len(ts) or len(xs) < 3 * MIN_PERIOD:
        return {"period": None, "r2": None}
    mean = sum(xs) / len(xs)
    total = sum((x - mean) ** 2 for x in xs)
    if total == 0:
        return {"period": None, "r2": None}
    longest = min(MAX_PERIOD, (ts[-1] - ts[0]) / 3)

    def sse(period):
        fit = harmonic_fit(ts, xs, period)
        return math.inf if fit is None else fit[3]

    coarse = min(range(MIN_PERIOD, int(longest) + 1), key=sse, default=None)
    if coarse is None:
        return {"period": None, "r2": None}
    steps = int(round(REFINE_SPAN / PERIOD_STEP))
    best = min((round(coarse + k * PERIOD_STEP, 6) for k in range(-steps, steps + 1)), key=sse)
    r2 = 1 - sse(best) / total
    return {"period": best if r2 >= SEASONAL_R2 else None, "r2": round(r2, 6)}


def _features(times, period):
    """Regression features per reading: the mean only, or the mean and one harmonic of ``period``."""
    if period is None:
        return [(1.0,) for _ in times]
    w = 2 * math.pi / period
    return [(1.0, math.sin(w * t), math.cos(w * t)) for t in times]


def _residual(gram, moment, square):
    """Residual sum of squares of a least-squares fit from its sufficient statistics; None when singular."""
    if len(moment) == 1:
        return square - moment[0] * moment[0] / gram[0][0]
    solution = _solve3(gram, moment)
    return None if solution is None else square - sum(b * m for b, m in zip(solution, moment))


def change_point(xs, *, times=None, period=None, min_segment=MIN_SEGMENT):
    """``{"index", "statistic", "clear"}`` of the best two-segment split, or None below two minimum segments.

    Each segment has its own mean and variance and, when ``period`` is given (with ``times``), its own harmonic of
    that period, so a seasonal sensor that freezes, shifts, scales or gets noisier is modelled without assuming the
    wave continues unchanged. ``index`` is the first value of the second segment. Ties go to the earliest split, and
    splits whose fit is singular are skipped.
    """
    n = len(xs)
    if period is not None and (times is None or len(times) != n):
        raise ValueError("A seasonal change point needs one time per value")
    if n < 2 * min_segment:
        return None
    features = _features(times if period is not None else range(n), period)
    p = len(features[0])
    grams, moments, squares = [[[0.0] * p for _ in range(p)]], [[0.0] * p], [0.0]
    for f, x in zip(features, xs):
        grams.append([[grams[-1][i][j] + f[i] * f[j] for j in range(p)] for i in range(p)])
        moments.append([moments[-1][i] + f[i] * x for i in range(p)])
        squares.append(squares[-1] + x * x)

    def cost(a, b):
        gram = [[grams[b][i][j] - grams[a][i][j] for j in range(p)] for i in range(p)]
        sse = _residual(gram, [moments[b][i] - moments[a][i] for i in range(p)], squares[b] - squares[a])
        return None if sse is None else (b - a) * math.log(max(sse / (b - a), VARIANCE_FLOOR))

    whole = cost(0, n)
    best = None
    for k in range(min_segment, n - min_segment + 1):
        left, right = cost(0, k), cost(k, n)
        if left is not None and right is not None and (best is None or left + right < best[1]):
            best = (k, left + right)
    if whole is None or best is None:
        return None
    statistic = round(max(0.0, whole - best[1]), 6)
    return {"index": best[0], "statistic": statistic, "clear": statistic >= CLEAR_STATISTIC}
