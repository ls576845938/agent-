import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const read = path => readFileSync(resolve(root, path), 'utf8');
const catalog = JSON.parse(read('frontend/src/workspaces/architecture/catalog.json'));
const dataSource = read('frontend/src/workspaces/architecture/mindmap.ts');
const component = read('frontend/src/workspaces/architecture/ArchitectureMindMap.tsx');
const workspace = read('frontend/src/workspaces/ArchitectureMapWorkspace.tsx');
const css = read('frontend/src/workspaces/architecture/architecture-mindmap.css');
const dataBlock = dataSource.split('// MINDMAP_DATA_START')[1].split('// MINDMAP_DATA_END')[0];
const mindMap = JSON.parse(dataBlock.split('export const architectureMindMap =')[1].split('as const satisfies')[0].trim());

test('mind map is a six-branch architecture overview backed by catalog modules', () => {
  assert.equal(mindMap.schemaVersion, 'architecture_mindmap_v1');
  assert.equal(mindMap.branches.length, 6);
  assert.deepEqual(mindMap.branches.map(branch => branch.id), [
    'market-inputs', 'decision-layers', 'evidence-governance',
    'shared-research', 'execution-domains', 'frontend-services',
  ]);
  assert.equal(mindMap.branches.filter(branch => branch.side === 'left').length, 3);
  assert.equal(mindMap.branches.filter(branch => branch.side === 'right').length, 3);
  const catalogIds = new Set(catalog.modules.map(module => module.id));
  const nodes = mindMap.branches.flatMap(branch => branch.nodes);
  assert.ok(nodes.length >= 30);
  assert.equal(new Set(nodes.map(node => node.id)).size, nodes.length);
  assert.deepEqual(nodes.filter(node => !catalogIds.has(node.moduleId)), []);
  assert.ok(nodes.every(node => ['source_mapped', 'planned'].includes(node.status)));
});

test('seven-layer sequence is explicit and does not claim one completed runtime', () => {
  const branch = mindMap.branches.find(item => item.id === 'decision-layers');
  assert.equal(branch.nodes.length, 7);
  assert.match(branch.detail, /不等于同一 runtime 已全部贯通/);
  assert.deepEqual(branch.nodes.map(node => node.label.split(' · ')[0]), ['1', '2', '3', '4', '5', '6', '7']);
  assert.match(branch.nodes[1].detail, /市场状态 v2 已实现/);
  assert.equal(branch.nodes[1].status, 'source_mapped');
  assert.match(branch.nodes[3].detail, /多条路径并存，尚非统一优化器/);
  assert.match(branch.nodes[6].detail, /权威链/);
});

test('current milestone and market boundaries remain fail-closed in the map copy', () => {
  const nodes = mindMap.branches.flatMap(branch => branch.nodes);
  assert.deepEqual(nodes.filter(node => node.status === 'planned').map(node => node.id), []);
  assert.match(nodes.find(node => node.id === 'qlib-adapter').detail, /factory_lgbm_ast_v1/);
  assert.match(nodes.find(node => node.id === 'candidate-worker').detail, /默认关闭/);
  assert.match(nodes.find(node => node.id === 'btc-authority').detail, /权威链路/);
  assert.match(component, /M2 历史探索没有稳定增量/);
  assert.match(component, /研究结果不会自动获得交易权限/);
  assert.match(component, /连线表示职责归属，不等于同一次运行已跑通调用链/);
  assert.doesNotMatch(component, /fetch\(|axios|method:\s*['"]POST/);
});

test('current development snapshot is pinned to the reviewed main and separates four evidence layers', () => {
  assert.match(dataSource, /asOf: '2026-09-29'/);
  assert.match(dataSource, /reviewedHead: '3fc39879d14ecab2288368afe588385cc44c08e1'/);
  assert.match(dataSource, /历史测试/);
  assert.match(workspace, /合入／页面/);
  assert.match(workspace, /运行限制/);
  assert.match(workspace, /data-testid="current-development-status"/);
  assert.match(dataSource, /不是实时权限、账户或运行监控/);
  assert.match(dataSource, /2960 \/ 8760/);
  assert.match(dataSource, /11 \/ 11/);
  assert.match(dataSource, /factory_lgbm_ast_v1/);
  assert.match(dataSource, /conditioned 1956 \/ 2960/);
});

test('default overview is interactive and retains the existing evidence drill-down', () => {
  assert.match(workspace, /useState\('overview'\)/);
  assert.match(workspace, /总览思维导图/);
  assert.match(workspace, /模块证据/);
  assert.match(workspace, /setSelected\(moduleId\); setView\('map'\)/);
  assert.match(component, /onClick=\{\(\) => onSelectModule\(node\.moduleId\)\}/);
  assert.match(component, /缩小总图/);
  assert.match(component, /放大总图/);
  assert.match(component, /适应画布/);
  assert.match(component, /恢复 100%/);
});

test('canvas is locally scrollable and responsive without widening the page', () => {
  assert.match(css, /\.mindmap-viewport[^}]*overflow:\s*auto/);
  assert.match(css, /\.mindmap-panel[^}]*min-width:\s*0/);
  assert.match(css, /@media \(max-width: 650px\)/);
  assert.match(component, /mindmap-stage/);
  assert.match(component, /transform: `scale\(\$\{zoom\}\)`/);
});
