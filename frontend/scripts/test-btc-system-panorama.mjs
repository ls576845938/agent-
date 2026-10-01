import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {
  BTC_PANORAMA_DRAFT_SCHEMA,
  parseBtcPanoramaDraft,
} from '../src/workspaces/architecture/btcPanoramaDraft.ts';
import {
  applyBtcPanoramaBaselineGeometry,
  arrangeBtcPanorama,
  inspectBtcPanoramaRoutes,
  routeBtcPanoramaEdges,
} from '../src/workspaces/architecture/btcPanoramaLayout.ts';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const read = path => readFileSync(resolve(root, path), 'utf8');
const dataSource = read('frontend/src/workspaces/architecture/btcPanoramaData.ts');
const component = read('frontend/src/workspaces/architecture/BtcSystemPanorama.tsx');
const workspace = read('frontend/src/workspaces/ArchitectureMapWorkspace.tsx');
const styles = read('frontend/src/workspaces/architecture/btc-system-panorama.css');
const validator = read('frontend/src/workspaces/architecture/btcPanoramaDraft.ts');
const browserSpec = read('frontend/e2e/btc-system-panorama.spec.ts');

const dataBlock = dataSource
  .split('// BTC_PANORAMA_DATA_START')[1]
  .split('// BTC_PANORAMA_DATA_END')[0];
const panorama = JSON.parse(
  dataBlock
    .split('export const btcSystemPanorama: BtcSystemPanorama =')[1]
    .trim()
    .replace(/;$/, ''),
);

test('BTC panorama keeps the complete A-I architecture snapshot', () => {
  assert.equal(panorama.schemaVersion, 'btc_system_panorama_v1');
  assert.equal(panorama.asOf, '2026-09-29');
  assert.equal(panorama.sourceHead, '5542a542459f2b56eaf11035fca409422142471d');
  assert.deepEqual(panorama.groups.map(group => group.id), [
    'data', 'research', 'market', 'delivery', 'decision',
    'authority', 'environment', 'ledger', 'evidence',
  ]);
  assert.equal(panorama.groups.length, 9);
  assert.equal(panorama.groups.flatMap(group => group.nodes).length, 37);
  assert.equal(new Set(panorama.groups.flatMap(group => group.nodes).map(node => node.id)).size, 37);
  assert.equal(panorama.edges.length, 49);
});

test('critical boundaries and execution chain remain explicit', () => {
  const text = JSON.stringify(panorama);
  for (const marker of [
    'research_readonly', 'factory_lgbm_ast_v1', '离线任务未配置、未启用',
    '研究完成不等于交易有效', '保护成交不是新策略信号',
    '页面读取不训练、不恢复、不重新核账',
  ]) assert.match(text, new RegExp(marker));
  const edge = (from, to) => panorama.edges.find(item => item.from === from && item.to === to);
  assert.equal(edge('target', 'risk')?.style, 'solid');
  assert.equal(edge('dispatcher', 'demo')?.style, 'dashed');
  assert.equal(edge('market-entry-policy', 'donchian-policy')?.style, 'dashed');
  assert.equal(edge('ledger-uow', 'account-facts')?.label, '核账后的事实供下一次决策使用');
});

