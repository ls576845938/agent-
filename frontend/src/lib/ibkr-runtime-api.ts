import {apiGet} from './api';

export const IBKR_RUNTIME_ENDPOINT = '/api/us/ibkr/runtime';

export const IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS = {
  heartbeat: 15,
  marketData: 15,
  brokerTruth: 60,
  reconciliation: 300,
} as const;

export type RuntimeState =
  | 'offline'
  | 'connecting'
  | 'authenticating'
  | 'broker_syncing'
  | 'reconciling'
  | 'ready'
  | 'degraded'
  | 'reconnecting'
  | 'recovery_pending'
  | 'halted'
  | 'unknown';

export type TradingMode =
  | 'normal'
  | 'reduce_only'
  | 'cancel_only'
  | 'frozen'
  | 'no_transport'
  | 'unknown';

export type RuntimeBool = boolean | null;

export type RuntimeGatewayStatus = {
  connected: RuntimeBool;
  last_heartbeat_at: string | null;
  heartbeat_age_seconds: number | null;
  client_id: number | string | null;
  paper_port: number | null;
  connection_epoch: number | null;
  reconnect_attempts: number | null;
  last_error: string | null;
};

export type RuntimeAccountStatus = {
  verified: RuntimeBool;
  account_hash: string | null;
};

export type RuntimeMarketDataStatus = {
  healthy: RuntimeBool;
  subscription_status: string;
  last_tick_at: string | null;
  last_tick_age_seconds: number | null;
  subscription_epoch: number | null;
  sequence_gap: RuntimeBool;
};

export type RuntimeBrokerTruthStatus = {
  snapshot_at: string | null;
  fresh: RuntimeBool;
  open_orders_count: number | null;
  executions_count: number | null;
  positions_count: number | null;
  cash: number | null;
};

export type RuntimeReconciliationStatus = {
  status: string;
  last_run_at: string | null;
  unknown_orders: number | null;
  unknown_executions: number | null;
  position_mismatches: number | null;
  cash_mismatch: RuntimeBool;
};

export type RuntimeKillSwitchStatus = {
  tripped: RuntimeBool;
  reason: string | null;
};

export type RuntimeRecoveryStatus = {
  state: string;
  requires_operator_ack: RuntimeBool;
  operator_acknowledged: RuntimeBool;
};

export type IbkrRuntimeStatus = {
  runtime_state: RuntimeState;
  trading_mode: TradingMode;
  block_new_orders: boolean;
  gateway: RuntimeGatewayStatus;
  account: RuntimeAccountStatus;
  market_data: RuntimeMarketDataStatus;
  broker_truth: RuntimeBrokerTruthStatus;
  reconciliation: RuntimeReconciliationStatus;
  oms: {
    reduce_only: RuntimeBool;
  };
  kill_switch: RuntimeKillSwitchStatus;
  recovery: RuntimeRecoveryStatus;
  blockers: string[];
};

export type IbkrRuntimeStatusResult =
  | {
      kind: 'available';
      snapshot: IbkrRuntimeStatus;
      fetched_at: string;
    }
  | {
      kind: 'unavailable';
      message: string;
      fetched_at: string;
    };

const RUNTIME_STATES = new Set<RuntimeState>([
  'offline',
  'connecting',
  'authenticating',
  'broker_syncing',
  'reconciling',
  'ready',
  'degraded',
  'reconnecting',
  'recovery_pending',
  'halted',
  'unknown',
]);

const TRADING_MODES = new Set<TradingMode>([
  'normal',
  'reduce_only',
  'cancel_only',
  'frozen',
  'no_transport',
  'unknown',
]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : null;
}

function asRecordOrEmpty(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
}

function asString(value: unknown, fallback: string | null = null): string | null {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function asNumber(value: unknown, fallback: number | null = null): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback: RuntimeBool = null): RuntimeBool {
  return typeof value === 'boolean' ? value : fallback;
}

function asCount(value: unknown): number | null {
  const count = asNumber(value);
  return count !== null && count >= 0 ? count : null;
}

