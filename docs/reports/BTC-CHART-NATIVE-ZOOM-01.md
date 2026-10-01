# BTC-CHART-NATIVE-ZOOM-01

- Role: btc_developer, root user session. Base main: bfe66305fb95ae1e220548af95e1b4dcbd49fa6c.
- change_risk: demo_transport_hotfix, public candle view-only correction. No strategy/risk/order construction/private-WS reconciliation/ledger/security/live permission changes. No independent integrator or promotion rebuild required; backend restart remains required by delivery policy.
- Planner worktree: btc_developer-btc-chart-native-zoom-01, sparse. Initial scoped dirty paths in main and producer: none. Other-agent/unrelated dirty files remain untouched.
- Touch set: frontend/src/workspaces/crypto/TradingViewChart.tsx; frontend/src/index.css; frontend/e2e/crypto.spec.ts; frontend/scripts/test-btc-chart-navigation.mjs; frontend/public/frontend-identity.json; this report; .agent/handoffs/BTC-CHART-NATIVE-ZOOM-01/ append-only event.

## Change and regression

- Remove the entire floating K-line navigation bar, its CSS and its bespoke +/- zoom implementation.
- Restore native minBarSpacing=0.5 (installed lightweight-charts 5.2.0 documented default) from the restrictive 3px floor. A narrow plot can therefore zoom out beyond width/3 candles.
- Preserve native wheel zoom, pinch, axis scaling, drag pan, double-click fit, resize range lock and drawing layer pointer behavior. No custom wheel interception or overlay is added.
- Keep live updates incremental; tick/rolling candle-window updates do not explicitly recreate/refit the chart.
- Failure-first component harness executed original source and failed on the restrictive 3px floor. After the fix, the harness verifies actual component options, rendered-tree absence of the bar, enabled native interactions and no recreate/refit on tick/rollover. Stub chart is not proof of actual browser gestures.
- `node frontend/scripts/test-btc-chart-navigation.mjs`: passed.
- `npm run check:btc-tradingview`: passed, all 11 static entry/layout markers.
- `npm run lint`: passed (tsc --noEmit).
- `npm run build`: passed, 5220 modules, 36.40s; existing >500k bundle advisory only.
- Browser regression updated to assert toolbar absence, both wheel directions, zoom below old floor, pan, next ticker refresh preserving span, and double-click reset at 1131x975. Actual browser run pending canonical service restart; never launch a worktree server.

## Delivery and safety

- Read preflight/handoff skills, AGENTS.md, knowledge README and non-negotiables, shared/BTC-developer playbooks, delivery risk policy. No raw incident log required.
- Context command: .venv/Scripts/python.exe tools/agent_governance/context_packet.py --role btc_developer --scope shared --change-risk demo_transport_hotfix --format markdown.
- IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001. Advisory GOV-PROMPT-001/GOV-WINDOWS-001. Catalog SHA256: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
- Frontend identity is refreshed from committed Git objects before source integration; final hashes are in the published handoff. No data/ledger/runtime artifact or schema changes; no claim that legacy artifacts are current-HEAD fresh.
- Previous-turn automatic stop/restart was policy-rejected. Current listeners still PID 4216 (3000) and 7008 (8765); no retry or alternative process termination was attempted. Owner operator: stop old services through approved local controls; root may then use canonical startup entries and run browser acceptance. Source integration does not equal running-page acceptance.
- Gate impact none. promotion_eligible, paper, live, private, order, real_order, transfer, withdraw remain false. No credentials/private/account/order endpoints used. Existing Demo leverage preflight blocker is outside this chart-only change and remains unchanged.
