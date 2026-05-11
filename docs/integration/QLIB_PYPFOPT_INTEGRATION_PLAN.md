# Qlib + PyPortfolioOpt Integration Plan

Status: implemented for phase-1 daily research integration.

Date: 2026-05-11

## Executive Boundary

This integration must add two adapter layers without replacing the existing trading system.

- Qlib is a research/model experiment engine only.
- PyPortfolioOpt is a portfolio construction engine only.
- Existing QuantStation data quality gates, promotion gate, event-driven backtest, risk, OMS, paper broker, ledger, reconciliation, and live safety gates remain authoritative.
- No Qlib output may be marked `paper_ready` or `live_ready`.
- No PyPortfolioOpt output may become an order directly.
- First phase is daily-only. Minute bars remain out of scope for Qlib and PyPortfolioOpt integration.

Current local dependency state in the project `venv`:

- `qlib`: installed
- `pypfopt`: installed
- `lightgbm`: installed

Adapters still degrade with explicit errors and support dry-run paths when a different environment lacks these optional packages. These packages must not become import-time dependencies of backend startup, CLI startup, or existing tests.

## Current Project Structure Observed

### Data Layer

Primary modules:

- `quant_us/data/pipeline.py`
  - `DataLakeService`
  - `DataLakeConfig`
  - `sync_bars()`
  - `read_cleaned_bars()`
- `quant_us/data/storage/parquet_store.py`
  - `ParquetBarStore`
  - partitioned bar storage
- `quant_us/data/storage/data_manifest.py`
  - `DataManifest`
  - `DataManifestStore`
  - `build_manifest_from_quality()`
  - `validate_manifest_for_promotion()`
- `quant_us/data/minute_quality_gate.py`
  - raw/cleaned minute quality overview
- `quant_us/data/connectors/yfinance_data.py`
- `quant_us/data/connectors/us_equity_ingestion.py`

Observed cleaned data path:

```text
data/cleaned/vendor=yfinance/asset_class=equity/bar_size=<bar_size>/symbol=<SYMBOL>/date=<YYYY-MM-DD>.parquet
```

Observed daily symbols currently available locally:

```text
AAPL, AMZN, GOOGL, MSFT, SPY, TSLA
```

Observed daily manifest files include:

```text
qs-yfinance-AAPL-1d-07ff0bf4c583.json
qs-yfinance-AAPL-1d-a897cf840620.json
qs-yfinance-AAPL-1d-d901e2b00523.json
qs-yfinance-GOOGL-1d-9a612c0ccb9b.json
qs-yfinance-IWM-1d-cdbd696a79f8.json
qs-yfinance-META-1d-d9cb9db38d81.json
qs-yfinance-MSFT-1d-a5a88bf14005.json
qs-yfinance-NVDA-1d-d30210b6212b.json
qs-yfinance-SPY-1d-268b4e155ee3.json
```

The requested phase-one universe also includes `QQQ`, `DIA`, `XLK`, `XLF`, and `XLE`; those cleaned daily partitions are not currently present under the observed cleaned-data tree. The Qlib export must fail clearly if a requested symbol is missing rather than downloading implicitly.

### Data Manifest Contract

`DataManifest` already carries the fields needed for Qlib export lineage:

- `data_version`
- `source`
- `symbol`
- `interval`
- `asset_class`
- `timezone`
- `adjustment_policy`
- `corporate_action_adjustment`
- `start`
- `end`
- `row_count`
- `expected_rows`
- `coverage_pct`
- `fingerprint`
- `checksum`
- `quality_score`
- `raw_path`
- `cleaned_path`
- `universe_id`
- `universe_source`
- `survivorship_bias_risk`

Qlib export should treat `DataManifestStore.read(data_version)` as canonical for single-symbol runs and should create a Qlib-specific dataset manifest that references all source manifests and source hashes for multi-symbol universes.

### Research / Factor Layer

Primary modules:

- `quant_us/factors/`
  - factor pipeline, evaluation, formula DSL
- `quant_us/research/lab/manifest.py`
  - `ResearchExperimentManifest`
  - `StrategyCandidate`
  - `ExperimentManager`
- `quant_us/research/automation/pipeline.py`
- `quant_us/research/automation/promotion_gate.py`
- `quant_us/research/automation/factor_mining.py`
- `quant_us/research/validation.py`
- `quant_us/research/evidence_registry.py`
- `quant_us/research/evidence_pack.py`
- `quant_us/research/model_scores.py`
  - currently a linear-model scoring helper that writes scores into the feature store shape, not a dedicated `research_model_scores` table.

