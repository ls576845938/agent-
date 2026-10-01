import {apiGet, apiPost} from './api';
import {acquireResearchRead, type ResearchReadLease} from './research-read-request';

export type FactoryRecord = Record<string, any>;
const prefix = '/api/research/alpha-factory';
export const alphaFactoryReadDeadlineMs = 20_000;
const readDeadlineMs = alphaFactoryReadDeadlineMs;
const overview = (signal?: AbortSignal) => apiGet<FactoryRecord>(prefix, {timeoutMs: readDeadlineMs, signal});
const detail = (runId: string, signal?: AbortSignal) => apiGet<FactoryRecord>(
  `${prefix}/runs/${encodeURIComponent(runId)}`,
  {timeoutMs: readDeadlineMs, signal},
);

export function acquireAlphaFactoryOverview(): ResearchReadLease<FactoryRecord> {
  return acquireResearchRead(
    'alpha-factory|overview',
    signal => overview(signal),
    {deadlineMs: readDeadlineMs},
  );
}

export function acquireAlphaFactoryDetail(
  runId: string,
  deadlineMs = readDeadlineMs,
): ResearchReadLease<FactoryRecord> {
  const boundedDeadlineMs = Math.min(readDeadlineMs, Math.max(1, deadlineMs));
  return acquireResearchRead(
    `alpha-factory|detail|${runId}`,
    signal => apiGet<FactoryRecord>(
      `${prefix}/runs/${encodeURIComponent(runId)}`,
      {timeoutMs: boundedDeadlineMs, signal},
    ),
    {deadlineMs: boundedDeadlineMs},
  );
}

export const alphaFactoryApi = {
  overview,
  detail,
  submit: (request: FactoryRecord) => apiPost<FactoryRecord>('/api/tasks/research/alpha-factory', request),
  resume: (runId: string) => apiPost<FactoryRecord>(`/api/tasks/research/alpha-factory/${encodeURIComponent(runId)}/resume`, {}),
};
