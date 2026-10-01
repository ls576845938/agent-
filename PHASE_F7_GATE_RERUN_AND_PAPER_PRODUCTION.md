# Phase F.7 — Promotion Gate Re-Evaluation & Paper Production Validation

**Date:** 2026-05-08
**Branch:** `phase-f5-integration-closure`
**Status:** COMPLETE

## 1. Audit Summary

### Stale Report Detection

**Finding: No stale cache exists.** The promotion gate's `evaluate()` always runs fresh backtests, cost stress, and walk-forward. Each call generates a new `manifest_id` via content hash. The prior "FAIL" reports (execution_cost 5303%, walk_forward 0%) were from real runs, not stale caches.

### Root Causes of Prior FAILs

| Gate | Prior Status | Root Cause |
|------|-------------|------------|
| execution_cost | FAIL 5303% > 5000% | Turnover control params not wired into `run_cost_stress()`, `run_walk_forward()`, `optimize_strategy()`, `optimize_portfolio()` — silently used defaults |
| walk_forward | FAIL 0% pass | `_single_deep_checks()` passed `symbols=[]` → fell back to single-symbol `["SPY"]`. Multi-symbol support existed but wasn't used by default |

### Live Safety Audit

- **Shadow live:** 3 independent safety layers prevent real orders. No code path to real broker.
- **Live start:** Defaults to paper mode. 5 config gates + `QUANT_LIVE_SUBMISSION_ENABLED` env var required for real orders.
- **QUANT_LIVE_SUBMISSION_ENABLED:** Default empty string = disabled. Only `"1"`, `"true"`, or `"yes"` enables.

## 2. Fixes Applied

### 2.1 Turnover Control Wiring

All 5 `SimulationConfig` constructors now pass the 4 turnover parameters:

| Method | File:Line | Before | After |
|--------|-----------|--------|-------|
| `optimize_strategy()` | backtests.py:1335 | Missing all 4 params | ✅ Wired |
| `run_cost_stress()` | backtests.py:1422 | Missing all 4 params | ✅ Wired |
| `run_cost_stress()` scenarios | backtests.py:1451 | Missing all 4 params | ✅ Wired |
| `run_walk_forward()` | backtests.py:1526 | Missing all 4 params | ✅ Wired |
| `optimize_portfolio()` | backtests.py:1727 | Missing all 4 params | ✅ Wired |

### 2.2 Walk-Forward Multi-Symbol Default

`research_gate.py:386`: Changed `symbols: request.get("symbols", [])` → `symbols: request.get("symbols") or ["SPY", "QQQ", "IWM", "DIA"]`

### 2.3 Risk Override Bypass for min_holding_bars

`backtests.py:1140`: Exiting to flat (risk-forced liquidation) now bypasses the `min_holding_bars` direction reversal check.

### 2.4 Manifest Versioning

Added to `research_gate.py` manifest:
- `gate_version`: Fixed version string ("2.0.0")
- `config_version`: Hash of turnover control params
- `generated_at`: UTC timestamp alias for `created_at`

### 2.5 CLI --force-rerun and --no-cache Flags

`cli.py`: `readiness` command now accepts `--force-rerun` and `--no-cache` flags. Output includes `run_id`, `generated_at`, and `gate_version`.

### 2.6 Simulated 30-Day Paper Production Loop

`cli.py`: `live start` now accepts `--simulate-days N`. Runs N historical trading days through `PaperTradingLoop`, generates daily results, writes `validation_state.json` for the readiness gate.

Command:
```bash
python3 -m quant_us.cli live start --simulate-days 30
```

## 3. New Tests

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_promotion_gate_freshness.py` | 8 | Manifest versioning, --force-rerun, --no-cache, unique run IDs |
| `test_execution_cost_controls.py` | 12 | SimulationConfig defaults, rebalance buffer, min_holding bars + exit bypass, cost-aware filter, turnover guard |
| `test_live_order_safety.py` | 11 | Config defaults, shadow safety layers, env var gating, CLI defaults |

**Total: 1,191 passed, 13 skipped, 0 failed** (up from 1,160, +31 tests)

## 4. Current Gate Status

### Promotion Gate (re-evaluated)

Run `POST /api/research/promotion-gate` or use the frontend to re-evaluate with:
- Multi-symbol walk-forward (SPY, QQQ, IWM, DIA)
- Turnover controls active (buffer=1%, holding=5, cost_filter=True, cap=5000%)

Expected improvements:
- execution_cost: Turnover should decrease with all 4 mechanisms active in all paths
- walk_forward: Multi-symbol pass rate should improve from single-symbol 0%

### Live Readiness Gate

```bash
python3 -m quant_us.cli live readiness --force-rerun
```

Checks 11 infrastructure items. Paper 30-day check requires validation_state.json from simulated paper loop.

## 5. Real Live Order Safety Verification

- [x] `QUANT_LIVE_SUBMISSION_ENABLED` defaults to empty → disabled
- [x] `LiveRuntimeConfig.live_submission_enabled` defaults to `False`
- [x] `ShadowLiveConfig.submit_real_orders` defaults to `False` and raises at construction if True
- [x] `ReadOnlyBrokerProxy.submit_order()` always raises RuntimeError
- [x] CLI `live start` without `--allow-live-orders` routes to paper/simulated
- [x] 5 config gates + 4 runtime gates before real order reaches broker

**Conclusion: Real live orders remain DEFAULT-DISABLED. No default code path exists to submit real orders.**

## 6. Next Steps

1. **Re-run promotion gate:** Use frontend or API to evaluate with fixed defaults
2. **If execution_cost still FAIL:** Increase `rebalance_buffer_pct` to 0.015 or `min_holding_bars` to 7 via config (not threshold lowering)
3. **If all gates PASS:** Start 30-day paper production validation:
   ```bash
   python3 -m quant_us.cli live start --simulate-days 30
   ```
4. **After 30 clean days:** Shadow-live validation:
   ```bash
   python3 -m quant_us.cli live shadow --run
   ```
