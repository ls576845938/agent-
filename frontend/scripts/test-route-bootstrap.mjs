import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import react from '@vitejs/plugin-react';
import ts from 'typescript';
import {build} from 'vite';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appPath = path.join(frontendRoot, 'src', 'App.tsx');
const entryPath = path.join(frontendRoot, 'src', 'main.tsx');
const normalizePath = (value) => value?.replaceAll('\\', '/');
const baselineAppRef = process.env.ROUTE_BOOTSTRAP_BASE_REF;
const baselineAppSource = baselineAppRef
  ? execFileSync(
      'git',
      ['show', `${baselineAppRef}:frontend/src/App.tsx`],
      {cwd: path.resolve(frontendRoot, '..'), encoding: 'utf8'},
    )
  : null;

const baselineAppPlugin = {
  name: 'route-bootstrap-baseline-app',
  enforce: 'pre',
  load(id) {
    if (baselineAppSource && normalizePath(id) === normalizePath(appPath)) return baselineAppSource;
    return null;
  },
};

const workspaceEntries = [
  'CryptoWorkspace.tsx',
  'CNEquityWorkspace.tsx',
  'USEquityWorkspace.tsx',
  'ExecutionSafetyRoute.tsx',
  'StrategyExplorer.tsx',
  'StrategyModulesWorkspace.tsx',
  'ResearchDashboard.tsx',
  'PortfolioMonitor.tsx',
  'ArchitectureMapWorkspace.tsx',
];

const iconNames = [
  'ArrowsOut',
  'CaretDown',
  'ChartLineUp',
  'ClipboardText',
  'Database',
  'FileMagnifyingGlass',
  'GearSix',
  'List',
  'Lock',
  'MagnifyingGlass',
  'ShieldCheck',
  'SlidersHorizontal',
  'SquaresFour',
  'Target',
  'WarningCircle',
  'X',
];

const result = await build({
  configFile: false,
  root: frontendRoot,
  logLevel: 'silent',
  define: {
    __QUANT_FRONTEND_IDENTITY__: JSON.stringify({
      schema_version: 'quant_frontend_runtime_identity_v1',
      release_id: 'route-bootstrap-test',
      fingerprint: 'test-fingerprint',
      configured_fingerprint: 'test-fingerprint',
      source_head: 'test-head',
      frontend_src_tree: 'test-tree',
      canonical_branch: 'main',
      canonical_port: 3000,
      canonical: false,
      manifest_match: false,
      worktree: 'route-bootstrap-test',
    }),
  },
  plugins: [baselineAppPlugin, react()],
  build: {
    write: false,
    minify: false,
    rollupOptions: {input: entryPath},
  },
});

assert.ok(!Array.isArray(result), 'expected one Vite build output');
const chunks = result.output.filter((item) => item.type === 'chunk');
const appChunk = chunks.find((chunk) =>
  chunk.isEntry && normalizePath(chunk.facadeModuleId) === normalizePath(entryPath));
assert.ok(appChunk, 'main.tsx entry chunk was not emitted');

const chunkByFileName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
const staticChunkNames = new Set();
const visitStaticImports = (chunk) => {
  if (staticChunkNames.has(chunk.fileName)) return;
  staticChunkNames.add(chunk.fileName);
  for (const importedFile of chunk.imports) {
    const importedChunk = chunkByFileName.get(importedFile);
    if (importedChunk) visitStaticImports(importedChunk);
  }
};
visitStaticImports(appChunk);

const initialModuleIds = new Set(
  [...staticChunkNames].flatMap((fileName) => Object.keys(chunkByFileName.get(fileName)?.modules ?? {})),
);

for (const workspaceEntry of workspaceEntries) {
  const normalizedSuffix = `/src/workspaces/${workspaceEntry}`;
  const eagerMatch = [...initialModuleIds].find((id) => normalizePath(id).endsWith(normalizedSuffix));
  assert.equal(eagerMatch, undefined, `${workspaceEntry} leaked into the initial App execution graph`);

  const dynamicChunk = chunks.find((chunk) =>
    chunk.isDynamicEntry
      && normalizePath(chunk.facadeModuleId)?.endsWith(normalizedSuffix));
  const dynamicFacades = chunks
    .filter((chunk) => chunk.isDynamicEntry)
    .map((chunk) => normalizePath(chunk.facadeModuleId) ?? `<no facade:${chunk.fileName}>`);
  assert.ok(
    dynamicChunk,
    `${workspaceEntry} was not emitted as a route-level dynamic entry; dynamic facades: ${dynamicFacades.join(', ')}`,
  );
}

await Promise.all(iconNames.map(async (iconName) => {
  const module = await import(`@phosphor-icons/react/dist/csr/${iconName}`);
  assert.ok(Object.keys(module).length > 0, `CSR icon module ${iconName} has no exports`);
}));

const appSourceFile = ts.createSourceFile(
  appPath,
  readFileSync(appPath, 'utf8'),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const routeIdentityKeys = [];
const visit = (node) => {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(appSourceFile) === 'LazyWorkspace') {
    const keyAttribute = node.attributes.properties.find((attribute) =>
      ts.isJsxAttribute(attribute) && attribute.name.getText(appSourceFile) === 'key');
    assert.ok(keyAttribute && ts.isJsxAttribute(keyAttribute), 'LazyWorkspace is missing a stable route identity key');
    assert.ok(
      keyAttribute.initializer && ts.isStringLiteral(keyAttribute.initializer),
      'LazyWorkspace route identity key must be a stable string literal',
    );
    routeIdentityKeys.push(keyAttribute.initializer.text);
  }
  ts.forEachChild(node, visit);
};
visit(appSourceFile);

assert.equal(routeIdentityKeys.length, workspaceEntries.length, 'every route dynamic entry must have a route identity key');
assert.equal(new Set(routeIdentityKeys).size, workspaceEntries.length, 'route identity keys must be unique');

console.log('route bootstrap regression passed: 9 lazy route chunks have isolated identities and 16 CSR icon modules resolve');
