# Research workbench refactor — producer checkpoint

- Ticket: RESEARCH-WORKBENCH-REFACTOR-01; role: super_developer.
- Change risk: unclassified (conservative policy); independent integration required.
- Base: 4096453b344e777e99f4272b43582d60cf1251f9.
- Worktree: planner-created sibling super_developer-research-workbench-refactor-01.
- Initial scoped dirty paths: none. All present changes are owned by this ticket.
- Other writer: STRATEGY-ALPHA-PARAMETER-MAP-01; disjoint /strategies source and backend history service. Its canonical integration/restart window remains reserved until explicitly released.
- Main worktree, shared shell/styles, strategy/risk/OMS/schema, broker/private/order/live code and credentials are not changed.

## Scope and design

ResearchDashboard selects the new four-stage workflow by default. Data/factors, experiments/backtests, candidate evidence, and portfolio/review retain their existing actions. Shared rule/factor context is explicit, advanced controls are collapsible, failed reads are labelled unknown, and interface availability is distinguished from data availability, execution completion and promotion.

ResearchWorkbench.tsx and ResearchDashboard.css implement local navigation/context/overview only. LegacyResearchDashboard.tsx preserves the entire original implementation, with module-relative import and exported-function-name adjustments only.

Immediate visual rollback: /research?layout=legacy. Return: /research. Local backup branch codex/research-before-20260908 points to the exact base above. Never reset main to roll back this page: that would remove another task's changes. Prefer the visual switch; a later permanent rollback must be a scoped revert through integration.

## Checks at this checkpoint

- node frontend/scripts/test-research-rollback.mjs: passed; exact baseline preservation.
- frontend: node node_modules/typescript/bin/tsc --noEmit: passed.
- frontend: npm.cmd run build: passed; existing large-bundle warning (1.604 MB JS, 460.7 KB gzip).
- frontend: Playwright --list for research.spec.ts and research-workbench.spec.ts: 7 tests discovered; execution pending canonical integration. Fixtures in these tests are UI contracts, not real research evidence.
- Python: py_compile scripts/verify_research_workbench.py: passed.
- Canonical Python invoked against producer source: pytest -q tests/integrations/test_qlib_adapter_contract.py tests/integrations/test_pypfopt_adapter_contract.py tests/integrations/test_qlib_to_pypfopt_pipeline.py tests/integrations/test_research_execution_pipeline.py backend/tests/test_research_automation_pipeline.py backend/tests/test_factor_pipeline.py tests/contracts/test_no_lookahead_factor_pipeline.py:
  **72 passed, 2 failed**, 249.84 seconds.
- The two failures are Windows path separator mismatches in expected blocker text for inline-only / missing canonical backtest manifests (tests at lines 1529 and 1568). Both actual decisions remained BLOCKED. The tested backend/quant_us files are byte-identical to base; no gate logic or test expectation is changed by this UI ticket. Not a full green regression result.

## Real verification, not yet completed

User explicitly authorized installing pyqlib, LightGBM and PyPortfolioOpt. Installation is in the producer's private .venv first; canonical .venv has not been mutated while the other task owns the restart window.

scripts/verify_research_workbench.py is an explicit research-only runner using historical cleaned data and repository adapters. It rejects reuse of an output directory, saves per-stage status/tracebacks and package/source-manifest hashes, never runs dry-run as success, and always leaves verification_complete=false for independent artifact review. It does not approve reviews or call trading endpoints.

Committed 2020–2025 daily bars for the configured 13-symbol universe are being exported from the base Git object into a dedicated local verification directory, not borrowed from uncommitted worktrees. This historical sample is not current market data and is not point-in-time universe/promotion evidence. Real factor, rule, Qlib and portfolio execution remain pending until receipts exist.

## Governance and acceptance boundaries

Read: quant-agent-preflight, quant-agent-handoff, quant-gate-evidence-review; knowledge README/non-negotiables; shared, super_developer and architect playbooks; delivery risk policy.
Catalog hash: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
Selected IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, RESEARCH-HOLDOUT-001, GOV-PROMPT-001, GOV-WINDOWS-001.

Source readiness: quality_checked only. Gate impact: none for the UI; real verification receipts are evidence-only and cannot unlock gates. No promotion artifact is claimed fresh or ready. Canonical browser acceptance/backend restart are pending independent integration. promotion, paper_or_live, private, order, real_order, transfer and withdraw remain false.

## Checkpoint 2: real-data failures and dependency installation

