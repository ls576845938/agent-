export const ALPHA_SOURCES = [
  {id: 'stat_arb', label: '统计套利策略'},
  {id: 'trend', label: '趋势策略'},
  {id: 'macro', label: '宏观因子策略'},
  {id: 'time_series', label: '时序因子策略'},
  {id: 'cross_sectional', label: '截面因子策略'},
  {id: 'event', label: '事件驱动策略'},
  {id: 'microstructure', label: '市场微观结构策略'},
] as const;
export type AlphaSource = typeof ALPHA_SOURCES[number]['id'];

// Strategy identity mappings, not guesses from display names or readiness.
const SOURCES: Record<string, AlphaSource[]> = {
  trend_macd: ['trend'], donchian_breakout: ['trend'], volatility_squeeze: ['trend'],
  trend_momentum: ['trend', 'time_series'], macro_trend: ['trend'],
  reversion_rsi: ['time_series'], short_reversion: ['time_series'], time_window: ['time_series'],
  dynamic_grid: ['time_series'], funding_sentiment: ['time_series'],
  // These registry implementations consume one price series. Their names and
  // descriptors do not establish macro inputs, cross-sectional ranks or events.
  factor_rank: ['time_series'], etf_rotation: ['trend', 'time_series'], earnings_drift: ['trend', 'time_series'],
  btc_low_turnover_trend: ['trend'], btc_trend_pullback: ['trend'], btc_vol_breakout: ['trend'],
  btc_regime_trend: ['trend'], btc_low_turnover_breakout: ['trend'], btc_compression_breakout: ['trend'],
  btc_capitulation_rebound: ['time_series'], btc_perp_dual_trend: ['trend'], btc_orderflow_pressure: ['microstructure'],
  long_short_donchian_top5: ['trend'], long_short_donchian_top5_okx_native: ['trend'],
};
export function alphaSourcesFor(strategyId: string | undefined): AlphaSource[] {
  return [...(SOURCES[strategyId || ''] || [])];
}
export function alphaLabel(id: string): string {
  return ALPHA_SOURCES.find((source) => source.id === id)?.label || '待归类';
}
