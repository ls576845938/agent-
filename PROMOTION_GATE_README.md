# Promotion Gate Reference

## Gate Overview

The promotion gate evaluates whether a strategy is ready to advance from research to paper trading candidate. It runs via the API endpoint `POST /api/research/promotion-gate`.

## Gates

### 1. data_quality
- **PASS:** `is_usable=True`, `coverage_pct >= 95%`, `quality_score >= 95`, `missing_bars == 0`
- **WARN:** `coverage_pct >= 85%` but < 95%, or `quality_score < 95`, or `missing_bars > 0`
- **FAIL:** `is_usable=False` or `coverage_pct < 85%`

### 2. backtest_survival
- **PASS:** `total_return_pct > 0`, `sharpe_ratio >= 0.5`, `profit_factor >= 1.2`, `max_drawdown_pct > -15%`, `trade_count >= 30`
- **FAIL:** `total_return_pct <= 0`, `sharpe_ratio < 0`, `max_drawdown_pct <= -25%`, `profit_factor < 0.5`, `trade_count < 10`

### 3. execution_cost
- **PASS:** `cost_drag_pct <= max(0.5%, |return| * 0.15)`, `annual_turnover_pct <= 1500%`
- **WARN:** `cost_drag_pct <= max(2%, |return| * 0.5)`, `annual_turnover_pct <= 5000%`
- **FAIL:** `cost_drag_pct > max(2%, |return| * 0.5)` OR `annual_turnover_pct > 5000%`

### 4. portfolio_risk
- **PASS:** `max_drawdown_pct > -12%`, `max_gross_exposure_pct <= 200%`
- **FAIL:** `max_drawdown_pct <= -20%` OR `max_gross_exposure_pct > 300%`

### 5. cost_stress (deep check)
- **PASS:** `survival_rate_pct == 100%`
- **WARN:** `survival_rate_pct >= 60%`
- **FAIL:** `survival_rate_pct < 60%`

### 6. walk_forward (deep check)
- **PASS:** `fold_pass_rate_pct == 100%`
- **WARN:** `fold_pass_rate_pct >= 60%` or `insufficient_data`
- **FAIL:** `fold_pass_rate_pct < 60%` AND NOT insufficient_data

### 7. portfolio_allocation (deep check, portfolio mode only)
- **PASS:** `max_pair_abs_correlation < 0.75`
- **FAIL:** `max_pair_abs_correlation >= 0.95`

## How to Force Re-run

The promotion gate always re-runs fresh — no caching. Each call generates a new backtest. Use the `--force-rerun` flag on CLI readiness to indicate intent:

```bash
python3 -m quant_us.cli live readiness --force-rerun
```

Or via API, simply POST again to `/api/research/promotion-gate`.

## Avoiding Stale Manifests

- Each manifest has `gate_version`, `config_version`, `generated_at` fields
- Compare `gate_version` against current codebase version
- If manifest's `gate_version` < current, re-evaluate
- If manifest's `config_version` differs from current config hash, re-evaluate

## PASS/WARN/FAIL Interpretation

| Decision | Meaning |
|----------|---------|
| **pass** | All gates pass. Strategy is a paper trading candidate. |
| **warn** | Some gates warn. Strategy needs iteration before paper production. |
| **fail** | One or more gates fail. Strategy is blocked from paper production. |
| **blocked** | Deep checks skipped. Must run full evaluation. |

## Turnover Control Parameters

These parameters affect the `execution_cost` gate:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `rebalance_buffer_pct` | 0.01 (1%) | Skip small weight adjustments below this % of max position |
| `min_holding_bars` | 5 | Minimum bars before direction reversal allowed (exit-to-flat always permitted) |
| `cost_aware_filter` | True | Block trades where estimated cost > expected return |
| `max_annual_turnover_pct` | 5000.0% | Hard cap on estimated annualized turnover |

Configure via API request parameters. If execution_cost still fails, increase `rebalance_buffer_pct` or `min_holding_bars` without lowering the 5000% gate threshold.
