import type {ChartSeriesPayload, RunStatusResponse} from '../../lib/view-model';

export type DemoStrategySpec = {
  strategy_id: string;
  candidate_id: string;
  strategy_version: string;
  params_hash: string;
  display_name: string;
  timeframe: string;
  direction_policy: string;
  adapter_fidelity: string;
  promotion_eligibility: string;
  canonical_signal_available: boolean;
  demo_selectable: boolean;
  demo_blocker: string;
};

export type DemoCatalog = {
  schema_version: string;
  environment: 'OKX Demo';
  instrument_id: 'BTC-USDT-SWAP';
  authorization_ticket: string;
  confirmation_text: string;
  default_strategy_id: string;
  default_candidate_id: string;
  default_reason: string;
  strategies: DemoStrategySpec[];
  safety: Record<string, boolean>;
};

export type DemoPosition = {
  instrument_id: string;
  position_side: string;
  margin_mode: string;
  contracts: string;
  average_price: string;
  mark_price: string;
  liquidation_price: string;
  unrealized_pnl: string;
  realized_pnl: string;
  leverage: string;
  updated_at_ms: string;
};

export type DemoOrder = {
  order_id: string;
  client_order_id: string;
  instrument_id: string;
  side: string;
  position_side: string;
  order_type: string;
  state: string;
  price: string;
  average_price: string;
  size: string;
  filled_size: string;
  fee: string;
  pnl: string;
  created_at_ms: string;
  updated_at_ms: string;
};

export type DemoFill = {
  fill_id: string;
  order_id: string;
  client_order_id: string;
  instrument_id: string;
  side: string;
  position_side: string;
  price: string;
  size: string;
  fee: string;
  fee_currency: string;
  pnl: string;
  execution_type: string;
  timestamp_ms: string;
};

export type DemoBill = {
  bill_id: string;
  instrument_id: string;
  currency: string;
  type: string;
  sub_type: string;
  balance_change: string;
  fee: string;
  pnl: string;
  timestamp_ms: string;
};

export type DemoOperatorControl = {
  schema_version: 'btc_demo_operator_control_v1';
  lifecycle: 'starting_preflight' | 'running' | 'degraded_no_new_risk' | 'stopped_clean' | 'stopped_needs_preflight';
  lifecycle_label: string;
  session_active: boolean;
  new_risk_allowed: boolean;
  safe_mode: 'normal' | 'cancel_only' | 'frozen_unknown';
  safe_mode_label: string;
  incident: {
    category: 'none' | 'service_restart' | 'network_transport' | 'preflight_progress' | 'account_risk' | 'runtime_recovery' | 'runtime_fault';
    severity: 'info' | 'warning' | 'danger' | 'critical';
    title: string;
    summary: string;
    impact_scope: 'none' | 'demo_start' | 'new_risk_only' | 'account_and_order_safety';
    impact_label: string;
    reason_codes: string[];
    current_attempt?: boolean;
    historical_reason_codes?: string[];
  };
  primary_action: {
    code: 'none' | 'wait_for_preflight' | 'authoritative_preflight_start' | 'stop_keep_position' | 'inspect_and_stop';
    label: string;
  };
  allowed_actions: {
    authoritative_preflight_start: boolean;
    direct_start: false;
    refresh_account_snapshot: boolean;
    stop_keep_position: boolean;
    stop_and_flatten: boolean;
    enter_cancel_only: boolean;
    emergency_reduce_only_exit?: boolean;
    acknowledge_guardian_trip?: boolean;
    recover_guardian_after_fresh_preflight?: boolean;
  };
  start_capability?: {
    ready?: boolean;
    incident_category?: string;
    blockers?: string[];
  };
  start_operation?: DemoStartOperation;
  /** Server-authoritative current StartAttempt read model. */
  start_attempt?: DemoStartAttempt;
  /** Historical attempts are retained for audit and never authorize a start. */
  historical_start_attempts?: DemoStartAttempt[];
  preflight_stages: Array<{
    key: string;
    label: string;
    state: 'ready' | 'waiting' | 'blocked';
    detail: string;
  }>;
  evidence: {
    status: 'ready' | 'incomplete';
    impact_scope: 'promotion_only';
    blocks_demo_start: false;
    reason_codes: string[];
  };
  raw_state: {
    runtime_status: string;
    risk_mode: string;
    risk_reason: string;
  };
};

