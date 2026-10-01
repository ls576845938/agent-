import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {useSearchParams} from 'react-router-dom';
import {
  Alarm,
  ArrowCounterClockwise,
  ArrowClockwise,
  ArrowsOut,
  Camera,
  CaretDown,
  ChartBar,
  ChartLineUp,
  CheckCircle,
  Clock,
  Cursor,
  CurrencyBtc,
  EyeSlash,
  GearSix,
  List,
  Lock,
  MagnifyingGlass,
  Pause,
  PencilLine,
  Play,
  Ruler,
  ShieldCheck,
  SlidersHorizontal,
  SquaresFour,
  Target,
  TextT,
  Trash,
  TrendUp,
  WarningCircle,
  WifiSlash,
  X,
} from '@phosphor-icons/react';

import {ApiError, apiGet, apiPost} from '../lib/api';
import {strategyPresentationName} from '../lib/strategy-presentation';
import type {ChartSeriesPayload, RunStatusResponse, StrategyInfo, Summary} from '../lib/view-model';
import {frontendIdentity} from '../frontendIdentity';

import DemoTradingConsole from './crypto/DemoTradingConsole';
import {cryptoWorkspaceAccess, type WorkspaceHealth} from './crypto/workspace-access';
import {accountFactsView, finiteAccountNumber} from './crypto/account-facts-view';
import {useDemoOperatorV2} from './crypto/demo-operator-v2';
import type {
  BacktestSnapshot,
  DemoBill,
  DemoFill,
  DemoOrder,
  DemoPosition,
  DemoRuntimeStatus,
  PrivateReadonlyObservationProjection,
  PublicMarketTicker,
  PublicMarketView,
  PublicMarketStreamEvent,
} from './crypto/demo-types';
import PublicDepthPanel from './crypto/PublicDepthPanel';
import StrategyTesterReport from './crypto/StrategyTesterReport';
import type {CryptoBacktestConfig, CryptoBacktestPhase} from './crypto/CryptoStrategyEditor';
import BtcResearchArchive, {BTC_ROLLOVER_ARCHIVE} from './crypto/BtcResearchArchive';
import TradingViewChart, {type TradingCandle, type TradingMarker} from './crypto/TradingViewChart';
import type {CanonicalBacktestReport, CanonicalTrade, ChartDrawing, DrawingTool} from './crypto/canonical-report-types';
import type {
  BTCStrategyHistoryResponse,
  BTCStrategyReportTab,
} from './crypto/strategy-history-types';
import {
  readLocalBacktestSnapshots,
  writeLocalBacktestSnapshots,
} from './crypto/user-backtest-strategy-catalog';

type BottomTab = 'tester' | 'orders' | 'fills' | 'positions' | 'costs' | 'audit';
type ChartMode = 'market' | 'canonical' | 'backtest';
type ToolbarMenu = 'symbol' | 'timeframe' | 'chart-type' | 'indicators' | 'alerts' | 'layout' | 'settings' | '';
const MARKET_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d', '1w', '1M'] as const;
const VISUAL_TRADE_ID_CAPACITY = 2_000;
type Timeframe = typeof MARKET_TIMEFRAMES[number];
type WorkspaceLayout = 'split' | 'chart' | 'report';
type ValueEvent = {target: {value: string}};
type ConsolePointerEvent = {
  pointerId: number;
  clientX: number;
  currentTarget: HTMLDivElement;
  preventDefault: () => void;
};
type ConsoleKeyboardEvent = {key: string; preventDefault: () => void};
type StrategyTesterPointerEvent = {
  pointerId: number;
  clientY: number;
  currentTarget: HTMLDivElement;
  preventDefault: () => void;
};
type DomainBlocker = {
  code: string;
  category: string;
  owner: string;
  next_executable_action: string;
};
type BTCCurrentHeadDomainReadModel = {
  status: string;
  current_stage: string;
  source_head: string;
  freshness: string;
  decision: string;
  gate_decision: string;
  readiness_class: string;
  promotion_evidence_ready: boolean;
  paper_ready: boolean;
  live_ready: boolean;
  blocker_count: number;
  required_blocker_count: number;
  required_blockers_sha256: string;
  required_blockers_preserved: boolean;
  required_blockers: string[];
  blockers: DomainBlocker[];
  safety: Record<string, boolean>;
};

const BTC_LEGACY_REQUIRED_BLOCKERS = [
  'btc_okx_websocket_client_dependency_missing',
  'real_timestamp_aligned_l2_missing',
  'btc_okx_l2_sequence_continuity_unverified',
  'l2_lt_30_natural_days',
  'btc_open_interest_history_not_verified_diagnostic_partial',
  'btc_okx_server_time_offset_exceeds_threshold',
  'manifest_data_schema_mismatch',
  'manifest_quality_status_not_pass',
  'l2_manifest_attestation_readiness_mismatch',
  'runtime_pointer_immutable_snapshot_not_published',
  'runtime_pointer_data_steward_attestation_required',
  'not_promotion_evidence',
  'owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing',
  'owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing',
  'owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing',
  'owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete',
  'owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing',
] as const;

const BTC_QUALITY_L2_REQUIRED_BLOCKERS = [
  'btc_okx_l2_history_below_30_natural_days',
  'btc_execution_latency_model_missing',
  'btc_queue_model_missing',
  'btc_okx_l2_natural_execution_observation_missing',
  'btc_okx_l2_two_sided_coverage_incomplete',
  'btc_private_ws_evidence_missing',
  'btc_real_funding_nonflat_fill_evidence_missing',
  'btc_paper_live_manual_approval_missing',
  'btc_open_interest_history_not_verified_diagnostic_partial',
  'not_promotion_evidence',
  'owner:btc_operations btc_next_stage:real_funding_cashflow_evidence_missing',
  'owner:btc_operations btc_next_stage:real_private_ws_reconciliation_evidence_missing',
  'owner:btc_observation btc_next_stage:real_non_flat_fill_evidence_missing',
  'owner:btc_observation btc_next_stage:natural_observation_window_30_60d_incomplete',
  'owner:architect/manual_reviewer btc_next_stage:manual_promotion_approval_missing',
  'btc_next_stage:ledger_positions_cash_pnl_receipts_missing',
  'btc_next_stage:replay_observe_only_offline_no_paper_queue',
] as const;

const BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS = [
  'btc_okx_native:promotion_evidence_current_head_rebuild_required',
  'btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing',
  'btc_okx_native:active_strategy_family_dependency_scope_missing',
  'btc_okx_native:effective_sample_regime_coverage_prereg_evidence_incomplete',
  'btc_okx_native:active_criteria_pointer_lineage_mismatch',
  'btc_okx_native:natural_strategy_runtime_non_flat_fill_sample_missing',
  'btc_okx_native:funding_cashflow_not_observed_in_demo_runtime',
  'btc_okx_native:private_ws_runtime_reconciliation_observation_incomplete',
  'btc_okx_native:25_hour_demo_observation_window_incomplete',
  'btc_okx_native:manual_promotion_approval_missing',
] as const;

const BTC_REQUIRED_BLOCKER_CONTRACTS = [
  {
    requiredBlockers: BTC_LEGACY_REQUIRED_BLOCKERS,
    sha256: 'd7e66f764b4f1c0a5ed19eed267d519ae662b3a3d09f125cdea649e1f2f8dd4f',
  },
  {
    requiredBlockers: BTC_QUALITY_L2_REQUIRED_BLOCKERS,
    sha256: 'f0e1ce43e7927f505d44ea2b1918bac3335868ec80681f1641e140c655dd7e36',
  },
  {
    requiredBlockers: BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS,
    sha256: 'cc0d8cbd8ff93afeab933d1b87bed493f667177aa1c9b1fdbe38a42a07ec65fa',
  },
] as const;

const BTC_SAFETY_KEYS = [
  'api_key_permission_reviewed',
  'approval_granted',
  'broker_access_allowed',
  'broker_calls_used',
  'broker_endpoint_accessed',
  'broker_endpoint_allowed',
  'broker_or_order_allowed',
  'credential_permissions_verified',
  'demo_allowed',
  'demo_order_submitted',
  'demo_trading_enabled',
  'live_allowed',
  'paper_allowed',
  'live_enabled',
  'live_order_allowed',
  'live_ready',
  'live_unlock_allowed',
  'manual_approval_recorded',
  'micro_live_allowed',
  'network_accessed',
  'oms_access_allowed',
  'order_endpoint_accessed',
  'order_endpoint_allowed',
  'order_endpoint_used',
  'order_submission_allowed',
  'paper_candidate_allowed',
  'paper_candidate_created',
  'paper_execution_authorized',
  'paper_order_intake_allowed',
  'paper_order_submitted',
  'paper_or_live_unlock_allowed',
  'paper_queue_write_allowed',
  'paper_queue_write_enabled',
  'paper_ready',
  'paper_start_allowed',
  'permission_evidence_ready',
  'permission_granted',
  'position_increase_allowed',
  'private_endpoint_accessed',
  'private_endpoint_allowed',
  'private_endpoint_used',
  'promotion_allowed',
  'promotion_evidence_ready',
  'real_order_submitted',
  'real_orders_enabled',
  'secret_access_allowed',
  'secrets_read',
  'strategy_skeleton_generated',
  'withdraw_allowed',
] as const;

const MAX_HISTORY = 8;
const CONSOLE_WIDTH_KEY = 'quantstation.btc.demo-console-width.v1';
const DEFAULT_CONSOLE_WIDTH = 376;
const MIN_CONSOLE_WIDTH = 320;
const MAX_CONSOLE_WIDTH = 720;
const MIN_CHART_WIDTH = 560;
const DRAWING_RAIL_WIDTH = 42;
const CONSOLE_SEPARATOR_WIDTH = 8;
const MIN_SIDE_BY_SIDE_WIDTH = DRAWING_RAIL_WIDTH + MIN_CHART_WIDTH + CONSOLE_SEPARATOR_WIDTH + MIN_CONSOLE_WIDTH;
const STRATEGY_TESTER_HEIGHT_KEY = 'quantstation.btc.strategy-tester-height.v1';
const DEFAULT_STRATEGY_TESTER_HEIGHT = 420;
const MIN_STRATEGY_TESTER_HEIGHT = 280;
const MAX_STRATEGY_TESTER_HEIGHT = 760;
const MIN_TOP_PANEL_HEIGHT = 420;
const RESIZABLE_VERTICAL_CHROME = 128;
const DOMAIN_READ_MODEL_PATH = '/api/research/btc/domain-read-model';
const DEMO_MARKET_VIEW_PATH = '/api/research/btc/demo-paper/market-view';
const DEMO_MARKET_TICKER_PATH = '/api/research/btc/demo-paper/market-ticker';
const BACKTEST_RESULT_POLL_INTERVAL_MS = 1_000;
const BACKTEST_RESULT_POLL_TIMEOUT_MS = 180_000;
const DEMO_MARKET_REFRESH_INTERVAL_MS = 10_000;
const DEMO_MARKET_REFRESH_MAX_BACKOFF_MS = 16_000;
const DEMO_MARKET_TICKER_INTERVAL_MS = 2_000;

let domainReadModelRequest: Promise<BTCCurrentHeadDomainReadModel> | null = null;
const demoMarketViewRequests = new Map<string, Promise<PublicMarketView>>();
const demoMarketTickerRequests = new Map<string, Promise<PublicMarketTicker>>();

function loadDemoMarketView(timeframe: Timeframe, path = DEMO_MARKET_VIEW_PATH): Promise<PublicMarketView> {
  const key = `${path}:${timeframe}`;
  const current = demoMarketViewRequests.get(key);
  if (current) return current;
  const request = apiGet<PublicMarketView>(
    `${path}?timeframe=${encodeURIComponent(timeframe)}&limit=300`,
    20_000,
  );
  demoMarketViewRequests.set(key, request);
  const clearRequest = () => {
    if (demoMarketViewRequests.get(key) === request) demoMarketViewRequests.delete(key);
  };
  void request.then(clearRequest, clearRequest);
  return request;
}

function loadDemoMarketTicker(path = DEMO_MARKET_TICKER_PATH): Promise<PublicMarketTicker> {
  const current = demoMarketTickerRequests.get(path);
  if (current) return current;
  const request = apiGet<PublicMarketTicker>(path, 8_000);
  demoMarketTickerRequests.set(path, request);
  const clearRequest = () => {
    if (demoMarketTickerRequests.get(path) === request) demoMarketTickerRequests.delete(path);
  };
  void request.then(clearRequest, clearRequest);
  return request;
}

function loadDomainReadModel(): Promise<BTCCurrentHeadDomainReadModel> {
  if (domainReadModelRequest === null) {
    const request = apiGet<BTCCurrentHeadDomainReadModel>(
      DOMAIN_READ_MODEL_PATH,
      10_000,
    );
    domainReadModelRequest = request;
    void request.then(
      () => {
        if (domainReadModelRequest === request) domainReadModelRequest = null;
      },
      () => {
        if (domainReadModelRequest === request) domainReadModelRequest = null;
      },
    );
  }
  return domainReadModelRequest;
}

function requiredBlockerCode(value: string): string {
  return value.startsWith('owner:') && value.includes(' ')
    ? value.slice(value.indexOf(' ') + 1)
    : value;
}

export type CryptoWorkspaceProps = {
  key?: string;
  health: WorkspaceHealth | null;
  strategies: StrategyInfo[];
  onToggleSidebar: () => void;
};

function dateInput(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function readHistory(): BacktestSnapshot[] {
  return readLocalBacktestSnapshots();
}

function clampConsoleWidth(value: number, maximum = MAX_CONSOLE_WIDTH): number {
  const safeMaximum = Math.max(MIN_CONSOLE_WIDTH, Math.min(MAX_CONSOLE_WIDTH, maximum));
  if (!Number.isFinite(value)) return Math.min(DEFAULT_CONSOLE_WIDTH, safeMaximum);
  return Math.min(safeMaximum, Math.max(MIN_CONSOLE_WIDTH, Math.round(value)));
}

function readConsoleWidth(): number {
  try {
    const stored = Number(localStorage.getItem(CONSOLE_WIDTH_KEY));
    return clampConsoleWidth(stored || DEFAULT_CONSOLE_WIDTH);
  } catch {
    return DEFAULT_CONSOLE_WIDTH;
  }
}

function clampStrategyTesterHeight(value: number, maximum = MAX_STRATEGY_TESTER_HEIGHT): number {
  const safeMaximum = Math.max(MIN_STRATEGY_TESTER_HEIGHT, Math.min(MAX_STRATEGY_TESTER_HEIGHT, maximum));
  if (!Number.isFinite(value)) return Math.min(DEFAULT_STRATEGY_TESTER_HEIGHT, safeMaximum);
  return Math.min(safeMaximum, Math.max(MIN_STRATEGY_TESTER_HEIGHT, Math.round(value)));
}

function readStrategyTesterHeight(): number {
  try {
    return clampStrategyTesterHeight(Number(localStorage.getItem(STRATEGY_TESTER_HEIGHT_KEY)) || DEFAULT_STRATEGY_TESTER_HEIGHT);
  } catch {
    return DEFAULT_STRATEGY_TESTER_HEIGHT;
  }
}

type StrategyWorkbenchBacktestRequest = {
  start?: string;
  end?: string;
  capital?: number;
  data_version?: string;
  strategy_id?: string;
  candidate_id?: string;
  strategy_version?: string;
  run_id?: string;
};

type StrategyWorkbenchBacktestResponse = {
  run_id: string;
  created_at?: string;
  completed_at?: string | null;
  status: string;
  request?: StrategyWorkbenchBacktestRequest;
  error?: string | null;
  report?: {
    summary?: Record<string, unknown>;
    chart?: Record<string, unknown>;
    strategy_details?: Array<Record<string, unknown>>;
    diagnostics?: Record<string, unknown>;
    report_scope?: string;
  } | null;
  safety?: Record<string, boolean>;
};

type StrategyWorkbenchVersionProjection = {
  version_id: string;
  latest_backtest?: StrategyWorkbenchBacktestResponse | null;
};

function finiteNumber(value: unknown): number | undefined {
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function normalizePointSeries(value: unknown): Array<{time: number; value: number}> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const record = recordValue(item);
    const time = finiteNumber(record.time ?? record.timestamp ?? record.ts);
    const point = finiteNumber(record.value ?? record.close ?? record.equity);
    return time !== undefined && point !== undefined ? [{time, value: point}] : [];
  });
}

