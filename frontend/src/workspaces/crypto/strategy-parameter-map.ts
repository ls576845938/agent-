export type ParameterRow = {candidate_id: string; family: string; params: Record<string, unknown>; metrics: Record<string, number | null>};
export type ParameterMetric = 'sharpe_ratio' | 'annual_return_pct' | 'max_drawdown_pct' | 'sortino_ratio';
export const MAP_METRICS: {key: ParameterMetric; label: string}[] = [
  {key: 'sharpe_ratio', label: 'Sharpe'}, {key: 'annual_return_pct', label: 'CAGR · 年化收益'},
  {key: 'max_drawdown_pct', label: '最大回撤'}, {key: 'sortino_ratio', label: 'Sortino'},
];
const PARAMETER_LABELS: Record<string, string> = {
  fast: 'FastMA · 快均线', slow: 'SlowMA · 慢均线', fast_window: 'FastMA · 快均线窗口', slow_window: 'SlowMA · 慢均线窗口',
  daily_fast: '日线快均线', daily_slow: '日线慢均线', entry_window: '唐奇安入场窗口', exit_window: '唐奇安退出窗口',
  cooldown_bars: '冷却周期', atr_mult: 'ATR 止损倍数', atr_window: 'ATR 窗口', failure_exit_window: '失败突破退出窗口',
};
export function parameterLabel(key: string) { return PARAMETER_LABELS[key] || key; }
export function numericParameters(rows: Pick<ParameterRow, 'params'>[]): string[] {
  return [...new Set(rows.flatMap((row) => Object.keys(row.params)))].filter((key) => rows.some((row) => finite(row.params[key])));
}
export function defaultAxes(rows: Pick<ParameterRow, 'params'>[]): [string, string] {
  const keys = numericParameters(rows);
  for (const pair of [['fast_window', 'slow_window'], ['fast', 'slow'], ['entry_window', 'cooldown_bars'], ['entry_window', 'exit_window'], ['daily_fast', 'daily_slow']]) {
    if (pair.every((key) => keys.includes(key))) return pair as [string, string];
  }
  return [keys[0] || '', keys[1] || ''];
}
export function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value); }
export function metricQuality(value: number, metric: ParameterMetric) { return metric === 'max_drawdown_pct' ? -Math.abs(value) : value; }
export function formatMapMetric(value: unknown, metric: ParameterMetric) {
  return finite(value) ? `${(metric === 'max_drawdown_pct' ? -Math.abs(value) : value).toFixed(2)}${metric.endsWith('_pct') ? '%' : ''}` : '未发布';
}
export type ParameterCell = {x: number; y: number; rows: ParameterRow[]; value: number | null; status: 'available' | 'missing' | 'ambiguous' | 'missing_metric'};
export function coupledExitWindow(rows: Pick<ParameterRow, 'params'>[], x: string, y: string) {
  return [x, y].includes('entry_window') && ![x, y].includes('exit_window') && rows.length > 0
    && rows.every((row) => row.params.signal_type === 'symmetric_donchian' && finite(row.params.entry_window) && row.params.exit_window === Math.floor(row.params.entry_window / 2));
}
export function buildParameterSlice(rows: ParameterRow[], x: string, y: string, fixed: Record<string, unknown>, metric: ParameterMetric) {
  const empty = {xValues: [] as number[], yValues: [] as number[], cells: [] as ParameterCell[]};
  if (!x || !y || x === y) return empty;
  const coupled = coupledExitWindow(rows, x, y);
  const otherKeys = [...new Set(rows.flatMap((row) => Object.keys(row.params)))].filter((key) => key !== x && key !== y && !(coupled && key === 'exit_window'));
  if (otherKeys.some((key) => !Object.hasOwn(fixed, key))) return empty;
  const candidates = rows.filter((row) => otherKeys.every((key) => JSON.stringify(row.params[key]) === JSON.stringify(fixed[key])) && finite(row.params[x]) && finite(row.params[y]));
  const xValues = [...new Set(rows.map((row) => row.params[x]).filter(finite))].sort((a, b) => a - b);
  const yValues = [...new Set(rows.map((row) => row.params[y]).filter(finite))].sort((a, b) => a - b);
  if (xValues.length * yValues.length > 2500) return empty;
  const cells = yValues.flatMap((yv) => xValues.map((xv): ParameterCell => {
    const matches = candidates.filter((row) => row.params[x] === xv && row.params[y] === yv);
    const value = matches.length === 1 && finite(matches[0].metrics[metric]) ? matches[0].metrics[metric] : null;
    return {x: xv, y: yv, rows: matches, value, status: matches.length > 1 ? 'ambiguous' : !matches.length ? 'missing' : value === null ? 'missing_metric' : 'available'};
  }));
  return {xValues, yValues, cells};
}
