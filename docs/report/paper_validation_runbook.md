# 30-Day Paper Validation Runbook

This runbook is for the read-only, fail-closed paper-validation evidence loop.
It does not enable Alpaca submit, does not enable live trading, and does not
modify the execution/live submit path.

## Scope

- Runtime mode: paper validation only
- Submit mode: disabled
- Live orders: forbidden
- Promotion target: evidence only, not broker authorization

The operator should treat any missing evidence as `BLOCKED`.

## Required Inputs

- Market data present under `data/raw/vendor=<source>/asset_class=equity/bar_size=<bar_size>/symbol=<SYMBOL>/date=*.parquet`
- Paper ledger root, default `data/paper_ledger`
- Validation state path, default `data/reports/paper_production/validation_state.json` or `data/paper_ledger/validation_state.json`

## Preflight

Run this before day 1, before every resume, and after any operational incident:

```bash
python3 scripts/check_paper_validation_readiness.py \
  --data-root data \
  --ledger-root data/paper_ledger \
  --validation-state data/reports/paper_production/validation_state.json
```

JSON form for automation:

```bash
python3 scripts/check_paper_validation_readiness.py \
  --data-root data \
  --ledger-root data/paper_ledger \
  --validation-state data/reports/paper_production/validation_state.json \
  --json
```

The preflight blocks on any of these:

- market data missing for one or more tracked symbols
- `validation_state.json` missing or unreadable
- daily report directory or latest daily report missing
- startup sync artifact missing, unreadable, or lacking no-submit proof
- broker-state recovery artifact missing or `operationally_complete=false`
- ledger reconciliation report missing, dirty, or missing reconciliation artifact
- session manifest missing, `submit_orders=true`, or no-submit proof failed

## Daily Run

Run the validation loop with submit disabled:

```bash
python3 scripts/run_paper_validation.py \
  --data-root data \
  --symbols AAPL,MSFT \
  --ledger-root data/paper_ledger \
  --days-required 30 \
  --source yfinance \
  --bar-size 1d
```

The script persists state after every processed trading day and rewrites the
evidence bundle after each save.

## Daily Artifacts

Expected artifacts after each clean trading day:

- `data/paper_ledger/daily_reports/daily_report_<DATE>.json`
- `data/paper_ledger/reconciliation/recon_<TIMESTAMP>.json`
- `data/paper_ledger/reconciliation/ledger_recon_artifact_<HASH>.json`
- `data/paper_ledger/audit/paper_session_manifest.json`
- `data/paper_ledger/audit/paper_broker_adapter_startup_sync.json`
- `data/paper_ledger/audit/paper_broker_state_recovery.json`
- `data/paper_ledger/validation_report.json`
- `data/paper_ledger/validation_state.json` or `data/reports/paper_production/validation_state.json`

Review surfaces:

```bash
python3 -m quant_us.cli report paper-validation --data-root data
python3 -m quant_us.cli report daily --latest --data-root data
```

## Resume

To resume after interruption, rerun the same command. The script reuses the
persisted validation state and fail-closes if recovery evidence is not
operationally complete.

Resume checklist:

1. Re-run preflight.
2. Confirm `paper_broker_state_recovery.json` exists and is operationally complete.
3. Confirm startup sync artifact still proves no submit.
4. Confirm latest ledger reconciliation artifact exists and is clean.
5. Resume only if preflight returns `PASS`.

## Fail-Closed Rules

Stop and investigate if any of these occur:

- preflight returns `BLOCKED`
- `paper_validation_state` in the CLI report is `BLOCKED`
- recovery artifact missing or incomplete
- startup sync missing or its no-submit proof fails
- ledger reconciliation missing, dirty, or missing artifact
- session manifest shows `submit_orders=true`
- any proof suggests real order submission

Do not override these by manually editing evidence files.

## Passing Standard

Paper validation passes only when all of these are true:

1. `consecutive_clean_days >= days_required`
2. preflight status is `PASS`
3. broker-state recovery artifact is present and operationally complete
4. startup sync artifact is present and proves no submit
5. session manifest proves read-only/no-submit
6. latest ledger reconciliation is clean and has a matching artifact
7. latest daily report has no recorded errors

Anything else is either `INCOMPLETE` or `BLOCKED`.
