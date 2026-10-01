import {useEffect, useMemo, useRef, useState} from 'react';

import {LoadingSpinner} from '../../components/LoadingSpinner';
import LegacyResearchDashboard from './LegacyResearchDashboard';
import {ResearchNavigation, ResearchOverview, ResearchContext} from './PreviousResearchWorkbench';
import './ResearchDashboard.css';
import {apiGet} from '../../lib/api';
import {researchApi} from '../../lib/research-api';
import {taskApi} from '../../lib/task-api';
import type {SystemOverviewResponse, TaskResponse} from '../../lib/shared-types';
import ExperimentList from './ExperimentList';
import CandidateTable from './CandidateTable';
import ExperimentReport from './ExperimentReport';
import ExperimentCompare from './ExperimentCompare';
import TaskQueuePanel from '../../components/TaskQueuePanel';
import {
  WorkbenchFrame,
  WorkbenchHeader,
  WorkbenchNotice,
  WorkbenchPanel,
} from '../../components/workbench/Workbench';

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

export default function PreviousResearchDashboard() {
  const legacy = new URLSearchParams(window.location.search).get('layout') === 'legacy';
  return legacy ? <div className="research-legacy"><a className="research-return-new" href="/research">返回新版研究台</a><LegacyResearchDashboard /></div> : <ResearchDashboardV2 />;
}