test('layered layout keeps all edges orthogonal and clear of non-endpoint nodes and group titles', async () => {
  const nodes = panorama.groups.flatMap(group => [
    {id: `group-${group.id}`, position: {x: group.x, y: group.y}, style: {width: group.width, height: group.height}, data: {kind: 'group'}},
    ...group.nodes.map(node => ({
      id: node.id,
      parentId: `group-${group.id}`,
      position: {x: node.x - group.x, y: node.y - group.y},
      style: {width: node.width, height: node.height},
      data: {kind: 'node'},
    })),
  ]);
  const edges = panorama.edges.map(edge => ({id: edge.id, source: edge.from, target: edge.to, label: edge.label ?? ''}));
  const arranged = await arrangeBtcPanorama(nodes, edges);
  const baseline = applyBtcPanoramaBaselineGeometry(nodes);
  const baselineRoutes = routeBtcPanoramaEdges(baseline, edges);
  assert.deepEqual(baseline, arranged.nodes);
  assert.deepEqual([...baselineRoutes], [...arranged.routes]);
  assert.equal(arranged.routes.size, 49);
  assert.deepEqual(inspectBtcPanoramaRoutes(arranged.nodes, edges, arranged.routes), []);
  for (const route of arranged.routes.values()) {
    assert.ok(route.points.length >= 2);
    for (let index = 1; index < route.points.length; index += 1) {
      assert.ok(route.points[index - 1].x === route.points[index].x
        || route.points[index - 1].y === route.points[index].y);
    }
  }
  const group = id => arranged.nodes.find(node => node.id === `group-${id}`);
  assert.ok(group('data').position.y < group('research').position.y);
  assert.ok(group('research').position.x < group('delivery').position.x);
  assert.ok(group('market').position.x < group('research').position.x);
  assert.ok(group('evidence').position.x < group('decision').position.x);
  assert.ok(group('ledger').position.y > group('environment').position.y);

  const dataChildren = arranged.nodes.filter(node => node.parentId === 'group-data');
  const nextX = Math.max(34, ...dataChildren.map(node => node.position.x + Number(node.style.width))) + 46;
  const withDraftNode = arranged.nodes.map(node => node.id === 'group-data'
    ? {...node, style: {...node.style, width: Math.max(Number(node.style.width), nextX + 374)}}
    : node);
  withDraftNode.push({
    id: 'draft-node-test', parentId: 'group-data', position: {x: nextX, y: 74},
    style: {width: 340, height: 120}, data: {kind: 'node'},
  });
  assert.equal(routeBtcPanoramaEdges(withDraftNode, edges).size, 49);
});

