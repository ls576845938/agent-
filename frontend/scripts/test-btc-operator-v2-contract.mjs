import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');
const operator = read('src/workspaces/crypto/demo-operator-v2.ts');
const apiSource = read('src/lib/api.ts');
const workspace = read('src/workspaces/CryptoWorkspace.tsx');
const consoleSource = read('src/workspaces/crypto/DemoTradingConsole.tsx');
const operationSchema = JSON.parse(read('../schemas/btc_demo_operator_operation_v2.schema.json'));
const backendOperationFixtures = JSON.parse(read('../tests/fixtures/btc_demo_operator_operation_v2.json'));

const actions = [
  'authoritative_preflight_start',
  'refresh_account_snapshot',
  'stop_keep_position',
  'stop_and_flatten',
  'enter_cancel_only',
  'emergency_reduce_only_exit',
  'acknowledge_guardian_trip',
  'recover_guardian_after_fresh_preflight',
];
const mustContain = (source, value) => assert.ok(source.includes(value), `missing ${value}`);
const mustMatch = (source, pattern) => assert.match(source, pattern, `missing ${pattern}`);

// Decoder failure-first contract: malformed identity/schema/action rows are
// represented as an all-denied projection, never as a v1 fallback.
mustContain(operator, "OPERATOR_CONTRACT_SCHEMA = 'btc_demo_operator_contract_v2'");
mustContain(operator, "OPERATION_READ_MODEL_SCHEMA = 'btc_demo_operation_read_model_v2'");
mustContain(operator, 'export function decodeOperatorContract');
mustContain(operator, 'export function decodeOperatorOperation');
mustContain(operator, 'invalidContract([');
mustContain(operator, 'operator_v2_contract_invalid');
mustContain(operator, 'row.execution_permission !== row.allowed');
mustContain(operator, 'safety_flag_enabled_or_missing');
mustContain(operator, 'action_set_invalid');
mustContain(operator, 'Promise.allSettled');
mustContain(operator, 'operator_v2_contract_unavailable');
mustContain(operator, 'applyOperatorAttemptOverlays');
mustContain(operator, 'markAttemptFailure');
mustContain(operator, 'operationRejectedAction');
mustContain(operator, 'awaitingFreshContractActions');
mustContain(operator, 'acknowledgeNewOperation');
mustContain(operator, 'buildOperatorAcknowledgementPayload');
mustContain(operator, 'resolveOperatorAcknowledgementAction');
mustContain(operator, 'decodeStartAttempt');
mustContain(operator, 'effective_policy_digest');
mustContain(operator, 'operator_terminal_acknowledgement_failed');
mustContain(operator, 'clearIdempotencyKey');
mustContain(operator, 'clearActionCache');
mustContain(operator, 'reconcileAuthoritativeContract');
mustContain(operator, 'shouldReleaseAuthoritativeActionCache');
mustContain(operator, 'actionsToReleaseForAuthoritativeContract');
mustContain(operator, 'shouldReleaseAcknowledgedOperation');
mustContain(operator, 'claimActionBusy');
mustContain(operator, 'releaseActionBusy');
mustContain(operator, 'busyActionsRef');
mustContain(operator, 'isActionBusy');
for (const action of actions) mustContain(operator, `'${action}'`);

