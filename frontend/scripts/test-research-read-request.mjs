import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import http from 'node:http';
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const ts = require('typescript');
async function importTypeScript(relativePath) {
  const sourceUrl = new URL(relativePath, import.meta.url);
  const source = await readFile(sourceUrl, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: pathToFileURL(sourceUrl.pathname).href,
  }).outputText;
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`;
  return import(moduleUrl);
}

async function importCommonJsTypeScript(relativePath, dependencies) {
  const sourceUrl = new URL(relativePath, import.meta.url);
  const source = await readFile(sourceUrl, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: pathToFileURL(sourceUrl.pathname).href,
  }).outputText;
  const module = {exports: {}};
  vm.runInNewContext(
    `(function(require,module,exports){${compiled}\n})`,
    {},
  )((id) => {
    if (id in dependencies) return dependencies[id];
    throw new Error(`Unexpected dependency: ${id}`);
  }, module, module.exports);
  return module.exports;
}

async function importViteConfigForTest() {
  const sourceUrl = new URL('../vite.config.ts', import.meta.url);
  const source = await readFile(sourceUrl, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: pathToFileURL(sourceUrl.pathname).href,
  }).outputText;
  const module = {exports: {}};
  const localRequire = (id) => {
    if (id === 'vite') return {defineConfig: (value) => value};
    if (id === '@vitejs/plugin-react') return {default: () => ({})};
    if (id === './scripts/candidate-local-guard.mjs') return {candidateLocalGuardPlugin: () => ({})};
    if (id === './scripts/frontend-identity-lib.mjs') return {};
    throw new Error(`Unexpected vite config dependency: ${id}`);
  };
  vm.runInNewContext(
    `(function(require,module,exports){${compiled}\n})`,
    {},
  )(localRequire, module, module.exports);
  return module.exports;
}

const {
  acquireResearchRead,
  classifyResearchReadError,
  summarizeResearchRegistry,
} = await importTypeScript('../src/lib/research-read-request.ts');
const {apiGet} = await importTypeScript('../src/lib/api.ts');

{
  const pending = deferred();
  const calls = [];
  const alphaFactory = await importCommonJsTypeScript('../src/lib/alpha-factory-api.ts', {
    './api': {
      apiGet: (path, options) => {
        calls.push({path, options});
        return pending.promise;
      },
      apiPost: () => { throw new Error('unexpected write'); },
    },
    './research-read-request': {acquireResearchRead},
  });
  assert.equal(typeof alphaFactory.acquireAlphaFactoryOverview, 'function');
  const firstMount = alphaFactory.acquireAlphaFactoryOverview();
  await Promise.resolve();
  firstMount.release();
  const secondMount = alphaFactory.acquireAlphaFactoryOverview();
  await Promise.resolve();
  assert.equal(calls.length, 1, 'Alpha StrictMode remount must share one verified overview GET');
  assert.equal(calls[0].path, '/api/research/alpha-factory');
  assert.equal(calls[0].options.timeoutMs, 20_000, 'Alpha keeps its existing 20 second budget');
  assert.equal(calls[0].options.signal.aborted, false);
  pending.resolve({runs: []});
  assert.deepEqual(await secondMount.promise, {runs: []});
  secondMount.release();
}

{
  const calls = [];
  const pending = new Map();
  const alphaFactory = await importCommonJsTypeScript('../src/lib/alpha-factory-api.ts', {
    './api': {
      apiGet: (path, options) => {
        calls.push({path, options});
        const result = deferred();
        pending.set(path, result);
        options.signal.addEventListener(
          'abort',
          () => result.reject(new DOMException('aborted', 'AbortError')),
          {once: true},
        );
        return result.promise;
      },
      apiPost: () => { throw new Error('unexpected write'); },
    },
    './research-read-request': {acquireResearchRead},
  });
  const oldRead = alphaFactory.acquireAlphaFactoryDetail('old-run');
  const oldRejected = assert.rejects(oldRead.promise, {name: 'AbortError'});
  await Promise.resolve();
  oldRead.release();
  await new Promise(resolve => setTimeout(resolve, 5));
  await oldRejected;
  assert.equal(calls[0].options.signal.aborted, true, 'released Alpha detail must abort its GET');

  const currentRead = alphaFactory.acquireAlphaFactoryDetail('current-run');
  await Promise.resolve();
  pending.get('/api/research/alpha-factory/runs/current-run').resolve({run_id: 'current-run'});
  assert.deepEqual(await currentRead.promise, {run_id: 'current-run'});
  currentRead.release();
  assert.deepEqual(
    calls.map(call => call.path),
    ['/api/research/alpha-factory/runs/old-run', '/api/research/alpha-factory/runs/current-run'],
    'switching run must not reuse a stale detail read',
  );
}

{
  const calls = [];
  const alphaFactory = await importCommonJsTypeScript('../src/lib/alpha-factory-api.ts', {
    './api': {
      apiGet: (path, options) => {
        calls.push({path, options});
        return Promise.resolve({run_id: 'budgeted-run'});
      },
      apiPost: () => { throw new Error('unexpected write'); },
    },
    './research-read-request': {acquireResearchRead},
  });
  const remainingBudgetMs = 12_345;
  const detailRead = alphaFactory.acquireAlphaFactoryDetail('budgeted-run', remainingBudgetMs);
  assert.deepEqual(await detailRead.promise, {run_id: 'budgeted-run'});
  detailRead.release();
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].options.timeoutMs,
    remainingBudgetMs,
    'serialized initial detail must use the remaining Alpha page budget',
  );
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return {promise, resolve, reject};
}

function fakeClock() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  return {
    setTimeout(callback, delay) {
      const id = nextId++;
      timers.set(id, {at: now + delay, callback});
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    tick(ms) {
      now += ms;
      while (true) {
        const due = [...timers.entries()].filter(([, timer]) => timer.at <= now).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        due[1].callback();
      }
    },
  };
}

{
  const clock = fakeClock();
  const result = deferred();
  let calls = 0;
  const load = async () => { calls += 1; return result.promise; };
  const first = acquireResearchRead('data|qlib|portfolio', load, {clock});
  const second = acquireResearchRead('data|qlib|portfolio', load, {clock});
  await Promise.resolve();
  assert.equal(calls, 1, 'same source must share one in-flight read');
  result.resolve({value: 7});
  assert.deepEqual(await first.promise, {value: 7});
  assert.deepEqual(await second.promise, {value: 7});
  first.release();
  second.release();
}

{
  const clock = fakeClock();
  const result = deferred();
  let calls = 0;
  let signal;
  const load = async (nextSignal) => { calls += 1; signal = nextSignal; return result.promise; };
  const firstMount = acquireResearchRead('strict-mode', load, {clock, releaseGraceMs: 1});
  await Promise.resolve();
  firstMount.release();
  const secondMount = acquireResearchRead('strict-mode', load, {clock, releaseGraceMs: 1});
  clock.tick(1);
  assert.equal(calls, 1, 'StrictMode remount must reuse the pending read');
  assert.equal(signal.aborted, false, 'remount must cancel the deferred release abort');
  result.resolve('ok');
  assert.equal(await secondMount.promise, 'ok');
  secondMount.release();
}

{
  const clock = fakeClock();
  let oldSignal;
  const oldRead = acquireResearchRead('old-root', (signal) => {
    oldSignal = signal;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), {once: true}));
  }, {clock, releaseGraceMs: 1});
  await Promise.resolve();
  oldRead.release();
  clock.tick(1);
  await assert.rejects(oldRead.promise, (error) => classifyResearchReadError(error, oldSignal).kind === 'cancelled');
  assert.equal(oldSignal.aborted, true, 'abandoned source must be aborted');
}

{
  const clock = fakeClock();
  let signal;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_url, options) => ({
    ok: true,
    json: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), {once: true})),
  });
  const read = acquireResearchRead('deadline', (nextSignal) => {
    signal = nextSignal;
    return apiGet('/large-registry', {timeoutMs: 20_000, signal: nextSignal});
  }, {clock, deadlineMs: 12_000});
  await Promise.resolve();
  await Promise.resolve();
  clock.tick(12_000);
  await assert.rejects(read.promise, (error) => classifyResearchReadError(error, signal).kind === 'deadline');
  globalThis.fetch = originalFetch;
  read.release();
}

{
  const summary = summarizeResearchRegistry({
    registry_status: 'CONFLICT',
    registry_integrity_status: 'CONFLICT',
    registry_notes: Array.from({length: 57}, (_, index) => `conflict-${index + 1}`),
  });
  assert.equal(summary.status, 'CONFLICT');
  assert.equal(summary.notesTotal, 57);
  assert.deepEqual(summary.notes, ['conflict-1', 'conflict-2', 'conflict-3']);
  assert.equal(summary.qualification, 'blocked');
  assert.equal(summarizeResearchRegistry(null, {registry: {integrity: 'unknown'}}).qualification, 'unknown');
}

{
  const {configureEvidenceRegistryProxyCancellation} = await importViteConfigForTest();
  assert.equal(typeof configureEvidenceRegistryProxyCancellation, 'function');

  function exercise({method = 'GET', url, headersSent = false, normal = false, destroyed = false, closed = false}) {
    const proxy = new EventEmitter();
    configureEvidenceRegistryProxyCancellation(proxy);
    let destroys = 0;
    const proxyRequest = {
      destroyed: false,
      destroy() { destroys += 1; this.destroyed = true; },
    };
    const response = new EventEmitter();
    response.headersSent = headersSent;
    response.writableEnded = false;
    response.destroyed = destroyed;
    response.closed = closed;
    proxy.emit('proxyReq', proxyRequest, {method, url}, response);
    const listenersBefore = {
      close: response.listenerCount('close'),
      finish: response.listenerCount('finish'),
    };
    if (destroyed || closed) {
      // The close event already happened before the proxyReq hook ran.
    } else if (normal) {
      response.writableEnded = true;
      response.emit('finish');
      response.emit('close');
    } else {
      response.emit('close');
    }
    return {
      destroys,
      listenersBefore,
      listenersAfter: {
        close: response.listenerCount('close'),
        finish: response.listenerCount('finish'),
      },
    };
  }

  for (const headersSent of [false, true]) {
    const cancelled = exercise({
      url: '/api/research/evidence-registry?data_root=data&view=summary',
      headersSent,
    });
    assert.equal(cancelled.destroys, 1, `cancelled registry GET must close upstream; headersSent=${headersSent}`);
    assert.deepEqual(cancelled.listenersBefore, {close: 1, finish: 1});
    assert.deepEqual(cancelled.listenersAfter, {close: 0, finish: 0});
  }

  for (const state of [{destroyed: true}, {closed: true}]) {
    const alreadyClosed = exercise({
      url: '/api/research/evidence-registry?view=summary',
      ...state,
    });
    assert.equal(alreadyClosed.destroys, 1, 'already-closed downstream must immediately close registry upstream');
    assert.deepEqual(alreadyClosed.listenersBefore, {close: 0, finish: 0});
    assert.deepEqual(alreadyClosed.listenersAfter, {close: 0, finish: 0});
  }

  const completed = exercise({
    url: '/api/research/evidence-registry?data_root=data&view=full',
    normal: true,
  });
  assert.equal(completed.destroys, 0, 'normal registry response must not close upstream');
  assert.deepEqual(completed.listenersAfter, {close: 0, finish: 0});

  for (const request of [
    {method: 'GET', url: '/api/research/global-registry'},
    {method: 'POST', url: '/api/research/evidence-registry'},
    {method: 'POST', url: '/api/research/evidence-registry/rebuild'},
  ]) {
    const untouched = exercise(request);
    assert.equal(untouched.destroys, 0, `${request.method} ${request.url} must not install registry cancellation`);
    assert.deepEqual(untouched.listenersBefore, {close: 0, finish: 0});
  }

  const rejectedRebuildGet = exercise({
    method: 'GET',
    url: '/api/research/evidence-registry?rebuild=true',
    normal: true,
  });
  assert.equal(rejectedRebuildGet.destroys, 0, 'normal rebuild-rejection response must remain intact');

  const {createServer: createViteServer} = require('vite');
  let resolveUpstreamStarted;
  let resolveUpstreamClosed;
  const upstreamStarted = new Promise((resolve) => { resolveUpstreamStarted = resolve; });
  const upstreamClosed = new Promise((resolve) => { resolveUpstreamClosed = resolve; });
  const upstream = http.createServer((_request, response) => {
    const completion = setTimeout(() => response.end('late response'), 3_000);
    response.once('close', () => {
      clearTimeout(completion);
      if (!response.writableEnded) resolveUpstreamClosed(true);
    });
    resolveUpstreamStarted();
  });
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  const upstreamAddress = upstream.address();
  assert.equal(typeof upstreamAddress, 'object');
  const vite = await createViteServer({
    configFile: false,
    appType: 'custom',
    logLevel: 'silent',
    optimizeDeps: {noDiscovery: true, include: []},
    server: {
      host: '127.0.0.1',
      port: 0,
      strictPort: false,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${upstreamAddress.port}`,
          changeOrigin: true,
          configure: configureEvidenceRegistryProxyCancellation,
        },
      },
    },
  });
  try {
    await vite.listen();
    const viteAddress = vite.httpServer.address();
    assert.equal(typeof viteAddress, 'object');
    const client = http.get(`http://127.0.0.1:${viteAddress.port}/api/research/evidence-registry?view=summary`);
    client.on('error', () => {});
    await upstreamStarted;
    client.destroy();
    const propagated = await Promise.race([
      upstreamClosed,
      new Promise((resolve) => setTimeout(() => resolve(false), 1_000)),
    ]);
    assert.equal(propagated, true, 'Vite registry proxy must propagate downstream cancellation upstream');
  } finally {
    await vite.close();
    await new Promise((resolve) => upstream.close(resolve));
  }
}

console.log(JSON.stringify({status: 'passed', tests: 17}));
