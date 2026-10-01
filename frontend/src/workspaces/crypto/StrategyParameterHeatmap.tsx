import {useEffect, useMemo, useState} from 'react';
import {ApiError, apiGet} from '../../lib/api';
import {buildParameterSlice, coupledExitWindow, defaultAxes, formatMapMetric, MAP_METRICS, metricQuality, numericParameters, parameterLabel, type ParameterCell, type ParameterMetric, type ParameterRow} from './strategy-parameter-map';

type ParameterEvidence = {
  strategy_id: string; status: string; evidence_sha256: string; relationship: string; rows: ParameterRow[];
  coverage: {published_count: number; declared_count: number; selection: string};
  source: {report_sha256: string; code_commit: string; generated_at: string; sample: string; freshness: string;
    data: {exchange: string; symbol: string; base_decision_interval: string; bar_4h_start: string; bar_4h_end: string};
    cost_model: {base_cost_bps: number}; execution_rule: string};
  safety: Record<string, boolean>;
};
type SelectionEvent = {target: {value: string}};

export default function StrategyParameterHeatmap({strategyId, candidateId}: {strategyId?: string; candidateId?: string}) {
  const [evidence, setEvidence] = useState<ParameterEvidence | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setEvidence(null); setError('');
    if (!strategyId) return;
    void apiGet<ParameterEvidence>(`/api/research/btc/strategy-parameter-map/${encodeURIComponent(strategyId)}`, 30000).then((payload) => {
      if (!active) return;
      if (payload.strategy_id !== strategyId || payload.status !== 'historical_research_only' || !Array.isArray(payload.rows)
        || !payload.safety || ['paper', 'live', 'order', 'private', 'promotion'].some((key) => payload.safety[key] !== false)) {
        setError('参数报告身份或权限校验失败'); return;
      }
      setEvidence(payload);
    }, (reason) => {
      if (active) setError(reason instanceof ApiError && reason.status === 404 ? '该策略尚未发布参数网格。需使用相同数据区间和成本模型完成多组参数回测后，才可观察稳定性。' : '参数报告暂不可读取，请检查历史研究报告配置或重试。');
    });
    return () => { active = false; };
  }, [strategyId, retry]);
  if (!strategyId) return <div className="strategy-workbench-empty">先选择一个策略以查看参数稳定性。</div>;
  if (error) return <div className="strategy-workbench-empty" role="status"><strong>参数网格不可用</strong><span>{error}</span><button type="button" onClick={() => setRetry((value) => value + 1)}>重新读取参数网格</button></div>;
  if (!evidence || evidence.strategy_id !== strategyId) return <div className="strategy-workbench-empty" role="status">正在读取已验证的参数回测结果…</div>;
  return <ParameterMap key={`${evidence.evidence_sha256}:${candidateId || strategyId}`} evidence={evidence} candidateId={candidateId?.replace(/^okx_native_/, '')} />;
}

