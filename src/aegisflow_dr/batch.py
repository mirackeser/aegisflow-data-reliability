# SPDX-License-Identifier: Apache-2.0
"""In-memory batch transformations and declared dataset-level impact analysis."""
from __future__ import annotations

import csv
from contextlib import closing
from dataclasses import asdict, dataclass, field
from decimal import Decimal
import hashlib
from importlib.resources import files
import io
import json
import sqlite3

from .pipeline import Report, diagnose_csv

DATASETS = ("source_orders", "staging_orders", "customer_sales", "sales_dashboard")
EDGES = (("source_orders", "staging_orders"), ("staging_orders", "customer_sales"),
         ("customer_sales", "sales_dashboard"))
STAGING_CONTRACT = b"stage-v1:logical-record-order;trim-identifiers;integer-cents"
TRANSFORMS = {"clean": "customer_sales_v1.sql",
              "exclude_first": "customer_sales_exclude_first_v1.sql"}


def downstream(dataset: str) -> tuple[str, ...]:
    """Return potential transitive consumers from the fixed, declared lineage DAG.

    This is dataset-level metadata, not runtime-inferred or column-level lineage.
    The dashboard is a declared consumer; no dashboard job is executed here.
    """
    if dataset not in DATASETS:
        raise ValueError("Unknown dataset")
    reached: set[str] = set()
    pending = [dataset]
    while pending:
        current = pending.pop()
        for parent, child in EDGES:
            if parent == current and child not in reached:
                reached.add(child)
                pending.append(child)
    return tuple(item for item in DATASETS if item in reached)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encode_csv(header: tuple[str, ...], rows: list[tuple]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


@dataclass(frozen=True)
class Artifact:
    dataset: str
    sha256: str
    row_count: int
    upstream_sha256: str | None
    transform_sha256: str | None


@dataclass(frozen=True)
class Reconciliation:
    check: str
    expected: int
    actual: int
    passed: bool
    evidence_sha256: tuple[str, ...]


@dataclass(frozen=True)
class BatchReport:
    status: str
    source_check: Report
    artifacts: tuple[Artifact, ...]
    reconciliation: tuple[Reconciliation, ...]
    affected_dataset: str | None
    potential_downstream: tuple[str, ...]
    transform_sha256: str
    format_version: str = "1"
    engine: str = "sqlite-memory-batch-v1"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class BatchSnapshot:
    name: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class BatchExecution:
    report: BatchReport
    snapshots: tuple[BatchSnapshot, ...]


def run_batch(payload: bytes, *, transform: str = "clean") -> BatchReport:
    return execute_batch(payload, transform=transform).report


def execute_batch(payload: bytes, *, transform: str = "clean") -> BatchExecution:
    """Validate input, stage exact integer cents, run reviewed SQL, reconcile.

    SQLite is exclusively in memory. Only packaged SQL can run. All emitted
    dataset hashes refer to canonical UTF-8 CSV bytes, except the source hash,
    which refers to exact supplied bytes. Raw business values are not emitted.
    """
    if transform not in TRANSFORMS:
        raise ValueError("Unknown packaged transform")
    sql_bytes = files("aegisflow_dr").joinpath("sql", TRANSFORMS[transform]).read_bytes()
    sql_hash = digest(sql_bytes)
    source = diagnose_csv(payload)
    source_artifact = Artifact("source_orders", source.source_sha256, source.row_count,
                               None, None)
    if source.status != "PASS":
        return BatchExecution(BatchReport("BLOCKED", source, (source_artifact,), (), "source_orders",
                           downstream("source_orders"), sql_hash), ())

    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    records = [
        (number, row["order_id"].strip(), row["customer_id"].strip(),
         int(Decimal(row["order_total"].strip()) * 100))
        for number, row in enumerate(reader, 1)
    ]
    stage_bytes = encode_csv(("record_number", "order_id", "customer_id", "total_cents"),
                             records)
    stage_hash = digest(stage_bytes)
    # Version the normalization contract independently of the SQL transformation.
    stage_version = digest(STAGING_CONTRACT)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE TABLE staging_orders (record_number INTEGER PRIMARY KEY, "
                           "order_id TEXT NOT NULL UNIQUE, customer_id TEXT NOT NULL, "
                           "total_cents INTEGER NOT NULL CHECK(total_cents >= 0))")
        connection.executemany("INSERT INTO staging_orders VALUES (?, ?, ?, ?)", records)
        mart = connection.execute(sql_bytes.decode("utf-8")).fetchall()
    mart_bytes = encode_csv(("customer_id", "order_count", "total_cents"), mart)
    mart_hash = digest(mart_bytes)
    expected_cents = sum(record[3] for record in records)
    actual_cents = sum(record[2] for record in mart)
    actual_count = sum(record[1] for record in mart)
    evidence = (stage_hash, mart_hash)
    checks = (
        Reconciliation("order_count", len(records), actual_count,
                       len(records) == actual_count, evidence),
        Reconciliation("amount_cents", expected_cents, actual_cents,
                       expected_cents == actual_cents, evidence),
    )
    failed = any(not check.passed for check in checks)
    artifacts = (source_artifact,
                 Artifact("staging_orders", stage_hash, len(records),
                          source.source_sha256, stage_version),
                 Artifact("customer_sales", mart_hash, len(mart), stage_hash, sql_hash))
    report = BatchReport("FAIL" if failed else "PASS", source, artifacts, checks,
                       "customer_sales" if failed else None,
                       downstream("customer_sales") if failed else (), sql_hash)
    return BatchExecution(report, (
        BatchSnapshot('staging_orders', stage_bytes), BatchSnapshot('customer_sales', mart_bytes),
        BatchSnapshot('sql_transform', sql_bytes), BatchSnapshot('staging_contract', STAGING_CONTRACT)))
