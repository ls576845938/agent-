import pandas as pd
import numpy as np

def calculate_signals(prices, macro_data, cfg):
    all_assets = list(set(cfg.TICKERS + cfg.DEFENSE_ASSETS + [cfg.BENCHMARK]))
    daily_ret = prices[all_assets].pct_change()
    
    market_ret = daily_ret[cfg.BENCHMARK]
    rolling_mkt_var = market_ret.rolling(cfg.BETA_WINDOW).var()
    
    beta_df = pd.DataFrame(index=prices.index, columns=all_assets)
    for ticker in all_assets:
        rolling_cov = daily_ret[ticker].rolling(cfg.BETA_WINDOW).cov(market_ret)
        beta_df[ticker] = rolling_cov / rolling_mkt_var
        
    beta_df = beta_df.ffill().fillna(0) 
    
    idio_ret = pd.DataFrame(index=prices.index, columns=cfg.TICKERS)
    for ticker in cfg.TICKERS:
        idio_ret[ticker] = daily_ret[ticker] - beta_df[ticker].shift(1) * market_ret
        
    idio_ret = idio_ret.fillna(daily_ret[cfg.TICKERS])
    idio_ret_clipped = idio_ret.clip(lower=-0.9999) 
    idio_log_ret = np.log1p(idio_ret_clipped)

    mom_score = pd.DataFrame(0.0, index=prices.index, columns=cfg.TICKERS)
    for lookback, weight in zip(cfg.MOM_LOOKBACKS, cfg.MOM_WEIGHTS):
        ret_lookback = np.expm1(idio_log_ret.rolling(lookback).sum())
        vol_lookback = idio_ret.rolling(lookback).std() * np.sqrt(252)
        vol_lookback = vol_lookback.replace(0, 0.0001)
        risk_adjusted_ret = ret_lookback / vol_lookback
        mom_score += risk_adjusted_ret * weight

    short_vol = idio_ret.rolling(cfg.VOL_SHORT_WINDOW).std() * np.sqrt(252)
    long_vol = idio_ret.rolling(cfg.VOL_LONG_WINDOW).std() * np.sqrt(252)
    long_vol = long_vol.replace(0, 0.0001)
    
    vol_ratio = short_vol / long_vol
    vol_penalty = np.where(
        vol_ratio > cfg.VOL_EXPANSION_THRESHOLD, 
        cfg.VOL_EXPANSION_THRESHOLD / vol_ratio, 
        1.0
    )
    vol_penalty_df = pd.DataFrame(vol_penalty, index=prices.index, columns=cfg.TICKERS)
    mom_score = np.where(mom_score > 0, mom_score * vol_penalty_df, mom_score)
    mom_score = pd.DataFrame(mom_score, index=prices.index, columns=cfg.TICKERS)

    sma200 = prices[cfg.TICKERS].rolling(200).mean()
    trend_filter = prices[cfg.TICKERS] > sma200
    
    defense_mom = prices[cfg.DEFENSE_ASSETS].pct_change(cfg.DEFENSE_MOM_WINDOW)
    
    if macro_data.empty:
        macro_regime = pd.Series(1.0, index=prices.index)
        yield_curve_inverted = pd.Series(False, index=prices.index)
    else:
        common_index = prices.index.intersection(macro_data.index)
        macro_df = macro_data.shift(cfg.MACRO_LAG_DAYS).loc[common_index].ffill()
        spy_prices = prices.loc[common_index, cfg.BENCHMARK]
        
        net_liquidity = macro_df['WALCL'] - macro_df['WTREGEN'] - macro_df['RRPONTSYD']
        liq_sma = net_liquidity.rolling(40).mean()
        sig_liquidity = (net_liquidity > liq_sma).astype(int)
        
        spread = macro_df['BAMLC0A0CM']
        spread_sma = spread.rolling(20).mean()
        sig_credit = (spread < spread_sma).astype(int)
        
        spy_sma200 = spy_prices.rolling(200).mean()
        sig_trend = (spy_prices > spy_sma200).astype(int)
        
        macro_regime_aligned = (
            sig_liquidity * cfg.W_LIQUIDITY +
            sig_credit    * cfg.W_CREDIT +
            sig_trend     * cfg.W_TREND
        )
        
        dgs10 = macro_df['DGS10']
        rate_change = dgs10.diff(cfg.RATE_SHOCK_WINDOW)
        rate_shock_penalty = np.where(rate_change > cfg.RATE_SHOCK_THRESHOLD, cfg.RATE_SHOCK_PENALTY, 1.0)
        rate_shock_series = pd.Series(rate_shock_penalty, index=macro_df.index).reindex(prices.index).ffill().fillna(1.0)
        
        macro_regime = macro_regime_aligned.reindex(prices.index).ffill() * rate_shock_series
        
        dgs2 = macro_df['DGS2']
        spread_10y2y = dgs10 - dgs2
        yield_curve_inverted = (spread_10y2y < 0).reindex(prices.index).ffill().fillna(False)
    
    vol_daily = daily_ret[all_assets].rolling(cfg.VOL_WINDOW).std()
    
    return mom_score, vol_daily, trend_filter, macro_regime, yield_curve_inverted, daily_ret, defense_mom, beta_df


