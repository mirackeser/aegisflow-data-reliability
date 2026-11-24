# SPDX-License-Identifier: Apache-2.0
"""Observation, hypothesis and probe contracts over a fixed catalog of simulated mechanisms (work package F04).

This is bookkeeping of candidate explanations, not root-cause inference. A "supported" hypothesis means fixed,
deterministic probes found the measurements consistent with it and inconsistent with none, nothing more.
``genuine_change`` (a real change in the measured process) cannot be tested from these data, so it always stays open.
Probe thresholds are written down in the design before any measurement and are not tuned on evaluation output.
"""
from functools import lru_cache
import hashlib
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

from .pipeline import InputRejected

FORMAT, ENGINE, CATALOG_VERSION = "1", "deterministic-hypotheses-v1", "1"
MAX_PROBES_DEFAULT, MAX_PROBES_LIMIT = 6, 20
STATEMENT = "Candidate mechanisms consistent with fixed probes on these measurements. Not a root-cause determination."
MECHANISMS = ("unit_change", "calibration_offset", "noise_increase", "stuck_sensor", "genuine_change", "sampling_config_change",
              "partial_load", "duplicate_delivery", "delivery_delay", "source_outage", "field_outage", "intermittent_loss")
PROBES = ("scale_ratio", "spread_ratio", "flat_share", "interval_regularity", "span_ratio", "freshness_lag", "duplicate_share",
          "empty_runs")
KINDS = ("observation", "hypothesis", "probe_result", "investigation")
PROFILE_CHECKS = ("flatline", "duplicate_rows", "timestamp_duplicate")
# Mechanism -> (column scoped?, observations it explains as (check, direction or None for any)).
CATALOG = {
    "unit_change": (True, (("distribution_shift", None),)),
    "calibration_offset": (True, (("distribution_shift", None),)),
    "noise_increase": (True, (("distribution_shift", None),)),
    "stuck_sensor": (True, (("distribution_shift", None), ("flatline", None))),
    "genuine_change": (True, (("distribution_shift", None),)),
    "sampling_config_change": (False, (("sampling_interval_change", None), ("volume_change", None))),
    "partial_load": (False, (("volume_change", "drop"),)),
    "duplicate_delivery": (False, (("volume_change", "increase"), ("duplicate_rows", None), ("timestamp_duplicate", None))),
    "delivery_delay": (False, (("freshness", None),)),
    "source_outage": (False, (("freshness", None), ("volume_change", "drop"))),
    "field_outage": (True, (("empty_rate_change", None),)),
    "intermittent_loss": (True, (("empty_rate_change", None),)),
}


def _offline(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=1)
def _schema():
    schema = json.loads(files("aegisflow_dr").joinpath("data", "hypothesis-contracts-v1.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=len(KINDS))
def _validator(kind):
    schema = _schema()
    wrapper = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/" + kind}
    return Draft202012Validator(wrapper, registry=Registry(retrieve=_offline))


def validate(kind, value):
    """Return ``value`` unchanged when it satisfies the ``kind`` contract; else raise InputRejected."""
    if type(kind) is not str or kind not in KINDS:
        raise InputRejected("Unknown hypothesis contract")
    try:
        _validator(kind).validate(value)
    except ValidationError:
        raise InputRejected("Hypothesis %s contract rejected" % kind.replace("_", " ")) from None
    return value


def trace_digest(record):
    """SHA-256 of the canonical JSON of ``record`` without its ``trace_sha256`` field."""
    body = {k: v for k, v in record.items() if k != "trace_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def verify_investigation(record):
    """Return ``record`` unchanged when it is schema-valid and its trace digest matches; else raise InputRejected."""
    validate("investigation", record)
    if record["trace_sha256"] != trace_digest(record):
        raise InputRejected("Investigation trace digest does not match its content")
    return record


def observations_from(comparison, profile):
    """Observations from every baseline finding, then from the profile's flatline and duplicate findings, in their order."""
    evidence = comparison["source_sha256"]
    picked = [("baseline", f) for f in comparison["findings"]]
    picked += [("profile", f) for f in profile["findings"] if f["check"] in PROFILE_CHECKS]
    return [{"id": "obs-%d" % number, "source": source, "check": f["check"], "column": f["column"],
             "direction": f["detail"].get("direction") if f["check"] == "volume_change" else None, "evidence_sha256": evidence}
            for number, (source, f) in enumerate(picked, 1)]


def _explains(mechanism, observation):
    return any(check == observation["check"] and direction in (None, observation["direction"])
               for check, direction in CATALOG[mechanism][1])


def generate(observations):
    """One open hypothesis per (mechanism, column) explaining at least one observation, with its competitors."""
    hypotheses, index = [], {}
    for obs in observations:
        for mechanism in MECHANISMS:
            if not _explains(mechanism, obs):
                continue
            key = (mechanism, obs["column"] if CATALOG[mechanism][0] else None)
            if key not in index:
                index[key] = {"id": "hyp-%d" % (len(hypotheses) + 1), "mechanism": mechanism, "column": key[1], "explains": [],
                              "competitors": [], "status": "open", "supporting": [], "refuting": []}
                hypotheses.append(index[key])
            index[key]["explains"].append(obs["id"])
    for hyp in hypotheses:
        hyp["competitors"] = [other["id"] for other in hypotheses
                              if other is not hyp and set(other["explains"]) & set(hyp["explains"])]
    return hypotheses
