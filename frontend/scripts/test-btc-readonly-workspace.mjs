import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const ts = require('typescript');
const calls = [];
const effects = [];
const timers = [];
const reactHooks = {
  useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}],
  useRef: initial => ({current: initial}),
  useMemo: build => build(),
  useEffect: effect => effects.push(effect),
};
const api = {
  ApiError: class extends Error {},
  apiGet: async url => { calls.push(['GET', url]); throw new Error('fixture unavailable'); },
  apiPost: async url => { calls.push(['POST', url]); throw new Error('must not submit'); },
};
function load(relative) {
  const filename = path.resolve(root, relative);
  const source = fs.readFileSync(filename, 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  const module = {exports: {}};
  new Function('require', 'module', 'exports', compiled)(name => {
    if (name === 'react') return reactHooks;
    if (name.endsWith('/lib/api')) return api;
    if (name.endsWith('/frontendIdentity')) return {frontendIdentity:{source_head:'readonly-test',fingerprint:'readonly-test'}};
    if (name.startsWith('.')) return load(path.relative(root, path.resolve(path.dirname(filename), `${name}.ts`)));
    return require(name);
  }, module, module.exports);
  return module.exports;
}
globalThis.window = {
  setInterval: fn => { timers.push(fn); return timers.length; },
  clearInterval: () => {},
};

// Failure-first: the original hook ignores enabled=false and still polls four
// unmounted Demo routes. Exercise real hooks/handlers, not a copied algorithm.
const {useDemoOperatorV2} = load('src/workspaces/crypto/demo-operator-v2.ts');
const disabled = useDemoOperatorV2({enabled: false});
effects.splice(0).forEach(effect => effect());
await disabled.refresh();
await disabled.dispatch('refresh_account_snapshot');
await disabled.acknowledgeNewOperation('refresh_account_snapshot');
timers.splice(0).forEach(tick => tick());
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(calls, [], 'readonly/unknown mode must not poll, refresh or submit to Demo');
assert.equal(disabled.catalog, null);
assert.equal(disabled.status, null);
assert.equal(disabled.klines, null);
assert.equal(disabled.contract.valid, false);
assert.equal(disabled.loading, false);
assert.equal(disabled.bootstrapFailed, false);
assert.equal(disabled.bootstrapError, '');

const {cryptoWorkspaceAccess} = load('src/workspaces/crypto/workspace-access.ts');
for (const health of [null, {}, {evidence_profile: 'unknown'}, {evidence_profile: 'research_readonly', read_only: false}]) {
  const access = cryptoWorkspaceAccess(health);
  assert.equal(access.mode, 'unavailable');
  assert.equal(access.demoRuntime, false);
  assert.equal(access.publicMarket, false);
  assert.equal(access.publicStream, false);
}
const readonly = cryptoWorkspaceAccess({evidence_profile: 'research_readonly', read_only: true, controls_disabled: true});
const management = cryptoWorkspaceAccess({evidence_profile: 'candidate_management', read_only: true, controls_disabled: true});
assert.deepEqual(management, readonly, 'management BTC workspace must retain only the readonly public surfaces');
for (const flags of [{read_only:false,controls_disabled:true}, {read_only:true,controls_disabled:false}, {}]) {
  const blocked = cryptoWorkspaceAccess({evidence_profile:'candidate_management', ...flags});
  assert.equal(blocked.mode, 'unavailable'); assert.equal(blocked.demoRuntime, false);
  assert.equal(blocked.publicMarket, false); assert.equal(blocked.publicStream, false);
}
assert.equal(readonly.mode, 'research_readonly');
assert.equal(readonly.demoRuntime, false);
assert.equal(readonly.publicMarket, true);
assert.equal(readonly.publicStream, true);
assert.equal(readonly.marketViewPath, '/api/research/btc/public-market/view');
assert.equal(readonly.marketTickerPath, '/api/research/btc/public-market/ticker');
assert.equal(readonly.marketStreamPath, '/api/research/btc/public-market/stream');
for (const profile of ['promotion_strict', 'demo_quasi_live']) {
  const runtime = cryptoWorkspaceAccess({evidence_profile: profile, read_only: false});
  assert.equal(runtime.mode, 'runtime');
  assert.equal(runtime.demoRuntime, true);
}

const workspace = fs.readFileSync(path.join(root, 'src/workspaces/CryptoWorkspace.tsx'), 'utf8');
assert.match(workspace, /useDemoOperatorV2\(\{refreshToken: bootstrapRetry, enabled: access\.demoRuntime\}\)/);
assert.match(workspace, /if \(!access\.publicMarket\)/);
assert.match(workspace, /if \(!access\.publicStream\)/);
assert.match(workspace, /new EventSource\(access\.marketStreamPath\)/);
// Keep the original surfaces mounted; a deployment restriction is not a new UI.
assert.doesNotMatch(workspace, /ReadonlyRuntimeNotice|ReadonlyResearchLinks/);
assert.match(workspace, /<DemoTradingConsole\s+workspaceMode=\{access\.mode\}/);
assert.match(workspace, /bottomTab === 'tester' \? \(\s*<StrategyTesterReport/);
for (const component of ['OrdersTable', 'FillsTable', 'PositionsTable', 'CostsPanel', 'AuditPanel']) {
  assert.ok(workspace.includes(`<${component}`), `${component} must remain in the original dock`);
}

// SSR the real console and tester, rather than a replacement notice. Local
// imports are transpiled; the chart engine is inert because SSR runs no effects.
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const icons = await import('@phosphor-icons/react');
const viewCache = new Map();
function loadView(filename) {
  if (viewCache.has(filename)) return viewCache.get(filename).exports;
  const module = {exports: {}};
  viewCache.set(filename, module);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  new Function('require', 'module', 'exports', code)(name => {
    if (name.endsWith('.css')) return {};
    if (name === '@phosphor-icons/react') return icons;
    if (name === 'lightweight-charts') return {};
    if (name.endsWith('/frontendIdentity')) return {frontendIdentity:{source_head:'readonly-test',fingerprint:'readonly-test'}};
    if (name.endsWith('/lib/api')) return api;
    if (!name.startsWith('.')) return require(name);
    const base = path.resolve(path.dirname(filename), name);
    const dependency = [base, `${base}.ts`, `${base}.tsx`].find(file => fs.existsSync(file) && fs.statSync(file).isFile());
    assert.ok(dependency, `missing local import ${name}`);
    return loadView(dependency);
  }, module, module.exports);
  return module.exports;
}
const view = name => loadView(path.join(root, `src/workspaces/crypto/${name}.tsx`)).default;
const Console = view('DemoTradingConsole');
const consoleProps = {
  operatorController: disabled, catalog: null, status: null, statusError: '',
  privateReadonlyObservation: null, privateReadonlyObservationError: '', selectedCandidateId: '',
  onCandidateChange() {}, onStrategyChange() {}, runtimeSignalLoading: false,
  runtimeSignalReady: false, runtimeSignalBlocker: '',
  promotionReadinessLoading: false, promotionReadinessBlockers: [],
};
const {MemoryRouter}=require('react-router-dom');
const renderConsole = props => renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/crypto']},
  React.createElement(Console, {...consoleProps, ...props})));
