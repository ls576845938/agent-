import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {inventory, validateArchitectureKnowledge} from './architecture-review.mjs';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const read = path => readFileSync(resolve(root, path), 'utf8');
const catalog = JSON.parse(read('frontend/src/workspaces/architecture/catalog.json'));
const knowledge = JSON.parse(read('frontend/src/workspaces/architecture/knowledge.json'));

test('layered knowledge covers the catalog with versioned file evidence', () => {
  const source = inventory(knowledge.source_commit).files;
  assert.deepEqual(validateArchitectureKnowledge(knowledge, catalog, source, inventory('HEAD').files), []);
  assert.equal(knowledge.modules.length, 25);
  assert.equal(knowledge.core_files.length, 28);
  assert.equal(knowledge.file_groups.length, 10);
  assert.ok(Object.values(knowledge.safety).every(value => value === false));
});

test('a copied or missing blob cannot certify a core file card', () => {
  const bad = structuredClone(knowledge);
  bad.core_files[0].source_blob = '0'.repeat(40);
  const errors = validateArchitectureKnowledge(bad, catalog, inventory(knowledge.source_commit).files);
  assert.ok(errors.includes(`knowledge_core_file_stale:${bad.core_files[0].path}`));
});

test('consumer and test references must exist and stay within committed line bounds', () => {
  const bad = structuredClone(knowledge);
  bad.core_files[0].consumers = ['backend/app/not-real.py:999999'];
  const errors = validateArchitectureKnowledge(
    bad, catalog, inventory(knowledge.source_commit).files, inventory('HEAD').files,
  );
  assert.ok(errors.includes(`knowledge_core_file_reference_invalid:${bad.core_files[0].path}:backend/app/not-real.py`));
});

test('module omissions, unknown links and optimistic safety are rejected', () => {
  const bad = structuredClone(knowledge);
  bad.modules.shift();
  bad.modules[0].downstream.push('not-a-module');
  bad.safety.order = true;
  const errors = validateArchitectureKnowledge(bad, catalog);
  assert.ok(errors.some(error => error.startsWith('knowledge_module_missing:')));
  assert.ok(errors.some(error => error.includes('not-a-module')));
  assert.ok(errors.includes('knowledge_safety_flags_must_remain_false'));
});

test('the architecture knowledge UI remains local and read-only', () => {
  const component = read('frontend/src/workspaces/architecture/ArchitectureKnowledge.tsx');
  assert.match(component, /分层架构说明/);
  assert.match(component, /职责说明 ≠ 已跑通调用链/);
  assert.match(component, /市场状态 v2 与历史诊断已实现/);
  assert.match(component, /conditioned 在 1956 \/ 2960/);
  assert.match(component, /M3—M4 未启动/);
  assert.match(component, /候选离线 worker 默认关闭/);
  assert.match(component, /真实账户只读验收未完成/);
  assert.match(component, /研究读取链 11 \/ 11/);
  assert.match(component, /版本化源码快照 · 是否变动以增量校验为准/);
  assert.doesNotMatch(component, /source_head/);
  assert.doesNotMatch(component, /fetch\(|axios|method:\s*['"]POST/);
});
