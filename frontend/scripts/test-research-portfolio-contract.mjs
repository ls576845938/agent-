import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import vm from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const root = fileURLToPath(new URL('../../',import.meta.url)), baseline='13486a7802628e93dd624213ba6c317c5deb4ddf';
const normalize=s=>s.replaceAll('\r\n','\n').trimEnd();
const read=p=>normalize(readFileSync(root+p,'utf8'));
const gitAt=(ref,p)=>normalize(execFileSync('git',['show',ref+':'+p],{cwd:root,encoding:'utf8'}));
const git=p=>gitAt(baseline,p);
const source = process.argv.includes('--baseline') ? git : read;
assert.match(source('frontend/src/workspaces/ResearchDashboard.tsx'),/surface="research"/,'Canonical research must use the isolated research surface');
assert.match(source('frontend/src/workspaces/PortfolioMonitor.tsx'),/surface="portfolio"/);
const oldResearch=git('frontend/src/workspaces/ResearchDashboard.tsx').replaceAll("from '../","from '../../").replaceAll("from './research/","from './").replace("from './ResearchWorkbench'","from './PreviousResearchWorkbench'").replace("import './research/ResearchDashboard.css'","import './ResearchDashboard.css'").replace('export default function ResearchDashboard()', 'export default function PreviousResearchDashboard()');
assert.equal(read('frontend/src/workspaces/research/PreviousResearchDashboard.tsx'),oldResearch);
assert.equal(read('frontend/src/workspaces/research/PreviousResearchWorkbench.tsx'),git('frontend/src/workspaces/research/ResearchWorkbench.tsx'));
const oldPortfolio=git('frontend/src/workspaces/PortfolioMonitor.tsx').replaceAll("from '../","from '../../").replaceAll("from './portfolio/","from './").replace('export default function PortfolioMonitor()', 'export default function LegacyPortfolioMonitor()');
assert.equal(read('frontend/src/workspaces/portfolio/LegacyPortfolioMonitor.tsx'),oldPortfolio);
for(const p of ['frontend/src/workspaces/LiveTradingDashboard.tsx',
 ...['PortfolioOverview','PortfolioRisk'].map(p=>'frontend/src/workspaces/portfolio/'+p+'.tsx'),
 ...['CandidateTable','CandidateDetail','ExperimentReport','ExperimentCompare','ExperimentList'].map(p=>'frontend/src/workspaces/research/'+p+'.tsx')]) assert.equal(read(p),git(p),'Frozen rollback dependency: '+p);
const allocationPath='frontend/src/workspaces/portfolio/PortfolioAllocation.tsx';
const expectedAllocation=git(allocationPath)
  .replace(/const rebalanceBtnStyle = \{[\s\S]*?\n\};\n\n/, '')
  .replace(`        <button
          style={rebalanceBtnStyle}
          onClick={() => {/* rebalance placeholder */}}
        >
          再平衡
        </button>`, `        <p style={{margin: '0 0 0 auto', fontSize: '0.8rem', color: '#94a3b8'}}>
          当前仅展示研究配置；再平衡尚未接入受控提交。
        </p>`);
