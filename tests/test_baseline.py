# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import random
import unittest
from unittest import mock

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


def series(n=400, offset=0, step=60, shift=0.0, seed=1, columns=("v", "w", "tag"), blank_tag=0, ts=None):
    """ts, then seeded Gaussian ``v`` and ``w``, then text ``tag``; ``blank_tag`` empties that many tag cells."""
    rng = random.Random(seed)
    rows = [",".join(("ts",) + columns)]
    for i in range(offset, offset + n):
        cells = [ts(i) if ts else (START + timedelta(seconds=step * i)).isoformat()]
        for name in columns:
            if name == "v":
                cells.append("%.3f" % (rng.gauss(50, 5) + shift))
            elif name in ("w", "z"):
                cells.append("%.3f" % rng.gauss(10, 2))
            else:
                cells.append("" if i - offset < blank_tag else "t%d" % (i % 4))
        rows.append(",".join(cells))
    return ("\n".join(rows) + "\n").encode()


def base_record(**kw):
    return bl.build_baseline([series(seed=10 + k, offset=400 * k, **kw) for k in range(3)])


def keys(result):
    return [(f["check"], f["column"]) for f in result["findings"]]


def reasons(result):
    return {(n["check"], n["column"]): n["reason"] for n in result["not_evaluated"]}


