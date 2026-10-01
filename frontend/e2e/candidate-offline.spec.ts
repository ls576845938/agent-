// Server-rendered component and selector contracts. No Vite/browser server.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import Evidence from '../src/workspaces/research/RegisteredCandidateOfflineEvidence';
import Controls from '../src/workspaces/research/RegisteredCandidateRunControls';
import {registeredOfflineId,verifyOfflineResult} from '../src/workspaces/research/candidate-offline-api';
import {SAFETY_FLAGS} from '../src/workspaces/research/candidate-handoff';
import {researchRunLink,DONCHIAN_OFFLINE_RUN,DONCHIAN_STAGE_RUN} from '../src/workspaces/research/research-run-links';

const id='coff_'+'a'.repeat(32);
const permissions=Object.fromEntries(SAFETY_FLAGS.map(k=>[k,false]));
const hash=(v:any)=>createHash('sha256').update(JSON.stringify(v,Object.keys(v).sort())).digest('hex');
const identity={schema_version:'candidate_offline_job_identity_v1',job_id:id,registration_id:'delivery_'+'b'.repeat(32),
  content_digest:'c'.repeat(64),binding_digest:'d'.repeat(64),account_ref:'fixture-account',account_identity_hash:'e'.repeat(64),
  runtime_contract_digest:'f'.repeat(64),state_directory_sha256:'1'.repeat(64),input_revision_id:'input-one',
  input_digest:'2'.repeat(64),input_head:'3'.repeat(40),input_evidence_kind:'synthetic_fixture',
  source_head:'4'.repeat(40),execution_head:'5'.repeat(40),catalog_sha256:'6'.repeat(64)};
const {schema_version:identitySchema,...identityFields}=identity;
const bound={...identityFields,job_identity:identity,job_identity_digest:hash(identity)};
const job={...bound,id,schema_version:'candidate_offline_job_v2',permissions};
test('controlled selectors keep old offline and sealed Qlib links exact',()=>{
  assert(registeredOfflineId(id));assert(!registeredOfflineId('latest'));assert(!registeredOfflineId(id+'/../other'));
  for(const selector of [id,DONCHIAN_OFFLINE_RUN,DONCHIAN_STAGE_RUN]){
    const url=new URL(researchRunLink('offline',selector,'?qlibRun=old&offlineRun=x&offlineRun=y&factoryRun=old'),'http://local');
    assert.deepEqual(url.searchParams.getAll('offlineRun'),[selector]);assert(!url.searchParams.has('qlibRun'));assert(!url.searchParams.has('factoryRun'));
  }
  assert(researchRunLink('qlib','sealed-a').includes('qlibRun=sealed-a'));
});
test('identity mismatch and unsafe result are rejected with no fallback',()=>{
  const value={job,permissions,start_allowed:false,result_bound:false,result:null,decisions:[]};
  assert.equal(verifyOfflineResult(value,id),value);
  assert.throws(()=>verifyOfflineResult(value,'coff_'+'b'.repeat(32)));
  assert.throws(()=>verifyOfflineResult({...value,permissions:{...permissions,order:true}},id));
  assert.throws(()=>verifyOfflineResult({...value,result:{job_id:id},result_bound:true},id));
});
test('all rehashed result and decision identities must match the authoritative job',()=>{
  const result={...bound,schema_version:'candidate_offline_result_v2',permissions};
  const decision={...bound,schema_version:'candidate_offline_decision_v2',cursor:1};
  const value={job,permissions,start_allowed:false,result_bound:true,result,decisions:[decision]};
  assert.equal(verifyOfflineResult(value,id),value);
  for(const target of ['result','decision']){
    for(const field of Object.keys(identityFields)){
      const copy=JSON.parse(JSON.stringify(value));
      const entry=target==='result'?copy.result:copy.decisions[0];
      entry[field]=entry.job_identity[field]=field==='input_evidence_kind'?'verified_historical_observations':
        field==='job_id'?'coff_'+'0'.repeat(32):'0'.repeat(entry[field].length);
      entry.job_identity_digest=hash(entry.job_identity);
      entry.sha256=hash(entry);
      assert.throws(()=>verifyOfflineResult(copy,id),field+' '+target);
    }
    const old=JSON.parse(JSON.stringify(value));
    delete (target==='result'?old.result:old.decisions[0]).job_identity;
    assert.throws(()=>verifyOfflineResult(old,id));
  }
  const old=JSON.parse(JSON.stringify(value));delete old.job.job_identity;
  assert.throws(()=>verifyOfflineResult(old,id));
});
test('initial result component distinguishes code from execution and reads only',()=>{
  const html=renderToStaticMarkup(React.createElement(Evidence,{runId:id}));
  assert(html.includes('结果未绑定'));assert(html.includes('离线读取模式尚未开放或待读取'));
  assert(!html.includes('type="password"'));assert(html.includes('disabled=""'));
  assert(!html.includes('localStorage'));assert(!html.includes('恢复原作业'));
});
test('controls default disabled and disclose unsupported protection',()=>{
  const row:any={id:'delivery_'+'c'.repeat(32),content_digest:'d'.repeat(64),revision:4,status:'registered'};
  const html=renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(Controls,{row,credential:''})));
  assert(html.includes('默认关闭'));assert(html.includes('保护成交尚未接入'));assert(html.includes('disabled=""'));
});
