import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

const read = (name) => fs.readFileSync(new URL(`../src/workspaces/crypto/${name}`, import.meta.url), 'utf8');
const source = read('DemoTradingConsole.tsx');
assert.match(read('PublicDepthPanel.tsx'), /hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3/, 'fractional seconds alone hides the clock fields');
const tree = ts.createSourceFile('console.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
for (const id of ['btc-demo-operator-v2-identity', 'btc-demo-start-attempt-binding']) {
  let folded = false;
  function visit(node, inDetails = false) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === 'details') {
      assert.ok(!node.openingElement.attributes.properties.some((attr) => attr.name?.getText(tree) === 'open'));
      inDetails = true;
    }
    if (ts.isJsxAttribute(node) && node.name.getText(tree) === 'data-testid' && node.initializer?.text === id) folded = inDetails;
    ts.forEachChild(node, (child) => visit(child, inDetails));
  }
  visit(tree);
  assert.ok(folded, `${id} must be collapsed by default`);
}
const mod = {exports: {}};
new Function('exports', ts.transpileModule(read('console-display.ts'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS},
}).outputText)(mod.exports);
const {guardianGuidance, depthSourceLabel} = mod.exports;
assert.match(guardianGuidance(undefined), /无法确认/);
assert.match(guardianGuidance({tripped: true}), /已触发/);
assert.match(guardianGuidance({reason_codes: ['latch_persistence_missing'], next_safe_action: 'recover_guardian_after_fresh_preflight'}), /重新预检/);
assert.match(guardianGuidance({reason_codes: ['new_unknown_code']}), /待确认/);
assert.doesNotMatch(guardianGuidance({reason_codes: ['new_unknown_code']}), /new_unknown_code/);
assert.equal(depthSourceLabel(true, true, true), '实时推送');
assert.match(depthSourceLabel(false, true, true), /2 秒轮询/);
assert.match(depthSourceLabel(false, true, false), /已过期/);
assert.match(depthSourceLabel(false, false, false), /等待/);
console.log('PASS: collapsed diagnostics, truthful depth labels and fail-closed Chinese guidance');
