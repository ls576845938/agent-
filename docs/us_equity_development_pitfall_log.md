# US Equity Development Pitfall Log

## 2026-07-09 IBKR 1m deep-history backfill needs small chunks and `py` on this Windows host

- Scenario: after the operator logged into the IBKR paper account, the US
  equity system probed QQQ/TQQQ 1-minute history through local IB Gateway paper
  port `4002`.
- Pitfall: `python` in this Windows environment returned exit code `9009` with
  no useful output, while `py` resolved to Python 3.14.4 and ran the scripts.
  Also, month-sized `1 min` historical requests for deep 2017 QQQ data timed
  out and IBKR cancelled the query with error `162`.
- Fix: run IBKR market-data utilities with `py`, not bare `python`, when
  `python --version` yields `9009`. For deep 1-minute backfills, use
  `--chunk-days 7 --duration "1 W"` and a small `--max-new-chunks-per-run`
  instead of month chunks. Keep request sleeps conservative and do not run QQQ
  and TQQQ backfills in parallel.
- Current boundary: this is raw broker historical market data only. It remains
  blocked for research use until point-in-time adjustment replay is performed;
  IBKR data must not be promoted as PIT-clean master data by the backfill
  report.
- 2026-07-09 checkpoint: with the paper Gateway logged in, the read-only
  `QQQ,TQQQ` 1-day 1-minute probe passed on `127.0.0.1:4002` and advanced the
  latest probe timestamp to `2026-07-08T21:56:00+00:00` with `837` rows per
  symbol. Another bounded 7-day chunk batch attempted `20` new chunks; `QQQ`
  now covers through `2019-04-16` and `TQQQ` through `2018-12-18`. The run is
  still intentionally `partial` and research-blocked because the full history
  and PIT adjustment replay are incomplete.

## 2026-07-07 IB Gateway installer error 34 can be a partial download, not a Java issue

- Scenario: installing traditional IB Gateway so the US equity data layer can
  probe IBKR historical bars through a local paper Gateway.
- Pitfall: the first downloaded
  `ibgateway-latest-standalone-windows-x64.exe` was only `43,147,957` bytes.
  install4j raised `internal error code 34`, and the early symptom looked like
  a local Java/installer failure.
- Diagnosis: `C:/Users/.../AppData/Local/install4j/t/i4j_nlog_*.log` showed
  `verifying integrity length 331072096` followed by `ReadFile failed`, proving
  the executable was incomplete. The official HEAD response reported
  `Content-Length: 331846840`.
- Fix: redownload the official IB Gateway latest standalone installer with
  PowerShell `Invoke-WebRequest`, verify the exact byte length before running,
  then install to `D:/Jts/ibgateway`.
- Current boundary: Gateway can be opened to the login page and set to
  `IB API + simulated trading`. Socket port probing remains blocked until the
  operator logs in; do not automate credentials or 2FA.

## 2026-06-25 US equity data source must be multi-strategy infrastructure, not ETF-only plumbing

- Scenario: adding Tiingo after validating the external ETF rotation strategy.
- Pitfall: naming and wiring the new source as an ETF-only feed would make the
  next strategy family duplicate data ingestion, quality checks, freshness
  checks, and source fallbacks.
- Fix: Tiingo EOD lands under the generic
  `data/external/us_equity_eod/tiingo` lake and emits a generic
  `us_equity_tiingo_eod_import_report_v1`. ETF rotation is only the first
  consumer; future US equity strategies should consume the same EOD lake and
  add strategy-specific reports on top.

## 2026-06-25 External user strategy projects can be refactored only after a file-hash backup

- Scenario: the original project under
  `D:/Trading/ETF轮动与数据引擎模块化代码` is allowed to be modified if the change
  serves the whole US equity system.
- Pitfall: directly editing the external project would destroy the original
  comparison baseline and make later diagnosis impossible.
- Fix: run `python scripts/backup_external_strategy_project.py` before any
  external source-code refactor. The backup manifest records the backup path,
  relative file paths, byte counts, and sha256 hashes so the original can be
  restored or compared.

## 2026-06-24 External ETF rotation strategy cannot be judged with partial yfinance universe

- Scenario: importing `D:/Trading/ETF轮动与数据引擎模块化代码` into the US equity system.
- Pitfall: the external strategy needs a broad ETF pool plus FRED macro data, but
  the current canonical US equity research bundle only has a small yfinance
  sample universe.
- Risk: running the strategy on only the overlapping symbols would create a
  misleading backtest because the offensive pool, defense pool, macro gate, and
  selection opportunity set are materially different.
- Decision: integrate as `research_only`, emit a missing-symbol/data-readiness
  report, and block promotion until canonical data coverage is complete.

## 2026-06-24 Month-end resampling should use last trading day, not calendar month-end label

- Scenario: the original external script used monthly resampling labels and then
  checked whether the label existed in the price index.
- Pitfall: if calendar month-end falls on a weekend or holiday, a rebalance can
  be skipped unintentionally.