Implication: the Qlib score importer should not overload `LinearModelScoreBuilder`. It should create a dedicated adapter-owned persisted score artifact first, then optionally expose a bridge into the existing feature/research scoring surface.

Recommended score artifact path:

```text
artifacts/qlib_runs/<run_id>/research_model_scores.parquet
```

Recommended schema:

```text
run_id
model_id
source
data_version
datetime
symbol
score
rank
universe
feature_set
label
created_at
```

### Strategy Manifest Layer

Primary module:

- `quant_us/research/strategy_manifest.py`
  - `StrategyCandidateManifest`
  - `StrategyManifestManager`

Important current behavior:

- `StrategyManifestManager.create_from_candidate()` requires `ResearchPromotionGate` decision `READY_FOR_PAPER_REVIEW`.
- Existing strategy manifests are stored under:

```text
data/research/manifests/<manifest_id>/manifest.json
```

Current local registry state after prior work:

```text
strategy_manifest_count = 6
paper_review_count = 0
candidate_count = 9
data_manifest_count = 12
```

The user's older note that `strategy_manifest_count=0` is no longer true in this workspace. However, the Qlib manifest should still be added as a new `source=qlib` candidate-style manifest and must not bypass the internal promotion gate.

Planning decision:

- Do not reuse `StrategyManifestManager.create_from_candidate()` for raw Qlib outputs because it is designed for candidates that already passed the internal promotion gate.
- Add `compile_qlib_strategy_manifest.py` as a Qlib adapter compiler that writes a Qlib research manifest with `promotion_status="candidate"` or `status="candidate"` in an adapter schema.
- If later promoted into native `StrategyCandidateManifest`, it must be done through the existing candidate/promotion path after event-driven backtest, cost stress, walk-forward, evidence pack, and paper review prerequisites.

### Backtest and Promotion Gate

Primary modules:

- `quant_us/backtest/engine.py`
- `quant_us/backtest/unified_runner.py`
- `quant_us/backtest/runner.py`
- `quant_us/backtest/timeframe_scheduler.py`
- `quant_us/research/automation/promotion_gate.py`
- `scripts/run_backtest.py`
- `scripts/run_research_experiment.py`
- `quant_us/cli.py`

Current important semantics:

- Event-driven engine owns execution semantics.
- Recent implementation fixes default semantics to signal-at-bar-close / order-next-bar.
- Multi-timeframe scheduler exists for backtest, but Qlib integration phase one must not use minute bars.
- Promotion gate is the automated research arbiter before human paper review.

Qlib backtest output must be treated as diagnostic research evidence only. It must never replace the event-driven backtest manifest required by `ResearchPromotionGate`.

### Portfolio Construction

Primary modules:

- `quant_us/portfolio/construction/allocator.py`
  - equal weight
  - inverse volatility
  - risk parity
  - HRP baseline
  - vol targeting
  - drawdown adjustment
- `quant_us/portfolio/construction/engine.py`
  - `PortfolioConstructionEngine`
  - `PortfolioTarget`
- `quant_us/risk/pre_trade.py`
  - `PortfolioRiskPolicy`
  - `PreTradeRiskEngine`
- `quant_us/core/types.py`
  - `TargetPosition`
  - `OrderIntent`
  - `RiskDecision`

Important boundary:

- Portfolio construction can emit target weights or target positions only.
- Existing risk and OMS are responsible for converting intents into approved orders.
- `PyPortfolioOpt` must not import or call `quant_us.execution.*`, `quant_us.live.*`, brokers, OMS, or paper runtime.

### Paper / Risk / Ledger / Reconciliation

Primary modules:

- `quant_us/risk/pre_trade.py`
- `quant_us/risk/post_trade.py`
- `quant_us/risk/kill_switch.py`
- `quant_us/execution/oms.py`
- `quant_us/execution/ledger.py`
- `quant_us/execution/paper_broker.py`
- `quant_us/live/paper_runtime.py`
- `quant_us/live/reconciliation_service.py`
- `quant_us/live/shadow_live.py`

These modules are explicitly out of scope for Qlib/PyPortfolioOpt replacement.

### Frontend / System Overview

Primary modules:

- `backend/app/api/app_factory.py`
  - `_system_overview_payload()`
  - `/api/system/overview`
- `frontend/src/workspaces/USEquityWorkspace.tsx`
- `frontend/src/lib/shared-types.ts`
- `frontend/src/workspaces/ResearchDashboard.tsx`

