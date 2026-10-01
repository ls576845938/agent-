import {useState} from 'react';

type Evidence = Record<string, any>;
const flags = ['execution_permission','runtime_observed','promotion','paper','live','private','order','real_order','transfer','withdraw'];
const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(4) : '未知';
const direction: Record<string,string> = {up:'向上',down:'向下',flat:'无方向'};

/** This component accepts only the exact run's sealed API projection. Never computes a state. */
export default function TrendEnvironmentEvidence({detail, runId}: {detail: Evidence | null; runId: string}) {
  const [selection, setSelection] = useState('');
  const evidence = detail?.trend_environment;
  const trusted = !!runId && detail?.summary?.run_id === runId && detail?.integrity_status === 'passed'
    && evidence?.identity?.run_id === runId && evidence?.schema_version === 'trend_environment_evidence_v1'
    && evidence?.usage === 'observation_only' && flags.every(key => evidence[key] === false && detail[key] !== true && detail.research_trace?.[key] !== true);
  const complete = trusted && evidence.status === 'completed';
  const rows: Evidence[] = complete ? evidence.preview || [] : [];
  const key = (row: Evidence) => `${runId}|${row.asset}|${row.decision_time}`;
  const options = [...new Map(rows.map(row => [key(row), row])).entries()];
  const selected = options.some(([id]) => id === selection) ? selection : options.at(-1)?.[0];
  const selectedRows = rows.filter(row => key(row) === selected);
  return <details className="qlib-version-details" data-testid="trend-environment-evidence">
    <summary>共享趋势环境 · M1 旁路观测 · {complete ? '已记录' : trusted && evidence.status === 'blocked' ? '观测受阻' : trusted && evidence.status === 'disabled' ? '未启用' : '无可核验证据'}</summary>
    <p>仅历史研究观测，不参与训练特征、工厂筛选、仓位或退出；不是实时市场状态，不授予交易权限。</p>
    {!complete ? <p role="status">{trusted ? (evidence.blockers || []).join('；') || '本次旁路未启用。' : '旧运行无环境证据或所选运行未匹配；不会自动补算，也不会借用其他 run。'}</p> : <>
      <p className="qlib-trace-warning">{evidence.source_stale ? '源代码版本不同，不作 current-HEAD 证据。' : '当前代码版本的历史观测，非运行时事实。'} 可见时间：{evidence.availability_semantics}</p>
      <label>环境观测时间与资产<select value={selected || ''} onChange={(event: {target: HTMLSelectElement}) => setSelection(event.target.value)}>
        {options.map(([id,row]) => <option key={id} value={id}>{row.asset} · {row.decision_time}</option>)}
      </select></label>
      <div className="qlib-layer-grid">{selectedRows.map(row => <article key={row.horizon_bars}>
        <h4>{row.horizon_bars} 根 K 线 · {row.calendar}</h4>
        {row.status !== 'observed' ? <p>未知：{row.reasons?.join('；')}</p> : <dl>
          <div><dt>趋势方向</dt><dd>{direction[row.direction] || '未知'}</dd></div>
          <div><dt>趋势适配度（描述分数，非概率）</dt><dd>{number(row.trend_fit)}</dd></div>
          <div><dt>单根收益波动</dt><dd>{number(row.bar_volatility)}</dd></div>
          <div><dt>冲击分数</dt><dd>{number(row.shock_score)}</dd></div>
          <div><dt>状态变化分数</dt><dd>{number(row.transition_score)}</dd></div>
        </dl>}
        {!!row.reasons?.length && row.status === 'observed' && <p>{row.reasons.join('；')}</p>}
      </article>)}</div>
      <details><summary>同版本来源与证据指纹</summary><pre>{JSON.stringify({identity:evidence.identity,
        model_version:evidence.model_version,config:evidence.config,config_hash:evidence.config_hash,
        evidence_sha256:evidence.evidence_sha256,context:evidence.context,counts:evidence.observation_counts},null,2)}</pre></details>
    </>}
  </details>;
}
