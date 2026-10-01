# BTC V3 Shared Boundary Adoption 01

## Scope and base

- Role: `btc_developer`
- Goal: `BTC-V3-SHARED-BOUNDARY-ADOPTION-01`
- Base/main: `07e32a043a3fd48e5b50f67dd90ed59679bf6af7`
- Governance ancestor: `5ed06e2e7bbb271e92dbe36eff523424528d7c57`
- Shared prerequisite:
  `integrated-shared-platform-v2-current-main-01-batch-02-takeover`
  validated on current main before implementation.
- Excluded: `quant_shared`, `quant_us`, shared schema/enums, US/CN writer
  paths, frontend, data collection, artifacts, secrets, private/order/live
  endpoints, Demo orders, and paper queue writes.

## Dependency baseline and result

An AST inventory at the base commit found 34 direct `quant_crypto -> quant_us`
import statements across 26 files:

- 23 UTC imports from `quant_us.core.clock`;
- 11 imports of existing Signal/TargetPosition/OrderIntent/RiskDecision types
  and their asset-neutral enums.

The delivered state has two direct import statements in one containment
adapter, `quant_crypto/adapters/legacy_quant_us.py`. Both are declared in
`quant_crypto/shared_boundary_allowlist.json` with owner, reason, regression
test, and retirement condition. Unallowlisted direct dependencies are zero.

## Adopted shared contracts

- UTC: all 23 BTC clock imports use `quant_shared.core.time`.
- Identity: new BTC runtime ids are created by a BTC adapter and validated by
  `quant_shared.core.StableIdentity`.
- Serialization/hash: BTC artifact and audit DAG hashing use
  `quant_shared.core.canonical_payload_hash`.
- Evidence: BTC adapter produces `shared_evidence_reference_v2`.
- Ledger: BTC adapter produces generic `shared_ledger_record_v2` while
  retaining BTC record types and payload semantics.
- Replay: `BTCReplayContext` converts explicitly injected snapshots, orders,
  and fills to `shared_replay_input_v2`; shared replay validation is executed
  before the BTC replay function.
- Read model: BTC adapter produces `shared_read_model_snapshot_v2` with
  BTC-owned blockers, decision, and metadata.

Funding, liquidation, mark/index rules, venue filters, WebSocket state, BTC
OMS lifecycle, reconciliation, outage/cancel-only behavior, and BTC-specific
gate decisions remain in `quant_crypto`.

## Compatibility and schema effects

- No `quant_shared` or `quant_us` file changed.
- No shared enum, lifecycle state, API schema, or execution semantic changed.
- The replay result metadata gains additive shared replay contract/id/source
  and input-count fields.
- Existing BTC domain objects remain the public inputs/outputs of the current
  Signal -> TargetPosition -> OrderIntent chain through the explicit legacy
  adapter. Retiring that adapter requires an architect-approved atomic shared
  domain-interface migration.

## Tests

All pytest commands used a unique Windows temp root, explicit `--basetemp`,
and `-p no:cacheprovider`.

- Ticket-owned boundary contract:
  `tests/contracts/test_btc_shared_boundary_adoption.py`
  -> `5 passed`.
- Shared platform plus focused BTC UTC/serialization/OMS/risk/replay contracts:
  -> `89 passed, 1 failed`.
  The only failure is the current-main absence of
  `configs/btc/security/api_key_permission_records.redacted.json`.
- Affected BTC group 1:
  -> `59 passed, 1 failed`; the same missing committed redacted config.
- Affected BTC group 2:
  -> `68 passed, 3 failed`; all three require absent current
  `artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json` or
  `artifacts/btc_manual_paper_review_approval/latest/` evidence.
- Affected BTC group 3:
  -> `59 passed`.
- A monolithic all-BTC-contract invocation exceeded four minutes and was
  terminated by exact PID; the same files were then run in bounded groups
  without selecting out failures.
- Scoped `git diff --check` -> passed.

No missing config or historical/current artifact was copied or synthesized.

## Gate decision and blockers

Deliverable readiness: `quality_checked`.

Not claimed:

- `research_ready=false`
- `backtest_ready=false`
- `promotion_evidence_ready=false`
- `paper_ready=false`
- `live_ready=false`

External/current-evidence blockers:

- `btc_security:redacted_api_key_permission_records_missing_on_current_main`
  - owner: BTC security-evidence ticket owner
  - next action: publish a separately reviewed, redacted, committed record;
    never include a secret.
- `btc_gate:current_head_gate_dashboard_artifact_missing`
  - owner: BTC gate-evidence rebuild ticket owner
  - next action: rebuild current-HEAD gate evidence under an authorized
    artifact ticket.
- `btc_gate:manual_paper_review_approval_artifact_missing`
  - owner: BTC gate-evidence/manual reviewer
  - next action: produce the separate reviewed approval evidence; this Goal
    does not authorize it.

Safety flags remain:

- `network_collection_allowed=false`
- `secret_read_allowed=false`
- `private_endpoint_allowed=false`
- `order_endpoint_allowed=false`
- `demo_order_allowed=false`
- `paper_queue_write_allowed=false`
- `paper_unlock_allowed=false`
- `live_unlock_allowed=false`
- `promotion_unlock_allowed=false`
- `withdraw_allowed=false`
