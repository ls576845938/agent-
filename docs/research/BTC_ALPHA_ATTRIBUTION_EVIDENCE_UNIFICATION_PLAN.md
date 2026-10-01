# BTC Alpha Attribution and Evidence Unification Plan

Run date: 2026-05-16

## Scope

This sprint is a research and evidence sprint. It does not expand system
infrastructure, does not add many strategies, and does not open paper or live.
The only BTC strategy candidate allowed for strategy-level refactor is
`btc_perp_dual_trend_v3`.

## AGENTS.md Rules In Force

- Strategy must not call broker directly.
- Strategy only emits `Signal`, `OrderIntent`, or `TargetPosition`.
- All orders must pass Risk Engine.
- All PnL must be derived from fills and ledger.
- Every backtest must generate a manifest.
- Every experiment records `data_version`, `strategy_version`, `params`,
  `cost_model`, `slippage_model`, and `commit_hash`.
- No future function and no look-ahead bias.
- Do not introduce live trading code before paper trading gate passes.

## Current Git State

Command:

```bash
git status --short
```

Result at Task 0 start: clean worktree.

Current branch:

```text
main
```

Current head:

```text
3e20644 Upload current project state
```

## Current Directory Structure

Relevant directories observed:

```text
backend/app/api/                 FastAPI app and request/response schemas
backend/app/domain/              strategy registry and domain models
backend/app/services/            research, backtest, data, paper-review services
configs/btc/alpha_hardening/     previous hardening candidate configs
docs/research/                   research plans and BTC hardening docs
docs/report/                     existing report runbooks
reports/research_gates/          existing research gate JSON reports
frontend/src/workspaces/crypto/  Crypto workspace panels
frontend/src/workspaces/research/Research dashboard panels
quant_us/backtest/               event-driven and crypto backtest engine
quant_us/research/               evidence, validation, automation, BTC helpers
quant_us/regime/                 regime detector/report modules
quant_us/live/                   paper/live safety shell modules
tests/                           core pytest suites
backend/tests/                   backend pytest suites
```

HTML sprint report target:

```text
docs/reports/quantstation_vnext_btc_alpha_attribution_report.html
```

`docs/reports/` does not currently exist and will be created in the HTML task.

## True Entrypoints

### BTC Data Loading

- `backend/app/services/market_data.py`
  - `load_from_sqlite`
  - `load_market_frame`
  - `inspect_market_data_quality`

### BTC SQLite Access

- SQLite path convention: `data/market_data.sqlite`
- Loader: `backend/app/services/market_data.py::load_from_sqlite`
- Market frame wrapper: `backend/app/services/market_data.py::load_market_frame`

### Multi-Timeframe Integrity

- `quant_us/backtest/crypto_event.py`
  - `CRYPTO_VALIDATION_INTERVALS`
  - `summarize_crypto_interval_validation`
- Service orchestration:
  - `backend/app/services/crypto_closure.py`

### BTC Strategy Definitions

- `backend/app/domain/strategy_registry.py`
  - `BtcPerpDualTrendStrategy`
  - `BtcOrderFlowPressureStrategy`
  - other BTC research strategies
- Sprint research helper from prior hardening:
  - `quant_us/research/btc_alpha_hardening.py`

### Event-Ledger Backtest

- Core function:
  - `quant_us/backtest/crypto_event.py::run_crypto_event_backtest`
- Service wrappers:
  - `backend/app/services/backtests.py::ResearchBacktestService.run_crypto_event`
  - related crypto event calls in `backend/app/services/backtests.py`

### Cost Model / Cost Stress

- Crypto stress scenarios:
  - `quant_us/backtest/crypto_event.py::CRYPTO_COST_STRESS_SCENARIOS`
- Service stress path:
  - `backend/app/services/backtests.py::run_event_driven_cost_stress`
- Existing hardening script stress path:
  - `scripts/run_btc_alpha_hardening.py`

### Walk-Forward

- Unified engine:
  - `quant_us/backtest/walk_forward.py`
- Service entry:
  - `backend/app/services/backtests.py::ResearchBacktestService.run_walk_forward`

### Regime Gate

- Service regime slices:
  - `backend/app/services/backtests.py::_market_regime_masks`
  - `backend/app/services/backtests.py::_build_regime_slices`
- Prior sprint BTC classifier:
  - `quant_us/research/btc_alpha_hardening.py::classify_btc_regimes`
- Generic regime modules:
  - `quant_us/regime/detector.py`
  - `quant_us/regime/report.py`

### PBO / DSR

- Existing validation implementation:
  - `quant_us/research/validation.py`
- Service CPCV validation:
  - `backend/app/services/backtests.py::run_cpcv_validation`
- Prior sprint simplified helpers:
  - `quant_us/research/btc_alpha_hardening.py::simplified_pbo`
  - `quant_us/research/btc_alpha_hardening.py::simplified_dsr`

