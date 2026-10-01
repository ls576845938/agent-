type Selection = {strategyId?: string; candidateId?: string; canonicalSignalAvailable?: boolean};
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const label = (value: unknown) => typeof value === 'string' && value.trim() ? value : '未发布';
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value);

export function shouldRequestSource(selection: Selection | null) {
  // History catalog capability is unknown, not a negative canonical decision.
  // The exact-identity backend endpoint remains the authority.
  return Boolean(selection?.strategyId && selection.candidateId && selection.canonicalSignalAvailable !== false);
}

export function validStrategySource(value: unknown, selection: Selection) {
  const source = record(value);
  const safety = record(source.safety);
  return source.strategy_id === selection.strategyId && source.candidate_id === selection.candidateId
    && source.canonical_signal_available === true && hash(source.content_sha256)
    && typeof source.content === 'string' && Boolean(source.content.trim())
    && typeof source.source_ref === 'string' && Boolean(source.source_ref)
    && Array.isArray(source.sections) && source.sections.length > 0 && source.sections.every((value) => {
      const section = record(value);
      return typeof section.symbol === 'string' && typeof section.source_ref === 'string' && typeof section.content === 'string' && hash(section.content_sha256);
    }) && ['paper', 'live', 'order', 'private', 'real_order'].every((key) => safety[key] === false);
}

export async function sourceContentHashesMatch(value: unknown) {
  const source = record(value);
  const blocks = [source, ...(Array.isArray(source.sections) ? source.sections.map(record) : [])];
  for (const block of blocks) {
    if (typeof block.content !== 'string' || !hash(block.content_sha256)) return false;
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(block.content));
    const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    if (actual !== String(block.content_sha256).toLowerCase()) return false;
  }
  return blocks.length > 1;
}

export function utcTime(value: unknown) {
  if (typeof value !== 'string' || !value.trim() || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return '未发布';
  const time = Date.parse(value);
  return Number.isFinite(time) ? `${new Date(time).toISOString().replace('T', ' ').replace('Z', '')} UTC` : '未发布';
}

export function historicalProvenance(value: unknown) {
  const detail = record(value);
  const source = record(detail.source);
  const data = record(source.data);
  const canonical = record(detail.canonical);
  const identity = record(canonical.strategy_identity);
  const exchange = label(data.exchange ?? identity.signal_data_venue);
  const sourceInterval = label(data.source_interval);
  const decisionInterval = label(data.decision_interval ?? data.base_decision_interval);
  return {
    exchange: exchange === 'binance_spot' ? 'Binance 现货' : exchange,
    symbol: label(data.symbol ?? identity.signal_instrument),
    interval: sourceInterval === '未发布' && decisionInterval === '未发布' ? '未发布' : `${sourceInterval} → ${decisionInterval}`,
    start: utcTime(data.bar_4h_start), end: utcTime(data.bar_4h_end),
    generated: utcTime(source.generated_at_utc), reportHash: label(source.report_sha256),
    code: label(source.source_code_commit),
    execution: identity.execution_venue === 'research_simulation' ? '研究模拟（非真实成交）' : label(identity.execution_venue),
  };
}

export function missingHistoricalSeries(value: unknown): string[] {
  const series = record(value);
  return [
    ['equity', '连续净值'], ['drawdown', '连续回撤'], ['monthly_returns', '月度收益序列'],
    ['trades', '完整成交账本'], ['costs', '现金成本分项'],
  ].filter(([key]) => !Array.isArray(series[key]) || !(series[key] as unknown[]).length).map(([, name]) => name);
}

export function filterChartWindow<T extends {time: number}>(candles: T[], start: string, end: string): {candles: T[]; error: string} {
  const date = (value: string) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN;
    const parsed = Date.parse(`${value}T00:00:00Z`);
    return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value ? parsed / 1000 : NaN;
  };
  const from = start ? date(start) : -Infinity;
  const to = end ? date(end) + 86400 : Infinity;
  if (Number.isNaN(from) || Number.isNaN(to) || from >= to) return {candles: [], error: '请输入有效的 UTC 日期区间，结束日期不得早于开始日期。'};
  return {candles: candles.filter((row) => row.time >= from && row.time < to), error: ''};
}