function asRuntimeState(value: unknown): RuntimeState {
  if (typeof value === 'string' && RUNTIME_STATES.has(value as RuntimeState)) {
    return value as RuntimeState;
  }
  return 'unknown';
}

function asTradingMode(value: unknown): TradingMode {
  if (typeof value === 'string' && TRADING_MODES.has(value as TradingMode)) {
    return value as TradingMode;
  }
  return 'unknown';
}

function normalizeStatus(value: unknown, fallback = 'unknown'): string {
  const status = asString(value, fallback);
  return status ? status.toLowerCase() : fallback;
}

function normalizeBlockers(value: unknown): string[] {
  if (!Array.isArray(value)) return [];

  const blockers: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    let blocker = typeof item === 'string' ? item.trim() : '';
    if (!blocker) {
      const structured = asRecord(item);
      const code = asString(structured?.code)?.trim() ?? '';
      const message = asString(structured?.message)?.trim() ?? '';
      blocker = code && message ? `${code}: ${message}` : code || message;
    }
    if (!blocker || seen.has(blocker)) continue;
    seen.add(blocker);
    blockers.push(blocker);
  }
  return blockers;
}

function normalizeTimestamp(value: unknown): string | null {
  const timestamp = asString(value);
  if (!timestamp) return null;
  return Number.isNaN(Date.parse(timestamp)) ? null : timestamp;
}

/**
 * Parse the backend contract into a fail-closed read model.
 * Missing safety-critical booleans become null/blocked instead of healthy.
 */
export function normalizeIbkrRuntimeStatus(payload: unknown): IbkrRuntimeStatus | null {
  const root = asRecord(payload);
  if (!root) return null;

  const gateway = asRecordOrEmpty(root.gateway);
  const account = asRecordOrEmpty(root.account);
  const marketData = asRecordOrEmpty(root.market_data);
  const brokerTruth = asRecordOrEmpty(root.broker_truth);
  const reconciliation = asRecordOrEmpty(root.reconciliation);
  const oms = asRecordOrEmpty(root.oms);
  const killSwitch = asRecordOrEmpty(root.kill_switch);
  const recovery = asRecordOrEmpty(root.recovery);

  return {
    runtime_state: asRuntimeState(root.runtime_state),
    trading_mode: asTradingMode(root.trading_mode),
    block_new_orders: asBoolean(root.block_new_orders, true) !== false,
    gateway: {
      connected: asBoolean(gateway.connected),
      last_heartbeat_at: normalizeTimestamp(gateway.last_heartbeat_at),
      heartbeat_age_seconds: asNumber(gateway.heartbeat_age_seconds),
      client_id: typeof gateway.client_id === 'number' || typeof gateway.client_id === 'string' ? gateway.client_id : null,
      paper_port: asNumber(gateway.paper_port),
      connection_epoch: asCount(gateway.connection_epoch),
      reconnect_attempts: asCount(gateway.reconnect_attempts),
      last_error: asString(gateway.last_error),
    },
    account: {
      verified: asBoolean(account.verified),
      account_hash: asString(account.account_hash),
    },
    market_data: {
      healthy: asBoolean(marketData.healthy),
      subscription_status: normalizeStatus(marketData.subscription_status),
      last_tick_at: normalizeTimestamp(marketData.last_tick_at),
      last_tick_age_seconds: asNumber(marketData.last_tick_age_seconds),
      subscription_epoch: asCount(marketData.subscription_epoch),
      sequence_gap: asBoolean(marketData.sequence_gap),
    },
    broker_truth: {
      snapshot_at: normalizeTimestamp(brokerTruth.snapshot_at),
      fresh: asBoolean(brokerTruth.fresh),
      open_orders_count: asCount(brokerTruth.open_orders_count),
      executions_count: asCount(brokerTruth.executions_count),
      positions_count: asCount(brokerTruth.positions_count),
      cash: asNumber(brokerTruth.cash),
    },
    reconciliation: {
      status: normalizeStatus(reconciliation.status),
      last_run_at: normalizeTimestamp(reconciliation.last_run_at),
      unknown_orders: asCount(reconciliation.unknown_orders),
      unknown_executions: asCount(reconciliation.unknown_executions),
      position_mismatches: asCount(reconciliation.position_mismatches),
      cash_mismatch: asBoolean(reconciliation.cash_mismatch),
    },
    oms: {
      reduce_only: asBoolean(oms.reduce_only),
    },
    kill_switch: {
      tripped: asBoolean(killSwitch.tripped),
      reason: asString(killSwitch.reason),
    },
    recovery: {
      state: normalizeStatus(recovery.state),
      requires_operator_ack: asBoolean(recovery.requires_operator_ack),
      operator_acknowledged: asBoolean(recovery.operator_acknowledged),
    },
    blockers: normalizeBlockers(root.blockers),
  };
}

