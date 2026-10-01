import {test, expect, type Page} from '@playwright/test';
import {portfolioConfigContracts} from '../src/workspaces/research/workspace-evidence';

test('one crypto research run links all three pages to the same shared replay without trading writes',async({page})=>{
 const writes=await fixture(page,{crypto:true});
 const forbidden:string[]=[];
 page.on('request',request=>{if(/private|\/orders?(\/|$)/.test(new URL(request.url()).pathname))forbidden.push(request.url());});
 await page.goto('/research?view=qlib&qlibRun=q1');
 await expect(page.getByTestId('qlib-decision-trace')).toHaveCount(0);
 await expect(page.getByTestId('qlib-run-summary')).toContainText('真实执行未绑定');
 await expect(page.getByTestId('qlib-research-context')).toContainText('BTC-USDT-SWAP · 1h');
 await expect(page.getByTestId('qlib-research-context')).toContainText('已核验研究版本');
 await expect(page.getByTestId('qlib-research-context')).not.toContainText('AAPL');
 await page.getByRole('link',{name:'打开运行详情 / 决策回放 →'}).click();
 await expect(page).toHaveURL(/view=run-details/);
 await expect(page.getByTestId('qlib-decision-trace').locator('.qlib-layer-grid article')).toHaveCount(7);
 await page.getByRole('link',{name:'返回 Qlib 手动实验 →'}).click();
 await page.getByRole('button',{name:'将此评分用于组合',exact:true}).click();
 await expect(page).toHaveURL(/qlibRun=q1/);
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 await expect(page.getByRole('link',{name:'打开运行详情 / 决策回放 →'})).toHaveAttribute('href',/qlibRun=q1/);
 await expect(page.getByTestId('qlib-decision-trace')).toHaveCount(0);
 await page.goto('/strategy-modules?qlibRun=q1');
 await expect(page.getByTestId('qlib-decision-trace')).toHaveCount(0);
 await page.getByRole('link',{name:'打开运行详情 / 决策回放 →'}).click();
 await expect(page).toHaveURL(/qlibRun=q1/);
 await expect(page.getByTestId('qlib-decision-trace').locator('.qlib-layer-grid article')).toHaveCount(7);
 expect(writes).toEqual([]);expect(forbidden).toEqual([]);
});

test('unverified crypto trace never shows seven observed layers',async({page})=>{
 await fixture(page,{crypto:true,corruptTrace:true});
 await page.goto('/research?view=qlib&qlibRun=q1');
 await expect(page.getByTestId('qlib-run-summary')).toContainText('证据完整性未通过');
 await expect(page.getByTestId('qlib-research-context')).toContainText('未核验，事实未知');
 await expect(page.getByTestId('qlib-research-context')).not.toContainText('BTC-USDT-SWAP');
 await page.getByRole('link',{name:'打开运行详情 / 决策回放 →'}).click();
 await expect(page.getByTestId('qlib-decision-trace')).toContainText('证据完整性未通过');
 await expect(page.getByTestId('qlib-decision-trace').locator('.qlib-layer-grid article')).toHaveCount(0);
});

test('OKX profile survives source-clearing navigation with an isolated read-only context',async({page})=>{
 const writes=await fixture(page);
 const forbidden:string[]=[];
 page.on('request',request=>{if(/private|\/orders?(\/|$)/.test(new URL(request.url()).pathname))forbidden.push(request.url());});
 await page.goto('/research');
 await page.getByRole('tab',{name:'手动实验',exact:true}).click();
 await page.getByRole('tab',{name:'Qlib 模型研究',exact:true}).click();
 await page.getByRole('combobox',{name:'Qlib 研究配置'}).selectOption('okx_btc_trend_1h');
 await expect(page).toHaveURL(/view=qlib/);
 await expect(page.getByTestId('qlib-research-context')).toContainText('BTC-USDT-SWAP · 1h');
 await expect(page.getByRole('combobox',{name:'Qlib 研究配置'})).toHaveValue('okx_btc_trend_1h');
 await expect(page.getByTestId('qlib-research-context')).toContainText('待运行');
 await expect(page.getByTestId('qlib-research-context')).not.toContainText('AAPL');
 await expect(page.getByRole('textbox',{name:'Qlib 产物根目录',exact:true})).toHaveAttribute('readonly','');
 await expect(page.getByText('仅日频研究',{exact:true})).toHaveCount(0);
 await page.reload();
 await expect(page.getByRole('combobox',{name:'Qlib 研究配置'})).toHaveValue('okx_btc_trend_1h');
 await expect(page.getByTestId('qlib-research-context')).toContainText('BTC-USDT-SWAP · 1h');
 expect(writes).toEqual([]);expect(forbidden).toEqual([]);
});