Current system overview state from local workspace:

```text
status = blocked
stage = paper_credentials_blocked
minute_data_quality.status = WARN
registry.integrity = PASS/STABLE
paper_review_count = 0
```

If Qlib/PyPortfolioOpt status is later exposed to the frontend, it should be added as research-only observability and should not affect live readiness directly.

## Proposed New Modules

### Qlib Adapter

Add:

```text
integrations/
  qlib_adapter/
    __init__.py
    export_to_qlib.py
    build_qlib_dataset.py
    run_qlib_workflow.py
    import_pred_score.py
    import_recorder_metrics.py
    compile_qlib_strategy_manifest.py
    schemas.py
    README.md
```

Responsibilities:

- Read only cleaned daily data from `DataLakeService` or `ParquetBarStore`.
- Validate data before export.
- Write Qlib input artifacts under `artifacts/qlib_runs/<run_id>/`.
- Convert/dump provider data only when `qlib` is installed.
- Run Qlib workflow only when `qlib` and model dependencies are installed.
- Import `pred_score` into a QuantStation-owned score schema.
- Compile a research-only Qlib strategy manifest.

Non-responsibilities:

- No risk checks.
- No order creation.
- No paper broker.
- No ledger writes.
- No live state changes.
- No implicit data download.

### PyPortfolioOpt Adapter

Add:

```text
integrations/
  pypfopt_adapter/
    __init__.py
    build_expected_returns.py
    build_covariance.py
    optimize_weights.py
    import_target_weights.py
    schemas.py
    README.md
```

Responsibilities:

- Read Qlib-imported score artifacts.
- Build expected return proxies without lookahead.
- Build covariance matrices from past daily returns only.
- Produce long-only target weights.
- Persist target weights under `artifacts/portfolio_runs/<portfolio_run_id>/`.
- Optionally convert target weights into existing `TargetPosition` schema for internal backtest/paper simulation entry.

Non-responsibilities:

- No order creation.
- No OMS calls.
- No broker calls.
- No live/paper submission.

## Proposed Config and Artifact Layout

Requested prompt uses `configs/`, but this repo currently has `config/` and no `configs/`.

Recommendation:

- Use `configs/` for third-party integration configs as requested, because it is additive and avoids mixing with current core config files.
- Do not rename or move existing `config/`.

Add later:

```text
configs/
  universe/
    us_core_liquid.yaml
  qlib/
    us_lgbm_alpha158_daily.yaml
  portfolio/
    pypfopt_long_only_max_sharpe.yaml
    pypfopt_long_only_min_volatility.yaml
    pypfopt_hrp.yaml

artifacts/
  qlib_runs/
  portfolio_runs/
```

`artifacts/` should hold generated run outputs. Tests should use temporary directories and must not rely on committed runtime artifacts.

## Data Flow

```text
data/cleaned daily parquet
  + data/manifests/<data_version>.json
        |
        v
daily quality/export gate
        |
        v
integrations/qlib_adapter/export_to_qlib.py
        |
        v
artifacts/qlib_runs/<run_id>/qlib_input/dataset_manifest.json
        |
        v
integrations/qlib_adapter/build_qlib_dataset.py
        |
        v
artifacts/qlib_runs/<run_id>/qlib_provider/
        |
        v
integrations/qlib_adapter/run_qlib_workflow.py
        |
        v
pred_score.parquet + recorder_metrics.json + qlib_backtest_summary.json
        |
        v
integrations/qlib_adapter/import_pred_score.py
        |
        v
research_model_scores adapter artifact
        |
        v
integrations/pypfopt_adapter/build_expected_returns.py
        |
        v
expected_returns.parquet
        |
        v
integrations/pypfopt_adapter/build_covariance.py
        |
        v
covariance.parquet
        |
        v
integrations/pypfopt_adapter/optimize_weights.py
        |
        v
target_weights.parquet
        |
        v
integrations/pypfopt_adapter/import_target_weights.py
        |
        v
TargetPosition-compatible portfolio input
        |
        v
existing internal event-driven backtest / risk gate / promotion gate
        |
        v
paper review gate
        |
        v
live remains frozen
```

## Data Contract for Qlib Export

Phase-one accepted input:

- `bar_size == "1d"`
- `asset_class == "equity"`
- `source` initially `yfinance` or any source already represented in `DataManifestStore`
- UTC timestamps
- symbols explicitly requested in a universe config
- no implicit downloads

