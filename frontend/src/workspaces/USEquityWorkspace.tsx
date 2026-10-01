import {useEffect, useMemo, useState} from 'react';

import LineChart from '../components/LineChart';
import {ModuleStateCard, type ModuleStateCardProps} from '../components/ModuleStateCard';
import StatusBadge from '../components/StatusBadge';
import {LoadingSpinner} from '../components/LoadingSpinner';
import {
  WorkbenchFrame,
  WorkbenchHeader,
  WorkbenchTabs,
  type WorkbenchTone,
} from '../components/workbench/Workbench';
import {apiGet, apiPost} from '../lib/api';
import type {
  EventDrivenCostStressResponse,
  MvpStep,
  PromotionGateResponse,
  SystemOverviewResponse,
  ValueEvent,
} from '../lib/shared-types';
import type {StrategyInfo} from '../lib/view-model';
import {buildDateBoundary, formatPrice, mvpStepClass} from '../lib/utils';
import USEquityDomainReadModelView from './us-equity/USEquityDomainReadModel';

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
};

type USEquityFormState = {
  symbol: string;
  barSize: '1m' | '2m' | '5m' | '15m' | '30m' | '1h' | '1d';
  startDate: string;
  endDate: string;
  dataRoot: string;
  strategyId: string;
  ledgerDir: string;
};

type USEquitySyncResponse = {
  run_id: string;
  status: string;
  symbol: string;
  bar_size: string;
  rows_received: number;
  rows_cleaned: number;
  data_version?: string;
  data_manifest_path?: string;
};

type USFeatureBuildResponse = {
  run_id: string;
  status: string;
  rows_written: number;
  version: string;
};

type USEventBacktestResponse = {
  run_id: string;
  status: string;
  summary: Record<string, number>;
  order_count: number;
  fill_count: number;
  snapshot_count: number;
  event_count: number;
};

type USReconciliationResponse = {
  status: string;
  break_count: number;
  breaks: Array<{symbol: string; local_quantity: number; broker_quantity: number}>;
  halt_new_orders?: boolean;
  alert_sent?: boolean;
  cash_diff?: number;
  position_diffs?: Record<string, unknown>;
  order_diffs?: Record<string, unknown>;
  fill_diffs?: Record<string, unknown>;
  report_path?: string;
};

type USQualityReportResponse = {
  symbol: string;
  data_version: string;
  total_issues: number;
  has_issues: boolean;
  reports: Array<{
    report_type: string;
    issues_found: number;
    details: Array<Record<string, unknown>>;
  }>;
};

type USUnifiedBacktestResponse = {
  run_id: string;
  status: string;
  summary: Record<string, number>;
  equity_consistent: boolean;
  equity_consistency_msg: string;
  order_count: number;
  fill_count: number;
  snapshot_count: number;
  event_count: number;
  ledger_final_equity: number;
  ledger_total_fees: number;
  equity_curve: Array<{time: number; value: number}>;
  drawdown_curve: Array<{time: number; value: number}>;
};

type USPaperStatusResponse = {
  equity: number;
  cash: number;
  buying_power: number;
  positions: number;
  kill_switch_triggered: boolean;
  kill_switch_reason: string | null;
  days_traded: number;
  healthy: boolean;
  last_reconciliation_passed: boolean | null;
};

type USPaperDayResultResponse = {
  date: string;
  starting_equity: number;
  ending_equity: number;
  daily_pnl: number;
  daily_return_pct: number;
  orders_submitted: number;
  orders_filled: number;
  orders_rejected: number;
  orders_cancelled: number;
  kill_switch_triggered: boolean;
  reconciliation_passed: boolean;
  reconciliation_diff: Record<string, unknown>;
  errors: string[];
};

type PaperBacktestResponse = {
  status: string;
  days_processed: number;
  total_pnl: number;
  final_equity: number;
  healthy: boolean;
  kill_switch_triggered: boolean;
  daily_results: USPaperDayResultResponse[];
};

type GateTone = 'neutral' | 'good' | 'bad';

type GateCard = {
  id: string;
  title: string;
  status: string;
  detail: string;
  tone: GateTone;
};

type EvidenceEntry = {
  label: string;
  value: string;
  muted?: boolean;
};

type LooseRecord = Record<string, unknown>;

type PortfolioSectionRow = {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: GateTone;
};

type PortfolioBudgetItem = {
  key: string;
  label: string;
  value: string;
  detail: string;
};

type PortfolioGateSummary = {
  key: string;
  label: string;
  status: string;
  detail: string;
  tone: GateTone;
};

type OpsStageKey = 'overview' | 'research' | 'portfolio' | 'paper' | 'evidence';

type OpsStageCard = {
  key: OpsStageKey;
  label: string;
  short: string;
  status: string;
  detail: string;
  tone: GateTone;
};

function cnStatus(value: string): string {
  const direct: Record<string, string> = {
    missing: '缺失',
    waiting: '等待中',
    frozen: '冻结',
    locked: '锁定',
    confirmed: '已确认',
    pending: '待处理',
    research: '研究',
    none: '无',
    'live runtime frozen': '实盘运行已冻结',
  };
  return direct[value.toLowerCase()] ?? value;
}

const defaultUSForm: USEquityFormState = {
  symbol: 'AAPL',
  barSize: '1d',
  startDate: '2024-01-01',
  endDate: '2024-06-01',
  dataRoot: 'data',
  strategyId: 'trend_momentum',
  ledgerDir: 'data/ledger/paper',
};

export type USEquityWorkspaceProps = {
  strategies: StrategyInfo[];
  health: HealthState | null;
};

function metricValue(value?: number, digits = 2, suffix = ''): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `${value.toFixed(digits)}${suffix}`;
}

function toneForPaper(status: USPaperStatusResponse | null): GateTone {
  if (!status) return 'neutral';
  if (!status.healthy || status.kill_switch_triggered || status.last_reconciliation_passed === false) return 'bad';
  if (status.days_traded > 0 && status.last_reconciliation_passed) return 'good';
  return 'neutral';
}

function getPaperStatusLabel(status: USPaperStatusResponse | null): string {
  if (!status) return '待运行';
  if (status.kill_switch_triggered) return '已冻结';
  if (!status.healthy) return '需处理';
  if (status.days_traded === 0) return '待观察';
  return '可复核';
}

function toneFromOverviewStatus(status?: string | boolean | null): GateTone {
  if (status === true || status === 'PASS' || status === 'present' || status === 'PASS/STABLE' || status === 'reviewable') return 'good';
  if (status === false || status === 'blocked' || status === 'frozen') return 'bad';
  return 'neutral';
}

function asRecord(value: unknown): LooseRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as LooseRecord : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function firstPresent<T>(...values: Array<T | null | undefined>): T | null {
  return values.find(value => value !== null && value !== undefined) ?? null;
}

function readRecord(source: LooseRecord | null, ...keys: string[]): LooseRecord | null {
  for (const key of keys) {
    const value = source?.[key];
    const record = asRecord(value);
    if (record) return record;
  }
  return null;
}

