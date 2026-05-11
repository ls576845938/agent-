# Crypto Frontend Runbook

This page describes the Crypto workspace in the frontend.

## What the workspace does

- Uses the SQLite market data store as the primary BTC source.
- Shows SQLite coverage by interval for `1m`, `5m`, `15m`, `1h`, `4h`, and `1d`.
- Exposes a resample chain button that triggers interval-specific SQLite sync jobs.
- Runs the existing event-driven backtest flow through the normal backtest endpoints.
- Surfaces data quality blockers and promotion-gate blockers before acceptance.

## Typical flow

1. Open `/crypto`.
2. Verify the SQLite path and interval coverage.
3. Run `1m -> 1d` resampling if any interval is missing.
4. Run the event-driven backtest with the desired mode.
5. Check data quality and promotion blockers before promotion review.

## Notes

- The workspace is review and research oriented.
- It does not bypass the backtest, risk, or promotion gate layers.
- SQLite coverage and blocker status are read from backend APIs; the frontend only presents the evidence.
