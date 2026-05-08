"""Regime detection and regime-aware backtest analysis for QuantStation.

Regime detection is purely informational — it never places orders or
interacts with live/execution modules.
"""

from quant_us.regime.detector import MarketRegimeDetector, RegimeResult, RegimeState
from quant_us.regime.store import RegimeFeatureStore, RegimeRecord
from quant_us.regime.backtest import RegimeAwareBacktest, RegimeBacktestResult
from quant_us.regime.report import RegimeReportBuilder

__all__ = [
    "MarketRegimeDetector",
    "RegimeResult",
    "RegimeState",
    "RegimeFeatureStore",
    "RegimeRecord",
    "RegimeAwareBacktest",
    "RegimeBacktestResult",
    "RegimeReportBuilder",
]