// Controller safety contract: V2 routes, durable per-action idempotency,
// replay-by-GET and no second POST for a known operation.
mustContain(operator, "'/api/research/btc/demo-paper/operator-v2/contract'");
mustContain(operator, "'/api/research/btc/demo-paper/operator-v2/operations'");
mustContain(operator, "`${OPERATOR_OPERATION_PATH}/${encodeURIComponent(known.operation_id)}/acknowledge`");
mustContain(operator, "'/api/research/btc/demo-paper/operator-v2/actions'");
mustContain(operator, 'Idempotency-Key');
mustContain(operator, 'expected_runtime_identity: contract.runtime_identity');
mustContain(operator, 'expected_state_revision: contract.state_revision');
mustContain(operator, 'expected_state_digest: contract.state_digest');
mustContain(operator, 'actionOperations.current.get(action)');
mustContain(operator, 'refreshKnownOperation');
mustContain(operator, 'isPendingState');
mustContain(operator, '仅 GET/replay，未重复提交');
mustContain(operator, '未重试 POST');
mustContain(operator, '操作已被后端拒绝');
mustContain(operator, '操作结果无法确认');
mustContain(operator, 'isTerminalOperationState');
mustContain(operator, 'canAcknowledgeNewOperation');
mustContain(operator, 'export function canAcknowledgeOperatorOperation');
mustMatch(
  operator,
  /canAcknowledgeOperatorOperation\(\s*known,\s*attempt\?\.disposition\s*\?\?\s*null,\s*operationReadFailures\.current\.has\(action\),\s*\)/,
);
assert.equal(operator.includes("'/api/research/btc/demo-paper/start'"), false, 'v1 start route must not be used by controller');

// Actual split: the workspace composes a controller; it no longer owns Demo
// runtime action dispatch or status polling.
mustContain(workspace, 'useDemoOperatorV2');
mustContain(workspace, 'operatorController={demoOperator}');
assert.equal(workspace.includes("'/api/research/btc/demo-paper/start'"), false, 'workspace must not own v1 start orchestration');
assert.equal(workspace.includes('const runDemoAction'), false, 'workspace must not own Demo action orchestration');

// HTTP decoding is strict: only the exact structured 4xx envelope may be
// definitive; a transport/5xx path must leave the attempt ambiguous.
mustContain(apiSource, "schema_version: 'btc_demo_operator_error_v2'");
mustContain(apiSource, 'decodeBtcDemoOperatorError');
mustContain(apiSource, 'response.status !== 408');
mustContain(apiSource, 'response.status < 500');

// UI safety: all eight server-authorized actions are present, with accessible
// blocker association, live status, visible stopped emergency, and dialogs.
mustContain(consoleSource, 'operatorController: DemoOperatorController');
mustContain(consoleSource, 'data-testid="btc-demo-operator-v2-actions"');
mustContain(consoleSource, 'btc-demo-action-help-');
mustContain(consoleSource, 'operatorController.isActionBusy(');
mustContain(consoleSource, 'aria-labelledby="btc-demo-flatten-title"');
mustContain(consoleSource, 'aria-labelledby="btc-demo-emergency-title"');
mustContain(consoleSource, '危险：');
mustContain(consoleSource, 'aria-live="polite"');
mustContain(consoleSource, '<dialog');
mustContain(consoleSource, 'data-testid="btc-demo-emergency-reduce-only-exit"');
mustContain(consoleSource, 'data-testid="btc-demo-emergency-confirm"');
mustContain(consoleSource, 'data-testid="btc-demo-start-attempt-binding"');
mustContain(consoleSource, 'actual long / short');
mustContain(consoleSource, 'startAttempt?.risk_profile');
for (const action of actions) mustContain(consoleSource, `'${action}'`);
assert.equal(consoleSource.includes('operatorControl.allowed_actions'), false, 'V2 buttons must not read v1 permissions');
assert.equal(consoleSource.includes('Boolean(busyAction)'), false, 'protective actions must not use global busy disabling');
assert.equal(consoleSource.includes('busyAction'), false, 'UI must use per-action isActionBusy only');
assert.equal(consoleSource.includes('{!isActive ?'), false, 'start confirmation must not be hidden by raw runtime.active');
assert.equal(consoleSource.includes('0.01 张'), false, 'limits must come from server projection');
assert.equal(consoleSource.includes('10 USDT'), false, 'notional limit must come from server projection');

