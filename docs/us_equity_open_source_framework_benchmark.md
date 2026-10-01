# US Equity Open Source Framework Benchmark

Date: 2026-07-08

## Context

The current US equity system is not an empty project. It already has a
research-first production line:

```text
data ingestion
-> data quality / PIT check
-> strategy hypothesis registration
-> standardized backtest
-> cost, liquidity, capacity stress
-> walk-forward / parameter stability
-> strategy validation gate
-> forward observation
-> manual review
-> paper simulation
-> small-capital live readiness
-> monitoring / attribution / retirement
```

Current local constraints remain:

- `quant_us` already has backtest, data, execution, risk, signals, strategies,
  reports, and forward-observation modules.
- The primary US ETF strategy is
  `us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x`.
- The current production-line report is still
  `production_line_blocked_before_paper_or_live`.
- Strategy validation is blocked by data quality / PIT evidence, not by the
  absence of a third-party framework.
- Forward observation verifies operational quality only. It is not alpha
  validation and must not unlock live trading.

Therefore, external frameworks should be used as reference implementations or
optional adapter libraries, not as a wholesale replacement for the local
production line.

## Selection Principles

Use external frameworks when they reduce proven engineering risk in one module:

- exchange calendar correctness;
- performance and tear-sheet reporting;
- portfolio optimization prototypes;
- ML research workflow structure;
- event-driven execution architecture reference;
- broker API adapter ergonomics.

Do not use external frameworks to bypass local rules:

- no broker calls from strategy code;
- no paper/live without promotion gates;
- no non-PIT data promoted as production-clean;
- no PnL that cannot be replayed from fills and ledger;
- no framework-native backtest report accepted without local evidence contract.

## Highest Priority: Use Or Vendor-Learn Now

### exchange_calendars

- Repository: https://github.com/gerrymanoim/exchange_calendars
- Role: US trading calendar, sessions, holidays, early closes.
- Why it matters: our US ETF system currently needs correct NYSE/Nasdaq session
  handling for daily close, next-session execution, forward observation, and
  month-end rebalance rules.
- Recommended use: add as a real dependency or wrap behind
  `quant_us.core.calendar`.
- Boundary: calendar output still needs local tests for market close,
  early-close, holiday, and timezone behavior.

### pandas_market_calendars

- Repository: https://github.com/rsheftel/pandas_market_calendars
- Role: alternative or secondary market-calendar library.
- Recommended use: compare against `exchange_calendars` for XNYS schedule
  parity; do not keep both in core unless the adapter boundary is clean.

### QuantStats

- Repository: https://github.com/ranaroussi/quantstats
- Role: performance analytics, drawdown charts, rolling stats, HTML tear sheets.
- Recommended use: use as report inspiration and possibly optional dashboard
  export after our own metrics are computed from ledger returns.
- Boundary: QuantStats output cannot become the source of truth for promotion
  gates. Local ledger-derived metrics remain canonical.

### PyPortfolioOpt

- Repository: https://github.com/PyPortfolio/PyPortfolioOpt
- Role: portfolio optimization prototypes: efficient frontier,
  Black-Litterman, HRP, shrinkage covariance.
- Recommended use: research sandbox for future multi-strategy / multi-ETF
  allocation. Good fit for translating alpha forecasts into target weights.
- Boundary: optimizer output must pass local risk constraints, turnover limits,
  financing cost, and small-account execution preflight.

### Riskfolio-Lib

- Repository: https://github.com/dcajasn/Riskfolio-Lib
- Role: richer portfolio optimization and risk measures.
- Recommended use: second-stage research only, after PyPortfolioOpt baseline.
- Boundary: heavier dependencies and solver behavior make it unsuitable as a
  first production dependency. Use for comparison and advanced allocation
  experiments.

## High Value Reference: Download For Architecture Study

### NautilusTrader

- Repository: https://github.com/nautechsystems/nautilus_trader
- Role: event-driven engine, deterministic simulation, live/research parity,
  adapters, cache, message bus, order and execution semantics.
- Why it is valuable: it is closest to our long-term goal of one shared
  research/backtest/live semantic model.
- Recommended use: clone outside the main package, study architecture, and
  borrow concepts for:
  - event model;
  - order lifecycle;
  - fill model;
  - execution semantics;
  - adapter boundaries;
  - deterministic replay.
- Boundary: do not migrate the current US ETF production line to Nautilus now.
  It is too heavy for the current blocker, which is PIT data evidence.

### QuantConnect LEAN

- Repository: https://github.com/QuantConnect/Lean
- Role: full algorithmic trading engine with research, backtest, optimization,
  live trading, brokerages, data, reports, and CLI.
- Recommended use: architecture reference for:
  - engine component boundaries;
  - brokerage models;
  - data normalization modes;
  - algorithm lifecycle;
  - report generation;
  - CLI workflow.
