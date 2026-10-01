# BTC-DEMO-START-FEEDBACK-01

## Scope and evidence

- Role: btc_developer (root user session); base: f7862301933777145f2934790afcb141925e15b1.
- change_risk: demo_execution_semantics, conservatively selected for operator feedback. No backend/execution behavior changes. Independent integration and backend restart required; no promotion rebuild authorized or required by this risk category.
- Dedicated sparse worktree: btc_developer-btc-demo-start-feedback-01. Initial scoped dirty paths: none. Existing main/other-agent edits are not consumed or overwritten.
- Touch set: frontend/src/workspaces/crypto/DemoTradingConsole.tsx; frontend/src/workspaces/crypto/demo-start-feedback.ts; frontend/scripts/test-btc-demo-start-feedback.mjs; frontend/public/frontend-identity.json; this report; .agent/handoffs/BTC-DEMO-START-FEEDBACK-01/ append-only event.
- Console delegates presentation to a side-effect-free resolver. Queued/running/reload show progress; unknown is not failure; terminal errors use current operation blocker_codes rather than stale POST receipt. A succeeded operation is not a claim of current runtime permission. Unrelated account actions are not labeled start failures.
- Only stale start receipt messages are suppressed beside derived feedback; acknowledgement failures and other control-action messages remain visible.
- Read-only local GET observations on 2026-09-06: the user's previously accepted start moved from running/account_positions_orders_oco to blocked. runtime.status=start_blocked_fail_closed; sole blocker=okx_demo_paper_exact_isolated_1x_leverage_required. Current account leverage values were not projected, so actual leverage cannot be inferred.
- Backend validator requires two distinct long/short isolated rows with exactly configured leverage 1. Missing/duplicate side, wrong margin mode, or multiplier can cause this blocker. No backend validation bypass, leverage mutation, or automatic retry is introduced.

## Verification

- Failure-first: node frontend/scripts/test-btc-demo-start-feedback.mjs failed against original Console predicate with `accepted/running is not a failed preflight`.
- node scripts/test-btc-demo-start-feedback.mjs: passed; queued/running, reload, terminal states, precise blocker precedence, isolated leverage guidance, success, unknown, rejected, submitting and unrelated action cases.
- node scripts/test-btc-operator-attempt-state.mjs: passed.
- node scripts/test-btc-operator-v2-contract.mjs: passed, including existing handler harness (8 actions).
- npm run build: passed (65s), existing bundle-size advisory remains.
- npm run lint (tsc --noEmit): passed, exit 0; direct canonical TypeScript binary with -p tsconfig.json also passed after a slow filesystem-bound run.
- node frontend/scripts/check-frontend-identity.mjs: passed on 9d2aeac225efa66116e065ae281bf0a1fea55570; fingerprint 251a2e5e821aa0cf426ed122a203c6852e73f0faaea9a4fac2496172b71e29eb, no frontend dirty paths.
- Canonical-main browser acceptance and restart: pending integration; no worktree server was started.
- Private/account refresh/start/order end-to-end: not run, unauthorized. No strategy execution was initiated by this ticket.

## Governance and remaining blockers

- Read quant-agent-preflight and quant-agent-handoff; docs/knowledge/README.md; quant_system_non_negotiables.md; shared_pitfalls.md; btc_developer_pitfalls.md; delivery_risk_policy.json.
- Context command: .venv/Scripts/python.exe tools/agent_governance/context_packet.py --role btc_developer --scope shared --change-risk demo_execution_semantics --format markdown.
- Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001. Advisory GOV-PROMPT-001/GOV-WINDOWS-001.
- Catalog SHA256: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
- Delivery: committed frontend objects and refreshed identity plus validated append-only handoff. No schema, dependency-order, ledger, market-data, runtime artifact, or promotion manifest changes. Existing artifacts are not promoted or asserted current-HEAD fresh.
- Owner operator: verify OKX Demo BTC-USDT-SWAP isolated long/short 1x settings and evidence, acknowledge the blocked operation, refresh account snapshot and manually retry authoritative preflight. Backend remains fail-closed until its actual checks pass.
- Owner integrator/root: validate committed touch set, tests, identity and independent integration; verify canonical-main page and restart only while runtime inactive and no pending operation.
- Safety flags remain false: promotion_eligible, paper, live, private, order, real_order, transfer, withdraw. Readiness is quality_checked only, never paper/live/promotion readiness.
