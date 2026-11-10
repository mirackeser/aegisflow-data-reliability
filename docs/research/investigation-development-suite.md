# Investigation development regressions

The versioned 10-case suite covers clean orders, schema rename, null total, duplicate ID, invalid decimal, empty data, zero values, filtering regression, zero-value record loss and BOM/reordered columns. Cases use explicit CSV inputs and independently declared expected assessments/tool paths. Expected labels are never passed to the investigator.

Run `PYTHONPATH=src python3 -m aegisflow_dr evaluate-investigation`. Exit 0 means every expected behavior matched; exit 1 means disagreement. The report includes suite, source, implementation and policy fingerprints, actual/expected paths, call counts and explicit `held_out_benchmark: false` / `model_calls: 0` markers.

This suite is deliberately visible to developers and used for regression development. Do not quote its agreement as unseen-failure accuracy, calibrated confidence or evidence of multi-agent improvement. The independent evaluation and model reliability gates in reliability-gates.md still apply. Denial, time/budget failures and forged evidence are exercised separately in unit/integration tests rather than hidden from a model benchmark denominator.