function normalizeCandleSeries(value: unknown): ChartSeriesPayload['candles'] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const record = recordValue(item);
    const time = finiteNumber(record.time ?? record.timestamp ?? record.ts);
    const open = finiteNumber(record.open);
    const high = finiteNumber(record.high);
    const low = finiteNumber(record.low);
    const close = finiteNumber(record.close);
    return time !== undefined && open !== undefined && high !== undefined && low !== undefined && close !== undefined
      ? [{time, open, high, low, close}]
      : [];
  });
}

function normalizeMarkers(value: unknown): ChartSeriesPayload['markers'] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const record = recordValue(item);
    const time = finiteNumber(record.time ?? record.timestamp ?? record.ts);
    if (time === undefined) return [];
    return [{
      time,
      position: String(record.position ?? 'aboveBar'),
      color: String(record.color ?? '#8ab4f8'),
      shape: String(record.shape ?? 'circle'),
      text: String(record.text ?? ''),
    }];
  });
}

function normalizeStrategyWorkbenchResult(
  response: StrategyWorkbenchBacktestResponse,
  sourceLabel: string,
): {run: RunStatusResponse; chart: ChartSeriesPayload} {
  const report = response.report ?? {};
  const reportChart = report.chart ?? {};
  const summary = report.summary ? report.summary as unknown as Summary : null;
  const run: RunStatusResponse = {
    run_id: response.run_id,
    mode: 'research_only_registered_strategy_replay',
    status: response.status,
    created_at: response.created_at ?? new Date().toISOString(),
    completed_at: response.completed_at ?? null,
    error: response.error ?? null,
    summary,
    latest_weights: [],
    strategy_details: report.strategy_details ?? [],
    diagnostics: {
      ...recordValue(report.diagnostics),
      report_scope: report.report_scope ?? 'research_only',
      source_label: sourceLabel,
      safety: response.safety ?? {},
      ledger_equity_consistent: recordValue(report.diagnostics).ledger_equity_consistent === true,
    },
  };
  const chart: ChartSeriesPayload = {
    candles: normalizeCandleSeries(reportChart.candles),
    markers: normalizeMarkers(reportChart.markers),
    equity: normalizePointSeries(reportChart.equity),
    drawdown: normalizePointSeries(reportChart.drawdown),
    exposure: normalizePointSeries(reportChart.exposure),
    net_units: normalizePointSeries(reportChart.net_units),
    turnover: normalizePointSeries(reportChart.turnover),
    leverage: normalizePointSeries(reportChart.leverage),
  };
  return {run, chart};
}

function backtestResponseMatchesRequest(
  response: StrategyWorkbenchBacktestResponse,
  config: CryptoBacktestConfig,
  strategy: {strategy_id: string; candidate_id: string; strategy_version: string},
): boolean {
  const request = response.request;
  return Boolean(
    request
    && request.start === `${config.start}T00:00:00Z`
    && request.end === `${config.end}T23:00:00Z`
    && Number(request.capital) === config.capital
    && request.data_version === ''
    && request.strategy_id === strategy.strategy_id
    && request.candidate_id === strategy.candidate_id
    && request.strategy_version === strategy.strategy_version,
  );
}

function isBacktestTransportTimeout(error: unknown): boolean {
  return error instanceof ApiError && error.status === 408;
}

