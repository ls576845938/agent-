# Verification

This baseline is documentation-first, but it still needs a small set of reproducible checks.

## Core Checks

```bash
PYTHONPATH=. pytest backend/tests/ -q
```

Use `PYTHONPATH=.` for the full test run so the repository imports resolve the same way they do for local commands and report scripts.

```bash
python -m quant_us.cli manifest list --kind all --limit 20
python -m quant_us.cli report backtest --run-id <run_id>
python -m quant_us.cli report daily --latest
python -m quant_us.cli readiness --profile simulated
python -m quant_us.cli research promotion-gate --candidate-id <candidate_id>
```

```bash
python scripts/run_full_pipeline.py --symbol AAPL --mode full --start 2024-01-01 --end 2024-03-31
```

## Verification Expectations

- the README states the full-test command with `PYTHONPATH=.`
- the README states that real Alpaca paper is not yet integrated
- the minimal closed-loop doc says promotion is not execution
- CLI report commands stay read-only
- the baseline directory contains the required report files

## Verification Notes

If a check fails, the report should record the exact command and the exact failure output. Do not infer pass/fail from summary text alone.
