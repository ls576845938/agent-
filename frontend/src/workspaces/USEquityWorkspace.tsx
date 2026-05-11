import {useEffect, useMemo, useState} from 'react';

import LineChart from '../components/LineChart';
import {ModuleStateCard, type ModuleStateCardProps} from '../components/ModuleStateCard';
import StatusBadge from '../components/StatusBadge';
import {LoadingSpinner} from '../components/LoadingSpinner';
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
    {label: 'strategy_version', value: promotionGateResult?.strategy_version ?? selectedStrategy?.display_name ?? usForm.strategyId},
    {label: 'data_version', value: usQualityReport?.data_version ?? promotionGateResult?.experiment_record.data_version ?? '未生成', muted: !usQualityReport && !promotionGateResult?.experiment_record.data_version},
    {label: 'manifest', value: systemOverview?.paper_review.manifest_path ?? promotionGateResult?.manifest_path ?? '未出具', muted: !systemOverview?.paper_review.manifest_path && !promotionGateResult?.manifest_path},
    {label: 'experiment', value: promotionGateResult?.experiment_record.experiment_id ?? '未记录', muted: !promotionGateResult?.experiment_record.experiment_id},
    {label: 'registry', value: systemOverview?.registry.path ?? `${usForm.dataRoot}/research/evidence_registry.json`},
    {label: 'paper_review', value: systemOverview?.paper_review.review_path ?? '未生成', muted: !systemOverview?.paper_review.review_path},
    {label: 'evidence_pack', value: systemOverview?.paper_review.evidence_pack_path ?? '未生成', muted: !systemOverview?.paper_review.evidence_pack_path},
    {label: 'ledger', value: usForm.ledgerDir},
    {label: 'reconcile report', value: usReconcile?.report_path ?? '未生成', muted: !usReconcile?.report_path},
  ];

  const planningOverview = useMemo(() => {
    const overviewRoot = systemOverview as unknown as LooseRecord | null;
    const integrationsRoot = readRecord(overviewRoot, 'integrations');
    const dependencyRoot = readRecord(integrationsRoot, 'dependencies');
    const qlibRoot = readRecord(integrationsRoot, 'qlib');
    const portfolioRoot = readRecord(integrationsRoot, 'portfolio');
    const coverageRoot = readRecord(overviewRoot, 'data_coverage');
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
    const latestQlibStatus = readString(qlibLatestRun, 'workflow_status', 'dataset_status', 'manifest_status', 'status') ?? readString(qlibRoot, 'status') ?? 'missing';
    const latestPortfolioLabel = readString(portfolioLatestRun, 'portfolio_run_id') ?? readString(portfolioRoot, 'latest_run_id') ?? '未找到';
    const latestPortfolioStatus = readString(portfolioLatestRun, 'optimizer', 'status') ?? readString(portfolioRoot, 'status') ?? 'missing';
    const conflictDetected = readBoolean(diagnosticsRoot, 'conflict_detected') ?? false;
    const conflictNotes = readArray(diagnosticsRoot, 'conflict_notes');
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
        hint: '数据同步、特征、回测、成本压力、walk-forward、晋升门',
        meta: [
          {label: '策略', value: selectedStrategy?.display_name ?? usForm.strategyId},
          {label: '阶段', value: systemOverview?.stage ?? 'waiting'},
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
        title: 'paper review',
        status: paperOutcome,
        tone: paperOutcome === 'PASS' ? 'good' : 'bad',
        reason: systemOverview?.paper_review.summary ?? '未进入 paper review。',
        hint: 'manifest、evidence pack、人工 review 入口',
        meta: [
          {label: 'manifest', value: systemOverview?.paper_review.manifest_path ?? 'missing'},
          {label: 'evidence', value: systemOverview?.paper_review.evidence_pack_path ?? 'missing'},
        ],
        actions: [{
          label: '运行 Paper 日',
          onClick: () => { void handleUSPaperRunDay(); },
          disabled: usLoading,
          variant: 'primary',
        }],
      },
      {
        id: 'live-freeze',
        title: 'live freeze',
        status: liveOutcome,
        tone: liveOutcome === 'PASS' ? 'good' : 'bad',
        reason: systemOverview?.execution.live_block_reason ?? 'live runtime frozen',
        hint: '冻结是默认状态，只有证据闭环完成后才允许审批',
        meta: [
          {label: 'live state', value: systemOverview?.execution.live_state ?? 'frozen'},
          {label: 'submit', value: systemOverview?.execution.paper_network_submit_confirmation ? 'confirmed' : 'locked'},
        ],
        actions: [{
          label: '刷新冻结状态',
          onClick: () => { void handleUSPaperStatus(); },
          disabled: usLoading,
        }],
      },
    ] satisfies ModuleStateCardProps[];
  }, [handleUSPaperRunDay, handleUSPaperStatus, handleUSPromotionGate, promotionGateResult, selectedStrategy?.display_name, systemOverview?.execution.live_block_reason, systemOverview?.execution.live_state, systemOverview?.execution.paper_network_submit_confirmation, systemOverview?.paper_review.evidence_pack_path, systemOverview?.paper_review.entry_allowed, systemOverview?.paper_review.manifest_path, systemOverview?.paper_review.summary, systemOverview?.stage, usForm.strategyId, usLoading]);

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
        label: 'Gross Exposure',
        value: formatPercentValue(grossExposure, 1),
        detail: grossExposure !== null ? '组合总曝险' : 'API 未提供 gross exposure 字段',
      },
      {
        key: 'net',
        label: 'Net Exposure',
        value: formatPercentValue(netExposure, 1),
        detail: netExposure !== null ? '净曝险' : 'API 未提供 net exposure 字段',
      },
      {
        key: 'risk-budget',
        label: 'Risk Budget',
        value: formatPercentValue(totalRiskBudget, 1),
        detail: totalRiskBudget !== null ? '策略级预算汇总' : '显示占位，等待 risk_budget',
      },
      {
        key: 'cash-buffer',
        label: 'Cash Buffer',
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
        label: 'Paper Gate',
        status: readString(paperGateRecord, 'status', 'state')
          ?? systemOverview?.paper_validation.state
          ?? getPaperStatusLabel(usPaperStatus),
        detail: readString(paperGateRecord, 'summary', 'detail')
          ?? systemOverview?.paper_review.summary
          ?? (usPaperStatus ? `${usPaperStatus.days_traded} 天留样本` : '等待 paper validation'),
        tone: toneFromOverviewStatus(
          firstPresent(
            readString(paperGateRecord, 'status', 'state'),
            systemOverview?.paper_validation.state,
          ),
        ),
      },
      {
        key: 'review',
        label: 'Review Gate',
        status: readString(reviewGateRecord, 'status', 'state')
          ?? systemOverview?.paper_review.status
          ?? 'manual_gate',
        detail: readString(reviewGateRecord, 'summary', 'detail')
          ?? systemOverview?.paper_review.summary
          ?? '等待人工 review / manifest',
        tone: toneFromOverviewStatus(
          firstPresent(
            readBoolean(reviewGateRecord, 'allowed', 'entry_allowed'),
            systemOverview?.paper_review.entry_allowed,
          ),
        ),
      },
      {
        key: 'live',
        label: 'Live Gate',
        status: readString(liveGateRecord, 'status', 'state')
          ?? systemOverview?.execution.live_state
          ?? 'frozen',
        detail: readString(liveGateRecord, 'summary', 'detail', 'reason')
          ?? systemOverview?.execution.live_block_reason
          ?? 'live runtime frozen',
        tone: toneFromOverviewStatus(
          firstPresent(
            readString(liveGateRecord, 'status', 'state'),
            systemOverview?.execution.live_state,
          ),
        ),
      },
    ];

    return {
      profile: readString(portfolioRoot, 'profile', 'mode', 'scope') ?? (strategyRows.length > 1 ? 'multi-strategy' : 'single-strategy fallback'),
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

  return (
    <main className="ops-dashboard">
      <section className="panel ops-hero-panel">
        <div className="ops-hero-copy">
          <div className="ops-title-row">
            <div>
              <p className="eyebrow">US Equity</p>
              <h2>{selectedStrategy?.display_name ?? '单策略操作台'}</h2>
            </div>
            <div className="ops-title-badges">
              <StatusBadge status={`Live ${systemOverview?.execution.live_state ?? 'frozen'}`} label="live-status" tone="bad" />
              <StatusBadge status={systemOverview?.paper_review.entry_allowed ? 'Reviewable' : 'Manual Gate'} label="paper-status" tone={systemOverview?.paper_review.entry_allowed ? 'good' : 'neutral'} />
            </div>
          </div>
          <p className="ops-hero-note">
            当前仍以 US equity pre-live 操作台为主，但会兼容显示 multi-strategy portfolio 状态。缺失字段不会阻塞页面，live 仍冻结，paper 仍需证据和人工门禁。
          </p>
          <div className="ops-context-grid">
            <div>
              <span>交易标的</span>
              <strong>{usForm.symbol}</strong>
            </div>
            <div>
              <span>观察窗口</span>
              <strong>{usForm.startDate} to {usForm.endDate}</strong>
            </div>
            <div>
              <span>频率</span>
              <strong>{usForm.barSize}</strong>
            </div>
            <div>
              <span>默认参数</span>
              <strong>{selectedStrategy ? `${Object.keys(selectedStrategy.default_params).length} 项` : '未配置'}</strong>
            </div>
            <div>
              <span>小资金上限</span>
              <strong>{systemOverview?.small_account.suggested_max_daily_notional ? `$${formatPrice(systemOverview.small_account.suggested_max_daily_notional)}/day` : '待加载'}</strong>
            </div>
            <div>
              <span>每日单数</span>
              <strong>{systemOverview?.small_account.suggested_max_daily_order_count ?? '-'}</strong>
            </div>
          </div>
        </div>
        <div className="ops-command-summary">
          <div className="ops-command-card">
            <span>当前控制面</span>
            <strong>{usLoading ? '任务运行中' : '等待操作'}</strong>
            <p>{usLoading ? '同一时间只允许一条链路写入。' : '从右侧证据区确认状态后执行下一步。'}</p>
          </div>
          <div className="ops-command-card ops-command-card-alert">
            <span>人工门禁</span>
            <strong>Required</strong>
            <p>promotion gate、paper 对账、风险摘要三项都要有证据，live 才能进入审批。</p>
          </div>
        </div>
      </section>

      <section className="panel" style={{marginBottom: 18}}>
        <div className="panel-header">
          <h3>规划总览</h3>
          <span>{systemOverview?.stage ?? 'waiting'}</span>
        </div>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10}}>
          <div className={`metric-card ${planningOverview.qlibInstalled ? 'metric-good' : 'metric-bad'}`}>
            <span>Qlib dependency</span>
            <strong>{planningOverview.qlibInstalled ? 'installed' : 'missing'}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestQlibLabel} · {planningOverview.latestQlibStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.pypfoptInstalled ? 'metric-good' : 'metric-bad'}`}>
            <span>PyPortfolioOpt dependency</span>
            <strong>{planningOverview.pypfoptInstalled ? 'installed' : 'missing'}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestPortfolioLabel} · {planningOverview.latestPortfolioStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.rawCoverage !== null ? 'metric-good' : ''}`}>
            <span>真实数据覆盖</span>
            <strong>{planningOverview.rawCoverage !== null ? formatPercentValue(planningOverview.rawCoverage, 1) : '未检查'}</strong>
            <p className="ops-portfolio-detail">
              {planningOverview.coverageStatus}
              {planningOverview.minCoverage !== null ? ` · min ${formatPercentValue(planningOverview.minCoverage, 1)}` : ''}
            </p>
          </div>
          <div className={`metric-card ${planningOverview.latestQlibLabel !== '未找到' ? 'metric-good' : ''}`}>
            <span>Latest Qlib run</span>
            <strong>{planningOverview.latestQlibLabel}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestQlibStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.latestPortfolioLabel !== '未找到' ? 'metric-good' : ''}`}>
            <span>Latest portfolio run</span>
            <strong>{planningOverview.latestPortfolioLabel}</strong>
            <p className="ops-portfolio-detail">{planningOverview.latestPortfolioStatus}</p>
          </div>
          <div className={`metric-card ${planningOverview.conflictDetected ? 'metric-bad' : 'metric-good'}`}>
            <span>Paper review conflict</span>
            <strong>{planningOverview.conflictDetected ? 'conflict' : 'clear'}</strong>
            <p className="ops-portfolio-detail">
              {planningOverview.conflictNotes.length > 0 ? planningOverview.conflictNotes[0] : systemOverview?.paper_review.summary ?? 'no conflict diagnostics'}
            </p>
          </div>
        </div>
        {planningOverview.nextActions.length ? (
          <div className="ops-next-actions" style={{marginTop: 12}}>
            {planningOverview.nextActions.map(action => (
              <div key={action} className="ops-next-action">{action}</div>
            ))}
          </div>
        ) : null}
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
          <span>美股 / paper review / live freeze</span>
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
          <span>{usLoading ? <LoadingSpinner text="running" /> : 'single strategy workflow'}</span>
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

      <section className="ops-grid">
        <div className="ops-main">
          <section className="panel ops-gates-panel">
            <div className="panel-header">
              <h3>系统与门禁摘要</h3>
              <span>{health?.status ?? 'unknown'}</span>
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

          <section className="panel ops-portfolio-panel">
            <div className="panel-header">
              <h3>多策略组合总览</h3>
              <span>{portfolioOverview.profile}</span>
            </div>
            <div className="ops-portfolio-summary-grid">
              <div className={`metric-card ${toneFromOverviewStatus(portfolioOverview.status) === 'good' ? 'metric-good' : toneFromOverviewStatus(portfolioOverview.status) === 'bad' ? 'metric-bad' : ''}`}>
                <span>Portfolio Status</span>
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
                <span>PnL Attribution</span>
                <strong>{formatSignedPrice(portfolioOverview.totalPnL)}</strong>
              </div>
            </div>
            <p className="ops-portfolio-detail">{portfolioOverview.detail}</p>

            <div className="ops-portfolio-grid">
              <section className="ops-subsection">
                <div className="ops-subsection-header">
                  <strong>策略权重</strong>
                  <span>{portfolioOverview.strategyRows.length > 0 ? `${portfolioOverview.strategyRows.length} rows` : 'placeholder'}</span>
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
                  <span>paper / review / live</span>
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
                  <span>graceful fallback</span>
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
                  <strong>PnL Attribution</strong>
                  <span>{portfolioOverview.pnlRows.length > 0 ? `${portfolioOverview.pnlRows.length} rows` : 'placeholder'}</span>
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
              <label>Ledger
                <input value={usForm.ledgerDir} onChange={(e: ValueEvent) => setUSForm({...usForm, ledgerDir: e.target.value})} />
              </label>
              <label className="wide-grid-field">数据根目录
                <input value={usForm.dataRoot} onChange={(e: ValueEvent) => setUSForm({...usForm, dataRoot: e.target.value})} />
              </label>
            </div>

            <div className="ops-action-groups">
              <div className="ops-action-group">
                <div className="ops-action-group-header">
                  <strong>Research Gate</strong>
                  <span>数据版本、回测证据、晋升门</span>
                </div>
                <div className="ops-button-grid">
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSDataSync}>同步数据</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSQualityReport}>数据质量</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBuildFeatures}>构建特征</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBacktest}>事件回测</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSUnifiedBacktest}>统一回测</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSCostStressED}>成本压力</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSWalkForward}>Walk-Forward</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPromotionGate}>晋升门</button>
                </div>
              </div>

              <div className="ops-action-group">
                <div className="ops-action-group-header">
                  <strong>Paper Gate</strong>
                  <span>先对账，再留样本，再人工审批</span>
                </div>
                <div className="ops-button-grid">
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperRunDay}>运行 Paper 日</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperBacktest}>Paper 回放</button>
                  <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSReconcile}>运行对账</button>
                  <button type="button" className="secondary-button danger" disabled={usLoading} onClick={handleUSPaperReset}>重置 Paper</button>
                </div>
              </div>
            </div>
          </section>

          <section className="panel ops-metrics-panel">
            <div className="panel-header">
              <h3>Paper 与风险摘要</h3>
              <span>{usPaperDailyResults.length > 0 ? `最近 ${usPaperDailyResults.length} 天` : '暂无样本'}</span>
            </div>
            <div className="ops-metric-grid">
              <div className="metric-card">
                <span>Paper 权益</span>
                <strong>{usPaperStatus ? formatPrice(usPaperStatus.equity) : '-'}</strong>
              </div>
              <div className={`metric-card ${paperPnL >= 0 ? 'metric-good' : 'metric-bad'}`}>
                <span>累计 PnL</span>
                <strong>{usPaperDailyResults.length > 0 ? formatPrice(paperPnL) : '-'}</strong>
              </div>
              <div className="metric-card">
                <span>成交率</span>
                <strong>{paperOrdersSubmitted > 0 ? `${((paperOrdersFilled / paperOrdersSubmitted) * 100).toFixed(0)}%` : '-'}</strong>
              </div>
              <div className={`metric-card ${usPaperStatus?.kill_switch_triggered ? 'metric-bad' : 'metric-good'}`}>
                <span>Kill Switch</span>
                <strong>{usPaperStatus?.kill_switch_triggered ? 'Triggered' : 'Clear'}</strong>
              </div>
            </div>
            <div className="ops-risk-grid">
              <div className="ops-risk-card">
                <span>对账通过率</span>
                <strong>{usPaperDailyResults.length > 0 ? `${paperReconPasses}/${usPaperDailyResults.length}` : '-'}</strong>
                <p>{usPaperStatus?.last_reconciliation_passed === false ? '最近一次对账失败，禁止推进 live。' : '需要连续留存 paper 对账证据。'}</p>
              </div>
              <div className="ops-risk-card">
                <span>Ledger 一致性</span>
                <strong>{usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? 'Pass' : 'Fail') : '-'}</strong>
                <p>{usUnifiedBacktest?.equity_consistency_msg ?? '统一回测尚未出具账本一致性结论。'}</p>
              </div>
              <div className="ops-risk-card">
                <span>晋升约束</span>
                <strong>{promotionGateResult ? promotionGateResult.next_stage : 'research'}</strong>
                <p>{systemOverview?.paper_review.summary ?? (promotionGateResult ? `决策 ${promotionGateResult.decision.toUpperCase()}，仍需人工门禁。` : '未出具 promotion manifest。')}</p>
              </div>
            </div>
            {paperEquityCurve.length > 1 ? (
              <div className="ops-chart-wrap">
                <LineChart title="Paper Equity Trail" points={paperEquityCurve} accentClass="line-accent" />
              </div>
            ) : null}
            {recentPaperRuns.length > 0 ? (
              <div className="paper-results-table">
                {recentPaperRuns.map(day => (
                  <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                    <span>{day.date}</span>
                    <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>{formatPrice(day.daily_pnl)}</span>
                    <span>{day.orders_filled}/{day.orders_submitted} fills</span>
                    <span className={`status-tag ${day.reconciliation_passed ? 'good' : 'bad'}`}>
                      {day.reconciliation_passed ? '对账通过' : '对账失败'}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        </div>

        <aside className="ops-rail">
          <section className="panel ops-evidence-panel">
            <div className="panel-header">
              <h3>账本 / 证据入口</h3>
              <span>live 审批前必查</span>
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
                <span>total_return</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.total_return_pct, 2, '%')}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>sharpe</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.sharpe_ratio)}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>max_drawdown</span>
                <strong>{metricValue(usUnifiedBacktest?.summary.max_drawdown_pct, 2, '%')}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>fills / events</span>
                <strong>{usUnifiedBacktest ? `${usUnifiedBacktest.fill_count} / ${usUnifiedBacktest.event_count}` : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>paper_validation</span>
                <strong>{systemOverview?.paper_validation.state ?? '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>clean_days</span>
                <strong>{systemOverview ? `${systemOverview.paper_validation.days_completed ?? 0}/${systemOverview.paper_validation.days_required ?? 0}` : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>registry_state</span>
                <strong>{systemOverview?.registry.state ?? '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>ledger_final_equity</span>
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
                <strong className={usReconcile?.halt_new_orders || systemOverview?.execution.live_state === 'frozen' ? 'status-err' : ''}>{usReconcile?.halt_new_orders ? 'halted' : systemOverview?.execution.live_state === 'frozen' ? 'live frozen' : 'open'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>break_count</span>
                <strong>{usReconcile ? String(usReconcile.break_count) : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>cash_diff</span>
                <strong>{typeof usReconcile?.cash_diff === 'number' ? formatPrice(usReconcile.cash_diff) : '-'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>alert_sent</span>
                <strong>{usReconcile?.alert_sent ? 'yes' : 'no'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>audit_blocker</span>
                <strong className="text-muted">{systemOverview?.paper_validation.audit_blocker_status ?? 'unknown'}</strong>
              </div>
              <div className="ops-evidence-row">
                <span>kill_switch_reason</span>
                <strong className="text-muted">{usPaperStatus?.kill_switch_reason ?? systemOverview?.execution.live_block_reason ?? 'none'}</strong>
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
    </main>
  );
}