export function createUnavailableIbkrRuntimeStatus(message: string): IbkrRuntimeStatus {
  return {
    runtime_state: 'unknown',
    trading_mode: 'unknown',
    block_new_orders: true,
    gateway: {
      connected: null,
      last_heartbeat_at: null,
      heartbeat_age_seconds: null,
      client_id: null,
      paper_port: null,
      connection_epoch: null,
      reconnect_attempts: null,
      last_error: message,
    },
    account: {verified: null, account_hash: null},
    market_data: {
      healthy: null,
      subscription_status: 'unknown',
      last_tick_at: null,
      last_tick_age_seconds: null,
      subscription_epoch: null,
      sequence_gap: null,
    },
    broker_truth: {
      snapshot_at: null,
      fresh: null,
      open_orders_count: null,
      executions_count: null,
      positions_count: null,
      cash: null,
    },
    reconciliation: {
      status: 'unknown',
      last_run_at: null,
      unknown_orders: null,
      unknown_executions: null,
      position_mismatches: null,
      cash_mismatch: null,
    },
    oms: {reduce_only: null},
    kill_switch: {tripped: null, reason: null},
    recovery: {
      state: 'unknown',
      requires_operator_ack: null,
      operator_acknowledged: null,
    },
    blockers: [message, 'IBKR runtime truth unavailable; new orders remain blocked'],
  };
}

export async function loadIbkrRuntimeStatus(): Promise<IbkrRuntimeStatusResult> {
  const fetchedAt = new Date().toISOString();
  try {
    const payload = await apiGet<unknown>(IBKR_RUNTIME_ENDPOINT);
    const snapshot = normalizeIbkrRuntimeStatus(payload);
    if (!snapshot) {
      return {
        kind: 'unavailable',
        message: 'IBKR runtime API returned an invalid status payload',
        fetched_at: fetchedAt,
      };
    }
    return {kind: 'available', snapshot, fetched_at: fetchedAt};
  } catch (error) {
    return {
      kind: 'unavailable',
      message: error instanceof Error ? error.message : 'IBKR runtime API unavailable',
      fetched_at: fetchedAt,
    };
  }
}

export function isReconciliationPass(status: string): boolean {
  return status.trim().toLowerCase() === 'pass' || status.trim().toLowerCase() === 'passed';
}

export function isIbkrRuntimeBlocked(snapshot: IbkrRuntimeStatus): boolean {
  return snapshot.block_new_orders
    || snapshot.runtime_state !== 'ready'
    || snapshot.trading_mode !== 'normal'
    || snapshot.gateway.connected !== true
    || snapshot.account.verified !== true
    || snapshot.broker_truth.fresh !== true
    || !isReconciliationPass(snapshot.reconciliation.status)
    || snapshot.kill_switch.tripped !== false
    || snapshot.market_data.healthy !== true
    || snapshot.market_data.sequence_gap !== false
    || snapshot.recovery.requires_operator_ack === true
    || snapshot.recovery.operator_acknowledged !== false
    || snapshot.blockers.length > 0;
}

export type FreshnessView = {
  label: string;
  absolute: string;
  stale: boolean;
  known: boolean;
};

