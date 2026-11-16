# SPDX-License-Identifier: Apache-2.0
"""Deterministic schema discovery and record-level impact analysis for order CSV files.

Everything here is computed from the supplied bytes: exact counts, exact decimal sums
and declared lineage. Nothing is inferred by a model, and explanations are limited to
observed patterns that are labelled as such. Raw identifiers are never returned; only
masked forms, record numbers and aggregates leave this module.
"""
from __future__ import annotations

import csv
from decimal import Decimal
from difflib import SequenceMatcher
import hashlib
import io
import re

from .batch import downstream
from .pipeline import EXPECTED_COLUMNS, InputRejected, diagnose_csv

MAX_LISTED_RECORDS = 200
MAX_DUPLICATE_GROUPS = 20
HISTOGRAM_BINS = 8
_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,2})?")
_INTEGER = re.compile(r"-?[0-9]+")
_DECIMAL = re.compile(r"-?[0-9]+\.[0-9]+")
_ALIASES = {
    "order_id": {"orderid", "order", "id", "ordernumber", "orderno", "ordernr", "ordno", "siparisid", "siparisno"},
    "customer_id": {"customerid", "customer", "custid", "customerno", "clientid", "client", "musteriid", "musterino"},
    "order_total": {"ordertotal", "total", "totalamount", "amount", "orderamount", "ordervalue", "price", "revenue",
                    "tutar", "toplam"},
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _parse(payload: bytes) -> tuple[list[str], list[list[str]]]:
    """Return header and rows after the same bounded validation used by the diagnostics."""
    diagnose_csv(payload)  # raises InputRejected for size, encoding, header and field-count violations
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
    header = next(reader)
    return header, [list(row) for row in reader]


def _infer_type(values: list[str]) -> str:
    filled = [v.strip() for v in values if v.strip()]
    if not filled:
        return "empty"
    if all(_INTEGER.fullmatch(v) for v in filled):
        return "integer"
    if all(_INTEGER.fullmatch(v) or _DECIMAL.fullmatch(v) for v in filled):
        return "decimal"
    return "text"


def _numeric_share(values: list[str]) -> float:
    """Share of non-empty values that look like numbers; used only to rank mapping candidates."""
    filled = [v.strip() for v in values if v.strip()]
    if not filled:
        return 0.0
    return sum(1 for v in filled if _INTEGER.fullmatch(v) or _DECIMAL.fullmatch(v)) / len(filled)


def _mask(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 3:
        return value[0] + "•••"
    if len(value) <= 6:
        return value[:1] + "•••" + value[-1:]
    return value[:2] + "•••" + value[-2:]


def _ratio(passed: int, total: int) -> dict:
    return {"passed": passed, "total": total, "ratio": round(passed / total, 4) if total else None}


def _candidates(header: list[str], columns: dict[str, list[str]]) -> dict[str, dict]:
    """Suggest, never apply, a mapping from unexpected columns to missing contract columns."""
    result: dict[str, dict] = {}
    unexpected = [name for name in header if name not in EXPECTED_COLUMNS]
    taken: set[str] = set()
    for target in EXPECTED_COLUMNS:
        if target in header:
            continue
        best: tuple[float, str, str] | None = None
        for name in unexpected:
            if name in taken:
                continue
            # Invalid amounts are reported as findings after mapping, so a mostly numeric column still qualifies.
            if target == "order_total" and _numeric_share(columns[name]) < 0.5:
                continue
            norm = _normalize(name)
            if norm in _ALIASES[target]:
                score, basis = 1.0, "alias"
            else:
                score = SequenceMatcher(None, norm, _normalize(target)).ratio()
                basis = "similar"
                if score < 0.75:
                    continue
            if best is None or score > best[0]:
                best = (score, name, basis)
        if best:
            taken.add(best[1])
            result[target] = {"column": best[1], "basis": best[2], "score": round(best[0], 2)}
    return result


def discover_schema(payload: bytes) -> dict:
    """Describe the file against the order contract without running an investigation."""
    header, rows = _parse(payload)
    columns = {name: [row[i] for row in rows] for i, name in enumerate(header)}
    candidates = _candidates(header, columns)
    contract = []
    for name in EXPECTED_COLUMNS:
        if name in header:
            contract.append({"name": name, "status": "matched", "candidate": None})
        elif name in candidates:
            contract.append({"name": name, "status": "candidate", "candidate": candidates[name]})
        else:
            contract.append({"name": name, "status": "missing", "candidate": None})
    described = []
    for position, name in enumerate(header, 1):
        values = columns[name]
        filled = [v for v in values if v.strip()]
        described.append({
            "name": name, "position": position, "inferred_type": _infer_type(values),
            "non_empty": len(filled), "empty": len(values) - len(filled),
            "distinct": len({v.strip() for v in filled}),
            "contract_role": name if name in EXPECTED_COLUMNS else None,
            "suggested_role": next((t for t, c in candidates.items() if c["column"] == name), None),
        })
    missing = [c for c in contract if c["status"] == "missing"]
    pending = [c for c in contract if c["status"] == "candidate"]
    extra = [d["name"] for d in described if d["contract_role"] is None and d["suggested_role"] is None]
    # The contract is strict: columns outside it are reported by the inspection, so they are not "compatible".
    status = ("INCOMPATIBLE" if missing else "MAPPING_NEEDED" if pending
              else "EXTRA_COLUMNS" if extra else "COMPATIBLE")
    return {
        "format_version": "1", "engine": "deterministic-discovery-v1", "status": status,
        "row_count": len(rows), "source_bytes": len(payload),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "columns": described, "contract": contract,
        "unexpected": extra,
    }


def apply_mapping(payload: bytes, mapping: dict[str, str]) -> bytes:
    """Return a normalized copy whose header names follow the explicit source→contract mapping."""
    header, rows = _parse(payload)
    if type(mapping) is not dict or not mapping or len(mapping) > len(EXPECTED_COLUMNS):
        raise InputRejected("Column mapping must be a small nonempty object")
    targets = list(mapping.values())
    if (any(type(k) is not str or type(v) is not str for k, v in mapping.items())
            or len(set(targets)) != len(targets) or not set(targets) <= set(EXPECTED_COLUMNS)):
        raise InputRejected("Column mapping targets must be distinct contract columns")
    if (not set(mapping) <= set(header) or set(targets) & set(header)
            or set(mapping) & set(EXPECTED_COLUMNS)):
        raise InputRejected("Mapping sources must be non-contract columns and targets must be absent")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([mapping.get(name, name) for name in header])
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def record_issues(header: list[str], rows: list[list[str]]) -> tuple[dict[int, set[str]], dict[tuple[str, str], set[int]]]:
    """Evaluate the order-contract record rules over every record (no display cap)."""
    index = {name: i for i, name in enumerate(header)}
    issues: dict[int, set[str]] = {}
    by_check: dict[tuple[str, str], set[int]] = {}

    def flag(number: int, check: str, column: str) -> None:
        issues.setdefault(number, set()).add(check)
        by_check.setdefault((column, check), set()).add(number)

    seen: dict[str, int] = {}
    for number, row in enumerate(rows, 1):
        for column in EXPECTED_COLUMNS:
            if column in index and not row[index[column]].strip():
                flag(number, "not_null", column)
        order_id = row[index["order_id"]].strip() if "order_id" in index else ""
        if order_id:
            if order_id in seen:
                flag(seen[order_id], "unique", "order_id")
                flag(number, "unique", "order_id")
            else:
                seen[order_id] = number
        raw = row[index["order_total"]].strip() if "order_total" in index else ""
        if raw and not _AMOUNT.fullmatch(raw):
            flag(number, "amount_format", "order_total")
    return issues, by_check


def _amount_state(raw: str | None) -> str:
    if raw is None:
        return "not_available"
    raw = raw.strip()
    if not raw:
        return "empty"
    return "valid" if _AMOUNT.fullmatch(raw) else "invalid"


def analyze_csv(payload: bytes) -> dict:
    """Return dimensions, record impact, duplicate evidence, downstream scope and review actions."""
    header, rows = _parse(payload)
    report = diagnose_csv(payload)
    index = {name: i for i, name in enumerate(header)}

    def cell(row: list[str], name: str) -> str | None:
        return row[index[name]] if name in index else None

    # The diagnostic report caps listed findings; impact must not be capped with it, so the
    # record-level rules are evaluated here in full. Tests assert equality with the report.
    issues, totals_by_check = record_issues(header, rows)
    schema_issues = [{"check": f.check, "column": f.column} for f in report.findings
                     if f.check in ("missing_column", "unexpected_column")]
    truncated = report.findings_truncated

    # Dimensions: exact numerators and denominators.
    non_empty_cells = sum(1 for row in rows for name in EXPECTED_COLUMNS if (cell(row, name) or "").strip())
    ids = [(cell(row, "order_id") or "").strip() for row in rows]
    filled_ids = [v for v in ids if v]
    amounts = [cell(row, "order_total") for row in rows]
    filled_amounts = [a for a in amounts if a is not None and a.strip()]
    valid_amounts = [a for a in filled_amounts if _AMOUNT.fullmatch(a.strip())]
    row_issues = {n for n in issues}
    dimensions = {
        "completeness": _ratio(non_empty_cells, len(rows) * len(EXPECTED_COLUMNS)),
        "uniqueness": _ratio(len(set(filled_ids)), len(filled_ids)) if "order_id" in index else _ratio(0, 0),
        "validity": _ratio(len(valid_amounts), len(filled_amounts)) if "order_total" in index else _ratio(0, 0),
        "record_health": _ratio(len(rows) - len(row_issues), len(rows)),
    }

    # Exact money arithmetic over valid amounts only.
    def money(numbers) -> Decimal:
        total = Decimal("0.00")
        for n in numbers:
            raw = cell(rows[n - 1], "order_total")
            if raw is not None and _AMOUNT.fullmatch(raw.strip()):
                total += Decimal(raw.strip())
        return total

    all_valid_total = money(range(1, len(rows) + 1))
    affected_total = money(sorted(row_issues))

    # Duplicate groups and the amount that would be counted twice.
    first_seen: dict[str, int] = {}
    groups: dict[str, list[int]] = {}
    for number, order_id in enumerate(ids, 1):
        if not order_id:
            continue
        if order_id in first_seen:
            groups.setdefault(order_id, [first_seen[order_id]]).append(number)
        else:
            first_seen[order_id] = number
    repeat_numbers = [n for members in groups.values() for n in members[1:]]
    duplicate_groups = []
    for order_id, members in list(groups.items())[:MAX_DUPLICATE_GROUPS]:
        differing = [name for name in header
                     if len({rows[n - 1][index[name]].strip() for n in members}) > 1]
        duplicate_groups.append({
            "order_id_masked": _mask(order_id), "records": members,
            "pattern": "IDENTICAL_REPEAT" if not differing else "CONFLICTING_VALUES",
            "differing_columns": differing,
        })

    affected_customers = {(cell(rows[n - 1], "customer_id") or "").strip() for n in row_issues} - {""}
    tags: dict[int, set[str]] = {}
    for (column, check), numbers in totals_by_check.items():
        for number in numbers:
            tags.setdefault(number, set()).add(f"{check}:{column}")
    listed = []
    for number in sorted(row_issues)[:MAX_LISTED_RECORDS]:
        row = rows[number - 1]
        listed.append({"record": number, "issues": sorted(tags[number]),
                       "order_id_masked": _mask(cell(row, "order_id") or ""),
                       "amount_state": _amount_state(cell(row, "order_total"))})

    histogram: list[dict] = []
    if valid_amounts:
        values = sorted(Decimal(a.strip()) for a in valid_amounts)
        low, high = values[0], values[-1]
        bins = 1 if low == high else HISTOGRAM_BINS
        width = (high - low) / bins if bins > 1 else Decimal(1)
        counts = [0] * bins
        for value in values:
            counts[min(int((value - low) / width), bins - 1) if bins > 1 else 0] += 1
        histogram = [{"from": f"{low + width * i:.2f}",
                      "to": f"{(low + width * (i + 1)) if bins > 1 else high:.2f}", "count": c}
                     for i, c in enumerate(counts)]

    heatmap = [{"column": column, "check": check, "records": len(numbers)}
               for (column, check), numbers in sorted(totals_by_check.items())]
    failed = report.status == "FAIL"
    return {
        "format_version": "1", "engine": "deterministic-analysis-v1",
        "row_count": len(rows), "status": report.status, "findings_truncated": truncated,
        "dimensions": dimensions,
        "impact": {
            "affected_records": len(row_issues),
            "affected_customers": len(affected_customers),
            "valid_amount_total": f"{all_valid_total:.2f}",
            "valid_amount_in_affected_records": f"{affected_total:.2f}",
            "double_count_exposure": f"{money(repeat_numbers):.2f}",
            "repeat_records": len(repeat_numbers),
            "records_without_amount": sum(1 for a in amounts if a is not None and not a.strip()),
        },
        "schema_issues": schema_issues, "heatmap": heatmap,
        "duplicate_groups": duplicate_groups, "affected_records": listed,
        "affected_records_truncated": len(row_issues) > MAX_LISTED_RECORDS,
        "amount_histogram": histogram,
        "downstream": {"dataset": "source_orders", "potential": list(downstream("source_orders")),
                       "lineage_kind": "declared_dataset_dag", "blocked_by_source": failed},
        "actions": _actions(report.status, schema_issues, totals_by_check, header,
                            {name: [row[i] for row in rows] for i, name in enumerate(header)}),
    }


def _actions(status, schema_issues, by_check, header, columns) -> list[dict]:
    """Reviewable, read-only next steps. They propose human work; nothing is applied."""
    actions: list[dict] = []

    def add(code: str, count: int, **extra) -> None:
        actions.append({"id": f"ACT-{len(actions) + 1:02d}", "code": code, "count": count,
                        "requires": "data_owner", "applies_changes": False, "status": "proposed", **extra})

    missing = [i["column"] for i in schema_issues if i["check"] == "missing_column"]
    candidates = _candidates(header, columns) if missing else {}
    for column in missing:
        if column in candidates:
            add("map_column", 1, column=column, candidate=candidates[column]["column"])
        else:
            add("restore_column", 1, column=column)
    extras = sum(1 for i in schema_issues if i["check"] == "unexpected_column")
    if extras and not candidates:
        add("review_extra_columns", extras)
    for (column, check), code in ((("order_id", "unique"), "resolve_duplicates"),
                                  (("order_total", "not_null"), "fill_missing_amounts"),
                                  (("order_total", "amount_format"), "correct_amount_format"),
                                  (("order_id", "not_null"), "fill_missing_identifiers"),
                                  (("customer_id", "not_null"), "fill_missing_customers")):
        if (column, check) in by_check:
            add(code, len(by_check[(column, check)]))
    if status == "FAIL":
        add("reinspect", 0)
    return actions
