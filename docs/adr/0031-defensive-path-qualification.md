# ADR-0031: Close A04 with negative and rollback qualification

Status: Accepted; PR and post-merge main evidence records delivery.

Increment 30 identified 40 uncovered statements and 33 uncovered branch exits, primarily in retained-evidence guards and CLI/error handling. Add 21 test methods targeting the corresponding failure invariants rather than changing product behavior to improve coverage.

Retained trace tests reject malformed/noncanonical policy grants, contradictory status, invalid trace shape, unknown tools, forged tool hashes, changed diagnosis/source evidence, duplicate batches, continued execution after failure, invalid failure outcomes, insufficient call accounting and orphan snapshots. Retained storage tests rewrite actual temporary database records with recomputed checksums to exercise semantic checks beyond simple hash failure. They reject substituted run sources, excess artifacts, incomplete evidence, false report/source binding, claim identity replacement and rehashed invalid lifecycle/event content.

Migration fault injection appends an incomplete DDL statement after real v2 DDL and verifies rollback of both schema and version. CLI tests exercise initialization, migration, read/closure round-trip, evaluation success/failure and entrypoint/import boundaries. Additional boundaries reject an untrusted tool policy, invalid suite/catalog claims, unexpected tool snapshots and an injected decimal-processing failure before downstream work.

No new application defect was reproduced in these cases. Initial test-fixture assumptions were corrected: serialized retained grants are lists and a clean investigation has two successful steps. Test fixtures reuse existing synthetic setup/tampering helpers without importing test classes into discovery. Product modules, original data/SQL, hashes and archived source/PDF remain unchanged.

Full application coverage reaches 3,542/3,542 statements and 1,068/1,068 branch exits, with no coverage exclusions added. Enforce 100% combined coverage in every CI Python job in addition to existing critical gates. Coverage measures executed statements/branch exits, not all possible paths, conditions or requirements. Explicit exceptions/failure injections are contract tests, not real disk corruption or an exhaustive filesystem fault campaign.

A04's previously recorded coverage gap is closed for this code revision. This does not complete authentication, protected storage, live provider transport/accounting, independent evaluation or production security/load/recovery operations. Future code must preserve the coverage gate and meaningful negative assertions; model accuracy remains separately qualified on independent data.