// Execute the pure decoders from the real TypeScript source. This deliberately
// avoids React, HTTP, and browser state: it is a controller/contract test that
// exercises fail-closed identity and operation semantics in the producer tree.
const require = createRequire(import.meta.url);
const typeScriptCandidates = [
  path.join(root, 'node_modules/typescript/lib/typescript.js'),
  path.resolve(root, '..', '..', '..', 'agent-', 'frontend/node_modules/typescript/lib/typescript.js'),
];
const typeScriptPath = typeScriptCandidates.find((candidate) => fs.existsSync(candidate));
assert.ok(typeScriptPath, 'TypeScript runtime is required for executable decoder tests');
const ts = require(typeScriptPath);
const transpiled = ts.transpileModule(operator, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true},
}).outputText;
const module = {exports: {}};
const reactStub = {
  useEffect: () => undefined,
  useMemo: (factory) => factory(),
  useRef: (value) => ({current: value}),
  useState: (value) => [value, () => undefined],
};
class StubApiError extends Error { constructor(status, message, operatorError = null) { super(message); this.status = status; this.operatorError = operatorError; } }
let runtimeGet = async () => { throw new Error('api stub'); };
let runtimePost = async () => { throw new Error('api stub'); };
const apiStub = {
  ApiError: StubApiError,
  apiGet: (...args) => runtimeGet(...args),
  apiPost: (...args) => runtimePost(...args),
};
const attemptSource = read('src/workspaces/crypto/operator-attempt-state.ts');
const attemptTranspiled = ts.transpileModule(attemptSource, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true},
}).outputText;
const attemptModule = {exports: {}};
const attemptRequire = (request) => request === '../../lib/api' ? apiStub : (() => { throw new Error(`unexpected attempt require ${request}`); })();
new Function('exports', 'require', 'module', '__filename', '__dirname', attemptTranspiled)(attemptModule.exports, attemptRequire, attemptModule, path.join(root, 'src/workspaces/crypto/operator-attempt-state.ts'), root);
const localRequire = (request) => request === 'react' ? reactStub : request === '../../lib/api' ? apiStub : request === './operator-attempt-state' ? attemptModule.exports : (() => { throw new Error(`unexpected require ${request}`); })();
new Function('exports', 'require', 'module', '__filename', '__dirname', transpiled)(module.exports, localRequire, module, path.join(root, 'src/workspaces/crypto/demo-operator-v2.ts'), root);
const decodedApi = module.exports;
const digest = 'a'.repeat(64);
const sourceHead = 'b'.repeat(40);
const asOf = '2026-08-22T00:00:00Z';
const contractFixture = {
  schema_version: 'btc_demo_operator_contract_v2',
  source: 'btc_demo_runtime',
  runtime_identity: 'runtime-test-1',
  source_head: sourceHead,
  state_revision: 7,
  state_digest: digest,
  as_of_utc: asOf,
  safety_flags: {promotion_eligible: false, paper: false, live: false, private: false, order: false, real_order: false, transfer: false, withdraw: false},
  actions: actions.map((action) => ({
    action,
    allowed: true,
    execution_permission: true,
    blocker_codes: [],
    reason_codes: ['authorized'],
    source: 'btc_demo_runtime',
    runtime_identity: 'runtime-test-1',
    state_revision: 7,
    state_digest: digest,
    as_of_utc: asOf,
  })),
  operation: null,
};
const valid = decodedApi.decodeOperatorContract(contractFixture);
assert.equal(valid.valid, true, 'valid identity-bound contract must decode');
assert.deepEqual(valid.actions.map((row) => row.allowed), actions.map(() => true));
const revoked = decodedApi.revokeOperatorContract('operator_v2_contract_unavailable');
assert.equal(revoked.valid, false, 'contract poll failure must revoke prior authorization');
assert.deepEqual(revoked.actions.map((row) => row.allowed), actions.map(() => false));
for (const field of ['source', 'runtime_identity', 'state_revision', 'state_digest', 'as_of_utc']) {
  const tampered = structuredClone(contractFixture);
  const value = field === 'state_revision' ? 8 : field === 'state_digest' ? 'c'.repeat(64) : field === 'source_head' ? 'd'.repeat(40) : 'tampered';
  tampered.actions[2][field] = value;
  assert.equal(decodedApi.decodeOperatorContract(tampered).valid, false, `row ${field} mismatch must fail closed`);
}
const invalidCodes = structuredClone(contractFixture);
invalidCodes.blockers = ['NOT-A-STABLE-CODE'];
assert.equal(decodedApi.decodeOperatorContract(invalidCodes).valid, false, 'invalid top-level blocker must fail closed');
assert.equal(operationSchema.$id, 'https://quantstation.local/schemas/btc_demo_operator_operation_v2.schema.json');
const operationFixture = backendOperationFixtures.failed_refresh;
const boundStartFixture = backendOperationFixtures.bound_start;
assert.equal(decodedApi.decodeOperatorOperation(operationFixture)?.action, 'refresh_account_snapshot', 'the real Python serializer fixture must decode');
assert.equal(decodedApi.decodeOperatorOperation(boundStartFixture)?.start_attempt?.risk_profile, 'stress_3x', 'a start operation requires a complete bound attempt');
assert.equal(decodedApi.decodeOperatorContract({...contractFixture, operation: operationFixture}).valid, true, 'a failed refresh terminal must not revoke the entire V2 contract');
assert.equal(decodedApi.decodeOperatorOperation({...operationFixture, start_attempt: {}}), null, 'an empty start_attempt object remains invalid');
for (const field of ['result_present', 'retryable', 'replayed', 'idempotent_replay', 'acknowledged', 'acknowledged_at_utc']) {
  const missing = structuredClone(operationFixture);
  delete missing[field];
  assert.equal(decodedApi.decodeOperatorOperation(missing), null, `missing ${field} must fail closed`);
}
assert.deepEqual(
  decodedApi.buildOperatorAcknowledgementPayload(operationFixture),
  {action: 'refresh_account_snapshot', expected_state_revision: 3},
  'backend acknowledgement must fence the exact terminal operation revision',
);
assert.equal(
  decodedApi.resolveOperatorAcknowledgementAction(null, '', actions[0]),
  actions[0],
  'a definitive backend rejection must not be hidden by an empty unknown-action sentinel',
);
assert.equal(
  decodedApi.resolveOperatorAcknowledgementAction({action: actions[1]}, actions[0], actions[2]),
  actions[1],
  'a durable operation remains the acknowledgement authority',
);
const acknowledgedOperation = {...operationFixture, acknowledged: true, acknowledged_at_utc: asOf, state_revision: 4};
assert.equal(decodedApi.decodeOperatorOperation(acknowledgedOperation)?.acknowledged, true);