- Fix: the integrated strategy selects the last actual trading timestamp in
  each month and then shifts weights by one trading day for T+1 execution.

## 2026-06-24 Strategy code must not own data downloads inside production research path

- Scenario: the external project includes Akshare and FRED fetchers plus a daily
  update script.
- Pitfall: importing downloader/scheduler code into the strategy layer would mix
  data acquisition, alpha logic, and execution readiness.
- Decision: port only the deterministic strategy math. Data must enter through
  the existing cleaned-bar and macro-data paths, and the report explicitly flags
  missing macro data with neutral-regime fallback.

## 2026-06-24 Check required ETF coverage before reading partitioned parquet

- Scenario: the local yfinance cleaned data is partitioned into many small
  date-level parquet files per symbol.
- Pitfall: an ETF strategy report can waste time reading all available parquet
  partitions even when required symbols are already missing and the backtest
  must be blocked.
- Fix: first inspect symbol directory coverage. Only read parquet contents after
  all required symbols are present.

## 2026-06-24 Windows workspace may not have GNU make

- Scenario: validating the new US equity ETF rotation target with
  `make validate-us-equity-evidence`.
- Pitfall: this Windows environment does not expose `make`, so Makefile targets
  cannot be assumed runnable from PowerShell.
- Fix: the repository now includes `make.cmd` plus `scripts/win_make.py`, a
  lightweight Windows runner that parses simple Makefile recipes, expands
  `$(PYTHON)` to the current interpreter, and supports commands such as
  `.\make.cmd validate-us-equity-evidence` without installing GNU Make.

## 2026-06-24 ETF rotation cache was outside the module folder

- Scenario: `D:/Trading/ETF轮动与数据引擎模块化代码` contained only source code, so
  the first integration attempt saw missing ETF symbols.
- Pitfall: the real historical cache lived under
  `D:/Trading/PythonApplication1/data_cache_lake`, not beside the moduleized
  source files.
- Fix: the ETF rotation report now checks this external lake as a read-only
  research source before falling back to canonical cleaned bars.

## 2026-06-24 External ETF cache can exist but still be stale

- Scenario: `D:/Trading/PythonApplication1/data_cache_lake` contains all ETF
  parquet files and `FRED_MACRO.parquet`.
- Pitfall: presence is not freshness. The located cache currently ends on
  `2026-03-24`, which is stale relative to current development date
  `2026-06-24`.
- Fix: the ETF rotation report now records latest common price date and adds a
  stale-data blocker when the cache is older than 30 days.

## 2026-06-24 External ETF update script needs the original working directory and UTF-8 console

- Scenario: updating `D:/Trading/PythonApplication1/data_cache_lake` from the
  external moduleized scripts under
  `D:/Trading/ETF轮动与数据引擎模块化代码`.
- Pitfall: running the script from its source directory writes to the wrong
  relative `./data_cache_lake`; running it in the default Windows console can
  fail before updates because the script prints emoji and the console encoding
  is GBK.
- Fix: run the original script from `D:/Trading/PythonApplication1` with
  `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`, for example
  `python D:/Trading/ETF轮动与数据引擎模块化代码/定时更新.py`.

## 2026-06-24 FRED macro refresh can fail independently of ETF prices

- Scenario: the original external update script refreshed all 24 ETF parquet
  files to `2026-06-23`, but `FRED_MACRO.parquet` remained at `2026-03-24`.
- Pitfall: `fred.stlouisfed.org:443` returned SSL EOF/timeouts from this
  Windows environment, so a script-level success message does not guarantee
  macro freshness.
- Fix: verify ETF and macro latest dates separately after every run. Treat the
  price update as successful only for market data, and keep FRED freshness as a
  separate blocker until the FRED connection is restored or another approved
  macro source is wired.

## 2026-06-24 FRED API key path refreshes macro data when the no-key CSV path is blocked

- Scenario: `fred.stlouisfed.org/graph/fredgraph.csv` and
  `fred.stlouisfed.org/data/*` timed out or reset from the local Windows
  environment, while `api.stlouisfed.org` was reachable.
- Pitfall: the original no-key `pandas_datareader` path is convenient but not
  always reachable. The official API endpoint works through a different host
  but requires a FRED API key.
- Fix: read the key from `FRED_API_KEY` or a one-time clipboard value, fetch
  `WALCL`, `WTREGEN`, `RRPONTSYD`, `BAMLC0A0CM`, `DGS10`, and `DGS2` from the
  official FRED observations API, merge into
  `D:/Trading/PythonApplication1/data_cache_lake/macro/FRED_MACRO.parquet`,
  resample to daily frequency, and forward-fill columns after the merge. Never
  print or commit the API key.

## 2026-06-25 Clipboard FRED key import must validate a single key candidate

- Scenario: the operator says the FRED key has been copied, but the clipboard
  can contain a full page, chat text, or another long blob instead of the key.