Minimum exported fields:

```text
datetime
symbol
open
high
low
close
volume
factor
data_version
source_manifest_hash
```

Validation before export:

- required columns exist
- `datetime + symbol` unique
- `open/high/low/close` finite and positive
- `high >= max(open, close)`
- `low <= min(open, close)`
- `volume >= 0`
- date is in requested calendar range
- no duplicate `datetime-symbol`
- missing rate computed by expected trading calendar
- every requested symbol has cleaned daily data and a manifest binding

Failure behavior:

- Write no provider output if export validation fails.
- Write a clear failure report if a run directory already exists.
- Do not call yfinance or any other vendor from Qlib adapter.

## PyPortfolioOpt Contract

Inputs:

- imported Qlib scores
- daily cleaned returns
- optional current weights
- portfolio config

Outputs:

```text
portfolio_run_id
source_score_run_id
datetime
symbol
target_weight
raw_weight
clipped_weight
optimizer
constraints_hash
fallback
created_at
```

Constraints:

- long-only
- no negative weights
- total target weight <= `1 - cash_buffer`
- each symbol <= `max_weight`
- turnover <= `max_turnover` or explicit failure/fallback
- no leverage
- no shorting

No-lookahead requirements:

- expected return on date T can use scores observed at or before T only.
- covariance for rebalance date T can use returns strictly before T, or at most through the last completed prior bar depending on chosen convention.
- `forward_return_fit` must use expanding/walk-forward calibration only.

## Modules That May Be Added

- `integrations/qlib_adapter/*`
- `integrations/pypfopt_adapter/*`
- `configs/qlib/*`
- `configs/portfolio/*`
- `configs/universe/us_core_liquid.yaml`
- `docs/integration/*`
- `tests/integrations/*`

## Existing Modules That May Need Small Additive Changes Later

- `quant_us/cli.py`
  - optional wrappers for integration commands, after module CLIs work.
- `backend/app/api/app_factory.py`
  - optional read-only integration status exposure.
- `frontend/src/lib/shared-types.ts`
  - optional type additions for Qlib/PyPortfolioOpt observability.
- `frontend/src/workspaces/ResearchDashboard.tsx`
  - optional read-only cards.
- `quant_us/research/model_scores.py`
  - optional bridge if score artifacts need to appear in existing feature-store views.
- `quant_us/research/evidence_registry.py`
  - optional evidence indexing for Qlib/PyPortfolioOpt artifacts.

All changes should be additive and gated. Existing behavior must not depend on Qlib/PyPortfolioOpt being installed.

## Modules That Must Not Be Replaced or Rewired

- `quant_us/risk/*`
- `quant_us/execution/*`
- `quant_us/live/*`
- `quant_us/backtest/engine.py`
- `quant_us/backtest/unified_runner.py`
- `quant_us/research/automation/promotion_gate.py`
- `quant_us/research/strategy_manifest.py` core gate semantics
- existing paper broker, ledger, reconciliation, kill-switch logic

Adapters may consume their outputs or create inputs for them, but must not bypass them.

## CLI Boundary

First module-level commands should exist exactly as module entry points:

```bash
python -m integrations.qlib_adapter.build_qlib_dataset \
  --data-version latest \
  --universe configs/universe/us_core_liquid.yaml \
  --start-date 2020-01-01 \
  --end-date 2025-12-31

python -m integrations.qlib_adapter.run_qlib_workflow \
  --config configs/qlib/us_lgbm_alpha158_daily.yaml

python -m integrations.qlib_adapter.import_pred_score \
  --run-id <run_id>

python -m integrations.qlib_adapter.compile_qlib_strategy_manifest \
  --run-id <run_id>

python -m integrations.pypfopt_adapter.optimize_weights \
  --score-run-id <run_id> \
  --config configs/portfolio/pypfopt_long_only_max_sharpe.yaml

python -m integrations.pypfopt_adapter.import_target_weights \
  --portfolio-run-id <portfolio_run_id>
```

Later optional `quant_us.cli` wrappers can be added after tests prove these module commands are stable.

## Major Risks

1. Qlib US daily data format mismatch.
   - Qlib examples are often China-market oriented. The adapter must isolate custom calendar/instrument logic and avoid modifying Qlib source.

2. Missing phase-one universe data.
   - Current cleaned daily partitions do not cover all requested symbols. Adapter must fail clearly instead of downloading silently.

