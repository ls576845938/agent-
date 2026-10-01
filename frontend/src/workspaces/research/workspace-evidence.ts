import type {WorkspaceContext} from './workspace-links';
type Row = Record<string, any>;
export function reviewSourceEligible(entry: Row | null, kind: 'candidate' | 'manifest', id: string): boolean {
 const ids = entry?.[kind === 'candidate' ? 'eligible_candidate_ids' : 'eligible_manifest_ids'];
 return entry?.creation_allowed === true && !!id && Array.isArray(ids) && ids.every(value => typeof value === 'string') && ids.includes(id);
}
export function firstTargetImportAllowed(rows: Row[], detail: Row | null, runId: string): boolean {
 const row = rows.find(value => value.portfolio_run_id === runId);
 return row?.has_target_positions === false && Number(row?.target_weight_rows) > 0
   && Array.isArray(detail?.target_positions_preview) && detail.target_positions_preview.length === 0
   && !!detail?.target_positions_json && typeof detail.target_positions_json === 'object' && Object.keys(detail.target_positions_json).length === 0;
}
export function completeLegacySnapshot(value: Row): boolean {
 const weights = (row: unknown) => !!row && typeof row === 'object' && !Array.isArray(row) && Object.values(row).every(n => typeof n === 'number' && Number.isFinite(n));
 return typeof value.portfolio_id === 'string' && !!value.portfolio_id && typeof value.date === 'string' && !!value.date
   && ['total_capital','expected_return','expected_volatility'].every(key => typeof value[key] === 'number' && Number.isFinite(value[key]))
   && weights(value.strategy_weights) && weights(value.symbol_exposures);
}
const pathText = (value: unknown) => String(value || '').replaceAll('\\','/').replace(/\/+$/,'').toLowerCase();
const m1Archive = {
  datasetId: 'm1-trend-environment-acceptance',
  datasetVersion: 'm1-okx-59f5eb861-20260911',
  manifestGitSpec: '165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json',
};
function exactM1QlibArchive(id: string, detail: Row): boolean {
  const provenance = detail.summary?.evidence_provenance;
  const logicalRun = `qlib_runs/${id}`;
  const logicalRoot = `shared-data://${m1Archive.datasetId}/${m1Archive.datasetVersion}/${logicalRun}`;
  return provenance?.storage === 'immutable_shared_data'
    && provenance.dataset_id === m1Archive.datasetId
    && provenance.dataset_version === m1Archive.datasetVersion
    && provenance.manifest_git_spec === m1Archive.manifestGitSpec
    && provenance.logical_run === logicalRun
    && provenance.consumer_read_only === true
    && provenance.historical_reconstructed_availability === true
    && detail.summary?.paths?.run_root === logicalRoot;
}
export function runEvidenceErrors(id: string, root: string, detail: Row | null, kind: 'qlib' | 'portfolio', scoreId = '', options: {allowReadonlyM1Archive?: boolean} = {}): string[] {
  if (!id) return [];
  if (!detail) return [kind + ' 详情尚未核验，相关操作禁止'];
  const errors: string[] = [];
  const key = kind === 'qlib' ? 'run_id' : 'portfolio_run_id';
  if (detail.summary?.[key] !== id) errors.push(kind + ' 详情运行编号不匹配');
  const localRootMatches = pathText(detail.summary?.paths?.run_root) === pathText(root + '/' + id);
  const archiveMatches = kind === 'qlib' && options.allowReadonlyM1Archive === true && exactM1QlibArchive(id, detail);
  if (!localRootMatches && !archiveMatches) errors.push(kind + ' 详情目录未匹配当前来源');
  if (kind === 'portfolio') {
    if (detail.run_manifest?.portfolio_run_id !== id) errors.push('组合原件运行编号缺失或不匹配');
    if (!scoreId || detail.run_manifest?.source_score_run_id !== scoreId || detail.summary?.source_score_run_id !== scoreId) errors.push('组合原件评分来源缺失或不匹配');
  }
  return errors;
}

type Settled<T> = PromiseSettledResult<T>;
type SharedReadEntry = {
  references: number;
  cancelled: boolean;
  selected: Promise<Settled<any> | null>;
  qlib: Promise<Settled<any>>;
  factory: Promise<Settled<any>>;
};
const researchReadEntries = new Map<string, SharedReadEntry>();
let researchReadTail: Promise<void> = Promise.resolve();
const settle = async <T>(load: () => Promise<T>): Promise<Settled<T>> => {
  try { return {status: 'fulfilled', value: await load()}; }
  catch (reason) { return {status: 'rejected', reason}; }
};
const cancelledRead = (): PromiseRejectedResult => ({status: 'rejected', reason: new Error('research_read_cancelled')});

