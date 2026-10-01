import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {validateCatalog, compareInventory} from './architecture-review.mjs';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const catalog = JSON.parse(readFileSync(resolve(root, 'frontend/src/workspaces/architecture/catalog.json'), 'utf8'));
test('atlas is a source review, never a trading or runtime receipt', () => {
  assert.deepEqual(validateCatalog(catalog), []);
  assert.equal(catalog.review_status, 'in_progress');
  assert.ok(catalog.files.length > 0);
  assert.ok(catalog.files.some(file => file.status === 'fully_read'));
  assert.ok(Object.values(catalog.safety).every(value => value === false));
});
test('inventory does not imply reading and drift invalidates reviewed content', () => {
  const baseline = [{path: 'a.py', blob: 'a'.repeat(40), status: 'fully_read'}, {path: 'b.py', blob: 'b'.repeat(40), status: 'unread'}];
  const current = [{path: 'a.py', blob: 'c'.repeat(40)}, {path: 'c.py', blob: 'd'.repeat(40)}];
  const result = compareInventory(baseline, current);
  assert.deepEqual(result.changed, ['a.py']);
  assert.deepEqual(result.deleted, ['b.py']);
  assert.deepEqual(result.added, ['c.py']);
  assert.deepEqual(result.review_invalidated, ['a.py']);
});
test('review coverage cannot be forged by a partial range or missing reader', () => {
  const bad = structuredClone(catalog);
  const file = bad.files.find(file => file.status === 'fully_read' && file.lines > 1);
  file.read_ranges = [[1, 1]];
  file.reader = '';
  assert.ok(validateCatalog(bad).some(error => error.includes(file.path)));
});
test('source files and evidence references use contained repository paths', () => {
  const bad = structuredClone(catalog);
  bad.files[0].path = '../secret';
  assert.ok(validateCatalog(bad).length > 0);
});
test('research legacy rollback entrypoints are preserved', () => {
  const route = readFileSync(resolve(root, 'frontend/src/workspaces/ResearchDashboard.tsx'), 'utf8');
  assert.match(route, /layout === 'previous'/);
  assert.match(route, /layout === 'legacy'/);
});

test('copied hashes cannot certify forged source line counts', () => {
  const bad = structuredClone(catalog);
  bad.files[0].lines += 1;
  assert.ok(validateCatalog(bad, catalog.files).some(error => error.startsWith('baseline_object_mismatch:')));
});

test('missing or optimistic safety fields are rejected', () => {
  for (const value of [true, null, 'false', undefined]) {
    const bad = structuredClone(catalog);
    bad.safety.order = value;
    assert.ok(validateCatalog(bad).includes('safety_flags_must_remain_false'));
  }
});

test('a source-reviewed edge requires an actually fully read source', () => {
  const bad = structuredClone(catalog);
  // Construct an unread fixture; the real inventory may now be fully read.
  const file = bad.files.find(file => file.lines > 0);
  file.status = 'unread';
  delete file.reader;
  delete file.batch;
  delete file.read_ranges;
  bad.edges[0].sources = [{path: file.path, line: 1}];
  bad.edges[0].status = 'source_reviewed';
  assert.ok(validateCatalog(bad).some(error => error.startsWith('edge_source_not_fully_read:')));
});

test('complete source coverage does not certify runtime or trading readiness', () => {
  const completeSource = structuredClone(catalog);
  for (const file of completeSource.files) {
    file.status = 'fully_read';
    file.reader = 'test-fixture';
    file.batch = 'synthetic-complete-coverage';
    file.read_ranges = file.lines ? [[1, file.lines]] : [];
  }
  assert.deepEqual(validateCatalog(completeSource, catalog.files), []);
  assert.ok(Object.values(completeSource.safety).every(value => value === false));
  completeSource.review_status = 'complete';
  assert.ok(validateCatalog(completeSource).includes('whole_repository_review_not_certified'));
});
