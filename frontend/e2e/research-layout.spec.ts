import {test,expect,type Page} from '@playwright/test';

// Synthetic UI evidence only; no test here trains, resumes, promotes or trades.
const safety=Object.fromEntries(['promotion','paper','live','private','order','real_order','transfer','withdraw','execution_permission','runtime_observed'].map(key=>[key,false]));
const profile={profile_id:'okx_btc_trend_1h',label:'BTC · OKX 永续 / 1h',metric_mode:'time_series',data_version:'dv',training_enabled:true,...safety};
const factory=(id:string)=>({run_id:id,status:'completed',profile_id:profile.profile_id,integrity_status:'passed',source_head:'historical-fixture',source_stale:true,stages:{train:'completed',screen:'completed',nominate:'completed'},events:[],...safety,
  result:{decision:'rejected',audit_status:'not_run_selection_failed',candidates:[],qlib_fit_count:8,factor_search:{trials:[],trial_count:43,unique_expression_count:41},profile,model_trials:[{trial_number:1,model_id:'synthetic-model',status:'completed',qlib_runs:[{qlib_run_id:'fold',seal_sha256:'synthetic'}],screen_blockers:['selection_rejected']}],split_plan:{segments:{}},lineage:{}}});
const qlib=(id:string,options:Record<string,unknown>={})=>({summary:{run_id:id,source_head:'historical-fixture',paths:{run_root:'artifacts/qlib_runs/'+id}},dataset_manifest:{data_version:'dv',feature_version:'fv'},integrity_status:'passed',seal:{source_head:'historical-fixture'},...safety,
  research_trace:{identity:{qlib_run_id:id,source_head:'historical-fixture',strategy_version:'synthetic',instrument:'BTC-USDT-SWAP'},status:'research_flow_blocked',decision_count:2,simulated_fill_count:0,blockers:['no_simulated_fills'],reconciliation:{status:'passed'}},
  decision_trace_preview:['early','late'].map((time,index)=>({decision_id:time,decision_time:time,layers:Object.fromEntries(['alpha','regime','risk','allocation','position','exit','execution'].map(key=>[key,{status:'passed',truth_kind:'research_simulated',raw_score:index+1,expected_return_bps:index+1,target_weight:(index+1)/10,quantity_before:index+1,triggered:index===1,reasons:[id+'-'+time+'-exit'],risk_truth_kind:id+'-'+time+'-risk',runtime_status:id+'-'+time+'-execution'}]))})),...options});
async function fixture(page:Page) {
  const posts:string[]=[];const requests:string[]=[];
  page.on('request',r=>{const path=new URL(r.url()).pathname;requests.push(path);if(r.method()!=='GET')posts.push(path);});
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/research/alpha-factory')return route.fulfill({json:{profiles:[profile],runs:[factory('batch')],...safety}});
    if(path.startsWith('/api/research/alpha-factory/runs/'))return route.fulfill({json:factory(path.split('/').at(-1)!)});
    if(path==='/api/integrations/qlib/runs')return route.fulfill({json:{runs:[{run_id:'first'},{run_id:'second'},{run_id:'fold'}]}});
    if(path.startsWith('/api/integrations/qlib/runs/')) {
      const id=path.split('/').at(-1)!;
      if(id==='missing')return route.fulfill({status:404,json:{detail:'exact_run_missing'}});
      return route.fulfill({json:qlib(id,id==='fold'?{research_trace:{},decision_trace_preview:[],pipeline:{stages:{training:{status:'completed'},candidate:{status:'completed'}}}}:{})});
    }
    if(/experiments|candidates|features|factors|strategy-manifests|pending|\/tasks$/.test(path))return route.fulfill({json:[]});
    return route.fulfill({json:{}});
  });
  return {posts,requests};
}

