# US Equity Local CSV Bundle Contract

## Layout

```text
data/external/us_equity_lineage/
  bundles/
    <bundle_id>/
      provider_bundle_manifest.json
      universe_membership_events.csv
      delisted_symbols.csv
      corporate_actions.csv
      symbol_mapping.csv
      adjustment_replay.csv
```

`data/external/us_equity_lineage/bundles/*` is ignored by git. Only docs,
schemas, and small test fixtures should be committed.

## Manifest Rules

`provider_bundle_manifest.json` pins the bundle identity, source, date range,
license/source note, file hashes, and record counts. Missing source metadata,
missing files, SHA mismatch, record-count mismatch, or missing sample date range
must fail closed.

`source_type` is one of:

- `fixture`: contract tests only; never promotion clean.
- `sample`: research/import testing only; never promotion clean by default.
- `production`: eligible for promotion-clean evaluation only after all local
  verification gates pass.

`promotion_clean_allowed` must be true in both the manifest and provider config
before a production bundle can become promotion clean. This flag alone does not
promote data.

## Required CSVs

- `universe_membership_events.csv`
- `delisted_symbols.csv`
- `corporate_actions.csv`
- `symbol_mapping.csv`
- `adjustment_replay.csv`

Each CSV must contain required headers, non-empty rows, valid dates, unique
`source_record_id`, valid event types, and security IDs that resolve through
effective-dated `symbol_mapping`.

## Promotion-Clean Gate

`promotion_clean=true` requires all of:

- selected provider is `local_csv` or another real provider adapter.
- `source_type=production`.
- manifest and config both set `promotion_clean_allowed=true`.
- local data is available.
- all required files, fields, hashes, and record counts validate.
- effective-dated identifier mapping is available.
- PIT universe membership is confirmed.
- delisting coverage is confirmed.
- corporate action event source is available.
- adjustment replay is within tolerance.
- survivorship is clean.
- blockers are empty.

Fixture/sample structural success is not promotion evidence.