### Promotion Gate

- Research automation:
  - `quant_us/research/automation/promotion_gate.py`
- Backend service:
  - `backend/app/services/research_gate.py`
- BTC closure orchestration:
  - `backend/app/services/crypto_closure.py`

### Evidence Registry

- `quant_us/research/evidence_registry.py`
- CLI/report helpers in `quant_us/cli.py`
- API overview reads saved registry in `backend/app/api/app_factory.py`

### Paper Review Queue

- `backend/app/services/paper_review.py`
- `quant_us/research/paper_review_candidate.py`
- `quant_us/research/paper_review_bridge.py`
- Existing tests:
  - `tests/api/test_paper_review_entry_state.py`
  - `tests/research/test_paper_review_candidate.py`
  - `tests/research/test_paper_review_queue_locked.py`

### Live Safety / No-Side-Effect Tests

- `tests/live/test_live_frozen_session_gate.py`
- `tests/live/test_live_runtime_safety.py`
- `tests/live/test_shadow_live_no_real_submit.py`
- `tests/live/test_safety_boundary_regressions.py`
- `tests/integrations/test_no_live_side_effects.py`
- `tests/research/test_no_live_side_effects.py`

### Crypto Workspace / Research Dashboard

- `frontend/src/workspaces/CryptoWorkspace.tsx`
- `frontend/src/workspaces/crypto/OptimizationPanel.tsx`
- `frontend/src/workspaces/crypto/ResultsPanel.tsx`
- `frontend/src/workspaces/ResearchDashboard.tsx`
- `frontend/src/workspaces/research/*`

## Canonical Artifact Target

Canonical outputs will be under:

```text
artifacts/btc_canonical/{run_id}/
  canonical_backtest_report.json
  canonical_metrics.json
  trade_ledger.parquet
  trade_ledger.csv
  trade_attribution.parquet
  trade_attribution.csv
  trade_attribution_summary.json
  run_manifest.json
  gate_inputs.json
  orderflow_ablation_report.json
  btc_perp_dual_trend_v3_results.json
  btc_perp_dual_trend_v3_gate_decision.json
  promotion_decision.json
```

Gate code must consume `canonical_backtest_report.json` and/or
`gate_inputs.json`. Other reports are diagnostic.

## Planned Files To Change

Task 1 and later may add or modify:

- `quant_us/research/btc_canonical.py`
- `scripts/run_btc_canonical_attribution.py`
- `configs/btc/alpha_attribution/btc_perp_dual_trend_v3.yaml`
- `docs/research/BTC_PROMOTION_GATE_CANONICAL_RULES.md`
- `docs/research/RUNTIME_BOUNDARY_AUDIT.md`
- `docs/reports/quantstation_vnext_btc_alpha_attribution_report.html`
- focused tests under `tests/research/`
- optional lightweight frontend display if needed, likely in
  `frontend/src/workspaces/crypto/OptimizationPanel.tsx`

Task 0 changes only this plan document.

## Files And Modules Not Allowed In This Sprint

- Do not change broker adapters to submit orders.
- Do not add new live broker integrations.
- Do not open or auto-start paper runtime.
- Do not relax gate thresholds.
- Do not make old non-canonical evidence eligible for promotion.
- Do not modify live readiness to produce `live_ready` or `live_enabled`.
- Do not create `paper_ready`.
- Do not rewrite unrelated modules.

Protected paths unless a later task has a specific audit-only reason:

```text
quant_us/live/
quant_us/execution/*broker*
backend/app/live/
backend/app/services/paper_review.py
```

## Baseline Reproduction Commands

Existing hardening evidence can be regenerated with:

```bash
PYTHONPATH=. python3 scripts/run_btc_alpha_hardening.py --run-id 20260516T000000Z
```

The canonical sprint runner to implement in Task 1/2 will use:

```bash
PYTHONPATH=. python3 scripts/run_btc_canonical_attribution.py --run-id 20260516T000000Z_attribution
```

The canonical runner must use event-ledger/fills/ledger PnL. Signal equity is
diagnostic-only.

## Canonical Report Schema

`canonical_backtest_report.json` must include at least:

- `run_id`
- `strategy_id`
- `strategy_version`
- `data_version`
- `data_range`
- `timeframe`
- `benchmark`
- `gross_pnl`
- `net_pnl`
- `fees`
- `slippage`
- `profit_factor`
- `event_profit_factor`
- `sharpe`
- `sortino`
- `max_drawdown`
- `annual_turnover`
- `trade_count`
- `win_rate`
- `avg_win`
- `avg_loss`
- `avg_holding_bars`
- `median_holding_bars`
- `exposure`
- `cost_stress_base`
- `cost_stress_harsh`
- `walk_forward_pass_rate`
- `regime_pass_rate`
- `pbo`
- `dsr`
- `no_lookahead_status`
- `event_ledger_status`
- `promotion_gate_status`
- `fail_reasons`
- `diagnostics.signal_equity`
- `artifact_hash`
- `code_commit`
- `config_hash`
- `cost_model_id`
- `ledger_engine_version`

