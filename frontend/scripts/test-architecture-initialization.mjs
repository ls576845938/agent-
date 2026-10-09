import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';

import react from '@vitejs/plugin-react';
import ts from 'typescript';
import {build} from 'vite';

import {arrangeBtcPanorama} from '../src/workspaces/architecture/btcPanoramaLayout.ts';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(frontendRoot, '..');
const workspacePath = path.join(frontendRoot, 'src', 'workspaces', 'ArchitectureMapWorkspace.tsx');
const layoutPath = path.join(frontendRoot, 'src', 'workspaces', 'architecture', 'btcPanoramaLayout.ts');
const normalizePath = value => value?.replaceAll('\\', '/');
const baselineRef = process.env.ARCHITECTURE_INIT_BASE_REF;

const sourceAt = (repoPath) => baselineRef
  ? execFileSync('git', ['show', `${baselineRef}:${repoPath}`], {cwd: repoRoot, encoding: 'utf8'})
  : readFileSync(path.join(repoRoot, repoPath), 'utf8');

const workspaceSource = sourceAt('frontend/src/workspaces/ArchitectureMapWorkspace.tsx');
const modelSource = sourceAt('frontend/src/workspaces/architecture/model.ts');
const catalog = JSON.parse(sourceAt('frontend/src/workspaces/architecture/catalog.json'));
const injectedSources = new Map([
  [normalizePath(workspacePath), workspaceSource],
  [normalizePath(layoutPath), sourceAt('frontend/src/workspaces/architecture/btcPanoramaLayout.ts')],
]);
const baselineSourcePlugin = {
  name: 'architecture-initialization-baseline-source',
  enforce: 'pre',
  load(id) {
    return injectedSources.get(normalizePath(id)) ?? null;
  },
};

const sourceFile = ts.createSourceFile(
  workspacePath,
  workspaceSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const modelSourceFile = ts.createSourceFile(
  'model.ts',
  modelSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TS,
);
let byModuleInitializer;
let moduleOfDeclaration;
const findByModule = (node) => {
  if (ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.name.text === 'byModule') {
    byModuleInitializer = node.initializer;
  }
  ts.forEachChild(node, findByModule);
};
findByModule(sourceFile);
assert.ok(byModuleInitializer, 'ArchitectureMapWorkspace must declare byModule');
const findModuleOf = (node) => {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'moduleOf') moduleOfDeclaration = node;
  ts.forEachChild(node, findModuleOf);
};
findModuleOf(modelSourceFile);
assert.ok(moduleOfDeclaration, 'architecture model must declare moduleOf');

const executableModuleOf = ts.transpileModule(
  `${moduleOfDeclaration.getText(modelSourceFile).replace(/^export\s+/, '')}\nreturn moduleOf;`,
  {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None}},
).outputText;
const moduleOf = new Function('catalog', executableModuleOf)(catalog);

const executableGrouping = ts.transpileModule(
  `const byModule = ${byModuleInitializer.getText(sourceFile)};\nreturn byModule;`,
  {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None}},
).outputText;

let moduleOfCalls = 0;
const actualByModule = new Function('catalog', 'moduleOf', 'useMemo', executableGrouping)(
  catalog,
  pathValue => {
    moduleOfCalls += 1;
    return moduleOf(pathValue);
  },
  factory => factory(),
);

const expectedByModule = new Map(catalog.modules.map(module => [
  module.id,
  catalog.files.filter(file => moduleOf(file.path) === module.id),
]));

const buildResult = await build({
  configFile: false,
  root: frontendRoot,
  logLevel: 'silent',
  plugins: [baselineSourcePlugin, react()],
  build: {
    write: false,
    minify: false,
    rollupOptions: {input: layoutPath, treeshake: false},
  },
});
assert.ok(!Array.isArray(buildResult), 'expected one Vite build output');
const chunks = buildResult.output.filter(item => item.type === 'chunk');
const entryChunk = chunks.find(chunk =>
  chunk.isEntry && normalizePath(chunk.facadeModuleId) === normalizePath(layoutPath));
assert.ok(entryChunk, 'btcPanoramaLayout entry chunk was not emitted');
const chunkByFileName = new Map(chunks.map(chunk => [chunk.fileName, chunk]));
const staticChunkNames = new Set();
const visitStaticImports = (chunk) => {
  if (staticChunkNames.has(chunk.fileName)) return;
  staticChunkNames.add(chunk.fileName);
  for (const importedFile of chunk.imports) {
    const importedChunk = chunkByFileName.get(importedFile);
    if (importedChunk) visitStaticImports(importedChunk);
  }
};
visitStaticImports(entryChunk);
const initialModuleIds = new Set(
  [...staticChunkNames].flatMap(fileName => Object.keys(chunkByFileName.get(fileName)?.modules ?? {})),
);
const elkModuleIds = chunks.flatMap(chunk => Object.keys(chunk.modules))
  .filter(id => normalizePath(id).includes('/node_modules/elkjs/'));

test('architecture catalog groups files once while preserving the previous moduleOf result and order', () => {
  assert.equal(moduleOfCalls, catalog.files.length, 'moduleOf must run exactly once per catalog file');
  assert.deepEqual([...actualByModule.keys()], catalog.modules.map(module => module.id));
  for (const module of catalog.modules) {
    assert.deepEqual(actualByModule.get(module.id), expectedByModule.get(module.id), module.id);
  }

  assert.equal(moduleOf('scripts/tie-check.py'), 'quality');
  assert.equal(moduleOf('schemas/tie-check.json'), 'quality');
  assert.equal(moduleOf('alpha-radar/tie-check.ts'), 'legacy');
  for (const emptyBucket of ['operation_scripts', 'evidence_schemas', 'legacy_audit']) {
    assert.deepEqual(actualByModule.get(emptyBucket), [], `${emptyBucket} must remain an empty bucket`);
  }

  const unmatchedFiles = catalog.files.filter(file => !catalog.modules.some(module =>
    module.roots.some(prefix => file.path.startsWith(prefix))));
  assert.ok(unmatchedFiles.length > 0, 'catalog fixture must exercise the legacy fallback');
  assert.deepEqual(
    actualByModule.get('legacy').filter(file => unmatchedFiles.includes(file)),
    unmatchedFiles,
    'unmatched files must retain their order in the legacy fallback bucket',
  );
});

test('ELK stays outside the static architecture initialization graph', () => {
  assert.ok(elkModuleIds.length > 0, 'the build must still emit the explicitly requested ELK implementation');
  const eagerElk = [...initialModuleIds].find(id => normalizePath(id).includes('/node_modules/elkjs/'));
  assert.equal(eagerElk, undefined, 'ELK leaked into the static btcPanoramaLayout graph');
});

test('explicit BTC panorama arrangement still loads ELK and returns an arranged graph', async () => {
  const nodes = [
    {id: 'group-data', position: {x: 0, y: 0}, style: {width: 480, height: 420}, data: {kind: 'group'}},
    {id: 'source', parentId: 'group-data', position: {x: 0, y: 0}, style: {width: 160, height: 80}, data: {kind: 'node'}},
    {id: 'target', parentId: 'group-data', position: {x: 0, y: 0}, style: {width: 160, height: 80}, data: {kind: 'node'}},
  ];
  const edges = [{id: 'source-target', source: 'source', target: 'target', label: 'test'}];
  const arranged = await arrangeBtcPanorama(nodes, edges);
  assert.equal(arranged.nodes.length, nodes.length);
  assert.equal(arranged.routes.size, edges.length);
  assert.ok(arranged.routes.get('source-target')?.points.length >= 2);
});
