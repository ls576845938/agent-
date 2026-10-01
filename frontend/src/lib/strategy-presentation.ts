/**
 * Presentation-only labels for the research/demo workbenches.
 * Stable strategy/candidate/version identifiers must always remain unchanged.
 */
const STRATEGY_LABELS: Record<string, string> = {
  long_short_donchian_top5: '多空唐奇安突破 Top5',
  long_short_donchian_top5_okx_native: '多空唐奇安突破 Top5（OKX 原生）',
  high_yield_donchian_v2: '高收益唐奇安 v2',
  high_octane_attack_sleeve_v2: '高强度进攻分仓 v2',
  btc_high_yield_v2: '高收益唐奇安 v2',
  btc_high_octane_v1: '高强度进攻分仓 v2',
  trend_macd: 'MACD 趋势',
  etf_rotation: '美股 ETF 轮动',
  'BTC Low Turnover Breakout': 'BTC 低换手突破',
  'BTC Compression Breakout': 'BTC 压缩突破',
  'BTC Capitulation Rebound': 'BTC 恐慌反弹',
  'BTC Perp Dual Trend': 'BTC 永续双趋势',
  'BTC Order Flow Pressure': 'BTC 订单流压力',
  'BTC Trend Pullback': 'BTC 趋势回撤',
  'BTC Volatility Breakout': 'BTC 波动率突破',
  'BTC Regime Trend': 'BTC 状态趋势',
  'Reversion RSI': 'RSI 均值回归',
  'Donchian Breakout': '唐奇安突破',
  'Volatility Squeeze': '波动率挤压',
  'Funding Sentiment': '资金费率情绪',
  'Macro Trend Stack': '宏观趋势叠加',
  'Time Window Effect': '时间窗口效应',
  'Dynamic Grid': '动态网格',
  'Trend Momentum (US)': '美股趋势动量',
  'Short Reversion (US)': '美股短线均值回归',
  'Factor Rank (US)': '美股因子排序',
  'Earnings Drift (US)': '美股财报漂移',
  'BTC Low Turnover Trend': 'BTC 低换手趋势',
  'Trend MACD': 'MACD 趋势',
  'ETF Rotation': '美股 ETF 轮动',
  'ETF Rotation (US)': '美股 ETF 轮动',
};

const NORMALIZED_LABELS: Record<string, string> = {
  'long/short donchian top5': '多空唐奇安突破 Top5',
  'long/short donchian top5 · okx native': '多空唐奇安突破 Top5（OKX 原生）',
  'long/short donchian top5 (okx native)': '多空唐奇安突破 Top5（OKX 原生）',
  'high-yield donchian v2': '高收益唐奇安 v2',
  'high-octane attack sleeve v2': '高强度进攻分仓 v2',
  'btc low turnover breakout': 'BTC 低换手突破',
  'btc compression breakout': 'BTC 压缩突破',
  'btc capitulation rebound': 'BTC 恐慌反弹',
  'btc perp dual trend': 'BTC 永续双趋势',
  'btc order flow pressure': 'BTC 订单流压力',
  'btc trend pullback': 'BTC 趋势回撤',
  'btc volatility breakout': 'BTC 波动率突破',
  'btc regime trend': 'BTC 状态趋势',
  'reversion rsi': 'RSI 均值回归',
  'donchian breakout': '唐奇安突破',
  'volatility squeeze': '波动率挤压',
  'funding sentiment': '资金费率情绪',
  'macro trend stack': '宏观趋势叠加',
  'time window effect': '时间窗口效应',
  'dynamic grid': '动态网格',
  'trend momentum (us)': '美股趋势动量',
  'short reversion (us)': '美股短线均值回归',
  'factor rank (us)': '美股因子排序',
  'earnings drift (us)': '美股财报漂移',
  'btc low turnover trend': 'BTC 低换手趋势',
  'trend macd': 'MACD 趋势',
  'etf rotation': '美股 ETF 轮动',
  'etf rotation (us)': '美股 ETF 轮动',
};

export function strategyPresentationName(raw: string | null | undefined, strategyId?: string | null): string {
  const value = String(raw ?? '').trim();
  const id = String(strategyId ?? '').trim();
  if (id && STRATEGY_LABELS[id]) return STRATEGY_LABELS[id];
  if (value && STRATEGY_LABELS[value]) return STRATEGY_LABELS[value];
  const normalized = value.toLowerCase().replace(/\s+/g, ' ');
  return NORMALIZED_LABELS[normalized] ?? value;
}

