import {defineConfig, type ProxyOptions} from 'vite';
import react from '@vitejs/plugin-react';
import {candidateLocalGuardPlugin} from './scripts/candidate-local-guard.mjs';

import {
  assertCanonicalServe,
  buildFrontendRuntimeDriftClientScript,
  createFrontendRuntimeGuard,
  inspectFrontendIdentity,
  inspectFrontendIdentityAsync,
} from './scripts/frontend-identity-lib.mjs';

function requestedPort(defaultPort: number) {
  const equalsArgument = process.argv.find(argument => argument.startsWith('--port='));
  if (equalsArgument) return Number(equalsArgument.slice('--port='.length));
  const index = process.argv.indexOf('--port');
  if (index >= 0 && process.argv[index + 1]) return Number(process.argv[index + 1]);
  return defaultPort;
}

type ProxyConfigure = NonNullable<ProxyOptions['configure']>;

export const configureEvidenceRegistryProxyCancellation: ProxyConfigure = (proxy) => {
  proxy.on('proxyReq', (proxyRequest, request, response) => {
    const requestPath = String(request.url || '').split('?', 1)[0];
    if (String(request.method || '').toUpperCase() !== 'GET'
      || requestPath !== '/api/research/evidence-registry') return;

    const responseClosed = response.destroyed
      || Boolean((response as typeof response & {closed?: boolean}).closed);
    if (responseClosed) {
      if (!proxyRequest.destroyed) proxyRequest.destroy();
      return;
    }

    let responseFinished = false;
    const cleanup = () => {
      response.off('finish', onFinish);
      response.off('close', onClose);
    };
    const onFinish = () => {
      responseFinished = true;
      cleanup();
    };
    const onClose = () => {
      const cancelled = !responseFinished && !response.writableEnded;
      cleanup();
      if (cancelled && !proxyRequest.destroyed) proxyRequest.destroy();
    };
    response.once('finish', onFinish);
    response.once('close', onClose);
  });
};

export default defineConfig(({command}) => {
  const inspection = inspectFrontendIdentity(process.cwd(), {requireClean: false});
  const port = requestedPort(inspection.manifest.canonical_port);
  let serveInspection = inspection;

  if (command === 'serve') {
    serveInspection = inspectFrontendIdentity(process.cwd(), {requireClean: true});
    assertCanonicalServe(serveInspection, port);
  }

  const runtimeIdentity = serveInspection.runtime_identity;
  const runtimeGuard = createFrontendRuntimeGuard({
    launchedIdentity: runtimeIdentity,
    inspectCurrent: () => inspectFrontendIdentityAsync(process.cwd(), {requireClean: true}),
  });

  const identityPlugin = {
    name: 'quant-frontend-canonical-identity',
    configureServer(server: {middlewares: {use: (handler: (request: {url?: string}, response: {
      statusCode: number;
      setHeader: (name: string, value: string) => void;
      end: (body: string) => void;
    }, next: () => void) => void) => void}}) {
      server.middlewares.use((request, response, next) => {
        void runtimeGuard.middleware(request, response, next);
      });
    },
    transformIndexHtml() {
      return [
        {
          tag: 'meta',
          attrs: {name: 'quant-frontend-fingerprint', content: runtimeIdentity.fingerprint},
          injectTo: 'head',
        },
        {
          tag: 'meta',
          attrs: {name: 'quant-frontend-source-head', content: runtimeIdentity.source_head},
          injectTo: 'head',
        },
        {
          tag: 'meta',
          attrs: {name: 'quant-frontend-canonical', content: String(runtimeIdentity.canonical)},
          injectTo: 'head',
        },
        {
          tag: 'script',
          attrs: {type: 'module'},
          children: buildFrontendRuntimeDriftClientScript(),
          injectTo: 'body',
        },
      ];
    },
  };

  return {
    define: {
      __QUANT_FRONTEND_IDENTITY__: JSON.stringify(runtimeIdentity),
    },
    plugins: [candidateLocalGuardPlugin(), react(), identityPlugin],
    server: {
      port: inspection.manifest.canonical_port,
      strictPort: true,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8765',
          changeOrigin: true,
          configure: configureEvidenceRegistryProxyCancellation,
        },
      },
    },
  };
});
