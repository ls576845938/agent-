import type {Summary} from './view-model';

export type ValueEvent = {target: {value: string}};

export type CryptoInterval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

export type CryptoCoverageSummary = {
  total_rows: number;
  covered_intervals: number;
  missing_intervals: CryptoInterval[];
  latest_updated_at?: string | null;
};

export type CryptoResamplePlanItem = {
  exchange: string;
  symbol: string;
  source_interval: CryptoInterval;
  target_interval: CryptoInterval;
  rows: number;
  start?: string | null;
  end?: string | null;
  updated_at?: string | null;
  status: 'seed' | 'ready' | 'missing';
  action: string;
  db_path: string;
};

export type CryptoBlockerGroup = {
  title: string;
  blockers: string[];
  tone: 'good' | 'neutral' | 'warn' | 'bad';
};

export type BtcScalpingResearchBacktest = {
  label: string;
  timeframe: '1m' | '5m';
  status: string;
  strategy_id: string;
  variant_id: string;
  scope: string;
  report_path: string | null;
  run_dir: string | null;
  artifacts: Record<string, string | null>;
  metrics: {
    event_count?: number | null;
    trade_count?: number | null;
    fill_count?: number | null;
    profit_factor?: number | null;
    hit_rate?: number | null;
    mean_trade_return_bps?: number | null;
    total_return_pct?: number | null;
    max_drawdown?: number | null;
    walk_forward_pass_rate?: number | null;
    regime_pass_rate?: number | null;
  };
  gate_passed: boolean;
  gate_status: string;
  blockers: string[];
  manifest: {
    path: string | null;
    present: boolean;
    required_fields_present: Record<string, boolean>;
    complete: boolean;
    paper_queue: string | null;
    live: string | null;
  };
  research_only_lock: {
    candidate_generation_allowed: false;
    strategy_skeleton_generation_allowed: false;
    paper_or_live_unlock_allowed: false;
    true_scalping_allowed: false;
  };
};

export type BtcScalpingResearchBacktestReport = {
  schema_version: 'btc_scalping_research_backtest_report_v1';
  generated_at: string;
  asset: 'btc';
  symbol: 'BTCUSDT';
  scope: string;
  status: string;
  decision: string;
  next_required_action: string;
  recommended_research_track: 'five_minute_drift_guarded_intraday' | 'one_minute_proxy_scalping' | 'none';
  operator_summary: {
    current_research_answer: string;
    run_command: string;
    direct_command: string;
  };
  backtests: {
    one_minute_proxy_scalping: BtcScalpingResearchBacktest;
    five_minute_drift_guarded_intraday: BtcScalpingResearchBacktest;
  };
  manifest_contract: {
    required_fields: string[];
    one_minute_proxy_scalping_complete: boolean;
    five_minute_drift_guarded_intraday_complete: boolean;
  };
  guardrails: {
    research_only: boolean;
    strategy_outputs_only: string[];
    broker_calls_allowed: false;
    private_endpoints_allowed: false;
    order_endpoints_allowed: false;
    real_orders_created: false;
    candidate_generation_allowed: false;
    paper_or_live_unlock_allowed: false;
    paper_queue: 'LOCKED';
    live: 'FROZEN';
    pnl_from_fill_or_trade_ledger: boolean;
  };
};

export type BtcTrendForwardSeriesPoint = {
  timestamp: string;
  buy_hold_equity?: number | null;
  strategy_equity?: number | null;
  target_exposure?: number | null;
  close?: number | null;
};

export type BtcTrendForwardLedgerRow = {
  timestamp?: string;
  generated_at?: string;
  strategy_id?: string;
  symbol?: string;
  raw_signal?: number | null;
  target_exposure?: number | null;
  prior_exposure?: number | null;
  signal_timestamp?: string;
  effective_timestamp?: string;
  reason?: string;
  equity?: number | null;
  prior_equity?: number | null;
  simulated_fee?: number | null;
  turnover?: number | null;
  reconciliation_status?: string;
};