test('panorama is a query-addressable editable view with effective controls', () => {
  assert.match(workspace, /btc-panorama/);
  assert.match(workspace, /BTC 系统全景/);
  assert.match(workspace, /<BtcSystemPanorama/);
  assert.match(workspace, /const view = searchParams\.get\('view'\) === 'btc-panorama' \? 'btc-panorama' : localView/);
  assert.doesNotMatch(workspace, /\[searchParams\]\);/);
  assert.match(component, /缩小全景图/);
  assert.match(component, /放大全景图/);
  assert.match(component, /适应画布/);
  assert.match(component, /恢复 100%/);
  assert.match(component, /<ReactFlow/);
  assert.match(component, /localStorage\.setItem\(STORAGE_KEY/);
  assert.match(component, /在当前分区新增节点/);
  assert.match(component, /新增连线/);
  assert.match(component, /onNodeClick=/);
  assert.match(component, /onEdgeClick=/);
  assert.match(component, /onPaneClick=/);
  assert.match(component, /onSelectionChange=\{handleSelectionChange\}/);
  assert.match(component, /if \(selectedEdges\.length\) selectEdge\(selectedEdges\[0\]\)/);
  assert.match(component, /applyBtcPanoramaBaselineGeometry/);
  assert.match(component, /恢复原始版本/);
  assert.match(component, /重新整理布局/);
  assert.match(component, /arrangeBtcPanorama/);
  assert.match(component, /routeBtcPanoramaEdges/);
  assert.match(component, /handleNodeDragStart[\s\S]*layoutRequestRef\.current \+= 1/);
  assert.match(component, /data: \{\.\.\.edge\.data!, dashed: Boolean\(value\)\}/);
  assert.match(component, /field === 'label'[\s\S]*routeSubsetSafely\(nodes, updated, new Set\(\[selectedEdgeId\]\)\)\.edges/);
  assert.match(component, /fitView\(\{padding: 0\.06, duration: 0\}\)/);
  const arrangedSource = component.match(/const applyArranged = async[\s\S]*?\n  \};/)?.[0] ?? '';
  assert.match(arrangedSource, /await fitPanoramaAfterRender\(250\)[\s\S]*if \(request !== layoutRequestRef\.current\) return;[\s\S]*setLayoutBusy\(false\)[\s\S]*setStatus\(message\)/);
  const restoreSource = component.match(/const restoreBaseline = \(\) => \{[\s\S]*?\n  \};/)?.[0] ?? '';
  assert.doesNotMatch(restoreSource, /applyArranged|arrangeBtcPanorama/);
  assert.match(restoreSource, /setNodes\(clone\(BASELINE_NODES\)\)[\s\S]*setEdges\(clone\(BASELINE_EDGES\)\)/);
  assert.match(restoreSource, /fitPanoramaAfterRender\(0\)[\s\S]*if \(request !== layoutRequestRef\.current\) return;[\s\S]*setLayoutBusy\(false\)[\s\S]*已恢复到画布/);
  assert.match(component, /nodesDraggable=\{!layoutBusy\}/);
  assert.match(component, /panOnDrag=\{!layoutBusy\}/);
  assert.match(component, /panOnScroll=\{!layoutBusy\}/);
  assert.match(component, /selectionOnDrag=\{!layoutBusy\}/);
  assert.match(component, /elementsSelectable=\{!layoutBusy\}/);
  assert.match(component, /zoomOnScroll=\{!layoutBusy\}/);
  assert.match(component, /zoomOnPinch=\{!layoutBusy\}/);
  assert.match(component, /zoomOnDoubleClick=\{!layoutBusy\}/);
  assert.match(component, /zoomActivationKeyCode=\{layoutBusy \? null : undefined\}/);
  assert.match(component, /<MiniMap pannable=\{!layoutBusy\} zoomable=\{!layoutBusy\}/);
  assert.match(component, /handleNodeDragStart[\s\S]*if \(layoutBusy\) \{[\s\S]*dragSnapshotRef\.current = null;[\s\S]*return;/);
  assert.match(component, /handleNodeDragStop[\s\S]*if \(layoutBusy\) \{[\s\S]*dragSnapshotRef\.current = null;[\s\S]*return;/);
  assert.match(component, /const isValidConnection[\s\S]*return !layoutBusy && Boolean/);
  assert.match(component, /const onConnect[\s\S]*if \(layoutBusy \|\| !isValidConnection\(connection\)\) return;/);
  assert.match(component, /<fieldset className="btc-panorama-inspector-fields" disabled=\{layoutBusy\}>/);
  assert.match(component, /personal_unverified_draft/);
  assert.match(component, /parseBtcPanoramaDraft/);
  assert.match(validator, /BTC_PANORAMA_MAX_DRAFT_BYTES = 1_000_000/);
  assert.match(workspace, /原始快照只读 · 个人草稿可编辑且未经代码核验/);
  assert.doesNotMatch(component, /fetch\(|axios|method:\s*['"]POST/);
  assert.doesNotMatch(component, /dangerouslySetInnerHTML/);
  assert.ok([...browserSpec.matchAll(/page\.reload\(\{waitUntil: 'domcontentloaded'\}\)/g)].length >= 3);
  assert.match(browserSpec, /scrollIntoViewIfNeeded\(\)[\s\S]*document\.elementFromPoint\(x, y\)\?\.closest\('\[data-panorama-node\]'\)/);
  assert.doesNotMatch(browserSpec, /force:\s*true/);
  assert.match(styles, /\.btc-panorama-viewport[^}]*overflow:\s*hidden/);
  assert.match(styles, /\.btc-panorama-viewport \.react-flow[^}]*background:\s*#090f18/);
  assert.match(styles, /\.btc-flow-node[^}]*color:\s*#f0f6ff[^}]*background:\s*#23384f/);
  assert.match(styles, /\.react-flow__edge-path[^}]*stroke:\s*#91a9c2/);
  assert.match(styles, /\.react-flow__edge\.selected \.react-flow__edge-path[^}]*stroke:\s*#f0b35a/);
  assert.match(component, /<Background color="#26374a"/);
  assert.match(component, /maskColor="rgba\(4, 8, 14, \.72\)"/);
  assert.doesNotMatch(component, /原始 A–I 结构及实虚线来自/);
  assert.doesNotMatch(component, /个人编辑草稿不是实时权限或代码验收/);
  assert.doesNotMatch(component, /可从节点右侧 \/ 下方手柄拖到另一节点/);
});

const validDraft = () => ({
  schemaVersion: BTC_PANORAMA_DRAFT_SCHEMA,
  sourceHead: panorama.sourceHead,
  savedAt: '2026-09-29T09:00:00.000Z',
  verification: 'personal_unverified_draft',
  nodes: [
    {
      id: 'group-a', type: 'panoramaGroup', position: {x: 0, y: 0},
      style: {width: 1200, height: 800},
      data: {kind: 'group', title: 'A', detail: '', original: true},
    },
    {
      id: 'node-a', type: 'panoramaNode', parentId: 'group-a', extent: 'parent',
      position: {x: 100, y: 100}, style: {width: 340, height: 120},
      data: {kind: 'node', title: '<img src=x onerror=globalThis.pwned=1>', detail: '<script>pwned()</script>', original: true},
      dangerouslySetInnerHTML: {__html: '<script>pwned()</script>'},
    },
    {
      id: 'node-b', type: 'panoramaNode', parentId: 'group-a', extent: 'parent',
      position: {x: 500, y: 100}, style: {width: 340, height: 120},
      data: {kind: 'node', title: 'B', detail: '', original: false},
    },
  ],
  edges: [{
    id: 'edge-a', source: 'node-a', target: 'node-b', label: '<b>plain text</b>',
    data: {original: false, dashed: false, bidirectional: false},
    style: {backgroundImage: 'url(https://invalid.example/track)'},
  }],
});

test('draft parser accepts plain-text markup but strips unapproved visual fields', () => {
  const parsed = parseBtcPanoramaDraft(JSON.stringify(validDraft()), panorama.sourceHead, ['group-a']);
  assert.equal(parsed.nodes[1].data.title, '<img src=x onerror=globalThis.pwned=1>');
  assert.equal(parsed.nodes[1].data.detail, '<script>pwned()</script>');
  assert.equal('dangerouslySetInnerHTML' in parsed.nodes[1], false);
  assert.deepEqual(parsed.nodes[1].style, {width: 340, height: 120});
  assert.equal('style' in parsed.edges[0], false);
});

test('draft parser rejects wrong identity, unsafe geometry and malformed node types', () => {
  const cases = [];
  const wrongVerification = validDraft();
  wrongVerification.verification = 'verified';
  cases.push(wrongVerification);
  const wrongSource = validDraft();
  wrongSource.sourceHead = 'different-head';
  cases.push(wrongSource);
  const wrongType = validDraft();
  wrongType.nodes[1].type = 'panoramaGroup';
  cases.push(wrongType);
  const unboundedPosition = validDraft();
  unboundedPosition.nodes[1].position.x = 100_001;
  cases.push(unboundedPosition);
  const unboundedSize = validDraft();
  unboundedSize.nodes[1].style.width = 10_001;
  cases.push(unboundedSize);
  const missingGroup = validDraft();
  missingGroup.nodes = missingGroup.nodes.filter(node => node.id !== 'group-a');
  cases.push(missingGroup);
  for (const draft of cases) {
    assert.throws(() => parseBtcPanoramaDraft(JSON.stringify(draft), panorama.sourceHead, ['group-a']));
  }
});

test('draft parser rejects duplicate, missing, group and self edge references', () => {
  const cases = [];
  const duplicate = validDraft();
  duplicate.edges.push(structuredClone(duplicate.edges[0]));
  cases.push(duplicate);
  const missing = validDraft();
  missing.edges[0].target = 'missing-node';
  cases.push(missing);
  const groupEndpoint = validDraft();
  groupEndpoint.edges[0].source = 'group-a';
  cases.push(groupEndpoint);
  const selfEdge = validDraft();
  selfEdge.edges[0].target = 'node-a';
  cases.push(selfEdge);
  for (const draft of cases) {
    assert.throws(() => parseBtcPanoramaDraft(JSON.stringify(draft), panorama.sourceHead, ['group-a']));
  }
});
