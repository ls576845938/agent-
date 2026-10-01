# Qlib Data Contract

Status: draft for the Qlib + PyPortfolioOpt integration phase.

## Scope

This contract defines the daily-only export path from QuantStation cleaned market data into a Qlib-compatible research dataset.

In scope:

- cleaned daily US equity bars
- explicit universe selection
- manifest-backed lineage
- research-only Qlib input and provider artifacts

Out of scope:

- minute data
- implicit vendor downloads
- broker, OMS, paper, or live execution
- order creation
- look-ahead data access

## Accepted Input

The exporter may read only from existing cleaned daily data and its manifest records.

The controlled preparation path for real data is:

```bash
python3 -m integrations.qlib_adapter.prepare_real_daily_data \
  --universe configs/universe/us_core_liquid.yaml \
  --start-date 2020-01-01 \
  --end-date 2025-12-31 \
  --sync-yfinance \
  --build-provider
```

`--sync-yfinance` is mandatory for vendor access. The adapter never downloads implicitly during export.

Required source properties:

- `bar_size == "1d"`
- `asset_class == "equity"`
- UTC timestamps
- explicit symbol list from `configs/universe/us_core_liquid.yaml` or an equivalent universe config
- one manifest per requested `data_version` or symbol partition

The exporter must not call external data vendors.

## Required Export Fields

The Qlib input table must contain, at minimum:

- `datetime`
- `symbol`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `factor`
- `data_version`
- `source_manifest_hash`

If additional fields are added later, they must remain backward compatible with the above contract.

## Validation Rules

Export must fail closed unless all requested symbols and dates pass validation.

Required checks:

- required columns exist
- `datetime` and `symbol` form a unique key
- `open`, `high`, `low`, `close` are finite and positive
- `high >= max(open, close)`
- `low <= min(open, close)`
- `volume >= 0`
- timestamps are UTC
- the requested date range is covered by the cleaned data
- zero missing daily bars across the requested universe window
- every requested symbol has a manifest binding
- no symbol is implicitly downloaded during export

If any requested symbol is missing, the run must fail clearly and write no provider output.

## Output Artifacts

The exporter should write run-scoped artifacts under:

- `artifacts/qlib_runs/<run_id>/qlib_input/`
- `artifacts/qlib_runs/<run_id>/qlib_provider/`

The export stage should also write a dataset manifest that records:

- `run_id`
- source manifest hashes
- requested universe
- symbol list
- date range
- validation status
- failure reason, if any

## Failure Behavior

The export path must be fail-closed.

Expected failure cases:

- missing symbol
- missing daily rows for any requested symbol/date pair
- invalid OHLC relationship
- duplicate `datetime` and `symbol`
- negative volume
- missing manifest
- unsupported bar size
- unsupported asset class
- any attempt to fall back to vendor download

No Qlib workflow step should proceed if export validation fails.

## Relationship to the Core Platform

This contract is research-only.

It does not change:

- the event-driven backtest engine
- risk checks
- ledger accounting
- paper trading gates
- live safety gates

Qlib output is evidence for research and promotion review only. It is not a readiness signal for paper or live execution.
