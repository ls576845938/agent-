// Read-only Git-object inventory and incremental architecture-review verification.
// Inventory is metadata extraction, not a claim that a person read the code.
import {execFileSync, spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export const CODE_ROOTS = ['quant_shared/', 'quant_crypto/', 'quant_us/', 'quant_cn/',
  'integrations/', 'backend/', 'frontend/', 'scripts/', 'tests/', 'tools/', 'schemas/',
  'configs/', 'config/', 'legacy_strategies/', 'alpha-radar/', 'deploy/', '.github/', '.codex/', '.agents/'];
export const CODE_EXTENSIONS = /\.(py|tsx?|jsx?|mjs|cjs|css|scss|html|ps1|cmd|bat|sh|sql|toml|ya?ml|json)$/i;
const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const catalogPath = resolve(root, 'frontend/src/workspaces/architecture/catalog.json');
const knowledgePath = resolve(root, 'frontend/src/workspaces/architecture/knowledge.json');
const git = (...args) => execFileSync('git', ['-C', root, ...args], {encoding: 'utf8', windowsHide: true, maxBuffer: 32 * 1024 * 1024});
export function containedPath(path) {
  return typeof path === 'string' && path.length > 0 && !path.includes('\\') && !path.startsWith('/')
    && !path.includes(':') && !path.split('/').some(part => !part || part === '.' || part === '..');
}
export function inScope(path) {
  return containedPath(path) && CODE_EXTENSIONS.test(path)
    && (CODE_ROOTS.some(prefix => path.startsWith(prefix)) || !path.includes('/'))
    && !/(^|\/)(node_modules|dist|build|coverage|__pycache__)(\/|$)/.test(path)
    && !/(^|\/)(package-lock\.json|pnpm-lock\.yaml|frontend-identity\.json)$/.test(path)
    && !/(^|\/)(\.env(?:\.|$)|credentials\.(json|ya?ml|toml)$|secrets?\.(json|ya?ml|toml)$)/i.test(path);
}
export function inventory(ref = 'HEAD') {
  const commit = git('rev-parse', '--verify', `${ref}^{commit}`).trim();
  const rows = git('ls-tree', '-r', '-z', '-l', '--full-tree', commit).split('\0').filter(Boolean);
  const files = rows.flatMap(row => {
    const [meta, path] = row.split('\t');
    const [, type, blob, bytes] = meta.trim().split(/\s+/);
    return type === 'blob' && inScope(path) ? [{path, blob, bytes: Number(bytes)}] : [];
  });
  const result = spawnSync('git', ['-C', root, 'cat-file', '--batch'], {
    input: files.map(file => file.blob).join('\n') + '\n', windowsHide: true,
    maxBuffer: 192 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) throw result.error || new Error('git_object_inventory_failed');
  let offset = 0;
  for (const file of files) {
    const end = result.stdout.indexOf(10, offset);
    const [blob, type, length] = result.stdout.subarray(offset, end).toString().split(' ');
    if (blob !== file.blob || type !== 'blob') throw new Error('git_object_identity_mismatch');
    const body = result.stdout.subarray(end + 1, end + 1 + Number(length));
    // Opaque/LFS objects remain inventoried, never counted as readable source.
    const text = body.toString('utf8');
    file.lines = body.includes(0) || text.startsWith('version https://git-lfs.github.com/spec/') ? null
      : text.length ? text.split('\n').length - (text.endsWith('\n') ? 1 : 0) : 0;
    offset = end + 1 + Number(length) + 1;
  }
  return {source_commit: commit, files};
}
export function compareInventory(baseline, current) {
  const before = new Map(baseline.map(file => [file.path, file]));
  const after = new Map(current.map(file => [file.path, file]));
  const changed = current.filter(file => before.has(file.path) && before.get(file.path).blob !== file.blob).map(file => file.path);
  const deleted = baseline.filter(file => !after.has(file.path)).map(file => file.path);
  return {changed, deleted, added: current.filter(file => !before.has(file.path)).map(file => file.path),
    review_invalidated: [...changed, ...deleted].filter(path => before.get(path).status === 'fully_read')};
}
export function validateCatalog(catalog, expectedFiles) {
  const errors = [];
  if (catalog.schema_version !== 'architecture_code_map_v1') errors.push('schema_invalid');
  if (catalog.review_status !== 'in_progress') errors.push('whole_repository_review_not_certified');
  if (!/^[a-f0-9]{40}$/.test(catalog.source_commit || '')) errors.push('source_commit_invalid');
  const requiredSafety = ['promotion', 'paper', 'live', 'private', 'order', 'real_order', 'transfer', 'withdraw', 'runtime_verified'];
  if (requiredSafety.some(key => catalog.safety?.[key] !== false)) errors.push('safety_flags_must_remain_false');
  const files = new Map();
  for (const file of catalog.files || []) {
    if (!containedPath(file.path) || files.has(file.path)) errors.push(`file_path_invalid:${file.path}`);
    files.set(file.path, file);
    if (!/^[a-f0-9]{40}$/.test(file.blob || '')) errors.push(`file_blob_invalid:${file.path}`);
    if (!['fully_read', 'unread'].includes(file.status)) errors.push(`file_status_invalid:${file.path}`);
    if (file.status === 'fully_read') {
      if (!file.reader || !file.batch || !Number.isInteger(file.lines) || file.lines < 0) errors.push(`file_review_invalid:${file.path}`);
      let next = 1;
      for (const range of file.read_ranges || []) {
        if (range.length !== 2 || !range.every(Number.isInteger) || range[0] !== next || range[1] < range[0]) errors.push(`file_range_invalid:${file.path}`);
        next = range[1] + 1;
      }
      if (next !== file.lines + 1) errors.push(`file_coverage_incomplete:${file.path}`);
    } else if (file.reader || file.read_ranges?.length) errors.push(`inventory_must_not_claim_reading:${file.path}`);
  }
  const modules = new Set((catalog.modules || []).map(module => module.id));
  if (modules.size !== catalog.modules?.length) errors.push('module_ids_invalid');
  if (expectedFiles) {
    const expected = new Map(expectedFiles.map(file => [file.path, file]));
    if (expected.size !== files.size) errors.push('baseline_inventory_size_mismatch');
    for (const file of files.values()) {
      const object = expected.get(file.path);
      if (!object || ['blob', 'lines', 'bytes'].some(key => file[key] !== object[key])) {
        errors.push('baseline_object_mismatch:' + file.path);
      }
    }
  }
  for (const edge of catalog.edges || []) {
    if (!modules.has(edge.from) || !modules.has(edge.to)) errors.push(`edge_endpoint_invalid:${edge.id}`);
    if (!['source_reviewed', 'reference_located'].includes(edge.status)) errors.push(`edge_status_invalid:${edge.id}`);
    if (!edge.sources?.length) errors.push(`edge_source_missing:${edge.id}`);
    for (const source of edge.sources || []) {
      const file = files.get(source.path);
      if (!file || !Number.isInteger(source.line) || source.line < 1 || source.line > file.lines) errors.push(`edge_source_invalid:${edge.id}`);
      if (edge.status === 'source_reviewed' && file?.status !== 'fully_read') errors.push(`edge_source_not_fully_read:${edge.id}`);
    }
  }
  return errors;
}
function sourceReference(value) {
  const match = String(value).match(/^([^:]+\.(?:py|tsx?|jsx?|mjs|cjs|ps1|cmd|json))(?:\:(\d+(?:,\d+)*))?(?:::.*)?$/i);
  return match ? {path: match[1], lines: (match[2] || '').split(',').filter(Boolean).map(Number)} : null;
}
export function validateArchitectureKnowledge(knowledge, catalog, sourceFiles, referenceFiles = sourceFiles) {
  const errors = [];
  if (knowledge.schema_version !== 'architecture_knowledge_v1') errors.push('knowledge_schema_invalid');
  if (!/^[a-f0-9]{40}$/.test(knowledge.source_commit || '')) errors.push('knowledge_source_commit_invalid');
  if (!knowledge.scope_note?.trim()) errors.push('knowledge_scope_note_missing');
  const catalogIds = new Set((catalog.modules || []).map(module => module.id));
  const moduleIds = new Set();
  for (const item of knowledge.modules || []) {
    if (!catalogIds.has(item.module_id) || moduleIds.has(item.module_id)) errors.push(`knowledge_module_invalid:${item.module_id}`);
    moduleIds.add(item.module_id);
    for (const field of ['inputs', 'outputs', 'entrypoints']) {
      if (!Array.isArray(item[field]) || !item[field].length || item[field].some(value => !String(value).trim())) {
        errors.push(`knowledge_module_${field}_missing:${item.module_id}`);
      }
    }
    if (!item.boundary?.trim()) errors.push(`knowledge_module_boundary_missing:${item.module_id}`);
    for (const relation of [...(item.upstream || []), ...(item.downstream || [])]) {
      if (!catalogIds.has(relation) || relation === item.module_id) errors.push(`knowledge_module_relation_invalid:${item.module_id}:${relation}`);
    }
  }
  for (const id of catalogIds) if (!moduleIds.has(id)) errors.push(`knowledge_module_missing:${id}`);
  if (moduleIds.size !== catalogIds.size) errors.push('knowledge_module_coverage_mismatch');

  const source = sourceFiles ? new Map(sourceFiles.map(file => [file.path, file])) : null;
  const references = referenceFiles ? new Map(referenceFiles.map(file => [file.path, file])) : null;
  const cards = new Set();
  const coreFiles = knowledge.core_files || [];
  if (coreFiles.length < 24 || coreFiles.length > 32) errors.push('knowledge_core_file_count_invalid');
  for (const card of coreFiles) {
    if (!containedPath(card.path) || cards.has(card.path)) errors.push(`knowledge_core_file_path_invalid:${card.path}`);
    cards.add(card.path);
    if (!catalogIds.has(card.module_id)) errors.push(`knowledge_core_file_module_invalid:${card.path}`);
    for (const field of ['purpose', 'entry', 'side_effects', 'forbidden']) {
      if (!card[field]?.trim()) errors.push(`knowledge_core_file_${field}_missing:${card.path}`);
    }
    for (const field of ['consumers', 'tests']) {
      if (!Array.isArray(card[field]) || !card[field].length || card[field].some(value => !String(value).trim())) {
        errors.push(`knowledge_core_file_${field}_missing:${card.path}`);
      }
      for (const value of card[field] || []) {
        const reference = sourceReference(value);
        if (!reference) continue;
        const file = references?.get(reference.path);
        if (references && (!file || reference.lines.some(line => !Number.isInteger(file.lines) || line < 1 || line > file.lines))) {
          errors.push(`knowledge_core_file_reference_invalid:${card.path}:${reference.path}`);
        }
      }
    }
    if (!/^[a-f0-9]{40}$/.test(card.source_blob || '')) errors.push(`knowledge_core_file_blob_invalid:${card.path}`);
    if (card.source_commit !== knowledge.source_commit) errors.push(`knowledge_core_file_commit_invalid:${card.path}`);
    const object = source?.get(card.path);
    if (source && (!object || object.blob !== card.source_blob)) errors.push(`knowledge_core_file_stale:${card.path}`);
  }

  const groups = new Set();
  if ((knowledge.file_groups || []).length < 8) errors.push('knowledge_file_group_count_invalid');
  for (const group of knowledge.file_groups || []) {
    if (!group.id?.trim() || groups.has(group.id)) errors.push(`knowledge_file_group_id_invalid:${group.id}`);
    groups.add(group.id);
    if (!group.label?.trim() || !group.purpose?.trim() || !group.patterns?.length || !group.modules?.length) {
      errors.push(`knowledge_file_group_content_missing:${group.id}`);
    }
    for (const id of group.modules || []) if (!catalogIds.has(id)) errors.push(`knowledge_file_group_module_invalid:${group.id}:${id}`);
  }
  if (Object.values(knowledge.safety || {}).length === 0 || Object.values(knowledge.safety || {}).some(value => value !== false)) {
    errors.push('knowledge_safety_flags_must_remain_false');
  }
  return errors;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const ref = process.argv.find(value => value.startsWith('--ref='))?.slice(6) || 'HEAD';
    if (process.argv.includes('--inventory')) {
      process.stdout.write(JSON.stringify(inventory(ref)) + '\n');
    } else {
      const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
      const errors = validateCatalog(catalog, inventory(catalog.source_commit).files);
      const current = inventory(ref);
      const knowledge = JSON.parse(readFileSync(knowledgePath, 'utf8'));
      const knowledgeErrors = validateArchitectureKnowledge(knowledge, catalog, inventory(knowledge.source_commit).files, current.files);
      const diff = compareInventory(catalog.files, current.files);
      const sourceConsistent = !diff.changed.length && !diff.deleted.length && !diff.added.length;
      const output = {schema_version: 'architecture_review_diff_v1', baseline_commit: catalog.source_commit,
        compared_commit: current.source_commit, catalog_errors: errors, knowledge_errors: knowledgeErrors,
        architecture_knowledge_source_commit: knowledge.source_commit, source_inventory_unchanged: sourceConsistent,
        reviewed_files: catalog.files.filter(file => file.status === 'fully_read').length,
        total_files: catalog.files.length, ...diff, runtime_verified: false, trading_permission: false};
      process.stdout.write(JSON.stringify(output, null, 2) + '\n');
      if (errors.length || knowledgeErrors.length || !sourceConsistent) process.exitCode = 1;
    }
  } catch (error) {
    process.stderr.write(String(error.message || error) + '\n');
    process.exitCode = 2;
  }
}