// Failure-first executable regression: exercise the real hook handler with a
// durable terminal operation loaded from the authoritative contract. The old
// handler incorrectly delegated only to canAcknowledgeOperatorAttempt, which
// rejected this known terminal state and therefore issued no acknowledgement
// POST despite the UI exposing the terminal acknowledgement capability.
const originalWindow = globalThis.window;
const localStorageValues = new Map();
globalThis.window = {
  localStorage: {
    getItem: (key) => localStorageValues.get(key) ?? null,
    setItem: (key, value) => localStorageValues.set(key, String(value)),
    removeItem: (key) => localStorageValues.delete(key),
  },
  crypto: {randomUUID: () => 'operator-test-idempotency'},
  setInterval: () => 1,
  clearInterval: () => undefined,
};
const postedAcknowledgements = [];
let contractReads = 0;
runtimeGet = async (requestPath) => {
  if (requestPath.endsWith('/contract')) {
    contractReads += 1;
    return {...contractFixture, operation: contractReads === 1 ? operationFixture : null};
  }
  if (requestPath.endsWith('/catalog')) return {};
  if (requestPath.endsWith('/status')) return {};
  if (requestPath.includes('/klines')) return {};
  throw new Error(`unexpected GET ${requestPath}`);
};
runtimePost = async (requestPath, payload) => {
  postedAcknowledgements.push({requestPath, payload});
  return acknowledgedOperation;
};
const handlerController = decodedApi.useDemoOperatorV2();
await handlerController.refresh();
const handlerAcknowledged = await handlerController.acknowledgeNewOperation(operationFixture.action);
assert.equal(handlerAcknowledged, true, 'durable terminal operation must be acknowledged by the real handler');
assert.equal(postedAcknowledgements.length, 1, 'terminal acknowledgement must issue exactly one POST');
assert.equal(
  postedAcknowledgements[0].requestPath,
  `/api/research/btc/demo-paper/operator-v2/operations/${operationFixture.operation_id}/acknowledge`,
);
assert.deepEqual(
  postedAcknowledgements[0].payload,
  {action: operationFixture.action, expected_state_revision: operationFixture.state_revision},
  'terminal acknowledgement must retain the operation/action/state-revision fence',
);
if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow;

