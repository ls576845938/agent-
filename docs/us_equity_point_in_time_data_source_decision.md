# US Equity Point-in-Time Data Source Decision

## Current Status

- yfinance daily bars are research-only price data.
- Current data lineage grade is `L1_sample_non_pit`.
- `promotion_clean` remains `false`.
- The local repository does not contain verified point-in-time membership, delisted symbol coverage, corporate action event source, adjustment replay, or effective-dated identifier mapping.

## Candidate Sources

| Source | PIT universe | Delisted coverage | Corporate actions | Adjustment reproducibility | Identifier mapping | Import complexity | Cost/access constraint | Expected max lineage grade | Remaining blockers |
|---|---|---|---|---|---|---|---|---|---|
| CRSP | Candidate capability must be locally verified | Candidate capability must be locally verified | Candidate capability must be locally verified | Requires local replay proof | Requires effective-dated mapping | Medium/high | External access required | Up to L4 after local verification | Provider not configured, local evidence missing |
| Sharadar / Nasdaq Data Link | Candidate capability must be locally verified | Candidate capability must be locally verified | Candidate capability must be locally verified | Requires local replay proof | Requires effective-dated mapping | Medium | External access required | Up to L4 after local verification | Provider not configured, local evidence missing |
| Polygon | Candidate capability must be locally verified | Candidate capability must be locally verified | Candidate capability must be locally verified | Requires local replay proof | Requires effective-dated mapping | Medium | External access required | Up to L4 only if all required local evidence verifies | Provider not configured, local evidence missing |
| Norgate | Candidate capability must be locally verified | Candidate capability must be locally verified | Candidate capability must be locally verified | Requires local replay proof | Requires effective-dated mapping | Medium | External access required | Up to L4 after local verification | Provider not configured, local evidence missing |
| Local CSV import | Supported by QuantStation adapter contract | Supported by QuantStation adapter contract | Supported by QuantStation adapter contract | Requires local adjustment replay report | Supported by required CSV schema | Low/medium | Depends on imported dataset | Up to L4 after local verification | CSV files missing, replay proof missing |

## Supplemental Sources

Tiingo, IBKR market data, and FRED may support price checks, macro features, or
execution-adjacent diagnostics, but they do not by themselves satisfy the
production PIT milestone. Their boundaries are recorded in
`docs/us_equity_supplemental_data_source_boundaries.md` and in the
`us_equity_pit_procurement_readiness_report`.

## Recommended Engineering Path

1. Keep provider contracts provider-neutral.
2. Use Local CSV as the first import path because it is cheap to test and does not hard-code a paid vendor.
3. Import a real sample containing PIT membership, delisted symbols, corporate actions, symbol mapping, and adjustment replay evidence.
4. Run `provider_verification_report` and require all blockers to clear before allowing `promotion_clean=true`.
5. Connect a specific provider only after its local files pass the same contract.

Provider advertised capability is not QuantStation evidence. A provider can only move the system toward `L4_promotion_clean` after local ingest, hashing, schema validation, event counts, identifier mapping, adjustment replay, and survivorship audit all pass.
