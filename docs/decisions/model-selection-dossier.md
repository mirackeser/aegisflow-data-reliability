# Model selection dossier (work package C04 preparation)

Status: **proposal for operator decision. No model has been downloaded, installed or run.**
Budget: USD 0. Nothing here authorises spending, a paid API, or a download.

## Why this decision is on the critical path

AegisFlow currently has no model. Root-cause inference, model accuracy and calibrated confidence therefore do not exist and are not claimed. Work packages C05–C08 (integration, measurement, calibration, acceptance) cannot start until (1) a model is approved and (2) a held-out labelled evaluation set exists (C01–C02).

## Constraints of the current environment

| Item | Value (measured in the build sandbox) |
|---|---|
| CPU | 2 cores, x86_64 |
| RAM | about 7 GB |
| GPU | none |
| Disk free | about 30 GB |
| huggingface.co / ollama.com | unreachable from the shell (HTTP 000) |

Consequences: models cannot be downloaded here, and anything above roughly 7–8B parameters at 4-bit will not fit comfortably in 7 GB. Real measurement therefore needs either the operator's own machine or an explicitly approved free/hosted option. The sandbox can only run the deterministic harness.

## Candidate families and licences

Licence facts come from third-party summaries (listed below) and **must be re-checked against each model card before adoption**. Memory sizes for small models were not stated in the sources and are not asserted here.

| Family | Licence reported | Commercial-use notes reported | Fit |
|---|---|---|---|
| Gemma 4 (E2B, E4B, 12B, 26B-A4B, 31B) | Apache 2.0 | none listed | E2B/E4B are plausible for 7 GB RAM; larger ones are not. Gemma 1–3 use the Gemma Terms of Use (output-distillation restriction), so avoid those. |
| Ministral 3 / Mistral Small 4 | Apache 2.0 | none listed | Ministral 3 is the small candidate; Small 4 is likely too large for this sandbox. |
| Qwen 3.6 / 3.8 (27B, 35B-A3B) | Apache 2.0 | none listed | About 17–22 GB at 4-bit per the source, so too large for the sandbox; needs the operator's machine. Other Qwen releases carry custom licences (research-only or revenue-gated), so check per model. |
| Llama 4 | Llama 4 Community License | "Built with Llama" notice, naming rule, 700M MAU cap, EU multimodal clause | Not preferred: attribution and naming obligations, EU clause, and large size. |
| DeepSeek V4 | MIT | notice retention only | Large; not feasible locally here. |

Apache 2.0 and MIT are preferred because the project is Apache-2.0 and may be used inside a holding company.

## Recommendation

1. Shortlist two small Apache-2.0 models that fit 7 GB, one from the Gemma 4 small tier and one from Ministral 3, plus one larger Apache-2.0 model (Qwen 3.6-27B class) as an upper reference if the operator's hardware allows.
2. Run all candidates through the same harness with schema-constrained output, thinking disabled where the runtime supports it (one source reports JSON landing in a reasoning field otherwise).
3. Pick by measured results on the held-out set, not by vendor benchmarks.

This ordering is a hypothesis to test, not a result.

## Evaluation protocol (to be built in C02/C05–C07)

- **Data:** labelled scenarios with known root causes, split into development and a sealed held-out set that is never used for prompt tuning. Real data requires the operator's consent; synthetic data is labelled synthetic and is a regression guard only.
- **Metrics:** valid-JSON/schema rate, root-cause top-1 and top-3 accuracy, citation validity (every cited passage verifies), abstention rate and correctness when evidence is insufficient, calibration (expected calibration error, reliability bins), latency and memory on the target machine.
- **Statistics:** Wilson 95% intervals for every rate; report sample size; no claim is made from overlapping intervals.
- **Judge:** the deterministic Judge stays authoritative for structure and citation checks. Passing it is not evidence of model accuracy.
- **Acceptance (C08):** thresholds are set by the operator **before** the held-out run, then reported as pass/fail with intervals. An accuracy figure is published only after that run.

## Decisions requested from the operator

1. Where may a model run? (a) the operator's own machine, (b) another free option the operator approves explicitly. No paid service will be used.
2. Approval to download one or more shortlisted models (state which and the maximum size).
3. Whether real labelled data may be provided for the held-out set (C01–C02), and under what handling rules.

## Sources

- InsiderLLM, "Best Local LLMs for Structured Output" — https://insiderllm.com/guides/structured-output-local-llms/
- WZ-IT, "Open LLM licences for commercial use" — https://wz-it.com/en/knowledge/ki/open-llm-licenses-commercial-use/
