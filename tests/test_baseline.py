# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest

from aegisflow_dr import baseline as bl
from aegisflow_dr.pipeline import InputRejected

START = datetime(2026, 1, 1)


def reference(n=400, offset=0, suffix="", value=None, tag=None, ts=None):
    rows = ["ts,v,tag"]
    for i in range(offset, offset + n):
        stamp = ts(i) if ts else (START + timedelta(seconds=60 * i)).isoformat() + suffix
        rows.append("%s,%s,%s" % (stamp, (i * 7) % 100 if value is None else value(i), "t%d" % (i % 5) if tag is None else tag(i)))
    return ("\n".join(rows) + "\n").encode()


def references(count=3):
    return [reference(offset=400 * k) for k in range(count)]


def record():
    return bl.build_baseline(references())


def forge(rec, mutate):
    """Apply ``mutate`` to a copy and recompute the digest, so only the structural checks can reject it."""
    out = deepcopy(rec)
    mutate(out)
    out["digest"] = bl.canonical_digest(out)
    return out


class BuildBaselineTests(unittest.TestCase):
    def test_record_shape_and_digest(self):
        r = record()
        self.assertEqual(set(r), {"format_version", "engine", "columns", "time_column", "references", "volume", "sampling",
                                  "freshness_sla_seconds", "empty_share", "numeric", "digest"})
        self.assertEqual((r["format_version"], r["engine"]), ("1", "deterministic-baseline-v1"))
        self.assertEqual(r["columns"], [{"name": "ts", "role": "timestamp"}, {"name": "v", "role": "numeric"},
                                        {"name": "tag", "role": "text"}])
        self.assertEqual(r["time_column"], "ts")
        self.assertEqual(r["sampling"]["median_interval_seconds"], 60)
        self.assertEqual(r["freshness_sla_seconds"], 180)
        self.assertEqual(r["volume"], {"min_records": 400, "max_records": 400, "median_records": 400})
        self.assertEqual(r["digest"], bl.canonical_digest(r))
        self.assertNotIn("tag", r["numeric"])
        self.assertEqual(r["references"][1]["first"], (START + timedelta(seconds=60 * 400)).isoformat())
        self.assertEqual(r["references"][1]["last"], (START + timedelta(seconds=60 * 799)).isoformat())
        self.assertEqual(r["references"][0]["median_interval_seconds"], 60)
        self.assertEqual(r["empty_share"], {"ts": 0.0, "v": 0.0, "tag": 0.0})
        self.assertEqual(r["numeric"]["v"]["count"], 1200)

    def test_digest_ignores_digest_field_and_is_stable(self):
        r = record()
        self.assertEqual(bl.canonical_digest({**r, "digest": "other"}), r["digest"])
        self.assertEqual(r, record())

    def test_explicit_sla_wins(self):
        self.assertEqual(bl.build_baseline(references(), freshness_sla_seconds=900)["freshness_sla_seconds"], 900)
        for bad in (0, -5, True, 1.5, "60"):
            with self.assertRaises(InputRejected, msg=repr(bad)):
                bl.build_baseline(references(), freshness_sla_seconds=bad)

    def test_no_time_column_means_no_sla(self):
        data = b"a,b\n" + b"\n".join(b"%d,x" % i for i in range(30)) + b"\n"
        r = bl.build_baseline([data])
        self.assertIsNone(r["time_column"])
        self.assertIsNone(r["freshness_sla_seconds"])
        self.assertEqual(r["sampling"], {"median_interval_seconds": None})
        self.assertEqual(r["references"][0]["first"], None)
        self.assertEqual(bl.load_baseline(json.loads(json.dumps(r))), r)

    def test_reference_count_bounds(self):
        for bad in ([], references(1) * 6, tuple(references()), None, b"a,b\n1,2\n"):
            with self.assertRaises(InputRejected, msg=repr(bad)[:30]):
                bl.build_baseline(bad)
        self.assertEqual(len(bl.build_baseline(references(1) * 5)["references"]), 5)

    def test_bad_reference_payload_rejected(self):
        with self.assertRaises(InputRejected):
            bl.build_baseline(["a,b\n1,2\n"])

    def test_headers_must_match_in_name_and_order(self):
        with self.assertRaises(InputRejected):
            bl.build_baseline([b"a,b\n1,2\n", b"b,a\n1,2\n"])
        with self.assertRaises(InputRejected):
            bl.build_baseline([b"a,b\n1,2\n", b"a,c\n1,2\n"])

    def test_mixed_timezone_awareness_rejected(self):
        with self.assertRaisesRegex(InputRejected, "mixed timezone"):
            bl.build_baseline([reference(suffix="Z"), reference(offset=400)])
        with self.assertRaises(InputRejected):
            bl.build_baseline([reference(ts=lambda i: (START + timedelta(seconds=60 * i)).isoformat() + ("Z" if i % 2 else ""))])
        aware = bl.build_baseline([reference(suffix="Z"), reference(offset=400, suffix="+00:00")])
        self.assertEqual(aware["references"][0]["first"], "2026-01-01T00:00:00+00:00")

    def test_edges_counts_and_constant_column(self):
        r = bl.build_baseline([reference(n=100, value=lambda i: i + 1)])
        entry = r["numeric"]["v"]
        self.assertEqual(len(entry["edges"]), 9)
        self.assertTrue(all(a < b for a, b in zip(entry["edges"], entry["edges"][1:])))
        self.assertEqual(len(entry["counts"]), 10)
        self.assertEqual(sum(entry["counts"]), 100)
        self.assertEqual((entry["mean"], entry["median"], entry["count"]), (50.5, 50.5, 100))
        flat = bl.build_baseline([reference(n=60, value=lambda i: 3)])["numeric"]["v"]
        self.assertEqual((flat["edges"], flat["counts"], flat["sd"]), ([], [60], 0.0))
        few = bl.build_baseline([reference(n=49)])["numeric"]["v"]
        self.assertIsNone(few["edges"])
        self.assertIsNone(few["counts"])
        self.assertEqual(few["count"], 49)

    def test_empty_share_and_empty_column(self):
        data = reference(n=50, value=lambda i: "" if i < 10 else i, tag=lambda i: "")
        r = bl.build_baseline([data])
        self.assertEqual(r["empty_share"]["v"], 0.2)
        self.assertEqual(r["empty_share"]["tag"], 1.0)
        self.assertEqual(r["columns"][2]["role"], "empty")
        self.assertEqual(r["numeric"]["v"]["count"], 40)
        self.assertEqual(bl.load_baseline(json.loads(json.dumps(r))), r)

    def test_unparsable_timestamps_ignored_and_empty_time_reference(self):
        good = reference(n=100, ts=lambda i: "" if i < 20 else ("2026-13-45" if i == 30 else (START + timedelta(seconds=60 * i)).isoformat()))
        r = bl.build_baseline([good])
        self.assertEqual(r["references"][0]["first"], (START + timedelta(seconds=60 * 20)).isoformat())
        blank = bl.build_baseline([reference(), reference(n=60, ts=lambda i: "")])
        self.assertEqual(blank["time_column"], "ts")
        self.assertEqual(blank["references"][1], {**blank["references"][1], "first": None, "last": None, "median_interval_seconds": None})
        self.assertEqual(bl.load_baseline(json.loads(json.dumps(blank))), blank)

    def test_no_raw_values_stored(self):
        r = bl.build_baseline([reference(tag=lambda i: "SECRET-TAG-123")])
        self.assertNotIn("SECRET-TAG-123", json.dumps(r))

    def test_interval_median_needs_ten_gaps(self):
        stamps = [START + timedelta(seconds=30 * i) for i in range(11)]
        self.assertIsNone(bl.interval_median(stamps[:10]))
        self.assertEqual(bl.interval_median(stamps), 30)
        self.assertEqual(bl.interval_median(stamps + stamps[::-1]), 30)
        self.assertIsNone(bl.interval_median([]))
        uneven = [START + timedelta(seconds=s) for s in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 400)]
        self.assertEqual(bl.interval_median(uneven), 10)

    def test_bin_counts(self):
        self.assertEqual(bl.bin_counts([], [1.0, 2.0]), [2])
        self.assertEqual(bl.bin_counts([1.0, 2.0], [0.5, 1.0, 1.5, 2.0, 9.0]), [1, 2, 2])


