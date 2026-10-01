import {test,expect,type Page} from '@playwright/test';

const safety=Object.fromEntries(['promotion','paper','live','private','order','real_order','transfer','withdraw','execution_permission','runtime_observed'].map(key=>[key,false]));
const profiles=[{profile_id:'okx_btc_trend_1h',label:'BTC · OKX 永续 / 1h',metric_mode:'time_series',calendar:'UTC_24x7',bar_size:'1h',training_enabled:true,data_version:'synthetic-ui-fixture',blockers:[],...safety},
  {profile_id:'us_equity_daily',label:'美股 · 共享日线横截面',metric_mode:'cross_sectional',calendar:'XNYS',bar_size:'1d',training_enabled:false,blockers:['verified_daily_bundle_missing'],...safety},
  {profile_id:'cn_equity_daily',label:'A 股 · 共享日线横截面',metric_mode:'cross_sectional',calendar:'XSHG',bar_size:'1d',training_enabled:false,blockers:['committed_cn_dataset_missing'],...safety}];
const detail=(runId:string,overrides:Record<string,unknown>={})=>({run_id:runId,profile_id:profiles[0].profile_id,status:'completed',integrity_status:'passed',source_head:'synthetic-ui-fixture',source_stale:false,events:[],stages:{data:'completed',generate:'completed',evaluate:'completed',train:'completed',screen:'completed',nominate:'completed'},decision:'rejected',blockers:['audit:rank_ic_below_0.02'],result:{decision:'rejected',factor_search:{trials:[],trial_count:42,unique_expression_count:40},model_trials:[],qlib_fit_count:9,split_plan:{purge_bars:15,segments:{}},profile:profiles[0],candidates:[],lineage:{as_of:'2020-01-01T00:00:00Z'}},...safety,...overrides});
async function fixture(page:Page, options:{response?:Record<string,unknown>; unsafeOverview?:boolean}={}) {
  const posts:string[]=[];const privateRequests:string[]=[];
  page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);if(/private|\/orders?(\/|$)/.test(new URL(r.url()).pathname))privateRequests.push(r.url());});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    // Test-only capability fixture. The real formal deployment remains
    // research_readonly; these tests exercise the existing bounded research
    // actions without changing runtime permissions.
    if(path==='/api/health')return route.fulfill({json:{evidence_profile:'promotion_strict',read_only:false,controls_disabled:false}});
    if(path==='/api/research/alpha-factory')return route.fulfill({json:{profiles,runs:[],...safety,...(options.unsafeOverview?{live:true}:{})}});
    if(path.startsWith('/api/research/alpha-factory/runs/'))return route.fulfill({json:options.response||detail(path.split('/').at(-1)!)});
    if(path==='/api/tasks/research/alpha-factory'){
      const request=route.request().postDataJSON();expect(request.profile_id).toBe('okx_btc_trend_1h');expect(request.population).toBe(12);expect(request).not.toHaveProperty('private');
      return route.fulfill({json:{run_id:request.run_id,status:'queued',task_id:'synthetic-task',...safety}});
    }
    if(path.endsWith('/resume'))return route.fulfill({json:{run_id:'fixture-resumed',status:'queued',...safety}});
    return route.fulfill({status:503,json:{detail:'synthetic_ui_test_unrelated_read_unavailable'}});
  });
  return {posts,privateRequests};
}

test('factory navigation only reads, and unavailable markets cannot train',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=alpha-factory');
  const console=page.getByTestId('alpha-factory-console');await expect(console).toBeVisible();
  await console.locator('.af-new-batch > summary').click();
  await expect(console.getByRole('button',{name:'启动统一研究批次'})).toBeEnabled();
  await console.getByRole('button',{name:/美股 · 共享日线横截面/}).click();
  await expect(console.getByText('verified_daily_bundle_missing')).toBeVisible();
  await expect(console.getByRole('button',{name:'启动统一研究批次'})).toBeDisabled();
  await console.getByRole('button',{name:/A 股 · 共享日线横截面/}).click();
  await expect(console.getByText('committed_cn_dataset_missing')).toBeVisible();
  expect(seen.posts).toEqual([]);expect(seen.privateRequests).toEqual([]);
});

