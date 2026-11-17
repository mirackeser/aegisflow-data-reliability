# SPDX-License-Identifier: Apache-2.0
import csv
import io
import unittest
from random import Random

from aegisflow_dr import consistency as cs
from aegisflow_dr.pipeline import InputRejected

H = "order_id,customer_id,order_total\n"


def csv_of(rows, header=H):
    return (header + "".join(r + "\n" for r in rows)).encode()


class CompareTests(unittest.TestCase):
    def test_agreeing_sources(self):
        a = csv_of(["A1,C1,10.00", "A2,C2,5"])
        report = cs.compare(a, a)
        self.assertEqual((report["matched"], report["identical"], report["differing"]), (2, 2, 0))
        self.assertEqual((report["only_in_first"], report["only_in_second"]), (0, 0))
        self.assertEqual(report["compared_columns"], ["customer_id", "order_total"])

    def test_numeric_amounts_ignore_formatting_but_not_value(self):
        report = cs.compare(csv_of(["A1,C1,10", "A2,C1,5.5"]), csv_of(["A1,C1,10.00", "A2,C1,5.51"]))
        self.assertEqual(report["differing"], 1)
        self.assertEqual(report["differing_by_column"], {"customer_id": 0, "order_total": 1})
        self.assertEqual(report["samples"]["differing"][0]["first"], {"order_total": "5.5"})
        self.assertEqual(report["samples"]["differing"][0]["second"], {"order_total": "5.51"})

    def test_text_comparison_for_invalid_amounts_and_customer_case(self):
        report = cs.compare(csv_of(["A1,c1,abc", "A2,C1,1"]), csv_of(["A1,C1,abc", "A2,C1,1"]))
        self.assertEqual(report["differing_by_column"]["customer_id"], 1)
        self.assertEqual(report["differing_by_column"]["order_total"], 0)
        one_invalid = cs.compare(csv_of(["A1,C1,abc"]), csv_of(["A1,C1,10.00"]))
        self.assertEqual(one_invalid["differing_by_column"]["order_total"], 1)

    def test_whitespace_is_trimmed_before_comparing(self):
        report = cs.compare(csv_of([" A1 ,C1, 10.00 "]), csv_of(["A1,C1,10.00"]))
        self.assertEqual((report["matched"], report["differing"]), (1, 0))

    def test_one_sided_records_are_counted_and_masked(self):
        report = cs.compare(csv_of(["ORDER-0001,C1,1", "ORDER-0002,C1,1"]), csv_of(["ORDER-0002,C1,1", "ORDER-0003,C1,1"]))
        self.assertEqual((report["only_in_first"], report["only_in_second"], report["matched"]), (1, 1, 1))
        self.assertEqual(report["samples"]["only_in_first"], ["OR•••01"])
        self.assertNotIn("ORDER-0001", str(report))

    def test_blank_and_repeated_identifiers_are_ambiguous_not_matched(self):
        report = cs.compare(csv_of(["A1,C1,1", "A1,C1,2", ",C1,1", "A2,C1,1"]), csv_of(["A1,C1,1", "A2,C1,1", ",C1,1"]))
        self.assertEqual((report["first"]["ambiguous_rows"], report["second"]["ambiguous_rows"]), (3, 1))
        self.assertEqual((report["matched"], report["identical"], report["only_in_first"], report["only_in_second"]), (1, 1, 0, 0))

    def test_missing_compare_columns_are_reported_not_guessed(self):
        report = cs.compare(csv_of(["A1,C1,1"]), b"order_id,order_total\nA1,1\n")
        self.assertEqual((report["compared_columns"], report["not_compared"]), (["order_total"], ["customer_id"]))

    def test_missing_key_or_invalid_input_is_rejected(self):
        good = csv_of(["A1,C1,1"])
        with self.assertRaises(InputRejected) as first:
            cs.compare(b"id,customer_id\nA1,C1\n", good)
        self.assertIn("first", str(first.exception))
        with self.assertRaises(InputRejected) as second:
            cs.compare(good, b"id,customer_id\nA1,C1\n")
        self.assertIn("second", str(second.exception))
        with self.assertRaises(InputRejected):
            cs.compare(b"", good)

    def test_samples_are_bounded_but_counts_are_exact(self):
        many = [f"K{i:04},C1,1" for i in range(50)]
        other = [f"K{i:04},C2,1" for i in range(50)]
        report = cs.compare(csv_of(many), csv_of(other))
        self.assertEqual(report["differing"], 50)
        self.assertEqual(len(report["samples"]["differing"]), cs.SAMPLE_LIMIT)
        report = cs.compare(csv_of(many), csv_of(["Z1,C1,1"]))
        self.assertEqual((report["only_in_first"], len(report["samples"]["only_in_first"])), (50, cs.SAMPLE_LIMIT))


class InjectedDifferenceTests(unittest.TestCase):
    """Differences are injected with known truth, so detection is measured, not assumed."""

    def test_random_pairs_recover_exactly_the_injected_differences(self):
        for seed in range(60):
            rng = Random(seed)
            base = [[f"S{seed}-{i:03}", f"C{rng.randrange(1, 9)}", f"{rng.randrange(100, 9999) / 100:.2f}"] for i in range(30)]
            left = [r[:] for r in base]
            right = [r[:] for r in base]
            picks = rng.sample(range(30), 9)
            expect_only_left, expect_only_right, expect_amount, expect_customer = picks[:2], picks[2:4], picks[4:6], picks[6:9]
            for i in expect_amount:
                right[i][2] = f"{float(right[i][2]) + 0.01:.2f}"
            for i in expect_customer:
                right[i][1] = right[i][1] + "x"
            for i in expect_only_left:
                right[i][0] = right[i][0] + "-r"
            for i in expect_only_right:
                left[i][0] = left[i][0] + "-l"
            right.reverse()  # order must not matter
            report = cs.compare(self.table(left), self.table(right))
            with self.subTest(seed=seed):
                self.assertEqual((report["only_in_first"], report["only_in_second"]), (4, 4))
                self.assertEqual(report["differing_by_column"], {"customer_id": 3, "order_total": 2})
                self.assertEqual(report["matched"], 26)  # 30 base ids minus the 4 whose id was altered
                self.assertEqual(report["identical"], 26 - 5)

    @staticmethod
    def table(rows):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["order_id", "customer_id", "order_total"])
        writer.writerows(rows)
        return stream.getvalue().encode()


if __name__ == "__main__":
    unittest.main()
