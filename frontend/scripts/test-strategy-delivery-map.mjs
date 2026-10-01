import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const require = createRequire(import.meta.url);
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const read = path => readFileSync(resolve(root, path), 'utf8');
function load(path, replacements = {}) {
  const module = {exports: {}};
  const compiled = ts.transpileModule(read(path), {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  const importModule = name => Object.hasOwn(replacements, name) ? replacements[name] : require(name);
  new Function('exports', 'require', 'module', compiled)(module.exports, importModule, module);
  return module.exports;
}
const model = load('frontend/src/workspaces/architecture/mindmap.ts');
const status = model.strategyDeliveryStatus;

test('V0-V3 are separate from M1-M4 and bound to a reviewed source, not the serving HEAD', () => {
  assert.ok(status, 'missing V0-V3 delivery assessment');
  assert.equal(status.asOf, '2026-09-21');
  assert.equal(status.reviewedHead, 'e2e7496acaa16b9fd5eda37dd65ea328a18ab032');
  assert.deepEqual(status.stages.map(stage => stage.id), ['V0', 'V1', 'V2', 'V3']);
  assert.equal(status.overallComplete, true);
  assert.equal(status.runtimeObserved, false);
  assert.equal(status.tradingAuthorized, false);
  assert.match(status.boundary, /不是 M3—M4/);
  assert.match(status.conclusion, /V0—V3 离线工程已限定结项/);
  assert.equal(status.closeoutSourceHead, 'e024f42468f4d0a7c39b83fe28ed86c5688459aa');
  assert.equal(status.historicalStageSourceHead, '897d5e99ebe4c898f71ac66cf33fb2d2420855d5');
});

test('engineering evidence, zero-trade candidate and remaining UI gap are not conflated', () => {
  assert.ok(status);
  assert.match(status.stages.find(stage => stage.id === 'V1').verification, /11 项/);
  assert.match(status.stages.find(stage => stage.id === 'V2').verification, /28 项/);
  assert.match(status.stages.find(stage => stage.id === 'V3').verification, /51.*1.*5/);
  assert.match(status.stages.find(stage => stage.id === 'V3').publication, /1,392.*0.*成交/);
  assert.match(status.stages.find(stage => stage.id === 'V3').evidence, /78aaa489214c24f00e076eae0e11ec9089f2f544/);
  assert.match(status.remaining.join(' '), /自然历史阶段.*正式入口验收/);
  assert.match(status.nonBlockers, /503.*不作为.*前置/);
  assert.match(status.nextStep, /不重训.*不搜参/);
  assert.match(status.reportPath, /^docs\/architecture\/system-code-map\/STRATEGY-DELIVERY-STATUS-/);
  const report = read(status.reportPath);
  for (const stage of status.stages) assert.ok(report.includes(stage.id));
  assert.ok(report.includes(status.reviewedHead));
});

test('the real workspace renders the bounded assessment without trading actions or new requests', () => {
  const {default: Workspace} = load('frontend/src/workspaces/ArchitectureMapWorkspace.tsx', {
    '../components/workbench/Workbench': {WorkbenchFrame: ({children}) => React.createElement('main', null, children)},
    '../frontendIdentity': {frontendIdentity: {source_head: 'a'.repeat(40)}},
    './architecture/ArchitectureMindMap': {ArchitectureMindMap: () => null},
    './architecture/ArchitectureKnowledge': {ArchitectureKnowledge: () => null},
    './architecture/mindmap': model,
    './architecture/model': load('frontend/src/workspaces/architecture/model.ts', {
      './catalog.json': JSON.parse(read('frontend/src/workspaces/architecture/catalog.json')),
    }),
    './architecture/architecture-map.css': {},
  });
  const {MemoryRouter} = require('react-router-dom');
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Workspace)));
  assert.match(html, /aria-label="策略接入交付进度"/);
  assert.match(html, /V0—V3 离线工程已限定结项/);
  assert.match(html, /技术验证.*页面发布.*整体结项/);
  assert.match(html, /e2e7496acaa1/);
  assert.match(html, /按上述版本核查/);
  assert.match(html, /自然历史阶段小封存.*正式入口验收/);
  assert.match(html, /href="\/research\?view=run-details&amp;qlibRun=m1-okx-qlib"/);
  assert.match(html, /href="\/research\?view=run-details&amp;offlineRun=donchian-v3-closeout-20260920"/);
  assert.match(html, /href="\/research\?view=run-details&amp;offlineRun=donchian-stage-20260921"/);
  assert.doesNotMatch(html, /<form|>启动 Demo<|>启动训练</);
  const workspace = read('frontend/src/workspaces/ArchitectureMapWorkspace.tsx');
  assert.doesNotMatch(workspace, /fetch\(|axios|method:\s*['"]POST/);
});