3. Score schema ambiguity.
   - Existing `quant_us/research/model_scores.py` writes feature-store style factor values. The integration needs a clear `research_model_scores` adapter artifact first.

4. Qlib backtest over-trust.
   - Qlib recorder metrics are research evidence only. Internal event-driven backtest remains required.

5. Dependency blast radius.
   - `qlib`, `lightgbm`, and `pypfopt` are not installed locally. Imports must be inside functions/commands with explicit install messages.

6. Lookahead in expected returns/covariance.
   - PyPortfolioOpt inputs must be generated with strict date cutoffs and tested with adversarial fixtures.

7. Portfolio weights bypassing risk.
   - Target weights must remain target weights or `TargetPosition` objects. No `OrderIntent` creation inside PyPortfolioOpt adapter.

8. Runtime artifact churn.
   - Generated files under `artifacts/` should be reproducible and testable, but tests must use temp roots.

9. Frontend misinterpretation.
   - Read-only Qlib/PyPortfolioOpt status cards must not imply paper/live readiness.

## Phased Execution Plan

### Phase 0: Planning and Boundary Confirmation

Completed by this document.

Deliverable:

- `docs/integration/QLIB_PYPFOPT_INTEGRATION_PLAN.md`

No production code change.

### Phase 1: Qlib Data Export Skeleton

Add:

- `integrations/qlib_adapter/schemas.py`
- `integrations/qlib_adapter/export_to_qlib.py`
- `configs/universe/us_core_liquid.yaml`
- tests for export schema and validation

Definition of done:

- Can export fake/small cleaned daily fixtures into `qlib_input`.
- Invalid OHLC, duplicate date-symbol, negative volume, or missing symbol fails clearly.
- No Qlib dependency required.

### Phase 2: Qlib Provider and Workflow Wrappers

Add:

- `build_qlib_dataset.py`
- `run_qlib_workflow.py`
- `import_recorder_metrics.py`
- `configs/qlib/us_lgbm_alpha158_daily.yaml`

Definition of done:

- Missing Qlib/LightGBM reports a clear dependency error.
- Dry-run validates paths and writes metadata.
- If dependencies are installed, run artifacts land under `artifacts/qlib_runs/<run_id>/`.

### Phase 3: Qlib Score Import and Research Manifest Compile

Add:

- `import_pred_score.py`
- `compile_qlib_strategy_manifest.py`
- tests for rank, duplicate rejection, candidate-only manifest status

Definition of done:

- `pred_score.parquet` imports to adapter `research_model_scores.parquet`.
- Rank is computed per datetime cross-section.
- Compiled Qlib manifest has `promotion_status = candidate`.
- No paper/live readiness fields are set.

### Phase 4: PyPortfolioOpt Adapter

Add:

- `build_expected_returns.py`
- `build_covariance.py`
- `optimize_weights.py`
- `import_target_weights.py`
- `configs/portfolio/*.yaml`

Definition of done:

- Expected returns and covariance are no-lookahead.
- `max_sharpe`, `min_volatility`, and `hrp` modes are implemented when PyPortfolioOpt is installed.
- Missing dependency gives clear install guidance.
- Fallback to equal-weight top-k is explicit and reported.
- Output is target weights only.

### Phase 5: Integration Tests and Read-Only Observability

Add:

- `tests/integrations/test_qlib_to_pypfopt_pipeline.py`
- `tests/integrations/test_no_live_side_effects.py`
- optional backend/frontend read-only status exposure

Definition of done:

- Fake data can run cleaned data -> Qlib-like score -> expected returns -> covariance -> target weights -> Qlib candidate manifest.
- Test proves no imports/calls into live broker submission path.
- Existing full test suite remains green.

## Acceptance Interpretation

The requested final acceptance target is valid, but should be interpreted in sequence:

1. First prove export/import/contracts with fake and local cleaned daily data.
2. Then install optional dependencies and run Qlib daily baseline.
3. Then generate real `pred_score.parquet`.
4. Then compile a Qlib candidate manifest.
5. Then run PyPortfolioOpt target weight generation.
6. Then feed target weights into internal risk/backtest/promotion flow.
7. Only after internal evidence passes should paper review be considered.
8. Live remains frozen.

## Immediate Next Step

Implement Phase 1 only:

- add adapter package skeleton
- add Qlib export schema and validation
- add daily-only universe config
- add tests for export schema, duplicate rejection, invalid OHLC, negative volume, missing symbol, and no implicit data download

Do not implement Qlib workflow execution until the export contract is tested.