for(const viewport of [{width:1131,height:975},{width:390,height:844}]) test(`factory conclusion has priority at ${viewport.width}px without registry reads`,async({page})=>{
  await page.setViewportSize(viewport);const seen=await fixture(page);
  await page.goto('/research?view=alpha-factory&factoryRun=batch');
  const nav=page.getByRole('tablist',{name:'研究工作区'});await expect(nav.getByRole('tab')).toHaveCount(5);
  await expect(nav.getByRole('tab',{name:'Alpha 工厂',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('region',{name:'研究状态总览'})).toHaveCount(0);
  await expect(page.locator('#research-subviews')).toHaveCount(0);
  await expect(page.locator('.af-new-batch')).not.toHaveAttribute('open','');
  const conclusion=page.getByTestId('factory-run-conclusion');await expect(conclusion).toContainText('淘汰');
  const box=await conclusion.boundingBox();expect(box!.y).toBeLessThan(viewport.height-220);
  expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(viewport.width+1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(seen.requests.some(path=>path==='/api/research/experiments')).toBe(false);expect(seen.posts).toEqual([]);
});

test('exact Qlib deep link shows conclusion before folded provenance and separate replay',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=run-details&qlibRun=first&dataVersion=dv&featureVersion=fv');
  const summary=page.getByTestId('qlib-run-summary');await expect(summary).toContainText('no_simulated_fills');
  await expect(page.getByTestId('run-context-warning')).toHaveCount(0);
  const provenance=summary.locator('details').filter({has:page.getByText('版本、数据来源与研究产物',{exact:true})});
  await expect(provenance).toHaveCount(1);
  await expect(summary).toContainText('源版本不同');await expect(provenance).not.toHaveAttribute('open','');
  await expect(summary.getByTestId('trend-environment-evidence')).not.toHaveAttribute('open','');
  await expect(page.getByTestId('qlib-decision-trace').locator('.qlib-layer-grid article')).toHaveCount(7);
  await expect(page.getByRole('region',{name:'实际运行证据'})).toContainText('未绑定');
  const back=page.getByRole('link',{name:'返回 Qlib 手动实验 →'});
  await expect(back).toHaveAttribute('href',/qlibRun=first/);await expect(back).toHaveAttribute('href',/dataVersion=dv/);await expect(back).toHaveAttribute('href',/featureVersion=fv/);
  expect(seen.posts).toEqual([]);
});

test('decision time changes update all seven layers together and new run resets local decision',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=run-details&qlibRun=first');
  const replay=page.getByTestId('qlib-decision-trace');const picker=replay.getByRole('combobox');
  await expect(replay).toContainText('first-late-execution');await picker.selectOption('first:early');
  for(const label of ['first-early-risk','first-early-exit','first-early-execution'])await expect(replay).toContainText(label);
  await expect(replay.locator('article').nth(0).locator('dd').first()).toHaveText('1');
  await expect(replay.locator('article').nth(4).locator('dd').first()).toHaveText('1');
  await page.getByRole('combobox',{name:'选择精确研究运行'}).selectOption('qlib:second');
  await expect(replay).toContainText('second-late-execution');await expect(replay).not.toContainText('first-');expect(seen.posts).toEqual([]);
});

test('late Qlib response cannot replace newly selected run and browser history restores identity',async({page})=>{
  const seen=await fixture(page);let release=()=>{};const delayed=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/integrations/qlib/runs/first?**',async route=>{await delayed;return route.fulfill({json:qlib('first')});});
  await page.goto('/research?view=run-details&qlibRun=first');
  await page.getByRole('combobox',{name:'选择精确研究运行'}).selectOption('qlib:second');
  await expect(page.getByTestId('qlib-decision-trace')).toContainText('second-late-execution');release();
  await expect(page.getByTestId('qlib-decision-trace')).not.toContainText('first-');
  await page.goBack();await expect(page).toHaveURL(/qlibRun=first/);await expect(page.getByTestId('qlib-decision-trace')).toContainText('first-late-execution');
  await page.goForward();await expect(page.getByTestId('qlib-decision-trace')).toContainText('second-late-execution');expect(seen.posts).toEqual([]);
});

test('bad seal and unsafe contract never reveal cached stages or research facts',async({page})=>{
  const seen=await fixture(page);
  await page.route('**/api/integrations/qlib/runs/first?**',route=>route.fulfill({json:qlib('first',{integrity_status:'blocked',pipeline:{stages:{training:{status:'completed'}}}})}));
  await page.goto('/research?view=run-details&qlibRun=first');await expect(page.getByTestId('qlib-run-summary')).toContainText('证据完整性未通过');
  await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);await expect(page.locator('.qlib-stage-list')).toHaveCount(0);
  await page.route('**/api/integrations/qlib/runs/second?**',route=>route.fulfill({json:qlib('second',{live:true})}));
  await page.getByRole('combobox',{name:'选择精确研究运行'}).selectOption('qlib:second');await expect(page.getByTestId('qlib-run-summary')).toContainText('安全合同异常');
  await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);expect(seen.posts).toEqual([]);
});

test('missing exact run, invalid root and absent selection never select a replacement',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=run-details&qlibRun=missing');
  await expect(page.getByRole('alert')).toContainText('不回退到最新运行');await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);
  await page.goto('/research?view=run-details&qlibRun=first&qlibRoot=other');await expect(page.getByRole('alert')).toContainText('不是服务器固定研究目录');
  expect(seen.requests.some(path=>path.endsWith('/runs/first'))).toBe(false);
  await page.goto('/research?view=run-details');await expect(page.getByRole('heading',{name:'先选择一次运行'})).toBeVisible();
  await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);expect(seen.posts).toEqual([]);
});

