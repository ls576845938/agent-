import {useEffect, useState} from 'react';
import {researchApi} from '../../lib/research-api';
import {Link} from 'react-router-dom';
import {frontendIdentity} from '../../frontendIdentity';
import {researchRunLink} from './research-run-links';
import TrendEnvironmentEvidence from './TrendEnvironmentEvidence';
import './qlib-trace.css';
import CandidateHandoff from './CandidateHandoff';

type Evidence = Record<string, any>;
const layers = [['alpha', 'Alpha / 预测'], ['regime', '市场状态'], ['risk', '风险模型'],
  ['allocation', '仓位分配'], ['position', '持仓管理'], ['exit', '退出机制'], ['execution', '执行与账本']];
const states: Record<string, string> = {passed:'已计算', completed:'已完成', blocked:'已阻断', unknown:'未知',
  not_run:'未执行', running:'进行中', dry_run:'仅检查', research_flow_completed:'研究流程完成', research_flow_blocked:'研究计算完成，下游受阻'};
const display = (value: unknown) => value == null ? '未知' : typeof value === 'number' ? Number(value.toPrecision(7)).toString() : String(value);
const truthLabels: Record<string,string> = {research_derived:'研究推导',research_derived_diagnostic:'历史诊断推导',research_simulated:'研究模拟'};
const safetyKeys = ['execution_permission','runtime_observed','promotion','paper','live','private','order','real_order','withdraw','transfer'];
export const qlibSafe = (detail: Evidence | null) => !!detail && !safetyKeys.some(key => detail[key] === true || detail.research_trace?.[key] === true);
export function QlibRunSummary({detail, runId, search='', showLink=true}: {detail: Evidence | null; runId: string; search?: string; showLink?: boolean}) {
  const matching = !!runId && detail?.summary?.run_id === runId;
  const verified = matching && detail?.integrity_status === 'passed' && qlibSafe(detail);
  const trace = verified && detail?.research_trace?.identity?.qlib_run_id === runId ? detail.research_trace : null;
  const sourceHead = verified ? detail?.seal?.source_head || trace?.identity?.source_head || detail?.summary?.source_head : '';
  const stale = verified && (detail?.source_stale === true || (!!sourceHead && sourceHead !== frontendIdentity.source_head));
  return <section className="qlib-trace qlib-run-summary" aria-label="研究运行概览" data-testid="qlib-run-summary">
    <header><div><small>RESEARCH RUN / 研究运行</small><h3>{runId || '尚未选择研究运行'}</h3></div><span className="qlib-trace-lock">真实执行未绑定 · 权限未解锁</span></header>
    {!verified ? <p role="status" className="qlib-trace-warning">{!runId ? '选择明确运行编号后查看结果。' : !matching ? '运行事实尚未匹配；不从其他运行补齐。' : !qlibSafe(detail) ? '安全合同异常，研究事实不可用。' : '证据完整性未通过，研究事实暂不可用。'} {matching && detail?.blockers?.join('；')}</p> : <>
      <p className="qlib-run-conclusion"><strong>{trace ? states[trace.status] || trace.status : '研究产物已封印 · 未生成七层决策记录'}</strong>
        {trace && <> · {trace.decision_count} 次决策 · {trace.simulated_fill_count} 笔研究模拟成交</>}</p>
      {!!trace?.blockers?.length && <p className="qlib-trace-warning">{trace.blockers.join('；')}</p>}
      <p className="qlib-trace-warning">{stale ? '源版本不同，不作 current-HEAD 证据。' : !sourceHead ? '源代码版本未知，不能认定为 current-HEAD 证据。' : '与当前页面代码版本一致；不代表晋级或交易权限通过。'}</p>
      {!trace && <p>Qlib 训练完成不等于工厂候选通过，也不等于决策回放或实际执行完成。</p>}
      {trace && <div className="qlib-metrics">
        <div><span>测试集时间序列 IC</span><strong>{display(detail?.signal_evaluation?.test?.time_series_ic)}</strong><small>原始分数；非实际交易收益</small></div>
        <div><span>研究模拟净收益</span><strong>{typeof trace.research_metrics?.net_return === 'number' ? (trace.research_metrics.net_return * 100).toFixed(2) + '%' : '未知'}</strong><small>含假设摩擦成本及历史资金费估算</small></div>
        <div><span>研究账本重算</span><strong>{states[trace.reconciliation?.status] || '未知'}</strong><small>非真实 OMS / 账本对账</small></div>
      </div>}
      <details className="qlib-version-details"><summary>版本、数据来源与研究产物</summary>
        <dl className="qlib-identity"><div><dt>策略版本 / 候选引用（不是晋级结论）</dt><dd>{trace?.identity?.strategy_version || '未知'} / {trace?.identity?.candidate_id || '未绑定'}</dd></div>
          <div><dt>市场与周期</dt><dd>{trace ? `${trace.identity.venue} · ${trace.identity.instrument} · ${trace.identity.bar_size}` : (detail?.summary?.symbols || []).join(', ') || '未知'}</dd></div>
          <div><dt>数据版本</dt><dd>{trace?.identity?.data_version || detail?.dataset_manifest?.data_version || '未知'}</dd></div>
          <div><dt>代码版本</dt><dd>{sourceHead || '未知'}</dd></div><div><dt>数据观测截止</dt><dd>{trace?.as_of || '未知'}（历史研究，不是实时行情）</dd></div></dl>
        {detail?.pipeline && <><p>以下为研究产物状态，不是七层决策，也不是工厂筛选结论。</p><ol className="qlib-stage-list" aria-label="Qlib 研究产物状态">{Object.entries(detail.pipeline.stages || {}).map(([key,value]: [string,any]) =>
          <li key={key} data-status={value.status}><strong>{key}</strong><span>{states[value.status] || value.status}</span></li>)}</ol></>}
      </details>
    </>}
    <TrendEnvironmentEvidence detail={detail} runId={runId} />
    {verified && <CandidateHandoff kind="qlib" runId={runId} detail={detail}/>}
    {showLink && runId && <Link className="research-detail-link" to={researchRunLink('qlib',runId,search)}>打开运行详情 / 决策回放 →</Link>}
  </section>;
}

