import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === './api' && context.parentURL?.endsWith('/ibkr-runtime-api.ts')) {
      return {
        shortCircuit: true,
        url: 'data:text/javascript,export async function apiGet(){throw new Error("not used by normalization regression")}',
      };
    }
    return nextResolve(specifier, context);
  },
});

const {
  isIbkrRuntimeBlocked,
  normalizeIbkrRuntimeStatus,
} = await import('../src/lib/ibkr-runtime-api.ts');

const normalize = (blockers) => normalizeIbkrRuntimeStatus({blockers});

const structured = normalize([
  {
    code: ' IBKR_RUNTIME_UNAVAILABLE ',
    message: ' Runtime provider is unavailable. ',
    severity: 'critical',
    blocks_new_orders: true,
  },
]);
assert.ok(structured);
assert.deepEqual(
  structured.blockers,
  ['IBKR_RUNTIME_UNAVAILABLE: Runtime provider is unavailable.'],
  'structured backend blockers must remain visible and auditable',
);

const strings = normalize(['  legacy blocker  ', 'legacy blocker', '', '   ']);
assert.ok(strings);
assert.deepEqual(strings.blockers, ['legacy blocker'], 'string blockers must be trimmed and deduplicated');

const mixed = normalize([
  null,
  17,
  {},
  {code: ' ', message: ' '},
  {code: 'STALE_TRUTH', message: 'Broker truth is stale'},
  {code: 'STALE_TRUTH', message: 'Broker truth is stale'},
]);
assert.ok(mixed);
assert.deepEqual(
  mixed.blockers,
  ['STALE_TRUTH: Broker truth is stale'],
  'malformed blockers must be discarded without duplicating valid records',
);

const unknown = normalizeIbkrRuntimeStatus({blockers: [{unexpected: 'payload'}]});
assert.ok(unknown);
assert.equal(unknown.block_new_orders, true, 'missing order permission must remain fail-closed');
assert.equal(isIbkrRuntimeBlocked(unknown), true, 'unknown runtime payload must remain blocked');

console.log('IBKR runtime blocker normalization regression: passed');
