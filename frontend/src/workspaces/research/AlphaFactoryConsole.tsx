import {useEffect, useRef, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  acquireAlphaFactoryDetail,
  acquireAlphaFactoryOverview,
  alphaFactoryApi,
  alphaFactoryReadDeadlineMs,
  type FactoryRecord,
} from '../../lib/alpha-factory-api';
import {researchRunLink} from './research-run-links';
import {parseWorkspaceContext} from './workspace-links';
import {versionEvidenceErrors} from './workspace-evidence';
import './alpha-factory.css';
import CandidateHandoff from './CandidateHandoff';

const stages = [['data','数据核验'],['generate','生成 / 搜索'],['evaluate','评价 / 去相关'],['train','Qlib 训练'],['screen','筛选 / 审计'],['nominate','研究提名']];
const flags = ['promotion','paper','live','private','order','real_order','transfer','withdraw','execution_permission','runtime_observed'];
const safe = (value: FactoryRecord | null) => !!value && flags.every(key => value[key] === false);
const labels: Record<string,string> = {queued:'排队',running:'进行中',completed:'计算完成',not_run:'未运行',failed:'失败',
  blocked:'阻塞',interrupted:'中断，待恢复',rejected:'淘汰',exploratory_nomination:'探索性提名',
  research_candidate:'研究候选',awaiting_fresh_confirmation:'等待全新确认样本',passed:'已核验',unsealed_running:'运行中，尚未封印',not_run_selection_failed:'未执行（筛选未通过）',
  registered:'注册因子',template:'公式模板',genetic:'遗传搜索',evaluated:'已评价'};
const text = (value: unknown) => typeof value === 'string' ? labels[value] || value : '未知';
const metric = (value: unknown, digits=4) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '未知';
const percent = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `${(100 * value).toFixed(1)}%` : '未知';
const validRun = (value: string) => /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(value) && value !== 'latest';

