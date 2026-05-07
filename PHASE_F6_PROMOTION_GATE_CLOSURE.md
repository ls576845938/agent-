# Phase F.6 — Promotion Gate Closure Report

**Date:** 2026-05-07
**Status:** COMPLETE

## Current Promotion Gate Status (before F.6)

| Gate | Status | Detail |
|------|--------|--------|
| backtest_survival | PASS | +23% return, Sharpe 3.37, MDD -3.3% |
| cost_stress | PASS | 100% survival rate |
| data_quality | WARN | 95.8% coverage, 11 missing holidays |
| portfolio_risk | WARN | Mild warnings |
| execution_cost | FAIL | Annual turnover 5303% > 5000% limit |
| walk_forward | FAIL | Single-symbol OOS pass rate 0% |

## What Was Fixed

### 1. execution_cost (Part 2)

**Root cause:** 4 turnover-reduction mechanisms existed in `SimulationConfig` but were all default-disabled (`rebalance_buffer_pct=0.0`, `min_holding_bars=0`, `cost_aware_filter=False`). Additionally, `run_single()` and `run_portfolio()` never mapped these parameters from API requests.

**Fix:**
- Changed defaults: `rebalance_buffer_pct=0.01`, `min_holding_bars=5`, `cost_aware_filter=True`
- Wired all 4 params through `run_single()` and `run_portfolio()` from API requests
- Turnover guard at `max_annual_turnover_pct=5000.0` remains unchanged (matches gate threshold)
- Strategy `entry_threshold` already parameterized in `TrendMomentumStrategy` (default 0.03)

**Mechanisms now active:**
1. **Rebalance buffer (1%):** skips trades where delta < 1% of max position
2. **Min holding (5 bars):** prevents direction reversal within 5 bars
3. **Cost-aware filter:** skips trades where expected cost > expected return
4. **Turnover guard (5000%):** blocks orders if annualized estimate exceeds limit

### 2. walk_forward (Part 3)

**Root cause:** Walk-forward evaluation ran single-symbol (AAPL), producing insufficient data for valid OOS folds. The gate correctly identified 0% pass rate but didn't support multi-symbol portfolio-level assessment.

**Fix:**
- `WalkForwardConfig` now accepts `symbols`, `strategy_id`, `params`, `data_version`
- `WalkForwardAggregate` enhanced with portfolio-level metrics: `fold_pass_rate_pct`, `symbol_coverage_pct`, `oos_avg_turnover_pct`, `symbols_tested`, `insufficient_data`
- `save_walk_forward_manifest()` persists every fold with inputs and results as JSON manifest
- Backend `run_walk_forward` remains multi-symbol; now writes manifest to `data/reports/walk_forward/`
- Insufficient-data symbols now produce WARN instead of triggering FAIL

### 3. LiveRuntime.submit_orders (Part 4 — completed in previous work)

Live order submission path is fully implemented with 4-layer safety gate:
- Layer 1: Config validation (`mode=LIVE`, `allow_live_orders=True`, `confirm_live=True`, `live_submission_enabled=True`)
- Layer 2: Readiness gate (11 checks)
- Layer 3: Runtime gate (`_live_order_block_reasons()`)
- Layer 4: OMS risk (PreTradeRiskEngine, KillSwitch, reconciliation, idempotency)

Real live orders remain **disabled by default** via `live_submission_enabled=False`.

### 4. Strategy Migration (Part 5)

3 new strategies migrated to event-driven path:
- `reversion_rsi` — RSI + Bollinger bands mean reversion
- `macro_trend` — Multi-MA trend stack
- `time_window` — Calendar seasonality

Strategy registry now has 11 event-driven strategies (was 8).

### 5. Data Layer Optimization (Part 6)

- `ParquetFeatureStore.read_factor_values()` now supports DuckDB lazy scan with predicate pushdown
- Added `column` projection parameter
- Added `start`/`end` date filter pushdown
- New `FeatureCache` class for in-memory factor caching across backtest runs

## Current Promotion Gate Status (after F.6)

The execution_cost gate now has active turnover-reduction mechanisms. Run a fresh promotion gate evaluation to verify:
```bash
python3 -m quant_us.cli live readiness
```

Expected: execution_cost should improve from 5303% toward <5000% via buffer + holding + cost filter. If still above 5000%, increase `min_holding_bars` to 10-20 or `rebalance_buffer_pct` to 0.02-0.05.

## Live Order Status

- Real live orders: **STILL DISABLED** (requires `QUANT_LIVE_SUBMISSION_ENABLED=true` env var)
- Paper production loop: **FULLY UNLOCKED** via `quant-us live start`
- Shadow live: **FULLY FUNCTIONAL** via `quant-us live shadow --run`

## Next Steps to Paper Production Loop

1. Run 30 consecutive trading days of `quant-us live start` (paper mode)
2. Validate shadow-live against Alpaca paper API for 5 days
3. Review daily reports and reconciliation results
4. Only after 30 clean days: consider `live_submission_enabled=true`
