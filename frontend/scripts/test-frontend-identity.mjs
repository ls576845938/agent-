import assert from 'node:assert/strict';
import {execFileSync, spawnSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

import {
  assertCanonicalServe,
  buildTrackedInventoryObjectId,
  CANONICAL_ROUTES,
  computeFrontendFingerprint,
  evaluateFrontendRuntimeBinding,
  FINGERPRINT_TARGETS,
  inspectFrontendIdentity,
  inspectFrontendIdentityAsync,
  latchFrontendRuntimeBinding,
  listFrontendDirtyPaths,
  parseWorktreeList,
} from './frontend-identity-lib.mjs';

const parsed = parseWorktreeList([
  'worktree D:/repo',
  'HEAD 1111111111111111111111111111111111111111',
  'branch refs/heads/main',
  '',
  'worktree D:/repo/worktrees/agent',
  'HEAD 2222222222222222222222222222222222222222',
  'branch refs/heads/agent/test',
  '',
].join('\n'));
assert.equal(parsed.length, 2);
assert.equal(parsed[0].branch, 'refs/heads/main');
assert.equal(parsed[1].worktree, 'D:/repo/worktrees/agent');

const objectIds = Object.fromEntries(
  Object.keys(FINGERPRINT_TARGETS).map((name, index) => [name, `${index + 1}`.padStart(40, '0')]),
);
const fingerprintA = computeFrontendFingerprint('release-a', objectIds);
const fingerprintB = computeFrontendFingerprint('release-a', objectIds);
assert.equal(fingerprintA, fingerprintB);
assert.match(fingerprintA, /^[0-9a-f]{64}$/);
assert.equal(CANONICAL_ROUTES.length, 7);
assert.equal(FINGERPRINT_TARGETS.frontend_runtime_inventory.path, 'frontend');
assert.deepEqual(
  FINGERPRINT_TARGETS.frontend_runtime_inventory.exclusions,
  ['frontend/public/frontend-identity.json'],
);

const canonicalInspection = {
  repo_root: 'D:/repo',
  branch: 'main',
  source_head: '1'.repeat(40),
  main_head: '1'.repeat(40),
  main_worktree: 'D:/repo',
  manifest: {
    baseline_commit: '0'.repeat(40),
    canonical_port: 3000,
  },
  manifest_match: true,
  baseline_ancestor: true,
  dirty_paths: [],
  canonical: true,
};
assert.equal(assertCanonicalServe(canonicalInspection, 3000), canonicalInspection);
assert.throws(
  () => assertCanonicalServe(canonicalInspection, 3100),
  /FRONTEND_CANONICAL_PORT_REQUIRED/,
);
assert.throws(
  () => assertCanonicalServe({
    ...canonicalInspection,
    repo_root: 'D:/repo/worktrees/old',
    branch: 'agent/old',
    source_head: '2'.repeat(40),
    canonical: false,
  }, 3000),
  /FRONTEND_CANONICAL_GUARD_FAILED/,
);

const liveBinding = evaluateFrontendRuntimeBinding(
  {
    ...canonicalInspection,
    fingerprint: fingerprintA,
    configured_fingerprint: fingerprintA,
    worktree: canonicalInspection.repo_root,
  },
  {
    ...canonicalInspection,
    fingerprint: fingerprintA,
  },
);
assert.equal(liveBinding.runtime_stale, false);
assert.equal(liveBinding.canonical, true);
assert.deepEqual(liveBinding.drift_reasons, []);

const advancedMainBinding = evaluateFrontendRuntimeBinding(
  {
    ...canonicalInspection,
    fingerprint: fingerprintA,
    configured_fingerprint: fingerprintA,
    worktree: canonicalInspection.repo_root,
  },
  {
    ...canonicalInspection,
    source_head: '2'.repeat(40),
    main_head: '2'.repeat(40),
    fingerprint: fingerprintA,
  },
);
assert.equal(advancedMainBinding.runtime_stale, true);
assert.equal(advancedMainBinding.canonical, false);
assert.deepEqual(advancedMainBinding.drift_reasons, ['main_head_changed']);

const dirtyBinding = evaluateFrontendRuntimeBinding(
  {
    ...canonicalInspection,
    fingerprint: fingerprintA,
    configured_fingerprint: fingerprintA,
    worktree: canonicalInspection.repo_root,
  },
  {
    ...canonicalInspection,
    canonical: false,
    fingerprint: fingerprintA,
    dirty_paths: [' M frontend/src/App.tsx'],
  },
);
assert.equal(dirtyBinding.runtime_stale, true);
assert.ok(dirtyBinding.drift_reasons.includes('current_main_not_canonical'));
assert.ok(dirtyBinding.drift_reasons.includes('frontend_worktree_dirty'));

const failedBinding = evaluateFrontendRuntimeBinding(
  {
    ...canonicalInspection,
    fingerprint: fingerprintA,
    configured_fingerprint: fingerprintA,
    worktree: canonicalInspection.repo_root,
  },
  null,
  new Error('synthetic'),
);
assert.equal(failedBinding.runtime_stale, true);
assert.deepEqual(
  failedBinding.drift_reasons,
  ['runtime_identity_check_failed', 'current_identity_unavailable'],
);

const latchedAt = new Date('2026-07-27T00:00:00Z');
const latchedDirty = latchFrontendRuntimeBinding(liveBinding, dirtyBinding, latchedAt);
assert.equal(latchedDirty.runtime_stale, true);
assert.equal(latchedDirty.stale_detected_at, '2026-07-27T00:00:00.000Z');
const attemptedRecovery = latchFrontendRuntimeBinding(latchedDirty, liveBinding);
assert.equal(attemptedRecovery.runtime_stale, true);
assert.equal(attemptedRecovery.canonical, false);
assert.ok(attemptedRecovery.drift_reasons.includes('frontend_worktree_dirty'));

const inventoryA = buildTrackedInventoryObjectId(
  process.cwd(),
  'HEAD',
  'frontend',
  ['frontend/public/frontend-identity.json'],
);
assert.match(inventoryA, /^[0-9a-f]{40}$/);
assert.equal(Array.isArray(listFrontendDirtyPaths(process.cwd())), true);

const inventoryRepo = mkdtempSync(join(tmpdir(), 'quant-frontend-inventory-'));
const inventoryGit = (...args) => execFileSync(
  'git',
  ['-C', inventoryRepo, ...args],
  {encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']},
).trim();
try {
  inventoryGit('init');
  inventoryGit('config', 'user.name', 'Quant Frontend Contract');
  inventoryGit('config', 'user.email', 'frontend-contract@example.invalid');
  mkdirSync(join(inventoryRepo, 'frontend', 'public'), {recursive: true});
  writeFileSync(join(inventoryRepo, 'frontend', 'index.html'), '<main>v1</main>\n');
  writeFileSync(join(inventoryRepo, 'frontend', 'public', 'favicon.svg'), '<svg>v1</svg>\n');
  writeFileSync(
    join(inventoryRepo, 'frontend', 'public', 'frontend-identity.json'),
    '{"excluded":"v1"}\n',
  );
  inventoryGit('add', '--', 'frontend');
  inventoryGit('commit', '-m', 'initial frontend');
  const initialInventory = buildTrackedInventoryObjectId(
    inventoryRepo,
    'HEAD',
    'frontend',
    ['frontend/public/frontend-identity.json'],
  );

  writeFileSync(join(inventoryRepo, 'frontend', 'index.html'), '<main>v2</main>\n');
  inventoryGit('add', '--', 'frontend/index.html');
  inventoryGit('commit', '-m', 'change index');
  const indexChangedInventory = buildTrackedInventoryObjectId(
    inventoryRepo,
    'HEAD',
    'frontend',
    ['frontend/public/frontend-identity.json'],
  );
  assert.notEqual(indexChangedInventory, initialInventory);

  writeFileSync(join(inventoryRepo, 'frontend', 'public', 'new.svg'), '<svg>new</svg>\n');
  inventoryGit('add', '--', 'frontend/public/new.svg');
  inventoryGit('commit', '-m', 'add public asset');
  const publicChangedInventory = buildTrackedInventoryObjectId(
    inventoryRepo,
    'HEAD',
    'frontend',
    ['frontend/public/frontend-identity.json'],
  );
  assert.notEqual(publicChangedInventory, indexChangedInventory);

  writeFileSync(join(inventoryRepo, 'frontend', 'public', 'new.svg'), '<svg>dirty</svg>\n');
  writeFileSync(join(inventoryRepo, 'frontend', 'public', 'untracked.svg'), '<svg>untracked</svg>\n');
  const inventoryDirtyPaths = listFrontendDirtyPaths(inventoryRepo);
  assert.ok(inventoryDirtyPaths.some(path => path.includes('frontend/public/new.svg')));
  assert.ok(inventoryDirtyPaths.some(path => path.includes('frontend/public/untracked.svg')));
} finally {
  rmSync(inventoryRepo, {recursive: true, force: true});
}

const inspection = inspectFrontendIdentity(process.cwd());
const asyncInspection = await inspectFrontendIdentityAsync(process.cwd());
for (const key of [
  'repo_root',
  'branch',
  'source_head',
  'main_head',
  'main_worktree',
  'fingerprint',
  'manifest_match',
  'baseline_ancestor',
  'canonical',
]) {
  assert.deepEqual(asyncInspection[key], inspection[key]);
}
assert.deepEqual(asyncInspection.object_ids, inspection.object_ids);
assert.deepEqual(asyncInspection.dirty_paths, inspection.dirty_paths);
assert.equal(inspection.manifest_match, true);
assert.equal(inspection.baseline_ancestor, true);
assert.equal(inspection.fingerprint, inspection.manifest.fingerprint);
assert.deepEqual(inspection.object_ids, inspection.manifest.object_ids);
if (inspection.branch !== 'main') assert.equal(inspection.canonical, false);

if (process.platform === 'win32') {
  const launcherPath = fileURLToPath(
    new URL('../../scripts/start_frontend_current_main.ps1', import.meta.url),
  );
  const launcherCheck = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-File', launcherPath, '-Check'],
    {encoding: 'utf8', windowsHide: true},
  );
  const launcherOutput = `${launcherCheck.stdout ?? ''}\n${launcherCheck.stderr ?? ''}`;
  assert.equal(launcherCheck.status, 0, launcherOutput);
  assert.match(launcherCheck.stdout, /canonical_main_worktree=.*量化系统.*agent-/u);
  assert.match(launcherCheck.stdout, /canonical_frontend=.*量化系统.*agent-.*frontend/u);
  assert.doesNotMatch(launcherOutput, /閲忓寲|绯荤粺/u);
}

console.log(JSON.stringify({
  status: 'passed',
  branch: inspection.branch,
  canonical: inspection.canonical,
  fingerprint: inspection.fingerprint,
  object_targets: Object.keys(inspection.object_ids).length,
}, null, 2));
