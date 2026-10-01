import type {ChartSeriesPayload, RunStatusResponse, Summary} from '../../lib/view-model';
import type {BacktestSnapshot} from './demo-types';

export const USER_BACKTEST_CATALOG_KEY = 'quantstation.user-backtest-strategy-catalog.v1';
export const USER_BACKTEST_CATALOG_EVENT = 'quantstation:user-backtest-catalog-changed';
const SCHEMA_VERSION = 'user_backtest_strategy_catalog_v1';
export const BTC_TRADING_WORKBENCH_HISTORY_KEY = 'quantstation.btc.trading-workbench.v2';
export const BTC_HISTORY_KEYS = [
  'quantstation.btc.backtest.latest.v2',
  BTC_TRADING_WORKBENCH_HISTORY_KEY,
  'quantstation.btc.backtest.latest.v1',
  'quantstation.btc.backtest-workbench.v1',
] as const;

export type NormalizedLocalBacktestSnapshot = BacktestSnapshot & {sourceStorageKey: string};
export type LocalBacktestHistoryWriteResult =
  | {status: 'persisted'}
  | {status: 'quota'; error: unknown}
  | {status: 'error'; error: unknown};

export type UserBacktestCatalogRecord = {
  catalog_key: string;
  run_id: string;
  strategy_id: string;
  candidate_id: string;
  display_name: string;
  domain: string;
  metrics: Summary;
  report_href: string;
  created_at: string;
  source_snapshot: string;
};

type Payload = {
  schema_version: typeof SCHEMA_VERSION;
  records: UserBacktestCatalogRecord[];
};

export function readUserBacktestCatalog(): UserBacktestCatalogRecord[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(USER_BACKTEST_CATALOG_KEY) ?? 'null') as Partial<Payload> | null;
    if (parsed?.schema_version !== SCHEMA_VERSION || !Array.isArray(parsed.records)) return [];
    return parsed.records.filter(validRecord);
  } catch {
    return [];
  }
}

export function upsertUserBacktestRecord(record: UserBacktestCatalogRecord): void {
  if (!validRecord(record)) throw new Error('completed backtest identity/metrics/report required');
  const current = readUserBacktestCatalog();
  const records = [record, ...current.filter((item) => item.catalog_key !== record.catalog_key)];
  write({schema_version: SCHEMA_VERSION, records});
}

export function removeUserBacktestRecord(catalogKey: string): void {
  write({schema_version: SCHEMA_VERSION, records: readUserBacktestCatalog().filter((item) => item.catalog_key !== catalogKey)});
}

export function renameUserBacktestRecord(catalogKey: string, displayName: string): void {
  const name = displayName.trim();
  if (!name) return;
  write({
    schema_version: SCHEMA_VERSION,
    records: readUserBacktestCatalog().map((item) => item.catalog_key === catalogKey ? {...item, display_name: name} : item),
  });
}

export function discoverImportableLocalRuns(): UserBacktestCatalogRecord[] {
  const records = new Map<string, UserBacktestCatalogRecord>();
  for (const snapshot of readLocalBacktestSnapshots()) {
    const record = createUserBacktestRecord({
      runId: snapshot.run.run_id,
      strategyId: snapshot.strategyId,
      candidateId: snapshot.candidateId,
      displayName: `${snapshot.strategyId} · ${snapshot.candidateId} · ${snapshot.run.run_id}`,
      metrics: snapshot.run.summary as Summary,
      createdAt: snapshot.savedAt,
      sourceSnapshot: snapshot.sourceStorageKey,
    });
    records.set(record.catalog_key, record);
  }
  return [...records.values()];
}

export function readLocalBacktestSnapshots(): NormalizedLocalBacktestSnapshot[] {
  const snapshots = new Map<string, NormalizedLocalBacktestSnapshot>();
  for (const storageKey of BTC_HISTORY_KEYS) {
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(localStorage.getItem(storageKey) ?? 'null');
    } catch {
      parsed = null;
    }
    for (const candidate of snapshotList(parsed)) {
      const snapshot = normalizeLocalSnapshot(candidate, storageKey);
      // Keys are ordered newest schema first. Never let a v1 duplicate replace v2.
      if (snapshot && !snapshots.has(snapshot.run.run_id)) snapshots.set(snapshot.run.run_id, snapshot);
    }
  }
  return [...snapshots.values()];
}