export function acquireResearchRunPageReads<TSelected, TQlib, TFactory>(
  key: string,
  loadSelected: (() => Promise<TSelected>) | null,
  loadQlib: () => Promise<TQlib>,
  loadFactory: () => Promise<TFactory>,
) {
  const existing = researchReadEntries.get(key);
  if (existing && !existing.cancelled) {
    existing.references += 1;
    return {...existing, release: () => releaseResearchRead(key, existing)};
  }
  const entry = {references: 1, cancelled: false} as SharedReadEntry;
  entry.selected = researchReadTail.then(() => entry.cancelled ? cancelledRead() : loadSelected ? settle(loadSelected) : null);
  entry.qlib = entry.selected.then(() => entry.cancelled ? cancelledRead() : settle(loadQlib));
  entry.factory = entry.qlib.then(() => entry.cancelled ? cancelledRead() : settle(loadFactory));
  researchReadTail = entry.factory.then(() => undefined, () => undefined);
  researchReadEntries.set(key, entry);
  void entry.factory.finally(() => {
    if (researchReadEntries.get(key) === entry) researchReadEntries.delete(key);
  });
  return {...entry, release: () => releaseResearchRead(key, entry)};
}

function releaseResearchRead(key: string, entry: SharedReadEntry): void {
  entry.references = Math.max(0, entry.references - 1);
  queueMicrotask(() => {
    if (entry.references === 0 && researchReadEntries.get(key) === entry) entry.cancelled = true;
  });
}
export function versionEvidenceErrors(context: WorkspaceContext, evidence: Row[]): string[] {
  const errors: string[] = [];
  for (const [queryKey, field] of [['dataVersion','data_version'],['featureVersion','feature_version']] as const) {
    if (!context[queryKey]) continue;
    const values = evidence.map(row => row?.[field]).filter(value => value != null && value !== '');
    if (!values.length) errors.push(field + ' 缺少原件证明；URL 只提供待核验引用');
    else if (values.some(value => String(value) !== context[queryKey])) errors.push(field + ' 与来源原件不匹配');
  }
  return errors;
}
export function simulationEvidenceErrors(context: WorkspaceContext, detail: Row | null): string[] {
  if (!context.simulation) return [];
  if (context.dataRoot !== 'data') return ['现有模拟读取接口只支持默认 data 目录'];
  if (detail?.portfolio_sim_id !== context.simulation) return ['组合模拟编号缺失或不匹配'];
  // Existing report does not expose the original manifest IDs. Do not infer a binding from strategy names.
  if (context.manifests.length) return ['现有模拟报告未提供策略证据编号绑定；只能查看，不可据此创建复核'];
  return [];
}
const baseConfig: Row = {fallback_optimizer:'equal_weight_topk',expected_return_method:'rank_zscore',covariance_method:'sample',top_k:5,lookback_days:252,min_observations:60,annualization:252,rebalance_freq:'daily',long_only:true,max_weight:0.15,cash_buffer:0.02,max_turnover:0.30,risk_free_rate:0,min_expected_return:0.02,max_expected_return:0.20,strategy_id:'pypfopt_daily_only',vendor:'yfinance',asset_class:'equity',bar_size:'1d'};
export const portfolioConfigContracts: Record<string, Row> = {
 'configs/portfolio/pypfopt_long_only_max_sharpe.yaml':{...baseConfig,optimizer:'max_sharpe'},
 'configs/portfolio/pypfopt_long_only_min_volatility.yaml':{...baseConfig,optimizer:'min_volatility'},
 'configs/portfolio/pypfopt_hrp.yaml':{...baseConfig,optimizer:'hrp'},
};
export function portfolioConfigMatches(detail: Row | null, configPath: string, strategyId: string, fallback: string): boolean {
 const expected = portfolioConfigContracts[configPath], actual = detail?.run_manifest?.config;
 if (!expected || !actual || actual.strategy_id !== strategyId || actual.fallback_optimizer !== fallback || actual.current_weights_path) return false;
 return Object.entries(expected).every(([key,value]) => actual[key] === value);
}
