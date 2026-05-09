import { apiGet, apiPost } from './api';

export const researchApi = {
  listExperiments: () => apiGet<any[]>('/api/research/experiments'),
  getExperiment: (id: string) => apiGet<any>(`/api/research/experiments/${id}`),
  listCandidates: () => apiGet<any[]>('/api/research/candidates'),
  getRanking: (expId: string) => apiGet<any[]>(`/api/research/experiments/${expId}/ranking`),
  compareExperiments: (ids: string[], metric?: string) =>
    apiPost<Record<string, any[]>>('/api/research/experiments/compare', { experiment_ids: ids, metric }),
  getLineage: (candId: string) => apiGet<any>(`/api/research/candidates/${candId}/lineage`),
  checkPromotionGate: (candId: string) => apiPost<any>(`/api/research/candidates/${candId}/promotion-gate`),
  generateCandidates: (config: any) => apiPost<any>('/api/research/experiments/generate', config),
  runExperiment: (expId: string) => apiPost<any>(`/api/research/experiments/${expId}/run`),
  scoreExperiment: (expId: string) => apiPost<any>(`/api/research/experiments/${expId}/score`),
  getReport: (expId: string) => apiGet<any>(`/api/research/experiments/${expId}/report`),
};