- Pitfall: blindly writing the whole clipboard to `FRED_API_KEY` can save junk
  into the user environment and make every later FRED refresh fail in a
  confusing way.
- Fix: use `scripts/set_fred_api_key_from_clipboard.ps1`. It accepts only one
  isolated 32-character alphanumeric candidate, never prints the key, and
  exits with `fred_key_candidate_missing` or `fred_key_candidate_ambiguous`
  when the clipboard is not safe to import.

## 2026-06-24 AkShare qfq ETF data can contain impossible adjusted prices

- Scenario: the external cache file
  `D:/Trading/PythonApplication1/data_cache_lake/kline/SPY.parquet` showed
  negative OHLC values and extreme 2008-2009 daily return jumps.
- Pitfall: AkShare `stock_us_daily(..., adjust="qfq")` can emit impossible
  pre-adjusted prices for old US ETF history. Filtering only prices below 2 in
  the research loader is not enough; bad positive jumps and negative rows can
  still pollute benchmark risk metrics.
- Fix: back up the bad SPY parquet, refresh SPY from AkShare with `adjust=""`,
  and verify zero nonpositive OHLC rows plus zero daily returns above 35%.
  Treat this as a data-quality repair, not a total-return benchmark. The broader
  external ETF lake still needs an all-symbol anomaly repair pass before relying
  on fine-grained cross-asset attribution.

## 2026-06-24 Repair external ETF kline quality before interpreting rotation backtests

- Scenario: scanning all ETF parquet files under
  `D:/Trading/PythonApplication1/data_cache_lake/kline` found many symbols with
  negative OHLC rows or impossible daily returns from AkShare `qfq` data.
- Pitfall: a single SPY repair is not enough. Offensive assets such as BITO,
  XLB, XLE, XLF, XLK, XLP, XLU, XLV, and XLY can also pollute factor scores,
  beta estimates, trend filters, and turnover.
- Fix: run `python scripts/repair_external_etf_kline_quality.py --backup-tag
  YYYYMMDD` after external kline updates. The script backs up each parquet,
  refreshes raw AkShare OHLCV, applies split-style back-adjustment for short-gap
  jumps, and writes
  `artifacts/us_equity_etf_macro_rotation/latest/external_etf_kline_quality_report.json`.
  The rotation report consumes this quality report and stays blocked/partial
  when unresolved source issues remain.
- QQQ fix: AkShare and the older local CSV both missed the 2005-2011 section.
  The repair script now falls back to Yahoo chart JSON when AkShare raw data has
  long-gap jump evidence. This restored QQQ to a continuous 2001-2026 series and
  removed the last external kline quality blocker.

## 2026-06-27 Playwright spec paths should use forward slashes on Windows

- Scenario: running `npx playwright test frontend\e2e\status-cards.spec.ts`
  from the repo root, or `npx playwright test e2e\status-cards.spec.ts` from
  `frontend`, reported "No tests found" even though `--list` showed the
  `status-cards.spec.ts` test.
- Pitfall: Playwright test file matching treats the CLI argument as a pattern.
  Backslash paths on Windows can fail to match discovered specs and make a good
  status-card test look broken.
- Fix: run from `frontend` with forward slashes:
  `npx playwright test e2e/status-cards.spec.ts`. The project now exposes
  `npm run test:status-cards` as the stable command for this regression check.
  In restricted PowerShell sessions, prefer `npm.cmd run test:status-cards`
  because `npm.ps1` can be blocked by execution policy.

## 2026-06-27 Schema changes must refresh latest artifacts before schema coverage tests

- Scenario: adding new required fields to US equity reports such as incoming
  drop readiness, strategy registry, or vendor-drop operator progress.
- Pitfall: contract tests that instantiate the builder can pass, while
  `test_us_equity_artifact_schema_coverage.py` still fails because the checked
  `artifacts/**/latest/*.json` file is an older shape.
- Fix: after changing a report schema, rerun the concrete builder and then
  `scripts/run_us_equity_daily_production_line.py` before running schema
  coverage. Commit the refreshed latest artifacts with `git add -f` only for
  the reports intentionally touched in that turn.

## 2026-06-27 Blocker taxonomy must classify source-level PIT file blockers

- Scenario: production PIT data is absent and reports emit source-level blockers
  such as `source_delisted_symbols_file_missing` and
  `source_symbol_mapping_file_missing`.
- Pitfall: if the taxonomy only knows generic `local_csv_*`, `bundle`, and
  `provider_*` patterns, these source-level file blockers fall into `other`.
  That creates a fake manual-triage ticket even though the cause is just the
  missing licensed PIT CSV drop.
- Fix: keep `source_*` PIT file blocker patterns in the `external_data`
  keyword set. The expected steady blocked state before data arrives is
  `uncategorized_blockers=0`; any `other` ticket should represent genuinely
  new blocker vocabulary.

## 2026-06-27 Operator progress must show all six required CSV gaps, not only the first blocker

