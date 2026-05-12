import {apiGet, apiPost} from './api';
import type {TaskResponse} from './shared-types';

export const taskApi = {
  listTasks: (kind = '', limit = 20) => apiGet<TaskResponse[]>(`/api/tasks${kind || limit ? `?${new URLSearchParams({kind, limit: String(limit)}).toString()}` : ''}`),
  getTask: (taskId: string) => apiGet<TaskResponse>(`/api/tasks/${encodeURIComponent(taskId)}`),
  submitCryptoClosureTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/crypto/closure', payload),
  submitResearchPromotionGateTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/research/promotion-gate', payload),
  submitQlibBuildDatasetTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/integrations/qlib/build-dataset', payload),
  submitQlibWorkflowTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/integrations/qlib/run-workflow', payload),
  submitPortfolioOptimizeWeightsTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/integrations/portfolio/optimize-weights', payload),
};