export type DemoStartOperation = {
  schema_version?: 'btc_demo_start_operation_v1' | string;
  accepted?: boolean;
  operation_id: string;
  attempt_id: string;
  idempotency_key: string;
  request_fingerprint: string;
  state: 'idle' | 'queued' | 'running' | 'completed' | 'blocked' | 'interrupted' | 'timed_out' | string;
  phase: string;
  revision: number;
  started_at_utc: string;
  updated_at_utc: string;
  deadline_utc: string;
  source_head: string;
  owner?: {pid?: number; nonce?: string; create_time_utc?: string};
  worker_generation?: number;
  incident?: {category?: string; code?: string};
  blockers?: string[];
  terminal_error?: string;
  post_counts?: {orders?: number; cancels?: number; dead_man?: number};
  parent_operation_id?: string;
  inner_operation_id?: string;
  runtime_identity?: string;
  effective_policy_digest?: string;
  risk_profile?: string;
  expected_leverage?: string;
  account_identity_hash?: string;
  current_attempt?: boolean;
  historical?: boolean;
  historical_reason_codes?: string[];
  actual_long_leverage?: string | null;
  actual_short_leverage?: string | null;
  start_attempt?: DemoStartAttempt;
};

export type DemoStartAttempt = {
  schema_version?: 'btc_demo_start_attempt_v1' | string;
  parent_operation_id: string;
  inner_operation_id: string;
  attempt_id: string;
  runtime_identity: string;
  source_head: string;
  effective_policy_digest: string;
  risk_profile: string;
  expected_leverage: string;
  account_identity_hash: string;
  created_at_utc: string;
  updated_at_utc: string;
  state?: string;
  phase?: string;
  current_attempt: boolean;
  historical: boolean;
  historical_reason_codes: string[];
  actual_long_leverage?: string | null;
  actual_short_leverage?: string | null;
};

export type PrivateReadonlyObservationProjection = {
  schema_version: 'btc_private_readonly_observation_projection_v1';
  status: 'observing' | 'historical' | 'blocked';
  freshness: 'current' | 'stale';
  source_head: string;
  current_head: string;
  head_match: boolean;
  runner_active: boolean;
  gate_eligible: false;
  run_id: string;
  runtime_version: string;
  phase: string;
  started_at_utc: string;
  eligible_since_utc: string;
  last_observed_at_utc: string;
  generated_at_utc: string;
  state_revision: number;
  restart_count: number;
  recovery_count: number;
  progress: {
    required_hours: number;
    completed_hours: number;
    current_hour_fraction: number;
    progress_hours: number;
    remaining_hours: number;
    receipt_count: number;
    last_receipt_hour_utc: string;
    complete: boolean;
  };
  private_ws: {
    connected: boolean;
    listener_alive: boolean;
    reconciled: boolean;
  };
  reconciliation: {
    rest_snapshot_observed: boolean;
    snapshot_reconciled: boolean;
    funding_reconciled: boolean;
  };
  blockers: string[];
  gap_flags: string[];
  safety_flags: {
    promotion: false;
    paper: false;
    live: false;
    private: false;
    order: false;
    real_order: false;
    transfer: false;
    withdraw: false;
  };
};

