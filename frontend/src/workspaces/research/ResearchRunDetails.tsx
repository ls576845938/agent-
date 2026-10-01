import {useEffect, useState} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {researchApi} from '../../lib/research-api';
import {alphaFactoryApi} from '../../lib/alpha-factory-api';
import {QlibDecisionTrace, QlibRunSummary, qlibSafe} from './QlibDecisionTrace';
import AlphaFactoryConsole from './AlphaFactoryConsole';
import {parseWorkspaceContext} from './workspace-links';
import {acquireResearchRunPageReads, runEvidenceErrors, versionEvidenceErrors} from './workspace-evidence';
import {DONCHIAN_OFFLINE_RUN, DONCHIAN_STAGE_RUN, researchRunLink, researchWorkspaceLink} from './research-run-links';
import OfflineExecutionSummary from './OfflineExecutionSummary';
import DonchianOfflineEvidence from './DonchianOfflineEvidence';
import DonchianStageEvidence from './DonchianStageEvidence';
import RegisteredCandidateOfflineEvidence from './RegisteredCandidateOfflineEvidence';
import {registeredOfflineId} from './candidate-offline-api';

type RecordLike = Record<string, any>;
export default function ResearchRunDetails() {
  const location = useLocation();
  const navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const parsed = parseWorkspaceContext(location.search);
  const factoryId = query.get('factoryRun') || '';
  const qlibId = parsed.context.qlibRun;
  const offlineId = query.get('offlineRun') || '';
  const errors = [...parsed.errors];
  if (query.getAll('factoryRun').length > 1) errors.push('重复的工厂运行引用。');
  if (query.getAll('offlineRun').length > 1) errors.push('重复的离线运行引用。');
  if (factoryId && (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(factoryId) || factoryId === 'latest')) errors.push('工厂运行引用无效。');
  if (factoryId && qlibId) errors.push('同时指定两类运行，无法确定详情来源；请明确选择一个。');
  if (offlineId && ![DONCHIAN_OFFLINE_RUN,DONCHIAN_STAGE_RUN].includes(offlineId) && !registeredOfflineId(offlineId)) errors.push('离线运行引用未登记。');
  if (offlineId && (factoryId || qlibId)) errors.push('同时指定多类运行，无法确定详情来源；请明确选择一个。');
  if (parsed.context.qlibRoot !== 'artifacts/qlib_runs') errors.push('Qlib 来源根目录不是服务器固定研究目录。');
  const [storedDetail, setDetail] = useState<RecordLike | null>(null);
  const [factoryDetail, setFactoryDetail] = useState<RecordLike | null>(null);
  const [factoryOverview, setFactoryOverview] = useState<RecordLike | null>(null);
  const [readError, setReadError] = useState('');
  const [listError, setListError] = useState('');
  const [runs, setRuns] = useState<{qlib: RecordLike[]; factory: RecordLike[]}>({qlib:[],factory:[]});
  const [loading, setLoading] = useState(false);
  const [offlineDetail, setOfflineDetail] = useState<RecordLike | null>(null);
  const [offlineError, setOfflineError] = useState('');
  const [offlineLoading, setOfflineLoading] = useState(false);
  const detail = storedDetail?.summary?.run_id === qlibId ? storedDetail : null;
  const contextIssues = detail?.integrity_status === 'passed' && qlibSafe(detail)
    ? versionEvidenceErrors(parsed.context, [detail.dataset_manifest,
      detail.research_trace?.identity?.qlib_run_id === qlibId ? detail.research_trace.identity : null].filter(Boolean)) : [];
  const offlineContextUnverified = offlineId && ['candidate','experiment','dataVersion','featureVersion','simulation','manifest','portfolioRun'].some(key => query.has(key));
  const valid = errors.length === 0;
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setOfflineDetail(null); setOfflineError(''); setOfflineLoading(false);
    if (!valid || !offlineId || registeredOfflineId(offlineId)) return () => {active=false;controller.abort();};
    setOfflineLoading(true);
    void researchApi.getDonchianOfflineRun(offlineId,{signal:controller.signal}).then(payload => {
      if (!active) return;
      const evidence=payload?.offline_evidence;
      const flags=['demo_control_enabled','execution_permission','live','order','paper','private',
        'promotion','real_order','runtime_observed','transfer','withdraw'];
      if (payload?.schema_version !== 'btc_strategy_registry_api_v1'
        || payload?.paper_queue_write_allowed !== false || payload?.live_unlock_allowed !== false
        || payload?.broker_or_order_allowed !== false || evidence?.selector !== offlineId
        || evidence?.read_only !== true || !flags.every(flag => evidence?.permissions?.[flag] === false)) {
        setOfflineError('离线封存的运行身份或安全合同不匹配；没有展示其他运行。');
      } else setOfflineDetail(evidence);
    }).catch(error => {
      if (active) setOfflineError(`离线证据读取失败：${String(error)}。不回退到其他运行。`);
    }).finally(() => {if (active) setOfflineLoading(false);});
    return () => {active=false;controller.abort();};
  },[offlineId,valid]);
  useEffect(() => {
    let active = true;
    setDetail(null); setFactoryDetail(null); setFactoryOverview(null); setRuns({qlib:[],factory:[]});
    setReadError(''); setListError(''); setLoading(false);
    if (!valid) return;
    const selectedKind = qlibId ? 'qlib' : factoryId ? 'factory' : 'none';
    const selectedId = qlibId || factoryId;
    const handle = acquireResearchRunPageReads(
      `${selectedKind}:${selectedId}`,
      qlibId ? () => researchApi.getQlibRun(qlibId,'artifacts/qlib_runs')
        : factoryId ? () => alphaFactoryApi.detail(factoryId) : null,
      () => researchApi.listQlibRuns('artifacts/qlib_runs'),
      () => alphaFactoryApi.overview(),
    );
    if (selectedId) setLoading(true);
    void handle.selected.then(result => {
      if (!active || !selectedId || !result) return;
      if (result.status === 'rejected') {
        setReadError(`所选运行不存在或读取失败：${String(result.reason)}。不回退到最新运行。`);
      } else if (qlibId) {
        if (runEvidenceErrors(qlibId,'artifacts/qlib_runs',result.value,'qlib','',{allowReadonlyM1Archive:true}).length) {
          setReadError('返回的运行身份或来源目录不匹配；没有展示其他运行。');
        } else setDetail(result.value);
      } else if (factoryId) {
        const unsafe = ['promotion','paper','live','private','order','real_order','transfer','withdraw','execution_permission','runtime_observed']
          .some(key => result.value?.[key] !== false);
        if (result.value?.run_id !== factoryId || unsafe) setReadError('返回的工厂运行身份或安全合同不匹配；没有展示其他运行。');
        else setFactoryDetail(result.value);
      }
    }).finally(() => {if(active) setLoading(false);});
    void handle.qlib.then(result => {
      if (!active) return;
      const qlib = result.status === 'fulfilled' && Array.isArray(result.value?.runs) ? result.value.runs : [];
      setRuns(current => ({...current, qlib}));
    });
    void handle.factory.then(result => {
      if (!active) return;
      const factory = result.status === 'fulfilled' && Array.isArray(result.value?.runs) ? result.value.runs : [];
      setRuns(current => ({...current, factory}));
      if (result.status === 'fulfilled') setFactoryOverview(result.value);
    });
    void Promise.all([handle.qlib,handle.factory]).then(([qlibRuns,factoryRuns]) => {
      if (!active) return;
      setListError(qlibRuns.status === 'rejected' || factoryRuns.status === 'rejected'
        ? '部分运行目录读取失败；可继续按明确编号读取，空目录不代表没有历史记录。' : '');
    });
    return () => {active=false;handle.release();};
  }, [factoryId, qlibId, offlineId, valid]);
  const selected = offlineId ? 'offline:' + offlineId : factoryId ? 'factory:' + factoryId : qlibId ? 'qlib:' + qlibId : '';
  const choices = [...runs.qlib.map(row=>({key:'qlib:'+row.run_id,label:'Qlib · '+row.run_id})), ...runs.factory.map(row=>({key:'factory:'+row.run_id,label:'Alpha 工厂 · '+row.run_id})),
    {key:'offline:'+DONCHIAN_OFFLINE_RUN,label:'Donchian · 五阶段离线封存'},
    {key:'offline:'+DONCHIAN_STAGE_RUN,label:'Donchian · 历史阶段基线（暂停）'}];
  return <div className="research-run-details" data-testid="research-run-details">
    <header className="research-run-heading"><div><span className="research-eyebrow">RUN DETAILS / 共享研究证据</span><h2>运行详情与决策回放</h2><p>研究结论、研究模拟、实际运行分开核验。此页只读，不启动训练、恢复或交易。</p></div>
      <Link to={researchWorkspaceLink(offlineId ? 'research-overview' : factoryId ? 'alpha-factory' : 'qlib',location.search)}>返回{offlineId ? ' 研究总览' : factoryId ? ' Alpha 工厂' : ' Qlib 手动实验'} →</Link></header>
    <label className="research-run-picker">研究运行<select aria-label="选择精确研究运行" value={selected} onChange={(event: {target:HTMLSelectElement}) => {
      const value=event.target.value; if (!value) return; const separator=value.indexOf(':');
      navigate(researchRunLink(value.slice(0,separator) as 'qlib'|'factory'|'offline',value.slice(separator+1),location.search));
    }}><option value="">选择明确运行，不自动读取 latest</option>
      {selected && !choices.some(row=>row.key===selected) && <option value={selected}>{selected}（按精确引用读取）</option>}
      {choices.map(row=><option key={row.key} value={row.key}>{row.label}</option>)}</select></label>
    {listError && <p role="status" className="research-footnote">{listError}</p>}
    {!valid ? <p role="alert" className="research-feedback error">{errors.join('；')} 未读取替代运行。</p> : <>
      {readError && <p role="alert" className="research-feedback error">{readError}</p>}
      {offlineError && <p role="alert" className="research-feedback error">{offlineError}</p>}
      {loading && <p role="status">正在读取 {qlibId || factoryId} 的封印证据…</p>}
      {offlineLoading && <p role="status">正在读取 {offlineId} 的提交态离线证据…</p>}
      {!!contextIssues.length && <p role="status" data-testid="run-context-warning" className="research-feedback">URL 上下文未核验 / 与封印 run 不符，以下只按封印 run 展示：{contextIssues.join('；')}。URL 参数不会改变原始运行事实。</p>}
      {offlineContextUnverified && <p role="status" data-testid="offline-context-warning" className="research-feedback">URL 中的候选、数据版本或其他上下文未与 Donchian 离线封存核验；仅以封存身份及证据为准。</p>}
      {!selected && <section className="research-intro-card"><h3>先选择一次运行</h3><p>可查看工厂批次的筛选结论，或独立 Qlib 研究及训练子试验。没有七层记录时明确显示未生成。</p><Link to="/research?view=alpha-factory">查看 Alpha 工厂</Link></section>}
      {factoryId && <AlphaFactoryConsole externalBusy={false} onWorking={() => undefined} readOnly readOnlyOverview={factoryOverview} readOnlyDetail={factoryDetail} />}
      {qlibId && <><QlibRunSummary detail={detail} runId={qlibId} showLink={false} /><OfflineExecutionSummary evidence={detail?.offline_execution} runId={qlibId} /><QlibDecisionTrace detail={detail} runId={qlibId} /></>}
      {offlineId === DONCHIAN_OFFLINE_RUN && !offlineError && <DonchianOfflineEvidence evidence={offlineDetail?.selector===offlineId ? offlineDetail : null} runId={offlineId} />}
      {offlineId === DONCHIAN_STAGE_RUN && !offlineError && <DonchianStageEvidence evidence={offlineDetail?.selector===offlineId ? offlineDetail : null} runId={offlineId} />}
      {registeredOfflineId(offlineId)&&<RegisteredCandidateOfflineEvidence key={offlineId} runId={offlineId}/>}
    </>}
    <section className="research-runtime-boundary" aria-label="实际运行证据"><strong>实际运行 · 未绑定</strong><p>本页未读取真实风控、OMS、成交或账户账本。不使用研究模拟补齐实际运行；执行安全页的受控运行证据仍为权威。</p></section>
  </div>;
}