/**
 * Keep the completed report and chart in React memory, but persist only the
 * scalar identity/summary needed to restore a research-only run after a
 * refresh.  Large report/chart payloads must never be copied into browser
 * storage, and a quota failure must not take down the workbench.
 */
export function writeLocalBacktestSnapshots(snapshots: BacktestSnapshot[]): LocalBacktestHistoryWriteResult {
  const persisted = snapshots.map((snapshot) => ({
    run: {
      run_id: snapshot.run.run_id,
      status: snapshot.run.status,
      created_at: snapshot.run.created_at,
      completed_at: snapshot.run.completed_at,
      summary: compactSummary(snapshot.run.summary ?? null),
    },
    strategyId: snapshot.strategyId,
    candidateId: snapshot.candidateId,
    strategyVersion: snapshot.strategyVersion,
    paramsHash: snapshot.paramsHash,
    savedAt: snapshot.savedAt,
    ...(snapshot.versionId ? {versionId: snapshot.versionId} : {}),
    ...(snapshot.request ? {request: snapshot.request} : {}),
  }));
  try {
    localStorage.setItem(BTC_TRADING_WORKBENCH_HISTORY_KEY, JSON.stringify(persisted));
    return {status: 'persisted'};
  } catch (error) {
    return isQuotaStorageError(error)
      ? {status: 'quota', error}
      : {status: 'error', error};
  }
}

export function createUserBacktestRecord({
  runId,
  strategyId,
  candidateId,
  displayName,
  metrics,
  createdAt,
  sourceSnapshot,
}: {
  runId: string;
  strategyId: string;
  candidateId: string;
  displayName: string;
  metrics: Summary;
  createdAt: string;
  sourceSnapshot: string;
}): UserBacktestCatalogRecord {
  const params = new URLSearchParams({
    strategy_id: strategyId,
    candidate_id: candidateId,
    panel: 'backtest',
    report_tab: 'overview',
    local_run_id: runId,
  });
  return {
    catalog_key: `user:btc:${strategyId}:${candidateId}:${runId}`,
    run_id: runId,
    strategy_id: strategyId,
    candidate_id: candidateId,
    display_name: displayName.trim() || `${strategyId} · ${runId}`,
    domain: 'btc',
    metrics,
    report_href: `/crypto?${params.toString()}`,
    created_at: createdAt,
    source_snapshot: sourceSnapshot,
  };
}

function write(payload: Payload): void {
  localStorage.setItem(USER_BACKTEST_CATALOG_KEY, JSON.stringify(payload));
  window.dispatchEvent(new CustomEvent(USER_BACKTEST_CATALOG_EVENT));
}

function validRecord(value: unknown): value is UserBacktestCatalogRecord {
  const record = objectValue(value);
  return Boolean(
    text(record.catalog_key)
    && text(record.run_id)
    && text(record.strategy_id)
    && text(record.candidate_id)
    && text(record.display_name)
    && text(record.report_href).startsWith('/crypto?')
    && summaryValue(record.metrics),
  );
}

function summaryValue(value: unknown): Summary | null {
  const record = objectValue(value);
  const keys: Array<keyof Summary> = [
    'total_return_pct', 'annual_return_pct', 'annual_volatility_pct', 'sharpe_ratio', 'sortino_ratio',
    'max_drawdown_pct', 'calmar_ratio', 'win_rate_pct', 'profit_factor', 'trade_count',
  ];
  if (!keys.every((key) => typeof record[key] === 'number' && Number.isFinite(record[key]))) return null;
  return Object.fromEntries(keys.map((key) => [key, record[key]])) as Summary;
}

function compactSummary(value: Summary | null): Summary | null {
  if (!value) return null;
  const keys: Array<keyof Summary> = [
    'total_return_pct', 'annual_return_pct', 'annual_volatility_pct', 'sharpe_ratio', 'sortino_ratio',
    'max_drawdown_pct', 'calmar_ratio', 'win_rate_pct', 'profit_factor', 'trade_count',
  ];
  return Object.fromEntries(keys.map((key) => [key, value[key]])) as Summary;
}

function isQuotaStorageError(error: unknown): boolean {
  const record = objectValue(error);
  const name = text(record.name);
  const code = Number(record.code);
  return name === 'QuotaExceededError'
    || name === 'NS_ERROR_DOM_QUOTA_REACHED'
    || code === 22
    || code === 1014;
}

function snapshotList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const record = objectValue(value);
  if (Array.isArray(record.snapshots)) return record.snapshots;
  if (objectValue(record.snapshot).run) return [record.snapshot];
  if (objectValue(record.latest).run) return [record.latest];
  return record.run ? [record] : [];
}