- Historical archive exported from the exact base: input-4096453b.zip SHA-256 2585f6648949a11557492beae50f6ef3967be7bbbb65ea3d161c3c90cc58a85e, 19,604 daily Parquet files across 13 symbols. Task-owned physical root: D:/vibe coding/Obsidian/量化系统/research-verification/research-workbench-refactor-01.
- rules-001 failed before stages because the private environment did not yet locate base dependencies. rules-002/receipt.json preserves the subsequent actual attempt: feature snapshot completed (3,263 rows), factor evaluation failed (0 observations), rule cycle failed (unknown strategy ID momentum).
- Current factory registers trend_momentum with lookback_bars, not momentum/lookback. The new UI and QA runner defaults are corrected; legacy remains byte-equivalent to the baseline. E2E asserts these new defaults.
- FactorPipeline dates inherit a +08:00 DuckDB timestamp, while FactorEvaluator forward dates are normalized to UTC. The same US session becomes Jan 3 vs Jan 2 and the merge is empty. Also, the existing automation regime sidecars add regime_filter, absent from all registered strategy constructors. These are existing backend blockers; authorization for a bounded backend scope extension was requested, not presumed.
- The runner now records setup exceptions in its durable receipt as well. Whitespace-only trailing blank lines were removed; exact legacy comparison still passes.
- Dependencies installed in the private environment: pyqlib 0.9.7, lightgbm 4.7.0, PyPortfolioOpt 1.6.0, with 193 dependencies via uv. No canonical environment changes yet. Slow initial pip downloads were cancelled before installation; the final command used a temporary HTTPS TUNA index and no global pip configuration changes. See the [mirror's official usage documentation](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/).
- Package import/solver smoke, real Qlib training, canonical install, source integration and browser acceptance are still pending at this checkpoint. No full-flow-success claim is made.

## Checkpoint 3: independent-review corrections

- Independent architect rejected f19be2c04 for invalid default strategy, silently swallowed integration refresh errors, and hidden/unread Qlib data-root submission. All three have producer corrections: registered defaults, shared error-aware refresh, unknown dependencies/run lists on failure, visible Qlib data root, and root-mismatch action guards. Dedicated E2E cases cover the latter two regressions. Stage aria-controls now points at the active content panel.
- The QA runner requires both --confirm-task-owned-data-root and a .research-workbench-owner.json marker for this ticket, and explicitly rejects canonical data. This prevents accidentally writing feature/research output into an ordinary shared data root. It also records the executed runner SHA-256. Its output-root remains exclusive/new per attempt.
- Private-environment import/solver smoke passed: pyqlib 0.9.7, lightgbm 4.7.0, PyPortfolioOpt 1.6.0; LightGBM produced 40 synthetic smoke predictions and the optimizer weight sum was 1.0000000000000002. pip check: no broken requirements. This is package functionality, not historical research evidence.
- qlib-001/receipt.json: real historical dataset/provider completed; real training failed in joblib resource_tracker because the Windows default temporary path contains non-ASCII characters. Preserve that failure. A task-owned ASCII JOBLIB_TEMP_FOLDER is the scoped environment correction for the next attempt; no package/source safety semantics are bypassed.
- Backend scope-extension permission is still pending. Canonical integration and services remain owned by the other task until its explicit release.

## Checkpoint 4: complete directory guard and actual Qlib outcome

- The second independent review found the same unread-directory risk outside Qlib. All action buttons now use a shared rootMismatch guard; both synchronous and queued submission functions reject mismatched roots before issuing requests. Read-only refresh remains available. An additional E2E starts with an enabled portfolio backtest, then verifies root changes disable it, optimization and registry rebuild. This is UI request consistency, not a change to execution or permission contracts.
- The other task explicitly released the canonical window at main bbc39bec1449c5ea6947c200be1541988d34db2c. Its history root and evidence are preserved. Canonical installation is proceeding under the user's explicit dependency authorization, using a snapshot of all preexisting packages and constraints that retain them except the necessary protobuf 7.35.1 to 6.33.6 compatibility change. Snapshot: external verification root/environment-before.json; constraints: install-constraints.txt.
- qlib-002/receipt.json records actual historical provider construction, LightGBM training and metric import as completed. However, nested Qlib portfolio analysis FAILED with `index 1508 is out of bounds for axis 0 with size 1508`. Training predictions are constant and Rank IC is NaN. Training completion does not establish useful alpha or backtest success.
- The subsequent actual research portfolio/risk pipeline FAILED and remained fail_closed. Its exact gate blockers are `pending_order_intents:3` and `walk_forward_produced_no_windows`. Weight generation used a fallback optimizer, not a successful default max-Sharpe solve. A partial backtest return must not be promoted as successful end-to-end evidence. Cost-stress survival is zero and there are no walk-forward windows.
- Evidence paths under the external root: qlib-002/receipt.json; qlib-002/qlib_runs/historical_qa/qlib_backtest_summary.json; qlib-002/pipeline_runs/historical_qa/pipeline_result_manifest.json; qlib-002/portfolio_runs/pfrun_872e01b704974ff6/run_manifest.json. The receipt started at source a12bb51d and records runner SHA-256 6fb33c433e8123c9cfd9acd50e425a7f631e5038a0ea86f1bd00b0eb2e0a3702; the later pipeline lineage captured handoff commit 3ef58aca. These are historical task evidence, not current-main promotion evidence.
- Existing backend repairs remain outside the approved touch set pending the user's answer. No parameter tuning, gate relaxation or changes to risk/OMS were made to force a passing result. All promotion/private/order/paper/live permissions remain false.
