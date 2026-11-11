# SPDX-License-Identifier: Apache-2.0
"""Offline baseline execution with label-free inputs and post-execution scoring."""
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from ..investigation import default_policy, investigate
from ..storage import IncidentStore, initialize
from .core import LABELS, canonical, load_suite, score
from .report import validate_report


def _execute(csv_text, transform):
    try:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'baseline.db'
            initialize(path)
            store = IncidentStore(path)
            saved = store.record(csv_text.encode('utf-8'), request_key='baseline')
            result = investigate(store, saved['incident_id'], default_policy(), transform=transform)
            label = result.assessment if result.status == 'COMPLETED' else 'ABSTAIN'
            if label not in (*LABELS, 'ABSTAIN'):
                label = 'ERROR'
            return label, [step.tool for step in result.steps], result.implementation_sha256, result.policy_sha256
    except (ValueError, OSError, sqlite3.DatabaseError):
        return 'ERROR', [], None, None


def evaluate_baseline():
    suite, digest = load_suite()
    predictions, implementations, policies = [], set(), set()
    for case in suite['cases']:
        # Project only operational inputs: no labels, split, group or family reach execution.
        label, tools, implementation, policy = _execute(case['csv_text'], case['transform'])
        predictions.append({'case_id': case['case_id'], 'assessment': label, 'tools': tools})
        if implementation is not None:
            implementations.add(implementation)
            policies.add(policy)
    measured = score(suite, predictions)
    # Frozen regression rule, not a production/model acceptance threshold.
    passed = all(part['metrics']['correct'] == part['metrics']['case_count']
        and part['metrics']['tool_sequence_matches'] == part['metrics']['case_count']
        for part in measured.values())
    root = files('aegisflow_dr.benchmark')
    scorer_digest = sha256(canonical({name: sha256(root.joinpath(name).read_bytes()).hexdigest()
                                     for name in ('core.py', 'runner.py', 'report.py')})).hexdigest()
    return validate_report({'version': '1', 'suite_id': suite['suite_id'], 'suite_sha256': digest,
        'scorer_sha256': scorer_digest, 'implementation_sha256': sorted(implementations),
        'policy_sha256': sorted(policies), 'model_calls': 0, 'blind_holdout': False,
        'scope': 'public_synthetic_deterministic_validation', 'splits': measured,
        'predictions': predictions, 'regression_gate_passed': passed})
