import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const files = {
  workspace: new URL('../src/workspaces/CNEquityWorkspace.tsx', import.meta.url),
  contract: new URL('../src/workspaces/cn/domainReadModel.ts', import.meta.url),
  style: new URL('../src/workspaces/cn/cn-equity.css', import.meta.url),
  e2e: new URL('../e2e/cn-equity.spec.ts', import.meta.url),
  harness: new URL('../src/workspaces/cn/e2e-harness.tsx', import.meta.url),
};

const source = Object.fromEntries(
  Object.entries(files).map(([key, path]) => [key, readFileSync(path, 'utf8')]),
);
const combined = Object.values(source).join('\n');

assert.match(source.workspace, /A 股证据工作台/);
assert.match(source.workspace, /PAPER/);
assert.match(source.workspace, /LIVE/);
assert.match(source.workspace, /LOCKED/);
assert.match(source.workspace, /CN_LAYER_IDS\.map/);
assert.match(source.contract, /\/api\/research\/cn-equity\/domain-read-model/);
assert.match(source.contract, /method:\s*'GET'/);
assert.match(source.contract, /cache:\s*'no-store'/);
assert.match(source.contract, /BACKEND_UNAVAILABLE/);
assert.match(source.contract, /CONTRACT_INVALID/);
assert.doesNotMatch(combined, /method:\s*['"]POST['"]/);
assert.doesNotMatch(combined, /\bapiPost(?:Raw)?\b/);
assert.doesNotMatch(combined, /components\/platform/);
assert.doesNotMatch(combined, /shared-types/);

for (const layer of ['data', 'market_rules', 'backtest', 'oms', 'replay', 'qmt']) {
  assert.match(source.contract, new RegExp(`['"]${layer}['"]`));
}

for (const flag of [
  'broker_access_allowed',
  'live_allowed',
  'order_endpoint_allowed',
  'paper_allowed',
  'paper_queue_allowed',
  'private_endpoint_allowed',
  'promotion_allowed',
  'qmt_sdk_allowed',
  'real_order_allowed',
  'withdraw_allowed',
  'demo_allowed',
  'network_allowed',
  'secret_access_allowed',
]) {
  assert.match(combined, new RegExp(flag));
}

assert.match(source.e2e, /BACKEND_UNAVAILABLE · FAIL-CLOSED/);
assert.match(source.e2e, /toHaveCount\(13\)/);
assert.match(source.harness, /CNEquityWorkspace/);
assert.match(source.style, /\.cn-equity-workspace/);

console.log('CN operations workspace smoke passed');
