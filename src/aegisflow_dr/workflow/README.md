# Durable local review execution

model defines bounded state and retry policies; schema creates a separate queue database; queue owns transactional reservations, history and result fencing; worker executes read-only A26/A27 slices outside write transactions; cli exposes explicit operator commands. Source/run evidence remains owned by storage and is not migrated by this package. See ADR-0009 and docs/contracts/durable-review-v1.md for guarantees and limits. No remote transport or background worker is enabled.