test('factory detail is readonly and completed child fold is not a candidate or seven-layer replay',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=run-details&factoryRun=batch');
  await expect(page.getByTestId('factory-run-conclusion')).toContainText('淘汰');
  await expect(page.locator('.af-new-batch')).toHaveCount(0);await expect(page.getByRole('button',{name:'启动统一研究批次'})).toHaveCount(0);
  await page.getByText('逐折 Qlib 运行、环境旁路与封印',{exact:true}).click();await page.getByRole('link',{name:'fold',exact:true}).click();
  await expect(page).toHaveURL(/qlibRun=fold/);expect(new URL(page.url()).searchParams.get('factoryRun')).toBeNull();
  await expect(page.getByTestId('qlib-run-summary')).toContainText('未生成七层决策记录');await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);
  expect(seen.posts).toEqual([]);
});

test('same-source manual workspace navigation and history preserve unsubmitted draft',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=cycle');
  await page.getByRole('textbox',{name:'策略 ID',exact:true}).fill('unsubmitted-draft');
  await page.getByRole('tab',{name:'数据与因子',exact:true}).click();
  await page.goBack();await expect(page.getByRole('textbox',{name:'策略 ID',exact:true})).toHaveValue('unsubmitted-draft');
  await page.goForward();await expect(page.getByRole('tab',{name:'数据与因子',exact:true})).toHaveAttribute('aria-selected','true');
  await page.getByRole('tab',{name:'手动实验',exact:true}).click();await expect(page.getByRole('textbox',{name:'策略 ID',exact:true})).toHaveValue('unsubmitted-draft');
  expect(seen.posts).toEqual([]);
});

test('ambiguous source IDs and mismatched responses cannot silently choose a run',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=run-details&factoryRun=batch&qlibRun=first');
  await expect(page.getByRole('alert')).toContainText('同时指定两类运行');
  expect(seen.requests.some(path=>path.endsWith('/runs/first')||path.endsWith('/runs/batch'))).toBe(false);
  await page.route('**/api/integrations/qlib/runs/first?**',route=>route.fulfill({json:qlib('wrong')}));
  await page.goto('/research?view=run-details&qlibRun=first');await expect(page.getByRole('alert')).toContainText('运行身份或来源目录不匹配');
  await expect(page.locator('.qlib-layer-grid article')).toHaveCount(0);await expect(page.getByTestId('qlib-run-summary')).not.toContainText('wrong');expect(seen.posts).toEqual([]);
});

for(const scenario of ['matching','missing','mismatched'] as const) test(`Qlib URL version hints are ${scenario} without replacing sealed facts`,async({page})=>{
  const seen=await fixture(page);
  if(scenario==='missing')await page.route('**/api/integrations/qlib/runs/first?**',route=>route.fulfill({json:qlib('first',{dataset_manifest:{}})}));
  const dataVersion=scenario==='mismatched'?'untrusted-other-version':'dv';
  await page.goto(`/research?view=run-details&qlibRun=first&dataVersion=${dataVersion}&featureVersion=fv`);
  await expect(page.getByTestId('qlib-decision-trace')).toContainText('first-late-execution');
  const warning=page.getByTestId('run-context-warning');
  if(scenario==='matching')await expect(warning).toHaveCount(0);
  else {await expect(warning).toContainText('以下只按封印 run 展示');await expect(warning).toContainText(scenario==='missing'?'缺少原件证明':'与来源原件不匹配');}
  const identity=page.getByTestId('qlib-run-summary').locator('details').filter({has:page.getByText('版本、数据来源与研究产物',{exact:true})});
  await expect(identity).toHaveCount(1);
  await identity.locator(':scope > summary').click();await expect(identity).toHaveAttribute('open','');
  await expect(identity).not.toContainText('untrusted-other-version');
  await expect(page.getByTestId('trend-environment-evidence')).not.toHaveAttribute('open','');
  expect(seen.posts).toEqual([]);
  // Development StrictMode replays the existing loader once; hint checks add no loader.
  expect(seen.requests.filter(path=>path==='/api/integrations/qlib/runs/first').length).toBeLessThanOrEqual(2);
});

for(const scenario of ['matching','missing-feature-contract','mismatched'] as const) test(`factory URL version hints are ${scenario} using the existing sealed response`,async({page})=>{
  const seen=await fixture(page);
  const hints=scenario==='mismatched'?'dataVersion=untrusted-other-version':scenario==='missing-feature-contract'?'dataVersion=dv&featureVersion=fv':'dataVersion=dv';
  await page.goto('/research?view=run-details&factoryRun=batch&'+hints);
  await expect(page.getByTestId('factory-run-conclusion')).toContainText('淘汰');
  const warning=page.getByTestId('run-context-warning');
  if(scenario==='matching')await expect(warning).toHaveCount(0);
  else {await expect(warning).toContainText('以下只按封印 run 展示');await expect(warning).toContainText(scenario==='mismatched'?'与来源原件不匹配':'feature_version 缺少原件证明');}
  expect(seen.posts).toEqual([]);expect(seen.requests.filter(path=>path==='/api/research/alpha-factory/runs/batch').length).toBeLessThanOrEqual(2);
});
