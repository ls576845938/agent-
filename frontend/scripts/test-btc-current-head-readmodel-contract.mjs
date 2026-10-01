import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';


const workspaceSource = await readFile(
  new URL('../src/workspaces/CryptoWorkspace.tsx', import.meta.url),
  'utf8',
);
const fixtureSource = await readFile(
  new URL('../e2e/btc-trading-fixtures.ts', import.meta.url),
  'utf8',
);

const contractNames = [
  'BTC_LEGACY_REQUIRED_BLOCKERS',
  'BTC_QUALITY_L2_REQUIRED_BLOCKERS',
  'BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS',
];

function extractArray(source, name) {
  const match = source.match(new RegExp(`const ${name} = \\[([\\s\\S]*?)\\] as const;`));
  assert.ok(match, `${name} array must exist`);
  return [...match[1].matchAll(/'([^']+)'/g)].map((item) => item[1]);
}

function extractContractHash(source, name) {
  const match = source.match(new RegExp(
    `requiredBlockers: ${name},\\s*sha256: '([0-9a-f]{64})'`,
  ));
  assert.ok(match, `${name} exact hash contract must exist`);
  return match[1];
}

function stablePayloadHash(payload) {
  return createHash('sha256').update(JSON.stringify(payload)).digest('hex');
}

for (const name of contractNames) {
  const workspaceBlockers = extractArray(workspaceSource, name);
  const fixtureBlockers = extractArray(fixtureSource, name);
  const workspaceHash = extractContractHash(workspaceSource, name);
  const fixtureHash = extractContractHash(fixtureSource, name);

  assert.deepEqual(fixtureBlockers, workspaceBlockers, `${name} fixture order drift`);
  assert.equal(fixtureHash, workspaceHash, `${name} fixture hash drift`);
}

const currentHeadBlockers = extractArray(
  workspaceSource,
  'BTC_CURRENT_HEAD_REBUILD_REQUIRED_BLOCKERS',
);
assert.equal(currentHeadBlockers.length, 10);
assert.equal(
  stablePayloadHash(currentHeadBlockers),
  'cc0d8cbd8ff93afeab933d1b87bed493f667177aa1c9b1fdbe38a42a07ec65fa',
);

for (const predicateFragment of [
  'domainReadModel.required_blockers_sha256 === contract.sha256',
  'domainReadModel.required_blocker_count === contract.requiredBlockers.length',
  'domainReadModel.required_blockers.length === contract.requiredBlockers.length',
  'domainReadModel.required_blockers[index] === blocker',
  'domainReadModel.blocker_count === domainReadModel.blockers.length',
  'domainReadModel.required_blockers_preserved === true',
  'domainReadModel.safety?.[key] === false',
  "domainReadModel.status === 'blocked'",
  "domainReadModel.freshness === 'current_head'",
  "domainReadModel.decision === 'blocked_fail_closed_no_paper_no_live'",
  "domainReadModel.gate_decision === 'blocked_fail_closed_no_paper_no_live'",
  'domainReadModel.promotion_evidence_ready === false',
  'domainReadModel.paper_ready === false',
  'domainReadModel.live_ready === false',
  'domainReadModel.source_head === frontendIdentity.source_head',
]) {
  assert.ok(
    workspaceSource.includes(predicateFragment),
    `fail-closed predicate drift: ${predicateFragment}`,
  );
}

console.log('BTC current-head read-model exact contracts: PASS');
