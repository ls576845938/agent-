export type CanonicalReportPoint = {
  time: number;
  value: number;
};

export type CanonicalMonthlyReturn = CanonicalReportPoint & {
  month: string;
};

export type CanonicalTrade = {
  trade_number: number;
  direction: 'long' | 'short';
  entry_time: number;
  exit_time: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  gross_pnl: number;
  commission: number;
  funding_cashflow?: number;
  net_pnl: number;
  cumulative_pnl: number;
  return_pct: number;
  duration_bars: number;
};

export type CanonicalCost = {
  key: string;
  label: string;
  value: number;
};

export type CanonicalBacktestReport = {
  schema_version: string;
  status: string;
  decision: string;
  run_id: string;
  source_run_id: string;
  artifact_binding: {
    pointer_path?: string;
    manifest_path?: string;
    evidence_pack_path?: string;
    ledger_artifact_path?: string;
    pointer_code_commit?: string;
    manifest_sha256_verified: boolean;
    evidence_pack_sha256_verified: boolean;
    ledger_artifact_sha256_verified: boolean;
    fills_hash_verified: boolean;
    ledger_equity_consistent: boolean;
  };
  series: {
    equity: CanonicalReportPoint[];
    drawdown: CanonicalReportPoint[];
    monthly_returns: CanonicalMonthlyReturn[];
    trades: CanonicalTrade[];
    costs: CanonicalCost[];
  };
  derived_metrics: {
    trade_count?: number;
    winning_trade_count?: number;
    losing_trade_count?: number;
    win_rate_pct?: number;
    profit_factor?: number;
    average_trade_pnl?: number;
    largest_winner?: number;
    largest_loser?: number;
    average_duration_bars?: number;
  };
  source_counts: Record<string, number>;
  safety: Record<string, boolean>;
  blockers: string[];
};

export type DrawingTool = 'cursor' | 'trend' | 'pencil' | 'measure' | 'target' | 'text';

export type DrawingPoint = {
  time: number;
  price: number;
};

export type ChartDrawing = {
  id: string;
  tool: Exclude<DrawingTool, 'cursor'>;
  points: DrawingPoint[];
  text?: string;
};