export type BtcTrendForwardStatusResponse = {
  schema_version: 'btc_trend_forward_status_v1';
  generated_at: string;
  asset: 'btc';
  symbol: 'BTCUSDT';
  status: 'ok' | 'partial' | string;
  missing_sources: string[];
  daily_run: {
    status: string;
    generated_at: string;
    data_refresh_status: string;
    readiness_status: string;
    roll_status: string;
    roll_cycle_status: string;
    evaluation_status: string;
    daily_rows: number;
    sample_start: string;
    sample_end: string;
  };
  strategy: {
    strategy_id: string;
    family_id: string;
    candidate_id: string;
    validation_status: string;
    validation_decision: string;
    selected_total_return_pct?: number | null;
    selected_max_drawdown_abs_pct?: number | null;
    selected_sharpe_ratio?: number | null;
    buy_hold_total_return_pct?: number | null;
    buy_hold_max_drawdown_abs_pct?: number | null;
    buy_hold_sharpe_ratio?: number | null;
  };
  current_signal: {
    timestamp: string;
    close?: number | null;
    raw_signal?: number | null;
    target_exposure?: number | null;
    signal_timestamp: string;
    effective_timestamp: string;
    reason: string;
    current_equity?: number | null;
  };
  forward_observation: {
    status: string;
    observation_days: number;
    minimum_complete_days: number;
    milestone_progress: Record<string, boolean>;
    target_position_count: number;
    target_position_change_count: number;
    simulated_fill_count: number;
    total_return_pct: number;
    max_drawdown_abs_pct: number;
    targets: BtcTrendForwardLedgerRow[];
    snapshots: BtcTrendForwardLedgerRow[];
    fills: BtcTrendForwardLedgerRow[];
  };
  gates: {
    paper_operational_status: string;
    volatility_branch_status: string;
    hft_freeze_status: string;
    private_endpoint_used: boolean;
    order_endpoint_used: boolean;
    live_order_allowed: boolean;
    real_order_submitted: boolean;
  };
  charts: {
    strategy_series: BtcTrendForwardSeriesPoint[];
  };
  source_files: Record<string, string>;
};

export type BtcSafetyGate = {
  research_only?: boolean;
  read_only_artifact_aggregation?: boolean;
  strategy_rerun_used?: boolean;
  network_collection_used?: boolean;
  broker_access_allowed?: boolean;
  broker_or_order_allowed?: boolean;
  oms_access_allowed?: boolean;
  paper_allowed?: boolean;
  paper_candidate_created?: boolean;
  paper_queue_write_allowed?: boolean;
  private_endpoint_used?: boolean;
  order_endpoint_used?: boolean;
  live_order_allowed?: boolean;
  live_unlock_allowed?: boolean;
  real_order_submitted?: boolean;
  strategy_skeleton_generated?: boolean;
  [key: string]: unknown;
};

export type BtcStrategyLedgerLine = {
  strategy_id: string;
  display_name_cn?: string;
  bucket?: string;
  role?: string;
  status?: string;
  decision?: string | null;
  latest_report_path?: string;
  latest_report_status?: string;
  latest_report_generated_at_utc?: string;
  input_data?: string[];
  parameter_summary?: Record<string, unknown>;
  latest_signal_or_exposure?: Record<string, unknown>;
  observation_days?: number | null;
  observation_count?: number | null;
  blockers?: string[];
  next_action?: string;
  keep_or_retire_recommendation?: string;
  is_auxiliary_model?: boolean;
  is_trade_strategy?: boolean;
  research_only?: boolean;
  paper_queue_write_allowed?: boolean;
  paper_allowed?: boolean;
  live_unlock_allowed?: boolean;
  broker_or_order_allowed?: boolean;
};

export type BtcStrategyLedgerReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  line_count?: number;
  fixed_strategy_line_count?: number;
  missing_report_count?: number;
  unsafe_line_count?: number;
  blockers?: string[];
  strategy_lines?: BtcStrategyLedgerLine[];
  gate?: BtcSafetyGate;
  guardrails?: BtcSafetyGate;
  outputs?: Record<string, string>;
};

export type BtcPromotionGateControlRow = {
  gate_id: string;
  gate_name_cn?: string;
  status?: string;
  blockers?: string[];
  checks?: Record<string, unknown>;
  next_action_cn?: string;
  responsible_automation?: string;
  source_ids?: string[];
  paper_queue_write_allowed?: boolean;
  paper_allowed?: boolean;
  live_unlock_allowed?: boolean;
  broker_or_order_allowed?: boolean;
};

export type BtcPromotionGateControlReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  gate_count?: number;
  blocked_gate_count?: number;
  missing_source_count?: number;
  safety_violation_count?: number;
  safety_violations?: string[];
  key_blockers_cn?: string[];
  legacy_paper_readiness_conflict?: boolean;
  gate_matrix?: BtcPromotionGateControlRow[];
  root_cause_summary?: Record<string, unknown>;
  root_cause_matrix?: Array<Record<string, unknown>>;
  root_cause_dag?: Record<string, unknown>;
  source_paths?: Record<string, string>;
  guardrails?: BtcSafetyGate;
};

export type BtcLeakageOverfitAuditReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  summary?: Record<string, unknown>;
  long_short_top5_audit?: Record<string, unknown>;
  high_octane_v2_audit?: Record<string, unknown>;
  data_coverage_audit?: Record<string, unknown>;
  leakage_checks?: Array<Record<string, unknown>>;
  warnings?: string[];
  guardrails?: BtcSafetyGate;
};

export type BtcAttackSleeveRiskStressReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  summary?: Record<string, unknown>;
  research_design?: Record<string, unknown>;
  top_risk_rows?: Array<Record<string, unknown>>;
  warnings?: string[];
  guardrails?: BtcSafetyGate;
};

export type BtcAttackStrategyContinuationShortlistReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  line_count?: number;
  continued_research_strategy_count?: number;
  danger_reference_count?: number;
  strategy_lines?: Array<Record<string, unknown>>;
  global_next_steps?: string[];
  warnings?: string[];
  guardrails?: BtcSafetyGate;
};

export type BtcAttackFollowupReviewReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  summary?: Record<string, unknown>;
  high_octane_strict_rows?: Array<Record<string, unknown>>;
  same_window_comparison_rows?: Array<Record<string, unknown>>;
  rolling_comparison_summary?: Record<string, unknown>;
  warnings?: string[];
  guardrails?: BtcSafetyGate;
};

export type BtcMicroLiveExperimentPacketReport = {
  schema_version?: string;
  status?: string;
  decision?: string;
  generated_at_utc?: string;
  summary?: Record<string, unknown>;
  experiment_rules?: Record<string, unknown>;
  observe_only_recorder?: {
    frequency?: string;
    record_count?: number;
    latest_decision_time?: string;
    latest_direction?: string;
    latest_triggered_strategies?: string[];
    records?: Array<Record<string, unknown>>;
  };
  alert_only?: {
    order_action_allowed?: boolean;
    alert_count?: number;
    block_alert_count?: number;
    alerts?: Array<Record<string, unknown>>;
  };
  no_trade_execution_rehearsal?: {
    real_order_submitted?: boolean;
    order_endpoint_used?: boolean;
    depth_context?: Record<string, unknown>;
    rows?: Array<Record<string, unknown>>;
  };
  pre_live_checklist?: Record<string, unknown>;
  warnings?: string[];
  blockers?: string[];
  gate?: BtcSafetyGate;
  guardrails?: BtcSafetyGate;
};

export type BtcResearchControlCenterResponse = {
  schema_version: string;
  generated_at_utc: string;
  status: string;
  decision: string;
  missing_sources: string[];
  source_paths: Record<string, string>;
  safety_violations: string[];
  provenance: {
    status: string;
    snapshot_status: string;
    snapshot_error: string;
    snapshot_commit: string;
    current_head: string;
    current_head_match: boolean;
    aggregation_batch_id: string;
    batch_id: string;
    manifest_path: string;
    manifest_sha256: string;
    manifest_hash: string;
  };
  summary: Record<string, unknown>;
  operator_summary?: Record<string, unknown>;
  reports: {
    strategy_ledger?: BtcStrategyLedgerReport;
    promotion_gate_control?: BtcPromotionGateControlReport;
    gate_dashboard?: Record<string, unknown>;
    leakage_overfit_audit?: BtcLeakageOverfitAuditReport;
    attack_sleeve_risk_stress?: BtcAttackSleeveRiskStressReport;
    attack_strategy_continuation_shortlist?: BtcAttackStrategyContinuationShortlistReport;
    attack_followup_review?: BtcAttackFollowupReviewReport;
    micro_live_experiment_packet?: BtcMicroLiveExperimentPacketReport;
    data_status?: Record<string, unknown>;
    paper_account_attestation?: Record<string, unknown>;
    exchange_runtime_local_probe?: Record<string, unknown>;
    exchange_runtime_gap?: Record<string, unknown>;
    kill_switch?: Record<string, unknown>;
    micro_live_preflight?: Record<string, unknown>;
    paper_runtime_replay?: Record<string, unknown>;
    [key: string]: unknown;
  };
  guardrails: BtcSafetyGate;
};

export type BtcOperatorSummaryTask = {
  root_cause_id: string;
  category: 'data_wait' | 'sample_wait' | 'engineering_action' | 'manual_action' | 'incident';
  label: string;
  owner: string;
  next_action: string;
  raw_blocker_count: number;
  acceptance_criteria: string[];
  evidence_paths: string[];
};

