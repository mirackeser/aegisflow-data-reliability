# ADR-0004: Enforce tool contracts before agent orchestration

Status: accepted for the local baseline. Date: 2026-11-10.

The gateway accepts a closed ToolRequest contract with an exact tool, dataset, optional CSV text and packaged transform selection. Unknown fields, wrong types and invalid argument combinations are rejected. Frozen ToolPolicy grants exact tool/dataset pairs and configures bounded bytes, calls and a monotonic session deadline. The trusted host constructs the policy; agent requests cannot override it.

Denied or invalid requests never dispatch a tool. Calls are reserved under a lock before dispatch, so concurrent callers cannot overspend a session's call budget. Admitted tool attempts consume a call even when the tool fails; invalid, denied and oversized requests are not charged. Budget and deadline violations produce explicit non-success outcomes. A tool's quality FAIL or BLOCKED remains a tool report with transport outcome OK, preserving the distinction between a valid finding and an execution failure.

Deadlines are cooperative checks before and after execution. An overrun's output is discarded; Python execution is not forcibly stopped. Existing deterministic tools independently bound input bytes/rows/findings. Hard resource isolation, authentication, tenant authorization, cross-process quota storage and durable audit are not implemented. Trusted Python code can call diagnostic functions directly; this gateway is not a security boundary against compromised host code. A new gateway creates a new session budget, so a future server must own session lifecycle and prevent agent-controlled resets.

Allowed tools: diagnose_csv and run_batch on source_orders; query_lineage on explicitly granted known datasets. No arbitrary SQL, file paths, network destinations or production-write tool is accepted. Gateway results contain sanitized error categories rather than raw exceptions. All 36 agent roles remain planned.
