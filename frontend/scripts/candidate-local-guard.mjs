// Runs before Vite's changeOrigin proxy. Never trust forwarding headers.
import {isIP} from 'node:net';

const HOSTS = new Set(['127.0.0.1:3000', 'localhost:3000', '[::1]:3000']);
const INTENT = 'candidate-management';
const namespace = /^\/api\/(?:strategy-delivery|candidate-offline)(?:\/|$)/;

export function candidateNamespace(url) {
  let path = String(url || '').split('?')[0];
  for (let i = 0; i < 5; i++) {
    const normalized = path.replaceAll('\\', '/').replace(/\/+/g, '/');
    if (namespace.test(normalized)) return true;
    try {
      if (namespace.test(new URL(normalized, 'http://localhost').pathname)) return true;
      const next = decodeURIComponent(path);
      if (next === path) break;
      path = next;
    } catch { break; }
  }
  return false;
}

function loopback(peer) {
  if (peer === '::1') return true;
  if (peer?.startsWith('::ffff:')) peer = peer.slice(7);
  return isIP(peer || '') === 4 && peer.startsWith('127.');
}

function originOfReferer(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || url.hash) return '';
    return url.origin;
  } catch { return ''; }
}

export function candidateLocalGuard(req, res, next) {
  if (!candidateNamespace(req.url)) return next();
  const reject = () => {
    res.statusCode = 403;
    res.setHeader('Content-Type', 'application/json');
    res.end('{"detail":"candidate_proxy_local_request_rejected"}');
  };
  const path = String(req.url).split('?')[0];
  if (!namespace.test(path) || /[%\\]/.test(path) || path.includes('//') ||
      path.endsWith('/') || path.split('/').some(x => x === '.' || x === '..')) return reject();
  if (!loopback(req.socket?.remoteAddress)) return reject();
  const headers = new Map();
  const raw = req.rawHeaders;
  if (!Array.isArray(raw) || raw.length % 2) return reject();
  for (let i = 0; i < raw.length; i += 2) {
    const name = raw[i].toLowerCase(), value = raw[i + 1];
    if (!/^[a-z0-9-]+$/.test(name) || headers.has(name) ||
        /[^\x20-\x7e]/.test(value) || name === 'forwarded' || name.startsWith('x-forwarded-')) return reject();
    headers.set(name, value);
  }
  const host = headers.get('host'), origin = headers.get('origin');
  if (!HOSTS.has(host)) return reject();
  const trustedOrigin = 'http://' + host;
  if (origin !== undefined && origin !== trustedOrigin) return reject();
  // Existing key-only clients need no new intent/metadata headers.
  // The backend still validates the key; merely sending one cannot select its
  // local mode. New clients always send the non-secret intent.
  if (headers.get('x-api-key') && !headers.has('x-qs-candidate-intent')) return next();
  if (headers.get('x-qs-candidate-intent') !== INTENT) return reject();
  const metadata = [...headers].filter(([name]) => name.startsWith('sec-fetch-'));
  if (metadata.length) {
    if (metadata.length !== 3 || headers.get('sec-fetch-site') !== 'same-origin' ||
        !['cors', 'same-origin'].includes(headers.get('sec-fetch-mode')) ||
        headers.get('sec-fetch-dest') !== 'empty') return reject();
    if (origin === undefined && (req.method !== 'GET' ||
        originOfReferer(headers.get('referer')) !== trustedOrigin)) return reject();
  } else if (origin === undefined && headers.has('referer')) return reject();
  return next();
}

export function candidateLocalGuardPlugin() {
  return {
    name: 'candidate-local-proxy-boundary',
    enforce: 'pre',
    configureServer(server) {
      // Immediate registration, NOT a returned post-proxy hook.
      server.middlewares.use(candidateLocalGuard);
    },
    configurePreviewServer(server) {
      server.middlewares.use(candidateLocalGuard);
    },
  };
}