- Scenario: the manual vendor drop is waiting for six licensed CSV files:
  membership events, delisted symbols, corporate actions, symbol mapping,
  adjustment replay, and macro release calendar.
- Pitfall: a report that only surfaces the first blocker tells the operator that
  something is missing, but not the complete checklist of missing or blocked
  files. This slows down handoff and makes partial drops harder to diagnose.
- Fix: `us_equity_vendor_drop_operator_progress_report` now summarizes
  `required_file_progress`, `missing_required_files`, and
  `ready_required_files` from the incoming readiness report. This remains
  metadata-only: it does not read, copy, or transform vendor data.

## 2026-06-27 Hypothesis strategy registry entries need design-spec evidence, not only cards

- Scenario: six US equity strategy families were registered as
  `hypothesis_registered_only` while waiting for production PIT data.
- Pitfall: a strategy card proves there is a human-readable idea, but not that
  the immutable strategy ID, parameter space, data requirements, cost model,
  and failure conditions are bound to a machine-readable design spec.
- Fix: every hypothesis-only registry entry must point to a
  `design_spec_report`, and the registry audit must verify that the report
  exists, is `design_spec_ready`, and its `registry_strategy_id` matches the
  registered strategy ID.

## 2026-06-27 Pytest basetemp can stay locked on Windows

- Scenario: rerunning contract tests with `--basetemp .tmp\pytest` failed before
  test setup with `PermissionError: [WinError 5]` while pytest tried to remove
  the previous basetemp directory.
- Pitfall: on Windows, a prior Python/pytest process, file watcher, antivirus
  scan, or shell handle can keep the old basetemp directory locked. The failure
  looks like test breakage but happens before assertions run.
- Fix: do not reuse a shared `.tmp\pytest` directory for repeated contract
  runs. Use a unique workspace-local basetemp such as
  `.tmp\pytest-us-equity-vendor-drop-<timestamp>` and point `TEMP`/`TMP` at
  `.tmp` before invoking pytest.

## 2026-07-09 IBKR minute backfill must be chunk-balanced and timeout-bound

- Scenario: after IB Gateway Paper was logged in on `127.0.0.1:4002`, the
  read-only QQQ/TQQQ historical probe passed, but long raw 1-minute backfill
  over old 2017 chunks could block for minutes inside an IBKR historical data
  request.
- Pitfall: the project `.venv` may not have `pip` or `ib_insync` installed, so
  IBKR scripts can fail before reaching Gateway. Also, a global
  `max_new_chunks_per_run` can let QQQ consume the whole run budget before TQQQ
  gets a request, creating uneven supplemental coverage.
- Fix: repair the local venv with `.venv\Scripts\python.exe -m ensurepip
  --upgrade`, install `ib_insync`, probe Paper Gateway on port `4002`, and run
  backfill with `--max-new-chunks-per-symbol` plus
  `--request-timeout-seconds`. Timeout failures should become explicit failed
  chunk evidence in the report, not a hung terminal. IBKR bars remain raw
  supplemental data and still require PIT adjustment replay before research
  use.
- 2026-07-09 follow-up: after a fresh Paper login, the `4002` probe still
  passed for QQQ/TQQQ and a bounded 60-new-chunk continuation advanced the
  local raw 1-minute store to common end `2018-07-03T20:59:00+00:00`.
  Full `2017-05-31` to current coverage is not a single interactive run:
  `planned_chunk_count_per_symbol=476`, with hundreds of chunks still deferred.
  Keep running small resumable batches and keep `research_use_status=blocked`
  until full coverage and PIT adjustment replay both pass.
- 2026-07-09 second follow-up: after another Paper login, a 100-chunk-per-symbol
  batch completed and advanced the refreshed report to QQQ
  `2021-03-16T23:59:00+00:00` and TQQQ `2020-11-17T23:59:00+00:00`; a later
  50-chunk-per-symbol continuation wrote extra QQQ/TQQQ parquet chunks but then
  surfaced IBKR `1100` disconnect / `1102` reconnect messages. When this
  happens, terminate only the stuck backfill process, then run a tiny
  `--max-new-chunks-per-symbol 1` continuation to rescan existing chunks and
  refresh `ibkr_minute_backfill_report.json`. Do not treat raw chunk growth as
  research-ready evidence until the report has been refreshed and still shows
  the expected deferred/PIT replay blockers.
- 2026-07-09 third follow-up: the read-only 1-day historical probe must not
  share the same default `data/external/us_equity_intraday/ibkr/interval=1m`
  output root as the long backfill. The probe now writes to
  `data/external/us_equity_intraday/ibkr_probe/interval=1m` so a quick
  connectivity check cannot overwrite the long-history backfill main kline.
