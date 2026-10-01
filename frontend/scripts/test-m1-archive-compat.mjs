import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = fileURLToPath(new URL('../../', import.meta.url));
const source = readFileSync(root + 'frontend/src/workspaces/research/workspace-evidence.ts', 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
}).outputText;
const module = {exports: {}};
vm.runInNewContext(`(function(require,module,exports){${compiled}\n})`, {
  console,
  queueMicrotask,
})(require, module, module.exports);
const evidence = module.exports;

const local = {
  summary: {run_id: 'q1', paths: {run_root: 'artifacts/qlib_runs/q1'}},
};
assert.equal(evidence.runEvidenceErrors('q1', 'artifacts/qlib_runs', local, 'qlib').length, 0);

const provenance = {
  storage: 'immutable_shared_data',
  dataset_id: 'm1-trend-environment-acceptance',
  dataset_version: 'm1-okx-59f5eb861-20260911',
  manifest_git_spec: '165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json',
  logical_run: 'qlib_runs/m1-okx-qlib',
  consumer_read_only: true,
  historical_reconstructed_availability: true,
};
const archived = {
  summary: {
    run_id: 'm1-okx-qlib',
    paths: {run_root: 'shared-data://m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911/qlib_runs/m1-okx-qlib'},
    evidence_provenance: provenance,
  },
};
assert.ok(
  evidence.runEvidenceErrors('m1-okx-qlib', 'artifacts/qlib_runs', archived, 'qlib').length,
  'shared workspace actions keep the legacy local-only evidence contract by default',
);
assert.equal(
  evidence.runEvidenceErrors('m1-okx-qlib', 'artifacts/qlib_runs', archived, 'qlib', '', {allowReadonlyM1Archive: true}).length,
  0,
  'the fixed immutable M1 archive must be accepted only through its exact logical identity',
);
for (const bad of [
  {...archived, summary: {...archived.summary, paths: {run_root: 'shared-data://other/m1-okx-59f5eb861-20260911/qlib_runs/m1-okx-qlib'}}},
  {...archived, summary: {...archived.summary, paths: {run_root: 'SHARED-DATA://m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911/qlib_runs/m1-okx-qlib'}}},
  {...archived, summary: {...archived.summary, paths: {run_root: 'shared-data:\\\\m1-trend-environment-acceptance\\m1-okx-59f5eb861-20260911\\qlib_runs\\m1-okx-qlib'}}},
  {...archived, summary: {...archived.summary, paths: {run_root: 'shared-data://m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911/qlib_runs/m1-okx-qlib/'}}},
  {...archived, summary: {...archived.summary, evidence_provenance: {...provenance, dataset_version: 'other'}}},
  {...archived, summary: {...archived.summary, evidence_provenance: {...provenance, manifest_git_spec: 'HEAD:untrusted.json'}}},
  {...archived, summary: {...archived.summary, evidence_provenance: {...provenance, logical_run: 'qlib_runs/other'}}},
  {...archived, summary: {...archived.summary, evidence_provenance: {...provenance, consumer_read_only: false}}},
  {...archived, summary: {...archived.summary, run_id: 'other'}},
]) {
  assert.ok(
    evidence.runEvidenceErrors('m1-okx-qlib', 'artifacts/qlib_runs', bad, 'qlib', '', {allowReadonlyM1Archive: true}).length,
    'wrong archive identity or provenance must fail closed',
  );
}
for (const key of Object.keys(provenance)) {
  const missing = {...provenance};
  delete missing[key];
  assert.ok(
    evidence.runEvidenceErrors('m1-okx-qlib', 'artifacts/qlib_runs', {...archived, summary:{...archived.summary,evidence_provenance:missing}}, 'qlib', '', {allowReadonlyM1Archive:true}).length,
    `missing provenance field must fail closed: ${key}`,
  );
}