## Attribution Output Schema

`trade_attribution.csv` and `trade_attribution.parquet` must include:

- `run_id`
- `strategy_id`
- `trade_id`
- `symbol`
- `side`
- `entry_time`
- `exit_time`
- `entry_price`
- `exit_price`
- `size`
- `gross_pnl`
- `net_pnl`
- `fees`
- `slippage`
- `holding_bars`
- `holding_hours`
- `entry_regime`
- `exit_regime`
- `dominant_regime_during_trade`
- `entry_signal_components`
- `exit_reason`
- `orderflow_value_at_entry`
- `trend_strength_at_entry`
- `volatility_state_at_entry`
- `compression_state_at_entry`
- `expansion_state_at_entry`
- `mfe`
- `mae`
- `realized_r`
- `cost_to_profit_ratio`
- `turnover_contribution`
- `attribution_source`

`attribution_source` must be `ledger_fills`. Attribution must not be inferred
from signal equity.

`trade_attribution_summary.json` must aggregate by:

- entry condition
- exit reason
- regime
- holding time bucket
- volatility bucket
- trend strength bucket
- orderflow bucket
- cost bucket
- top 20 profit trades
- top 20 loss trades
- top 3 profit condition combinations
- top 3 loss condition combinations

## btc_perp_dual_trend_v3 Boundary

Allowed:

- Add `btc_perp_dual_trend_v3` research config.
- Build v3 signal in research-only code or a tightly scoped strategy registry
  addition if tests require registry access.
- Use attribution to keep profitable entry/exit conditions.
- Use order-flow only as sizing, veto, or diagnostic.
- Add regime veto, entry confidence threshold, exit hysteresis, cooldown,
  min holding bars, time stop, cost-aware scoring, and turnover penalty.

Forbidden:

- No standalone order-flow entry trigger.
- No large strategy expansion.
- No lowered gate.
- No paper/live status promotion beyond allowed states.
- No signal-scale-only metric improvement.
- No look-ahead regime labels.

## Gate Thresholds

For this sprint:

- PF >= `1.15`
- event PF >= `1.15`
- annual turnover <= `10.0`
- walk-forward pass rate >= `0.80`
- regime pass rate >= `0.75`
- cost stress base positive/pass
- harsh cost stress must not collapse
- PBO <= `0.50`
- DSR >= `0.10`
- no-lookahead pass
- event-ledger pass with PnL from fills/ledger

Allowed states:

- `research_failed`
- `research_candidate`
- `candidate_gate_failed`
- `candidate_passed_internal_gate`
- `paper_review_pending`

Forbidden states:

- `paper_ready`
- `live_ready`
- `live_enabled`

## HTML Report Path

Final report:

```text
docs/reports/quantstation_vnext_btc_alpha_attribution_report.html
```

The file must be static, self-contained, and diagnostic. It must clearly show:

- `PAPER QUEUE: LOCKED` or `PAPER_REVIEW_PENDING`
- `LIVE: FROZEN`
- `candidate_passed_internal_gate` count
- canonical artifact paths
- baseline vs v2 vs v3 comparison
- attribution conclusions
- order-flow ablation result
- test commands and outcomes

## Task Execution Order

1. Task 0: repo scan and this plan document.
2. Task 1: canonical backtest report and canonical gate inputs.
3. Task 2: per-trade attribution engine.
4. Task 5: gate unification and runtime boundary audit.
5. Task 6: core tests and no-side-effect tests.
6. Task 3: `btc_perp_dual_trend_v3` attribution-driven refactor.
7. Task 4: order-flow sizing/veto ablation.
8. Task 7: HTML report generator.
9. Task 8: final aggregation, tests, commit, and clean worktree check.

Task 1 must finish before v3 strategy refactor starts because current risk is
evidence inconsistency.

## Risk Points

- Existing strict evidence and fresh event-ledger reruns can differ. Canonical
  artifacts must define the single promotion source of truth.
- Full event-ledger manifests can be large. Commit summary artifacts and
  reproducible commands; avoid committing huge per-run manifests unless needed.
- Order-flow has prior information value but also high turnover and sensitivity.
  It must be treated as sizing/veto/diagnostic only.
- V3 may fail PF even if turnover and regime stability improve. Failure must
  remain visible in reports and gate decisions.
- Paper/live code paths are extensive. Boundary audit must distinguish active,
  review-only, and inactive entrypoints.
- GCP/local HTML services are operational conveniences only; HTML report must be
  committed as a static file.

## Task 0 Acceptance

- Plan document exists.
- Strategy logic unchanged.
- Gate logic unchanged.
- Live/paper unchanged.
- Plan committed separately before implementation tasks start.
