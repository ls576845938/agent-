# FRONTEND-ROUTE-BOOTSTRAP-INTEGRATION-20261003 independent review

## Decision

- Independent integration status: `quality_checked`; canonical main merge, service restart, current-main identity, and browser acceptance remain owned by the root session.
- Change risk: `research_readonly_release`.
- Approved base / rollback point: `b21bb541127ae71ee5e80c3aa4006c7d5338bd6d`.
- Producer final: `4101c37b1f051ef3024b170eafa977f4d1ee6e83`; corrected deliverable: `aeb187ddfa3e04010d81581f1d7ef94ca1e49ac2`.
- Integration merge head before identity/report: `2d11df8d664221446287c605ef3e2a761badaf04`.
- The earlier `feddeecfebdf035ea72d6e90e417b74617149599` delivery is superseded because its shared unkeyed loader could retain component or error state across routes.

## Independent review

- Both the corrected `published` envelope and its required `superseded` event passed `handoff.py validate`.
- Base → corrected deliverable → producer final ancestry is valid. The four corrected deliverable SHA-256 values match the committed Git blobs exactly.
- The complete producer diff is limited to `App.tsx`, `Workbench.tsx`, the focused graph regression, the producer acceptance record, and three append-only handoff events.
- All nine outer `LazyWorkspace` instances have distinct stable route keys. The BTC workspace keeps a separate health-derived `componentKey`, so route identity and BTC health remount behavior are not conflated.
- Existing route props and callbacks are preserved. Import failures expose a full-page refresh action; the root session still must prove this in the canonical browser.
- The 16 Phosphor icons use the installed package's supported per-icon CSR entry points. No dependency or lock-file change is present.
- No strategy, risk, OMS, protection, ledger, broker/private transport, launcher, permission, artifact, or promotion semantics changed.

## Validation

- `node scripts\\test-route-bootstrap.mjs`: passed; 9 lazy route chunks have isolated identities and 16 CSR icon modules resolve.
- `npm.cmd run identity:refresh`: passed; generated fingerprint `df3c364cf2fdfe1b822023412ce49514d906c658bcb9357a55da4bad2d084f5b` for the integration merge head.
- `npm.cmd run identity:check`: passed; manifest match and baseline ancestry true on the integration branch.
- Producer evidence reused without rerunning unchanged full checks: final `npm run lint` passed; base graph failed first on eager workspace leakage; pre-correction graph failed on missing stable route identity.
- Not run here: Vite/preview/backend/frontend services, the 29-case browser matrix, current-main canonical identity, and public page checks. Those are release checks, not silently counted as passed.

## Scope and safety

- Planner-created sparse worktree: `agent/integrator/frontend-route-bootstrap-integration-20261003`.
- Initial scoped dirty paths: none; no conflicting or unrelated files were overwritten.
- Catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`.
- Playbooks: `quant-agent-preflight`, `quant-agent-handoff`, `quant-gate-evidence-review`, shared pitfalls, integrator profile, and research-readonly release contract.
- Active rules applied: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`, `GOV-ENGINEERING-CIRCUIT-001`, `GOV-HANDOFF-001`, `GOV-OBJECTIVE-001`, `GOV-ROOT-001`, `GOV-STORAGE-001`, `GOV-WORKTREE-001`, `MONITOR-AUDIT-001`, `QSYS-GATE-001`, `GOV-PROMPT-001`, `GOV-WINDOWS-001`.
- No runtime artifact, manifest, ledger, replay, or market data was created or modified. Promotion artifact rebuild is not required for this release class.
- Required safety flags remain false: `demo_control_enabled`, `promotion`, `paper`, `live`, `private`, `order`, `real_order`, `transfer`, `withdraw`, `execution_permission`, `runtime_observed`.

## Remaining release checks

The root session must merge this committed integration candidate into registered `main`, preserve the rollback ref at the approved base, start only the canonical main services under `research_readonly`, and record current-main identity plus the unchanged 29-case / 30-second / 5-second / one-worker / zero-retry browser acceptance. This integration does not unlock Demo, paper, private, order, or live access.