- Boundary: LEAN is C#/Python and a large platform. Do not embed it into this
  repo. Use it for design comparison and optional external smoke tests only.

### Zipline Reloaded

- Repository: https://github.com/stefan-jansen/zipline-reloaded
- Role: Pythonic event-driven backtesting, historical lineage from Quantopian.
- Recommended use: study bundle ingestion, Pipeline-style factor research,
  asset finder, adjustments, and exchange-calendar integration.
- Boundary: do not adopt it as the production engine. It can be difficult to
  reconcile with our custom PIT vendor bundle and ledger-first evidence
  contract.

## Research Acceleration: Useful But Not Production Backbone

### vectorbt

- Repository: https://github.com/polakowo/vectorbt
- Role: fast vectorized research, parameter sweeps, multi-asset experiments,
  interactive analysis.
- Recommended use: optional sandbox for early hypothesis screening and parameter
  neighborhood scans.
- Boundary: vectorized outputs are not sufficient for promotion. Any promising
  idea must be replayed through the local event-driven ledger backtest.

### bt

- Repository: https://github.com/pmorissette/bt
- Role: reusable algo stacks for portfolio strategy research.
- Recommended use: study its composable `Algo` pattern for our signal and
  portfolio layer. It is especially relevant to ETF rotation.
- Boundary: do not replace our backtest engine; use as design inspiration.

### Qlib

- Repository: https://github.com/microsoft/qlib
- Role: AI / ML quant research platform with data processing, model training,
  backtesting, alpha seeking, risk modeling, portfolio optimization, and order
  execution concepts.
- Current local state: `pyqlib` is already an optional `integrations`
  dependency.
- Recommended use: make Qlib an external research agent for future US
  single-stock or ETF-factor experiments. Use it for ML workflow patterns:
  dataset handler, recorder, model training, evaluation, IC/RankIC style
  analysis.
- Boundary: Qlib must not define live permission or production data lineage.
  It depends on the quality of the data we feed it.

### OpenBB

- Repository: https://github.com/OpenBB-finance/OpenBB
- Role: data integration and analyst/research surfaces.
- Recommended use: supplemental data exploration, research dashboards,
  fundamentals/news/macro discovery, AI assistant data surface.
- Boundary: OpenBB is not a PIT-clean production data source by itself. Any data
  that matters for promotion must enter through our provider-neutral ingest and
  lineage contract.

## Lower Priority / Learn Only

### Backtesting.py

- Repository: https://github.com/kernc/backtesting.py
- Role: simple educational backtesting.
- Reason to avoid as dependency: AGPL-3.0 license and simplified model make it
  unsuitable for our core production engine.
- Use: learn API ergonomics and plotting ideas only.

### Backtrader

- Repository: https://github.com/mementum/backtrader
- Role: classic Python backtesting and learning framework.
- Reason to avoid as dependency: older live-trading ecosystem and no direct fit
  with our PIT/ledger/promotion contract.
- Use: educational reference only.

### FinRL / TradeMaster

- Role: reinforcement-learning research.
- Reason to defer: RL adds sample-efficiency, reward-design, overfitting, and
  environment mismatch risk. It does not solve our current data lineage and ETF
  production-line blockers.
- Use: future research only, after the deterministic production line is stable.

### TradingAgents

- Role: LLM multi-agent investment discussion / research workflow.
- Reason to avoid in trading path: output is not deterministic enough for
  strategy signals, risk gates, or execution.
- Use: research-note generation, narrative challenge, and post-trade review
  only.

## IBKR API Adapter

### ib_async

- Repository: https://github.com/ib-api-reloaded/ib_async
- Role: Python sync/async framework for Interactive Brokers API.
- Recommended use: evaluate as a future replacement or complement to
  `ib_insync` for data probes and paper/live adapter experiments.
- Boundary: keep it behind a broker/data adapter. Strategy code must never
  import IBKR libraries directly.

## Current System Gap Mapping

| Gap | Best external reference | Action |
| --- | --- | --- |
| US session calendar, early close, month-end actual trading day | `exchange_calendars`, `pandas_market_calendars` | Wrap and test in `quant_us.core.calendar` |
| Fast parameter neighborhood screening | `vectorbt` | Optional sandbox, then replay through local ledger |
| ETF portfolio construction patterns | `bt`, `PyPortfolioOpt`, `Riskfolio-Lib` | Borrow composable portfolio layer ideas |
| ML alpha research production workflow | `Qlib` | Keep as external research integration, not execution |
| Data explorer / research surface | `OpenBB` | Supplemental data discovery only |
| Event-driven execution architecture | `NautilusTrader`, `LEAN`, `Zipline Reloaded` | Architecture study, not immediate migration |
| Performance reports | `QuantStats`, `pyfolio/empyrical concepts` | Optional reporting layer, local metrics canonical |
| IBKR connectivity | `ib_async`, official IB API | Adapter-only, no strategy imports |

