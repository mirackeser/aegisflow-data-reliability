# SPDX-License-Identifier: Apache-2.0
from datetime import datetime, timezone
import hashlib
import json
import unittest
from unittest import mock

from aegisflow_dr import baseline as bl
from aegisflow_dr import simulation as sim
from aegisflow_dr.pipeline import InputRejected

START = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)


def plant(seed=7):
    return sim.Plant(seed=seed, start=START)


def until_incident(p, limit):
    """Advance one check at a time; return the simulated seconds until the first incident (None within ``limit``)."""
    begin = p.now
    while p.now - begin < limit:
        p.advance(sim.CHECK_EVERY)
        if p.incidents:
            return p.now - begin
    return None


class PlantTests(unittest.TestCase):
    def test_deterministic_for_a_seed_and_start(self):
        first, second = plant(), plant()
        for p in (first, second):
            p.advance(40)
            p.inject("unit_change", "pressure_kpa")
            p.advance(100)
        self.assertEqual(json.dumps(first.snapshot()), json.dumps(second.snapshot()))
        self.assertEqual(first.export_window(200), second.export_window(200))
        self.assertNotEqual(plant(8).export_window(50), first.export_window(50))
        self.assertEqual(first.snapshot()["start"], "2026-11-26T09:00:00Z")

    def test_commissioning_baseline_and_snapshot_shape(self):
        p = plant()
        commissioning = sim.WINDOW_SECONDS * sim.REFERENCE_WINDOWS
        self.assertEqual((p.now, p.live_start, p.emitted, len(p.references)), (commissioning, commissioning, commissioning, 3))
        self.assertEqual(p.baseline, bl.build_baseline(p.references))
        snap = p.snapshot()
        self.assertTrue(snap["simulation"])
        self.assertEqual(len(snap["series"]["t"]), sim.CHART_READINGS)
        self.assertEqual(set(snap["series"]), {"t", *sim.SENSORS})
        self.assertEqual(snap["baseline"]["records"], commissioning)
        band = snap["baseline"]["bands"]["pressure_kpa"]
        self.assertAlmostEqual(band["high"] - band["low"], 6 * band["sd"], places=5)
        self.assertEqual(snap["current"]["t"], commissioning - 1)
        self.assertEqual((snap["elapsed_s"], snap["checks"], snap["last_check"]), (0, 0, None))
        self.assertLessEqual(abs(band["mean"] - 100), 0.3)
        p.advance(sim.CHECK_EVERY)
        self.assertEqual(p.snapshot()["last_check"]["records"], sim.WINDOW_SECONDS)

    def test_invalid_construction_and_arguments(self):
        for seed, start in ((1.5, START), (1, START.replace(tzinfo=None)), (1, "2026-01-01")):
            with self.assertRaises(ValueError):
                sim.Plant(seed=seed, start=start)
        p = plant()
        for bad in (-1, 1.0, "1"):
            with self.assertRaises(ValueError):
                p.advance(bad)
        for bad in (0, "3"):
            with self.assertRaises(ValueError):
                p.export_window(bad)

    def test_export_round_trip_through_compare(self):
        p = plant()
        p.advance(sim.WINDOW_SECONDS)
        payload = p.export_window(sim.WINDOW_SECONDS)
        self.assertEqual(payload.splitlines()[0], b"ts,temp_c,pressure_kpa,flow_lpm")
        result = bl.compare(p.baseline, payload, as_of=sim.timestamp(p.start, p.now - 1))
        self.assertEqual(result["status"], "NO_DRIFT", result["findings"])
        self.assertEqual(result["records"], sim.WINDOW_SECONDS)
        self.assertEqual(result["baseline_digest"], p.baseline["digest"])

    def test_clean_data_opens_no_incident_over_twenty_windows(self):
        for seed in (7, 11):
            p = plant(seed)
            p.advance(20 * sim.WINDOW_SECONDS)
            self.assertEqual(p.incidents, [], seed)
            self.assertEqual(p.detections, [])
            self.assertEqual(p.checks, 20 * sim.WINDOW_SECONDS // sim.CHECK_EVERY)


class FaultTests(unittest.TestCase):
    def test_each_sensor_fault_changes_only_its_sensor(self):
        clean = plant()
        clean.advance(60)
        for fault in sim.SENSOR_FAULTS:
            p = plant()
            p.advance(30)
            record = p.inject(fault, "pressure_kpa")
            p.advance(30)
            after = [r for r in p.readings if r["t"] >= record["started_t"]]
            reference = [r for r in clean.readings if r["t"] >= record["started_t"]]
            self.assertEqual(len(after), 30)
            for got, want in zip(after, reference):
                self.assertEqual((got["temp_c"], got["flow_lpm"], got["t"]), (want["temp_c"], want["flow_lpm"], want["t"]))
            pressure = [r["pressure_kpa"] for r in after]
            expected = [r["pressure_kpa"] for r in reference]
            if fault == "unit_change":
                self.assertEqual(pressure, [round(v * 10, 3) for v in expected])
            elif fault == "calibration_offset":
                self.assertEqual(record["offset"], round(1.5 * p.baseline["numeric"]["pressure_kpa"]["sd"], 6))
                self.assertEqual(pressure, [round(v + record["offset"], 3) for v in expected])
            elif fault == "stuck_sensor":
                self.assertEqual(set(pressure), {record["value"]})
            else:
                for got, want in zip(pressure, expected):
                    self.assertAlmostEqual(got - 100, 3 * (want - 100), delta=0.003)

    def test_stream_faults(self):
        p = plant()
        p.inject("sampling_slowdown")
        before = p.emitted
        p.advance(20)
        self.assertEqual(p.emitted - before, 10)
        gaps = {b["t"] - a["t"] for a, b in zip(p.readings[-10:], p.readings[-9:])}
        self.assertEqual(gaps, {2})
        p = plant()
        pause = p.inject("ingestion_pause")
        before = p.emitted
        p.advance(20)
        self.assertEqual(p.emitted, before)
        p.clear(pause["id"])
        p.advance(5)
        self.assertEqual(p.emitted, before + 5)
        p = plant()
        last = [dict(r) for r in p.readings[-30:]]
        burst = p.inject("duplicate_burst")
        self.assertEqual(p.readings[-30:], last)
        self.assertEqual(p.emitted, sim.WINDOW_SECONDS * 3 + 30)
        self.assertTrue(burst["one_shot"])
        self.assertEqual(burst["ended_t"], burst["started_t"])
        with self.assertRaises(KeyError):
            p.clear(burst["id"])

    def test_inject_and_clear_validation(self):
        p = plant()
        for fault, sensor in (("melt", "temp_c"), ("unit_change", None), ("unit_change", "humidity"),
                              ("ingestion_pause", "temp_c")):
            with self.assertRaises(InputRejected):
                p.inject(fault, sensor)
        first = p.inject("unit_change", "temp_c")
        with self.assertRaises(InputRejected):
            p.inject("unit_change", "temp_c")
        p.inject("unit_change", "flow_lpm")
        p.inject("stuck_sensor", "pressure_kpa")
        p.inject("sampling_slowdown")
        with self.assertRaises(InputRejected):
            p.inject("ingestion_pause")
        cleared = p.clear(first["id"])
        self.assertEqual(cleared["ended_t"], p.now)
        with self.assertRaises(KeyError):
            p.clear(first["id"])
        with self.assertRaises(KeyError):
            p.clear("F99")
        self.assertEqual(p.inject("unit_change", "temp_c")["id"], "F5")
        self.assertEqual([f["id"] for f in p.snapshot()["faults"]], ["F5", "F4", "F3", "F2", "F1"])

    def test_faults_history_is_bounded(self):
        p = plant()
        for _ in range(sim.MAX_FAULTS + 5):
            p.inject("duplicate_burst")
        self.assertEqual(len(p.faults), sim.MAX_FAULTS)
        self.assertLessEqual(len(p.readings), sim.MAX_READINGS)


class MonitorTests(unittest.TestCase):
    def test_detection_within_two_windows(self):
        for fault, sensor, expected in (("unit_change", "pressure_kpa", "distribution_shift"),
                                        ("calibration_offset", "pressure_kpa", "distribution_shift"),
                                        ("calibration_offset", "temp_c", "distribution_shift"),
                                        ("stuck_sensor", "flow_lpm", "flatline"), ("stuck_sensor", "temp_c", "flatline")):
            p = plant()
            p.advance(30)
            p.inject(fault, sensor)
            waited = until_incident(p, 2 * sim.WINDOW_SECONDS)
            self.assertIsNotNone(waited, fault)
            p.advance(2 * sim.WINDOW_SECONDS - waited)
            (incident,) = p.incidents
            self.assertEqual(incident["sensor"], sensor)
            self.assertIn(expected, incident["checks"], fault)
            marker = [d for d in p.detections if d["check"] == expected][0]
            self.assertEqual((marker["incident"], marker["column"]), (incident["id"], sensor))

    def test_unit_change_opens_a_high_incident_with_a_distribution_shift(self):
        p = plant()
        p.advance(30)
        p.inject("unit_change", "pressure_kpa")
        self.assertLessEqual(until_incident(p, 30), 15)
        incident = p.incidents[0]
        self.assertEqual((incident["severity"], incident["status"], incident["id"]), ("high", "open", "INC-0001"))
        p.advance(4 * sim.CHECK_EVERY)
        self.assertIn("distribution_shift", p.incidents[0]["checks"])
        payload, as_of = p.evidence("INC-0001")
        self.assertEqual(p.incidents[0]["window"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(as_of, p.incidents[0]["window"]["as_of"])
        self.assertEqual(bl.compare(p.baseline, payload, as_of=as_of)["status"], "DRIFT")

    def test_dedupe_while_finding_persists_and_close_after_two_clean_checks(self):
        p = plant()
        p.advance(30)
        fault = p.inject("unit_change", "pressure_kpa")
        p.advance(2 * sim.WINDOW_SECONDS)
        self.assertEqual(len(p.incidents), 1)
        keys = [(d["check"], d["column"]) for d in p.detections]
        self.assertEqual(p.snapshot()["detected"], len(keys))
        self.assertEqual(len(keys), len(set(keys)))
        p.clear(fault["id"])
        p.advance(3 * sim.WINDOW_SECONDS)
        (incident,) = p.incidents
        self.assertEqual(incident["status"], "closed")
        self.assertIsNotNone(incident["closed_at"])
        self.assertGreaterEqual(incident["clean_checks"], sim.CLOSE_AFTER)
        self.assertEqual(p.incident("INC-0001")["id"], "INC-0001")
        with self.assertRaises(KeyError):
            p.incident("INC-0009")

    def test_stream_incidents_and_an_empty_window(self):
        p = plant()
        p.inject("ingestion_pause")
        p.advance(sim.WINDOW_SECONDS + 2 * sim.CHECK_EVERY)
        (incident,) = p.incidents
        self.assertEqual((incident["sensor"], incident["severity"]), ("stream", "medium"))
        self.assertEqual(incident["checks"], ["freshness", "volume_change"])
        self.assertEqual(p.last_check["records"], 0)
        with self.assertRaises(KeyError):
            p.evidence(incident["id"])
        with self.assertRaises(KeyError):
            p.evidence("INC-0404")
        q = plant()
        q.inject("duplicate_burst")
        q.advance(sim.CHECK_EVERY)
        self.assertEqual(q.incidents[0]["checks"], ["duplicate_rows", "timestamp_duplicate"])
        self.assertEqual(q.incidents[0]["severity"], "low")

    def test_closed_incidents_are_bounded(self):
        p = plant()
        with mock.patch.object(sim, "MAX_INCIDENTS", 2):
            for _ in range(4):
                p.inject("duplicate_burst")
                p.advance(4 * sim.WINDOW_SECONDS)
        self.assertEqual(len(p.incidents), 2)
        last = int(p.incidents[-1]["id"][4:])
        self.assertEqual([i["id"] for i in p.incidents], ["INC-%04d" % (last - 1), "INC-%04d" % last])
        self.assertNotIn("INC-0001", p._evidence)


class PureTests(unittest.TestCase):
    def test_severity_rule(self):
        self.assertEqual([sim.severity(c) for c in ("distribution_shift", "level_shift", "role_change", "volume_change",
                                                    "freshness", "sampling_interval_change", "flatline", "duplicate_rows")],
                         ["high", "high", "high", "medium", "medium", "medium", "low", "low"])

    def test_findings_of_keeps_the_monitored_profile_checks(self):
        comparison = {"findings": [{"check": "volume_change", "column": None, "detail": {"current": 10}}]}
        profile = {"findings": [{"check": "outlier", "column": "temp_c", "count": 1, "records": [3]},
                                {"check": "flatline", "column": "temp_c", "count": 9, "records": list(range(9))}]}
        found = sim.findings_of(comparison, profile)
        self.assertEqual([(f["check"], f["severity"], f["source"]) for f in found],
                         [("volume_change", "medium", "baseline"), ("flatline", "low", "profile")])
        self.assertEqual(found[1]["detail"], {"count": 9, "records": [0, 1, 2, 3, 4]})

    def test_update_incidents_is_pure_and_groups_by_sensor(self):
        window = {"sha256": "a" * 64}
        level = {"check": "level_shift", "column": "temp_c", "severity": "high", "source": "profile", "detail": {}}
        flat = {"check": "flatline", "column": "temp_c", "severity": "low", "source": "profile", "detail": {}}
        dup = {"check": "duplicate_rows", "column": None, "severity": "low", "source": "profile", "detail": {}}
        first, detections, next_id = sim.update_incidents([], [flat], t=1, at="a", window=window, next_id=1)
        self.assertEqual((len(first), next_id, first[0]["severity"]), (1, 2, "low"))
        second, detections, next_id = sim.update_incidents(first, [flat, level, dup], t=2, at="b", window=window, next_id=next_id)
        self.assertEqual(len(first[0]["findings"]), 1)
        self.assertEqual([(i["id"], i["sensor"], i["severity"]) for i in second],
                         [("INC-0001", "temp_c", "high"), ("INC-0002", "stream", "low")])
        self.assertEqual([d["check"] for d in detections], ["level_shift", "duplicate_rows"])
        third, _, _ = sim.update_incidents(second, [dup], t=3, at="c", window=window, next_id=next_id)
        self.assertEqual((third[0]["status"], third[0]["clean_checks"]), ("open", 1))
        fourth, _, _ = sim.update_incidents(third, [], t=4, at="d", window=window, next_id=next_id)
        self.assertEqual([(i["status"], i["closed_t"]) for i in fourth], [("closed", 4), ("open", None)])
        fifth, _, after = sim.update_incidents(fourth, [level], t=5, at="e", window=window, next_id=next_id)
        self.assertEqual([i["id"] for i in fifth], ["INC-0001", "INC-0002", "INC-0003"])
        self.assertEqual((fifth[0]["status"], fifth[2]["status"], after), ("closed", "open", 4))
        self.assertEqual(sim.group_of("ts"), "stream")

    def test_clean_values_and_csv(self):
        values = sim.clean_values(25, (0.0, 0.0, 0.0))
        self.assertEqual(values, {"temp_c": 23.0, "pressure_kpa": 100.0, "flow_lpm": 5.0})
        self.assertEqual(sim.clean_values(0, (1.0, 1.0, 1.0), {"pressure_kpa": 3})["pressure_kpa"], 103.0)
        rows = [{"t": 0, "ts": "2026-01-01T00:00:00Z", "temp_c": 1, "pressure_kpa": 2, "flow_lpm": 3.25}]
        self.assertEqual(sim.to_csv(rows), b"ts,temp_c,pressure_kpa,flow_lpm\n2026-01-01T00:00:00Z,1.000,2.000,3.250\n")


if __name__ == "__main__":
    unittest.main()