test('explicit bounded submit follows exact run and separates completion from rejection',async({page})=>{
  const seen=await fixture(page);await page.goto('/research?view=alpha-factory');
  const console=page.getByTestId('alpha-factory-console');await console.locator('.af-new-batch > summary').click();await console.getByRole('button',{name:'启动统一研究批次'}).click();
  await expect(page).toHaveURL(/factoryRun=af-/);await expect(console.getByRole('heading',{name:'输入与时间隔离'})).toBeVisible();
  await expect(console.getByText('42 / 40')).toBeVisible();await expect(console.getByText('audit:rank_ic_below_0.02')).toBeVisible();
  expect(seen.posts).toEqual(['/api/tasks/research/alpha-factory']);expect(seen.privateRequests).toEqual([]);
});

test('corrupt seal exposes blockers not fabricated result',async({page})=>{
  const seen=await fixture(page,{response:detail('corrupt',{integrity_status:'blocked',status:'blocked',blockers:['referenced_qlib_seal_invalid']})});
  await page.goto('/research?view=alpha-factory&factoryRun=corrupt');const console=page.getByTestId('alpha-factory-console');
  await expect(console.getByText('referenced_qlib_seal_invalid')).toBeVisible();
  await expect(console.getByRole('heading',{name:'输入与时间隔离'})).toHaveCount(0);expect(seen.posts).toEqual([]);
});

test('unsafe capability response locks submission',async({page})=>{
  const seen=await fixture(page,{unsafeOverview:true});await page.goto('/research?view=alpha-factory');
  const console=page.getByTestId('alpha-factory-console');await expect(console.getByRole('alert')).toContainText('安全旗标异常');
  await console.locator('.af-new-batch > summary').click();
  await expect(console.getByRole('button',{name:'启动统一研究批次'})).toBeDisabled();expect(seen.posts).toEqual([]);
});

test('interrupted run requires explicit resume and never restarts on navigation',async({page})=>{
  const seen=await fixture(page,{response:detail('orphan',{status:'interrupted',integrity_status:'unsealed_running',result:null,recovery:{explicit_resume_required:true},blockers:['owner_process_not_running_explicit_resume_required']})});
  await page.goto('/research?view=alpha-factory&factoryRun=orphan');const button=page.getByRole('button',{name:'校验封印并显式恢复'});
  await expect(button).toBeEnabled();expect(seen.posts).toEqual([]);await button.click();
  await expect(page).toHaveURL(/factoryRun=fixture-resumed/);expect(seen.posts).toEqual(['/api/tasks/research/alpha-factory/orphan/resume']);
});

test('mobile console keeps controls inside viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});const seen=await fixture(page);
  await page.goto('/research?view=alpha-factory');const console=page.getByTestId('alpha-factory-console');await expect(console).toBeVisible();
  await console.locator('.af-new-batch > summary').click();
  const box=await console.getByRole('button',{name:'启动统一研究批次'}).boundingBox();
  expect(box).not.toBeNull();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(391);expect(seen.posts).toEqual([]);
});

test('switching run hides previous facts before the delayed replacement arrives',async({page})=>{
  await fixture(page);
  await page.route('**/api/research/alpha-factory',route=>route.fulfill({json:{profiles,runs:[detail('first'),detail('second')],...safety}}));
  let release:()=>void=()=>{};const delayed=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/research/alpha-factory/runs/second',async route=>{await delayed;return route.fulfill({json:detail('second',{result:null})});});
  await page.goto('/research?view=alpha-factory&factoryRun=first');const console=page.getByTestId('alpha-factory-console');
  await expect(console.getByText('42 / 40')).toBeVisible();
  await console.getByRole('button',{name:/^second /}).click();await expect(page).toHaveURL(/factoryRun=second/);
  await expect(console.getByRole('heading',{name:'second',exact:true})).toBeVisible();
  await expect(console.getByText('42 / 40')).toHaveCount(0);release();
});