function relativeAge(seconds: number): string {
  if (seconds < 1) return '刚刚';
  if (seconds < 60) return `${Math.floor(seconds)} 秒前`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时前`;
}

export function formatFreshness(
  timestamp: string | null,
  staleAfterSeconds: number,
  now = Date.now(),
): FreshnessView {
  if (!timestamp) return {label: '未知', absolute: 'UTC 时间不可用', stale: true, known: false};
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return {label: '未知', absolute: 'UTC 时间无效', stale: true, known: false};
  const ageSeconds = Math.max(0, (now - parsed) / 1000);
  const stale = ageSeconds > staleAfterSeconds;
  return {
    label: stale ? `已过期 · ${relativeAge(ageSeconds)}` : relativeAge(ageSeconds),
    absolute: new Date(parsed).toISOString(),
    stale,
    known: true,
  };
}

export function formatRuntimeLabel(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '未知';
  const raw = String(value).trim();
  const key = raw.toLowerCase();
  const text = raw.replace(/_/g, ' ').trim();
  if (!text) return '未知';
  const labels: Record<string, string> = {
    offline: '离线', connecting: '连接中', authenticating: '认证中', broker_syncing: '同步 Broker 中',
    reconciling: '对账中', ready: '就绪', degraded: '降级', reconnecting: '重连中',
    recovery_pending: '等待恢复', halted: '已停止', unknown: '未知',
    normal: '正常', reduce_only: '仅减仓', cancel_only: '仅撤单', frozen: '已冻结',
    no_transport: '无传输', pass: '通过', passed: '已通过', fail: '失败', failed: '失败',
    connected: '已连接', disconnected: '已断开', subscribed: '已订阅', subscribing: '订阅中',
    effective: '已生效', live: '运行中', clear: '正常', blocked: '已阻断',
  };
  return labels[key] ?? labels[text.toLowerCase()] ?? `状态码：${text}`;
}

export function formatRuntimeBoolean(value: RuntimeBool, trueLabel: string, falseLabel: string): string {
  if (value === true) return trueLabel;
  if (value === false) return falseLabel;
  return '未知';
}

export function runtimeBanner(snapshot: IbkrRuntimeStatus): {title: string; detail: string; blocked: boolean} {
  if (snapshot.gateway.connected === false) {
    return {title: 'IBKR 连接已断开', detail: '新订单已阻断 · Broker 传输不可用', blocked: true};
  }
  const reconciliationStatus = snapshot.reconciliation.status.trim().toLowerCase();
  if (reconciliationStatus === 'fail' || reconciliationStatus === 'failed') {
    return {title: '对账失败', detail: '新订单已阻断 · Broker 事实需要人工复核', blocked: true};
  }
  if (!isReconciliationPass(reconciliationStatus)) {
    return {title: '新订单已阻断', detail: '对账状态未知 · 运行时事实尚未证明', blocked: true};
  }
  if (snapshot.broker_truth.fresh === false) {
    return {title: 'Broker 事实已过期', detail: '新订单已阻断 · 等待新鲜 Broker 快照', blocked: true};
  }
  if (snapshot.runtime_state === 'ready' && !isIbkrRuntimeBlocked(snapshot)) {
    return {title: '运行时就绪', detail: '仅 Paper 校验 · Live 始终锁定', blocked: false};
  }
  if (snapshot.kill_switch.tripped === true || snapshot.trading_mode === 'frozen' || snapshot.runtime_state === 'halted') {
    return {title: '交易已冻结', detail: '新订单已阻断 · 安全控制已生效', blocked: true};
  }
  return {title: '新订单已阻断', detail: '运行时状态尚未证明就绪 · 故障闭锁（fail-closed）', blocked: true};
}

export function formatRuntimeBlocker(value: string): string {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    'ibkr runtime truth unavailable; new orders remain blocked': 'IBKR 运行时事实不可用；新订单保持阻断',
  };
  return labels[normalized] ?? `原始阻断码：${value}`;
}
