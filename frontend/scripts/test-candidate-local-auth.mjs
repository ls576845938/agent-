import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {candidateLocalGuard, candidateLocalGuardPlugin, candidateNamespace} from './candidate-local-guard.mjs';

const H = ['Host','127.0.0.1:3000','X-QS-Candidate-Intent','candidate-management'];
const browser = ['Sec-Fetch-Site','same-origin','Sec-Fetch-Mode','cors','Sec-Fetch-Dest','empty'];
function check(extra = {}) {
  let forwarded = false, status = 0;
  const req = {url:'/api/strategy-delivery/capabilities',method:'GET',
    socket:{remoteAddress:'127.0.0.1'},rawHeaders:H,...extra};
  const response = {setHeader(){},end(){status=this.statusCode;}};
  candidateLocalGuard(req,response,()=>{forwarded=true;});
  return {forwarded,status};
}
test('local CLI and browser reads/writes pass; unrelated market reads untouched',()=>{
  assert.equal(check().forwarded,true);
  assert.equal(check({rawHeaders:[...H,...browser,'Referer','http://127.0.0.1:3000/research']}).forwarded,true);
  assert.equal(check({method:'POST',url:'/api/strategy-delivery/packages',
    rawHeaders:[...H,...browser,'Origin','http://127.0.0.1:3000']}).forwarded,true);
  assert.equal(check({url:'/api/market',socket:{remoteAddress:'192.168.1.2'},rawHeaders:[]}).forwarded,true);
  assert.equal(check({rawHeaders:['Host','127.0.0.1:3000','X-API-Key','fixture-only']}).forwarded,true);
});
test('LAN, Host spoof, cross-site/null Origin, duplicate and forwarded headers rejected',()=>{
  const cases = [
    {socket:{remoteAddress:'192.168.1.2'}},
    {socket:{remoteAddress:'::ffff:192.168.1.2'}},
    {rawHeaders:['Host','evil.test','X-QS-Candidate-Intent','candidate-management']},
    {rawHeaders:[...H,'Host','localhost:3000']},
    {rawHeaders:[...H,'Origin','null']},
    {rawHeaders:[...H,'Origin','http://evil.test']},
    {rawHeaders:[...H,'Origin','http://127.0.0.1:3000','Origin','http://evil.test']},
    {rawHeaders:[...H,'X-Forwarded-For','127.0.0.1']},
    {rawHeaders:[...H,'Forwarded','for=127.0.0.1']},
    {rawHeaders:[...H,'X-QS-Candidate-Intent','candidate-management']},
    {rawHeaders:[...H,'Sec-Fetch-Site','cross-site']},
    {rawHeaders:[...H,'Sec-Fetch-Site','same-origin']},
    {rawHeaders:[...H,...browser,'Referer','http://evil.test/research']},
    {method:'POST',rawHeaders:[...H,...browser,'Referer','http://127.0.0.1:3000/research']},
    {rawHeaders:[...H,...browser]},
    {rawHeaders:['Host','127.0.0.1:3000']},
  ];
  for(const value of cases) assert.deepEqual(check(value),{forwarded:false,status:403},JSON.stringify(value));
});
test('encoded, doubled, trailing slash and dot-segment namespace variants cannot bypass guard',()=>{
  for(const url of ['/api/strategy-delivery/','/api//strategy-delivery/capabilities',
    '/api/%73trategy-delivery/capabilities','/api/%2573trategy-delivery/capabilities',
    '/api/candidate-offline/jobs/','/api/x/../candidate-offline/jobs',
    '/api\\candidate-offline/jobs','/api/strategy-delivery/%63apabilities']) {
    assert.equal(candidateNamespace(url),true,url);
    assert.deepEqual(check({url}),{forwarded:false,status:403},url);
  }
});
test('actual configured plugin installs pre-proxy middleware, never a post hook',async()=>{
  const {loadConfigFromFile}=await import('vite');
  const loaded=await loadConfigFromFile({command:'build',mode:'test'},
    fileURLToPath(new URL('../vite.config.ts',import.meta.url)));
  const plugins=loaded.config.plugins.flat();
  assert.equal(plugins[0].name,'candidate-local-proxy-boundary');
  const plugin=candidateLocalGuardPlugin(),handlers=[];
  assert.equal(plugin.enforce,'pre');
  assert.equal(plugin.configureServer({middlewares:{use:f=>handlers.push(f)}}),undefined);
  assert.equal(handlers[0],candidateLocalGuard);
  let reachedProxy=false;
  handlers.push(()=>{reachedProxy=true;});
  handlers[0]({url:'/api/candidate-offline/jobs',method:'POST',
    rawHeaders:H,socket:{remoteAddress:'192.168.1.5'}},
    {setHeader(){},end(){}},()=>handlers[1]());
  assert.equal(reachedProxy,false);
});

