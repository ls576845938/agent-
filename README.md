# QuantStation vNext

Research-first quant platform being migrated toward a personal US equity
"light institutional" architecture. The current backend remains compatible with
the existing console, while the new `quant_us` package introduces the production
shape for long-term US equity research, event-driven simulation, paper trading,
and live execution.

Existing console capabilities:

- Binance Spot K-line downloader, local SQLite market-data warehouse, manual backfill, incremental update, and in-process daily scheduler
- Python backend for single-strategy and portfolio backtesting
- FastAPI API contract for a single Web console
- React/Vite frontend for running backtests and reviewing equity, drawdown, and trade markers
- Optional live-trading adapter boundary that does not block research workflows when vn.py is absent

New US equity platform foundation:

- Shared domain contracts for `Signal`, `TargetPosition`, `OrderIntent`, `RiskDecision`, `Order`, `Fill`, `Position`, and `PortfolioSnapshot`
- Event-driven chain: market data -> strategy signal -> target position -> portfolio rebalance -> order intent -> pre-trade risk -> OMS -> broker fill -> ledger/account update
- US equity session calendar with regular, pre-market, after-hours, and optional overnight sessions
- Data lake contracts for raw/cleaned/feature data, including bar cleaning, session flags, Parquet partitions, and DuckDB query boundary
- Reusable strategy, portfolio, risk, OMS, broker, simulated broker, and event-driven backtest modules under `quant_us`

## Repository layout

- `backend/app/core`: settings, logging, exceptions, shared dependencies
- `backend/app/domain`: strategy implementations, risk controls, domain models
- `backend/app/services`: market data loading/downloading, SQLite data warehouse, backtest execution, run registry
- `backend/app/api`: FastAPI schemas and app factory
- `backend/app/live`: optional vn.py compatibility layer
- `backend/tests`: unittest-based backend verification
- `frontend`: Vite + React control console
- `quant_us/core`: shared events, clock/calendar, enums, and domain types
- `quant_us/data`: connectors, Parquet/DuckDB storage boundaries, cleaners, validators, and universe tools
- `quant_us/strategies`: signal-only strategy implementations
- `quant_us/portfolio`: target sizing, allocation combining, and rebalance planning
- `quant_us/risk`: pre-trade, post-trade, liquidity, exposure, and kill-switch controls
- `quant_us/execution`: OMS and broker adapter boundaries
- `quant_us/backtest`: event-driven simulation broker, slippage, commission, and performance
- `quant_us/research`: leakage-aware ML/research dataset builders and manifests
- `config`: starter YAML configs for data, broker, risk, and strategies
- `scripts`: CLI entry points for ingestion, backtest, paper, live, and reconciliation

## Quant System Framework

The project now follows a production-oriented quant layout:

- Data layer: Binance Spot REST K-line ingestion, idempotent SQLite upserts, coverage metadata, sync-run audit log, database preview API.
- Research layer: deterministic fixture data for smoke tests, SQLite data for real backtests, single-strategy and portfolio simulation, risk scaling, drawdown circuit breaker, dynamic weights.
- Backtest validation layer: single run diagnostics, parameter robustness/OOS optimization, cost stress testing, and walk-forward market-regime slicing through shared strategy code.
- Execution boundary: `backend/app/live` keeps vn.py integration optional and isolated until API keys, gateways, and production risk controls are configured.
- Operations layer: health checks, API-key guard, structured logs, explicit errors, retry-safe sync runs, and an in-process daily updater for workstation deployments.

For a larger production deployment, keep SQLite for local research and replace the scheduler with systemd/cron/Airflow plus a server-grade database such as PostgreSQL/TimescaleDB.

## Quick start

### Backend

1. Install Python dependencies from `pyproject.toml`
2. Configure `.env` from `.env.example` if needed
3. Start the API:

```bash
python -m backend.app
```

The backend defaults to deterministic fixture data, so it can run without a SQLite database.

### Download Binance K-lines

The default database is `data/market_data.sqlite`. It is created automatically.