- 2026-07-09 fourth follow-up: do not mix `--use-rth` chunks with the existing
  extended-hours IBKR 1-minute backfill. The default importer policy is
  `use_rth=false`, and existing chunks contain extended-hours bars. If a run
  accidentally writes RTH-only chunks, rerun the affected date range without
  `--use-rth` and with `--no-skip-existing`, then refresh the two-symbol report
  with a tiny continuation. After the latest fresh Paper login, the read-only
  extended-hours probe passed with `960` rows per symbol, the accidental RTH
  chunks were overwritten, and the unified raw backfill report stayed
  `partial` / `research_ready_status=blocked` with QQQ `271/476` chunks, TQQQ
  `214/476` chunks, common end `2021-07-06T23:59:00+00:00`, and all
  paper/live/order guardrails false.
- 2026-07-09 fifth follow-up: after another Paper login, a `1 D` read-only
  probe returned IBKR error `162` / empty rows for both QQQ and TQQQ, while the
  same connection returned data with `--duration "2 D"`. Use a bounded `2 D`
  probe for connectivity smoke instead of treating a `1 D` empty response as a
  failed login. A 5-new-chunk-per-symbol continuation then advanced the raw
  supplemental store to QQQ `2023-05-16T23:59:00+00:00` and TQQQ
  `2021-11-30T23:59:00+00:00`; the report correctly remained `partial` /
  `research_ready_status=blocked` because full coverage and PIT adjustment
  replay are still incomplete.
- 2026-07-09 sixth follow-up: a fresh Paper Gateway login confirmed port
  `4002` works while `7497` is connection-refused on this host; the stable
  connectivity smoke is a bounded `2 D` probe, which returned `1009` rows per
  symbol for QQQ/TQQQ. During a bounded continuation IBKR emitted `1100`
  disconnect and `1102` reconnect messages and temporarily reported `ushmds` as
  not connected; let the importer finish and inspect the written report instead
  of assuming strategy failure. A transient empty QQQ chunk for
  `2023-05-03_2023-05-09` was repaired by retrying that exact range, but
  single-symbol retry overwrites the shared `ibkr_minute_backfill_report.json`;
  immediately run a full QQQ/TQQQ bounded continuation afterward to restore the
  global coverage report. The refreshed raw supplemental store reached QQQ
  `2023-07-03T20:59:00+00:00` and TQQQ `2022-01-25T23:59:00+00:00`, still
  `partial` / `research_ready_status=blocked`, with all
  private/account/order/live guardrails false.
- 2026-07-09 seventh follow-up: after the operator logged in again, the bounded
  `2 D` QQQ/TQQQ probe on `127.0.0.1:4002` passed with `1240` rows per symbol
  and latest timestamp `2026-07-09T12:39:00+00:00`. A 5-new-chunk-per-symbol
  continuation then produced no terminal output for several minutes and had to
  be stopped by terminating only the `fetch_us_equity_ibkr_minute_backfill.py`
  `py.exe`/`python.exe` child processes, leaving TWS/IB Gateway untouched. The
  refreshed local backfill report still showed `partial` /
  `research_ready_status=blocked`, common end `2024-01-16T23:59:00+00:00`,
  latest any timestamp `2024-01-23T23:59:00+00:00`, and the expected deferred
  plus PIT-adjustment blockers. Recovery should restart with a tiny
  `--max-new-chunks-per-symbol 1` continuation, then inspect the report rather
  than assuming the raw chunk store is research-ready. A later tiny
  `--max-new-chunks-per-symbol 1` continuation also hung with no terminal
  output and had to be stopped the same way, so when Gateway/HMDS is in this
  state the right next step is a fresh Gateway reconnect plus a new `2 D` probe
  before attempting more backfill.

## 2026-07-09 PowerShell is not Bash for inline Python probes

- Scenario: while extracting a small JSON status summary, a Bash-style
  `py -3 - <<'PY'` heredoc was accidentally run in PowerShell.
- Pitfall: PowerShell treats `<` as a redirection operator and fails before
  Python starts, which creates noisy parser errors unrelated to the quant
  system.
- Fix: use `py -3 -c "..."` for short probes, or write a temporary/reusable
  script through the normal code path when the extraction becomes non-trivial.

## 2026-07-09 Queue reports depend on freshly rebuilt completion dependencies

- Scenario: while refreshing the US equity operator queue, the completion
  dependency builder and next-action queue builder were initially launched in
  parallel.
- Pitfall: `us_equity_next_action_queue_report.json` consumes
  `us_equity_completion_dependency_report.json`; parallel execution can leave
  the queue based on stale dependency evidence even if both commands exit
  cleanly.
- Fix: run `python scripts/build_us_equity_completion_dependency_report.py`
  first, then run `python scripts/build_us_equity_next_action_queue_report.py`.
  Treat queue freshness as dependent on this order, especially before using
  owner/actionability fields for operator handoff.
- 2026-07-09 follow-up: when producing an operator-facing unblock packet and
  completion audit, extend the sequence to
  `completion_dependency -> next_action_queue -> operator_unblock_packet ->
  completion_audit`. The audit reads the operator packet, and the packet reads
  the queue, so all four reports should be refreshed in that order before
  citing open input counts or first-blocker fields.

