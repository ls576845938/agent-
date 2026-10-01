# BTC-V3-RUNTIME-ARTIFACT-SOURCE-IDENTITY-CONTRACT-01

## Scope

This ticket makes source identity fail closed for three BTC research-only runtime
report builders:

- timestamp-aligned L2 capture quality;
- public WebSocket order-book replay;
- WebSocket reconnect/resync policy.

It does not change strategy, portfolio/risk, OMS/execution, fill/ledger,
promotion-gate, shared-data, backend, frontend, private endpoint, order endpoint,
paper queue, or live-order behavior.

## Contract

The shared source-identity component executes exactly:

```text
git rev-parse HEAD
```

The command must succeed and return a lowercase 40-character hexadecimal
`source_head`. The report `commit` is derived only as `source_head[:12]`.
Unknown, short, uppercase, non-hexadecimal, Git-error, prefix-mismatch, and
expected-current-HEAD-mismatch identities are rejected.

Each builder:

1. resolves the full source identity without a CLI override;
2. validates the payload identity before acquiring the artifact write lock;
3. atomically writes the report;
4. reads the persisted report back and validates the same identity again.

An identity validation failure therefore cannot acquire the artifact write lock
or replace existing evidence.

## Schema migration

The three report schemas advance from v1 to v2. Each v2 schema requires:

- `source_head` matching `^[0-9a-f]{40}$`;
- `commit` matching `^[0-9a-f]{12}$`.

The prior nine-character sample is rejected by both the shared validator and the
v2 schemas. Existing report names, CLI parameters, research-only statuses,
exit-zero status sets, blockers, and fail-closed safety flags are unchanged.

## Safety and readiness

All affected builders remain research-only. In particular:

- `contract_satisfied=false`;
- `event_ledger_feature_validation_allowed=false`;
- `true_scalping_allowed=false`;
- `candidate_generation_allowed=false`;
- `strategy_skeleton_generation_allowed=false`;
- `promotion_allowed=false`;
- `paper_review_pending_allowed=false`;
- `paper_or_live_unlock_allowed=false`;
- `paper_queue=LOCKED`;
- `live=FROZEN`.

This ticket creates no runtime-root artifact and does not by itself provide
promotion, paper, or live readiness.
