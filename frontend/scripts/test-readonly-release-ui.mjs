import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

function loadAccess() {
  const module = {exports: {}};
  const code = ts.transpileModule(read('src/lib/research-workspace-access.ts'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  new Function('module', 'exports', 'require', code)(module, module.exports, require);
  return module.exports;
}

test('research workspace permissions are strict and unknown stays fail-closed', () => {
  const {researchWorkspaceAccess} = loadAccess();
  const readonly = researchWorkspaceAccess({evidence_profile: 'research_readonly', read_only: true, controls_disabled: true});
  assert.equal(readonly.mode, 'research_readonly');
  assert.equal(readonly.researchWrites, false);
  assert.equal(readonly.candidateManagement, false);

  const management = researchWorkspaceAccess({evidence_profile: 'candidate_management', read_only: true, controls_disabled: true});
  assert.equal(management.mode, 'candidate_management');
  assert.equal(management.researchWrites, false);
  assert.equal(management.candidateManagement, true);

  for (const health of [null, {}, {evidence_profile: 'research_readonly'},
    {evidence_profile: 'research_readonly', read_only: false, controls_disabled: true},
    {evidence_profile: 'candidate_management', read_only: true, controls_disabled: false}]) {
    const access = researchWorkspaceAccess(health);
    assert.equal(access.mode, 'unknown');
    assert.equal(access.researchWrites, false);
    assert.equal(access.candidateManagement, false);
  }
});

test('known runtime profiles require affirmative writable health flags', () => {
  const {researchWorkspaceAccess} = loadAccess();
  for (const profile of ['demo_quasi_live', 'promotion_strict']) {
    assert.equal(researchWorkspaceAccess({evidence_profile: profile, read_only: false, controls_disabled: false}).researchWrites, true);
    assert.equal(researchWorkspaceAccess({evidence_profile: profile, read_only: false}).researchWrites, false);
  }
});

test('readonly release removes inert placeholders and preserves explanatory copy', () => {
  const handoff = read('src/workspaces/research/CandidateHandoff.tsx');
  const workspace = read('src/workspaces/ResearchPortfolioWorkspace.tsx');
  const allocation = read('src/workspaces/portfolio/PortfolioAllocation.tsx');
  assert.doesNotMatch(handoff, /<button[^>]*>直接发布本地草稿/);
  assert.match(handoff, /本地草稿不能直接发布/);
  assert.doesNotMatch(workspace, /<button[^>]*>再平衡（尚未接入）/);
  assert.doesNotMatch(workspace, /<button[^>]*>实际持仓风险（未连接账户）/);
  assert.match(workspace, /实际持仓风险未连接账户/);
  assert.doesNotMatch(allocation, /rebalance placeholder/);
  assert.match(allocation, /再平衡尚未接入受控提交/);
});

test('read failure next action expands the real provenance details in place', () => {
  const workbench = read('src/workspaces/research/ResearchWorkbench.tsx');
  assert.match(workbench, /provenanceRef\.current\.open\s*=\s*true/);
  assert.match(workbench, /aria-controls=\{readFailures\.length \? 'research-provenance-details'/);
  assert.match(workbench, /id="research-provenance-details"/);
});

test('write dispatchers and alpha factory have explicit profile gates while GET refresh remains', () => {
  const workspace = read('src/workspaces/ResearchPortfolioWorkspace.tsx');
  const factory = read('src/workspaces/research/AlphaFactoryConsole.tsx');
  const delivery = read('src/workspaces/research/CandidateDelivery.tsx');
  assert.match(workspace, /workspaceAccess\.researchWrites/);
  assert.match(workspace, /if \(!readOnly && !workspaceAccess\.researchWrites\)/);
  assert.match(workspace, /disabled=\{!!busy\} onClick=\{\(\) => runTask\('refresh'/);
  assert.match(factory, /commandsDisabled/);
  assert.match(factory, /if \(readOnly \|\| commandsDisabled/);
  assert.match(factory, /loadOverview/);
  assert.match(delivery, /candidateManagement/);
  assert.match(delivery, /researchWorkspaceAccess/);
  assert.match(delivery, /候选管理写入口保持关闭/);
});

test('sealed A/B blocked evidence copy remains visible and fail-closed', () => {
  const evidence = read('src/workspaces/research/MarketStateEvidence.tsx');
  assert.match(evidence, /固定 A\/B 未完成 · 安全阻断/);
  assert.match(evidence, /两臂没有共同完成预定的 2960 事件/);
  assert.match(evidence, /不支持改善、晋级或交易授权声明/);
});
