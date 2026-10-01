# US ETF Macro Momentum Rotation Integration

## Status

`us_etf_macro_momentum_rotation_v1` is integrated as a research-only US equity
strategy candidate. It is adapted from:

`legacy_strategies/us_etf_rotation_original`

That directory is a repository-local snapshot copied from
`D:/Trading/ETF轮动与数据引擎模块化代码` after running
`python scripts/backup_external_strategy_project.py --repo-root .`.

The integration ports the strategy math and report generation only. It does not
import the external scheduler, downloader, plotting code, broker calls, private
endpoints, or order endpoints.

## Strategy Shape

- Monthly rebalance on the last available trading day of each month.
- T+1 effective weights by shifting target weights one trading day forward.
- Offensive ETF pool ranked by idiosyncratic, volatility-adjusted momentum.
- 200-day moving average trend filter.
- Macro regime score from liquidity, credit spread, and SPY trend when FRED
  macro data is available.
- Defense asset allocation across `IEF`, `GLD`, `DBMF`, and `SHV`.
- Inverse-volatility weighting plus target-volatility scaling.
- Turnover cost deducted through `cost_per_turnover`.

## Current Boundary

The canonical Tiingo EOD lake now sits at:

`data/external/us_equity_eod/tiingo`

It is the preferred price source for this strategy and for future US equity
strategy families. The integration can still fall back to the user's external
strategy data lake at:

`D:/Trading/PythonApplication1/data_cache_lake`

That external lake contains the legacy ETF pool and `FRED_MACRO.parquet`, so it
remains useful as a migration fallback and parity source. It is still not
promotion-clean PIT data.

The strategy requires this wider ETF pool:

`QQQ, VOO, MTUM, QMOM, SOXX, IGV, XBI, XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, BITO, PDBC, GLD, USO, IEF, DBMF, SHV, SPY`

Until these symbols plus macro data are available through the canonical data
path, the strategy can only use the external data lake as non-production
research evidence.

## Artifact

Run:

```powershell
python scripts\build_us_etf_macro_rotation_research_report.py
```

The default command checks Tiingo first, then the legacy external data lake, then
canonical cleaned bars. To force Tiingo off:

```powershell
python scripts\build_us_etf_macro_rotation_research_report.py --tiingo-data-lake ""
```

Output:

```text
artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json
artifacts/us_equity_etf_macro_rotation/latest/target_weights.csv
artifacts/us_equity_etf_macro_rotation/latest/daily_returns.csv
```

The CSV outputs are written only when all required price symbols have enough
common history.

## Promotion Rule

This integration does not unlock portfolio, paper, or live progression. The
report always sets:

```text
allowed_next_action = research_only
promotion_ready = false
paper_ready = false
live_ready = false
live_order_allowed = false
```

Before this strategy can become a real candidate, the US equity system must
first clear production-grade data lineage: point-in-time universe membership,
delisting coverage, corporate action event source, symbol mapping, and
adjustment replay.
