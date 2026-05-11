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

export const defaultOptimizationFramework: OptimizationFrameworkItem[] = [
  {priority: 1, title: '参数稳健性 + 样本外验证', status: 'selected', reason: '当前系统已有回测报告，下一步先做参数筛选和样本外检验，防止把单次回测优化成过拟合。'},
  {priority: 2, title: '交易成本压力测试', status: 'next', reason: '放大手续费、滑点和执行误差，确认收益不会被真实交易吞噬。'},
  {priority: 3, title: 'Walk-forward 与市场状态切片', status: 'next', reason: '按时间窗和波动率/流动性状态分别评估，确保在不同市场环境中策略依然稳定。'},
  {priority: 4, title: '多因子和组合优化', status: 'later', reason: '当前为单策略验证阶段，组合优化在策略通过 walk-forward 后执行更安全。'},
  {priority: 5, title: '数据质量与特征版本治理', status: 'later', reason: '为后续机器学习和多数据源接入保留可复现的数据谱系。'},
];