```bash
curl -X POST http://127.0.0.1:8000/api/data/sync \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "interval": "1m",
    "start": "2024-01-01T00:00:00Z",
    "end": "2024-01-03T23:00:00Z",
    "closed_only": true
  }'
```

Use the frontend **数据管理** panel to download a date range, update to the latest closed candle, start/stop the daily updater, and preview database rows. After data is downloaded, choose `SQLite` as the backtest data source.

### Frontend

```bash
cd frontend
npm run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

### Research validation flow

The crypto research console now exposes the staged validation path used before
paper trading:

The MVP delivery path is available from the frontend through **一键 MVP 验收**.
It runs the minimum closed loop in order: data quality check, backtest, chart
artifact fetch, research promotion gate, and experiment-registry write. The
status panel shows whether the current configuration has a complete MVP record.

1. Run a single-strategy or portfolio backtest.
2. Run **当前优先优化** for train/validation parameter robustness.
3. Run **成本压力测试** to expand fees and slippage.
4. Run **Walk-forward** to test expanding-window OOS slices and market regimes.
5. Run **组合优化** to compare current weights with correlation-aware,
   risk-budgeted strategy allocation.
6. Run **数据质量检查** to record coverage, missing bars, anomalies, a stable
   dataset fingerprint, and a reproducible data version before promoting a run.
7. Run **研究准入门** to aggregate data quality, core backtest survival,
   execution cost, risk gates, strategy-version fingerprint, a reproducible
   promotion manifest, and an optional experiment-registry record.

The corresponding API endpoints are:

- `POST /api/backtests/optimize`
- `POST /api/backtests/cost-stress`
- `POST /api/backtests/walk-forward`
- `POST /api/backtests/portfolio-optimize`
- `POST /api/data/quality`
- `POST /api/research/promotion-gate`

### Event-driven US equity backtest

```bash
python scripts/run_backtest.py
```

This synthetic smoke run uses `quant_us` only: a momentum strategy emits
signals, portfolio construction creates target positions, the rebalance planner
creates order intents, pre-trade risk approves them, OMS submits them to the
simulated broker, and fills update the account ledger.

### US equity data lake MVP

Install dependencies into the active environment, then ingest auxiliary
yfinance data into local raw and cleaned Parquet partitions:

```bash
python scripts/ingest_daily.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data
```

Build versioned factor values from cleaned bars:

```bash
python scripts/build_features.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data \
  --version v1
```

For portfolio or ML research, build the same factor version across multiple
symbols:

```bash
python scripts/build_features.py \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --version v1 \
  --universe core_us
```

Build a liquidity/history-filtered universe from cleaned daily bars:

```bash
python scripts/build_universe.py \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --min-price 5 \
  --min-dollar-volume 20000000 \
  --min-history-bars 20
```

Run the event-driven backtest or walk-forward validation from the same data:

```bash
python scripts/run_backtest.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data

python scripts/run_backtest.py \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id trend_momentum \
  --strategy-params-json '{"lookback_bars":20,"entry_threshold":0.03}'

python scripts/run_backtest.py \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id factor_rank \
  --strategy-params-json '{"factor_name":"momentum_score","top_n":2,"min_symbols":3}' \
  --feature-version v1 \
  --feature-universe core_us

python scripts/run_walk_forward.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data \
  --train-bars 60 \
  --test-bars 20
```

The event-driven engine groups bars by timestamp for portfolio-level backtests:
all symbols in a slice update market state first, then strategies emit signals,
portfolio construction creates targets, OMS/risk handles orders, and the broker
records one portfolio snapshot per timestamp.

Factor and ML-derived features enter strategies through the same event-driven
context. Versioned factor values from `data/features` are loaded into
`StrategyContext.features` by date; `factor_rank` ranks the current universe,
emits only signals, and still relies on portfolio construction, risk, OMS, and
the broker simulator for all trading decisions.

The event-driven runner can apply point-in-time data filters before the strategy
sees bars:

- `CorporateActionAdjuster` backward-adjusts OHLCV for splits and cash dividends.
- `EarningsBlackoutFilter` removes bars around configured earnings event dates.
- Backtest diagnostics include input rows, processed rows, action count, event count, and removed blackout rows.

Build a leakage-aware ML dataset from cleaned bars and versioned factors:

```bash
python scripts/build_ml_dataset.py \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --version v1 \
  --universe core_us \
  --horizon-bars 5 \
  --train-end 2024-04-30 \
  --validation-end 2024-05-31
