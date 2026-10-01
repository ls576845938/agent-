from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


MACRO_COLUMNS = ("WALCL", "WTREGEN", "RRPONTSYD", "BAMLC0A0CM", "DGS10", "DGS2")


@dataclass(frozen=True)
class UsEtfAlphaSignals:
    """Alpha-only outputs for the US ETF rotation strategy."""

    cross_sectional_momentum: pd.DataFrame
    absolute_trend: pd.DataFrame
    macro_regime: pd.Series
    yield_curve_inverted: pd.Series
    defensive_momentum: pd.DataFrame
    realized_volatility: pd.DataFrame
    asset_returns: pd.DataFrame
    beta: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)


def generate_us_etf_rotation_alpha_signals(
    prices: pd.DataFrame,
    macro_data: pd.DataFrame,
    cfg: Any,
) -> UsEtfAlphaSignals:
    """Generate signals without deciding target weights or simulated fills."""

    _validate_price_columns(prices, cfg)
    all_assets = list(cfg.required_symbols())
    daily_ret = prices[all_assets].pct_change(fill_method=None)
    market_ret = daily_ret[cfg.benchmark]
    rolling_mkt_var = market_ret.rolling(cfg.beta_window).var()

    beta_df = pd.DataFrame(index=prices.index, columns=all_assets, dtype=float)
    for ticker in all_assets:
        rolling_cov = daily_ret[ticker].rolling(cfg.beta_window).cov(market_ret)
        beta_df[ticker] = rolling_cov / rolling_mkt_var
    beta_df = beta_df.ffill().fillna(0.0)

    idio_ret = pd.DataFrame(index=prices.index, columns=cfg.offensive_assets, dtype=float)
    for ticker in cfg.offensive_assets:
        idio_ret[ticker] = daily_ret[ticker] - beta_df[ticker].shift(1) * market_ret
    idio_ret = idio_ret.fillna(daily_ret[list(cfg.offensive_assets)])
    idio_log_ret = np.log1p(idio_ret.clip(lower=-0.9999))

    momentum = pd.DataFrame(0.0, index=prices.index, columns=cfg.offensive_assets)
    for lookback, weight in zip(cfg.mom_lookbacks, cfg.mom_weights):
        ret_lookback = np.expm1(idio_log_ret.rolling(lookback).sum())
        vol_lookback = idio_ret.rolling(lookback).std() * np.sqrt(252)
        risk_adjusted_ret = ret_lookback / vol_lookback.replace(0.0, 0.0001)
        momentum += risk_adjusted_ret * weight

    short_vol = idio_ret.rolling(cfg.vol_short_window).std() * np.sqrt(252)
    long_vol = idio_ret.rolling(cfg.vol_long_window).std() * np.sqrt(252)
    vol_ratio = short_vol / long_vol.replace(0.0, 0.0001)
    vol_penalty = pd.DataFrame(
        np.where(
            vol_ratio > cfg.vol_expansion_threshold,
            cfg.vol_expansion_threshold / vol_ratio,
            1.0,
        ),
        index=prices.index,
        columns=cfg.offensive_assets,
    )
    momentum = momentum.where(momentum <= 0.0, momentum * vol_penalty)

    absolute_trend = prices[list(cfg.offensive_assets)] > prices[list(cfg.offensive_assets)].rolling(200).mean()
    defensive_momentum = prices[list(cfg.defense_assets)].pct_change(cfg.defense_mom_window, fill_method=None)
    macro_regime, yield_curve_inverted, macro_status = _build_macro_regime(prices, macro_data, cfg)
    volatility = daily_ret[all_assets].rolling(cfg.vol_window).std()
    return UsEtfAlphaSignals(
        cross_sectional_momentum=momentum,
        absolute_trend=absolute_trend,
        macro_regime=macro_regime,
        yield_curve_inverted=yield_curve_inverted,
        defensive_momentum=defensive_momentum,
        realized_volatility=volatility,
        asset_returns=daily_ret,
        beta=beta_df,
        diagnostics={
            "macro_status": macro_status,
            "layer": "alpha_signal",
            "outputs": [
                "cross_sectional_momentum",
                "absolute_trend",
                "macro_regime",
                "defensive_momentum",
                "realized_volatility",
            ],
        },
    )


def _build_macro_regime(
    prices: pd.DataFrame,
    macro_data: pd.DataFrame,
    cfg: Any,
) -> tuple[pd.Series, pd.Series, str]:
    if macro_data.empty or any(column not in macro_data.columns for column in MACRO_COLUMNS):
        return (
            pd.Series(1.0, index=prices.index),
            pd.Series(False, index=prices.index),
            "missing_neutral_regime_used",
        )
    macro = macro_data.copy()
    macro.index = pd.to_datetime(macro.index, utc=True)
    common_index = prices.index.intersection(macro.index)
    if common_index.empty:
        return (
            pd.Series(1.0, index=prices.index),
            pd.Series(False, index=prices.index),
            "no_common_macro_dates_neutral_regime_used",
        )
    macro_df = macro.shift(cfg.macro_lag_days).loc[common_index].ffill()
    spy_prices = prices.loc[common_index, cfg.benchmark]
    net_liquidity = macro_df["WALCL"] - macro_df["WTREGEN"] - macro_df["RRPONTSYD"]
    sig_liquidity = (net_liquidity > net_liquidity.rolling(40).mean()).astype(int)
    spread = macro_df["BAMLC0A0CM"]
    sig_credit = (spread < spread.rolling(20).mean()).astype(int)
    sig_trend = (spy_prices > spy_prices.rolling(200).mean()).astype(int)
    macro_regime_aligned = (
        sig_liquidity * cfg.liquidity_weight
        + sig_credit * cfg.credit_weight
        + sig_trend * cfg.trend_weight
    )
    dgs10 = macro_df["DGS10"]
    rate_change = dgs10.diff(cfg.rate_shock_window)
    rate_shock_penalty = np.where(
        rate_change > cfg.rate_shock_threshold,
        cfg.rate_shock_penalty,
        1.0,
    )
    rate_shock = pd.Series(rate_shock_penalty, index=macro_df.index).reindex(prices.index).ffill().fillna(1.0)
    macro_regime = macro_regime_aligned.reindex(prices.index).ffill().fillna(1.0) * rate_shock
    yield_curve_inverted = ((dgs10 - macro_df["DGS2"]) < 0).reindex(prices.index).ffill().fillna(False)
    return macro_regime, yield_curve_inverted.astype(bool), "available_lagged"


def _validate_price_columns(prices: pd.DataFrame, cfg: Any) -> None:
    missing = [symbol for symbol in cfg.required_symbols() if symbol not in prices.columns]
    if missing:
        raise ValueError(f"price matrix missing required symbols: {missing}")
