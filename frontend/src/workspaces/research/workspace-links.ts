export type WorkspaceSurface = 'research' | 'portfolio' | 'review';
export type WorkspaceContext = {
  dataRoot: string; qlibRoot: string; portfolioRoot: string;
  candidate: string; experiment: string; qlibRun: string; portfolioRun: string;
  simulation: string; manifests: string[]; dataVersion: string; featureVersion: string;
};
const keys = ['dataRoot','qlibRoot','portfolioRoot','candidate','experiment','qlibRun','portfolioRun','simulation','dataVersion','featureVersion'] as const;
export const emptyContext: WorkspaceContext = {dataRoot:'data',qlibRoot:'artifacts/qlib_runs',portfolioRoot:'artifacts/portfolio_runs',candidate:'',experiment:'',qlibRun:'',portfolioRun:'',simulation:'',manifests:[],dataVersion:'',featureVersion:''};
export function validWorkspaceRoot(value: string): boolean {
  return !/^[\\/]/.test(value) && !/[\u0000-\u001f<>:"|?*]/.test(value)
    && !value.split(/[\\/]/).some(part => part === '.' || part === '..');
}
export function parseWorkspaceContext(search: string): {context: WorkspaceContext; errors: string[]} {
  const query = new URLSearchParams(search);
  const context = {...emptyContext, manifests: [] as string[]};
  const errors: string[] = [];
  for (const key of keys) {
    const values = query.getAll(key);
    if (values.length > 1) errors.push('重复的来源字段：' + key);
    if (!values.length) continue;
    const value = values[0].trim();
    const path = key.endsWith('Root');
    if (value.length > (path ? 512 : 160) || /[\u0000-\u001f]/.test(value) || (path && !validWorkspaceRoot(value)) || (!path && value && (!/^[\w.:-]+$/.test(value) || ['.','..','latest'].includes(value)))) {
      errors.push('无效的来源字段：' + key); continue;
    }
    context[key] = value || emptyContext[key];
  }
  for (const id of query.getAll('manifest')) {
    if (!/^[\w.:-]{1,160}$/.test(id) || context.manifests.length >= 50) errors.push('无效的策略证据引用');
    else if (!context.manifests.includes(id)) context.manifests.push(id);
  }
  return {context, errors};
}
export function workspaceLink(surface: WorkspaceSurface, context: WorkspaceContext, view?: string): string {
  const query = new URLSearchParams();
  for (const key of keys) if (context[key]) query.set(key, context[key]);
  context.manifests.forEach(id => query.append('manifest', id));
  if (surface === 'review') query.set('view','research-review');
  else if (view) query.set('view',view);
  return (surface === 'review' ? '/live' : '/' + surface) + '?' + query.toString();
}
export function referenceErrors(context: WorkspaceContext, rows: {candidates: any[]; experiments: any[]; manifests: any[]; qlib: any[]; portfolios: any[]}): string[] {
  const errors: string[] = [];
  const candidate = rows.candidates.find(row => row.candidate_id === context.candidate);
  if (context.candidate && !candidate) errors.push('候选引用未在当前数据目录找到：' + context.candidate);
  if (context.experiment && !rows.experiments.some(row => row.experiment_id === context.experiment)) errors.push('来源实验不存在：' + context.experiment);
  if (candidate && context.experiment && candidate.experiment_id !== context.experiment) errors.push('候选与来源实验不匹配');
  context.manifests.forEach(id => {
    const manifest = rows.manifests.find(row => row.strategy_candidate_id === id);
    if (!manifest) errors.push('策略证据未找到：' + id);
    else if (context.candidate && manifest.source_candidate_id !== context.candidate) errors.push('候选与策略证据关联缺失或不匹配');
  });
  if (context.qlibRun && !rows.qlib.some(row => row.run_id === context.qlibRun)) errors.push('Qlib 运行未找到：' + context.qlibRun);
  const portfolio = rows.portfolios.find(row => row.portfolio_run_id === context.portfolioRun);
  if (context.portfolioRun && !portfolio) errors.push('组合版本未找到：' + context.portfolioRun);
  if (portfolio && context.qlibRun && portfolio.source_score_run_id !== context.qlibRun) errors.push('组合版本与评分来源不匹配');
  return errors;
}
