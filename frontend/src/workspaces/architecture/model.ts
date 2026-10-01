import source from './catalog.json';

export type SourceRef = {path: string; line: number};
export type SourceFile = {
  path: string; blob: string; bytes: number; lines: number | null;
  status: 'fully_read' | 'unread'; reader?: string; batch?: string; read_ranges?: number[][];
};
export type Module = {id: string; label: string; group: string; roots: string[]; purpose: string; caution: string};
export type Edge = {id: string; from: string; to: string; label: string; status: string; sources: SourceRef[]};
export type Finding = {id: string; module: string; title: string; detail: string; kind: string; status: string; sources: SourceRef[]};
export const catalog = source as {
  schema_version: string; source_commit: string; review_status: string; title: string;
  scope_note: string; review_note: string; safety: Record<string, boolean>;
  modules: Module[]; edges: Edge[]; findings: Finding[]; files: SourceFile[];
};
export const groups = ['研究', '决策', '执行边界', '展示', '支撑'];
export const readers: Record<string, string> = {
  root: '主代理', btc_regime_readonly: 'BTC 只读审阅',
  shared_regime_readonly: '共享／美股只读审阅', research_layout_producer: '前端只读审阅',
};
export function moduleOf(path: string) {
  // Most-specific match avoids counting one file in several nodes.
  return catalog.modules.flatMap(module => module.roots
    .filter(prefix => path.startsWith(prefix))
    .map(prefix => ({id: module.id, specificity: prefix.length})))
    .sort((a, b) => b.specificity - a.specificity)[0]?.id ?? 'legacy';
}
export function coverage(files: SourceFile[]) {
  const read = files.filter(file => file.status === 'fully_read');
  return {total: files.length, read: read.length, unread: files.length - read.length,
    lines: files.reduce((sum, file) => sum + (file.lines ?? 0), 0),
    readLines: read.reduce((sum, file) => sum + (file.lines ?? 0), 0)};
}
