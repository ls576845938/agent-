# Generic Local CSV to Local CSV Mapping

## Provider Role

Generic local CSV import supports manually curated or internally transformed
production data. It is the common adapter target for all providers.

## Expected Source Files or Tables

- Dated membership events
- Delisted symbol records
- Corporate action event records
- Dated symbol/security mapping
- Raw/adjusted price replay records

## Mapping

- `universe_membership_events.csv`: one row per membership event with
  `security_id`, ticker, event type, effective date, and source id.
- `delisted_symbols.csv`: one row per delisted security with delisting date,
  reason, last trade date, optional return, and source id.
- `corporate_actions.csv`: one row per split, dividend, merger, spin-off,
  symbol change, delisting, or other action.
- `symbol_mapping.csv`: one row per valid ticker/security interval.
- `adjustment_replay.csv`: one row per replay check with raw close, adjusted
  close, factors, replayed close, and replay error.

## Identifier Strategy

Use `security_id` as the stable key. Ticker is never the stable identity because
tickers can be reused or changed.

## Known Gaps

Manual curation can miss delisted securities, corporate actions, or overlapping
mapping intervals. These must be caught by verification.

## Verification Blockers

Missing required files, missing required fields, invalid dates, duplicate
source ids, mapping conflicts, delisting gaps, corporate action gaps, or replay
errors block promotion.

## Expected Max Lineage Grade Before Verification

At most `L2_static_snapshot`; fixture data remains `L0_fixture`.

## Why Local Verification Is Required

The local bundle contract is the only promotion gate. Human statements about
the files do not count as verified evidence.
