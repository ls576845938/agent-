import {apiGet, apiPost} from './api';

// G-series: Live Pilot
export const livePilot = {
  secondReview: (ticketId: string, reviewer: string) =>
    apiPost('/api/live-pilot/second-review', {ticket_id: ticketId, manual_review: 'approve', reviewer}),
  episodeStatus: (episodeId: string) =>
    apiGet(`/api/live-pilot/episode/${episodeId}`),
  riskStatus: (episodeId: string) =>
    apiGet(`/api/live-pilot/risk-status/${episodeId}`),
  exitPlan: (episodeId: string) =>
    apiGet(`/api/live-pilot/exit-plan/${episodeId}`),
};

// R-series: Research
export const research = {
  listExperiments: () => apiGet('/api/research/experiments'),
  getExperiment: (id: string) => apiGet(`/api/research/experiments/${id}`),
  listCandidates: () => apiGet('/api/research/candidates'),
  promoteCandidate: (id: string) => apiPost(`/api/research/candidates/${id}/promote`),
  runFactor: (factorId: string, symbols: string[]) =>
    apiPost('/api/factors/compute', {factor_id: factorId, symbols}),
  getRegime: (symbol?: string) =>
    apiGet(`/api/regime/current?symbol=${symbol || 'SPY'}`),
};
