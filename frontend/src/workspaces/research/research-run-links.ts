// A run link is a reference, never a request to execute or resolve "latest".
export const DONCHIAN_OFFLINE_RUN = 'donchian-v3-closeout-20260920';
export const DONCHIAN_STAGE_RUN = 'donchian-stage-20260921';

export function researchRunLink(kind: 'qlib' | 'factory' | 'offline', runId: string, search = ''): string {
  const query = new URLSearchParams(search);
  query.delete('layout');
  query.set('view', 'run-details');
  query.delete('qlibRun');
  query.delete('factoryRun');
  query.delete('offlineRun');
  query.set(kind === 'qlib' ? 'qlibRun' : kind === 'factory' ? 'factoryRun' : 'offlineRun', runId);
  return '/research?' + query.toString();
}

export function researchWorkspaceLink(view: string, search = ''): string {
  const query = new URLSearchParams(search);
  query.delete('layout');
  query.set('view', view);
  return '/research?' + query.toString();
}
