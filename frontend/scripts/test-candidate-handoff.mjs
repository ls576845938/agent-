import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const read = name => readFileSync(new URL('../src/workspaces/research/' + name, import.meta.url), 'utf8');
function load(name, overrides = {}) {
  const module = {exports: {}};
  const code = ts.transpileModule(read(name), {compilerOptions: {module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true}}).outputText;
  new Function('module','exports','require',code)(module,module.exports,
    name => Object.hasOwn(overrides,name) ? overrides[name] : require(name));
  return module.exports;
}
const m = load('candidate-handoff.ts');
const flags = Object.fromEntries(m.SAFETY_FLAGS.map(key => [key,false]));
const hash = 'a'.repeat(64), head = 'b'.repeat(40);
const qlib = () => ({...flags,integrity_status:'passed',summary:{run_id:'run-1',source_head:head,
  data_version:'data-1',asset_class:'crypto',symbols:['BTC-USDT-SWAP'],bar_size:'1h'},
  seal:{run_id:'run-1',source_head:head,files:{'model.txt':hash,'qlib_strategy_manifest.json':hash,
    'qlib_workflow_config.yaml':hash,'research_trace.json':hash}},
  strategy_manifest:{run_id:'run-1',candidate_id:'candidate-1',strategy_id:'qlib_trend',
    asset_class:'crypto',symbols:['BTC-USDT-SWAP'],promotion_status:'blocked'},
  research_trace:{identity:{qlib_run_id:'run-1',candidate_id:'candidate-1',source_head:head},blockers:['no_simulated_fills']}});
const factory = () => ({...flags,run_id:'batch-1',source_head:head,integrity_status:'passed',
  result:{profile:{market:'crypto',symbols:['BTC-USDT-SWAP'],bar_size:'1h'},candidates:[{
    ...flags,candidate_id:'alpha-1',factory_run_id:'batch-1',qlib_run_id:'final-audit',data_version:'data-1',
    strategy_config:{strategy_id:'qlib_forecast'},status:'exploratory_nomination',
    audit_qlib_reference:{qlib_run_id:'final-audit',seal_sha256:hash},gate:{blockers:[]}}]}});

