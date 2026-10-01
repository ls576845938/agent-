# Shared Platform V2 Contract

## Boundary

`quant_shared` is an asset-neutral infrastructure kernel. It may be imported by
asset domains, but it must not import `quant_us`, `quant_crypto`, `backend`, or
`frontend`.

The shared kernel owns only:

- UTC normalization and canonical serialization/hash;
- stable namespaced identity;
- immutable evidence references, publication, and freshness assessment;
- generic append-only ledger records and fingerprint reconciliation;
- deterministic replay over explicitly injected snapshots and events;
- backtest identity and evidence validation;
- immutable read-model projection envelopes;
- the pre-existing shared forecasting API.

It does not own asset enums, venue state, lifecycle state, broker adapters,
execution routing, funding, liquidation, or domain strategy rules. It exposes
no submission, cancellation, queue-write, paper, or live capability.

## Dependency direction

Asset domain -> adapter/service -> `quant_shared`

`quant_shared` -> Python standard library only, except the existing optional
forecasting adapter dependency boundary.

Consumers must adapt domain-specific records into shared envelopes. A shared
contract change does not authorize modifying consumer code; consumer wiring
requires an integrator ticket and a validated committed handoff.

## Evidence and state

Evidence run paths are immutable. Re-publishing identical bytes is idempotent;
re-publishing different bytes to the same path fails closed. Freshness requires
availability, bounded age, current code binding, and dependency timestamps no
newer than the consumer.

Ledger contracts are generic append-only records. Replay accepts only injected
history with a fixed clock and random seed. Read models are derived projections,
not sources of truth. Backtest evidence must retain cost/slippage rules,
walk-forward and no-lookahead checks, ledger reconciliation, replay binding, and
current-HEAD binding.

## Safety

This package cannot unlock promotion or expose paper/live/private/order
capabilities. Those decisions remain in asset-domain service and governance
layers. All such safety flags remain false for this ticket.