## 2026-07-09 Paper simulation ledger evidence is a schema-wide contract

- Scenario: the US equity paper-simulation runner already wrote target
  positions, fills, positions, cash ledger, portfolio snapshots, and validation
  state, but there was no first-class per-cycle daily report under the
  independent paper ledger root for manual review.
- Pitfall: adding or removing one ledger evidence type is not a local runner
  change. It must update the broker-free domain payload, runner write path,
  roll report schema, evaluation reader, evaluation schema, contract tests, and
  refreshed artifacts together. Otherwise the UI/operator reports can show a
  valid roll while the evaluation still reasons with an older ledger contract.
- Fix: treat `daily_reports` as a seventh ledger evidence family and write
  `data/paper_ledger/us_equity_etf_rotation_v1/daily_reports/<timestamp>.json`
  only after reconciliation passes. Blocked prestart runs should expose the
  would-be path and zero rows, but must not write the file and must not convert
  expected missing files into ledger-write failures when the upstream roll is
  already blocked.

## 2026-07-09 Execution drill evidence uses the evidence report name

- Scenario: while checking the US equity OMS/execution drill status, looking
  for `us_equity_execution_drill_report.json` made the latest evidence appear
  missing even though the production chain consumes
  `us_equity_execution_drill_evidence_report.json`.
- Pitfall: similarly named execution artifacts can create a false blocker if
  the report name is guessed instead of read from
  `scripts/build_us_equity_completion_dependency_report.py` or the source
  reports section of the dependency artifact.
- Fix: rebuild `python scripts/build_us_equity_execution_drill_evidence_report.py`
  and then refresh the dependent chain in order:
  `completion_dependency -> next_action_queue -> operator_unblock_packet ->
  completion_audit`. The current dependency group `execution_infra_evidence`
  should show `blocked_count=0`; remaining completion blockers belong to
  PIT/data, manual review, natural-time observation, or live governance.

## 2026-07-09 Portfolio promotion evidence must be wired into completion dependencies

- Scenario: `artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json`
  existed and correctly separated fixture, candidate, and promotion evidence,
  but the completion dependency dashboard did not consume it as a milestone.
- Pitfall: a promotion gate artifact can look complete as a standalone skeleton
  while the operator queue and completion audit remain blind to its concrete
  missing layers. This hides portfolio-specific blockers such as production
  event ledger, event-driven flow, ledger PnL, construction controls, cost
  stress, walk-forward, and exposure checks.
- Fix: add `portfolio_promotion_evidence` as an `engineering_after_data`
  milestone in the completion dependency chain, source it from
  `portfolio_promotion`, and refresh
  `portfolio_promotion_evidence -> completion_dependency -> next_action_queue
  -> operator_unblock_packet -> completion_audit` before citing remaining
  portfolio promotion blockers.

## 2026-07-09 Daily monitoring sources need queue-ready owner/action/command coverage

- Scenario: `us_equity_strategy_production_line_report.json` was refreshed and
  blocked correctly, but daily monitoring only consumed the daily production
  runner and next-action queue. Adding the total production-line report as a
  monitoring source exposed a separate queue defect: the existing
  `portfolio_promotion_evidence` next-action item had an empty
  `recommended_command`.
- Pitfall: monitoring a new gate is not just adding one JSON path. The source
  must be listed in expected statuses, blocking statuses, blocked-gate owner
  mapping, recommended command mapping, and tests. Otherwise the dashboard can
  either miss the blocked gate or generate an operator item that fails schema
  coverage because it has no actionable command.
- Fix: wire new monitoring sources through `EXPECTED_STATUSES`,
  `BLOCKING_STATUSES`, `OWNER_BY_SOURCE`, and `COMMAND_BY_SOURCE`; add a
  contract test for the concrete blocked gate; rebuild `next_action_queue`,
  `operator_unblock_packet`, and `daily_monitoring`; then run schema coverage
  before citing the monitoring queue.

## 2026-07-10 Completion audit must cover direct P0/P1/P2 evidence, not only dependency summaries

- Scenario: `us_equity_completion_audit_report.json` was still a 7-phase
  high-level audit and did not directly list portfolio promotion evidence,
  manual decision records, independent paper simulation ledgers, execution
  drills, broker credential review, or daily monitoring as first-class phases.
- Pitfall: a completion audit can look current while important P1/P2 work is
  only indirectly visible through the dependency dashboard or operator queue.
  Another pitfall is classifying every `not_complete` blocker as natural-time
  progress; `not_ready`, `not_passed`, `source_blocked`, missing manual fields,
  and open operator queues are hard blocked gates.
- Fix: add direct audit phases for portfolio promotion, manual review/decision
  record, paper simulation ledger, execution/broker safety, and monitoring
  replay/incident evidence. Classify only the forward-observation natural-time
  window as `in_progress`; keep other failed gate evidence as `blocked`. After
  changing audit source coverage, refresh the concrete latest artifact and run
  both the audit contract and schema coverage.

