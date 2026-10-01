import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(fileURLToPath(new URL('../..',import.meta.url)));
const require=createRequire(import.meta.url);
const ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const read=path=>readFileSync(resolve(root,path),'utf8');
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
const marketState=load('frontend/src/workspaces/research/MarketStateEvidence.tsx').default;
const stage=load('frontend/src/workspaces/research/DonchianStageEvidence.tsx',{
  './research-run-links':links,
  './MarketStateEvidence':marketState,
}).default;
const snapshot=JSON.parse(read('.agent/offline_evidence/donchian-stage-20260921.json'));
const marketStateEvidence=JSON.parse(read('.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json'));
const evidence={...snapshot,read_only:true,historical_source:true,
  publication_head:'e2e7496acaa16b9fd5eda37dd65ea328a18ab032',
  snapshot_sha256:'ff5d5ad93538a4b74a2b3da1c7f76cad963e4a25195ff56373ad83c7806cce01',
  manifest_ref:'committed:stage',market_state_evidence:{...marketStateEvidence,read_only:true,
    publication_head:'e2e7496acaa16b9fd5eda37dd65ea328a18ab032',
    artifact_sha256:'2a4345a7d9a867cd1888addad00659583ea744911aa0b5b8486ad8c282c9c00b',
    manifest_ref:'committed:market-state'}};

test('three run families switch with one selector and clear the previous one',()=>{
  const stageUrl=links.researchRunLink('offline',links.DONCHIAN_STAGE_RUN,
    '?qlibRun=m1-okx-qlib&factoryRun=batch&offlineRun=donchian-v3-closeout-20260920');
  const first=new URL(stageUrl,'http://local').searchParams;
  assert.equal(first.get('offlineRun'),links.DONCHIAN_STAGE_RUN);
  assert.equal(first.get('qlibRun'),null);
  assert.equal(first.get('factoryRun'),null);
  const qlib=new URL(links.researchRunLink('qlib','m1-okx-qlib',first.toString()),'http://local').searchParams;
  assert.equal(qlib.get('offlineRun'),null);
  assert.equal(qlib.get('qlibRun'),'m1-okx-qlib');
  const fixture=new URL(links.researchRunLink('offline',links.DONCHIAN_OFFLINE_RUN,qlib.toString()),'http://local').searchParams;
  assert.equal(fixture.get('offlineRun'),links.DONCHIAN_OFFLINE_RUN);
  assert.equal(fixture.get('qlibRun'),null);
});

test('paused stage renders only evidenced references and distinguishes source from publication',()=>{
  const html=renderToStaticMarkup(React.createElement(stage,{evidence,runId:links.DONCHIAN_STAGE_RUN}));
  assert.match(html,/2960 \/ 8760/);
  assert.match(html,/30 条主决策/);
  assert.match(html,/26 次保护退出/);
  assert.match(html,/不补造策略主决策 ID/);
  assert.match(html,/历史模拟/);
  assert.match(html,/全年评估或独立确认/);
  assert.ok(html.includes(evidence.source_head));
  assert.ok(html.includes(evidence.publication_head));
  assert.ok(html.includes(evidence.decision_links[0].ledger_event_hash));
  assert.ok(html.includes(evidence.roundtrips[0].close_fill_id));
  assert.ok(html.includes(evidence.identity.params_hash));
  assert.ok(html.includes(evidence.identity.cost_policy_hash));
  assert.match(html,/半侧价差 0.5 bps/);
  assert.match(html,/资金费以先前可见小时 mark 收盘近似/);
  assert.match(html,/未建模队列与市场冲击/);
  assert.match(html,/全年表现/);
  assert.match(html,/统一市场状态 · 描述与分组证据/);
  assert.match(html,/政策试验尚未启动/);
  assert.doesNotMatch(html,/input_fingerprints|<form|<button|启动 Demo|实际成交：56/);
});

test('wrong run, permission or complete-state claim never renders stage facts',()=>{
  for(const bad of [
    {...evidence,selector:'latest'},
    {...evidence,permissions:{...evidence.permissions,order:true}},
    {...evidence,progress:{...evidence.progress,paused:false}},
    {...evidence,publication_head:evidence.source_head},
    {...evidence,counts:{...evidence.counts,protective_exits:30}},
    {...evidence,not_verified:undefined},
    {...evidence,execution_assumptions:undefined},
    {...evidence,decision_links:[{...evidence.decision_links[0],ledger_event_id:null},...evidence.decision_links.slice(1)]},
  ]) {
    const html=renderToStaticMarkup(React.createElement(stage,{evidence:bad,runId:links.DONCHIAN_STAGE_RUN}));
    assert.match(html,/尚未绑定/);
    assert.doesNotMatch(html,/2960 \/ 8760|主决策关联 30 笔成交/);
  }
});