export default function AlphaFactoryConsole({externalBusy, onWorking, readOnly=false, readOnlyOverview=null, readOnlyDetail=null,
  commandsDisabled=false, commandsDisabledReason=''}: {
  externalBusy: boolean;
  onWorking: (working: boolean)=>void;
  readOnly?: boolean;
  readOnlyOverview?: FactoryRecord | null;
  readOnlyDetail?: FactoryRecord | null;
  commandsDisabled?: boolean;
  commandsDisabledReason?: string;
}) {
  const [query, setQuery] = useSearchParams();
  const selected = query.get('factoryRun') || '';
  const [storedOverview, setOverview] = useState<FactoryRecord | null>(null);
  const [storedDetail, setDetail] = useState<FactoryRecord | null>(null);
  const overview = readOnly ? readOnlyOverview : storedOverview;
  const selectedDetail = readOnly ? readOnlyDetail : storedDetail;
  const detail = selectedDetail?.run_id === selected ? selectedDetail : null;
  const [profileId, setProfileId] = useState('okx_btc_trend_1h');
  const [budget, setBudget] = useState({population:12,generations:2,max_features:6,model_trials:2,seed:17});
  const [generators, setGenerators] = useState(['registered','template','genetic']);
  const [overviewError, setOverviewError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [actionError, setActionError] = useState('');
  const [posting, setPosting] = useState(false);
  const [filter, setFilter] = useState('all');
  const submitLock = useRef(false);
  const fetchSequence = useRef(0);
  const overviewSequence = useRef(0);
  const alive = useRef(true);
  const callback = useRef(onWorking); callback.current = onWorking;
  const profile = (overview?.profiles || []).find((p: FactoryRecord) => p.profile_id === profileId);
  const active = !!detail && ['running','queued'].includes(detail.status);
  const result = detail?.integrity_status === 'passed' && safe(detail) ? detail.result : null;
  const contextIssues = result ? versionEvidenceErrors(parseWorkspaceContext(query.toString()).context,
    [result.profile, result.lineage].filter(Boolean)) : [];
  const selectedIdentityMatches = detail?.run_id === selected;
  const candidates = result?.candidates || [];
  const visibleEvents = safe(detail) && ['passed','unsealed_running'].includes(detail?.integrity_status) ? detail?.events || [] : [];
  const modelTrials = result?.model_trials || visibleEvents.findLast?.((event: FactoryRecord) => event.stage === 'train' && event.status === 'completed')?.detail?.model_trials || [];
  const factorTrials = result?.factor_search?.trials || visibleEvents.filter((event: FactoryRecord) => event.stage === 'generate' && event.status === 'trial').map((event: FactoryRecord) => event.detail) || [];
  const selectedFactorIds = new Set<string>((result?.factor_specs || []).map((spec: FactoryRecord) => spec.factor_id));
  const selectionRejections = result?.factor_search?.selection_rejections || [];
  const error = actionError || detailError || overviewError;
  const validateOverview = (value: FactoryRecord) => {
    if (!safe(value) || !Array.isArray(value.profiles) || !Array.isArray(value.runs)) throw new Error('控制台合同或安全旗标异常，操作已锁定。');
    return value;
  };
  const loadOverview = async () => {
    const lease = acquireAlphaFactoryOverview();
    try {
      const value = validateOverview(await lease.promise);
      if (alive.current) {setOverview(value);setOverviewError('');}
      return value;
    } finally {
      lease.release();
    }
  };
  useEffect(() => {
    const sequence = ++overviewSequence.current;
    let effectActive = true;
    alive.current = true;
    setOverviewError('');
    const lease = readOnly ? null : acquireAlphaFactoryOverview();
    if (lease) void lease.promise.then(value => {
      const validated = validateOverview(value);
      if (effectActive && overviewSequence.current === sequence) {setOverview(validated);setOverviewError('');}
    }).catch(e => {
      if(effectActive && overviewSequence.current === sequence) {setOverview(null);setOverviewError(String(e));}
    });
    return () => {
      effectActive = false;
      lease?.release();
      if (overviewSequence.current === sequence) alive.current = false;
      callback.current(false);
    };
  }, [readOnly]);
  useEffect(() => {
    const sequence = ++fetchSequence.current;
    setDetail(null); setDetailError('');
    if (readOnly) return;
    if (!selected) return;
    if (!validRun(selected)) {setDetailError('运行引用无效；未读取其他路径。');return;}
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const initialReadStartedAt = performance.now();
    let detailLease: ReturnType<typeof acquireAlphaFactoryDetail> | null = null;
    const overviewLease = storedOverview ? null : acquireAlphaFactoryOverview();
    let observedActive = !!storedOverview?.runs?.some(
      (row: FactoryRecord) => row.run_id === selected && ['running','queued'].includes(row.status),
    );
    const poll = async (deadlineMs=alphaFactoryReadDeadlineMs) => {
      detailLease = acquireAlphaFactoryDetail(selected, deadlineMs);
      try {
        const value = await detailLease.promise;
        if (stopped || fetchSequence.current !== sequence) return;
        if (!safe(value) || value.run_id !== selected) throw new Error('运行身份或安全合同不匹配。');
        setDetail(value);setDetailError('');
        if (['running','queued'].includes(value.status)) {observedActive = true;timer = setTimeout(poll, 2000);}
        else if (observedActive) void loadOverview().catch(e => {if(alive.current) setOverviewError(String(e));});
      } catch (e) {
        if(!stopped && fetchSequence.current === sequence) {setDetail(null);setDetailError(String(e));}
      } finally {
        detailLease?.release();detailLease = null;
      }
    };
    if (overviewLease) void overviewLease.promise.then(value => {
      observedActive = !!value.runs?.some(
        (row: FactoryRecord) => row.run_id === selected && ['running','queued'].includes(row.status),
      );
    }).catch(() => undefined).finally(() => {
      overviewLease.release();
      if (stopped || fetchSequence.current !== sequence) return;
      const remainingMs = alphaFactoryReadDeadlineMs - (performance.now() - initialReadStartedAt);
      if (remainingMs <= 0) {
        setDetailError(`Alpha 工厂详情未在 ${alphaFactoryReadDeadlineMs}ms 页面预算内启动。`);
        return;
      }
      void poll(remainingMs);
    });
    else void poll();
    return () => {stopped = true;overviewLease?.release();detailLease?.release();clearTimeout(timer);};
  }, [readOnly, selected]);
  useEffect(() => {callback.current(posting || active);}, [posting, active]);
  const chooseRun = (runId: string) => {
    if (!validRun(runId)) return;
    const next = new URLSearchParams(query);next.set('view','alpha-factory');next.set('factoryRun',runId);setQuery(next);
  };
  const invalidBudget = !Object.entries(budget).every(([key,value]) => Number.isInteger(value) && value >= (key === 'seed' ? 0 : key === 'population' ? 4 : 1)
    && value <= ({population:32,generations:4,max_features:12,model_trials:3,seed:2147483647}[key as keyof typeof budget]));
  const run = async (resume=false) => {
    if (readOnly || commandsDisabled || submitLock.current || externalBusy || posting || active || !safe(overview)) return;
    if (!resume && (!profile?.training_enabled || !safe(profile) || invalidBudget || !generators.length)) return;
    if (resume && (!selectedIdentityMatches || detail?.source_stale || !detail?.recovery?.explicit_resume_required || detail?.integrity_status === 'blocked')) return;
    submitLock.current = true;setPosting(true);setActionError('');
    try {
      const receipt = resume ? await alphaFactoryApi.resume(selected) : await alphaFactoryApi.submit({
        profile_id:profileId,run_id:'af-'+crypto.randomUUID().replaceAll('-',''),...budget,generators});
      if(!safe(receipt) || !validRun(receipt.run_id)) throw new Error('提交回执无效，请刷新运行记录；不要盲目重试。');
      chooseRun(receipt.run_id);
    } catch(e) {setActionError(String(e));}
    finally {submitLock.current = false;setPosting(false);}
  };
  return <div className={'alpha-factory' + (readOnly ? ' af-readonly' : '')} data-testid="alpha-factory-console">
    {!readOnly && <header className="af-heading"><div><span className="af-kicker">SHARED ALPHA FACTORY</span><h3>统一 Alpha 工厂</h3>
      <p>生成 → Qlib 训练 → 样本外筛选 → 研究提名。一套引擎，按市场注入数据与规则。</p></div>
      <span className="af-safety">研究专用 · paper / live / order 未授权</span></header>}
    {!readOnly && commandsDisabled && <p className="af-warning" role="status">{commandsDisabledReason || '后端模式未授予研究写入；可刷新和查看已有证据。'}</p>}
    {error && <p className="af-error" role="alert">{error}</p>}
    {!!contextIssues.length && <p role="status" data-testid="run-context-warning" className="af-warning">URL 上下文未核验 / 与封印 run 不符，以下只按封印 run 展示：{contextIssues.join('；')}。工厂未提供 feature_version 合同时不能确认该特征版本引用；URL 参数不会改变原始运行事实。</p>}
    {!readOnly && <details className="af-new-batch"><summary>新建研究批次 · 市场与参数配置</summary><div className="af-controls">
    <div className="af-capabilities" aria-label="跨市场能力">
      {(overview?.profiles || []).map((p: FactoryRecord) => <button key={p.profile_id} type="button" aria-pressed={profileId === p.profile_id}
        disabled={commandsDisabled || posting || active || externalBusy} onClick={()=>setProfileId(p.profile_id)}>
        <strong>{p.label}</strong><span>{p.training_enabled ? '研究输入已绑定' : '数据 / 合同未就绪'}</span>
        <small>{p.metric_mode === 'time_series' ? '时序评价' : p.metric_mode === 'cross_sectional' ? '横截面评价' : '评价合同待注册'}</small>
      </button>)}
      {!overview && <p>能力状态未读取，不能判断可用性或提交任务。</p>}
    </div>
      <section><h4>新建有界研究批次</h4><p>{profile?.label || '未选择已核验配置'}</p>
        <dl><dt>日历 / 周期</dt><dd>{profile?.calendar || '未知'} / {profile?.bar_size || '未知'}</dd>
          <dt>数据版本</dt><dd>{profile?.data_version || '尚未绑定'}</dd>
          <dt>确认样本</dt><dd>历史已查看数据仅可探索性提名</dd></dl>
        {profile?.blockers?.length > 0 && <div className="af-blocked"><strong>该市场暂不能启动</strong><ul>{profile.blockers.map((reason:string)=><li key={reason}>{reason}</li>)}</ul></div>}
        <fieldset disabled={commandsDisabled || posting || active || externalBusy}><legend>生成来源</legend>
          {['registered','template','genetic'].map(item=><label key={item}><input type="checkbox" checked={generators.includes(item)} onChange={(e: {target: HTMLInputElement})=>setGenerators(old=>e.target.checked ? [...old,item] : old.filter(x=>x!==item))}/>{text(item)}</label>)}
        </fieldset>
        <div className="af-budget">{([['population','每代种群',4,32],['generations','遗传代数',1,4],['max_features','最多保留因子',1,12],['model_trials','模型配置数',1,3],['seed','随机种子',0,2147483647]] as const).map(([key,label,min,max])=>
          <label key={key}>{label}<input type="number" min={min} max={max} value={budget[key]} disabled={commandsDisabled || posting || active || externalBusy}
            onChange={(e: {target: HTMLInputElement})=>setBudget(old=>({...old,[key]:Number(e.target.value)}))}/></label>)}</div>
        <p className="af-note">每个模型配置执行 4 折滚动验证；冠军冻结后仅作一次末段审计。单次有限批次，不启动无限后台搜索。</p>
        <button className="af-primary" disabled={commandsDisabled || !safe(overview) || !profile?.training_enabled || !safe(profile) || invalidBudget || !generators.length || posting || active || externalBusy}
          onClick={()=>void run()}>{posting ? '提交中…' : active ? '研究计算进行中' : '启动统一研究批次'}</button>
      </section></div></details>}
    <div className="af-grid">
      {!readOnly && <aside className="af-controls"><section><div className="af-row"><h4>持久运行记录</h4><button disabled={posting} onClick={()=>{setOverviewError('');void loadOverview().catch(e=>setOverviewError(String(e)));}}>刷新</button></div>
        {(overview?.runs || []).map((row: FactoryRecord)=><button className="af-run" key={row.run_id} aria-pressed={selected===row.run_id} onClick={()=>chooseRun(row.run_id)}>
          <strong>{row.run_id}</strong><span>{row.profile_id} · {text(row.status)}</span><small>{text(row.decision)}{row.source_stale ? ' · 代码版本已变化' : ''}</small></button>)}
        {overview && !overview.runs.length && <p className="af-note">暂无工厂运行。旧 Qlib 固定特征实验不冒充工厂结果。</p>}
      </section></aside>}
      <main className="af-evidence">
        {!selected && <section className="af-empty"><h4>选择一次运行，沿同一证据链检查结果</h4><p>这里将显示全部因子、模型试验、淘汰原因和候选。数据缺失或未计算时显示未知，不填演示曲线。</p></section>}
        {selected && <><section data-testid="factory-run-conclusion"><div className="af-row"><div><h4>{selected}</h4><p>{detail ? text(detail.status) : '正在读取 / 尚未核验'} · {text(detail?.integrity_status)}</p></div>
          {!readOnly && detail?.recovery?.explicit_resume_required && <button disabled={commandsDisabled || posting || externalBusy || detail.source_stale || detail.integrity_status==='blocked'} onClick={()=>void run(true)}>校验封印并显式恢复</button>}</div>
          {result && <div className="af-facts"><div><span>筛选结论</span><strong>{text(result.decision)}</strong></div><div><span>研究候选</span><strong>{candidates.length}</strong></div><div><span>Qlib 拟合 / 末段审计</span><strong>{result.qlib_fit_count ?? '未知'} / {text(result.audit_status)}</strong></div></div>}
          <p className="af-note">运行配置 {detail?.profile_id || '未知'} · 代码 {detail?.source_head?.slice(0,12) || '未知'}{detail?.source_stale ? '（源版本不同，不作 current-HEAD 证据）' : ''}</p>
          <ol className="af-stages">{stages.map(([key,label])=>{const status=safe(detail) && ['passed','unsealed_running'].includes(detail?.integrity_status) ? detail?.stages?.[key] || 'not_run' : 'unknown';return <li key={key} data-status={status}><strong>{label}</strong><span>{text(status)}</span></li>;})}</ol>
          {!!detail?.blockers?.length && <div className="af-blocked"><strong>阻塞 / 未通过原因</strong><ul>{detail.blockers.map((b:string)=><li key={b}>{b}</li>)}</ul></div>}
          <p className="af-note">“计算完成”不等于 Alpha 有效；恢复会新建关联 attempt，复用已封印训练，不覆盖原失败记录。</p>
          {!readOnly && <a className="research-detail-link" href={researchRunLink('factory',selected,query.toString())}>打开批次运行详情 →</a>}
        </section>
        {result && <section><h4>输入与时间隔离</h4><div className="af-facts"><div><span>因子提案 / 独立表达式</span><strong>{result.factor_search?.trial_count} / {result.factor_search?.unique_expression_count}</strong></div>
          <div><span>模型配置 / Qlib 拟合</span><strong>{result.model_trials?.length} / {result.qlib_fit_count ?? '未完成'}</strong></div><div><span>候选结论</span><strong>{text(result.decision)}</strong></div></div>
          <p>数据截止 {result.lineage?.as_of || '未知'} · {result.profile?.metric_mode} · purge {result.split_plan?.purge_bars} 根</p>
          <div className="af-table"><table><thead><tr><th>窗口</th><th>开始</th><th>结束</th><th>用途</th></tr></thead><tbody>{Object.entries(result.split_plan?.segments || {}).map(([key,value])=><tr key={key}><td>{key}</td><td>{(value as string[])[0]}</td><td>{(value as string[])[1]}</td><td>{({train:'生成 / 去相关',valid:'早停验证',selection:'模型选择 / 滚动验证',audit:'只审计，不重新挑冠军'} as Record<string,string>)[key]}</td></tr>)}</tbody></table></div>
          <p className="af-warning">历史回看，非确认性样本外。OI / 清算等未绑定字段不可用；资金费字段还需满足训练窗口覆盖。</p>
          <details><summary>不可用字段与完整输入身份</summary><pre>{JSON.stringify({unavailable_primitives:result.unavailable_primitives,unavailable_fields:result.profile?.unavailable_fields,input_hash:result.lineage?.input_sha256,source_manifest:result.lineage?.source_manifest},null,2)}</pre></details>
        </section>}
        {!!modelTrials.length && <section><h4>模型试验与成本筛选</h4><p className="af-note">Rank IC / HAC 检验经 BY-FDR 校正；成本为预测边际诊断，不是成交账本收益。</p><div className="af-table"><table><thead><tr><th>模型</th><th>状态</th><th>选择段 Rank IC</th><th>BY 调整 p</th><th>一致折数</th><th>保守成本净边际 bps</th><th>结论</th></tr></thead><tbody>{modelTrials.map((row: FactoryRecord)=><tr key={row.trial_number}><td>{row.model_id}</td><td>{text(row.status)}</td><td>{metric(row.selection_metrics?.rank_ic)}</td><td>{metric(row.fdr_adjusted_p)}</td><td>{row.consistent_folds ?? '未知'} / 4</td><td>{metric(row.cost_diagnostics?.conservative?.forecast_net_edge_bps,2)}</td><td>{row.error || row.screen_blockers?.join('; ') || '等待最终筛选'}</td></tr>)}</tbody></table></div>
          <details><summary>逐折 Qlib 运行、环境旁路与封印</summary><p>训练子试验只证明训练结果；不代表工厂候选通过或七层决策已生成。环境旁路不参与本页筛选或排名。</p>{modelTrials.flatMap((row:FactoryRecord)=>row.qlib_runs || []).map((ref:FactoryRecord)=><p key={ref.qlib_run_id}><a href={researchRunLink('qlib',ref.qlib_run_id)}>{ref.qlib_run_id}</a> · {ref.seal_sha256?.slice(0,16)} · 环境旁路：{ref.environment_observation?.run_id === ref.qlib_run_id ? text(ref.environment_observation.status) : '旧运行无环境证据'}</p>)}</details>
        </section>}
        {!!factorTrials.length && <section><div className="af-row"><h4>全部因子提案 · {factorTrials.length}</h4><label>来源筛选 <select value={filter} onChange={(e: {target: HTMLSelectElement})=>setFilter(e.target.value)}><option value="all">全部</option>{['registered','template','genetic'].map(key=><option key={key} value={key}>{text(key)}</option>)}</select></label></div>
          <p className="af-note">换手是归一化因子信号的变化，不是订单换手。Rank ICIR 为分块 Rank IC 的均值 / 标准差，未年化；筛选和相关性仅使用训练段。</p><div className="af-table"><table><thead><tr><th>提案 / 来源</th><th>训练 IC</th><th>训练 Rank IC</th><th>Rank ICIR</th><th>信号换手</th><th>覆盖率</th><th>保留 / 淘汰原因</th></tr></thead><tbody>{factorTrials.filter((row:FactoryRecord)=>filter==='all'||row.origin===filter).map((row:FactoryRecord)=><tr key={row.trial_number}><td><details><summary>#{row.trial_number} {text(row.origin)} · {row.name}</summary><code>{JSON.stringify(row.expression)}</code><p>{row.factor_id}</p></details></td><td>{metric(row.metrics?.ic)}</td><td>{metric(row.metrics?.rank_ic)}</td><td>{metric(row.metrics?.icir)}</td><td>{metric(row.metrics?.factor_signal_turnover)}</td><td>{percent(row.metrics?.coverage)}</td><td>{row.reason || (selectedFactorIds.has(row.factor_id) ? '保留为训练特征' : selectionRejections.find((r:FactoryRecord)=>r.factor_id===row.factor_id)?.reason) || '已评价，等待筛选'}</td></tr>)}</tbody></table></div>
        </section>}
        {!!candidates.length && <section><h4>冻结候选与最终审计</h4>{candidates.map((row:FactoryRecord)=><article key={row.candidate_id} className="af-candidate"><strong>{text(row.status)}</strong><p>{row.candidate_id}</p><div className="af-facts"><div><span>审计 Rank IC</span><strong>{metric(row.audit_metrics?.rank_ic)}</strong></div><div><span>审计方向命中</span><strong>{percent(row.audit_metrics?.direction_hit_rate)}</strong></div><div><span>确认性样本</span><strong>{row.gate?.confirmatory_holdout ? '已绑定' : '否 · 历史回看'}</strong></div></div>
          <p>{row.gate?.blockers?.join('; ') || '仅通过研究提名，不是交易晋级。'}</p><a href={researchRunLink('qlib',row.qlib_run_id)}>查看实际 Qlib 冠军运行</a>
          <details><summary>研究策略配置及下一阶段证据要求</summary><pre>{JSON.stringify({strategy_config:row.strategy_config,required_next_evidence:row.gate?.required_next_evidence},null,2)}</pre></details>
          <CandidateHandoff kind="factory" runId={selected} detail={detail} candidateId={row.candidate_id}/></article>)}</section>}
        {result && !candidates.length && <p className="af-note">本批次没有生成研究候选，不能准备部署交接；不使用训练子试验替代。</p>}
        {visibleEvents.length > 0 && <details className="af-event-log"><summary>追加式阶段记录 · {detail?.event_count || 0}</summary>{visibleEvents.slice(-40).map((event:FactoryRecord)=><p key={event.sequence}>#{event.sequence} {event.time} · {event.stage} / {text(event.status)} · {event.event_hash?.slice(0,12)}</p>)}</details>}
        </>}
      </main>
    </div>
  </div>;
}