test('binds Qlib identity and distinguishes sealed references from deployment approval', () => {
  const source=m.resolveHandoffSource('qlib','run-1',qlib());
  assert.equal(source.candidateId,'candidate-1');
  assert.equal(source.sourceHead,head);
  assert.equal(source.artifacts.find(x=>x.key==='model').reference,hash);
  assert.ok(source.blockers.includes('no_simulated_fills'));
  assert.equal(m.canPublishRuntimeCandidate(),false);
});
test('rejects mismatched, latest, unsealed, unsafe and missing safety contracts', () => {
  for(const data of [null,{...qlib(),integrity_status:'blocked'},{...qlib(),order:true},
    {...qlib(),order:undefined},{...qlib(),summary:{run_id:'wrong'}},
    {...qlib(),seal:{...qlib().seal,run_id:'other'}},
    {...qlib(),research_trace:{identity:{qlib_run_id:'other'}}}]) {
    assert.throws(()=>m.resolveHandoffSource('qlib','run-1',data));
  }
  assert.throws(()=>m.resolveHandoffSource('qlib','latest',qlib()));
});
test('factory source uses an exact nominated candidate, never a trial or first-row fallback', () => {
  assert.equal(m.resolveHandoffSource('factory','batch-1',factory(),'alpha-1').qlibRunId,'final-audit');
  for(const id of ['', 'wrong']) assert.throws(()=>m.resolveHandoffSource('factory','batch-1',factory(),id));
  const duplicate=factory(); duplicate.result.candidates.push({...duplicate.result.candidates[0]});
  assert.throws(()=>m.resolveHandoffSource('factory','batch-1',duplicate,'alpha-1'));
  const wrong=factory();wrong.result.candidates[0].audit_qlib_reference.qlib_run_id='trial';
  assert.throws(()=>m.resolveHandoffSource('factory','batch-1',wrong,'alpha-1'));
});
test('draft keeps all operations disabled even for a complete-looking source', () => {
  const source=m.resolveHandoffSource('qlib','run-1',qlib());
  const draft=m.createHandoffDraft(source,'okx_demo','Review account binding separately',true,
    '12345678-1234-4234-8234-123456789012','2026-09-24T00:00:00Z');
  assert.equal(draft.status,'local_draft');
  assert.equal(draft.account_binding,'not_bound');
  assert.ok(Object.values(draft.permissions).every(x=>x===false));
  assert.equal(m.parseHandoffDraft(JSON.stringify(draft)).id,draft.id);
  assert.equal(m.reconcileHandoffDraft(draft,source),'matched');
  assert.equal(m.reconcileHandoffDraft(draft,{...source,sourceHead:'c'.repeat(40)}),'changed');
  assert.throws(()=>m.createHandoffDraft(source,'okx_demo','',false,draft.id,draft.created_at));
  assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,permissions:{...flags,order:true}})));
  assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,status:'approved'})));
  assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,account_binding:'approved-account'})));
  assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,target:'live'})));
  assert.throws(()=>m.parseHandoffDraft('{'));
});
test('navigation carries only a local draft reference and source-specific research link', () => {
  const source=m.resolveHandoffSource('factory','batch-1',factory(),'alpha-1');
  const url=new URL(m.handoffSourceLink(source),'http://local');
  assert.equal(url.searchParams.get('factoryRun'),'batch-1');
  assert.equal(url.searchParams.get('qlibRun'),null);
  assert.throws(()=>m.parseHandoffSelector('?researchHandoff=latest'));
  assert.throws(()=>m.parseHandoffSelector('?researchHandoff=a&researchHandoff=b'));
  assert.equal(m.parseHandoffSelector(''),null);
});
test('other markets remain reviewable but cannot hand off to BTC Demo', () => {
  const detail=qlib();detail.summary.asset_class='us_equity';detail.summary.symbols=['AAPL'];
  detail.strategy_manifest.asset_class='us_equity';detail.strategy_manifest.symbols=['AAPL'];
  const source=m.resolveHandoffSource('qlib','run-1',detail);
  assert.equal(m.isBtcSource(source),false);
  assert.throws(()=>m.createHandoffDraft(source,'okx_demo','',true,
    '12345678-1234-4234-8234-123456789012','2026-09-24T00:00:00Z'));
});
test('session storage denial is explicit; unavailable drafts are not recreated', () => {
  const storage={getItem:()=>{throw new Error('denied');},setItem:()=>{throw new Error('denied');}};
  assert.throws(()=>m.readHandoffDraft(storage,'12345678-1234-4234-8234-123456789012'));
  assert.throws(()=>m.readHandoffDraft({getItem:()=>null},'12345678-1234-4234-8234-123456789012'));
});
test('candidate, code, instrument, data and manifest conflicts never get silently repaired', () => {
  const mutations=[
    d=>{d.strategy_manifest.candidate_id='different';d.research_trace.identity.candidate_id='candidate-1';},
    d=>{d.seal.source_head='c'.repeat(40);},
    d=>{d.strategy_manifest.run_id='different';},
    d=>{d.strategy_manifest.symbols=['ETH-USDT-SWAP'];},
    d=>{d.research_trace.identity.data_version='different';},
    d=>{d.strategy_manifest.order=true;},
    d=>{d.research_trace.execution_permission=true;},
  ];
  for(const mutate of mutations) {const data=qlib();mutate(data);assert.throws(()=>m.resolveHandoffSource('qlib','run-1',data));}
});
test('no model hash means missing model, not a completed deployment package', () => {
  const data=qlib();delete data.seal.files['model.txt'];
  const source=m.resolveHandoffSource('qlib','run-1',data);
  assert.equal(source.artifacts.find(x=>x.key==='model').kind,'missing');
  assert.equal(source.artifacts.find(x=>x.key==='package').kind,'missing');
  assert.equal(m.canPublishRuntimeCandidate(),false);
});
test('draft parser rejects malformed shapes and strips injected top-level approval', () => {
  const source=m.resolveHandoffSource('qlib','run-1',qlib());
  const draft=m.createHandoffDraft(source,'offline','',true,'12345678-1234-4234-8234-123456789012','2026-09-24T00:00:00Z');
  for(const change of [{source:null},{source_fingerprint:'forged'},{note:'a'.repeat(501)},
    {created_at:'bad'},{acknowledgement:false},{id:'../another'},{source:{...source,artifacts:[null]}}]) {
    assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,...change})));
  }
  const parsed=m.parseHandoffDraft(JSON.stringify({...draft,approved:true,runtime_candidate_id:'forged'}));
  assert.equal(parsed.approved,undefined);assert.equal(parsed.runtime_candidate_id,undefined);
});
test('draft parser rejects non-string source identifiers without regexp coercion', () => {
  const source=m.resolveHandoffSource('qlib','run-1',qlib());
  const draft=m.createHandoffDraft(source,'offline','',true,'12345678-1234-4234-8234-123456789012','2026-09-24T00:00:00Z');
  for (const key of ['runId','candidateId','qlibRunId']) {
    const malformedSource={...source,[key]:123};
    assert.throws(()=>m.parseHandoffDraft(JSON.stringify({...draft,source:malformedSource,
      source_fingerprint:JSON.stringify(malformedSource)})));
  }
});
test('request content is bounded to research metadata, never full backend payload', () => {
  const data=qlib();data.strategy_manifest.private_key='must-not-export';data.dataset_manifest={files:{local:'D:/private/path'}};
  const serialized=JSON.stringify(m.resolveHandoffSource('qlib','run-1',data));
  assert.doesNotMatch(serialized,/must-not-export|private.path|private_key/);
});
test('new handoff components cannot invoke control or registration writes', () => {
  for(const file of ['candidate-handoff.ts','CandidateHandoff.tsx','CandidateHandoffInbox.tsx']) {
    assert.doesNotMatch(read(file),/apiPost|\.submit\(|\.resume\(|onCandidateChange\(|onStrategyChange\(|operatorController\.|\/demo-paper\/|fetch\(/);
  }
});
test('real component renders blocked publishing, stages, and missing account binding', () => {
  const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
  const view=load('CandidateHandoff.tsx',{'./candidate-handoff':m,'./candidate-handoff.css':{},
    './CandidateDelivery':()=>React.createElement('p',null,'服务端交付入口'),
    '../../frontendIdentity':{frontendIdentity:{source_head:head}}}).CandidateHandoffPanel;
  const html=renderToStaticMarkup(React.createElement(view,{source:m.resolveHandoffSource('qlib','run-1',qlib())}));
  assert.match(html,/部署交接/);
  assert.match(html,/待补齐／未审定/);
  assert.match(html,/本地草稿不能直接发布/);
  assert.doesNotMatch(html,/直接发布本地草稿/);
  assert.doesNotMatch(html,/发布成功|注册成功/);
});