test('shared Qlib pipeline sends only profile identity and handles failed task without old-run fallback',async({page})=>{
 const writes=await fixture(page);
 let submitted:any;
 await page.route('**/api/tasks/integrations/qlib/run-pipeline',async route=>{
   submitted=route.request().postDataJSON();
   await route.fulfill({json:{task_id:'failed-pipeline',status:'failed',kind:'qlib_pipeline',error:'fixture_training_failed',request:submitted}});
 });
 await page.route('**/api/tasks/failed-pipeline',route=>route.fulfill({json:{task_id:'failed-pipeline',status:'failed',kind:'qlib_pipeline',error:'fixture_training_failed',request:submitted}}));
 await page.goto('/research?view=qlib');
 await page.getByRole('combobox',{name:'Qlib 研究配置'}).selectOption('okx_btc_trend_1h');
 await page.getByRole('button',{name:'检查统一研究流程',exact:true}).click();
 await expect.poll(()=>submitted?.profile_id).toBe('okx_btc_trend_1h');
 expect(Object.keys(submitted).sort()).toEqual(['data_version','dry_run','profile_id','run_id']);
 await expect(page.getByRole('alert').filter({hasText:'fixture_training_failed'})).toBeVisible();
 expect(writes).toEqual([]);
});
type Options={crypto?:boolean;corruptTrace?:boolean;empty?:boolean; badDetail?:boolean; failedDetail?:boolean; failedLists?:boolean; missingReviewGate?:boolean; unqualifiedReview?:boolean};
async function fixture(page:Page,options:Options={}) {
 const writes:{path:string;body:any}[]=[];
 const config=portfolioConfigContracts['configs/portfolio/pypfopt_long_only_max_sharpe.yaml'];
 await page.route('**/api/**',async route=>{
  const request=route.request(), url=new URL(request.url()), path=url.pathname, root=url.searchParams.get('artifacts_root');
  if(request.method()!=='GET'){
   writes.push({path,body:request.postDataJSON()});
   if(path.startsWith('/api/tasks/'))await route.fulfill({json:{task_id:'ui-task',status:'completed',kind:'portfolio_optimize_weights',label:'UI fixture',result:{portfolio_run_id:'p1'}}});
   else await route.fulfill({json:{status:'completed',portfolio_sim_id:'s1',portfolio_run_id:'p1',research_only:true,live_enabled:false}});
   return;
  }
  let data:any={};
  if(path==='/api/health')data={status:'ok',evidence_profile:'demo_quasi_live',read_only:false,controls_disabled:false};
  else if(path==='/api/strategies'||path==='/api/tasks')data=[];
  else if(path==='/api/tasks/ui-task')data={task_id:'ui-task',status:'completed',kind:'portfolio_optimize_weights',label:'UI fixture',result:{portfolio_run_id:'p1'}};
  else if(path==='/api/research/experiments')data=options.empty?[]:[{experiment_id:'e1',strategy_id:'trend_momentum',status:'completed',created_at:'2026-09-01',data_version:'dv1',feature_version:'fv1'}];
  else if(path==='/api/research/candidates')data=options.empty?[]:[{candidate_id:'c1',experiment_id:'e1',strategy_id:'trend_momentum',promotion_status:'READY_FOR_PORTFOLIO_SIM',turnover_score:0.1,created_at:'2026-09-01',data_version:'dv1',feature_version:'fv1'}];
  else if(path==='/api/research/strategy-manifests')data=options.empty?[]:[{strategy_candidate_id:'m1',source_candidate_id:'c1',promotion_status:'READY_FOR_PORTFOLIO_SIM',symbols:['AAPL']}];
  else if(path==='/api/research/features'||path==='/api/research/factors')data=[];
  else if(path==='/api/research/paper-review/pending')data=options.empty?[]:[{paper_review_id:'r1',status:'PENDING',strategy_manifest_id:'m1'}];
  else if(path==='/api/research/paper-review/entry-state')data=options.missingReviewGate?{}:{creation_allowed:true,eligible_candidate_ids:options.unqualifiedReview?['c2']:['c1'],eligible_manifest_ids:options.unqualifiedReview?['m2']:['m1'],why_blocked:[],status:'RESEARCH_ONLY'};
  else if(path==='/api/integrations/qlib/runs'){
   if(options.failedLists){await route.fulfill({status:503,json:{detail:'unavailable'}});return;}
   data={status:'ok',dependencies:{qlib:true,lightgbm:true},profiles:[
     {profile_id:'us_equity_daily',label:'美股 · Alpha158 日线',asset_class:'equity'},
     {profile_id:'okx_btc_trend_1h',label:'OKX BTC 永续 · 趋势小时线',asset_class:'crypto',bar_size:'1h',symbols:['BTC-USDT-SWAP'],source:'okx',data_version:'fixture-okx',
       config:'configs/qlib/okx_btc_trend_1h.yaml',universe:'configs/universe/okx_btc_perpetual_1h.yaml',start_date:'2025-12-22',end_date:'2026-07-29'}],
     runs:options.empty?[]:[{run_id:'q2',score_rows:2,workflow_status:'completed'},{run_id:'q1',score_rows:5,workflow_status:'completed'}]};
  }
  else if(path.startsWith('/api/integrations/qlib/runs/')){
   if(options.failedDetail){await route.fulfill({status:503,json:{detail:'missing detail'}});return;}
   const id=path.split('/').pop();
   data={summary:{run_id:options.badDetail?'wrong':id,score_rows:5,paths:{run_root:(root||'artifacts/qlib_runs')+'/'+id}},dataset_manifest:{data_version:'dv1',feature_version:'fv1'},scores_preview:[{symbol:'AAPL',score:0.2}]};
   if(options.crypto){
     data.summary.asset_class='crypto';
     data.integrity_status=options.corruptTrace?'blocked':'passed';
     data.research_trace={identity:{qlib_run_id:id,profile_id:'okx_btc_trend_1h',strategy_version:'fixture-v1',candidate_id:id,
       venue:'okx',instrument:'BTC-USDT-SWAP',bar_size:'1h',data_version:'fixture-okx',source_head:'fixture-head'},
       status:'research_flow_completed',decision_count:1,simulated_fill_count:1,reconciliation:{status:'passed'},
       as_of:'2026-07-01T01:00:00Z',research_metrics:{net_return:.01},calibration:{sample_size:500},limitations:['fixture_only']};
     data.decision_trace_preview=[{decision_id:'fixture-decision',decision_time:'2026-07-01T00:00:00Z',
       layers:Object.fromEntries(['alpha','regime','risk','allocation','position','exit','execution'].map(key=>[key,{status:'passed',truth_kind:'research_observed',blockers:[]}]))}];
   }
  }
  else if(path==='/api/integrations/portfolio/runs')data={status:'ok',dependencies:{pypfopt:true},runs:options.empty?[]:[{portfolio_run_id:'p2',source_score_run_id:'q2',has_target_positions:true},{portfolio_run_id:'p1',source_score_run_id:'q1',has_target_positions:true,status:'RESEARCH_ONLY',latest_weight_sum:0.5,fallback_used:true}]};
  else if(path.startsWith('/api/integrations/portfolio/runs/')){
   if(options.failedDetail){await route.fulfill({status:503,json:{detail:'missing detail'}});return;}
   const id=path.split('/').pop(), qid=id==='p2'?'q2':'q1';
   data={summary:{portfolio_run_id:id,source_score_run_id:qid,paths:{run_root:(root||'artifacts/portfolio_runs')+'/'+id}},run_manifest:{portfolio_run_id:id,source_score_run_id:qid,config:{...config,current_weights_path:''},research_only:true},target_weights_preview:[{symbol:'AAPL',target_weight:0.15}],target_positions_preview:[{symbol:'AAPL',target_weight:0.15}],target_positions_json:{source:'existing'}};
  }
  else if(path==='/api/portfolio/status')data={status:'ok',latest_portfolio:{portfolio_id:'old-target-only',date:'2026-08-01',total_capital:100000,expected_return:0.1,expected_volatility:0.2,strategy_weights:{strategy_a:1},symbol_exposures:{AAPL:0.4}}};
  else if(path==='/api/research/portfolio-sims/s1')data={portfolio_sim_id:'s1',decision:'RESEARCH_ONLY',contribution_by_strategy:{strategy_a:1}};
  else if(path==='/api/system/overview')data={stage:'RESEARCH_ONLY',paper_enabled:false,live_enabled:false};
  await route.fulfill({json:data});
 });
 return writes;
}
test('canonical pages have exclusive tools and five primary research workspaces',async({page})=>{
 const writes=await fixture(page);
 await page.goto('/research?view=qlib');
 await expect(page.getByRole('tablist',{name:'研究工作区'}).getByRole('tab')).toHaveCount(5);
 await expect(page.getByRole('button',{name:'运行工作流',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'人工批准',exact:true})).toHaveCount(0);
 await page.getByRole('tab',{name:'候选与证据',exact:true}).click();
 await page.getByRole('tab',{name:'候选与来源交接',exact:true}).click();
 await expect(page.getByRole('tabpanel')).toContainText('选择研究来源');
 await page.goto('/portfolio?view=optimize');
 await expect(page.getByRole('button',{name:'运行工作流',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 expect(writes).toEqual([]);
});
test('selected Qlib ID, roots and versions survive handoff with no auto POST or latest fallback',async({page})=>{
 const writes=await fixture(page);
 await page.goto('/research?view=qlib&qlibRun=q1&dataVersion=dv1&featureVersion=fv1');
 const handoff=page.getByRole('button',{name:'将此评分用于组合',exact:true});
 await expect(handoff).toBeEnabled(); await handoff.click();
 await expect(page).toHaveURL(/\/portfolio\?/);
 let query=new URL(page.url()).searchParams;
 expect(query.get('qlibRun')).toBe('q1');expect(query.get('dataRoot')).toBe('data');expect(query.get('dataVersion')).toBe('dv1');expect(query.get('featureVersion')).toBe('fv1');
 await expect(page.getByRole('combobox',{name:'评分运行 ID',exact:true})).toHaveValue('q1');
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'执行安全中心 · 人工复核',exact:true}).click();
 query=new URL(page.url()).searchParams;expect(query.get('qlibRun')).toBe('q1');expect(query.get('view')).toBe('research-review');
 await expect(page.getByRole('heading',{name:/研究准入人工复核/})).toBeVisible();
 expect(writes).toEqual([]);
});
test('candidate, experiment and manifest handoff stays explicit',async({page})=>{
 const writes=await fixture(page);await page.goto('/research?view=handoff');
 await page.getByRole('button',{name:'用于组合 · c1',exact:true}).click();
 const q=new URL(page.url()).searchParams;
 expect(q.get('candidate')).toBe('c1');expect(q.get('experiment')).toBe('e1');expect(q.getAll('manifest')).toEqual(['m1']);expect(q.get('dataVersion')).toBe('dv1');
 await expect(page.getByRole('button',{name:'运行组合模拟',exact:true})).toBeEnabled();expect(writes).toEqual([]);
 await page.getByRole('button',{name:'运行组合模拟',exact:true}).click();
 await expect.poll(()=>writes.length).toBe(1);expect(writes[0]).toEqual({path:'/api/research/portfolio-sims/run',body:{manifest_ids:['m1'],config:{initial_cash:50000}}});
});
test('one mocked optimization writes the exact selected source only',async({page})=>{
 const writes=await fixture(page);await page.goto('/portfolio?view=optimize&qlibRun=q1');
 const button=page.getByRole('button',{name:'优化目标权重',exact:true});await expect(button).toBeEnabled();await button.click();
 await expect.poll(()=>writes.length).toBe(1);
 expect(writes[0].path).toBe('/api/tasks/integrations/portfolio/optimize-weights');
 expect(writes[0].body.score_run_id).toBe('q1');expect(writes[0].body.portfolio_run_id).toBeUndefined();
});
test('selected portfolio version is immutable and risk uses bound config, not newest version',async({page})=>{
 const writes=await fixture(page);await page.goto('/portfolio?view=optimize&qlibRun=q1&portfolioRun=p1');
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'运行风险回测流水线',exact:true})).toBeEnabled();
 await expect(page.getByRole('button',{name:'导入目标持仓',exact:true})).toBeDisabled();
 const weights = page.getByRole('heading',{name:'target_weights 预览',exact:true}).locator('xpath=ancestor::section[1]');
 await expect(weights.getByRole('cell',{name:'AAPL',exact:true})).toBeVisible();
 await page.getByRole('tab',{name:'风险与证据',exact:true}).click();
 await expect(page.getByRole('tabpanel')).toContainText('当前版本：p1');
 await expect(page.getByRole('tabpanel')).toContainText('降级优化器');
 await expect(page.getByRole('tabpanel')).toContainText('没有证据不表示风险为零');
 expect(writes).toEqual([]);
});
test('intermediate portfolio draft freezes source and config until a new version is created',async({page})=>{
 const writes=await fixture(page);
 await page.route('**/api/integrations/portfolio/build-expected-returns',async r=>{writes.push({path:new URL(r.request().url()).pathname,body:r.request().postDataJSON()});await r.fulfill({json:{portfolio_run_id:'draft1',status:'completed'}});});
 await page.goto('/portfolio?view=optimize&qlibRun=q1');
 await page.getByRole('button',{name:'生成预期收益',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'评分运行 ID',exact:true})).toBeDisabled();
 await expect(page.getByRole('combobox',{name:'优化器配置',exact:true})).toBeDisabled();
 await expect(page.getByRole('combobox',{name:'降级优化器',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'基于此评分新建版本',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'优化器配置',exact:true})).toBeEnabled();
 expect(writes).toHaveLength(1);
});
for(const [name,query,options] of [
 ['unknown source','qlibRun=missing',{}],
 ['version mismatch','qlibRun=q1&dataVersion=wrong',{}],
 ['detail identity mismatch','qlibRun=q1',{badDetail:true}],
 ['failed detail','qlibRun=q1',{failedDetail:true}],
 ['source score mismatch','qlibRun=q2&portfolioRun=p1',{}],
 ['custom data root is readonly','qlibRun=q1&dataRoot=data%2Fcustom',{}],
 ['custom artifact root is readonly','qlibRun=q1&qlibRoot=artifacts%2Fcustom',{}],
 ['invalid path','qlibRun=q1&dataRoot=..%2Fother',{}],
] as const) test(name+' blocks writes',async({page})=>{
 const writes=await fixture(page,options);await page.goto('/portfolio?view=optimize&'+query);
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();expect(writes).toEqual([]);
});
test('clearing or failing a source read never leaves the previous detail actionable',async({page})=>{
 const writes=await fixture(page);await page.goto('/portfolio?view=optimize&qlibRun=q1');
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeEnabled();
 await page.getByRole('combobox',{name:'评分运行 ID',exact:true}).selectOption('');
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 await page.route('**/api/integrations/qlib/runs/q1**',r=>r.fulfill({status:503,json:{detail:'failed reread'}}));
 await page.getByRole('combobox',{name:'评分运行 ID',exact:true}).selectOption('q1');
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 await expect(page.getByRole('alert').filter({hasText:'Qlib 详情读取失败'})).toBeVisible();
 expect(writes).toEqual([]);
});
test('review requires explicit selected evidence and reviewer plus reason; all requests mocked',async({page})=>{
 const writes=await fixture(page);await page.goto('/live?view=research-review&candidate=c1&experiment=e1&manifest=m1');
 const approve=page.getByRole('button',{name:'人工批准',exact:true});await expect(approve).toBeDisabled();
 await expect(page.getByRole('button',{name:'从所选候选创建复核',exact:true})).toBeEnabled();expect(writes).toEqual([]);
 await page.getByRole('button',{name:'从所选候选创建复核',exact:true}).click();
 await expect.poll(()=>writes.length).toBe(1);expect(writes[0]).toEqual({path:'/api/research/paper-review/create',body:{candidate_id:'c1',data_root:'data'}});
 await page.getByLabel('复核人',{exact:true}).fill('UI tester');await expect(approve).toBeDisabled();
 await page.getByLabel('批准理由',{exact:true}).fill('mocked evidence verified');
 await expect(approve).toBeEnabled();await approve.click();
 await expect.poll(()=>writes.length).toBe(2);expect(writes[1]).toEqual({path:'/api/research/paper-review/r1/approve',body:{manual:true,reviewer:'UI tester',reason:'mocked evidence verified'}});
});
test('unproven simulation-manifest binding and missing review gate stay blocked',async({page})=>{
 const writes=await fixture(page,{missingReviewGate:true});await page.goto('/live?view=research-review&simulation=s1&manifest=m1');
 await expect(page.getByRole('button',{name:'从已核验模拟创建复核',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'从所选策略证据创建复核',exact:true})).toBeDisabled();
 await expect(page.getByRole('alert').filter({hasText:'未提供策略证据编号绑定'})).toBeVisible();expect(writes).toEqual([]);
});
test('empty and failed registries remain distinguishable; old target snapshot has no inert rebalance control',async({page})=>{
 const writes=await fixture(page,{empty:true});await page.goto('/portfolio');
 await expect(page.getByRole('tabpanel')).toContainText('尚未生成组合版本');
 await page.getByText('旧目标快照（独立来源，不作为当前组合结果）',{exact:true}).click();
 await expect(page.getByRole('tabpanel')).toContainText('old-target-only');
 await expect(page.getByText('再平衡尚未接入受控提交；当前快照只用于查看。',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:/再平衡/})).toHaveCount(0);
 await page.goto('/portfolio?view=simulate');await expect(page.getByRole('button',{name:'运行组合模拟',exact:true})).toBeDisabled();expect(writes).toEqual([]);
});
test('keyboard, compact layouts and both saved rollback routes remain available',async({page})=>{
 // Legacy links deliberately perform full document navigation through the canonical guard.
 test.setTimeout(60000);
 const writes=await fixture(page);await page.setViewportSize({width:768,height:900});
 await page.goto('/research');const first=page.getByRole('tablist',{name:'研究工作区'}).getByRole('tab').first();await first.focus();await page.keyboard.press('End');
 await expect(page.getByRole('tab',{name:'候选与证据',exact:true})).toBeFocused();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.getByRole('link',{name:'切回改版前',exact:true}).click();await expect(page).toHaveURL(/layout=previous/);
 await expect(page.getByRole('tab',{name:/组合与复核/})).toBeVisible({timeout:15000});
 await page.getByRole('link',{name:'返回新版研究台',exact:true}).click();
 await expect(page.getByRole('tablist',{name:'研究工作区'})).toBeVisible({timeout:15000});
 await page.goto('/portfolio');const tabs=page.getByRole('tablist',{name:'投资组合工作流'});await tabs.getByRole('tab').first().focus();await page.keyboard.press('End');
 await expect(tabs.getByRole('tab',{name:'风险与证据',exact:true})).toBeFocused();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.getByRole('link',{name:'切回改版前',exact:true}).click();await expect(page).toHaveURL(/layout=legacy/);
 await expect(page.getByRole('heading',{name:'投资组合监控',exact:true})).toBeVisible({timeout:15000});
 await page.getByRole('link',{name:'返回新版投资组合',exact:true}).click();await expect(page.getByRole('heading',{name:/组合构建与风险/})).toBeVisible({timeout:15000});
 expect(writes).toEqual([]);
});
test('global review readiness does not qualify a different selected candidate or manifest',async({page})=>{
 const writes=await fixture(page,{unqualifiedReview:true});
 await page.goto('/live?view=research-review&candidate=c1&experiment=e1&manifest=m1');
 await expect(page.getByRole('button',{name:'从所选候选创建复核',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'从所选策略证据创建复核',exact:true})).toBeDisabled();
 expect(writes).toEqual([]);
});
for(const path of ['C:\\temp','C:/temp','/tmp/data','\\rooted','\\\\server\\share','data/./x']) test('invalid root has no source GET or POST: '+path,async({page})=>{
 const writes=await fixture(page), reads:string[]=[];
 page.on('request',r=>{if(/\/api\/(?:integrations|research)\//.test(r.url()))reads.push(r.url());});
 await page.goto('/portfolio?view=optimize&qlibRun=q1&portfolioRun=p1&dataRoot='+encodeURIComponent(path));
 await expect(page.getByRole('alert').filter({hasText:'无效的来源字段'})).toBeVisible();
 await expect(page.getByRole('button',{name:'优化目标权重',exact:true})).toBeDisabled();
 expect(reads).toEqual([]);expect(writes).toEqual([]);
});

test('first target import is explicit and a completed import cannot be repeated',async({page})=>{
 const writes=await fixture(page);let imported=false;
 const config=portfolioConfigContracts['configs/portfolio/pypfopt_long_only_max_sharpe.yaml'];
 await page.route('**/api/integrations/portfolio/runs?**',r=>r.fulfill({json:{dependencies:{pypfopt:true},runs:[{portfolio_run_id:'p1',source_score_run_id:'q1',target_weight_rows:2,has_target_positions:imported}]}}));
 await page.route('**/api/integrations/portfolio/runs/p1?**',r=>r.fulfill({json:{
   summary:{portfolio_run_id:'p1',source_score_run_id:'q1',paths:{run_root:'artifacts/portfolio_runs/p1'}},
   run_manifest:{portfolio_run_id:'p1',source_score_run_id:'q1',config:{...config,current_weights_path:''}},
   target_weights_preview:[{symbol:'AAPL',target_weight:0.15}],
   target_positions_preview:imported?[{symbol:'AAPL'}]:[],target_positions_json:imported?{source:'imported'}:{}
 }}));
 await page.route('**/api/integrations/portfolio/import-target-weights',async r=>{writes.push({path:new URL(r.request().url()).pathname,body:r.request().postDataJSON()});imported=true;await r.fulfill({json:{portfolio_run_id:'p1',status:'completed'}});});
 await page.goto('/portfolio?view=optimize&qlibRun=q1&portfolioRun=p1');
 const button=page.getByRole('button',{name:'导入目标持仓',exact:true});await expect(button).toBeEnabled();await button.click();
 await expect.poll(()=>writes.length).toBe(1);expect(writes[0].body.portfolio_run_id).toBe('p1');expect(writes[0].body.score_run_id).toBe('q1');
 await expect(button).toBeDisabled();
});
test('malformed old target snapshot remains an explicit error rather than crashing or showing zero',async({page})=>{
 const writes=await fixture(page);
 await page.route('**/api/portfolio/status',r=>r.fulfill({json:{status:'ok',latest_portfolio:{portfolio_id:'broken',date:'2026-01-01'}}}));
 await page.goto('/portfolio');
 await page.getByText('旧目标快照（独立来源，不作为当前组合结果）',{exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'旧目标快照字段不完整'})).toBeVisible();
 await expect(page.getByRole('heading',{name:/组合构建与风险/})).toBeVisible();expect(writes).toEqual([]);
});