export type BtcOperatorSummaryResponse = {
  schema_version: string;
  generated_at_utc: string;
  status: string;
  decision: string;
  state_kinds: string[];
  snapshot: {
    status: string;
    error: string;
    aggregation_batch_id: string;
    code_commit: string;
    snapshot_commit: string;
    current_head: string;
    current_head_match: boolean;
    batch_id: string;
    published_at_utc: string;
    manifest_path: string;
    manifest_sha256: string;
    manifest_hash: string;
  };
  root_causes: Array<{
    root_cause_id: string;
    category: string;
    label: string;
    owner: string;
    next_action: string;
    raw_blocker_count: number;
    evidence_paths: string[];
  }>;
  tasks: Record<string, BtcOperatorSummaryTask[]>;
  freshness: {
    status: string;
    snapshot_commit: string;
    current_head: string;
    current_head_match: boolean;
    stale_source_count: number;
    missing_source_count: number;
    mismatch_count: number;
    future_source_count: number;
    dependency_newer_than_consumer_count: number;
    max_source_age_hours: number | null;
    required_rebuild_reports: string[];
  };
  missing_sources: Array<{artifact_id: string; logical_path: string; error: string}>;
  safety: BtcSafetyGate & {violations: string[]};
  evidence_links: Array<{
    artifact_id: string;
    api_path: string;
    logical_path: string;
    snapshot_source: string;
    aggregation_batch_id: string;
    status: string;
  }>;
};

export type BtcStrategyRegistrySpec = {
  strategy_id: string;
  candidate_id: string;
  strategy_version: string;
  params_hash: string;
  instrument: string;
  venue: string;
  timeframe: string;
  direction_policy: string;
  promotion_eligibility: string;
  promotion_credit_eligible: boolean;
  promotion_credit_allowed: false;
  adapter_fidelity: string;
  signal_data_venue: string;
  execution_venue: string;
  signal_instrument: string;
  execution_instrument: string;
  canonical_signal_available: boolean;
  strategy_callable: string;
  params: Record<string, unknown>;
};

export type BtcStrategyRegistryResponse = {
  schema_version: string;
  status: string;
  decision: string;
  default_strategy_id: string;
  default_candidate_id: string;
  specs: BtcStrategyRegistrySpec[];
  paper_queue_write_allowed: false;
  live_unlock_allowed: false;
  broker_or_order_allowed: false;
};

