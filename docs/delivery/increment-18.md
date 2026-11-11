# Increment 18 — Cooperative stream deadlines, cancellation and bounds

Delivered a synchronous-worker bridge for owned cooperative async generators, bounded aggregate bytes/frame count, final trusted usage, shared deadline, guaranteed source-close attempts and conservative timeout/cancellation accounting. No network provider is configured. See [ADR-0018](../adr/0018-bounded-cooperative-stream.md) for the exact trust and cancellation limits.

Validation: 412 application + 13 security/hygiene tests = 425 distinct passing methods. Sixteen new stream tests; stream and existing critical statement/branch gates remain 100%. Nine installed checks include fragmented success and actual timeout cleanup with retained usage holds. Dependency, candidate/PDF and full-history CI security checks remain release gates.

Location: stage B of the 84-work-package roadmap; B01/B02 local foundations delivered, B03 partial, B04 local cooperative boundary delivered, B05 classification delivered. This is development increment 18, not work package 18/84. Next: B06 bounded retry/backoff; real provider transport, sealed evaluation and UI remain gated.
