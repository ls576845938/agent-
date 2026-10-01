import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const require = createRequire(import.meta.url);
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const read = path => readFileSync(resolve(root,path),'utf8');
function load(path,replacements={}) {
  const module={exports:{}};
  const compiled=ts.transpileModule(read(path),{compilerOptions:{
    module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
    jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,
  }}).outputText;
  const imported=name=>Object.hasOwn(replacements,name)?replacements[name]:require(name);
  new Function('exports','require','module',compiled)(module.exports,imported,module);
  return module.exports;
}
const links=load('frontend/src/workspaces/research/research-run-links.ts');
const view=load('frontend/src/workspaces/research/DonchianOfflineEvidence.tsx',{
  './research-run-links':links,
}).default;
const envelope=JSON.parse(read('.agent/offline_evidence/donchian-v3-closeout-20260920.json'));
const evidence={...envelope.summary,summary_sha256:envelope.sha256,read_only:true,
  historical_source:true,manifest_ref:'committed:receipt'};

test('one exact Donchian link removes Qlib and factory selectors on every switch',()=>{
  const offline=links.researchRunLink('offline',links.DONCHIAN_OFFLINE_RUN,
    '?qlibRun=m1-okx-qlib&factoryRun=batch&dataVersion=dv');
  const selected=new URL(offline,'http://local').searchParams;
  assert.equal(selected.get('offlineRun'),links.DONCHIAN_OFFLINE_RUN);
  assert.equal(selected.get('qlibRun'),null);
  assert.equal(selected.get('factoryRun'),null);
  const qlib=new URL(links.researchRunLink('qlib','m1-okx-qlib',selected.toString()),'http://local').searchParams;
  assert.equal(qlib.get('qlibRun'),'m1-okx-qlib');
  assert.equal(qlib.get('offlineRun'),null);
  const factory=new URL(links.researchRunLink('factory','batch',qlib.toString()),'http://local').searchParams;
  assert.equal(factory.get('factoryRun'),'batch');
  assert.equal(factory.get('qlibRun'),null);
});

test('real component renders all five linked phases and no order action',()=>{
  const html=renderToStaticMarkup(React.createElement(view,{evidence,runId:links.DONCHIAN_OFFLINE_RUN}));
  assert.match(html,/原策略五阶段纵向闭环/);
  assert.match(html,/行情仅用于信号/);
  assert.match(html,/固定成交价 60000/);
  assert.match(html,/实际资金费现金流 0 USDT/);
  for(const stage of evidence.stages) {
    assert.ok(html.includes(stage.evidence.decision_id));
    assert.ok(html.includes(stage.evidence.input_digest));
    if(stage.ledger) assert.ok(html.includes(stage.ledger.event_hash));
  }
  assert.match(html,/持有阶段：无新订单、无新成交、无新账本事件/);
  assert.match(html,/模拟成交 4/);
  assert.doesNotMatch(html,/<form|<button|启动 Demo|执行订单/);
});

test('unsafe or mismatched receipt displays only the blocked state',()=>{
  for(const invalid of [
    {...evidence,permissions:{...evidence.permissions,order:true}},
    {...evidence,selector:'wrong'},
    {...evidence,read_only:false},
    {selector:links.DONCHIAN_OFFLINE_RUN,status:'blocked',read_only:true,
     permissions:evidence.permissions},
  ]) {
    const html=renderToStaticMarkup(React.createElement(view,{evidence:invalid,runId:links.DONCHIAN_OFFLINE_RUN}));
    assert.match(html,/尚未绑定/);
    assert.doesNotMatch(html,/offline-fill-1|原策略五阶段纵向闭环/);
  }
});