export function QlibDecisionTrace({detail, runId}: {detail: Evidence | null; runId: string}) {
  const [decisionId, setDecisionId] = useState('');
  const trace = detail?.research_trace;
  const matching = !!runId && detail?.summary?.run_id === runId && trace?.identity?.qlib_run_id === runId;
  const verified = matching && detail?.integrity_status === 'passed' && qlibSafe(detail);
  const decisions: Evidence[] = verified ? detail?.decision_trace_preview || [] : [];
  const decision = decisions.find(row => `${runId}:${row.decision_id}` === decisionId) || decisions[decisions.length - 1];
  const evaluation = detail?.signal_evaluation;
  return <section className="qlib-trace" aria-label="研究决策回放" data-testid="qlib-decision-trace">
    <header><div><small>DECISION REPLAY / 研究模拟</small><h3>同一次决策，七层可追溯</h3></div><span className="qlib-trace-lock">真实执行未绑定 · 权限未解锁</span></header>
    <p>机制说明 ≠ 候选配置 ≠ 研究观测 ≠ 运行观测。此处只读取所选 run 的证据，不触发训练或交易。</p>
    {!verified ? <p role="status" className="qlib-trace-warning">{!runId ? '尚未选择研究运行。' : !matching ? '没有与此 run 精确匹配的七层研究记录；不能从其他运行补齐。' : !qlibSafe(detail) ? '安全合同异常，研究事实不可用。' : '证据完整性未通过，研究事实暂不可用。'} {detail?.summary?.run_id === runId && detail?.blockers?.join('；')}</p> : <>
      <label>决策时间（最近 48 条预览；完整记录保存在该 run）
        <select disabled={!decisions.length} value={decision ? `${runId}:${decision.decision_id}` : ''} onChange={(event: {target: HTMLSelectElement}) => setDecisionId(event.target.value)}>
          {!decisions.length && <option value="">没有可回放的决策记录</option>}
          {decisions.map(row => <option key={row.decision_id} value={`${runId}:${row.decision_id}`}>{row.decision_time} · {row.layers?.alpha?.expected_return_bps?.toFixed(2) ?? '未知'} bps</option>)}
        </select>
      </label>
      <div className="qlib-layer-grid">{layers.map(([key,label],index) => {
        const layer = decision?.layers?.[key];
        const values: Record<string, string[]> = {alpha:['raw_score','expected_return_bps','forecast_id'],regime:['regime','momentum_24h','regime_usage','funding_filter','oi_observation'],
          risk:['protection_truth_kind','risk_truth_kind'],allocation:['method','sizing_scope','target_weight','target_quantity','volatility_target_applied','production_perpetual_sizing_ready'],
          position:['quantity_before','average_entry','mark_price','cash','equity'],exit:['triggered','holding_bars','fill_policy'],
          execution:['fill_time','fill_price','quantity_delta','fee','runtime_status']};
        return <article key={key} data-status={layer?.status || 'unknown'}><header><h4>{index+1}. {label}</h4><span>{states[layer?.status] || '未知'}</span></header>
          <small>{truthLabels[layer?.truth_kind] || '证据类型未知'}；{key === 'execution' ? '真实 OMS / 账本未知' : '非运行观测'}</small>
          <dl>{values[key].map(field => <div key={field}><dt>{field}</dt><dd>{display(layer?.[field])}</dd></div>)}</dl>
          {!!layer?.blockers?.length && <p className="qlib-trace-warning">{layer.blockers.join('；')}</p>}
          {key === 'exit' && <p>{layer?.reasons?.join('；') || (layer?.triggered === false ? '本次未触发退出条件' : '退出证据未知')}</p>}
          {key === 'regime' && <p>市场状态是历史因果诊断，当前不作为仓位过滤条件。</p>}
          <details><summary>原始证据与关联 ID</summary><pre>{JSON.stringify(layer,null,2)}</pre></details>
        </article>;
      })}</div>
      <details><summary>候选配置、特征贡献与研究限制</summary><pre>{JSON.stringify({configured_research_risk:trace.configured_research_risk,features:evaluation?.feature_importance,
        calibration:trace.calibration,validation:evaluation?.validation,test:evaluation?.test,calibrated_test:evaluation?.calibrated_test,limitations:trace.limitations},null,2)}</pre></details>
      <p className="qlib-trace-warning">以上仓位分配为单资产风险预算，不是股票 PyPortfolioOpt，也没有实施波动率目标优化。真实风控、OMS、成交与账本仍以现有 BTC 运行链为权威。</p>
    </>}
  </section>;
}

