# SPDX-License-Identifier: Apache-2.0
"""Deterministic simulated plant, fault injectors and live monitor for the Command Center.

This is a **simulation**, labelled as such wherever it is shown: three generated sensor series, not real sensors.
Every number it reports is computed here or by the existing deterministic checks; nothing is estimated or invented.

* Readings every simulated second ``t``: ``temp_c = 20 + 3 sin(2 pi t / 100) + N(0, 0.5)``,
  ``pressure_kpa = N(100, 1)`` and ``flow_lpm = N(5, 1)``, drawn from one seeded generator in a fixed order, so a seed
  and a start time give the same plant every time. Time is injected: the package never reads a wall clock.
* On ``reset`` the plant records a clean commissioning period of ``REFERENCE_WINDOWS`` windows (three windows of
  ``WINDOW_SECONDS`` readings) and builds its baseline from them with ``baseline.build_baseline``.
* Every ``CHECK_EVERY`` simulated seconds the monitor takes the readings of the last ``WINDOW_SECONDS`` simulated
  seconds, compares them with the baseline (``baseline.compare``) and profiles them (``profiling.profile_csv``). New
  findings open an incident; findings on a sensor that already has an open incident are added to it (no duplicate
  incident while a finding persists); an incident closes after ``CLOSE_AFTER`` consecutive checks without findings on
  its sensor.

The window is time-based (not a fixed number of readings) so that volume and sampling changes are visible, and it is
200 s long, not 120: ``baseline.compare`` evaluates a distribution only with at least ``baseline.MIN_VALUES`` (150)
values, and 200 s covers exactly two temperature cycles, so a clean window has the same distribution as the baseline.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import math
from random import Random

from . import baseline as baseline_checks
from .pipeline import InputRejected
from .profiling import profile_csv

SENSORS = ("temp_c", "pressure_kpa", "flow_lpm")
HEADER = ("ts",) + SENSORS
UNITS = {"temp_c": "°C", "pressure_kpa": "kPa", "flow_lpm": "L/min"}
PERIOD, TEMP_MEAN, TEMP_AMPLITUDE = 100, 20.0, 3.0
NOISE_SD = {"temp_c": 0.5, "pressure_kpa": 1.0, "flow_lpm": 1.0}
LEVEL = {"pressure_kpa": 100.0, "flow_lpm": 5.0}
WINDOW_SECONDS, REFERENCE_WINDOWS, CHECK_EVERY, CLOSE_AFTER = 200, 3, 15, 2
MAX_READINGS, CHART_READINGS = 1200, 300
MAX_INCIDENTS, MAX_FAULTS, MAX_DETECTIONS, MAX_ACTIVE_FAULTS = 50, 30, 100, 4
OFFSET_SD, UNIT_FACTOR, NOISE_FACTOR, SLOW_EVERY, DUPLICATE_BURST = 1.5, 10, 3, 2, 30
SENSOR_FAULTS = ("calibration_offset", "unit_change", "stuck_sensor", "noise_increase")
STREAM_FAULTS = ("sampling_slowdown", "ingestion_pause", "duplicate_burst")
FAULTS = SENSOR_FAULTS + STREAM_FAULTS
# Profile findings the monitor reports; the others (single outliers, gaps after a pause) would only repeat these.
PROFILE_CHECKS = ("level_shift", "flatline", "constant_column", "duplicate_rows", "timestamp_duplicate")
HIGH = ("distribution_shift", "level_shift", "role_change", "column_missing", "column_added")
MEDIUM = ("sampling_interval_change", "volume_change", "freshness")
SEVERITIES = ("low", "medium", "high")
STREAM = "stream"


def severity(check):
    """Fixed rule: distribution, level shift and unit/role changes are high; sampling, volume, freshness medium."""
    return "high" if check in HIGH else "medium" if check in MEDIUM else "low"


def timestamp(start, t):
    return (start + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_csv(rows):
    """CSV bytes of reading rows (``ts`` then the sensors, three decimals)."""
    lines = [",".join(HEADER)] + ["%s,%.3f,%.3f,%.3f" % (r["ts"], r["temp_c"], r["pressure_kpa"], r["flow_lpm"])
                                  for r in rows]
    return ("\n".join(lines) + "\n").encode()


def clean_values(t, noise, factor=None):
    """The undisturbed reading at second ``t`` from its three standard-normal draws; ``factor`` scales a sensor's noise."""
    factor = factor or {}
    wave = TEMP_MEAN + TEMP_AMPLITUDE * math.sin(2 * math.pi * t / PERIOD)
    base = {"temp_c": wave, "pressure_kpa": LEVEL["pressure_kpa"], "flow_lpm": LEVEL["flow_lpm"]}
    return {s: round(base[s] + n * NOISE_SD[s] * factor.get(s, 1), 3) for s, n in zip(SENSORS, noise)}


