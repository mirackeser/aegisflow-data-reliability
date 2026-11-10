# ADR-0002: Build evidence-producing deterministic diagnostics first

Status: accepted for the research baseline. Date: 2026-11-10.

The architecture requires specialists to use reliable tools. Implementing agent dialogue before a real data contract would make results difficult to verify. The first vertical increment therefore covers synthetic orders, controlled faults and byte-bound diagnostic evidence.

The baseline accepts UTF-8 CSV with unique column names and exactly the order contract columns. Column order may vary. Required fields must be nonempty; order IDs must be unique after whitespace trimming. Amounts are nonnegative base-10 values with at most two fractional digits and twelve integer digits. Exponents and special numeric values are invalid. Monetary arithmetic uses Decimal, never binary float.

Input is limited to 1000000 bytes and 10000 logical records. Reports retain at most 100 findings while preserving the total violation count and an explicit truncation flag. Oversize or malformed inputs produce an input-rejected outcome, never a partial successful report. Missing/extra columns and empty datasets are quality failures. Aggregates are published only for a passing dataset.

Evidence uses SHA-256 of exact source bytes and 1-based logical CSV record numbers excluding the header. Repeated runs are identical for identical input. This binds observations to supplied bytes; it does not attest source authenticity, prove causal relationships or provide immutable enterprise storage.

No source connector, SQL executor, LLM, automatic remediation or claimed specialist implementation is added. The clean/fault demos are development regressions, not held-out evaluation evidence.
