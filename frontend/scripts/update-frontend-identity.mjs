import {writeFileSync} from 'node:fs';
import {resolve} from 'node:path';

import {
  buildObjectIds,
  CANONICAL_BRANCH,
  CANONICAL_PORT,
  CANONICAL_ROUTES,
  computeFrontendFingerprint,
  FRONTEND_IDENTITY_SCHEMA,
  FRONTEND_MANIFEST_PATH,
  readFrontendManifest,
  resolveRepoRoot,
} from './frontend-identity-lib.mjs';
import {execFileSync} from 'node:child_process';

const repoRoot = resolveRepoRoot(process.cwd());
const manifest = readFrontendManifest(repoRoot, {allowTargetMigration: true});
const baselineCommit = execFileSync('git', ['-C', repoRoot, 'rev-parse', 'HEAD'], {
  encoding: 'utf8',
  windowsHide: true,
}).trim();
const objectIds = buildObjectIds(repoRoot, baselineCommit);
const fingerprint = computeFrontendFingerprint(manifest.release_id, objectIds);

const next = {
  schema_version: FRONTEND_IDENTITY_SCHEMA,
  release_id: manifest.release_id,
  canonical_branch: CANONICAL_BRANCH,
  canonical_port: CANONICAL_PORT,
  baseline_commit: baselineCommit,
  frontend_generation: manifest.frontend_generation,
  routes: CANONICAL_ROUTES,
  object_ids: objectIds,
  fingerprint,
  safety: manifest.safety,
};

writeFileSync(resolve(repoRoot, FRONTEND_MANIFEST_PATH), `${JSON.stringify(next, null, 2)}\n`, 'utf8');
console.log(JSON.stringify({
  status: 'updated',
  path: FRONTEND_MANIFEST_PATH,
  baseline_commit: baselineCommit,
  fingerprint,
  object_ids: objectIds,
}, null, 2));