## Recommended Download Plan

Clone reference repos outside the import path so they cannot accidentally become
runtime dependencies:

```powershell
mkdir D:\quant_open_source_reference
cd D:\quant_open_source_reference
git clone https://github.com/nautechsystems/nautilus_trader.git
git clone https://github.com/QuantConnect/Lean.git
git clone https://github.com/stefan-jansen/zipline-reloaded.git
git clone https://github.com/polakowo/vectorbt.git
git clone https://github.com/pmorissette/bt.git
git clone https://github.com/microsoft/qlib.git
git clone https://github.com/OpenBB-finance/OpenBB.git
git clone https://github.com/gerrymanoim/exchange_calendars.git
git clone https://github.com/rsheftel/pandas_market_calendars.git
git clone https://github.com/ranaroussi/quantstats.git
git clone https://github.com/PyPortfolio/PyPortfolioOpt.git
git clone https://github.com/dcajasn/Riskfolio-Lib.git
git clone https://github.com/ib-api-reloaded/ib_async.git
```

Do not copy code from incompatible-license projects into `quant_us`. Treat these
as reference material unless a dependency decision is separately reviewed.

## Architecture Recommendation

Do not rebuild the US equity system around a third-party framework.

Instead:

1. Keep `quant_us` as the production-line owner.
2. Add `exchange_calendars` first because it directly reduces US ETF calendar
   risk.
3. Add `QuantStats` only as optional report export after local ledger metrics.
4. Use `vectorbt` as a separate research accelerator for hypothesis screening.
5. Use `PyPortfolioOpt` before `Riskfolio-Lib` for portfolio construction
   prototypes.
6. Keep `Qlib` as a future ML research branch.
7. Study `NautilusTrader` and `LEAN` for architecture, but do not migrate until
   our own PIT data and ledger gates are clean.

The immediate bottleneck is still production-clean data lineage and validation,
not missing framework code.

## Adoption Status

### Landed

- `exchange_calendars` is now the preferred provider behind
  `quant_us.core.calendar.USEquityCalendar.with_holidays()`.
- `pandas_market_calendars` is available as a secondary parity provider through
  `USEquityCalendar.with_pandas_market_calendars()`.
- The calendar layer now exposes actual `last_trading_day_of_month()` and
  inclusive `trading_days_between()` helpers for rebalance and forward
  observation scheduling.
- `QuantStats` has a guarded report adapter at
  `quant_us.reports.quantstats_ledger_profile`. It only accepts
  ledger-derived `PortfolioSnapshot` and `Fill` evidence. It refuses raw price
  returns or unreconciled ledgers, so it cannot replace the canonical PnL path.
- `PyPortfolioOpt` has a research-only adapter at
  `quant_us.portfolio.optimizer.build_pypfopt_portfolio_candidate()`. It
  consumes local expected returns and covariance inputs, emits candidate
  weights only, and keeps `promotion_allowed=false`.
- `vectorbt` has a research-only screening adapter at
  `integrations.vectorbt_adapter.screen_parameter_grid`. It performs fast
  vectorized parameter screening with next-bar exposure and explicitly marks
  PnL as `not_ledger_replay`.
- `OpenBB` has a supplemental research manifest adapter at
  `integrations.openbb_adapter.research_manifest`. It records exploratory data
  requests and keeps `production_pit_clean=false`.
- NautilusTrader, LEAN, and Zipline Reloaded have a local architecture mapping
  note at `docs/integration/EXTERNAL_ENGINE_ARCHITECTURE_STUDY.md`.
- Reference clone commands are captured in
  `scripts/clone_us_equity_framework_references.py`, which defaults to dry-run
  and clones outside the repository.
- The current adoption audit is generated at
  `artifacts/us_equity_external_framework_adoption/latest/us_equity_external_framework_adoption_audit.json`
  and mirrored to
  `docs/integration/US_EQUITY_EXTERNAL_FRAMEWORK_ADOPTION_AUDIT.md`.

### Next Borrowing Tickets

1. Wire the PyPortfolioOpt adapter to the ETF research pipeline after local
   forecast/covariance artifacts are standardized. The adapter output still
   must pass local allocation and risk checks.
2. Connect vectorbt screening output to the local research trial registry, with
   an explicit `requires_ledger_replay` state before any strategy validation
   report can consume it.
3. Use OpenBB manifests to drive supplemental research panels only after each
   captured dataset is normalized through provider-neutral lineage records.
4. Convert the Nautilus/LEAN/Zipline mapping note into concrete US equity
   tickets: OMS replay audit, lifecycle manifest checklist, and ETF bundle
   registry design.

### Non-Negotiable Borrowing Boundary

External framework output is evidence input, not authority. Promotion still
requires local data lineage, local ledger PnL, cost/slippage/capacity pressure,
walk-forward or parameter stability, forward observation quality, and manual
review.
