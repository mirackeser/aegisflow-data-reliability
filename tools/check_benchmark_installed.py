# SPDX-License-Identifier: Apache-2.0
"""Verify installed benchmark fixtures, scoring and CLI outside the checkout."""
import json
from pathlib import Path
import subprocess
import sys
import aegisflow_dr
from aegisflow_dr.benchmark.report import validate_report
from aegisflow_dr.benchmark.runner import evaluate_baseline

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed benchmark check imported source checkout')
report = evaluate_baseline()
completed = subprocess.run([sys.executable, '-m', 'aegisflow_dr.benchmark'],
                           capture_output=True, text=True, timeout=20, check=True)
restored = validate_report(json.loads(completed.stdout))
if restored != report or not report['regression_gate_passed']:
    raise RuntimeError('Installed benchmark reproducibility failed')
if report['splits']['validation']['metrics']['case_count'] != 8 or report['blind_holdout']:
    raise RuntimeError('Installed benchmark scope inconsistent')
print('Installed benchmark schemas, frozen fixtures, deterministic scoring and CLI passed.')

# A perfect public fixture must still be blocked by provenance/sample requirements.
from aegisflow_dr.benchmark.quality import freeze_protocol, evaluate_quality
from aegisflow_dr.benchmark.core import canonical, LABELS
cases=[{'case_id':str(i),'family':'fixture','label':LABELS[i%3]} for i in range(3)]
outputs=[{'case_id':x['case_id'],'prediction':x['label'],'unsupported_claim':False} for x in cases]
protocol=freeze_protocol(canonical(cases),model_revision_sha256='a'*64,families=('fixture',))
gate=evaluate_quality(protocol,canonical(cases),canonical(outputs),model_revision_sha256='a'*64)
if gate['decision'] != 'BLOCK' or 'PROVENANCE_NOT_APPROVED' not in gate['reasons']:
    raise RuntimeError('Installed quality gate accepted public fixture evidence')
print('Installed quality gate blocks unapproved fixture evidence.')

from tempfile import TemporaryDirectory
from uuid import uuid4
from aegisflow_dr.benchmark.protocol_store import EvaluationRegistry,register_protocol
with TemporaryDirectory() as temporary:
    path=Path(temporary)/'evaluation.db'
    digest=register_protocol(path,protocol)
    registry=EvaluationRegistry(path,expected_protocol_sha256=digest)
    run_id=str(uuid4())
    result=registry.evaluate(canonical(cases),canonical(outputs),run_id=run_id,model_revision_sha256='a'*64)
    registry.evaluate(canonical(cases),canonical(outputs),run_id=run_id,model_revision_sha256='a'*64)
    if result['decision'] != 'BLOCK' or len(registry.history()) != 1:
        raise RuntimeError('Installed registration lost blocked result or duplicated replay')
print('Installed immutable registration and blocked-result history passed.')

# Agreement is a preparation artifact; independent provenance still needs host approval.
from hashlib import sha256
from aegisflow_dr.benchmark.curation import prepare_manifest, reconcile_annotations
development=canonical([{'case_id':'development','family':'development','group_id':'development',
                        'csv_text':'id,value\n1,100\n','transform':'clean'}])
candidate=canonical([{'case_id':'candidate','family':'candidate','group_id':'candidate',
                      'csv_text':'id,value\n2,200\n','transform':'clean'}])
manifest=prepare_manifest(development,candidate)
digest=sha256(manifest).hexdigest()
reviewers=('reviewer-a','reviewer-b')
annotations=tuple(canonical({'version':'1','reviewer_id':reviewer,'manifest_sha256':digest,
                            'labels':[{'case_id':'candidate','label':LABELS[0]}]}) for reviewer in reviewers)
consensus=reconcile_annotations(manifest,annotations,expected_manifest_sha256=digest,reviewer_ids=reviewers)
if consensus['status'] != 'AGREED' or len(consensus['cases']) != 1:
    raise RuntimeError('Installed curation consensus failed')
print('Installed label-free manifest and exact dual-review reconciliation passed.')
