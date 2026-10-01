# BTC Demo 重连重复快照与底部空白修复

- Role: btc_developer; change_risk: demo_execution_semantics.
- Base: e3888924df645e1e69981c04190c14d15bcb9430.
- Dedicated sparse producer: BTC-DEMO-RECONNECT-LAYOUT-01.
- Touch set: quant_crypto/oms/okx_demo_private_ws.py; tests/contracts/test_btc_okx_demo_private_ws.py; frontend/src/index.css; frontend/src/workspaces/crypto/demo-start-feedback.ts; frontend/scripts/test-btc-operator-cleanup.mjs; frontend/scripts/test-btc-demo-start-feedback.mjs; frontend/public/frontend-identity.json; this report; ticket handoffs.
- Initial main and producer scoped dirty: clean. Only task-owned changes; no upstream uncommitted files consumed.

## Current incident

Local status GET on 2026-09-06 showed current attempt 22:33:06–22:37:07 +08:00, source e3888924. Four WS subscription channels were complete. Diagnostic: reconnect / ProbeWallClockTimeout / okx_demo_private_ws_probe_wallclock_timeout. Runtime was inactive, worker_alive=false, orders_submitted=0. Actual long and short leverage both 1. No exchange API called by this task.

Code inspection found that the connector's two authenticated generations fetched THREE full REST snapshots: initial startup once; after reconnect the newly constructed reconciler ran startup(), then on_disconnect(), then on_reconnect(). The extra startup snapshot in generation two is redundant: on_reconnect() itself performs the same snapshot validator with a fresh snapshot. It increases latency inside the unchanged 160-second default wall-clock probe budget.

Fix: reconnect enters on_disconnect()/on_reconnect() directly after login and subscription. It still fetches a new post-disconnect snapshot. No prior snapshot is cached or reused. Two authenticated generations and their respective fresh snapshots remain mandatory. Unknown orders/fills, multiple positions, missing balance, timeout invalidation, retry/backoff and fail-closed behavior remain tested. No changes to runtime locks, strategy, risk, order construction, ledger, shared schema, credentials or security policy. Timeout diagnostic is categorized as transport rather than unknown.

The observed timeout and redundant requests are established; whether this is the sole cause of the user's real exchange failure is NOT yet verified. Offline probe success must not be called real Demo startup success. User authorized UI testing, but injected private/order permissions remain false, so no start/refresh/ack/private calls were made.

## Layout regression

At 1131x975, document scrollHeight was 4159 while body was 975. Eight clipped sr-only action descriptions had absolute static-position anchors around 4028px and no containing block. This was introduced by the previous hiding-style change.

Fix: position the action container relatively; explicitly anchor the clipped descriptions at top:0/left:0. They remain available to assistive technology without contributing out-of-bounds document overflow. The K-line/backtest height allocation is unchanged.

## Verification

- Failure-first: five new snapshot count/fresh unsafe snapshot tests failed on 3 calls vs 2; CSS anchoring assertion failed.
- tests/contracts/test_btc_okx_demo_private_ws.py + test_btc_demo_start_attempt.py + test_btc_shared_platform_v3_operator_contract_v2.py: 96 passed.
- test_btc_okx_demo_paper_runtime.py -k 'startup or private_ws or reconnect': 43 passed, 398 deselected.
- Includes new test preventing a redundant third snapshot from consuming the wall-clock deadline; hung generation-two result remains terminal and late-worker isolated.
- node frontend/scripts/test-btc-operator-cleanup.mjs: passed.
- node frontend/scripts/test-btc-demo-start-feedback.mjs: passed.
- Frontend lint, operator-attempt-state and operator-v2-contract scripts: passed. Vite build: passed in 49.02s (existing large chunk warning). Independent integration pending; final receipt records it.
- Browser comparison and service restart: after reviewed main integration only.
- Real Demo/private startup: NOT RUN; capability blocked. No readiness claim.

## Governance

Read: preflight/handoff skills, AGENTS, knowledge README and non-negotiables, shared_pitfalls, btc_developer_pitfalls, delivery_risk_policy, websocket_reconnect_gapfill, exchange_api_runtime_contract, api_key_permission_policy.
Catalog: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001; advisory GOV-PROMPT-001, GOV-WINDOWS-001. No raw historical pitfall log needed.

Readiness quality_checked only; gate_impact=none. Independent integrator and backend restart required. No promotion artifacts, manifests of market data, or ledgers rebuilt. Frontend identity binds committed source. Promotion, paper_or_live, private, order, real_order, transfer, withdraw remain false.
