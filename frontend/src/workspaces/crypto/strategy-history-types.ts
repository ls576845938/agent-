import type {CanonicalBacktestReport} from './canonical-report-types';

export type BTCStrategyHistoryCatalogEntry = {
  strategy_id: string;
  candidate_id: string;
  source_candidate_id: string;
  variant_id: string;
  display_name: string;
  relationship: string;
  relationship_label: string;
  research_status: 'research_only';
  annual_return_pct?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  report_sha256: string;
  generated_at_utc: string;
  history_runs: BTCStrategyHistoryRun[];
  history_run_count: number;
};

export type BTCStrategyHistoryCatalog = {
  schema_version: string;
  status: string;
  decision: string;
  candidates: BTCStrategyHistoryCatalogEntry[];
  safety: Record<string, boolean>;
};

export type BTCStrategyHistoryRun = {
  run_id: string;
  source_run_id: string;
  candidate_id: string;
  source_candidate_id: string;
  generated_at_utc: string;
  status: string;
  relationship: string;
  label: string;
  report_sha256: string;
};

export type BTCStrategyHistoryDetails = {
  full_metrics: Record<string, unknown>;
  params: Record<string, unknown>;
  annual_attribution: Record<string, unknown>;
  confirmation_holdout: Record<string, unknown>;
  walk_forward: Record<string, unknown>;
  cost_stress: Record<string, unknown>;
  market_regime_attribution: Record<string, unknown>;
  max_drawdown_attribution: Record<string, unknown>;
  return_concentration: Record<string, unknown>;
  failure_review: Record<string, unknown>;
  forward_observation: Record<string, unknown>;
  review_design: Record<string, unknown>;
  warnings: string[];
};

export type BTCStrategyHistoryResponse = {
  schema_version: string;
  status: string;
  decision: string;
  strategy_id: string;
  candidate_id: string;
  source_candidate_id: string;
  relationship: string;
  relationship_label: string;
  research_status: 'research_only';
  history_runs: BTCStrategyHistoryRun[];
  selected_run_id: string;
  canonical: Record<string, unknown>;
  canonical_report: CanonicalBacktestReport;
  details: BTCStrategyHistoryDetails;
  source: {
    report_path: string;
    report_sha256: string;
    report_schema_version: string;
    source_code_commit: string;
    generated_at_utc: string;
    data: Record<string, unknown>;
  };
  blockers: string[];
  safety: Record<string, boolean>;
};

export type BTCStrategyReportTab = 'overview' | 'performance' | 'trades' | 'risk' | 'evidence';
