from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quant_us.backtest.us_etf_rotation_execution import simulate_us_etf_rotation_backtest_execution
from quant_us.portfolio.us_etf_rotation_portfolio import (
    construct_us_etf_rotation_portfolio,
)
from quant_us.signals.us_etf_rotation_alpha import (
    UsEtfAlphaSignals,
    generate_us_etf_rotation_alpha_signals,
)


MACRO_COLUMNS = ("WALCL", "WTREGEN", "RRPONTSYD", "BAMLC0A0CM", "DGS10", "DGS2")


@dataclass(frozen=True)
class UsEtfMacroMomentumRotationConfig:
    strategy_id: str = "us_etf_macro_momentum_rotation_v1"
    offensive_assets: tuple[str, ...] = (
        "QQQ",
        "VOO",
        "MTUM",
        "QMOM",
        "SOXX",
        "IGV",
        "XBI",
        "XLK",
        "XLF",
        "XLV",
        "XLE",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
        "BITO",
        "PDBC",
        "GLD",
        "USO",
    )
    benchmark: str = "SPY"
    defense_assets: tuple[str, ...] = ("IEF", "GLD", "DBMF", "SHV")
    beta_window: int = 63
    defense_mom_window: int = 20
    defense_target_vol: float = 0.07
    vol_window: int = 21
    cov_lookback: int = 63
    liquidity_weight: float = 0.4
    credit_weight: float = 0.4
    trend_weight: float = 0.2
    top_n: int = 2
    mom_lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    mom_weights: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4)
    target_vol: float = 0.20
    target_vol_inverted: float = 0.15
    rate_shock_window: int = 21
    rate_shock_threshold: float = 0.40
    rate_shock_penalty: float = 0.4
    vol_short_window: int = 21
    vol_long_window: int = 63
    vol_expansion_threshold: float = 1.1
    macro_mode: str = "CONTINUOUS"
    macro_threshold: float = 0.4
    macro_cont_lower: float = 0.2
    macro_cont_upper: float = 0.4
    start_date: str = "2018-01-01"
    cost_per_turnover: float = 0.0015
    macro_lag_days: int = 2
    min_rows: int = 300
    source_project_path: str = "legacy_strategies/us_etf_rotation_original"

    def required_symbols(self) -> tuple[str, ...]:
        return tuple(_unique([*self.offensive_assets, *self.defense_assets, self.benchmark]))

    def to_report_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_symbols"] = list(self.required_symbols())
        return data


@dataclass(frozen=True)
class RotationBacktestResult:
    strategy_returns: pd.Series
    macro_regime: pd.Series
    equity_exposure: pd.Series
    daily_weights: pd.DataFrame
    beta: pd.DataFrame
    diagnostics: dict[str, Any] = field(default_factory=dict)


def build_price_matrix_from_bars(bars: pd.DataFrame, symbols: list[str] | tuple[str, ...]) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame()
    required = {"timestamp_utc", "symbol", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"bars missing columns: {sorted(missing)}")
    working = bars.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    working["symbol"] = working["symbol"].astype(str).str.upper()
    working = working[working["symbol"].isin([symbol.upper() for symbol in symbols])]
    if working.empty:
        return pd.DataFrame()
    matrix = (
        working.sort_values(["timestamp_utc", "symbol"])
        .drop_duplicates(["timestamp_utc", "symbol"], keep="last")
        .pivot(index="timestamp_utc", columns="symbol", values="close")
        .sort_index()
    )
    matrix = matrix.where(matrix > 2.0).ffill()
    return matrix