class CompareTests(unittest.TestCase):
    def test_self_comparison_is_quiet(self):
        data = series()
        r = bl.build_baseline([data])
        out = bl.compare(r, data, as_of=(START + timedelta(seconds=60 * 400)).isoformat())
        self.assertEqual((out["status"], out["findings"]), ("NO_DRIFT", []))
        self.assertEqual(out["baseline_digest"], r["digest"])
        self.assertEqual(out["records"], 400)
        self.assertEqual(out["source_sha256"], r["references"][0]["sha256"])
        for entry in r["numeric"].values():
            self.assertEqual(bl.psi(entry["counts"], entry["counts"]), 0.0)
        self.assertEqual(set(out), {"format_version", "engine", "baseline_digest", "source_sha256", "records", "as_of",
                                    "measurements", "findings", "not_evaluated", "status"})
        m = out["measurements"]
        self.assertEqual(m["psi"], {"v": 0.0, "w": 0.0})
        self.assertEqual(m["sampling_interval"], {"baseline_seconds": 60, "current_seconds": 60})
        self.assertEqual(m["volume"], {"baseline_min": 400, "baseline_max": 400, "current": 400})
        self.assertEqual(m["freshness"]["lag_seconds"], 60)
        self.assertEqual(m["freshness"]["sla_seconds"], 180)
        self.assertEqual(m["bin_shares"]["v"]["baseline"], m["bin_shares"]["v"]["current"])

    def test_psi_listed_for_quiet_and_shifted_columns(self):
        out = bl.compare(base_record(), series(offset=1200, seed=99, shift=15.0))
        psi = out["measurements"]["psi"]
        self.assertEqual(set(psi), {"v", "w"})
        self.assertLessEqual(psi["w"], 0.25)
        self.assertEqual(psi["v"], out["findings"][0]["detail"]["psi"])
        self.assertEqual(out["measurements"]["freshness"], {"sla_seconds": 180, "latest": out["measurements"]["freshness"]["latest"],
                                                            "lag_seconds": None})

    def test_threshold_decided_on_unrounded_psi(self):
        r, data = base_record(), series(offset=1200, seed=99)
        with mock.patch.object(bl, "_psi_raw", return_value=0.2500001):
            out = bl.compare(r, data)
        self.assertEqual([k for k in keys(out) if k[0] == "distribution_shift"], [("distribution_shift", "v"), ("distribution_shift", "w")])
        self.assertEqual(out["findings"][0]["detail"]["psi"], 0.25)
        with mock.patch.object(bl, "_psi_raw", return_value=0.25):
            self.assertEqual(bl.compare(r, data)["findings"], [])

    def test_psi_hand_computed(self):
        b, c = [50.5 / 101, 50.5 / 101], [90.5 / 101, 10.5 / 101]
        expected = sum((y - x) * math.log(y / x) for x, y in zip(b, c))
        self.assertEqual(bl.psi([50, 50], [90, 10]), round(expected, 6))
        self.assertGreater(bl.psi([50, 50], [90, 10]), 0.5)

    def test_distribution_shift_found_and_detail(self):
        r = base_record()
        out = bl.compare(r, series(offset=1200, seed=99, shift=15.0), as_of=None)
        self.assertEqual(keys(out), [("distribution_shift", "v")])
        d = out["findings"][0]["detail"]
        self.assertGreater(d["psi"], 0.25)
        self.assertEqual(d["threshold"], 0.25)
        self.assertEqual(len(d["baseline_proportions"]), len(d["current_proportions"]))
        self.assertEqual(len(d["baseline_proportions"]), len(d["edges"]) + 1)
        self.assertAlmostEqual(sum(d["baseline_proportions"]), 1.0, places=5)
        self.assertAlmostEqual(sum(d["current_proportions"]), 1.0, places=5)
        self.assertGreater(d["current_mean"], d["baseline_mean"] + 10)
        self.assertEqual(out["status"], "DRIFT")
        json.dumps(out)

    def test_sampling_ratio_boundaries(self):
        r = base_record()
        for step, expect in ((90, False), (91, True), (40, False), (39, True)):
            out = bl.compare(r, series(step=step, seed=5))
            self.assertEqual(("sampling_interval_change", "ts") in keys(out), expect, step)
        d = bl.compare(r, series(step=91, seed=5))["findings"][0]["detail"]
        self.assertEqual(d, {"baseline_seconds": 60, "current_seconds": 91, "ratio": round(91 / 60, 4)})

    def test_volume_band(self):
        r = base_record()
        for n, direction in ((267, None), (266, "drop"), (600, None), (601, "increase")):
            out = bl.compare(r, series(n=n, seed=5))
            found = [f for f in out["findings"] if f["check"] == "volume_change"]
            self.assertEqual([f["detail"]["direction"] for f in found], [direction] if direction else [], n)
        d = found[0]["detail"]
        self.assertEqual((d["baseline_min"], d["baseline_max"], d["current"]), (400, 400, 601))
        self.assertIsNone(found[0]["column"])

    def test_freshness(self):
        r = base_record()
        data = series(seed=5)
        latest = START + timedelta(seconds=60 * 399)
        ok = bl.compare(r, data, as_of=(latest + timedelta(seconds=180)).isoformat())
        self.assertNotIn(("freshness", "ts"), keys(ok))
        late = bl.compare(r, data, as_of=(latest + timedelta(seconds=181)).isoformat())
        f = [x for x in late["findings"] if x["check"] == "freshness"][0]
        self.assertEqual(f["detail"], {"lag_seconds": 181, "sla_seconds": 180, "latest": latest.isoformat()})
        self.assertEqual(late["as_of"], (latest + timedelta(seconds=181)).isoformat())
        self.assertEqual(reasons(bl.compare(r, data))[("freshness", "ts")], "no_as_of")
        self.assertIsNone(bl.compare(r, data)["as_of"])
        self.assertEqual(reasons(bl.compare(r, data, as_of="2026-01-02T00:00:00Z"))[("freshness", "ts")], "timezone_mismatch")
        self.assertEqual(reasons(bl.compare(r, data, as_of=(latest - timedelta(seconds=1)).isoformat()))[("freshness", "ts")],
                         "as_of_before_latest_record")
        for bad in ("yesterday", 5, b"2026-01-01", ""):
            with self.assertRaises(InputRejected, msg=repr(bad)):
                bl.compare(r, data, as_of=bad)

    def test_freshness_with_aware_data_and_mixed_awareness(self):
        aware = [series(seed=10 + k, offset=400 * k, ts=lambda i: (START + timedelta(seconds=60 * i)).isoformat() + "Z")
                 for k in range(3)]
        r = bl.build_baseline(aware)
        data = series(seed=5, ts=lambda i: (START + timedelta(seconds=60 * i)).isoformat() + "Z")
        out = bl.compare(r, data, as_of="2026-01-01T07:00:00Z")
        self.assertEqual([f["check"] for f in out["findings"]], ["freshness"])
        self.assertEqual(reasons(bl.compare(r, data, as_of="2026-01-01T07:00:00"))[("freshness", "ts")], "timezone_mismatch")
        naive = series(seed=5)
        out = bl.compare(r, naive, as_of="2026-01-01T07:00:00Z")
        self.assertEqual(reasons(out)[("freshness", "ts")], "timezone_mismatch")
        self.assertEqual(reasons(out)[("sampling_interval_change", "ts")], "too_few_intervals")
        half = lambda i: (START + timedelta(seconds=60 * i)).isoformat() + ("Z" if i % 2 else "")
        out = bl.compare(r, series(seed=5, ts=half), as_of="2026-01-01T07:00:00Z")
        self.assertEqual(out["records"], 400)

    def test_empty_rate_change(self):
        r = base_record()
        self.assertEqual([k for k in keys(bl.compare(r, series(seed=5, blank_tag=40))) if k[0] == "empty_rate_change"], [])
        out = bl.compare(r, series(seed=5, blank_tag=44))
        self.assertEqual(keys(out), [("empty_rate_change", "tag")])
        self.assertEqual(out["findings"][0]["detail"], {"baseline": 0.0, "current": 0.11})

    def test_schema_changes(self):
        r = base_record()
        data = series(seed=5, columns=("v", "z", "tag"))
        rows = data.decode().splitlines()
        rows = [rows[0]] + [line.rsplit(",", 1)[0] + ",%d" % (j * 3) for j, line in enumerate(rows[1:])]
        out = bl.compare(r, ("\n".join(rows) + "\n").encode())
        self.assertEqual(keys(out), [("column_missing", "w"), ("column_added", "z"), ("role_change", "tag")])
        self.assertEqual(out["findings"][2]["detail"], {"baseline": "text", "current": "numeric"})
        self.assertNotIn(("distribution_shift", "w"), keys(out))
        self.assertEqual(reasons(out)[("distribution_shift", "tag")], "role_changed")
        order = [bl.CHECKS.index(f["check"]) for f in out["findings"]]
        self.assertEqual(order, sorted(order))

    def test_findings_sorted_by_check_then_column(self):
        r = base_record()
        out = bl.compare(r, series(n=700, seed=5, shift=20.0, step=120, blank_tag=300), as_of="2026-01-01T00:00:00")
        self.assertEqual(keys(out), [("sampling_interval_change", "ts"), ("volume_change", None), ("empty_rate_change", "tag"),
                                     ("distribution_shift", "v")])

    def test_not_evaluated_reasons(self):
        r = base_record()
        no_ts = b"v,w,tag\n" + b"\n".join(b"%d,%d,x" % (i, i) for i in range(400)) + b"\n"
        out = bl.compare(r, no_ts, as_of="2026-01-01T00:00:00")
        self.assertEqual(keys(out)[0], ("column_missing", "ts"))
        self.assertEqual(reasons(out)[("sampling_interval_change", "ts")], "no_time_column")
        self.assertEqual(reasons(out)[("freshness", "ts")], "no_time_column")
        few = bl.compare(r, series(n=30, seed=5))
        self.assertEqual(reasons(few)[("distribution_shift", "v")], "too_few_values")
        # constant column and short column in the baseline
        rows = ["ts,c,s"] + ["%s,5,%s" % ((START + timedelta(seconds=60 * i)).isoformat(), i if i < 49 else "") for i in range(120)]
        r2 = bl.build_baseline([("\n".join(rows) + "\n").encode()])
        out = bl.compare(r2, ("\n".join(rows) + "\n").encode())
        self.assertEqual(reasons(out), {("distribution_shift", "c"): "constant_in_baseline", ("freshness", "ts"): "no_as_of",
                                        ("distribution_shift", "s"): "too_few_values_in_baseline"})
        # baseline without time column
        plain = b"a,b\n" + b"\n".join(b"%d,%d" % (i, i * 2) for i in range(60)) + b"\n"
        r3 = bl.build_baseline([plain])
        out = bl.compare(r3, plain, as_of="2026-01-01T00:00:00")
        self.assertEqual(reasons(out), {("sampling_interval_change", None): "no_baseline_interval",
                                        ("freshness", None): "no_time_column"})
        self.assertEqual(out["status"], "NO_DRIFT")

    def test_no_sla_when_no_sampling_median(self):
        few = [series(n=5, seed=3)]
        r = bl.build_baseline(few)
        self.assertIsNone(r["freshness_sla_seconds"])
        out = bl.compare(r, series(n=5, seed=3), as_of="2026-01-02T00:00:00")
        self.assertEqual(reasons(out)[("freshness", "ts")], "no_sla")
        self.assertEqual(reasons(out)[("sampling_interval_change", "ts")], "no_baseline_interval")
        r = bl.build_baseline(few, freshness_sla_seconds=60)
        out = bl.compare(r, series(n=5, seed=3), as_of="2026-01-02T00:00:00")
        self.assertEqual(keys(out), [("freshness", "ts")])

    def test_time_column_role_change_treated_as_absent(self):
        r = base_record()
        rows = series(seed=5).decode().splitlines()
        text = [rows[0]] + ["id%d" % j + line[line.index(","):] for j, line in enumerate(rows[1:])]
        out = bl.compare(r, ("\n".join(text) + "\n").encode(), as_of="2026-01-01T00:00:00")
        self.assertIn(("role_change", "ts"), keys(out))
        self.assertEqual(reasons(out)[("freshness", "ts")], "no_time_column")
        self.assertEqual(reasons(out)[("sampling_interval_change", "ts")], "no_time_column")

    def test_tampered_baseline_rejected_before_reading_payload(self):
        r = base_record()
        bad = deepcopy(r)
        bad["numeric"]["v"]["counts"][0] += 1
        with self.assertRaises(InputRejected):
            bl.compare(bad, b"\xff\x00 not csv")
        with self.assertRaises(InputRejected):
            bl.compare(r, b"\xff\x00 not csv")
        with self.assertRaises(InputRejected):
            bl.compare(r, "text, not bytes")
        with self.assertRaises(InputRejected):
            bl.compare("nonsense", series())


if __name__ == "__main__":
    unittest.main()
