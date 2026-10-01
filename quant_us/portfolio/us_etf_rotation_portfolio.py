from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quant_us.signals.us_etf_rotation_alpha import UsEtfAlphaSignals


@dataclass(frozen=True)
class UsEtfPortfolioTargets:
    """Portfolio-construction outputs before execution simulation."""

    rebalance_weights: pd.DataFrame
    daily_target_weights: pd.DataFrame
    equity_exposure: pd.Series
    turnover: pd.Series
    reasons: dict[str, str]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def construct_us_etf_rotation_portfolio(
    prices: pd.DataFrame,
    signals: UsEtfAlphaSignals,
    cfg: Any,
) -> UsEtfPortfolioTargets:
    """Convert alpha signals into target weights without applying execution costs."""

    rebalance_dates = _last_trading_dates_by_month(prices.index)
    weight_columns = list(_unique([*cfg.offensive_assets, *cfg.defense_assets]))
    weights_monthly = pd.DataFrame(0.0, index=rebalance_dates, columns=weight_columns)
    reasons: dict[str, str] = {}
    asset_rets = signals.asset_returns
    volatility = signals.realized_volatility

    for date in rebalance_dates:
        current_macro_score = float(signals.macro_regime.loc[date])
        is_inverted = bool(signals.yield_curve_inverted.loc[date])
        current_target_vol = cfg.target_vol_inverted if is_inverted else cfg.target_vol
        defense_allocations = _defense_allocations(
            date,
            asset_rets,
            volatility,
            signals.defensive_momentum,
            cfg,
        )
        base_equity_weight = _base_equity_weight(current_macro_score, cfg)
        weights_monthly.loc[date] = 0.0

        if base_equity_weight <= 0.0:
            for asset in cfg.defense_assets:
                weights_monthly.loc[date, asset] += defense_allocations.get(asset, 0.0)
            reasons[str(date)] = "macro_risk_off_defense_only"
            continue

        selected = _select_offensive_assets(
            date,
            asset_rets,
            signals.cross_sectional_momentum,
            signals.absolute_trend,
            cfg,
        )
        if not selected:
            for asset in cfg.defense_assets:
                weights_monthly.loc[date, asset] += defense_allocations.get(asset, 0.0)
            reasons[str(date)] = "no_positive_trend_defense_only"
            continue

        selected_vols = volatility.loc[date, selected].replace(0.0, 0.0001)
        inv_vols = 1.0 / selected_vols
        risk_parity_weights = inv_vols / inv_vols.sum()
        hist_rets = asset_rets.loc[:date, selected].tail(cfg.cov_lookback)
        vol_scaler = 1.0
        if len(hist_rets) > 10:
            cov_matrix = hist_rets.cov() * 252
            port_variance = float(np.dot(risk_parity_weights.values.T, np.dot(cov_matrix.values, risk_parity_weights.values)))
            expected_vol = float(np.sqrt(max(port_variance, 0.0)))
            vol_scaler = min(1.0, current_target_vol / expected_vol) if expected_vol > 0 else 1.0

        final_equity_weight = float(base_equity_weight * vol_scaler)
        for asset in selected:
            weights_monthly.loc[date, asset] += float(risk_parity_weights[asset] * final_equity_weight)

        defense_total_weight = 1.0 - final_equity_weight
        for asset in cfg.defense_assets:
            weights_monthly.loc[date, asset] += defense_allocations.get(asset, 0.0) * defense_total_weight
        reasons[str(date)] = "offensive_rotation_with_defense_residual"

    daily_weights = weights_monthly.reindex(prices.index).ffill().shift(1).fillna(0.0)
    turnover = daily_weights.diff().abs().sum(axis=1).fillna(0.0)
    equity_exposure = daily_weights[list(cfg.offensive_assets)].sum(axis=1)
    reason_counts: dict[str, int] = {}
    for reason in reasons.values():
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return UsEtfPortfolioTargets(
        rebalance_weights=weights_monthly,
        daily_target_weights=daily_weights,
        equity_exposure=equity_exposure,
        turnover=turnover,
        reasons=reasons,
        diagnostics={
            "layer": "portfolio_construction",
            "rebalance_count": int(len(weights_monthly)),
            "rebalance_reason_counts": reason_counts,
            "latest_rebalance_reasons": dict(list(reasons.items())[-12:]),
            "t_plus_1_execution": _check_t_plus_1(weights_monthly, daily_weights),
            "outputs": [
                "rebalance_weights",
                "daily_target_weights",
                "equity_exposure",
                "turnover",
            ],
        },
    )


