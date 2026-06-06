# US Equity Local CSV Lineage Bundles

This directory is the local landing zone for production or sample point-in-time
US equity lineage bundles.

Commit only this README, `.gitkeep`, schemas, tests, and documentation. Do not
commit vendor data files under `bundles/`; those paths are ignored by default.

Expected bundle layout:

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