for (const mode of ['research_readonly', 'unavailable']) {
  const html = renderConsole({workspaceMode: mode});
  assert.match(html, mode === 'research_readonly' ? /研究只读/ : /后端模式尚未确认/);
  for (const section of ['OKX 模拟盘', '策略线', '授权限额', '风险保护状态', '运行健康', '启动确认', '权威预检并启动', '刷新账户快照']) {
    assert.ok(html.includes(section), `original console section missing: ${section}`);
  }
  assert.match(html, /未知/);
  assert.doesNotMatch(html, /后端统一运行控制契约不可用|正在读取冻结策略目录|not healthy|historical \/ mismatch/);
  const controls = html.match(/<(?:button|input|select)\b[^>]*>/g) ?? [];
  assert.ok(controls.length >= 15);
  assert.ok(controls.every(control => /\bdisabled/.test(control)), 'all console actions and confirmations stay disabled');
}
// A permissive/stale controller must not override the display-level restriction.
const permissive = {...disabled, contract: {...disabled.contract, valid: true,
  action_map: Object.fromEntries(Object.keys(disabled.contract.action_map).map(action => [action, {
    action, allowed: true, execution_permission: true, blocker_codes: [], reason_codes: [],
  }])),
}};
const restricted = renderConsole({workspaceMode: 'research_readonly', operatorController: permissive});
assert.ok((restricted.match(/<button\b[^>]*>/g) ?? []).every(control => /\bdisabled/.test(control)));
const runtimeHtml = renderConsole({operatorController: permissive});
const runtimeRefresh = runtimeHtml.match(/<button\b[^>]*>刷新账户快照<\/button>/)?.[0];
assert.ok(runtimeRefresh);
assert.doesNotMatch(runtimeRefresh, /\bdisabled/);

const testerProps = {
  strategyCatalog: [], editorCandidateId: '', onStrategyChange() {}, selectedCandidateId: '', selectedStrategyId: '',
  selectedStrategyVersion: '', selectedParamsHash: '', sourceLabel: '未读取', sampleEnd: '',
  form: {startDate: '2026-01-01', endDate: '2026-01-02', capital: 5000, commissionRate: 0.0005, slippageBps: 1},
  onFormChange() {}, busy: false, onRun() { throw new Error('must not start research'); },
  run: null, chart: null, history: [], onRestore() {}, canonicalFreshness: 'unavailable', canonical: null,
  canonicalReport: null, historyResponse: null, historyError: '', selectedHistoricalRunId: '', onHistoricalRunSelect() {},
  reportTab: 'overview', onReportTabChange() {}, canRunBacktest: false, readonlyReason: '研究只读：不执行新回测。',
};
const testerHtml = renderToStaticMarkup(React.createElement(view('StrategyTesterReport'), testerProps));
for (const section of ['btc-strategy-tester', '回测报告视图', '业绩表现', '交易分析', '风险与资本', '证据链', '本机研究草稿源码']) {
  assert.ok(testerHtml.includes(section), `original tester section missing: ${section}`);
}
assert.match(testerHtml, /研究只读：不执行新回测/);
assert.match(testerHtml, /aria-label="运行本地研究回测" disabled=""/);
assert.match(testerHtml, /未加载研究证据/);
assert.deepEqual(calls, [], 'restoring layout must not introduce side effects');

// Existing runtime-mode defaults still issue the four existing diagnostic GETs.
calls.length = 0;
effects.length = 0;
const runtime = useDemoOperatorV2({enabled: true});
await runtime.refresh();
assert.equal(calls.length, 4);
assert.ok(calls.every(([method]) => method === 'GET'));
delete globalThis.window;
console.log('BTC readonly restoration: original console/tester mounted; actions disabled; zero GET/POST/timers; honest missing facts; runtime compatibility passed');
