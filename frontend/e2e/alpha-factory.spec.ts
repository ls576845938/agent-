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
