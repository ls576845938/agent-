import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const consoleSource = fs.readFileSync(new URL('../src/workspaces/crypto/DemoTradingConsole.tsx', import.meta.url), 'utf8');
assert.ok(!consoleSource.includes('recoveryAttempted && !isActive && message'),
  'accepted/running is not a failed preflight: failure must use authoritative operation state');
const sourcePath = fileURLToPath(new URL('../src/workspaces/crypto/demo-start-feedback.ts', import.meta.url));
const compiled = ts.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
}).outputText;
const module = {exports: {}};
new Function('exports', 'require', 'module', compiled)(module.exports, () => {throw new Error('Feedback must be side-effect free');}, module);
const {resolveStartFeedback} = module.exports;
const start = 'authoritative_preflight_start';
const operation = {action: start, state: 'running', phase: 'account_positions_orders_oco', blocker_codes: [], acknowledged: false};
const base = {operation, unknownAction: '', rejectedAction: '', busy: false, attempted: true,
  message: `${start} 已受理：running。`};

for (const state of ['queued', 'running']) {
  const result = resolveStartFeedback({...base, attempted: false, operation: {...operation, state}});
  assert.equal(result.kind, 'pending', `${state} must remain pending even after reload`);
  assert.match(result.detail, /核对账户、仓位和挂单/);
  assert.doesNotMatch(result.title, /失败/);
}
for (const state of ['blocked', 'failed', 'interrupted', 'timed_out']) {
  const result = resolveStartFeedback({...base, operation: {...operation, state, blocker_codes: ['actual_backend_blocker']}});
  assert.equal(result.kind, 'failed');
  if (state !== 'timed_out') assert.match(result.detail, /actual_backend_blocker/);
  assert.doesNotMatch(result.detail, /已受理/);
}
const leverage = resolveStartFeedback({...base, operation: {...operation, state: 'blocked',
  blocker_codes: ['okx_demo_paper_exact_isolated_1x_leverage_required']}});
assert.match(leverage.guidance, /逐仓/);
assert.match(leverage.guidance, /两侧.*1 倍/);
assert.match(leverage.guidance, /不能据此推断实际杠杆/);
const locked = resolveStartFeedback({...base, operation: {...operation, state: 'timed_out', phase: 'timed_out',
  blocker_codes: ['okx_demo_fault_drill_runtime_root_writer_lock_unavailable', 'okx_demo_startup_worker_thread_join_timed_out']}});
assert.match(locked.title, /运行目录被占用/);
assert.match(locked.guidance, /不要删除锁文件/);
const reconnectFailed = resolveStartFeedback({...base, operation: {...operation, state: 'blocked', phase: 'blocked',
  blocker_codes: ['okx_demo_private_ws_startup_reconnect_probe_failed']}});
assert.match(reconnectFailed.title, /账户实时连接核验失败/);
assert.match(reconnectFailed.guidance, /超时不能视为成功/);
assert.equal(resolveStartFeedback({...base, operation: {...operation, state: 'succeeded'}}).kind, 'succeeded');
assert.equal(resolveStartFeedback({...base, operation: {...operation, acknowledged: true}}), null);
assert.equal(resolveStartFeedback({...base, operation: null, unknownAction: start}).kind, 'unknown');
assert.equal(resolveStartFeedback({...base, operation: null, rejectedAction: start, message: '拒绝代码'}).kind, 'failed');
assert.equal(resolveStartFeedback({...base, operation: null, busy: true}).kind, 'pending');
assert.equal(resolveStartFeedback({...base, operation: {...operation, action: 'refresh_account_snapshot'}}), null);
assert.equal(resolveStartFeedback({...base, operation: null}), null, 'stale accepted message is not failure evidence');
assert.match(consoleSource, /resolveStartFeedback\(/);
assert.equal(module.exports.isStartReceiptMessage(base.message), true);
assert.equal(module.exports.isStartReceiptMessage(`${start} 已完成。`), true);
assert.equal(module.exports.isStartReceiptMessage('操作 authoritative_preflight_start 的后端终态确认失败'), false);
assert.equal(module.exports.isStartReceiptMessage('stop_strategy_keep_position 已受理：running。'), false);
assert.match(consoleSource, /!startFeedback \|\| !isStartReceiptMessage\(message\)/);
console.log('PASS: start feedback pending, terminal, leverage, reload, unknown, rejection and unrelated-action regressions');
