# RESEARCH-WORKSPACE-LAYOUT-01

## Scope and rollback

- Producer: `super_developer`, `change_risk=unclassified`.
- Base / rollback target: `33bbfcedb9b34ff8dd4c3fd2304c6b01856cd0b9`.
- Planner branch: `agent/super_developer/research-workspace-layout-01`, sparse checkout; no main edits or worktree preview.
- Initial scoped dirty: empty. Additional `ResearchDashboard.tsx` source-key edit approved by root and checked clean. No other agent changes overwritten or consumed.
- Rollback through reverting the eventual independent integration merge; existing run artifacts are not overwritten.

## Changes

- `frontend/src/workspaces/ResearchDashboard.tsx`: view-only navigation among ordinary `ResearchPortfolioContent` tabs preserves same-source drafts. Entering focused factory/details unmounts that content and does not promise cross-workspace draft persistence. Run/root and other source identity changes still remount for isolation.
- `ResearchPortfolioWorkspace.tsx` and `research/ResearchWorkbench.tsx`: five primary workspaces (overview, Alpha factory, data/factors, manual experiments, candidates/evidence). Factory and run details use independent canvas/read models without legacy registry requests or its unrelated count/status cards. Previous/legacy URLs retained.
- `research/AlphaFactoryConsole.tsx`: collapsed new-batch configuration, result-first batch canvas, exact shared-detail links, read-only detail mode, bad-seal event/stage suppression. Existing finite submit and explicit resume remain only in the factory console; no research engine changes.
- `research/ResearchRunDetails.tsx`, `research/research-run-links.ts`, `research/QlibDecisionTrace.tsx`: shared exact-run overview/replay. Qlib, portfolio and strategy-module entrances now show a summary and precise link, not three duplicated replay canvases. Run/root/trace identities and integrity checks fail closed; selection never falls back to latest. Decisions are keyed by run and decision ID. Historical code is compared with the canonical page's build-time `frontendIdentity.source_head`; this is not a new dynamic current-main API.
- `research/ResearchDashboard.css`, `research/alpha-factory.css`, `research/qlib-trace.css`: compact primary navigation, folded provenance, responsive evidence layout.
- `frontend/e2e/{alpha-factory,research-portfolio-workflow,research-workbench}.spec.ts`: existing 50 checks adapted to approved navigation and shared entry links without removing safety assertions. New `research-layout.spec.ts`: 16 UI scenarios covering viewport priority, precise deep links, seven-layer decision switching, late response/history isolation, corruption/unsafe contracts, absent/invalid/ambiguous/mismatched references, child-fold limits, ordinary-tab same-source draft restoration and six Qlib/factory URL version-hint cases.
- Source-review correction: retained `dataVersion` / `featureVersion` URL hints are checked against sealed Qlib `dataset_manifest` / exact trace identity and existing factory result `profile` / `lineage`. Missing/mismatched hints show an explicit warning while leaving sealed-run facts unchanged. Factory feature versions without a published contract remain unverified. No duplicate run-detail fetch, latest fallback, POST, backend change or new training.

## Producer validation

- From producer `frontend`: `D:/New Folder/node.exe node_modules/typescript/bin/tsc --noEmit` — passed, rerun after the URL-hint review correction.
- `D:/New Folder/node.exe node_modules/vite/bin/vite.js build` — final passed after the URL-hint correction; 5245 transformed modules, 18.68 s, existing >500 kB bundle warning. No serve/preview started.
- `git diff --check` — passed. Git reports normal LF-to-CRLF checkout notices only.
- Canonical-only Playwright command for integrator: `node node_modules/@playwright/test/cli.js test e2e/alpha-factory.spec.ts e2e/research-portfolio-workflow.spec.ts e2e/research-workbench.spec.ts e2e/research-layout.spec.ts` (66 cases: 50 existing + 16 layout/hint cases). Not run by producer; requires integrated main and official launcher identities. Root owns actual 1131x975 and 390px browser QA.
- No Python/engine tests or new training campaign: backend, Qlib engine, market data, schemas, risk, OMS and ledger unchanged.

## Rules, evidence and gate

Read: quant-agent-preflight / quant-agent-handoff; AGENTS, knowledge README/non-negotiables, shared/super-developer playbooks, delivery risk policy, role TOML, architecture rules and backtest evidence contract. No historical raw pitfall log needed.

Catalog hash: `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`.
Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001.

Producer evidence is code/build quality only. No artifact/manifest/ledger is produced or restamped as current-HEAD evidence. Old runs remain historical after this source change. Factory rejection, completed training folds, research simulation and actual runtime are distinct. Factory folds without a research trace do not render invented seven-layer observations.

Independent integration, canonical browser regression and official service restart remain pending producer handoff. Strict promotion evidence remains blocked by `btc_runtime_artifact_root_env_missing`; no bootstrap or gate rebuild is authorized by this layout-only task. Old registry errors are out of scope. Promotion, paper, live, private, order, real_order, transfer, withdraw and execution/runtime authority remain false. No private/order/live endpoint or secret access.