def run_backtest(prices, asset_rets, mom_score, volatility, trend_filter, macro_regime, yield_curve_inverted, defense_mom, cfg):
    rebalance_dates = prices.resample('ME').last().index
    unique_assets = list(set(cfg.TICKERS + cfg.DEFENSE_ASSETS))
    weights_monthly = pd.DataFrame(0.0, index=rebalance_dates, columns=unique_assets)
    
    for date in rebalance_dates:
        if date not in prices.index: continue
            
        current_macro_score = macro_regime.loc[date]
        is_inverted = yield_curve_inverted.loc[date]
        current_target_vol = cfg.TARGET_VOL_INVERTED if is_inverted else cfg.TARGET_VOL
        
        defense_allocations = {asset: 0.0 for asset in cfg.DEFENSE_ASSETS}
        risk_def_assets = [a for a in cfg.DEFENSE_ASSETS if a != 'SHV']
        
        current_def_mom = defense_mom.loc[date, risk_def_assets]
        shv_mom = defense_mom.loc[date, 'SHV'] if not pd.isna(defense_mom.loc[date, 'SHV']) else 0.0
        
        if current_def_mom.isna().all():
            defense_allocations['SHV'] = 1.0
        else:
            valid_def = [
                asset for asset in risk_def_assets 
                if current_def_mom[asset] > 0 and current_def_mom[asset] > shv_mom
            ]
            
            if not valid_def:
                defense_allocations['SHV'] = 1.0
            else:
                def_vols = volatility.loc[date, valid_def].replace(0, 0.0001)
                def_moms = current_def_mom[valid_def]
                risk_adj_mom = def_moms / def_vols
                raw_def_weights = risk_adj_mom / risk_adj_mom.sum()
                
                def_hist_rets = asset_rets.loc[:date, valid_def].tail(cfg.COV_LOOKBACK)
                if len(def_hist_rets) > 10:
                    def_cov = def_hist_rets.cov() * 252
                    def_var = np.dot(raw_def_weights.values.T, np.dot(def_cov.values, raw_def_weights.values))
                    def_expected_vol = np.sqrt(def_var)
                    scale_factor = cfg.DEFENSE_TARGET_VOL / def_expected_vol if def_expected_vol > cfg.DEFENSE_TARGET_VOL else 1.0
                else:
                    scale_factor = 1.0
                
                for asset in valid_def:
                    defense_allocations[asset] = raw_def_weights[asset] * scale_factor
                defense_allocations['SHV'] = 1.0 - sum(defense_allocations.values())

        if cfg.MACRO_MODE == 'STEP':
            base_equity_weight = 1.0 if current_macro_score >= cfg.MACRO_THRESHOLD else 0.0
        elif cfg.MACRO_MODE == 'CONTINUOUS':
            if current_macro_score >= cfg.MACRO_CONT_UPPER: base_equity_weight = 1.0
            elif current_macro_score <= cfg.MACRO_CONT_LOWER: base_equity_weight = 0.0
            else: base_equity_weight = (current_macro_score - cfg.MACRO_CONT_LOWER) / (cfg.MACRO_CONT_UPPER - cfg.MACRO_CONT_LOWER)
        else:
            base_equity_weight = current_macro_score
            
        weights_monthly.loc[date] = 0.0
        
        if base_equity_weight == 0:
            for asset in cfg.DEFENSE_ASSETS:
                weights_monthly.loc[date, asset] += defense_allocations[asset]
            continue
            
        current_mom = mom_score.loc[date]          
        current_trend = trend_filter.loc[date]      
        valid_mom = current_mom.where(current_trend, -999)
        
        sorted_assets = valid_mom.sort_values(ascending=False)
        valid_assets_list = sorted_assets[sorted_assets != -999].index.tolist()
        
        top_assets = []
        if len(valid_assets_list) > 0:
            corr_hist_rets = asset_rets.loc[:date, valid_assets_list].tail(cfg.COV_LOOKBACK)
            current_corr = corr_hist_rets.corr() if len(corr_hist_rets) > 10 else pd.DataFrame()
            
            for asset in valid_assets_list:
                if not top_assets:
                    top_assets.append(asset)
                else:
                    is_too_correlated = False
                    if not current_corr.empty:
                        for picked_asset in top_assets:
                            if current_corr.loc[asset, picked_asset] > 0.80:
                                is_too_correlated = True
                                break
                    if not is_too_correlated: top_assets.append(asset)
                if len(top_assets) >= cfg.TOP_N: break
            
            if len(top_assets) < cfg.TOP_N:
                for asset in valid_assets_list:
                    if asset not in top_assets: top_assets.append(asset)
                    if len(top_assets) >= cfg.TOP_N: break

        if not top_assets:
            for asset in cfg.DEFENSE_ASSETS:
                weights_monthly.loc[date, asset] += defense_allocations[asset]
        else:
            selected_vols = volatility.loc[date, top_assets].replace(0, 0.0001)
            inv_vols = 1.0 / selected_vols
            rp_weights = inv_vols / inv_vols.sum()  
            
            hist_rets = asset_rets.loc[:date, top_assets].tail(cfg.COV_LOOKBACK)
            if len(hist_rets) > 10:
                cov_matrix = hist_rets.cov() * 252
                port_variance = np.dot(rp_weights.values.T, np.dot(cov_matrix.values, rp_weights.values))
                expected_vol = np.sqrt(port_variance)
                vol_scaler = min(1.0, current_target_vol / expected_vol) if expected_vol > 0 else 1.0
            else:
                vol_scaler = 1.0
                
            final_equity_weight = base_equity_weight * vol_scaler
            
            for asset in top_assets:
                weights_monthly.loc[date, asset] += rp_weights[asset] * final_equity_weight
            
            def_total_weight = 1.0 - final_equity_weight
            for asset in cfg.DEFENSE_ASSETS:
                weights_monthly.loc[date, asset] += defense_allocations[asset] * def_total_weight

    daily_weights = weights_monthly.reindex(prices.index).ffill().shift(1)
    daily_weights.fillna(0.0, inplace=True)
    
    port_daily_ret = (daily_weights * asset_rets[daily_weights.columns]).sum(axis=1)
    turnover = daily_weights.diff().abs().sum(axis=1)
    port_daily_ret = port_daily_ret - (turnover * cfg.COST_BPS)
    
    pure_equity_assets = [a for a in cfg.TICKERS if a not in cfg.DEFENSE_ASSETS]
    equity_exposure = daily_weights[pure_equity_assets].sum(axis=1)
    
    return port_daily_ret, macro_regime, equity_exposure, daily_weights