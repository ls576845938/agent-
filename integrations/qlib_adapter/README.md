# Qlib Adapter

This adapter is a research-only bridge from QuantStation cleaned daily parquet data into optional Qlib workflows.

## Scope

- Daily bars only (`1d`)
- US equity cleaned parquet only
- No implicit data download
- No broker, OMS, paper, live, or risk-engine calls
- Missing `qlib` or `lightgbm` must not break package import

## Run Layout

Each run writes under `artifacts/qlib_runs/<run_id>/`.

Key artifacts:

- `qlib_input/dataset_manifest.json`
- `qlib_input/daily_bars.parquet`
- `qlib_input/csv/<SYMBOL>.csv`
- `qlib_provider/`
- `pred_score.parquet`
- `research_model_scores.parquet`
- `recorder_metrics.json`
- `imported_recorder_metrics.json`
- `qlib_backtest_summary.json`
- `qlib_strategy_manifest.json`

## Commands

Export cleaned daily bars into adapter-owned Qlib input:

```bash
python3 -m integrations.qlib_adapter.export_to_qlib \
  --data-version latest \
  --universe configs/universe/us_core_liquid.yaml \
  --start-date 2020-01-01 \
  --end-date 2025-12-31
```

Explicitly sync real daily data from yfinance, generate manifests, then export to Qlib input:

```bash
python3 -m integrations.qlib_adapter.prepare_real_daily_data \
  --universe configs/universe/us_core_liquid.yaml \
  --start-date 2020-01-01 \
  --end-date 2025-12-31 \
  --sync-yfinance \
  --dry-run
```

Export and optionally build a Qlib provider:

```bash
python3 -m integrations.qlib_adapter.build_qlib_dataset \
  --data-version latest \
  --universe configs/universe/us_core_liquid.yaml \
  --start-date 2020-01-01 \
  --end-date 2025-12-31 \
  --dry-run
```

Run the Qlib workflow wrapper:

```bash
python3 -m integrations.qlib_adapter.run_qlib_workflow \
  --config configs/qlib/us_lgbm_alpha158_daily.yaml \
  --dry-run
```

Import prediction scores and recorder metrics:

```bash
python -m integrations.qlib_adapter.import_pred_score --run-id <run_id>
python -m integrations.qlib_adapter.import_recorder_metrics --run-id <run_id>
```

Compile the candidate-only Qlib strategy manifest:

```bash
python -m integrations.qlib_adapter.compile_qlib_strategy_manifest \
  --run-id <run_id> \
  --config configs/qlib/us_lgbm_alpha158_daily.yaml
```

## Missing Dependency Behavior

- `import integrations.qlib_adapter` succeeds without `qlib` or `lightgbm`.
- `build_qlib_dataset --dry-run` validates export inputs without importing Qlib.
- `run_qlib_workflow --dry-run` validates run paths and config without importing Qlib.
- `build_qlib_dataset` without `qlib` fails with a clear dependency error.
- `run_qlib_workflow` without `qlib` or `lightgbm` fails with a clear dependency error.

## Data Validation

`prepare_real_daily_data` and `export_to_qlib` validate:

- required OHLCV columns
- positive finite OHLC
- `high >= max(open, close)`
- `low <= min(open, close)`
- `volume >= 0`
- unique `datetime + symbol`
- expected US trading calendar coverage
- zero missing daily rows for every requested symbol
- manifest binding for every requested symbol
- no silent yfinance sync unless `--sync-yfinance` is passed
- exact universe membership count when configured (`expected_symbol_count`)

The adapter writes a dataset manifest even on failure so the failed run remains inspectable.