const require=createRequire(import.meta.url),ts=require('typescript');
const read=name=>readFileSync(new URL('../src/workspaces/research/'+name,import.meta.url),'utf8');
function load(name,overrides={}) {
  const module={exports:{}};
  const code=ts.transpileModule(read(name),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
    jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
  new Function('module','exports','require',code)(module,module.exports,n=>Object.hasOwn(overrides,n)?overrides[n]:require(n));
  return module.exports;
}
const handoff=load('candidate-handoff.ts');
const api=load('candidate-delivery-api.ts',{'./candidate-handoff':handoff});
const offline=load('candidate-offline-api.ts',{'./candidate-delivery-api':api});
const accessModule=(()=>{const module={exports:{}};
  const source=readFileSync(new URL('../src/lib/research-workspace-access.ts',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  new Function('module','exports','require',code)(module,module.exports,require);return module.exports;})();
const candidateProfileOverrides={'../../lib/api':{apiGet:async()=>({evidence_profile:'candidate_management',read_only:true,controls_disabled:true})},
  '../../lib/research-workspace-access':accessModule};

test('unknown, failed or readonly capability discovery never invents a password gate',async()=>{
  for(const failure of ['network','readonly','invalid']) {
    const request=async()=>{if(failure==='invalid')return {};throw new Error(failure);};
    const candidate=harness('CandidateDelivery.tsx',{...candidateProfileOverrides,'./candidate-delivery-api':{...api,deliveryRequest:request},
      './RegisteredCandidateRunControls':{default:()=>null}});
    const props={source:{kind:'qlib',runId:'r',candidateId:'c'},target:'offline'};
    candidate.render(props);await new Promise(resolve=>setImmediate(resolve));
    nodes(candidate.render(props)).find(n=>n.type==='button').props.onClick();
    candidate.render(props);await new Promise(resolve=>setImmediate(resolve));
    assert.equal(nodes(candidate.render(props)).some(n=>n.props?.type==='password'),false);
    const evidence=harness('RegisteredCandidateOfflineEvidence.tsx',
      {'./candidate-offline-api':{...offline,offlineRequest:request},'./candidate-delivery-api':api});
    evidence.render({runId:'coff_'+'a'.repeat(32)});await new Promise(resolve=>setImmediate(resolve));
    assert.equal(nodes(evidence.render({runId:'coff_'+'a'.repeat(32)})).some(n=>n.props?.type==='password'),false);
  }
});

test('local frontend sends public intent, no empty key, GET never submits',async()=>{
  const old=globalThis.fetch,calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,...options});return {ok:true,json:async()=>({})};};
  try {
    await api.deliveryRequest('/capabilities','');
    await offline.offlineRequest('/capabilities','');
    for(const call of calls) {
      assert.equal(call.method,'GET');
      assert.equal(call.headers['X-QS-Candidate-Intent'],'candidate-management');
      assert.equal(call.headers['X-API-Key'],undefined);
      assert.equal(call.body,undefined);
    }
  }finally{globalThis.fetch=old;}
});
function harness(name,overrides) {
  const state=[],refs=[],deps=[],pending=[];let si=0,ri=0,ei=0;
  const react={...require('react'),
    useState(initial){const i=si++;if(!(i in state))state[i]=initial;return [state[i],value=>{state[i]=typeof value==='function'?value(state[i]):value;}];},
    useRef(initial){const i=ri++;return refs[i]??=( {current:initial} );},
    useEffect(fn,current){const i=ei++;if(!deps[i]||!current||current.some((x,k)=>x!==deps[i][k])){deps[i]=current;pending.push(fn);}},
  };
  const view=load(name,{react,...overrides}).default;
  return {render(props){si=ri=ei=0;const tree=view(props);for(const fn of pending.splice(0))fn();return tree;}};
}
function nodes(value) {
  if(Array.isArray(value))return value.flatMap(nodes);
  if(!value||typeof value!=='object')return [];
  return [value,...nodes(value.props?.children)];
}
test('real candidate and evidence components remove password only in discovered local mode',async()=>{
  for(const mode of ['local_no_password','key']) {
    const calls=[];
    const cap={schema_version:'strategy_delivery_capabilities_v1',auth_mode:mode,permissions:Object.fromEntries(handoff.SAFETY_FLAGS.map(k=>[k,false])),
      authenticated:mode==='local_no_password',commands_enabled:mode==='local_no_password',operator:'operator'};
    const request=async(path,...args)=>{calls.push({path,args});return path==='/capabilities'?cap:path==='/packages'?{records:[]}:{accounts:[]};};
    const candidate=harness('CandidateDelivery.tsx',{...candidateProfileOverrides,'./candidate-delivery-api':{...api,deliveryRequest:request},
      './RegisteredCandidateRunControls':{default:()=>null}});
    const props={source:{kind:'qlib',runId:'r',candidateId:'c'},target:'offline'};
    candidate.render(props);await new Promise(resolve=>setImmediate(resolve));
    nodes(candidate.render(props)).find(n=>n.type==='button').props.onClick();
    candidate.render(props);await new Promise(resolve=>setImmediate(resolve));
    const tree=candidate.render(props);
    assert.equal(nodes(tree).some(n=>n.props?.type==='password'),mode==='key');
    assert.equal(calls.some(c=>c.args[1]!==undefined),false,'GET only');
    assert.equal(calls.some(c=>/register|bind|review/.test(c.path)),false);
    const evidence=harness('RegisteredCandidateOfflineEvidence.tsx',{'./candidate-offline-api':{...offline,offlineRequest:request},'./candidate-delivery-api':api});
    evidence.render({runId:'coff_'+'a'.repeat(32)});await new Promise(resolve=>setImmediate(resolve));
    const result=evidence.render({runId:'coff_'+'a'.repeat(32)});
    assert.equal(nodes(result).some(n=>n.props?.type==='password'),mode==='key');
    assert.equal(nodes(result).find(n=>n.type==='button').props.disabled,mode==='key');
  }
});
