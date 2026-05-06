import {FormEvent, useEffect, useMemo, useRef, useState} from 'react';

import {
  buildPortfolioRequest,
  buildSingleRequest,
  createRunViewModel,
  humanizeError,
  summarizeMetrics,
  type ChartSeriesPayload,
  type DatabaseStatusResponse,
  type DataSyncRunResponse,
  type FormState,
  type KlinePreviewResponse,
  type RunStatusResponse,
  type SchedulerStatusResponse,
  type StrategyInfo,
  type Summary,
} from './lib/view-model';

type Mode = 'single' | 'portfolio';
type SystemView = 'crypto' | 'us_equity';
type ValueEvent = {target: {value: string}};

const defaultForm: FormState = {
  source: 'fixture',
  symbol: 'BTCUSDT',
  interval: '1h',
  startDate: '2024-01-01',
  endDate: '2024-02-15',
  capital: 100000,
  commissionRate: 0.0004,
  slippage: 4,
  leverage: 1,
  positionBasis: 'equity',
  strategyId: 'trend_macd',
  dataDbPath: '',
};

type DataFormState = {
  symbol: string;
  interval: FormState['interval'];
  startDate: string;
  endDate: string;
  dbPath: string;
};

type USEquityFormState = {
  symbol: string;
  barSize: '1m' | '2m' | '5m' | '15m' | '30m' | '1h' | '1d';
  startDate: string;
  endDate: string;
  dataRoot: string;
  strategyId: 'trend_momentum' | 'short_reversion' | 'factor_rank' | 'earnings_drift';
  ledgerDir: string;
};

const defaultDataForm: DataFormState = {
  symbol: 'BTCUSDT',
  interval: '1m',
  startDate: '2024-01-01',
  endDate: '2024-01-03',
  dbPath: '',
};

const defaultUSForm: USEquityFormState = {
  symbol: 'AAPL',
  barSize: '1d',
  startDate: '2024-01-01',
  endDate: '2024-03-01',
  dataRoot: 'data',
  strategyId: 'trend_momentum',
  ledgerDir: 'data/ledger/paper',
};

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
};

type USEquitySyncResponse = {
  run_id: string;
  status: string;
  symbol: string;
  bar_size: string;
  rows_received: number;
  rows_cleaned: number;
  quality: {
    row_count: number;
    missing_bars: number;
    is_usable: boolean;
  };
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
  breaks: Array<{
    symbol: string;
    local_quantity: number;
    broker_quantity: number;
  }>;
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
  ledger_curve_points: number;
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

type EventDrivenCostStressResponse = {
  status: string;
  engine: string;
  strategy_id: string;
  symbol: string;
  interval: string;
  scenarios: Array<{
    name: string;
    commission_rate: number;
    slippage_bps: number;
    survives: boolean;
    total_return_pct: number;
    sharpe_ratio: number;
    max_drawdown_pct: number;
    fill_count: number;
  }>;
  survival_rate_pct: number;
  baseline_fill_count: number;
  engine_note: string;
};

type ReportMetric = {
  label: string;
  display: string;
  tone?: string;
  description?: string;
};

type ReportSection = {
  priority: number;
  title: string;
  subtitle?: string;
  metrics: ReportMetric[];
};

type OptimizationHint = {
  severity: string;
  message: string;
};

type DrawdownPeriod = {
  start_time: number;
  trough_time: number;
  end_time: number;
  depth_pct: number;
  duration_bars: number;
  recovered: boolean;
  recovery_bars?: number | null;
};

type PeriodReturn = {
  period: string;
  return_pct: number;
};

type OptimizationFrameworkItem = {
  priority: number;
  title: string;
  status: string;
  reason: string;
};

type OptimizationCandidate = {
  rank: number;
  strategy_id: string;
  parameters: Record<string, number>;
  score: number;
  train: Summary;
  validation: Summary;
  overfit_gap: number;
};

type StrategyOptimizationResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  split: {
    train_start: number;
    train_end: number;
    validation_start: number;
    validation_end: number;
    train_rows: number;
    validation_rows: number;
  };
  baseline?: OptimizationCandidate | null;
  best?: OptimizationCandidate | null;
  candidates: OptimizationCandidate[];
  recommendations: string[];
};

type CostStressScenario = {
  name: string;
  label: string;
  commission_multiplier: number;
  slippage_multiplier: number;
  commission_rate: number;
  slippage: number;
  survives: boolean;
  summary: Summary;
  execution: Record<string, number>;
  return_decay_pct: number;
  sharpe_decay: number;
};

type CostStressResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  strategy_id: string;
  strategy_params: Record<string, number>;
  baseline?: CostStressScenario | null;
  scenarios: CostStressScenario[];
  survival_rate_pct: number;
  worst_case?: CostStressScenario | null;
  recommendations: string[];
};

type WalkForwardWindow = {
  fold: number;
  train_start: number;
  train_end: number;
  validation_start: number;
  validation_end: number;
  train_rows: number;
  validation_rows: number;
  selected_params: Record<string, number>;
  train_score: number;
  train: Summary;
  validation: Summary;
  survives: boolean;
};

type RegimeSlice = {
  name: string;
  label: string;
  bar_count: number;
  coverage_pct: number;
  survives: boolean;
  summary: Summary;
};

type WalkForwardResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  strategy_id: string;
  strategy_params: Record<string, number>;
  windows: WalkForwardWindow[];
  regimes: RegimeSlice[];
  stability: {
    window_count: number;
    pass_rate_pct: number;
    avg_oos_return_pct: number;
    median_oos_sharpe: number;
    worst_oos_drawdown_pct: number;
    parameter_stability_pct: number;
    regime_pass_rate_pct: number;
  };
  recommendations: string[];
};

type PortfolioWeightRow = {
  strategy_id: string;
  display_name: string;
  weight: number;
  weight_pct: number;
  baseline_weight_pct: number;
};

type StrategyAllocationRow = {
  strategy_id: string;
  display_name: string;
  category: string;
  baseline_weight_pct: number;
  optimized_weight_pct: number;
  quality_score: number;
  avg_abs_correlation: number;
  summary: Summary;
};

type CorrelationPair = {
  left: string;
  right: string;
  correlation: number;
  abs_correlation: number;
};

type RiskContribution = {
  strategy_id: string;
  weight_pct: number;
  risk_contribution_pct: number;
  standalone_volatility_pct: number;
  avg_abs_correlation: number;
};

type PortfolioOptimizationResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  baseline_weights: Record<string, number>;
  optimized_weights: Record<string, number>;
  optimized_weight_rows: PortfolioWeightRow[];
  baseline_summary: Summary;
  optimized_summary: Summary;
  improvement: {
    return_delta_pct: number;
    sharpe_delta: number;
    drawdown_delta_pct: number;
    cost_delta: number;
  };
  strategy_allocations: StrategyAllocationRow[];
  correlation_pairs: CorrelationPair[];
  risk_budget: {
    active_gross_pct: number;
    cash_reserve_pct: number;
    risk_contributions: RiskContribution[];
    max_pair_abs_correlation: number;
  };
  risk_overlay: {
    state: string;
    suggested_gross_multiplier: number;
    cash_reserve_pct: number;
    max_single_weight_pct: number;
    drawdown_trigger_pct: number;
  };
  recommendations: string[];
};

type DataQualityIssue = {
  severity: string;
  code: string;
  message: string;
};

type DataQualityResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  source: string;
  actual_source: string;
  symbol: string;
  interval: string;
  row_count: number;
  raw_row_count: number;
  expected_rows: number;
  coverage_pct: number;
  missing_bars: number;
  duplicate_timestamps: number;
  cleaning_loss_rows: number;
  invalid_ohlc: number;
  non_positive_prices: number;
  non_positive_volume: number;
  large_price_jumps: number;
  volume_anomalies: number;
  max_gap_bars: number;
  max_price_jump_pct: number;
  first_timestamp?: string | null;
  last_timestamp?: string | null;
  quality_score: number;
  is_usable: boolean;
  fingerprint: string;
  data_version: string;
  issues: DataQualityIssue[];
};

type PromotionGate = {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
  metrics: Record<string, number | string | boolean>;
  threshold: string;
};

type PromotionGateResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  decision: 'pass' | 'warn' | 'fail';
  next_stage: string;
  manifest_id: string;
  manifest_path: string;
  strategy_version: string;
  experiment_record: {
    experiment_name?: string;
    experiment_id?: string;
    run_id?: string;
    registry_path?: string;
    index_path?: string;
    strategy_version?: string;
    data_version?: string;
    decision?: string;
    next_stage?: string;
  };
  data_quality: DataQualityResponse;
  backtest_summary: Summary;
  gates: PromotionGate[];
  recommendations: string[];
};

type MvpStep = {
  id: string;
  label: string;
  status: 'pending' | 'active' | 'done' | 'warn' | 'fail';
  detail: string;
};

const defaultOptimizationFramework: OptimizationFrameworkItem[] = [
  {
    priority: 1,
    title: '参数稳健性 + 样本外验证',
    status: 'selected',
    reason: '当前系统已有回测报告，下一步先做参数筛选和样本外检验，防止把单次回测优化成过拟合。',
  },
  {
    priority: 2,
    title: '交易成本压力测试',
    status: 'next',
    reason: '放大手续费、滑点和执行误差，确认收益不会被真实交易吞噬。',
  },
  {
    priority: 3,
    title: 'Walk-forward 与市场状态切片',
    status: 'next',
    reason: '按牛熊、震荡、高波动、低波动切片验证策略稳定性。',
  },
  {
    priority: 4,
    title: '组合层相关性与资金分配',
    status: 'later',
    reason: '单策略样本外稳定后，再优化组合权重、相关性惩罚和风险预算。',
  },
  {
    priority: 5,
    title: '数据质量与特征版本治理',
    status: 'later',
    reason: '为后续机器学习和多数据源接入保留可复现的数据谱系。',
  },
];

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function formatTimestamp(unix: number): string {
  return new Date(unix * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatIso(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPrice(value: number): string {
  return value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
  });
}

function buildDateBoundary(date: string, boundary: 'start' | 'end', interval: string): string {
  if (boundary === 'start') {
    return `${date}T00:00:00Z`;
  }
  if (interval === '1d') {
    return `${date}T23:59:59Z`;
  }
  return `${date}T23:00:00Z`;
}

function metricClass(tone: string): string {
  if (tone === 'good') return 'metric-card metric-good';
  if (tone === 'bad') return 'metric-card metric-bad';
  return 'metric-card';
}

function reportMetricClass(tone?: string): string {
  if (tone === 'good') return 'report-metric metric-good';
  if (tone === 'bad') return 'report-metric metric-bad';
  return 'report-metric';
}

function hintClass(severity: string): string {
  if (severity === 'high') return 'hint-row hint-high';
  if (severity === 'medium') return 'hint-row hint-medium';
  return 'hint-row';
}

function diagnosticsList<T>(diagnostics: Record<string, unknown> | undefined, key: string): T[] {
  const value = diagnostics?.[key];
  return Array.isArray(value) ? (value as T[]) : [];
}

function reportSectionsFromDiagnostics(diagnostics: Record<string, unknown> | undefined): ReportSection[] {
  return diagnosticsList<ReportSection>(diagnostics, 'report_sections').sort((left, right) => left.priority - right.priority);
}

function formatParams(params?: Record<string, number> | null): string {
  if (!params) return '-';
  const entries = Object.entries(params);
  if (entries.length === 0) return 'default';
  return entries.map(([key, value]) => `${key}=${value}`).join(', ');
}

function formatOptimizationScore(value?: number): string {
  return typeof value === 'number' ? value.toFixed(3) : '-';
}

function scenarioClass(survives: boolean): string {
  return survives ? 'stress-row stress-pass' : 'stress-row stress-fail';
}

function gateClass(status: string): string {
  return `promotion-gate-row promotion-${status}`;
}

function mvpStepClass(status: MvpStep['status']): string {
  return `mvp-step mvp-${status}`;
}

function createLinePath(points: Array<{time: number; value: number}>, width: number, height: number): string {
  if (points.length === 0) return '';
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((point.value - min) / range) * height;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
}

function LineChart({
  title,
  points,
  accentClass,
}: {
  title: string;
  points: Array<{time: number; value: number}>;
  accentClass: string;
}) {
  const width = 860;
  const height = 240;
  const path = createLinePath(points, width, height);
  const latest = points[points.length - 1];
  const first = points[0];

  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <span>
          {first && latest
            ? `${formatTimestamp(first.time)} - ${formatTimestamp(latest.time)}`
            : '暂无数据'}
        </span>
      </div>
      {points.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="line-chart">
          <path d={path} className={`line-path ${accentClass}`} />
        </svg>
      ) : (
        <div className="empty-chart">等待回测结果</div>
      )}
    </section>
  );
}

