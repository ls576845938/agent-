# Factor Research Runbook

## Overview

The Factor Research module provides tools for defining, computing, and evaluating alpha factors. It includes a factor library with built-in factors, a feature pipeline for batch computation, and evaluation metrics for factor quality assessment.

## Components

### FactorLibrary
Registry of defined factors with built-in defaults:
- `momentum_60d`: 60-day momentum (sector-neutralized)
- `momentum_20d`: 20-day momentum (sector-neutralized)
- `momentum_120d`: 120-day momentum (sector-neutralized)
- `volatility_20d`: 20-day realized volatility
- `volatility_60d`: 60-day realized volatility
- `liquidity_20d`: 20-day average dollar volume
- `reversal_1d`: 1-day short-term reversal
- `volume_20d`: 20-day volume trend

### FeaturePipeline
Computes bar-level factors from OHLCV data:
- Momentum score (rolling)
- Realized volatility (rolling)
- Average dollar volume (rolling)
- Outputs to parquet via ParquetFeatureStore

### Factor Evaluation Metrics

**Information Coefficient (IC)**: Pearson correlation between factor values and forward returns. Measures linear predictive power.

**Rank IC (Spearman)**: Spearman rank correlation between factor values and forward returns. More robust to outliers.

**IC Information Ratio (ICIR)**: Mean IC divided by IC standard deviation. Measures consistency of predictive power.

**Quantile Returns**: Sort stocks into quantiles by factor value, compute mean return per quantile. Tests monotonicity and spread.

## Common Operations

### Registering and Using the Factor Library

```python
from quant_us.factors.definition import FactorDefinition, FactorLibrary

lib = FactorLibrary()

# List all built-in factors
for f in lib.list_all():
    print(f"{f.factor_id}: {f.name} ({f.category})")

# Get a specific factor
momentum = lib.get("momentum_60d")
print(f"Lookback: {momentum.lookback}")
print(f"Neutralization: {momentum.neutralization}")

# Register a custom factor
custom = FactorDefinition(
    factor_id="custom_macd",
    name="MACD Signal",
    category="trend",
    lookback=26,
    formula="ema(12) - ema(26)",
    required_fields=["close"],
    neutralization="none",
)
lib.register(custom)

# List by category
vol_factors = lib.list_by_category("volatility")
```

### Computing Bar-Level Factors

```python
import pandas as pd
from quant_us.factors.feature_pipeline import FeaturePipeline

pipeline = FeaturePipeline(feature_root="data/features")

# Load OHLCV data
bars = pd.read_parquet("data/raw/bars.parquet")

# Compute factors for all symbols
result = pipeline.build_bar_factors(
    bars=bars,
    universe="default",
    version="v1",
)
print(f"Wrote {result.rows_written} rows to {result.files_written}")
```

### Evaluating Factor Performance (IC Analysis)

```python
import pandas as pd
import numpy as np

def compute_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
    """Compute Information Coefficient (Pearson correlation)."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(combined) < 5:
        return 0.0
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))

def compute_rank_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
    """Compute Rank IC (Spearman correlation)."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(combined) < 5:
        return 0.0
    return float(combined.iloc[:, 0].corr(
        combined.iloc[:, 1], method="spearman"
    ))

def compute_icir(ic_series: pd.Series) -> float:
    """Compute IC Information Ratio."""
    if len(ic_series) < 2:
        return 0.0
    return float(ic_series.mean() / ic_series.std()) if ic_series.std() > 0 else 0.0

# Example usage
factor_values = pd.Series(np.random.randn(200))
returns = pd.Series(factor_values * 0.1 + np.random.randn(200) * 0.01)

ic = compute_ic(factor_values, returns)
rank_ic = compute_rank_ic(factor_values, returns)
print(f"IC: {ic:.4f}, Rank IC: {rank_ic:.4f}")
```

### Quantile Return Analysis

```python
def compute_quantile_returns(
    factor: pd.Series,
    forward_returns: pd.Series,
    n_quantiles: int = 5,
) -> dict[int, float]:
    """Compute mean forward return per factor quantile."""
    combined = pd.concat([factor, forward_returns], axis=1).dropna()
    combined.columns = ["factor", "return"]
    combined["quantile"] = pd.qcut(
        combined["factor"], n_quantiles, labels=False, duplicates="drop"
    )
    return {
        q: group["return"].mean()
        for q, group in combined.groupby("quantile")
    }

quantiles = compute_quantile_returns(factor_values, returns)
for q, ret in sorted(quantiles.items()):
    print(f"Q{q}: {ret:.4f}")

# Long-short spread
spread = quantiles[max(quantiles)] - quantiles[min(quantiles)]
print(f"Long-Short Spread: {spread:.4f}")
```

### Factor Recommendation Logic

```python
def recommend_factor(ic: float, icir: float, quantile_monotonic: bool) -> str:
    """Recommendation: REJECT | RESEARCH_MORE | USABLE | STRONG"""
    if abs(ic) < 0.02:
        return "REJECT"
    if icir < 0.5:
        return "RESEARCH_MORE"
    if not quantile_monotonic:
        return "RESEARCH_MORE"
    if abs(ic) > 0.1 and icir > 1.0:
        return "STRONG"
    return "USABLE"
```

## Safety Rules

1. **No lookahead bias**: All factor computations use rolling windows (never shift(-1) or bfill)
2. **No broker imports**: Factor modules do not import from `quant_us.live` or `quant_us.execution`
3. **No future data**: Only data available at time `t` is used for computation
4. **Dataset time-split**: ML datasets enforce train/validation/test splits with chronological ordering

## Factor Categories

| Category | Factors | Typical Use |
|----------|---------|-------------|
| momentum | momentum_20d, momentum_60d, momentum_120d | Trend following |
| reversal | reversal_1d | Mean reversion |
| volatility | volatility_20d, volatility_60d | Risk estimation |
| liquidity | liquidity_20d | Capacity estimation |
| volume | volume_20d | Volume analysis |
| trend | (custom) | Trend detection |
| quality | (custom) | Fundamental quality |
| macro | (custom) | Macroeconomic factors |
