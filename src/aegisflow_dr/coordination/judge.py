# SPDX-License-Identifier: Apache-2.0
"""Independent deterministic assessment gate, not an LLM or causal judge."""
from decimal import Decimal

from ..batch import downstream
from ..storage.store import canonical, sha
from .contracts import encode, parse


def abstain(run_id: str) -> dict:
    return _verdict(run_id, 'ABSTAIN', 'RUN_UNAVAILABLE', None, None)


def _verdict(run_id, decision, reason, assessment, record_hash):
    value = {'version': '1', 'run_id': run_id, 'decision': decision, 'reason': reason,
             'assessment': assessment, 'reviewer': 'A27', 'mode': 'deterministic',
             'record_sha256': record_hash}
    return parse('verdict', encode('verdict', value))


def _derive(record):
    """Derive an assessment from evidence values, never from trace.assessment."""
    trace = record['trace']
    steps = trace['steps']
    if trace['status'] != 'COMPLETED' or not steps or any(s['outcome'] != 'OK' for s in steps):
        return None, 'INCOMPLETE', set()
    source_hash = record['manifest']['source_sha256']
    evidence = {source_hash}
    if (trace['source_sha256'] != source_hash or trace['incident_id'] != record['manifest']['request']['incident_id']
            or sha(canonical(trace)) != record['manifest']['trace_sha256']):
        raise ValueError('Invalid trace reference')
    for step in steps:
        if sha(canonical(step['report'])) != step['report_sha256']:
            raise ValueError('Invalid report reference')
        evidence.add(step['report_sha256'])
    source = steps[0]['report']
    path = [(step['tool'], step['dataset']) for step in steps]
    if (path[0] != ('diagnose_csv', 'source_orders') or source['source_sha256'] != source_hash
            or source['status'] not in {'PASS', 'FAIL'}):
        raise ValueError('Invalid source evidence')
    if source['status'] == 'FAIL':
        expected, affected = 'SOURCE_QUALITY_FAILURE', 'source_orders'
        required = [('diagnose_csv', 'source_orders')]
    else:
        if len(steps) < 2 or path[1] != ('run_batch', 'source_orders'):
            raise ValueError('Missing batch evidence')
        batch = steps[1]['report']
        if canonical(batch['source_check']) != canonical(source):
            raise ValueError('Batch source differs')
        expected_values = (source['row_count'], int(Decimal(source['total_valid_amount']) * 100))
        checks = batch['reconciliation']
        if type(checks) is not list or len(checks) != 2:
            raise ValueError('Incomplete reconciliation')
        passed = []
        for check, name, value in zip(checks, ('order_count', 'amount_cents'), expected_values):
            if (check['check'] != name or type(check['expected']) is not int or check['expected'] != value
                    or type(check['actual']) is not int or check['actual'] < 0
                    or type(check['passed']) is not bool or check['passed'] != (check['actual'] == value)):
                raise ValueError('Contradictory reconciliation')
            passed.append(check['actual'] == value)
        failed = not all(passed)
        if batch['status'] != ('FAIL' if failed else 'PASS'):
            raise ValueError('Contradictory batch status')
        expected = 'TRANSFORMATION_RECONCILIATION_FAILURE' if failed else 'NO_FAILURE_OBSERVED'
        affected = 'customer_sales' if failed else None
        required = [('diagnose_csv', 'source_orders'), ('run_batch', 'source_orders')]
    if affected:
        required.append(('query_lineage', affected))
        impact = steps[-1]['report']
        if impact != {'dataset': affected, 'potential_downstream': list(downstream(affected)),
                      'lineage_kind': 'declared_dataset_dag'}:
            raise ValueError('Invalid impact evidence')
    if path != required or trace['assessment'] != expected:
        raise ValueError('Contradictory workflow')
    return expected, None, evidence


def review(record: dict, proposal: dict) -> dict:
    """record must come from InvestigationRuns.read in the trusted host."""
    proposal = parse('proposal', encode('proposal', proposal))
    run_id = proposal['run_id']
    record_hash = sha(canonical(record))
    try:
        if (record['run_id'] != run_id or record['manifest']['request']['incident_id'] != proposal['incident_id']):
            raise ValueError('Cross-context proposal')
        expected, reason, evidence = _derive(record)
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError):
        return _verdict(run_id, 'ABSTAIN', 'INVALID_EVIDENCE', None, record_hash)
    if reason:
        return _verdict(run_id, 'ABSTAIN', reason, None, record_hash)
    if set(proposal['evidence_sha256']) != evidence:
        return _verdict(run_id, 'REJECT', 'EVIDENCE_MISMATCH', expected, record_hash)
    matched = proposal['assessment'] == expected
    return _verdict(run_id, 'ACCEPT' if matched else 'REJECT',
                    'MATCH' if matched else 'CONTRADICTION', expected, record_hash)
