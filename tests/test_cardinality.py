# SPDX-License-Identifier: Apache-2.0
import unittest
from decimal import Decimal
from random import Random

from aegisflow_dr import cardinality as cd
from aegisflow_dr.pipeline import InputRejected

H = "order_id,customer_id,order_total\n"


def table(rows):
    return (H + "".join(f"{k},C,{v}\n" for k, v in rows)).encode()


class ProfileTests(unittest.TestCase):
    def test_multiplicity_and_extra_rows(self):
        report = cd.profile_keys(table([("A", "1.00"), ("A", "1.00"), ("A", "1.00"), ("B", "2.00"), ("B", "2.00"), ("C", "3.00"), ("", "1.00")]))
        self.assertEqual(report, {"rows": 7, "blank_keys": 1, "distinct_keys": 3, "repeated_keys": 2, "max_multiplicity": 3,
                                  "extra_rows": 3, "multiplicity": {"1": 1, "2": 1, "3": 1}})

    def test_unique_and_empty_tables(self):
        self.assertEqual(cd.profile_keys(table([("A", "1"), ("B", "2")]))["extra_rows"], 0)
        empty = cd.profile_keys(H.encode())
        self.assertEqual((empty["max_multiplicity"], empty["distinct_keys"], empty["multiplicity"]), (0, 0, {}))

    def test_missing_key_column_is_rejected(self):
        with self.assertRaises(InputRejected):
            cd.profile_keys(b"id,customer_id\nA,C\n")
        with self.assertRaises(InputRejected) as caught:
            cd.join_cardinality(table([("A", "1")]), b"id\nA\n")
        self.assertIn("second", str(caught.exception))
        with self.assertRaises(InputRejected) as caught:
            cd.join_cardinality(b"id\nA\n", table([("A", "1")]))
        self.assertIn("first", str(caught.exception))


class JoinTests(unittest.TestCase):
    def test_one_to_one_join_has_no_fan_out(self):
        report = cd.join_cardinality(table([("A", "10.00"), ("B", "5.00")]), table([("B", "5.00"), ("A", "10.00"), ("Z", "1.00")]))
        self.assertEqual((report["shared_keys"], report["join_rows"], report["extra_rows_from_join"], report["fan_out"]), (2, 2, 0, False))
        self.assertEqual(report["relationship"], {"one_to_one": 2, "one_to_many": 0, "many_to_one": 0, "many_to_many": 0})
        self.assertEqual(report["amount_inflation"]["first"], {"before": "15.00", "after_join": "15.00", "inflation": "0.00"})

    def test_each_relationship_and_exact_inflation(self):
        first = table([("OO", "1.00"), ("OM", "10.00"), ("MO", "5.00"), ("MO", "5.00"), ("MM", "2.00"), ("MM", "2.00")])
        second = table([("OO", "1.00"), ("OM", "10.00"), ("OM", "10.00"), ("OM", "10.00"), ("MO", "5.00"), ("MM", "2.00"), ("MM", "2.00"), ("MM", "2.00")])
        report = cd.join_cardinality(first, second)
        self.assertEqual(report["relationship"], {"one_to_one": 1, "one_to_many": 1, "many_to_one": 1, "many_to_many": 1})
        self.assertEqual((report["join_rows"], report["extra_rows_from_join"], report["fan_out"]), (1 + 3 + 2 + 6, 8, True))
        # first side: OO 1, OM 10 x3 = 30, MO 10 x1 = 10, MM 4 x3 = 12
        self.assertEqual(report["amount_inflation"]["first"], {"before": "25.00", "after_join": "53.00", "inflation": "28.00"})
        # second side: OO 1, OM 30 x1 = 30, MO 5 x2 = 10, MM 6 x2 = 12
        self.assertEqual(report["amount_inflation"]["second"], {"before": "42.00", "after_join": "53.00", "inflation": "11.00"})

    def test_invalid_amounts_are_not_counted_and_missing_amount_column_is_tolerated(self):
        report = cd.join_cardinality(table([("A", "abc"), ("A", "2.00")]), b"order_id,customer_id\nA,C\nA,C\n")
        self.assertEqual(report["amount_inflation"]["first"]["before"], "2.00")
        self.assertEqual(report["amount_inflation"]["first"]["after_join"], "4.00")
        self.assertEqual(report["amount_inflation"]["second"], {"before": "0.00", "after_join": "0.00", "inflation": "0.00"})

    def test_disjoint_sources(self):
        report = cd.join_cardinality(table([("A", "1.00")]), table([("B", "1.00")]))
        self.assertEqual((report["shared_keys"], report["join_rows"], report["fan_out"]), (0, 0, False))

    def test_blank_keys_never_join(self):
        report = cd.join_cardinality(table([("", "1.00")]), table([("", "1.00")]))
        self.assertEqual(report["join_rows"], 0)


class IndependentOracleTests(unittest.TestCase):
    """Compare with a deliberately naive nested-loop join so the closed-form figures are checked, not trusted."""

    @staticmethod
    def naive(left, right):
        rows, first_total, second_total = 0, Decimal(0), Decimal(0)
        for lk, lv in left:
            for rk, rv in right:
                if lk == rk:
                    rows += 1
                    first_total += Decimal(lv)
                    second_total += Decimal(rv)
        return rows, first_total, second_total

    def test_random_tables_match_a_nested_loop_join(self):
        for seed in range(80):
            rng = Random(seed)
            left = [(f"K{rng.randrange(12)}", f"{rng.randrange(100, 5000) / 100:.2f}") for _ in range(rng.randrange(1, 25))]
            right = [(f"K{rng.randrange(12)}", f"{rng.randrange(100, 5000) / 100:.2f}") for _ in range(rng.randrange(1, 25))]
            rows, first_after, second_after = self.naive(left, right)
            report = cd.join_cardinality(table(left), table(right))
            with self.subTest(seed=seed):
                self.assertEqual(report["join_rows"], rows)
                self.assertEqual(Decimal(report["amount_inflation"]["first"]["after_join"]), first_after)
                self.assertEqual(Decimal(report["amount_inflation"]["second"]["after_join"]), second_after)
                shared = {k for k, _ in left} & {k for k, _ in right}
                self.assertEqual(report["shared_keys"], len(shared))
                self.assertEqual(report["extra_rows_from_join"], rows - len(shared))


if __name__ == "__main__":
    unittest.main()
