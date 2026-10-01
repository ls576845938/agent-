import {execFile, execFileSync, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';

export const FRONTEND_IDENTITY_SCHEMA = 'quant_frontend_identity_v1';
export const FRONTEND_RUNTIME_IDENTITY_SCHEMA = 'quant_frontend_runtime_identity_v1';
export const FRONTEND_MANIFEST_PATH = 'frontend/public/frontend-identity.json';
export const CANONICAL_BRANCH = 'main';
export const CANONICAL_PORT = 3000;
export const CANONICAL_ROUTES = Object.freeze([
  '/',
  '/cn-equity',
  '/research',
  '/portfolio',
  '/crypto',
  '/live',
  '/strategies',
]);
export const FINGERPRINT_TARGETS = Object.freeze({
  frontend_runtime_inventory: {
    path: 'frontend',
    kind: 'inventory',
    exclusions: [FRONTEND_MANIFEST_PATH],
  },
  frontend_src_tree: {path: 'frontend/src', kind: 'tree'},
  powershell_launcher_blob: {path: 'scripts/start_frontend_current_main.ps1', kind: 'blob'},
  cmd_launcher_blob: {path: 'start-frontend.cmd', kind: 'blob'},
});
export const FRONTEND_DIRTY_SCOPES = Object.freeze([
  'frontend',
  'scripts/start_frontend_current_main.ps1',
  'start-frontend.cmd',
]);

function runGit(repoRoot, args, options = {}) {
  try {
    return execFileSync('git', ['-C', repoRoot, ...args], {
      encoding: 'utf8',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...options,
    }).trim();
  } catch (error) {
    const stderr = String(error?.stderr ?? error?.message ?? error).trim();
    throw new Error(`FRONTEND_IDENTITY_GIT_FAILED git ${args.join(' ')}: ${stderr}`);
  }
}

function runGitAsync(repoRoot, args, {encoding = 'utf8'} = {}) {
  return new Promise((resolvePromise, reject) => {
    execFile(
      'git',
      ['-C', repoRoot, ...args],
      {
        encoding,
        windowsHide: true,
        maxBuffer: 16 * 1024 * 1024,
      },
      (error, stdout, stderr) => {
        if (error) {
          const detail = String(stderr ?? error.message ?? error).trim();
          reject(new Error(`FRONTEND_IDENTITY_GIT_FAILED git ${args.join(' ')}: ${detail}`));
          return;
        }
        resolvePromise(encoding === 'buffer' ? stdout : String(stdout).trim());
      },
    );
  });
}

function normalizePath(value) {
  const normalized = resolve(value).replaceAll('\\', '/').replace(/\/+$/, '');
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

export function resolveRepoRoot(startPath = process.cwd()) {
  return runGit(startPath, ['rev-parse', '--show-toplevel']);
}

export function resolveRepoRootAsync(startPath = process.cwd()) {
  return runGitAsync(startPath, ['rev-parse', '--show-toplevel']);
}

export function parseWorktreeList(text) {
  const records = [];
  let current = {};
  const flush = () => {
    if (current.worktree) records.push(current);
    current = {};
  };
  for (const line of `${text}\n`.split(/\r?\n/)) {
    if (!line) {
      flush();
      continue;
    }
    const separator = line.indexOf(' ');
    const key = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? true : line.slice(separator + 1);
    current[key] = value;
  }
  return records;
}

export function resolveMainWorktree(repoRoot) {
  const records = parseWorktreeList(runGit(repoRoot, ['worktree', 'list', '--porcelain']));
  return resolveMainWorktreeFromRecords(records);
}

function resolveMainWorktreeFromRecords(records) {
  const main = records.find(record => record.branch === 'refs/heads/main');
  if (!main?.worktree) {
    throw new Error('FRONTEND_MAIN_WORKTREE_MISSING refs/heads/main has no registered worktree');
  }
  return main.worktree;
}

export function readFrontendManifest(repoRoot, {allowTargetMigration = false} = {}) {
  const path = resolve(repoRoot, FRONTEND_MANIFEST_PATH);
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    throw new Error(`FRONTEND_IDENTITY_MANIFEST_INVALID ${path}: ${error.message}`);
  }
  validateManifest(manifest, {allowTargetMigration});
  return manifest;
}

export function validateManifest(manifest, {allowTargetMigration = false} = {}) {
  if (manifest?.schema_version !== FRONTEND_IDENTITY_SCHEMA) {
    throw new Error(`FRONTEND_IDENTITY_SCHEMA_INVALID expected=${FRONTEND_IDENTITY_SCHEMA}`);
  }
  if (manifest.canonical_branch !== CANONICAL_BRANCH || manifest.canonical_port !== CANONICAL_PORT) {
    throw new Error('FRONTEND_IDENTITY_CANONICAL_TARGET_INVALID');
  }
  if (!/^[0-9a-f]{40}$/.test(manifest.baseline_commit ?? '')) {
    throw new Error('FRONTEND_IDENTITY_BASELINE_INVALID');
  }
  if (!/^[0-9a-f]{64}$/.test(manifest.fingerprint ?? '')) {
    throw new Error('FRONTEND_IDENTITY_FINGERPRINT_INVALID');
  }
  const expectedKeys = Object.keys(FINGERPRINT_TARGETS);
  const actualKeys = Object.keys(manifest.object_ids ?? {});
  if (!allowTargetMigration && JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) {
    throw new Error(`FRONTEND_IDENTITY_TARGETS_INVALID expected=${expectedKeys.join(',')}`);
  }
  for (const [name, objectId] of Object.entries(manifest.object_ids)) {
    if (!/^[0-9a-f]{40}$/.test(objectId)) {
      throw new Error(`FRONTEND_IDENTITY_OBJECT_INVALID ${name}`);
    }
  }
  if (JSON.stringify(manifest.routes) !== JSON.stringify(CANONICAL_ROUTES)) {
    throw new Error('FRONTEND_IDENTITY_ROUTES_INVALID');
  }
}

export function buildObjectIds(repoRoot, ref = 'HEAD') {
  return Object.fromEntries(
    Object.entries(FINGERPRINT_TARGETS).map(([name, target]) => [
      name,
      target.kind === 'inventory'
        ? buildTrackedInventoryObjectId(repoRoot, ref, target.path, target.exclusions)
        : runGit(repoRoot, ['rev-parse', `${ref}:${target.path}`]),
    ]),
  );
}

export async function buildObjectIdsAsync(repoRoot, ref = 'HEAD') {
  const entries = await Promise.all(
    Object.entries(FINGERPRINT_TARGETS).map(async ([name, target]) => [
      name,
      target.kind === 'inventory'
        ? await buildTrackedInventoryObjectIdAsync(
          repoRoot,
          ref,
          target.path,
          target.exclusions,
        )
        : await runGitAsync(repoRoot, ['rev-parse', `${ref}:${target.path}`]),
    ]),
  );
  return Object.fromEntries(entries);
}

export function buildTrackedInventoryObjectId(
  repoRoot,
  ref,
  path,
  exclusions = [],
) {
  let output;
  try {
    output = execFileSync(
      'git',
      ['-C', repoRoot, 'ls-tree', '-r', '-z', '--full-tree', ref, '--', path],
      {
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
  } catch (error) {
    const stderr = String(error?.stderr ?? error?.message ?? error).trim();
    throw new Error(`FRONTEND_IDENTITY_GIT_FAILED git ls-tree ${ref} ${path}: ${stderr}`);
  }
  const excluded = new Set(exclusions.map(item => item.replaceAll('\\', '/')));
  const entries = output
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .filter(entry => {
      const separator = entry.indexOf('\t');
      const entryPath = separator >= 0 ? entry.slice(separator + 1) : '';
      return !excluded.has(entryPath);
    });
  if (entries.length === 0) {
    throw new Error(`FRONTEND_IDENTITY_INVENTORY_EMPTY ${path}`);
  }
  return createHash('sha1').update(entries.join('\0')).digest('hex');
}

export async function buildTrackedInventoryObjectIdAsync(
  repoRoot,
  ref,
  path,
  exclusions = [],
) {
  const output = await runGitAsync(
    repoRoot,
    ['ls-tree', '-r', '-z', '--full-tree', ref, '--', path],
    {encoding: 'buffer'},
  );
  const excluded = new Set(exclusions.map(item => item.replaceAll('\\', '/')));
  const entries = output
    .toString('utf8')
    .split('\0')
    .filter(Boolean)
    .filter(entry => {
      const separator = entry.indexOf('\t');
      const entryPath = separator >= 0 ? entry.slice(separator + 1) : '';
      return !excluded.has(entryPath);
    });
  if (entries.length === 0) {
    throw new Error(`FRONTEND_IDENTITY_INVENTORY_EMPTY ${path}`);
  }
  return createHash('sha1').update(entries.join('\0')).digest('hex');
}

export function computeFrontendFingerprint(releaseId, objectIds) {
  const targets = Object.keys(FINGERPRINT_TARGETS).map(name => [
    name,
    FINGERPRINT_TARGETS[name].kind,
    FINGERPRINT_TARGETS[name].path,
    objectIds[name],
  ]);
  const payload = JSON.stringify({
    schema_version: FRONTEND_IDENTITY_SCHEMA,
    release_id: releaseId,
    canonical_branch: CANONICAL_BRANCH,
    canonical_port: CANONICAL_PORT,
    routes: CANONICAL_ROUTES,
    targets,
  });
  return createHash('sha256').update(payload).digest('hex');
}

function isAncestor(repoRoot, ancestor, descendant) {
  return spawnSync('git', ['-C', repoRoot, 'merge-base', '--is-ancestor', ancestor, descendant], {
    windowsHide: true,
    stdio: 'ignore',
  }).status === 0;
}

function isAncestorAsync(repoRoot, ancestor, descendant) {
  return new Promise((resolvePromise, reject) => {
    execFile(
      'git',
      ['-C', repoRoot, 'merge-base', '--is-ancestor', ancestor, descendant],
      {windowsHide: true},
      error => {
        if (!error) {
          resolvePromise(true);
          return;
        }
        if (error.code === 1) {
          resolvePromise(false);
          return;
        }
        reject(new Error(
          `FRONTEND_IDENTITY_GIT_FAILED git merge-base --is-ancestor: ${error.message}`,
        ));
      },
    );
  });
}

export function listFrontendDirtyPaths(repoRoot) {
  const output = runGit(repoRoot, [
    'status',
    '--porcelain=v1',
    '--untracked-files=all',
    '--',
    ...FRONTEND_DIRTY_SCOPES,
  ]);
  return output ? output.split(/\r?\n/).filter(Boolean) : [];
}

export async function listFrontendDirtyPathsAsync(repoRoot) {
  const output = await runGitAsync(repoRoot, [
    'status',
    '--porcelain=v1',
    '--untracked-files=all',
    '--',
    ...FRONTEND_DIRTY_SCOPES,
  ]);
  return output ? output.split(/\r?\n/).filter(Boolean) : [];
}

function assembleFrontendInspection({
  repoRoot,
  manifest,
  objectIds,
  sourceHead,
  branch,
  mainHead,
  mainWorktree,
  baselineAncestor,
  dirtyPaths,
}) {
  const fingerprint = computeFrontendFingerprint(manifest.release_id, objectIds);
  const manifestMatch = fingerprint === manifest.fingerprint
    && Object.keys(FINGERPRINT_TARGETS).every(name => objectIds[name] === manifest.object_ids[name]);
  const canonical = branch === CANONICAL_BRANCH
    && sourceHead === mainHead
    && normalizePath(repoRoot) === normalizePath(mainWorktree)
    && manifestMatch
    && baselineAncestor
    && dirtyPaths.length === 0;

  return {
    repo_root: repoRoot,
    branch,
    source_head: sourceHead,
    main_head: mainHead,
    main_worktree: mainWorktree,
    manifest,
    object_ids: objectIds,
    fingerprint,
    manifest_match: manifestMatch,
    baseline_ancestor: baselineAncestor,
    dirty_paths: dirtyPaths,
    canonical,
    runtime_identity: {
      schema_version: FRONTEND_RUNTIME_IDENTITY_SCHEMA,
      release_id: manifest.release_id,
      fingerprint,
      configured_fingerprint: manifest.fingerprint,
      source_head: sourceHead,
      launched_source_head: sourceHead,
      current_source_head: sourceHead,
      current_main_head: mainHead,
      frontend_src_tree: objectIds.frontend_src_tree,
      canonical_branch: CANONICAL_BRANCH,
      canonical_port: CANONICAL_PORT,
      canonical,
      manifest_match: manifestMatch,
      runtime_stale: false,
      drift_reasons: [],
      stale_detected_at: null,
      current_branch: branch,
      current_fingerprint: fingerprint,
      current_dirty_paths: dirtyPaths,
      current_worktree: repoRoot,
      worktree: repoRoot,
    },
  };
}

export function inspectFrontendIdentity(startPath = process.cwd(), {ref = 'HEAD', requireClean = false} = {}) {
  const repoRoot = resolveRepoRoot(startPath);
  const manifest = readFrontendManifest(repoRoot);
  return assembleFrontendInspection({
    repoRoot,
    manifest,
    objectIds: buildObjectIds(repoRoot, ref),
    sourceHead: runGit(repoRoot, ['rev-parse', ref]),
    branch: runGit(repoRoot, ['branch', '--show-current']),
    mainHead: runGit(repoRoot, ['rev-parse', 'refs/heads/main']),
    mainWorktree: resolveMainWorktree(repoRoot),
    baselineAncestor: isAncestor(repoRoot, manifest.baseline_commit, ref),
    dirtyPaths: requireClean ? listFrontendDirtyPaths(repoRoot) : [],
  });
}

export async function inspectFrontendIdentityAsync(
  startPath = process.cwd(),
  {ref = 'HEAD', requireClean = false} = {},
) {
  const repoRoot = await resolveRepoRootAsync(startPath);
  const manifest = readFrontendManifest(repoRoot);
  const [
    objectIds,
    sourceHead,
    branch,
    mainHead,
    worktreeText,
    baselineAncestor,
    dirtyPaths,
  ] = await Promise.all([
    buildObjectIdsAsync(repoRoot, ref),
    runGitAsync(repoRoot, ['rev-parse', ref]),
    runGitAsync(repoRoot, ['branch', '--show-current']),
    runGitAsync(repoRoot, ['rev-parse', 'refs/heads/main']),
    runGitAsync(repoRoot, ['worktree', 'list', '--porcelain']),
    isAncestorAsync(repoRoot, manifest.baseline_commit, ref),
    requireClean ? listFrontendDirtyPathsAsync(repoRoot) : Promise.resolve([]),
  ]);
  return assembleFrontendInspection({
    repoRoot,
    manifest,
    objectIds,
    sourceHead,
    branch,
    mainHead,
    mainWorktree: resolveMainWorktreeFromRecords(parseWorktreeList(worktreeText)),
    baselineAncestor,
    dirtyPaths,
  });
}

export function evaluateFrontendRuntimeBinding(launchedIdentity, currentInspection, checkError = null) {
  const driftReasons = [];
  if (checkError) {
    driftReasons.push('runtime_identity_check_failed');
  }
  if (!currentInspection) {
    driftReasons.push('current_identity_unavailable');
  } else {
    if (!currentInspection.canonical) driftReasons.push('current_main_not_canonical');
    if (currentInspection.source_head !== launchedIdentity.source_head) {
      driftReasons.push('main_head_changed');
    }
    if (currentInspection.fingerprint !== launchedIdentity.fingerprint) {
      driftReasons.push('frontend_fingerprint_changed');
    }
    if (currentInspection.dirty_paths.length > 0) {
      driftReasons.push('frontend_worktree_dirty');
    }
    if (normalizePath(currentInspection.repo_root) !== normalizePath(launchedIdentity.worktree)) {
      driftReasons.push('main_worktree_changed');
    }
  }

  const reasons = [...new Set(driftReasons)];
  return {
    ...launchedIdentity,
    canonical: reasons.length === 0,
    manifest_match: currentInspection?.manifest_match ?? false,
    runtime_stale: reasons.length > 0,
    drift_reasons: reasons,
    current_source_head: currentInspection?.source_head ?? null,
    current_main_head: currentInspection?.main_head ?? null,
    current_branch: currentInspection?.branch ?? null,
    current_fingerprint: currentInspection?.fingerprint ?? null,
    current_dirty_paths: currentInspection?.dirty_paths ?? [],
    current_worktree: currentInspection?.repo_root ?? null,
  };
}

export function latchFrontendRuntimeBinding(previousBinding, nextBinding, detectedAt = new Date()) {
  if (previousBinding?.runtime_stale !== true && nextBinding.runtime_stale !== true) {
    return nextBinding;
  }
  const firstDetection = previousBinding?.runtime_stale === true
    ? previousBinding.stale_detected_at
    : detectedAt.toISOString();
  return {
    ...nextBinding,
    canonical: false,
    runtime_stale: true,
    drift_reasons: [
      ...new Set([
        ...(previousBinding?.drift_reasons ?? []),
        ...(nextBinding.drift_reasons ?? []),
      ]),
    ],
    stale_detected_at: firstDetection,
  };
}

function evaluateFrontendCurrentMainHeadBinding(
  launchedIdentity,
  currentMainHead,
  checkError = null,
) {
  const driftReasons = [];
  if (checkError) driftReasons.push('runtime_identity_check_failed');
  if (!currentMainHead) driftReasons.push('current_identity_unavailable');
  if (currentMainHead && currentMainHead !== launchedIdentity.source_head) {
    driftReasons.push('main_head_changed');
  }
  if (launchedIdentity.canonical !== true) {
    driftReasons.push('current_main_not_canonical');
  }
  const reasons = [...new Set(driftReasons)];
  return {
    ...launchedIdentity,
    canonical: reasons.length === 0,
    runtime_stale: reasons.length > 0,
    drift_reasons: reasons,
    current_source_head: launchedIdentity.source_head,
    current_main_head: currentMainHead || null,
  };
}

function writeJsonResponse(response, statusCode, payload) {
  response.statusCode = statusCode;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store');
  response.end(JSON.stringify(payload));
}

export function classifyFrontendRuntimeRequest(request) {
  const path = request.url?.split('?')[0] ?? '/';
  const rawAccept = request.headers?.accept;
  const accept = Array.isArray(rawAccept)
    ? rawAccept.join(',')
    : String(rawAccept ?? '');

  if (path === '/__frontend_identity') {
    return {
      path,
      kind: 'identity',
      requiresFullInspection: false,
      requiresCurrentMainInspection: true,
    };
  }
  if (path === '/api' || path.startsWith('/api/')) {
    return {
      path,
      kind: 'api',
      requiresFullInspection: false,
      requiresCurrentMainInspection: true,
    };
  }
  if (CANONICAL_ROUTES.includes(path)) {
    return {
      path,
      kind: 'document',
      requiresFullInspection: false,
      requiresCurrentMainInspection: true,
    };
  }
  if (accept.toLowerCase().includes('text/html')) {
    return {
      path,
      kind: 'document',
      requiresFullInspection: false,
      requiresCurrentMainInspection: true,
    };
  }
  return {
    path,
    kind: 'static',
    requiresFullInspection: false,
    requiresCurrentMainInspection: false,
  };
}

export function createFrontendRuntimeGuard({
  launchedIdentity,
  inspectCurrentMainHead = () => runGitAsync(
    launchedIdentity.worktree,
    ['rev-parse', 'refs/heads/main'],
  ),
  detectedAt = () => new Date(),
}) {
  let binding = {...launchedIdentity};
  let refreshInFlight = null;

  function refresh() {
    if (binding.runtime_stale === true) return Promise.resolve(binding);
    if (refreshInFlight) return refreshInFlight;
    const operation = Promise.resolve()
      .then(() => inspectCurrentMainHead())
      .then(
        currentMainHead => evaluateFrontendCurrentMainHeadBinding(
          launchedIdentity,
          currentMainHead,
        ),
        error => evaluateFrontendCurrentMainHeadBinding(
          launchedIdentity,
          null,
          error,
        ),
      )
      .then(evaluated => {
        binding = latchFrontendRuntimeBinding(binding, evaluated, detectedAt());
        return binding;
      });
    const singleFlight = operation.finally(() => {
      if (refreshInFlight === singleFlight) refreshInFlight = null;
    });
    refreshInFlight = singleFlight;
    return singleFlight;
  }

  function writeBlocked(response, currentBinding) {
    writeJsonResponse(response, 409, {
      status: 'blocked',
      error: 'FRONTEND_RUNTIME_MAIN_DRIFT',
      identity: currentBinding,
      next_action: 'Restart through start-frontend.cmd after the current main checkout is clean.',
    });
  }

  async function middleware(request, response, next) {
    try {
      const classification = classifyFrontendRuntimeRequest(request);
      const currentBinding = classification.requiresCurrentMainInspection
        ? await refresh()
        : binding;
      if (classification.kind === 'identity') {
        writeJsonResponse(
          response,
          currentBinding.runtime_stale ? 409 : 200,
          currentBinding,
        );
        return;
      }
      if (currentBinding.runtime_stale) {
        writeBlocked(response, currentBinding);
        return;
      }
      next();
    } catch (error) {
      const evaluated = evaluateFrontendCurrentMainHeadBinding(
        launchedIdentity,
        null,
        error,
      );
      binding = latchFrontendRuntimeBinding(binding, evaluated, detectedAt());
      writeBlocked(response, binding);
    }
  }

  return {
    getBinding: () => binding,
    refresh,
    middleware,
  };
}

export function buildFrontendRuntimeDriftClientScript({pollIntervalMs = 2000} = {}) {
  if (!Number.isInteger(pollIntervalMs) || pollIntervalMs < 25) {
    throw new Error('FRONTEND_RUNTIME_POLL_INTERVAL_INVALID');
  }
  return `
    (() => {
      const blockerId = 'quant-frontend-runtime-drift-blocker';
      const renderBlocked = identity => {
        if (document.getElementById(blockerId)) return;
        document.documentElement.dataset.quantRuntimeStale = 'true';
        const panel = document.createElement('main');
        panel.id = blockerId;
        panel.dataset.quantRuntimeStale = 'true';
        panel.setAttribute('role', 'alert');
        panel.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#07111f;color:#dce9f7;display:grid;place-items:center;padding:32px;font-family:Inter,system-ui,sans-serif';
        const content = document.createElement('section');
        content.style.cssText = 'max-width:720px;border:1px solid #29445f;background:#0c1928;padding:28px;border-radius:8px;box-shadow:0 20px 70px rgba(0,0,0,.35)';
        const title = document.createElement('h1');
        title.textContent = '前端已因主线版本变化停止服务';
        const detail = document.createElement('p');
        detail.textContent = '当前页面进程不再匹配 refs/heads/main。请从仓库根目录运行 start-frontend.cmd。';
        const heads = document.createElement('code');
        heads.textContent = 'launched=' + (identity.launched_source_head ?? 'unknown') + ' current=' + (identity.current_main_head ?? 'unknown');
        content.append(title, detail, heads);
        panel.append(content);
        document.body.append(panel);
      };
      let checkInFlight = null;
      const check = () => {
        if (checkInFlight !== null) return checkInFlight;
        const operation = (async () => {
          try {
            const response = await fetch('/__frontend_identity', {cache: 'no-store'});
            const identity = await response.json();
            if (identity.runtime_stale !== true && identity.canonical === true) return false;
            renderBlocked(identity);
            return true;
          } catch {
            return false;
          }
        })();
        const singleFlight = operation.finally(() => {
          if (checkInFlight === singleFlight) checkInFlight = null;
        });
        checkInFlight = singleFlight;
        return singleFlight;
      };
      let interval = null;
      const poll = () => {
        if (checkInFlight !== null) return;
        void check().then(blocked => {
          if (!blocked) return;
          if (interval !== null) window.clearInterval(interval);
        });
      };
      interval = window.setInterval(poll, ${pollIntervalMs});
      poll();
    })();
  `;
}

export function assertCanonicalFrontend(inspection) {
  const blockers = [];
  if (inspection.branch !== CANONICAL_BRANCH) blockers.push(`branch=${inspection.branch || 'DETACHED'}`);
  if (inspection.source_head !== inspection.main_head) blockers.push(`head=${inspection.source_head} main=${inspection.main_head}`);
  if (normalizePath(inspection.repo_root) !== normalizePath(inspection.main_worktree)) {
    blockers.push(`worktree=${inspection.repo_root} expected=${inspection.main_worktree}`);
  }
  if (!inspection.manifest_match) blockers.push('fingerprint_or_object_ids_mismatch');
  if (!inspection.baseline_ancestor) blockers.push(`baseline_not_ancestor=${inspection.manifest.baseline_commit}`);
  if (inspection.dirty_paths.length > 0) blockers.push(`dirty=${inspection.dirty_paths.join(';')}`);
  if (!inspection.canonical || blockers.length > 0) {
    throw new Error(`FRONTEND_CANONICAL_GUARD_FAILED ${blockers.join(' | ') || 'unknown'}`);
  }
  return inspection;
}

export function assertCanonicalServe(inspection, requestedPort) {
  assertCanonicalFrontend(inspection);
  const canonicalPort = inspection.manifest.canonical_port;
  if (requestedPort !== canonicalPort) {
    throw new Error(
      `FRONTEND_CANONICAL_PORT_REQUIRED requested=${requestedPort} expected=${canonicalPort}`,
    );
  }
  return inspection;
}