```

The dataset builder writes `dataset.parquet` plus `manifest.json` under
`data/ml_datasets`. Labels are forward returns computed within each symbol, and
train/validation/test splits are assigned by date to avoid random row-level
leakage.

Score a dataset with a model artifact and write predictions back as versioned
features:

```bash
python scripts/score_linear_model.py \
  --dataset-path data/ml_datasets/dataset=bar_factor_forward_return/version=v1/run_id=<dataset_run_id>/dataset.parquet \
  --model-id linear_rank_v1 \
  --feature-names momentum_score,realized_vol_20 \
  --weights-json '{"momentum_score":1.0,"realized_vol_20":-0.25}' \
  --score-name model_score \
  --score-version linear_rank_v1 \
  --feature-version v1 \
  --dataset-run-id <dataset_run_id> \
  --universe core_us \
  --data-root data
```

The scorer stores the linear model spec under `data/models`, registers a
`ModelArtifact` under `data/experiments/models`, and writes `model_score` into
the same feature store used by factor strategies. More advanced ML frameworks
can replace the scorer later as long as they write the same versioned score
contract.

Register a reproducible research experiment from a local data-lake backtest:

```bash
python scripts/run_research_experiment.py \
  --experiment-name momentum_core_us \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id trend_momentum \
  --strategy-params-json '{"lookback_bars":20,"entry_threshold":0.03}' \
  --backtest-params-json '{"default_strategy_weight":0.12,"cash_reserve_weight":0.08,"min_weight_change":0.002}' \
  --feature-version v1 \
  --tag baseline
```

Register a factor ranking experiment against a specific factor version:

```bash
python scripts/run_research_experiment.py \
  --experiment-name factor_rank_core_us \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id factor_rank \
  --strategy-params-json '{"factor_name":"momentum_score","top_n":2,"min_symbols":3}' \
  --feature-names momentum_score \
  --feature-version v1 \
  --feature-universe core_us
```

Run the same path against model scores:

```bash
python scripts/run_research_experiment.py \
  --experiment-name model_score_rank_core_us \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id factor_rank \
  --strategy-params-json '{"factor_name":"model_score","top_n":2,"min_symbols":3}' \
  --feature-names model_score \
  --feature-version linear_rank_v1 \
  --feature-universe core_us
```

This writes queryable backtest artifacts under `data/backtest_results` and an
experiment manifest/index under `data/experiments`. The manifest records data
range, symbols, strategy id, risk/backtest parameters, metrics, and artifact
paths. Compare registered runs by any persisted metric:

```bash
python scripts/compare_experiments.py \
  --data-root data \
  --experiment-name momentum_core_us \
  --metric sharpe_ratio
```

The web research promotion gate can now write the same registry contract. When
`register_experiment=true`, `/api/research/promotion-gate` stores a promotion
manifest under `reports/research_gates`, registers an experiment under
`data/experiments`, and records `strategy_version`, `data_version`,
`promotion_decision`, `promotion_stage`, gate counts, and promotion score. This
is the bridge from visual research to later paper candidates, model-score
experiments, and cross-run comparison.

Run a parameter sweep while preserving the same data, risk, OMS, and registry
path:

```bash
python scripts/run_parameter_sweep.py \
  --experiment-name momentum_grid_us \
  --symbols AAPL,MSFT,SPY \
  --start 2024-01-01T00:00:00Z \
  --end 2024-06-30T00:00:00Z \
  --data-root data \
  --strategy-id trend_momentum \
  --grid-json '{"lookback_bars":[10,20,40],"entry_threshold":[0.01,0.03]}' \
  --portfolio-grid-json '{"cash_reserve_weight":[0.05,0.10],"default_strategy_weight":[0.08,0.12]}' \
  --compare-metric sharpe_ratio
