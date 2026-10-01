# US Equity Local CSV PIT Import Operator Guide

## Bundle Directory

Place real external data under:

```text
data/external/us_equity_lineage/bundles/<bundle_id>/
```

Required files:

- `provider_bundle_manifest.json`
- `universe_membership_events.csv`
- `delisted_symbols.csv`
- `corporate_actions.csv`
- `symbol_mapping.csv`
- `adjustment_replay.csv`

Do not commit vendor data. The bundle directory is ignored by git.

## CSV Fields

`universe_membership_events.csv`:
`security_id,ticker,universe_name,event_type,effective_date,end_date,source_record_id`

`delisted_symbols.csv`:
`security_id,ticker,delisting_date,delisting_reason,last_trade_date,delisting_return,source_record_id`

`corporate_actions.csv`:
`security_id,ticker,event_type,ex_date,effective_date,ratio,cash_amount,old_symbol,new_symbol,source_record_id`

`symbol_mapping.csv`:
`security_id,ticker,start_date,end_date,figi,cik,cusip,permno,exchange,source_record_id`

`adjustment_replay.csv`:
`security_id,ticker,date,raw_close,adjusted_close,split_factor,dividend_adjustment,total_adjustment_factor,replay_adjusted_close,replay_error,source_record_id`

## Source Type

- `fixture`: tests only; never `promotion_clean`.
- `sample`: research/import testing; never `promotion_clean` by default.
- `production`: eligible for L4 only after every verification gate passes.

`promotion_clean_allowed` must be true in both manifest and
`configs/data/us_equity_provider_sources.yaml`. It does not bypass validation.

## SHA256

Compute per-file hashes with:

```bash
sha256sum universe_membership_events.csv delisted_symbols.csv corporate_actions.csv symbol_mapping.csv adjustment_replay.csv
```

Generate a manifest:

```bash
python3 scripts/build_us_equity_local_csv_bundle_manifest.py \
  --bundle-root data/external/us_equity_lineage/bundles/<bundle_id> \
  --bundle-id <bundle_id> \
  --source-provider local_csv \
  --source-type production \
  --sample-start YYYY-MM-DD \
  --sample-end YYYY-MM-DD \
  --as-of-date YYYY-MM-DD \
  --universe-name <name> \
  --price-data-reference <data_version_or_path> \
  --license-note "<source/license note>"
```

## Provider Verification

Enable `local_csv` in `configs/data/us_equity_provider_sources.yaml`, set
`bundle_manifest`, and run:

```bash
python3 scripts/build_us_equity_provider_verification_report.py
python3 scripts/build_us_equity_data_status_report.py
python3 scripts/run_us_equity_factor_evidence.py
python3 scripts/build_global_research_registry.py
```

Inspect blockers:

```bash
python3 -m json.tool artifacts/us_equity_data_lineage/latest/provider_verification_report.json
```

## Provider Conversion Path

CRSP, Sharadar, Polygon, Norgate, or self-maintained data should first be
normalized into this local CSV bundle. The provider verification report is the
only path toward promotion-clean lineage. Provider capability, fixture data, and
sample data are never enough.
