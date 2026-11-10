# SPDX-License-Identifier: Apache-2.0
"""A bounded, synthetic-only baseline for batch data quality diagnostics.

Findings describe observed violations, not inferred root causes. No model calls,
production connectors, database writes, or automatic remediation are performed.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from random import Random
import re

EXPECTED_COLUMNS = ("order_id", "customer_id", "order_total")
MAX_INPUT_BYTES = 1_000_000
MAX_ROWS = 10_000
MAX_FINDINGS = 100
FAULTS = ("clean", "schema_drift", "null_total", "duplicate_order")


class InputRejected(ValueError):
    """The input is malformed or exceeds the local diagnostic budget."""


@dataclass(frozen=True)
class Finding:
    check: str
    column: str
    record_numbers: tuple[int, ...]
    message: str


@dataclass(frozen=True)
class Report:
    status: str
    source_sha256: str
    source_bytes: int
    row_count: int
    finding_count: int
    findings_truncated: bool
    findings: tuple[Finding, ...]
    total_valid_amount: str | None
    format_version: str = "1"
    engine: str = "deterministic-csv-v1"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, sort_keys=True)


def generate_orders(*, seed: int = 42, rows: int = 24, fault: str = "clean") -> bytes:
    """Return reproducible UTF-8 CSV bytes; never write a file."""
    if type(seed) is not int or type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError("Use an integer seed and 1-10000 rows")
    if fault not in FAULTS:
        raise ValueError("Unknown synthetic fault")
    rng = Random(seed)
    records = [
        [f"ORD-{i + 1:05}", f"CUS-{rng.randrange(1, 11):03}",
         f"{Decimal(rng.randrange(100, 100001)) / 100:.2f}"]
        for i in range(rows)
    ]
    columns = list(EXPECTED_COLUMNS)
    if fault == "schema_drift":
        columns[2] = "total_amount"
    elif fault == "null_total":
        records[0][2] = ""
    elif fault == "duplicate_order":
        # Keep row count fixed so a one-row input can still contain a duplicate.
        if rows < 2:
            raise ValueError("Duplicate injection requires at least two rows")
        records[-1][0] = records[0][0]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(records)
    return stream.getvalue().encode("utf-8")


def diagnose_csv(payload: bytes) -> Report:
    """Inspect bounded CSV bytes with evidence bound to the exact byte digest.

    Record numbers are 1-based logical CSV data records, excluding the header;
    quoted multiline fields therefore do not change record numbering.
    """
    if len(payload) > MAX_INPUT_BYTES:
        raise InputRejected("CSV exceeds the 1000000-byte input budget")
    try:
        source = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputRejected("CSV must be UTF-8") from exc
    if "\x00" in source:
        raise InputRejected("NUL characters are not supported")
    reader = csv.reader(io.StringIO(source, newline=""), strict=True)
    findings: list[Finding] = []
    count = 0

    def add(check: str, column: str, numbers: tuple[int, ...], message: str) -> None:
        nonlocal count
        count += 1
        if len(findings) < MAX_FINDINGS:
            findings.append(Finding(check, column, numbers, message))

    row_count = 0
    total = Decimal("0.00")
    try:
        header = next(reader, None)
        if not header or len(set(header)) != len(header) or any(not h for h in header):
            raise InputRejected("A nonempty header with unique column names is required")
        missing = sorted(set(EXPECTED_COLUMNS) - set(header))
        extra = sorted(set(header) - set(EXPECTED_COLUMNS))
        for column in missing:
            add("missing_column", column, (), "Required column is absent")
        for column in extra:
            add("unexpected_column", column, (), "Column is outside the data contract")
        seen: dict[str, int] = {}
        for number, values in enumerate(reader, 1):
            if number > MAX_ROWS:
                raise InputRejected("CSV exceeds the 10000-record input budget")
            row_count = number
            if len(values) != len(header):
                raise InputRejected(f"Record {number} has an inconsistent field count")
            row = dict(zip(header, values))
            for column in EXPECTED_COLUMNS:
                if column in row and not row[column].strip():
                    add("not_null", column, (number,), "Required value is empty")
            order_id = row.get("order_id", "").strip()
            if order_id:
                if order_id in seen:
                    add("unique", "order_id", (seen[order_id], number),
                        "Order identifier occurs in multiple records")
                else:
                    seen[order_id] = number
            raw = row.get("order_total", "").strip()
            if raw:
                # Bound decimal parsing before arithmetic; reject exponents,
                # NaN, Infinity and sub-cent values without rounding silently.
                if not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,2})?", raw):
                    add("amount_format", "order_total", (number,),
                        "Expected a nonnegative decimal amount with at most two decimal places")
                else:
                    try:
                        total += Decimal(raw)
                    except InvalidOperation as exc:
                        raise InputRejected("Invalid decimal amount") from exc
        if row_count == 0:
            add("nonempty_dataset", "", (), "No data records were supplied")
    except csv.Error as exc:
        raise InputRejected("Malformed CSV") from exc
    return Report(
        status="PASS" if count == 0 else "FAIL",
        source_sha256=hashlib.sha256(payload).hexdigest(),
        source_bytes=len(payload), row_count=row_count, finding_count=count,
        findings_truncated=count > len(findings), findings=tuple(findings),
        total_valid_amount=f"{total:.2f}" if count == 0 else None,
    )