class LoadBaselineTests(unittest.TestCase):
    def test_round_trip(self):
        r = record()
        loaded = bl.load_baseline(json.loads(json.dumps(r)))
        self.assertEqual(loaded, r)

    def test_every_single_field_edit_is_rejected(self):
        r = record()
        for key in r:
            if key != "digest":
                edited = deepcopy(r)
                edited[key] = "tampered"
                with self.assertRaises(InputRejected, msg=key):
                    bl.load_baseline(edited)
        digest_only = {
            "volume": lambda x: x["volume"].update(max_records=401),
            "sampling": lambda x: x["sampling"].update(median_interval_seconds=61),
            "freshness_sla_seconds": lambda x: x.update(freshness_sla_seconds=181),
            "empty_share": lambda x: x["empty_share"].update(tag=0.5),
            "edge": lambda x: x["numeric"]["v"]["edges"].__setitem__(0, x["numeric"]["v"]["edges"][0] - 1),
            "count": lambda x: (x["numeric"]["v"]["counts"].__setitem__(0, x["numeric"]["v"]["counts"][0] - 1),
                                x["numeric"]["v"]["counts"].__setitem__(1, x["numeric"]["v"]["counts"][1] + 1)),
            "sha": lambda x: x["references"][0].update(sha256="0" * 64),
            "mean": lambda x: x["numeric"]["v"].update(mean=1.0),
        }
        for name, edit in digest_only.items():
            edited = deepcopy(r)
            edit(edited)
            with self.assertRaisesRegex(InputRejected, "digest", msg=name):
                bl.load_baseline(edited)
            bl.load_baseline(forge(r, edit))

    def test_digest_recomputed_after_valid_edit_still_checks_bounds(self):
        r = record()
        edges = r["numeric"]["v"]["edges"]
        with self.assertRaises(InputRejected):
            bl.load_baseline(forge(r, lambda x: x["numeric"]["v"].update(edges=list(reversed(edges)))))

    def test_wrong_types_rejected(self):
        r = record()
        for bad in (None, [], "x", 3, {}):
            with self.assertRaises(InputRejected):
                bl.load_baseline(bad)
        extra = deepcopy(r)
        extra["extra"] = 1
        missing = deepcopy(r)
        del missing["volume"]
        for bad in (extra, missing):
            with self.assertRaises(InputRejected):
                bl.load_baseline(bad)

    def test_huge_integers_rejected_not_overflow(self):
        r = record()
        huge = 10 ** 400
        edits = {
            "median_records": lambda x: x["volume"].update(median_records=huge),
            "edge": lambda x: x["numeric"]["v"]["edges"].__setitem__(0, huge),
            "mean": lambda x: x["numeric"]["v"].update(mean=huge),
            "empty_share": lambda x: x["empty_share"].update(tag=huge),
            "negative": lambda x: x["numeric"]["v"].update(median=-huge),
        }
        for name, edit in edits.items():
            with self.assertRaises(InputRejected, msg=name):
                bl.load_baseline(forge(r, edit))

    def test_forged_structures_rejected(self):
        r = record()
        v = lambda x: x["numeric"]["v"]
        cases = {
            "version": lambda x: x.update(format_version=1),
            "engine": lambda x: x.update(engine="other"),
            "columns_not_list": lambda x: x.update(columns={}),
            "columns_empty": lambda x: x.update(columns=[]),
            "columns_41": lambda x: x.update(columns=[{"name": "c%d" % i, "role": "text"} for i in range(41)], numeric={},
                                             time_column=None, empty_share={"c%d" % i: 0.0 for i in range(41)}),
            "column_extra_key": lambda x: x["columns"][0].update(x=1),
            "column_not_dict": lambda x: x["columns"].__setitem__(0, "ts"),
            "column_role": lambda x: x["columns"][2].update(role="weird"),
            "column_name_type": lambda x: x["columns"][2].update(name=3),
            "column_name_empty": lambda x: x["columns"][2].update(name=""),
            "column_duplicate": lambda x: x["columns"][2].update(name="v"),
            "time_column_wrong": lambda x: x.update(time_column="tag"),
            "time_column_none": lambda x: x.update(time_column=None),
            "refs_empty": lambda x: x.update(references=[]),
            "refs_six": lambda x: x.update(references=x["references"] * 2),
            "ref_not_dict": lambda x: x["references"].__setitem__(0, 1),
            "ref_extra": lambda x: x["references"][0].update(x=1),
            "sha_upper": lambda x: x["references"][0].update(sha256="A" * 64),
            "sha_short": lambda x: x["references"][0].update(sha256="a" * 63),
            "sha_type": lambda x: x["references"][0].update(sha256=None),
            "records_bool": lambda x: x["references"][0].update(records=True),
            "records_zero": lambda x: x["references"][0].update(records=0),
            "first_only": lambda x: x["references"][0].update(first=None),
            "first_bad": lambda x: x["references"][0].update(first="yesterday"),
            "first_type": lambda x: x["references"][0].update(first=5),
            "interval_zero": lambda x: x["references"][0].update(median_interval_seconds=0),
            "interval_str": lambda x: x["references"][0].update(median_interval_seconds="60"),
            "interval_nan": lambda x: x["references"][0].update(median_interval_seconds=float("nan")),
            "volume_keys": lambda x: x["volume"].pop("min_records"),
            "volume_not_dict": lambda x: x.update(volume=[]),
            "volume_bool": lambda x: x["volume"].update(min_records=True),
            "volume_order": lambda x: x["volume"].update(min_records=500),
            "volume_median": lambda x: x["volume"].update(median_records="400"),
            "sampling_keys": lambda x: x["sampling"].update(x=1),
            "sampling_neg": lambda x: x["sampling"].update(median_interval_seconds=-1),
            "sla_bool": lambda x: x.update(freshness_sla_seconds=True),
            "sla_float": lambda x: x.update(freshness_sla_seconds=1.5),
            "sla_zero": lambda x: x.update(freshness_sla_seconds=0),
            "empty_keys": lambda x: x["empty_share"].pop("tag"),
            "empty_range": lambda x: x["empty_share"].update(tag=1.5),
            "empty_type": lambda x: x["empty_share"].update(tag="0"),
            "numeric_keys": lambda x: x["numeric"].update(tag=v(x)),
            "numeric_entry_keys": lambda x: v(x).pop("sd"),
            "numeric_entry_type": lambda x: x["numeric"].update(v=[]),
            "count_bool": lambda x: v(x).update(count=True),
            "count_zero": lambda x: v(x).update(count=0),
            "mean_nan": lambda x: v(x).update(mean=float("nan")),
            "mean_str": lambda x: v(x).update(mean="1"),
            "sd_negative": lambda x: v(x).update(sd=-1.0),
            "median_inf": lambda x: v(x).update(median=float("inf")),
            "edges_none_but_enough": lambda x: v(x).update(edges=None, counts=None),
            "edges_only_none": lambda x: v(x).update(edges=None),
            "edges_present_but_few": lambda x: v(x).update(count=10, counts=[1] * 10),
            "edges_not_list": lambda x: v(x).update(edges="x"),
            "edges_ten": lambda x: v(x).update(edges=list(range(10)), counts=[120] * 10 + [0]),
            "edges_equal": lambda x: v(x).update(edges=[1.0, 1.0]),
            "edges_nan": lambda x: v(x).update(edges=[float("nan")] + v(x)["edges"][1:]),
            "edges_bool": lambda x: v(x).update(edges=[True] + v(x)["edges"][1:]),
            "counts_not_list": lambda x: v(x).update(counts="x"),
            "counts_short": lambda x: v(x).update(counts=v(x)["counts"][:-1]),
            "counts_negative": lambda x: v(x).update(counts=[-1] + v(x)["counts"][1:]),
            "counts_bool": lambda x: v(x).update(counts=[True] + v(x)["counts"][1:]),
            "counts_float": lambda x: v(x).update(counts=[float(c) for c in v(x)["counts"]]),
            "counts_sum": lambda x: v(x).update(counts=[c + 1 for c in v(x)["counts"]]),
            "constant_counts": lambda x: v(x).update(edges=[], counts=[1199]),
            "digest_type": lambda x: x.update(digest=5),
        }
        for name, edit in cases.items():
            with self.assertRaises(InputRejected, msg=name):
                bl.load_baseline(forge(r, edit) if name != "digest_type" else {**r, "digest": 5})
        constant = bl.build_baseline([reference(n=60, value=lambda i: 3)])
        self.assertEqual(bl.load_baseline(json.loads(json.dumps(constant))), constant)
        self.assertEqual(bl.load_baseline(forge(constant, lambda x: None)), forge(constant, lambda x: None))


if __name__ == "__main__":
    unittest.main()