def group_of(column):
    """The incident a finding belongs to: its sensor, or the stream for whole-table and timestamp findings."""
    return column if column in SENSORS else STREAM


def findings_of(comparison, profile):
    """The monitor's findings from one comparison and one profile, each with its severity and a short detail."""
    found = [{"check": f["check"], "column": f["column"], "source": "baseline", "detail": f["detail"]}
             for f in comparison["findings"]]
    found += [{"check": f["check"], "column": f["column"], "source": "profile",
               "detail": {"count": f["count"], "records": f["records"][:5]}}
              for f in profile["findings"] if f["check"] in PROFILE_CHECKS]
    for item in found:
        item["severity"] = severity(item["check"])
    return found


def update_incidents(incidents, findings, *, t, at, window, next_id):
    """Apply one check's findings to the incidents; returns (incidents, new detections, next id). Inputs are unchanged.

    ``window`` describes the checked window (digest, bounds, records, as_of); it becomes the evidence window of every
    incident that has findings in it.
    """
    incidents = [dict(item, findings=list(item["findings"])) for item in incidents]
    detections, groups = [], {}
    for finding in findings:
        groups.setdefault(group_of(finding["column"]), []).append(finding)
    for item in incidents:
        if item["status"] == "open" and item["sensor"] not in groups:
            item["clean_checks"] += 1
            if item["clean_checks"] >= CLOSE_AFTER:
                item.update(status="closed", closed_t=t, closed_at=at)
    for group, items in groups.items():
        incident = next((i for i in incidents if i["status"] == "open" and i["sensor"] == group), None)
        if incident is None:
            incident = {"id": "INC-%04d" % next_id, "sensor": group, "status": "open", "opened_t": t, "opened_at": at,
                        "closed_t": None, "closed_at": None, "clean_checks": 0, "findings": [], "run_id": None}
            next_id += 1
            incidents.append(incident)
        incident["clean_checks"], incident["window"] = 0, dict(window)
        known = {(f["check"], f["column"]) for f in incident["findings"]}
        for finding in items:
            key = (finding["check"], finding["column"])
            if key in known:
                continue
            known.add(key)
            incident["findings"].append({**finding, "first_t": t, "first_at": at})
            detections.append({"t": t, "at": at, "check": finding["check"], "column": finding["column"],
                               "severity": finding["severity"], "incident": incident["id"]})
        incident["checks"] = sorted({f["check"] for f in incident["findings"]})
        incident["severity"] = max((f["severity"] for f in incident["findings"]), key=SEVERITIES.index)
    return incidents, detections, next_id


