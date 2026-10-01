import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
const read=name=>readFileSync(new URL('../src/workspaces/research/'+name,import.meta.url),'utf8');
function load(name,overrides={}) {
  const module={exports:{}};
  const code=ts.transpileModule(read(name),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
    jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  new Function('module','exports','require',code)(module,module.exports,name=>Object.hasOwn(overrides,name)?overrides[name]:require(name));
  return module.exports;
}
const handoff=load('candidate-handoff.ts');
const api=load('candidate-delivery-api.ts',{'./candidate-handoff':handoff});
const accessModule=(()=>{const module={exports:{}};const source=readFileSync(new URL('../src/lib/research-workspace-access.ts',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('module','exports','require',code)(module,module.exports,require);return module.exports;})();
const source={kind:'qlib',runId:'exact-run',candidateId:'exact-candidate'};
const record=()=>({schema_version:'strategy_delivery_record_v1',id:'delivery_'+'a'.repeat(32),revision:1,
  source:{kind:'qlib',run_id:'exact-run',candidate_id:'exact-candidate'},target:'offline',status:'validated',
  content_digest:'c'.repeat(64),permissions:Object.fromEntries(handoff.SAFETY_FLAGS.map(x=>[x,false])),
  validation:{blockers:[]},registration:null});

test('server result must bind exact source, target and all closed permissions',()=>{
  assert.equal(api.verifyDelivery(record(),source,'offline').id,record().id);
  for(const mutation of [r=>{r.source.run_id='other';},r=>{r.target='okx_demo';},r=>{r.permissions.order=true;},
    r=>{delete r.permissions.private;},r=>{r.registration={start_allowed:true};},r=>{r.status='running';}]) {
    const row=record();mutation(row);assert.throws(()=>api.verifyDelivery(row,source,'offline'));
  }
});
test('only candidate management commands can be built',()=>{
  assert.throws(()=>api.createDeliveryRequest('/demo-paper/start',{}));
  assert.throws(()=>api.createDeliveryRequest('/packages/latest/register',{}));
  const req=api.createDeliveryRequest('/packages',{source},'stable-request-id');
  assert.equal(req.key,'stable-request-id');
});
test('authentication and stable idempotency travel in headers, not bodies',async()=>{
  const old=globalThis.fetch,calls=[];
  try {
    globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>record()};};
    const req=api.createDeliveryRequest('/packages',{target:'offline'},'stable-request-id');
    await api.deliveryRequest(req.path,'fixture-management-key',req);
    await api.deliveryRequest(req.path,'fixture-management-key',req);
    assert.equal(calls[0].options.headers['Idempotency-Key'],calls[1].options.headers['Idempotency-Key']);
    assert.doesNotMatch(calls[0].options.body,/fixture-management-key/);
    assert.equal(calls[0].options.headers['X-API-Key'],'fixture-management-key');
  } finally {globalThis.fetch=old;}
});
test('transport failure and 5xx are ambiguous, definitive auth rejection is not',async()=>{
  const old=globalThis.fetch;
  try {
    for(const status of [0,503,403]) {
      globalThis.fetch=async()=>{if(!status)throw new Error('network');return {ok:false,status,json:async()=>({detail:'blocked'})};};
      await assert.rejects(()=>api.deliveryRequest('/packages','fixture'),e=>e.outcomeUnknown===(status!==403));
    }
  } finally {globalThis.fetch=old;}
});
test('real component starts fail-closed before health confirmation and never stores credentials',()=>{
  const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
  const view=load('CandidateDelivery.tsx',{'./candidate-delivery-api':api,'./RegisteredCandidateRunControls':{default:()=>null},
    '../../lib/api':{apiGet:async()=>({})},'../../lib/research-workspace-access':accessModule}).default;
  const html=renderToStaticMarkup(React.createElement(view,{source,target:'offline'}));
  assert.match(html,/候选管理写入口保持关闭/);
  assert.doesNotMatch(html,/读取候选管理能力与记录|提交一次服务端包验证|绑定账户|登记到候选管理目录/);
  assert.match(read('CandidateDelivery.tsx'),/服务端验证、审定与登记/);
  assert.doesNotMatch(read('CandidateDelivery.tsx'),/localStorage|sessionStorage|\/demo-paper\/|operatorController/);
});

test('registration copy describes management records, not a connected runtime directory',()=>{
  const text=read('CandidateDelivery.tsx');
  assert.match(text,/登记到候选管理目录/);
  assert.match(text,/已登记候选管理记录 · 运行另查/);
  assert.doesNotMatch(text,/登记到目标环境目录|已登记 · 未启动/);
});