## 2026-07-10 Completion audit rules must live below the CLI entrypoint

- Scenario: after expanding the completion audit to direct P0/P1/P2 phases,
  the core classification logic still lived in
  `scripts/build_us_equity_completion_audit_report.py`.
- Pitfall: a script can look like a harmless report builder while carrying
  production gate rules. That makes the logic harder to reuse from monitoring,
  harder to test with fake inputs, and easier for future changes to fork a
  second completion definition.
- Fix: move completion phase classification, blocker extraction, markdown
  rendering, and fail-closed guardrails into
  `quant_us/monitoring/completion_audit.py`; keep the script as a thin CLI
  wrapper. Add a contract test that imports through the script but asserts the
  callable comes from the monitoring service module. After this kind of move,
  rebuild the concrete latest artifact and rerun both the focused audit tests
  and the production-line/schema coverage tests.
- Follow-up pitfall: refreshed latest artifacts under
  `artifacts/us_equity_strategy_production_line/` can be ignored by the local
  `.gitignore`, so a normal `git add` may skip the report even when it appears
  as modified. Use `git add -f` for the specific refreshed report path only;
  do not force-add broad artifact directories.

## 2026-07-10 Completion dependency rules must share the same service boundary

- Scenario: `us_equity_completion_dependency_report.json` is the upstream
  dependency dashboard consumed by the next-action queue, operator unblock
  packet, daily production line, and completion audit, but its milestone and
  blocker classification still lived in
  `scripts/build_us_equity_completion_dependency_report.py`.
- Pitfall: if this report remains script-owned while downstream reports are
  service-owned, the production line can end up with two architecture styles
  for one gate chain. It also encourages refreshing only the first report and
  accidentally leaving queue/operator/audit evidence stale.
- Fix: move dependency milestone classification, grouping, operator action
  extraction, markdown rendering, and fail-closed guardrails into
  `quant_us/monitoring/completion_dependency.py`; keep the script as a thin
  CLI wrapper. When this report changes, refresh in order:
  `completion_dependency -> next_action_queue -> operator_unblock_packet ->
  completion_audit`, then run the focused dependency/queue/operator/audit
  tests plus schema coverage.

## 2026-07-10 Strategy production line rules must not stay script-owned

- Scenario: `us_equity_strategy_production_line_report.json` is the first-class
  gate monitored by daily monitoring and the daily production runner, but its
  stage order, evidence-chain checks, unsafe-flag detection, architecture layer
  contract, markdown rendering, and fail-closed output logic still lived in
  `scripts/build_us_equity_strategy_production_line_report.py`.
- Pitfall: leaving this P0 gate as script-owned while completion dependency and
  audit are service-owned creates a split governance chain. It also makes
  importers such as the registry report and daily production runner depend on
  a CLI file for domain constants like `STAGE_ORDER`.
- Fix: move the strategy production-line rules into
  `quant_us/monitoring/strategy_production_line.py` and keep the script as a
  thin CLI wrapper that re-exports compatibility symbols. Add a contract test
  asserting the builder comes from the monitoring service module. After
  refreshing `us_equity_strategy_production_line_report.json`, refresh
  `us_equity_daily_monitoring_report.json` as well; that builder also updates
  incident template, replay diff, and operator queue artifacts, which should be
  committed together when regenerated.

## 2026-07-10 Broker credential review report assembly belongs in live service code

- Scenario: the broker credential evaluator already lived in
  `quant_us/live/broker_credentials_review.py`, but the report builder still
  assembled payloads, markdown, secret-scan summaries, and atomic artifact
  writes inside `scripts/build_us_equity_broker_credentials_review_report.py`.
- Pitfall: even when validation rules are service-owned, leaving report
  assembly in a CLI script creates a second place where paper/live unlock flags,
  secret redaction, and local-review write policy can drift. It also makes the
  daily production line import a script for a P1 safety gate.
- Fix: move metadata-only report assembly into
  `quant_us/live/broker_credentials_review_report.py`; keep the script as a
  thin CLI wrapper. Add a contract test asserting the builder comes from the
  live service module. After refreshing broker credential review, refresh
  dependent artifacts in order: broker handoff, execution drill evidence,
  completion dependency, next-action queue, operator unblock packet,
  completion audit, then daily monitoring. All refreshed artifacts must keep
  `live_order_allowed=false`, `order_endpoint_allowed=false`, and
  `broker_calls_used=false`.

## 2026-07-10 Manual decision-record report assembly belongs in live service code

- Scenario: the manual decision evaluator already lived in
  `quant_us/live/manual_decision_record.py`, but payload assembly, Markdown
  rendering, atomic writes, and paper/live guardrails remained in
  `scripts/build_us_equity_manual_decision_record_report.py`.
- Pitfall: a CLI-owned report can silently become a second governance layer,
  while the daily production runner imports that CLI as if it were reusable
  service code. A malformed local JSON file also caused the command to crash
  before it could preserve a fail-closed report.
