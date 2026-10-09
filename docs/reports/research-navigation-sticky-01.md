# RESEARCH-NAVIGATION-STICKY-01

- Role/risk: `super_developer` / `unclassified`.
- Base/rollback: `196066dfa46437c07b1af327251f4ad033c3d342`.
- Planner branch: `agent/super_developer/research-navigation-sticky-01`; new isolated sparse worktree, not the previous layout ticket.
- Initial and final source scopes: only this ticket's files; initial dirty empty, no overlapping edits consumed or overwritten. Revert the future independent integration merge for rollback.

## Minimal change

`frontend/src/workspaces/research/ResearchDashboard.css`: only the five-item primary research navigation sticks at the canvas top, with opaque background and local stacking order. Headers, status, sources and secondary navigation are not fixed.

Canonical CSS correction: main `27f7545e` navigation regression returned 6 passed / 3 failed. The three long-page navs stopped at y=137 while canvas top=119 (18px top padding). A research-scoped variable now binds the unchanged 22/18/12px top padding to the primary navigation's negative sticky offset. Portfolio/legacy/global canvas padding remains numerically unchanged. The three desktop bounds/hit-test assertions remain strict; 390px now also checks the same top upper bound. Already-passing focus code and DOM are unchanged.

Canonical mobile correction: main `07d` diagnosis found the 390px canvas had scrollHeight=clientHeight=6257, max scroll=0; document scrolling moved nav y=418 to -181. The prior mobile before/after=0 assertions did not prove real canvas scrolling. Research-only <=760px grid height is now bounded by min(720px,100dvh), including the collapsed-console selector; chart/canvas min-height stays 0 and canvas overflow-y stays auto. The same 390px case now requires positive canvas scroll capacity and positive actual scroll, then strict sticky bounds and hit testing before End. The short destination after End permits only natural scroll-height clamp for both canvas and document, retaining focus/horizontal visibility checks. Global CSS, HTML/body/root, focus and DOM remain unchanged.

`frontend/src/workspaces/research/ResearchWorkbench.tsx`: secondary tabs are ordinary-flow siblings, so a short parent cannot constrain sticky movement. Research-specific focus uses `preventScroll`; horizontal visibility changes only the tablist's `scrollLeft`, never body `scrollIntoView`. Exported `navigateTabs` defaults preserve the portfolio consumer. No new scroll restoration/top-reset mechanism, URL/context/draft changes, or legacy layout changes.

P2 source-review correction: a short-lived, single keyboard target intent bridges the focused-to-ordinary loading/remount gap without parent route-state changes. It is bound to `/research`, source query, target view and primary/secondary key; it is consumed before focusing and expires after 8 seconds. Later keyboard/pointer interaction, other-control focus, window blur or target mismatch cancels it and removes listeners. Secondary restoration is not overwritten by the old primary focus flag. No scroll positions or persistent state are stored.

`frontend/e2e/research-navigation.spec.ts`: nine UI regressions for long ordinary/factory/detail pages, non-sticky secondary tabs, hit testing, contextual navigation/history, 390px keyboard visibility/natural height clamp, delayed remount/secondary focus, and cancellation on transferred focus, expiry or history mismatch. Each long page waits for its actual fixture sentinel before scrolling. All requests are synthetic read-only evidence; no POST/real research/execution. Desktop and mobile scrolled screenshots use `testInfo.outputPath`.

## Validation

- Final mobile visual correction: the bounded canvas compressed the two-row toolbar to 44px (content 60px), covering all three layout buttons. Research-only `flex-shrink:0` preserves its natural height. The original 390px case now asserts toolbar/context separation and layout-button bounds/hit testing before its existing real-scroll and sticky assertions. The root coordinator took over this clean producer worktree after interrupting the pending producer; no concurrent writer remains. Full 75-case regression passed on `f9902005db8bcef316aa19e9797ec8a207d9324e`; final-head navigation/layout retest remains pending.

- Failure-first on unchanged canonical main `196066df`, port 3000: dedicated test config has **no webServer**. BeforeEach verifies canonical identity and exact baseline HEAD. Long records page failed as expected: navigation y=`-1488.0625`, canvas top=`119`, required y>=`118`. This is real browser red evidence, not new-source acceptance.
- Red command: `QS_NAVIGATION_BASELINE_HEAD=196066dfa46437c07b1af327251f4ad033c3d342 node node_modules/@playwright/test/cli.js test --config <evidence>/producer.baseline.config.mjs --grep "only primary navigation sticks through long canvas: records"` — 1 failed at sticky-position assertion.
- Evidence base: `C:/Users/LOCAL_USER/.codex/visualizations/2026/09/08/01a080f1-4630-7253-bcda-f37ffa68c539/output/playwright/research-navigation-sticky-01`. Baseline red screenshot: `baseline-red/research-navigation-only-p-37ffb-through-long-canvas-records/desktop-scrolled.png`. Baseline screenshots cannot be cited as green evidence.
- `node node_modules/typescript/bin/tsc --noEmit` — passed after the P2, CSS offset and mobile scroll-container corrections.
- `node node_modules/vite/bin/vite.js build` — passed after P2 (17.73 s), CSS offset (19.91 s), and mobile scroll-container correction (5245 modules, 19.61 s); existing large-bundle warning retained.
- `git diff --check` — passed. Playwright `--list` parsed all nine tests.
- Final canonical green / screenshots not run by producer. Integrator must run `node node_modules/@playwright/test/cli.js test e2e/research-navigation.spec.ts` against integrated main using the official launchers. Existing research regressions remain the integration safety net. No worktree serve/preview was started.

## Governance and boundaries

Read skills: quant-agent-preflight, quant-agent-handoff, playwright; shared/super-developer playbooks, AGENTS, knowledge non-negotiables, architecture/evidence rules and delivery policy retained. Catalog `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`. Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001. No raw historical pitfall log needed. Team Context was read from canonical main: sparse producer lacks `quant_crypto`, so its local Team Context invocation could not import that module; no sparse expansion or dependency consumption was needed.

No backend, Qlib, data, risk, OMS, ledger, frontend identity or run artifacts changed. No training or promotion artifact rebuild. Source screenshots/builds are UI quality evidence only, not current-HEAD trading evidence. Strict promotion remains blocked by `btc_runtime_artifact_root_env_missing`. Promotion, paper, live, private, order, real_order, transfer, withdraw and execution permissions remain false. Independent integration, canonical regression and required official service restart remain pending.
