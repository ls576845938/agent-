import type {CryptoCoverageSummary, CryptoResamplePlanItem} from './shared-types';

export type StrategyInfo = {
  id: string;
  display_name: string;
  description: string;
  category: string;
  default_weight: number;
  default_params: Record<string, number>;
};

export type Summary = {
  total_return_pct: number;
  annual_return_pct: number;
  annual_volatility_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
  trade_count: number;
};

export type RunStatusResponse = {
  run_id: string;
  mode: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  error?: string | null;
  summary?: Summary | null;
  latest_weights: Array<Record<string, unknown>>;
  strategy_details: Array<Record<string, unknown>>;
  diagnostics: Record<string, unknown>;
};

export type ChartSeriesPayload = {
  candles: Array<{time: number; open: number; high: number; low: number; close: number}>;
  markers: Array<{time: number; position: string; color: string; shape: string; text: string}>;
  equity: Array<{time: number; value: number}>;
  drawdown: Array<{time: number; value: number}>;
  exposure: Array<{time: number; value: number}>;
  net_units: Array<{time: number; value: number}>;
  turnover: Array<{time: number; value: number}>;
  leverage: Array<{time: number; value: number}>;
};

export type DataCoverageItem = {
  exchange: string;
  symbol: string;
  interval: string;
  rows: number;
  start?: string | null;
  end?: string | null;
  updated_at?: string | null;
};

export type DatabaseStatusResponse = {
  db_path: string;
  exists: boolean;
  initialized: boolean;
  table_count: number;
  coverage: DataCoverageItem[];
};

export type DataSyncRunResponse = {
  run_id: string;
  status: string;
  db_path: string;
  exchange: string;
  symbol: string;
  interval: string;
  start: string;
  end: string;
  rows_received: number;
  rows_written: number;
  requests: number;
  created_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
};

export type CryptoResampleResponse = {
  status: string;
  db_path: string;
  exchange: string;
  symbol: string;
  source_interval: string;
  target_interval: string;
  start: string;
  end: string;
  source_rows: number;
  expected_source_rows: number;
  rows_written: number;
  coverage_pct: number;
  quality_score: number;
  manifest_path: string;
  data_version: string;
  fingerprint: string;
  completed_at?: string | null;
  quality_summary: Record<string, number>;
};

export type KlinePreviewResponse = {
  db_path: string;
  rows: Array<{
    exchange: string;
    symbol: string;
    interval: string;
    time: string;
    open_time_ms: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    quote_volume: number;
    trade_count: number;
  }>;
};

export type SchedulerStatusResponse = {
  running: boolean;
  interval_seconds: number;
  symbol: string;
  interval: string;
  db_path: string;
  last_started_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
  last_result?: Record<string, unknown> | null;
};

export type FormState = {
  source: 'fixture' | 'sqlite' | 'auto';
  symbol: string;
  interval: '1m' | '5m' | '15m' | '1h' | '4h' | '1d';
  startDate: string;
  endDate: string;
  capital: number;
  commissionRate: number;
  slippage: number;
  leverage: number;
  positionBasis: 'equity' | 'capital';
  strategyId: string;
  dataDbPath: string;
};

export function normalizeWeights(weightMap: Record<string, number>): Record<string, number>;
export const cryptoIntervalOrder: Array<'1m' | '5m' | '15m' | '1h' | '4h' | '1d'>;
export function summarizeCryptoCoverage(coverage: DataCoverageItem[]): CryptoCoverageSummary & {intervals: DataCoverageItem[]};
export function buildCryptoResamplePlan(
  coverage: DataCoverageItem[],
  symbol?: string,
  dbPath?: string,
  exchange?: string,
): CryptoResamplePlanItem[];
export function collectCryptoBlockers(
  dataQuality: import('./shared-types').DataQualityResponse | null | undefined,
  promotionGate: import('./shared-types').PromotionGateResponse | null | undefined,
): {
  dataQualityBlockers: string[];
  promotionBlockers: string[];
  coverageBlockers: string[];
  blockers: string[];
};
export function buildSingleRequest(form: FormState): Record<string, unknown>;
export function buildPortfolioRequest(form: FormState, weightMap: Record<string, number>): Record<string, unknown>;
export function summarizeMetrics(summary?: Summary | null): Array<{label: string; value: string; tone: string}>;
export function humanizeError(error: unknown): string;
export function createRunViewModel(
  run: RunStatusResponse | null,
  chart: ChartSeriesPayload | null,
): {
  hasResult: boolean;
  hasError: boolean;
  candleCount: number;
  equityPoints: number;
  statusTone: string;
};
