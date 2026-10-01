import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = path.join(root, 'src/workspaces/crypto/operator-attempt-state.ts');
const source = fs.readFileSync(sourcePath, 'utf8');
const require = createRequire(import.meta.url);
const tsPath = [
  path.join(root, 'node_modules/typescript/lib/typescript.js'),
  path.resolve(root, '..', '..', '..', 'agent-', 'frontend/node_modules/typescript/lib/typescript.js'),
].find((candidate) => fs.existsSync(candidate));
assert.ok(tsPath, 'TypeScript runtime is required for attempt-state tests');
const ts = require(tsPath);
const apiSourcePath = path.join(root, 'src/lib/api.ts');
const apiSource = fs.readFileSync(apiSourcePath, 'utf8');
const apiTranspiled = ts.transpileModule(apiSource, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true},
}).outputText;
const apiModule = {exports: {}};
new Function('exports', 'require', 'module', '__filename', '__dirname', apiTranspiled)(
  apiModule.exports,
  () => { throw new Error('api.ts must remain dependency-free'); },
  apiModule,
  apiSourcePath,
  root,
);
const transpiled = ts.transpileModule(source, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true},
}).outputText;

class StubApiError extends Error {
  constructor(status, message, operatorError = null) {
    super(message);
    this.status = status;
    this.operatorError = operatorError;
  }
}
const apiStub = {ApiError: StubApiError};
const module = {exports: {}};
const localRequire = (request) => request === '../../lib/api' ? apiStub : (() => { throw new Error(`unexpected require ${request}`); })();
new Function('exports', 'require', 'module', '__filename', '__dirname', transpiled)(module.exports, localRequire, module, sourcePath, root);
const attempt = module.exports;

const safetyFlags = {promotion_eligible: false, paper: false, live: false, private: false, order: false, real_order: false, transfer: false, withdraw: false};
const envelope = {
  schema_version: 'btc_demo_operator_error_v2',
  error_code: 'operator_action_failed',
  allowed: false,
  execution_permission: false,
  blocker_codes: ['operator_action_failed'],
  reason_codes: ['authoritative_preflight_rejected'],
  safety_flags: safetyFlags,
};

assert.deepEqual(apiModule.exports.decodeBtcDemoOperatorError(envelope), envelope, 'trusted operator envelope must survive API decoding');
assert.equal(apiModule.exports.decodeBtcDemoOperatorError({...envelope, allowed: true}), null, 'allowed envelope cannot be a rejection proof');
assert.equal(apiModule.exports.decodeBtcDemoOperatorError({
  ...envelope,
  safety_flags: {...safetyFlags, order: true},
}), null, 'unsafe envelope cannot be trusted by the frontend');

const definitive = attempt.classifyOperatorAttemptError(new StubApiError(400, 'HTTP 400', envelope));
assert.equal(definitive.disposition, 'definitive_rejected');
assert.equal(definitive.errorCode, 'operator_action_failed');
assert.deepEqual(definitive.blockerCodes, ['operator_action_failed']);

for (const error of [
  new StubApiError(408, 'timeout'),
  new StubApiError(400, 'untrusted 400'),
  new StubApiError(500, 'HTTP 500', envelope),
  new Error('TypeError: Failed to fetch'),
]) {
  assert.equal(attempt.classifyOperatorAttemptError(error).disposition, 'ambiguous_unknown');
}

const contract = {
  valid: true,
  actions: [
    {action: 'authoritative_preflight_start', allowed: true, execution_permission: true, blocker_codes: [], reason_codes: ['authorized']},
    {action: 'refresh_account_snapshot', allowed: true, execution_permission: true, blocker_codes: [], reason_codes: ['authorized']},
  ],
  action_map: {
    authoritative_preflight_start: {action: 'authoritative_preflight_start', allowed: true, execution_permission: true, blocker_codes: [], reason_codes: ['authorized']},
    refresh_account_snapshot: {action: 'refresh_account_snapshot', allowed: true, execution_permission: true, blocker_codes: [], reason_codes: ['authorized']},
  },
};
const overlaid = attempt.applyOperatorAttemptOverlay(contract, {
  action: 'authoritative_preflight_start',
  disposition: 'definitive_rejected',
  errorCode: 'operator_action_failed',
  blockerCodes: ['operator_action_failed'],
  reasonCodes: ['authoritative_preflight_rejected'],
  message: 'rejected',
});
assert.equal(overlaid.action_map.authoritative_preflight_start.allowed, false);
assert.equal(overlaid.action_map.refresh_account_snapshot.allowed, true, 'overlay must remain action-scoped');
assert.equal(overlaid.valid, true, 'overlay must not revoke fresh contract');

console.log(JSON.stringify({ok: true, contract: 'btc_demo_operator_attempt_state_v1'}));