def _defense_allocations(
    date: pd.Timestamp,
    asset_rets: pd.DataFrame,
    volatility: pd.DataFrame,
    defense_mom: pd.DataFrame,
    cfg: Any,
) -> dict[str, float]:
    allocations = {asset: 0.0 for asset in cfg.defense_assets}
    risk_def_assets = [asset for asset in cfg.defense_assets if asset != "SHV"]
    current_def_mom = defense_mom.loc[date, risk_def_assets]
    shv_mom = float(defense_mom.loc[date, "SHV"]) if not pd.isna(defense_mom.loc[date, "SHV"]) else 0.0
    if current_def_mom.isna().all():
        allocations["SHV"] = 1.0
        return allocations
    valid_def = [
        asset
        for asset in risk_def_assets
        if current_def_mom[asset] > 0 and current_def_mom[asset] > shv_mom
    ]
    if not valid_def:
        allocations["SHV"] = 1.0
        return allocations
    def_vols = volatility.loc[date, valid_def].replace(0.0, 0.0001)
    risk_adj_mom = current_def_mom[valid_def] / def_vols
    raw_weights = risk_adj_mom / risk_adj_mom.sum()
    scale_factor = 1.0
    hist_rets = asset_rets.loc[:date, valid_def].tail(cfg.cov_lookback)
    if len(hist_rets) > 10:
        cov = hist_rets.cov() * 252
        variance = float(np.dot(raw_weights.values.T, np.dot(cov.values, raw_weights.values)))
        expected_vol = float(np.sqrt(max(variance, 0.0)))
        scale_factor = cfg.defense_target_vol / expected_vol if expected_vol > cfg.defense_target_vol else 1.0
    for asset in valid_def:
        allocations[asset] = float(raw_weights[asset] * scale_factor)
    allocations["SHV"] = max(0.0, 1.0 - sum(allocations.values()))
    return allocations


def _select_offensive_assets(
    date: pd.Timestamp,
    asset_rets: pd.DataFrame,
    mom_score: pd.DataFrame,
    trend_filter: pd.DataFrame,
    cfg: Any,
) -> list[str]:
    current_mom = mom_score.loc[date]
    current_trend = trend_filter.loc[date]
    valid_mom = current_mom.where(current_trend, -999.0)
    valid_assets = valid_mom.sort_values(ascending=False)
    valid_assets = valid_assets[valid_assets != -999.0].index.tolist()
    selected: list[str] = []
    corr_hist = asset_rets.loc[:date, valid_assets].tail(cfg.cov_lookback)
    current_corr = corr_hist.corr() if len(corr_hist) > 10 else pd.DataFrame()
    for asset in valid_assets:
        if not selected:
            selected.append(asset)
        else:
            too_correlated = False
            if not current_corr.empty:
                for picked in selected:
                    if float(current_corr.loc[asset, picked]) > 0.80:
                        too_correlated = True
                        break
            if not too_correlated:
                selected.append(asset)
        if len(selected) >= cfg.top_n:
            break
    if len(selected) < cfg.top_n:
        for asset in valid_assets:
            if asset not in selected:
                selected.append(asset)
            if len(selected) >= cfg.top_n:
                break
    return selected


def _base_equity_weight(current_macro_score: float, cfg: Any) -> float:
    mode = cfg.macro_mode.upper()
    if mode == "STEP":
        return 1.0 if current_macro_score >= cfg.macro_threshold else 0.0
    if mode == "CONTINUOUS":
        if current_macro_score >= cfg.macro_cont_upper:
            return 1.0
        if current_macro_score <= cfg.macro_cont_lower:
            return 0.0
        return (current_macro_score - cfg.macro_cont_lower) / (cfg.macro_cont_upper - cfg.macro_cont_lower)
    return float(current_macro_score)


def _last_trading_dates_by_month(index: pd.Index) -> pd.DatetimeIndex:
    ts_index = pd.DatetimeIndex(index).sort_values()
    period_index = ts_index.tz_convert(None).to_period("M") if ts_index.tz is not None else ts_index.to_period("M")
    dates = [group.iloc[-1] for _, group in pd.Series(ts_index, index=ts_index).groupby(period_index)]
    return pd.DatetimeIndex(dates)


def _check_t_plus_1(weights_monthly: pd.DataFrame, daily_weights: pd.DataFrame) -> bool:
    for rebalance_date in weights_monthly.index:
        if rebalance_date not in daily_weights.index:
            continue
        if not np.allclose(daily_weights.loc[rebalance_date].fillna(0.0), 0.0):
            previous_dates = daily_weights.index[daily_weights.index < rebalance_date]
            if len(previous_dates) == 0:
                return False
            previous = daily_weights.loc[previous_dates[-1]].fillna(0.0)
            current = daily_weights.loc[rebalance_date].fillna(0.0)
            if not np.allclose(current, previous):
                return False
    return True


def _unique(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        symbol = str(item).upper()
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result