export type DemoRuntimeStatus = {
  schema_version: string;
  runtime_version: string;
  start_capability?: {
    ready?: boolean;
    incident_category?: string;
    blockers?: string[];
  };
  risk_profile?: {
    name?: string;
    max_configured_leverage?: string;
    instrument_id?: string;
    margin_mode?: string;
  };
  environment: 'OKX Demo';
  instrument_id: 'BTC-USDT-SWAP';
  runtime: {
    run_id: string;
    status: string;
    active: boolean;
    worker_alive: boolean;
    opening_allowed: boolean;
    cancel_only: boolean;
    started_at_utc: string;
    stopped_at_utc: string;
    last_heartbeat_utc: string;
    last_reconciled_at_utc: string;
    last_processed_bar_close_utc: string;
    last_error: string;
    blockers: string[];
    orders_submitted: number;
    fills_observed: number;
    authorization_ticket: string;
    start_operation?: DemoStartOperation;
  };
  start_operation?: DemoStartOperation;
  start_attempt?: DemoStartAttempt;
  historical_start_attempts?: DemoStartAttempt[];
  private_ws: {
    status?: string;
    connected: boolean;
    listener_alive: boolean;
    opening_allowed_after_reconciliation: boolean;
    reconnect_rest_reconciled?: boolean;
    blockers?: string[];
    promotion_evidence_ready: boolean;
  };
  observation: {
    observation_receipt_count: number;
    consecutive_hours: number;
    window_complete: boolean;
    cumulative_observation_hours?: number;
    cumulative_window_25h_complete?: boolean;
    cumulative_blockers?: string[];
    ledger_hash: string;
    last_receipt_sha256: string;
    last_observation_hour_utc: string;
    blockers: string[];
    promotion_evidence_ready: boolean;
  };
  ledger_reconciliation: {
    status: string;
    current_state_exchange_snapshot_match: boolean;
    funding_cashflow_reconciled: boolean;
    order_count?: number;
    pending_order_count?: number;
    fill_count?: number;
    position_count?: number;
    funding_bill_count?: number;
    funding_cashflow?: string;
    last_funding_ledger_hash: string;
    fixture: boolean;
    promotion_evidence_ready: boolean;
  };
  operator_control?: DemoOperatorControl;
  guardian?: {
    schema_version?: string;
    persistence_state?: string;
    status?: string;
    tripped?: boolean;
    acknowledged?: boolean;
    reason_codes?: string[];
    generation?: number;
    state_revision?: number;
    evidence_identity?: string;
    evidence_digest?: string;
    observation_digest?: string;
    last_observation_identity?: string;
    last_observation_digest?: string;
    last_observation_time_utc?: string | null;
    position?: {nonflat?: boolean; contracts?: string; side?: string};
    exposure?: {value?: string; mark_price?: string; unit?: string};
    pnl?: {realized?: string; unrealized?: string; unit?: string};
    drawdown?: {value?: string | null; unit?: string; provenance?: string};
    next_safe_action?: string;
  };
  risk_control?: {
    mode?: string;
    reason?: string;
    write_path_trusted?: boolean;
    dead_man?: {
      armed?: boolean;
      heartbeat_thread_alive?: boolean;
      watchdog_renews_dead_man?: boolean;
      last_ack_utc?: string;
      last_error?: string;
    };
  };
  strategy: Partial<DemoStrategySpec>;
  limits: Record<string, string>;
  signal: Record<string, unknown>;
  exchange: {
    captured_at_utc: string;
    account: {
      account_level?: string;
      position_mode?: string;
      permissions?: string[];
      withdraw_permission_present?: boolean;
      identity?: {hash?: string; source?: string; captured_at_utc?: string};
    };
    balance: {equity_usdt?: string; available_usdt?: string; unrealized_pnl_usdt?: string; timestamp_ms?: string};
    positions: DemoPosition[];
    pending_orders: DemoOrder[];
    pending_algo_orders?: Array<{
      algo_id?: string;
      algo_client_order_id?: string;
      state?: string;
      order_type?: string;
    }>;
    orders: DemoOrder[];
    fills: DemoFill[];
    bills: DemoBill[];
    fee_schedule: {level?: string; maker_rate?: string; taker_rate?: string; rule_type?: string; timestamp_ms?: string};
    funding: {funding_rate?: string; next_funding_rate?: string; funding_time_ms?: string; next_funding_time_ms?: string};
    ticker: {bid?: string; ask?: string; last?: string; timestamp_ms?: string};
    mark: {mark_price?: string; timestamp_ms?: string};
  };
  audit: Array<Record<string, unknown>>;
  events: Array<{event_id: string; timestamp_utc: string; event_type: string; payload: Record<string, unknown>}>;
  safety: Record<string, boolean>;
};