type CandleViewport = {
  count: number;
  endIndex: number;
};

type CandleDragState = {
  chartWidth: number;
  startClientX: number;
  startEndIndex: number;
  visibleCount: number;
};

type CandlePoint = ChartSeriesPayload['candles'][number];
type TradeMarker = ChartSeriesPayload['markers'][number];
type CandleDisplayInterval = '1m' | '5m' | '15m' | '4h' | '1d' | '1w' | '1mo';

type ChartPointerEvent = {
  clientX: number;
  pointerId?: number;
  currentTarget: Element & {
    setPointerCapture?: (pointerId: number) => void;
  };
  preventDefault(): void;
};

type ChartWheelEvent = {
  deltaY: number;
  preventDefault(): void;
};

const defaultVisibleCandles = 120;
const minimumVisibleCandles = 20;
const candleDisplayOptions: Array<{value: CandleDisplayInterval; label: string}> = [
  {value: '1m', label: '1m'},
  {value: '5m', label: '5m'},
  {value: '15m', label: '15m'},
  {value: '4h', label: '4h'},
  {value: '1d', label: '1D'},
  {value: '1w', label: '1W'},
  {value: '1mo', label: '1M'},
];
const fixedIntervalSeconds: Record<Exclude<CandleDisplayInterval, '1w' | '1mo'>, number> = {
  '1m': 60,
  '5m': 5 * 60,
  '15m': 15 * 60,
  '4h': 4 * 60 * 60,
  '1d': 24 * 60 * 60,
};

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function floorTimestampToInterval(unix: number, interval: CandleDisplayInterval): number {
  if (interval === '1w' || interval === '1mo') {
    const timestamp = new Date(unix * 1000);
    if (interval === '1w') {
      const utcDay = timestamp.getUTCDay();
      const daysFromMonday = (utcDay + 6) % 7;
      return Date.UTC(
        timestamp.getUTCFullYear(),
        timestamp.getUTCMonth(),
        timestamp.getUTCDate() - daysFromMonday,
      ) / 1000;
    }
    return Date.UTC(timestamp.getUTCFullYear(), timestamp.getUTCMonth(), 1) / 1000;
  }

  const seconds = fixedIntervalSeconds[interval];
  return Math.floor(unix / seconds) * seconds;
}

