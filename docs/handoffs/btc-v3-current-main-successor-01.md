# BTC-V3-CURRENT-MAIN-SUCCESSOR-01

## Delivery boundary

- Role: `btc_developer`
- Base: `refs/heads/main` at `5ed06e2e7bbb271e92dbe36eff523424528d7c57`
- Branch: `agent/btc_developer/btc-v3-current-main-successor-01`
- Goal: publish one minimal BTC-owned successor for integrator consumption.
- Excluded: `quant_shared`, `quant_us` changes, frontend, shared `app_factory`, data, historical artifacts, network collection, secrets, private/order/live calls, Demo orders, paper queue writes.
- Safety: promotion, paper, live, private, order and withdraw remain disabled.

## Validated historical handoffs

All six envelopes were extracted from committed Git objects and passed
`handoff.py validate` before their contents were consumed.

| Event | Deliverable commit | Depends on | Supersedes | Use in successor |
| --- | --- | --- | --- | --- |
| `published-btc-current-head-formal-delivery-v1` | `007cbfd79a9cc70a28d8cf59aa15241b5f74aa56` | none | none | Historical boundary/report only; no old artifact copied. |
| `published-btc-demo-promotion-readiness-012af8b1` | `012af8b10d22fd91044e2d4e26c4761f453dc884` | none | none | Dependency history only; all declared paths are frontend and therefore excluded. |
| `published-btc-promotion-evidence-closure-final-1e8bf21a` | `1e8bf21a550e50aeafc4cf3f873db29dd0f6f6f6` | demo readiness, closure `67b00e40` | closure `67b00e40` | Current-main gate consistency test correction. |
| `published-btc-promotion-evidence-closure-final-678d78ba` | `678d78bab88b6843b41640d7a1d4cc16e209553e` | demo readiness, closure `1e8bf21a` | closure `1e8bf21a` | Root-cause classifier and contracts. |
| `published-btc-demo-readiness-separation-fdd694b6` | `fdd694b60fb00fbd0ee02737a3893d7d6c6ec7dc` | closure `678d78ba` | none | BTC backend service and service contract. |
| `published-btc-okx-demo-runtime-start-a4209451` | `a4209451f525896b69e7f4822f7f5433f71776d9` | demo separation | none | Final OKX Demo runtime and runtime contract. |

## Per-path comparison and provenance

Hashes below are SHA-256 of committed bytes obtained with `git show`.

| Source commit | Source path | Source SHA-256 | Main state | Successor action |
| --- | --- | --- | --- | --- |
| `1e8bf21a550e` | `tests/contracts/test_btc_gate_report_consistency.py` | `be3d79132276d4759d45b07d424c7caed0d802059ca3168b9acaf73680083018` | Present but missing blocked-readiness assertions | Applied the exact historical correction. |
| `678d78bab88b` | `quant_crypto/monitoring/btc_root_cause_dag.py` | `02332c981d6d42a5600a55afb5f4e3cbc501a4eeb1649b4e17acfc3fef88ffe5` | Present but missing blocker families | Restored the exact historical classifier additions. |
| `678d78bab88b` | `tests/contracts/test_btc_root_cause_dag.py` | `a84358e0f6f8a079ab077639d6febc73e15dc47ff1d19e6bf3dbebcff3c1385e` | Present but missing regression cases | Restored the exact historical tests. |
| `fdd694b60fb0` | `backend/app/services/btc_demo_runtime.py` | `5d080bc42c7f4fdb7bfa5a9abc2fc1d89ec2e245b8b9b7b24f6a7a17f3337248` | Missing | Transplanted with its import redirected to the current BTC OMS boundary. |
| `fdd694b60fb0` | `backend/tests/test_btc_demo_runtime_service.py` | `a8bbeda23047f9721136788d429151e3b4bf3db70d5917b01bd4744638142cc8` | Missing | Exact per-file transplant. |
| `a4209451f525` | `quant_crypto/exchange/okx_demo_paper_runtime.py` | `37b3118229ff2c1af18dbecd07ffc36727bf9a4bb93c18c8b2a40d0ee8963862` | Missing | Moved to `quant_crypto/oms/okx_demo_paper_runtime.py`; the historical exchange location fails current order-surface governance. |
| `a4209451f525` | `tests/contracts/test_btc_okx_demo_paper_runtime.py` | `b5fdbe1059bb9f6814d44b8524ece4ac71b106379defa13b58928100ea89d6ac` | Missing | Transplanted with imports redirected to the BTC OMS boundary. |
| `a4209451f525` | `quant_crypto/exchange/okx_demo.py` | `3cc943ba488b7cc5a133d8b1eddc817184187778486012704f10a705ff89c694` | Missing | Moved to `quant_crypto/oms/okx_demo.py`; this transitive dependency was not enumerated by the older envelope, so its committed-byte hash is recorded explicitly. |
| `a4209451f525` | `quant_crypto/application/btc_strategy_registry.py` | `ab3f7b488479a42cc0168f5b357fb7c4d4db97f32a13bc98c54e86f6a1d1e5f1` | Present without OKX-native identity | Adapted only the BTC-native constant/spec required by the transplanted runtime; unrelated historical registry changes were not copied. |
| `a4209451f525` | `backend/app/api/app_factory.py` | `8d5febb08b84f22639b7fa63257230274c0b85af2fea722b139b4de7a7f8203d` | Shared entry intentionally unchanged | Demo routes were refactored into new BTC-owned `backend/app/api/btc_demo_runtime.py`. |
| `a4209451f525` | `backend/tests/test_btc_demo_runtime_api.py` | `e424a3a8de0c7f6a794a9ae85b88c62b68e3623563363656f241ebf0b47644ae` | Missing | Rebuilt against the BTC router factory; added default `control_enabled=false` contract. |

