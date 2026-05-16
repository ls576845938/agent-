# BTC Alpha Hardening Sprint Plan

Run date: 2026-05-16

## Repository Scan

- Project rules: `AGENTS.md`.
- BTC strategy implementations: `backend/app/domain/strategy_registry.py`.
  - `btc_perp_dual_trend`
  - `btc_orderflow_pressure`
- BTC data loading: `backend/app/services/market_data.py`.
  - `load_from_sqlite`
  - `load_market_frame`
  - `inspect_market_data_quality`
- SQLite data file: `data/market_data.sqlite`.
  - BTCUSDT intervals observed: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.
- Multi-timeframe integrity: `quant_us/backtest/crypto_event.py`.
  - `CRYPTO_VALIDATION_INTERVALS`
  - `summarize_crypto_interval_validation`
  - service orchestration in `backend/app/services/crypto_closure.py`
- Event-ledger backtest: `quant_us/backtest/crypto_event.py`.
  - `run_crypto_event_backtest`
  - PnL source must remain `ledger_fills`.
- Backtest service entry: `backend/app/services/backtests.py`.
  - `ResearchBacktestService.run_crypto_event`
- Cost stress: `backend/app/services/backtests.py`.
  - `run_event_driven_cost_stress`
  - crypto stress scenarios also defined in `quant_us/backtest/crypto_event.py`.
- Walk-forward: `backend/app/services/backtests.py` and `quant_us/backtest/walk_forward.py`.
- Regime reporting: existing crypto split in `quant_us/backtest/crypto_event.py`; Sprint-specific past-only classifier is in `quant_us/research/btc_alpha_hardening.py`.
- Promotion gate: `quant_us/research/automation/promotion_gate.py`.
- PBO / DSR: `quant_us/research/validation.py`; Sprint simplifications are in `quant_us/research/btc_alpha_hardening.py`.
- Paper review queue / research-only boundary tests: `tests/api/test_paper_review_entry_state.py`, `tests/research/test_paper_review_candidate.py`, `tests/live/*`.
- BTC workspace frontend: `frontend/src/workspaces/CryptoWorkspace.tsx` and `frontend/src/workspaces/crypto/OptimizationPanel.tsx`.
- Tests: `tests/` and `backend/tests/`.

## Files Changed In This Sprint

- `quant_us/research/btc_alpha_hardening.py`
- `scripts/run_btc_alpha_hardening.py`
- `configs/btc/alpha_hardening/*.yaml`
- `docs/research/BTC_ALPHA_HARDENING_PLAN.md`
- `docs/research/BTC_REGIME_FILTER_DESIGN.md`
- `docs/research/BTC_ORDERFLOW_CONFIRMATION_DESIGN.md`
- `docs/research/BTC_PROMOTION_GATE_RULES.md`
- focused tests under `tests/research/`
- BTC research display in `frontend/src/workspaces/crypto/OptimizationPanel.tsx`
- reproducible artifacts under `artifacts/btc_alpha_hardening/{run_id}/`

## Modules Not To Change

- Live broker adapters and live runtime code.
- Paper runtime auto-start paths.
- Risk engine bypasses.
- Ledger accounting semantics.
- Existing BTC baseline strategy logic before baseline evidence is recorded.
- Existing tests unrelated to BTC hardening.
- Gate thresholds.

## Baseline Reproduction

The strict historical evidence used for baseline reproduction is:

- `data/research/btc_closure_runs/btc_closure_btcusdt_1h_9e2ec8206064_strict_evidence.json`
- `data/research/btc_closure_runs/btc_closure_btcusdt_1h_e9b3502a9b57_strict_evidence.json`

Baseline and candidate artifacts are generated with:

```bash
PYTHONPATH=. python3 scripts/run_btc_alpha_hardening.py --run-id 20260516T000000Z
```

Direct event-ledger spot checks can be run by calling `run_crypto_event_backtest` with `source=sqlite`, `symbol=BTCUSDT`, `interval=1h`, `start=2024-01-01`, `end=2026-05-12`, `commission_rate=0.0004`, `slippage_bps=4.0`, and `target_weight=0.90`.

## Experiment Artifacts

Artifacts are written to:

```text
artifacts/btc_alpha_hardening/{run_id}/
  baseline_report.json
  candidate_results.json
  regime_report.json
  walk_forward_report.json
  cost_stress_report.json
  pbo_dsr_report.json
  promotion_decision.json
  btc_perp_dual_trend_v2_results.json
  btc_orderflow_confirmed_trend_v1_results.json
  strategy_manifest_candidates/
    btc_perp_dual_trend_v2.yaml
    btc_orderflow_confirmed_trend_v1.yaml
```

Event-ledger manifests are generated under `artifacts/btc_alpha_hardening/{run_id}/manifests/`.

## Gate Thresholds

- Profit Factor >= `1.15`
- event-ledger Profit Factor >= `1.15`
- walk-forward pass rate >= `0.80`
- regime pass rate >= `0.75`
- annual turnover <= `15.0`
- max drawdown must not cross `-15.0%`
- base cost stress must pass
- harsh cost stress must not collapse
- no-lookahead checks must pass
- event-ledger diagnostics must pass
- DSR >= `0.10`
- PBO <= `0.50`

These thresholds are hard gates and must not be relaxed to promote a candidate.

## Risk Points

- Strict evidence and a fresh direct event-ledger rerun do not match exactly because the strict evidence comes from prior closure artifacts and the direct rerun uses current code/data loaders.
- `btc_orderflow_pressure` has useful information but excessive turnover when used as a direct trigger.
- Regime labels must be based only on current and historical bars.
- Signal scaling can reduce notional turnover but must not be the only reason a strategy looks better.
- Paper review queue is allowed only after internal gate pass; paper auto-start remains disabled.
- Live remains frozen.

## Execution Plan

1. Preserve baseline evidence before editing strategy behavior.
2. Add Sprint-only research helpers for regime classification, confirmation-only order-flow, min-hold/cooldown, objective scoring, simplified PBO/DSR, and gate decisions.
3. Generate `btc_perp_dual_trend_v2` and `btc_orderflow_confirmed_trend_v1` artifacts through event-ledger backtests.
4. Run cost stress, rolling walk-forward, regime attribution, simplified PBO/DSR, and promotion gate checks.
5. Keep failed candidates visible with explicit fail reasons.
6. Render hardening diagnostics in the BTC workspace.
7. Run focused tests and commit only Sprint-related files.