def calculate_rotation_inputs(
    prices: pd.DataFrame,
    macro_data: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signals = generate_us_etf_rotation_alpha_signals(prices, macro_data, cfg)
    signals.cross_sectional_momentum.attrs["macro_status"] = signals.diagnostics.get("macro_status", "unknown")
    return (
        signals.cross_sectional_momentum,
        signals.realized_volatility,
        signals.absolute_trend,
        signals.macro_regime,
        signals.yield_curve_inverted,
        signals.asset_returns,
        signals.defensive_momentum,
        signals.beta,
    )


def run_rotation_backtest(
    prices: pd.DataFrame,
    asset_rets: pd.DataFrame,
    mom_score: pd.DataFrame,
    volatility: pd.DataFrame,
    trend_filter: pd.DataFrame,
    macro_regime: pd.Series,
    yield_curve_inverted: pd.Series,
    defense_mom: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
) -> RotationBacktestResult:
    signals = UsEtfAlphaSignals(
        cross_sectional_momentum=mom_score,
        absolute_trend=trend_filter,
        macro_regime=macro_regime,
        yield_curve_inverted=yield_curve_inverted,
        defensive_momentum=defense_mom,
        realized_volatility=volatility,
        asset_returns=asset_rets,
        beta=pd.DataFrame(index=prices.index),
        diagnostics={"layer": "alpha_signal_compatibility_adapter"},
    )
    portfolio = construct_us_etf_rotation_portfolio(prices, signals, cfg)
    execution = simulate_us_etf_rotation_backtest_execution(portfolio, asset_rets, cfg)
    diagnostics = {
        **portfolio.diagnostics,
        **execution.diagnostics,
        "architecture_layers": ["alpha_signal", "portfolio_construction", "execution_simulation"],
        "layer_contract": "signals_to_portfolio_to_execution",
        "t_plus_1_execution": portfolio.diagnostics.get("t_plus_1_execution", False),
    }
    return RotationBacktestResult(
        strategy_returns=execution.strategy_returns,
        macro_regime=macro_regime,
        equity_exposure=portfolio.equity_exposure,
        daily_weights=portfolio.daily_target_weights,
        beta=pd.DataFrame(index=prices.index),
        diagnostics=diagnostics,
    )


def run_us_etf_macro_momentum_rotation(
    prices: pd.DataFrame,
    macro_data: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
) -> RotationBacktestResult:
    signals = generate_us_etf_rotation_alpha_signals(prices, macro_data, cfg)
    portfolio = construct_us_etf_rotation_portfolio(prices, signals, cfg)
    execution = simulate_us_etf_rotation_backtest_execution(portfolio, signals.asset_returns, cfg)
    diagnostics = {
        **signals.diagnostics,
        **portfolio.diagnostics,
        **execution.diagnostics,
        "macro_status": signals.diagnostics.get("macro_status", "unknown"),
        "architecture_layers": ["alpha_signal", "portfolio_construction", "execution_simulation"],
        "layer_contract": "signals_to_portfolio_to_execution",
        "t_plus_1_execution": portfolio.diagnostics.get("t_plus_1_execution", False),
    }
    return RotationBacktestResult(
        strategy_returns=execution.strategy_returns,
        macro_regime=signals.macro_regime,
        equity_exposure=portfolio.equity_exposure,
        daily_weights=portfolio.daily_target_weights,
        beta=signals.beta,
        diagnostics=diagnostics,
    )


def performance_summary(
    returns: pd.Series,
    benchmark_prices: pd.Series | None = None,
    *,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    clean = returns.dropna()
    if clean.empty:
        return {}
    equity = (1.0 + clean).cumprod()
    years = max(len(clean) / periods_per_year, 1.0 / periods_per_year)
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    annualized_return = float(clean.mean() * periods_per_year)
    annualized_vol = float(clean.std(ddof=0) * np.sqrt(periods_per_year))
    sharpe = float(annualized_return / annualized_vol) if annualized_vol > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    annual_returns = {
        str(year): float((1.0 + group).prod() - 1.0)
        for year, group in clean.groupby(clean.index.year)
    }
    summary: dict[str, Any] = {
        "rows": int(len(clean)),
        "sample_start": str(clean.index.min().date()),
        "sample_end": str(clean.index.max().date()),
        "total_return": total_return,
        "cagr": cagr,
        "annualized_return_arithmetic": annualized_return,
        "annualized_volatility": annualized_vol,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "annual_returns": annual_returns,
    }
    if benchmark_prices is not None and not benchmark_prices.empty:
        bench_ret = benchmark_prices.pct_change(fill_method=None).reindex(clean.index).fillna(0.0)
        bench_equity = (1.0 + bench_ret).cumprod()
        summary["benchmark_total_return"] = float(bench_equity.iloc[-1] - 1.0)
        summary["excess_total_return"] = total_return - summary["benchmark_total_return"]
    return summary


def _build_macro_regime(
    prices: pd.DataFrame,
    macro_data: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
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


def _defense_allocations(
    date: pd.Timestamp,
    asset_rets: pd.DataFrame,
    volatility: pd.DataFrame,
    defense_mom: pd.DataFrame,
    cfg: UsEtfMacroMomentumRotationConfig,
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
    cfg: UsEtfMacroMomentumRotationConfig,
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


def _base_equity_weight(current_macro_score: float, cfg: UsEtfMacroMomentumRotationConfig) -> float:
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


def _validate_price_columns(prices: pd.DataFrame, cfg: UsEtfMacroMomentumRotationConfig) -> None:
    missing = [symbol for symbol in cfg.required_symbols() if symbol not in prices.columns]
    if missing:
        raise ValueError(f"price matrix missing required symbols: {missing}")


def _unique(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        symbol = str(item).upper()
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result