- Fix: move report assembly into
  `quant_us/live/manual_decision_record_report.py`, keep the script as a thin
  CLI compatibility entrypoint, assert the callable's service-module
  ownership in contract tests, and treat unreadable/non-object local JSON as
  invalid evidence. Refresh manual decision, manual review, paper readiness,
  dependency queue, completion audit, and daily monitoring evidence before
  citing current gate state.

## 2026-07-10 Manual-review packet assembly must not remain in the CLI

- Scenario: `quant_us/live/manual_review_packet.py` owned the evidence checks,
  but the CLI still read ten upstream reports, assembled the packet and
  guardrails, rendered Markdown, and wrote artifacts.
- Pitfall: this leaves reusable governance orchestration in `scripts/` and
  makes the daily production runner depend on a CLI module. An unreadable
  upstream JSON also terminated the packet builder instead of producing a
  review-pending artifact.
- Fix: move report orchestration into
  `quant_us/live/manual_review_packet_report.py`, leave only argument parsing
  in the script, assert service ownership in contract tests, and convert
  unreadable/non-object source reports into invalid evidence so the manual
  review gate remains fail-closed. Refresh downstream paper readiness,
  completion dependencies, operator queue, audit, and daily monitoring in
  dependency order.

## 2026-07-10 Paper-readiness report assembly is a live service boundary

- Scenario: the readiness evaluator already enforced manual review, decision
  traceability, strategy validation, forward evidence, PIT acceptance, and
  safety flags in `quant_us/live/paper_simulation_readiness.py`, while its CLI
  still loaded eight reports and owned the persisted gate payload.
- Pitfall: CLI-owned gate assembly can drift from the evaluator and makes a
  malformed upstream JSON terminate the daily chain. A complete manual record
  can also look persuasive unless the report explicitly proves that it cannot
  bypass blocked strategy, forward, or PIT evidence.
- Fix: move evidence loading, report/Markdown assembly, and atomic writes into
  `quant_us/live/paper_simulation_readiness_report.py`; leave the script as a
  thin entrypoint. Contract-test service ownership, malformed evidence, and a
  complete manual record combined with blocked upstream gates. In every case,
  keep `paper_runner_allowed=false` and all live/order flags false.

## 2026-07-10 Paper roll orchestration belongs in a live service, not a CLI

- Scenario: pure paper-row rules lived in
  `quant_us/live/paper_simulation_roll.py`, but the 300-line CLI still owned
  preflight, idempotency, state recovery, reconciliation, seven ledger writes,
  and the final roll artifact.
- Pitfall: importing the CLI from the daily production line hides a service
  boundary and makes malformed readiness or validation-state JSON an uncaught
  failure. Treating a corrupt state as an empty initial state would be worse:
  it could append duplicate targets, fills, positions, cash and snapshots.
- Fix: move the broker-free use case into
  `quant_us/live/paper_simulation_runner.py` and keep the script as argument
  parsing only. Malformed readiness must block before the paper root is
  created; malformed validation state must block before any append. Contract
  tests assert service ownership and zero ledger writes while all broker,
  private, order and live flags remain false.

## 2026-07-10 Independent paper ledger writes need a recoverable unit of work

- Scenario: one successful paper cycle appended target, fills, positions,
  cash, and snapshots, then separately replaced validation state and the daily
  report.
- Pitfall: a process or disk failure between those writes leaves a half-cycle.
  If validation state was not written, a retry can duplicate fills and cash;
  if state was written too early, idempotency can hide missing ledger rows.
- Fix: stage complete replacement bytes for all seven evidence files under
  `.transactions/<transaction_id>`, preserve before-images, and atomically
  journal `PREPARED -> APPLYING -> COMMITTED`. A caught apply failure restores
  every before-image and records `ROLLED_BACK`; the next process recovers any
  pending transaction before a new cycle. Runner tests must prove a failed
  transaction produces a BLOCKED report and no partial paper ledger while
  live/order/broker flags stay false.

## 2026-07-10 Paper equity must be marked and replayed from ledgers

- Scenario: the paper runner carried `current_equity` from the previous cycle
  and only subtracted current slippage/financing. It did not mark yesterday's
  quantities at today's prices, and position rows could trust forward-provided
  shares/notionals without proving them from fills.
- Pitfall: a trend strategy could run for weeks while paper equity ignored all
  market returns. Snapshot-to-cash checks still looked clean because the same
  incorrect `final_equity` value was copied into every ledger family.
- Fix: persist current cash and quantities, mark them at current prices before
  rebalancing, derive target quantity deltas and standard paper fills, then set
  equity to `ending_cash + marked_position_value`. Evaluation must adapt those
  rows into `quant_us.backtest.ledger_pnl`, replay canonical cash/positions/PnL,
  and block on snapshot, cash, fill-integrity or position-quantity divergence.
  Forward `shares` and `notionals` are advisory inputs, not paper ledger truth.
