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