export type SystemOverviewResponse = {
  status: string;
  stage: string;
  mode: string;
  data_root: string;
  health: {
    service?: string;
    data_source_default?: string;
    fastapi_available?: boolean;
  };
  registry: {
    state?: string;
    integrity?: string;
    path?: string;
    counts?: Record<string, number>;
    notes?: string[];
    rebuild_available?: boolean;
  };
  paper_validation: {
    state?: string;
    days_completed?: number;
    days_required?: number;
    consecutive_clean_days?: number;
    submit_orders?: string;
    audit_blocker_status?: string;
    data_strict_status?: string;
    recovery_status?: string;
    gaps?: string[];
    evidence?: Array<Record<string, unknown>>;
  };
  minute_data_quality?: {
    status?: string;
    evaluated_symbols?: string[];
    bar_sizes?: string[];
    symbols?: Array<Record<string, unknown>>;
    lookback_trading_days?: number;
    datasets?: Array<Record<string, unknown>>;
    evidence_summary?: Record<string, unknown>;
    remediation_summary?: {
      action_count?: number;
      download_performed?: boolean;
      actions?: Array<Record<string, unknown>>;
    };
    dataset_statuses?: Record<string, {
      status?: string;
      dataset_root?: string;
      issue_count?: number;
      evaluated_symbols?: string[];
      coverage_pct?: number | null;
      min_coverage_pct?: number | null;
    }>;
  };
  data_coverage?: {
    status?: string;
    coverage_pct?: number | null;
    min_coverage_pct?: number | null;
    dataset_summaries?: Array<{
      root_subdir?: string;
      status?: string;
      issue_count?: number;
      evaluated_symbols?: string[];
      coverage_pct?: number | null;
      min_coverage_pct?: number | null;
    }>;
  };
  paper_review: {
    status?: string;
    entry_allowed?: boolean;
    manual_review_pending?: boolean;
    summary?: string;
    evidence_path?: string;
    review_path?: string;
    manifest_path?: string;
    evidence_pack_path?: string;
    creation?: {
      creation_allowed?: boolean;
      why_blocked?: string[];
      next_command?: string;
      eligible_manifest_ids?: string[];
      eligible_candidate_ids?: string[];
      preferred_manifest_id?: string;
      preferred_candidate_id?: string;
      create_from_manifest_command?: string;
      create_from_candidate_command?: string;
      eligible_manifest_count?: number;
      eligible_candidate_count?: number;
      summary?: string;
      eligible_manifest_rows?: Array<{
        strategy_manifest_id?: string;
        source_candidate_id?: string;
        promotion_status?: string;
        paper_review_candidate_status?: string;
        paper_review_evidence_pack_path?: string;
        paper_review_id?: string;
      }>;
    };
    diagnostics?: {
      registry_state?: string;
      registry_integrity?: string;
      conflict_notes?: string[];
      latest_review_status?: string;
      latest_manifest_status?: string;
      conflict_detected?: boolean;
    };
  };
  broker_credentials: {
    credentials_present?: boolean;
    api_key_present?: boolean;
    api_secret_present?: boolean;
    endpoint_kind?: string;
    base_url_valid?: boolean;
    allowed_base_url?: string;
  };
  execution: {
    strategy_direct_broker_allowed?: boolean;
    paper_submit_default?: string;
    paper_network_submit_confirmation?: boolean;
    paper_submit_requires?: string[];
    live_submit_allowed?: boolean;
    live_state?: string;
    live_block_reason?: string;
  };
  small_account: {
    profile?: string;
    splitting_required?: boolean;
    default_capital?: number;
    suggested_max_order_notional?: number;
    suggested_max_daily_notional?: number;
    suggested_max_daily_order_count?: number;
  };
  integrations?: {
    dependencies?: {
      qlib?: boolean;
      lightgbm?: boolean;
      pypfopt?: boolean;
    };
    qlib?: {
      artifacts_root?: string;
      run_count?: number;
      status?: string;
      latest_run_id?: string;
      latest_updated_at?: string;
      latest_run?: Record<string, unknown>;
    };
    portfolio?: {
      artifacts_root?: string;
      run_count?: number;
      status?: string;
      latest_run_id?: string;
      latest_updated_at?: string;
      latest_run?: Record<string, unknown>;
    };
  };
  pit_data_intake?: {
    status?: string;
    current_blocking_stage?: string;
    next_action?: {
      stage_id?: string;
      description?: string;
      first_blocker?: string;
    };
    stages?: Array<{
      stage_id?: string;
      status?: string;
      report_status?: string;
      blockers?: string[];
      summary?: Record<string, unknown>;
    }>;
    blockers?: string[];
    source_report?: string;
    operator_actions?: Array<{
      label?: string;
      intent?: string;
      command?: string;
      blocked_until?: string;
    }>;
  };
  pit_operator_handoff?: {
    status?: string;
    current_blocking_stage?: string;
    current_blocking_step?: string;
    incoming_drop_dir?: string;
    default_bundle_id?: string;
    required_table_count?: number;
    required_tables?: Array<{
      table?: string;
      filename?: string;
      field_count?: number;
      minimum_record_count?: number;
      empty_template_is_not_valid_drop?: boolean;
    }>;
    operator_next_actions?: string[];
    commands?: Record<string, string>;
    blockers?: string[];
    outputs?: Record<string, string>;
    source_reports?: Record<string, unknown>;
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  development_plan_audit?: {
    status?: string;
    decision?: string;
    summary?: {
      phase_count?: number;
      complete_count?: number;
      blocked_count?: number;
      observing_count?: number;
      action_required_count?: number;
    };
    phase_checks?: Array<{
      phase_id?: string;
      title?: string;
      status?: string;
      blockers?: string[];
      blocked_count?: number;
      metrics?: Record<string, unknown>;
    }>;
    blockers?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  live_readiness?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    account_capital_usd?: number;
    max_live_principal_usd?: number;
    live_order_allowed?: boolean;
    paper_simulation_unlocked_by_this_report?: boolean;
    blockers?: string[];
    gate_checks?: Record<string, unknown>;
    risk_constitution?: Record<string, unknown>;
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  strategy_validation_gate?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    candidate_variant?: string;
    allowed_next_action?: string;
    forward_observation_allowed?: boolean;
    paper_ready?: boolean;
    live_ready?: boolean;
    blockers?: string[];
    checks?: Array<Record<string, unknown>>;
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  forward_observation?: {
    status?: string;
    decision?: string;
    daily_health_status?: string;
    daily_health_decision?: string;
    observation_days?: number;
    minimum_complete_days?: number;
    latest_observation_date?: string;
    ledger?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    blockers?: string[];
    warnings?: string[];
    source_reports?: Record<string, string>;
    guardrails?: Record<string, unknown>;
  };
  manual_review_packet?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    blockers?: string[];
    evidence_checklist?: Array<Record<string, unknown>>;
    signoff_requirements?: Array<Record<string, unknown>>;
    review_milestones?: Array<Record<string, unknown>>;
    paper_or_live_unlock_decision?: Record<string, unknown>;
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  paper_simulation_readiness?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    paper_ledger_root?: string;
    paper_runner_allowed?: boolean;
    required_runner_contract?: Record<string, unknown>;
    manual_review_evidence?: Record<string, unknown>;
    blockers?: string[];
    unsafe_flags?: string[];
    source_reports?: Record<string, string>;
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  small_account_execution_preflight?: {
    status?: string;
    strategy_id?: string;
    candidate_variant?: string;
    timestamp?: string;
    account_equity?: number;
    annual_financing_rate?: number;
    slippage_bps?: number;
    min_trade_amount_usd?: number;
    latest_target?: Record<string, unknown>;
    scenario_count?: number;
    passed_scenario_count?: number;
    scenarios?: Array<{
      scenario_id?: string;
      description?: string;
      gross_cap?: number;
      effective_gross?: number;
      allow_margin?: boolean;
      passes_preflight?: boolean;
      fractional_cash_after_orders?: number;
      fractional_estimated_financing_daily?: number;
      fractional_estimated_slippage?: number;
      whole_cash_after_orders?: number;
      whole_estimated_slippage?: number;
      first_blocker?: string;
    }>;
    blockers?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  data_lineage_governance?: {
    status?: string;
    reconciliation_status?: string;
    remediation_status?: string;
    macro_release_lag_status?: string;
    selected_price_source?: string;
    selected_price_root?: string;
    lineage_maturity?: string;
    remediation_task_count?: number;
    remediation_groups?: Array<{
      group_id?: string;
      status?: string;
      blocker_count?: number;
    }>;
    macro_source?: string;
    accepted_evidence_for_promotion?: boolean;
    blockers?: string[];
    source_reports?: Record<string, string>;
    guardrails?: Record<string, unknown>;
  };
  production_data_acquisition?: {
    status?: string;
    acquisition_status?: string;
    candidate_evidence_status?: string;
    candidate_evidence_decision?: string;
    intake_packet_status?: string;
    intake_packet_decision?: string;
    manual_package_status?: string;
    incoming_drop_dir?: string;
    default_bundle_id?: string;
    acceptable_provider_ids?: string[];
    missing_contract_groups?: string[];
    required_table_count?: number;
    field_count?: number;
    required_tables?: Array<{
      table?: string;
      filename?: string;
      field_count?: number;
    }>;
    operator_steps?: Array<{
      step_id?: string;
      command?: string;
      expected_result?: string;
    }>;
    acceptance_commands?: string[];
    blockers?: string[];
    source_reports?: Record<string, string>;
    guardrails?: Record<string, unknown>;
  };
  production_bundle_gate?: {
    status?: string;
    current_blocking_stage?: string;
    stages?: Array<{
      stage_id?: string;
      status?: string;
      decision?: string;
      blockers?: string[];
      source_report?: string;
      summary?: Record<string, unknown>;
    }>;
    operator_actions?: Array<{
      stage_id?: string;
      label?: string;
      command?: string;
      blocked_until?: string;
    }>;
    blockers?: string[];
    source_reports?: Record<string, string>;
    guardrails?: Record<string, unknown>;
  };
  standard_report_schema_audit?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    candidate_variant?: string;
    required_fields?: string[];
    coverage_summary?: {
      required_field_count?: number;
      passed_field_count?: number;
      missing_input_count?: number;
      unsafe_flag_count?: number;
    };
    field_checks?: Array<Record<string, unknown>>;
    blockers?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  monitoring_rules?: {
    status?: string;
    strategy_id?: string;
    monitor_count?: number;
    required_before_paper_or_live?: boolean;
    minimum_required_before_paper?: string[];
    rule_sections?: string[];
    blockers?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  replay_readiness?: {
    status?: string;
    decision?: string;
    strategy_id?: string;
    latest_observation?: Record<string, unknown>;
    checks?: Array<Record<string, unknown>>;
    blockers?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  strategy_registry?: {
    status?: string;
    schema_version?: string;
    strategy_count?: number;
    primary_strategy_id?: string;
    primary_stage?: string;
    primary_status?: string;
    registered_families?: string[];
    stage_counts?: Record<string, number>;
    status_counts?: Record<string, number>;
    strategies?: Array<{
      strategy_id?: string;
      family?: string;
      status?: string;
      current_stage?: string;
      primary_candidate?: boolean;
      paper_ready?: boolean;
      live_ready?: boolean;
    }>;
    policy?: Record<string, unknown>;
    audit?: {
      status?: string;
      strategy_count?: number;
      primary_candidate_count?: number;
      formal_candidate_count?: number;
      missing_required_families?: string[];
      required_families?: string[];
      blockers?: string[];
      warnings?: string[];
      source_report?: string;
      guardrails?: Record<string, unknown>;
    };
    blockers?: string[];
    source_report?: string;
  };
  daily_production_line?: {
    status?: string;
    decision?: string;
    generated_at?: string;
    pipeline?: string;
    step_count?: number;
    passed_step_count?: number;
    failed_step_count?: number;
    expected_external_blocker?: Record<string, unknown>;
    forward_observation?: Record<string, unknown>;
    forward_data_gate?: {
      status?: string;
      checks?: Array<{
        check_id?: string;
        status?: string;
        passed?: boolean;
        first_blocker?: string;
        source_report?: string;
      }>;
      blockers?: string[];
      guardrails?: Record<string, unknown>;
    };
    steps?: Array<{
      step_id?: string;
      status?: string;
      passed?: boolean;
      first_blocker?: string;
      output?: string;
    }>;
    blockers?: string[];
    unsafe_flags?: string[];
    source_report?: string;
    guardrails?: Record<string, unknown>;
  };
  portfolio?: Record<string, unknown>;
  multi_strategy?: Record<string, unknown>;
  multi_strategy_portfolio?: Record<string, unknown>;
  strategy_weights?: Array<Record<string, unknown>>;
  risk_budget?: Record<string, unknown>;
  pnl_attribution?: Array<Record<string, unknown>>;
  gates?: Record<string, unknown>;
  next_actions: string[];
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
  candidateId: string;
  strategyVersion: string;
  dataDbPath: string;
};

export type OptimizationFrameworkItem = {
  priority: number;
  title: string;
  status: string;
  reason: string;
};

export type OptimizationCandidate = {
  rank: number;
  strategy_id: string;
  parameters: Record<string, number>;
  score: number;
  train: Summary;
  validation: Summary;
  overfit_gap: number;
};

export type StrategyOptimizationResponse = {
  status: string;
  selected_priority: string;
  framework: OptimizationFrameworkItem[];
  split: {
    train_start: number; train_end: number;
    validation_start: number; validation_end: number;
    train_rows: number; validation_rows: number;
  };
  baseline?: OptimizationCandidate | null;
  best?: OptimizationCandidate | null;
  candidates: OptimizationCandidate[];
  recommendations: string[];
};

export type CostStressScenario = {
  name: string; label: string;
  commission_multiplier: number; slippage_multiplier: number;
  commission_rate: number; slippage: number;
  survives: boolean; summary: Summary;
  execution: {total_cost: number};
};

export type CostStressResponse = {
  status: string; selected_priority: string;
  framework: OptimizationFrameworkItem[];
  strategy_id: string; strategy_params: Record<string, number>;
  scenarios: CostStressScenario[];
  survival_rate_pct: number;
  worst_case?: CostStressScenario | null; recommendations: string[];
};

export type WalkForwardWindow = {
  fold: number;
  train_start: number; train_end: number;
  validation_start: number; validation_end: number;
  selected_params: Record<string, number>;
  train: Summary; validation: Summary;
  survives: boolean;
};

export type WalkForwardRegime = {
  name: string; label: string;
  coverage_pct: number; survives: boolean;
  summary: Summary;
};

export type WalkForwardResponse = {
  status: string; selected_priority: string;
  framework: OptimizationFrameworkItem[];
  stability: {
    pass_rate_pct: number;
    fold_pass_rate_pct?: number;
    median_oos_sharpe: number;
    avg_oos_return_pct: number;
    parameter_stability_pct: number;
    worst_oos_drawdown_pct: number;
  };
  windows: WalkForwardWindow[];
  regimes: WalkForwardRegime[];
  recommendations: string[];
};

export type PortfolioOptimizationResponse = {
  status: string; selected_priority: string;
  framework: OptimizationFrameworkItem[];
  baseline_summary: Summary; optimized_summary: Summary;
  improvement: {sharpe_delta: number};
  risk_overlay: {
    state: string;
    max_single_weight_pct: number;
    suggested_gross_multiplier: number;
  };
  risk_budget: {
    cash_reserve_pct: number;
    max_pair_abs_correlation: number;
    risk_contributions: Array<{strategy_id: string; risk_contribution_pct: number; weight_pct: number}>;
  };
  optimized_weight_rows: Array<{strategy_id: string; display_name: string; baseline_weight_pct: number; weight_pct: number}>;
  strategy_allocations: Array<{
    strategy_id: string;
    summary: Summary;
    avg_abs_correlation: number;
  }>;
  correlation_pairs: Array<{left: string; right: string; correlation: number; abs_correlation: number}>;
  recommendations: string[];
};

export type DataQualityIssue = {
  severity: string; code: string; message: string;
};

export type DataQualityResponse = {
  status: string; selected_priority: string;
  framework: OptimizationFrameworkItem[];
  source: string; actual_source: string;
  symbol: string; interval: string;
  row_count: number; raw_row_count: number; expected_rows: number;
  coverage_pct: number;
  missing_bars: number; duplicate_timestamps: number;
  cleaning_loss_rows: number; invalid_ohlc: number;
  non_positive_prices: number; non_positive_volume: number;
  large_price_jumps: number; volume_anomalies: number;
  max_gap_bars: number; max_price_jump_pct: number;
  first_timestamp?: string | null; last_timestamp?: string | null;
  quality_score: number; is_usable: boolean;
  fingerprint: string; data_version: string;
  issues: DataQualityIssue[];
};

export type PromotionGate = {
  name: string;
  status: 'pass' | 'warn' | 'fail';
  message: string;
  metrics: Record<string, number | string | boolean>;
  threshold: string;
};

export type PromotionGateResponse = {
  status: string; selected_priority: string;
  framework: OptimizationFrameworkItem[];
  decision: 'pass' | 'warn' | 'fail';
  next_stage: string;
  manifest_id: string; manifest_path: string;
  strategy_version: string;
  experiment_record: {
    experiment_name?: string; experiment_id?: string;
    run_id?: string; registry_path?: string;
    index_path?: string; strategy_version?: string;
    data_version?: string; decision?: string; next_stage?: string;
  };
  data_quality: DataQualityResponse;
  backtest_summary: Summary;
  gates: PromotionGate[];
  recommendations: string[];
};

export type CryptoClosureCandidate = {
  rank: number;
  strategy_id: string;
  parameters: Record<string, number>;
  score: number;
  validation: Partial<Summary>;
  train?: Partial<Summary>;
  overfit_gap?: number;
  candidate_count?: number;
  candidate_key?: string;
  qualified?: boolean;
  selected?: boolean;
  screening_metrics?: Record<string, number>;
  qualification_blockers?: string[];
  statistical_validation_blockers?: string[];
  audit?: Record<string, unknown>;
};

export type CryptoClosureResponse = {
  status: string;
  selected_priority: string;
  symbol: string;
  source: string;
  interval: string;
  target_intervals: string[];
  data_integrity: {
    status?: string;
    blockers?: string[];
    resample_results?: Array<Record<string, unknown>>;
    quality_results?: Array<Record<string, unknown>>;
  };
  candidate_screen: {
    status?: string;
    candidate_count?: number;
    candidates?: CryptoClosureCandidate[];
    selected_candidate?: CryptoClosureCandidate | null;
    errors?: Array<Record<string, string>>;
    blockers?: string[];
  };
  selected_candidate?: CryptoClosureCandidate | null;
  event_backtest: {
    status?: string;
    mode?: string;
    summary?: Summary;
    diagnostics?: Record<string, unknown>;
  };
  cost_stress: Record<string, unknown>;
  walk_forward: Partial<WalkForwardResponse> & {stability?: Partial<WalkForwardResponse['stability']> & Record<string, unknown>};
  promotion_gate: Partial<PromotionGateResponse>;
  closure_evidence_paths?: string[];
  decision: string;
  next_stage: string;
  blockers: string[];
  recommendations: string[];
};

export type MvpStep = {
  id: string; label: string;
  status: 'pending' | 'active' | 'done' | 'warn' | 'fail';
  detail: string;
};

export type ReportMetric = {
  label: string; display: string;
  tone?: string; description?: string;
};

export type ReportSection = {
  priority: number; title: string;
  subtitle?: string; metrics: ReportMetric[];
};

export type OptimizationHint = {severity: string; message: string};

export type DrawdownPeriod = {
  start_time: number; trough_time: number; end_time: number;
  depth_pct: number; duration_bars: number;
  recovered: boolean; recovery_bars?: number | null;
};

export type PeriodReturn = {period: string; return_pct: number};

export type EventDrivenCostStressResponse = {
  status: string; engine: string;
  strategy_id: string; symbol: string; interval: string;
  scenarios: Array<{
    name: string; commission_rate: number; slippage_bps: number;
    survives: boolean; total_return_pct: number;
    sharpe_ratio: number; max_drawdown_pct: number; fill_count: number;
  }>;
  survival_rate_pct: number; baseline_fill_count: number;
  engine_note: string;
};

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed';

export type TaskResponse = {
  task_id: string;
  kind: string;
  label: string;
  status: TaskStatus;
  stage: string;
  progress: number;
  message: string;
  request: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error?: string | null;
  blockers: string[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
};

export const defaultOptimizationFramework: OptimizationFrameworkItem[] = [
  {priority: 1, title: '参数稳健性 + 样本外验证', status: 'selected', reason: '当前系统已有回测报告，下一步先做参数筛选和样本外检验，防止把单次回测优化成过拟合。'},
  {priority: 2, title: '交易成本压力测试', status: 'next', reason: '放大手续费、滑点和执行误差，确认收益不会被真实交易吞噬。'},
  {priority: 3, title: 'Walk-forward 与市场状态切片', status: 'next', reason: '按时间窗和波动率/流动性状态分别评估，确保在不同市场环境中策略依然稳定。'},
  {priority: 4, title: '多因子和组合优化', status: 'later', reason: '当前为单策略验证阶段，组合优化在策略通过 walk-forward 后执行更安全。'},
  {priority: 5, title: '数据质量与特征版本治理', status: 'later', reason: '为后续机器学习和多数据源接入保留可复现的数据谱系。'},
];