export function hasCanonicalStrategySource(spec: {canonical_signal_available?: boolean; adapter_fidelity?: string} | null | undefined): boolean {
  return spec?.canonical_signal_available === true && spec.adapter_fidelity !== 'identity_only';
}

export type StrategyCapabilityStatus = {
  canonicalSignalAvailable?: boolean;
  backtestSupported?: boolean;
  promotionCreditEligible?: boolean;
  demoSelectable?: boolean;
  adapterFidelity?: string;
};

/**
 * Stable presentation-only variant label. Candidate IDs remain the identity;
 * this label only prevents equal family titles from looking like duplicates.
 */
export function strategyVariantLabel(candidateId: string | null | undefined, strategyId?: string | null): string {
  const candidate = String(candidateId ?? '').trim();
  if (!candidate) return '默认变体';
  const native = `${String(strategyId ?? '')} ${candidate}`.toLowerCase().includes('okx_native') ? 'OKX 原生 · ' : '';
  const numbered = candidate.match(/(?:^|[-_])(?:stable|variant|candidate|tf)?[-_]?([0-9]{1,4})$/i);
  if (numbered) return `${native}变体 ${Number(numbered[1])}`;
  const short = candidate.length > 22 ? `${candidate.slice(0, 22)}…` : candidate;
  return `${native}候选 ${short}`;
}

function capability(value: boolean | undefined, label: string): string {
  return `${label}：${value === true ? '可用' : value === false ? '不可用' : '未知'}`;
}

export function strategyCapabilityText(status: StrategyCapabilityStatus): string {
  const identity = status.adapterFidelity === 'identity_only' ? '身份模式：仅身份/历史证据' : '';
  return [
    capability(status.canonicalSignalAvailable, '信号'),
    capability(status.backtestSupported, '回测'),
    capability(status.promotionCreditEligible, '晋级凭证'),
    capability(status.demoSelectable, 'Demo'),
    identity,
  ].filter(Boolean).join(' · ');
}

export function strategyAdapterLabel(value: string | null | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '适配状态：未知';
  if (raw === 'identity_only') return '适配状态：仅身份/历史证据';
  if (raw === 'canonical') return '适配状态：标准源码';
  return `适配状态：${raw.replace(/_/g, ' ')}`;
}

const STATUS_LABELS: Record<string, string> = {
  research_only: '仅研究/只读',
  research_display: '研究展示',
  blocked: '已阻断',
  gated: '待门禁',
  complete_research_only: '研究完成（只读）',
  git_object_verified_not_promotion_ready: '已核验 Git 对象（未达到晋级条件）',
  identity_only_no_demo_execution_ledger: '仅身份候选；没有 Demo 执行账本',
  account_not_synced: '未同步账户',
  not_forward_ready: '未达到晋级条件',
  not_observed: '尚未观测',
  unknown: '未知',
  not_available: '暂不可用',
  'not available': '暂不可用',
  promotion_artifact_unavailable: '晋级产物暂不可用',
};

export function strategyStatusLabel(value: string | null | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '未知';
  return STATUS_LABELS[raw] ?? STATUS_LABELS[raw.toLowerCase()] ?? raw.replace(/_/g, ' ');
}

export function strategySourceLabel(value: string | null | undefined): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '未知来源';
  const normalized = raw.toLowerCase();
  if (normalized === '/api/strategies') return '通用策略目录';
  if (normalized.includes('btc strategy registry')) return 'BTC 策略注册表';
  if (normalized.includes('btc demo catalog')) return 'BTC Demo 目录';
  if (normalized.includes('btc history catalog')) return 'BTC 历史目录';
  if (normalized.includes('cross-market history catalog')) return '跨市场历史目录';
  if (normalized.includes('user') && normalized.includes('backtest')) return '本机研究回测';
  if (normalized.includes('tracked explanation')) return '跟踪说明';
  if (normalized.includes('local ignored latest')) return '本地历史参照';
  return raw;
}

export function strategySafetyText(): string {
  return '研究只读 · 纸盘/实盘/订单/私有接口均禁用';
}