function ParameterMap({evidence, candidateId}: {key?: string; evidence: ParameterEvidence; candidateId?: string}) {
  const selectedRow = evidence.rows.find((row) => row.candidate_id === candidateId) || evidence.rows[0];
  const families = [...new Set(evidence.rows.map((row) => row.family))];
  const [family, setFamily] = useState(selectedRow?.family || families[0]);
  const familyRows = useMemo(() => evidence.rows.filter((row) => row.family === family), [evidence, family]);
  const initialAxes = defaultAxes(familyRows);
  const [x, setX] = useState(initialAxes[0]);
  const [y, setY] = useState(initialAxes[1]);
  const [fixed, setFixed] = useState<Record<string, unknown>>(selectedRow?.params || {});
  const [metric, setMetric] = useState<ParameterMetric>('sharpe_ratio');
  const [activeCell, setActiveCell] = useState<ParameterCell | null>(null);
  const axes = numericParameters(familyRows);
  const coupled = coupledExitWindow(familyRows, x, y);
  const otherKeys = [...new Set(familyRows.flatMap((row) => Object.keys(row.params)))].filter((key) => key !== x && key !== y && !(coupled && key === 'exit_window'));
  const variableKeys = otherKeys.filter((key) => new Set(familyRows.map((row) => JSON.stringify(row.params[key]))).size > 1);
  const slice = useMemo(() => buildParameterSlice(familyRows, x, y, fixed, metric), [familyRows, x, y, fixed, metric]);
  const available = slice.cells.filter((cell) => cell.status === 'available');
  const qualities = available.map((cell) => metricQuality(cell.value!, metric));
  const low = Math.min(...qualities), high = Math.max(...qualities);
  const anchor = activeCell && slice.cells.find((cell) => cell.x === activeCell.x && cell.y === activeCell.y);
  const resetCell = () => setActiveCell(null);
  const changeFamily = (value: string) => {
    const rows = evidence.rows.filter((row) => row.family === value);
    const [nextX, nextY] = defaultAxes(rows);
    setFamily(value); setX(nextX); setY(nextY); setFixed(rows[0]?.params || {}); resetCell();
  };
  const familyLabel = (value: string) => value === 'symmetric_donchian_formal_narrow / formal_narrow_grid' ? '唐奇安趋势 · 完整窄网格（1,440 组）' : value.replace(' / ', ' · ');
  const cellLabel = (cell: ParameterCell) => `${parameterLabel(x)} ${cell.x}，${parameterLabel(y)} ${cell.y}，${cell.status === 'ambiguous' ? '重复结果，无法比较' : formatMapMetric(cell.value, metric)}`;
  const fill = (cell: ParameterCell) => {
    if (cell.value === null) return '#142033';
    const t = high === low ? 0.5 : (metricQuality(cell.value, metric) - low) / (high - low);
    return `hsl(${222 - t * 58} 48% ${18 + t * 21}%)`;
  };
  return <div className="parameter-map" data-testid="strategy-parameter-map">
    <header className="parameter-map-heading"><div><h2>参数稳定性</h2><p>观察连续有效的参数区域与孤立尖峰</p></div><span>历史研究</span></header>
    <p className="parameter-map-context">{evidence.source.data.symbol} · {evidence.source.data.base_decision_interval} · {evidence.source.data.bar_4h_start.slice(0, 10)} — {evidence.source.data.bar_4h_end.slice(0, 10)} · 成本 {evidence.source.cost_model.base_cost_bps} bps</p>
    <div className="parameter-map-metrics" role="tablist" aria-label="热力图指标">{MAP_METRICS.map((item) => <button type="button" role="tab" key={item.key} aria-selected={metric === item.key} onClick={() => {setMetric(item.key); resetCell();}}>{item.label}</button>)}</div>
    <div className="parameter-map-controls">
      <label>策略公式 / 研究阶段<select aria-label="参数图策略公式" value={family} onChange={(event: SelectionEvent) => changeFamily(event.target.value)}>{families.map((value) => <option key={value} value={value}>{familyLabel(value)}</option>)}</select></label>
      <label>横轴<select aria-label="参数图横轴" value={x} onChange={(event: SelectionEvent) => {const value = event.target.value; setX(value); if (value === y) setY(x); resetCell();}}>{axes.map((key) => <option key={key} value={key}>{parameterLabel(key)}</option>)}</select></label>
      <label>纵轴<select aria-label="参数图纵轴" value={y} onChange={(event: SelectionEvent) => {const value = event.target.value; setY(value); if (value === x) setX(y); resetCell();}}>{axes.map((key) => <option key={key} value={key}>{parameterLabel(key)}</option>)}</select></label>
    </div>
    {variableKeys.length ? <details className="parameter-map-fixed"><summary>固定其他参数 · {variableKeys.length} 项可调整</summary><div>{variableKeys.map((key) => {
      const values = [...new Set(familyRows.map((row) => JSON.stringify(row.params[key])))];
      return <label key={key}>{parameterLabel(key)}<select aria-label={`固定参数 ${key}`} value={JSON.stringify(fixed[key]) ?? '__missing__'} onChange={(event: SelectionEvent) => {setFixed((prev) => ({...prev, [key]: event.target.value === '__missing__' ? undefined : JSON.parse(event.target.value)})); resetCell();}}>{values.map((value) => <option key={value ?? '__missing__'} value={value ?? '__missing__'}>{value ?? '未定义'}</option>)}</select></label>;
    })}</div></details> : null}
    <div className="parameter-map-legend"><span>低</span><i aria-hidden="true" /><span>高{metric === 'max_drawdown_pct' ? '（回撤更小）' : ''}</span><small>每格显示同一指标 · 缺失留空</small></div>
    {coupled ? <p className="parameter-map-context">公式联动：退出窗口 = 入场窗口的一半（向下取整），已逐行核验。其余参数固定。</p> : null}
    <p className="parameter-map-coverage" data-testid="parameter-map-coverage">当前切片 {available.length} / {slice.cells.length} 格有值 · 本公式 {familyRows.length} 组 · 全部发布 {evidence.coverage.published_count} / {evidence.coverage.declared_count} 组</p>
    {slice.cells.length ? <div className="parameter-map-scroll"><table className="parameter-map-grid" aria-label="参数稳定性热力图"><caption>{parameterLabel(y)} ↓ / {parameterLabel(x)} →</caption><thead><tr><th scope="col">{parameterLabel(y)} / {parameterLabel(x)}</th>{slice.xValues.map((value) => <th scope="col" key={value}>{value}</th>)}</tr></thead><tbody>{slice.yValues.map((yv) => <tr key={yv}><th scope="row">{yv}</th>{slice.cells.filter((cell) => cell.y === yv).map((cell) => <td key={cell.x}><button type="button" title={cellLabel(cell)} aria-label={cellLabel(cell)} aria-pressed={anchor?.x === cell.x && anchor?.y === cell.y} data-cell-status={cell.status} style={{background: fill(cell)}} onFocus={() => setActiveCell(cell)} onMouseEnter={() => setActiveCell(cell)} onClick={() => setActiveCell(cell)}>{cell.status === 'available' ? formatMapMetric(cell.value, metric) : cell.status === 'ambiguous' ? '重复' : '—'}</button></td>)}</tr>)}</tbody></table></div> : <div className="strategy-workbench-empty">没有可比较的二维参数切片。请选择两个不同的数值参数并固定其他参数。</div>}
    <section className="parameter-map-inspector" aria-live="polite" data-testid="parameter-map-inspector">{anchor ? <><strong>{parameterLabel(x)} = {anchor.x} · {parameterLabel(y)} = {anchor.y}</strong>{anchor.status === 'ambiguous' ? <p>该组合有多个结果；请细分条件。不会选取其中最高值。</p> : !anchor.rows.length ? <p>此固定条件下未发布该组合的回测；不插值、不补零。</p> : <><dl>{MAP_METRICS.map((item) => <div key={item.key}><dt>{item.label}</dt><dd>{formatMapMetric(anchor.rows[0].metrics[item.key], item.key)}</dd></div>)}</dl><code>{anchor.rows[0].candidate_id}</code></>}</> : <span>悬停、键盘聚焦或点击格子，查看该组合的四项指标。</span>}</section>
    <p className="parameter-map-warning">{evidence.relationship}。这是已参与选参的历史研究样本；颜色为当前切片内相对值，连续高值区域仍需样本外和成本压力验证。源行情未保留数据文件哈希，本快照只核验历史结果，尚不支持凭此证明可重放。</p>
    <details className="parameter-map-provenance"><summary>数据来源与固定条件</summary><p>报告时间：{evidence.source.generated_at} · 源代码：{evidence.source.code_commit}</p><p>快照 SHA-256：<code>{evidence.evidence_sha256}</code></p><p>源报告 SHA-256：<code>{evidence.source.report_sha256}</code></p><p>{evidence.source.execution_rule}</p><pre>{JSON.stringify(Object.fromEntries(otherKeys.map((key) => [key, fixed[key] ?? '未定义'])), null, 2)}</pre></details>
  </div>;
}
