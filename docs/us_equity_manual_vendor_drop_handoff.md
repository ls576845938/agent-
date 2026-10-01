# US Equity Manual Vendor Drop Handoff

This package is the operator-facing contract for a licensed production PIT data drop.

- Incoming drop dir: `data/external/us_equity_lineage/incoming/manual_vendor_drop`
- Default bundle id: `manual_vendor_bundle_v1`
- Template root: `docs/us_equity_manual_vendor_drop_templates`
- Field dictionary: `docs/us_equity_manual_vendor_drop_field_dictionary.md`

## Required Files

- `universe_membership_events.csv`: 7 required fields for `universe_membership_events`
- `delisted_symbols.csv`: 7 required fields for `delisted_symbols`
- `corporate_actions.csv`: 10 required fields for `corporate_actions`
- `symbol_mapping.csv`: 10 required fields for `symbol_mapping`
- `adjustment_replay.csv`: 11 required fields for `adjustment_replay`
- `macro_release_calendar.csv`: 6 required fields for `macro_release_calendar`

## Commands

```powershell
python scripts/build_us_equity_manual_vendor_drop_package.py
```
```powershell
python scripts/build_us_equity_incoming_drop_readiness_report.py
```
```powershell
python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --sample-start 2000-01-01 --sample-end 2026-06-24 --license-note "<license scope>" --promotion-clean-allowed
```
```powershell
python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id manual_vendor_bundle_v1 --license-reviewed
```
```powershell
python scripts/run_us_equity_daily_production_line.py
```

## Operator Checklist

- `build_handoff_package`: Build the handoff package and templates -> us_equity_manual_vendor_drop_package_report.status == manual_vendor_drop_package_ready
- `create_incoming_drop_dir`: Create the incoming vendor drop directory -> data/external/us_equity_lineage/incoming/manual_vendor_drop exists and is a directory
- `copy_six_licensed_csv_files`: Copy exactly six licensed CSV files into the incoming drop -> incoming drop contains the six required CSV filenames and no parquet/xlsx substitutes
- `run_incoming_drop_readiness`: Run incoming drop readiness -> us_equity_incoming_drop_readiness_report.status == incoming_drop_ready_for_import
- `import_local_csv_bundle`: Import the local CSV production bundle -> us_equity_local_csv_production_bundle_import_report.status == production_bundle_imported
- `run_acceptance_and_activation`: Run PIT bundle acceptance and activation preflight -> pit acceptance ready and activation candidate emitted for manual config apply
- `rerun_daily_production_line`: Rerun the daily production line after data evidence changes -> daily report updates production_pit_drop and remediation closure state

## Acceptance Rules

- Use the exact six CSV filenames; do not substitute parquet/xlsx files in the incoming drop.
- Every CSV must include the exact header order from docs/us_equity_manual_vendor_drop_templates.
- Templates are header-only and are not valid vendor data.
- Tiingo, IBKR, FRED, yfinance, fixtures, templates, and latest-only exports are not standalone production PIT evidence.
- All date fields use YYYY-MM-DD; macro available_time_utc uses UTC timestamp ending with Z.
- source_record_id must be globally unique across all six CSVs.
- security_id must be stable and effective-dated through symbol_mapping.
- The package does not grant promotion-clean status and cannot unlock paper/live trading.

## Source Boundary Rules

### Acceptable only after normalization

- `crsp`: CRSP / WRDS or CRSP direct export
- `sharadar_nasdaq_data_link`: Sharadar / Nasdaq Data Link export
- `polygon_massive`: Polygon / Massive reference and corporate action export
- `norgate`: Norgate export
- `curated_local_csv`: Manually curated licensed local CSV bundle

### Supplemental only

- `tiingo_eod`: not sufficient for `point-in-time universe membership, full delisted-security coverage`
- `ibkr_market_data`: not sufficient for `historical point-in-time index membership, survivorship-bias-free research universe`
- `fred`: not sufficient for `equity universe membership, delisted equity coverage`

## Guardrails

- This handoff contains no vendor data.
- Do not commit licensed CSV drops.
- Do not treat readiness/import success as strategy validation or live readiness.