for (const state of ['succeeded', 'failed', 'blocked', 'interrupted', 'timed_out', 'cancelled']) {
  assert.equal(
    decodedApi.canAcknowledgeOperatorOperation({state}, null),
    true,
    `durable ${state} terminal operation must be handler-acknowledgeable`,
  );
}
for (const state of ['queued', 'running']) {
  assert.equal(
    decodedApi.canAcknowledgeOperatorOperation({state}, null),
    false,
    `${state} operation must remain pending and unacknowledgeable`,
  );
}
assert.equal(
  decodedApi.canAcknowledgeOperatorOperation(operationFixture, null, true),
  false,
  'known operation read failure must remain fail-closed',
);
assert.equal(
  decodedApi.canAcknowledgeOperatorOperation(null, 'definitive_rejected'),
  true,
  'definitive rejection without a durable operation keeps manual acknowledgement semantics',
);
assert.equal(
  decodedApi.canAcknowledgeOperatorOperation(null, 'ambiguous_unknown'),
  true,
  'ambiguous unknown without a durable operation keeps manual acknowledgement semantics',
);

assert.equal(decodedApi.canAcknowledgeNewOperation(null, false), false);
assert.equal(decodedApi.canAcknowledgeNewOperation(null, true), true, 'unknown attempt requires explicit acknowledgement');
assert.equal(decodedApi.canAcknowledgeNewOperation({state: 'running'}, false), false, 'pending operation cannot reset');
assert.equal(decodedApi.canAcknowledgeNewOperation({state: 'succeeded'}, false), true, 'terminal operation can reset explicitly');