function readArray(source: LooseRecord | null, ...keys: string[]): unknown[] {
  for (const key of keys) {
    const value = source?.[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function readString(source: LooseRecord | null, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}

function readBoolean(source: LooseRecord | null, ...keys: string[]): boolean | null {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === 'boolean') return value;
  }
  return null;
}

function readNumber(source: LooseRecord | null, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function formatPercentValue(value: number | null, digits = 1): string {
  if (value === null || Number.isNaN(value)) return '-';
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(digits)}%`;
}

function formatSignedPrice(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '-';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}$${formatPrice(value)}`;
}

export default function USEquityWorkspace({strategies, health}: USEquityWorkspaceProps) {
  const [usForm, setUSForm] = useState<USEquityFormState>(() => ({
    ...defaultUSForm,
    strategyId: strategies[0]?.id ?? defaultUSForm.strategyId,
  }));
  const [usLoading, setUSLoading] = useState(false);
  const [usMessage, setUSMessage] = useState('');
  const [usSync, setUSSync] = useState<USEquitySyncResponse | null>(null);
  const [usFeature, setUSFeature] = useState<USFeatureBuildResponse | null>(null);
  const [usBacktest, setUSBacktest] = useState<USEventBacktestResponse | null>(null);
  const [usReconcile, setUSReconcile] = useState<USReconciliationResponse | null>(null);
  const [usQualityReport, setUSQualityReport] = useState<USQualityReportResponse | null>(null);
  const [usUnifiedBacktest, setUSUnifiedBacktest] = useState<USUnifiedBacktestResponse | null>(null);
  const [usPaperStatus, setUSPaperStatus] = useState<USPaperStatusResponse | null>(null);
  const [usPaperDailyResults, setUSPaperDailyResults] = useState<USPaperDayResultResponse[]>([]);
  const [paperBacktest, setPaperBacktest] = useState<PaperBacktestResponse | null>(null);
  const [edCostStress, setEDCostStress] = useState<EventDrivenCostStressResponse | null>(null);
  const [promotionGateResult, setPromotionGateResult] = useState<PromotionGateResponse | null>(null);
  const [systemOverview, setSystemOverview] = useState<SystemOverviewResponse | null>(null);
  const [activeStage, setActiveStage] = useState<OpsStageKey>('overview');

  useEffect(() => {
    if (strategies.length > 0 && !strategies.find(strategy => strategy.id === usForm.strategyId)) {
      setUSForm(current => ({...current, strategyId: strategies[0].id}));
    }
  }, [strategies, usForm.strategyId]);

  const handleUSPaperStatus = async () => {
    try {
      const result = await apiGet<USPaperStatusResponse>('/api/us/paper/status');
      setUSPaperStatus(result);
    } catch {
      // read-only dashboard fetch
    }
  };

  const handleUSPaperDailyResults = async () => {
    try {
      const results = await apiGet<USPaperDayResultResponse[]>('/api/us/paper/daily-results');
      setUSPaperDailyResults(results);
    } catch {
      // read-only dashboard fetch
    }
  };

  const loadSystemOverview = async (dataRoot = usForm.dataRoot) => {
    try {
      const result = await apiGet<SystemOverviewResponse>(`/api/system/overview?data_root=${encodeURIComponent(dataRoot)}`);
      setSystemOverview(result);
    } catch {
      // overview is additive; page still works with direct endpoints
    }
  };

  useEffect(() => {
    void loadSystemOverview();
    void handleUSPaperStatus();
    void handleUSPaperDailyResults();
    const interval = setInterval(() => {
      void loadSystemOverview();
      void handleUSPaperStatus();
      void handleUSPaperDailyResults();
    }, 20000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    void loadSystemOverview(usForm.dataRoot);
  }, [usForm.dataRoot]);

  const selectedStrategy = useMemo(
    () => strategies.find(strategy => strategy.id === usForm.strategyId) ?? null,
    [strategies, usForm.strategyId],
  );

  const recentPaperRuns = usPaperDailyResults.slice(-6).reverse();
  const paperPnL = usPaperDailyResults.reduce((sum, day) => sum + day.daily_pnl, 0);
  const paperOrdersSubmitted = usPaperDailyResults.reduce((sum, day) => sum + day.orders_submitted, 0);
  const paperOrdersFilled = usPaperDailyResults.reduce((sum, day) => sum + day.orders_filled, 0);
  const paperReconPasses = usPaperDailyResults.filter(day => day.reconciliation_passed).length;

  const handleUSDataSync = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USEquitySyncResponse>('/api/us/data/sync', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
      });
      setUSSync(result);
      setUSMessage(`数据同步完成，清洗 ${result.rows_cleaned} 行，版本 ${result.data_version || '未生成'}。`);
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '同步失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSBuildFeatures = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USFeatureBuildResponse>('/api/us/features/build', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
        version: 'v1',
        universe: 'default',
        auto_sync: true,
      });
      setUSFeature(result);
      setUSMessage(`特征写入 ${result.rows_written} 行，版本 ${result.version}。`);
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '构建失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USEventBacktestResponse>('/api/us/backtests/event', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
        auto_sync: true,
      });
      setUSBacktest(result);
      setUSMessage(`事件回测完成，${result.fill_count} 笔成交。`);
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '回测失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSReconcile = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USReconciliationResponse>('/api/us/reconcile', {
        ledger_dir: usForm.ledgerDir,
        tolerance: 0.000001,
      });
      setUSReconcile(result);
      setUSMessage(result.status === 'clean' ? '账本与券商侧对账一致。' : `发现 ${result.break_count} 个对账差异。`);
      void loadSystemOverview();
      void handleUSPaperStatus();
      void handleUSPaperDailyResults();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '对账失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSUnifiedBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USUnifiedBacktestResponse>('/api/us/backtests/unified', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
        auto_sync: true,
      });
      setUSUnifiedBacktest(result);
      setUSMessage(result.equity_consistent ? '统一回测完成，权益验证通过。' : '统一回测完成，权益验证失败。');
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '统一回测失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperRunDay = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USPaperDayResultResponse>('/api/us/paper/run-day', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        target_date: usForm.startDate,
        data_root: usForm.dataRoot,
        capital: 100000,
      });
      setUSMessage(`Paper 日运行完成，${result.date} PnL ${formatPrice(result.daily_pnl)}。`);
      void loadSystemOverview();
      void handleUSPaperStatus();
      void handleUSPaperDailyResults();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : 'paper 运行失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<PaperBacktestResponse>('/api/us/paper/backtest', {
        vendor: 'yfinance',
        asset_class: 'equity',
        symbol: usForm.symbol,
        bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
        capital: 100000,
        auto_sync: true,
      });
      setPaperBacktest(result);
      setUSMessage(`Paper 回放完成，处理 ${result.days_processed} 天。`);
      void loadSystemOverview();
      void handleUSPaperStatus();
      void handleUSPaperDailyResults();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : 'paper 回测失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSQualityReport = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<USQualityReportResponse>('/api/us/data/quality-report', {
        symbol: usForm.symbol,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
      });
      setUSQualityReport(result);
      setUSMessage(result.has_issues ? `数据质量发现 ${result.total_issues} 个问题。` : '数据质量检查通过。');
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '数据质量检查失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSCostStressED = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<EventDrivenCostStressResponse>('/api/backtests/cost-stress/event-driven', {
        source: 'yfinance',
        symbol: usForm.symbol,
        interval: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000,
        max_scenarios: 5,
      });
      setEDCostStress(result);
      setUSMessage(`成本压力完成，生存率 ${result.survival_rate_pct.toFixed(0)}%。`);
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '成本压力失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSWalkForward = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<{stability: {pass_rate_pct?: number}; windows: Array<unknown>}>('/api/backtests/walk-forward', {
        source: 'yfinance',
        symbol: usForm.symbol,
        interval: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000,
        commission_rate: 0.0001,
        strategy_id: usForm.strategyId,
        data_root: usForm.dataRoot,
      });
      setUSMessage(`Walk-forward 完成，pass rate ${metricValue(result.stability.pass_rate_pct, 0, '%')}。`);
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : 'walk-forward 失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPromotionGate = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await apiPost<PromotionGateResponse>('/api/research/promotion-gate', {
        strategy_id: usForm.strategyId,
        symbol: usForm.symbol,
        interval: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000,
        source: 'yfinance',
        data_root: usForm.dataRoot,
        skip_deep_checks: false,
      });
      setPromotionGateResult(result);
      const passed = result.gates.filter(gate => gate.status === 'pass').length;
      setUSMessage(`晋升门完成，${passed}/${result.gates.length} 通过，结论 ${result.decision.toUpperCase()}。`);
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '晋升门失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSCreatePaperReview = async (payload: {strategy_manifest_id?: string; candidate_id?: string}) => {
    setUSLoading(true);
    setUSMessage('');
    try {
      if (!payload.strategy_manifest_id && !payload.candidate_id) {
        throw new Error('没有 eligible manifest 时不能创建 paper-review evidence');
      }
      const result = await apiPost<{paper_review_id: string; status: string; note: string}>('/api/research/paper-review/create', {
        ...payload,
        data_root: usForm.dataRoot,
      });
      setUSMessage(`Paper review evidence 创建完成: ${result.paper_review_id}.`);
      void loadSystemOverview();
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '创建 paper-review evidence 失败');
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperReset = async () => {
    setUSLoading(true);
    try {
      await apiPost<{status: string}>('/api/us/paper/reset');
      setUSMessage('Paper 账本已重置。');
      setPaperBacktest(null);
      setUSPaperStatus(null);
      setUSPaperDailyResults([]);
      setUSReconcile(null);
    } catch (e: unknown) {
      setUSMessage(e instanceof Error ? e.message : '重置失败');
    } finally {
      setUSLoading(false);
      void loadSystemOverview();
      void handleUSPaperStatus();
      void handleUSPaperDailyResults();
    }
  };

  const workflowSteps: MvpStep[] = [
    {
      id: 'data',
      label: '数据质量',
      status: usQualityReport ? (usQualityReport.has_issues ? 'fail' : 'done') : usSync ? 'warn' : 'pending',
      detail: usQualityReport ? (usQualityReport.has_issues ? `${usQualityReport.total_issues} 个问题` : `版本 ${usQualityReport.data_version}`) : '先同步再校验',
    },
    {
      id: 'features',
      label: '研究快照',
      status: usFeature ? 'done' : 'pending',
      detail: usFeature ? `${usFeature.rows_written} 行 / ${usFeature.version}` : '保留特征版本',
    },
    {
      id: 'backtest',
      label: '账本回测',
      status: usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? 'done' : 'fail') : usBacktest ? 'warn' : 'pending',
      detail: usUnifiedBacktest ? `${usUnifiedBacktest.fill_count} fills` : '等待统一回测',
    },
    {
      id: 'promotion',
      label: 'Paper Review',
      status: systemOverview?.paper_review.status ? (systemOverview.paper_review.entry_allowed ? 'done' : 'fail') : 'pending',
      detail: systemOverview?.paper_review.status ?? '未进入 paper review',
    },
    {
      id: 'paper',
      label: 'Paper Ready',
      status: systemOverview?.paper_validation.state ? (systemOverview.paper_validation.state === 'PASS' ? 'done' : 'fail') : usPaperStatus ? (toneForPaper(usPaperStatus) === 'good' ? 'done' : toneForPaper(usPaperStatus) === 'bad' ? 'fail' : 'warn') : 'pending',
      detail: systemOverview?.paper_validation.state ? `${systemOverview.paper_validation.days_completed ?? 0}/${systemOverview.paper_validation.days_required ?? 0} 天` : usPaperStatus ? `${usPaperStatus.days_traded} 天 / ${usPaperStatus.last_reconciliation_passed ? '对账通过' : '待复核'}` : '待 paper 记录',
    },
  ];

  const gateCards: GateCard[] = [
    {
      id: 'system',
      title: '系统状态',
      status: systemOverview?.status ?? (health?.fastapi_available ? 'online' : '等待连接'),
      detail: systemOverview ? `${systemOverview.stage} · ${systemOverview.mode}` : health ? `${health.service} · 数据源 ${health.data_source_default}` : '后端未返回总览',
      tone: systemOverview ? toneFromOverviewStatus(systemOverview.status) : health?.fastapi_available ? 'good' : 'neutral',
    },
    {
      id: 'registry',
      title: 'Registry',
      status: systemOverview?.registry.integrity ?? usQualityReport?.data_version ?? '待检查',
      detail: systemOverview?.registry.path ?? `${usForm.dataRoot}/research/evidence_registry.json`,
      tone: systemOverview ? toneFromOverviewStatus(systemOverview.registry.integrity) : usQualityReport ? (usQualityReport.has_issues ? 'bad' : 'good') : 'neutral',
    },
    {
      id: 'paper-validation',
      title: 'Paper Validation',
      status: systemOverview?.paper_validation.state ?? '待运行',
      detail: systemOverview ? `${systemOverview.paper_validation.days_completed ?? 0}/${systemOverview.paper_validation.days_required ?? 0} 天 clean` : '等待 paper validation',
      tone: systemOverview ? toneFromOverviewStatus(systemOverview.paper_validation.state) : 'neutral',
    },
    {
      id: 'minute-data',
      title: 'Minute Data',
      status: systemOverview?.minute_data_quality?.status ?? '未检查',
      detail: systemOverview?.minute_data_quality
        ? `${systemOverview.minute_data_quality.evaluated_symbols?.length ?? 0} symbols · ${(systemOverview.minute_data_quality.bar_sizes ?? []).join('/') || '1m/5m/15m'}`
        : '等待 1m/5m/15m quality gate',
      tone: systemOverview ? toneFromOverviewStatus(systemOverview.minute_data_quality?.status) : 'neutral',
    },
    {
      id: 'paper-review',
      title: 'Paper Review',
      status: systemOverview?.paper_review.status ?? '未出具',
      detail: systemOverview?.paper_review.summary ?? '等待 review evidence',
      tone: systemOverview ? (systemOverview.paper_review.entry_allowed ? 'good' : 'bad') : 'neutral',
    },
    {
      id: 'credentials',
      title: 'Broker Credentials',
      status: systemOverview?.broker_credentials.credentials_present ? 'Present' : 'Missing',
      detail: systemOverview ? `${systemOverview.broker_credentials.endpoint_kind ?? 'unset'} · base URL ${systemOverview.broker_credentials.base_url_valid ? 'valid' : 'invalid'}` : '等待总览',
      tone: systemOverview ? (systemOverview.broker_credentials.credentials_present && systemOverview.broker_credentials.base_url_valid ? 'good' : 'bad') : 'neutral',
    },
    {
      id: 'execution',
      title: 'Execution State',
      status: systemOverview?.execution.live_state ?? 'frozen',
      detail: systemOverview
        ? `paper submit ${systemOverview.execution.paper_network_submit_confirmation ? 'confirmed' : 'locked'} · ${systemOverview.execution.live_block_reason ?? 'live runtime frozen'}`
        : 'live runtime frozen',
      tone: systemOverview ? toneFromOverviewStatus(systemOverview.execution.live_state) : 'bad',
    },
  ];

  const evidenceEntries: EvidenceEntry[] = [
    {label: '策略版本', value: promotionGateResult?.strategy_version ?? selectedStrategy?.display_name ?? usForm.strategyId},
    {label: '数据版本', value: usQualityReport?.data_version ?? promotionGateResult?.experiment_record.data_version ?? '未生成', muted: !usQualityReport && !promotionGateResult?.experiment_record.data_version},
    {label: 'manifest', value: systemOverview?.paper_review.manifest_path ?? promotionGateResult?.manifest_path ?? '未出具', muted: !systemOverview?.paper_review.manifest_path && !promotionGateResult?.manifest_path},
    {label: '阻塞原因', value: (systemOverview?.paper_review.creation?.why_blocked ?? []).join(' · ') || '无', muted: !(systemOverview?.paper_review.creation?.why_blocked ?? []).length},
    {label: '下一条命令', value: systemOverview?.paper_review.creation?.next_command ?? '无', muted: !systemOverview?.paper_review.creation?.next_command},
    {label: '合格 manifest', value: systemOverview?.paper_review.creation?.preferred_manifest_id ?? '无', muted: !systemOverview?.paper_review.creation?.preferred_manifest_id},
    {label: '实验', value: promotionGateResult?.experiment_record.experiment_id ?? '未记录', muted: !promotionGateResult?.experiment_record.experiment_id},
    {label: '注册表', value: systemOverview?.registry.path ?? `${usForm.dataRoot}/research/evidence_registry.json`},
    {label: '纸交易复核', value: systemOverview?.paper_review.review_path ?? '未生成', muted: !systemOverview?.paper_review.review_path},
    {label: '证据包', value: systemOverview?.paper_review.evidence_pack_path ?? '未生成', muted: !systemOverview?.paper_review.evidence_pack_path},
    {label: '账本', value: usForm.ledgerDir},
    {label: '对账报告', value: usReconcile?.report_path ?? '未生成', muted: !usReconcile?.report_path},
  ];

  const planningOverview = useMemo(() => {
    const overviewRoot = systemOverview as unknown as LooseRecord | null;
    const integrationsRoot = readRecord(overviewRoot, 'integrations');
    const dependencyRoot = readRecord(integrationsRoot, 'dependencies');
    const qlibRoot = readRecord(integrationsRoot, 'qlib');
    const portfolioRoot = readRecord(integrationsRoot, 'portfolio');
    const coverageRoot = readRecord(overviewRoot, 'data_coverage');
    const pitRoot = readRecord(overviewRoot, 'pit_data_intake');
    const pitNextAction = readRecord(pitRoot, 'next_action');
    const pitHandoffRoot = readRecord(overviewRoot, 'pit_operator_handoff');
    const pitHandoffOutputsRoot = readRecord(pitHandoffRoot, 'outputs');
    const developmentAuditRoot = readRecord(overviewRoot, 'development_plan_audit');
    const developmentAuditSummary = readRecord(developmentAuditRoot, 'summary');
    const liveReadinessRoot = readRecord(overviewRoot, 'live_readiness');
    const strategyValidationRoot = readRecord(overviewRoot, 'strategy_validation_gate');
    const forwardObservationRoot = readRecord(overviewRoot, 'forward_observation');
    const manualReviewPacketRoot = readRecord(overviewRoot, 'manual_review_packet');
    const paperSimulationRoot = readRecord(overviewRoot, 'paper_simulation_readiness');
    const paperRunnerContractRoot = readRecord(paperSimulationRoot, 'required_runner_contract');
    const paperManualEvidenceRoot = readRecord(paperSimulationRoot, 'manual_review_evidence');
    const paperSourceReportsRoot = readRecord(paperSimulationRoot, 'source_reports');
    const smallAccountPreflightRoot = readRecord(overviewRoot, 'small_account_execution_preflight');
    const smallLatestTargetRoot = readRecord(smallAccountPreflightRoot, 'latest_target');
    const dataLineageGovernanceRoot = readRecord(overviewRoot, 'data_lineage_governance');
    const productionDataAcquisitionRoot = readRecord(overviewRoot, 'production_data_acquisition');
    const productionBundleGateRoot = readRecord(overviewRoot, 'production_bundle_gate');
    const schemaAuditRoot = readRecord(overviewRoot, 'standard_report_schema_audit');
    const schemaCoverageRoot = readRecord(schemaAuditRoot, 'coverage_summary');
    const monitoringRulesRoot = readRecord(overviewRoot, 'monitoring_rules');
    const replayReadinessRoot = readRecord(overviewRoot, 'replay_readiness');
    const replayLatestRoot = readRecord(replayReadinessRoot, 'latest_observation');
    const strategyRegistryRoot = readRecord(overviewRoot, 'strategy_registry');
    const strategyRegistryAuditRoot = readRecord(strategyRegistryRoot, 'audit');
    const registryStageCountsRoot = readRecord(strategyRegistryRoot, 'stage_counts');
    const registryStatusCountsRoot = readRecord(strategyRegistryRoot, 'status_counts');
    const dailyProductionLineRoot = readRecord(overviewRoot, 'daily_production_line');
    const dailyExpectedBlockerRoot = readRecord(dailyProductionLineRoot, 'expected_external_blocker');
    const dailyForwardRoot = readRecord(dailyProductionLineRoot, 'forward_observation');
    const dailyForwardDataGateRoot = readRecord(dailyProductionLineRoot, 'forward_data_gate');
    const reviewRoot = readRecord(overviewRoot, 'paper_review');
    const diagnosticsRoot = readRecord(reviewRoot, 'diagnostics');
    const qlibLatestRun = readRecord(qlibRoot, 'latest_run');
    const portfolioLatestRun = readRecord(portfolioRoot, 'latest_run');
    const rawCoverage = readNumber(coverageRoot, 'coverage_pct');
    const minCoverage = readNumber(coverageRoot, 'min_coverage_pct');
    const coverageStatus = readString(coverageRoot, 'status') ?? readString(readRecord(overviewRoot, 'minute_data_quality'), 'status') ?? '未检查';
    const qlibInstalled = readBoolean(dependencyRoot, 'qlib');
    const pypfoptInstalled = readBoolean(dependencyRoot, 'pypfopt');
    const latestQlibLabel = readString(qlibLatestRun, 'run_id') ?? readString(qlibRoot, 'latest_run_id') ?? '未找到';
    const latestQlibStatus = cnStatus(readString(qlibLatestRun, 'workflow_status', 'dataset_status', 'manifest_status', 'status') ?? readString(qlibRoot, 'status') ?? 'missing');
    const latestPortfolioLabel = readString(portfolioLatestRun, 'portfolio_run_id') ?? readString(portfolioRoot, 'latest_run_id') ?? '未找到';
    const latestPortfolioStatus = cnStatus(readString(portfolioLatestRun, 'optimizer', 'status') ?? readString(portfolioRoot, 'status') ?? 'missing');
    const conflictDetected = readBoolean(diagnosticsRoot, 'conflict_detected') ?? false;
    const conflictNotes = readArray(diagnosticsRoot, 'conflict_notes');
    const pitStatus = readString(pitRoot, 'status') ?? 'missing';
    const pitBlockingStage = readString(pitRoot, 'current_blocking_stage') ?? 'unknown';
    const pitFirstBlocker = readString(pitNextAction, 'first_blocker') ?? '';
    const pitAction = readString(pitNextAction, 'description') ?? '等待 PIT 数据接入报告';
    const pitStages = readArray(pitRoot, 'stages');
    const pitPassedStages = pitStages.filter(stage => readString(asRecord(stage), 'status') === 'pass').length;
    const pitOperatorActions = readArray(pitRoot, 'operator_actions')
      .map(action => {
        const row = asRecord(action);
        if (!row) return null;
        return {
          label: readString(row, 'label') ?? 'PIT 操作',
          intent: readString(row, 'intent') ?? '',
          command: readString(row, 'command') ?? '',
          blockedUntil: readString(row, 'blocked_until') ?? '',
        };
      })
      .filter((action): action is {label: string; intent: string; command: string; blockedUntil: string} => Boolean(action?.command))
      .slice(0, 5);
    const pitHandoffStatus = readString(pitHandoffRoot, 'status') ?? 'missing';
    const pitHandoffBlockingStage = readString(pitHandoffRoot, 'current_blocking_stage') ?? 'unknown';
    const pitHandoffIncomingDropDir = readString(pitHandoffRoot, 'incoming_drop_dir') ?? '';
    const pitHandoffBundleId = readString(pitHandoffRoot, 'default_bundle_id') ?? '';
    const pitHandoffMarkdown = readString(pitHandoffOutputsRoot, 'markdown') ?? '';
    const pitHandoffRequiredTableCount = readNumber(pitHandoffRoot, 'required_table_count') ?? 0;
    const pitHandoffBlockers = readArray(pitHandoffRoot, 'blockers').map(blocker => String(blocker));
    const pitHandoffActions = readArray(pitHandoffRoot, 'operator_next_actions').map(action => String(action)).slice(0, 5);
    const pitHandoffTables = readArray(pitHandoffRoot, 'required_tables')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          table: readString(row, 'table') ?? '',
          filename: readString(row, 'filename') ?? '',
          fieldCount: readNumber(row, 'field_count') ?? 0,
        };
      })
      .filter((item): item is {table: string; filename: string; fieldCount: number} => Boolean(item?.table))
      .slice(0, 6);
    const developmentStatus = readString(developmentAuditRoot, 'status') ?? 'missing';
    const developmentPhaseCount = readNumber(developmentAuditSummary, 'phase_count') ?? 0;
    const developmentCompleteCount = readNumber(developmentAuditSummary, 'complete_count') ?? 0;
    const developmentBlockedCount = readNumber(developmentAuditSummary, 'blocked_count') ?? 0;
    const developmentObservingCount = readNumber(developmentAuditSummary, 'observing_count') ?? 0;
    const developmentPhases = readArray(developmentAuditRoot, 'phase_checks')
      .map(phase => {
        const row = asRecord(phase);
        if (!row) return null;
        const blockers = readArray(row, 'blockers').map(blocker => String(blocker));
        return {
          id: readString(row, 'phase_id') ?? '',
          title: readString(row, 'title') ?? readString(row, 'phase_id') ?? '阶段',
          status: readString(row, 'status') ?? 'unknown',
          blockers,
          blockedCount: readNumber(row, 'blocked_count') ?? blockers.length,
        };
      })
      .filter((phase): phase is {id: string; title: string; status: string; blockers: string[]; blockedCount: number} => Boolean(phase?.id))
      .filter(phase => ['phase_1_data_lineage_hardening', 'phase_2_strategy_validation_gate', 'phase_3_forward_observation_evaluation', 'phase_6_live_readiness'].includes(phase.id));
    const liveReadinessStatus = readString(liveReadinessRoot, 'status') ?? 'missing';
    const liveReadinessDecision = readString(liveReadinessRoot, 'decision') ?? '';
    const liveReadinessBlockers = readArray(liveReadinessRoot, 'blockers').map(blocker => String(blocker));
    const accountCapitalUsd = readNumber(liveReadinessRoot, 'account_capital_usd');
    const maxLivePrincipalUsd = readNumber(liveReadinessRoot, 'max_live_principal_usd');
    const liveOrderAllowed = readBoolean(liveReadinessRoot, 'live_order_allowed') ?? false;
    const strategyValidationStatus = readString(strategyValidationRoot, 'status') ?? 'missing';
    const strategyValidationDecision = readString(strategyValidationRoot, 'decision') ?? '';
    const strategyValidationVariant = readString(strategyValidationRoot, 'candidate_variant') ?? '';
    const strategyValidationBlockers = readArray(strategyValidationRoot, 'blockers').map(blocker => String(blocker));
    const strategyValidationChecks = readArray(strategyValidationRoot, 'checks')
      .map(check => {
        const row = asRecord(check);
        if (!row) return null;
        return {
          id: readString(row, 'check_id') ?? 'check',
          passed: readBoolean(row, 'passed') ?? false,
          firstBlocker: readArray(row, 'matched_data_quality_blockers').map(item => String(item))[0] ?? '',
        };
      })
      .filter((check): check is {id: string; passed: boolean; firstBlocker: string} => Boolean(check?.id))
      .slice(0, 8);
    const forwardStatus = readString(forwardObservationRoot, 'status') ?? 'missing';
    const forwardHealthStatus = readString(forwardObservationRoot, 'daily_health_status') ?? 'missing';
    const forwardObservationDays = readNumber(forwardObservationRoot, 'observation_days') ?? 0;
    const forwardMinimumDays = readNumber(forwardObservationRoot, 'minimum_complete_days') ?? 30;
    const forwardLatestDate = readString(forwardObservationRoot, 'latest_observation_date') ?? '';
    const forwardBlockers = readArray(forwardObservationRoot, 'blockers').map(blocker => String(blocker));
    const manualReviewStatus = readString(manualReviewPacketRoot, 'status') ?? 'missing';
    const manualReviewDecision = readString(manualReviewPacketRoot, 'decision') ?? '';
    const manualReviewBlockers = readArray(manualReviewPacketRoot, 'blockers').map(blocker => String(blocker));
    const manualChecklist = readArray(manualReviewPacketRoot, 'evidence_checklist')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'check_id') ?? 'check',
          passed: readBoolean(row, 'passed') ?? false,
        };
      })
      .filter((item): item is {id: string; passed: boolean} => Boolean(item?.id));
    const manualChecklistPassed = manualChecklist.filter(item => item.passed).length;
    const manualSignoffs = readArray(manualReviewPacketRoot, 'signoff_requirements')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'signoff_id') ?? 'signoff',
          recorded: readBoolean(row, 'recorded') ?? false,
          required: readBoolean(row, 'required') ?? false,
        };
      })
      .filter((item): item is {id: string; recorded: boolean; required: boolean} => Boolean(item?.id));
    const manualRequiredSignoffs = manualSignoffs.filter(item => item.required).length;
    const manualRecordedSignoffs = manualSignoffs.filter(item => item.recorded).length;
    const paperSimulationStatus = readString(paperSimulationRoot, 'status') ?? 'missing';
    const paperSimulationDecision = readString(paperSimulationRoot, 'decision') ?? '';
    const paperLedgerRoot = readString(paperSimulationRoot, 'paper_ledger_root') ?? '';
    const paperRunnerAllowed = readBoolean(paperSimulationRoot, 'paper_runner_allowed') ?? false;
    const paperSimulationBlockers = readArray(paperSimulationRoot, 'blockers').map(blocker => String(blocker));
    const paperSimulationUnsafeFlags = readArray(paperSimulationRoot, 'unsafe_flags').map(flag => String(flag));
    const paperContractIndependentRoot = readString(paperRunnerContractRoot, 'independent_ledger_root') ?? '';
    const paperContractNoForwardReuse = readBoolean(paperRunnerContractRoot, 'must_not_reuse_forward_observation_ledger') ?? false;
    const paperContractNoOrders = readBoolean(paperRunnerContractRoot, 'order_endpoint_allowed') === false
      && readBoolean(paperRunnerContractRoot, 'real_order_submitted') === false;
    const paperForwardDataGateClean = readBoolean(paperManualEvidenceRoot, 'forward_data_gate_no_blocked_runs') ?? false;
    const paperForwardDataGateBlockedCount = readNumber(paperManualEvidenceRoot, 'forward_data_gate_blocked_count') ?? 0;
    const paperProductionPitIntakeSource = readString(paperSourceReportsRoot, 'production_pit_intake_status') ?? '';
    const smallAccountPreflightStatus = readString(smallAccountPreflightRoot, 'status') ?? 'missing';
    const smallAccountTimestamp = readString(smallAccountPreflightRoot, 'timestamp') ?? '';
    const smallAccountEquity = readNumber(smallAccountPreflightRoot, 'account_equity') ?? 0;
    const smallAnnualFinancingRate = readNumber(smallAccountPreflightRoot, 'annual_financing_rate') ?? 0;
    const smallSlippageBps = readNumber(smallAccountPreflightRoot, 'slippage_bps') ?? 0;
    const smallScenarioCount = readNumber(smallAccountPreflightRoot, 'scenario_count') ?? 0;
    const smallPassedScenarioCount = readNumber(smallAccountPreflightRoot, 'passed_scenario_count') ?? 0;
    const smallTargetGross = readNumber(smallLatestTargetRoot, 'gross_exposure');
    const smallTargetSymbols = readArray(smallLatestTargetRoot, 'symbols').map(symbol => String(symbol));
    const smallAccountBlockers = readArray(smallAccountPreflightRoot, 'blockers').map(blocker => String(blocker));
    const smallAccountScenarios = readArray(smallAccountPreflightRoot, 'scenarios')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'scenario_id') ?? 'scenario',
          grossCap: readNumber(row, 'gross_cap') ?? 0,
          effectiveGross: readNumber(row, 'effective_gross') ?? 0,
          allowMargin: readBoolean(row, 'allow_margin') ?? false,
          passed: readBoolean(row, 'passes_preflight') ?? false,
          fractionalCash: readNumber(row, 'fractional_cash_after_orders') ?? 0,
          wholeCash: readNumber(row, 'whole_cash_after_orders') ?? 0,
          firstBlocker: readString(row, 'first_blocker') ?? '',
        };
      })
      .filter((item): item is {id: string; grossCap: number; effectiveGross: number; allowMargin: boolean; passed: boolean; fractionalCash: number; wholeCash: number; firstBlocker: string} => Boolean(item?.id))
      .slice(0, 4);
    const dataLineageStatus = readString(dataLineageGovernanceRoot, 'status') ?? 'missing';
    const dataReconciliationStatus = readString(dataLineageGovernanceRoot, 'reconciliation_status') ?? 'missing';
    const dataRemediationStatus = readString(dataLineageGovernanceRoot, 'remediation_status') ?? 'missing';
    const macroLagStatus = readString(dataLineageGovernanceRoot, 'macro_release_lag_status') ?? 'missing';
    const selectedPriceSource = readString(dataLineageGovernanceRoot, 'selected_price_source') ?? '';
    const selectedPriceRoot = readString(dataLineageGovernanceRoot, 'selected_price_root') ?? '';
    const lineageMaturity = readString(dataLineageGovernanceRoot, 'lineage_maturity') ?? '';
    const remediationTaskCount = readNumber(dataLineageGovernanceRoot, 'remediation_task_count') ?? 0;
    const macroSource = readString(dataLineageGovernanceRoot, 'macro_source') ?? '';
    const acceptedEvidenceForPromotion = readBoolean(dataLineageGovernanceRoot, 'accepted_evidence_for_promotion') ?? false;
    const dataLineageBlockers = readArray(dataLineageGovernanceRoot, 'blockers').map(blocker => String(blocker));
    const remediationGroups = readArray(dataLineageGovernanceRoot, 'remediation_groups')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'group_id') ?? 'group',
          status: readString(row, 'status') ?? 'unknown',
          blockerCount: readNumber(row, 'blocker_count') ?? 0,
        };
      })
      .filter((item): item is {id: string; status: string; blockerCount: number} => Boolean(item?.id))
      .slice(0, 6);
    const productionAcquisitionStatus = readString(productionDataAcquisitionRoot, 'status') ?? 'missing';
    const productionCandidateStatus = readString(productionDataAcquisitionRoot, 'candidate_evidence_status') ?? 'missing';
    const productionIntakeStatus = readString(productionDataAcquisitionRoot, 'intake_packet_status') ?? 'missing';
    const productionManualPackageStatus = readString(productionDataAcquisitionRoot, 'manual_package_status') ?? 'missing';
    const productionIncomingDropDir = readString(productionDataAcquisitionRoot, 'incoming_drop_dir') ?? '';
    const productionDefaultBundleId = readString(productionDataAcquisitionRoot, 'default_bundle_id') ?? '';
    const productionRequiredTableCount = readNumber(productionDataAcquisitionRoot, 'required_table_count') ?? 0;
    const productionFieldCount = readNumber(productionDataAcquisitionRoot, 'field_count') ?? 0;
    const productionAcceptableProviders = readArray(productionDataAcquisitionRoot, 'acceptable_provider_ids').map(item => String(item));
    const productionMissingGroups = readArray(productionDataAcquisitionRoot, 'missing_contract_groups').map(item => String(item));
    const productionBlockers = readArray(productionDataAcquisitionRoot, 'blockers').map(blocker => String(blocker));
    const productionRequiredTables = readArray(productionDataAcquisitionRoot, 'required_tables')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          table: readString(row, 'table') ?? '',
          filename: readString(row, 'filename') ?? '',
          fieldCount: readNumber(row, 'field_count') ?? 0,
        };
      })
      .filter((item): item is {table: string; filename: string; fieldCount: number} => Boolean(item?.table))
      .slice(0, 6);
    const productionOperatorSteps = readArray(productionDataAcquisitionRoot, 'operator_steps')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'step_id') ?? 'step',
          command: readString(row, 'command') ?? '',
          expected: readString(row, 'expected_result') ?? '',
        };
      })
      .filter((item): item is {id: string; command: string; expected: string} => Boolean(item?.command))
      .slice(0, 4);
    const productionBundleGateStatus = readString(productionBundleGateRoot, 'status') ?? 'missing';
    const productionBundleCurrentStage = readString(productionBundleGateRoot, 'current_blocking_stage') ?? '';
    const productionBundleBlockers = readArray(productionBundleGateRoot, 'blockers').map(blocker => String(blocker));
    const productionBundleStages = readArray(productionBundleGateRoot, 'stages')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        const summary = readRecord(row, 'summary');
        return {
          id: readString(row, 'stage_id') ?? '',
          status: readString(row, 'status') ?? 'unknown',
          firstBlocker: readArray(row, 'blockers').map(blocker => String(blocker))[0] ?? '',
          bundleId: readString(summary, 'bundle_id', 'candidate_bundle_id') ?? '',
          sourceDir: readString(summary, 'source_dir') ?? '',
        };
      })
      .filter((item): item is {id: string; status: string; firstBlocker: string; bundleId: string; sourceDir: string} => Boolean(item?.id))
      .slice(0, 4);
    const productionBundleActions = readArray(productionBundleGateRoot, 'operator_actions')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'label') ?? readString(row, 'stage_id') ?? 'action',
          stage: readString(row, 'stage_id') ?? '',
          command: readString(row, 'command') ?? '',
          blockedUntil: readString(row, 'blocked_until') ?? '',
        };
      })
      .filter((item): item is {id: string; stage: string; command: string; blockedUntil: string} => Boolean(item?.command))
      .slice(0, 5);
    const schemaAuditStatus = readString(schemaAuditRoot, 'status') ?? 'missing';
    const schemaAuditDecision = readString(schemaAuditRoot, 'decision') ?? '';
    const schemaPassedFields = readNumber(schemaCoverageRoot, 'passed_field_count') ?? 0;
    const schemaRequiredFields = readNumber(schemaCoverageRoot, 'required_field_count') ?? 0;
    const schemaMissingInputs = readNumber(schemaCoverageRoot, 'missing_input_count') ?? 0;
    const schemaUnsafeFlags = readNumber(schemaCoverageRoot, 'unsafe_flag_count') ?? 0;
    const schemaFieldChecks = readArray(schemaAuditRoot, 'field_checks')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'field_id') ?? 'field',
          passed: readBoolean(row, 'passed') ?? false,
        };
      })
      .filter((item): item is {id: string; passed: boolean} => Boolean(item?.id))
      .slice(0, 12);
    const schemaBlockers = readArray(schemaAuditRoot, 'blockers').map(blocker => String(blocker));
    const monitoringStatus = readString(monitoringRulesRoot, 'status') ?? 'missing';
    const monitorCount = readNumber(monitoringRulesRoot, 'monitor_count') ?? 0;
    const monitoringRequiredBeforePaper = readBoolean(monitoringRulesRoot, 'required_before_paper_or_live') ?? true;
    const monitoringSections = readArray(monitoringRulesRoot, 'rule_sections').map(section => String(section));
    const monitoringMinimum = readArray(monitoringRulesRoot, 'minimum_required_before_paper').map(item => String(item));
    const replayStatus = readString(replayReadinessRoot, 'status') ?? 'missing';
    const replayDecision = readString(replayReadinessRoot, 'decision') ?? '';
    const replayTimestamp = readString(replayLatestRoot, 'timestamp') ?? '';
    const replayFillCount = readNumber(replayLatestRoot, 'fill_count') ?? 0;
    const replayChecks = readArray(replayReadinessRoot, 'checks')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {id: readString(row, 'check_id') ?? 'check', passed: readBoolean(row, 'passed') ?? false};
      })
      .filter((item): item is {id: string; passed: boolean} => Boolean(item?.id));
    const replayPassedChecks = replayChecks.filter(item => item.passed).length;
    const registryStatus = readString(strategyRegistryRoot, 'status') ?? 'missing';
    const registryStrategyCount = readNumber(strategyRegistryRoot, 'strategy_count') ?? 0;
    const registryPrimaryStrategyId = readString(strategyRegistryRoot, 'primary_strategy_id') ?? '';
    const registryPrimaryStage = readString(strategyRegistryRoot, 'primary_stage') ?? '';
    const registryPrimaryStatus = readString(strategyRegistryRoot, 'primary_status') ?? '';
    const registryFamilies = readArray(strategyRegistryRoot, 'registered_families').map(item => String(item));
    const registryForwardCount = readNumber(registryStageCountsRoot, 'forward_observation') ?? 0;
    const registryHypothesisCount = readNumber(registryStageCountsRoot, 'strategy_hypothesis_registration') ?? 0;
    const registryHypothesisStatusCount = readNumber(registryStatusCountsRoot, 'hypothesis_registered_only') ?? 0;
    const registryBlockers = readArray(strategyRegistryRoot, 'blockers').map(blocker => String(blocker));
    const registryAuditStatus = readString(strategyRegistryAuditRoot, 'status') ?? 'missing';
    const registryAuditStrategyCount = readNumber(strategyRegistryAuditRoot, 'strategy_count') ?? 0;
    const registryAuditFormalCount = readNumber(strategyRegistryAuditRoot, 'formal_candidate_count') ?? 0;
    const registryAuditPrimaryCount = readNumber(strategyRegistryAuditRoot, 'primary_candidate_count') ?? 0;
    const registryAuditMissingFamilies = readArray(strategyRegistryAuditRoot, 'missing_required_families').map(item => String(item));
    const registryAuditRequiredFamilies = readArray(strategyRegistryAuditRoot, 'required_families').map(item => String(item));
    const registryAuditBlockers = readArray(strategyRegistryAuditRoot, 'blockers').map(blocker => String(blocker));
    const registryStrategies = readArray(strategyRegistryRoot, 'strategies')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'strategy_id') ?? 'strategy',
          family: readString(row, 'family') ?? '',
          status: readString(row, 'status') ?? 'unknown',
          stage: readString(row, 'current_stage') ?? 'unknown',
          primary: readBoolean(row, 'primary_candidate') ?? false,
          paperReady: readBoolean(row, 'paper_ready') ?? false,
          liveReady: readBoolean(row, 'live_ready') ?? false,
        };
      })
      .filter((item): item is {id: string; family: string; status: string; stage: string; primary: boolean; paperReady: boolean; liveReady: boolean} => Boolean(item?.id))
      .slice(0, 7);
    const dailyProductionStatus = readString(dailyProductionLineRoot, 'status') ?? 'missing';
    const dailyProductionDecision = readString(dailyProductionLineRoot, 'decision') ?? '';
    const dailyProductionGeneratedAt = readString(dailyProductionLineRoot, 'generated_at') ?? '';
    const dailyStepCount = readNumber(dailyProductionLineRoot, 'step_count') ?? 0;
    const dailyPassedStepCount = readNumber(dailyProductionLineRoot, 'passed_step_count') ?? 0;
    const dailyFailedStepCount = readNumber(dailyProductionLineRoot, 'failed_step_count') ?? 0;
    const dailyProductionPitRequired = readBoolean(dailyExpectedBlockerRoot, 'production_pit_data_required') ?? false;
    const dailyProductionLineStatus = readString(dailyExpectedBlockerRoot, 'production_line_status') ?? '';
    const dailyDevelopmentPlanStatus = readString(dailyExpectedBlockerRoot, 'development_plan_status') ?? '';
    const dailyForwardHealthStatus = readString(dailyForwardRoot, 'daily_health_status') ?? '';
    const dailyForwardObservationDays = readNumber(dailyForwardRoot, 'observation_days') ?? 0;
    const dailyForwardMinimumDays = readNumber(dailyForwardRoot, 'minimum_complete_days') ?? 30;
    const dailyForwardDataGateStatus = readString(dailyForwardDataGateRoot, 'status') ?? 'missing';
    const dailyForwardDataGateBlockers = readArray(dailyForwardDataGateRoot, 'blockers').map(blocker => String(blocker));
    const dailyForwardDataGateChecks = readArray(dailyForwardDataGateRoot, 'checks')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'check_id') ?? 'check',
          status: readString(row, 'status') ?? 'unknown',
          passed: readBoolean(row, 'passed') ?? false,
          firstBlocker: readString(row, 'first_blocker') ?? '',
        };
      })
      .filter((item): item is {id: string; status: string; passed: boolean; firstBlocker: string} => Boolean(item?.id))
      .slice(0, 4);
    const dailyBlockers = readArray(dailyProductionLineRoot, 'blockers').map(blocker => String(blocker));
    const dailyUnsafeFlags = readArray(dailyProductionLineRoot, 'unsafe_flags').map(flag => String(flag));
    const dailySteps = readArray(dailyProductionLineRoot, 'steps')
      .map(item => {
        const row = asRecord(item);
        if (!row) return null;
        return {
          id: readString(row, 'step_id') ?? 'step',
          status: readString(row, 'status') ?? 'unknown',
          passed: readBoolean(row, 'passed') ?? false,
          firstBlocker: readString(row, 'first_blocker') ?? '',
        };
      })
      .filter((item): item is {id: string; status: string; passed: boolean; firstBlocker: string} => Boolean(item?.id))
      .slice(0, 8);
    const nextActions = (systemOverview?.next_actions ?? []).slice(0, 3);
    const recommendedActions: Array<{label: string; onClick: () => void; disabled: boolean}> = [
      {
        label: '同步数据',
        onClick: handleUSDataSync,
        disabled: usLoading,
      },
      {
        label: '检查质量',
        onClick: handleUSQualityReport,
        disabled: usLoading,
      },
      {
        label: '统一回测',
        onClick: handleUSUnifiedBacktest,
        disabled: usLoading,
      },
      {
        label: '晋升门',
        onClick: handleUSPromotionGate,
        disabled: usLoading,
      },
    ];
    return {
      qlibInstalled,
      pypfoptInstalled,
      coverageStatus,
      rawCoverage,
      minCoverage,
      latestQlibLabel,
      latestQlibStatus,
      latestPortfolioLabel,
      latestPortfolioStatus,
      conflictDetected,
      conflictNotes: conflictNotes.map(note => String(note)),
      pitStatus,
      pitBlockingStage,
      pitFirstBlocker,
      pitAction,
      pitStageCount: pitStages.length,
      pitPassedStages,
      pitOperatorActions,
      pitHandoffStatus,
      pitHandoffBlockingStage,
      pitHandoffIncomingDropDir,
      pitHandoffBundleId,
      pitHandoffMarkdown,
      pitHandoffRequiredTableCount,
      pitHandoffBlockers,
      pitHandoffActions,
      pitHandoffTables,
      developmentStatus,
      developmentPhaseCount,
      developmentCompleteCount,
      developmentBlockedCount,
      developmentObservingCount,
      developmentPhases,
      liveReadinessStatus,
      liveReadinessDecision,
      liveReadinessBlockers,
      accountCapitalUsd,
      maxLivePrincipalUsd,
      liveOrderAllowed,
      strategyValidationStatus,
      strategyValidationDecision,
      strategyValidationVariant,
      strategyValidationBlockers,
      strategyValidationChecks,
      forwardStatus,
      forwardHealthStatus,
      forwardObservationDays,
      forwardMinimumDays,
      forwardLatestDate,
      forwardBlockers,
      manualReviewStatus,
      manualReviewDecision,
      manualReviewBlockers,
      manualChecklistPassed,
      manualChecklistCount: manualChecklist.length,
      manualRecordedSignoffs,
      manualRequiredSignoffs,
      paperSimulationStatus,
      paperSimulationDecision,
      paperLedgerRoot,
      paperRunnerAllowed,
      paperSimulationBlockers,
      paperSimulationUnsafeFlags,
      paperContractIndependentRoot,
      paperContractNoForwardReuse,
      paperContractNoOrders,
      paperForwardDataGateClean,
      paperForwardDataGateBlockedCount,
      paperProductionPitIntakeSource,
      smallAccountPreflightStatus,
      smallAccountTimestamp,
      smallAccountEquity,
      smallAnnualFinancingRate,
      smallSlippageBps,
      smallScenarioCount,
      smallPassedScenarioCount,
      smallTargetGross,
      smallTargetSymbols,
      smallAccountBlockers,
      smallAccountScenarios,
      dataLineageStatus,
      dataReconciliationStatus,
      dataRemediationStatus,
      macroLagStatus,
      selectedPriceSource,
      selectedPriceRoot,
      lineageMaturity,
      remediationTaskCount,
      macroSource,
      acceptedEvidenceForPromotion,
      dataLineageBlockers,
      remediationGroups,
      productionAcquisitionStatus,
      productionCandidateStatus,
      productionIntakeStatus,
      productionManualPackageStatus,
      productionIncomingDropDir,
      productionDefaultBundleId,
      productionRequiredTableCount,
      productionFieldCount,
      productionAcceptableProviders,
      productionMissingGroups,
      productionBlockers,
      productionRequiredTables,
      productionOperatorSteps,
      productionBundleGateStatus,
      productionBundleCurrentStage,
      productionBundleBlockers,
      productionBundleStages,
      productionBundleActions,
      schemaAuditStatus,
      schemaAuditDecision,
      schemaPassedFields,
      schemaRequiredFields,
      schemaMissingInputs,
      schemaUnsafeFlags,
      schemaFieldChecks,
      schemaBlockers,
      monitoringStatus,
      monitorCount,
      monitoringRequiredBeforePaper,
      monitoringSections,
      monitoringMinimum,
      replayStatus,
      replayDecision,
      replayTimestamp,
      replayFillCount,
      replayPassedChecks,
      replayCheckCount: replayChecks.length,
      registryStatus,
      registryStrategyCount,
      registryPrimaryStrategyId,
      registryPrimaryStage,
      registryPrimaryStatus,
      registryFamilies,
      registryForwardCount,
      registryHypothesisCount,
      registryHypothesisStatusCount,
      registryBlockers,
      registryAuditStatus,
      registryAuditStrategyCount,
      registryAuditFormalCount,
      registryAuditPrimaryCount,
      registryAuditMissingFamilies,
      registryAuditRequiredFamilies,
      registryAuditBlockers,
      registryStrategies,
      dailyProductionStatus,
      dailyProductionDecision,
      dailyProductionGeneratedAt,
      dailyStepCount,
      dailyPassedStepCount,
      dailyFailedStepCount,
      dailyProductionPitRequired,
      dailyProductionLineStatus,
      dailyDevelopmentPlanStatus,
      dailyForwardHealthStatus,
      dailyForwardObservationDays,
      dailyForwardMinimumDays,
      dailyForwardDataGateStatus,
      dailyForwardDataGateBlockers,
      dailyForwardDataGateChecks,
      dailyBlockers,
      dailyUnsafeFlags,
      dailySteps,
      nextActions,
      recommendedActions,
    };
  }, [systemOverview, usLoading, handleUSDataSync, handleUSQualityReport, handleUSUnifiedBacktest, handleUSPromotionGate]);

  const statusCards = useMemo<ModuleStateCardProps[]>(() => {
    const usOutcome = promotionGateResult?.decision === 'pass' ? 'PASS' : 'BLOCKED';
    const paperOutcome = systemOverview?.paper_review.entry_allowed ? 'PASS' : 'BLOCKED';
    const liveOutcome = systemOverview?.execution.live_state === 'frozen' ? 'PASS' : 'BLOCKED';
    return [
      {
        id: 'us-equity',
        title: '美股',
        status: usOutcome,
        tone: usOutcome === 'PASS' ? 'good' : 'bad',
        reason: promotionGateResult
          ? `${promotionGateResult.next_stage} · ${promotionGateResult.recommendations[0] ?? '晋升门已出具'}`
          : systemOverview?.paper_review.summary ?? '等待数据质量、回测和晋升门证据。',
        hint: '数据同步、特征、回测、成本压力、滚动验证、晋升门',
        meta: [
          {label: '策略', value: selectedStrategy?.display_name ?? usForm.strategyId},
          {label: '阶段', value: cnStatus(systemOverview?.stage ?? 'waiting')},
        ],
        actions: [{
          label: '运行晋升门',
          onClick: () => { void handleUSPromotionGate(); },
          disabled: usLoading,
          variant: 'primary',
        }],
      },
      {
        id: 'paper-review',
        title: '纸交易复核',
        status: paperOutcome,
        tone: paperOutcome === 'PASS' ? 'good' : 'bad',
        reason: systemOverview?.paper_review.creation?.summary ?? systemOverview?.paper_review.summary ?? '未进入纸交易复核。',
        hint: 'manifest、证据包、人工复核入口',
        meta: [
          {label: 'manifest', value: systemOverview?.paper_review.manifest_path ?? '缺失'},
          {label: '证据', value: systemOverview?.paper_review.evidence_pack_path ?? '缺失'},
        ],
        actions: [{
          label: '运行纸交易日',
          onClick: () => { void handleUSPaperRunDay(); },
          disabled: usLoading,
          variant: 'primary',
        }, {
          label: '创建复核证据',
          onClick: () => {
            void handleUSCreatePaperReview({
              strategy_manifest_id: systemOverview?.paper_review.creation?.preferred_manifest_id,
              candidate_id: systemOverview?.paper_review.creation?.preferred_candidate_id,
            });
          },
          disabled: usLoading || !systemOverview?.paper_review.creation?.creation_allowed || !systemOverview?.paper_review.creation?.preferred_manifest_id,
        }],
      },
      {
        id: 'live-freeze',
        title: '实盘冻结',
        status: liveOutcome,
        tone: liveOutcome === 'PASS' ? 'good' : 'bad',
        reason: `${cnStatus(planningOverview.liveReadinessStatus)} · ${planningOverview.liveReadinessBlockers[0] ?? cnStatus(systemOverview?.execution.live_block_reason ?? 'live runtime frozen')}`,
        hint: '冻结是默认状态，只有证据闭环完成后才允许审批',
        meta: [
          {label: '实盘状态', value: cnStatus(systemOverview?.execution.live_state ?? 'frozen')},
          {label: 'live gate', value: cnStatus(planningOverview.liveReadinessStatus)},
          {label: '最大实盘本金', value: planningOverview.maxLivePrincipalUsd ? `$${planningOverview.maxLivePrincipalUsd.toLocaleString()}` : '未设置'},
        ],
        actions: [{
          label: '刷新冻结状态',
          onClick: () => { void handleUSPaperStatus(); },
          disabled: usLoading,
        }],
      },
    ] satisfies ModuleStateCardProps[];
  }, [handleUSCreatePaperReview, handleUSPaperRunDay, handleUSPaperStatus, handleUSPromotionGate, planningOverview.liveReadinessBlockers, planningOverview.liveReadinessStatus, planningOverview.maxLivePrincipalUsd, promotionGateResult, selectedStrategy?.display_name, systemOverview?.execution.live_block_reason, systemOverview?.execution.live_state, systemOverview?.paper_review.creation?.creation_allowed, systemOverview?.paper_review.creation?.preferred_manifest_id, systemOverview?.paper_review.creation?.preferred_candidate_id, systemOverview?.paper_review.creation?.summary, systemOverview?.paper_review.evidence_pack_path, systemOverview?.paper_review.entry_allowed, systemOverview?.paper_review.manifest_path, systemOverview?.paper_review.summary, systemOverview?.stage, usForm.strategyId, usLoading]);

  const paperEquityCurve = paperBacktest?.daily_results.length
    ? paperBacktest.daily_results.map((day, index) => ({time: index + 1, value: day.ending_equity}))
    : usPaperDailyResults.map((day, index) => ({time: index + 1, value: day.ending_equity}));

  const portfolioOverview = useMemo(() => {
    const overviewRoot = systemOverview as unknown as LooseRecord | null;
    const portfolioRoot = firstPresent(
      readRecord(overviewRoot, 'multi_strategy_portfolio'),
      readRecord(overviewRoot, 'multi_strategy'),
      readRecord(overviewRoot, 'portfolio'),
      readRecord(overviewRoot, 'portfolio_overview'),
      readRecord(overviewRoot, 'portfolio_status'),
    );
    const gatesRoot = firstPresent(
      readRecord(portfolioRoot, 'gates'),
      readRecord(overviewRoot, 'gates'),
    );
    const weightRecords = readArray(portfolioRoot, 'strategy_weights', 'weights', 'allocations', 'strategy_allocations', 'strategies');
    const overviewWeightRecords = readArray(overviewRoot, 'strategy_weights');
    const pnlRecords = readArray(portfolioRoot, 'pnl_attribution', 'attribution', 'pnl_breakdown');
    const overviewPnlRecords = readArray(overviewRoot, 'pnl_attribution');
    const riskBudgetRoot = firstPresent(
      readRecord(portfolioRoot, 'risk_budget'),
      readRecord(overviewRoot, 'risk_budget'),
    );

    const strategyRows: PortfolioSectionRow[] = (weightRecords.length > 0 ? weightRecords : overviewWeightRecords)
      .map((item, index) => {
        const row = asRecord(item);
        if (!row) return null;
        const id = readString(row, 'strategy_id', 'id', 'strategy', 'name') ?? `strategy-${index + 1}`;
        const label = readString(row, 'display_name', 'name', 'strategy_name', 'strategy_id', 'id') ?? id;
        const weight = readNumber(row, 'weight_pct', 'weight', 'target_weight_pct', 'target_weight', 'allocation_pct');
        const riskBudget = readNumber(row, 'risk_budget_pct', 'risk_contribution_pct', 'budget_pct', 'risk_budget');
        const pnl = readNumber(row, 'pnl', 'pnl_usd', 'net_pnl', 'contribution_pnl', 'attribution_pnl');
        const status = readString(row, 'status', 'state', 'readiness') ?? '';
        const note = readString(row, 'summary', 'detail', 'notes', 'note') ?? '权重已加载，等待更细的组合归因字段。';
        return {
          key: id,
          label,
          value: weight !== null ? formatPercentValue(weight, 1) : '待提供',
          detail: `${riskBudget !== null ? `风险预算 ${formatPercentValue(riskBudget, 1)}` : '风险预算待提供'} · ${pnl !== null ? `PnL ${formatSignedPrice(pnl)}` : 'PnL attribution 待提供'}${status ? ` · ${status}` : ''}`,
          tone: pnl !== null ? (pnl >= 0 ? 'good' : 'bad') : 'neutral',
        } satisfies PortfolioSectionRow;
      })
      .filter((row): row is PortfolioSectionRow => row !== null);

    const pnlRows: PortfolioSectionRow[] = (pnlRecords.length > 0 ? pnlRecords : overviewPnlRecords)
      .map((item, index) => {
        const row = asRecord(item);
        if (!row) return null;
        const id = readString(row, 'strategy_id', 'id', 'bucket', 'name') ?? `attr-${index + 1}`;
        const label = readString(row, 'display_name', 'name', 'bucket', 'strategy_name', 'strategy_id') ?? id;
        const pnl = readNumber(row, 'pnl', 'pnl_usd', 'net_pnl', 'contribution_pnl', 'value');
        const contribution = readNumber(row, 'contribution_pct', 'weight_pct', 'share_pct');
        const detail = readString(row, 'summary', 'detail', 'notes') ?? '等待 API 返回更细的归因说明。';
        return {
          key: id,
          label,
          value: formatSignedPrice(pnl),
          detail: `${contribution !== null ? `占比 ${formatPercentValue(contribution, 1)}` : '归因占比待提供'} · ${detail}`,
          tone: pnl !== null ? (pnl >= 0 ? 'good' : 'bad') : 'neutral',
        } satisfies PortfolioSectionRow;
      })
      .filter((row): row is PortfolioSectionRow => row !== null);

    const pnlValues = (pnlRecords.length > 0 ? pnlRecords : overviewPnlRecords)
      .map(item => {
        const row = asRecord(item);
        return row ? readNumber(row, 'pnl', 'pnl_usd', 'net_pnl', 'contribution_pnl', 'value') : null;
      })
      .filter((value): value is number => value !== null);

    const strategyCount = readNumber(portfolioRoot, 'strategy_count', 'count') ?? strategyRows.length;
    const grossExposure = readNumber(portfolioRoot, 'gross_exposure_pct', 'gross_weight_pct', 'gross_weight');
    const netExposure = readNumber(portfolioRoot, 'net_exposure_pct', 'net_weight_pct', 'net_weight');
    const totalPnL = firstPresent(
      readNumber(portfolioRoot, 'total_pnl', 'pnl', 'portfolio_pnl'),
      pnlValues.length > 0 ? pnlValues.reduce((sum, value) => sum + value, 0) : null,
    );
    const totalRiskBudget = firstPresent(
      readNumber(riskBudgetRoot, 'total_budget_pct', 'portfolio_budget_pct', 'risk_budget_pct'),
      strategyRows.length
        ? strategyRows.reduce<number | null>((sum, row) => {
          const match = row.detail.match(/风险预算 ([\d.]+)%/);
          return match ? (sum ?? 0) + Number(match[1]) : sum;
        }, 0)
        : null,
    );

    const budgetItems: PortfolioBudgetItem[] = [
      {
        key: 'gross',
        label: '总曝险',
        value: formatPercentValue(grossExposure, 1),
        detail: grossExposure !== null ? '组合总曝险' : 'API 未提供 gross exposure 字段',
      },
      {
        key: 'net',
        label: '净曝险',
        value: formatPercentValue(netExposure, 1),
        detail: netExposure !== null ? '净曝险' : 'API 未提供 net exposure 字段',
      },
      {
        key: 'risk-budget',
        label: '风险预算',
        value: formatPercentValue(totalRiskBudget, 1),
        detail: totalRiskBudget !== null ? '策略级预算汇总' : '显示占位，等待 risk_budget',
      },
      {
        key: 'cash-buffer',
        label: '现金缓冲',
        value: formatPercentValue(readNumber(riskBudgetRoot, 'cash_buffer_pct', 'cash_reserve_pct', 'reserve_pct'), 1),
        detail: '现金留存 / 风险缓冲',
      },
    ];

    const paperGateRecord = firstPresent(
      readRecord(gatesRoot, 'paper'),
      readRecord(portfolioRoot, 'paper_gate'),
    );
    const liveGateRecord = firstPresent(
      readRecord(gatesRoot, 'live'),
      readRecord(portfolioRoot, 'live_gate'),
    );
    const reviewGateRecord = firstPresent(
      readRecord(gatesRoot, 'review'),
      readRecord(portfolioRoot, 'review_gate'),
    );

    const gateSummaries: PortfolioGateSummary[] = [
      {
        key: 'paper',
        label: '纸交易门禁',
        status: readString(paperGateRecord, 'status', 'state')
          ?? systemOverview?.paper_validation.state
          ?? getPaperStatusLabel(usPaperStatus),
        detail: readString(paperGateRecord, 'summary', 'detail')
          ?? systemOverview?.paper_review.summary
          ?? (usPaperStatus ? `${usPaperStatus.days_traded} 天留样本` : '等待纸交易验证'),
        tone: toneFromOverviewStatus(
          firstPresent(
            readString(paperGateRecord, 'status', 'state'),
            systemOverview?.paper_validation.state,
          ),
        ),
      },
      {
        key: 'review',
        label: '复核门禁',
        status: readString(reviewGateRecord, 'status', 'state')
          ?? systemOverview?.paper_review.status
          ?? 'manual_gate',
        detail: readString(reviewGateRecord, 'summary', 'detail')
          ?? systemOverview?.paper_review.summary
          ?? '等待人工复核 / manifest',
        tone: toneFromOverviewStatus(
          firstPresent(
            readBoolean(reviewGateRecord, 'allowed', 'entry_allowed'),
            systemOverview?.paper_review.entry_allowed,
          ),
        ),
      },
      {
        key: 'live',
        label: '实盘门禁',
        status: readString(liveGateRecord, 'status', 'state')
          ?? systemOverview?.execution.live_state
          ?? 'frozen',
        detail: readString(liveGateRecord, 'summary', 'detail', 'reason')
          ?? systemOverview?.execution.live_block_reason
          ?? '实盘运行已冻结',
        tone: toneFromOverviewStatus(
          firstPresent(
            readString(liveGateRecord, 'status', 'state'),
            systemOverview?.execution.live_state,
          ),
        ),
      },
    ];

    return {
      profile: readString(portfolioRoot, 'profile', 'mode', 'scope') ?? (strategyRows.length > 1 ? '多策略' : '单策略降级'),
      status: readString(portfolioRoot, 'status', 'state') ?? systemOverview?.status ?? 'pending',
      detail: readString(portfolioRoot, 'summary', 'detail') ?? '若 overview 尚未返回组合字段，此区块使用单策略系统状态占位。',
      strategyCount,
      totalPnL,
      totalRiskBudget,
      strategyRows,
      pnlRows,
      budgetItems,
      gateSummaries,
    };
  }, [systemOverview, usPaperStatus]);

  const workflowDoneCount = workflowSteps.filter(step => step.status === 'done').length;
  const opsStages: OpsStageCard[] = [
    {
      key: 'overview',
      label: '总览',
      short: '00',
      status: systemOverview?.stage ?? '等待',
      detail: `${workflowDoneCount}/${workflowSteps.length} 个流程节点完成`,
      tone: workflowDoneCount >= 3 ? 'good' : 'neutral',
    },
    {
      key: 'research',
      label: '数据研究',
      short: '01',
      status: usQualityReport ? (usQualityReport.has_issues ? '数据异常' : '质量通过') : usUnifiedBacktest ? '回测完成' : '待验证',
      detail: usQualityReport
        ? (usQualityReport.has_issues ? `${usQualityReport.total_issues} 个数据问题` : `数据版本 ${usQualityReport.data_version}`)
        : '同步、质量、特征、回测、压力测试',
      tone: usQualityReport ? (usQualityReport.has_issues ? 'bad' : 'good') : usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? 'good' : 'bad') : 'neutral',
    },
    {
      key: 'portfolio',
      label: '组合',
      short: '02',
      status: portfolioOverview.status,
      detail: `${portfolioOverview.strategyCount || 0} 策略 · 风险预算 ${formatPercentValue(portfolioOverview.totalRiskBudget, 1)}`,
      tone: toneFromOverviewStatus(portfolioOverview.status),
    },
    {
      key: 'paper',
      label: '纸交易',
      short: '03',
      status: getPaperStatusLabel(usPaperStatus),
      detail: `${usPaperStatus?.days_traded ?? 0} 天样本 · 对账 ${usPaperStatus?.last_reconciliation_passed === true ? '通过' : usPaperStatus?.last_reconciliation_passed === false ? '失败' : '待确认'}`,
      tone: toneForPaper(usPaperStatus),
    },
    {
      key: 'evidence',
      label: '证据风控',
      short: '04',
      status: systemOverview?.execution.live_state ?? 'frozen',
      detail: systemOverview?.paper_review.summary ?? '等待 manifest、对账报告和人工复核',
      tone: systemOverview?.execution.live_state === 'frozen' ? 'neutral' : toneFromOverviewStatus(systemOverview?.execution.live_state),
    },
  ];

  return (
    <WorkbenchFrame className="ops-dashboard us-equity-workbench">
      <WorkbenchHeader
        code="US"
        eyebrow="US Equity / ETF Research"
        title={selectedStrategy?.display_name ?? '单策略操作台'}
        description="数据 → Signal / Forecast → TargetPosition → RiskDecision → paper evidence；任何缺口都保持 fail-closed。"
        status={`LIVE ${(systemOverview?.execution.live_state ?? 'frozen').toUpperCase()}`}
        statusTone={systemOverview?.execution.live_state === 'frozen' ? 'good' : 'bad'}
        secondaryStatus={systemOverview?.paper_review.entry_allowed ? 'PAPER REVIEW READY' : 'MANUAL GATE'}
        meta={[
          {label: '交易标的', value: usForm.symbol, tone: 'info'},
          {label: '观察窗口', value: `${usForm.startDate} → ${usForm.endDate}`},
          {label: '频率', value: usForm.barSize},
          {label: '策略参数', value: selectedStrategy ? `${Object.keys(selectedStrategy.default_params).length} 项` : '未配置'},
          {label: '小资金上限', value: systemOverview?.small_account.suggested_max_daily_notional ? `$${formatPrice(systemOverview.small_account.suggested_max_daily_notional)}/日` : '待加载'},
          {label: '当前控制面', value: usLoading ? '任务运行中' : opsStages.find(stage => stage.key === activeStage)?.label ?? '总览', tone: usLoading ? 'warn' : 'neutral'},
        ]}
      />

      <WorkbenchTabs
        itemClassName="ops-stage-tab"
        items={opsStages.map(stage => ({
          key: stage.key,
          index: stage.short,
          label: stage.label,
          status: stage.status,
          detail: stage.detail,
          tone: stage.tone as WorkbenchTone,
        }))}
        activeKey={activeStage}
        onChange={(key) => setActiveStage(key as OpsStageKey)}
        ariaLabel="美股量化业务流程"
      />

      {activeStage === 'overview' ? (
        <div className="ops-stage-content">
      <section className="panel" style={{marginBottom: 18}}>
        <div className="panel-header">
          <h3>规划总览</h3>
          <span>{systemOverview?.stage ?? '等待中'}</span>
        </div>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10}}>
          <div className={`metric-card ${planningOverview.qlibInstalled ? 'metric-good' : 'metric-bad'}`}>
            <span>Qlib 依赖</span>
            <strong>{planningOverview.qlibInstalled ? '已安装' : '缺失'}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestQlibLabel} · {planningOverview.latestQlibStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.pypfoptInstalled ? 'metric-good' : 'metric-bad'}`}>
            <span>PyPortfolioOpt 依赖</span>
            <strong>{planningOverview.pypfoptInstalled ? '已安装' : '缺失'}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestPortfolioLabel} · {planningOverview.latestPortfolioStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.rawCoverage !== null ? 'metric-good' : ''}`}>
            <span>真实数据覆盖</span>
            <strong>{planningOverview.rawCoverage !== null ? formatPercentValue(planningOverview.rawCoverage, 1) : '未检查'}</strong>
            <p className="ops-portfolio-detail">
              {planningOverview.coverageStatus}
              {planningOverview.minCoverage !== null ? ` · 最小 ${formatPercentValue(planningOverview.minCoverage, 1)}` : ''}
            </p>
          </div>
          <div
            className={`metric-card ${planningOverview.pitStatus === 'production_pit_data_intake_ready' ? 'metric-good' : 'metric-bad'}`}
            data-testid="us-equity-pit-intake-card"
          >
            <span>生产 PIT 数据</span>
            <strong>{cnStatus(planningOverview.pitStatus)}</strong>
            <p className="ops-portfolio-detail">
              {planningOverview.pitBlockingStage}
              {planningOverview.pitFirstBlocker ? ` · ${planningOverview.pitFirstBlocker}` : ''}
            </p>
          </div>
          <div className={`metric-card ${planningOverview.latestQlibLabel !== '未找到' ? 'metric-good' : ''}`}>
            <span>最新 Qlib 运行</span>
            <strong>{planningOverview.latestQlibLabel}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestQlibStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.latestPortfolioLabel !== '未找到' ? 'metric-good' : ''}`}>
            <span>最新组合运行</span>
            <strong>{planningOverview.latestPortfolioLabel}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestPortfolioStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.conflictDetected ? 'metric-bad' : 'metric-good'}`}>
            <span>纸交易复核冲突</span>
            <strong>{planningOverview.conflictDetected ? '有冲突' : '无冲突'}</strong>
            <p className="ops-portfolio-detail">
              {planningOverview.conflictNotes.length > 0 ? planningOverview.conflictNotes[0] : systemOverview?.paper_review.summary ?? '无冲突诊断'}
            </p>
          </div>
          <div className="metric-card">
            <span>PIT 接入进度</span>
            <strong>{planningOverview.pitPassedStages}/{planningOverview.pitStageCount || 7}</strong>
            <p className="ops-portfolio-detail">{planningOverview.pitAction}</p>
          </div>
        </div>
        {planningOverview.nextActions.length ? (
          <div className="ops-next-actions" style={{marginTop: 12}}>
            {planningOverview.nextActions.map(action => (
              <div key={action} className="ops-next-action">{action}</div>
            ))}
          </div>
        ) : null}
        {planningOverview.pitOperatorActions.length ? (
          <div data-testid="us-equity-pit-operator-actions" style={{marginTop: 12, display: 'grid', gap: 8}}>
            {planningOverview.pitOperatorActions.map(action => (
              <div key={`${action.label}-${action.command}`} className="ops-next-action">
                <strong>{action.label}</strong>
                <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>{action.intent}</p>
                <code style={{display: 'block', whiteSpace: 'normal'}}>{action.command}</code>
                {action.blockedUntil ? <span className="ops-portfolio-detail">等待：{action.blockedUntil}</span> : null}
              </div>
            ))}
          </div>
        ) : null}
        <div data-testid="us-equity-pit-handoff-summary" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>PIT operator handoff: {cnStatus(planningOverview.pitHandoffStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              stage {planningOverview.pitHandoffBlockingStage}
              {planningOverview.pitHandoffBundleId ? ` · bundle ${planningOverview.pitHandoffBundleId}` : ''}
              {planningOverview.pitHandoffIncomingDropDir ? ` · ${planningOverview.pitHandoffIncomingDropDir}` : ''}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              required CSV {planningOverview.pitHandoffRequiredTableCount}
              {planningOverview.pitHandoffMarkdown ? ` · one-page ${planningOverview.pitHandoffMarkdown}` : ''}
            </p>
            {planningOverview.pitHandoffBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.pitHandoffBlockers[0]}</code>
            ) : null}
            {planningOverview.pitHandoffTables.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.pitHandoffTables.map(table => (
                  <div key={table.table} className="metric-card">
                    <span>{table.table}</span>
                    <strong>{table.filename}</strong>
                    <p className="ops-portfolio-detail">{table.fieldCount} fields</p>
                  </div>
                ))}
              </div>
            ) : null}
            {planningOverview.pitHandoffActions.length ? (
              <div style={{display: 'grid', gap: 8, marginTop: 8}}>
                {planningOverview.pitHandoffActions.slice(0, 3).map(action => (
                  <div key={action} className="ops-next-action">
                    <code style={{display: 'block', whiteSpace: 'normal'}}>{action}</code>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-production-data-acquisition" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>生产数据获取：{cnStatus(planningOverview.productionAcquisitionStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              候选证据 {cnStatus(planningOverview.productionCandidateStatus)}
              {' · '}intake {cnStatus(planningOverview.productionIntakeStatus)}
              {' · '}drop package {cnStatus(planningOverview.productionManualPackageStatus)}
              {' · '}bundle {planningOverview.productionDefaultBundleId || '未指定'}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              providers {planningOverview.productionAcceptableProviders.join(', ') || '未列出'}
              {' · '}tables {planningOverview.productionRequiredTableCount}
              {' · '}fields {planningOverview.productionFieldCount}
              {planningOverview.productionIncomingDropDir ? ` · ${planningOverview.productionIncomingDropDir}` : ''}
            </p>
            {planningOverview.productionMissingGroups.length ? (
              <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
                missing {planningOverview.productionMissingGroups.slice(0, 6).join(', ')}
              </p>
            ) : null}
            {planningOverview.productionBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.productionBlockers[0]}</code>
            ) : null}
            {planningOverview.productionRequiredTables.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.productionRequiredTables.slice(0, 4).map(table => (
                  <div key={table.table} className="metric-card">
                    <span>{table.table}</span>
                    <strong>{table.filename}</strong>
                    <p className="ops-portfolio-detail">{table.fieldCount} fields</p>
                  </div>
                ))}
              </div>
            ) : null}
            {planningOverview.productionOperatorSteps.length ? (
              <div style={{display: 'grid', gap: 8, marginTop: 8}}>
                {planningOverview.productionOperatorSteps.slice(0, 2).map(step => (
                  <div key={step.id} className="ops-next-action">
                    <strong>{step.id}</strong>
                    <code style={{display: 'block', whiteSpace: 'normal', marginTop: 4}}>{step.command}</code>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-production-bundle-gate" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>Production bundle gate: {cnStatus(planningOverview.productionBundleGateStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              current {planningOverview.productionBundleCurrentStage || 'none'}
              {' / '}stages {planningOverview.productionBundleStages.length}
            </p>
            {planningOverview.productionBundleBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.productionBundleBlockers[0]}</code>
            ) : null}
            {planningOverview.productionBundleStages.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.productionBundleStages.map(stage => (
                  <div key={stage.id} className={`metric-card ${stage.status.includes('pass') ? 'metric-good' : 'metric-bad'}`}>
                    <span>{stage.id}</span>
                    <strong>{cnStatus(stage.status)}</strong>
                    <p className="ops-portfolio-detail">
                      {stage.firstBlocker || stage.bundleId || stage.sourceDir || 'no blocker'}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
            {planningOverview.productionBundleActions.length ? (
              <div style={{display: 'grid', gap: 8, marginTop: 8}}>
                {planningOverview.productionBundleActions.slice(0, 3).map(action => (
                  <div key={`${action.stage}-${action.id}`} className="ops-next-action">
                    <strong>{action.stage || action.id}</strong>
                    <code style={{display: 'block', whiteSpace: 'normal', marginTop: 4}}>{action.command}</code>
                    {action.blockedUntil ? (
                      <p className="ops-portfolio-detail" style={{margin: '4px 0 0'}}>until {action.blockedUntil}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-data-lineage-governance" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>数据链路治理：{cnStatus(planningOverview.dataLineageStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              对账 {cnStatus(planningOverview.dataReconciliationStatus)}
              {' · '}修复 {cnStatus(planningOverview.dataRemediationStatus)}
              {' · '}宏观滞后 {cnStatus(planningOverview.macroLagStatus)}
              {' · '}promotion evidence {planningOverview.acceptedEvidenceForPromotion ? 'accepted' : 'blocked'}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              price {planningOverview.selectedPriceSource || '未选择'}
              {planningOverview.selectedPriceRoot ? ` · ${planningOverview.selectedPriceRoot}` : ''}
              {' · '}lineage {planningOverview.lineageMaturity || 'unknown'}
              {' · '}tasks {planningOverview.remediationTaskCount}
              {planningOverview.macroSource ? ` · macro ${planningOverview.macroSource}` : ''}
            </p>
            {planningOverview.dataLineageBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.dataLineageBlockers[0]}</code>
            ) : null}
            {planningOverview.remediationGroups.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.remediationGroups.map(group => (
                  <div key={group.id} className={`metric-card ${group.blockerCount ? 'metric-bad' : ''}`}>
                    <span>{group.id}</span>
                    <strong>{cnStatus(group.status)}</strong>
                    <p className="ops-portfolio-detail">{group.blockerCount ? `${group.blockerCount} 个阻塞` : '无阻塞'}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-development-plan-audit" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>开发路线审计：{cnStatus(planningOverview.developmentStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              完成 {planningOverview.developmentCompleteCount}/{planningOverview.developmentPhaseCount || '-'}
              {' · '}阻塞 {planningOverview.developmentBlockedCount}
              {' · '}观察 {planningOverview.developmentObservingCount}
            </p>
            {planningOverview.developmentPhases.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.developmentPhases.map(phase => (
                  <div key={phase.id} className={`metric-card ${phase.status.includes('complete') ? 'metric-good' : phase.status.includes('blocked') ? 'metric-bad' : ''}`}>
                    <span>{phase.title}</span>
                    <strong>{cnStatus(phase.status)}</strong>
                    <p className="ops-portfolio-detail">
                      {phase.blockedCount ? `${phase.blockedCount} 个阻塞` : '无阻塞'}
                      {phase.blockers[0] ? ` · ${phase.blockers[0]}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-daily-production-line" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>日更生产线：{cnStatus(planningOverview.dailyProductionStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.dailyProductionDecision || '等待日更生产线运行报告'}
              {planningOverview.dailyProductionGeneratedAt ? ` · ${planningOverview.dailyProductionGeneratedAt}` : ''}
              {' · '}steps {planningOverview.dailyPassedStepCount}/{planningOverview.dailyStepCount || '-'}
              {planningOverview.dailyFailedStepCount ? ` · failed ${planningOverview.dailyFailedStepCount}` : ''}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              PIT required {planningOverview.dailyProductionPitRequired ? 'yes' : 'no'}
              {planningOverview.dailyProductionLineStatus ? ` · ${planningOverview.dailyProductionLineStatus}` : ''}
              {planningOverview.dailyDevelopmentPlanStatus ? ` · ${planningOverview.dailyDevelopmentPlanStatus}` : ''}
              {planningOverview.dailyForwardHealthStatus ? ` · forward ${planningOverview.dailyForwardHealthStatus}` : ''}
              {' · '}obs {planningOverview.dailyForwardObservationDays}/{planningOverview.dailyForwardMinimumDays}
              {' · '}data gate {cnStatus(planningOverview.dailyForwardDataGateStatus)}
            </p>
            {planningOverview.dailyForwardDataGateBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.dailyForwardDataGateBlockers[0]}</code>
            ) : null}
            {planningOverview.dailyForwardDataGateChecks.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.dailyForwardDataGateChecks.map(check => (
                  <div key={check.id} className={`metric-card ${check.passed ? 'metric-good' : 'metric-bad'}`}>
                    <span>{check.id}</span>
                    <strong>{cnStatus(check.status)}</strong>
                    <p className="ops-portfolio-detail">{check.firstBlocker || 'pass'}</p>
                  </div>
                ))}
              </div>
            ) : null}
            {planningOverview.dailyBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.dailyBlockers[0]}</code>
            ) : null}
            {planningOverview.dailyUnsafeFlags[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.dailyUnsafeFlags[0]}</code>
            ) : null}
            {planningOverview.dailySteps.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.dailySteps.map(step => (
                  <div key={step.id} className={`metric-card ${step.passed ? 'metric-good' : 'metric-bad'}`}>
                    <span>{step.id}</span>
                    <strong>{cnStatus(step.status)}</strong>
                    <p className="ops-portfolio-detail">{step.firstBlocker || '无阻塞'}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-strategy-registry-summary" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>策略池注册表：{cnStatus(planningOverview.registryStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              策略 {planningOverview.registryStrategyCount}
              {' · '}主候选 {planningOverview.registryPrimaryStrategyId || '未指定'}
              {planningOverview.registryPrimaryStage ? ` · ${planningOverview.registryPrimaryStage}` : ''}
              {planningOverview.registryPrimaryStatus ? ` · ${planningOverview.registryPrimaryStatus}` : ''}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              forward {planningOverview.registryForwardCount}
              {' · '}hypothesis {planningOverview.registryHypothesisCount || planningOverview.registryHypothesisStatusCount}
              {' · '}families {planningOverview.registryFamilies.length}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              audit {cnStatus(planningOverview.registryAuditStatus)}
              {' / '}formal {planningOverview.registryAuditFormalCount}
              {' / '}primary {planningOverview.registryAuditPrimaryCount}
              {' / '}required families {planningOverview.registryAuditRequiredFamilies.length || '-'}
            </p>
            {planningOverview.registryAuditMissingFamilies.length ? (
              <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
                missing families {planningOverview.registryAuditMissingFamilies.slice(0, 6).join(', ')}
              </p>
            ) : null}
            {planningOverview.registryBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.registryBlockers[0]}</code>
            ) : null}
            {planningOverview.registryAuditBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.registryAuditBlockers[0]}</code>
            ) : null}
            {planningOverview.registryStrategies.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.registryStrategies.map(strategy => (
                  <div key={strategy.id} className={`metric-card ${strategy.primary ? 'metric-good' : ''}`}>
                    <span>{strategy.primary ? '主候选' : strategy.family}</span>
                    <strong>{strategy.id}</strong>
                    <p className="ops-portfolio-detail">
                      {strategy.stage}
                      {' · '}{strategy.status}
                      {' · '}paper {strategy.paperReady ? 'ready' : 'locked'}
                      {' · '}live {strategy.liveReady ? 'ready' : 'locked'}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-live-readiness-summary" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>实盘前门禁：{cnStatus(planningOverview.liveReadinessStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.liveReadinessDecision || '等待 live readiness 报告'}
              {' · '}账户 ${planningOverview.accountCapitalUsd?.toLocaleString() ?? '未设置'}
              {' · '}最大实盘 ${planningOverview.maxLivePrincipalUsd?.toLocaleString() ?? '未设置'}
              {' · '}下单 {planningOverview.liveOrderAllowed ? '允许' : '锁定'}
            </p>
            {planningOverview.liveReadinessBlockers.length ? (
              <div style={{display: 'grid', gap: 6, marginTop: 8}}>
                {planningOverview.liveReadinessBlockers.slice(0, 5).map(blocker => (
                  <code key={blocker} style={{display: 'block', whiteSpace: 'normal'}}>{blocker}</code>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-strategy-validation-gate" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>策略验证门槛：{cnStatus(planningOverview.strategyValidationStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.strategyValidationDecision || '等待策略验证报告'}
              {planningOverview.strategyValidationVariant ? ` · ${planningOverview.strategyValidationVariant}` : ''}
            </p>
            {planningOverview.strategyValidationBlockers.length ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.strategyValidationBlockers[0]}</code>
            ) : null}
            {planningOverview.strategyValidationChecks.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.strategyValidationChecks.map(check => (
                  <div key={check.id} className={`metric-card ${check.passed ? 'metric-good' : 'metric-bad'}`}>
                    <span>{check.id}</span>
                    <strong>{check.passed ? 'PASS' : 'BLOCKED'}</strong>
                    <p className="ops-portfolio-detail">{check.firstBlocker || '无阻塞'}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-forward-observation-summary" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>Forward Observation：{cnStatus(planningOverview.forwardStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              健康 {cnStatus(planningOverview.forwardHealthStatus)}
              {' · '}进度 {planningOverview.forwardObservationDays}/{planningOverview.forwardMinimumDays} 日
              {planningOverview.forwardLatestDate ? ` · 最新 ${planningOverview.forwardLatestDate}` : ''}
            </p>
            {planningOverview.forwardBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.forwardBlockers[0]}</code>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-manual-review-packet" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>人工审阅包：{cnStatus(planningOverview.manualReviewStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.manualReviewDecision || '等待人工审阅包'}
              {' · '}证据 {planningOverview.manualChecklistPassed}/{planningOverview.manualChecklistCount}
              {' · '}签名 {planningOverview.manualRecordedSignoffs}/{planningOverview.manualRequiredSignoffs}
            </p>
            {planningOverview.manualReviewBlockers.length ? (
              <div style={{display: 'grid', gap: 6, marginTop: 8}}>
                {planningOverview.manualReviewBlockers.slice(0, 4).map(blocker => (
                  <code key={blocker} style={{display: 'block', whiteSpace: 'normal'}}>{blocker}</code>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-small-account-preflight" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>小账户执行预检：{cnStatus(planningOverview.smallAccountPreflightStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              账户 ${planningOverview.smallAccountEquity.toLocaleString()}
              {' · '}场景 {planningOverview.smallPassedScenarioCount}/{planningOverview.smallScenarioCount || '-'}
              {' · '}滑点 {planningOverview.smallSlippageBps}bps
              {' · '}融资 {formatPercentValue(planningOverview.smallAnnualFinancingRate, 1)}
              {planningOverview.smallAccountTimestamp ? ` · ${planningOverview.smallAccountTimestamp}` : ''}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              目标 gross {planningOverview.smallTargetGross !== null ? planningOverview.smallTargetGross.toFixed(2) : '-'}
              {' · '}symbols {planningOverview.smallTargetSymbols.slice(0, 5).join(', ') || '未生成'}
            </p>
            {planningOverview.smallAccountBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.smallAccountBlockers[0]}</code>
            ) : null}
            {planningOverview.smallAccountScenarios.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.smallAccountScenarios.map(scenario => (
                  <div key={scenario.id} className={`metric-card ${scenario.passed ? 'metric-good' : 'metric-bad'}`}>
                    <span>{scenario.id}</span>
                    <strong>{scenario.passed ? 'PASS' : 'BLOCKED'}</strong>
                    <p className="ops-portfolio-detail">
                      cap {scenario.grossCap.toFixed(2)}x
                      {' · '}margin {scenario.allowMargin ? 'yes' : 'no'}
                      {' · '}cash ${Math.round(scenario.wholeCash).toLocaleString()}
                      {scenario.firstBlocker ? ` · ${scenario.firstBlocker}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-paper-simulation-readiness" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>纸面模拟门禁：{cnStatus(planningOverview.paperSimulationStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.paperSimulationDecision || '等待纸面模拟门禁报告'}
              {' · '}runner {planningOverview.paperRunnerAllowed ? 'allowed' : 'locked'}
              {planningOverview.paperLedgerRoot ? ` · ${planningOverview.paperLedgerRoot}` : ''}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              independent root {planningOverview.paperContractIndependentRoot || '未声明'}
              {' · '}no forward reuse {planningOverview.paperContractNoForwardReuse ? 'yes' : 'no'}
              {' · '}orders {planningOverview.paperContractNoOrders ? 'locked' : 'unsafe'}
            </p>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              forward data gate {planningOverview.paperForwardDataGateClean ? 'clean' : 'blocked'}
              {' · '}blocked runs {planningOverview.paperForwardDataGateBlockedCount}
              {planningOverview.paperProductionPitIntakeSource ? ` · PIT ${planningOverview.paperProductionPitIntakeSource}` : ''}
            </p>
            {planningOverview.paperSimulationBlockers.length ? (
              <div style={{display: 'grid', gap: 6, marginTop: 8}}>
                {planningOverview.paperSimulationBlockers.slice(0, 4).map(blocker => (
                  <code key={blocker} style={{display: 'block', whiteSpace: 'normal'}}>{blocker}</code>
                ))}
              </div>
            ) : null}
            {planningOverview.paperSimulationUnsafeFlags[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.paperSimulationUnsafeFlags[0]}</code>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-standard-schema-audit" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>标准报告 Schema：{cnStatus(planningOverview.schemaAuditStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.schemaAuditDecision || '等待 schema 审计'}
              {' · '}字段 {planningOverview.schemaPassedFields}/{planningOverview.schemaRequiredFields || '-'}
              {' · '}缺输入 {planningOverview.schemaMissingInputs}
              {' · '}unsafe {planningOverview.schemaUnsafeFlags}
            </p>
            {planningOverview.schemaBlockers[0] ? (
              <code style={{display: 'block', whiteSpace: 'normal'}}>{planningOverview.schemaBlockers[0]}</code>
            ) : null}
            {planningOverview.schemaFieldChecks.length ? (
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginTop: 8}}>
                {planningOverview.schemaFieldChecks.map(field => (
                  <div key={field.id} className={`metric-card ${field.passed ? 'metric-good' : 'metric-bad'}`}>
                    <span>{field.id}</span>
                    <strong>{field.passed ? 'PASS' : 'MISSING'}</strong>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-monitoring-rules" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>监控/归因/停用规则：{cnStatus(planningOverview.monitoringStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              监控 {planningOverview.monitorCount}
              {' · '}paper/live 前置 {planningOverview.monitoringRequiredBeforePaper ? '是' : '否'}
              {' · '}规则域 {planningOverview.monitoringSections.length}
            </p>
            {planningOverview.monitoringMinimum.length ? (
              <div style={{display: 'grid', gap: 6, marginTop: 8}}>
                {planningOverview.monitoringMinimum.slice(0, 4).map(item => (
                  <code key={item} style={{display: 'block', whiteSpace: 'normal'}}>{item}</code>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div data-testid="us-equity-replay-readiness" style={{marginTop: 12}}>
          <div className="ops-next-action">
            <strong>Replay 预检：{cnStatus(planningOverview.replayStatus)}</strong>
            <p className="ops-portfolio-detail" style={{margin: '4px 0'}}>
              {planningOverview.replayDecision || '等待 replay 预检'}
              {planningOverview.replayTimestamp ? ` · ${planningOverview.replayTimestamp}` : ''}
              {' · '}fills {planningOverview.replayFillCount}
              {' · '}checks {planningOverview.replayPassedChecks}/{planningOverview.replayCheckCount}
            </p>
          </div>
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 12}}>
          {planningOverview.recommendedActions.map(action => (
            <button key={action.label} type="button" className="secondary-button" disabled={action.disabled} onClick={action.onClick}>
              {action.label}
            </button>
          ))}
        </div>
      </section>

      <section className="panel" style={{marginBottom: 18}}>
        <div className="panel-header">
          <h3>状态卡</h3>
          <span>美股 / 纸交易复核 / 实盘冻结</span>
        </div>
        <div className="state-board">
          {statusCards.map(card => (
            <ModuleStateCard
              key={card.id}
              id={card.id}
              title={card.title}
              status={card.status}
              tone={card.tone}
              reason={card.reason}
              actions={card.actions}
              meta={card.meta}
              hint={card.hint}
            />
          ))}
        </div>
      </section>

      <section className="panel mvp-panel">
        <div className="panel-header">
          <h3>晋升路径</h3>
              <span>{usLoading ? <LoadingSpinner text="运行中" /> : '单策略流程'}</span>
        </div>
        <div className="mvp-step-grid">
          {workflowSteps.map((step, index) => (
            <div key={step.id} className={mvpStepClass(step.status)}>
              <span>{index + 1}</span>
              <strong>{step.label}</strong>
              <p>{step.detail}</p>
            </div>
          ))}
        </div>
      </section>

        </div>
      ) : null}

      {activeStage !== 'overview' ? (
      <section className="ops-grid">
        <div className="ops-main">
          {activeStage === 'evidence' ? (
            <>
              <USEquityDomainReadModelView />
              <div className="ops-next-action" data-view-zone="legacy-research-operations">
                <strong>历史研究操作台</strong>
                <p className="ops-portfolio-detail">
                  以下区域保留研究与人工复核入口；上方当前 HEAD 证据视图只读且不会触发同步、回测、paper run 或 reset。
                </p>
              </div>
            </>
          ) : null}
          {(activeStage === 'research' || activeStage === 'evidence') ? (
          <section className="panel ops-gates-panel">
            <div className="panel-header">
              <h3>系统与门禁摘要</h3>
              <span>{health?.status ?? '未知'}</span>
            </div>
            <div className="ops-gates-grid">
              {gateCards.map(card => (
                <article key={card.id} className={`ops-gate-card ops-gate-${card.tone}`}>
                  <div className="ops-gate-header">
                    <span>{card.title}</span>
                    <StatusBadge status={card.status} label={card.title} tone={card.tone} />
                  </div>
                  <p>{card.detail}</p>
                </article>
              ))}
            </div>
            {systemOverview?.next_actions.length ? (
              <div className="ops-next-actions">
                {systemOverview.next_actions.map(action => (
                  <div key={action} className="ops-next-action">{action}</div>
                ))}
              </div>
            ) : null}
          </section>
          ) : null}

          {activeStage === 'portfolio' ? (
          <section className="panel ops-portfolio-panel">
            <div className="panel-header">
              <h3>多策略组合总览</h3>
              <span>{portfolioOverview.profile}</span>
            </div>
            <div className="ops-portfolio-summary-grid">
              <div className={`metric-card ${toneFromOverviewStatus(portfolioOverview.status) === 'good' ? 'metric-good' : toneFromOverviewStatus(portfolioOverview.status) === 'bad' ? 'metric-bad' : ''}`}>
                <span>组合状态</span>
                <strong>{portfolioOverview.status}</strong>
              </div>
              <div className="metric-card">
                <span>策略数</span>
                <strong>{portfolioOverview.strategyCount || '-'}</strong>
              </div>
              <div className={`metric-card ${portfolioOverview.totalRiskBudget !== null ? 'metric-good' : ''}`}>
                <span>风险预算</span>
                <strong>{formatPercentValue(portfolioOverview.totalRiskBudget, 1)}</strong>
              </div>
              <div className={`metric-card ${portfolioOverview.totalPnL !== null ? (portfolioOverview.totalPnL >= 0 ? 'metric-good' : 'metric-bad') : ''}`}>
                <span>盈亏归因</span>
                <strong>{formatSignedPrice(portfolioOverview.totalPnL)}</strong>
              </div>
            </div>
            <p className="ops-portfolio-detail">{portfolioOverview.detail}</p>

            <div className="ops-portfolio-grid">
              <section className="ops-subsection">
                <div className="ops-subsection-header">
                  <strong>策略权重</strong>
                  <span>{portfolioOverview.strategyRows.length > 0 ? `${portfolioOverview.strategyRows.length} 行` : '占位'}</span>
                </div>
                <div className="ops-section-list">
                  {portfolioOverview.strategyRows.length > 0 ? portfolioOverview.strategyRows.map(row => (
                    <div key={row.key} className={`ops-section-row ops-row-${row.tone}`}>
                      <div>
                        <strong>{row.label}</strong>
                        <p>{row.detail}</p>
                      </div>
                      <span>{row.value}</span>
                    </div>
                  )) : (
                    <div className="ops-empty-state">
                      <strong>未返回多策略权重字段</strong>
                      <p>兼容路径已启用，等待 `/api/system/overview` 提供 `strategy_weights` / `allocations` / `strategies`。</p>
                    </div>
                  )}
                </div>
              </section>

              <section className="ops-subsection">
                <div className="ops-subsection-header">
                  <strong>组合门禁</strong>
                  <span>纸交易 / 复核 / 实盘</span>
                </div>
                <div className="ops-section-list">
                  {portfolioOverview.gateSummaries.map(gate => (
                    <div key={gate.key} className={`ops-section-row ops-row-${gate.tone}`}>
                      <div>
                        <strong>{gate.label}</strong>
                        <p>{gate.detail}</p>
                      </div>
                      <StatusBadge status={gate.status} label={gate.label} tone={gate.tone} />
                    </div>
                  ))}
                </div>
              </section>
            </div>

            <div className="ops-portfolio-grid">
              <section className="ops-subsection">
                <div className="ops-subsection-header">
                  <strong>风险预算占位</strong>
                  <span>降级显示</span>
                </div>
                <div className="ops-budget-grid">
                  {portfolioOverview.budgetItems.map(item => (
                    <div key={item.key} className="ops-budget-card">
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                      <p>{item.detail}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="ops-subsection">
                <div className="ops-subsection-header">
                  <strong>盈亏归因</strong>
                  <span>{portfolioOverview.pnlRows.length > 0 ? `${portfolioOverview.pnlRows.length} 行` : '占位'}</span>
                </div>
                <div className="ops-section-list">
                  {portfolioOverview.pnlRows.length > 0 ? portfolioOverview.pnlRows.map(row => (
                    <div key={row.key} className={`ops-section-row ops-row-${row.tone}`}>
                      <div>
                        <strong>{row.label}</strong>
                        <p>{row.detail}</p>
                      </div>
                      <span>{row.value}</span>
                    </div>
                  )) : (
                    <div className="ops-empty-state">
                      <strong>暂无归因明细</strong>
                      <p>当前显示占位。API 若提供 `pnl_attribution` / `attribution` / `pnl_breakdown`，此处会自动渲染。</p>
                    </div>
                  )}
                </div>
              </section>
            </div>
          </section>
          ) : null}

          {(activeStage === 'research' || activeStage === 'paper') ? (
          <section className="panel ops-actions-panel">
            <div className="panel-header">
              <h3>工作流操作</h3>
              <span>{usMessage || '按门禁顺序推进'}</span>
            </div>
            <div className="form-grid us-form-grid">
              <label>标的
                <input value={usForm.symbol} onChange={(e: ValueEvent) => setUSForm({...usForm, symbol: e.target.value.toUpperCase()})} />
              </label>
              <label>周期
                <select value={usForm.barSize} onChange={(e: ValueEvent) => setUSForm({...usForm, barSize: e.target.value as USEquityFormState['barSize']})}>
                  {['1d', '1h', '30m', '15m', '5m', '2m', '1m'].map(barSize => <option key={barSize} value={barSize}>{barSize}</option>)}
                </select>
              </label>
              <label>开始日期
                <input type="date" value={usForm.startDate} onChange={(e: ValueEvent) => setUSForm({...usForm, startDate: e.target.value})} />
              </label>
              <label>结束日期
                <input type="date" value={usForm.endDate} onChange={(e: ValueEvent) => setUSForm({...usForm, endDate: e.target.value})} />
              </label>
              <label>策略
                <select value={usForm.strategyId} onChange={(e: ValueEvent) => setUSForm({...usForm, strategyId: e.target.value})}>
                  {strategies.map(strategy => <option key={strategy.id} value={strategy.id}>{strategy.display_name}</option>)}
                </select>
              </label>
              <label>账本目录
                <input value={usForm.ledgerDir} onChange={(e: ValueEvent) => setUSForm({...usForm, ledgerDir: e.target.value})} />
              </label>
              <label className="wide-grid-field">数据根目录
                <input value={usForm.dataRoot} onChange={(e: ValueEvent) => setUSForm({...usForm, dataRoot: e.target.value})} />
              </label>
            </div>

            <div className="ops-action-groups">
              {activeStage === 'research' ? (
              <div className="ops-action-group">
                <div className="ops-action-group-header">
                  <strong>研究门禁</strong>
                  <span>数据版本、回测证据、晋升门</span>
                </div>
                <div className="ops-button-grid">
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSDataSync}>同步数据</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSQualityReport}>数据质量</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBuildFeatures}>构建特征</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBacktest}>事件回测</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSUnifiedBacktest}>统一回测</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSCostStressED}>成本压力</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSWalkForward}>滚动验证</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPromotionGate}>晋升门</button>
                </div>
              </div>
              ) : null}

              {activeStage === 'paper' ? (
              <div className="ops-action-group">
                <div className="ops-action-group-header">
                  <strong>纸交易门禁</strong>
                  <span>先对账，再留样本，再人工审批</span>
                </div>
                <div className="ops-button-grid">
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperRunDay}>运行纸交易日</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperBacktest}>纸交易回放</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSReconcile}>运行对账</button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={usLoading || !systemOverview?.paper_review.creation?.creation_allowed || !systemOverview?.paper_review.creation?.preferred_manifest_id}
                    onClick={() => {
                      void handleUSCreatePaperReview({
                        strategy_manifest_id: systemOverview?.paper_review.creation?.preferred_manifest_id,
                        candidate_id: systemOverview?.paper_review.creation?.preferred_candidate_id,
                      });
                    }}
                  >
                    创建复核证据
                  </button>
                  <button type="button" className="secondary-button danger" disabled={usLoading} onClick={handleUSPaperReset}>重置纸交易</button>
                </div>
              </div>
              ) : null}
            </div>
          </section>
          ) : null}

          {activeStage === 'paper' ? (
          <section className="panel ops-metrics-panel">
            <div className="panel-header">
              <h3>纸交易与风险摘要</h3>
              <span>{usPaperDailyResults.length > 0 ? `最近 ${usPaperDailyResults.length} 天` : '暂无样本'}</span>
            </div>
            <div className="ops-metric-grid">
              <div className="metric-card">
                <span>纸交易权益</span>
                <strong>{usPaperStatus ? formatPrice(usPaperStatus.equity) : '-'}</strong>
              </div>
              <div className={`metric-card ${paperPnL >= 0 ? 'metric-good' : 'metric-bad'}`}>
                <span>累计盈亏</span>
                <strong>{usPaperDailyResults.length > 0 ? formatPrice(paperPnL) : '-'}</strong>
              </div>
              <div className="metric-card">
                <span>成交率</span>
                <strong>{paperOrdersSubmitted > 0 ? `${((paperOrdersFilled / paperOrdersSubmitted) * 100).toFixed(0)}%` : '-'}</strong>
              </div>
              <div className={`metric-card ${usPaperStatus?.kill_switch_triggered ? 'metric-bad' : 'metric-good'}`}>
                <span>熔断开关</span>
                <strong>{usPaperStatus?.kill_switch_triggered ? '已触发' : '正常'}</strong>
              </div>
            </div>
            <div className="ops-risk-grid">
              <div className="ops-risk-card">
                <span>对账通过率</span>
                <strong>{usPaperDailyResults.length > 0 ? `${paperReconPasses}/${usPaperDailyResults.length}` : '-'}</strong>
                <p>{usPaperStatus?.last_reconciliation_passed === false ? '最近一次对账失败，禁止推进 live。' : '需要连续留存 paper 对账证据。'}</p>
              </div>
              <div className="ops-risk-card">
                <span>账本一致性</span>
                <strong>{usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? '通过' : '失败') : '-'}</strong>
                <p>{usUnifiedBacktest?.equity_consistency_msg ?? '统一回测尚未出具账本一致性结论。'}</p>
              </div>
              <div className="ops-risk-card">
                <span>晋升约束</span>
                <strong>{promotionGateResult ? promotionGateResult.next_stage : '研究'}</strong>
                <p>{systemOverview?.paper_review.summary ?? (promotionGateResult ? `决策 ${promotionGateResult.decision.toUpperCase()}，仍需人工门禁。` : '未出具晋升 manifest。')}</p>
              </div>
            </div>
            {paperEquityCurve.length > 1 ? (
              <div className="ops-chart-wrap">
                <LineChart title="纸交易权益曲线" points={paperEquityCurve} accentClass="line-accent" />
              </div>
            ) : null}
            {recentPaperRuns.length > 0 ? (
              <div className="paper-results-table">
                {recentPaperRuns.map(day => (
                  <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                    <span>{day.date}</span>
                    <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>{formatPrice(day.daily_pnl)}</span>
                    <span>{day.orders_filled}/{day.orders_submitted} 成交</span>
                    <span className={`status-tag ${day.reconciliation_passed ? 'good' : 'bad'}`}>
                      {day.reconciliation_passed ? '对账通过' : '对账失败'}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
          ) : null}
        </div>

        <aside className="ops-rail">
          <section className="panel ops-evidence-panel">
            <div className="panel-header">
              <h3>账本 / 证据入口</h3>
              <span>实盘审批前必查</span>
            </div>
            <div className="ops-evidence-list">
              {evidenceEntries.map(entry => (
                <div key={entry.label} className="ops-evidence-row">
                  <span>{entry.label}</span>
                  <strong className={entry.muted ? 'text-muted' : ''}>{entry.value}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="panel ops-evidence-panel">
            <div className="panel-header">
              <h3>回测证据</h3>
              <span>{usUnifiedBacktest ? usUnifiedBacktest.status : '未运行'}</span>
            </div>
            <div className="ops-evidence-list">
              <div className="ops-evidence-row">
                <span>总收益</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.total_return_pct, 2, '%')}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>Sharpe</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.sharpe_ratio)}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>最大回撤</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.max_drawdown_pct, 2, '%')}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>成交 / 事件</span>
                <strong>{usUnifiedBacktest ? `${usUnifiedBacktest.fill_count} / ${usUnifiedBacktest.event_count}` : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>纸交易验证</span>
                <strong>{systemOverview?.paper_validation.state ?? '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>干净天数</span>
                <strong>{systemOverview ? `${systemOverview.paper_validation.days_completed ?? 0}/${systemOverview.paper_validation.days_required ?? 0}` : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>注册表状态</span>
                <strong>{systemOverview?.registry.state ?? '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>账本期末权益</span>
                <strong>{usUnifiedBacktest ? formatPrice(usUnifiedBacktest.ledger_final_equity) : '-'}</strong>
              </div>
            </div>
          </section>

          <section className="panel ops-evidence-panel">
            <div className="panel-header">
              <h3>风控摘要</h3>
              <span>{usReconcile?.status ?? '待生成'}</span>
            </div>
            <div className="ops-evidence-list">
              <div className="ops-evidence-row">
                <span>新单状态</span>
                <strong className={usReconcile?.halt_new_orders || systemOverview?.execution.live_state === 'frozen' ? 'status-err' : ''}>{usReconcile?.halt_new_orders ? '已暂停' : systemOverview?.execution.live_state === 'frozen' ? '实盘冻结' : '开放'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>差异数</span>
                <strong>{usReconcile ? String(usReconcile.break_count) : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>现金差异</span>
                <strong>{typeof usReconcile?.cash_diff === 'number' ? formatPrice(usReconcile.cash_diff) : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>已告警</span>
                <strong>{usReconcile?.alert_sent ? '是' : '否'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>审计阻塞</span>
                <strong className="text-muted">{systemOverview?.paper_validation.audit_blocker_status ?? '未知'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>熔断原因</span>
                <strong className="text-muted">{usPaperStatus?.kill_switch_reason ?? systemOverview?.execution.live_block_reason ?? '无'}</strong>
              </div>
            </div>
          </section>

          {promotionGateResult ? (
            <section className="panel ops-evidence-panel">
              <div className="panel-header">
                <h3>晋升门细项</h3>
                <StatusBadge status={promotionGateResult.decision.toUpperCase()} label="promotion" tone={promotionGateResult.decision === 'pass' ? 'good' : promotionGateResult.decision === 'warn' ? 'neutral' : 'bad'} />
              </div>
              <div className="promotion-gate-list">
                {promotionGateResult.gates.map(gate => (
                  <div key={gate.name} className={`promotion-gate-row promotion-${gate.status}`}>
                    <span>{gate.status.toUpperCase()}</span>
                    <strong>{gate.name}</strong>
                    <p>{gate.message}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </aside>
      </section>
      ) : null}
    </WorkbenchFrame>
  );
}