export type LocalKlineResponse = {
  db_path: string;
  read_only: boolean;
  schema_maintenance_performed: boolean;
  source_kind: string;
  source_sha256: string;
  strategy_signal_compatible: boolean;
  sample_end: string;
  freshness_status: string;
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

export type PublicMarketView = {
  schema_version: 'okx_public_market_view_v1';
  source_kind: 'okx_public_market_view_v1';
  instrument_id: 'BTC-USDT-SWAP';
  timeframe: '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w' | '1M';
  read_only: true;
  public_only: true;
  private_endpoint_used: false;
  order_endpoint_used: false;
  strategy_signal_compatible: false;
  persisted_market_rows: false;
  captured_at_ms: number;
  cache_age_ms: number;
  stale: boolean;
  last_error_code: string;
  depth_source?: 'okx_public_ws' | 'okx_public_rest_books5' | 'unavailable' | string;
  depth_error_code?: string;
  ticker: {bid: string; ask: string; last: string; timestamp_ms: number};
  candles: Array<{
    open_time_ms: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    confirmed: boolean;
    in_progress: boolean;
  }>;
  depth?: {
    source?: 'okx_public_ws' | 'okx_public_rest_books5' | string;
    instrument_id: 'BTC-USDT-SWAP';
    bids: Array<{price: string; size: string; count: string}>;
    asks: Array<{price: string; size: string; count: string}>;
    spread: string;
    top5_imbalance: number;
    timestamp_ms: number;
    sequence?: number | null;
    checksum?: string | null;
  } | null;
};

export type PublicMarketTicker = {
  schema_version: 'okx_public_market_ticker_v1';
  source_kind: 'okx_public_market_ticker_v1';
  instrument_id: 'BTC-USDT-SWAP';
  read_only: true;
  public_only: true;
  private_endpoint_used: false;
  order_endpoint_used: false;
  strategy_signal_compatible: false;
  persisted_market_rows: false;
  captured_at_ms: number;
  cache_age_ms: number;
  stale: boolean;
  last_error_code: string;
  ticker: {bid: string; ask: string; last: string; timestamp_ms: number};
};

export type PublicMarketStreamEvent = {
  schema_version: 'btc_okx_public_market_stream_v1';
  instrument_id: 'BTC-USDT-SWAP';
  public_only: true;
  display_only: true;
  persisted: false;
  strategy_signal_compatible: false;
  private_endpoint_accessed: false;
  order_endpoint_accessed: false;
  status: 'live' | 'stale' | 'reconnecting';
  last_error_code: string;
  last_update_ms: number;
  subscriber_count: number;
  trade: {trade_id: string; price: string; size: string; side: 'buy' | 'sell'; timestamp_ms: number} | null;
  depth: {
    bids: Array<{price: string; size: string; count: string}>;
    asks: Array<{price: string; size: string; count: string}>;
    spread: string;
    top5_imbalance: number;
    timestamp_ms: number;
    sequence: number;
  } | null;
};

export type BacktestSnapshot = {
  run: RunStatusResponse;
  chart: ChartSeriesPayload | null;
  strategyId: string;
  candidateId: string;
  strategyVersion: string;
  paramsHash: string;
  savedAt: string;
  versionId?: string;
  request?: {
    start: string;
    end: string;
    capital: number;
    dataVersion: string;
  };
};
