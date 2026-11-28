# SPDX-License-Identifier: Apache-2.0
"""The case file of an incident: a hash chain over its evidence, and the human decision record.

Design: docs/superpowers/specs/2026-11-28-evidence-chain-decision-report-design.md.

A chain links, in a fixed order, the baseline, the frozen evidence window, the probe-loop record, the sealed agent run
and the human decision. Each link carries the SHA-256 of the record it stands for and the hash of the previous link, so
changing any record or reordering links is detectable. The digests are integrity checks anyone can recompute, not
signatures. A decision is recorded, never executed.
"""
from hashlib import sha256
import json

from .pipeline import InputRejected

LINKS = ("baseline", "evidence", "probes", "agent_run", "decision")
VERIFIED, MISMATCH, MISSING = "verified", "mismatch", "missing"
DECISIONS = ("accepted", "rejected", "more_evidence")
MAX_REVIEWER, MAX_NOTE = 60, 500
_HEX = frozenset("0123456789abcdef")


def canonical(value):
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def is_digest(value):
    return type(value) is str and len(value) == 64 and set(value) <= _HEX


def link(kind, record_sha256, at, summary, prev):
    """One chain link; ``link_sha256`` covers every other field, ``prev`` included."""
    if kind not in LINKS or not is_digest(record_sha256) or not (prev is None or is_digest(prev)):
        raise InputRejected("Invalid chain link")
    body = {"kind": kind, "digest": record_sha256, "at": at, "summary": summary, "prev": prev}
    return {**body, "link_sha256": digest(body)}


def build_chain(items):
    """Links for ``items`` = [(kind, record digest, at, summary), ...] in ``LINKS`` order (a prefix of it)."""
    if [kind for kind, *_ in items] != list(LINKS[:len(items)]):
        raise InputRejected("Chain links must follow the fixed order")
    chain, prev = [], None
    for kind, record_sha256, at, summary in items:
        chain.append(link(kind, record_sha256, at, summary, prev))
        prev = chain[-1]["link_sha256"]
    return chain


def chain_intact(chain):
    """True when every link hashes to its ``link_sha256`` and points at the previous one, in ``LINKS`` order."""
    prev = None
    for position, item in enumerate(chain):
        body = {k: item.get(k) for k in ("kind", "digest", "at", "summary", "prev")}
        if (position >= len(LINKS) or item.get("kind") != LINKS[position] or item.get("prev") != prev
                or item.get("link_sha256") != digest(body)):
            return False
        prev = item["link_sha256"]
    return True


def _text(value, limit, *, required):
    if type(value) is not str:
        raise InputRejected("Text fields must be strings")
    value = " ".join(value.split())
    if (required and not value) or len(value) > limit or not all(c.isprintable() for c in value):
        raise InputRejected("Text field is empty, too long or not printable")
    return value


def decision_record(*, incident_id, evidence_sha256, run_id, decision, candidate, supported, reviewer, note, decided_at):
    """A validated decision record with its digest.

    ``accepted`` needs ``candidate``, which must be one of the ``supported`` mechanisms on the frozen evidence; the other
    decisions take no candidate. A person can record that the evidence is not enough, never accept what it does not
    support.
    """
    if decision not in DECISIONS:
        raise InputRejected("Unknown decision")
    if not is_digest(evidence_sha256) or type(run_id) is not str or not run_id:
        raise InputRejected("A decision needs the frozen evidence and the agent run it applies to")
    if decision == "accepted":
        if candidate not in supported:
            raise InputRejected("Only a candidate the probes support on the frozen evidence can be accepted")
    elif candidate is not None:
        raise InputRejected("Only an accepted decision names a candidate")
    record = {"incident_id": incident_id, "evidence_sha256": evidence_sha256, "run_id": run_id, "decision": decision,
              "candidate": candidate, "reviewer": _text(reviewer, MAX_REVIEWER, required=True),
              "note": _text(note, MAX_NOTE, required=False), "decided_at": decided_at, "executed": False}
    return {**record, "sha256": digest(record)}


def decision_intact(record):
    body = {k: v for k, v in record.items() if k != "sha256"}
    return record.get("executed") is False and record.get("sha256") == digest(body)
