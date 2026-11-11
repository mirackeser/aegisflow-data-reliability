# SPDX-License-Identifier: Apache-2.0
from .runner import evaluate_baseline
from .core import canonical

if __name__ == '__main__':
    report = evaluate_baseline()
    print(canonical(report).decode())
    raise SystemExit(0 if report['regression_gate_passed'] else 1)
