# SPDX-License-Identifier: Apache-2.0
"""Run offline acceptance from the installed wheel and print a bounded JSON report."""
import json
from pathlib import Path
import aegisflow_dr
from aegisflow_dr.advisory.qualification import qualify_operations

if Path(aegisflow_dr.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1] / 'src'):
    raise RuntimeError('Operational qualification imported source checkout')
print(json.dumps(qualify_operations(), sort_keys=True, indent=2))
