# ADR-0030: Verify benchmark report semantics, not only shape

Status: Accepted; exact-revision PR and main evidence records delivery.

## Reproduced defect

The public deterministic benchmark scorer calculated correct metrics, but `validate_report` checked only the closed JSON Schema. Changing the validation split's `correct` count to zero while leaving other metrics and a passing regression gate unchanged was accepted. This could allow inconsistent imported research reports even though the scorer itself was correct. The separate registered model-quality v1/v2 evaluator already recomputes counts and is not changed by this fix.

## Decision

Bind report validation to the packaged frozen suite digest, require exact prediction coverage, recompute overall/class/family metrics from the supplied predictions and require the saved splits and gate to match. Preserve valid non-passing reports. Reuse the existing scorer without executing a model or pipeline during validation. No report fields or exported v1 schema are changed; previously schema-valid but inconsistent reports are deliberately rejected.

This checks consistency against the installed frozen public suite, not authenticated execution. A caller can fabricate predictions and matching metrics; source/scorer/implementation hash fields do not alone attest actual execution. Historical reports with other suite versions need their matching validator. Future provenance/identity and independently protected evaluation remain necessary. Public synthetic report agreement is not measured model accuracy.

## Verification and QA scope

Six new methods cover forged overall counts/rates, family/class metrics, gate changes, suite digest/prediction coverage, changed predictions with stale versus recomputed metrics and validation without input mutation. An installed-package check rejects a forged count. The label-isolation unit test now supplies its intentionally modified suite to both mocked suite readers; normal production validation always loads the packaged suite.

Full application tests, security tooling, dependency consistency/audit, critical coverage, installed distribution checks, CLI scenarios, local mTLS/A2A/MCP and advisory simulations apply. Documentation review corrected stale live-milestone, agent dispatcher and LLM status descriptions; historical verification snapshots remain labeled historical.

Whole-application defensive gaps remain A04: 40 statements and 33 branch exits are not covered in this run. Critical modules retain 100% statement/branch gates. Test success does not establish complete requirements coverage, production penetration/load/chaos readiness, authenticated curators, encrypted storage or real model quality. No UI or new external authority is introduced.
