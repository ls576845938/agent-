import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';

import {chromium} from '@playwright/test';

import {
  buildFrontendRuntimeDriftClientScript,
  CANONICAL_ROUTES,
  classifyFrontendRuntimeRequest,
  createFrontendRuntimeGuard,
} from './frontend-identity-lib.mjs';

const HEAD_A = '1'.repeat(40);
const HEAD_B = '2'.repeat(40);
const FINGERPRINT_A = 'a'.repeat(64);

function inspection(overrides = {}) {
  return {
    repo_root: 'D:/repo',
    branch: 'main',
    source_head: HEAD_A,
    main_head: HEAD_A,
    main_worktree: 'D:/repo',
    fingerprint: FINGERPRINT_A,
    manifest_match: true,
    dirty_paths: [],
    canonical: true,
    ...overrides,
  };
}

function launchedIdentity(overrides = {}) {
  return {
    schema_version: 'quant_frontend_runtime_identity_v1',
    release_id: 'test',
    fingerprint: FINGERPRINT_A,
    configured_fingerprint: FINGERPRINT_A,
    source_head: HEAD_A,
    launched_source_head: HEAD_A,
    current_source_head: HEAD_A,
    current_main_head: HEAD_A,
    current_branch: 'main',
    current_fingerprint: FINGERPRINT_A,
    current_dirty_paths: [],
    current_worktree: 'D:/repo',
    canonical_branch: 'main',
    canonical_port: 3000,
    canonical: true,
    manifest_match: true,
    runtime_stale: false,
    drift_reasons: [],
    stale_detected_at: null,
    worktree: 'D:/repo',
    ...overrides,
  };
}

