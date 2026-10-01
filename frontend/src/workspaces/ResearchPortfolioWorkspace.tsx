import {QlibRunSummary} from './research/QlibDecisionTrace';
import AlphaFactoryConsole from './research/AlphaFactoryConsole';
import ResearchRunDetails from './research/ResearchRunDetails';
import {researchWorkspaceLink} from './research/research-run-links';
import {useEffect, useMemo, useRef, useState} from 'react';

import {LoadingSpinner} from '../components/LoadingSpinner';
import {useLocation, useNavigate, Link} from 'react-router-dom';
import {runEvidenceErrors, versionEvidenceErrors, simulationEvidenceErrors, portfolioConfigMatches, completeLegacySnapshot, reviewSourceEligible, firstTargetImportAllowed} from './research/workspace-evidence';
import {parseWorkspaceContext, workspaceLink, referenceErrors, type WorkspaceSurface, type WorkspaceContext} from './research/workspace-links';
import {createResearchActions} from './research-actions';
import {createPortfolioActions} from './portfolio-actions';
import {createReviewActions} from './review-actions';
import PortfolioOverview from './portfolio/PortfolioOverview';
import {ResearchNavigation, ResearchOverview, ResearchContext, navigateTabs} from './research/ResearchWorkbench';
import './research/ResearchDashboard.css';
import {apiGet} from '../lib/api';
import {researchWorkspaceAccess, type ResearchWorkspaceAccess, type ResearchWorkspaceHealth} from '../lib/research-workspace-access';
import {researchApi} from '../lib/research-api';
import {
  acquireResearchRead,
  classifyResearchReadError,
  summarizeResearchRegistry,
  type ResearchReadFailure,
  type ResearchReadLease,
} from '../lib/research-read-request';
import {taskApi} from '../lib/task-api';
import type {SystemOverviewResponse, TaskResponse} from '../lib/shared-types';
import ExperimentList from './research/ExperimentList';
import CandidateTable from './research/CandidateTable';
import ExperimentReport from './research/ExperimentReport';
import ExperimentCompare from './research/ExperimentCompare';
import TaskQueuePanel from '../components/TaskQueuePanel';
import {
  WorkbenchFrame,
  WorkbenchHeader,
  WorkbenchNotice,
  WorkbenchPanel,
} from '../components/workbench/Workbench';

type LooseRecord = Record<string, any>;

interface Experiment {
  experiment_id: string;
  strategy_id: string;
  strategy_family: string;
  symbols: string[];
  status: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

interface Candidate {
  candidate_id: string;
  experiment_id: string;
  strategy_id: string;
  symbols?: string[];
  timeframe?: string;
  data_source?: string;
  asset_class?: string;
  promotion_status: string;
  robustness_score?: number;
  overfit_score?: number;
  alpha_score?: number;
  risk_score?: number;
  turnover_score: number;
  backtest_manifest_path?: string;
  scorecard_path?: string;
  walk_forward_result_path?: string;
  cost_stress_result_path?: string;
  metrics?: LooseRecord;
  created_at: string;
}

const inputStyle = {
  width: '100%',
  minWidth: 0,
  padding: '8px 10px',
  borderRadius: 3,
  border: '1px solid rgba(91,111,142,0.56)',
  background: '#09111d',
  color: '#dbe7f5',
  outline: 'none',
} as const;

const labelStyle = {
  display: 'grid',
  gap: 6,
  fontSize: '0.78rem',
  color: '#7f93ad',
} as const;

const buttonStyle = {
  border: '1px solid rgba(79,124,255,0.54)',
  background: 'rgba(79,124,255,0.18)',
  color: '#a8bdff',
  borderRadius: 3,
  padding: '8px 12px',
  fontWeight: 650,
  cursor: 'pointer',
} as const;

const ghostButtonStyle = {
  ...buttonStyle,
  border: '1px solid rgba(91,111,142,0.56)',
  background: '#101a2a',
  color: '#c7d4e5',
} as const;

const dangerButtonStyle = {
  ...buttonStyle,
  border: '1px solid rgba(255,93,108,0.48)',
  background: 'rgba(255,93,108,0.13)',
  color: '#ff8390',
} as const;

const sectionStyle = {
  border: '1px solid #263247',
  background: '#0d1420',
  borderRadius: 2,
  padding: 16,
  boxShadow: '0 12px 24px rgba(0,0,0,0.14)',
} as const;

function splitCsv(value: string): string[] {
  return value.split(',').map(item => item.trim().toUpperCase()).filter(Boolean);
}

function parseJsonObject(value: string, fallback: LooseRecord = {}): LooseRecord {
  const trimmed = value.trim();
  if (!trimmed) return fallback;
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON 必须是对象');
  }
  return parsed;
}

function isActiveTask(task: TaskResponse | null): boolean {
  return !!task && (task.status === 'queued' || task.status === 'running');
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => { setTimeout(resolve, ms); });
}

