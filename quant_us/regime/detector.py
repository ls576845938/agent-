"""Rule-based market regime detector.

All rules use only data available at time t (no lookahead).
This module never imports from quant_us.live or quant_us.execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


class RegimeState:
    """Named regime identifiers used across the regime module."""

    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"
    PANIC = "PANIC"
    RECOVERY = "RECOVERY"
    LIQUIDITY_STRESS = "LIQUIDITY_STRESS"
    UNKNOWN = "UNKNOWN"

    _ALL = frozenset({
        BULL_TREND, BEAR_TREND, SIDEWAYS, HIGH_VOL, LOW_VOL,
        PANIC, RECOVERY, LIQUIDITY_STRESS, UNKNOWN,
    })

    @classmethod
    def is_valid(cls, regime: str) -> bool:
        return regime in cls._ALL


@dataclass
class RegimeResult:
    """Single-point regime classification output."""

    date: str
    regime: str
    confidence: float = 0.0
    features: dict[str, float] = field(default_factory=dict)


class MarketRegimeDetector:
    """Rule-based regime detection using OHLCV data.

    Rules are evaluated in priority order:

    1. Drawdown < -20% from 1Y high                           -> PANIC
    2. Recovering from >10% drawdown (rising, above MA200)    -> RECOVERY
    3. Volatility percentile > 80th                            -> HIGH_VOL
    4. Volatility percentile < 20th                            -> LOW_VOL
    5. Price > MA200 AND MA200 sloping up                     -> BULL_TREND
    6. Price < MA200 AND MA200 sloping down                   -> BEAR_TREND
    7. Otherwise                                               -> SIDEWAYS

    All rules use only data available at time t.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.ma_period: int = 200
        self.vol_lookback: int = 20
        self.vol_high_percentile: int = 80
        self.vol_low_percentile: int = 20
        self.drawdown_panic_threshold: float = -0.20
        self.data_root: str = data_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        prices: pd.DataFrame,
        volume: pd.DataFrame | None = None,
        start: str = "",
        end: str = "",
    ) -> pd.DataFrame:
        """Run full regime detection on a price DataFrame.

        Parameters
        ----------
        prices : pd.DataFrame
            Must contain columns: ``timestamp_utc``, ``close``.
            May also contain ``open``, ``high``, ``low``, ``volume``.
        volume : pd.DataFrame, optional
            Not used directly (volume is expected inside *prices*).
        start : str, optional
            ISO date filter (inclusive).
        end : str, optional
            ISO date filter (inclusive).

        Returns
        -------
        pd.DataFrame
            Columns: date, regime, confidence, trend_strength, vol_percentile,
            drawdown_pct, volume_ratio, vix_proxy, breadth_pct.
        """
        features = self._compute_features(prices)
        if start:
            features = features[features["date"] >= start]
        if end:
            features = features[features["date"] <= end]

        records: list[dict[str, Any]] = []
        for _, row in features.iterrows():
            regime, confidence = self._classify_regime(row)
            records.append({
                "date": row["date"],
                "regime": regime,
                "confidence": round(confidence, 4),
                "trend_strength": round(row.get("trend_strength", 0.0), 6),
                "vol_percentile": round(row.get("vol_percentile", 0.0), 2),
                "drawdown_pct": round(row.get("drawdown_pct", 0.0), 6),
                "volume_ratio": round(row.get("volume_ratio", 1.0), 4),
                "vix_proxy": round(row.get("vix_proxy", 0.0), 4),
                "breadth_pct": round(row.get("breadth_pct", 0.0), 2),
            })

        out = pd.DataFrame(records)
        if out.empty:
            out = pd.DataFrame(
                columns=[
                    "date", "regime", "confidence", "trend_strength",
                    "vol_percentile", "drawdown_pct", "volume_ratio",
                    "vix_proxy", "breadth_pct",
                ]
            )
        return out

    def detect_all(self, symbol: str = "SPY") -> pd.DataFrame:
        """Full regime history for a symbol, loading data from parquet store.

        Parameters
        ----------
        symbol : str
            Ticker symbol.

        Returns
        -------
        pd.DataFrame
            Same schema as :meth:`detect`.
        """
        prices = self._load_prices(symbol)
        if prices.empty:
            return pd.DataFrame()
        return self.detect(prices)

    def current_regime(self, symbol: str = "SPY") -> RegimeResult:
        """Get the most recent regime classification for a symbol.

        Parameters
        ----------
        symbol : str
            Ticker symbol.

        Returns
        -------
        RegimeResult
        """
        prices = self._load_prices(symbol)
        if prices.empty:
            return RegimeResult(date="", regime=RegimeState.UNKNOWN, confidence=0.0)

        full = self._compute_features(prices)
        if full.empty:
            return RegimeResult(date="", regime=RegimeState.UNKNOWN, confidence=0.0)

        latest = full.iloc[-1]
        regime, confidence = self._classify_regime(latest)
        return RegimeResult(
            date=str(latest["date"]),
            regime=regime,
            confidence=round(confidence, 4),
            features={
                "trend_strength": round(latest.get("trend_strength", 0.0), 6),
                "vol_percentile": round(latest.get("vol_percentile", 0.0), 2),
                "drawdown_pct": round(latest.get("drawdown_pct", 0.0), 6),
                "volume_ratio": round(latest.get("volume_ratio", 1.0), 4),
            },
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_prices(self, symbol: str) -> pd.DataFrame:
        """Load daily OHLCV data for *symbol* from the parquet bar store."""
        from quant_us.data.storage.parquet_store import ParquetBarStore

        store = ParquetBarStore(Path(self.data_root) / "raw")
        return store.read_bars(
            vendor="yfinance",
            asset_class="equity",
            bar_size="1d",
            symbol=symbol,
        )

    # ------------------------------------------------------------------
    # Feature computation  (no lookahead)
    # ------------------------------------------------------------------

    def _compute_features(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Compute regime-relevant features from price data.

        All rolling windows use only data available at time t.
        """
        if prices.empty:
            return pd.DataFrame()

        df = prices.copy()
        df = df.sort_values("timestamp_utc").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["timestamp_utc"]).dt.strftime("%Y-%m-%d")

        close = df["close"].astype(float)

        # --- trend features ---
        df["ma200"] = close.rolling(self.ma_period, min_periods=self.ma_period).mean()
        # MA200 slope over 20 trading days (positive = rising)
        df["ma200_slope"] = df["ma200"].diff(20)

        # Trend strength: normalised distance from MA200
        ma200 = df["ma200"].fillna(close)
        df["trend_strength"] = (close - ma200).abs() / close

        # --- volatility features ---
        df["returns"] = close.pct_change()
        df["returns_10d"] = close.pct_change(10)
        df["volatility"] = (
            df["returns"]
            .rolling(self.vol_lookback, min_periods=self.vol_lookback)
            .std()
            * (252.0**0.5)
        )
        # Volatility percentile — expanding rank over valid (non-NaN) values only.
        # No bfill/ffill so that early rows with insufficient history get NaN
        # and are excluded naturally by the downstream dropna.
        df["vol_percentile"] = df["volatility"].expanding().rank(pct=True) * 100.0

        # --- drawdown features ---
        df["high_1y"] = close.rolling(252, min_periods=60).max()
        df["drawdown_pct"] = close / df["high_1y"] - 1.0

        # --- volume features ---
        if "volume" in df.columns:
            vol_series = df["volume"].astype(float)
            vol_sma = vol_series.rolling(20, min_periods=5).mean()
            df["volume_ratio"] = (vol_series / vol_sma).fillna(1.0)
        else:
            df["volume_ratio"] = 1.0

        # --- breadth / VIX proxies (placeholder, require multi-symbol or VIX data) ---
        df["breadth_pct"] = 0.0
        df["vix_proxy"] = 0.0

        # Drop rows where core indicators are still NaN
        df = df.dropna(subset=["drawdown_pct", "vol_percentile"]).reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    # Classification rules  (priority order)
    # ------------------------------------------------------------------

    def _classify_regime(self, row: pd.Series) -> tuple[str, float]:
        """Classify a single feature-row into (regime, confidence)."""
        drawdown = float(row.get("drawdown_pct", 0.0))
        vol_pct = float(row.get("vol_percentile", 50.0))
        close = float(row.get("close", 0.0))
        ma200 = float(row.get("ma200"))
        ma200_slope = float(row.get("ma200_slope", 0.0))
        trend_strength = float(row.get("trend_strength", 0.0))
        ten_day_return = float(row.get("returns_10d", 0.0))

        # Insufficient data
        if pd.isna(ma200) or pd.isna(drawdown) or pd.isna(vol_pct):
            return RegimeState.UNKNOWN, 0.0

        # 1. PANIC — drawdown deeper than threshold
        if drawdown < self.drawdown_panic_threshold:
            conf = min(1.0, abs(drawdown) * 3.0)
            return RegimeState.PANIC, round(conf, 4)

        # 2. RECOVERY — bounced from significant drawdown
        if drawdown < -0.10 and ten_day_return > 0.02 and close > ma200:
            conf = min(1.0, abs(drawdown) * 2.0)
            return RegimeState.RECOVERY, round(conf, 4)

        # 3. HIGH_VOL
        if vol_pct > self.vol_high_percentile:
            conf = min(1.0, vol_pct / 100.0)
            return RegimeState.HIGH_VOL, round(conf, 4)

        # 4. LOW_VOL
        if vol_pct < self.vol_low_percentile:
            conf = min(1.0, (100.0 - vol_pct) / 100.0)
            return RegimeState.LOW_VOL, round(conf, 4)

        # 5. BULL_TREND
        if close > ma200 and ma200_slope > 0:
            conf = min(1.0, trend_strength * 5.0)
            return RegimeState.BULL_TREND, round(conf, 4)

        # 6. BEAR_TREND
        if close < ma200 and ma200_slope < 0:
            conf = min(1.0, trend_strength * 5.0)
            return RegimeState.BEAR_TREND, round(conf, 4)

        # 7. SIDEWAYS (default)
        return RegimeState.SIDEWAYS, 0.3
