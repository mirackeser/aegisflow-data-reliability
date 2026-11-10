# Reliability gates before model claims

Status: evaluation requirements, not implemented model benchmark results.

No model accuracy percentage is claimed by the current deterministic baseline. Passing software regression tests establishes behavior on those cases; it does not establish root-cause accuracy on unseen failures.

Before model-driven investigation is accepted:

1. Freeze ground-truth root causes, affected datasets and acceptable evidence references independently of model output. Keep clean/no-fault and insufficient-evidence cases in the evaluation, not only injected failures.
2. Split development and held-out cases by pipeline, failure template and scenario family. Never use the held-out set to tune prompts, routing or thresholds. Preserve dataset/split hashes and label versions.
3. Record model identifier, prompt and tool contract versions, routing policy, budgets and input/evidence versions for every run. Reruns of a changed implementation are new experiments, not replacements for failed history.
4. Measure root-cause Top-1/Top-3 results separately from evidence precision, unsupported-claim rate, abstention/coverage, tool failures, latency and cost. A system that abstains on every hard case must not appear accurate by omitting those cases.
5. Evaluate claim support against retained source and diagnostic evidence; an existing evidence ID proves traceability, not semantic support. Distinguish observation, hypothesis, counter-hypothesis and verified finding explicitly.
6. Compare deterministic, single-agent, static and dynamic multi-agent approaches on the same held-out cases and allowed tools. Repeat stochastic runs with recorded settings and report uncertainty and failure-family breakdowns.
7. Define acceptance thresholds and regression tolerances before final evaluation. Keep unsupported results inconclusive; do not optimize a single accuracy number at the expense of evidence quality or unsafe tool behavior.

These gates precede the web interface and any enterprise pilot. Durable source evidence is the current prerequisite; semantic verification, model benchmarking and batch-evidence persistence remain separate deliverables.
