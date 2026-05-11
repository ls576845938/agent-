# PyPortfolioOpt Adapter

This adapter is daily-only and research-only.

- Input scores: `artifacts/qlib_runs/<score_run_id>/research_model_scores.parquet`
- Input prices: cleaned daily bars under `data/cleaned/`
- Output weights: `artifacts/portfolio_runs/<portfolio_run_id>/target_weights.parquet`
- Output target positions: `artifacts/portfolio_runs/<portfolio_run_id>/target_positions.parquet`

## Boundaries

- No `OrderIntent` creation
- No risk/OMS/broker/live calls
- No implicit data download
- Long-only only
- No negative weights
- `sum(weights) <= 1 - cash_buffer`

## Commands

```bash
venv/bin/python -m integrations.pypfopt_adapter.build_expected_returns \
  --score-run-id <score_run_id> \
  --config configs/portfolio/pypfopt_long_only_max_sharpe.yaml
```

```bash
venv/bin/python -m integrations.pypfopt_adapter.build_covariance \
  --score-run-id <score_run_id> \
  --config configs/portfolio/pypfopt_long_only_max_sharpe.yaml
```

```bash
venv/bin/python -m integrations.pypfopt_adapter.optimize_weights \
  --score-run-id <score_run_id> \
  --config configs/portfolio/pypfopt_long_only_max_sharpe.yaml
```

```bash
venv/bin/python -m integrations.pypfopt_adapter.optimize_weights \
  --score-run-id <score_run_id> \
  --config configs/portfolio/pypfopt_long_only_max_sharpe.yaml \
  --fallback-optimizer equal_weight_topk
```

```bash
venv/bin/python -m integrations.pypfopt_adapter.import_target_weights \
  --portfolio-run-id <portfolio_run_id>
```

## Dependency Behavior

- `optimizer=max_sharpe|min_volatility|hrp` requires `pypfopt`
- If `pypfopt` is missing and no explicit fallback is provided, the command fails with a clear install message
- If `--fallback-optimizer equal_weight_topk` is supplied, the adapter emits equal-weight top-k target weights and records the fallback in the artifact

## Output Notes

- `build_expected_returns.py` converts score ranks into a bounded annualized expected-return proxy
- `build_covariance.py` uses cleaned daily returns strictly before each rebalance timestamp
- `import_target_weights.py` writes TargetPosition-compatible artifacts only