function withTimeout<T>(promise: Promise<T>, fallback: T, ms = 4500): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((resolve) => {
    timer = setTimeout(() => resolve(fallback), ms);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

function fmt(value: unknown, digits = 2): string {
  if (typeof value === 'number' && Number.isFinite(value)) return value.toFixed(digits);
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'boolean') return value ? '是' : '否';
  return '-';
}

function pct(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(1)}%`;
}

function asRecord(value: unknown): LooseRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as LooseRecord : null;
}

function asArray(value: unknown): LooseRecord[] {
  return Array.isArray(value) ? value.map(item => asRecord(item)).filter((item): item is LooseRecord => !!item) : [];
}

function readString(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function tone(status?: string): string {
  const normalized = String(status || '').toUpperCase();
  if (['COMPLETED', 'READY_FOR_PAPER_REVIEW', 'READY_FOR_REVIEW', 'PASS', 'PASSED', 'READY_FOR_PORTFOLIO_SIM'].includes(normalized)) {
    return '#22c55e';
  }
  if (['FAILED', 'BLOCKED', 'REJECTED', 'FAIL', 'ERROR'].includes(normalized)) {
    return '#ef4444';
  }
  if (['WATCHLIST', 'NEED_MORE_RESEARCH', 'PENDING_HUMAN_REVIEW', 'RUNNING'].includes(normalized)) {
    return '#eab308';
  }
  return '#94a3b8';
}

const statusLabels: Record<string, string> = {
  COMPLETED: '完成',
  READY_FOR_PAPER_REVIEW: '可进入纸交易复核',
  READY_FOR_REVIEW: '可复核',
  READY_FOR_PORTFOLIO_SIM: '可进入组合模拟',
  READY_FOR_BACKTEST_ENTRY: '可进入回测',
  PAPER_ELIGIBLE: '纸交易合格',
  PAPER_REVIEW_CANDIDATE: '纸交易复核候选',
  PASS: '通过',
  PASSED: '通过',
  FAILED: '失败',
  BLOCKED: '阻塞',
  REJECTED: '拒绝',
  FAIL: '失败',
  ERROR: '错误',
  WATCHLIST: '观察',
  NEED_MORE_RESEARCH: '需继续研究',
  PENDING_HUMAN_REVIEW: '待人工复核',
  RUNNING: '运行中',
  QUEUED: '排队中',
  PENDING: '待处理',
  MISSING: '缺失',
  MISSING_TARGET_POSITIONS: '缺少目标持仓',
  UNKNOWN: '未知',
  EMPTY: '空',
  LOCKED: '锁定',
  INSTALLED: '已安装',
  FALLBACK: '降级',
};

function statusLabel(value: string) {
  return statusLabels[value.trim().replace(/\s+/g, '_').toUpperCase()] ?? value;
}

function StatusPill({value}: {value?: string}) {
  const label = value || '-';
  const displayLabel = statusLabel(label);
  return (
    <span style={{
      color: tone(label),
      border: `1px solid ${tone(label)}55`,
      background: `${tone(label)}18`,
      borderRadius: 999,
      padding: '3px 8px',
      fontSize: '0.74rem',
      fontWeight: 700,
      whiteSpace: 'nowrap',
    }}>
      {displayLabel}
    </span>
  );
}

function Field({label, children}: {label: string; children: any}) {
  return <label style={labelStyle}><span>{label}</span>{children}</label>;
}

function ResultBlock({title, value}: {title: string; value: unknown}) {
  if (!value) return null;
  return (
    <section style={sectionStyle}>
      <h3 style={{margin: '0 0 10px', fontSize: '0.95rem'}}>{title}</h3>
      <pre style={{
        margin: 0,
        maxHeight: 320,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        color: '#cbd5e1',
        fontSize: '0.76rem',
      }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </section>
  );
}

function PreviewTable({title, rows, columns}: {title: string; rows?: LooseRecord[]; columns: string[]}) {
  const data = Array.isArray(rows) ? rows : [];
  return (
    <section style={sectionStyle}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
        <h3 style={{margin: 0, fontSize: '0.95rem'}}>{title}</h3>
        <span style={{color: '#94a3b8', fontSize: '0.78rem'}}>{data.length} 行</span>
      </div>
      <div style={{overflowX: 'auto'}}>
        <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem'}}>
          <thead style={{color: '#94a3b8'}}>
            <tr>
              {columns.map(column => <th key={column} style={{textAlign: 'left', padding: 7}}>{column}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.map((row, idx) => (
              <tr key={`${idx}-${columns.map(column => row[column]).join('-')}`} style={{borderTop: '1px solid rgba(148,163,184,0.12)'}}>
                {columns.map(column => (
                  <td key={column} style={{padding: 7, whiteSpace: 'nowrap'}}>{fmt(row[column], typeof row[column] === 'number' ? 4 : 2)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!data.length ? <p style={{color: '#94a3b8', margin: 0}}>暂无预览数据</p> : null}
      </div>
    </section>
  );
}

export default function ResearchPortfolioWorkspace({surface}: {surface: WorkspaceSurface; key?: string}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [workspaceAccess, setWorkspaceAccess] = useState<ResearchWorkspaceAccess>(() => researchWorkspaceAccess(null));
  useEffect(() => {
    const controller = new AbortController();
    apiGet<ResearchWorkspaceHealth>('/api/health', {timeoutMs: 8000, signal: controller.signal})
      .then(value => setWorkspaceAccess(researchWorkspaceAccess(value)))
      .catch(() => setWorkspaceAccess(researchWorkspaceAccess(null)));
    return () => controller.abort();
  }, []);
  const view = new URLSearchParams(location.search).get('view') || 'research-overview';
  // These independent read models must not wait on unrelated legacy registries.
  if (surface === 'research' && ['alpha-factory', 'run-details'].includes(view)) return (
    <WorkbenchFrame className="research-workbench research-v2 workspace-unified workspace-research research-focused" testId="research-content" mode="research">
      <div className="research-focused-toolbar"><span>研究台 / {view === 'alpha-factory' ? 'Alpha 工厂' : '运行详情'}</span>
        <details><summary>布局版本</summary><a href="/research?layout=previous">切回改版前</a><a href="/research?layout=legacy">切回原版</a></details></div>
      <ResearchNavigation tab={view} onChange={next => navigate(researchWorkspaceLink(next, location.search))} />
      <section id="research-active-panel" role="tabpanel" aria-label={view === 'run-details' ? '运行详情' : 'Alpha 工厂'} className="research-active-panel">
        {view === 'alpha-factory' ? <AlphaFactoryConsole externalBusy={false} onWorking={() => undefined}
          commandsDisabled={!workspaceAccess.researchWrites} commandsDisabledReason={workspaceAccess.reason} /> : <ResearchRunDetails />}
      </section>
    </WorkbenchFrame>
  );
  return <ResearchPortfolioContent surface={surface} workspaceAccess={workspaceAccess} />;
}

function ResearchPortfolioContent({surface, workspaceAccess}: {surface: WorkspaceSurface; workspaceAccess: ResearchWorkspaceAccess}) {
  const location = useLocation();
  const navigate = useNavigate();
  const incoming = useMemo(() => parseWorkspaceContext(location.search), [location.search]);
  const source = incoming.context;
  const requestedQlibProfileId = typeof location.state?.qlibProfileId === 'string' ? location.state.qlibProfileId : '';
  const restoredQlibProfile = useRef('');
  const [loadedRoots, setLoadedRoots] = useState({qlib: source.qlibRoot, portfolio: source.portfolioRoot});
  const [referenceIssues, setReferenceIssues] = useState<string[]>([]);
  const [referenceLoading, setReferenceLoading] = useState(true);
  const [persistedPortfolio, setPersistedPortfolio] = useState<LooseRecord | null>(null);
  const [persistedPortfolioError, setPersistedPortfolioError] = useState('');
  const alive = useRef(true);
  const actionLock = useRef(false);
  const draftBinding = useRef<{runId: string; configKey: string} | null>(null);
  const allowedViews = surface === 'research' ? ['research-overview','data','factors','cycle','records','qlib','evidence','workflow','handoff'] : surface === 'portfolio' ? ['overview','optimize','simulate','risk'] : ['review'];
  const requestedView = new URLSearchParams(location.search).get('view') || '';
  const initialView = allowedViews.includes(requestedView) ? requestedView : allowedViews[0];
  const [dataRoot, setDataRoot] = useState(source.dataRoot);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [features, setFeatures] = useState<LooseRecord[]>([]);
  const [factors, setFactors] = useState<LooseRecord[]>([]);
  const [manifests, setManifests] = useState<LooseRecord[]>([]);
  const [pendingReviews, setPendingReviews] = useState<LooseRecord[]>([]);
  const [qlibStatus, setQlibStatus] = useState<LooseRecord | null>(null);
  const [qlibRuns, setQlibRuns] = useState<LooseRecord[]>([]);
  const [qlibRunDetail, setQlibRunDetail] = useState<LooseRecord | null>(null);
  const [qlibDetailKey, setQlibDetailKey] = useState('');
  const [portfolioDetailKey, setPortfolioDetailKey] = useState('');
  const [simulationDetail, setSimulationDetail] = useState<LooseRecord | null>(null);
  const [portfolioIntegrationStatus, setPortfolioIntegrationStatus] = useState<LooseRecord | null>(null);
  const [portfolioIntegrationRuns, setPortfolioIntegrationRuns] = useState<LooseRecord[]>([]);
  const [portfolioIntegrationDetail, setPortfolioIntegrationDetail] = useState<LooseRecord | null>(null);
  const [registry, setRegistry] = useState<LooseRecord | null>(null);
  const [globalRegistry, setGlobalRegistry] = useState<LooseRecord | null>(null);
  const [systemOverview, setSystemOverview] = useState<SystemOverviewResponse | null>(null);
  const [paperReviewEntry, setPaperReviewEntry] = useState<LooseRecord | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [readFailures, setReadFailures] = useState<string[]>([]);
  const [readFailureDetails, setReadFailureDetails] = useState<ResearchReadFailure[]>([]);
  const [readAt, setReadAt] = useState('');
  const [loadedRoot, setLoadedRoot] = useState(source.dataRoot);

  const readSequence = useRef(0);
  const activeRead = useRef<ResearchReadLease<LooseRecord> | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [taskQueue, setTaskQueue] = useState<TaskResponse[]>([]);
  const [tab, setLocalTab] = useState(initialView);
  useEffect(() => {if (surface === 'research') setLocalTab(initialView);}, [initialView,surface]);
  const setTab = (next: string) => {
    if (surface === 'research') navigate(researchWorkspaceLink(next, location.search),{state:{...location.state,researchNavigationFocus:true,researchContentFocus:undefined}});
    else setLocalTab(next);
  };
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null);
  const [selectedReportExp, setSelectedReportExp] = useState(source.experiment);
  const [selectedManifestIds, setSelectedManifestIds] = useState<string[]>(source.manifests);
  const experimentFormRef = useRef<HTMLElement | null>(null);
  const consumedExperimentFocus = useRef('');
  useEffect(() => {
    if (surface !== 'research' || tab !== 'cycle' || location.state?.researchContentFocus !== 'experiment-form'
      || consumedExperimentFocus.current === location.key) return;
    consumedExperimentFocus.current = location.key;
    const form = experimentFormRef.current;
    form?.scrollIntoView({block: 'start'});
    form?.querySelector<HTMLElement>('input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')?.focus({preventScroll: true});
  }, [location.key, location.state, surface, tab]);

  const [autoForm, setAutoForm] = useState({
    strategyId: 'trend_momentum',
    symbols: 'AAPL,MSFT',
    family: 'frontend_research_cycle',
    params: '{"lookback_bars": 20}',
    paramGrid: '{"lookback_bars": [10, 20, 60]}',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
    dataVersion: source.dataVersion,
    featureVersion: source.featureVersion,
  });
  const [factorForm, setFactorForm] = useState({
    factorId: 'momentum_60d',
    symbols: 'AAPL,MSFT',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
    forwardPeriod: '5',
  });
  const [featureForm, setFeatureForm] = useState({
    featureId: 'momentum_60d',
    version: 'v1',
    symbols: 'AAPL,MSFT',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
  });
  const [portfolioForm, setPortfolioForm] = useState({
    manifestIds: source.manifests.join(', '),
    initialCash: '50000',
    reviewer: '',
    reviewReason: '',
  });
  const [qlibForm, setQlibForm] = useState({
    profileId: requestedQlibProfileId || 'us_equity_daily',
    dataVersion: source.dataVersion || 'latest',
    universe: 'configs/universe/us_core_liquid.yaml',
    qlibConfig: 'configs/qlib/us_lgbm_alpha158_daily.yaml',
    startDate: '2020-01-01',
    endDate: '2025-12-31',
    runId: source.qlibRun,
    artifactsRoot: source.qlibRoot,
    source: '',
    dryRun: true,
  });
  const [pypfoptForm, setPypfoptForm] = useState({
    scoreRunId: source.qlibRun,
    portfolioRunId: source.portfolioRun,
    config: 'configs/portfolio/pypfopt_long_only_max_sharpe.yaml',
    artifactsRoot: source.portfolioRoot,
    fallbackOptimizer: 'equal_weight_topk',
    strategyId: 'pypfopt_daily_only',
  });

  // Navigation remounts this workspace. Restore only an ID, resolving every
  // configuration field against the server-owned profile list after it loads.
  useEffect(() => {
    if (!requestedQlibProfileId || source.qlibRun || restoredQlibProfile.current === requestedQlibProfileId) return;
    const profile = qlibStatus?.profiles?.find((item: LooseRecord) => item.profile_id === requestedQlibProfileId);
    if (!profile) return;
    restoredQlibProfile.current = requestedQlibProfileId;
    setQlibForm(current => ({...current, profileId: profile.profile_id, dataVersion: profile.data_version || 'latest',
      universe: profile.universe, qlibConfig: profile.config, startDate: profile.start_date, endDate: profile.end_date,
      source: profile.source, runId: '', dryRun: true}));
  }, [requestedQlibProfileId, source.qlibRun, qlibStatus]);

  const rootMismatch = dataRoot !== loadedRoot || qlibForm.artifactsRoot !== loadedRoots.qlib || pypfoptForm.artifactsRoot !== loadedRoots.portfolio;
  const detailQlibId = surface === 'portfolio' ? pypfoptForm.scoreRunId.trim() : qlibForm.runId.trim();
  const checkedQlibDetail = qlibDetailKey === [qlibForm.artifactsRoot,detailQlibId,readAt].join('|') ? qlibRunDetail : null;
  const checkedPortfolioDetail = portfolioDetailKey === [pypfoptForm.artifactsRoot,pypfoptForm.portfolioRunId,readAt].join('|') ? portfolioIntegrationDetail : null;
  const editedRootErrors = parseWorkspaceContext(new URLSearchParams({dataRoot,qlibRoot:qlibForm.artifactsRoot,portfolioRoot:pypfoptForm.artifactsRoot}).toString()).errors;
  if (qlibForm.artifactsRoot !== 'artifacts/qlib_runs') editedRootErrors.push('Qlib 结果目录由服务器固定，不能更换来源根目录');
  const editedIdErrors = parseWorkspaceContext(new URLSearchParams({qlibRun:detailQlibId,portfolioRun:pypfoptForm.portfolioRunId}).toString()).errors;
  const sourceReadable = !incoming.errors.length && !editedRootErrors.length && !editedIdErrors.length;
  const sourceEvidenceIssues = [
    ...runEvidenceErrors(surface === 'portfolio' ? pypfoptForm.scoreRunId : source.qlibRun, qlibForm.artifactsRoot, checkedQlibDetail, 'qlib'),
    ...runEvidenceErrors(source.portfolioRun, pypfoptForm.artifactsRoot, checkedPortfolioDetail, 'portfolio', pypfoptForm.scoreRunId),
    ...versionEvidenceErrors(source, [candidates.find(c => c.candidate_id === source.candidate),experiments.find(e => e.experiment_id === source.experiment),checkedQlibDetail?.dataset_manifest,checkedQlibDetail?.strategy_manifest].filter(Boolean) as LooseRecord[]),
    ...simulationEvidenceErrors(source, simulationDetail),
  ];
  const sourceActionBlocked = !!busy || rootMismatch || referenceLoading || !sourceReadable || !!referenceIssues.length || !!sourceEvidenceIssues.length;
  const actionBlocked = sourceActionBlocked || !workspaceAccess.researchWrites;
  const finalizedPortfolioVersion = !!source.portfolioRun || portfolioIntegrationRuns.some(run => run.portfolio_run_id === pypfoptForm.portfolioRunId && (run.has_target_positions || Number(run.target_weight_rows) > 0));
  const cryptoQlibRun = checkedQlibDetail?.summary?.asset_class === 'crypto';
  const draftQlibProfile = qlibStatus?.profiles?.find((item: LooseRecord) => item.profile_id === qlibForm.profileId);
  const verifiedQlibContext = checkedQlibDetail?.integrity_status === 'passed' && checkedQlibDetail?.summary?.run_id === detailQlibId;
  const qlibContextIdentity = verifiedQlibContext ? checkedQlibDetail?.research_trace?.identity : null;
  const portfolioWriteBlocked = cryptoQlibRun || actionBlocked || !pypfoptForm.scoreRunId || finalizedPortfolioVersion || dataRoot !== 'data' || qlibForm.artifactsRoot !== 'artifacts/qlib_runs' || pypfoptForm.artifactsRoot !== 'artifacts/portfolio_runs';
  const matchingPortfolioConfig = portfolioConfigMatches(checkedPortfolioDetail,pypfoptForm.config,pypfoptForm.strategyId,pypfoptForm.fallbackOptimizer);
  const currentContext = (extra: Partial<WorkspaceContext> = {}): WorkspaceContext => ({
    ...source, dataRoot: loadedRoot, qlibRoot: loadedRoots.qlib, portfolioRoot: loadedRoots.portfolio,
    qlibRun: surface === 'portfolio' ? pypfoptForm.scoreRunId : qlibForm.runId, portfolioRun: pypfoptForm.portfolioRunId,
    manifests: selectedManifestIds, ...extra,
  });
  const go = (target: WorkspaceSurface, extra: Partial<WorkspaceContext> = {}, view?: string) => {
    if (busy || rootMismatch) {setError('任务进行中或来源目录已修改，请先完成任务 / 重新读取。'); return;}
    navigate(workspaceLink(target, currentContext(extra), view));
  };
  const candidateContext = (candidate: Candidate): Partial<WorkspaceContext> => ({
    candidate: candidate.candidate_id, experiment: candidate.experiment_id, qlibRun:'', portfolioRun:'', simulation:'',
    manifests: manifests.filter(m => m.source_candidate_id === candidate.candidate_id).map(m => String(m.strategy_candidate_id)),
    dataVersion: String((candidate as LooseRecord).data_version || ''), featureVersion: String((candidate as LooseRecord).feature_version || ''),
  });
  const [autoResult, setAutoResult] = useState<LooseRecord | null>(null);
  const [factorResult, setFactorResult] = useState<LooseRecord | null>(null);
  const [factorPreview, setFactorPreview] = useState<LooseRecord | null>(null);
  const [factorMiningResult, setFactorMiningResult] = useState<LooseRecord | null>(null);
  const [featureResult, setFeatureResult] = useState<LooseRecord | null>(null);
  const [candidateActionResult, setCandidateActionResult] = useState<LooseRecord | null>(null);
  const [portfolioResult, setPortfolioResult] = useState<LooseRecord | null>(null);
  const [qlibActionResult, setQlibActionResult] = useState<LooseRecord | null>(null);
  const [pypfoptActionResult, setPypfoptActionResult] = useState<LooseRecord | null>(null);
  const [executionPipelineResult, setExecutionPipelineResult] = useState<LooseRecord | null>(null);

  const refresh = async (root = dataRoot) => {
    setError('');
    const invalidRoots = parseWorkspaceContext(new URLSearchParams({dataRoot:root,qlibRoot:qlibForm.artifactsRoot,portfolioRoot:pypfoptForm.artifactsRoot}).toString()).errors;
    if (qlibForm.artifactsRoot !== 'artifacts/qlib_runs') invalidRoots.push('Qlib 结果目录由服务器固定');
    if (incoming.errors.length || invalidRoots.length) {setReferenceIssues([...incoming.errors,...invalidRoots]);setReferenceLoading(false);return;}
    setReferenceLoading(true);
    const sequence = ++readSequence.current;
    const requestKey = ['research-workspace-read-v1', root, qlibForm.artifactsRoot, pypfoptForm.artifactsRoot].join('|');
    const lease = acquireResearchRead<LooseRecord>(requestKey, async (signal) => {
      const failures: ResearchReadFailure[] = [];
      async function read<T>(name: string, request: () => Promise<T>, fallback: T): Promise<T> {
        try {
          return await request();
        } catch (readError) {
          failures.push({name, ...classifyResearchReadError(readError, signal)});
          return fallback;
        }
      }
      const [registryPayload, qlibPayload, exps, cands, snaps, factorDefs, manifestRows, reviews, globalRegistryPayload, portfolioPayload, overviewPayload, paperReviewEntryPayload] = await Promise.all([
        read('证据注册表', () => researchApi.getEvidenceRegistry(root, false, {signal}), null),
        read('Qlib', () => researchApi.listQlibRuns(qlibForm.artifactsRoot, {signal}), null),
        read('实验列表', () => researchApi.listExperiments(root, {signal}), []),
        read('候选列表', () => researchApi.listCandidates(root, {signal}), []),
        read('特征快照', () => researchApi.listFeatures({signal}), []),
        read('因子目录', () => researchApi.listFactors(root, {signal}), []),
        read('策略证据', () => researchApi.listStrategyManifests(root, '', {signal}), []),
        read('复核队列', () => researchApi.listPendingReviews(root, {signal}), []),
        read('全局注册表', () => researchApi.getGlobalRegistry({signal}), null),
        read('组合工具', () => researchApi.listPortfolioIntegrationRuns(pypfoptForm.artifactsRoot, {signal}), null),
        read('系统总览', () => apiGet<SystemOverviewResponse>(`/api/system/overview?data_root=${encodeURIComponent(root)}`, {timeoutMs: 20000, signal}), null),
        read('人工复核入口', () => researchApi.getPaperReviewEntryState(root, {signal}), null),
      ]);
      return {exps, cands, snaps, factorDefs, manifestRows, reviews, registryPayload, globalRegistryPayload,
        qlibPayload, portfolioPayload, overviewPayload, paperReviewEntryPayload, failures};
    }, {deadlineMs: 12000}) as ResearchReadLease<LooseRecord>;
    activeRead.current?.release();
    activeRead.current = lease;
    let payload: LooseRecord;
    try {
      payload = await lease.promise;
    } catch (readError) {
      if (sequence !== readSequence.current || !alive.current) return;
      const failure = {name: '研究状态', ...classifyResearchReadError(readError)};
      setReadFailures([failure.name]);
      setReadFailureDetails([failure]);
      setReferenceLoading(false);
      return;
    } finally {
      if (activeRead.current === lease) activeRead.current = null;
      lease.release();
    }
    if (sequence !== readSequence.current || !alive.current) return;
    const {exps, cands, snaps, factorDefs, manifestRows, reviews, registryPayload, globalRegistryPayload,
      qlibPayload, portfolioPayload, overviewPayload, paperReviewEntryPayload, failures} = payload;
    setLoadedRoots({qlib: qlibForm.artifactsRoot, portfolio: pypfoptForm.artifactsRoot});
    const issues = referenceErrors({...source, dataRoot:root}, {candidates:cands || [],experiments:exps || [],manifests:manifestRows || [],qlib:qlibPayload?.runs || [],portfolios:portfolioPayload?.runs || []});
    setReferenceIssues(issues);
    setReferenceLoading(false);
    setReadFailures(failures.map((failure: ResearchReadFailure) => failure.name));
    setReadFailureDetails(failures);
    setReadAt(new Date().toLocaleString('zh-CN', {hour12: false}));
    setLoadedRoot(root);
    setExperiments(exps || []);
    setCandidates(cands || []);
    setFeatures(snaps || []);
    setFactors(factorDefs || []);
    setManifests(manifestRows || []);
    setPendingReviews(reviews || []);
    setRegistry(registryPayload);
    setGlobalRegistry(globalRegistryPayload);
    setQlibStatus(qlibPayload);
    setQlibRuns(Array.isArray(qlibPayload?.runs) ? qlibPayload.runs : []);
    setPortfolioIntegrationStatus(portfolioPayload);
    setPortfolioIntegrationRuns(Array.isArray(portfolioPayload?.runs) ? portfolioPayload.runs : []);
    setSystemOverview(overviewPayload);
    setPaperReviewEntry(paperReviewEntryPayload);
    setSelectedManifestIds(current => {
      const available = (manifestRows || []).map((row: LooseRecord) => String(row.strategy_candidate_id || '')).filter(Boolean);
      return current.filter(id => available.includes(id));
    });
    if ((factorDefs || []).length && !factorDefs.find((f: LooseRecord) => f.factor_id === factorForm.factorId)) {
      setFactorForm(current => ({...current, factorId: String(factorDefs[0].factor_id)}));
      setFeatureForm(current => ({...current, featureId: String(factorDefs[0].factor_id)}));
    }
  };

  useEffect(() => {
    let cancelled = false;
    alive.current = true;
    (async () => {
      try {
        await Promise.all([refresh(dataRoot), withTimeout(refreshTaskQueue(), undefined, 2500)]);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载研究数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; alive.current = false; readSequence.current++; activeRead.current?.release(); activeRead.current = null; };
  }, []);

  const candidatesForExp = selectedExp
    ? candidates.filter(c => c.experiment_id === selectedExp.experiment_id)
    : source.experiment ? candidates.filter(c => c.experiment_id === source.experiment) : candidates;

  const paperReadyCount = useMemo(() => {
    return candidates.filter(c => ['READY_FOR_PAPER_REVIEW', 'PAPER_ELIGIBLE'].includes(String(c.promotion_status))).length;
  }, [candidates]);

  const updateAuto = (key: string, value: string) => setAutoForm(current => ({...current, [key]: value}));
  const updateFactor = (key: string, value: string) => setFactorForm(current => ({...current, [key]: value}));
  const updateFeature = (key: string, value: string) => setFeatureForm(current => ({...current, [key]: value}));
  const updatePortfolio = (key: string, value: string) => setPortfolioForm(current => ({...current, [key]: value}));
  const updateQlib = (key: string, value: string | boolean) => setQlibForm(current => ({...current, [key]: value}));
  const clearQlibSourceContext = (profileId = qlibForm.profileId) => navigate(workspaceLink('research', {
    ...currentContext(),qlibRun:'',portfolioRun:'',candidate:'',experiment:'',manifests:[],simulation:'',dataVersion:'',featureVersion:'',
  },'qlib'), {state: {qlibProfileId: profileId}});
  const updatePypfopt = (key: string, value: string) => {
    if (busy || (pypfoptForm.portfolioRunId && !finalizedPortfolioVersion && ['config','fallbackOptimizer','strategyId'].includes(key))) {
      setError('进行中的组合草稿配置已冻结；请新建版本再修改。'); return;
    }
    setPypfoptForm(current => ({...current, [key]: value}));
  };

  const selectedQlibRunId = detailQlibId;
  const selectedPortfolioRunId = pypfoptForm.portfolioRunId.trim();
  const minuteRemediationActions = asArray(systemOverview?.minute_data_quality?.remediation_summary?.actions);
  const selectedManifestRows = manifests.filter(row => selectedManifestIds.includes(String(row.strategy_candidate_id || '')));
  const latestPortfolioRun = asRecord(portfolioIntegrationRuns.find(run => run.portfolio_run_id === selectedPortfolioRunId));
  const targetWeightReady = !!latestPortfolioRun?.has_target_positions;
  const targetWeightStatus = targetWeightReady
    ? 'READY_FOR_BACKTEST_ENTRY'
    : readString(latestPortfolioRun?.status, 'MISSING_TARGET_POSITIONS');
  const targetWeightDetail = targetWeightReady
    ? `target positions 已生成，最新权重和 ${pct(latestPortfolioRun?.latest_weight_sum)}`
    : '尚未生成 target_positions，当前只停留在 target_weights 或更早阶段。';
  const globalAssets = asRecord(globalRegistry?.assets);
  const globalUsEquity = asRecord(globalAssets?.us_equity);
  const globalBtc = asRecord(globalAssets?.btc);
  const globalUsBlockers = Array.isArray(globalUsEquity?.blockers) ? globalUsEquity?.blockers as string[] : [];
  const globalBtcDataStatus = asRecord(globalBtc?.data_status);
  const globalBtcCandidates = asArray(globalBtc?.current_candidates);
  const workflowManifestRows = useMemo(() => manifests.slice(0, 10).map(row => {
    const evidencePairs = [
      ['数据 manifest', row.data_manifest_path],
      ['回测 manifest', row.backtest_manifest_path],
      ['评分卡', row.scorecard_path],
      ['滚动验证', row.walk_forward_result_path],
      ['成本压力', row.cost_stress_result_path],
      ['晋升', row.promotion_result_path],
      ['纸交易复核包', row.paper_review_evidence_pack_path],
    ].filter(([, value]) => !!value);
    const missingEvidence = ['data_manifest_path', 'backtest_manifest_path', 'scorecard_path', 'walk_forward_result_path', 'cost_stress_result_path']
      .filter(key => !row[key])
      .map(key => key.replace(/_path$/, ''));
    const blockingReasons = [
      ...(Array.isArray(row.paper_review_blocking_reasons) ? row.paper_review_blocking_reasons.map(item => String(item)) : []),
      ...(String(row.promotion_status || '') && !['READY_FOR_PORTFOLIO_SIM', 'PAPER_REVIEW_CANDIDATE'].includes(String(row.promotion_status))
        ? [`晋升状态=${row.promotion_status}`]
        : []),
      ...missingEvidence.map(item => `缺少 ${item}`),
    ];
    return {
      id: String(row.strategy_candidate_id || ''),
      sourceCandidateId: String(row.source_candidate_id || ''),
      status: String(row.promotion_status || 'UNKNOWN'),
      symbols: Array.isArray(row.symbols) ? row.symbols.join(', ') : '-',
      evidencePairs,
      blockingReasons,
      reviewStatus: String(row.paper_review_candidate_status || row.paper_review_gate_status || '未创建'),
    };
  }), [manifests]);

  const runTask = async (label: string, task: () => Promise<void>) => {
    if (actionLock.current) {setError('已有操作进行中，请等待完成。');return;}
    const readOnly = ['refresh','integration-refresh'].includes(label) || label.startsWith('qlib-detail-') || label.startsWith('portfolio-detail-');
    if (!readOnly && !workspaceAccess.researchWrites) {setError(workspaceAccess.reason); return;}
    if (!readOnly && actionBlocked) {setError('来源未就绪或任务进行中，未提交操作。'); return;}
    if (!readOnly && ((label.startsWith('pypfopt-') || label === 'portfolio-sim' || label === 'research-execution-pipeline') && surface !== 'portfolio')) {setError('组合操作仅在投资组合页执行。'); return;}
    if (!readOnly && ((label.includes('review') || label.startsWith('approve-')) && surface !== 'review')) {setError('人工复核仅在执行安全中心进行。'); return;}
    if (rootMismatch && !['refresh', 'integration-refresh'].includes(label)) {
      setError('数据目录已修改，请先重新读取状态；未提交任何操作。');
      return;
    }
    actionLock.current = true;
    setBusy(label);
    setError('');
    setMessage('');
    try {
      await task();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      actionLock.current = false;
      setBusy('');
    }
  };

  const upsertTask = (task: TaskResponse) => {
    setTaskQueue((current) => [task, ...current.filter((item) => item.task_id !== task.task_id)].slice(0, 8));
  };

  const refreshTaskQueue = async () => {
    try {
      const tasks = await taskApi.listTasks('', 8);
      setTaskQueue(tasks);
    } catch {
      // Task queue is best-effort. A transient failure should not block the page.
    }
  };

  const trackTask = async (taskId: string, onComplete?: (task: TaskResponse) => Promise<void> | void) => {
    let current = await taskApi.getTask(taskId);
    upsertTask(current);
    while (isActiveTask(current) && alive.current) {
      await sleep(800);
      current = await taskApi.getTask(taskId);
      upsertTask(current);
    }
    if (onComplete && alive.current) {
      await onComplete(current);
    }
    return current;
  };

  const toggleManifestSelection = (manifestId: string) => {
    setSelectedManifestIds(current => current.includes(manifestId) ? current.filter(id => id !== manifestId) : [...current, manifestId]);
  };

  const openExperimentForm = () => {
    navigate(researchWorkspaceLink('cycle', location.search), {state:{...location.state,researchNavigationFocus:false,researchContentFocus:'experiment-form'}});
    setMessage('已打开研究闭环实验表单；尚未创建或提交实验。');
  };

  const refreshIntegrationPanels = async () => {
    await refresh(dataRoot);
  };

  const loadQlibRunDetail = (runId: string) => runTask(`qlib-detail-${runId}`, async () => {
    if (parseWorkspaceContext(new URLSearchParams({qlibRun:runId}).toString()).errors.length) throw new Error('无效运行编号，不读取此来源');
    setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot));
    setQlibForm(current => ({...current, runId}));
    setPypfoptForm(current => ({...current, scoreRunId: current.scoreRunId || runId}));
  });

  const blockedAction = (..._args: unknown[]) => {setError('当前页面不拥有此操作。');};
  const researchActions = surface === 'research' ? createResearchActions({surface, actionBlocked, actionLock, dataRoot, selectedQlibRunId, source, refresh, refreshIntegrationPanels, upsertTask, trackTask, autoForm, factorForm, featureForm, qlibForm, setQlibForm, setAutoResult, setFactorResult, setFactorPreview, setFactorMiningResult, setFeatureResult, setRegistry, setCandidateActionResult, setQlibActionResult, setQlibRunDetail, setBusy, setError, setMessage}) : null;
  const {handleAutoCycle, handleFactorEvaluate, handleFactorCompute, handleFactorMine, handleFactorMineAndRun, handleFeatureBuild, handleRegistryRebuild, handleCandidateAction, handleQlibAction} = researchActions || {handleAutoCycle: blockedAction, handleFactorEvaluate: blockedAction, handleFactorCompute: blockedAction, handleFactorMine: blockedAction, handleFactorMineAndRun: blockedAction, handleFeatureBuild: blockedAction, handleRegistryRebuild: blockedAction, handleCandidateAction: blockedAction, handleQlibAction: blockedAction};
  const portfolioActions = surface === 'portfolio' ? createPortfolioActions({surface, actionBlocked: actionBlocked || cryptoQlibRun, actionLock, draftBinding, dataRoot, selectedQlibRunId, selectedPortfolioRunId, selectedManifestIds, manifests, qlibRuns, portfolioIntegrationRuns, source, portfolioIntegrationDetail: checkedPortfolioDetail, matchingPortfolioConfig, qlibRunDetail: checkedQlibDetail, refresh, refreshIntegrationPanels, upsertTask, trackTask, portfolioForm, qlibForm, pypfoptForm, setPypfoptForm, setPortfolioResult, setPypfoptActionResult, setPortfolioIntegrationDetail, setExecutionPipelineResult, setBusy, setError, setMessage}) : null;
  const {handlePortfolioSim, handlePypfoptAction, handleResearchExecutionPipeline} = portfolioActions || {handlePortfolioSim: blockedAction, handlePypfoptAction: blockedAction, handleResearchExecutionPipeline: blockedAction};
  const reviewActions = surface === 'review' ? createReviewActions({surface, actionBlocked, actionLock, dataRoot, portfolioResult, paperReviewEntry, source, pendingReviews, refresh, portfolioForm, setPortfolioResult, setBusy, setError, setMessage}) : null;
  const {handleCreateReview, handleCreateReviewFromManifest, handleCreateReviewFromCandidate, handleApproveReview} = reviewActions || {handleCreateReview: blockedAction, handleCreateReviewFromManifest: blockedAction, handleCreateReviewFromCandidate: blockedAction, handleApproveReview: blockedAction};

  const contextErrors = [
    !splitCsv(autoForm.symbols).length ? '请填写至少一个标的' : '',
    !autoForm.start || !autoForm.end || autoForm.start > autoForm.end ? '请检查研究起止日期' : '',
    dataRoot !== loadedRoot ? '数据目录已修改，请先重新读取状态' : '',
  ].filter(Boolean);

  const updateContext = (key: string, value: string) => {
    updateAuto(key, value);
    if (['symbols', 'start', 'end', 'barSize'].includes(key)) {
      updateFactor(key, value);
      updateFeature(key, value);
    }
  };
  const integrationTasks = useMemo(
    () => taskQueue.filter((task) => ['qlib_dataset', 'qlib_workflow', 'portfolio_optimize_weights'].includes(task.kind)),
    [taskQueue],
  );

  const [detailError, setDetailError] = useState('');
  useEffect(() => {
    let cancelled = false;
    setPortfolioIntegrationDetail(null);
    setDetailError('');
    if (sourceReadable && selectedPortfolioRunId && !rootMismatch && !referenceLoading) {
      researchApi.getPortfolioIntegrationRun(selectedPortfolioRunId, pypfoptForm.artifactsRoot).then(detail => {
        if (!cancelled) {setPortfolioIntegrationDetail(detail);setPortfolioDetailKey([pypfoptForm.artifactsRoot,selectedPortfolioRunId,readAt].join('|'));}
      }).catch(e => {if (!cancelled) setDetailError('组合详情读取失败：' + String(e));});
    }
    return () => {cancelled = true;};
  }, [selectedPortfolioRunId, pypfoptForm.artifactsRoot, rootMismatch, referenceLoading, readAt, sourceReadable]);
  useEffect(() => {
    let cancelled = false;
    setQlibRunDetail(null);
    if (sourceReadable && selectedQlibRunId && !rootMismatch && !referenceLoading) {
      researchApi.getQlibRun(selectedQlibRunId, qlibForm.artifactsRoot).then(detail => {
        if (!cancelled) {setQlibRunDetail(detail);setQlibDetailKey([qlibForm.artifactsRoot,selectedQlibRunId,readAt].join('|'));}
      }).catch(e => {if (!cancelled) setDetailError('Qlib 详情读取失败：' + String(e));});
    }
    return () => {cancelled = true;};
  }, [selectedQlibRunId, qlibForm.artifactsRoot, rootMismatch, referenceLoading, readAt, sourceReadable]);
  useEffect(() => {
    if (surface !== 'portfolio' || !sourceReadable) return;
    let cancelled = false;
    setPersistedPortfolio(null);
    setPersistedPortfolioError('');
    if (loadedRoot !== 'data') {setPersistedPortfolioError('旧组合快照只绑定默认 data 目录，当前自定义目录不展示它。');return;}
    apiGet<LooseRecord>('/api/portfolio/status', 8000).then(result => {
      if (cancelled) return;
      if (result.status !== 'ok') throw new Error(result.detail || result.status || '状态未知');
      if (result.latest_portfolio && !completeLegacySnapshot(result.latest_portfolio)) throw new Error('旧目标快照字段不完整或数值无效，不能当作可用组合状态。');
      setPersistedPortfolio(result.latest_portfolio || null);
    }).catch(e => {if (!cancelled) setPersistedPortfolioError(String(e));});
    return () => {cancelled = true;};
  }, [surface, loadedRoot, readAt, sourceReadable]);
  useEffect(() => {
    if (!sourceReadable || rootMismatch || referenceLoading || !source.simulation || loadedRoot !== 'data') return;
    let cancelled = false;
    apiGet<LooseRecord>('/api/research/portfolio-sims/' + encodeURIComponent(source.simulation), 8000).then(result => {
      if (!cancelled) {setSimulationDetail(result);setPortfolioResult(result);}
    }).catch(e => {if (!cancelled) setDetailError('组合模拟证据读取失败：' + String(e));});
    return () => {cancelled = true;};
  }, [source.simulation, loadedRoot, sourceReadable, rootMismatch, referenceLoading]);
  const sourceIssues = [...incoming.errors, ...referenceIssues, ...editedRootErrors, ...editedIdErrors, ...sourceEvidenceIssues];
  const portfolioTitle = surface === 'portfolio' ? '组合构建与风险' : surface === 'review' ? '研究准入人工复核' : '研究台';
  const sourcePanel = <details className="workspace-source" aria-label="来源与版本" open={surface !== 'research' || !!source.candidate || !!source.qlibRun || !!source.portfolioRun || !!source.experiment || !!sourceIssues.length || rootMismatch}>
    <summary>来源与版本 · {source.candidate || source.qlibRun || source.portfolioRun || loadedRoot}</summary>
    <div><span className="research-eyebrow">SOURCE / VERSION</span><h3>{surface === 'research' ? '当前研究来源' : '研究来源与组合草稿'}</h3>
      <p>仅引用来源，不自动计算、不发布组合、不创建复核、不授予交易权限。</p></div>
    <dl><div><dt>候选 / 实验</dt><dd>{source.candidate || '未选择'} / {source.experiment || '未选择'}</dd></div>
      <div><dt>评分运行</dt><dd>{pypfoptForm.scoreRunId || selectedQlibRunId || '未选择'}</dd></div>
      <div><dt>组合版本</dt><dd>{selectedPortfolioRunId || '新草稿，尚未生成'}</dd></div>
      <div><dt>策略证据</dt><dd>{selectedManifestIds.join(', ') || '未选择'}</dd></div>
      <div><dt>数据目录</dt><dd>{loadedRoot}</dd></div><div><dt>版本提示（以来源原件为准）</dt><dd>{source.dataVersion || '未绑定'} / {source.featureVersion || '未绑定'}</dd></div></dl>
    {sourceIssues.length > 0 && <p className="warning" role="alert">{sourceIssues.join('；')}。不会自动改用最新运行。</p>}
    {rootMismatch && <p className="warning" role="alert">来源目录已修改，请先重新读取；旧结果不能用于新目录的操作。</p>}
    <div className="research-actions">
      {surface !== 'research' && <button disabled={!!busy || rootMismatch} onClick={() => go('research', {}, source.qlibRun ? 'qlib' : source.experiment ? 'records' : 'handoff')}>返回来源实验</button>}
      {surface !== 'portfolio' && <button disabled={!!busy || rootMismatch} onClick={() => go('portfolio', {}, source.qlibRun ? 'optimize' : 'overview')}>前往投资组合</button>}
      <button disabled={!!busy || rootMismatch} onClick={() => go('review', {simulation: String(portfolioResult?.portfolio_sim_id || source.simulation)})}>执行安全中心 · 人工复核</button>
    </div>
    <details><summary>来源目录与版本原件</summary>
      <label>数据根目录<input style={inputStyle} value={dataRoot} onChange={(e: {target: {value: string}}) => setDataRoot(e.target.value)} /></label>
      <label>Qlib 结果目录（服务器固定）<input style={inputStyle} value={qlibForm.artifactsRoot} readOnly /></label>
      <label>组合结果目录<input style={inputStyle} value={pypfoptForm.artifactsRoot} onChange={(e: {target: {value: string}}) => updatePypfopt('artifactsRoot',e.target.value)} /></label>
      <button disabled={!!busy} onClick={() => runTask('refresh', () => refresh(dataRoot))}>读取来源目录</button>
      <p>目录改变后必须重新读取。优化器配置和组合模拟接口的默认目录限制会明确阻止不兼容操作。</p>
    </details>
  </details>;
  const sourceCards = <div className="workspace-source-list">
    <h3>选择研究来源</h3><p>选择只打开草稿。未通过证据检查的候选仍可查看，但不能据此进入执行。</p>
    {!candidates.length && !qlibRuns.length && !manifests.length && <div className="research-empty">
      <p>{readFailures.some(name => ['候选列表','Qlib','策略证据'].includes(name)) ? '研究来源读取失败，当前数量未知。' : '还没有研究来源。先完成实验与证据，再选择用于组合。'}</p>
      <Link to={workspaceLink('research', {...currentContext(),candidate:'',experiment:'',qlibRun:'',portfolioRun:'',manifests:[],simulation:''},'cycle')}>前往研究台创建实验</Link></div>}
    {candidates.map(candidate => <article key={candidate.candidate_id}>
      <div><strong>{candidate.strategy_id}</strong><p>{candidate.candidate_id} · {candidate.experiment_id}</p><StatusPill value={candidate.promotion_status} /></div>
      <button disabled={!!busy || rootMismatch} onClick={() => go('portfolio',candidateContext(candidate),'simulate')}>用于组合 · {candidate.candidate_id}</button>
    </article>)}
    {qlibRuns.map(run => <article key={run.run_id}>
      <div><strong>Qlib · {run.run_id}</strong><p>评分 {fmt(run.score_rows,0)} 条 · {String(run.workflow_status || run.dataset_status || '未知')}</p></div>
      <button disabled={!!busy || rootMismatch} onClick={() => go('portfolio',{candidate:'',experiment:'',manifests:[],qlibRun:String(run.run_id),portfolioRun:'',simulation:'',dataVersion:String(run.data_version || ''),featureVersion:''},'optimize')}>用于组合 · {run.run_id}</button>
    </article>)}
    {manifests.filter(m => !candidates.some(c => c.candidate_id === m.source_candidate_id)).map(m => <article key={m.strategy_candidate_id}>
      <div><strong>{m.strategy_candidate_id}</strong><StatusPill value={m.promotion_status} /></div>
      <button disabled={!!busy || rootMismatch} onClick={() => go('portfolio',{candidate:'',experiment:'',qlibRun:'',portfolioRun:'',simulation:'',manifests:[String(m.strategy_candidate_id)],dataVersion:'',featureVersion:''},'simulate')}>使用此策略证据</button>
    </article>)}
  </div>;

  if (loading) {
    return (
      <WorkbenchFrame className="research-workbench" mode={surface === 'portfolio' ? 'portfolio' : surface === 'review' ? 'execution' : 'research'}>
        <WorkbenchHeader
          code="RQ"
          eyebrow="Research / Evidence"
          title={portfolioTitle}
          description="加载实验、候选、特征、证据注册表与组合集成状态。"
          status="LOADING"
          statusTone="info"
          secondaryStatus="PAPER / LIVE LOCKED"
        />
        <WorkbenchPanel title="加载研究数据" kicker="Research Registry">
          <LoadingSpinner text="加载研究数据..." />
        </WorkbenchPanel>
      </WorkbenchFrame>
    );
  }

  return (
    <WorkbenchFrame className={`research-workbench research-v2 workspace-unified workspace-${surface}`} testId={surface === 'research' ? 'research-content' : `workspace-${surface}`} mode={surface === 'portfolio' ? 'portfolio' : surface === 'review' ? 'execution' : 'research'}>
      <div className="research-page-heading">
        <div><span className="research-eyebrow">{surface === 'research' ? 'RESEARCH LAB' : surface === 'portfolio' ? 'PORTFOLIO LAB' : 'EXECUTION SAFETY / REVIEW'}</span><h2>{portfolioTitle} <span>{surface === 'research' ? '从假设到候选' : surface === 'portfolio' ? '从候选到组合证据' : '独立审批 · 交易仍锁定'}</span></h2></div>
        <div className="research-heading-actions"><span className="research-lock">仅研究 · 交易锁定</span><a href={surface === 'portfolio' ? '/portfolio?layout=legacy' : '/research?layout=previous'}>切回改版前</a>{surface === 'research' && <a href="/research?layout=legacy">切回原版</a>}
          <button disabled={!!busy} onClick={() => runTask('refresh', async () => refresh(dataRoot))}>刷新状态</button></div>
      </div>
      {!workspaceAccess.researchWrites && <p className="research-feedback" role="status">{workspaceAccess.reason}</p>}
      {surface === 'research' && <ResearchNavigation tab={tab} onChange={setTab} />}
      {surface === 'research' && <>{tab === 'research-overview' && <ResearchOverview loading={loading} readFailures={readFailures} readFailureDetails={readFailureDetails} readAt={readAt}
        experiments={experiments} candidates={candidates} manifests={manifests}
        qlib={qlibStatus} portfolio={portfolioIntegrationStatus} overview={systemOverview} registry={registry}
        root={loadedRoot} onNavigate={setTab} busy={busy} />}
      {tab === 'qlib' ? <section style={sectionStyle} data-testid="qlib-research-context" aria-label="Qlib 研究上下文">
        <strong>Qlib 研究上下文 · {detailQlibId ? (verifiedQlibContext ? '已核验研究版本' : '未核验，事实未知') : '待运行配置'}</strong>
        <p>运行 ID：{detailQlibId || '待运行'} · 配置：{detailQlibId
          ? (verifiedQlibContext ? qlibContextIdentity?.profile_id || checkedQlibDetail?.summary?.profile_id || '未知' : '未知')
          : draftQlibProfile?.profile_id || '未核验'}</p>
        <p>{detailQlibId
          ? (verifiedQlibContext ? `${qlibContextIdentity?.instrument || checkedQlibDetail?.summary?.symbols?.join(', ') || '标的未知'} · ${qlibContextIdentity?.bar_size || checkedQlibDetail?.summary?.bar_size || '周期未知'}` : '标的、周期与数据版本未知；不回退到默认股票配置。')
          : `${draftQlibProfile?.symbols?.join(', ') || '标的未核验'} · ${draftQlibProfile?.bar_size || '周期未核验'} · ${draftQlibProfile?.start_date || '日期未核验'} → ${draftQlibProfile?.end_date || '日期未核验'}`}</p>
        <p className="research-footnote">已选运行事实与下方新建配置分开；历史研究不代表当前行情或真实账户。</p>
      </section> : !['data','factors','cycle'].includes(tab) ? null : <ResearchContext open={contextOpen} onToggle={() => setContextOpen(value => !value)}
        value={autoForm} onChange={updateContext} errors={contextErrors} disabled={!!busy} />}</>}
      {(surface !== 'research' || tab === 'handoff' || source.candidate || source.experiment || source.qlibRun || source.manifests.length > 0) && sourcePanel}
      {detailError && <p role="alert" className="research-feedback error">{detailError}</p>}
      {surface !== 'research' && readFailures.length > 0 && <p role="alert" className="research-feedback">部分状态读取失败：{readFailures.join('、')}；失败不代表零记录。</p>}
      {error ? <div className="research-feedback error" role="alert">{error}</div> : null}
      {message ? <div className="research-feedback" role="status">{message}</div> : null}
      {busy ? <div className="research-feedback" role="status">任务进行中：{busy}。完成后请查看结果与各环节检查。</div> : null}
      {surface === 'research' ? null : surface === 'portfolio' ? <nav className="workspace-tabs" aria-label="投资组合工作流" role="tablist" onKeyDown={navigateTabs}>
        {[['overview','来源与版本'],['optimize','权重优化'],['simulate','组合模拟'],['risk','风险与证据']].map(([key,label]) => <button key={key} id={'research-tab-'+key} role="tab" tabIndex={tab===key ? 0 : -1} aria-selected={tab===key} aria-controls="research-active-panel" onClick={() => setTab(key)}>{label}</button>)}
      </nav> : <nav className="research-actions"><Link to="/live">返回执行安全中心总览</Link></nav>}
      <section id="research-active-panel" role="tabpanel" aria-label={surface === 'review' ? '人工复核' : undefined} aria-labelledby={surface === 'review' ? undefined : `research-tab-${tab}`} className="research-active-panel">
      {surface === 'research' && tab === 'research-overview' && <div className="research-start-grid">
        <section className="research-intro-card"><h3>自动研究 · Alpha 工厂</h3><p>统一生成、Qlib 训练、筛选与研究提名。批次状态由工厂自己的证据读取，不混入规则实验计数。</p><button onClick={() => setTab('alpha-factory')}>进入 Alpha 工厂 →</button></section>
        <section className="research-intro-card"><h3>运行详情与决策回放</h3><p>按精确运行编号核验结果与七层研究证据。真实运行未绑定时，明确保留未知。</p><button onClick={() => setTab('run-details')}>选择研究运行 →</button></section>
      </div>}
      {tab === 'handoff' && <><section className="research-intro-card"><h3>研究结论与交接</h3><p>保留研究证据，只把选中的来源用于组合草稿。优化、组合模拟和风险报告在投资组合页统一处理。</p></section>{sourceCards}</>}
      {tab === 'overview' && <div className="workspace-overview">
        <section className="research-intro-card"><h3>组合研究，不是账户持仓</h3><p>所有视图共用同一组合运行 ID 和来源。历史模拟、目标权重与实际持仓严格区分；此页没有真实账户或下单连接。</p>
          <div className="research-data-facts"><div><span>可读取组合版本</span><strong>{readFailures.includes('组合工具') ? '未知' : portfolioIntegrationRuns.length}</strong></div><div><span>当前选择</span><strong>{selectedPortfolioRunId || '未选择'}</strong></div><div><span>执行权限</span><strong>未授予</strong></div></div>
          {portfolioIntegrationRuns.map(run => <article className="workspace-run-row" key={run.portfolio_run_id}><div><strong>{run.portfolio_run_id}</strong><p>评分来源 {run.source_score_run_id || '未绑定'} · {String(run.status || '未知')} · {run.fallback_used ? '已使用降级优化器' : '未标记降级'}</p></div><button disabled={!!busy || rootMismatch} onClick={() => go('portfolio',{portfolioRun:String(run.portfolio_run_id),qlibRun:String(run.source_score_run_id || ''),candidate:'',experiment:'',manifests:[],simulation:'',dataVersion:'',featureVersion:''},'optimize')}>查看此组合版本</button></article>)}
          {!portfolioIntegrationRuns.length && <p>{readFailures.includes('组合工具') ? '组合运行读取失败，不能判断是否存在版本。' : '尚未生成组合版本。选择下方研究来源，或前往权重优化建立研究组合。'}</p>}
        </section>{sourceCards}
        <details className="research-intro-card"><summary>旧目标快照（独立来源，不作为当前组合结果）</summary><p>来源：data/portfolio/targets。策略权重与标的目标权重不是同一指标；此快照不表示实际账户持仓。</p>
          {persistedPortfolioError ? <p role="alert">{persistedPortfolioError}</p> : persistedPortfolio ? <><p>快照编号：{String(persistedPortfolio.portfolio_id)} · 日期：{String(persistedPortfolio.date)}</p><PortfolioOverview pf={persistedPortfolio as any} /></> : <p>没有旧目标快照。</p>}
          <p className="research-footnote">再平衡尚未接入受控提交；当前快照只用于查看。</p></details>
      </div>}
      {tab === 'risk' && <div className="workspace-overview">
        <section className="research-intro-card"><h3>所选组合的风险与来源证据</h3><p>仅展示实际回测 / 运行证据。不用波动率倍数冒充最大回撤或 VaR，不把任务 completed 当作全部检查通过。</p>
          <p>当前版本：{selectedPortfolioRunId || '未选择'} · 评分来源：{pypfoptForm.scoreRunId || '未选择'}</p>
          {latestPortfolioRun?.fallback_used && <p className="warning">所选组合使用了降级优化器，请核对原因。</p>}
          {!executionPipelineResult && !portfolioResult && <p>本页尚未加载风险回测结果；没有证据不表示风险为零或已通过。</p>}
          <button onClick={() => setTab('optimize')}>查看权重与运行风险验证</button>
          <p className="research-footnote">实际持仓风险未连接账户，当前只展示研究运行证据。</p>
        </section>
        <ResultBlock title="风险回测结果（逐项核验）" value={executionPipelineResult} />
        <p className="research-footnote">组合模拟为现有简化研究模型，估计指标不等于真实成交回测或准入证据。</p><ResultBlock title="组合模拟证据" value={portfolioResult} />
        <ResultBlock title="所选组合版本原件" value={portfolioIntegrationDetail?.run_manifest} />
        <section className="research-intro-card"><h3>准入状态独立判断</h3><StatusPill value={paperReviewEntry?.status || systemOverview?.paper_review?.status || 'UNKNOWN'} /><p>{(paperReviewEntry?.why_blocked || []).join('；') || '此处不提供准入通过证明。'}</p><Link to={workspaceLink('review',currentContext({simulation:String(portfolioResult?.portfolio_sim_id || source.simulation)}))}>前往执行安全中心复核</Link></section>
      </div>}
      {tab === 'data' && <div className="research-start-grid">
        <section className="research-intro-card">
          <span className="research-eyebrow">01 / 准备研究输入</span>
          <h3>先确认数据，再开始实验</h3>
          <p>标的、区间与周期沿用上方研究上下文。数据版本、缺口和可见时间，需要以实际数据检查结果为准。</p>
          <div className="research-data-facts">
            <div><span>当前数据目录</span><strong>{loadedRoot}</strong></div>
            <div><span>分钟数据检查</span><strong>{statusLabel(String(systemOverview?.minute_data_quality?.status || 'UNKNOWN'))}</strong></div>
            <div><span>冻结特征</span><strong>{readFailures.includes('特征快照') ? '读取失败' : features.length}</strong></div>
          </div>
          <p className="research-footnote">分钟数据缺失仅影响相应周期；日频数据是否齐备仍需独立核验。Qlib 的股票池与训练区间由它自己的配置文件定义。</p>
          <div className="research-actions"><button className="primary" onClick={() => setTab('factors')}>进入因子评估</button><button onClick={() => setTab('workflow')}>查看数据与证据检查</button></div>
        </section>
        <section className="research-intro-card">
          <span className="research-eyebrow">研究路径</span><h3>选择适合当前假设的入口</h3>
          <button className="research-route" onClick={() => setTab('cycle')}><strong>规则策略实验 →</strong><span>配置策略和参数，运行回测与稳健性验证</span></button>
          <button className="research-route" onClick={() => setTab('qlib')}><strong>Qlib 模型研究 →</strong><span>准备日频数据、训练模型、导入评分并形成研究候选</span></button>
          <p className="research-footnote">两条研究路径按需选择；不要求每个实验都使用 Qlib。</p>
        </section>
        <details className="research-source-details"><summary>数据目录与读取范围</summary>
          <Field label="数据根目录"><input style={inputStyle} value={dataRoot} onChange={(e: any) => setDataRoot(e.target.value)} /></Field>
          <button disabled={!!busy} onClick={() => runTask('refresh', async () => refresh(dataRoot))}>读取此目录</button>
          <p>读取时间：{readAt || '未读取'}。读取时间不是市场数据截止时间；特征快照目录沿用现有服务默认配置。</p>
        </details>
      </div>}
      {tab === 'workflow' && (
        <div style={{display: 'grid', gap: 16}}>
          <section style={{display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10}}>
            {[
              ['分钟数据质量', systemOverview?.minute_data_quality?.status || 'MISSING'],
              ['manifest', manifests.length],
              ['纸交易复核队列', pendingReviews.length],
              ['目标权重', targetWeightStatus],
            ].map(([label, value]) => (
              <div key={String(label)} style={sectionStyle}>
                <div style={{fontSize: '0.75rem', color: '#94a3b8'}}>{label}</div>
                <div style={{fontSize: '1.1rem', fontWeight: 750, marginTop: 4}}>{typeof value === 'string' ? statusLabel(value) : String(value)}</div>
              </div>
            ))}
          </section>

          <section style={sectionStyle}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
              <h3 style={{margin: 0}}>全局注册表</h3>
              <StatusPill value={readString(globalRegistry?.paper_queue_status, 'locked')} />
            </div>
            <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10}}>
              <div><span style={{color: '#94a3b8'}}>美股</span><br />{readString(globalUsEquity?.status, '缺失')}</div>
              <div><span style={{color: '#94a3b8'}}>美股阻塞项</span><br />{globalUsBlockers.length}</div>
              <div><span style={{color: '#94a3b8'}}>BTC 数据</span><br />{readString(globalBtcDataStatus?.status, '缺失')}</div>
              <div><span style={{color: '#94a3b8'}}>BTC 当前候选</span><br />{globalBtcCandidates.map(row => row.name).join(', ') || '-'}</div>
            </div>
            <div style={{marginTop: 10, color: '#94a3b8', fontSize: '0.78rem', display: 'grid', gap: 4}}>
              <span>因子证据：{readString(globalUsEquity?.latest_factor_evidence, '-')}</span>
              <span>组合报告：{readString(globalUsEquity?.latest_portfolio_report, '-')}</span>
              <span>BTC 归因：{readString(globalBtcCandidates[0]?.latest_attribution_report, '-')}</span>
            </div>
          </section>

          <div style={{display: 'grid', gridTemplateColumns: 'minmax(420px, 0.9fr) minmax(560px, 1.1fr)', gap: 16}}>
            <section style={sectionStyle}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
                <h3 style={{margin: 0}}>分钟数据修复</h3>
                <StatusPill value={systemOverview?.minute_data_quality?.status || 'MISSING'} />
              </div>
              <div style={{display: 'grid', gap: 8}}>
                {minuteRemediationActions.slice(0, 8).map((action, index) => (
                  <div key={`${action.category || 'action'}-${index}`} style={{borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 8}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center'}}>
                      <strong>{readString(action.summary, readString(action.category, '修复'))}</strong>
                      <StatusPill value={readString(action.severity, '信息')} />
                    </div>
                    <div style={{color: '#94a3b8', fontSize: '0.78rem', marginTop: 4}}>
                      {readString(action.command, readString(action.dataset_root, readString(action.bar_size, '检查数据集')))}
                    </div>
                  </div>
                ))}
                {!minuteRemediationActions.length ? <span style={{color: '#94a3b8'}}>暂无修复建议，分钟数据质量已通过或尚未生成细项。</span> : null}
              </div>
              <div style={{display: 'flex', gap: 10, marginTop: 14}}>
                <button style={ghostButtonStyle} disabled={!!busy} onClick={() => runTask('refresh', async () => refresh(dataRoot))}>刷新状态</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={handleRegistryRebuild}>重建注册表</button>
              </div>
            </section>

            <section style={sectionStyle}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
                <h3 style={{margin: 0}}>晋升阻塞项</h3>
                <StatusPill value={systemOverview?.paper_review?.status || 'UNKNOWN'} />
              </div>
              <div style={{display: 'grid', gap: 8}}>
                {(paperReviewEntry?.why_blocked || systemOverview?.next_actions || []).slice(0, 6).map((action: string) => (
                  <div key={action} style={{borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 8, color: '#cbd5e1'}}>
                    {action}
                  </div>
                ))}
                {!((paperReviewEntry?.why_blocked || systemOverview?.next_actions || []).length) ? <span style={{color: '#94a3b8'}}>暂无全局阻塞项。</span> : null}
              </div>
              <div style={{marginTop: 14, fontSize: '0.8rem', color: '#94a3b8', display: 'grid', gap: 6}}>
                <span>复核摘要：{systemOverview?.paper_review?.summary || '-'}</span>
                <span>注册表：{summarizeResearchRegistry(registry, systemOverview).status}</span>
                <span>manifest：{systemOverview?.paper_review?.manifest_path || '-'}</span>
                <span>下一条命令：{paperReviewEntry?.next_command || systemOverview?.paper_review?.creation?.next_command || '-'}</span>
              </div>
            </section>
          </div>

          <section style={sectionStyle}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
              <h3 style={{margin: 0}}>策略 manifest 证据</h3>
              <div style={{display: 'flex', gap: 8}}>
                <button style={buttonStyle} disabled={sourceActionBlocked || !selectedManifestIds.length} onClick={() => go('portfolio', {}, 'simulate')}>将所选证据用于组合</button>
              </div>
            </div>
            <div style={{display: 'grid', gap: 10}}>
              {workflowManifestRows.map(row => {
                const checked = selectedManifestIds.includes(row.id);
                return (
                  <div key={row.id} style={{border: '1px solid rgba(148,163,184,0.12)', borderRadius: 6, padding: 12}}>
                    <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr auto auto', gap: 10, alignItems: 'center'}}>
                      <input type="checkbox" checked={checked} onChange={() => toggleManifestSelection(row.id)} />
                      <div>
                        <strong>{row.id}</strong>
                        <div style={{color: '#94a3b8', fontSize: '0.78rem', marginTop: 3}}>
                          {row.sourceCandidateId || '-'} · {row.symbols} · 复核 {row.reviewStatus}
                        </div>
                      </div>
                      <StatusPill value={row.status} />
                      <button style={ghostButtonStyle} disabled={!!busy || rootMismatch} onClick={() => go('review', {manifests:[row.id]})}>前往安全中心复核</button>
                    </div>
                    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 10, fontSize: '0.78rem'}}>
                      <div>
                        <div style={{color: '#94a3b8', marginBottom: 4}}>证据</div>
                        <div style={{display: 'grid', gap: 4}}>
                          {row.evidencePairs.map(([label, value]) => <span key={String(label)}>{String(label)}: {String(value)}</span>)}
                          {!row.evidencePairs.length ? <span style={{color: '#94a3b8'}}>暂无已绑定证据</span> : null}
                        </div>
                      </div>
                      <div>
                        <div style={{color: '#94a3b8', marginBottom: 4}}>阻塞项</div>
                        <div style={{display: 'grid', gap: 4}}>
                          {row.blockingReasons.length ? row.blockingReasons.slice(0, 6).map(reason => <span key={reason} style={{color: '#fca5a5'}}>{reason}</span>) : <span style={{color: '#86efac'}}>无显式阻塞项</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
              {!workflowManifestRows.length ? <span style={{color: '#94a3b8'}}>暂无策略 manifest；先物化候选证据。</span> : null}
            </div>
          </section>

          <div style={{display: 'grid', gridTemplateColumns: 'minmax(360px, 0.8fr) minmax(620px, 1.2fr)', gap: 16}}>
            <section style={sectionStyle}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
                <h3 style={{margin: 0}}>纸交易复核队列</h3>
                <StatusPill value={systemOverview?.paper_review?.status || 'EMPTY'} />
              </div>
              <div style={{display: 'grid', gap: 8}}>
                {pendingReviews.map(review => (
                  <div key={String(review.paper_review_id)} style={{borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 8, display: 'grid', gap: 6}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center'}}>
                      <strong>{String(review.paper_review_id)}</strong>
                      <StatusPill value={String(review.status || 'UNKNOWN')} />
                    </div>
                    <div style={{color: '#94a3b8', fontSize: '0.78rem'}}>
                      {String(review.strategy_manifest_id || review.portfolio_sim_id || '-')}
                    </div>
                    <button style={ghostButtonStyle} disabled={!!busy || rootMismatch} onClick={() => go('review')}>查看独立复核</button>
                  </div>
                ))}
                {!pendingReviews.length ? <span style={{color: '#94a3b8'}}>当前没有待处理队列。</span> : null}
              </div>
            </section>

            <section style={sectionStyle}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
                <h3 style={{margin: 0}}>目标权重 / 回测入口</h3>
                <StatusPill value={targetWeightStatus} />
              </div>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, marginBottom: 12}}>
                <div><span style={{color: '#94a3b8'}}>组合运行</span><br />{readString(latestPortfolioRun?.portfolio_run_id, '-')}</div>
                <div><span style={{color: '#94a3b8'}}>优化器</span><br />{readString(latestPortfolioRun?.optimizer, '-')}</div>
                <div><span style={{color: '#94a3b8'}}>权重合计</span><br />{pct(latestPortfolioRun?.latest_weight_sum)}</div>
              </div>
              <p style={{marginTop: 0, color: '#cbd5e1', fontSize: '0.82rem'}}>{targetWeightDetail}</p>
              <div className="research-actions"><button style={buttonStyle} disabled={!!busy || rootMismatch} onClick={() => go('portfolio',{},'overview')}>前往组合构建与风险</button></div>
              <ResultBlock title="研究执行流水线" value={executionPipelineResult} />
              <PreviewTable
                title="最新 target_positions"
                rows={portfolioIntegrationDetail?.target_positions_preview || pypfoptActionResult?.preview}
                columns={['timestamp_utc', 'strategy_id', 'symbol', 'target_weight', 'target_quantity']}
              />
            </section>
          </div>
        </div>
      )}

      {tab === 'cycle' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(340px, 0.9fr) minmax(420px, 1.1fr)', gap: 16}}>
          <section id="research-experiment-form" ref={experimentFormRef} style={sectionStyle}>
            <h3 style={{marginTop: 0}}>新建策略实验</h3><p className="research-footnote">使用共享研究上下文：{autoForm.symbols} · {autoForm.barSize} · {autoForm.start} 至 {autoForm.end}</p>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="策略 ID"><input style={inputStyle} value={autoForm.strategyId} onChange={(e: any) => updateAuto('strategyId', e.target.value)} /></Field>
              <Field label="策略族"><input style={inputStyle} value={autoForm.family} onChange={(e: any) => updateAuto('family', e.target.value)} /></Field>
            </div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12}}>
              <details className="research-advanced" open><summary>策略参数 · 高级 JSON</summary><p className="research-footnote">仅填写当前策略支持的参数。参数网格会生成多组实验。</p><Field label="params JSON"><textarea style={{...inputStyle, minHeight: 92}} value={autoForm.params} onChange={(e: any) => updateAuto('params', e.target.value)} /></Field>
              <Field label="param_grid JSON"><textarea style={{...inputStyle, minHeight: 92}} value={autoForm.paramGrid} onChange={(e: any) => updateAuto('paramGrid', e.target.value)} /></Field></details>
            </div>
            <div style={{display: 'flex', gap: 10, marginTop: 14}}>
              <button style={buttonStyle} disabled={actionBlocked || contextErrors.length > 0} onClick={handleAutoCycle}>运行研究闭环</button>
              <button style={ghostButtonStyle} disabled={actionBlocked} onClick={handleRegistryRebuild}>重建证据注册表</button>
            </div>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>闭环结果</h3>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10}}>
                <div><span style={{color: '#94a3b8'}}>状态</span><br /><StatusPill value={String(autoResult?.status || '-')} /></div>
                <div><span style={{color: '#94a3b8'}}>流水线</span><br />{fmt(autoResult?.pipeline_result?.pipeline_id)}</div>
                <div><span style={{color: '#94a3b8'}}>候选数</span><br />{fmt(autoResult?.candidate_ids?.length ?? 0, 0)}</div>
                <div><span style={{color: '#94a3b8'}}>注册表</span><br />{summarizeResearchRegistry(registry, systemOverview).status}</div>
              </div>
            </section>
            <ResultBlock title="闭环结果载荷" value={autoResult} />
          </div>
        </div>
      )}

      {tab === 'factors' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(340px, 0.9fr) minmax(420px, 1.1fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>因子评估</h3><p className="research-footnote">使用共享研究上下文：{factorForm.symbols} · {factorForm.barSize} · {factorForm.start} 至 {factorForm.end}</p>
            <p className="research-footnote">横截面 IC 需要同日不少于 10 个有效标的。有效样本为 0 不能视为评估成功；少量标的可先计算预览。</p>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="因子"><select style={inputStyle} value={factorForm.factorId} onChange={(e: any) => updateFactor('factorId', e.target.value)}>{factors.map(f => <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>)}</select></Field>
              <Field label="前瞻周期"><input style={inputStyle} value={factorForm.forwardPeriod} onChange={(e: any) => updateFactor('forwardPeriod', e.target.value)} /></Field>
            </div>
            <div style={{display: 'flex', gap: 10, marginTop: 14}}>
              <button style={buttonStyle} disabled={actionBlocked || contextErrors.length > 0} onClick={handleFactorEvaluate}>运行因子评估</button>
              <button style={ghostButtonStyle} disabled={actionBlocked || contextErrors.length > 0} onClick={handleFactorCompute}>计算预览</button>
              <details className="research-advanced"><summary>高级：因子挖掘</summary><p className="research-footnote">可能运行多个周期及多组参数，耗时随数据规模增加。</p><button style={ghostButtonStyle} disabled={actionBlocked || contextErrors.length > 0} onClick={handleFactorMine}>自动挖掘</button>
              <button style={ghostButtonStyle} disabled={actionBlocked || contextErrors.length > 0} onClick={handleFactorMineAndRun}>挖掘+回测</button></details>
            </div>
            <h3 style={{margin: '18px 0 10px'}}>冻结特征快照</h3>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
              <Field label="feature_id"><select style={inputStyle} value={featureForm.featureId} onChange={(e: any) => updateFeature('featureId', e.target.value)}>{factors.map(f => <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>)}</select></Field>
              <Field label="version"><input style={inputStyle} value={featureForm.version} onChange={(e: any) => updateFeature('version', e.target.value)} /></Field>
            </div>
            <button style={{...buttonStyle, marginTop: 14}} disabled={actionBlocked || contextErrors.length > 0} onClick={handleFeatureBuild}>构建特征快照</button>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>因子指标</h3>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10}}>
                <div><span style={{color: '#94a3b8'}}>IC mean</span><br />{fmt(factorResult?.ic_mean, 4)}</div>
                <div><span style={{color: '#94a3b8'}}>Rank IC</span><br />{fmt(factorResult?.rank_ic_mean, 4)}</div>
                <div><span style={{color: '#94a3b8'}}>ICIR</span><br />{fmt(factorResult?.icir, 3)}</div>
                <div><span style={{color: '#94a3b8'}}>样本数</span><br />{fmt(factorResult?.n_observations, 0)}</div>
              </div>
            </section>
            <ResultBlock title="因子预览" value={factorPreview} />
            <ResultBlock title="因子挖掘" value={factorMiningResult} />
            <ResultBlock title="特征快照" value={featureResult} />
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>已冻结特征</h3>
              <div style={{display: 'grid', gap: 8}}>
                {features.slice(0, 8).map(s => (
                  <div key={s.snapshot_id} style={{display: 'grid', gridTemplateColumns: '1.5fr 0.6fr 0.6fr 0.6fr', gap: 8, fontSize: '0.8rem'}}>
                    <span>{s.snapshot_id}</span><span>{s.bar_size || '1d'}</span><span>{fmt(s.row_count, 0)}</span><span>{s.feature_version}</span>
                  </div>
                ))}
                {!features.length ? <span style={{color: '#94a3b8'}}>暂无特征快照</span> : null}
              </div>
            </section>
          </div>
        </div>
      )}

      {tab === 'evidence' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(620px, 1fr) minmax(360px, 0.7fr)', gap: 16}}>
          <section style={sectionStyle}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
              <h3 style={{margin: 0}}>候选证据操作</h3>
              <button style={ghostButtonStyle} disabled={actionBlocked} onClick={handleRegistryRebuild}>重建注册表</button>
            </div>
            <div style={{overflowX: 'auto'}}>
              <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem'}}>
                <thead style={{color: '#94a3b8'}}>
                  <tr>
                    <th style={{textAlign: 'left', padding: 8}}>候选</th>
                    <th style={{textAlign: 'left', padding: 8}}>策略</th>
                    <th style={{textAlign: 'left', padding: 8}}>周期</th>
                    <th style={{textAlign: 'left', padding: 8}}>状态</th>
                    <th style={{textAlign: 'left', padding: 8}}>证据</th>
                    <th style={{textAlign: 'left', padding: 8}}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map(candidate => {
                    const evidenceCount = [
                      candidate.backtest_manifest_path,
                      candidate.scorecard_path,
                      candidate.walk_forward_result_path,
                      candidate.cost_stress_result_path,
                    ].filter(Boolean).length;
                    return (
                      <tr key={candidate.candidate_id} style={{borderTop: '1px solid rgba(148,163,184,0.12)'}}>
                        <td style={{padding: 8}}>{candidate.candidate_id}</td>
                        <td style={{padding: 8}}>{candidate.strategy_id}</td>
                        <td style={{padding: 8}}>{candidate.timeframe || '-'}</td>
                        <td style={{padding: 8}}><StatusPill value={candidate.promotion_status} /></td>
                        <td style={{padding: 8}}>{evidenceCount}/4</td>
                        <td style={{padding: 8}}>
                          <div style={{display: 'flex', flexWrap: 'wrap', gap: 6}}>
                            <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleCandidateAction(candidate.candidate_id, 'materialize')}>物化</button>
                            <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleCandidateAction(candidate.candidate_id, 'gate')}>门禁</button>
                            <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleCandidateAction(candidate.candidate_id, 'pack')}>证据包</button>
                            <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleCandidateAction(candidate.candidate_id, 'robustness')}>R6</button>
                            <button style={buttonStyle} disabled={!!busy || rootMismatch} onClick={() => go('portfolio',candidateContext(candidate),'simulate')}>用于组合</button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!candidates.length ? <div className="research-empty"><p>还没有候选：研究实验 → 回测与评分 → 候选证据。</p><button onClick={openExperimentForm}>创建第一个实验</button></div> : null}
            </div>
          </section>
          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>证据注册表</h3>
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: '0.82rem'}}>
                <span>结构版本</span><span>{fmt(registry?.schema_version)}</span>
                <span>状态</span><span>{fmt(summarizeResearchRegistry(registry, systemOverview).status)}</span>
                <span>路径</span><span>{fmt(registry?.registry_path || registry?.path)}</span>
              </div>
              {summarizeResearchRegistry(registry, systemOverview).qualification === 'blocked' && <p role="alert" className="warning">
                注册表已返回 {summarizeResearchRegistry(registry, systemOverview).status}，共 {summarizeResearchRegistry(registry, systemOverview).notesTotal} 条说明；这是可读的冲突状态，不代表证据合格或可晋级。
                {summarizeResearchRegistry(registry, systemOverview).notes.length > 0 && <span> 前 3 条：{summarizeResearchRegistry(registry, systemOverview).notes.join('；')}</span>}
              </p>}
            </section>
            <ResultBlock title="候选操作结果" value={candidateActionResult} />
          </div>
        </div>
      )}

      {(tab === 'qlib' || tab === 'optimize') && (
        <div style={{display: 'grid', gap: 16}}>
          <section data-testid="research-dependencies" style={{...sectionStyle, display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12}}>
            <div>
              <div style={{color: '#94a3b8', fontSize: '0.75rem'}}>Qlib 依赖</div>
              <StatusPill value={typeof qlibStatus?.dependencies?.qlib !== 'boolean' ? 'unknown' : qlibStatus.dependencies.qlib ? 'installed' : 'missing'} />
            </div>
            <div>
              <div style={{color: '#94a3b8', fontSize: '0.75rem'}}>LightGBM</div>
              <StatusPill value={typeof qlibStatus?.dependencies?.lightgbm !== 'boolean' ? 'unknown' : qlibStatus.dependencies.lightgbm ? 'installed' : 'missing'} />
            </div>
            <div>
              <div style={{color: '#94a3b8', fontSize: '0.75rem'}}>PyPortfolioOpt</div>
              <StatusPill value={typeof portfolioIntegrationStatus?.dependencies?.pypfopt !== 'boolean' ? 'unknown' : portfolioIntegrationStatus.dependencies.pypfopt ? 'installed' : 'missing'} />
            </div>
            <div>
              <div style={{color: '#94a3b8', fontSize: '0.75rem'}}>边界</div>
              <strong>股票日线 / BTC 小时线 · 仅研究</strong>
            </div>
          </section>

          <TaskQueuePanel title={surface === 'research' ? 'Qlib 研究任务' : '组合优化任务'} tasks={integrationTasks.filter(t => surface === 'research' ? t.kind !== 'portfolio_optimize_weights' : t.kind === 'portfolio_optimize_weights')} onRefresh={refreshTaskQueue} emptyText="暂无 Qlib 或 PyPortfolioOpt 后台任务" />

          {tab === 'qlib' && (<>
          <div style={{display: 'grid', gridTemplateColumns: 'minmax(380px, 0.95fr) minmax(520px, 1.05fr)', gap: 16}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>Qlib 统一研究引擎</h3>
              <Field label="研究配置"><select style={inputStyle} aria-label="Qlib 研究配置" value={qlibForm.profileId} disabled={actionBlocked}
                onChange={(event: any) => {
                  const profile = qlibStatus?.profiles?.find((item: LooseRecord)=>item.profile_id===event.target.value);
                  if (!profile) return;
                  clearQlibSourceContext(profile.profile_id);
                  setQlibForm(current=>({...current,profileId:profile.profile_id,dataVersion:profile.data_version || 'latest',
                    universe:profile.universe,qlibConfig:profile.config,startDate:profile.start_date,endDate:profile.end_date,
                    source:profile.source,runId:'',dryRun:true}));
                }}>
                {(qlibStatus?.profiles || [{profile_id:'us_equity_daily',label:'美股 · Alpha158 日线'}]).map((profile: LooseRecord)=>
                  <option key={profile.profile_id} value={profile.profile_id}>{profile.label}</option>)}
              </select></Field>
              {qlibForm.profileId === 'okx_btc_trend_1h' && <p className="research-footnote">OKX BTC-USDT-SWAP · 已完成 UTC 小时线 · 固定训练/验证/测试隔离。资金费缺失不填零；这是历史研究，不是实时行情。</p>}
              <p className="research-footnote">实际数据目录：{dataRoot}（共享设置）；已读取目录：{loadedRoot}。</p>
              {dataRoot !== loadedRoot && <p className="warning" role="alert">数据目录尚未重新读取。请返回数据准备并读取此目录后再运行。</p>}
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
                <Field label="数据版本"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.dataVersion} onChange={(e: any) => updateQlib('dataVersion', e.target.value)} /></Field>
                <Field label="运行 ID"><input style={inputStyle} value={qlibForm.runId} onChange={(e: any) => updateQlib('runId', e.target.value)} placeholder="新建时自动生成，导入前明确选择" /></Field>
                <Field label="开始日期"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.startDate} onChange={(e: any) => updateQlib('startDate', e.target.value)} /></Field>
                <Field label="结束日期"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.endDate} onChange={(e: any) => updateQlib('endDate', e.target.value)} /></Field>
                <Field label="标的配置"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.universe} onChange={(e: any) => updateQlib('universe', e.target.value)} /></Field>
                <Field label="工作流配置"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.qlibConfig} onChange={(e: any) => updateQlib('qlibConfig', e.target.value)} /></Field>
                <Field label="产物根目录（服务器固定）"><input aria-label="Qlib 产物根目录" style={inputStyle} value={qlibForm.artifactsRoot} readOnly /></Field>
                <Field label="数据源覆盖"><input disabled={qlibForm.profileId !== 'us_equity_daily'} style={inputStyle} value={qlibForm.source} onChange={(e: any) => updateQlib('source', e.target.value)} placeholder="默认使用股票池配置" /></Field>
              </div>
              <label style={{display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, color: '#cbd5e1', fontSize: '0.82rem'}}>
                <input type="checkbox" checked={qlibForm.dryRun} onChange={(e: any) => updateQlib('dryRun', !!e.target.checked)} />
                仅检查配置（dry-run，不训练模型、不算运行成功）
              </label>
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 14}}>
                <button style={buttonStyle} disabled={actionBlocked || !draftQlibProfile} onClick={() => handleQlibAction('pipeline')}>{qlibForm.dryRun ? '检查统一研究流程' : '运行完整研究流程'}</button>
                <button style={ghostButtonStyle} disabled={!!busy || rootMismatch} onClick={() => {updateQlib('runId','');clearQlibSourceContext();}}>新研究版本</button>
                <button style={buttonStyle} disabled={actionBlocked || qlibForm.profileId !== 'us_equity_daily'} onClick={() => handleQlibAction('build')}>构建数据集</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || qlibForm.profileId !== 'us_equity_daily'} onClick={() => handleQlibAction('workflow')}>运行工作流</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || qlibForm.profileId !== 'us_equity_daily'} onClick={() => handleQlibAction('scores')}>导入评分</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || qlibForm.profileId !== 'us_equity_daily'} onClick={() => handleQlibAction('metrics')}>导入指标</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || qlibForm.profileId !== 'us_equity_daily'} onClick={() => handleQlibAction('manifest')}>编译候选</button>
              </div>
              <p style={{color: '#94a3b8', fontSize: '0.78rem', lineHeight: 1.5}}>
                同一引擎按 profile 区分股票日线与 BTC 永续小时线。研究结果不会自动晋级、启动纸交易或实盘。
              </p>
            </section>

            <div style={{display: 'grid', gap: 12}}>
              <section style={sectionStyle}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
                  <h3 style={{margin: 0}}>Qlib 运行</h3>
                  <button style={ghostButtonStyle} disabled={!!busy} onClick={() => runTask('integration-refresh', refreshIntegrationPanels)}>刷新集成</button>
                </div>
                <div style={{display: 'grid', gap: 8}}>
                  {qlibRuns.slice(0, 8).map(run => (
                    <button
                      key={run.run_id}
                      style={{...ghostButtonStyle, display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 10, textAlign: 'left', alignItems: 'center'}}
                      disabled={actionBlocked}
                      onClick={() => loadQlibRunDetail(String(run.run_id))}
                    >
                      <span>
                        <strong>{run.run_id}</strong>
                        <div style={{fontSize: '0.74rem', color: '#94a3b8'}}>{(run.symbols || []).slice(0, 6).join(', ') || '无标的'}</div>
                      </span>
                      <StatusPill value={run.workflow_status || run.dataset_status} />
                      <span>{fmt(run.score_rows, 0)} 条评分</span>
                    </button>
                  ))}
                  {!qlibRuns.length ? <span style={{color: '#94a3b8'}}>{readFailures.includes('Qlib') ? 'Qlib 状态读取失败，运行记录未知。' : '暂无 Qlib 运行；先构建数据集。'}</span> : null}
                </div>
              </section>
              <ResultBlock title="Qlib 操作结果" value={qlibActionResult} />
              <PreviewTable
                title="research_model_scores 预览"
                rows={qlibRunDetail?.scores_preview}
                columns={['datetime', 'symbol', 'score', 'rank', 'model_id', 'feature_set']}
              />
            </div>
          </div>

          <QlibRunSummary detail={checkedQlibDetail} runId={selectedQlibRunId} search={location.search} />
          {!!selectedQlibRunId && <a href={'/strategy-modules?qlibRun='+encodeURIComponent(selectedQlibRunId)}>在策略模块查看同一研究版本 →</a>}
          <div className="research-actions"><button disabled={sourceActionBlocked || !selectedQlibRunId} onClick={() => go('portfolio',{qlibRun:selectedQlibRunId,portfolioRun:'',candidate:'',experiment:'',manifests:[],simulation:'',dataVersion:String(checkedQlibDetail?.dataset_manifest?.data_version || ''),featureVersion:String(checkedQlibDetail?.dataset_manifest?.feature_version || '')},'optimize')}>将此评分用于组合</button><p className="research-footnote">权重优化和组合模拟统一在投资组合页进行。</p></div></>)}
          {tab === 'optimize' && (<>
          <QlibRunSummary detail={checkedQlibDetail} runId={selectedQlibRunId} search={location.search} />
          {cryptoQlibRun && <p role="status" className="warning">所选 BTC 研究使用现有 BTC 风险预算与纯风控合同生成研究仓位。股票 PyPortfolioOpt 操作禁用；真实持仓以 BTC 执行账本为准。</p>}
          <div style={{display: 'grid', gridTemplateColumns: 'minmax(380px, 0.95fr) minmax(520px, 1.05fr)', gap: 16}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>PyPortfolioOpt 目标权重</h3>
              <p className="research-footnote">这是标的目标权重，不是实际持仓。约束、成本和数据版本以选中配置与运行原件为准；优化器结果不会自动发布到旧目标快照。</p>
              {!!pypfoptForm.portfolioRunId && <p className="warning">{finalizedPortfolioVersion ? '已有权重版本只读，不能覆盖。' : '当前为未完成组合草稿。'}<button disabled={!!busy || rootMismatch} onClick={() => {draftBinding.current = null;setPypfoptForm(current => ({...current,portfolioRunId:''}));setPypfoptActionResult(null);setPortfolioIntegrationDetail(null);go('portfolio',{portfolioRun:'',simulation:''},'optimize');}}>基于此评分新建版本</button></p>}
              {selectedPortfolioRunId && !matchingPortfolioConfig && <p role="alert">配置尚未与所选组合原件匹配。导入目标持仓与风险验证已禁用；请核对原件和配置，不会使用默认配置冒充该版本。</p>}
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
                <Field label="评分运行 ID"><select style={inputStyle} value={pypfoptForm.scoreRunId} disabled={!!pypfoptForm.portfolioRunId || !!busy} onChange={(e: {target: {value: string}}) => go('portfolio',{qlibRun:e.target.value,portfolioRun:'',candidate:'',experiment:'',manifests:[],simulation:'',dataVersion:'',featureVersion:''},'optimize')}>
                  <option value="">明确选择评分来源</option>{qlibRuns.map(run => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.score_rows ?? 0} 条评分</option>)}
                </select></Field>
                <Field label="组合运行 ID"><input style={inputStyle} value={pypfoptForm.portfolioRunId} readOnly placeholder="首次生成后分配运行 ID" /></Field>
                <Field label="优化器配置">
                  <select style={inputStyle} value={pypfoptForm.config} disabled={!!busy || (!!pypfoptForm.portfolioRunId && !finalizedPortfolioVersion)} onChange={(e: any) => updatePypfopt('config', e.target.value)}>
                    <option value="configs/portfolio/pypfopt_long_only_max_sharpe.yaml">max_sharpe</option>
                    <option value="configs/portfolio/pypfopt_long_only_min_volatility.yaml">min_volatility</option>
                    <option value="configs/portfolio/pypfopt_hrp.yaml">hrp</option>
                  </select>
                </Field>
                <Field label="降级优化器"><select style={inputStyle} value={pypfoptForm.fallbackOptimizer} disabled={!!busy || (!!pypfoptForm.portfolioRunId && !finalizedPortfolioVersion)} onChange={(e: any) => updatePypfopt('fallbackOptimizer', e.target.value)}><option value="equal_weight_topk">equal_weight_topk</option><option value="">无</option></select></Field>
                <Field label="产物根目录"><input style={inputStyle} value={pypfoptForm.artifactsRoot} onChange={(e: any) => updatePypfopt('artifactsRoot', e.target.value)} /></Field>
                <Field label="策略 ID"><input style={inputStyle} value={pypfoptForm.strategyId} disabled={!!busy || (!!pypfoptForm.portfolioRunId && !finalizedPortfolioVersion)} onChange={(e: any) => updatePypfopt('strategyId', e.target.value)} /></Field>
              </div>
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 14}}>
                <button style={buttonStyle} disabled={portfolioWriteBlocked} onClick={() => handlePypfoptAction('expected')}>生成预期收益</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || (!!source.portfolioRun)} onClick={() => handlePypfoptAction('covariance')}>生成协方差</button>
                <button style={ghostButtonStyle} disabled={portfolioWriteBlocked} onClick={() => handlePypfoptAction('optimize')}>优化目标权重</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !matchingPortfolioConfig || !firstTargetImportAllowed(portfolioIntegrationRuns,checkedPortfolioDetail,selectedPortfolioRunId)} onClick={() => handlePypfoptAction('import')}>导入目标持仓</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !matchingPortfolioConfig || !latestPortfolioRun?.has_target_positions || latestPortfolioRun?.source_score_run_id !== pypfoptForm.scoreRunId} onClick={handleResearchExecutionPipeline}>运行风险回测流水线</button>
              </div>
              <p className="research-footnote">风险验证口径：初始资金 {portfolioForm.initialCash}；单笔风险比例 25%；滚动训练 / 测试 / 步长 252 / 63 / 63 根。沿用现有后端合同，结果需逐项核验。</p>
              <p style={{color: '#94a3b8', fontSize: '0.78rem', lineHeight: 1.5}}>
                优化器只产目标权重 / TargetPosition 兼容产物；风险验证中的模拟订单不等于真实下单。配置与原件未匹配时禁止导入或复用。
              </p>
            </section>

            <div style={{display: 'grid', gap: 12}}>
              <section style={sectionStyle}>
                <h3 style={{margin: '0 0 10px'}}>组合运行</h3>
                <div style={{display: 'grid', gap: 8}}>
                  {portfolioIntegrationRuns.slice(0, 8).map(run => (
                    <button
                      key={run.portfolio_run_id}
                      style={{...ghostButtonStyle, display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 10, textAlign: 'left', alignItems: 'center'}}
                      disabled={!!busy}
                      onClick={() => go('portfolio',{portfolioRun:String(run.portfolio_run_id),qlibRun:String(run.source_score_run_id || ''),candidate:'',experiment:'',manifests:[],simulation:''},'optimize')}
                    >
                      <span>
                        <strong>{run.portfolio_run_id}</strong>
                        <div style={{fontSize: '0.74rem', color: '#94a3b8'}}>{run.source_score_run_id || '无评分运行'}</div>
                      </span>
                      <StatusPill value={run.fallback_used ? 'fallback' : run.optimizer || 'pending'} />
                      <span>{pct(run.latest_weight_sum)}</span>
                    </button>
                  ))}
                  {!portfolioIntegrationRuns.length ? <span style={{color: '#94a3b8'}}>{readFailures.includes('组合工具') ? '组合工具读取失败，运行记录未知。' : '暂无组合运行；先生成预期收益。'}</span> : null}
                </div>
              </section>
              <ResultBlock title="PyPortfolioOpt 操作结果" value={pypfoptActionResult} />
              <PreviewTable
                title="target_weights 预览"
                rows={portfolioIntegrationDetail?.target_weights_preview || pypfoptActionResult?.preview}
                columns={['datetime', 'symbol', 'target_weight', 'raw_weight', 'clipped_weight', 'optimizer', 'fallback']}
              />
              <PreviewTable
                title="target_positions 预览"
                rows={portfolioIntegrationDetail?.target_positions_preview}
                columns={['timestamp_utc', 'strategy_id', 'symbol', 'target_weight', 'target_quantity']}
              />
            </div>
          </div>

          <ResultBlock title="风险回测结果（逐项核验）" value={executionPipelineResult} /></>)}
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16}}>
            <ResultBlock title="Qlib 运行详情" value={qlibRunDetail?.summary ? {
              summary: qlibRunDetail.summary,
              strategy_manifest: qlibRunDetail.strategy_manifest,
              failure_report: qlibRunDetail.failure_report,
              recorder_metrics: qlibRunDetail.recorder_metrics,
            } : null} />
            <ResultBlock title="组合运行详情" value={portfolioIntegrationDetail?.summary ? {
              summary: portfolioIntegrationDetail.summary,
              run_manifest: portfolioIntegrationDetail.run_manifest,
              target_positions_json: portfolioIntegrationDetail.target_positions_json,
            } : null} />
          </div>
        </div>
      )}

      {(tab === 'review' || tab === 'simulate') && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(360px, 0.8fr) minmax(480px, 1.2fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>{surface === 'review' ? '人工复核 · 独立准入' : '多策略组合模拟'}</h3>
            <div style={{display: 'grid', gap: 12}}>
              {surface === 'portfolio' && <>
                <fieldset className="workspace-manifest-picker" disabled={!!busy || rootMismatch}><legend>选择策略证据（需符合模拟入口要求）</legend>
                  {manifests.map(m => <label key={m.strategy_candidate_id}><input type="checkbox" checked={selectedManifestIds.includes(String(m.strategy_candidate_id))} onChange={() => {toggleManifestSelection(String(m.strategy_candidate_id));updatePortfolio('manifestIds','');}} />
                    <span>{m.strategy_candidate_id} · {String(m.promotion_status || '未知')}</span></label>)}
                  {!manifests.length && <p>{readFailures.includes('策略证据') ? '证据读取失败。' : '暂无策略证据，请返回研究台物化候选。'}</p>}
                </fieldset>
                <Field label="初始资金"><input type="number" min="1" style={inputStyle} value={portfolioForm.initialCash} onChange={(e: any) => updatePortfolio('initialCash', e.target.value)} /></Field>
                <button style={buttonStyle} disabled={actionBlocked || dataRoot !== 'data' || !selectedManifestIds.length || selectedManifestRows.some(m => !['READY_FOR_PORTFOLIO_SIM','PAPER_REVIEW_CANDIDATE'].includes(String(m.promotion_status)))} onClick={handlePortfolioSim}>运行组合模拟</button>
                {dataRoot !== 'data' && <p className="warning">现有模拟接口固定读取默认 data 目录；此自定义目录只读。</p>}
                <p>仅运行选中的证据，不会默认全选。组合模拟输出历史证据，不提交真实订单。</p>
                <Link to={workspaceLink('review',currentContext({simulation:String(portfolioResult?.portfolio_sim_id || source.simulation)}))}>查看独立复核入口</Link>
              </>}
              {surface === 'review' && <>
                <p>先核对来源与准入证据。创建复核和人工批准是不同操作，均不直接授予下单权限。</p>
                <p>组合模拟：{source.simulation || '未选择'} · 策略证据：{selectedManifestIds.join(', ') || '未选择'}</p>
                <button style={ghostButtonStyle} disabled={actionBlocked || dataRoot !== 'data' || !portfolioResult?.portfolio_sim_id || paperReviewEntry?.creation_allowed !== true} onClick={handleCreateReview}>从已核验模拟创建复核</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || dataRoot !== 'data' || !reviewSourceEligible(paperReviewEntry,'candidate',source.candidate)} onClick={() => handleCreateReviewFromCandidate(source.candidate)}>从所选候选创建复核</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || dataRoot !== 'data' || selectedManifestIds.length !== 1 || !reviewSourceEligible(paperReviewEntry,'manifest',selectedManifestIds[0])} onClick={() => handleCreateReviewFromManifest(selectedManifestIds[0])}>从所选策略证据创建复核</button>
              <Field label="复核人"><input style={inputStyle} value={portfolioForm.reviewer} onChange={(e: any) => updatePortfolio('reviewer', e.target.value)} /></Field>
              <Field label="批准理由"><input style={inputStyle} value={portfolioForm.reviewReason} onChange={(e: any) => updatePortfolio('reviewReason', e.target.value)} /></Field></>}
            </div>
          </section>

          <div style={{display: 'grid', gap: 12}}>
            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>待处理复核</h3>
              <div style={{display: 'grid', gap: 8}}>
                {pendingReviews.map(review => (
                  <div key={review.paper_review_id} style={{display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, alignItems: 'center', borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 8}}>
                    <div>
                      <strong>{review.paper_review_id}</strong>
                      <div style={{color: '#94a3b8', fontSize: '0.78rem'}}>{review.strategy_manifest_id || review.portfolio_sim_id}</div>
                    </div>
                    <StatusPill value={review.status} />
                    {surface === 'review' ? <button style={dangerButtonStyle} disabled={actionBlocked || dataRoot !== 'data' || !portfolioForm.reviewer.trim() || !portfolioForm.reviewReason.trim()} onClick={() => handleApproveReview(String(review.paper_review_id))}>人工批准</button> : <Link to={workspaceLink('review',currentContext())}>前往复核</Link>}
                  </div>
                ))}
                {!pendingReviews.length ? <span style={{color: '#94a3b8'}}>暂无待人工复核项</span> : null}
              </div>
            </section>

            <ResultBlock title="组合 / 复核结果" value={portfolioResult} />

            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>策略 manifest</h3>
              <div style={{display: 'grid', gap: 8}}>
                {manifests.slice(0, 8).map(manifest => (
                  <div key={manifest.strategy_candidate_id} style={{display: 'grid', gridTemplateColumns: '1fr auto', gap: 8}}>
                    <span>{manifest.strategy_candidate_id}</span>
                    <StatusPill value={manifest.promotion_status} />
                  </div>
                ))}
                {!manifests.length ? <span style={{color: '#94a3b8'}}>暂无策略 manifest；先在候选证据里物化候选。</span> : null}
              </div>
            </section>

            <section style={sectionStyle}>
              <h3 style={{margin: '0 0 10px'}}>纸交易复核入口</h3>
              <div style={{display: 'grid', gap: 8, fontSize: '0.82rem'}}>
                <div><span style={{color: '#94a3b8'}}>状态</span><br />{String(systemOverview?.paper_review?.creation?.creation_allowed ? '就绪' : '阻塞')}</div>
                <div><span style={{color: '#94a3b8'}}>阻塞原因</span><br />{(paperReviewEntry?.why_blocked || systemOverview?.paper_review?.creation?.why_blocked || []).join(' · ') || '-'}</div>
                <div><span style={{color: '#94a3b8'}}>下一条命令</span><br />{paperReviewEntry?.next_command || systemOverview?.paper_review?.creation?.next_command || '-'}</div>
                <div><span style={{color: '#94a3b8'}}>合格 manifest</span><br />{paperReviewEntry?.preferred_manifest_id || systemOverview?.paper_review?.creation?.preferred_manifest_id || '-'}</div>
              </div>
              {!paperReviewEntry?.creation_allowed ? (
                <p style={{color: '#94a3b8', marginTop: 10}}>
                  没有合格 manifest 时，创建会被明确禁止。
                </p>
              ) : null}
            </section>
          </div>
        </div>
      )}

      {tab === 'records' && (
        <div style={{display: 'grid', gap: 18}}>
          <section style={sectionStyle}>
            <ExperimentList
              experiments={experiments}
              onCreateExperiment={openExperimentForm}
              onSelectExperiment={(exp) => { setSelectedExp(exp); setSelectedReportExp(exp.experiment_id); }}
            />
          </section>
          <section style={sectionStyle}>
            <CandidateTable candidates={candidatesForExp}  />
          </section>
          <section style={sectionStyle}>
            {loadedRoot === 'data' ? <ExperimentCompare /> : <p>跨实验对比接口尚未支持自定义数据目录，此处不混入默认目录的实验。</p>}
          </section>
          <section style={sectionStyle}>
            <ExperimentReport
              experiments={experiments}
              candidates={candidatesForExp}
              selectedExpId={selectedReportExp || selectedExp?.experiment_id}
            />
          </section>
        </div>
      )}
      </section>
    </WorkbenchFrame>
  );
}
