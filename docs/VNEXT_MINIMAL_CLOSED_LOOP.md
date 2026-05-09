# QuantStation VNEXT Minimal Closed Loop

This page documents the smallest end-to-end loop that is actually present in the current codebase and the acceptance boundary for the current baseline:

1. Generate and validate a data manifest.
2. Run a ledger-backed, event-driven backtest.
3. Evaluate research promotion for human paper-review only.
4. Pass paper/runtime readiness gates.
5. Inspect daily and backtest reports from persisted evidence.

It does not describe automatic paper trading or live trading. Promotion is not execution, and this page should not be read as an automation promise.

## 1) Data Manifest

The data manifest lives at `quant_us/data/storage/data_manifest.py`.
The generator script is `scripts/generate_data_manifest.py`.

Generate one manifest:

```bash
python scripts/generate_data_manifest.py \
  --source yfinance \
  --symbol AAPL \
  --interval 1d \
  --start 2024-01-01 \
  --end 2024-03-31 \
  --validate
```

Useful options supported by the script:

- `--source`
- `--symbol`
- `--interval`
- `--start`
- `--end`
- `--db-path`
- `--all`
- `--list`
- `--manifest-root`
- `--validate`

The manifest records `data_version`, `source`, `symbol`, `interval`, `asset_class`, `timezone`,
`adjustment`, `start`, `end`, `row_count`, `expected_rows`, `coverage_pct`, `fingerprint`,
`checksum`, `quality_score`, `cleaning`, and `git_commit`.

Promotion-grade validation blocks:

- fixture data
- non-equity assets
- unsupported sources
- missing checksum
- low coverage or low quality
- non-UTC timestamps
- duplicate timestamps
- invalid or non-positive prices
- future timestamps

List stored manifests:

```bash
python -m quant_us.cli manifest list --kind all --limit 20
```

Inspect one manifest:

```bash
python -m quant_us.cli manifest inspect --manifest qs-yfinance-AAPL-1d-07ff0bf4c583
python -m quant_us.cli manifest inspect --manifest ubt_000bd9a6e7794fff
```

## 2) Event-Driven Backtest

The unified backtest runner is `quant_us/backtest/unified_runner.py`.
Its run output is ledger-backed and event-driven.

The persisted report command reads the backtest manifest rather than recomputing from scratch:

```bash
python -m quant_us.cli report backtest --run-id ubt_000bd9a6e7794fff
python -m quant_us.cli report backtest --manifest data/manifests/run_ubt_000bd9a6e7794fff.json
```

The report highlights:

- `data_version`
- data manifest binding status, manifest id, checksum, and fingerprint when present
- `strategy_version`
- `commit_hash`
- commission and slippage configuration
- manifest path

Corporate actions in the backtest ledger are handled with a split/reverse-split quantity and cost-basis adjustment only.
The bar data on and after the ex-date is assumed to already be on the post-split price scale, so the system does not
re-price bars a second time.

The full pipeline script can generate ingest + backtest output in one pass:

```bash
python scripts/run_full_pipeline.py \
  --symbol AAPL \
  --source yfinance \
  --interval 1d \
  --start 2024-01-01 \
  --end 2024-03-31 \
  --mode backtest
```

## 3) Research Promotion Gate

The research promotion gate is `quant_us/research/automation/promotion_gate.py`.
The CLI entry point is:

```bash
python -m quant_us.cli research promotion-gate --candidate-id cand_123
```

The gate reads persisted candidate and experiment evidence, then returns one of:

- `BLOCKED`
- `WATCHLIST`
- `NEED_MORE_RESEARCH`
- `READY_FOR_PAPER_REVIEW`

This is a human-review boundary only. It does not start paper trading and does not start live trading.

The gate expects evidence such as:

- candidate file
- experiment manifest
- scorecard
- overfit check
- walk-forward evidence
- cost stress evidence
- ledger consistency and event-driven backtest metadata

The gate also validates data scope:

- explicit US equity symbols
- allowed source: `yfinance`, `alpaca`, or `sqlite`
- equity only
- manifest validation through `validate_manifest_for_promotion()`

`scripts/run_full_pipeline.py --mode gate` stops at this stage and prints the promotion decision.

## 4) Paper Runtime Gate and Readiness

The paper runtime code is in `quant_us/live/paper_runtime.py`.
The unified live runtime boundary is in `quant_us/live/runtime.py`.

Important rules enforced in code:

- paper runtime rejects `allow_live_orders=True`
- Alpaca paper access requires `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`
- if `APCA_API_BASE_URL` is set, it must be a paper URL
- paper runtime accepts either an approved promotion manifest or an approved paper review as entry evidence
- `paper_broker=alpaca` currently fails closed until a real Alpaca paper broker adapter is wired
- the fake Alpaca adapter is local-only and exists for contract tests; it does not connect to the network
- the implemented runtime broker backend is explicit in audit records as `broker_backend=simulated`
- live mode stays default-blocked unless `allow_live_orders`, `confirm_live`, `live_submission_enabled`, and readiness all pass

Readiness inspection commands:

```bash
python -m quant_us.cli readiness --profile simulated
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json --check-credentials
python -m quant_us.cli readiness --small-live --validation-state data/reports/paper_production/validation_state.json
```

The readiness output is read-only. It does not submit paper or live orders.

## 5) Paper Adapter Contract

The paper adapter contract is fail-closed by default.

- There is no real Alpaca paper adapter in the current runtime path.
- The local fake adapter is only for contract tests and offline validation.
- `paper_broker=alpaca` requires the approved adapter hook plus the required paper credentials and review evidence; otherwise the runtime remains blocked.

## 6) Paper Review Boundary

Promotion gate success does not equal paper trading.
If paper review is required, the research CLI provides manual-only paper review commands:

```bash
python -m quant_us.cli research paper-review-create --portfolio-sim-id <portfolio_sim_id>
python -m quant_us.cli research paper-review-approve --paper-review-id <paper_review_id> --manual --reviewer <name>
```

Approval is manual and does not start trading. The paper runtime gate only consumes approved evidence.

## 7) Daily Report

Daily paper reports are persisted under the paper ledger root.

```bash
python -m quant_us.cli report daily --latest
python -m quant_us.cli report daily --date 2026-05-08
```

The report includes the report path, ledger root, ending equity, daily PnL, order counts, reconciliation status,
and validation-state evidence pointers.

## 8) Minimal Boundary Summary

- Strategy emits signals or intents; it does not call a broker directly.
- Every order must pass risk.
- PnL comes from fills and ledger.
- Every backtest should have a manifest.
- Reconciliation detail is the next doc/report bridge to land in promotion and daily/backtest reports; until then, report pages remain evidence views, not execution flow.
- Promotion stops at `READY_FOR_PAPER_REVIEW`; paper/live are separate manual gates.
- Paper startup sync artifacts are audit inputs only and stay fail-closed; they do not mean real trading has been enabled.
- Live stays disabled by default.

## 9) Baseline Acceptance Boundary

For the 2026-05-09 baseline, the document scope is limited to:

- data manifest correctness
- unified backtest evidence
- canonical research-gate evidence
- paper-runtime fail-closed behavior
- surface alignment across docs and CLI help

It does not assert that real Alpaca paper execution is wired, and it does not claim automatic paper or live order submission.
