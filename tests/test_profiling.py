# SPDX-License-Identifier: Apache-2.0
import hashlib
from random import Random
import unittest

from aegisflow_dr import profiling as pr
from aegisflow_dr.pipeline import InputRejected


def csv(header, rows):
    return ("\n".join([",".join(header)] + [",".join(str(c) for c in r) for r in rows]) + "\n").encode()


def checks(report):
    return {(f["check"], f["column"]): f for f in report["findings"]}


def series(n=60, noise=0.0, seed=1):
    rng = Random(seed)
    rows = []
    for i in range(n):
        rows.append(["2026-01-01T00:%02d:%02d" % (i // 60, i % 60), "%.3f" % (20 + i * 0.01 + rng.gauss(0, noise or 0.3))])
    return rows


class KindTests(unittest.TestCase):
    def test_kinds(self):
        cases = {"": "empty", "  ": "empty", "12": "integer", "-3": "integer", "+7": "integer", "1.5": "decimal", "-0.25": "decimal",
                 "abc": "text", "1e5": "text", "12.": "text", "NaN": "text", "inf": "text", "2026-01-01": "timestamp",
                 "2026-01-01T10:20": "timestamp", "2026-01-01 10:20:30.5": "timestamp", "2026-01-01T10:20:30Z": "timestamp",
                 "2026-01-01T10:20:30+03:00": "timestamp", "2026-13-01": "text", "2026-02-30": "text", "1" * 16: "text"}
        for value, kind in cases.items():
            self.assertEqual(pr.kind_of(value), kind, value)

    def test_parse_timestamp_awareness(self):
        self.assertIsNone(pr.parse_timestamp("2026-01-01T00:00:00").tzinfo)
        self.assertIsNotNone(pr.parse_timestamp("2026-01-01T00:00:00Z").tzinfo)
        self.assertIsNone(pr.parse_timestamp("yesterday"))
        self.assertIsNone(pr.parse_timestamp("2026-01-32"))


class ReadTableTests(unittest.TestCase):
    def test_rejections(self):
        bad = [None, "a,b\n1,2\n", b"x" * (pr.MAX_BYTES + 1), b"\xff\xfe", b"a,b\n1,\x00\n", b'a,b\n1,"2\n', b"", b"a,b\n",
               b"a,a\n1,2\n", b"a,\n1,2\n", b" ,b\n1,2\n", b"a,b\n1\n", b"a,b\n1,2,3\n",
               ("c%d" % 0).encode() + b"".join((",c%d" % i).encode() for i in range(1, pr.MAX_COLUMNS + 1)) + b"\n1\n"]
        for payload in bad:
            with self.assertRaises(InputRejected, msg=repr(payload)[:50]):
                pr.read_table(payload)

    def test_row_limit_is_inclusive(self):
        header, rows = pr.read_table(b"a\n" + b"1\n" * pr.MAX_ROWS)
        self.assertEqual((header, len(rows)), (["a"], pr.MAX_ROWS))
        with self.assertRaises(InputRejected):
            pr.read_table(b"a\n" + b"1\n" * (pr.MAX_ROWS + 1))

    def test_bom_blank_lines_and_quotes(self):
        header, rows = pr.read_table("﻿a, b\n1,\"x,y\"\n".encode())
        self.assertEqual((header, rows), (["a", "b"], [["1", "x,y"]]))


class ChecksTests(unittest.TestCase):
    def test_clean_series_has_no_findings(self):
        report = pr.profile_csv(csv(["ts", "v"], series()))
        self.assertEqual((report["status"], report["findings"], report["time_column"]), ("NO_FINDINGS", [], "ts"))
        self.assertEqual(report["source_sha256"], hashlib.sha256(csv(["ts", "v"], series())).hexdigest())
        self.assertEqual([c["role"] for c in report["columns"]], ["timestamp", "numeric"])
        self.assertEqual({k: report["columns"][1][k] for k in ("filled", "empty", "distinct")}, {"filled": 60, "empty": 0, "distinct": len({r[1] for r in series()})})

    def test_column_profile_numbers(self):
        report = pr.profile_csv(csv(["a"], [[1], [2], [3], [4]]))
        column = report["columns"][0]
        self.assertEqual((column["min"], column["max"], column["mean"], column["median"]), (1.0, 4.0, 2.5, 2.5))

    def test_empty_rate_and_boundary(self):
        rows = [[i, "" if i < 3 else 1.5 + i] for i in range(10)]
        found = checks(pr.profile_csv(csv(["i", "v"], rows)))[("empty_rate", "v")]
        self.assertEqual((found["count"], found["records"], found["detail"]["share"]), (3, [1, 2, 3], 0.3))
        exactly = [[i, "" if i < 2 else i] for i in range(10)]
        self.assertNotIn(("empty_rate", "v"), checks(pr.profile_csv(csv(["i", "v"], exactly))))

    def test_all_empty_column_has_role_empty(self):
        report = pr.profile_csv(csv(["a", "b"], [[1, ""], [2, ""]]))
        self.assertEqual(report["columns"][1]["role"], "empty")
        self.assertIn(("empty_rate", "b"), checks(report))

    def test_type_mismatch_numeric_and_timestamp(self):
        rows = series(40)
        rows[4][1] = "ERR"
        rows[9][0] = "not-a-time"
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))
        self.assertEqual(found[("type_mismatch", "v")]["records"], [5])
        self.assertEqual(found[("type_mismatch", "ts")]["records"], [10])
        self.assertEqual(found[("type_mismatch", "ts")]["detail"], {"expected": "timestamp"})

    def test_text_columns_are_not_type_checked(self):
        report = pr.profile_csv(csv(["name"], [["a"], ["b"], ["1"], ["c"], ["d"], ["e"], ["f"], ["g"], ["h"], ["i"]]))
        self.assertEqual(report["columns"][0]["role"], "text")
        self.assertNotIn("type_mismatch", {f["check"] for f in report["findings"]})

    def test_duplicate_rows(self):
        rows = [[1, "a"], [2, "b"], [1, "a"], [1, "a"], [3, "c"]]
        found = checks(pr.profile_csv(csv(["i", "s"], rows)))[("duplicate_rows", None)]
        self.assertEqual((found["records"], found["count"]), ([3, 4], 2))

    def test_constant_column(self):
        found = checks(pr.profile_csv(csv(["a", "b"], [[i, " x "] for i in range(8)])))
        self.assertEqual(found[("constant_column", "b")]["detail"], {"value": "x"})
        self.assertNotIn(("constant_column", "b"), checks(pr.profile_csv(csv(["a", "b"], [[i, "x"] for i in range(7)]))))

    def test_outlier_ordered_finds_spikes_and_ignores_edges(self):
        rows = series(100)
        rows[30][1] = "%.3f" % (float(rows[30][1]) + 9)
        rows[0][1] = "50.000"
        rows[99][1] = "50.000"
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))[("outlier", "v")]
        self.assertEqual((found["records"], found["detail"]["method"]), ([31], "second_difference"))

    def test_edge_spikes_are_never_blamed_on_a_neighbour(self):
        def flagged(index, delta):
            rows = series(100)
            rows[index][1] = "%.3f" % (float(rows[index][1]) + delta)
            found = checks(pr.profile_csv(csv(["ts", "v"], rows)))
            return found.get(("outlier", "v"), {"records": []})["records"]
        for delta in (9, -9):
            self.assertEqual(flagged(0, delta), [])
            self.assertEqual(flagged(99, delta), [])
            self.assertEqual(flagged(1, delta), [2])
            self.assertEqual(flagged(98, delta), [99])
            self.assertEqual(flagged(2, delta), [3])
            self.assertEqual(flagged(97, delta), [98])

    def shifted(self, first, delta, n=100):
        rows = series(n)
        for i in range(first, n):
            rows[i][1] = "%.3f" % (float(rows[i][1]) + delta)
        return checks(pr.profile_csv(csv(["ts", "v"], rows)))

    def test_level_shift_is_a_step_not_a_spike(self):
        for delta in (3, -3):
            found = self.shifted(50, delta)
            self.assertEqual(found[("level_shift", "v")]["records"], [51])
            self.assertAlmostEqual(found[("level_shift", "v")]["detail"]["shifts"][0], delta, delta=0.6)
            self.assertNotIn(("outlier", "v"), found)

    def test_level_shift_at_the_ends(self):
        self.assertEqual(self.shifted(1, 3)[("level_shift", "v")]["records"], [2])
        self.assertEqual(self.shifted(99, 3)[("level_shift", "v")]["records"], [100])

    def test_spike_is_not_a_level_shift(self):
        rows = series(100)
        rows[50][1] = "%.3f" % (float(rows[50][1]) + 3)
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))
        self.assertNotIn(("level_shift", "v"), found)
        self.assertEqual(found[("outlier", "v")]["records"], [51])

    def test_level_shift_needs_time_order_enough_values_and_a_scale(self):
        values = [[10 + (i % 5) * 0.1 + (5 if i >= 20 else 0)] for i in range(40)]
        self.assertNotIn("level_shift", {f["check"] for f in pr.profile_csv(csv(["v"], values))["findings"]})
        short = [[r[0], 5 if i >= 10 else 1] for i, r in enumerate(series(19))]
        self.assertNotIn("level_shift", {f["check"] for f in pr.profile_csv(csv(["ts", "v"], short))["findings"]})
        flat = [[r[0], 5.5 if i < 30 else 9.5] for i, r in enumerate(series(60))]
        self.assertNotIn("level_shift", {f["check"] for f in pr.profile_csv(csv(["ts", "v"], flat))["findings"]})

    def test_outlier_unordered_uses_the_median(self):
        values = [10 + (i % 5) * 0.1 for i in range(40)]
        values[7] = 99.0
        found = checks(pr.profile_csv(csv(["v"], [[v] for v in values])))[("outlier", "v")]
        self.assertEqual((found["records"], found["detail"]["method"]), ([8], "median"))

    def test_outlier_needs_enough_values_and_a_nonzero_scale(self):
        few = [[v] for v in ([1.0] * 18 + [900.0])]
        self.assertNotIn(("outlier", "v"), checks(pr.profile_csv(csv(["v"], few))))
        flat = [[5.5]] * 30 + [[900.5]]
        self.assertNotIn(("outlier", "v"), checks(pr.profile_csv(csv(["v"], flat))))

    def test_flatline(self):
        rows = series(80)
        for i in range(20, 31):
            rows[i][1] = rows[20][1]
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))[("flatline", "v")]
        self.assertEqual((found["records"], found["count"]), (list(range(21, 32)), 11))
        self.assertEqual(found["detail"]["runs"], [{"first": 21, "last": 31, "value": float(rows[20][1])}])

    def test_flatline_ignores_short_runs_discrete_signals_and_empty_breaks(self):
        short = series(80)
        for i in range(20, 27):
            short[i][1] = short[20][1]
        self.assertNotIn(("flatline", "v"), checks(pr.profile_csv(csv(["ts", "v"], short))))
        discrete = [[r[0], i % 2] for i, r in enumerate(series(80))]
        self.assertNotIn(("flatline", "v"), checks(pr.profile_csv(csv(["ts", "v"], discrete))))
        broken = series(80)
        for i in range(20, 32):
            broken[i][1] = broken[20][1]
        broken[26][1] = ""
        found = checks(pr.profile_csv(csv(["ts", "v"], broken)))
        self.assertNotIn(("flatline", "v"), found)

    def test_flatline_needs_a_time_column(self):
        values = [[1.0 + i * 0.01] for i in range(30)]
        for i in range(10, 20):
            values[i] = [5.0]
        self.assertNotIn("flatline", {f["check"] for f in pr.profile_csv(csv(["v"], values))["findings"]})

    def test_timestamp_duplicate_out_of_order_and_gap(self):
        rows = series(60)
        rows[10][0] = rows[9][0]
        rows[20][0] = "2026-01-01T00:00:15.500"
        del rows[40:45]
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))
        self.assertEqual(found[("timestamp_duplicate", "ts")]["records"], [11])
        self.assertEqual(found[("timestamp_out_of_order", "ts")]["records"], [21])
        gap = found[("timestamp_gap", "ts")]
        self.assertEqual((gap["records"], gap["detail"]["typical_seconds"], gap["detail"]["missing_intervals"]), ([41], 1.0, [5]))

    def test_gap_needs_enough_intervals(self):
        rows = series(8)
        del rows[4:6]
        self.assertNotIn(("timestamp_gap", "ts"), checks(pr.profile_csv(csv(["ts", "v"], rows))))

    def test_mixed_timezone_skips_ordering_checks(self):
        rows = series(30)
        rows[5][0] += "Z"
        rows[6][0] = rows[3][0]
        found = checks(pr.profile_csv(csv(["ts", "v"], rows)))
        self.assertEqual(found[("timestamp_mixed_timezone", "ts")]["count"], 29)
        self.assertEqual([k for k in found if k[0].startswith("timestamp")], [("timestamp_mixed_timezone", "ts")])

    def test_timezone_aware_series_is_ordered_normally(self):
        rows = [[r[0] + "+03:00", r[1]] for r in series(30)]
        self.assertEqual(pr.profile_csv(csv(["ts", "v"], rows))["findings"], [])

    def test_records_are_truncated_but_counted(self):
        rows = [[i, ""] for i in range(50)]
        found = checks(pr.profile_csv(csv(["i", "v"], rows)))[("empty_rate", "v")]
        self.assertEqual((found["count"], len(found["records"])), (50, pr.MAX_RECORDS_LISTED))

    def test_findings_are_ordered_by_check_then_column(self):
        rows = series(60)
        rows[3][1] = "ERR"
        rows[10][0] = rows[9][0]
        rows = [r + ["" if i % 2 else "1"] for i, r in enumerate(rows)]
        order = [(f["check"], f["column"]) for f in pr.profile_csv(csv(["ts", "v", "w"], rows))["findings"]]
        self.assertEqual(order, sorted(order, key=lambda k: (pr.CHECKS.index(k[0]), k[1] or "")))
        self.assertGreater(len(order), 2)

    def test_noise_only_data_rarely_raises_outliers(self):
        flagged = 0
        for seed in range(3):
            rng = Random(seed)
            rows = [["2026-01-01T%02d:%02d:%02d" % (i // 3600 % 24, i // 60 % 60, i % 60), "%.3f" % rng.gauss(0, 1), "%.3f" % rng.gauss(5, 2)]
                    for i in range(pr.MAX_ROWS)]
            found = checks(pr.profile_csv(csv(["ts", "a", "b"], rows)))
            flagged += sum(f["count"] for k, f in found.items() if k[0] == "outlier")
        self.assertLessEqual(flagged, 6)

    def test_profile_is_deterministic(self):
        payload = csv(["ts", "v"], series(50))
        self.assertEqual(pr.profile_csv(payload), pr.profile_csv(payload))


if __name__ == "__main__":
    unittest.main()