assert.equal(read(allocationPath),expectedAllocation,'Only the inert rebalance placeholder becomes explanatory text');
// Keep the cancellable GET contract pinned to its reviewed source commit.  The
// only release-ticket delta is the explicit bounded registry summary view.
const researchApiPath='frontend/src/lib/research-api.ts';
const researchApiReviewed='be0bf76a739c848662055c9dec249e2d24529e22';
const registryFullQuery="query({data_root: dataRoot, rebuild})";
const registrySummaryQuery="query({data_root: dataRoot, rebuild, view: 'summary'})";
const frozenResearchApi=gitAt(researchApiReviewed,researchApiPath);
assert.equal(frozenResearchApi.split(registryFullQuery).length,2,'Exactly one reviewed registry query');
const expectedResearchApi=frozenResearchApi.replace(registryFullQuery,registrySummaryQuery);
const assertResearchApiContract=value=>assert.equal(value,expectedResearchApi,'Reviewed cancellable GET API plus bounded registry summary view');
assertResearchApiContract(read(researchApiPath));
assert.throws(()=>assertResearchApiContract(expectedResearchApi.replace('/api/research/evidence-registry','/api/research/other')),assert.AssertionError,'Registry endpoint drift must fail');
assert.throws(()=>assertResearchApiContract(expectedResearchApi.replace('timeoutMs: 20000','timeoutMs: 30000')),assert.AssertionError,'Research timeout budget drift must fail');
assert.throws(()=>assertResearchApiContract(expectedResearchApi.replace(", view: 'summary'",'')),assert.AssertionError,'Registry full-payload fallback must fail');
// The original rollback dependencies stay pinned. The sole reviewed additive
// task helper landed in 5a400ebc1b8b037ae18dc98ada5bc83ecd8f3dc9; do not repin
// the whole file to HEAD or allow arbitrary new endpoints under this exception.
const taskPath='frontend/src/lib/task-api.ts';
const pipelineHelper="  submitQlibPipelineTask: (payload: any) => apiPost<TaskResponse>('/api/tasks/integrations/qlib/run-pipeline', payload),";
const taskAnchor='  submitPortfolioOptimizeWeightsTask:';
const frozenTask=git(taskPath);
assert.equal(frozenTask.split(taskAnchor).length,2,'Exactly one frozen insertion point');
const expectedTask=frozenTask.replace(taskAnchor,pipelineHelper+'\n'+taskAnchor);
const assertTaskContract=value=>assert.equal(value,expectedTask,'Frozen task API plus the single reviewed Qlib pipeline helper');
assertTaskContract(read(taskPath));
assert.throws(()=>assertTaskContract(expectedTask.replace('/qlib/run-pipeline','/qlib/other')),assert.AssertionError,'Endpoint drift must fail');
assert.throws(()=>assertTaskContract(expectedTask.replace('getTask:','renamedTask:')),assert.AssertionError,'Legacy API drift must fail');
assert.throws(()=>assertTaskContract(expectedTask.replace(taskAnchor,'  unexpectedSubmit: () => {},\n'+taskAnchor)),assert.AssertionError,'Unreviewed additions must fail');
const taskCalls=[], taskModule={exports:{}};
const taskJs=ts.transpileModule(read(taskPath),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
vm.runInNewContext('(function(require,module,exports){'+taskJs+'\n})',{})(id=>{
 assert.equal(id,'./api','No extra task API dependencies');
 return {apiGet:(...args)=>{taskCalls.push(['GET',...args]);},apiPost:(...args)=>{taskCalls.push(['POST',...args]);return Promise.resolve({task_id:'fixture-only'});}};
},taskModule,taskModule.exports);
assert.equal(taskCalls.length,0,'Importing task helpers must never submit');
const pipelinePayload={config:'configs/qlib/okx_btc_trend_1h.yaml',run_id:'fixture-only'};
await taskModule.exports.taskApi.submitQlibPipelineTask(pipelinePayload);
assert.deepEqual(taskCalls,[['POST','/api/tasks/integrations/qlib/run-pipeline',pipelinePayload]],'Explicit helper forwards the exact payload to the reviewed research endpoint; mock only');
// Navigation additions were inserted among rules, not only appended at EOF.
// Compare every old rule in its original media context, allowing only the
// reviewed sticky-padding substitution (44b4fc2bd); all old defaults remain.
const postcss=require('postcss'), cssPath='frontend/src/workspaces/research/ResearchDashboard.css';
const ruleContext=rule=>{const parts=[];for(let parent=rule.parent;parent?.type==='atrule';parent=parent.parent)parts.unshift('@'+parent.name+' '+parent.params);return parts.join('|')+'|'+rule.selector;};
const declarations=rule=>rule.nodes.map(node=>node.type==='decl'?[node.prop,node.value,!!node.important]:[node.type,node.toString()]);
function assertLegacyCss(value) {
 const current=[];postcss.parse(value).walkRules(rule=>current.push(rule));
 postcss.parse(git(cssPath)).walkRules(rule=>{
  const expected=declarations(rule).map(([property,value,...rest])=>{
   if(rule.selector==='.research-v2 .system-tv-canvas-scroll'&&property==='padding') {
    const replacements={'22px 24px 28px':'var(--research-canvas-top-padding, 22px) 24px 28px','18px':'var(--research-canvas-top-padding, 18px) 18px 18px','12px':'var(--research-canvas-top-padding, 12px) 12px 12px'};
    value=replacements[value]??value;
   }
   return [property,value,...rest];
  });
  assert.ok(current.some(candidate=>ruleContext(candidate)===ruleContext(rule)&&JSON.stringify(declarations(candidate))===JSON.stringify(expected)),'Old CSS rule/defaults preserved: '+ruleContext(rule));
 });
}
assertLegacyCss(read(cssPath));
assert.throws(()=>assertLegacyCss(read(cssPath).replace('font-size: 23px','font-size: 1px')),assert.AssertionError,'Old heading styles must remain protected');
const shared=read('frontend/src/workspaces/ResearchPortfolioWorkspace.tsx');
for(const match of shared.matchAll(/(?:researchApi|taskApi)\.(\w+)\(/g)) assert.match(match[1],/^(get|list)/,'Shared shell may only read: '+match[1]);
assert.doesNotMatch(shared,/submitTrackedTask|volatility\s*\*\s*(2\.5|1\.645)/);
const registryRead=shared.indexOf("read('证据注册表'");
const qlibRead=shared.indexOf("read('Qlib'");
const experimentRead=shared.indexOf("read('实验列表'");
assert.ok(registryRead >= 0 && qlibRead >= 0 && experimentRead >= 0,'Overview read contract must keep registry, Qlib, and experiment reads');
assert.ok(registryRead < experimentRead && qlibRead < experimentRead,'Registry and Qlib reads must be initiated before lighter overview reads');
assert.match(shared,/\{deadlineMs:\s*12000\}/,'Whole-page deadline stays fixed at 12 seconds');
for(const name of ['research','portfolio','review']) {
 const actions=read('frontend/src/workspaces/'+name+'-actions.ts');
 for(const other of ['research','portfolio','review'].filter(n=>n!==name)) assert.doesNotMatch(actions,new RegExp("from ['\"].*"+other+"-actions"));
 assert.match(actions,new RegExp("surface !== '"+name+"'"));
 assert.match(actions,/actionLock\.current/);
}
const cache=new Map(), writes=[];
const api=new Proxy({}, {get:(_,name)=>(...args)=>{writes.push([name,...args]);return Promise.resolve({status:'completed',portfolio_run_id:'p1',task_id:'task1',result:{},kind:'ui_fixture',label:'fixture'});}});
function load(name) {
 if(cache.has(name)) return cache.get(name);
 const m={exports:{}}, js=ts.transpileModule(read('frontend/src/workspaces/'+name+'.ts'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const localRequire=id=>{
  if(id==='../lib/research-api')return {researchApi:api};
  if(id==='../lib/task-api')return {taskApi:api};
  if(id.endsWith('workspace-links'))return load('research/workspace-links');
  if(id.endsWith('workspace-evidence'))return load('research/workspace-evidence');
  throw new Error('Unexpected import; network is unavailable: '+id);
 };
 vm.runInNewContext('(function(require,module,exports){'+js+'\n})',{URLSearchParams,console})(localRequire,m,m.exports);
 cache.set(name,m.exports);return m.exports;
}
const links=load('research/workspace-links'), evidence=load('research/workspace-evidence');
assert.equal(evidence.completeLegacySnapshot({portfolio_id:'p',date:'2026-01-01',total_capital:1,expected_return:null,expected_volatility:0,strategy_weights:{},symbol_exposures:{}}),false);
assert.equal(evidence.completeLegacySnapshot({portfolio_id:'p',date:'2026-01-01',total_capital:1,expected_return:0,expected_volatility:0,strategy_weights:{},symbol_exposures:{}}),true);
assert.ok(links.referenceErrors({...links.emptyContext,candidate:'c1',manifests:['m1']},{candidates:[{candidate_id:'c1'}],experiments:[],manifests:[{strategy_candidate_id:'m1'}],qlib:[],portfolios:[]}).length,'No inferred candidate/manifest binding');
for (const path of ['C:\\temp','C:/temp','/tmp/data','\\rooted','\\\\server\\share','./data','data/./x','data/../x','file:data','data:stream']) assert.ok(links.parseWorkspaceContext(new URLSearchParams({dataRoot:path}).toString()).errors.length,path);
assert.equal(evidence.reviewSourceEligible({creation_allowed:true},'candidate','c1'),false);
assert.equal(evidence.reviewSourceEligible({creation_allowed:true,eligible_candidate_ids:['c2']},'candidate','c1'),false);
assert.equal(evidence.reviewSourceEligible({creation_allowed:true,eligible_candidate_ids:['c1']},'candidate','c1'),true);
const context={...links.emptyContext,candidate:'c1',experiment:'e1',qlibRun:'q1',portfolioRun:'p1',simulation:'s1',manifests:['m1','m2'],dataVersion:'dv1',featureVersion:'fv1'};
assert.equal(JSON.stringify(links.parseWorkspaceContext(links.workspaceLink('review',context).split('?')[1]).context),JSON.stringify(context));
for(const query of ['qlibRun=..','qlibRun=latest','portfolioRun=a%2Fb','dataRoot=..%2Fdata','dataRoot=https%3A%2F%2Fexample.com','qlibRun=a&qlibRun=b','manifest=..%2Fx']) assert.ok(links.parseWorkspaceContext(query).errors.length,query);
const qdetail={summary:{run_id:'q1',paths:{run_root:'artifacts/qlib_runs/q1'}},dataset_manifest:{data_version:'dv1'}};
const pdetail={summary:{portfolio_run_id:'p1',source_score_run_id:'q1',paths:{run_root:'artifacts/portfolio_runs/p1'}},run_manifest:{portfolio_run_id:'p1',source_score_run_id:'q1',config:{...evidence.portfolioConfigContracts['configs/portfolio/pypfopt_long_only_max_sharpe.yaml'],current_weights_path:''}}};
assert.equal(evidence.runEvidenceErrors('q1','artifacts/qlib_runs',qdetail,'qlib').length,0);
assert.ok(evidence.runEvidenceErrors('q2','artifacts/qlib_runs',qdetail,'qlib').length);
assert.ok(evidence.runEvidenceErrors('q1','other',qdetail,'qlib').length);
assert.ok(evidence.runEvidenceErrors('q1','artifacts/qlib_runs',null,'qlib').length);
assert.ok(evidence.runEvidenceErrors('p1','artifacts/portfolio_runs',pdetail,'portfolio','q2').length);
assert.ok(evidence.versionEvidenceErrors(context,[{data_version:'wrong',feature_version:'fv1'}]).length);
assert.ok(evidence.versionEvidenceErrors(context,[]).length);
assert.ok(evidence.simulationEvidenceErrors(context,{portfolio_sim_id:'s1'}).length,'No inferred manifest binding');
assert.ok(evidence.portfolioConfigMatches(pdetail,'configs/portfolio/pypfopt_long_only_max_sharpe.yaml','pypfopt_daily_only','equal_weight_topk'));
assert.equal(evidence.portfolioConfigMatches(pdetail,'configs/portfolio/pypfopt_hrp.yaml','pypfopt_daily_only','equal_weight_topk'),false);
for(const [path,contract]of Object.entries(evidence.portfolioConfigContracts)) {
 const yaml=Object.fromEntries(read(path).split('\n').filter(Boolean).map(line=>{const i=line.indexOf(':');const value=line.slice(i+1).trim();return[line.slice(0,i),value==='true'?true:value==='false'?false:Number.isFinite(Number(value))?Number(value):value];}));
 assert.equal(JSON.stringify(Object.entries(contract).sort()),JSON.stringify(Object.entries(yaml).sort()),'Config contract drift: '+path);
}
const errors=[],noop=()=>{},flush=()=>new Promise(resolve=>setImmediate(resolve));
const base={surface:'portfolio',actionBlocked:false,actionLock:{current:false},draftBinding:{current:null},dataRoot:'data',selectedQlibRunId:'q1',selectedPortfolioRunId:'p1',selectedManifestIds:['m1'],manifests:[{strategy_candidate_id:'m1',promotion_status:'READY_FOR_PORTFOLIO_SIM'}],qlibRuns:[{run_id:'q1',score_rows:2}],portfolioIntegrationRuns:[{portfolio_run_id:'p1',source_score_run_id:'q1',has_target_positions:true}],source:{...links.emptyContext},portfolioIntegrationDetail:pdetail,qlibRunDetail:qdetail,matchingPortfolioConfig:true,refresh:async()=>{},refreshIntegrationPanels:async()=>{},upsertTask:noop,trackTask:async()=>({}),portfolioForm:{initialCash:'50000',reviewer:'',reviewReason:''},qlibForm:{artifactsRoot:'artifacts/qlib_runs',qlibConfig:'configs/qlib/us_lgbm_alpha158_daily.yaml'},pypfoptForm:{scoreRunId:'q1',portfolioRunId:'',config:'configs/portfolio/pypfopt_long_only_max_sharpe.yaml',artifactsRoot:'artifacts/portfolio_runs',fallbackOptimizer:'equal_weight_topk',strategyId:'pypfopt_daily_only'},setPypfoptForm:noop,setPortfolioResult:noop,setPypfoptActionResult:noop,setPortfolioIntegrationDetail:noop,setExecutionPipelineResult:noop,setBusy:noop,setError:e=>errors.push(e),setMessage:noop};
const pf=load('portfolio-actions');
assert.equal(writes.length,0,'Factory creation/codec/read model has no side effects');
await pf.createPortfolioActions({...base,surface:'research'}).handlePortfolioSim(); assert.equal(writes.length,0);
await pf.createPortfolioActions({...base,actionBlocked:true}).handlePortfolioSim(); assert.equal(writes.length,0);
await pf.createPortfolioActions({...base,dataRoot:'data/custom'}).handlePortfolioSim(); assert.equal(writes.length,0);
await pf.createPortfolioActions({...base,selectedManifestIds:[]}).handlePortfolioSim(); assert.equal(writes.length,0);
pf.createPortfolioActions(base).handlePypfoptAction('unexpected');await flush();assert.equal(writes.length,0,'Unknown action never falls through to import');
pf.createPortfolioActions(base).handlePypfoptAction('import');await flush();assert.equal(writes.length,0,'Existing target positions cannot be overwritten');
pf.createPortfolioActions({...base,pypfoptForm:{...base.pypfoptForm,portfolioRunId:'draft1'},draftBinding:{current:{runId:'draft1',configKey:'different'}}}).handlePypfoptAction('covariance');await flush();assert.equal(writes.length,0,'Draft config mismatch blocked at command handler');
const firstDetail={...pdetail,target_positions_preview:[],target_positions_json:{}};
assert.equal(evidence.firstTargetImportAllowed([{portfolio_run_id:'p1',has_target_positions:false,target_weight_rows:2}],firstDetail,'p1'),true);
assert.equal(evidence.firstTargetImportAllowed([{portfolio_run_id:'p1',has_target_positions:true,target_weight_rows:2}],firstDetail,'p1'),false);
assert.equal(evidence.firstTargetImportAllowed([{portfolio_run_id:'p1',has_target_positions:false,target_weight_rows:2}],{...firstDetail,target_positions_json:{already:'exists'}},'p1'),false);
const a=pf.createPortfolioActions(base); await a.handlePortfolioSim(); assert.equal(writes[0][0],'runPortfolioSim'); assert.equal(JSON.stringify(writes[0].slice(1)),JSON.stringify([['m1'],{initial_cash:50000}]));
writes.length=0; pf.createPortfolioActions({...base,source:{...links.emptyContext,portfolioRun:'p1'}}).handlePypfoptAction('optimize'); await flush(); assert.equal(writes.length,0,'Existing version cannot be overwritten');
pf.createPortfolioActions({...base,dataRoot:'other'}).handlePypfoptAction('expected'); await flush(); assert.equal(writes.length,0);
pf.createPortfolioActions({...base,qlibRunDetail:null}).handlePypfoptAction('expected'); await flush(); assert.equal(writes.length,0);
await pf.createPortfolioActions({...base,matchingPortfolioConfig:false}).handleResearchExecutionPipeline(); assert.equal(writes.length,0);
a.handlePypfoptAction('expected'); await flush(); assert.equal(writes[0][0],'buildPortfolioExpectedReturns');assert.equal(writes[0][1].score_run_id,'q1');
writes.length=0;
let finish; const delayed={...base,refresh:()=>new Promise(resolve=>{finish=resolve;})};const commands=pf.createPortfolioActions(delayed);
const first=commands.handleResearchExecutionPipeline();await flush();await commands.handleResearchExecutionPipeline();assert.equal(writes.length,1,'Dispatcher locks double click');finish();await first;
writes.length=0; const review=load('review-actions');
const rc={...base,surface:'review',source:{...links.emptyContext,candidate:'c1',manifests:['m1']},pendingReviews:[{paper_review_id:'r1'}],portfolioResult:null,paperReviewEntry:{creation_allowed:true,eligible_candidate_ids:['c1'],eligible_manifest_ids:['m1']}};
await review.createReviewActions({...rc,paperReviewEntry:{creation_allowed:true}}).handleCreateReviewFromCandidate('c1');assert.equal(writes.length,0,'Global gate does not qualify this candidate');
await review.createReviewActions(rc).handleApproveReview('r1');assert.equal(writes.length,0,'Reviewer and reason required');
await review.createReviewActions(rc).handleCreateReviewFromCandidate('other');assert.equal(writes.length,0,'Only selected candidate');
await review.createReviewActions({...rc,portfolioForm:{reviewer:'UI tester',reviewReason:'mocked evidence verified'}}).handleApproveReview('r1');assert.equal(JSON.stringify(writes[0]),JSON.stringify(['approvePaperReview','r1','UI tester','mocked evidence verified']));
console.log('PASS: frozen rollback dependencies, page ownership, codec, run/root/version/config provenance, fail-closed actions, explicit payloads and duplicate-submit lock. No network calls.');
