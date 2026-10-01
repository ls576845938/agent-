# BTC Demo 操作界面与失败诊断修复

- role: btc_developer; change_risk: demo_execution_semantics.
- base: 3ab3c023e1bedbda1a4d063dc71cf9513df86999.
- ticket: BTC-DEMO-OPERATOR-CLEANUP-01; dedicated sparse producer.
- touch set: backend/app/services/btc_demo_runtime.py (read-model diagnostics only), backend/tests/test_btc_demo_operation_diagnostics.py; frontend/src/index.css; frontend/src/workspaces/crypto/{CryptoStrategyEditor,DemoTradingConsole,StrategyTesterReport}.tsx; demo-start-feedback.ts; frontend/scripts/{test-btc-demo-start-feedback,test-btc-operator-cleanup}.mjs; frontend/public/frontend-identity.json; this report and ticket handoff.
- Initial scoped dirty: clean in main and producer. No uncommitted upstream consumed; unrelated changes preserved.

## Findings and limits

Local persisted status GET on 2026-09-06 confirmed the current attempt began at 21:57:58 +08:00, deadline 22:02:58, terminal timed_out; actual_long_leverage=1 and actual_short_leverage=1. Runtime inactive, opening_allowed=false, cancel_only=true, worker_alive=false, orders_submitted=0.

The persisted error is a compound string: okx_demo_fault_drill_runtime_root_writer_lock_unavailable;okx_demo_startup_worker_thread_join_timed_out. The adapter passed that as one code into a strict contract which silently removed it. Failure-first tests reproduced empty blocker_codes, including an invalid-code case. The adapter now splits stable compound diagnostic codes and emits a safe invalid-diagnostic sentinel rather than dropping every reason. This also decodes existing terminal records without rewriting them. No shared schema, authorization matrix, state transition, runtime lock, strategy, order, ledger or security semantics changed.

The underlying lock failure is recorded, but its source (another holder versus in-process lifetime/concurrency) is NOT established by current evidence. No lock files deleted, no timeout enlarged, no private calls or automated preflight performed. Restart is service recovery only; a successful authorized new Demo preflight remains an operator acceptance item.

UI: removed external immutable history strip; retained historical-data-unavailable warning in Chinese with raw diagnostics collapsed. Candidate/version/source hashes are collapsed in strategy technical details. Fixed missing sr-only CSS that exposed action descriptions in the button grid. Scoped dark brown-gray scrollbars to crypto workspace. Converted key report and preflight phase text to Chinese. Required risk warnings and backend disabled conditions remain.

## Verification

- Failure-first: frontend cleanup assertion failed on missing sr-only style.
- Failure-first: two backend diagnostic tests failed (empty codes); passed after fix.
- Python: backend/tests/test_btc_demo_operation_diagnostics.py + backend/tests/test_btc_demo_runtime_service.py + tests/contracts/test_btc_demo_start_attempt.py: 53 passed.
- Python: tests/contracts/test_btc_shared_platform_v3_operator_contract_v2.py: 60 passed.
- node frontend/scripts/test-btc-demo-start-feedback.mjs: passed.
- node frontend/scripts/test-btc-operator-cleanup.mjs: passed.
- node frontend/scripts/test-btc-operator-attempt-state.mjs: passed.
- node frontend/scripts/test-btc-operator-v2-contract.mjs: passed.
- npm run lint: passed; npm run build: passed, 25.14 seconds, existing large bundle warning.
- Canonical browser validation, integration and restart: pending independent integration; never claim actual trading startup from these tests.
- No full live/private startup acceptance; current capability private=false.

## Governance and safety

Read AGENTS, knowledge README/non-negotiables, shared_pitfalls, btc_developer_pitfalls, delivery_risk_policy, order_lifecycle, audit_trail, api_key_permission_policy; preflight and handoff skills.
Catalog: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
Active rules: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001; GOV-PROMPT-001 and GOV-WINDOWS-001 advisory. No unrelated raw pitfall log scan.

Readiness: quality_checked only. gate_impact=none; no promotion artifact/ledger rebuild. Frontend identity refreshed from committed source. Independent integrator and backend restart required. Promotion, paper_or_live, private, order, real_order, transfer, withdraw remain false. No external writes or secrets read. Existing historical evidence remains stale independently.
