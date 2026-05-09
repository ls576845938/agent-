# CLI Report Commands

These commands are read-only report and evidence inspection helpers. They do not submit broker orders and do not approve paper trading.
Operator-facing evidence states are normalized to `PASS`, `STALE`, `MISSING`, and `CONFLICT`; report surfaces also print `report only, no execution`.
Passing evidence is not execution authorization. In the current baseline, `LiveRuntime` is a safety shell, `live start`
is review-only/fail-closed, and live mode does not submit orders even if live-gate evidence passes.

Canonical closed-loop path for the current baseline:

`manifest -> ledger-backed backtest -> promotion handoff -> paper/runtime readiness report`

## Baseline Entry

The current P0 baseline report lives at [docs/report/baseline/2026-05-09-vnext-minimal-closed-loop/](./baseline/2026-05-09-vnext-minimal-closed-loop/).

Use that report for the current scope, change slices, verification commands, and evidence map.

## Manifest

List recent manifests:

```bash
python -m quant_us.cli manifest list --kind all --limit 20
```

Filter the list by data source, symbol, or interval:

```bash
python -m quant_us.cli manifest list --kind data --source yfinance --symbol AAPL --interval 1d --limit 20
```

Inspect a data manifest or backtest run manifest by ID or JSON path:

```bash
python -m quant_us.cli manifest inspect --manifest qs-yfinance-AAPL-1d-07ff0bf4c583
python -m quant_us.cli manifest inspect --manifest ubt_000bd9a6e7794fff
python -m quant_us.cli manifest inspect --manifest data/manifests/run_ubt_000bd9a6e7794fff.json
```

## Backtest Report

Render a backtest report from persisted manifest evidence:

```bash
python -m quant_us.cli report backtest --run-id ubt_000bd9a6e7794fff
python -m quant_us.cli report backtest --manifest data/manifests/run_ubt_000bd9a6e7794fff.json
```

The output highlights `data_version`, `strategy_version`, `commit_hash`, cost model, slippage, and the manifest path.
The backtest manifest is ledger-backed and event-driven, so the report is meant to be read from persisted evidence rather than live engine state.
Promotion-grade manifests also expose data-manifest binding: manifest id, checksum/fingerprint, and whether the binding was missing.
The output includes `evidence_state: PASS manifest_path` when the manifest exists, plus `scope: report only, no execution`.

## Evidence Registry Report

Inspect the saved evidence registry without rebuilding it:

```bash
python -m quant_us.cli report evidence-registry --data-root data
```

The registry status is rendered as one of `PASS`, `STALE`, `MISSING`, or `CONFLICT`.
`CONFLICT` means saved registry content no longer matches the current artifact content.
This command is report-only and does not start paper/live execution.

## Daily Paper Report

Render the latest paper daily report:

```bash
python -m quant_us.cli report daily --latest
```

Render a specific date:

```bash
python -m quant_us.cli report daily --date 2026-05-08
```

The output includes the daily report path, ledger root, validation-state evidence pointers,
and a read-only paper-review status block:

- whether research evidence currently allows entry into `PAPER_REVIEW`
- whether the item is only `manual review pending`
- the review or manifest evidence path used for that conclusion

This report does not approve paper trading and does not enable any order path.
It prints `report_state`, `readiness_state`, `evidence_registry_state`, and `scope: report only, no execution`.
It is evidence-only and cannot submit paper/live orders.
Ledger-derived report artifacts must be idempotent across repeated report runs. If a future command writes ledger state,
it should use a file lock or document why the artifact is single-writer/rebuild-only; the report commands listed here
are read-only evidence views.

## Readiness

Run readiness with traceable evidence paths:

```bash
python -m quant_us.cli readiness --profile simulated
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json --check-credentials
python -m quant_us.cli readiness --profile shadow_live --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile live --validation-state data/reports/paper_production/validation_state.json --check-credentials
```

For small-live gate checks, validation state is required:

```bash
python -m quant_us.cli readiness --small-live --validation-state data/reports/paper_production/validation_state.json
```

Readiness is used as review evidence for runtime decisions. It does not enable broker writes by itself.
Current live mode remains a review-only `LiveRuntime` safety shell even when live-gate evidence passes.
`live start` is fail-closed and must not be treated as an executable order path.

Readiness output also prints validation-state, latest daily report, evidence registry, and paper-review status paths. This is evidence-only:
it does not approve paper trading, and it does not enable paper/live order submission.
`report` and `readiness` are review-only surfaces; they stop at evidence and do not trigger any broker action.

The paper-review status reader now consumes the full Evidence Registry at
`data/research/evidence_registry.json` and still writes the legacy mirror at
`data/research/paper_review_index.json`. The registry is authoritative; the legacy mirror exists for compatibility.
CLI status values are rendered as `PASS`, `STALE`, `MISSING`, and `CONFLICT`; persisted registry internals may still store `present`, `missing`, `stale`, or `changed`.
Rebuild from persisted evidence before operator review handoff:

```python
from quant_us.monitoring.paper_review_status import build_paper_review_evidence_index
build_paper_review_evidence_index("data")
```

Inspect a candidate evidence chain directly:

```python
from quant_us.research.evidence_registry import inspect_candidate_evidence
inspect_candidate_evidence("cand_123", "data")
```

## Research Promotion Gate

Evaluate whether a candidate can enter human paper-review consideration:

```bash
python -m quant_us.cli research promotion-gate --candidate-id cand_123
```

This command only evaluates evidence. It does not start paper trading.
The result is `READY_FOR_PAPER_REVIEW` at best; paper/runtime still needs separate manual approval and a separate readiness report.
Inline backtest manifests remain diagnostic only. Promotion evidence must come from a persisted canonical `backtest_manifest_path`.
The promotion handoff is report/review only, not execution.

## Legacy Candidate Migration

Audit historical candidates that are missing `backtest_manifest_path` and verify whether a canonical
`research/backtests/<candidate_id>/run_manifest.json` exists:

```bash
python scripts/migrate_backtest_manifest_path.py --data-root data
```

Persist the canonical relative manifest path back into `candidate.json` only when the manifest exists:

```bash
python scripts/migrate_backtest_manifest_path.py --data-root data --apply
```

Default mode is dry-run. Inline `backtest_manifest` payloads are never accepted as promotion evidence and are reported for follow-up instead of migrated.

## Full Pipeline Boundary

`scripts/run_full_pipeline.py --mode full` stops at manual paper-review handoff. It prints manifest/evidence references and does not start a paper trading session.

```bash
python scripts/run_full_pipeline.py --symbol AAPL --mode full --start 2024-01-01 --end 2024-03-31
```

Paper trading still requires a separate operator action after human review approval.
Until a later change wires a real Alpaca paper broker adapter into an approved submit path, `paper_broker=alpaca` is expected to fail closed; use the simulated paper backend for local validation.
Paper orders are not submitted by default; an explicit paper submit path must be selected before any broker-write behavior can exist.
The full pipeline handoff is not a paper/live execution command.
