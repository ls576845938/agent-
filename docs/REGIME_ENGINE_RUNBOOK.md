# Regime Engine Runbook

## Overview

The Regime Engine provides rule-based market regime detection, regime-aware backtest analysis, and regime report generation. All detection uses only data available at time `t` -- no lookahead bias.

## Components

### MarketRegimeDetector
Rule-based regime detection using OHLCV data. Rules are evaluated in priority order:

1. **PANIC**: Drawdown < -20% from 1-year high
2. **RECOVERY**: Recovering from >10% drawdown, price above MA200
3. **HIGH_VOL**: Volatility percentile > 80th
4. **LOW_VOL**: Volatility percentile < 20th
5. **BULL_TREND**: Price > MA200 and MA200 sloping up
6. **BEAR_TREND**: Price < MA200 and MA200 sloping down
7. **SIDEWAYS**: Default when no other rule matches

### RegimeAwareBacktest
Analyze backtest results through the lens of market regimes:
- `split_by_regime()`: Performance breakdown per regime
- `filter_by_regime()`: Compute stats using only specific regime periods
- `transition_analysis()`: Regime transition matrix and duration statistics

### RegimeReportBuilder
Generate human-readable markdown reports:
- `build_timeline()`: Chronological regime timeline
- `strategy_report()`: Regime-specific strategy performance
- `filter_recommendation()`: Suggested regime filters based on performance

## Common Operations

### Detecting Current Market Regime

```python
from quant_us.regime.detector import MarketRegimeDetector

detector = MarketRegimeDetector(data_root="data")
result = detector.current_regime("SPY")
print(f"Current regime: {result.regime}")
print(f"Confidence: {result.confidence:.2f}")
print(f"Features: {result.features}")
```

### Running Full Regime Detection

```python
import pandas as pd
from quant_us.regime.detector import MarketRegimeDetector

# Load price data
prices = pd.read_parquet("data/raw/yfinance/equity/1d/SPY/daily.parquet")

detector = MarketRegimeDetector(data_root="data")
regime_df = detector.detect(prices, start="2023-01-01", end="2024-12-31")
print(regime_df.head())
print(f"Regime distribution:")
print(regime_df["regime"].value_counts())
```

### Regime-Aware Backtest Analysis

```python
from quant_us.regime.backtest import RegimeAwareBacktest

analyzer = RegimeAwareBacktest(data_root="data")

# Split performance by regime
perf_by_regime = analyzer.split_by_regime(
    backtest_result_path="data/backtest_results/run_001",
    regime_data=regime_df,
)
for regime, perf in perf_by_regime.items():
    print(f"{regime}: Sharpe={perf['sharpe_ratio']:.2f}, "
          f"CAGR={perf['cagr_pct']:.1f}%")

# Transition analysis
transitions = analyzer.transition_analysis(regime_df)
print(f"Total transitions: {transitions['transitions']}")
print(f"Transition matrix: {transitions['transition_matrix']}")
print(f"Avg days per regime: {transitions['avg_days_per_regime']}")

# Filter by bullish regimes only
filtered = analyzer.filter_by_regime(
    backtest_result_path="data/backtest_results/run_001",
    allowed_regimes=["BULL_TREND", "RECOVERY"],
)
```

### Generating Regime Reports

```python
from quant_us.regime.report import RegimeReportBuilder

builder = RegimeReportBuilder(data_root="data")

# Timeline
timeline = builder.build_timeline(regime_df)
print(timeline)

# Strategy-specific report
report = builder.strategy_report(
    strategy_id="momentum_v3",
    regime_data=regime_df,
    regime_performance=perf_by_regime,
)
print(report)

# Get filter recommendation
recommended = builder.filter_recommendation(perf_by_regime)
print(f"Recommended regimes: {recommended}")
```

## Regime State Reference

| State | Description | Detection Rule | Typical Confidence |
|-------|-------------|----------------|-------------------|
| BULL_TREND | Uptrending market | Price > MA200, MA200 rising | 0.5-1.0 |
| BEAR_TREND | Downtrending market | Price < MA200, MA200 falling | 0.5-1.0 |
| SIDEWAYS | Range-bound market | No clear trend | 0.3 |
| HIGH_VOL | Elevated volatility | Vol percentile > 80 | 0.8-1.0 |
| LOW_VOL | Low volatility | Vol percentile < 20 | 0.8-1.0 |
| PANIC | Severe drawdown | Drawdown < -20% | 0.6-1.0 |
| RECOVERY | Bouncing from low | Drawdown < -10%, rising | 0.2-0.4 |
| UNKNOWN | Insufficient data | Missing indicators | 0.0 |

## Safety Rules

1. **No lookahead**: All rolling windows use only data available at time `t`
2. **No broker imports**: Regime modules never import `quant_us.live` or `quant_us.execution`
3. **No order submission**: Regime detection is purely informational
4. **Past-only computation**: Uses `rolling()`, `expanding()`, and `iterrows()` -- never full-dataset statistics that peek at future data

## Feature Computation Details

The `_compute_features()` method computes the following features without lookahead:

- **MA200**: 200-day simple moving average (rolling window)
- **MA200 Slope**: 20-day difference of MA200
- **Trend Strength**: Normalized distance from MA200
- **Volatility**: 20-day rolling standard deviation of daily returns, annualized
- **Volatility Percentile**: Expanding rank percentile (uses only past data)
- **Drawdown**: Current price relative to 1-year high (252-day rolling max)
- **Volume Ratio**: Current volume / 20-day average volume
