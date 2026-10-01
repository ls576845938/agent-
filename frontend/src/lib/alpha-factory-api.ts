import {apiGet, apiPost} from './api';

export type FactoryRecord = Record<string, any>;
const prefix = '/api/research/alpha-factory';
export const alphaFactoryApi = {
  overview: () => apiGet<FactoryRecord>(prefix),
  detail: (runId: string) => apiGet<FactoryRecord>(`${prefix}/runs/${encodeURIComponent(runId)}`),
  submit: (request: FactoryRecord) => apiPost<FactoryRecord>('/api/tasks/research/alpha-factory', request),
  resume: (runId: string) => apiPost<FactoryRecord>(`/api/tasks/research/alpha-factory/${encodeURIComponent(runId)}/resume`, {}),
};
