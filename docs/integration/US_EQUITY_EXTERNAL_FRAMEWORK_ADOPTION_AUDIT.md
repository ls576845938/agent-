# US Equity External Framework Adoption Audit

- Status: `adoption_complete`
- Generated at: `2026-07-08T14:00:24.186088+00:00`
- Commit: `dc80254e`
- Reference root: `D:\quant_open_source_reference`

| Framework | Status | Dependency | Reference | Boundary |
| --- | --- | --- | --- | --- |
| exchange_calendars / pandas_market_calendars | `complete` | exchange_calendars=yes | n/a | calendar provider only; strategy and execution logic remain local |
| pandas_market_calendars secondary provider | `complete` | pandas_market_calendars=yes | n/a | secondary validation provider, not a separate trading clock |
| QuantStats | `complete` | quantstats=yes | n/a | reporting only; metrics source remains local ledger PnL |
| PyPortfolioOpt | `complete` | pypfopt=yes | n/a | research candidate weights only; local risk and allocator remain authoritative |
| vectorbt | `complete` | vectorbt=yes | n/a | screening only; promising ideas must replay through event-driven ledger backtest |
| Qlib | `complete_optional_dependency_missing` | qlib=no | n/a | research/model workflow only; not live execution or production data lineage authority |
| OpenBB | `complete_optional_dependency_missing` | openbb=no | n/a | supplemental exploration only; not production PIT source |
| NautilusTrader | `complete` | n/a | yes | reference repo outside import path; no migration |
| QuantConnect LEAN | `complete` | n/a | yes | reference repo outside import path; no migration |
| Zipline Reloaded | `complete` | n/a | yes | reference repo outside import path; no migration |

## Guardrails

- External framework output is evidence input only.
- Local ledger PnL and local promotion gates remain authoritative.
- Qlib and OpenBB remain optional research surfaces.
- NautilusTrader, LEAN, and Zipline Reloaded are reference repos outside the import path.
