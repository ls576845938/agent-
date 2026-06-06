# US Equity Production PIT Data Acquisition Operator Guide

This guide describes how to land a real production PIT bundle for QuantStation.
It does not require this sprint to have data and does not authorize portfolio,
paper, or live progression.

## Why yfinance Is Research-Only

The current yfinance daily bars are useful for research diagnostics, but they
do not provide verified PIT membership, delisted coverage, corporate action
events, identifier mapping, or reproducible adjustment replay. They remain
`L1_sample_non_pit`.

## Why Fixture and Sample Bundles Cannot Be Promotion-Clean

Fixtures are contract-test inputs. Samples are partial research inputs. Neither
can prove production survivorship, corporate action, or PIT coverage, even if
their structural validation passes.

## Production Bundle Directory

Use:

```text
data/external/us_equity_lineage/bundles/<bundle_id>/
  provider_bundle_manifest.json
  universe_membership_events.csv
  delisted_symbols.csv
  corporate_actions.csv
  symbol_mapping.csv
  adjustment_replay.csv
```

Files under `bundles/*` are ignored by git and should not be committed.

## Choosing a Provider

Choose an export route that can produce PIT membership, delistings, corporate
actions, symbol mapping, and price adjustment replay inputs. Candidate routes
include CRSP, Sharadar/Nasdaq Data Link, Polygon/Massive, Norgate, or an
internally curated CSV package.

## Converting Vendor Export to Local CSV

Normalize vendor data into the five required CSVs. Provider-specific mapping
notes live in `docs/us_equity_provider_mappings/`.

Keep ticker as an alias. Use `security_id` as the stable identity.

## Computing SHA256

From the bundle directory:

```bash
sha256sum universe_membership_events.csv delisted_symbols.csv corporate_actions.csv symbol_mapping.csv adjustment_replay.csv
```

Record each digest in `provider_bundle_manifest.json`.

## Filling the Manifest

Set:

- `source_type = production`
- `source_provider` to the export route
- `sample_start` and `sample_end`
- `license_note` with local access/source context
- `promotion_clean_allowed = true` only after human approval that this is a
  real production bundle
- each file path, `sha256`, and `record_count`

## Selecting the Bundle

Set `configs/data/us_equity_provider_sources.yaml`:

```yaml
providers:
  local_csv:
    enabled: true
    root: data/external/us_equity_lineage/
    selected_bundle_id: <bundle_id>
    require_explicit_bundle_selection: true
    promotion_clean_allowed: true
```

Do not enable `promotion_clean_allowed` for fixture or sample bundles.

## Running Validation

Use CI-friendly fail-closed validation:

```bash
make validate-us-equity-production-bundle
```

Use strict acquisition validation when a production bundle is expected:

```bash
make validate-us-equity-production-bundle-strict
```

Then rebuild broader evidence:

```bash
make validate-us-equity-evidence
```

## Reading Artifacts

Check:

- `artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json`
- `artifacts/us_equity_data_lineage/latest/provider_verification_report.json`
- `artifacts/us_equity_data_status/latest/data_status_report.json`
- `artifacts/us_equity_factor_evidence/latest/factor_evidence_pack.json`
- `artifacts/global_research_registry/research_registry.json`

## Common Blockers

- `point_in_time_universe_not_confirmed`
- `delisting_coverage_missing`
- `corporate_action_event_source_missing`
- `identifier_mapping_missing`
- `adjustment_reproducibility_missing`
- `config_promotion_clean_not_allowed`
- `bundle_promotion_clean_not_allowed`
- `local_csv_*_sha256_mismatch`
- `local_csv_*_record_count_mismatch`
- symbol mapping overlap blockers

## Promotion Boundary

L4 only allows a new factor evidence run on promotion-clean data. L4 does not
allow direct portfolio, paper queue unlock, or live unlock.