function normalizeLocalSnapshot(value: unknown, sourceStorageKey: string): NormalizedLocalBacktestSnapshot | null {
  const snapshot = objectValue(value);
  const rawRun = objectValue(snapshot.run);
  const diagnostics = objectValue(rawRun.diagnostics);
  const diagnosticIdentity = objectValue(diagnostics.btc_strategy_identity);
  const topStrategyId = text(snapshot.strategyId) || text(snapshot.strategy_id);
  const diagnosticStrategyId = text(diagnosticIdentity.strategy_id);
  const topCandidateId = text(snapshot.candidateId) || text(snapshot.candidate_id);
  const diagnosticCandidateId = text(diagnosticIdentity.candidate_id);
  const topParamsHash = text(snapshot.paramsHash) || text(snapshot.params_hash);
  const diagnosticParamsHash = text(diagnosticIdentity.params_hash);
  const topStrategyVersion = text(snapshot.strategyVersion) || text(snapshot.strategy_version);
  const diagnosticStrategyVersion = text(diagnosticIdentity.strategy_version);
  if (
    (topStrategyId && diagnosticStrategyId && topStrategyId !== diagnosticStrategyId)
    || (topCandidateId && diagnosticCandidateId && topCandidateId !== diagnosticCandidateId)
    || (topParamsHash && diagnosticParamsHash && topParamsHash !== diagnosticParamsHash)
    || (topStrategyVersion && diagnosticStrategyVersion && topStrategyVersion !== diagnosticStrategyVersion)
  ) return null;
  const strategyId = topStrategyId || diagnosticStrategyId;
  const candidateId = topCandidateId || diagnosticCandidateId;
  const runId = text(rawRun.run_id);
  const summary = summaryValue(rawRun.summary);
  if (rawRun.status !== 'completed' || !runId || !strategyId || !candidateId || !summary) return null;
  const paramsHash = topParamsHash || diagnosticParamsHash;
  const strategyVersion = topStrategyVersion || diagnosticStrategyVersion;
  const versionId = text(snapshot.versionId);
  const requestRecord = objectValue(snapshot.request);
  const requestCapital = Number(requestRecord.capital);
  const request = text(requestRecord.start)
    && text(requestRecord.end)
    && Number.isFinite(requestCapital)
    ? {
      start: text(requestRecord.start),
      end: text(requestRecord.end),
      capital: requestCapital,
      dataVersion: text(requestRecord.dataVersion),
    }
    : undefined;
  const normalizedIdentity = {
    ...diagnosticIdentity,
    strategy_id: strategyId,
    candidate_id: candidateId,
    ...(paramsHash ? {params_hash: paramsHash} : {}),
    ...(strategyVersion ? {strategy_version: strategyVersion} : {}),
  };
  const run: RunStatusResponse = {
    run_id: runId,
    mode: text(rawRun.mode) || 'backtest',
    status: 'completed',
    created_at: text(rawRun.created_at) || text(snapshot.savedAt) || text(snapshot.saved_at),
    completed_at: text(rawRun.completed_at) || null,
    error: typeof rawRun.error === 'string' ? rawRun.error : null,
    summary,
    latest_weights: Array.isArray(rawRun.latest_weights) ? rawRun.latest_weights as Array<Record<string, unknown>> : [],
    strategy_details: Array.isArray(rawRun.strategy_details) ? rawRun.strategy_details as Array<Record<string, unknown>> : [],
    diagnostics: {...diagnostics, btc_strategy_identity: normalizedIdentity},
  };
  return {
    run,
    chart: chartValue(snapshot.chart),
    strategyId,
    candidateId,
    strategyVersion,
    paramsHash,
    savedAt: text(snapshot.savedAt) || text(snapshot.saved_at) || run.completed_at || run.created_at,
    sourceStorageKey,
    ...(versionId ? {versionId} : {}),
    ...(request ? {request} : {}),
  };
}

function chartValue(value: unknown): ChartSeriesPayload | null {
  const chart = objectValue(value);
  const keys: Array<keyof ChartSeriesPayload> = [
    'candles', 'markers', 'equity', 'drawdown', 'exposure', 'net_units', 'turnover', 'leverage',
  ];
  if (!keys.some((key) => Array.isArray(chart[key]))) return null;
  return Object.fromEntries(keys.map((key) => [key, Array.isArray(chart[key]) ? chart[key] : []])) as ChartSeriesPayload;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