async function pollBacktestResult(
  versionPath: string,
  versionId: string,
  previousRunId: string,
  config: CryptoBacktestConfig,
  strategy: {strategy_id: string; candidate_id: string; strategy_version: string},
): Promise<StrategyWorkbenchBacktestResponse> {
  const deadline = Date.now() + BACKTEST_RESULT_POLL_TIMEOUT_MS;
  let lastError = '';
  while (Date.now() < deadline) {
    try {
      const projection = await apiGet<StrategyWorkbenchVersionProjection>(
        versionPath,
        Math.max(1, Math.min(20_000, deadline - Date.now())),
      );
      if (projection.version_id !== versionId) {
        throw new Error('回测版本身份与本次请求不一致；已停止只读确认。');
      }
      const latest = projection.latest_backtest;
      if (
        latest
        && latest.run_id !== previousRunId
        && backtestResponseMatchesRequest(latest, config, strategy)
        && (latest.status === 'completed' || latest.status === 'failed')
      ) {
        return latest;
      }
    } catch (error) {
      lastError = errorMessage(error);
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await new Promise((resolve) => setTimeout(resolve, Math.min(BACKTEST_RESULT_POLL_INTERVAL_MS, remaining)));
  }
  throw new Error(
    lastError
      ? `后端回测结果在 180 秒内未收敛；已保持单次 POST，未重发。最后一次只读确认：${lastError}`
      : '后端回测结果在 180 秒内未收敛；已保持单次 POST，未重发。',
  );
}

function backtestResponseMatchesSnapshot(
  response: StrategyWorkbenchBacktestResponse,
  snapshot: BacktestSnapshot,
): boolean {
  const request = response.request;
  if (!request || request.strategy_id !== snapshot.strategyId || request.candidate_id !== snapshot.candidateId) return false;
  if (request.strategy_version !== snapshot.strategyVersion) return false;
  if (request.run_id && request.run_id !== snapshot.run.run_id) return false;
  if (!snapshot.request) return true;
  return request.start === snapshot.request.start
    && request.end === snapshot.request.end
    && Number(request.capital) === snapshot.request.capital
    && request.data_version === snapshot.request.dataVersion;
}

async function fetchPersistedBacktestReport(snapshot: BacktestSnapshot): Promise<{run: RunStatusResponse; chart: ChartSeriesPayload}> {
  if (!snapshot.versionId) throw new Error('本地 run 未记录 version_id；仅恢复摘要，未伪造回测报告。');
  const path = `/api/research/btc/strategy-versions/${encodeURIComponent(snapshot.versionId)}`;
  const projection = await apiGet<StrategyWorkbenchVersionProjection>(path, 15_000);
  if (projection.version_id !== snapshot.versionId) {
    throw new Error('GET 回测版本身份与本地 run 不一致；报告已隐藏。');
  }
  const latest = projection.latest_backtest;
  if (!latest || latest.run_id !== snapshot.run.run_id || latest.status !== 'completed') {
    throw new Error('GET 未返回匹配的 completed run；报告已隐藏。');
  }
  if (!backtestResponseMatchesSnapshot(latest, snapshot)) {
    throw new Error('GET 回测结果与本地 strategy/candidate/请求参数不一致；报告已隐藏。');
  }
  return normalizeStrategyWorkbenchResult(latest, 'GET-only local run restore');
}

export default function CryptoWorkspace({health, onToggleSidebar}: CryptoWorkspaceProps) {
  const access = cryptoWorkspaceAccess(health);
  const [searchParams, setSearchParams] = useSearchParams();
  const [demoCandidateId, setDemoCandidateId] = useState('');
  const [backtestCandidateId, setBacktestCandidateId] = useState('');
  const [selectedCandidateId, setSelectedCandidateId] = useState('');
  const [bootstrapRetry, setBootstrapRetry] = useState(0);
  const demoOperator = useDemoOperatorV2({refreshToken: bootstrapRetry, enabled: access.demoRuntime});
  const {
    catalog,
    status: demoStatus,
    statusError: demoStatusError,
    klines,
    loading,
    bootstrapFailed,
    bootstrapError: demoBootstrapError,
  } = demoOperator;
  const accountDock = accountDockView(demoStatus, demoStatusError);
  const [strategyHistory, setStrategyHistory] = useState<BTCStrategyHistoryResponse | null>(null);
  const [strategyHistoryError, setStrategyHistoryError] = useState('');
  const [selectedHistoricalRunId, setSelectedHistoricalRunId] = useState('');
  const [domainReadModel, setDomainReadModel] = useState<BTCCurrentHeadDomainReadModel | null>(null);
  const [domainReadModelError, setDomainReadModelError] = useState('');
  const [privateReadonlyObservation, setPrivateReadonlyObservation] = useState<PrivateReadonlyObservationProjection | null>(null);
  const [privateReadonlyObservationError, setPrivateReadonlyObservationError] = useState('');
  // URL/history selection never controls the candidate sent to the Demo
  // runtime.  The latter starts at the catalog default and is mutated only by
  // the Demo console itself.
  const [bottomTab, setBottomTab] = useState<BottomTab>('tester');
  const [chartMode, setChartMode] = useState<ChartMode>('market');
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [backtestChart, setBacktestChart] = useState<ChartSeriesPayload | null>(null);
  const [history, setHistory] = useState<BacktestSnapshot[]>(() => readHistory());
  const [backtestBusy, setBacktestBusy] = useState(false);
  const [marketView, setMarketView] = useState<PublicMarketView | null>(null);
  const [marketTicker, setMarketTicker] = useState<PublicMarketTicker | null>(null);
  const [marketViewError, setMarketViewError] = useState('');
  const [marketStream, setMarketStream] = useState<PublicMarketStreamEvent | null>(null);
  const [promotionLoading, setPromotionLoading] = useState(true);
  const [pageMessage, setPageMessage] = useState('');
  const [toolbarMenu, setToolbarMenu] = useState<ToolbarMenu>('');
  const [activeDrawingTool, setActiveDrawingTool] = useState<DrawingTool>('cursor');
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [redoDrawings, setRedoDrawings] = useState<ChartDrawing[]>([]);
  const [drawingsLocked, setDrawingsLocked] = useState(false);
  const [drawingsHidden, setDrawingsHidden] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [consoleWidth, setConsoleWidth] = useState(readConsoleWidth);
  const [consoleMaximum, setConsoleMaximum] = useState(MAX_CONSOLE_WIDTH);
  const [consoleStacked, setConsoleStacked] = useState(false);
  const [strategyTesterHeight, setStrategyTesterHeight] = useState(readStrategyTesterHeight);
  const [strategyTesterMaximum, setStrategyTesterMaximum] = useState(MAX_STRATEGY_TESTER_HEIGHT);
  const [chartExpanded, setChartExpanded] = useState(false);
  const [workspaceLayout, setWorkspaceLayout] = useState<WorkspaceLayout>('split');
  const [timeframe, setTimeframe] = useState<Timeframe>('1m');
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles');
  const [replayOpen, setReplayOpen] = useState(false);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replaySpeed, setReplaySpeed] = useState(500);
  const [chartSettings, setChartSettings] = useState({grid: true, crosshair: true});
  const [chartOverlays, setChartOverlays] = useState({volume: true, donchian: true, markers: true});
  const [lastChartRefreshUtc, setLastChartRefreshUtc] = useState('');
  const [backtestForm, setBacktestForm] = useState({
    startDate: dateInput(new Date(Date.now() - 730 * 86_400_000)),
    endDate: dateInput(new Date()),
    capital: 10_000,
    commissionRate: 0.0005,
    slippageBps: 5,
  });
  const historyRequestSequence = useRef(0);
  const chartModeIntentRef = useRef({historyIdentityKey: '', userSelected: false});
  const primaryGridRef = useRef<HTMLDivElement | null>(null);
  const marketViewRef = useRef<PublicMarketView | null>(null);
  const streamFrameRef = useRef<number | null>(null);
  const pendingMarketStreamRef = useRef<PublicMarketStreamEvent | null>(null);
  const pendingVisualTradesRef = useRef<Map<string, NonNullable<PublicMarketStreamEvent['trade']>>>(new Map());
  const visualTradeIdsRef = useRef<{order: string[]; seen: Set<string>}>({order: [], seen: new Set()});
  const consoleResizeRef = useRef<{pointerId: number; startX: number; startWidth: number} | null>(null);
  const strategyTesterResizeRef = useRef<{pointerId: number; startY: number; startHeight: number} | null>(null);
  const requestedStrategyId = searchParams.get('strategy_id') ?? '';
  const requestedCandidateId = searchParams.get('candidate_id') ?? '';
  const requestedPanel = searchParams.get('panel') ?? '';
  const requestedReportTab = validReportTab(searchParams.get('report_tab'));
  const requestedLocalRunId = searchParams.get('local_run_id') ?? '';
  const requestedResearchArchive = searchParams.get('research_archive') ?? '';
  const researchArchiveOpen = requestedResearchArchive === BTC_ROLLOVER_ARCHIVE.routeId;
  const requestedHistoryIdentity = requestedStrategyId && requestedCandidateId
    ? {strategy_id: requestedStrategyId, candidate_id: requestedCandidateId}
    : null;
  const requestedIdentityIncomplete = Boolean(requestedStrategyId || requestedCandidateId) && !requestedHistoryIdentity;
  const historyReportContext = researchArchiveOpen || Boolean(requestedHistoryIdentity);
  const applyPendingVisualTrades = (
    current: PublicMarketView | null,
    trades: Array<NonNullable<PublicMarketStreamEvent['trade']>>,
  ) => {
    if (!current) return current;
    let merged: PublicMarketView | null = current;
    for (const trade of trades) {
      if (claimVisualTradeId(visualTradeIdsRef.current, trade.trade_id)) {
        merged = mergeVisualTrade(merged, trade, timeframe);
      }
    }
    return merged;
  };

  useEffect(() => {
    document.body.classList.add('crypto-route-active');
    return () => document.body.classList.remove('crypto-route-active');
  }, []);

  useEffect(() => {
    if (!access.publicMarket) {
      setMarketViewError(access.marketUnavailable);
      return;
    }
    let active = true;
    let timer: number | null = null;
    let failureCount = 0;

    const schedule = (delayMs: number) => {
      if (!active) return;
      timer = window.setTimeout(refresh, delayMs);
    };

    const refresh = () => {
      if (!active) return;
      void loadDemoMarketView(timeframe, access.marketViewPath).then(
        (payload) => {
          if (!active) return;
          failureCount = 0;
          const mergedRest = mergeRestMarketView(marketViewRef.current, payload);
          const pendingTrades = [...pendingVisualTradesRef.current.values()];
          pendingVisualTradesRef.current.clear();
          const merged = applyPendingVisualTrades(mergedRest, pendingTrades);
          marketViewRef.current = merged;
          setMarketView(merged);
          setMarketViewError('');
          setLastChartRefreshUtc(new Date().toISOString());
        },
        (error) => {
          if (!active) return;
          failureCount = Math.min(failureCount + 1, 4);
          setMarketViewError(errorMessage(error));
          const lastGood = marketViewRef.current;
          if (lastGood) {
            const stale = {
              ...lastGood,
              stale: true,
              last_error_code: errorMessage(error),
            };
            marketViewRef.current = stale;
            setMarketView(stale);
          }
        },
      ).finally(() => {
        if (!active) return;
        const delay = failureCount === 0
          ? DEMO_MARKET_REFRESH_INTERVAL_MS
          : Math.min(
            DEMO_MARKET_REFRESH_MAX_BACKOFF_MS,
            DEMO_MARKET_REFRESH_INTERVAL_MS * 2 ** failureCount,
          );
        schedule(delay);
      });
    };
    refresh();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [timeframe, access.publicMarket, access.marketUnavailable, access.marketViewPath]);

  useEffect(() => {
    if (!access.publicMarket) return;
    let active = true;
    let timer: number | null = null;

    const refresh = () => {
      if (!active) return;
      void loadDemoMarketTicker(access.marketTickerPath).then(
        (payload) => {
          if (!active) return;
          setMarketTicker(payload);
          const merged = mergeVisualTicker(marketViewRef.current, payload, timeframe);
          if (merged) {
            marketViewRef.current = merged;
            setMarketView(merged);
            setLastChartRefreshUtc(new Date().toISOString());
          }
        },
        (error) => {
          if (!active) return;
          setMarketTicker((current) => current ? {
            ...current,
            stale: true,
            last_error_code: errorMessage(error),
          } : current);
        },
      ).finally(() => {
        if (active) timer = window.setTimeout(refresh, DEMO_MARKET_TICKER_INTERVAL_MS);
      });
    };
    refresh();
    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [timeframe, access.publicMarket, access.marketTickerPath]);

  useEffect(() => {
    if (!access.publicStream) return;
    const source = new EventSource(access.marketStreamPath);
    const consume = (event: Event) => {
      try {
        const next = JSON.parse((event as MessageEvent<string>).data) as PublicMarketStreamEvent;
        pendingMarketStreamRef.current = next;
        const trade = next.trade;
        if (trade?.trade_id) {
          const pendingTrades = pendingVisualTradesRef.current;
          if (!pendingTrades.has(trade.trade_id)) pendingTrades.set(trade.trade_id, trade);
          if (pendingTrades.size > VISUAL_TRADE_ID_CAPACITY) {
            const oldestPendingId = pendingTrades.keys().next().value;
            if (oldestPendingId) pendingTrades.delete(oldestPendingId);
          }
        }
      } catch {
        return;
      }
      if (streamFrameRef.current !== null) return;
      streamFrameRef.current = window.requestAnimationFrame(() => {
        streamFrameRef.current = null;
        const next = pendingMarketStreamRef.current;
        if (!next) return;
        setMarketStream(next);
        const current = marketViewRef.current;
        if (current?.timeframe === timeframe && pendingVisualTradesRef.current.size > 0) {
          const pendingTrades = [...pendingVisualTradesRef.current.values()];
          pendingVisualTradesRef.current.clear();
          const merged = applyPendingVisualTrades(current, pendingTrades);
          marketViewRef.current = merged;
          setMarketView(merged);
        }
      });
    };
    source.addEventListener('market', consume);
    source.onerror = () => setMarketStream((current) => current ? {...current, status: 'reconnecting'} : null);
    return () => {
      source.removeEventListener('market', consume);
      source.close();
      if (streamFrameRef.current !== null) window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
      pendingVisualTradesRef.current.clear();
    };
  }, [timeframe, access.publicStream, access.marketStreamPath]);

  useEffect(() => {
    try {
      localStorage.setItem(CONSOLE_WIDTH_KEY, String(consoleWidth));
    } catch {
      // Storage can be unavailable in hardened browser contexts; resizing remains session-local.
    }
  }, [consoleWidth]);

  useEffect(() => {
    try {
      localStorage.setItem(STRATEGY_TESTER_HEIGHT_KEY, String(strategyTesterHeight));
    } catch {
      // Storage can be unavailable; resizing still works for this session.
    }
  }, [strategyTesterHeight]);

  useEffect(() => {
    const updateConstraint = () => {
      const maximum = Math.max(
        MIN_STRATEGY_TESTER_HEIGHT,
        Math.min(MAX_STRATEGY_TESTER_HEIGHT, window.innerHeight - MIN_TOP_PANEL_HEIGHT - RESIZABLE_VERTICAL_CHROME),
      );
      setStrategyTesterMaximum(maximum);
      setStrategyTesterHeight((current) => clampStrategyTesterHeight(current, maximum));
    };
    updateConstraint();
    window.addEventListener('resize', updateConstraint);
    return () => window.removeEventListener('resize', updateConstraint);
  }, []);

  useEffect(() => {
    const grid = primaryGridRef.current;
    if (!grid) return undefined;
    const updateLayout = (width: number) => {
      const stacked = window.matchMedia('(max-width: 900px)').matches || width < MIN_SIDE_BY_SIDE_WIDTH;
      setConsoleStacked(stacked);
      if (stacked) return;
      const maximum = Math.min(
        MAX_CONSOLE_WIDTH,
        Math.max(MIN_CONSOLE_WIDTH, width - DRAWING_RAIL_WIDTH - CONSOLE_SEPARATOR_WIDTH - MIN_CHART_WIDTH),
      );
      setConsoleMaximum(maximum);
      setConsoleWidth((current) => clampConsoleWidth(current, maximum));
    };
    const observer = new ResizeObserver(([entry]) => updateLayout(entry.contentRect.width));
    observer.observe(grid);
    updateLayout(grid.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let active = true;
    setPageMessage('');
    setDomainReadModelError('');
    void loadDomainReadModel().then((payload) => {
      if (!active) return;
      setDomainReadModel(payload);
    }).catch((error) => {
      if (!active) return;
      setDomainReadModel(null);
      setDomainReadModelError(errorMessage(error));
    });
    return () => { active = false; };
  }, [bootstrapRetry]);

  useEffect(() => {
    // Research navigation never starts private observation or polls its projection.
    setPrivateReadonlyObservation(null);
    setPrivateReadonlyObservationError('未主动读取账户观测；需要独立的显式授权与有效 receipt。');
  }, [bootstrapRetry]);

  useEffect(() => {
    if (!catalog) return;
    const hasRequestedIdentity = Boolean(requestedStrategyId || requestedCandidateId);
    if (hasRequestedIdentity) {
      if (!requestedHistoryIdentity) {
        setSelectedCandidateId('');
        setStrategyHistory(null);
        setStrategyHistoryError(
          `strategy identity mismatch: ${requestedStrategyId || 'missing'}/${requestedCandidateId || 'missing'}`,
        );
        setPromotionLoading(false);
        return;
      }
      const requested = catalog.strategies.find(
        (item) => item.strategy_id === requestedStrategyId
          && item.candidate_id === requestedCandidateId,
      );
      setSelectedCandidateId(requested?.candidate_id ?? '');
      if (requestedPanel === 'backtest') setBottomTab('tester');
      return;
    }
    setSelectedCandidateId(String(catalog.default_candidate_id || ''));
  }, [
    catalog,
    requestedCandidateId,
    requestedPanel,
    requestedStrategyId,
  ]);

  useEffect(() => {
    if (!catalog) return;
    const defaultCandidate = catalog.default_candidate_id;
    setDemoCandidateId((current) => (
      current && catalog.strategies.some(
        (item) => item.candidate_id === current && item.demo_selectable,
      )
        ? current
        : defaultCandidate
    ));
  }, [catalog]);

  useEffect(() => {
    if (!catalog) return;
    setBacktestCandidateId((current) => (
      current && catalog.strategies.some((item) => item.candidate_id === current)
        ? current
        : String(catalog.default_candidate_id || '')
    ));
  }, [catalog]);

  const selectedSpec = useMemo(
    () => catalog?.strategies.find((item) => item.candidate_id === selectedCandidateId) ?? null,
    [catalog?.strategies, selectedCandidateId],
  );
  const runningSpec = useMemo(() => {
    if (demoStatus?.operator_control?.session_active !== true) return null;
    return catalog?.strategies.find((item) => (
      item.strategy_id === demoStatus.strategy.strategy_id
      && item.candidate_id === demoStatus.strategy.candidate_id
    )) ?? null;
  }, [catalog?.strategies, demoStatus?.operator_control?.session_active, demoStatus?.strategy.candidate_id, demoStatus?.strategy.strategy_id]);
  const demoOperatorControl = demoStatus?.operator_control;
  const runtimeVisibilityTone = demoOperatorControl?.lifecycle === 'running'
    ? 'running'
    : ['critical', 'danger'].includes(demoOperatorControl?.incident.severity ?? '')
      ? 'blocked'
      : demoOperatorControl?.incident.severity === 'warning'
        ? 'warning'
        : 'stopped';
  const historyIdentity = requestedHistoryIdentity ?? (selectedSpec ? {
    strategy_id: selectedSpec.strategy_id,
    candidate_id: selectedSpec.candidate_id,
  } : null);
  const historyIdentityKey = historyIdentity
    ? `${historyIdentity.strategy_id}:${historyIdentity.candidate_id}`
    : '';
  const backtestSpec = useMemo(
    () => catalog?.strategies.find((item) => item.candidate_id === backtestCandidateId) ?? null,
    [backtestCandidateId, catalog?.strategies],
  );
  const requestedLocalSnapshot = useMemo(() => {
    if (!requestedLocalRunId || !requestedHistoryIdentity) return null;
    return history.find((item) => (
      item.run.run_id === requestedLocalRunId
      && item.run.status === 'completed'
      && item.strategyId === requestedHistoryIdentity.strategy_id
      && item.candidateId === requestedHistoryIdentity.candidate_id
      && (
        !item.paramsHash
        || selectedSpec?.strategy_id !== requestedHistoryIdentity.strategy_id
        || selectedSpec?.candidate_id !== requestedHistoryIdentity.candidate_id
         || !selectedSpec?.params_hash
         || item.paramsHash === selectedSpec?.params_hash
      )
    )) ?? null;
  }, [
    history,
    requestedCandidateId,
    requestedLocalRunId,
    requestedStrategyId,
    selectedSpec?.params_hash,
  ]);
  useEffect(() => {
    if (!access.demoRuntime) return;
    if (!requestedLocalSnapshot || run?.run_id === requestedLocalSnapshot.run.run_id) return;
    setBottomTab('tester');
    let active = true;
    const restoreSummaryOnly = (detail: string) => {
      if (!active) return;
      setRun(requestedLocalSnapshot.run);
      setBacktestChart(null);
      setChartMode('market');
      setPageMessage([
        '本地 completed run 摘要已恢复；未显示或伪造回测曲线。',
        detail,
        !requestedLocalSnapshot.paramsHash && selectedSpec?.params_hash ? '旧快照未记录 params hash；参数身份未知，未声明与当前参数匹配。' : '',
      ].filter(Boolean).join(' '));
    };
    if (requestedLocalSnapshot.chart) {
      setRun(requestedLocalSnapshot.run);
      setBacktestChart(requestedLocalSnapshot.chart);
      setChartMode('backtest');
      setPageMessage('');
    } else if (!requestedLocalSnapshot.versionId) {
      restoreSummaryOnly('旧快照未记录 version_id；未发起任何 POST。');
    } else {
      setPageMessage('正在通过 GET-only 恢复本地 completed run；未重发回测请求。');
      void fetchPersistedBacktestReport(requestedLocalSnapshot)
        .then((restored) => {
          if (!active) return;
          setRun(restored.run);
          setBacktestChart(restored.chart);
          setChartMode('backtest');
          setPageMessage('');
        })
        .catch((error) => {
          restoreSummaryOnly(`GET-only 恢复失败：${errorMessage(error)}`);
        });
    }
    return () => { active = false; };
  }, [
    access.demoRuntime,
    requestedLocalSnapshot,
    run?.run_id,
    selectedSpec?.params_hash,
  ]);
  useEffect(() => {
    if (chartModeIntentRef.current.historyIdentityKey === historyIdentityKey) return;
    chartModeIntentRef.current = {historyIdentityKey, userSelected: false};
  }, [historyIdentityKey]);

  useEffect(() => {
    const sequence = ++historyRequestSequence.current;
    if (!access.demoRuntime) {
      setPromotionLoading(false);
      return;
    }
    if (requestedLocalSnapshot) {
      setStrategyHistory(null);
      setStrategyHistoryError('');
      setSelectedHistoricalRunId('');
      setPromotionLoading(false);
      return;
    }
    setRun(null);
    setBacktestChart(null);
    setChartMode((current) => current === 'backtest' ? 'market' : current);
    if (requestedIdentityIncomplete) {
      setStrategyHistory(null);
      setStrategyHistoryError(
        `strategy identity mismatch: ${requestedStrategyId || 'missing'}/${requestedCandidateId || 'missing'}`,
      );
      setPromotionLoading(false);
      return;
    }
    if (!historyIdentity) {
      setStrategyHistory(null);
      setPromotionLoading(false);
      return;
    }
    const identityChanged = strategyHistory?.strategy_id !== historyIdentity.strategy_id
      || strategyHistory?.candidate_id !== historyIdentity.candidate_id;
    const selectedRun = identityChanged ? '' : selectedHistoricalRunId;
    if (identityChanged && selectedHistoricalRunId) setSelectedHistoricalRunId('');
    setPromotionLoading(true);
    setStrategyHistoryError('');
    const endpoint = `/api/research/btc/strategy-history/${encodeURIComponent(historyIdentity.strategy_id)}/${encodeURIComponent(historyIdentity.candidate_id)}${selectedRun ? `?run_id=${encodeURIComponent(selectedRun)}` : ''}`;
    void apiGet<BTCStrategyHistoryResponse>(endpoint, 15_000)
      .then((payload) => {
        if (historyRequestSequence.current !== sequence) return;
        if (
          payload.strategy_id !== historyIdentity.strategy_id
          || payload.candidate_id !== historyIdentity.candidate_id
          || payload.canonical?.strategy_identity === null
          || recordValue(payload.canonical?.strategy_identity).strategy_id !== historyIdentity.strategy_id
          || recordValue(payload.canonical?.strategy_identity).candidate_id !== historyIdentity.candidate_id
        ) {
          setStrategyHistory(null);
          setStrategyHistoryError('strategy history response identity mismatch; report hidden fail-closed');
          return;
        }
        setStrategyHistory(payload);
        setSelectedHistoricalRunId(payload.selected_run_id);
        if (
          chartModeIntentRef.current.historyIdentityKey === historyIdentityKey
          && !chartModeIntentRef.current.userSelected
        ) {
          setChartMode('canonical');
        }
      })
      .catch((error) => {
        if (historyRequestSequence.current !== sequence) return;
        setStrategyHistory(null);
        setStrategyHistoryError(errorMessage(error));
      })
      .finally(() => {
        if (historyRequestSequence.current === sequence) setPromotionLoading(false);
      });
  }, [
    access.demoRuntime,
    historyIdentity?.candidate_id,
    historyIdentity?.strategy_id,
    historyIdentityKey,
    requestedCandidateId,
    requestedIdentityIncomplete,
    requestedStrategyId,
    requestedLocalSnapshot,
    selectedHistoricalRunId,
  ]);
  const selectChartMode = (mode: ChartMode) => {
    chartModeIntentRef.current = {historyIdentityKey, userSelected: true};
    setChartMode(mode);
  };
  const canonical = strategyHistory?.canonical ?? null;
  const canonicalReport = strategyHistory?.canonical_report ?? null;
  const completedCandles = useMemo<TradingCandle[]>(() => (klines?.rows ?? []).map((row) => ({
    time: Math.floor(row.open_time_ms / 1000),
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
    volume: row.volume,
  })).sort((left, right) => left.time - right.time), [klines?.rows]);
  const marketCandles = useMemo<TradingCandle[]>(() => (marketView?.candles ?? []).map((row) => ({
    time: Math.floor(row.open_time_ms / 1000),
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
    volume: row.volume,
    in_progress: row.in_progress,
  })).sort((left, right) => left.time - right.time), [marketView?.candles]);
  const backtestCandles = useMemo<TradingCandle[]>(() => (backtestChart?.candles ?? []).map((item) => ({...item})), [backtestChart?.candles]);
  const demoMarkers = useMemo<TradingMarker[]>(() => fillMarkers(
    demoStatus?.exchange.fills ?? [],
    marketCandles,
    timeframe,
  ), [demoStatus?.exchange.fills, marketCandles, timeframe]);
  const backtestMarkers = useMemo<TradingMarker[]>(() => (backtestChart?.markers ?? []).map((item) => ({
    time: item.time,
    position: item.position === 'aboveBar' ? 'aboveBar' : 'belowBar',
    color: item.color,
    shape: item.shape === 'arrowDown' ? 'arrowDown' : 'arrowUp',
    text: item.text,
  })), [backtestChart?.markers]);
  const canonicalMarkers = useMemo<TradingMarker[]>(
    () => canonicalTradeMarkers(canonicalReport?.series.trades ?? [], completedCandles),
    [canonicalReport?.series.trades, completedCandles],
  );
  const canonicalEventCount = (canonicalReport?.series.trades.length ?? 0) * 2;
  const sourceCandles = chartMode === 'backtest'
    ? backtestCandles
    : chartMode === 'canonical'
      ? completedCandles
      : marketCandles;
  const sourceMarkers = chartMode === 'backtest'
    ? backtestMarkers
    : chartMode === 'canonical'
      ? canonicalMarkers
      : demoMarkers;
  const timeframeCandles = useMemo(() => resampleCandles(sourceCandles, timeframe), [sourceCandles, timeframe]);
  const timeframeMarkers = useMemo(() => resampleMarkers(sourceMarkers, timeframe), [sourceMarkers, timeframe]);
  const activeCandles = replayOpen ? timeframeCandles.slice(0, Math.max(1, replayIndex)) : timeframeCandles;
  const replayLastTime = activeCandles.at(-1)?.time ?? 0;
  const activeMarkers = replayOpen ? timeframeMarkers.filter((marker) => marker.time <= replayLastTime) : timeframeMarkers;
  const latest = activeCandles.at(-1);
  const prior = activeCandles.at(-2);
  const changePct = latest && prior && prior.close ? (latest.close / prior.close - 1) * 100 : 0;
  const marketVisualCandle = marketCandles.at(-1);
  const marketPriorCandle = marketCandles.at(-2);
  const publicStreamDepth = marketStream?.status === 'live' ? marketStream.depth : null;
  const publicBookDepth = publicStreamDepth ?? marketView?.depth ?? null;
  const publicBookBid = marketTicker?.ticker.bid ?? publicBookDepth?.bids[0]?.price ?? marketView?.ticker.bid;
  const publicBookAsk = marketTicker?.ticker.ask ?? publicBookDepth?.asks[0]?.price ?? marketView?.ticker.ask;
  const publicLast = marketVisualCandle?.close ?? Number(marketView?.ticker.last);
  const marketChangePct = marketVisualCandle && marketPriorCandle && marketPriorCandle.close
    ? (marketVisualCandle.close / marketPriorCandle.close - 1) * 100
    : 0;
  const summaryCandle = chartMode === 'market' ? marketVisualCandle : latest;
  const summaryChangePct = chartMode === 'market' ? marketChangePct : changePct;
  const summaryIsVisual = chartMode === 'market' && marketVisualCandle?.in_progress === true;
  const canonicalFreshness = nestedText(canonical, 'artifact_freshness', 'status') || nestedText(canonical, 'freshness', 'status') || nestedText(canonical, 'status') || 'unavailable';
  const canonicalIdentity = recordValue(canonical?.strategy_identity);
  const canonicalFreshnessRecord = recordValue(canonical?.artifact_freshness);
  const canonicalCurrentHead = canonicalFreshnessRecord.current_head_match === true;
  const promotionReadinessBlockers = [...new Set(arrayStrings(canonical?.promotion_readiness_blockers))];
  const canonicalBlockers = [...new Set([
    ...arrayStrings(canonical?.backtest_blockers),
    ...promotionReadinessBlockers,
    ...(canonicalReport?.blockers ?? []),
  ])];
  const strategySignalReady = klines?.strategy_signal_compatible === true && klines.freshness_status === 'pass';
  const researchBacktestReady = access.demoRuntime && Boolean(backtestSpec) && !backtestBusy;
  const klineFresh = klines?.freshness_status === 'pass';
  const marketTickerFresh = marketTicker?.stale === false;
  const marketViewFresh = marketView !== null && (
    marketStream?.status === 'live'
    || marketTickerFresh
    || marketView.stale === false
  );
  const chartSourceLabel = klines?.source_kind === 'okx_runtime_confirmed_completed_swap_1h'
    ? 'OKX runtime · latest completed 1h · confirmed'
    : klines?.source_kind === 'okx_shared_manifest_verified_completed_swap_1h'
      ? 'OKX shared baseline · completed 1h · SHA verified'
      : klines?.source_kind === 'okx_native_manifest_verified_completed_swap_1h'
        ? 'OKX SWAP · completed 1h · SHA verified'
    : klines?.source_kind === 'canonical_manifest_verified_mark_price_1h'
      ? 'Canonical mark-price · SHA verified'
      : 'OKX completed 1h · unavailable';
  const signalSourceLabel = `${textOr(canonicalIdentity.signal_data_venue, 'unknown')} · ${textOr(canonicalIdentity.signal_instrument, 'unknown')}`;
  const executionVenueLabel = `${textOr(canonicalIdentity.execution_venue, 'OKX')} · ${textOr(canonicalIdentity.execution_instrument, 'BTC-USDT-SWAP')} · Demo`;
  const chartModeLabel = chartMode === 'backtest'
    ? `浏览器本地回测 · ${run?.run_id ?? 'run unavailable'}`
    : chartMode === 'canonical'
      ? `Canonical fills · ${canonicalReport?.run_id ?? 'report unavailable'}`
      : chartMode === 'market'
        ? marketView
          ? `OKX public · ${timeframe} · ${marketView.stale ? (marketTickerFresh ? 'REST tick live' : 'STALE') : 'live'}${marketView.candles.at(-1)?.in_progress ? ' · in-progress bar' : ''}`
          : 'OKX public market · unavailable'
        : chartSourceLabel;
  const domainSafetyFalse = domainReadModel !== null
    && Object.keys(domainReadModel.safety ?? {}).length === BTC_SAFETY_KEYS.length
    && BTC_SAFETY_KEYS.every((key) => domainReadModel.safety?.[key] === false);
  const domainRequiredBlockerContract = domainReadModel === null
    ? undefined
    : BTC_REQUIRED_BLOCKER_CONTRACTS.find(
      (contract) => domainReadModel.required_blockers_sha256 === contract.sha256
        && domainReadModel.required_blocker_count === contract.requiredBlockers.length
        && Array.isArray(domainReadModel.required_blockers)
        && domainReadModel.required_blockers.length === contract.requiredBlockers.length
        && contract.requiredBlockers.every(
          (blocker, index) => domainReadModel.required_blockers[index] === blocker,
        ),
    );
  const domainBlockerCodes = new Set(
    Array.isArray(domainReadModel?.blockers)
      ? domainReadModel.blockers.map((blocker) => blocker.code)
      : [],
  );
  const domainRequiredBlockerPayloadConsistent = domainReadModel !== null
    && domainRequiredBlockerContract !== undefined
    && Array.isArray(domainReadModel.blockers)
    && domainReadModel.blocker_count === domainReadModel.blockers.length
    && domainRequiredBlockerContract.requiredBlockers.every(
      (blocker) => domainBlockerCodes.has(requiredBlockerCode(blocker)),
    );
  const domainRequiredBlockersExact = domainReadModel !== null
    && domainRequiredBlockerContract !== undefined
    && domainReadModel.required_blockers_preserved === true
    && domainRequiredBlockerPayloadConsistent;
  const domainHeadCurrent = domainReadModel !== null
    && frontendIdentity.canonical
    && domainReadModel.source_head === frontendIdentity.source_head;
  const domainReadModelAccepted = domainReadModel !== null
    && domainReadModel.status === 'blocked'
    && domainReadModel.current_stage === 'pending_next_stage_gate'
    && domainReadModel.freshness === 'current_head'
    && domainReadModel.decision === 'blocked_fail_closed_no_paper_no_live'
    && domainReadModel.gate_decision === 'blocked_fail_closed_no_paper_no_live'
    && domainReadModel.readiness_class === 'quality_checked'
    && domainReadModel.promotion_evidence_ready === false
    && domainReadModel.paper_ready === false
    && domainReadModel.live_ready === false
    && domainSafetyFalse
    && domainRequiredBlockersExact
    && domainHeadCurrent;
  const firstDomainBlocker = domainReadModel?.blockers?.[0] ?? null;

  const commitDrawing = (drawing: ChartDrawing) => {
    setDrawings((current) => [...current, drawing]);
    setRedoDrawings([]);
  };

  const undoDrawing = () => {
    const removed = drawings.at(-1);
    if (!removed) return;
    setDrawings(drawings.slice(0, -1));
    setRedoDrawings((current) => [removed, ...current]);
  };

  const redoDrawing = () => {
    const [restored, ...rest] = redoDrawings;
    if (!restored) return;
    setRedoDrawings(rest);
    setDrawings((current) => [...current, restored]);
  };

  const toggleReplay = () => {
    if (replayOpen) {
      setReplayOpen(false);
      setReplayPlaying(false);
      setReplayIndex(timeframeCandles.length);
      return;
    }
    if (timeframeCandles.length < 20) {
      setPageMessage('当前本地数据不足 20 根 K 线，无法启动研究回放。');
      return;
    }
    setReplayIndex(Math.max(20, Math.floor(timeframeCandles.length * 0.65)));
    setReplayOpen(true);
    setReplayPlaying(false);
    setToolbarMenu('');
  };

  useEffect(() => {
    if (!replayOpen || !replayPlaying) return undefined;
    const timer = window.setInterval(() => {
      setReplayIndex((current) => {
        if (current >= timeframeCandles.length) {
          setReplayPlaying(false);
          return timeframeCandles.length;
        }
        return current + 1;
      });
    }, replaySpeed);
    return () => window.clearInterval(timer);
  }, [replayOpen, replayPlaying, replaySpeed, timeframeCandles.length]);

  useEffect(() => {
    if (!replayOpen) return;
    setReplayIndex((current) => Math.min(Math.max(1, current), timeframeCandles.length));
  }, [replayOpen, timeframeCandles.length]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select')) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redoDrawing();
        else undoDrawing();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redoDrawing();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  const runBacktest = async (config: CryptoBacktestConfig, onPhase: (phase: CryptoBacktestPhase) => void) => {
    if (!access.demoRuntime) return;
    if (!backtestSpec) return;
    setBacktestBusy(true);
    setPageMessage('');
    try {
      const versionPath = `/api/research/btc/strategy-versions/${encodeURIComponent(config.versionId)}`;
      const previousVersion = await apiGet<StrategyWorkbenchVersionProjection>(versionPath, 15_000);
      if (previousVersion.version_id !== config.versionId) {
        throw new Error('回测版本身份与本次请求不一致；已拒绝执行。');
      }
      const previousRunId = previousVersion.latest_backtest?.run_id ?? '';
      setBacktestForm((current) => ({...current, startDate: config.start, endDate: config.end, capital: config.capital}));
      onPhase('submitting');
      onPhase('computing');
      const requestPayload = {
        start: `${config.start}T00:00:00Z`,
        end: `${config.end}T23:00:00Z`,
        capital: config.capital,
        data_version: '',
      };
      let response: StrategyWorkbenchBacktestResponse;
      try {
        response = await apiPost<StrategyWorkbenchBacktestResponse>(
          `/api/research/btc/strategy-versions/${encodeURIComponent(config.versionId)}/backtests`,
          requestPayload,
        );
      } catch (error) {
        if (!isBacktestTransportTimeout(error)) throw error;
        setPageMessage('后端仍在计算，正在只读确认结果；仅 GET 轮询，未重发回测请求。');
        response = await pollBacktestResult(versionPath, config.versionId, previousRunId, config, backtestSpec);
        setPageMessage('');
      }
      if (response.run_id === previousRunId || !backtestResponseMatchesRequest(response, config, backtestSpec)) {
        throw new Error('回测结果与本次 strategy/candidate/时间范围/资金参数不一致；已拒绝展示。');
      }
      if (response.status !== 'completed' && response.status !== 'failed') {
        setPageMessage('后端仍在计算，正在只读确认结果；仅 GET 轮询，未重发回测请求。');
        response = await pollBacktestResult(versionPath, config.versionId, previousRunId, config, backtestSpec);
        setPageMessage('');
      }
      onPhase('loading_results');
      const normalized = normalizeStrategyWorkbenchResult(response, chartSourceLabel);
      const nextRun = normalized.run;
      const nextChart = normalized.chart;
      setRun(nextRun);
      if (nextRun.status !== 'completed') throw new Error(nextRun.error || `backtest status=${nextRun.status}`);
      setBacktestChart(nextChart);
      setChartMode('backtest');
      const snapshot: BacktestSnapshot = {
        run: nextRun,
        chart: nextChart,
        strategyId: backtestSpec.strategy_id,
        candidateId: backtestSpec.candidate_id,
        strategyVersion: backtestSpec.strategy_version,
        paramsHash: backtestSpec.params_hash,
        savedAt: new Date().toISOString(),
        versionId: config.versionId,
        request: {
          start: `${config.start}T00:00:00Z`,
          end: `${config.end}T23:00:00Z`,
          capital: config.capital,
          dataVersion: '',
        },
      };
      const nextHistory = [snapshot, ...history.filter((item) => item.run.run_id !== nextRun.run_id)].slice(0, MAX_HISTORY);
      const historyWrite = writeLocalBacktestSnapshots(nextHistory);
      setHistory(nextHistory);
      if (historyWrite.status === 'quota') {
        setPageMessage('回测已完成；浏览器存储空间不足，未保存本地历史快照。当前结果仍保留在本页面内。');
      } else if (historyWrite.status === 'error') {
        setPageMessage(`回测已完成；本地历史快照保存失败：${errorMessage(historyWrite.error)}。当前结果仍保留在本页面内。`);
      }
      onPhase('completed');
    } catch (error) {
      setPageMessage(errorMessage(error));
      onPhase('failed');
      throw error;
    } finally {
      setBacktestBusy(false);
    }
  };

  const restoreHistory = (snapshot: BacktestSnapshot) => {
    if (
      !historyIdentity
      || snapshot.strategyId !== historyIdentity.strategy_id
      || snapshot.candidateId !== historyIdentity.candidate_id
      || (snapshot.paramsHash && selectedSpec?.params_hash && snapshot.paramsHash !== selectedSpec.params_hash)
    ) {
      setPageMessage('本地 run 身份与当前候选不一致；已拒绝展示。');
      return;
    }
    if (!snapshot.chart && snapshot.versionId) {
      setBottomTab('tester');
      setPageMessage('正在通过 GET-only 恢复本地 completed run；未重发回测请求。');
      void fetchPersistedBacktestReport(snapshot)
        .then((restored) => {
          setRun(restored.run);
          setBacktestChart(restored.chart);
          setChartMode('backtest');
          setPageMessage('');
        })
        .catch((error) => {
          setRun(snapshot.run);
          setBacktestChart(null);
          setChartMode('market');
          setPageMessage(`本地 completed run 摘要已恢复；GET-only 恢复失败：${errorMessage(error)}；未显示或伪造回测曲线。`);
        });
      return;
    }
    setRun(snapshot.run);
    setBacktestChart(snapshot.chart);
    setChartMode(snapshot.chart ? 'backtest' : 'market');
    setPageMessage([
      snapshot.chart ? '' : '本地 completed run 摘要已恢复；chart 证据缺失，未显示或伪造回测曲线。',
      !snapshot.paramsHash && selectedSpec?.params_hash ? '旧快照未记录 params hash；参数身份未知，未声明与当前参数匹配。' : '',
    ].filter(Boolean).join(' '));
    setBottomTab('tester');
  };

  const selectDemoCandidate = (candidateId: string) => {
    const next = catalog?.strategies.find(
      (item) => item.candidate_id === candidateId && item.demo_selectable,
    );
    if (!next) {
      setPageMessage(`Demo candidate is not selectable: ${candidateId}`);
      return;
    }
    setDemoCandidateId(next.candidate_id);
  };

  const selectDemoStrategyLine = (strategyId: string) => {
    const next = catalog?.strategies.find(
      (item) => item.strategy_id === strategyId && item.demo_selectable,
    );
    if (next) selectDemoCandidate(next.candidate_id);
  };

  const selectBacktestCandidate = (candidateId: string) => {
    if (!catalog?.strategies.some((item) => item.candidate_id === candidateId)) return;
    setBacktestCandidateId(candidateId);
    setRun(null);
    setBacktestChart(null);
    setPageMessage('');
  };

  const candidateLocalHistory = useMemo(
    () => historyIdentity
      ? history.filter(
        (item) => item.strategyId === historyIdentity.strategy_id
          && item.candidateId === historyIdentity.candidate_id
          && (!item.paramsHash || !selectedSpec?.params_hash || item.paramsHash === selectedSpec.params_hash),
      )
      : [],
    [history, historyIdentity?.candidate_id, historyIdentity?.strategy_id, selectedSpec?.params_hash],
  );

  const effectiveConsoleOpen = consoleOpen && !researchArchiveOpen;
  const separatorVisible = effectiveConsoleOpen
    && !chartExpanded
    && workspaceLayout !== 'report'
    && !consoleStacked;
  const primaryGridStyle = {
    '--btc-console-width': `${consoleWidth}px`,
    '--btc-strategy-tester-height': `${strategyTesterHeight}px`,
  } as Record<string, string>;

  const resizeConsoleFromPointer = (event: ConsolePointerEvent) => {
    const resize = consoleResizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    setConsoleWidth(clampConsoleWidth(resize.startWidth + resize.startX - event.clientX, consoleMaximum));
  };

  const finishConsoleResize = (event: ConsolePointerEvent) => {
    if (consoleResizeRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    consoleResizeRef.current = null;
  };

  const resizeConsoleFromKeyboard = (event: ConsoleKeyboardEvent) => {
    let next: number | null = null;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') next = consoleWidth - 16;
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') next = consoleWidth + 16;
    if (event.key === 'Home') next = MIN_CONSOLE_WIDTH;
    if (event.key === 'End') next = consoleMaximum;
    if (next === null) return;
    event.preventDefault();
    setConsoleWidth(clampConsoleWidth(next, consoleMaximum));
  };

  const resizeStrategyTesterFromPointer = (event: StrategyTesterPointerEvent) => {
    const resize = strategyTesterResizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    setStrategyTesterHeight(clampStrategyTesterHeight(resize.startHeight + resize.startY - event.clientY, strategyTesterMaximum));
  };

  const finishStrategyTesterResize = (event: StrategyTesterPointerEvent) => {
    if (strategyTesterResizeRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    strategyTesterResizeRef.current = null;
  };

  const resizeStrategyTesterFromKeyboard = (event: ConsoleKeyboardEvent) => {
    let next: number | null = null;
    if (event.key === 'ArrowUp') next = strategyTesterHeight + 16;
    if (event.key === 'ArrowDown') next = strategyTesterHeight - 16;
    if (event.key === 'Home') next = MIN_STRATEGY_TESTER_HEIGHT;
    if (event.key === 'End') next = strategyTesterMaximum;
    if (next === null) return;
    event.preventDefault();
    setStrategyTesterHeight(clampStrategyTesterHeight(next, strategyTesterMaximum));
  };

  return (
    <main className={`crypto-tv-shell ${chartExpanded ? 'chart-expanded' : ''} ${researchArchiveOpen ? 'research-archive-open' : ''} layout-${workspaceLayout}`} data-testid="crypto-workspace">
      <header className="tv-global-toolbar">
        <div className="tv-toolbar-cluster">
          <button type="button" className="tv-icon-button" title="收起/展开工作台导航" onClick={onToggleSidebar}><List size={19} /></button>
          <button type="button" className={`tv-symbol-switcher ${toolbarMenu === 'symbol' ? 'active' : ''}`} onClick={() => setToolbarMenu((value) => value === 'symbol' ? '' : 'symbol')}><CurrencyBtc size={18} weight="fill" /><strong>BTCUSDT.P</strong><CaretDown size={13} /></button>
          <button type="button" className="tv-icon-button" title="搜索交易对" onClick={() => setToolbarMenu((value) => value === 'symbol' ? '' : 'symbol')}><MagnifyingGlass size={18} /></button>
          <span className="tv-toolbar-separator" />
          <button type="button" className={`tv-toolbar-button ${toolbarMenu === 'timeframe' ? 'active' : ''}`} onClick={() => setToolbarMenu((value) => value === 'timeframe' ? '' : 'timeframe')}>{timeframeLabel(timeframe)}<CaretDown size={12} /></button>
          <button type="button" className={`tv-icon-button ${toolbarMenu === 'chart-type' ? 'active' : ''}`} title="图表类型" onClick={() => setToolbarMenu((value) => value === 'chart-type' ? '' : 'chart-type')}>{chartType === 'candles' ? <ChartBar size={19} /> : <ChartLineUp size={19} />}</button>
          <button type="button" className={toolbarMenu === 'indicators' ? 'tv-toolbar-button active' : 'tv-toolbar-button'} onClick={() => setToolbarMenu((value) => value === 'indicators' ? '' : 'indicators')}><ChartLineUp size={18} />指标</button>
          <button type="button" className={toolbarMenu === 'alerts' ? 'tv-toolbar-button active' : 'tv-toolbar-button'} onClick={() => setToolbarMenu((value) => value === 'alerts' ? '' : 'alerts')}><Alarm size={18} />提醒</button>
          <button type="button" className={`tv-toolbar-button ${replayOpen ? 'active' : ''}`} onClick={toggleReplay}>{replayPlaying ? <Pause size={17} /> : <Play size={17} />}{replayOpen ? '退出回放' : '回放'}</button>
        </div>
        <div className="tv-toolbar-cluster tv-toolbar-actions">
          <button type="button" className="tv-icon-button" title="撤销绘图 Ctrl+Z" disabled={!drawings.length} onClick={undoDrawing}><ArrowCounterClockwise size={17} /></button>
          <button type="button" className="tv-icon-button" title="重做绘图 Ctrl+Y" disabled={!redoDrawings.length} onClick={redoDrawing}><ArrowClockwise size={17} /></button>
          <span className="tv-toolbar-separator" />
          <button type="button" className={`tv-icon-button ${toolbarMenu === 'layout' ? 'active' : ''}`} title="工作区布局" onClick={() => setToolbarMenu((value) => value === 'layout' ? '' : 'layout')}><SquaresFour size={18} /></button>
          <button type="button" className="tv-icon-button" title="下载图表快照" onClick={() => downloadChartCanvas()}><Camera size={18} /></button>
          <button type="button" className="tv-icon-button" title="图表全屏" onClick={() => setChartExpanded((value) => !value)}>{chartExpanded ? <X size={18} /> : <ArrowsOut size={18} />}</button>
          <button type="button" className={`tv-icon-button ${toolbarMenu === 'settings' ? 'active' : ''}`} title="图表设置" onClick={() => setToolbarMenu((value) => value === 'settings' ? '' : 'settings')}><GearSix size={18} /></button>
          <button type="button" disabled={researchArchiveOpen} className={`tv-trade-panel-toggle ${effectiveConsoleOpen ? 'active' : ''}`} title={researchArchiveOpen ? '历史危险参照视图保持只读，不显示 Demo 控制台' : '显示或隐藏 Demo 控制台'} onClick={() => setConsoleOpen((value) => !value)}><ShieldCheck size={18} />Demo 控制台</button>
        </div>

        {toolbarMenu === 'symbol' ? (
          <div className="tv-toolbar-popover tv-symbol-popover" data-testid="btc-symbol-menu">
            <div className="tv-popover-head"><div><MagnifyingGlass size={18} /><strong>交易品种</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            <input className="tv-symbol-search" autoFocus placeholder="搜索本地已验证交易品种" defaultValue="BTC" />
            <button type="button" className="tv-symbol-result active" onClick={() => setToolbarMenu('')}><CurrencyBtc size={20} weight="fill" /><span><strong>BTC-USDT-SWAP</strong><small>OKX · public visual market / confirmed 1h strategy</small></span><b>已选择</b></button>
            <p>当前工作台只开放 BTC-USDT-SWAP；不会用未验证品种替换策略输入。</p>
          </div>
        ) : null}
        {toolbarMenu === 'timeframe' ? (
          <div className="tv-toolbar-popover tv-option-popover" data-testid="btc-timeframe-menu">
            <div className="tv-popover-head"><div><ChartBar size={18} /><strong>图表周期</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            {MARKET_TIMEFRAMES.map((value) => <button key={value} type="button" className={timeframe === value ? 'active' : ''} onClick={() => { setTimeframe(value); setToolbarMenu(''); }}>{timeframeLabel(value)}<small>{value === '1h' ? '视觉实时；策略仍只用 confirmed 1h' : 'OKX public visual only'}</small></button>)}
          </div>
        ) : null}
        {toolbarMenu === 'chart-type' ? (
          <div className="tv-toolbar-popover tv-option-popover" data-testid="btc-chart-type-menu">
            <div className="tv-popover-head"><div><ChartLineUp size={18} /><strong>图表类型</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            <button type="button" className={chartType === 'candles' ? 'active' : ''} onClick={() => { setChartType('candles'); setToolbarMenu(''); }}><ChartBar size={18} />蜡烛图<small>OHLC</small></button>
            <button type="button" className={chartType === 'line' ? 'active' : ''} onClick={() => { setChartType('line'); setToolbarMenu(''); }}><ChartLineUp size={18} />收盘线<small>Close</small></button>
          </div>
        ) : null}

        {toolbarMenu === 'indicators' ? (
          <div className="tv-toolbar-popover" data-testid="btc-indicator-menu">
            <div className="tv-popover-head"><div><SlidersHorizontal size={18} /><strong>图表图层</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            <label><input type="checkbox" disabled={chartMode === 'market'} checked={chartMode !== 'market' && chartOverlays.donchian} onChange={() => setChartOverlays((value) => ({...value, donchian: !value.donchian}))} /><span>Donchian 120h 通道</span><small>{chartMode === 'market' ? '公共可视行情不可用；策略指标仅适用于 confirmed completed 1h' : '研究叠加'}</small></label>
            <label><input type="checkbox" checked={chartOverlays.volume} onChange={() => setChartOverlays((value) => ({...value, volume: !value.volume}))} /><span>成交量</span><small>本地 K 线</small></label>
            <label><input type="checkbox" checked={chartOverlays.markers} onChange={() => setChartOverlays((value) => ({...value, markers: !value.markers}))} /><span>成交 / 回测标记</span><small>{activeMarkers.length} 条</small></label>
          </div>
        ) : null}
        {toolbarMenu === 'alerts' ? (
          <div className="tv-toolbar-popover tv-alert-popover">
            <div className="tv-popover-head"><div><Alarm size={18} /><strong>研究提醒</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            <p>提醒只针对 completed bar、数据 freshness 和策略决策，不会直接调用交易所。</p>
            <button type="button" className="tv-popover-action" onClick={() => { setPageMessage('研究提醒保持只读；自动订单仍仅由已授权 Demo runtime 经 Risk 与 OMS 处理。'); setToolbarMenu(''); }}>确认提醒边界</button>
          </div>
        ) : null}
        {toolbarMenu === 'settings' ? (
          <div className="tv-toolbar-popover tv-settings-popover" data-testid="btc-chart-settings">
            <div className="tv-popover-head"><div><GearSix size={18} /><strong>图表设置</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            <label><input type="checkbox" checked={chartSettings.grid} onChange={() => setChartSettings((value) => ({...value, grid: !value.grid}))} /><span>网格线</span><small>{chartSettings.grid ? '显示' : '隐藏'}</small></label>
            <label><input type="checkbox" checked={chartSettings.crosshair} onChange={() => setChartSettings((value) => ({...value, crosshair: !value.crosshair}))} /><span>十字光标</span><small>{chartSettings.crosshair ? '显示' : '隐藏'}</small></label>
            <p>深色主题已按当前偏好锁定；设置仅影响视觉，不改变回测参数。</p>
          </div>
        ) : null}
        {toolbarMenu === 'layout' ? (
          <div className="tv-toolbar-popover tv-option-popover tv-layout-popover" data-testid="btc-layout-menu">
            <div className="tv-popover-head"><div><SquaresFour size={18} /><strong>工作区布局</strong></div><button type="button" onClick={() => setToolbarMenu('')}><X size={16} /></button></div>
            {([['split', '图表 + 报告'], ['chart', '图表聚焦'], ['report', '报告聚焦']] as Array<[WorkspaceLayout, string]>).map(([value, label]) => <button key={value} type="button" className={workspaceLayout === value ? 'active' : ''} onClick={() => { setWorkspaceLayout(value); setToolbarMenu(''); }}>{label}<small>{value === 'split' ? '完整研究台' : value === 'chart' ? '隐藏回测报告' : '隐藏图表与 Demo 控制台'}</small></button>)}
          </div>
        ) : null}
      </header>

      <section
        className={`panel ${domainReadModelAccepted ? '' : 'error-panel'} ${historyReportContext ? 'history-report-context' : ''}`}
        data-testid="btc-current-head-domain-read-model"
        aria-live="polite"
      >
        <div className="panel-header">
          <div>
            <p className="eyebrow">BTC CURRENT-HEAD READ MODEL · GET ONLY</p>
            <h2>{domainReadModelAccepted ? 'CURRENT HEAD · BLOCKED FAIL-CLOSED' : 'BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE'}</h2>
          </div>
          <span className="status-chip">{domainReadModel?.freshness ?? 'unavailable'}</span>
        </div>
        {domainReadModel && historyReportContext ? (
          <p>
            promotion/current-HEAD contract {domainReadModelAccepted ? 'blocked fail-closed' : 'unavailable or unsafe'}；
            历史研究报告仍可只读查看，但不解锁 Demo、paper、live、private 或 order。HEAD <code>{domainReadModel.source_head}</code>
          </p>
        ) : domainReadModel ? (
          <>
            <p>
              status={domainReadModel.status} · stage={domainReadModel.current_stage} ·
              decision={domainReadModel.decision} · gate={domainReadModel.gate_decision} ·
              readiness={domainReadModel.readiness_class}
            </p>
            <p>
              HEAD <code>{domainReadModel.source_head}</code> · frontend match={String(domainHeadCurrent)}
            </p>
            <p>
              blockers={domainReadModel.blocker_count} · required={domainReadModel.required_blocker_count} ·
              required preserved={String(domainReadModel.required_blockers_preserved)} ·
              safety false={Object.values(domainReadModel.safety ?? {}).filter((value) => value === false).length}/49
            </p>
            <p>
              promotion_evidence_ready={String(domainReadModel.promotion_evidence_ready)} ·
              paper_ready={String(domainReadModel.paper_ready)} · live_ready={String(domainReadModel.live_ready)}
            </p>
            <p>
              first blocker: <strong>{firstDomainBlocker?.code ?? 'missing'}</strong> ·
              owner={firstDomainBlocker?.owner ?? 'unknown'} ·
              action={firstDomainBlocker?.next_executable_action ?? 'missing'}
            </p>
          </>
        ) : (
          <p>{historyReportContext
            ? `promotion/current-HEAD contract unavailable；历史研究报告仍可只读查看，不解锁任何执行。${domainReadModelError ? ` ${domainReadModelError}` : ''}`
            : `current-head published contract request failed: ${domainReadModelError || 'loading'}`}</p>
        )}
      </section>

      <div
        ref={primaryGridRef}
        className={`tv-primary-grid ${effectiveConsoleOpen ? '' : 'console-collapsed'} ${consoleStacked ? 'console-stacked' : ''}`}
        style={primaryGridStyle}
      >
        <nav className="tv-drawing-rail" aria-label="图表工具">
          <button type="button" className={activeDrawingTool === 'cursor' ? 'active' : ''} title="光标" onClick={() => setActiveDrawingTool('cursor')}><Cursor size={19} /></button>
          <button type="button" disabled={drawingsLocked} className={activeDrawingTool === 'trend' ? 'active' : ''} title="趋势线" onClick={() => setActiveDrawingTool('trend')}><TrendUp size={19} /></button>
          <button type="button" disabled={drawingsLocked} className={activeDrawingTool === 'pencil' ? 'active' : ''} title="自由标注" onClick={() => setActiveDrawingTool('pencil')}><PencilLine size={19} /></button>
          <button type="button" disabled={drawingsLocked} className={activeDrawingTool === 'measure' ? 'active' : ''} title="价格与时间测量" onClick={() => setActiveDrawingTool('measure')}><Ruler size={19} /></button>
          <button type="button" disabled={drawingsLocked} className={activeDrawingTool === 'target' ? 'active' : ''} title="2:1 风险收益测量" onClick={() => setActiveDrawingTool('target')}><Target size={19} /></button>
          <button type="button" disabled={drawingsLocked} className={activeDrawingTool === 'text' ? 'active' : ''} title="文本注释" aria-pressed={activeDrawingTool === 'text'} onClick={() => setActiveDrawingTool((current) => current === 'text' ? 'cursor' : 'text')}><TextT size={19} /></button>
          <span className="tv-drawing-separator" />
          <button type="button" className={drawingsLocked ? 'active' : ''} title={drawingsLocked ? '解锁全部图形' : '锁定全部图形'} aria-pressed={drawingsLocked} onClick={() => { setDrawingsLocked((value) => !value); setActiveDrawingTool('cursor'); }}><Lock size={18} /></button>
          <button type="button" className={drawingsHidden ? 'active' : ''} title={drawingsHidden ? '显示全部图形' : '隐藏全部图形'} aria-pressed={drawingsHidden} onClick={() => setDrawingsHidden((value) => !value)}><EyeSlash size={18} /></button>
          <button type="button" disabled={!drawings.length} title="删除全部图形" onClick={() => { setDrawings([]); setRedoDrawings([]); }}><Trash size={18} /></button>
          <span className="tv-drawing-count">{drawings.length}</span>
        </nav>

        <section className="tv-chart-panel">
          <header className="tv-symbol-bar">
            <div className="tv-symbol-identity">
              <span className="tv-btc-icon"><CurrencyBtc size={22} weight="fill" /></span>
              <div><strong>BTC-USDT-SWAP</strong><span>执行标的 · OKX Demo · {timeframeLabel(timeframe)}</span></div>
              <span className="tv-demo-tag">DEMO</span>
            </div>
            <div className="tv-quote-pair" title="OKX BTC-USDT-SWAP 公共行情；运行时停机时不会回退为共享 baseline">
              <div className="sell"><strong>{formatQuote(publicBookBid)}</strong><span>OKX Public Bid</span></div>
              <small>{marketView ? `${price(publicLast)} · ${marketViewFresh ? (marketTickerFresh && marketView.stale ? 'REST LIVE' : 'LIVE') : 'STALE'}` : 'unavailable'}</small>
              <div className="buy"><strong>{formatQuote(publicBookAsk)}</strong><span>OKX Public Ask</span></div>
            </div>
            <div
              className={`tv-last-price ${summaryIsVisual ? 'visual' : 'completed'} ${(chartMode === 'market' ? marketViewFresh : klineFresh) ? '' : 'stale'} ${summaryChangePct >= 0 ? 'positive' : 'negative'}`}
              data-testid="btc-market-summary"
              data-market-last={Number.isFinite(publicLast) ? publicLast : ''}
              data-market-ticker-timestamp={marketTicker?.ticker.timestamp_ms ?? ''}
            >
              <small>{summaryIsVisual ? '实时 forming bar' : '最后 completed bar'}</small>
              <strong>{price(summaryCandle?.close)}</strong><span>{summaryChangePct >= 0 ? '+' : ''}{summaryChangePct.toFixed(2)}%</span>
              <time>{summaryIsVisual ? formatIso(new Date(marketView?.ticker.timestamp_ms ?? 0).toISOString()) : formatIso(klines?.sample_end ?? '') || '等待本地数据'}</time>
            </div>
            <div className="tv-ohlc-strip">
              <span>开 <b>{price(summaryCandle?.open)}</b></span><span>高 <b>{price(summaryCandle?.high)}</b></span><span>低 <b>{price(summaryCandle?.low)}</b></span><span>收 <b>{price(summaryCandle?.close)}</b></span><span>量 <b>{fixed(summaryCandle?.volume)}</b></span>
            </div>
            <div className="tv-safety-badges">
              <span className="safe">{access.demoRuntime ? 'Demo only' : access.mode === 'research_readonly' ? '仅研究 · 只读' : '模式待确认'}</span><span className="locked">Live locked</span><span>{health?.service ?? 'backend offline'}</span>
            </div>
          </header>
          <div className="tv-provenance-strip" data-testid="btc-provenance-strip">
            {!access.demoRuntime ? <>
              <ProvenanceItem label="行情来源" value={marketView ? 'OKX 公共 REST · 仅展示' : '公共行情待读取'} tone="neutral" />
              <ProvenanceItem label="策略信号" value="未绑定运行 · 不计算信号" tone="neutral" />
              <ProvenanceItem label="交易执行" value="未开放 · 账户未接入" tone="neutral" />
              <ProvenanceItem label="研究证据" value="从研究台按运行身份查看" tone="neutral" />
            </> : <>
            <ProvenanceItem label="信号源" value={signalSourceLabel} tone={signalSourceLabel.includes('unknown') ? 'blocked' : 'neutral'} />
            <ProvenanceItem label="K线源" value={chartSourceLabel} tone={klineFresh ? 'pass' : 'blocked'} />
            <ProvenanceItem label="执行场所" value={executionVenueLabel} tone="neutral" />
            <ProvenanceItem label="数据截至" value={formatIso(klines?.sample_end ?? '') || 'unavailable'} tone={klineFresh ? 'pass' : 'blocked'} />
            <ProvenanceItem label="证据 HEAD" value={canonicalCurrentHead ? 'current-HEAD match' : 'stale / mismatch'} tone={canonicalCurrentHead ? 'pass' : 'blocked'} />
            </>}
          </div>
          <div
            className={`tv-runtime-visibility ${runtimeVisibilityTone}`}
            data-testid="btc-runtime-visibility"
          >
            <div className="tv-runtime-state">
              <span className="tv-runtime-pulse" />
              <strong>{!access.demoRuntime ? access.title : demoOperatorControl?.incident.category === 'none'
                ? demoOperatorControl.lifecycle_label
                : demoOperatorControl?.incident.title ?? '后端控制契约不可用'}</strong>
              <small>{!access.demoRuntime ? access.summary : demoOperatorControl?.incident.summary ?? '前端不会从原始 runtime 字段推导运行权限'}</small>
            </div>
            <dl>
              <div><dt>浏览策略</dt><dd>{strategyPresentationName(selectedSpec?.display_name, selectedSpec?.strategy_id) || strategyPresentationName(requestedStrategyId) || '—'}</dd></div>
              <div><dt>运行策略</dt><dd>{strategyPresentationName(runningSpec?.display_name, runningSpec?.strategy_id) || strategyPresentationName(demoStatus?.strategy.display_name, demoStatus?.strategy.strategy_id) || '—'}</dd></div>
              <div><dt>Signal</dt><dd>{textOr(demoStatus?.signal.direction, '—')}</dd></div>
              <div><dt>Decision bar</dt><dd>{formatIso(textOr(demoStatus?.signal.decision_bar_close_utc ?? demoStatus?.runtime.last_processed_bar_close_utc, '')) || '—'}</dd></div>
              <div><dt>Heartbeat</dt><dd>{formatIso(demoStatus?.runtime.last_heartbeat_utc ?? '') || '—'}</dd></div>
              <div><dt>图表刷新</dt><dd>{formatIso(lastChartRefreshUtc) || '—'}</dd></div>
            </dl>
            <p>市场图来自 OKX public {timeframeLabel(timeframe)}；未完成 bar 仅视觉显示。公共可视行情关闭策略指标；策略与 Donchian 仅适用于 confirmed completed 1h。</p>
          </div>
          <div className="tv-chart-toolbar">
            <div className="tv-timeframes">{MARKET_TIMEFRAMES.map((value) => <button key={value} type="button" className={timeframe === value ? 'active' : ''} onClick={() => setTimeframe(value)}>{timeframeLabel(value)}</button>)}</div>
            <div className="tv-chart-modes">
              <button type="button" className={chartMode === 'market' ? 'active' : ''} onClick={() => selectChartMode('market')}>市场 K 线</button>
              <button type="button" className={chartMode === 'canonical' ? 'active' : ''} disabled={!canonicalEventCount} onClick={() => selectChartMode('canonical')}>Canonical 成交</button>
              <button type="button" className={chartMode === 'backtest' ? 'active' : ''} disabled={!backtestChart} onClick={() => selectChartMode('backtest')}>本地回测成交</button>
            </div>
            <div className="tv-chart-source"><span>{chartModeLabel}</span><span>{activeCandles.length} / {timeframeCandles.length} bars · {chartMode === 'market' ? (marketViewFresh ? (marketTickerFresh && marketView?.stale ? 'REST tick live' : 'live') : marketView ? 'stale' : 'unavailable') : klines?.freshness_status ?? 'unknown'}</span></div>
          </div>
          <div className="tv-chart-legend">{chartMode === 'market' ? <span>公共可视行情：策略指标不可用</span> : <><span className="blue">Donchian 120H</span><span className="purple">Lower band</span></>}<span>Volume</span><span>绘图：{drawingToolLabel(activeDrawingTool)} · {drawings.length}</span>{replayOpen ? <span className="replay">REPLAY</span> : null}</div>
          {(!marketViewFresh && chartMode === 'market') || chartMode === 'canonical' ? (
            <div className={`tv-chart-context-banner ${(!marketViewFresh && chartMode === 'market') ? 'blocked' : ''}`} data-testid="btc-chart-context">
              {(!marketViewFresh && chartMode === 'market') ? <WifiSlash size={15} /> : <CheckCircle size={15} />}
              <span>{chartMode === 'market' && !access.publicMarket
                ? access.marketUnavailable
                : chartMode === 'market'
                ? marketView?.stale
                  ? `OKX public 行情暂不可刷新，显示最后成功快照；${marketView.last_error_code || 'transport_error'}。`
                  : `OKX public 行情不可用；${marketViewError || '无可用缓存'}。不会回退为共享 baseline。`
                : '当前图层只显示 canonical fills 派生的入场/出场，不包含 Demo fills。'}</span>
              {chartMode === 'canonical' ? <strong>{canonicalMarkers.length} / {canonicalEventCount} 个事件落在当前 K 线窗口</strong> : null}
            </div>
          ) : null}
          {replayOpen ? (
            <div className="tv-replay-panel" data-testid="btc-replay-panel">
              <button type="button" onClick={() => setReplayIndex((value) => Math.max(1, value - 1))} title="后退一根"><ArrowCounterClockwise size={16} /></button>
              <button type="button" className="primary" onClick={() => setReplayPlaying((value) => !value)}>{replayPlaying ? <Pause size={16} weight="fill" /> : <Play size={16} weight="fill" />}{replayPlaying ? '暂停' : '播放'}</button>
              <button type="button" onClick={() => setReplayIndex((value) => Math.min(timeframeCandles.length, value + 1))} title="前进一根"><ArrowClockwise size={16} /></button>
              <input aria-label="回放位置" type="range" min="1" max={Math.max(1, timeframeCandles.length)} value={Math.max(1, replayIndex)} onChange={(event: ValueEvent) => { setReplayPlaying(false); setReplayIndex(Number(event.target.value)); }} />
              <strong>{replayIndex} / {timeframeCandles.length}</strong>
              <select aria-label="回放速度" value={replaySpeed} onChange={(event: ValueEvent) => setReplaySpeed(Number(event.target.value))}><option value={1000}>0.5x</option><option value={500}>1x</option><option value={200}>2.5x</option><option value={80}>6x</option></select>
              <button type="button" onClick={() => { setReplayIndex(timeframeCandles.length); setReplayPlaying(false); }}>跳到最新</button>
              <span>研究回放只改变本地显示，不触发 Demo / OMS / order。</span>
            </div>
          ) : null}
          <div className="tv-market-terminal-body">
            <TradingViewChart
              candles={activeCandles}
              markers={activeMarkers}
              loading={loading}
              showVolume={chartOverlays.volume}
              showMarkers={chartOverlays.markers}
              showDonchian={chartMode !== 'market' && chartOverlays.donchian}
              showGrid={chartSettings.grid}
              showCrosshair={chartSettings.crosshair}
              chartType={chartType}
              activeDrawingTool={activeDrawingTool}
              drawings={drawings}
              drawingsLocked={drawingsLocked}
              drawingsHidden={drawingsHidden}
              onCommitDrawing={commitDrawing}
            />
            <PublicDepthPanel stream={marketStream} marketView={marketView} ticker={marketView?.ticker ?? null} visualCandle={marketVisualCandle} />
          </div>
          <div className="tv-chart-foot">
            <span>TradingView Lightweight Charts · 本地只读</span>
            <span>{chartMode === 'market'
              ? `Public only=${marketView?.public_only ? 'PASS' : 'UNKNOWN'} · 策略兼容=${marketView?.strategy_signal_compatible ? 'NO (invalid)' : 'false'} · ticker ${formatQuote(marketView?.ticker.last)}`
              : `K 线：${klines?.read_only ? 'PASS' : 'UNKNOWN'} · Schema 写入：${klines?.schema_maintenance_performed ? 'YES' : 'NO'} · 截至 ${formatIso(klines?.sample_end ?? '')}`}</span>
            <span>成交标记 {activeMarkers.length}{chartMode === 'canonical' ? ` / Canonical ${canonicalEventCount}` : ''} · 绘图 {drawingsHidden ? '隐藏' : drawings.length} · {drawingsLocked ? '已锁定' : '可编辑'}</span>
          </div>
        </section>

        {separatorVisible ? (
          <div
            className="tv-console-separator"
            data-testid="btc-demo-console-separator"
            role="separator"
            aria-label="调整 Demo 控制台宽度"
            aria-orientation="vertical"
            aria-valuemin={MIN_CONSOLE_WIDTH}
            aria-valuemax={consoleMaximum}
            aria-valuenow={consoleWidth}
            aria-valuetext={`${consoleWidth} 像素；双击恢复 ${DEFAULT_CONSOLE_WIDTH} 像素`}
            tabIndex={0}
            title="拖拽或使用方向键调整；双击恢复默认宽度"
            onPointerDown={(event: ConsolePointerEvent) => {
              consoleResizeRef.current = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startWidth: consoleWidth,
              };
              event.currentTarget.setPointerCapture(event.pointerId);
              event.preventDefault();
            }}
            onPointerMove={resizeConsoleFromPointer}
            onPointerUp={finishConsoleResize}
            onPointerCancel={finishConsoleResize}
            onKeyDown={resizeConsoleFromKeyboard}
            onDoubleClick={() => setConsoleWidth(clampConsoleWidth(DEFAULT_CONSOLE_WIDTH, consoleMaximum))}
          />
        ) : null}

        {effectiveConsoleOpen ? (
          <DemoTradingConsole
            workspaceMode={access.mode}
            operatorController={demoOperator}
            catalog={catalog}
            status={demoStatus}
            statusError={demoStatusError}
            privateReadonlyObservation={privateReadonlyObservation}
            privateReadonlyObservationError={privateReadonlyObservationError}
            selectedCandidateId={demoCandidateId}
            onCandidateChange={selectDemoCandidate}
            onStrategyChange={selectDemoStrategyLine}
            runtimeSignalLoading={loading}
            runtimeSignalReady={strategySignalReady}
            runtimeSignalBlocker={strategySignalReady ? '' : '图表 / 历史 completed 1h freshness 未通过；仅影响图表与回测，不影响 Demo 启动，OKX Native 后端负责最终预检。'}
            promotionReadinessLoading={promotionLoading}
            promotionReadinessBlockers={promotionReadinessBlockers}
          />
        ) : null}

        {!chartExpanded && workspaceLayout === 'split' && bottomTab === 'tester' && !researchArchiveOpen && !consoleStacked ? (
        <div
          className="tv-strategy-tester-separator"
          data-testid="btc-strategy-tester-separator"
          role="separator"
          aria-label="调整策略测试器高度"
          aria-orientation="horizontal"
          aria-valuemin={MIN_STRATEGY_TESTER_HEIGHT}
          aria-valuemax={strategyTesterMaximum}
          aria-valuenow={strategyTesterHeight}
          aria-valuetext={`${strategyTesterHeight} 像素；双击恢复 ${DEFAULT_STRATEGY_TESTER_HEIGHT} 像素`}
          tabIndex={0}
          title="拖拽或使用上下方向键调整；双击恢复默认高度"
          onPointerDown={(event: StrategyTesterPointerEvent) => {
            strategyTesterResizeRef.current = {
              pointerId: event.pointerId,
              startY: event.clientY,
              startHeight: strategyTesterHeight,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            event.preventDefault();
          }}
          onPointerMove={resizeStrategyTesterFromPointer}
          onPointerUp={finishStrategyTesterResize}
          onPointerCancel={finishStrategyTesterResize}
          onKeyDown={resizeStrategyTesterFromKeyboard}
          onDoubleClick={() => setStrategyTesterHeight(clampStrategyTesterHeight(DEFAULT_STRATEGY_TESTER_HEIGHT, strategyTesterMaximum))}
        />
      ) : null}

      <section className="tv-bottom-dock" style={{'--btc-strategy-tester-height': `${strategyTesterHeight}px`} as Record<string, string>}>
        {researchArchiveOpen ? (
          <nav className="tv-bottom-tabs" aria-label="BTC 历史研究档案"><span className="active" aria-current="page">只读历史危险参照</span></nav>
        ) : (
        <nav className="tv-bottom-tabs" aria-label="BTC 工作台视图">
          {([
            ['tester', '策略测试器'],
            ['orders', `订单 ${accountDock.orders?.length ?? '未知'}`],
            ['fills', `成交 ${accountDock.fills?.length ?? '未知'}`],
            ['positions', `仓位 ${accountDock.positions?.filter((item) => Number(item.contracts) !== 0).length ?? '未知'}`],
            ['costs', '费用与资金费'],
            ['audit', '审计'],
          ] as Array<[BottomTab, string]>).map(([id, label]) => <button key={id} type="button" className={bottomTab === id ? 'active' : ''} onClick={() => setBottomTab(id)}>{label}</button>)}
        </nav>
        )}
        <div className="tv-dock-content">
          {researchArchiveOpen ? <BtcResearchArchive /> : bottomTab === 'tester' ? (
            <StrategyTesterReport
              readonlyReason={access.demoRuntime ? '' : access.mode === 'research_readonly' ? '研究只读：不执行新回测，未加载的数据保持未知。' : '后端模式尚未确认：新回测保持禁用。'}
              strategyCatalog={catalog?.strategies ?? []}
              editorCandidateId={backtestCandidateId}
              onStrategyChange={selectBacktestCandidate}
              selectedStrategyId={historyIdentity?.strategy_id ?? selectedSpec?.strategy_id ?? ''}
              selectedCandidateId={historyIdentity?.candidate_id ?? selectedCandidateId}
              selectedStrategyVersion={requestedLocalSnapshot?.strategyVersion ?? selectedSpec?.strategy_version ?? ''}
              selectedParamsHash={requestedLocalSnapshot?.paramsHash ?? selectedSpec?.params_hash ?? ''}
              sourceLabel={chartSourceLabel}
              sampleEnd={klines?.sample_end ?? ''}
              form={backtestForm}
              onFormChange={setBacktestForm}
              busy={backtestBusy}
              onRun={runBacktest}
              run={run}
              chart={backtestChart}
              history={candidateLocalHistory}
              onRestore={restoreHistory}
              canonicalFreshness={canonicalFreshness}
              canonical={canonical}
              canonicalReport={canonicalReport}
              historyResponse={strategyHistory}
              historyError={strategyHistoryError}
              selectedHistoricalRunId={selectedHistoricalRunId}
              onHistoricalRunSelect={setSelectedHistoricalRunId}
              reportTab={requestedReportTab}
              onReportTabChange={(tab) => {
                const params = new URLSearchParams(searchParams);
                params.set('report_tab', tab);
                setSearchParams(params);
              }}
              canRunBacktest={researchBacktestReady}
            />
          ) : null}
          {!researchArchiveOpen && bottomTab === 'orders' ? <OrdersTable rows={accountDock.orders} /> : null}
          {!researchArchiveOpen && bottomTab === 'fills' ? <FillsTable rows={accountDock.fills} /> : null}
          {!researchArchiveOpen && bottomTab === 'positions' ? <PositionsTable rows={accountDock.positions} /> : null}
          {!researchArchiveOpen && bottomTab === 'costs' ? <CostsPanel status={accountDock.status} canonicalReport={canonicalReport} blockers={canonicalBlockers} /> : null}
          {!researchArchiveOpen && bottomTab === 'audit' ? <AuditPanel status={demoStatusError ? null : demoStatus} /> : null}
        </div>
      </section>
      </div>

      {(pageMessage || (bootstrapFailed && demoBootstrapError)) ? (
        <div className="tv-page-message">
          <span>{pageMessage || `Demo V2 数据暂不可用：${demoBootstrapError}`}</span>
          {bootstrapFailed ? (
            <button
              type="button"
              data-testid="btc-crypto-bootstrap-retry"
              onClick={() => setBootstrapRetry((value) => value + 1)}
            >
              重试工作台数据
            </button>
          ) : null}
        </div>
      ) : null}
      <footer className="tv-research-disclaimer">研究回测与受限 OKX Demo runtime 是两条隔离链路；本页面不表示 paper/live ready，实盘能力始终关闭。</footer>
    </main>
  );
}

function Metric({label, value, tone = ''}: {label: string; value: string; tone?: string}) {
  return <div className={`tv-metric ${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function ProvenanceItem({label, value, tone}: {label: string; value: string; tone: 'pass' | 'blocked' | 'neutral'}) {
  return <div className={`tv-provenance-item ${tone}`}><span>{label}</span><strong title={value}>{value}</strong></div>;
}

// Display-only projection. Missing or unreconciled facts never mean an empty account.
function accountDockView(status: DemoRuntimeStatus | null, error: string) {
  const ledger = status?.ledger_reconciliation;
  const facts = accountFactsView(status?.exchange, !error && ledger?.status === 'reconciled'
    && ledger.current_state_exchange_snapshot_match === true && ledger.funding_cashflow_reconciled === true);
  const available = <T,>(rows: T[] | undefined): T[] | null => facts.usable && Array.isArray(rows)
    && rows.every(row => row !== null && typeof row === 'object') ? rows : null;
  return {
    status: facts.usable ? status : null,
    orders: available(status?.exchange?.orders),
    fills: available(status?.exchange?.fills),
    positions: facts.position.startsWith('未知') ? null : available(status?.exchange?.positions),
  };
}

function OrdersTable({rows}: {rows: DemoOrder[] | null}) {
  if (rows === null) return <p className="tv-empty">订单未知 · 账户事实缺失、读取失败或尚未对账；不能视为零订单。</p>;
  return <DataTable empty="尚无已对账订单。" headers={['时间', '方向', '仓位侧', '类型', '数量', '均价', '状态', 'Client ID']} rows={rows.map((row) => [timestamp(row.updated_at_ms), row.side, row.position_side, row.order_type, row.size, row.average_price || row.price, row.state, row.client_order_id])} />;
}

function FillsTable({rows}: {rows: DemoFill[] | null}) {
  if (rows === null) return <p className="tv-empty">成交未知 · 账户事实缺失、读取失败或尚未对账；不能视为零成交。</p>;
  return <DataTable empty="尚无已对账成交。" headers={['时间', '方向', '仓位侧', '数量', '价格', '手续费', 'PnL', 'Fill ID']} rows={rows.map((row) => [timestamp(row.timestamp_ms), row.side, row.position_side, row.size, row.price, `${row.fee} ${row.fee_currency}`, row.pnl, row.fill_id])} />;
}

function PositionsTable({rows}: {rows: DemoPosition[] | null}) {
  if (rows === null) return <p className="tv-empty">仓位未知 · 账户事实缺失、读取失败或尚未对账；不能视为空仓。</p>;
  const visible = rows.filter((row) => Number(row.contracts) !== 0);
  return <DataTable empty="当前 Demo 账户为空仓。" headers={['方向', '张数', '均价', 'Mark', '未实现 PnL', '已实现 PnL', '杠杆', '强平价']} rows={visible.map((row) => [row.position_side, row.contracts, row.average_price, row.mark_price, row.unrealized_pnl, row.realized_pnl, row.leverage, row.liquidation_price || '—'])} />;
}

function CostsPanel({status, canonicalReport, blockers}: {status: DemoRuntimeStatus | null; canonicalReport: CanonicalBacktestReport | null; blockers: string[]}) {
  const facts = accountDockView(status, '');
  const exchange = facts.status?.exchange;
  const fills = facts.fills;
  const bills = Array.isArray(exchange?.bills) && exchange.bills.every(row => row && typeof row.type === 'string' && typeof row.sub_type === 'string') ? exchange.bills : null;
  const totalFees = fills?.every(row => finiteAccountNumber(row.fee) !== null && row.fee_currency === 'USDT')
    ? fills.reduce((sum, row) => sum + Number(row.fee), 0) : null;
  const fundingBills = bills?.filter((row) => isFundingBill(row)) ?? null;
  const fundingCashflow = fundingBills?.every(row => finiteAccountNumber(row.balance_change) !== null && row.currency === 'USDT')
    ? fundingBills.reduce((sum, row) => sum + Number(row.balance_change), 0) : null;
  const canonicalFillCount = finiteAccountNumber(canonicalReport?.source_counts.fill_count);
  return (
    <div className="tv-cost-workbench">
      <div className="tv-cost-grid">
        <Metric label="Maker rate" value={rateBps(exchange?.fee_schedule?.maker_rate)} />
        <Metric label="Taker rate" value={rateBps(exchange?.fee_schedule?.taker_rate)} />
        <Metric label="当前 funding" value={rateBps(exchange?.funding?.funding_rate)} />
        <Metric label="Demo 成交手续费" value={totalFees === null ? '未知' : `${totalFees.toFixed(8)} USDT`} tone={totalFees !== null && totalFees < 0 ? 'bad' : ''} />
        <Metric label="Funding 现金流" value={fundingCashflow === null ? '未知' : `${fundingCashflow.toFixed(8)} USDT`} tone={fundingCashflow === null ? '' : fundingCashflow >= 0 ? 'good' : 'bad'} />
        <Metric label="Funding 样本" value={fundingBills === null ? '未知' : String(fundingBills.length)} />
      </div>
      <div className="tv-cost-evidence-grid">
        <CostEvidence label="Demo fill 样本" value={fills === null ? '未知' : `${fills.length} fills`} state={fills && fills.length > 0 ? 'observed' : 'missing'} />
        <CostEvidence label="Canonical fill 样本" value={canonicalFillCount === null ? '未知' : `${canonicalFillCount} fills`} state={canonicalFillCount !== null && canonicalFillCount > 0 ? 'observed' : 'missing'} />
        <CostEvidence label="Depth → fill mapping" value="未验证 · 需同源映射证据" state="blocked" />
        <CostEvidence label="实测滑点归因" value="未验证 · 不能仅凭成交数推断" state="blocked" />
        <CostEvidence label="OKX native 成本" value={blockers.some(item => item.includes('okx_native_cost_and_funding_validation_missing')) ? '缺失' : '未验证 · 无阻断项不代表完整'} state="blocked" />
        <CostEvidence label="私有 WS / gapfill" value="未接入 / 未验证" state="blocked" />
      </div>
      <div className="tv-cost-note">费用与资金费只展示已对账样本；页面不根据盘口或费率表补造滑点。Depth mapping、私有 WS 与 OKX native 成本缺证时继续 fail-closed。</div>
    </div>
  );
}

function CostEvidence({label, value, state}: {label: string; value: string; state: 'observed' | 'missing' | 'blocked'}) {
  return <div className={`tv-cost-evidence ${state}`}><span>{label}</span><strong>{value}</strong><small>{state === 'observed' ? 'OBSERVED' : state === 'missing' ? 'NO SAMPLE' : 'BLOCKED'}</small></div>;
}

function AuditPanel({status}: {status: DemoRuntimeStatus | null}) {
  if (!Array.isArray(status?.events)) return <p className="tv-empty">审计事件未知 · 尚未取得运行记录，不能视为零事件。</p>;
  const events = [...(status?.events ?? [])].reverse();
  return (
    <div className="tv-audit-workbench">
      <div className="tv-audit-summary"><ShieldCheck size={17} /><span>Append-only 本地审计</span><strong>{events.length} events</strong><small>任何错误都不会自动解除 fail-closed</small></div>
      <div className="tv-audit-list">
        {events.map((event) => {
          const severity = auditSeverity(event.event_type, event.payload);
          return (
            <article key={event.event_id} className={`tv-audit-event ${severity}`}>
              <span className="tv-audit-event-icon">{severity === 'error' ? <WarningCircle size={16} /> : severity === 'warning' ? <Clock size={16} /> : <CheckCircle size={16} />}</span>
              <div><time>{formatIso(event.timestamp_utc)}</time><strong>{auditEventLabel(event.event_type)}</strong><p>{auditSummary(event.event_type, event.payload)}</p><code>{event.event_id}</code></div>
              <details><summary>原始 payload</summary><code>{JSON.stringify(event.payload)}</code></details>
            </article>
          );
        })}
        {!events.length ? <p className="tv-empty">运行、对账或控制动作发生后显示 append-only 审计事件。</p> : null}
      </div>
    </div>
  );
}

function DataTable({headers, rows, empty}: {headers: string[]; rows: string[][]; empty: string}) {
  if (!rows.length) return <p className="tv-empty">{empty}</p>;
  return (
    <div className="tv-data-table-wrap"><table className="tv-data-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={`${rowIndex}-${row.join('-')}`}>{row.map((cell, cellIndex) => <td key={`${cellIndex}-${cell}`}><span>{cell || '—'}</span></td>)}</tr>)}</tbody></table></div>
  );
}

function resampleCandles(candles: TradingCandle[], timeframe: Timeframe): TradingCandle[] {
  void timeframe;
  return candles;
}

function resampleMarkers(markers: TradingMarker[], timeframe: Timeframe): TradingMarker[] {
  void timeframe;
  return markers;
}

function timeframeLabel(timeframe: Timeframe): string {
  return ({
    '1m': '1 分钟',
    '5m': '5 分钟',
    '15m': '15 分钟',
    '1h': '1 小时',
    '4h': '4 小时',
    '1d': '1 天',
    '1w': '1 周',
    '1M': '1 月',
  } as Record<Timeframe, string>)[timeframe];
}

function drawingToolLabel(tool: DrawingTool): string {
  return ({cursor: '光标', trend: '趋势线', pencil: '自由标注', measure: '测量', target: '风险收益', text: '文本'} as Record<DrawingTool, string>)[tool];
}

function downloadChartCanvas(): void {
  const wrapper = document.querySelector<HTMLElement>('.tv-chart-stack');
  const layers = wrapper ? Array.from(wrapper.querySelectorAll('canvas')) : [];
  if (!wrapper || !layers.length) return;
  const bounds = wrapper.getBoundingClientRect();
  const output = document.createElement('canvas');
  output.width = Math.max(1, Math.round(bounds.width * window.devicePixelRatio));
  output.height = Math.max(1, Math.round(bounds.height * window.devicePixelRatio));
  const context = output.getContext('2d');
  if (!context) return;
  context.fillStyle = '#0b0e14';
  context.fillRect(0, 0, output.width, output.height);
  layers.forEach((layer) => context.drawImage(layer, 0, 0, output.width, output.height));
  const link = document.createElement('a');
  link.href = output.toDataURL('image/png');
  link.download = `btc-chart-${new Date().toISOString().replaceAll(':', '-')}.png`;
  link.click();
}

function formatQuote(value: string | undefined): string {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', {minimumFractionDigits: 1, maximumFractionDigits: 1}) : '—';
}

function spread(status: DemoRuntimeStatus | null): string {
  const bid = Number(status?.exchange.ticker.bid);
  const ask = Number(status?.exchange.ticker.ask);
  return Number.isFinite(bid) && Number.isFinite(ask) ? Math.max(0, ask - bid).toFixed(1) : '—';
}

function fillMarkers(fills: DemoFill[], candles: TradingCandle[], timeframe: Timeframe): TradingMarker[] {
  const times = new Set(candles.map((item) => item.time));
  const seen = new Set<string>();
  return fills.flatMap((fill) => {
    const identity = fill.fill_id || `${fill.order_id}:${fill.client_order_id}:${fill.timestamp_ms}`;
    if (!identity || seen.has(identity)) return [];
    seen.add(identity);
    const raw = Math.floor(Number(fill.timestamp_ms) / 1000);
    if (!Number.isFinite(raw)) return [];
    const bucket = visualCandleOpenUtc(raw, candles, timeframe);
    if (bucket === null || !times.has(bucket)) return [];
    const buy = fill.side === 'buy';
    const executionType = String(fill.execution_type ?? '').toLowerCase();
    const lifecycle = ['open', 'entry', 'close', 'exit', 'reduce', 'reduce_only']
      .find((value) => executionType === value || executionType.includes(value));
    const lifecycleLabel = lifecycle === 'open' || lifecycle === 'entry'
      ? 'OPEN'
      : lifecycle === 'close' || lifecycle === 'exit' || lifecycle === 'reduce' || lifecycle === 'reduce_only'
        ? 'CLOSE'
        : '';
    const price = Number(fill.price);
    const pnl = Number(fill.pnl);
    const timeLabel = new Date(Number(fill.timestamp_ms)).toLocaleTimeString('zh-CN', {hour12: false});
    const pnlLabel = Number.isFinite(pnl) ? ` · 已实现 ${pnl.toFixed(4)} USDT` : '';
    return [{
      time: bucket,
      position: buy ? 'belowBar' : 'aboveBar',
      color: buy ? '#22c55e' : '#ef4444',
      shape: buy ? 'arrowUp' : 'arrowDown',
      text: `Demo run · ${fill.side.toUpperCase()}${lifecycleLabel ? ` ${lifecycleLabel}` : ''} FILL ${fill.size} @ ${Number.isFinite(price) ? price : '—'} · ${timeLabel}${pnlLabel}`,
    } as TradingMarker];
  });
}

function visualCandleOpenUtc(
  timestampSeconds: number,
  candles: TradingCandle[],
  timeframe: Timeframe,
): number | null {
  const ordered = [...candles].sort((left, right) => left.time - right.time);
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const current = ordered[index];
    if (timestampSeconds < current.time) continue;
    const nextOpen = nextVisualCandleOpenUtc(current.time, timeframe);
    const following = ordered[index + 1]?.time;
    // A real candle open and its actual following boundary control marker
    // placement.  For a missing visual bar, do not smear a fill across the
    // gap merely because a fixed-duration bucket happened to contain it.
    const upperBound = Math.min(nextOpen, following ?? Number.POSITIVE_INFINITY);
    return timestampSeconds < upperBound ? current.time : null;
  }
  return null;
}

export function mergeVisualTrade(
  current: PublicMarketView | null,
  trade: NonNullable<PublicMarketStreamEvent['trade']>,
  timeframe: Timeframe,
): PublicMarketView | null {
  if (!current || !trade) return current;
  const price = Number(trade.price);
  const size = Number(trade.size);
  const timestampSeconds = Math.floor(Number(trade.timestamp_ms) / 1_000);
  if (![price, size, timestampSeconds].every(Number.isFinite) || price <= 0 || size <= 0) return current;
  const candles = [...current.candles];
  const index = candles.length - 1;
  const last = candles[index];
  if (!last?.in_progress) return current;
  const openSeconds = Math.floor(last.open_time_ms / 1_000);
  if (timestampSeconds < openSeconds) return current;
  const tickOpenSeconds = visualCandleBucketOpenUtc(timestampSeconds, timeframe);
  if (tickOpenSeconds > openSeconds) {
    // This was a visual-only unfinished candle.  A later bucket replaces it
    // with another visual-only unfinished candle; it never becomes confirmed
    // until the next REST snapshot supplies an exchange-confirmed history bar.
    candles[index] = {...last, confirmed: false, in_progress: false};
    candles.push({
      open_time_ms: tickOpenSeconds * 1_000,
      open: price,
      high: price,
      low: price,
      close: price,
      volume: size,
      confirmed: false,
      in_progress: true,
    });
    return {
      ...current,
      candles,
      ticker: {...current.ticker, last: trade.price, timestamp_ms: Number(trade.timestamp_ms)},
    };
  }
  candles[index] = {
    ...last,
    high: Math.max(last.high, price),
    low: Math.min(last.low, price),
    close: price,
    volume: last.volume + size,
    confirmed: false,
    in_progress: true,
  };
  return {
    ...current,
    candles,
    ticker: {...current.ticker, last: trade.price, timestamp_ms: Number(trade.timestamp_ms)},
  };
}

export function mergeVisualTicker(
  current: PublicMarketView | null,
  payload: PublicMarketTicker,
  timeframe: Timeframe,
): PublicMarketView | null {
  if (!current || current.instrument_id !== payload.instrument_id || current.timeframe !== timeframe) return current;
  const price = Number(payload.ticker.last);
  const timestampMs = Number(payload.ticker.timestamp_ms);
  const currentTimestampMs = Number(current.ticker.timestamp_ms);
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(timestampMs)
    || timestampMs <= currentTimestampMs) return current;
  const candles = [...current.candles];
  const index = candles.length - 1;
  const last = candles[index];
  if (!last) return {...current, ticker: payload.ticker};
  const openSeconds = Math.floor(last.open_time_ms / 1_000);
  const tickOpenSeconds = visualCandleBucketOpenUtc(Math.floor(timestampMs / 1_000), timeframe);
  if (tickOpenSeconds > openSeconds) {
    candles[index] = {...last, confirmed: false, in_progress: false};
    candles.push({
      open_time_ms: tickOpenSeconds * 1_000,
      open: price,
      high: price,
      low: price,
      close: price,
      volume: 0,
      confirmed: false,
      in_progress: true,
    });
  } else if (last.in_progress && tickOpenSeconds === openSeconds) {
    candles[index] = {
      ...last,
      high: Math.max(last.high, price),
      low: Math.min(last.low, price),
      close: price,
    };
  }
  return {...current, candles, ticker: payload.ticker};
}

function mergeRestMarketView(
  current: PublicMarketView | null,
  incoming: PublicMarketView,
): PublicMarketView {
  if (!current || current.instrument_id !== incoming.instrument_id || current.timeframe !== incoming.timeframe) {
    return incoming;
  }
  const currentTickerTimestamp = Number(current.ticker.timestamp_ms);
  const incomingTickerTimestamp = Number(incoming.ticker.timestamp_ms);
  if (!Number.isFinite(currentTickerTimestamp) || !Number.isFinite(incomingTickerTimestamp)
    || incomingTickerTimestamp >= currentTickerTimestamp) {
    return incoming;
  }
  const currentVisual = [...current.candles].reverse().find((candle) => candle.in_progress);
  if (!currentVisual) return {...incoming, ticker: current.ticker};
  const incomingTailOpen = incoming.candles.reduce(
    (latest, candle) => Math.max(latest, candle.open_time_ms),
    Number.NEGATIVE_INFINITY,
  );
  const currentVisualTail = current.candles.filter(
    (candle) => !candle.confirmed && candle.open_time_ms >= incomingTailOpen,
  );
  if (currentVisualTail.length === 0) return {...incoming, ticker: current.ticker};
  const restHistory = incoming.candles
    .filter((candle) => candle.open_time_ms < currentVisualTail[0].open_time_ms)
    .map((candle) => candle.in_progress ? {...candle, confirmed: false, in_progress: false} : candle);
  return {
    ...incoming,
    candles: [...restHistory, ...currentVisualTail],
    ticker: current.ticker,
  };
}

export function claimVisualTradeId(
  state: {order: string[]; seen: Set<string>},
  tradeId: string,
  capacity = VISUAL_TRADE_ID_CAPACITY,
): boolean {
  const normalized = String(tradeId ?? '').trim();
  if (!normalized || state.seen.has(normalized)) return false;
  state.seen.add(normalized);
  state.order.push(normalized);
  while (state.order.length > capacity) {
    const expired = state.order.shift();
    if (expired) state.seen.delete(expired);
  }
  return true;
}

function visualCandleBucketOpenUtc(timestampSeconds: number, timeframe: Timeframe): number {
  const date = new Date(timestampSeconds * 1_000);
  if (timeframe === '1M') {
    return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1) / 1_000);
  }
  if (timeframe === '1w') {
    const utcDay = date.getUTCDay();
    const daysSinceMonday = (utcDay + 6) % 7;
    return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - daysSinceMonday) / 1_000);
  }
  if (timeframe === '1d') {
    return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 1_000);
  }
  const interval = ({'1m': 60, '5m': 300, '15m': 900, '1h': 3_600, '4h': 14_400} as const)[timeframe];
  return Math.floor(timestampSeconds / interval) * interval;
}

function nextVisualCandleOpenUtc(candleOpenSeconds: number, timeframe: Timeframe): number {
  const date = new Date(candleOpenSeconds * 1_000);
  if (timeframe === '1M') {
    return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1) / 1_000);
  }
  if (timeframe === '1w') {
    return candleOpenSeconds + 7 * 86_400;
  }
  if (timeframe === '1d') {
    return Math.floor(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1) / 1_000);
  }
  const interval = ({'1m': 60, '5m': 300, '15m': 900, '1h': 3_600, '4h': 14_400} as const)[timeframe];
  return candleOpenSeconds + interval;
}

function canonicalTradeMarkers(trades: CanonicalTrade[], candles: TradingCandle[]): TradingMarker[] {
  const times = new Set(candles.map((item) => item.time));
  return trades.flatMap((trade) => {
    const entryTime = Math.floor(trade.entry_time / 3600) * 3600;
    const exitTime = Math.floor(trade.exit_time / 3600) * 3600;
    const isLong = trade.direction === 'long';
    const markers: TradingMarker[] = [];
    if (times.has(entryTime)) {
      markers.push({
        time: entryTime,
        position: isLong ? 'belowBar' : 'aboveBar',
        color: isLong ? '#22c55e' : '#f23645',
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: `C#${trade.trade_number} ${isLong ? '多入' : '空入'}`,
      });
    }
    if (times.has(exitTime)) {
      markers.push({
        time: exitTime,
        position: isLong ? 'aboveBar' : 'belowBar',
        color: '#f0b90b',
        shape: isLong ? 'arrowDown' : 'arrowUp',
        text: `C#${trade.trade_number} ${isLong ? '多出' : '空出'} · ${trade.net_pnl >= 0 ? '+' : ''}${trade.net_pnl.toFixed(2)}`,
      });
    }
    return markers;
  });
}

function isFundingBill(row: DemoBill): boolean {
  return row.type === '8' || row.sub_type === '173' || row.sub_type.toLowerCase().includes('fund');
}

function nestedText(source: Record<string, unknown> | null, ...path: string[]): string {
  let current: unknown = source;
  for (const key of path) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return '';
    current = (current as Record<string, unknown>)[key];
  }
  return current === null || current === undefined ? '' : String(current);
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function textOr(value: unknown, fallback: string): string {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function auditEventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    fill_reconciled: '成交已对账',
    order_reconciled: '订单已对账',
    manual_reconciliation_failed: '人工对账失败',
    reconciliation_completed: '账户对账完成',
    cancel_only_entered: '进入 Cancel-only',
    runtime_started: 'Demo runtime 启动',
    runtime_stopped: 'Demo runtime 停止',
  };
  return labels[eventType] ?? eventType.replaceAll('_', ' ');
}

function auditSeverity(eventType: string, payload: Record<string, unknown>): 'success' | 'warning' | 'error' {
  const error = String(payload.error ?? '');
  if (eventType.includes('failed') || eventType.includes('error') || error) return 'error';
  if (eventType.includes('cancel') || eventType.includes('stop') || eventType.includes('blocked')) return 'warning';
  return 'success';
}

function auditSummary(eventType: string, payload: Record<string, unknown>): string {
  const error = String(payload.error ?? '');
  if (error) {
    const code = error.match(/:(\d{4,6})(?:\b|$)/)?.[1];
    return `对账或费用查询未完成${code ? `，错误码 ${code}` : ''}；需检查接口合同与本地状态，未自动解除 fail-closed。`;
  }
  const fillId = textOr(payload.fill_id, '');
  const orderId = textOr(payload.order_id, '');
  const status = textOr(payload.status, '');
  if (fillId) return `已记录并对账 fill ${fillId}；不代表 depth/slippage mapping 已验证。`;
  if (orderId) return `已记录订单 ${orderId} 的本地对账状态。`;
  if (status) return `运行状态更新为 ${status}。`;
  return `${auditEventLabel(eventType)}；原始字段保留在下方 payload。`;
}

function numeric(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '请求失败');
}

function price(value: number | undefined): string {
  return Number.isFinite(value) ? Number(value).toLocaleString('zh-CN', {minimumFractionDigits: 1, maximumFractionDigits: 1}) : '—';
}

function percent(value: number | undefined): string {
  return Number.isFinite(value) ? `${Number(value).toFixed(2)}%` : '—';
}

function fixed(value: number | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(2) : '—';
}

function rateBps(value: string | undefined): string {
  const number = finiteAccountNumber(value);
  return number !== null ? `${(number * 10_000).toFixed(3)} bps` : '未知';
}

function timestamp(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return '—';
  return new Date(number).toLocaleString('zh-CN', {hour12: false});
}

function formatIso(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', {hour12: false});
}

function validReportTab(value: string | null): BTCStrategyReportTab {
  return value === 'performance'
    || value === 'trades'
    || value === 'risk'
    || value === 'evidence'
    ? value
    : 'overview';
}