const flush = () => new Promise(resolve => setImmediate(resolve));
const order = [];
let selectedCalls = 0;
const firstHandle = evidence.acquireResearchRunPageReads(
  'qlib:q1',
  async () => {selectedCalls += 1; order.push('detail:start'); await flush(); order.push('detail:end'); return {run_id: 'q1'};},
  async () => {order.push('qlib:start'); await flush(); order.push('qlib:end'); return {runs: [{run_id: 'q1'}]};},
  async () => {order.push('factory:start'); await flush(); order.push('factory:end'); return {runs: [{run_id: 'af1'}]};},
);
firstHandle.release();
const reads = evidence.acquireResearchRunPageReads(
  'qlib:q1',
  async () => {order.push('detail:start'); await flush(); order.push('detail:end'); return {run_id: 'q1'};},
  async () => {order.push('qlib:start'); await flush(); order.push('qlib:end'); return {runs: [{run_id: 'q1'}]};},
  async () => {order.push('factory:start'); await flush(); order.push('factory:end'); return {runs: [{run_id: 'af1'}]};},
);
const [selectedRead, qlibRead, factoryRead] = await Promise.all([reads.selected, reads.qlib, reads.factory]);
assert.deepEqual(
  order,
  ['detail:start', 'detail:end', 'qlib:start', 'qlib:end', 'factory:start', 'factory:end'],
  'full-integrity archive reads must be serialized to avoid cross-request I/O contention',
);
assert.equal(selectedCalls, 1, 'StrictMode setup/cleanup/setup shares one in-flight read chain');
assert.equal(selectedRead.status, 'fulfilled');
assert.equal(qlibRead.status, 'fulfilled');
assert.equal(factoryRead.status, 'fulfilled');
reads.release();
await flush();
let refreshedCalls = 0;
const refreshed = evidence.acquireResearchRunPageReads(
  'qlib:q1',
  async () => {refreshedCalls += 1; return {run_id: 'q1'};},
  async () => ({runs: []}),
  async () => ({runs: []}),
);
await refreshed.factory;
refreshed.release();
assert.equal(refreshedCalls, 1, 'completed reads are not cached; an explicit refresh can issue a new verified GET');

const partial = evidence.acquireResearchRunPageReads(
  'none',
  null,
  async () => {throw new Error('qlib unavailable');},
  async () => ({runs: []}),
);
assert.equal(await partial.selected, null);
assert.equal((await partial.qlib).status, 'rejected');
assert.equal((await partial.factory).status, 'fulfilled');
partial.release();

let finishOld;
let activeReads = 0;
let maxActiveReads = 0;
const obsoleteCalls = [];
const old = evidence.acquireResearchRunPageReads(
  'qlib:old',
  () => new Promise(resolve => {
    activeReads += 1; maxActiveReads = Math.max(maxActiveReads, activeReads);
    finishOld = () => {activeReads -= 1; resolve({run_id: 'old'});};
  }),
  async () => {obsoleteCalls.push('old:qlib'); return {runs: []};},
  async () => {obsoleteCalls.push('old:factory'); return {runs: []};},
);
await flush();
old.release();
await flush();
const current = evidence.acquireResearchRunPageReads(
  'qlib:current',
  async () => {activeReads += 1; maxActiveReads = Math.max(maxActiveReads, activeReads); activeReads -= 1; return {run_id: 'current'};},
  async () => {obsoleteCalls.push('current:qlib'); return {runs: []};},
  async () => {obsoleteCalls.push('current:factory'); return {runs: []};},
);
finishOld();
await Promise.all([old.factory, current.selected, current.qlib, current.factory]);
current.release();
assert.deepEqual(obsoleteCalls, ['current:qlib', 'current:factory'], 'an obsolete selection stops before starting its remaining archive reads');
assert.equal(maxActiveReads, 1, 'a replacement selection does not overlap a full-integrity read already in progress');

let finishSameKey;
const sameKeyCalls = [];
const staleSameKey = evidence.acquireResearchRunPageReads(
  'qlib:same',
  () => new Promise(resolve => {finishSameKey = resolve;}),
  async () => {sameKeyCalls.push('stale:qlib'); return {runs: []};},
  async () => {sameKeyCalls.push('stale:factory'); return {runs: []};},
);
await flush();
staleSameKey.release();
await flush();
const replacementSameKey = evidence.acquireResearchRunPageReads(
  'qlib:same',
  async () => {sameKeyCalls.push('replacement:detail'); return {run_id: 'same'};},
  async () => {sameKeyCalls.push('replacement:qlib'); return {runs: []};},
  async () => {sameKeyCalls.push('replacement:factory'); return {runs: []};},
);
finishSameKey({run_id: 'stale'});
await Promise.all([staleSameKey.factory, replacementSameKey.selected, replacementSameKey.qlib, replacementSameKey.factory]);
replacementSameKey.release();
assert.deepEqual(
  sameKeyCalls,
  ['replacement:detail', 'replacement:qlib', 'replacement:factory'],
  'a cancelled same-key entry cannot delete or feed the replacement entry',
);

console.log('PASS: exact M1 archive provenance and sequential full-integrity research reads.');