function ResearchDashboardV2() {
  const [dataRoot, setDataRoot] = useState('data');
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [features, setFeatures] = useState<LooseRecord[]>([]);
  const [factors, setFactors] = useState<LooseRecord[]>([]);
  const [manifests, setManifests] = useState<LooseRecord[]>([]);
  const [pendingReviews, setPendingReviews] = useState<LooseRecord[]>([]);
  const [qlibStatus, setQlibStatus] = useState<LooseRecord | null>(null);
  const [qlibRuns, setQlibRuns] = useState<LooseRecord[]>([]);
  const [qlibRunDetail, setQlibRunDetail] = useState<LooseRecord | null>(null);
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
  const [readAt, setReadAt] = useState('');
  const [loadedRoot, setLoadedRoot] = useState('data');
  const rootMismatch = dataRoot !== loadedRoot;
  const actionBlocked = !!busy || rootMismatch;
  const readSequence = useRef(0);
  const [contextOpen, setContextOpen] = useState(false);
  const [taskQueue, setTaskQueue] = useState<TaskResponse[]>([]);
  const [tab, setTab] = useState('data');
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null);
  const [selectedReportExp, setSelectedReportExp] = useState('');
  const [selectedManifestIds, setSelectedManifestIds] = useState<string[]>([]);
  const experimentFormRef = useRef<HTMLElement | null>(null);

  const [autoForm, setAutoForm] = useState({
    strategyId: 'trend_momentum',
    symbols: 'AAPL,MSFT',
    family: 'frontend_research_cycle',
    params: '{"lookback_bars": 20}',
    paramGrid: '{"lookback_bars": [10, 20, 60]}',
    start: '2024-01-01',
    end: '2024-12-31',
    barSize: '1d',
    dataVersion: '',
    featureVersion: '',
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
    manifestIds: '',
    initialCash: '50000',
    reviewer: '',
    reviewReason: '前端人工复核',
  });
  const [qlibForm, setQlibForm] = useState({
    dataVersion: 'latest',
    universe: 'configs/universe/us_core_liquid.yaml',
    qlibConfig: 'configs/qlib/us_lgbm_alpha158_daily.yaml',
    startDate: '2020-01-01',
    endDate: '2025-12-31',
    runId: '',
    artifactsRoot: 'artifacts/qlib_runs',
    source: '',
    dryRun: true,
  });
  const [pypfoptForm, setPypfoptForm] = useState({
    scoreRunId: '',
    portfolioRunId: '',
    config: 'configs/portfolio/pypfopt_long_only_max_sharpe.yaml',
    artifactsRoot: 'artifacts/portfolio_runs',
    fallbackOptimizer: 'equal_weight_topk',
    strategyId: 'pypfopt_daily_only',
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
    const sequence = ++readSequence.current;
    const failures: string[] = [];
    async function read<T>(name: string, promise: Promise<T>, fallback: T): Promise<T> {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        return await Promise.race([promise, new Promise<T>((_, reject) => { timer = setTimeout(() => reject(new Error('读取超时')), 12000); })]);
      } catch { failures.push(name); return fallback; }
      finally { if (timer) clearTimeout(timer); }
    }
    const [exps, cands, snaps, factorDefs, manifestRows, reviews, registryPayload, globalRegistryPayload, qlibPayload, portfolioPayload, overviewPayload, paperReviewEntryPayload] = await Promise.all([
      read('实验列表', researchApi.listExperiments(root), []),
      read('候选列表', researchApi.listCandidates(root), []),
      read('特征快照', researchApi.listFeatures(), []),
      read('因子目录', researchApi.listFactors(root), []),
      read('策略证据', researchApi.listStrategyManifests(root), []),
      read('复核队列', researchApi.listPendingReviews(root), []),
      read('证据注册表', researchApi.getEvidenceRegistry(root), null),
      read('全局注册表', researchApi.getGlobalRegistry(), null),
      read('Qlib', researchApi.listQlibRuns(qlibForm.artifactsRoot), null),
      read('组合工具', researchApi.listPortfolioIntegrationRuns(pypfoptForm.artifactsRoot), null),
      read('系统总览', apiGet<SystemOverviewResponse>(`/api/system/overview?data_root=${encodeURIComponent(root)}`), null),
      read('人工复核入口', researchApi.getPaperReviewEntryState(root), null),
    ]);
    if (sequence !== readSequence.current) return;
    setReadFailures(failures);
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
    (async () => {
      try {
        await Promise.all([refresh(dataRoot), withTimeout(refreshTaskQueue(), undefined, 2500)]);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载研究数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const candidatesForExp = selectedExp
    ? candidates.filter(c => c.experiment_id === selectedExp.experiment_id)
    : candidates;

  const paperReadyCount = useMemo(() => {
    return candidates.filter(c => ['READY_FOR_PAPER_REVIEW', 'PAPER_ELIGIBLE'].includes(String(c.promotion_status))).length;
  }, [candidates]);

  const updateAuto = (key: string, value: string) => setAutoForm(current => ({...current, [key]: value}));
  const updateFactor = (key: string, value: string) => setFactorForm(current => ({...current, [key]: value}));
  const updateFeature = (key: string, value: string) => setFeatureForm(current => ({...current, [key]: value}));
  const updatePortfolio = (key: string, value: string) => setPortfolioForm(current => ({...current, [key]: value}));
  const updateQlib = (key: string, value: string | boolean) => setQlibForm(current => ({...current, [key]: value}));
  const updatePypfopt = (key: string, value: string) => setPypfoptForm(current => ({...current, [key]: value}));

  const selectedQlibRunId = qlibForm.runId.trim() || String(qlibRuns[0]?.run_id || '');
  const selectedPortfolioRunId = pypfoptForm.portfolioRunId.trim() || String(portfolioIntegrationRuns[0]?.portfolio_run_id || '');
  const minuteRemediationActions = asArray(systemOverview?.minute_data_quality?.remediation_summary?.actions);
  const selectedManifestRows = manifests.filter(row => selectedManifestIds.includes(String(row.strategy_candidate_id || '')));
  const latestPortfolioRun = asRecord(portfolioIntegrationRuns[0]);
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
    if (rootMismatch && !['refresh', 'integration-refresh'].includes(label)) {
      setError('数据目录已修改，请先重新读取状态；未提交任何操作。');
      return;
    }
    setBusy(label);
    setError('');
    setMessage('');
    try {
      await task();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
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
    while (isActiveTask(current)) {
      await sleep(800);
      current = await taskApi.getTask(taskId);
      upsertTask(current);
    }
    if (onComplete) {
      await onComplete(current);
    }
    return current;
  };

  const submitTrackedTask = async (
    label: string,
    submit: () => Promise<TaskResponse>,
    onComplete?: (task: TaskResponse) => Promise<void> | void,
  ) => {
    if (rootMismatch) {
      setError('数据目录已修改，请先重新读取状态；未提交任何任务。');
      return;
    }
    setBusy(label);
    setError('');
    setMessage('');
    try {
      const task = await submit();
      upsertTask(task);
      void trackTask(task.task_id, onComplete).catch((e) => {
        setError(e instanceof Error ? e.message : String(e));
      });
      return task;
    } finally {
      setBusy('');
    }
  };

  const toggleManifestSelection = (manifestId: string) => {
    setSelectedManifestIds(current => current.includes(manifestId) ? current.filter(id => id !== manifestId) : [...current, manifestId]);
  };

  const openExperimentForm = () => {
    setTab('cycle');
    setMessage('已打开研究闭环实验表单；尚未创建或提交实验。');
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const form = experimentFormRef.current;
        form?.scrollIntoView({block: 'start'});
        form?.querySelector<HTMLElement>('input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')?.focus();
      });
    });
  };

  const handleAutoCycle = () => runTask('auto-cycle', async () => {
    const payload = {
      strategy_id: autoForm.strategyId,
      symbols: splitCsv(autoForm.symbols),
      experiment_name: autoForm.family,
      params: parseJsonObject(autoForm.params),
      param_grid: parseJsonObject(autoForm.paramGrid),
      start_date: autoForm.start,
      end_date: autoForm.end,
      bar_size: autoForm.barSize,
      timeframe: autoForm.barSize,
      data_version: autoForm.dataVersion,
      feature_version: autoForm.featureVersion,
      data_root: dataRoot,
    };
    const result = await researchApi.runAutoCycle(payload);
    setAutoResult(result);
    setMessage(`研究闭环已返回：${result.status || '未知'}。请核对各阶段结果，返回成功不代表候选通过门禁。`);
    await refresh(dataRoot);
  });

  const handleFactorEvaluate = () => runTask('factor-evaluate', async () => {
    const result = await researchApi.evaluateFactor({
      factor_id: factorForm.factorId,
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_size: factorForm.barSize,
      timeframe: factorForm.barSize,
      forward_period: Number(factorForm.forwardPeriod || 5),
      data_root: dataRoot,
    });
    setFactorResult(result);
  });

  const handleFactorCompute = () => runTask('factor-compute', async () => {
    const result = await researchApi.computeFactor({
      factor_ids: [factorForm.factorId],
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_size: factorForm.barSize,
      timeframe: factorForm.barSize,
      data_root: dataRoot,
      limit: 25,
    });
    setFactorPreview(result);
  });

  const handleFactorMine = () => runTask('factor-mine', async () => {
    const result = await researchApi.mineFactors({
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_sizes: ['1d', '1m', '5m', '15m'],
      forward_period: Number(factorForm.forwardPeriod || 5),
      min_abs_rank_ic: 0.01,
      min_observations: 20,
      max_abs_correlation: 0.9,
      max_selected: 8,
      auto_generate_formulas: true,
      max_generated_factors: 24,
      data_root: dataRoot,
    });
    setFactorMiningResult(result);
  });

  const handleFactorMineAndRun = () => runTask('factor-mine-run', async () => {
    const result = await researchApi.mineAndRunFactors({
      symbols: splitCsv(factorForm.symbols),
      start: factorForm.start,
      end: factorForm.end,
      bar_sizes: ['1d', '1m', '5m', '15m'],
      forward_period: Number(factorForm.forwardPeriod || 5),
      min_abs_rank_ic: 0.01,
      min_observations: 20,
      max_abs_correlation: 0.9,
      max_selected: 8,
      max_runs: 4,
      auto_generate_formulas: true,
      max_generated_factors: 24,
      data_root: dataRoot,
    });
    setFactorMiningResult(result);
    setMessage(`因子挖掘研究闭环完成: ${result.candidate_ids?.length ?? 0} candidates`);
    await refresh(dataRoot);
  });

  const handleFeatureBuild = () => runTask('feature-build', async () => {
    const result = await researchApi.buildFeature({
      feature_id: featureForm.featureId,
      version: featureForm.version,
      symbols: splitCsv(featureForm.symbols),
      start: featureForm.start,
      end: featureForm.end,
      bar_size: featureForm.barSize,
      timeframe: featureForm.barSize,
      data_root: dataRoot,
    });
    setFeatureResult(result);
    await refresh(dataRoot);
  });

  const handleRegistryRebuild = () => runTask('registry', async () => {
    const result = await researchApi.rebuildEvidenceRegistry(dataRoot);
    setRegistry(result);
    setMessage('证据 registry 已重建');
    await refresh(dataRoot);
  });

  const handleCandidateAction = (candidateId: string, action: string) => runTask(`${candidateId}-${action}`, async () => {
    let result: LooseRecord;
    if (action === 'materialize') result = await researchApi.materializeEvidence(candidateId, dataRoot);
    else if (action === 'gate') result = await researchApi.checkPromotionGate(candidateId, dataRoot);
    else if (action === 'pack') result = await researchApi.saveEvidencePack(candidateId, dataRoot);
    else result = await researchApi.runRobustness(candidateId, dataRoot, 200);
    setCandidateActionResult({candidate_id: candidateId, action, result});
    await refresh(dataRoot);
  });

  const handlePortfolioSim = () => runTask('portfolio-sim', async () => {
    const manifestIds = portfolioForm.manifestIds
      ? portfolioForm.manifestIds.split(/[,\n]/).map(id => id.trim()).filter(Boolean)
      : (selectedManifestIds.length ? selectedManifestIds : manifests.map(row => String(row.strategy_candidate_id)).filter(Boolean));
    const result = await researchApi.runPortfolioSim(manifestIds, {
      initial_cash: Number(portfolioForm.initialCash || 50000),
    });
    setPortfolioResult(result);
  });

  const handleCreateReview = () => runTask('paper-review-create', async () => {
    const simId = String(portfolioResult?.portfolio_sim_id || '');
    if (!simId) throw new Error('先运行 portfolio simulation');
    const result = await researchApi.createPaperReview(simId, dataRoot);
    setPortfolioResult({...(portfolioResult || {}), paper_review: result});
    await refresh(dataRoot);
  });

  const handleCreateReviewFromManifest = (manifestId: string) => runTask(`manifest-review-${manifestId}`, async () => {
    const result = await researchApi.createPaperReviewFromManifest(manifestId, dataRoot);
    setPortfolioResult({strategy_manifest_id: manifestId, paper_review: result});
    setMessage(`已把 ${manifestId} 放入 paper review queue。`);
    await refresh(dataRoot);
  });

  const handleCreateReviewFromCandidate = (candidateId: string) => runTask(`candidate-review-${candidateId}`, async () => {
    const result = await researchApi.createPaperReviewFromCandidate(candidateId, dataRoot);
    setPortfolioResult({candidate_id: candidateId, paper_review: result});
    setMessage(`已从 candidate ${candidateId} 创建 paper review evidence。`);
    await refresh(dataRoot);
  });

  const handleApproveReview = (reviewId: string) => runTask(`approve-${reviewId}`, async () => {
    if (!portfolioForm.reviewer.trim()) throw new Error('填写 reviewer 后才能人工批准');
    const result = await researchApi.approvePaperReview(reviewId, portfolioForm.reviewer, portfolioForm.reviewReason);
    setPortfolioResult({approved_review: result});
    await refresh(dataRoot);
  });

  const refreshIntegrationPanels = async () => {
    await refresh(dataRoot);
  };

  const qlibPayload = () => ({
    data_root: dataRoot,
    data_version: qlibForm.dataVersion,
    universe: qlibForm.universe,
    config: qlibForm.qlibConfig,
    start_date: qlibForm.startDate,
    end_date: qlibForm.endDate,
    run_id: qlibForm.runId.trim() || undefined,
    artifacts_root: qlibForm.artifactsRoot,
    source: qlibForm.source.trim() || undefined,
    dry_run: qlibForm.dryRun,
    asset_class: 'equity',
    bar_size: '1d',
  });

  const pypfoptPayload = () => ({
    score_run_id: pypfoptForm.scoreRunId.trim() || selectedQlibRunId,
    portfolio_run_id: pypfoptForm.portfolioRunId.trim() || undefined,
    config: pypfoptForm.config,
    fallback_optimizer: pypfoptForm.fallbackOptimizer || undefined,
    strategy_id: pypfoptForm.strategyId.trim() || undefined,
  });

  const handleQlibAction = (action: string) => {
    if (action === 'build' || action === 'workflow') {
      void submitTrackedTask(`qlib-${action}`, async () => (
        action === 'build'
          ? taskApi.submitQlibBuildDatasetTask(qlibPayload())
          : taskApi.submitQlibWorkflowTask(qlibPayload())
      ), async (task) => {
        const result = (task.result ?? {}) as LooseRecord;
        setQlibActionResult({action, task_id: task.task_id, ...result});
        await refreshIntegrationPanels();
        const runId = String(result.run_id || selectedQlibRunId || '');
        if (runId) {
          setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot).catch(() => null));
          setPypfoptForm(current => ({...current, scoreRunId: current.scoreRunId || runId}));
        }
        setMessage(`Qlib task ${task.status.toUpperCase()}: ${task.label}`);
      });
      return;
    }

    void runTask(`qlib-${action}`, async () => {
      let result: LooseRecord;
      if (action === 'scores') {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.importQlibPredScore({...qlibPayload(), run_id: selectedQlibRunId});
      } else if (action === 'metrics') {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.importQlibRecorderMetrics({...qlibPayload(), run_id: selectedQlibRunId});
      } else {
        if (!selectedQlibRunId) throw new Error('先填写或选择 run_id');
        result = await researchApi.compileQlibStrategyManifest({...qlibPayload(), run_id: selectedQlibRunId});
      }
      setQlibActionResult({action, ...result});
      await refreshIntegrationPanels();
      const runId = String(result.run_id || selectedQlibRunId || '');
      if (runId) {
        setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot).catch(() => null));
        setPypfoptForm(current => ({...current, scoreRunId: current.scoreRunId || runId}));
      }
    });
  };

  const loadQlibRunDetail = (runId: string) => runTask(`qlib-detail-${runId}`, async () => {
    setQlibRunDetail(await researchApi.getQlibRun(runId, qlibForm.artifactsRoot));
    setQlibForm(current => ({...current, runId}));
    setPypfoptForm(current => ({...current, scoreRunId: current.scoreRunId || runId}));
  });

  const handlePypfoptAction = (action: string) => {
    if (action === 'optimize') {
      void submitTrackedTask('pypfopt-optimize', async () => taskApi.submitPortfolioOptimizeWeightsTask(pypfoptPayload()), async (task) => {
        const result = (task.result ?? {}) as LooseRecord;
        setPypfoptActionResult({action, task_id: task.task_id, ...result});
        await refreshIntegrationPanels();
        const portfolioRunId = String(result.portfolio_run_id || pypfoptPayload().portfolio_run_id || selectedPortfolioRunId || portfolioIntegrationRuns[0]?.portfolio_run_id || '');
        if (portfolioRunId) {
          setPypfoptForm(current => ({...current, portfolioRunId: current.portfolioRunId || portfolioRunId}));
          setPortfolioIntegrationDetail(await researchApi.getPortfolioIntegrationRun(portfolioRunId, pypfoptForm.artifactsRoot).catch(() => null));
        }
        setMessage(`PyPortfolioOpt task ${task.status.toUpperCase()}: ${task.label}`);
      });
      return;
    }

    void runTask(`pypfopt-${action}`, async () => {
      const payload = pypfoptPayload();
      if (action !== 'import' && !payload.score_run_id) throw new Error('先填写 score_run_id 或选择 Qlib run');
      if (action === 'import' && !selectedPortfolioRunId) throw new Error('先填写或选择 portfolio_run_id');
      let result: LooseRecord;
      if (action === 'expected') {
        result = await researchApi.buildPortfolioExpectedReturns(payload);
      } else if (action === 'covariance') {
        result = await researchApi.buildPortfolioCovariance(payload);
      } else {
        result = await researchApi.importPortfolioTargetWeights({...payload, portfolio_run_id: selectedPortfolioRunId});
      }
      setPypfoptActionResult({action, ...result});
      await refreshIntegrationPanels();
      const portfolioRunId = String(result.portfolio_run_id || payload.portfolio_run_id || selectedPortfolioRunId || portfolioIntegrationRuns[0]?.portfolio_run_id || '');
      if (portfolioRunId) {
        setPypfoptForm(current => ({...current, portfolioRunId: current.portfolioRunId || portfolioRunId}));
        setPortfolioIntegrationDetail(await researchApi.getPortfolioIntegrationRun(portfolioRunId, pypfoptForm.artifactsRoot).catch(() => null));
      }
    });
  };

  const loadPortfolioRunDetail = (portfolioRunId: string) => runTask(`portfolio-detail-${portfolioRunId}`, async () => {
    setPortfolioIntegrationDetail(await researchApi.getPortfolioIntegrationRun(portfolioRunId, pypfoptForm.artifactsRoot));
    setPypfoptForm(current => ({...current, portfolioRunId}));
  });

  const handleResearchExecutionPipeline = () => runTask('research-execution-pipeline', async () => {
    const qlibRunId = selectedQlibRunId || pypfoptForm.scoreRunId.trim();
    const portfolioRunId = selectedPortfolioRunId || pypfoptForm.portfolioRunId.trim();
    if (!qlibRunId) throw new Error('先选择 Qlib score run');
    if (!portfolioRunId) throw new Error('先生成或选择 portfolio run');
    const result = await researchApi.runResearchExecutionPipeline({
      qlib_run_id: qlibRunId,
      qlib_config: qlibForm.qlibConfig,
      portfolio_config: pypfoptForm.config,
      portfolio_run_id: portfolioRunId,
      strategy_id: pypfoptForm.strategyId,
      qlib_runs_root: qlibForm.artifactsRoot,
      portfolio_runs_root: pypfoptForm.artifactsRoot,
      pipeline_runs_root: 'artifacts/research_execution_runs',
      initial_cash: Number(portfolioForm.initialCash || 50000),
      risk_max_order_notional_pct: 0.25,
      walk_forward_train_bars: 252,
      walk_forward_test_bars: 63,
      walk_forward_step_bars: 63,
    });
    setExecutionPipelineResult(result);
    setMessage(`研究执行流水线完成: ${result.status || 'unknown'}`);
    await refresh(dataRoot);
  });

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

  if (loading) {
    return (
      <WorkbenchFrame className="research-workbench">
        <WorkbenchHeader
          code="RQ"
          eyebrow="Research / Evidence"
          title="研究台"
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
    <WorkbenchFrame className="research-workbench research-v2" testId="research-content">
      <div className="research-page-heading">
        <div><span className="research-eyebrow">RESEARCH LAB</span><h2>研究台 <span>从假设到证据</span></h2></div>
        <div className="research-heading-actions"><span className="research-lock">仅研究 · 交易锁定</span><a href="/research?layout=legacy">切回原版</a>
          <button disabled={!!busy} onClick={() => runTask('refresh', async () => refresh(dataRoot))}>刷新状态</button></div>
      </div>
      <ResearchOverview loading={loading} readFailures={readFailures} readAt={readAt}
        experiments={experiments} candidates={candidates} manifests={manifests}
        qlib={qlibStatus} portfolio={portfolioIntegrationStatus} overview={systemOverview}
        root={loadedRoot} onNavigate={setTab} busy={busy} />
      <ResearchContext open={contextOpen} onToggle={() => setContextOpen(value => !value)}
        value={autoForm} onChange={updateContext} errors={contextErrors} disabled={!!busy} />
      {error ? <div className="research-feedback error" role="alert">{error}</div> : null}
      {message ? <div className="research-feedback" role="status">{message}</div> : null}
      {busy ? <div className="research-feedback" role="status">任务进行中：{busy}。完成后请查看结果与各环节检查。</div> : null}
      <ResearchNavigation tab={tab} onChange={setTab} />
      <section id="research-active-panel" role="tabpanel" aria-labelledby={`research-tab-${tab}`} className="research-active-panel">
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
          <button className="research-route" onClick={() => setTab('qlib')}><strong>Qlib 模型研究 →</strong><span>准备日频数据、训练模型、导入评分和构建组合</span></button>
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
                <span>注册表：{systemOverview?.registry?.integrity || registry?.registry_integrity_status || '-'}</span>
                <span>manifest：{systemOverview?.paper_review?.manifest_path || '-'}</span>
                <span>下一条命令：{paperReviewEntry?.next_command || systemOverview?.paper_review?.creation?.next_command || '-'}</span>
              </div>
            </section>
          </div>

          <section style={sectionStyle}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
              <h3 style={{margin: 0}}>策略 manifest 证据</h3>
              <div style={{display: 'flex', gap: 8}}>
                <button style={buttonStyle} disabled={actionBlocked || !selectedManifestIds.length} onClick={handlePortfolioSim}>运行选中 manifest 组合回测入口</button>
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
                      <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleCreateReviewFromManifest(row.id)}>创建复核证据</button>
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
                    <button style={dangerButtonStyle} disabled={actionBlocked} onClick={() => handleApproveReview(String(review.paper_review_id))}>人工批准</button>
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
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12}}>
                <button style={buttonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('optimize')}>优化目标权重</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('import')}>生成目标持仓</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !targetWeightReady} onClick={handleResearchExecutionPipeline}>运行风险回测流水线</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !selectedManifestRows.length} onClick={handlePortfolioSim}>进入组合回测</button>
              </div>
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
                <div><span style={{color: '#94a3b8'}}>注册表</span><br />{fmt(registry?.state || registry?.status || registry?.schema_version)}</div>
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
                <span>状态</span><span>{fmt(registry?.state || registry?.status)}</span>
                <span>路径</span><span>{fmt(registry?.registry_path || registry?.path)}</span>
              </div>
            </section>
            <ResultBlock title="候选操作结果" value={candidateActionResult} />
          </div>
        </div>
      )}

      {tab === 'qlib' && (
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
              <strong>仅日频研究</strong>
            </div>
          </section>

          <TaskQueuePanel title="Qlib / PyPortfolioOpt 任务" tasks={integrationTasks} onRefresh={refreshTaskQueue} emptyText="暂无 Qlib 或 PyPortfolioOpt 后台任务" />

          <div style={{display: 'grid', gridTemplateColumns: 'minmax(380px, 0.95fr) minmax(520px, 1.05fr)', gap: 16}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>Qlib 日频基线</h3>
              <p className="research-footnote">实际数据目录：{dataRoot}（共享设置）；已读取目录：{loadedRoot}。</p>
              {dataRoot !== loadedRoot && <p className="warning" role="alert">数据目录尚未重新读取。请返回数据准备并读取此目录后再运行。</p>}
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
                <Field label="数据版本"><input style={inputStyle} value={qlibForm.dataVersion} onChange={(e: any) => updateQlib('dataVersion', e.target.value)} /></Field>
                <Field label="运行 ID"><input style={inputStyle} value={qlibForm.runId} onChange={(e: any) => updateQlib('runId', e.target.value)} placeholder={String(qlibRuns[0]?.run_id || '自动/最新')} /></Field>
                <Field label="开始日期"><input style={inputStyle} value={qlibForm.startDate} onChange={(e: any) => updateQlib('startDate', e.target.value)} /></Field>
                <Field label="结束日期"><input style={inputStyle} value={qlibForm.endDate} onChange={(e: any) => updateQlib('endDate', e.target.value)} /></Field>
                <Field label="股票池"><input style={inputStyle} value={qlibForm.universe} onChange={(e: any) => updateQlib('universe', e.target.value)} /></Field>
                <Field label="工作流配置"><input style={inputStyle} value={qlibForm.qlibConfig} onChange={(e: any) => updateQlib('qlibConfig', e.target.value)} /></Field>
                <Field label="产物根目录"><input style={inputStyle} value={qlibForm.artifactsRoot} onChange={(e: any) => updateQlib('artifactsRoot', e.target.value)} /></Field>
                <Field label="数据源覆盖"><input style={inputStyle} value={qlibForm.source} onChange={(e: any) => updateQlib('source', e.target.value)} placeholder="默认使用股票池配置" /></Field>
              </div>
              <label style={{display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, color: '#cbd5e1', fontSize: '0.82rem'}}>
                <input type="checkbox" checked={qlibForm.dryRun} onChange={(e: any) => updateQlib('dryRun', !!e.target.checked)} />
                仅检查配置（dry-run，不训练模型、不算运行成功）
              </label>
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 14}}>
                <button style={buttonStyle} disabled={actionBlocked} onClick={() => handleQlibAction('build')}>构建数据集</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleQlibAction('workflow')}>运行工作流</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleQlibAction('scores')}>导入评分</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleQlibAction('metrics')}>导入指标</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handleQlibAction('manifest')}>编译候选</button>
              </div>
              <p style={{color: '#94a3b8', fontSize: '0.78rem', lineHeight: 1.5}}>
                当前只允许 1d、long-only、research-only。Qlib 回测结果不会直接变成纸交易或实盘结论。
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

          <div style={{display: 'grid', gridTemplateColumns: 'minmax(380px, 0.95fr) minmax(520px, 1.05fr)', gap: 16}}>
            <section style={sectionStyle}>
              <h3 style={{marginTop: 0}}>PyPortfolioOpt 目标权重</h3>
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
                <Field label="评分运行 ID"><input style={inputStyle} value={pypfoptForm.scoreRunId} onChange={(e: any) => updatePypfopt('scoreRunId', e.target.value)} placeholder={selectedQlibRunId || 'Qlib 运行 ID'} /></Field>
                <Field label="组合运行 ID"><input style={inputStyle} value={pypfoptForm.portfolioRunId} onChange={(e: any) => updatePypfopt('portfolioRunId', e.target.value)} placeholder={String(portfolioIntegrationRuns[0]?.portfolio_run_id || '自动')} /></Field>
                <Field label="优化器配置">
                  <select style={inputStyle} value={pypfoptForm.config} onChange={(e: any) => updatePypfopt('config', e.target.value)}>
                    <option value="configs/portfolio/pypfopt_long_only_max_sharpe.yaml">max_sharpe</option>
                    <option value="configs/portfolio/pypfopt_long_only_min_volatility.yaml">min_volatility</option>
                    <option value="configs/portfolio/pypfopt_hrp.yaml">hrp</option>
                  </select>
                </Field>
                <Field label="降级优化器"><select style={inputStyle} value={pypfoptForm.fallbackOptimizer} onChange={(e: any) => updatePypfopt('fallbackOptimizer', e.target.value)}><option value="equal_weight_topk">equal_weight_topk</option><option value="">无</option></select></Field>
                <Field label="产物根目录"><input style={inputStyle} value={pypfoptForm.artifactsRoot} onChange={(e: any) => updatePypfopt('artifactsRoot', e.target.value)} /></Field>
                <Field label="策略 ID"><input style={inputStyle} value={pypfoptForm.strategyId} onChange={(e: any) => updatePypfopt('strategyId', e.target.value)} /></Field>
              </div>
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 14}}>
                <button style={buttonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('expected')}>生成预期收益</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('covariance')}>生成协方差</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('optimize')}>优化目标权重</button>
                <button style={ghostButtonStyle} disabled={actionBlocked} onClick={() => handlePypfoptAction('import')}>导入目标持仓</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !selectedPortfolioRunId} onClick={handleResearchExecutionPipeline}>运行风险回测流水线</button>
              </div>
              <p style={{color: '#94a3b8', fontSize: '0.78rem', lineHeight: 1.5}}>
                这里只产目标权重 / TargetPosition 兼容产物，不生成 OrderIntent，不提交 broker。
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
                      onClick={() => loadPortfolioRunDetail(String(run.portfolio_run_id))}
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

      {tab === 'review' && (
        <div style={{display: 'grid', gridTemplateColumns: 'minmax(360px, 0.8fr) minmax(480px, 1.2fr)', gap: 16}}>
          <section style={sectionStyle}>
            <h3 style={{marginTop: 0}}>组合模拟 → 纸交易复核</h3>
            <div style={{display: 'grid', gap: 12}}>
              <Field label="manifest_ids">
                <textarea
                  style={{...inputStyle, minHeight: 80}}
                  placeholder={manifests.map(m => m.strategy_candidate_id).join(',') || 'sman_xxx,sman_yyy'}
                  value={portfolioForm.manifestIds}
                  onChange={(e: any) => updatePortfolio('manifestIds', e.target.value)}
                />
              </Field>
              <Field label="初始资金"><input style={inputStyle} value={portfolioForm.initialCash} onChange={(e: any) => updatePortfolio('initialCash', e.target.value)} /></Field>
              <div style={{display: 'flex', gap: 10}}>
                <button style={buttonStyle} disabled={actionBlocked} onClick={handlePortfolioSim}>运行组合模拟</button>
                <button style={ghostButtonStyle} disabled={actionBlocked || !portfolioResult?.portfolio_sim_id} onClick={handleCreateReview}>创建人工复核</button>
              </div>
              <Field label="复核人"><input style={inputStyle} value={portfolioForm.reviewer} onChange={(e: any) => updatePortfolio('reviewer', e.target.value)} /></Field>
              <Field label="批准理由"><input style={inputStyle} value={portfolioForm.reviewReason} onChange={(e: any) => updatePortfolio('reviewReason', e.target.value)} /></Field>
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
                    <button style={dangerButtonStyle} disabled={!!busy} onClick={() => handleApproveReview(String(review.paper_review_id))}>人工批准</button>
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
              <div style={{display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap'}}>
                <button
                  style={buttonStyle}
                  disabled={actionBlocked || !paperReviewEntry?.preferred_manifest_id}
                  onClick={() => handleCreateReviewFromManifest(String(paperReviewEntry?.preferred_manifest_id || systemOverview?.paper_review?.creation?.preferred_manifest_id || ''))}
                >
                  从 manifest 创建
                </button>
                <button
                  style={ghostButtonStyle}
                  disabled={actionBlocked || !paperReviewEntry?.preferred_candidate_id}
                  onClick={() => handleCreateReviewFromCandidate(String(paperReviewEntry?.preferred_candidate_id || systemOverview?.paper_review?.creation?.preferred_candidate_id || ''))}
                >
                  从候选创建
                </button>
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
            <CandidateTable candidates={candidatesForExp} onCreatePaperReview={handleCreateReviewFromCandidate} />
          </section>
          <section style={sectionStyle}>
            <ExperimentCompare />
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
