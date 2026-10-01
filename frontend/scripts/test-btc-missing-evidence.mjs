import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
const sourceAt = path => process.env.BTC_DISPLAY_TEST_REF
  ? execFileSync('git', ['show', `${process.env.BTC_DISPLAY_TEST_REF}:frontend/src/workspaces/${path}`], {encoding: 'utf8'})
  : read(`../src/workspaces/${path}`);
const workspace = sourceAt('CryptoWorkspace.tsx');
const report = sourceAt('crypto/StrategyTesterReport.tsx');
assert.equal(report.includes('当前 run 已公开的研究证据完整'), false, 'An absent blocker list must not claim complete evidence');
// Compile the actual named view functions, not copied logic or a replacement UI.
function functions(source, names, prelude = '') {
  const tree = ts.createSourceFile('view.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const selected = tree.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name?.text));
  assert.equal(selected.length, names.length, `missing view function: ${names}`);
  const module = {exports: {}};
  const code = prelude + selected.map(node => node.getText(tree)).join('\n') + `\nexport {${names.join(',')}};`;
  new Function('exports', 'require', 'module', ts.transpileModule(code, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText)(module.exports, name => name === '@phosphor-icons/react'
    ? {ShieldCheck: () => null, WarningCircle: () => null, Clock: () => null, CheckCircle: () => null}
    : require(name), module);
  return module.exports;
}
const helpers = read('../src/workspaces/crypto/account-facts-view.ts');
const views = functions(workspace, ['accountDockView', 'OrdersTable', 'FillsTable', 'PositionsTable', 'DataTable', 'CostsPanel', 'Metric', 'CostEvidence', 'isFundingBill', 'rateBps', 'timestamp', 'AuditPanel', 'auditSeverity', 'auditEventLabel', 'auditSummary', 'formatIso'], `import {ShieldCheck, WarningCircle, Clock, CheckCircle} from '@phosphor-icons/react';\n${helpers}`);
const render = (name, props) => renderToStaticMarkup(React.createElement(views[name], props));
const valid = {ledger_reconciliation: {status: 'reconciled', current_state_exchange_snapshot_match: true, funding_cashflow_reconciled: true}, exchange: {
  captured_at_utc: '2026-09-20T01:00:00Z', orders: [], fills: [], positions: [], bills: [], fee_schedule: {}, funding: {},
}};
for (const [status, error] of [[null, ''], [valid, 'read failed'], [{...valid, ledger_reconciliation: {}}, ''], [{...valid, exchange: {...valid.exchange, captured_at_utc: ''}}, '']]) {
  const view = views.accountDockView(status, error);
  for (const key of ['orders', 'fills', 'positions']) assert.equal(view[key], null);
  for (const name of ['OrdersTable', 'FillsTable', 'PositionsTable']) {
    const html = render(name, {rows: null});
    assert.match(html, /未知/);
    assert.doesNotMatch(html, /当前 Demo 账户为空仓|尚无已对账/);
  }
  const costs = render('CostsPanel', {status: view.status, canonicalReport: null, blockers: []});
  assert.match(costs, /未知/);
  assert.doesNotMatch(costs, /0\.00000000 USDT|证据未阻塞|0 fills/);
}
const empty = views.accountDockView(valid, '');
assert.deepEqual(empty.positions, []);
assert.match(render('PositionsTable', {rows: empty.positions}), /为空仓/);
assert.match(render('OrdersTable', {rows: empty.orders}), /尚无已对账/);
for (const contracts of [null, undefined, '', ' ', 'bad', Infinity]) {
  assert.equal(views.accountDockView({...valid, exchange: {...valid.exchange, positions: [{position_side: 'long', contracts}]}}, '').positions, null);
}
const held = views.accountDockView({...valid, exchange: {...valid.exchange, positions: [{position_side: 'long', contracts: '2'}]}}, '');
assert.equal(held.positions.length, 1);
const costs = render('CostsPanel', {status: valid, canonicalReport: null, blockers: []});
assert.match(costs, /0\.00000000 USDT/);
assert.doesNotMatch(costs, /证据未阻塞/);
for (const fee of ['', null, undefined, 'bad', Infinity]) {
  const invalidCosts = render('CostsPanel', {status: {...valid, exchange: {...valid.exchange, fills: [{fee, fee_currency: 'USDT'}]}}, canonicalReport: null, blockers: []});
  assert.match(invalidCosts, /Demo 成交手续费<\/span><strong>未知/);
}
assert.match(render('AuditPanel', {status: null}), /审计事件未知/);
assert.doesNotMatch(render('AuditPanel', {status: null}), /0 events/);
assert.match(render('AuditPanel', {status: {events: []}}), /0 events/);
const {ResearchBoundary} = functions(report, ['ResearchBoundary']);
const boundary = props => renderToStaticMarkup(React.createElement(ResearchBoundary, props));
assert.match(boundary({blockers: [], sourceKnown: false}), /未知/);
assert.doesNotMatch(boundary({blockers: [], sourceKnown: false}), /0 blockers|研究证据完整/);
assert.match(boundary({blockers: [], sourceKnown: true}), /不代表.*完整/);
assert.match(boundary({blockers: ['retained_blocker'], sourceKnown: false}), /retained_blocker/);
assert.match(workspace, /accountDockView\(demoStatus, demoStatusError\)/);
assert.match(workspace, /<OrdersTable rows=\{accountDock.orders\}/);
assert.match(workspace, /<FillsTable rows=\{accountDock.fills\}/);
assert.match(workspace, /<PositionsTable rows=\{accountDock.positions\}/);
assert.doesNotMatch(workspace, /demoStatus\?\.exchange\.(orders|fills|positions).*\?\? 0/);
assert.equal((report.match(/<ResearchBoundary /g) ?? []).length, 2);
assert.doesNotMatch(report, /当前 run 已公开的研究证据完整/);
console.log('BTC missing evidence: account/error/reconciliation/empty/invalid/held/cost and research boundary SSR passed');