function aggregateCandles(candles: CandlePoint[], interval: CandleDisplayInterval): CandlePoint[] {
  if (candles.length === 0) return [];
  const aggregated = new Map<number, CandlePoint>();

  for (const candle of candles) {
    const bucketTime = floorTimestampToInterval(candle.time, interval);
    const current = aggregated.get(bucketTime);
    if (!current) {
      aggregated.set(bucketTime, {
        time: bucketTime,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
      continue;
    }

    current.high = Math.max(current.high, candle.high);
    current.low = Math.min(current.low, candle.low);
    current.close = candle.close;
  }

  return Array.from(aggregated.values()).sort((left, right) => left.time - right.time);
}

function aggregateMarkers(markers: TradeMarker[], interval: CandleDisplayInterval): TradeMarker[] {
  return markers.map((marker) => ({
    ...marker,
    time: floorTimestampToInterval(marker.time, interval),
  }));
}

function defaultCandleViewport(length: number): CandleViewport {
  const count = Math.min(defaultVisibleCandles, Math.max(0, length));
  return {
    count,
    endIndex: length,
  };
}

function clampCandleViewport(length: number, viewport: CandleViewport): CandleViewport {
  if (length <= 0) return {count: 0, endIndex: 0};
  const minCount = Math.min(minimumVisibleCandles, length);
  const count = clampNumber(Math.round(viewport.count), minCount, length);
  const endIndex = clampNumber(Math.round(viewport.endIndex), count, length);
  return {count, endIndex};
}

function CandleChart({
  candles,
  markers,
}: {
  candles: ChartSeriesPayload['candles'];
  markers: ChartSeriesPayload['markers'];
}) {
  const width = 860;
  const height = 360;
  const plot = {left: 58, right: 18, top: 18, bottom: 34};
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const [displayInterval, setDisplayInterval] = useState<CandleDisplayInterval>('1m');
  const displayCandles = useMemo(() => aggregateCandles(candles, displayInterval), [candles, displayInterval]);
  const displayMarkers = useMemo(() => aggregateMarkers(markers, displayInterval), [markers, displayInterval]);
  const [viewport, setViewport] = useState<CandleViewport>(() => defaultCandleViewport(displayCandles.length));
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const drag = useRef<CandleDragState | null>(null);
  const firstCandleTime = displayCandles[0]?.time ?? 0;
  const lastCandleTime = displayCandles[displayCandles.length - 1]?.time ?? 0;

  useEffect(() => {
    setViewport(defaultCandleViewport(displayCandles.length));
    setHoverIndex(null);
  }, [displayCandles.length, displayInterval, firstCandleTime, lastCandleTime]);

  const activeViewport = viewport.count === 0 && displayCandles.length > 0 ? defaultCandleViewport(displayCandles.length) : viewport;
  const clampedViewport = clampCandleViewport(displayCandles.length, activeViewport);
  const startIndex = Math.max(0, clampedViewport.endIndex - clampedViewport.count);
  const visibleCandles = displayCandles.slice(startIndex, clampedViewport.endIndex);
  const visibleTimes = new Set(visibleCandles.map((candle) => candle.time));
  const visibleMarkers = displayMarkers.filter((marker) => visibleTimes.has(marker.time));
  const hoveredCandle = hoverIndex === null ? null : visibleCandles[hoverIndex] ?? null;

  const updateViewport = (next: CandleViewport | ((current: CandleViewport) => CandleViewport)) => {
    setViewport((current) => clampCandleViewport(displayCandles.length, typeof next === 'function' ? next(current) : next));
  };

  const zoomAroundCenter = (ratio: number) => {
    updateViewport((current) => {
      const normalized = clampCandleViewport(displayCandles.length, current);
      const start = normalized.endIndex - normalized.count;
      const center = start + normalized.count / 2;
      const nextCount = normalized.count * ratio;
      return {
        count: nextCount,
        endIndex: center + nextCount / 2,
      };
    });
  };

  const panCandles = (delta: number) => {
    updateViewport((current) => ({
      ...current,
      endIndex: current.endIndex + delta,
    }));
  };

  const showAllCandles = () => {
    updateViewport({count: displayCandles.length, endIndex: displayCandles.length});
  };

  const resetCandles = () => {
    updateViewport(defaultCandleViewport(displayCandles.length));
  };

  const updateHoverIndex = (event: ChartPointerEvent) => {
    if (visibleCandles.length === 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const chartX = (event.clientX - bounds.left) * (width / Math.max(1, bounds.width));
    const rawIndex = Math.round((chartX - plot.left) / Math.max(1, plotWidth) * Math.max(1, visibleCandles.length - 1));
    setHoverIndex(clampNumber(rawIndex, 0, visibleCandles.length - 1));
  };

  const handlePointerDown = (event: ChartPointerEvent) => {
    if (visibleCandles.length <= 1) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    drag.current = {
      chartWidth: bounds.width,
      startClientX: event.clientX,
      startEndIndex: clampedViewport.endIndex,
      visibleCount: clampedViewport.count,
    };
    if (event.pointerId !== undefined) {
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }
    updateHoverIndex(event);
  };

  const handlePointerMove = (event: ChartPointerEvent) => {
    updateHoverIndex(event);
    if (!drag.current) return;
    const candlePixelWidth = drag.current.chartWidth / Math.max(1, drag.current.visibleCount);
    const deltaBars = Math.round(-(event.clientX - drag.current.startClientX) / Math.max(1, candlePixelWidth));
    updateViewport({
      count: drag.current.visibleCount,
      endIndex: drag.current.startEndIndex + deltaBars,
    });
  };

  const handlePointerUp = () => {
    drag.current = null;
  };

  const handleWheel = (event: ChartWheelEvent) => {
    if (displayCandles.length <= minimumVisibleCandles) return;
    event.preventDefault();
    zoomAroundCenter(event.deltaY > 0 ? 1.25 : 0.8);
  };

  if (visibleCandles.length === 0) {
    return (
      <section className="panel chart-panel">
        <div className="panel-header">
          <h3>K 线与调仓标记</h3>
          <span>暂无数据</span>
        </div>
        <div className="empty-chart">等待回测结果</div>
      </section>
    );
  }

  const lows = visibleCandles.map((candle) => candle.low);
  const highs = visibleCandles.map((candle) => candle.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const candleSlotWidth = plotWidth / Math.max(1, visibleCandles.length);
  const candleBodyWidth = clampNumber(candleSlotWidth * 0.56, 1.4, 10);
  const priceTicks = [max, min + range / 2, min];
  const timeTicks = [
    visibleCandles[0],
    visibleCandles[Math.floor((visibleCandles.length - 1) / 2)],
    visibleCandles[visibleCandles.length - 1],
  ].filter(Boolean);

  const scaleY = (value: number) => plot.top + ((max - value) / range) * plotHeight;
  const xForIndex = (index: number) => plot.left + index * candleSlotWidth + candleSlotWidth / 2;

  return (
    <section className="panel chart-panel">
      <div className="panel-header chart-panel-header">
        <h3>K 线与调仓标记</h3>
        <div className="chart-header-meta">
          <span>
            {formatTimestamp(visibleCandles[0].time)} - {formatTimestamp(visibleCandles[visibleCandles.length - 1].time)}
            {' · '}
            {startIndex + 1}-{clampedViewport.endIndex}/{displayCandles.length}
          </span>
          <div className="chart-toolbar">
            <select
              className="chart-interval-select"
              value={displayInterval}
              onChange={(event: ValueEvent) => setDisplayInterval(event.target.value as CandleDisplayInterval)}
            >
              {candleDisplayOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button type="button" className="chart-tool" title="向前平移" onClick={() => panCandles(-Math.ceil(clampedViewport.count * 0.45))}>
              ‹
            </button>
            <button type="button" className="chart-tool" title="缩小" onClick={() => zoomAroundCenter(1.35)}>
              -
            </button>
            <button type="button" className="chart-tool" title="放大" onClick={() => zoomAroundCenter(0.72)}>
              +
            </button>
            <button type="button" className="chart-tool" title="向后平移" onClick={() => panCandles(Math.ceil(clampedViewport.count * 0.45))}>
              ›
            </button>
            <button type="button" className="chart-text-tool" onClick={showAllCandles}>
              全部
            </button>
            <button type="button" className="chart-text-tool" onClick={resetCandles}>
              重置
            </button>
          </div>
        </div>
      </div>
      <input
        className="chart-range"
        type="range"
        min={Math.max(1, clampedViewport.count)}
        max={Math.max(1, displayCandles.length)}
        value={Math.max(1, clampedViewport.endIndex)}
        onChange={(event: ValueEvent) => updateViewport({...clampedViewport, endIndex: Number(event.target.value)})}
      />
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className={`candle-chart ${drag.current ? 'is-dragging' : ''}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onPointerLeave={() => {
          handlePointerUp();
          setHoverIndex(null);
        }}
        onWheel={handleWheel}
      >
        <rect className="chart-plot-bg" x={plot.left} y={plot.top} width={plotWidth} height={plotHeight} />
        {priceTicks.map((tick, index) => {
          const y = scaleY(tick);
          return (
            <g key={`${tick}-${index}`}>
              <line className="chart-grid-line" x1={plot.left} y1={y} x2={width - plot.right} y2={y} />
              <text className="axis-label price-label" x={plot.left - 8} y={y + 4}>
                {formatPrice(tick)}
              </text>
            </g>
          );
        })}
        {timeTicks.map((candle, tickIndex) => {
          const index = visibleCandles.findIndex((item) => item.time === candle.time);
          const x = xForIndex(Math.max(0, index));
          return (
            <text key={`${candle.time}-${tickIndex}`} className="axis-label time-label" x={x} y={height - 8}>
              {formatTimestamp(candle.time)}
            </text>
          );
        })}
        {visibleCandles.map((candle, index) => {
          const x = xForIndex(index);
          const openY = scaleY(candle.open);
          const closeY = scaleY(candle.close);
          const highY = scaleY(candle.high);
          const lowY = scaleY(candle.low);
          const rising = candle.close >= candle.open;
          const bodyTop = Math.min(openY, closeY);
          const bodyHeight = Math.max(2, Math.abs(closeY - openY));

          return (
            <g key={candle.time}>
              <line className="wick" x1={x} y1={highY} x2={x} y2={lowY} />
              <rect
                className={rising ? 'candle-body candle-up' : 'candle-body candle-down'}
                x={x - candleBodyWidth / 2}
                y={bodyTop}
                width={candleBodyWidth}
                height={bodyHeight}
                rx={1.5}
              />
            </g>
          );
        })}
        {visibleMarkers.map((marker, markerIndex) => {
          const index = visibleCandles.findIndex((candle) => candle.time === marker.time);
          if (index < 0) return null;
          const candle = visibleCandles[index];
          const x = xForIndex(index);
          const y =
            marker.position === 'aboveBar'
              ? Math.max(plot.top + 10, scaleY(candle.high) - 14)
              : Math.min(height - plot.bottom - 10, scaleY(candle.low) + 14);
          const points =
            marker.position === 'aboveBar'
              ? `${x},${y - 10} ${x - 7},${y + 4} ${x + 7},${y + 4}`
              : `${x},${y + 10} ${x - 7},${y - 4} ${x + 7},${y - 4}`;
          return <polygon key={`${marker.time}-${marker.text}-${markerIndex}`} points={points} fill={marker.color} className="marker" />;
        })}
        {hoveredCandle ? (
          <g className="chart-hover-layer">
            <line
              className="chart-crosshair"
              x1={xForIndex(hoverIndex ?? 0)}
              y1={plot.top}
              x2={xForIndex(hoverIndex ?? 0)}
              y2={height - plot.bottom}
            />
            <g transform={`translate(${xForIndex(hoverIndex ?? 0) > width - 180 ? width - 212 : plot.left + 12}, ${plot.top + 12})`}>
              <rect className="chart-tooltip-box" width="190" height="86" rx="8" />
              <text className="chart-tooltip-text" x="10" y="20">
                {formatTimestamp(hoveredCandle.time)}
              </text>
              <text className="chart-tooltip-text muted" x="10" y="42">
                O {formatPrice(hoveredCandle.open)}  H {formatPrice(hoveredCandle.high)}
              </text>
              <text className="chart-tooltip-text muted" x="10" y="64">
                L {formatPrice(hoveredCandle.low)}  C {formatPrice(hoveredCandle.close)}
              </text>
            </g>
          </g>
        ) : null}
      </svg>
      <div className="marker-list">
        {visibleMarkers.slice(-4).map((marker, markerIndex) => (
          <div key={`${marker.time}-${marker.text}-${markerIndex}`} className="marker-pill">
            <span className="marker-dot" style={{backgroundColor: marker.color}} />
            <span>{formatTimestamp(marker.time)}</span>
            <span>{marker.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const [activeSystem, setActiveSystem] = useState<SystemView>('crypto');
  const [mode, setMode] = useState<Mode>('portfolio');
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [weightMap, setWeightMap] = useState<Record<string, number>>({});
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [chart, setChart] = useState<ChartSeriesPayload | null>(null);
  const [dataForm, setDataForm] = useState<DataFormState>(defaultDataForm);
  const [database, setDatabase] = useState<DatabaseStatusResponse | null>(null);
  const [klinePreview, setKlinePreview] = useState<KlinePreviewResponse | null>(null);
  const [syncRuns, setSyncRuns] = useState<DataSyncRunResponse[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatusResponse | null>(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataMessage, setDataMessage] = useState('');
  const [usForm, setUSForm] = useState<USEquityFormState>(defaultUSForm);
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
  const [usPaperLoading, setUSPaperLoading] = useState(false);
  const [paperBacktest, setPaperBacktest] = useState<PaperBacktestResponse | null>(null);
  const [optimization, setOptimization] = useState<StrategyOptimizationResponse | null>(null);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [optimizationMessage, setOptimizationMessage] = useState('');
  const [optimizedStrategyParams, setOptimizedStrategyParams] = useState<Record<string, number> | null>(null);
  const [costStress, setCostStress] = useState<CostStressResponse | null>(null);
  const [costStressLoading, setCostStressLoading] = useState(false);
  const [costStressMessage, setCostStressMessage] = useState('');
  const [edCostStress, setEDCostStress] = useState<EventDrivenCostStressResponse | null>(null);
  const [walkForward, setWalkForward] = useState<WalkForwardResponse | null>(null);
  const [walkForwardLoading, setWalkForwardLoading] = useState(false);
  const [walkForwardMessage, setWalkForwardMessage] = useState('');
  const [portfolioOptimization, setPortfolioOptimization] = useState<PortfolioOptimizationResponse | null>(null);
  const [portfolioOptimizationLoading, setPortfolioOptimizationLoading] = useState(false);
  const [portfolioOptimizationMessage, setPortfolioOptimizationMessage] = useState('');
  const [dataQuality, setDataQuality] = useState<DataQualityResponse | null>(null);
  const [dataQualityLoading, setDataQualityLoading] = useState(false);
  const [dataQualityMessage, setDataQualityMessage] = useState('');
  const [promotionGate, setPromotionGate] = useState<PromotionGateResponse | null>(null);
  const [promotionGateLoading, setPromotionGateLoading] = useState(false);
  const [promotionGateMessage, setPromotionGateMessage] = useState('');
  const [mvpLoading, setMvpLoading] = useState(false);
  const [mvpMessage, setMvpMessage] = useState('');
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const refreshDataPanel = async (nextForm: DataFormState = dataForm) => {
    const baseParams = new URLSearchParams();
    if (nextForm.dbPath) baseParams.set('db_path', nextForm.dbPath);

    const previewParams = new URLSearchParams(baseParams);
    previewParams.set('symbol', nextForm.symbol);
    previewParams.set('interval', nextForm.interval);
    previewParams.set('limit', '16');

    const runsParams = new URLSearchParams(baseParams);
    runsParams.set('limit', '6');

    const [databaseResult, previewResult, runsResult, schedulerResult] = await Promise.all([
      fetchJson<DatabaseStatusResponse>(`/api/data/database?${baseParams.toString()}`),
      fetchJson<KlinePreviewResponse>(`/api/data/klines?${previewParams.toString()}`),
      fetchJson<DataSyncRunResponse[]>(`/api/data/sync-runs?${runsParams.toString()}`),
      fetchJson<SchedulerStatusResponse>('/api/data/scheduler'),
    ]);
    setDatabase(databaseResult);
    setKlinePreview(previewResult);
    setSyncRuns(runsResult);
    setScheduler(schedulerResult);
  };

  useEffect(() => {
    void (async () => {
      try {
        const [healthResult, strategyResult] = await Promise.all([
          fetchJson<HealthState>('/api/health'),
          fetchJson<StrategyInfo[]>('/api/strategies'),
        ]);
        setHealth(healthResult);
        setStrategies(strategyResult);
        setForm((current) => ({
          ...current,
          strategyId: strategyResult[0]?.id ?? current.strategyId,
        }));
        setWeightMap(
          Object.fromEntries(
            strategyResult.map((strategy) => [strategy.id, strategy.default_weight]),
          ),
        );
        await refreshDataPanel(defaultDataForm);
      } catch (caughtError) {
        setError(humanizeError(caughtError));
      }
    })();
  }, []);

  const metricCards = useMemo(() => summarizeMetrics(run?.summary), [run]);
  const viewModel = useMemo(() => createRunViewModel(run, chart), [run, chart]);
  const reportSections = useMemo(() => reportSectionsFromDiagnostics(run?.diagnostics), [run]);
  const optimizationHints = useMemo(() => diagnosticsList<OptimizationHint>(run?.diagnostics, 'optimization_hints'), [run]);
  const drawdownPeriods = useMemo(() => diagnosticsList<DrawdownPeriod>(run?.diagnostics, 'drawdown_periods'), [run]);
  const monthlyReturns = useMemo(() => diagnosticsList<PeriodReturn>(run?.diagnostics, 'monthly_returns'), [run]);
  const optimizationFramework = promotionGate?.framework ?? dataQuality?.framework ?? portfolioOptimization?.framework ?? walkForward?.framework ?? costStress?.framework ?? optimization?.framework ?? defaultOptimizationFramework;
  const mvpSteps = useMemo<MvpStep[]>(() => {
    const gateFails = promotionGate?.gates.filter((gate) => gate.status === 'fail').length ?? 0;
    const gateWarns = promotionGate?.gates.filter((gate) => gate.status === 'warn').length ?? 0;
    const completedSummary = run?.status === 'completed' ? run.summary : null;
    return [
      {
        id: 'data_quality',
        label: '数据质量',
        status: dataQualityLoading || (mvpLoading && !dataQuality) ? 'active' : dataQuality ? (dataQuality.is_usable ? 'done' : 'fail') : 'pending',
        detail: dataQuality ? `Score ${dataQuality.quality_score.toFixed(0)} · ${dataQuality.coverage_pct.toFixed(1)}% 覆盖` : '等待检查数据版本与覆盖率',
      },
      {
        id: 'backtest',
        label: '回测执行',
        status: loading || (mvpLoading && !run) ? 'active' : completedSummary ? 'done' : run?.status === 'failed' ? 'fail' : 'pending',
        detail: completedSummary ? `Return ${completedSummary.total_return_pct.toFixed(2)}% · Sharpe ${completedSummary.sharpe_ratio.toFixed(2)}` : '等待生成策略/组合回测',
      },
      {
        id: 'visual_report',
        label: '图表报告',
        status: chart ? 'done' : run?.status === 'completed' ? 'warn' : 'pending',
        detail: chart ? `${chart.candles.length} 根 K 线 · ${chart.markers.length} 个交易标记` : '等待权益曲线、回撤和 K 线标记',
      },
      {
        id: 'promotion_gate',
        label: '准入门',
        status: promotionGateLoading || (mvpLoading && !promotionGate) ? 'active' : promotionGate ? (promotionGate.decision === 'fail' ? 'fail' : promotionGate.decision === 'warn' ? 'warn' : 'done') : 'pending',
        detail: promotionGate ? `${promotionGate.decision.toUpperCase()} · ${gateWarns} warn · ${gateFails} fail` : '等待综合数据、回测、成本和风险门槛',
      },
      {
        id: 'experiment_registry',
        label: '实验登记',
        status: promotionGate?.experiment_record.registry_path ? 'done' : promotionGate ? 'warn' : 'pending',
        detail: promotionGate?.experiment_record.registry_path ?? '等待写入 manifest 与 experiment registry',
      },
    ];
  }, [chart, dataQuality, dataQualityLoading, loading, mvpLoading, promotionGate, promotionGateLoading, run]);

  const mvpDoneCount = mvpSteps.filter((step) => step.status === 'done').length;

  const buildPromotionGateRequest = () => ({
    mode,
    source: form.source,
    symbol: form.symbol,
    interval: form.interval,
    start: buildDateBoundary(form.startDate, 'start', form.interval),
    end: buildDateBoundary(form.endDate, 'end', form.interval),
    capital: form.capital,
    commission_rate: form.commissionRate,
    slippage: form.slippage,
    leverage: form.leverage,
    position_basis: form.positionBasis,
    data_db_path: form.dataDbPath,
    strategy_id: form.strategyId,
    strategy_params: optimizedStrategyParams ?? {},
    weights: Object.entries(weightMap)
      .filter(([, weight]) => weight > 0)
      .map(([strategy_id, weight]) => ({strategy_id, weight})),
    skip_deep_checks: false,
    persist_manifest: true,
    register_experiment: true,
    experiment_name: `${form.symbol.toLowerCase()}_${mode}_promotion_gate`,
    notes: 'Created from QuantStation MVP acceptance flow.',
  });

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload =
        mode === 'single'
          ? {...buildSingleRequest(form), strategy_params: optimizedStrategyParams ?? {}}
          : buildPortfolioRequest(form, weightMap);
      const nextRun = await fetchJson<RunStatusResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setRun(nextRun);

      if (nextRun.status === 'completed') {
        const nextChart = await fetchJson<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
        setChart(nextChart);
      } else {
        setChart(null);
        setError(nextRun.error ?? '运行失败');
      }
    } catch (caughtError) {
      setError(humanizeError(caughtError));
      setChart(null);
    } finally {
      setLoading(false);
    }
  };

  const handleMvpAcceptance = async () => {
    setMvpLoading(true);
    setMvpMessage('MVP 验收开始：正在检查数据质量。');
    setError('');
    try {
      const quality = await fetchJson<DataQualityResponse>('/api/data/quality', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          data_db_path: form.dataDbPath,
        }),
      });
      setDataQuality(quality);
      setDataQualityMessage(
        `数据质量检查完成：Score ${quality.quality_score.toFixed(0)}，覆盖率 ${quality.coverage_pct.toFixed(2)}%，版本 ${quality.data_version}。`,
      );
      if (!quality.is_usable) {
        throw new Error('数据质量存在阻断级问题，MVP 验收停止。');
      }

      setMvpMessage('数据质量通过，正在运行回测并生成图表。');
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload =
        mode === 'single'
          ? {...buildSingleRequest(form), strategy_params: optimizedStrategyParams ?? {}}
          : buildPortfolioRequest(form, weightMap);
      const nextRun = await fetchJson<RunStatusResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setRun(nextRun);
      if (nextRun.status !== 'completed') {
        throw new Error(nextRun.error ?? '回测失败，MVP 验收停止。');
      }
      const nextChart = await fetchJson<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
      setChart(nextChart);

      setMvpMessage('回测完成，正在运行研究准入门并登记实验。');
      const gate = await fetchJson<PromotionGateResponse>('/api/research/promotion-gate', {
        method: 'POST',
        body: JSON.stringify(buildPromotionGateRequest()),
      });
      setPromotionGate(gate);
      setPromotionGateMessage(
        `准入门完成：Decision ${gate.decision.toUpperCase()}，下一阶段 ${gate.next_stage}，实验 ${gate.experiment_record.experiment_name ?? '-'}。`,
      );
      setMvpMessage(
        `MVP 验收完成：${gate.decision.toUpperCase()}，已登记 ${gate.experiment_record.experiment_name ?? 'experiment'}。`,
      );
    } catch (caughtError) {
      const message = humanizeError(caughtError);
      setMvpMessage(message);
      setError(message);
    } finally {
      setMvpLoading(false);
    }
  };

  const handlePriorityOptimization = async () => {
    setOptimizationLoading(true);
    setOptimizationMessage('');
    setError('');
    try {
      const result = await fetchJson<StrategyOptimizationResponse>('/api/backtests/optimize', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          capital: form.capital,
          commission_rate: form.commissionRate,
          slippage: form.slippage,
          leverage: form.leverage,
          position_basis: form.positionBasis,
          data_db_path: form.dataDbPath,
          strategy_id: form.strategyId,
          max_candidates: 12,
        }),
      });
      setOptimization(result);
      setOptimizationMessage(`优化完成：已评估 ${result.candidates.length} 组参数，当前优先方向为 ${result.selected_priority}。`);
      if (result.best?.parameters) {
        setOptimizedStrategyParams(result.best.parameters);
        setForm((current) => ({
          ...current,
          strategyId: result.best?.strategy_id ?? current.strategyId,
        }));
      }
    } catch (caughtError) {
      setOptimizationMessage(humanizeError(caughtError));
    } finally {
      setOptimizationLoading(false);
    }
  };

  const handleCostStress = async () => {
    setCostStressLoading(true);
    setCostStressMessage('');
    setError('');
    try {
      const strategyParams = optimizedStrategyParams ?? {};
      const result = await fetchJson<CostStressResponse>('/api/backtests/cost-stress', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          capital: form.capital,
          commission_rate: form.commissionRate,
          slippage: form.slippage,
          leverage: form.leverage,
          position_basis: form.positionBasis,
          data_db_path: form.dataDbPath,
          strategy_id: form.strategyId,
          strategy_params: strategyParams,
          max_scenarios: 5,
        }),
      });
      setCostStress(result);
      setCostStressMessage(`压力测试完成：${result.survival_rate_pct.toFixed(0)}% 场景通过。`);
    } catch (caughtError) {
      setCostStressMessage(humanizeError(caughtError));
    } finally {
      setCostStressLoading(false);
    }
  };

  const handleWalkForward = async () => {
    setWalkForwardLoading(true);
    setWalkForwardMessage('');
    setError('');
    try {
      const strategyParams = optimizedStrategyParams ?? {};
      const result = await fetchJson<WalkForwardResponse>('/api/backtests/walk-forward', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          capital: form.capital,
          commission_rate: form.commissionRate,
          slippage: form.slippage,
          leverage: form.leverage,
          position_basis: form.positionBasis,
          data_db_path: form.dataDbPath,
          strategy_id: form.strategyId,
          strategy_params: strategyParams,
          windows: 4,
          max_candidates: optimizedStrategyParams ? 1 : 6,
        }),
      });
      setWalkForward(result);
      setWalkForwardMessage(
        `Walk-forward 完成：${result.stability.pass_rate_pct.toFixed(0)}% 样本外窗口通过，${result.stability.regime_pass_rate_pct.toFixed(0)}% 市场状态切片通过。`,
      );
    } catch (caughtError) {
      setWalkForwardMessage(humanizeError(caughtError));
    } finally {
      setWalkForwardLoading(false);
    }
  };

  const handlePortfolioOptimization = async () => {
    setPortfolioOptimizationLoading(true);
    setPortfolioOptimizationMessage('');
    setError('');
    try {
      const result = await fetchJson<PortfolioOptimizationResponse>('/api/backtests/portfolio-optimize', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          capital: form.capital,
          commission_rate: form.commissionRate,
          slippage: form.slippage,
          leverage: form.leverage,
          position_basis: form.positionBasis,
          data_db_path: form.dataDbPath,
          weights: Object.entries(weightMap)
            .filter(([, weight]) => weight > 0)
            .map(([strategy_id, weight]) => ({strategy_id, weight})),
          max_single_weight: 0.35,
          correlation_penalty: 0.75,
          cash_reserve_pct: 5,
        }),
      });
      setPortfolioOptimization(result);
      setPortfolioOptimizationMessage(
        `组合优化完成：Sharpe ${result.baseline_summary.sharpe_ratio.toFixed(2)} -> ${result.optimized_summary.sharpe_ratio.toFixed(2)}，建议现金预留 ${result.risk_budget.cash_reserve_pct.toFixed(0)}%。`,
      );
    } catch (caughtError) {
      setPortfolioOptimizationMessage(humanizeError(caughtError));
    } finally {
      setPortfolioOptimizationLoading(false);
    }
  };

  const handleApplyPortfolioWeights = () => {
    if (!portfolioOptimization) return;
    setMode('portfolio');
    setWeightMap(portfolioOptimization.optimized_weights);
    setPortfolioOptimizationMessage('已把组合优化权重写入左侧组合权重编辑器。');
  };

  const handleDataQuality = async () => {
    setDataQualityLoading(true);
    setDataQualityMessage('');
    setError('');
    try {
      const result = await fetchJson<DataQualityResponse>('/api/data/quality', {
        method: 'POST',
        body: JSON.stringify({
          source: form.source,
          symbol: form.symbol,
          interval: form.interval,
          start: buildDateBoundary(form.startDate, 'start', form.interval),
          end: buildDateBoundary(form.endDate, 'end', form.interval),
          data_db_path: form.dataDbPath,
        }),
      });
      setDataQuality(result);
      setDataQualityMessage(
        `数据质量检查完成：Score ${result.quality_score.toFixed(0)}，覆盖率 ${result.coverage_pct.toFixed(2)}%，版本 ${result.data_version}。`,
      );
    } catch (caughtError) {
      setDataQualityMessage(humanizeError(caughtError));
    } finally {
      setDataQualityLoading(false);
    }
  };

  const handlePromotionGate = async () => {
    setPromotionGateLoading(true);
    setPromotionGateMessage('');
    setError('');
    try {
      const result = await fetchJson<PromotionGateResponse>('/api/research/promotion-gate', {
        method: 'POST',
        body: JSON.stringify(buildPromotionGateRequest()),
      });
      setPromotionGate(result);
      setPromotionGateMessage(
        `准入门完成：Decision ${result.decision.toUpperCase()}，下一阶段 ${result.next_stage}，实验 ${result.experiment_record.experiment_name ?? '-'}。`,
      );
    } catch (caughtError) {
      setPromotionGateMessage(humanizeError(caughtError));
    } finally {
      setPromotionGateLoading(false);
    }
  };

  const handleDataSync = async () => {
    setDataLoading(true);
    setDataMessage('');
    setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/sync', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          start: buildDateBoundary(dataForm.startDate, 'start', dataForm.interval),
          end: buildDateBoundary(dataForm.endDate, 'end', dataForm.interval),
          db_path: dataForm.dbPath,
          limit: 1000,
          closed_only: true,
        }),
      });
      setDataMessage(`下载完成：写入 ${nextRun.rows_written} 根 K 线，请求 ${nextRun.requests} 次。`);
      setForm((current) => ({
        ...current,
        source: 'sqlite',
        symbol: dataForm.symbol,
        interval: dataForm.interval,
        startDate: dataForm.startDate,
        endDate: dataForm.endDate,
        dataDbPath: dataForm.dbPath,
      }));
      await refreshDataPanel(dataForm);
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleUpdateLatest = async () => {
    setDataLoading(true);
    setDataMessage('');
    setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/update-latest', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          db_path: dataForm.dbPath,
          lookback_days: 30,
          limit: 1000,
        }),
      });
      setDataMessage(`增量更新完成：写入 ${nextRun.rows_written} 根 K 线。`);
      setForm((current) => ({
        ...current,
        source: 'sqlite',
        symbol: dataForm.symbol,
        interval: dataForm.interval,
        dataDbPath: dataForm.dbPath,
      }));
      await refreshDataPanel(dataForm);
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleStartScheduler = async () => {
    setDataLoading(true);
    setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/start', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          db_path: dataForm.dbPath,
          lookback_days: 30,
          interval_seconds: 86400,
          run_immediately: true,
        }),
      });
      setScheduler(nextStatus);
      setDataMessage('日更任务已启动。');
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleStopScheduler = async () => {
    setDataLoading(true);
    setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/stop', {
        method: 'POST',
      });
      setScheduler(nextStatus);
      setDataMessage('日更任务已停止。');
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleUSDataSync = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USEquitySyncResponse>('/api/us/data/sync', {
        method: 'POST',
        body: JSON.stringify({
          vendor: 'yfinance',
          asset_class: 'equity',
          symbol: usForm.symbol,
          bar_size: usForm.barSize,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          data_root: usForm.dataRoot,
        }),
      });
      setUSSync(result);
      setUSMessage(`美股数据同步完成：清洗 ${result.rows_cleaned} 行。`);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSBuildFeatures = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USFeatureBuildResponse>('/api/us/features/build', {
        method: 'POST',
        body: JSON.stringify({
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
        }),
      });
      setUSFeature(result);
      setUSMessage(`因子构建完成：写入 ${result.rows_written} 行。`);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USEventBacktestResponse>('/api/us/backtests/event', {
        method: 'POST',
        body: JSON.stringify({
          vendor: 'yfinance',
          asset_class: 'equity',
          symbol: usForm.symbol,
          bar_size: usForm.barSize,
          strategy_id: usForm.strategyId,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          data_root: usForm.dataRoot,
          auto_sync: true,
        }),
      });
      setUSBacktest(result);
      setUSMessage(`事件回测完成：订单 ${result.order_count}，成交 ${result.fill_count}。`);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };


  const handleUSQualityReport = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USQualityReportResponse>('/api/us/data/quality-report', {
        method: 'POST',
        body: JSON.stringify({
          symbol: usForm.symbol,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          data_root: usForm.dataRoot,
        }),
      });
      setUSQualityReport(result);
      setUSMessage(result.has_issues
        ? '数据质量报告：发现 ' + result.total_issues + ' 个问题（' + result.reports.filter(r => r.issues_found > 0).length + ' 类）。'
        : '数据质量报告：无问题。');
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSReconcile = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USReconciliationResponse>('/api/us/reconcile', {
        method: 'POST',
        body: JSON.stringify({
          ledger_dir: usForm.ledgerDir,
          tolerance: 0.000001,
        }),
      });
      setUSReconcile(result);
      setUSMessage(result.status === 'clean' ? '本地 ledger 持仓一致。' : `发现 ${result.break_count} 个持仓差异。`);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSUnifiedBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USUnifiedBacktestResponse>('/api/us/backtests/unified', {
        method: 'POST',
        body: JSON.stringify({
          vendor: 'yfinance',
          asset_class: 'equity',
          symbol: usForm.symbol,
          bar_size: usForm.barSize,
          strategy_id: usForm.strategyId,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          data_root: usForm.dataRoot,
          auto_sync: true,
        }),
      });
      setUSUnifiedBacktest(result);
      setUSMessage(
        result.equity_consistent
          ? `统一回测完成：权益一致性验证通过。${result.equity_consistency_msg}`
          : `统一回测完成：权益一致性验证失败！${result.equity_consistency_msg}`,
      );
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperRunDay = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<USPaperDayResultResponse>('/api/us/paper/run-day', {
        method: 'POST',
        body: JSON.stringify({
          vendor: 'yfinance',
          asset_class: 'equity',
          symbol: usForm.symbol,
          bar_size: usForm.barSize,
          strategy_id: usForm.strategyId,
          target_date: usForm.startDate,
          data_root: usForm.dataRoot,
          capital: 100000,
        }),
      });
      setUSMessage(
        `纸交易运行完成：PnL $${result.daily_pnl.toFixed(2)}，成交 ${result.orders_filled}/${result.orders_submitted} 笔。`,
      );
      handleUSPaperStatus();
      handleUSPaperDailyResults();
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperStatus = async () => {
    setUSPaperLoading(true);
    try {
      const result = await fetchJson<USPaperStatusResponse>('/api/us/paper/status');
      setUSPaperStatus(result);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSPaperLoading(false);
    }
  };

  const handleUSPaperDailyResults = async () => {
    setUSPaperLoading(true);
    try {
      const results = await fetchJson<USPaperDayResultResponse[]>('/api/us/paper/daily-results');
      setUSPaperDailyResults(results);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSPaperLoading(false);
    }
  };

  const handleUSPaperBacktest = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<PaperBacktestResponse>('/api/us/paper/backtest', {
        method: 'POST',
        body: JSON.stringify({
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
        }),
      });
      setPaperBacktest(result);
      setUSMessage(
        `纸交易回测完成：${result.days_processed} 天，总 PnL $${result.total_pnl.toFixed(2)}，最终权益 ${formatPrice(result.final_equity)}`,
      );
      handleUSPaperStatus();
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSCostStressED = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<EventDrivenCostStressResponse>('/api/backtests/cost-stress/event-driven', {
        method: 'POST',
        body: JSON.stringify({
          source: 'fixture',
          symbol: usForm.symbol,
          interval: '1h',
          strategy_id: usForm.strategyId,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          capital: 100000,
          max_scenarios: 5,
        }),
      });
      setEDCostStress(result);
      setUSMessage(`事件驱动成本压力测试完成：${result.survival_rate_pct.toFixed(0)}% 生存率，引擎：${result.engine}`);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSWalkForward = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<{stability: Record<string, unknown>; windows: Array<unknown>}>('/api/backtests/walk-forward', {
        method: 'POST',
        body: JSON.stringify({
          source: 'yfinance',
          symbol: usForm.symbol,
          interval: usForm.barSize,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          capital: 100000,
          commission_rate: 0.0001,
          strategy_id: usForm.strategyId,
          data_root: usForm.dataRoot,
        }),
      });
      const stability = result.stability as Record<string, number>;
      setUSMessage(
        'Walk-Forward: pass_rate ' + ((stability.pass_rate_pct ?? 0) as number).toFixed(0) + '%, ' +
        'OOS return ' + ((stability.avg_oos_return_pct ?? 0) as number).toFixed(2) + '%, ' +
        'windows ' + (result.windows as Array<unknown>).length,
      );
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPromotionGate = async () => {
    setUSLoading(true);
    setUSMessage('');
    try {
      const result = await fetchJson<{decision: string; next_stage: string; gates: Array<{name: string; status: string}>}>('/api/research/promotion-gate', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: usForm.strategyId,
          symbol: usForm.symbol,
          interval: usForm.barSize,
          start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
          end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
          capital: 100000,
          source: 'yfinance',
          data_root: usForm.dataRoot,
          skip_deep_checks: false,
        }),
      });
      const passed = result.gates.filter(function(g: {status: string}) { return g.status === 'pass'; }).length;
      setUSMessage(
        'Promotion Gate: ' + result.decision + ' -> ' + result.next_stage +
        ' (' + passed + '/' + result.gates.length + ' gates passed)',
      );
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  const handleUSPaperReset = async () => {
    setUSLoading(true);
    try {
      await fetchJson<{status: string}>('/api/us/paper/reset', {method: 'POST'});
      setUSMessage('纸交易状态已重置。');
      setPaperBacktest(null);
      setUSPaperStatus(null);
      setUSPaperDailyResults([]);
    } catch (caughtError) {
      setUSMessage(humanizeError(caughtError));
    } finally {
      setUSLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <header className="hero">
        <div>
          <p className="eyebrow">QuantStation vNext</p>
          <h1>{activeSystem === 'crypto' ? '比特币多策略投研控制台' : '美股量化 MVP 工作台'}</h1>
          <p className="hero-copy">
            {activeSystem === 'crypto'
              ? '单策略回测、组合净敞口推演、风险缩放与调仓复盘现在收敛到同一条链路里。'
              : '数据湖、因子构建、事件回测和本地 ledger 核对拆成独立工作区。'}
          </p>
        </div>
        <div className="hero-actions">
          <div className="system-switch">
            <button
              type="button"
              className={activeSystem === 'crypto' ? 'active' : ''}
              onClick={() => setActiveSystem('crypto')}
            >
              加密策略
            </button>
            <button
              type="button"
              className={activeSystem === 'us_equity' ? 'active' : ''}
              onClick={() => setActiveSystem('us_equity')}
            >
              美股量化
            </button>
          </div>
          <div className="hero-status">
            <span className="status-chip">{health?.service ?? '等待后端'}</span>
            <span className="status-chip muted">默认数据源 {health?.data_source_default ?? 'unknown'}</span>
          </div>
        </div>
      </header>

      {activeSystem === 'crypto' ? (
      <main className="layout">
        <aside className="side-column">
        <form className="panel control-panel" onSubmit={handleSubmit}>
          <div className="panel-header">
            <h2>运行配置</h2>
            <div className="mode-toggle">
              <button type="button" className={mode === 'portfolio' ? 'active' : ''} onClick={() => setMode('portfolio')}>
                组合回测
              </button>
              <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => setMode('single')}>
                单策略
              </button>
            </div>
          </div>

          <div className="form-grid">
            <label>
              数据源
              <select value={form.source} onChange={(event: ValueEvent) => setForm({...form, source: event.target.value as FormState['source']})}>
                <option value="fixture">Fixture</option>
                <option value="auto">Auto</option>
                <option value="sqlite">SQLite</option>
              </select>
            </label>
            <label>
              标的
              <input value={form.symbol} onChange={(event: ValueEvent) => setForm({...form, symbol: event.target.value})} />
            </label>
            <label>
              周期
              <select value={form.interval} onChange={(event: ValueEvent) => setForm({...form, interval: event.target.value as FormState['interval']})}>
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((interval) => (
                  <option key={interval} value={interval}>
                    {interval}
                  </option>
                ))}
              </select>
            </label>
            <label>
              资金基准
              <select
                value={form.positionBasis}
                onChange={(event: ValueEvent) => setForm({...form, positionBasis: event.target.value as FormState['positionBasis']})}
              >
                <option value="equity">动态权益</option>
                <option value="capital">固定本金</option>
              </select>
            </label>
            <label>
              开始日期
              <input type="date" value={form.startDate} onChange={(event: ValueEvent) => setForm({...form, startDate: event.target.value})} />
            </label>
            <label>
              结束日期
              <input type="date" value={form.endDate} onChange={(event: ValueEvent) => setForm({...form, endDate: event.target.value})} />
            </label>
            <label>
              初始资金
              <input type="number" value={form.capital} onChange={(event: ValueEvent) => setForm({...form, capital: Number(event.target.value)})} />
            </label>
            <label>
              杠杆
              <input type="number" step="0.1" value={form.leverage} onChange={(event: ValueEvent) => setForm({...form, leverage: Number(event.target.value)})} />
            </label>
            <label>
              手续费率
              <input
                type="number"
                step="0.0001"
                value={form.commissionRate}
                onChange={(event: ValueEvent) => setForm({...form, commissionRate: Number(event.target.value)})}
              />
            </label>
            <label>
              滑点
              <input type="number" step="0.1" value={form.slippage} onChange={(event: ValueEvent) => setForm({...form, slippage: Number(event.target.value)})} />
            </label>
            <label className="wide-grid-field">
              SQLite 数据库
              <input
                value={form.dataDbPath}
                placeholder="留空使用后端默认库"
                onChange={(event: ValueEvent) => setForm({...form, dataDbPath: event.target.value})}
              />
            </label>
          </div>

          {mode === 'single' ? (
            <label className="wide-field">
              策略
              <select
                value={form.strategyId}
                onChange={(event: ValueEvent) => {
                  setOptimizedStrategyParams(null);
                  setForm({...form, strategyId: event.target.value});
                }}
              >
                {strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.display_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="weights-panel">
              <div className="weights-header">
                <h3>组合权重编辑</h3>
                <span>系统会自动归一化正权重</span>
              </div>
              {strategies.map((strategy) => (
                <div key={strategy.id} className="weight-row">
                  <div>
                    <strong>{strategy.display_name}</strong>
                    <p>{strategy.description}</p>
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={weightMap[strategy.id] ?? 0}
                    onChange={(event: ValueEvent) =>
                      setWeightMap({
                        ...weightMap,
                        [strategy.id]: Number(event.target.value),
                      })
                    }
                  />
                </div>
              ))}
            </div>
          )}

          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? '运行中...' : '启动回测'}
          </button>
        </form>

        <section className="panel data-panel">
          <div className="panel-header">
            <h2>数据管理</h2>
            <span>{database?.initialized ? 'SQLite 已就绪' : '等待初始化'}</span>
          </div>

          <div className="data-status-grid">
            <div>
              <span>数据库</span>
              <strong>{database?.exists ? '已创建' : '未创建'}</strong>
            </div>
            <div>
              <span>覆盖组合</span>
              <strong>{database?.coverage.length ?? 0}</strong>
            </div>
            <div>
              <span>日更任务</span>
              <strong>{scheduler?.running ? '运行中' : '停止'}</strong>
            </div>
          </div>

          <label className="wide-field">
            数据库路径
            <input
              value={dataForm.dbPath}
              placeholder={database?.db_path ?? '留空使用后端默认库'}
              onChange={(event: ValueEvent) => {
                const nextForm = {...dataForm, dbPath: event.target.value};
                setDataForm(nextForm);
                setForm((current) => ({...current, dataDbPath: event.target.value}));
              }}
            />
          </label>

          <div className="form-grid data-form-grid">
            <label>
              标的
              <input
                value={dataForm.symbol}
                onChange={(event: ValueEvent) => setDataForm({...dataForm, symbol: event.target.value.toUpperCase()})}
              />
            </label>
            <label>
              周期
              <select
                value={dataForm.interval}
                onChange={(event: ValueEvent) => setDataForm({...dataForm, interval: event.target.value as FormState['interval']})}
              >
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((interval) => (
                  <option key={interval} value={interval}>
                    {interval}
                  </option>
                ))}
              </select>
            </label>
            <label>
              下载开始
              <input type="date" value={dataForm.startDate} onChange={(event: ValueEvent) => setDataForm({...dataForm, startDate: event.target.value})} />
            </label>
            <label>
              下载结束
              <input type="date" value={dataForm.endDate} onChange={(event: ValueEvent) => setDataForm({...dataForm, endDate: event.target.value})} />
            </label>
          </div>

          <div className="data-actions">
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleDataSync}>
              下载区间
            </button>
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleUpdateLatest}>
              更新到最新
            </button>
            <button type="button" className="secondary-button" disabled={dataLoading || scheduler?.running} onClick={handleStartScheduler}>
              启动日更
            </button>
            <button type="button" className="secondary-button danger" disabled={dataLoading || !scheduler?.running} onClick={handleStopScheduler}>
              停止日更
            </button>
          </div>

          {dataMessage ? <p className="data-message">{dataMessage}</p> : null}

          <div className="coverage-list">
            {(database?.coverage ?? []).slice(0, 4).map((item) => (
              <div key={`${item.exchange}-${item.symbol}-${item.interval}`} className="coverage-row">
                <strong>{item.symbol} {item.interval}</strong>
                <span>{item.rows.toLocaleString('en-US')} 根</span>
                <span>{formatIso(item.start)} - {formatIso(item.end)}</span>
              </div>
            ))}
          </div>

          <div className="panel-header compact-header">
            <h3>数据库预览</h3>
            <button type="button" className="ghost-button" onClick={() => void refreshDataPanel(dataForm)}>
              刷新
            </button>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>开</th>
                  <th>高</th>
                  <th>低</th>
                  <th>收</th>
                  <th>量</th>
                </tr>
              </thead>
              <tbody>
                {(klinePreview?.rows ?? []).map((row) => (
                  <tr key={row.open_time_ms}>
                    <td>{formatIso(row.time)}</td>
                    <td>{formatPrice(row.open)}</td>
                    <td>{formatPrice(row.high)}</td>
                    <td>{formatPrice(row.low)}</td>
                    <td>{formatPrice(row.close)}</td>
                    <td>{row.volume.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sync-log">
            {syncRuns.map((item) => (
              <div key={item.run_id} className="sync-row">
                <span className={`status-tag ${item.status === 'completed' ? 'good' : item.status === 'failed' ? 'bad' : 'neutral'}`}>
                  {item.status}
                </span>
                <span>{item.symbol} {item.interval}</span>
                <span>{item.rows_written.toLocaleString('en-US')} 根</span>
              </div>
            ))}
          </div>
        </section>

        </aside>

        <section className="results-column">
          <section className="panel mvp-panel">
            <div className="panel-header">
              <h2>MVP 交付闭环</h2>
              <span>已完成 {mvpDoneCount}/{mvpSteps.length}</span>
            </div>
            <div className="mvp-command-row">
              <div>
                <strong>{promotionGate ? promotionGate.next_stage : run?.status === 'completed' ? 'ready_for_gate' : 'research_ready'}</strong>
                <p>{promotionGate?.manifest_id ? `Manifest ${promotionGate.manifest_id}` : '最小闭环待验收'}</p>
              </div>
              <button type="button" className="primary-button" disabled={mvpLoading || loading || promotionGateLoading || dataQualityLoading} onClick={handleMvpAcceptance}>
                {mvpLoading ? '验收中...' : '一键 MVP 验收'}
              </button>
            </div>
            <div className="mvp-step-grid">
              {mvpSteps.map((step, index) => (
                <div key={step.id} className={mvpStepClass(step.status)}>
                  <span>{index + 1}</span>
                  <strong>{step.label}</strong>
                  <p>{step.detail}</p>
                </div>
              ))}
            </div>
            {mvpMessage ? <p className="data-message">{mvpMessage}</p> : null}
          </section>

          {error ? (
            <div className="panel error-panel">
              <div className="panel-header">
                <h2>运行错误</h2>
              </div>
              <p>{error}</p>
            </div>
          ) : null}

          <section className="panel optimization-panel">
            <div className="panel-header">
              <h2>下一步优化框架</h2>
              <span>{promotionGate?.selected_priority ?? dataQuality?.selected_priority ?? portfolioOptimization?.selected_priority ?? walkForward?.selected_priority ?? costStress?.selected_priority ?? optimization?.selected_priority ?? '当前优先：参数稳健性 + 样本外验证'}</span>
            </div>
            <div className="optimization-framework">
              {optimizationFramework.map((item) => (
                <div key={item.priority} className={`optimization-step optimization-${item.status}`}>
                  <span>{item.priority}</span>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.reason}</p>
                  </div>
                </div>
              ))}
            </div>
            <div className="optimization-actions">
              <button type="button" className="secondary-button" disabled={optimizationLoading} onClick={handlePriorityOptimization}>
                {optimizationLoading ? '优化中...' : '运行当前优先优化'}
              </button>
              <button type="button" className="secondary-button" disabled={costStressLoading} onClick={handleCostStress}>
                {costStressLoading ? '压力测试中...' : '运行成本压力测试'}
              </button>
              <button type="button" className="secondary-button" disabled={walkForwardLoading} onClick={handleWalkForward}>
                {walkForwardLoading ? 'Walk-forward 中...' : '运行 Walk-forward'}
              </button>
              <button type="button" className="secondary-button" disabled={portfolioOptimizationLoading} onClick={handlePortfolioOptimization}>
                {portfolioOptimizationLoading ? '组合优化中...' : '运行组合优化'}
              </button>
              <button type="button" className="secondary-button" disabled={dataQualityLoading} onClick={handleDataQuality}>
                {dataQualityLoading ? '质量检查中...' : '运行数据质量检查'}
              </button>
              <button type="button" className="secondary-button" disabled={promotionGateLoading} onClick={handlePromotionGate}>
                {promotionGateLoading ? '准入门检查中...' : '运行研究准入门'}
              </button>
              {optimizedStrategyParams ? <span>已应用优化参数：{formatParams(optimizedStrategyParams)}</span> : null}
            </div>
            {optimizationMessage ? <p className="data-message">{optimizationMessage}</p> : null}
            {costStressMessage ? <p className="data-message">{costStressMessage}</p> : null}
            {walkForwardMessage ? <p className="data-message">{walkForwardMessage}</p> : null}
            {portfolioOptimizationMessage ? <p className="data-message">{portfolioOptimizationMessage}</p> : null}
            {dataQualityMessage ? <p className="data-message">{dataQualityMessage}</p> : null}
            {promotionGateMessage ? <p className="data-message">{promotionGateMessage}</p> : null}

            {optimization?.best ? (
              <div className="optimization-result-grid">
                <div className="optimization-best">
                  <span>最佳样本外候选</span>
                  <strong>Score {formatOptimizationScore(optimization.best.score)}</strong>
                  <p>{formatParams(optimization.best.parameters)}</p>
                </div>
                <div className="optimization-best">
                  <span>样本外表现</span>
                  <strong>Sharpe {optimization.best.validation.sharpe_ratio.toFixed(2)}</strong>
                  <p>Return {optimization.best.validation.total_return_pct.toFixed(2)}% · MDD {optimization.best.validation.max_drawdown_pct.toFixed(2)}%</p>
                </div>
                <div className="optimization-best">
                  <span>切分</span>
                  <strong>{optimization.split.train_rows} / {optimization.split.validation_rows}</strong>
                  <p>{formatTimestamp(optimization.split.train_start)} - {formatTimestamp(optimization.split.validation_end)}</p>
                </div>
              </div>
            ) : null}

            {optimization?.recommendations.length ? (
              <div className="optimization-recommendations">
                {optimization.recommendations.map((item, index) => (
                  <p key={index}>{item}</p>
                ))}
              </div>
            ) : null}

            {optimization?.candidates.length ? (
              <div className="optimization-table">
                {optimization.candidates.slice(0, 5).map((candidate) => (
                  <div key={candidate.rank} className="optimization-row">
                    <span>#{candidate.rank}</span>
                    <span>{formatOptimizationScore(candidate.score)}</span>
                    <span>{candidate.validation.sharpe_ratio.toFixed(2)} Sharpe</span>
                    <span>{candidate.validation.max_drawdown_pct.toFixed(2)}% MDD</span>
                    <span>{formatParams(candidate.parameters)}</span>
                  </div>
                ))}
              </div>
            ) : null}

            {costStress ? (
              <div className="stress-panel">
                <div className="stress-summary-grid">
                  <div className="optimization-best">
                    <span>压力存活率</span>
                    <strong>{costStress.survival_rate_pct.toFixed(0)}%</strong>
                    <p>{costStress.selected_priority}</p>
                  </div>
                  <div className="optimization-best">
                    <span>最差场景</span>
                    <strong>{costStress.worst_case?.label ?? '-'}</strong>
                    <p>
                      Return {costStress.worst_case?.summary.total_return_pct.toFixed(2) ?? '-'}% ·
                      MDD {costStress.worst_case?.summary.max_drawdown_pct.toFixed(2) ?? '-'}%
                    </p>
                  </div>
                  <div className="optimization-best">
                    <span>测试参数</span>
                    <strong>{costStress.strategy_id}</strong>
                    <p>{formatParams(costStress.strategy_params)}</p>
                  </div>
                </div>

                <div className="stress-table">
                  {costStress.scenarios.map((scenario) => (
                    <div key={scenario.name} className={scenarioClass(scenario.survives)}>
                      <span>{scenario.survives ? 'PASS' : 'FAIL'}</span>
                      <span>{scenario.label}</span>
                      <span>{scenario.summary.total_return_pct.toFixed(2)}%</span>
                      <span>{scenario.summary.sharpe_ratio.toFixed(2)} Sharpe</span>
                      <span>{scenario.summary.max_drawdown_pct.toFixed(2)}% MDD</span>
                      <span>{Number(scenario.execution.total_cost ?? 0).toLocaleString('en-US', {maximumFractionDigits: 0})} cost</span>
                    </div>
                  ))}
                </div>

                <div className="optimization-recommendations">
                  {costStress.recommendations.map((item, index) => (
                    <p key={index}>{item}</p>
                  ))}
                </div>
              </div>
            ) : null}

            {walkForward ? (
              <div className="walk-panel">
                <div className="stress-summary-grid">
                  <div className="optimization-best">
                    <span>样本外通过率</span>
                    <strong>{walkForward.stability.pass_rate_pct.toFixed(0)}%</strong>
                    <p>{walkForward.selected_priority}</p>
                  </div>
                  <div className="optimization-best">
                    <span>样本外中位 Sharpe</span>
                    <strong>{walkForward.stability.median_oos_sharpe.toFixed(2)}</strong>
                    <p>Avg OOS Return {walkForward.stability.avg_oos_return_pct.toFixed(2)}%</p>
                  </div>
                  <div className="optimization-best">
                    <span>参数稳定性</span>
                    <strong>{walkForward.stability.parameter_stability_pct.toFixed(0)}%</strong>
                    <p>Worst OOS MDD {walkForward.stability.worst_oos_drawdown_pct.toFixed(2)}%</p>
                  </div>
                </div>

                <div className="walk-table">
                  {walkForward.windows.map((window) => (
                    <div key={window.fold} className={`walk-row ${window.survives ? 'stress-pass' : 'stress-fail'}`}>
                      <span>W{window.fold}</span>
                      <span>{window.survives ? 'PASS' : 'FAIL'}</span>
                      <span>{formatTimestamp(window.validation_start)} - {formatTimestamp(window.validation_end)}</span>
                      <span>{window.validation.total_return_pct.toFixed(2)}%</span>
                      <span>{window.validation.sharpe_ratio.toFixed(2)} Sharpe</span>
                      <span>{window.validation.max_drawdown_pct.toFixed(2)}% MDD</span>
                      <span>{formatParams(window.selected_params)}</span>
                    </div>
                  ))}
                </div>

                <div className="regime-grid">
                  {walkForward.regimes.map((regime) => (
                    <div key={regime.name} className={`regime-card ${regime.survives ? 'stress-pass' : 'stress-fail'}`}>
                      <span>{regime.survives ? 'PASS' : 'FAIL'}</span>
                      <strong>{regime.label}</strong>
                      <p>
                        {regime.coverage_pct.toFixed(0)}% bars · Return {regime.summary.total_return_pct.toFixed(2)}% ·
                        MDD {regime.summary.max_drawdown_pct.toFixed(2)}%
                      </p>
                    </div>
                  ))}
                </div>

                <div className="optimization-recommendations">
                  {walkForward.recommendations.map((item, index) => (
                    <p key={index}>{item}</p>
                  ))}
                </div>
              </div>
            ) : null}

            {portfolioOptimization ? (
              <div className="portfolio-opt-panel">
                <div className="stress-summary-grid">
                  <div className="optimization-best">
                    <span>优化后 Sharpe</span>
                    <strong>{portfolioOptimization.optimized_summary.sharpe_ratio.toFixed(2)}</strong>
                    <p>Delta {portfolioOptimization.improvement.sharpe_delta.toFixed(2)}</p>
                  </div>
                  <div className="optimization-best">
                    <span>优化后收益</span>
                    <strong>{portfolioOptimization.optimized_summary.total_return_pct.toFixed(2)}%</strong>
                    <p>Baseline {portfolioOptimization.baseline_summary.total_return_pct.toFixed(2)}%</p>
                  </div>
                  <div className="optimization-best">
                    <span>风险状态</span>
                    <strong>{portfolioOptimization.risk_overlay.state}</strong>
                    <p>Gross x{portfolioOptimization.risk_overlay.suggested_gross_multiplier.toFixed(2)} · Cash {portfolioOptimization.risk_budget.cash_reserve_pct.toFixed(0)}%</p>
                  </div>
                </div>

                <div className="portfolio-action-row">
                  <button type="button" className="secondary-button" onClick={handleApplyPortfolioWeights}>
                    应用建议权重
                  </button>
                  <span>最大单策略 {portfolioOptimization.risk_overlay.max_single_weight_pct.toFixed(0)}% · 最大相关性 {portfolioOptimization.risk_budget.max_pair_abs_correlation.toFixed(2)}</span>
                </div>

                <div className="portfolio-table">
                  {portfolioOptimization.optimized_weight_rows.map((row) => (
                    <div key={row.strategy_id} className="portfolio-row">
                      <span>{row.display_name}</span>
                      <span>{row.baseline_weight_pct.toFixed(1)}% to {row.weight_pct.toFixed(1)}%</span>
                      <span>{portfolioOptimization.strategy_allocations.find((item) => item.strategy_id === row.strategy_id)?.summary.sharpe_ratio.toFixed(2) ?? '-'} Sharpe</span>
                      <span>{portfolioOptimization.strategy_allocations.find((item) => item.strategy_id === row.strategy_id)?.avg_abs_correlation.toFixed(2) ?? '-'} avg corr</span>
                    </div>
                  ))}
                </div>

                <div className="portfolio-split-grid">
                  <div>
                    <h4>风险贡献</h4>
                    <div className="risk-list">
                      {portfolioOptimization.risk_budget.risk_contributions.map((item) => (
                        <div key={item.strategy_id} className="risk-row">
                          <span>{item.strategy_id}</span>
                          <span>{item.risk_contribution_pct.toFixed(1)}% risk</span>
                          <span>{item.weight_pct.toFixed(1)}% weight</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4>最高相关性</h4>
                    <div className="risk-list">
                      {portfolioOptimization.correlation_pairs.slice(0, 4).map((pair) => (
                        <div key={`${pair.left}-${pair.right}`} className="risk-row">
                          <span>{pair.left} / {pair.right}</span>
                          <span>{pair.correlation.toFixed(2)}</span>
                          <span>{pair.abs_correlation.toFixed(2)} abs</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="optimization-recommendations">
                  {portfolioOptimization.recommendations.map((item, index) => (
                    <p key={index}>{item}</p>
                  ))}
                </div>
              </div>
            ) : null}

            {dataQuality ? (
              <div className="data-quality-panel">
                <div className="stress-summary-grid">
                  <div className="optimization-best">
                    <span>质量分数</span>
                    <strong>{dataQuality.quality_score.toFixed(0)}</strong>
                    <p>{dataQuality.is_usable ? '可用于研究回测' : '存在阻断级问题'}</p>
                  </div>
                  <div className="optimization-best">
                    <span>覆盖率</span>
                    <strong>{dataQuality.coverage_pct.toFixed(2)}%</strong>
                    <p>{dataQuality.row_count.toLocaleString('en-US')} / {dataQuality.expected_rows.toLocaleString('en-US')} bars</p>
                  </div>
                  <div className="optimization-best">
                    <span>数据版本</span>
                    <strong>{dataQuality.actual_source}</strong>
                    <p>{dataQuality.data_version}</p>
                  </div>
                </div>

                <div className="quality-metrics-grid">
                  <div>
                    <span>缺失 K 线</span>
                    <strong>{dataQuality.missing_bars}</strong>
                  </div>
                  <div>
                    <span>重复时间戳</span>
                    <strong>{dataQuality.duplicate_timestamps}</strong>
                  </div>
                  <div>
                    <span>OHLC 异常</span>
                    <strong>{dataQuality.invalid_ohlc}</strong>
                  </div>
                  <div>
                    <span>价格跳变</span>
                    <strong>{dataQuality.large_price_jumps}</strong>
                  </div>
                  <div>
                    <span>最大跳变</span>
                    <strong>{dataQuality.max_price_jump_pct.toFixed(2)}%</strong>
                  </div>
                  <div>
                    <span>清洗剔除</span>
                    <strong>{dataQuality.cleaning_loss_rows}</strong>
                  </div>
                </div>

                <div className="quality-version-row">
                  <span>{dataQuality.first_timestamp ? formatIso(dataQuality.first_timestamp) : '-'} - {dataQuality.last_timestamp ? formatIso(dataQuality.last_timestamp) : '-'}</span>
                  <span>{dataQuality.fingerprint.slice(0, 16)}</span>
                </div>

                <div className="quality-issue-list">
                  {dataQuality.issues.map((issue) => (
                    <div key={`${issue.code}-${issue.message}`} className={`quality-issue quality-${issue.severity}`}>
                      <span>{issue.severity}</span>
                      <strong>{issue.code}</strong>
                      <p>{issue.message}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {promotionGate ? (
              <div className="promotion-panel">
                <div className="stress-summary-grid">
                  <div className="optimization-best">
                    <span>晋级决策</span>
                    <strong>{promotionGate.decision.toUpperCase()}</strong>
                    <p>{promotionGate.next_stage}</p>
                  </div>
                  <div className="optimization-best">
                    <span>核心 Sharpe</span>
                    <strong>{promotionGate.backtest_summary.sharpe_ratio.toFixed(2)}</strong>
                    <p>MDD {promotionGate.backtest_summary.max_drawdown_pct.toFixed(2)}%</p>
                  </div>
                  <div className="optimization-best">
                    <span>Manifest</span>
                    <strong>{promotionGate.manifest_id.slice(0, 8)}</strong>
                    <p>{promotionGate.manifest_path || 'not persisted'}</p>
                  </div>
                  <div className="optimization-best">
                    <span>策略版本</span>
                    <strong>{promotionGate.strategy_version.slice(0, 18)}</strong>
                    <p>{promotionGate.experiment_record.data_version || promotionGate.data_quality.data_version}</p>
                  </div>
                  <div className="optimization-best">
                    <span>实验登记</span>
                    <strong>{promotionGate.experiment_record.experiment_name ?? '-'}</strong>
                    <p>{promotionGate.experiment_record.registry_path ?? 'not registered'}</p>
                  </div>
                </div>

                <div className="promotion-gate-list">
                  {promotionGate.gates.map((gate) => (
                    <div key={gate.name} className={gateClass(gate.status)}>
                      <span>{gate.status.toUpperCase()}</span>
                      <strong>{gate.name}</strong>
                      <p>{gate.message}</p>
                    </div>
                  ))}
                </div>

                <div className="optimization-recommendations">
                  {promotionGate.recommendations.map((item, index) => (
                    <p key={index}>{item}</p>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <section className="metrics-grid">
            {metricCards.length > 0 ? (
              metricCards.map((card) => (
                <article key={card.label} className={metricClass(card.tone)}>
                  <span>{card.label}</span>
                  <strong>{card.value}</strong>
                </article>
              ))
            ) : (
              <article className="panel metrics-placeholder">
                <h3>回测结果会显示在这里</h3>
                <p>先运行一次单策略或组合回测，系统会返回绩效卡片、净值、回撤和 K 线标记。</p>
              </article>
            )}
          </section>

          {reportSections.length > 0 ? (
            <section className="report-stack">
              {reportSections.map((section) => (
                <article key={section.title} className="panel report-section">
                  <div className="report-section-header">
                    <span className="report-priority">{section.priority}</span>
                    <div>
                      <h3>{section.title}</h3>
                      {section.subtitle ? <p>{section.subtitle}</p> : null}
                    </div>
                  </div>
                  <div className="report-metrics">
                    {section.metrics.map((metric) => (
                      <div key={`${section.title}-${metric.label}`} className={reportMetricClass(metric.tone)}>
                        <span>{metric.label}</span>
                        <strong>{metric.display}</strong>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          ) : null}

          {optimizationHints.length > 0 ? (
            <section className="panel insight-panel">
              <div className="panel-header">
                <h3>优化优先级</h3>
                <span>{optimizationHints.length} 条</span>
              </div>
              <div className="hint-list">
                {optimizationHints.map((hint, index) => (
                  <div key={`${hint.severity}-${index}`} className={hintClass(hint.severity)}>
                    <span>{hint.severity}</span>
                    <p>{hint.message}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <div className="charts-grid">
            <LineChart title="权益曲线" points={chart?.equity ?? []} accentClass="line-accent" />
            <LineChart title="回撤曲线" points={chart?.drawdown ?? []} accentClass="line-accent-secondary" />
            <LineChart title="换手率" points={chart?.turnover ?? []} accentClass="line-accent-muted" />
            <LineChart title="动态杠杆" points={chart?.leverage ?? []} accentClass="line-accent-risk" />
          </div>

          <CandleChart candles={chart?.candles ?? []} markers={chart?.markers ?? []} />

          {(drawdownPeriods.length > 0 || monthlyReturns.length > 0) ? (
            <section className="analysis-grid">
              <article className="panel table-panel">
                <div className="panel-header">
                  <h3>Top 回撤区间</h3>
                  <span>按深度排序</span>
                </div>
                <div className="detail-table">
                  {drawdownPeriods.map((item, index) => (
                    <div key={`${item.start_time}-${index}`} className="detail-row drawdown-row">
                      <span>{formatTimestamp(item.start_time)} - {formatTimestamp(item.end_time)}</span>
                      <span>{item.depth_pct.toFixed(2)}% · {item.duration_bars} bars</span>
                    </div>
                  ))}
                </div>
              </article>
              <article className="panel table-panel">
                <div className="panel-header">
                  <h3>月度收益</h3>
                  <span>最近 {monthlyReturns.length} 个月</span>
                </div>
                <div className="monthly-grid">
                  {monthlyReturns.map((item) => (
                    <div key={item.period} className={item.return_pct >= 0 ? 'month-cell month-up' : 'month-cell month-down'}>
                      <span>{item.period}</span>
                      <strong>{item.return_pct.toFixed(2)}%</strong>
                    </div>
                  ))}
                </div>
              </article>
            </section>
          ) : null}

          <section className="panel detail-panel">
            <div className="panel-header">
              <h3>运行详情</h3>
              <span className={`status-tag ${viewModel.statusTone}`}>{run?.status ?? 'idle'}</span>
            </div>
            <div className="detail-grid">
              <div>
                <h4>策略表现</h4>
                <div className="detail-table">
                  {(run?.strategy_details ?? []).map((item) => (
                    <div key={String(item.strategy_id)} className="detail-row">
                      <span>{String(item.display_name)}</span>
                      <span>{Number(item.total_return_pct ?? 0).toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h4>最新组合权重</h4>
                <div className="detail-table">
                  {(run?.latest_weights ?? []).map((item) => (
                    <div key={String(item.strategy_id)} className="detail-row">
                      <span>{String(item.display_name)}</span>
                      <span>{(Number(item.weight ?? 0) * 100).toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </section>
      </main>
      ) : (
      <main className="us-workspace">
        <section className="panel us-command-panel">
          <div className="panel-header">
            <h2>美股任务配置</h2>
            <span>{usBacktest?.status ?? 'event chain'}</span>
          </div>

          <div className="form-grid us-form-grid">
            <label>
              标的
              <input value={usForm.symbol} onChange={(event: ValueEvent) => setUSForm({...usForm, symbol: event.target.value.toUpperCase()})} />
            </label>
            <label>
              周期
              <select value={usForm.barSize} onChange={(event: ValueEvent) => setUSForm({...usForm, barSize: event.target.value as USEquityFormState['barSize']})}>
                {['1d', '1h', '30m', '15m', '5m', '2m', '1m'].map((barSize) => (
                  <option key={barSize} value={barSize}>
                    {barSize}
                  </option>
                ))}
              </select>
            </label>
            <label>
              开始日期
              <input type="date" value={usForm.startDate} onChange={(event: ValueEvent) => setUSForm({...usForm, startDate: event.target.value})} />
            </label>
            <label>
              结束日期
              <input type="date" value={usForm.endDate} onChange={(event: ValueEvent) => setUSForm({...usForm, endDate: event.target.value})} />
            </label>
            <label className="wide-grid-field">
              数据湖根目录
              <input value={usForm.dataRoot} onChange={(event: ValueEvent) => setUSForm({...usForm, dataRoot: event.target.value})} />
            </label>
            <label>
              策略
              <select value={usForm.strategyId} onChange={(event: ValueEvent) => setUSForm({...usForm, strategyId: event.target.value as USEquityFormState['strategyId']})}>
                <option value="trend_momentum">趋势动量</option>
                <option value="short_reversion">短期均值回归</option>
                <option value="factor_rank">因子排序</option>
                <option value="earnings_drift">盈利漂移</option>
                <option value="etf_rotation">ETF 动量轮动</option>
              </select>
            </label>
            <label>
              Ledger
              <input value={usForm.ledgerDir} onChange={(event: ValueEvent) => setUSForm({...usForm, ledgerDir: event.target.value})} />
            </label>
          </div>

          <div className="data-actions us-actions">
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSDataSync}>
              同步数据湖
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBuildFeatures}>
              构建因子
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBacktest}>
              事件回测
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSReconcile}>
              持仓核对
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSUnifiedBacktest}>
              统一回测（权益验证）
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperRunDay}>
              纸交易（运行日）
            </button>
            <button type="button" className="secondary-button" disabled={usPaperLoading} onClick={handleUSPaperStatus}>
              纸交易状态
            </button>
            <button type="button" className="secondary-button" disabled={usPaperLoading} onClick={handleUSPaperDailyResults}>
              纸交易每日结果
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperBacktest}>
              纸交易回测（多日）
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSQualityReport}>
              数据质量报告
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSCostStressED}>
              事件驱动成本压力
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSWalkForward}>
              Walk-Forward 验证
            </button>
            <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPromotionGate}>
              晋升门检查
            </button>
            <button type="button" className="secondary-button danger" disabled={usLoading} onClick={handleUSPaperReset}>
              重置纸交易
            </button>
          </div>

          {usMessage ? <p className="data-message">{usMessage}</p> : null}

          {/* 数据质量报告 */}
          {usQualityReport ? (
            <div className="panel quality-panel">
              <div className="panel-header">
                <h3>数据质量报告 — {usQualityReport.symbol}</h3>
                <span className={usQualityReport.has_issues ? 'status-warn' : 'status-ok'}>
                  {usQualityReport.has_issues ? usQualityReport.total_issues + ' 个问题' : '全部通过'}
                </span>
              </div>
              <table className="quality-table">
                <thead><tr><th>检查项</th><th>问题数</th><th>详情</th></tr></thead>
                <tbody>
                  {usQualityReport.reports.map((r) => (
                    <tr key={r.report_type}>
                      <td>{r.report_type}</td>
                      <td className={r.issues_found > 0 ? 'text-warn' : 'text-ok'}>{r.issues_found}</td>
                      <td className="text-muted">{r.details.slice(0, 3).map(d => JSON.stringify(d)).join(', ') || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {/* 对账结果 + halt 状态 */}
          {usReconcile ? (
            <div className="panel recon-panel">
              <div className="panel-header">
                <h3>持仓核对</h3>
                <span className={usReconcile.status === 'clean' ? 'status-ok' : 'status-err'}>
                  {usReconcile.status === 'clean' ? '一致' : '差异'}
                  {usReconcile.halt_new_orders ? ' — 已暂停新开仓' : ''}
                </span>
              </div>
              {usReconcile.status !== 'clean' ? (
                <div className="recon-details">
                  {usReconcile.cash_diff !== undefined && usReconcile.cash_diff !== 0 ? (
                    <p>现金差异: ${usReconcile.cash_diff.toFixed(2)}</p>
                  ) : null}
                  {usReconcile.position_diffs && Object.keys(usReconcile.position_diffs).length > 0 ? (
                    <p>持仓差异: {Object.keys(usReconcile.position_diffs).join(', ')}</p>
                  ) : null}
                  {usReconcile.order_diffs && Object.keys(usReconcile.order_diffs).length > 0 ? (
                    <p>订单差异: {Object.keys(usReconcile.order_diffs).join(', ')}</p>
                  ) : null}
                  {usReconcile.report_path ? <p className="text-muted">报告: {usReconcile.report_path}</p> : null}
                  {usReconcile.alert_sent ? <p className="text-warn">已发送告警</p> : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <section className="panel mvp-panel">
          <div className="panel-header">
            <h2>美股工作流</h2>
            <span>已同步 → 回测 → 验证 → 纸交易</span>
          </div>
          <div className="mvp-step-grid">
            {[
              {
                id: 'us_data',
                label: '数据同步',
                status: usSync ? 'done' : 'pending',
                detail: usSync ? `${usSync.rows_cleaned} 行清洗` : '等待同步',
              },
              {
                id: 'us_features',
                label: '因子构建',
                status: usFeature ? 'done' : usSync ? 'warn' : 'pending',
                detail: usFeature ? `${usFeature.rows_written} 行` : '等待构建',
              },
              {
                id: 'us_backtest',
                label: '事件回测',
                status: usBacktest ? 'done' : usFeature ? 'warn' : 'pending',
                detail: usBacktest ? `${usBacktest.fill_count} 笔成交` : '等待回测',
              },
              {
                id: 'us_unified',
                label: '权益验证',
                status: usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? 'done' : 'fail') : usBacktest ? 'warn' : 'pending',
                detail: usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? '一致' : '不一致') : '等待验证',
              },
              {
                id: 'us_paper',
                label: '纸交易',
                status: usPaperStatus?.days_traded && usPaperStatus.days_traded > 0 ? (usPaperStatus.healthy ? 'done' : 'warn') : usUnifiedBacktest ? 'warn' : 'pending',
                detail: usPaperStatus ? `${usPaperStatus.days_traded} 天 ${usPaperStatus.healthy ? '健康' : '异常'}` : '等待运行',
              },
            ].map((step, index) => (
              <div key={step.id} className={mvpStepClass(step.status as MvpStep['status'])}>
                <span>{index + 1}</span>
                <strong>{step.label}</strong>
                <p>{step.detail}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="panel us-output-panel">
          <div className="panel-header">
            <h2>美股链路状态</h2>
            <span>{usLoading ? 'running' : 'idle'}</span>
          </div>

          <div className="us-stage-grid">
            <div>
              <span>清洗数据</span>
              <strong>{usSync ? `${usSync.rows_cleaned}/${usSync.rows_received}` : '-'}</strong>
            </div>
            <div>
              <span>因子行数</span>
              <strong>{usFeature?.rows_written ?? '-'}</strong>
            </div>
            <div>
              <span>事件/成交</span>
              <strong>{usBacktest ? `${usBacktest.event_count}/${usBacktest.fill_count}` : '-'}</strong>
            </div>
            <div>
              <span>核对状态</span>
              <strong>{usReconcile ? `${usReconcile.status} (${usReconcile.break_count})` : '-'}</strong>
            </div>
          </div>

          <div className="us-mini-metrics">
            <div>
              <span>总收益</span>
              <strong>{usBacktest ? `${(usBacktest.summary.total_return_pct ?? 0).toFixed(2)}%` : '-'}</strong>
            </div>
            <div>
              <span>Sharpe</span>
              <strong>{usBacktest ? (usBacktest.summary.sharpe_ratio ?? 0).toFixed(2) : '-'}</strong>
            </div>
            <div>
              <span>最大回撤</span>
              <strong>{usBacktest ? `${(usBacktest.summary.max_drawdown_pct ?? 0).toFixed(2)}%` : '-'}</strong>
            </div>
          </div>

          <div className="us-break-list">
            {(usReconcile?.breaks ?? []).map((item) => (
              <div key={item.symbol} className="detail-row">
                <span>{item.symbol}</span>
                <span>{item.local_quantity} / {item.broker_quantity}</span>
              </div>
            ))}
          </div>

          {usUnifiedBacktest ? (
            <div className="us-unified-section">
              <div className="panel-header">
                <h3>统一回测结果</h3>
                <span className={`status-tag ${usUnifiedBacktest.equity_consistent ? 'good' : 'bad'}`}>
                  {usUnifiedBacktest.equity_consistent ? '权益验证 PASS' : '权益验证 FAIL'}
                </span>
              </div>
              <div className="us-mini-metrics">
                <div>
                  <span>总收益</span>
                  <strong className={(usUnifiedBacktest.summary.total_return_pct ?? 0) >= 0 ? 'metric-good' : 'metric-bad'}>
                    {(usUnifiedBacktest.summary.total_return_pct ?? 0).toFixed(2)}%
                  </strong>
                </div>
                <div>
                  <span>Sharpe</span>
                  <strong>{(usUnifiedBacktest.summary.sharpe_ratio ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span>最大回撤</span>
                  <strong>{(usUnifiedBacktest.summary.max_drawdown_pct ?? 0).toFixed(2)}%</strong>
                </div>
                <div>
                  <span>账本权益</span>
                  <strong>{formatPrice(usUnifiedBacktest.ledger_final_equity)}</strong>
                </div>
              </div>
              <div className="us-stage-grid">
                <div>
                  <span>订单/成交</span>
                  <strong>{usUnifiedBacktest.order_count}/{usUnifiedBacktest.fill_count}</strong>
                </div>
                <div>
                  <span>快照/事件</span>
                  <strong>{usUnifiedBacktest.snapshot_count}/{usUnifiedBacktest.event_count}</strong>
                </div>
                <div>
                  <span>总费用</span>
                  <strong>{formatPrice(usUnifiedBacktest.ledger_total_fees)}</strong>
                </div>
                <div>
                  <span>验证</span>
                  <strong style={{color: usUnifiedBacktest.equity_consistent ? 'var(--good)' : 'var(--bad)'}}>
                    {usUnifiedBacktest.equity_consistent ? '一致' : '不一致'}
                  </strong>
                </div>
              </div>
              <p className="data-message">{usUnifiedBacktest.equity_consistency_msg}</p>
              {usUnifiedBacktest.equity_curve.length > 1 ? (
                <div className="charts-grid" style={{marginTop: 14}}>
                  <LineChart title="美股权益曲线" points={usUnifiedBacktest.equity_curve} accentClass="line-accent" />
                  <LineChart title="美股回撤曲线" points={usUnifiedBacktest.drawdown_curve} accentClass="line-accent-secondary" />
                </div>
              ) : null}
            </div>
          ) : null}

          {usPaperStatus ? (
            <div className="us-paper-section">
              <div className="panel-header">
                <h3>纸交易状态</h3>
                <span className={`status-tag ${usPaperStatus.healthy ? 'good' : 'bad'}`}>
                  {usPaperStatus.healthy ? '健康' : '异常'}
                </span>
              </div>
              <div className="us-mini-metrics">
                <div>
                  <span>权益</span>
                  <strong>{formatPrice(usPaperStatus.equity)}</strong>
                </div>
                <div>
                  <span>现金</span>
                  <strong>{formatPrice(usPaperStatus.cash)}</strong>
                </div>
                <div>
                  <span>购买力</span>
                  <strong>{formatPrice(usPaperStatus.buying_power)}</strong>
                </div>
                <div>
                  <span>持仓数</span>
                  <strong>{usPaperStatus.positions}</strong>
                </div>
              </div>
              <div className="us-stage-grid">
                <div>
                  <span>交易日数</span>
                  <strong>{usPaperStatus.days_traded}</strong>
                </div>
                <div>
                  <span>风控开关</span>
                  <strong style={{color: usPaperStatus.kill_switch_triggered ? 'var(--bad)' : 'var(--good)'}}>
                    {usPaperStatus.kill_switch_triggered ? '已触发' : '正常'}
                  </strong>
                </div>
                <div>
                  <span>上次对账</span>
                  <strong>{usPaperStatus.last_reconciliation_passed === null ? '-' : usPaperStatus.last_reconciliation_passed ? '通过' : '失败'}</strong>
                </div>
              </div>
              {usPaperStatus.kill_switch_reason ? (
                <p className="data-message">风控原因：{usPaperStatus.kill_switch_reason}</p>
              ) : null}
            </div>
          ) : null}

          {usPaperDailyResults.length > 0 ? (
            <div className="us-paper-results-section">
              <div className="panel-header">
                <h3>纸交易每日结果</h3>
                <span>最近 {Math.min(usPaperDailyResults.length, 10)} 天</span>
              </div>
              <div className="paper-results-table">
                {usPaperDailyResults.slice(-10).reverse().map((day) => (
                  <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                    <span>{day.date}</span>
                    <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>
                      ${day.daily_pnl.toFixed(2)}
                    </span>
                    <span className={day.reconciliation_passed ? 'status-tag good' : 'status-tag bad'}>
                      {day.reconciliation_passed ? '对账通过' : '对账失败'}
                    </span>
                    <span>{day.orders_filled}/{day.orders_submitted} 成交</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {edCostStress ? (
            <div className="us-unified-section">
              <div className="panel-header">
                <h3>事件驱动成本压力测试</h3>
                <span className={`status-tag ${edCostStress.survival_rate_pct >= 50 ? 'good' : 'bad'}`}>
                  {edCostStress.survival_rate_pct.toFixed(0)}% 生存率
                </span>
              </div>
              <div className="us-stage-grid">
                <div><span>引擎</span><strong>{edCostStress.engine}</strong></div>
                <div><span>基准成交</span><strong>{edCostStress.baseline_fill_count}</strong></div>
                <div><span>策略</span><strong>{edCostStress.strategy_id}</strong></div>
                <div><span>标的</span><strong>{edCostStress.symbol} · {edCostStress.interval}</strong></div>
              </div>
              <p className="data-message">{edCostStress.engine_note}</p>
              <div className="paper-results-table">
                {edCostStress.scenarios.map((scenario) => (
                  <div key={scenario.name} className={`paper-result-row ${scenario.survives ? '' : 'paper-fail'}`}>
                    <span>{scenario.name}</span>
                    <span className={scenario.total_return_pct >= 0 ? 'metric-good' : 'metric-bad'}>
                      {scenario.total_return_pct?.toFixed(2) ?? '-'}%
                    </span>
                    <span>Sharpe: {scenario.sharpe_ratio?.toFixed(2) ?? '-'}</span>
                    <span>成交: {scenario.fill_count ?? '-'}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {paperBacktest ? (
            <div className="us-unified-section">
              <div className="panel-header">
                <h3>纸交易回测汇总</h3>
                <span className={`status-tag ${paperBacktest.healthy ? 'good' : 'bad'}`}>
                  {paperBacktest.healthy ? '健康' : '异常'}
                </span>
              </div>
              <div className="us-mini-metrics">
                <div>
                  <span>总 PnL</span>
                  <strong className={paperBacktest.total_pnl >= 0 ? 'metric-good' : 'metric-bad'}>
                    ${paperBacktest.total_pnl.toFixed(2)}
                  </strong>
                </div>
                <div>
                  <span>最终权益</span>
                  <strong>{formatPrice(paperBacktest.final_equity)}</strong>
                </div>
                <div>
                  <span>处理天数</span>
                  <strong>{paperBacktest.days_processed}</strong>
                </div>
                <div>
                  <span>风控开关</span>
                  <strong style={{color: paperBacktest.kill_switch_triggered ? 'var(--bad)' : 'var(--good)'}}>
                    {paperBacktest.kill_switch_triggered ? '已触发' : '正常'}
                  </strong>
                </div>
              </div>
              {paperBacktest.daily_results.length > 0 ? (
                <div className="paper-results-table">
                  {paperBacktest.daily_results.map((day) => (
                    <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                      <span>{day.date}</span>
                      <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>
                        ${day.daily_pnl.toFixed(2)}
                      </span>
                      <span>{day.orders_filled}/{day.orders_submitted} 成交</span>
                      <span>{day.reconciliation_passed ? '通过' : '失败'}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </main>
      )}
    </div>
  );
}
