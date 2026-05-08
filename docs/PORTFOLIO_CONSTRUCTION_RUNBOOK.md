# Portfolio Construction Runbook

## Overview

The Portfolio Construction module builds multi-strategy portfolios from candidate strategy scorecards. It provides allocation methods, exposure management, backtesting, and performance scorecards -- all without any broker or execution access.

## Components

### PortfolioConstructionEngine
Top-level entry point for constructing and rebalancing portfolios:
- `construct()`: Build portfolio from candidate strategy scorecards
- `rebalance()`: Rebalance existing portfolio toward target weights
- `save_target()` / `load_target()`: Persist/load portfolio targets as JSON

### CapitalAllocator
Strategy-level capital allocation with multiple methods:
- `EQUAL_WEIGHT`: Equal weight across all strategies
- `INVERSE_VOL`: Weight inversely proportional to volatility
- `RISK_PARITY`: Equal risk contribution (simplified, uses inverse vol as proxy without full covariance)
- `VOL_TARGET`: Scale to target portfolio volatility
- `DRAWDOWN_ADJUSTED`: Reduce weight for strategies with large drawdowns

### ExposureManager
Portfolio-level exposure analysis and constraint checking:
- `analyze()`: Compute gross/net exposure, single-symbol, sector, strategy exposures
- `check_limits()`: Validate against constraint limits
- Returns `ExposureReport` with diversification ratio

### PortfolioBacktestRunner
Simulate portfolio-level performance by combining strategy return series:
- `run()`: Compute CAGR, Sharpe, max drawdown, attribution
- `compute_attribution()`: Strategy-level contribution analysis
- No order submission or broker interaction

### PortfolioScorecardBuilder
Aggregated performance summary for a constructed portfolio:
- Weighted average CAGR, Sharpe, max drawdown
- Strategy contributions and marginal risk
- Capital efficiency and diversification ratio
- Markdown report generation

## Common Operations

### Constructing a Portfolio

```python
from quant_us.portfolio.construction.engine import (
    PortfolioConfig,
    PortfolioConstructionEngine,
)

engine = PortfolioConstructionEngine(data_root="data")

config = PortfolioConfig(
    portfolio_id="momentum_value_combo",
    capital=500000.0,
    max_single_weight=0.20,
    max_sector_weight=0.35,
    target_volatility=0.12,
)

candidates = [
    {
        "id": "momentum_v3",
        "volatility": 0.18,
        "expected_return": 0.15,
        "holdings": {"AAPL": 0.3, "MSFT": 0.3, "GOOGL": 0.4},
    },
    {
        "id": "value_v2",
        "volatility": 0.12,
        "expected_return": 0.10,
        "holdings": {"XOM": 0.5, "JPM": 0.3, "WMT": 0.2},
    },
]

target = engine.construct(config, candidates)
print(f"Strategy weights: {target.strategy_weights}")
print(f"Expected return: {target.expected_return:.2%}")
print(f"Expected vol: {target.expected_volatility:.2%}")
engine.save_target(target)
```

### Rebalancing

```python
# Rebalance with same config
new_target = engine.rebalance(
    portfolio_id="momentum_value_combo",
    current_weights={"momentum_v3": 0.55, "value_v2": 0.45},
    candidate_scorecards=candidates,
    config=config,
)
```

### Using Different Allocation Methods

```python
from quant_us.portfolio.construction.allocator import CapitalAllocator, AllocationMethod

allocator = CapitalAllocator()

# Equal weight
weights = allocator.allocate(candidates, AllocationMethod.EQUAL_WEIGHT)

# Inverse volatility
weights = allocator.allocate(candidates, AllocationMethod.INVERSE_VOL)

# With constraints
weights = allocator.allocate(
    candidates,
    AllocationMethod.INVERSE_VOL,
    constraints={"max_single_weight": 0.15},
)
```

### Checking Portfolio Exposure

```python
from quant_us.portfolio.construction.exposure import ExposureManager

mgr = ExposureManager()
report = mgr.analyze(
    positions={"AAPL": 50000, "MSFT": 30000, "XOM": 20000},
    prices={"AAPL": 150, "MSFT": 300, "XOM": 80},
    sectors={"AAPL": "tech", "MSFT": "tech", "XOM": "energy"},
)

print(f"Gross exposure: {report.gross_exposure:.2f}")
print(f"Net exposure: {report.net_exposure:.2f}")

# Check against limits
limits = {"max_gross_exposure": 1.0, "max_single_weight": 0.25}
passed, violations = mgr.check_limits(report, limits)
if not passed:
    print("Violations:", violations)
```

### Running a Portfolio Backtest

```python
from quant_us.portfolio.construction.backtest import PortfolioBacktestRunner

runner = PortfolioBacktestRunner(data_root="data")
result = runner.run(
    portfolio_id="my_portfolio",
    start="2024-01-01",
    end="2024-12-31",
    strategy_returns={
        "momentum_v3": [0.01] * 252,  # daily returns
        "value_v2": [0.005] * 252,
    },
    weights={"momentum_v3": 0.6, "value_v2": 0.4},
)
print(f"CAGR: {result.cagr:.2%}")
print(f"Sharpe: {result.sharpe:.2f}")
```

### Building a Portfolio Scorecard

```python
from quant_us.portfolio.construction.scorecard import PortfolioScorecardBuilder

builder = PortfolioScorecardBuilder(data_root="data")
scorecard = builder.build(
    portfolio_id="my_portfolio",
    strategy_scorecards=[
        {"id": "mom", "cagr": 0.12, "sharpe": 1.5, "max_drawdown": 0.08, "volatility": 0.18},
        {"id": "val", "cagr": 0.08, "sharpe": 1.0, "max_drawdown": 0.12, "volatility": 0.14},
    ],
    portfolio_weights={"mom": 0.6, "val": 0.4},
)
print(PortfolioScorecardBuilder.to_markdown(scorecard))
```

## Allocation Method Details

### Equal Weight
- Simplest method: `1/n` per strategy
- No risk or return assumptions
- Good baseline for comparison

### Inverse Volatility
- Weight = `1/volatility`, normalized to sum to 1
- Lower volatility strategies get higher allocation
- Reduces portfolio volatility vs equal weight

### Risk Parity
- Equal risk contribution from each strategy
- Simplified version uses inverse vol as proxy
- Full implementation requires covariance matrix

### Volatility Targeting
- Scale entire portfolio to target volatility level
- `scale = target_vol / current_portfolio_vol`
- Useful for maintaining consistent risk level

### Drawdown Adjusted
- Penalizes strategies with recent large drawdowns
- `penalty = 1.0 - (drawdown / max_drawdown) * 0.5`
- Max penalty is 50% reduction

## Safety Rules

1. **No broker imports**: Portfolio construction modules never import from `quant_us.live` or `quant_us.execution`
2. **No order submission**: PortfolioTarget contains allocation weights only, never orders
3. **All methods normalize**: All allocation results are normalized to sum to 1.0 (or less if constrained)
4. **Weight caps enforced**: `max_single_weight` is always applied after allocation

## File Locations

- Portfolio targets: `data/portfolio/targets/<portfolio_id>.json`
- Portfolio backtest returns: `data/portfolio/returns/<portfolio_id>.json`
