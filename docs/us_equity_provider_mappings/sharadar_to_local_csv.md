# Sharadar to Local CSV Mapping

## Provider Role

Sharadar / Nasdaq Data Link can be a candidate source for prices, corporate
actions, delistings, ticker metadata, and security coverage. It is not treated
as verified evidence until local exports pass QuantStation verification.

## Expected Source Files or Tables

- Equity price exports
- Ticker/security metadata
- Corporate action tables
- Delisted ticker coverage
- Optional index or universe membership source

## Mapping

- `universe_membership_events.csv`: derive add/list/remove/delist membership
  records from dated universe or listing metadata.
- `delisted_symbols.csv`: map delisted ticker rows to dated delisting records.
- `corporate_actions.csv`: map dividends, splits, symbol changes, mergers, and
  comparable actions.
- `symbol_mapping.csv`: map provider ticker/security identifiers to dated
  ticker intervals and optional CIK/CUSIP fields.
- `adjustment_replay.csv`: replay adjusted close from raw close plus available
  split/dividend adjustment factors.

## Identifier Strategy

Use provider ticker/security identifiers as `security_id` only when they remain
stable across symbol changes; otherwise create an internal stable id and map
dated aliases.

## Known Gaps

PIT index membership may not be included in a basic export. Delisting and
corporate action completeness must be checked per subscription/export.

## Verification Blockers

PIT missing, delisting missing, corporate action missing, mapping conflicts,
or replay error over tolerance block promotion.

## Expected Max Lineage Grade Before Verification

At most `L2_static_snapshot` before local verification.

## Why Local Verification Is Required

Provider claims do not establish local row counts, hashes, date coverage, or
replay reproducibility.
