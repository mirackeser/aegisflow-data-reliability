# SPDX-License-Identifier: Apache-2.0
"""Bounded deterministic investigations over retained source evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from importlib.resources import files
import json
import re
import sqlite3
from time import monotonic
from typing import Callable

from .batch import STAGING_CONTRACT, TRANSFORMS, downstream
from .gateway import ToolGateway, ToolPolicy, ToolRequest, ToolResult
from .storage import IncidentStore, StoreError
from .storage.store import canonical, engine_fingerprint, sha

VERSION = 'bounded-investigation-v1'
FAILURES = frozenset({'DENIED', 'INVALID_REQUEST', 'BUDGET_EXCEEDED',
                      'DEADLINE_EXCEEDED', 'INPUT_REJECTED', 'TOOL_ERROR'})


def default_policy() -> ToolPolicy:
    return ToolPolicy(frozenset({('diagnose_csv', 'source_orders'),
                                 ('run_batch', 'source_orders'),
                                 ('query_lineage', 'source_orders'),
                                 ('query_lineage', 'customer_sales')}), max_calls=3)


@dataclass(frozen=True)
class Step:
    tool: str
    dataset: str
    outcome: str
    report_sha256: str | None = None
    report: dict | None = None


@dataclass(frozen=True)
class Observation:
    dataset: str
    check: str
    evidence_sha256: tuple[str, ...]


@dataclass(frozen=True)
class Investigation:
    incident_id: str
    source_sha256: str | None
    status: str
    assessment: str | None
    reason: str | None
    calls_used: int
    steps: tuple[Step, ...]
    observations: tuple[Observation, ...]
    policy_sha256: str
    implementation_sha256: str
    workflow_version: str = VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, indent=2)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError('Evidence contract mismatch')


def _hash(value) -> bool:
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _validate_batch(report: dict, source: dict, transform_hash: str) -> None:
    _require(set(report) == {'status', 'source_check', 'artifacts', 'reconciliation',
                             'affected_dataset', 'potential_downstream', 'transform_sha256',
                             'format_version', 'engine'})
    _require(report['format_version'] == '1' and report['engine'] == 'sqlite-memory-batch-v1')
    _require(canonical(report['source_check']) == canonical(source))
    _require(report['transform_sha256'] == transform_hash)
    artifacts = report['artifacts']
    _require(type(artifacts) is list and len(artifacts) == 3)
    for artifact, name in zip(artifacts, ('source_orders', 'staging_orders', 'customer_sales')):
        _require(type(artifact) is dict and set(artifact) == {
            'dataset', 'sha256', 'row_count', 'upstream_sha256', 'transform_sha256'})
        _require(artifact['dataset'] == name and _hash(artifact['sha256']))
        _require(type(artifact['row_count']) is int and 0 <= artifact['row_count'] <= source['row_count'])
    original, staging, mart = artifacts
    _require(original['sha256'] == source['source_sha256']
             and original['row_count'] == staging['row_count'] == source['row_count']
             and original['upstream_sha256'] is None and original['transform_sha256'] is None)
    _require(staging['upstream_sha256'] == original['sha256']
             and staging['transform_sha256'] == sha(STAGING_CONTRACT))
    _require(mart['upstream_sha256'] == staging['sha256']
             and mart['transform_sha256'] == transform_hash)
    checks = report['reconciliation']
    _require(type(checks) is list and len(checks) == 2)
    expected = (source['row_count'], int(Decimal(source['total_valid_amount']) * 100))
    for check, name, value in zip(checks, ('order_count', 'amount_cents'), expected):
        _require(type(check) is dict and set(check) == {
            'check', 'expected', 'actual', 'passed', 'evidence_sha256'})
        _require(check['check'] == name and type(check['expected']) is int and check['expected'] == value)
        _require(type(check['actual']) is int and check['actual'] >= 0)
        _require(type(check['passed']) is bool and check['passed'] == (value == check['actual']))
        _require(check['evidence_sha256'] == [staging['sha256'], mart['sha256']])
    _require(mart['row_count'] <= checks[0]['actual']
             and (mart['row_count'] == 0) == (checks[0]['actual'] == 0))
    failed = any(not check['passed'] for check in checks)
    _require(report['status'] == ('FAIL' if failed else 'PASS'))
    _require(report['affected_dataset'] == ('customer_sales' if failed else None))
    _require(report['potential_downstream'] == (list(downstream('customer_sales')) if failed else []))


def investigate(store: IncidentStore, incident_id: str, policy: ToolPolicy, *,
                transform: str = 'clean', clock: Callable[[], float] = monotonic) -> Investigation:
    """Read retained context and execute at most diagnosis, batch and impact tools.

    This workflow makes observations, never causal claims or probability estimates.
    It does not change the source incident or persist the returned workflow trace.
    """
    if (type(incident_id) is not str
            or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', incident_id)
            or type(policy) is not ToolPolicy or type(transform) is not str or transform not in TRANSFORMS):
        raise ValueError('Invalid investigation request')
    policy_hash = sha(canonical({'grants': sorted(policy.grants), 'max_calls': policy.max_calls,
                                 'max_input_bytes': policy.max_input_bytes,
                                 'timeout_seconds': policy.timeout_seconds}))
    module_hashes = {name: sha(files('aegisflow_dr').joinpath(name).read_bytes())
                     for name in ('investigation.py', 'batch.py', 'gateway.py', 'storage/store.py')}
    transform_hash = sha(files('aegisflow_dr').joinpath('sql', TRANSFORMS[transform]).read_bytes())
    implementation_hash = sha(canonical({**module_hashes, 'source_engine': engine_fingerprint(),
                                         'sql': transform_hash}))
    steps: list[Step] = []
    source_hash = None
    gateway = ToolGateway(policy, clock=clock)

    def finish(assessment=None, reason=None, observations=()):
        return Investigation(incident_id, source_hash, 'INCONCLUSIVE' if reason else 'COMPLETED',
                             assessment, reason, gateway.calls_used, tuple(steps), tuple(observations),
                             policy_hash, implementation_hash)

    try:
        snapshot = store.source_snapshot(incident_id)
    except (StoreError, OSError, sqlite3.DatabaseError):
        return finish(reason='SOURCE_UNAVAILABLE')
    source_hash = sha(snapshot.payload)
    if snapshot.engine_fingerprint != engine_fingerprint():
        return finish(reason='VERSION_MISMATCH')

    def call(tool, dataset, validator):
        request = ToolRequest(tool, dataset,
                              snapshot.payload.decode('utf-8') if tool != 'query_lineage' else None,
                              transform if tool == 'run_batch' else 'clean')
        try:
            result = gateway.execute(request)
        except Exception:
            steps.append(Step(tool, dataset, 'TOOL_ERROR'))
            return None
        if type(result) is not ToolResult or type(result.outcome) is not str:
            steps.append(Step(tool, dataset, 'INVALID_EVIDENCE'))
            return None
        if result.outcome != 'OK':
            steps.append(Step(tool, dataset,
                              result.outcome if result.outcome in FAILURES else 'INVALID_EVIDENCE'))
            return None
        try:
            _require(type(result.report) is dict)
            report_bytes = canonical(result.report)
            report = json.loads(report_bytes)
            validator(report)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError):
            steps.append(Step(tool, dataset, 'INVALID_EVIDENCE'))
            return None
        steps.append(Step(tool, dataset, 'OK', sha(report_bytes), report))
        return report

    def validate_source(report):
        _require(canonical(report) == snapshot.report_json)
        _require(report['source_sha256'] == source_hash)

    source = call('diagnose_csv', 'source_orders', validate_source)
    if source is None:
        return finish(reason=steps[-1].outcome)
    observations = [Observation('source_orders', 'source_contract_' + source['status'].lower(),
                                (source_hash, steps[-1].report_sha256))]
    if source['status'] == 'FAIL':
        affected, assessment = 'source_orders', 'SOURCE_QUALITY_FAILURE'
    else:
        batch = call('run_batch', 'source_orders', lambda report: _validate_batch(report, source, transform_hash))
        if batch is None:
            return finish(reason=steps[-1].outcome)
        observations.append(Observation('customer_sales', 'reconciliation_' + batch['status'].lower(),
                                         (source_hash, steps[-1].report_sha256)))
        if batch['status'] == 'PASS':
            return finish(assessment='NO_FAILURE_OBSERVED', observations=observations)
        affected, assessment = 'customer_sales', 'TRANSFORMATION_RECONCILIATION_FAILURE'
    expected_impact = {'dataset': affected, 'potential_downstream': list(downstream(affected)),
                       'lineage_kind': 'declared_dataset_dag'}
    impact = call('query_lineage', affected, lambda report: _require(report == expected_impact))
    if impact is None:
        return finish(reason=steps[-1].outcome)
    observations.append(Observation(affected, 'declared_potential_impact',
                                     (source_hash, steps[-1].report_sha256)))
    return finish(assessment=assessment, observations=observations)
