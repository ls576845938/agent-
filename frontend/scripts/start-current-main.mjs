import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import net from 'node:net';
import {resolve} from 'node:path';

import {
  assertCanonicalServe,
  inspectFrontendIdentity,
} from './frontend-identity-lib.mjs';

let inspection;
try {
  const candidate = inspectFrontendIdentity(process.cwd(), {requireClean: true});
  inspection = assertCanonicalServe(candidate, candidate.manifest.canonical_port);
} catch (error) {
  console.error(JSON.stringify({
    status: 'blocked',
    error: 'FRONTEND_CANONICAL_GUARD_FAILED',
    detail: error.message,
    next_action: 'Use start-frontend.cmd from the registered main worktree; every other worktree and port is blocked.',
  }, null, 2));
  process.exit(2);
}

if (process.argv.includes('--check')) {
  console.log(JSON.stringify({
    status: 'passed',
    canonical: true,
    source_head: inspection.source_head,
    worktree: inspection.repo_root,
    fingerprint: inspection.fingerprint,
  }, null, 2));
  process.exit(0);
}

function portIsOpen(port) {
  return new Promise(resolvePromise => {
    const socket = net.createConnection({host: '127.0.0.1', port});
    const done = value => {
      socket.destroy();
      resolvePromise(value);
    };
    socket.setTimeout(750);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

async function readRunningIdentity(port) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/__frontend_identity`, {
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

const port = inspection.manifest.canonical_port;
if (await portIsOpen(port)) {
  const running = await readRunningIdentity(port);
  const accepted = running?.canonical === true
    && running?.runtime_stale !== true
    && running?.source_head === inspection.source_head
    && running?.fingerprint === inspection.fingerprint;
  if (!accepted) {
    console.error(JSON.stringify({
      status: 'blocked',
      error: 'FRONTEND_PORT_IDENTITY_MISMATCH',
      port,
      expected: inspection.runtime_identity,
      observed: running,
      next_action: 'Stop the stale or unverified listener on port 3000, then rerun start-frontend.cmd.',
    }, null, 2));
    process.exit(3);
  }
  console.log(JSON.stringify({
    status: 'already_running',
    url: `http://127.0.0.1:${port}/`,
    source_head: running.source_head,
    fingerprint: running.fingerprint,
  }, null, 2));
  process.exit(0);
}

const viteBin = resolve(process.cwd(), 'node_modules/vite/bin/vite.js');
if (!existsSync(viteBin)) {
  console.error('FRONTEND_DEPENDENCIES_MISSING run npm.cmd ci --offline in the canonical main frontend first');
  process.exit(4);
}

console.log(JSON.stringify({
  status: 'starting',
  url: `http://127.0.0.1:${port}/`,
  source_head: inspection.source_head,
  fingerprint: inspection.fingerprint,
  worktree: inspection.repo_root,
}, null, 2));

const child = spawn(process.execPath, [
  viteBin,
  '--host',
  '0.0.0.0',
  '--port',
  String(port),
  '--strictPort',
], {
  cwd: process.cwd(),
  env: {
    ...process.env,
    QUANT_FRONTEND_CANONICAL_LAUNCH: '1',
  },
  stdio: 'inherit',
  windowsHide: false,
});

child.once('error', error => {
  console.error(`FRONTEND_VITE_START_FAILED ${error.message}`);
  process.exitCode = 5;
});
child.once('exit', code => {
  process.exitCode = code ?? 5;
});