// Cross-tab acknowledgement recovery: a fresh authoritative contract with no
// durable operation releases only terminal/read-failure residue. Pending or
// ambiguous state remains fail-closed, and invalid/unavailable contracts never
// authorize cache cleanup.
const validEmptyContract = {valid: true, operation: null};
const invalidEmptyContract = {valid: false, operation: null};
const terminalCache = {
  operation: operationFixture,
  readFailure: true,
  overlayDisposition: 'read_failure',
};
assert.equal(
  decodedApi.shouldReleaseAuthoritativeActionCache(validEmptyContract, terminalCache),
  true,
  'authoritative operation=null must release terminal/read-failure residue',
);
assert.equal(
  decodedApi.shouldReleaseAuthoritativeActionCache(invalidEmptyContract, terminalCache),
  false,
  'invalid contract must not clear terminal cache or idempotency key',
);
assert.equal(
  decodedApi.shouldReleaseAuthoritativeActionCache(validEmptyContract, {
    operation: {...operationFixture, state: 'running'},
    readFailure: true,
    overlayDisposition: 'read_failure',
  }),
  false,
  'queued/running cached operation remains fail-closed when projection is absent',
);
assert.equal(
  decodedApi.shouldReleaseAuthoritativeActionCache(validEmptyContract, {
    operation: null,
    readFailure: false,
    overlayDisposition: 'ambiguous_unknown',
  }),
  false,
  'ambiguous unknown result must not be cleared by an absent projection',
);
assert.equal(
  decodedApi.shouldReleaseAuthoritativeActionCache(
    {...validEmptyContract, operation: {...operationFixture, state: 'running'}},
    terminalCache,
  ),
  false,
  'an authoritative unacknowledged operation must preserve other unresolved cache state',
);
assert.deepEqual(
  decodedApi.actionsToReleaseForAuthoritativeContract(validEmptyContract, new Map([
    [actions[0], terminalCache],
    [actions[1], {operation: {...operationFixture, state: 'running'}, readFailure: true, overlayDisposition: 'read_failure'}],
    [actions[2], {operation: null, readFailure: false, overlayDisposition: 'ambiguous_unknown'}],
  ])),
  [actions[0]],
  'only the terminal action cache is releasable; pending and ambiguous actions remain protected',
);
assert.deepEqual(
  decodedApi.actionsToReleaseForAuthoritativeContract(invalidEmptyContract, new Map([[actions[0], terminalCache]])),
  [],
  'invalid contract never authorizes cache cleanup',
);
assert.equal(
  decodedApi.shouldReleaseAcknowledgedOperation(validEmptyContract, {...operationFixture, acknowledged: true}),
  true,
  'acknowledged terminal GET replay must release stale cache before a fresh fenced POST',
);
assert.equal(
  decodedApi.shouldReleaseAcknowledgedOperation(validEmptyContract, operationFixture),
  false,
  'unacknowledged terminal replay remains durable and must not be cleared',
);

const operatorError = {
  schema_version: 'btc_demo_operator_error_v2', error_code: 'operator_action_failed', allowed: false, execution_permission: false,
  blocker_codes: ['operator_action_failed'], reason_codes: ['authoritative_preflight_rejected'],
  safety_flags: {promotion_eligible: false, paper: false, live: false, private: false, order: false, real_order: false, transfer: false, withdraw: false},
};
assert.equal(attemptModule.exports.classifyOperatorAttemptError(new StubApiError(400, 'HTTP 400', operatorError)).disposition, 'definitive_rejected');
assert.equal(attemptModule.exports.classifyOperatorAttemptError(new StubApiError(408, 'timeout')).disposition, 'ambiguous_unknown');
assert.equal(attemptModule.exports.classifyOperatorAttemptError(new StubApiError(500, 'HTTP 500', operatorError)).disposition, 'ambiguous_unknown');

// Immediate ref-backed single-flight semantics: unrelated actions may overlap,
// while the same action can only be claimed once and releases only itself.
const startAction = 'authoritative_preflight_start';
const emergencyAction = 'emergency_reduce_only_exit';
const startBusy = decodedApi.claimActionBusy(new Set(), startAction);
assert.ok(startBusy?.has(startAction));
const bothBusy = decodedApi.claimActionBusy(startBusy, emergencyAction);
assert.ok(bothBusy?.has(startAction) && bothBusy.has(emergencyAction), 'start and emergency may be concurrent');
assert.equal(decodedApi.claimActionBusy(bothBusy, startAction), null, 'same action second claim must fail');
const afterStart = decodedApi.releaseActionBusy(bothBusy, startAction);
assert.equal(afterStart.has(startAction), false, 'completed start is released');
assert.equal(afterStart.has(emergencyAction), true, 'releasing start must preserve emergency busy');

console.log(JSON.stringify({
  ok: true,
  actions: actions.length,
  contract: 'btc_demo_operator_contract_v2',
  read_model: 'btc_demo_operation_read_model_v2',
  handler_harness: {executed: true, fenced_ack_posts: postedAcknowledgements.length, payload_asserted: true},
}));
