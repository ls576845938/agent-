# US Equity Production PIT Data Acquisition Checklist

This checklist defines what a real production PIT data bundle must contain before
QuantStation treats it as eligible for provider verification. It is not a data
purchase recommendation, and no provider is considered locally verified until
`provider_verification_report.json` says so.

## Minimum Files

A production bundle must be placed under
`data/external/us_equity_lineage/bundles/<bundle_id>/` and contain:

- `provider_bundle_manifest.json`
- `universe_membership_events.csv`
- `delisted_symbols.csv`
- `corporate_actions.csv`
- `symbol_mapping.csv`
- `adjustment_replay.csv`

Vendor files under `data/external/us_equity_lineage/bundles/*` must not be
committed to git.

## Minimum Fields

Every CSV must include `security_id`. Every event file must include
`source_record_id`. Date fields must be populated where required by the local
CSV contract.

The bundle must provide:

- Identifier mapping effective intervals in `symbol_mapping.csv`.
- Delisting records in `delisted_symbols.csv`.
- PIT membership records in `universe_membership_events.csv`.
- Split, dividend, symbol-change, or equivalent corporate action records in
  `corporate_actions.csv`.
- Adjustment replay records in `adjustment_replay.csv`.

## Minimum Verification Requirements

A bundle is not L4 just because it is labelled production. L4 can only be
derived from local verification.

Required before L4 is possible:

- `source_type = production`
- Manifest `promotion_clean_allowed = true`
- Config `local_csv.promotion_clean_allowed = true`
- Manifest `sha256` values match all files
- Manifest `record_count` values match all files
- `required_tables_available = true`
- `required_fields_available = true`
- `identifier_mapping_available = true`
- `point_in_time_universe_confirmed = true`
- `delisting_coverage_confirmed = true`
- `corporate_action_event_source_available = true`
- `adjustment_reproducibility_confirmed = true`
- `survivorship_clean = true`
- `blockers = []`

## Source Routes

Acceptable engineering routes include:

- CRSP / WRDS or CRSP direct export
- Sharadar / Nasdaq Data Link export
- Polygon / Massive reference and corporate action export
- Norgate export
- Manually curated local CSV bundle

Each route must be normalized into the same local CSV bundle contract before
verification.

## Limits

- Provider capability does not equal local verified evidence.
- Vendor subscription does not equal L4.
- Production bundle presence does not equal L4.
- Preflight pass does not equal promotion clean.
- L4 is determined only by `provider_verification_report.json` and downstream
  `data_status_report.json`.
- L4 only allows the next sprint to re-run factor evidence. It does not allow
  direct portfolio, paper, or live progression.