```

Each grid combination is a separate registered experiment run with its own
backtest artifacts, `strategy_params`, and `backtest_params`, so later ML
models and manual strategies can be compared through the same registry. The
portfolio layer supports per-symbol caps, aggregate cash reserve, optional
group exposure caps, and rebalance thresholds; pre-trade risk still enforces
cash, order notional, gross exposure, and long-only constraints before OMS
submits an order.

Run local paper mode with persistent JSONL order/fill/snapshot records:

```bash
python scripts/run_paper.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data \
  --ledger-dir data/ledger/paper
```

To also persist the paper run into PostgreSQL/TimescaleDB tables from
`config/schema.sql`, pass a DSN:

```bash
python scripts/run_paper.py \
  --symbol AAPL \
  --start 2024-01-01T00:00:00Z \
  --end 2024-03-01T00:00:00Z \
  --data-root data \
  --ledger-dir data/ledger/paper \
  --postgres-dsn postgresql://quant:quant@127.0.0.1:5432/quant
```

Reconcile local ledger-derived positions against the paper mirror or Alpaca:

```bash
python scripts/reconcile_account.py --ledger-dir data/ledger/paper --broker paper
```

Run live readiness checks before any live loop is allowed:

```bash
python scripts/run_live.py --broker paper --ledger-dir data/ledger/paper
```

The live runner blocks by default. It requires clean reconciliation and an
explicit `--allow-live-orders` flag before it reports ready.

The backend exposes the same US equity MVP through:

- `POST /api/us/data/sync`
- `POST /api/us/features/build`
- `POST /api/us/backtests/event`
- `POST /api/us/reconcile`
- `GET /metrics`

`POST /api/us/backtests/event` accepts optional `symbols`,
`corporate_actions`, and `earnings_events` arrays, so API-driven backtests use
the same portfolio and preprocessing path as local Python runs.

The frontend includes a **美股量化 MVP** control panel for those API calls:
data-lake sync, factor build, event backtest, and ledger reconciliation.

yfinance is included only as an auxiliary MVP source. Production data should
move to Alpaca/IBKR/Polygon/Nasdaq/DataBento and keep the same cleaned data
contracts.

### Docker Compose

```bash
docker compose up --build
```

The compose stack starts the API, TimescaleDB/PostgreSQL, Redis, Prometheus,
and Grafana. The SQL contract in `config/schema.sql` creates the initial
market-data, factor, order, fill, position, and portfolio snapshot tables.

## Verification

Backend tests:

```bash
py -3 -m unittest discover -s backend/tests -v
```

Frontend checks:

```bash
cd frontend
npm run lint
npm run smoke
npm run build
```

## Environment variables

- `QS_DEFAULT_DATA_SOURCE`: `fixture`, `auto`, or `sqlite`
- `QS_DATA_DB_PATH`: path to SQLite market data, default `data/market_data.sqlite`
- `QS_BINANCE_BASE_URL`: Binance Spot REST base URL, default `https://api.binance.com`
- `QS_BINANCE_REQUEST_SLEEP_SECONDS`: sleep between Binance pagination requests, default `0.15`
- `QS_HTTP_TIMEOUT_SECONDS`: outbound HTTP timeout, default `20`
- `QS_DATA_UPDATE_INTERVAL_SECONDS`: scheduler interval, default `86400`
- `QS_DATA_DEFAULT_BACKFILL_DAYS`: initial incremental-update lookback when a symbol has no rows, default `30`
- `QS_DEFAULT_SYMBOL`: default trading symbol
- `QS_DEFAULT_INTERVAL`: default bar interval
- `QS_TIMEZONE`: runtime timezone label
- `QS_WEB_API_KEY`: optional API key for `/api/*`
- `QS_REPORT_DIR`: output directory for reports or exports
- `QS_API_HOST`: backend bind host
- `QS_API_PORT`: backend bind port

## Notes

- The research system is self-contained and does not require vn.py.
- Live-trading support lives behind `backend/app/live` and only activates when vn.py dependencies are installed.
- If FastAPI or uvicorn is not installed locally, backend service code remains present but the API server cannot start until dependencies are installed.