async function startHarness({
  includeBrowserPage = false,
  pollIntervalMs = 50,
  initialIdentity = launchedIdentity(),
} = {}) {
  let currentHead = HEAD_A;
  let failure = null;
  let downstreamHits = 0;
  let fullInspectorCalls = 0;
  let headInspectorCalls = 0;
  const guard = createFrontendRuntimeGuard({
    launchedIdentity: initialIdentity,
    inspectCurrent: () => {
      fullInspectorCalls += 1;
      return inspection();
    },
    inspectCurrentMainHead: () => {
      headInspectorCalls += 1;
      if (failure) throw failure;
      return currentHead;
    },
    detectedAt: () => new Date('2026-07-27T00:00:00Z'),
  });
  const clientScript = buildFrontendRuntimeDriftClientScript({pollIntervalMs});
  const server = createServer((request, response) => {
    guard.middleware(request, response, () => {
      downstreamHits += 1;
      response.statusCode = 200;
      response.setHeader('Content-Type', 'text/html; charset=utf-8');
      response.end(includeBrowserPage
        ? `<!doctype html><html><body><div id="root">canonical</div><script>${clientScript}</script></body></html>`
        : 'downstream');
    });
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.equal(typeof address, 'object');
  const baseUrl = `http://127.0.0.1:${address.port}`;
  return {
    baseUrl,
    close: async () => {
      server.close();
      await once(server, 'close');
    },
    get downstreamHits() {
      return downstreamHits;
    },
    get fullInspectorCalls() {
      return fullInspectorCalls;
    },
    get headInspectorCalls() {
      return headInspectorCalls;
    },
    setHead: value => {
      currentHead = value;
    },
    setFailure: value => {
      failure = value;
    },
  };
}

for (const route of CANONICAL_ROUTES) {
  for (const method of ['GET', 'HEAD', 'POST']) {
    for (const accept of [undefined, '*/*', 'text/plain', 'text/html']) {
      const classified = classifyFrontendRuntimeRequest({
        url: `${route}?matrix=1`,
        method,
        headers: accept === undefined ? {} : {accept},
      });
      assert.equal(classified.kind, 'document');
      assert.equal(classified.requiresFullInspection, false);
      assert.equal(classified.requiresCurrentMainInspection, true);
    }
  }
}
for (const method of ['GET', 'HEAD', 'POST', 'DELETE']) {
  const identityRequest = classifyFrontendRuntimeRequest({
    url: '/__frontend_identity?matrix=1',
    method,
    headers: {accept: 'text/plain'},
  });
  assert.equal(identityRequest.kind, 'identity');
  assert.equal(identityRequest.requiresFullInspection, false);
  assert.equal(identityRequest.requiresCurrentMainInspection, true);

  for (const path of ['/api', '/api/runtime/deep']) {
    const apiRequest = classifyFrontendRuntimeRequest({
      url: `${path}?matrix=1`,
      method,
      headers: {},
    });
    assert.equal(apiRequest.kind, 'api');
    assert.equal(apiRequest.requiresFullInspection, false);
    assert.equal(apiRequest.requiresCurrentMainInspection, true);
  }
}
for (const path of ['/@vite/client', '/src/main.tsx', '/assets/app.js', '/favicon.svg']) {
  const staticRequest = classifyFrontendRuntimeRequest({
    url: `${path}?v=1`,
    method: 'GET',
    headers: {accept: '*/*'},
  });
  assert.equal(staticRequest.kind, 'static');
  assert.equal(staticRequest.requiresFullInspection, false);
  assert.equal(staticRequest.requiresCurrentMainInspection, false);
}

async function readIdentity(baseUrl, expectedStatus = 200) {
  const response = await fetch(`${baseUrl}/__frontend_identity`, {cache: 'no-store'});
  assert.equal(response.status, expectedStatus);
  return await response.json();
}

function deferred() {
  let resolvePromise;
  let rejectPromise;
  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {promise, resolve: resolvePromise, reject: rejectPromise};
}

const hotpathHarness = await startHarness();
try {
  const staticPaths = [
    '/@vite/client',
    '/src/main.tsx',
    '/assets/index.js',
    '/assets/index.css',
    '/favicon.svg',
  ];
  for (const path of staticPaths) {
    const response = await fetch(`${hotpathHarness.baseUrl}${path}`, {
      headers: {Accept: '*/*'},
    });
    assert.equal(response.status, 200);
  }
  assert.equal(hotpathHarness.fullInspectorCalls, 0);
  assert.equal(hotpathHarness.headInspectorCalls, 0);
  assert.equal(hotpathHarness.downstreamHits, staticPaths.length);

  await readIdentity(hotpathHarness.baseUrl);
  assert.equal(hotpathHarness.fullInspectorCalls, 0);
  assert.equal(hotpathHarness.headInspectorCalls, 1);

  const documentResponse = await fetch(`${hotpathHarness.baseUrl}/crypto`, {
    headers: {Accept: 'text/html,application/xhtml+xml'},
  });
  assert.equal(documentResponse.status, 200);
  assert.equal(hotpathHarness.headInspectorCalls, 2);

  const apiResponse = await fetch(`${hotpathHarness.baseUrl}/api/runtime`);
  assert.equal(apiResponse.status, 200);
  assert.equal(hotpathHarness.headInspectorCalls, 3);

  hotpathHarness.setHead(HEAD_B);
  const staleDocument = await fetch(`${hotpathHarness.baseUrl}/portfolio`, {
    headers: {Accept: 'text/html'},
  });
  assert.equal(staleDocument.status, 409);
  assert.equal(hotpathHarness.headInspectorCalls, 4);
  assert.equal(hotpathHarness.fullInspectorCalls, 0);
  const downstreamBeforeBlockedStatic = hotpathHarness.downstreamHits;

  hotpathHarness.setHead(HEAD_A);
  for (const path of staticPaths) {
    const response = await fetch(`${hotpathHarness.baseUrl}${path}`, {
      headers: {Accept: '*/*'},
    });
    assert.equal(response.status, 409);
  }
  assert.equal(hotpathHarness.headInspectorCalls, 4);
  assert.equal(hotpathHarness.downstreamHits, downstreamBeforeBlockedStatic);
} finally {
  await hotpathHarness.close();
}

let pendingInspection = deferred();
let inspectionStarted = deferred();
let actualInspectorCalls = 0;
let activeInspectors = 0;
let maxConcurrentInspectors = 0;
let singleFlightDownstreamHits = 0;
const singleFlightGuard = createFrontendRuntimeGuard({
  launchedIdentity: launchedIdentity(),
  inspectCurrent: () => {
    throw new Error('full inspection must not run on the request hot path');
  },
  inspectCurrentMainHead: () => {
    actualInspectorCalls += 1;
    activeInspectors += 1;
    inspectionStarted.resolve();
    maxConcurrentInspectors = Math.max(
      maxConcurrentInspectors,
      activeInspectors,
    );
    return pendingInspection.promise.finally(() => {
      activeInspectors -= 1;
    });
  },
  detectedAt: () => new Date('2026-07-27T00:00:00Z'),
});
const singleFlightServer = createServer((request, response) => {
  void singleFlightGuard.middleware(request, response, () => {
    singleFlightDownstreamHits += 1;
    response.statusCode = 200;
    response.end('downstream');
  });
});
singleFlightServer.listen(0, '127.0.0.1');
await once(singleFlightServer, 'listening');
const singleFlightAddress = singleFlightServer.address();
assert.equal(typeof singleFlightAddress, 'object');
const singleFlightBaseUrl = `http://127.0.0.1:${singleFlightAddress.port}`;
try {
  const firstWave = [
    fetch(`${singleFlightBaseUrl}/__frontend_identity?tab=1`, {method: 'POST'}),
    fetch(`${singleFlightBaseUrl}/api/runtime?tab=2`, {method: 'DELETE'}),
    fetch(`${singleFlightBaseUrl}/crypto?tab=3`, {headers: {Accept: '*/*'}}),
    fetch(`${singleFlightBaseUrl}/research?tab=4`, {
      method: 'POST',
      headers: {Accept: 'text/plain'},
    }),
  ];
  await inspectionStarted.promise;
  assert.equal(actualInspectorCalls, 1);
  assert.equal(activeInspectors, 1);
  assert.equal(maxConcurrentInspectors, 1);

  let cheapTimerFired = false;
  const cheapTimer = new Promise(resolvePromise => {
    setImmediate(() => {
      cheapTimerFired = true;
      resolvePromise();
    });
  });
  const staticWhileInspecting = fetch(
    `${singleFlightBaseUrl}/assets/non-blocking.js`,
    {headers: {Accept: '*/*'}},
  );
  await cheapTimer;
  assert.equal(cheapTimerFired, true);
  const staticResponse = await staticWhileInspecting;
  assert.equal(staticResponse.status, 200);
  assert.equal(actualInspectorCalls, 1);
  assert.equal(activeInspectors, 1);

  pendingInspection.resolve(HEAD_A);
  const firstStatuses = await Promise.all(
    firstWave.map(async responsePromise => (await responsePromise).status),
  );
  assert.deepEqual(firstStatuses, [200, 200, 200, 200]);
  assert.equal(actualInspectorCalls, 1);
  assert.equal(maxConcurrentInspectors, 1);

  pendingInspection = deferred();
  inspectionStarted = deferred();
  const errorWave = [
    fetch(`${singleFlightBaseUrl}/__frontend_identity?tab=1`, {method: 'HEAD'}),
    fetch(`${singleFlightBaseUrl}/api?tab=2`, {method: 'POST'}),
    fetch(`${singleFlightBaseUrl}/portfolio?tab=3`),
    fetch(`${singleFlightBaseUrl}/strategies?tab=4`, {
      headers: {Accept: 'text/plain'},
    }),
  ];
  await inspectionStarted.promise;
  assert.equal(actualInspectorCalls, 2);
  assert.equal(activeInspectors, 1);
  assert.equal(maxConcurrentInspectors, 1);
  pendingInspection.reject(new Error('delayed synthetic inspection error'));
  const errorStatuses = await Promise.all(
    errorWave.map(async responsePromise => (await responsePromise).status),
  );
  assert.deepEqual(errorStatuses, [409, 409, 409, 409]);
  assert.equal(singleFlightGuard.getBinding().runtime_stale, true);
  assert.ok(
    singleFlightGuard
      .getBinding()
      .drift_reasons
      .includes('runtime_identity_check_failed'),
  );

  const callsBeforeBlockedStatic = actualInspectorCalls;
  const hitsBeforeBlockedStatic = singleFlightDownstreamHits;
  const blockedStaticResponse = await fetch(
    `${singleFlightBaseUrl}/assets/blocked-after-error.css`,
    {headers: {Accept: 'text/css'}},
  );
  assert.equal(blockedStaticResponse.status, 409);
  assert.equal(actualInspectorCalls, callsBeforeBlockedStatic);
  assert.equal(singleFlightDownstreamHits, hitsBeforeBlockedStatic);
} finally {
  singleFlightServer.close();
  await once(singleFlightServer, 'close');
}

const dirtyPaths = [' M frontend/index.html', '?? frontend/public/new.svg'];
const dirtyHarness = await startHarness({
  initialIdentity: launchedIdentity({
    canonical: false,
    manifest_match: false,
    runtime_stale: true,
    drift_reasons: ['frontend_worktree_dirty'],
    stale_detected_at: '2026-07-27T00:00:00.000Z',
    current_dirty_paths: dirtyPaths,
  }),
});
try {
  const dirtyIdentity = await readIdentity(dirtyHarness.baseUrl, 409);
  assert.equal(dirtyIdentity.runtime_stale, true);
  assert.equal(dirtyIdentity.stale_detected_at, '2026-07-27T00:00:00.000Z');
  assert.deepEqual(dirtyIdentity.current_dirty_paths, dirtyPaths);
  assert.equal(dirtyHarness.fullInspectorCalls, 0);
  assert.equal(dirtyHarness.headInspectorCalls, 0);
  const blockedStatic = await fetch(`${dirtyHarness.baseUrl}/assets/app.js`, {
    headers: {Accept: '*/*'},
  });
  assert.equal(blockedStatic.status, 409);
  assert.equal(dirtyHarness.headInspectorCalls, 0);
  assert.equal(dirtyHarness.downstreamHits, 0);
} finally {
  await dirtyHarness.close();
}

const mainHarness = await startHarness();
try {
  await readIdentity(mainHarness.baseUrl);
  mainHarness.setHead(HEAD_B);
  const advanced = await readIdentity(mainHarness.baseUrl, 409);
  assert.equal(advanced.runtime_stale, true);
  assert.equal(advanced.current_source_head, HEAD_A);
  assert.equal(advanced.current_main_head, HEAD_B);
  assert.ok(advanced.drift_reasons.includes('main_head_changed'));
  mainHarness.setHead(HEAD_A);
  const reverted = await readIdentity(mainHarness.baseUrl, 409);
  assert.equal(reverted.runtime_stale, true);
  assert.ok(reverted.drift_reasons.includes('main_head_changed'));
  assert.equal(reverted.current_source_head, HEAD_A);
  assert.equal(reverted.current_main_head, HEAD_B);
} finally {
  await mainHarness.close();
}

const failedHarness = await startHarness();
try {
  await readIdentity(failedHarness.baseUrl);
  failedHarness.setFailure(new Error('synthetic identity failure'));
  const failed = await readIdentity(failedHarness.baseUrl, 409);
  assert.equal(failed.runtime_stale, true);
  assert.ok(failed.drift_reasons.includes('runtime_identity_check_failed'));
  failedHarness.setFailure(null);
  const recovered = await readIdentity(failedHarness.baseUrl, 409);
  assert.equal(recovered.runtime_stale, true);
  assert.ok(recovered.drift_reasons.includes('runtime_identity_check_failed'));
  assert.equal(recovered.current_source_head, HEAD_A);
  assert.equal(recovered.current_fingerprint, FINGERPRINT_A);
} finally {
  await failedHarness.close();
}

const browserHarness = await startHarness({includeBrowserPage: true});
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage();
  await page.goto(browserHarness.baseUrl, {waitUntil: 'domcontentloaded'});
  await page.locator('#root').waitFor({state: 'visible'});
  browserHarness.setHead(HEAD_B);
  const blocker = page.locator('#quant-frontend-runtime-drift-blocker');
  await blocker.waitFor({state: 'visible', timeout: 5000});
  assert.match(await blocker.textContent(), /前端已因主线版本变化停止服务/u);

  browserHarness.setHead(HEAD_A);
  await page.evaluate(() => {
    document.getElementById('root')?.replaceChildren(document.createTextNode('react rerender'));
  });
  await page.waitForTimeout(200);
  assert.equal(await blocker.isVisible(), true);
  assert.equal(await page.locator('html[data-quant-runtime-stale="true"]').count(), 1);
} finally {
  await browser.close();
  await browserHarness.close();
}

const tabHarness = await startHarness({
  includeBrowserPage: true,
  pollIntervalMs: 2000,
});
const tabBrowser = await chromium.launch({headless: true});
try {
  const pages = await Promise.all(
    Array.from({length: 4}, async () => {
      const page = await tabBrowser.newPage();
      await page.addInitScript(delayMs => {
        const originalFetch = window.fetch.bind(window);
        window.__quantIdentityFetchMetrics = {
          active: 0,
          maxActive: 0,
          starts: [],
          completions: [],
          driftMarkedAt: null,
        };
        window.fetch = async (...args) => {
          const target = String(args[0]);
          if (!target.includes('/__frontend_identity')) {
            return originalFetch(...args);
          }
          const metrics = window.__quantIdentityFetchMetrics;
          metrics.active += 1;
          metrics.maxActive = Math.max(metrics.maxActive, metrics.active);
          metrics.starts.push(performance.now());
          await new Promise(resolvePromise => window.setTimeout(resolvePromise, delayMs));
          try {
            return await originalFetch(...args);
          } finally {
            metrics.active -= 1;
            metrics.completions.push(performance.now());
          }
        };
      }, 125);
      await page.goto(tabHarness.baseUrl, {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => (
        window.__quantIdentityFetchMetrics.starts.length >= 1
        && window.__quantIdentityFetchMetrics.active === 0
      ));
      return page;
    }),
  );

  tabHarness.setHead(HEAD_B);
  await Promise.all(pages.map(page => page.evaluate(() => {
    window.__quantIdentityFetchMetrics.driftMarkedAt = performance.now();
  })));
  await Promise.all(pages.map(page => (
    page
      .locator('#quant-frontend-runtime-drift-blocker')
      .waitFor({state: 'visible', timeout: 5000})
  )));

  for (const page of pages) {
    const metrics = await page.evaluate(() => ({
      ...window.__quantIdentityFetchMetrics,
      blockedAt: performance.now(),
    }));
    assert.equal(metrics.maxActive, 1);
    const driftInspectionStartedAt = metrics.starts.find(
      value => value >= metrics.driftMarkedAt,
    );
    assert.notEqual(driftInspectionStartedAt, undefined);
    assert.ok(driftInspectionStartedAt - metrics.driftMarkedAt <= 2500);
    assert.ok(metrics.blockedAt - driftInspectionStartedAt <= 1000);
  }
} finally {
  await tabBrowser.close();
  await tabHarness.close();
}

console.log(JSON.stringify({
  status: 'passed',
  scenarios: [
    'static_hotpath_reuses_latched_binding',
    'identity_document_api_use_cheap_current_main_inspection',
    'request_hotpath_never_repeats_full_inspection',
    'stale_static_blocked_without_downstream_or_rescan',
    'startup_dirty_and_fingerprint_identity_remains_latched',
    'main_advance_revert_latched',
    'inspection_failure_recovery_latched',
    'identity_healthy_200_stale_all_409_proxy_not_hit',
    'chromium_blocker_persistent',
    'async_single_flight_four_critical_requests',
    'event_loop_static_response_while_inspection_pending',
    'four_tabs_client_fetch_single_flight_and_bounded_detection',
  ],
}, null, 2));