class Plant:
    """The simulated plant: readings, faults, baseline and monitor state. Not thread-safe; callers hold a lock."""

    def __init__(self, *, seed, start):
        if type(seed) is not int or type(start) is not datetime or start.tzinfo is None:
            raise ValueError("A plant needs an integer seed and a timezone-aware start time")
        self.seed, self.start = seed, start.astimezone(timezone.utc).replace(microsecond=0)
        self.reset()

    # -- lifecycle --------------------------------------------------------------------------------------------------
    def reset(self):
        self._rng = Random("aegisflow-plant:%d" % self.seed)
        self.now, self.readings, self.emitted, self.checks, self.detected = 0, [], 0, 0, 0
        self.faults, self.incidents, self.detections, self.last_check = [], [], [], None
        self._evidence, self._next_fault, self._next_incident = {}, 1, 1
        commissioning = WINDOW_SECONDS * REFERENCE_WINDOWS
        self.advance(commissioning, monitor=False)
        rows = self.readings[-commissioning:]
        self.references = [to_csv(rows[k * WINDOW_SECONDS:(k + 1) * WINDOW_SECONDS]) for k in range(REFERENCE_WINDOWS)]
        self.baseline = baseline_checks.build_baseline(self.references)
        self.live_start = self.now

    def _stamp(self, t):
        return timestamp(self.start, t)

    def _active(self, fault, sensor=None):
        return next((f for f in self.faults if f["ended_t"] is None and f["fault"] == fault
                     and (sensor is None or f["sensor"] == sensor)), None)

    def _emit(self, row):
        self.readings.append(row)
        self.emitted += 1
        del self.readings[:-MAX_READINGS]

    def _reading(self, t, noise):
        factor = {f["sensor"]: NOISE_FACTOR for f in self.faults if f["ended_t"] is None and f["fault"] == "noise_increase"}
        values = clean_values(t, noise, factor)
        for fault in self.faults:
            if fault["ended_t"] is not None or fault["fault"] not in SENSOR_FAULTS:
                continue
            sensor = fault["sensor"]
            if fault["fault"] == "calibration_offset":
                values[sensor] = round(values[sensor] + fault["offset"], 3)
            elif fault["fault"] == "unit_change":
                values[sensor] = round(values[sensor] * UNIT_FACTOR, 3)
            elif fault["fault"] == "stuck_sensor":
                values[sensor] = fault["value"]
        return {"t": t, "ts": self._stamp(t), **values}

    def advance(self, seconds, *, monitor=True):
        """Run ``seconds`` simulated seconds: one reading per second unless a stream fault drops it."""
        if type(seconds) is not int or seconds < 0:
            raise ValueError("seconds must be a non-negative integer")
        for _ in range(seconds):
            t = self.now
            noise = (self._rng.gauss(0, 1), self._rng.gauss(0, 1), self._rng.gauss(0, 1))  # drawn every second
            slow = self._active("sampling_slowdown")
            dropped = self._active("ingestion_pause") or (slow and (t - slow["started_t"]) % SLOW_EVERY)
            if not dropped:
                self._emit(self._reading(t, noise))
            self.now += 1
            if monitor and (self.now - self.live_start) % CHECK_EVERY == 0:
                self.check()

    # -- faults -------------------------------------------------------------------------------------------------------
    def inject(self, fault, sensor=None):
        """Inject a simulated fault from now on; returns its record. InputRejected for an invalid or repeated fault."""
        if fault not in FAULTS:
            raise InputRejected("Unknown fault")
        if fault in SENSOR_FAULTS and sensor not in SENSORS:
            raise InputRejected("This fault needs one of the sensors: %s" % ", ".join(SENSORS))
        if fault in STREAM_FAULTS and sensor is not None:
            raise InputRejected("This fault acts on the whole stream and takes no sensor")
        if self._active(fault, sensor):
            raise InputRejected("This fault is already active")
        if sum(f["ended_t"] is None for f in self.faults) >= MAX_ACTIVE_FAULTS:
            raise InputRejected("At most %d faults can be active at once" % MAX_ACTIVE_FAULTS)
        t = self.now - 1
        record = {"id": "F%d" % self._next_fault, "fault": fault, "sensor": sensor, "started_t": self.now,
                  "started_at": self._stamp(self.now), "ended_t": None, "ended_at": None, "one_shot": False}
        self._next_fault += 1
        if fault == "calibration_offset":
            record["offset"] = round(OFFSET_SD * self.baseline["numeric"][sensor]["sd"], 6)
        elif fault == "stuck_sensor":
            record["value"] = self.readings[-1][sensor]
        elif fault == "duplicate_burst":
            for row in [dict(r) for r in self.readings[-DUPLICATE_BURST:]]:
                self._emit(row)
            record.update(started_t=t, started_at=self._stamp(t), ended_t=t, ended_at=self._stamp(t), one_shot=True)
        self.faults.append(record)
        del self.faults[:-MAX_FAULTS]
        return dict(record)

    def clear(self, fault_id):
        """End an active fault; KeyError when no active fault has this id."""
        fault = next((f for f in self.faults if f["id"] == fault_id and f["ended_t"] is None), None)
        if fault is None:
            raise KeyError(fault_id)
        fault.update(ended_t=self.now, ended_at=self._stamp(self.now))
        return dict(fault)

    # -- monitor ------------------------------------------------------------------------------------------------------
    def window(self, end_t):
        """Readings with ``end_t - WINDOW_SECONDS < t <= end_t``, in arrival order."""
        return [r for r in self.readings if end_t - WINDOW_SECONDS < r["t"] <= end_t]

    def check(self):
        """Compare and profile the latest window; update incidents. Returns this check's findings."""
        end = self.now - 1
        rows, as_of = self.window(end), self._stamp(end)
        payload = to_csv(rows) if rows else None
        if payload is None:  # nothing arrived in a whole window: only freshness and volume can be said
            findings = [{"check": "freshness", "column": "ts", "source": "baseline", "severity": "medium",
                         "detail": {"latest": None, "sla_seconds": self.baseline["freshness_sla_seconds"]}},
                        {"check": "volume_change", "column": None, "source": "baseline", "severity": "medium",
                         "detail": {"current": 0, "direction": "drop"}}]
        else:
            findings = findings_of(baseline_checks.compare(self.baseline, payload, as_of=as_of), profile_csv(payload))
        digest = hashlib.sha256(payload or b"").hexdigest()
        window = {"sha256": digest, "first_t": rows[0]["t"] if rows else None, "last_t": end, "records": len(rows),
                  "as_of": as_of}
        self.incidents, detections, self._next_incident = update_incidents(
            self.incidents, findings, t=end, at=as_of, window=window, next_id=self._next_incident)
        for item in self.incidents:
            if item["window"]["sha256"] == digest and item["status"] == "open":
                self._evidence[item["id"]] = (payload, as_of)
        self.detections = (self.detections + detections)[-MAX_DETECTIONS:]
        self.detected += len(detections)
        self.checks += 1
        self.last_check = {"t": end, "at": as_of, "records": len(rows), "sha256": digest, "findings": len(findings)}
        drop = [i["id"] for i in self.incidents if i["status"] == "closed"][:max(0, len(self.incidents) - MAX_INCIDENTS)]
        self.incidents = [i for i in self.incidents if i["id"] not in drop]
        for key in drop:
            self._evidence.pop(key, None)
        return findings

    def evidence(self, incident_id):
        """(CSV bytes, as_of) of the incident's evidence window; KeyError when unknown or empty."""
        payload, as_of = self._evidence[incident_id]
        if payload is None:
            raise KeyError(incident_id)
        return payload, as_of

    def incident(self, incident_id):
        found = next((i for i in self.incidents if i["id"] == incident_id), None)
        if found is None:
            raise KeyError(incident_id)
        return found

    # -- export and views ---------------------------------------------------------------------------------------------
    def export_window(self, n):
        """CSV bytes of the last ``n`` readings."""
        if type(n) is not int or n < 1:
            raise ValueError("n must be a positive integer")
        return to_csv(self.readings[-n:])

    def bands(self):
        """Baseline mean +/- 3 sd per sensor, from the stored baseline record."""
        return {s: {"mean": e["mean"], "sd": e["sd"], "low": round(e["mean"] - 3 * e["sd"], 6),
                    "high": round(e["mean"] + 3 * e["sd"], 6)}
                for s, e in ((s, self.baseline["numeric"][s]) for s in SENSORS)}

    def snapshot(self):
        rows = self.readings[-CHART_READINGS:]
        return {
            "simulation": True, "seed": self.seed, "start": self._stamp(0), "now_t": self.now, "now": self._stamp(self.now),
            "live_start_t": self.live_start, "elapsed_s": self.now - self.live_start, "emitted": self.emitted,
            "checks": self.checks, "detected": self.detected, "last_check": self.last_check, "units": dict(UNITS),
            "settings": {"window_seconds": WINDOW_SECONDS, "check_every": CHECK_EVERY, "reference_windows": REFERENCE_WINDOWS,
                         "close_after": CLOSE_AFTER, "chart_readings": CHART_READINGS},
            "baseline": {"digest": self.baseline["digest"], "records": sum(r["records"] for r in self.baseline["references"]),
                         "first_t": 0, "last_t": self.live_start - 1, "bands": self.bands(),
                         "freshness_sla_seconds": self.baseline["freshness_sla_seconds"]},
            "series": {"t": [r["t"] for r in rows], **{s: [r[s] for r in rows] for s in SENSORS}},
            "current": {"t": rows[-1]["t"], **{s: rows[-1][s] for s in SENSORS}},
            "faults": [dict(f) for f in reversed(self.faults)],
            "incidents": [dict(i, findings=[dict(f) for f in i["findings"]]) for i in reversed(self.incidents)],
            "detections": [dict(d) for d in self.detections],
        }