Frontend deliverables from the historical envelopes were compared only at the
handoff inventory level and excluded from this writer branch.

## Integrator wiring list

Owner: `integrator`.

1. Import `BtcDemoRuntimeService` and `build_btc_demo_runtime_router` in the shared backend composition layer.
2. Instantiate the service only in the shared dependency container; do not auto-start it.
3. Include the BTC router under `/api`, passing the existing API-key verifier.
4. Keep `control_enabled=False`. Enabling it requires a separately approved ticket; this successor does not authorize Demo orders or paper execution.
5. Run `backend/tests/test_btc_demo_runtime_api.py` plus the frontend-owned BTC E2E assertions after integration.

## Test record

- Initial ticket suite: collection blocked by sparse omission of tracked `quant_us` and missing OKX-native registry identity.
- The writer sparse set was extended to read tracked `quant_us`; no `quant_us` file was modified.
- Ticket suite after dependency and OMS-boundary repair: `28 passed, 3 failed`.
- All three failures are current-evidence tests requiring absent
  `artifacts/**/latest` paths. No old artifact was copied and no failure was
  skipped. These failures remain external-evidence blockers.
- First related regression run: `134 passed, 3 skipped, 2 failed`.
  - The new historical exchange location caused the order-surface failure. It
    was repaired by moving the adapter/runtime beneath `quant_crypto/oms`.
  - The remaining paper-validation preflight assertion consumes missing
    current artifacts and is classified as external evidence.
- Order-surface audit after repair: `3 passed`.
- Focused BTC OMS/runtime/risk/audit/replay regression after repair:
  `71 passed`.

## Gate decision

- Deliverable class target: `quality_checked`.
- `research_ready=false`
- `backtest_ready=false`
- `promotion_evidence_ready=false`
- `promotion_allowed=false`
- `paper_allowed=false`
- `live_allowed=false`
- `private_endpoint_allowed=false`
- `order_endpoint_allowed=false`
- `withdraw_allowed=false`

Current objective blockers remain:

- `btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing`
- `btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing`
- `btc_okx_native:funding_cashflow_not_observed_in_demo_runtime`
- `btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete`
- `btc_okx_native:30_60_day_observation_window_incomplete`
- `btc_okx_native:manual_promotion_approval_missing`
- `btc_successor:current_head_artifacts_missing_in_sparse_worktree`
- `btc_demo_runtime:shared_app_factory_wiring_requires_integrator`
