# Norgate to Local CSV Mapping

## Provider Role

Norgate can be a candidate source for survivorship-aware equities data,
delistings, corporate actions, and index membership exports. It is not locally
verified until normalized bundle files pass QuantStation verification.

## Expected Source Files or Tables

- PIT constituent or universe membership export
- Delisted/security status export
- Split/dividend/corporate action export
- Symbol/security identifier export
- Raw and adjusted prices for replay checks

## Mapping

- `universe_membership_events.csv`: map constituent and status changes to
  add/list/remove/delist events.
- `delisted_symbols.csv`: map delisted records with dates, reasons, and last
  trade dates.
- `corporate_actions.csv`: map splits, dividends, mergers, and symbol changes.
- `symbol_mapping.csv`: map Norgate security ids to dated ticker/exchange
  intervals.
- `adjustment_replay.csv`: replay adjusted prices from raw bars and action
  factors.

## Identifier Strategy

Use a stable security id from the export. Keep ticker as a dated alias and
include exchange when available.

## Known Gaps

Export settings can change coverage. Adjustment replay must be independently
validated instead of assuming provider-adjusted bars are reproducible.

## Verification Blockers

Missing membership, delisting, corporate action, mapping, or replay evidence
blocks promotion.

## Expected Max Lineage Grade Before Verification

At most `L2_static_snapshot` before local verification.

## Why Local Verification Is Required

Local row hashes, counts, coverage, and replay accuracy must be proven inside
QuantStation.