export function QlibTraceExplorer() {
  const requested = new URLSearchParams(window.location.search).get('qlibRun') || '';
  const [runs,setRuns] = useState<Evidence[]>([]);
  const [runId,setRunId] = useState(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(requested) && requested !== 'latest' ? requested : '');
  const [detail,setDetail] = useState<Evidence | null>(null);
  const [error,setError] = useState('');
  useEffect(() => {let active=true; researchApi.listQlibRuns('artifacts/qlib_runs').then(payload => {if(active)setRuns(payload.runs || []);})
    .catch(error => {if(active)setError(String(error));});return () => {active=false;};},[]);
  useEffect(() => {let active=true;setDetail(null);setError('');if(runId)researchApi.getQlibRun(runId,'artifacts/qlib_runs')
    .then(payload=>{if(active)setDetail(payload);}).catch(error=>{if(active)setError(String(error));});return()=>{active=false;};},[runId]);
  return <section><h2>研究版本与决策证据入口</h2><p>独立选择准确研究版本；不自动绑定到下方已注册的 BTC 候选。完整回放在共享运行详情中查看。</p>
    <label>研究运行<select value={runId} onChange={(event: {target: HTMLSelectElement})=>setRunId(event.target.value)}><option value="">选择明确 run</option>
      {requested && !runs.some(run=>run.run_id===requested) && <option value={requested}>{requested}</option>}
      {runs.map(run=><option key={run.run_id} value={run.run_id}>{run.run_id} · {run.asset_class} · {run.bar_size}</option>)}</select></label>
    {error && <p role="alert">{error}</p>}<QlibRunSummary detail={detail?.summary?.run_id === runId ? detail : null} runId={runId}/></section>;
}
