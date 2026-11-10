# SPDX-License-Identifier: Apache-2.0
"""Development-only orchestration regressions; not model accuracy measurement."""
from importlib.resources import files
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from .batch import TRANSFORMS
from .investigation import default_policy, investigate
from .storage import IncidentStore, initialize
from .storage.store import sha


def evaluate_development_suite() -> dict:
    raw = files('aegisflow_dr').joinpath('data/investigation-development-v1.json').read_bytes()
    suite = json.loads(raw)
    if (type(suite) is not dict or set(suite) != {'suite_id', 'suite_kind', 'cases'}
            or suite['suite_kind'] != 'development_regression'
            or suite['suite_id'] != 'investigation-development-v1'
            or type(suite['cases']) is not list or not 1 <= len(suite['cases']) <= 50):
        raise ValueError('Invalid development suite')
    seen = set()
    # Validate the entire suite before opening a store or running any scenario.
    for case in suite['cases']:
        if (type(case) is not dict or set(case) != {
                'case_id', 'csv_text', 'transform', 'expected_assessment', 'expected_tools'}
                or type(case['case_id']) is not str
                or not re.fullmatch(r'[a-z0-9-]{1,64}', case['case_id'])
                or case['case_id'] in seen or type(case['csv_text']) is not str
                or type(case['transform']) is not str or case['transform'] not in TRANSFORMS
                or type(case['expected_assessment']) is not str
                or case['expected_assessment'] not in {
                    'NO_FAILURE_OBSERVED', 'SOURCE_QUALITY_FAILURE',
                    'TRANSFORMATION_RECONCILIATION_FAILURE'}
                or type(case['expected_tools']) is not list
                or not 1 <= len(case['expected_tools']) <= 3
                or any(type(tool) is not str or tool not in {
                    'diagnose_csv', 'run_batch', 'query_lineage'} for tool in case['expected_tools'])):
            raise ValueError('Invalid development case')
        seen.add(case['case_id'])
    results = []
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / 'evaluation.db'
        initialize(path)
        store = IncidentStore(path)
        for case in suite['cases']:
            record = store.record(case['csv_text'].encode('utf-8'), request_key=case['case_id'])
            # Expected labels are used only AFTER execution, never as planner input.
            result = investigate(store, record['incident_id'], default_policy(), transform=case['transform'])
            actual_tools = [step.tool for step in result.steps]
            matched = (result.status == 'COMPLETED'
                       and result.assessment == case['expected_assessment']
                       and actual_tools == case['expected_tools'])
            results.append({'case_id': case['case_id'], 'status': result.status,
                            'expected_assessment': case['expected_assessment'],
                            'actual_assessment': result.assessment,
                            'expected_tools': case['expected_tools'], 'actual_tools': actual_tools,
                            'calls_used': result.calls_used, 'matched': matched,
                            'workflow_version': result.workflow_version,
                            'implementation_sha256': result.implementation_sha256,
                            'policy_sha256': result.policy_sha256, 'source_sha256': result.source_sha256})
    return {'suite_id': suite['suite_id'], 'suite_kind': suite['suite_kind'],
            'suite_sha256': sha(raw), 'cases': results,
            'matching_cases': sum(result['matched'] for result in results),
            'case_count': len(results), 'all_matched': all(result['matched'] for result in results),
            'model_calls': 0, 'held_out_benchmark': False}
