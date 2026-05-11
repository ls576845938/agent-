import { apiGet, apiPost } from './api';

function query(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  return entries.length ? `?${entries.join('&')}` : '';
}

export const researchApi = {
  listExperiments: (dataRoot = 'data') => apiGet<any[]>(`/api/research/experiments${query({data_root: dataRoot})}`),
  getExperiment: (id: string) => apiGet<any>(`/api/research/experiments/${id}`),
  listCandidates: (dataRoot = 'data') => apiGet<any[]>(`/api/research/candidates${query({data_root: dataRoot})}`),
  getRanking: (expId: string) => apiGet<any[]>(`/api/research/experiments/${expId}/ranking`),
  compareExperiments: (ids: string[], metric?: string) =>
    apiPost<Record<string, any[]>>('/api/research/experiments/compare', { experiment_ids: ids, metric }),
  getLineage: (candId: string, dataRoot = 'data') => apiGet<any>(`/api/research/candidates/${candId}/lineage${query({data_root: dataRoot})}`),
  checkPromotionGate: (candId: string, dataRoot = 'data') => apiPost<any>(`/api/research/candidates/${candId}/promotion-gate`, {data_root: dataRoot}),
  generateCandidates: (config: any) => apiPost<any>('/api/research/experiments/generate', config),
  runExperiment: (expId: string) => apiPost<any>(`/api/research/experiments/${expId}/run`),
  scoreExperiment: (expId: string) => apiPost<any>(`/api/research/experiments/${expId}/score`),
  getReport: (expId: string) => apiGet<any>(`/api/research/experiments/${expId}/report`),
  runAutoCycle: (payload: any) => apiPost<any>('/api/research/auto-cycle', payload),
  materializeEvidence: (candId: string, dataRoot = 'data') =>
    apiPost<any>(`/api/research/candidates/${candId}/evidence/materialize`, {data_root: dataRoot}),
  saveEvidencePack: (candId: string, dataRoot = 'data') =>
    apiPost<any>(`/api/research/candidates/${candId}/evidence-pack`, {data_root: dataRoot}),
  getEvidenceRegistry: (dataRoot = 'data', rebuild = false) =>
    apiGet<any>(`/api/research/evidence-registry${query({data_root: dataRoot, rebuild})}`),
  rebuildEvidenceRegistry: (dataRoot = 'data') =>
    apiPost<any>('/api/research/evidence-registry/rebuild', {data_root: dataRoot}),
  listFactors: () => apiGet<any[]>('/api/research/factors'),
  computeFactor: (payload: any) => apiPost<any>('/api/research/factors/compute', payload),
  evaluateFactor: (payload: any) => apiPost<any>('/api/research/factors/evaluate', payload),
  mineFactors: (payload: any) => apiPost<any>('/api/research/factors/mine', payload),
  mineAndRunFactors: (payload: any) => apiPost<any>('/api/research/factors/mine-and-run', payload),
  listFeatures: () => apiGet<any[]>('/api/research/features'),
  buildFeature: (payload: any) => apiPost<any>('/api/research/features/build', payload),
  validateFeature: (snapshotId: string) => apiPost<any>(`/api/research/features/${snapshotId}/validate`),
  listStrategyManifests: (dataRoot = 'data', status = '') =>
    apiGet<any[]>(`/api/research/strategy-manifests${query({data_root: dataRoot, status})}`),
  runPortfolioSim: (manifestIds: string[], config: any = {}) =>
    apiPost<any>('/api/research/portfolio-sims/run', {manifest_ids: manifestIds, config}),
  listPendingReviews: () => apiGet<any[]>('/api/research/paper-review/pending'),
  createPaperReview: (portfolioSimId: string) =>
    apiPost<any>('/api/research/paper-review/create', {portfolio_sim_id: portfolioSimId}),
  approvePaperReview: (reviewId: string, reviewer: string, reason: string) =>
    apiPost<any>(`/api/research/paper-review/${reviewId}/approve`, {manual: true, reviewer, reason}),
  runRobustness: (candidateId: string, dataRoot = 'data', nSimulations = 500) =>
    apiPost<any>('/api/research/robustness/run', {
      strategy_manifest_id: candidateId,
      data_root: dataRoot,
      n_simulations: nSimulations,
    }),
};
