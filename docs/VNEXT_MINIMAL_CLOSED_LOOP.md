# QuantStation VNEXT Minimal Closed Loop

This page documents the smallest end-to-end loop that is actually present in the current codebase and the acceptance boundary for the current baseline:

1. Generate and validate a data manifest.
2. Run a ledger-backed, event-driven backtest.
3. Produce a canonical promotion handoff from persisted evidence.
4. Generate a paper/runtime readiness report.
5. Inspect daily and backtest reports from persisted evidence.

Canonical path for this baseline:

`manifest -> ledger-backed backtest -> promotion handoff -> paper/runtime readiness report`

It does not describe automatic paper trading or live trading. Promotion is not execution, and this page should not be read as an automation promise.
The readiness/report/paper runtime gate in this baseline consumes the saved Evidence Registry by default. It does not implicitly rebuild the registry. Missing, `STALE`, or `CONFLICT` registry state is fail-closed.

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
Data Manifest v2 additionally records `universe_id`, `universe_source`, `survivorship_bias_risk`,
`adjustment_policy`, and `corporate_action_adjustment`.

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
- ledger reconciliation binding: `ledger_artifact_hash`, `ledger_hash`, `fills_hash`, `orders_hash`, `portfolio_snapshots_hash`
- evidence timestamps: `generated_at` and `as_of_utc`
- artifact consistency and completeness states, with absent fields shown as `(missing)`
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
The paper/runtime gate reads the saved Evidence Registry as source of truth. It does not implicitly rebuild the registry during readiness or report evaluation.

Important rules enforced in code:

- paper runtime rejects `allow_live_orders=True`
- Alpaca paper access requires `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`
- if `APCA_API_BASE_URL` is set, it must be a paper URL
- paper/runtime readiness consumes evidence and renders a report only; it does not submit paper or live orders
- readiness/report/paper runtime gate only consumes the saved Evidence Registry; it does not rebuild from `review.json` or any other legacy input
- if registry state is `MISSING`, `STALE`, or `CONFLICT`, the gate fails closed
- saved registry rebuild is an explicit atomic maintenance action protected by a lock
- `paper_broker=alpaca` is fail-closed by default in the current runtime path
- paper orders are not submitted by default; enabling paper submission requires an explicit paper path separate from readiness/report commands
- the real Alpaca paper adapter is not in the automatic submit path in this baseline
- the fake Alpaca adapter is local-only and exists for contract tests; it does not connect to the network
- the implemented runtime broker backend is explicit in audit records as `broker_backend=simulated` unless a future adapter is separately wired and approved
- `LiveRuntime` is a safety shell; live mode remains review-only and does not execute orders even if live-gate evidence passes
- `live start` is review-only and fail-closed; it may inspect or print readiness/evidence state, but it is not an order submission path

Readiness inspection commands:

```bash
python -m quant_us.cli readiness --profile simulated
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json --check-credentials
python -m quant_us.cli readiness --profile shadow_live --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile live --validation-state data/reports/paper_production/validation_state.json --check-credentials
python -m quant_us.cli report evidence-registry --data-root data
```

The readiness and evidence-registry outputs are read-only. They render evidence as `PASS`, `STALE`, `MISSING`, or `CONFLICT`, print `report only, no execution`, and do not submit paper or live orders.
Passing live readiness evidence is still only review evidence in the current baseline. It does not unlock `LiveRuntime` order submission.

## 5) Paper Adapter Contract

The paper adapter contract is fail-closed by default.

- There is no real Alpaca paper adapter in the current automatic submit path for this baseline.
- The local fake adapter is only for contract tests and offline validation.
- `paper_broker=alpaca` remains blocked unless a separate adapter implementation, credentials, and approved evidence are all present and explicitly wired in a later change.
- Paper-review approval and paper readiness do not submit orders; an explicit paper execution path is required before any broker write can occur.
- `paper_review_index` is a legacy view for compatibility. It is not the source of truth for readiness or paper runtime gating.
- `review.json` alone is not enough to start paper runtime. The registry must be rebuilt explicitly before the gate can consume it.

## 6) Paper Review Boundary

Promotion gate success does not equal paper trading.
If paper review is required, the research CLI provides manual-only paper review commands:

```bash
python -m quant_us.cli research paper-review-create --portfolio-sim-id <portfolio_sim_id>
python -m quant_us.cli research paper-review-approve --paper-review-id <paper_review_id> --manual --reviewer <name>
```

Approval is manual and does not start trading. The paper runtime gate only consumes approved evidence.
The persisted paper review record now includes an approval object with reviewer, reason, timestamp,
candidate provenance, and a promotion-gate snapshot so the approval can be audited after the fact.
This handoff is evidence only; it is not a paper order submission path.

## 7) Daily Report

Daily paper reports are persisted under the paper ledger root.

```bash
python -m quant_us.cli report daily --latest
python -m quant_us.cli report daily --date 2026-05-08
python -m quant_us.cli report evidence-registry --data-root data
```

The report includes the report path, ledger root, ending equity, daily PnL, order counts, reconciliation status,
validation-state evidence pointers, evidence-registry status, paper session manifest, startup sync artifact,
ledger reconciliation artifact hash/fill hash/duplicate and conflict fill counts/ledger PnL, and `report only, no execution`.
If present, the CLI also prints the paper session manifest `history_artifact_path` for the immutable
`paper_ledger/audit/paper_session_manifests/<session_id>.json` copy.
This report is review-only and does not submit paper or live orders.
Paper session manifests and startup sync files are persisted audit evidence only; they do not enable broker writes.
Ledger-derived report artifacts must remain idempotent. Runtime/report writers should use a file lock for ledger writes
or explicitly document when a path is single-writer/rebuild-only; read-only report commands must not imply a write lock
that has not been implemented.

## 8) Minimal Boundary Summary

- Strategy emits signals or intents; it does not call a broker directly.
- Every order must pass risk.
- PnL comes from fills and ledger.
- Every backtest should have a manifest.
- Ledger reconciliation artifacts are persisted evidence views, not execution flow.
- Ledger-backed backtest manifests bind ledger, fills, orders, snapshot hashes, `generated_at`, and `as_of_utc`; missing bindings must be surfaced as missing evidence.
- Promotion stops at `READY_FOR_PAPER_REVIEW`; paper/live are separate manual gates.
- Paper startup sync artifacts are audit inputs only and stay fail-closed; they do not mean real trading has been enabled.
- Evidence Registry subject indexes are lookup aids over saved evidence and do not replace gate decisions.
- Saved Evidence Registry state is the gate input. `paper_review_index` remains a legacy view, and `review.json` alone does not authorize paper runtime startup.
- Live runtime stays disabled for execution; current live mode is review-only even when live-gate evidence passes.
- Paper order submission is default-off and requires an explicit paper submit path.

## 9) Baseline Acceptance Boundary

For the 2026-05-09 baseline, the document scope is limited to:

- data manifest correctness
- unified backtest evidence
- canonical research-gate evidence
- paper-runtime fail-closed behavior
- surface alignment across docs and CLI help

It does not assert that real Alpaca paper execution is wired, and it does not claim automatic paper or live order submission.