test('StrictMode never overlaps Alpha overview reads and a cancelled old run cannot overwrite the current result',async({page})=>{
  let overviewCalls=0;let activeOverview=0;let maxConcurrentOverview=0;let oldCalls=0;let currentCalls=0;
  const overviewEvents:{call:number;phase:'start'|'fulfill';at:number}[]=[];
  let releaseOverview:()=>void=()=>{};let markOverviewStarted:()=>void=()=>{};
  const overviewStarted=new Promise<void>(resolve=>{markOverviewStarted=resolve;});
  const overviewRelease=new Promise<void>(resolve=>{releaseOverview=resolve;});
  let releaseOld:()=>void=()=>{};let markOldStarted:()=>void=()=>{};
  const oldStarted=new Promise<void>(resolve=>{markOldStarted=resolve;});
  const oldRelease=new Promise<void>(resolve=>{releaseOld=resolve;});
  let markCurrentStarted:()=>void=()=>{};
  const currentStarted=new Promise<void>(resolve=>{markCurrentStarted=resolve;});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/health')return route.fulfill({json:{evidence_profile:'research_readonly',read_only:true,controls_disabled:true}});
    if(path==='/api/research/alpha-factory'){
      overviewCalls+=1;activeOverview+=1;maxConcurrentOverview=Math.max(maxConcurrentOverview,activeOverview);
      const call=overviewCalls;overviewEvents.push({call,phase:'start',at:Date.now()});markOverviewStarted();await overviewRelease;
      overviewEvents.push({call,phase:'fulfill',at:Date.now()});
      activeOverview-=1;
      return route.fulfill({json:{profiles,runs:[detail('old-run'),detail('current-run')],...safety}});
    }
    if(path==='/api/research/alpha-factory/runs/old-run'){
      oldCalls+=1;markOldStarted();await oldRelease;
      try{return await route.fulfill({status:408,json:{detail:'obsolete read'}});}catch{return;}
    }
    if(path==='/api/research/alpha-factory/runs/current-run'){
      currentCalls+=1;markCurrentStarted();return route.fulfill({json:detail('current-run')});
    }
    return route.fulfill({status:503,json:{detail:'synthetic_ui_test_unrelated_read_unavailable'}});
  });
  await page.goto('/research?view=alpha-factory&factoryRun=old-run');
  const console=page.getByTestId('alpha-factory-console');await overviewStarted;
  await expect(console).toBeVisible();releaseOverview();await oldStarted;
  await console.getByRole('button',{name:/^current-run /}).click();
  releaseOld();await currentStarted;
  await expect(console.getByRole('heading',{name:'current-run',exact:true})).toBeVisible();
  await expect(console.getByRole('alert')).toHaveCount(0);
  expect({oldCalls,currentCalls,maxConcurrentOverview}).toEqual({oldCalls:1,currentCalls:1,maxConcurrentOverview:1});
  expect(overviewCalls).toBeLessThanOrEqual(2);
  if(overviewCalls===2)expect(overviewEvents[2].at).toBeGreaterThanOrEqual(overviewEvents[1].at);
});

test('leaving Alpha while the shared overview is pending never starts selected detail',async({page})=>{
  let releaseOverview:()=>void=()=>{};let markOverviewStarted:()=>void=()=>{};let detailCalls=0;
  const overviewStarted=new Promise<void>(resolve=>{markOverviewStarted=resolve;});
  const overviewRelease=new Promise<void>(resolve=>{releaseOverview=resolve;});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/health')return route.fulfill({json:{evidence_profile:'research_readonly',read_only:true,controls_disabled:true}});
    if(path==='/api/research/alpha-factory'){
      markOverviewStarted();await overviewRelease;
      try{return await route.fulfill({json:{profiles,runs:[detail('pending-run')],...safety}});}catch{return;}
    }
    if(path==='/api/research/alpha-factory/runs/pending-run'){
      detailCalls+=1;return route.fulfill({json:detail('pending-run')});
    }
    return route.fulfill({status:503,json:{detail:'synthetic_ui_test_unrelated_read_unavailable'}});
  });
  await page.goto('/research?view=alpha-factory&factoryRun=pending-run');await overviewStarted;
  await page.getByRole('link',{name:'架构地图'}).click();
  await expect(page).toHaveURL(/\/architecture/);releaseOverview();await page.waitForTimeout(50);
  expect(detailCalls).toBe(0);
});
