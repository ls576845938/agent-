import {test,expect,type Page} from '@playwright/test';

// UI-only synthetic rows; all interactions are read-only. The browser always uses canonical main:3000.
const safety=Object.fromEntries(['promotion','paper','live','private','order','real_order','transfer','withdraw','execution_permission','runtime_observed'].map(key=>[key,false]));
async function fixture(page:Page) {
  const writes:string[]=[];
  page.on('request',request=>{if(request.method()!=='GET')writes.push(new URL(request.url()).pathname);});
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/research/experiments')return route.fulfill({json:Array.from({length:24},(_,i)=>({experiment_id:'fixture-'+i,strategy_id:'trend',strategy_family:'synthetic',symbols:['SPY'],status:'completed',created_at:'2026-01-01',start_date:'2025-01-01',end_date:'2025-12-31'}))});
    if(path==='/api/research/alpha-factory')return route.fulfill({json:{profiles:[],runs:[],...safety}});
    if(path==='/api/research/alpha-factory/runs/batch')return route.fulfill({json:{run_id:'batch',status:'completed',integrity_status:'passed',events:[],...safety,result:{decision:'rejected',profile:{},lineage:{},split_plan:{segments:{}},candidates:[],factor_search:{trial_count:24,trials:Array.from({length:24},(_,i)=>({trial_number:i,factor_id:'f'+i,name:'fixture factor '+i,origin:'registered',metrics:{ic:.01}}))},model_trials:[]}}});
    if(path==='/api/integrations/qlib/runs')return route.fulfill({json:{runs:[{run_id:'q1'}],profiles:[],dependencies:{}}});
    if(path==='/api/integrations/qlib/runs/q1')return route.fulfill({json:{summary:{run_id:'q1',paths:{run_root:'artifacts/qlib_runs/q1'}},integrity_status:'passed',...safety,
      research_trace:{identity:{qlib_run_id:'q1',source_head:'synthetic'},status:'research_flow_blocked',blockers:['fixture_only'],decision_count:1,simulated_fill_count:0},
      decision_trace_preview:[{decision_id:'d1',decision_time:'2026-01-01',layers:Object.fromEntries(['alpha','regime','risk','allocation','position','exit','execution'].map(key=>[key,{status:'not_run',truth_kind:'research_simulated'}]))}]}});
    if(/experiments|candidates|features|factors|strategy-manifests|pending|\/tasks$|\/strategies$/.test(path))return route.fulfill({json:[]});
    return route.fulfill({json:{}});
  });
  return writes;
}

test.beforeEach(async({request},testInfo)=>{
  const response=await request.get('/__frontend_identity');expect(response.status()).toBe(200);
  const identity=await response.json();expect(identity.canonical).toBe(true);expect(identity.runtime_stale).toBe(false);
  if(process.env.QS_NAVIGATION_BASELINE_HEAD)expect(identity.current_main_head || identity.source_head).toBe(process.env.QS_NAVIGATION_BASELINE_HEAD);
  await testInfo.attach('canonical-identity',{body:JSON.stringify(identity),contentType:'application/json'});
});

for(const view of ['records','alpha-factory&factoryRun=batch','run-details&qlibRun=q1']) test('only primary navigation sticks through long canvas: '+view,async({page},testInfo)=>{
  await page.setViewportSize({width:1131,height:975});const writes=await fixture(page);await page.goto('/research?view='+view);
  const nav=page.getByRole('navigation',{name:'研究工作区导航'});await expect(nav).toBeVisible();
  if(view==='records')await expect(page.getByRole('cell',{name:'fixture-23',exact:true})).toHaveCount(1);
  else if(view.startsWith('alpha-factory'))await expect(page.locator('.af-table tbody tr')).toHaveCount(24);
  else await expect(page.locator('.qlib-layer-grid article')).toHaveCount(7);
  const canvas=page.locator('.workspace-research .system-tv-canvas-scroll');
  await canvas.evaluate(element=>{element.scrollTop=element.scrollHeight;});
  const top=await canvas.evaluate(element=>element.getBoundingClientRect().top);
  await page.screenshot({path:testInfo.outputPath('desktop-scrolled.png')});
  const box=await nav.boundingBox();expect(box).not.toBeNull();expect(box!.y).toBeGreaterThanOrEqual(top-1);expect(box!.y).toBeLessThanOrEqual(top+2);
  await expect(nav.getByRole('tab')).toHaveCount(5);
  await expect(nav.locator('#research-subviews')).toHaveCount(0);
  if(view==='records') {const secondary=await page.locator('#research-subviews').boundingBox();expect(secondary!.y+secondary!.height).toBeLessThan(top);}
  const navStyle=await nav.evaluate(element=>({position:getComputedStyle(element).position,background:getComputedStyle(element).backgroundColor,z:getComputedStyle(element).zIndex}));
  expect(navStyle.position).toBe('sticky');expect(navStyle.background).not.toBe('rgba(0, 0, 0, 0)');expect(Number(navStyle.z)).toBeGreaterThan(1);
  const hit=await nav.getByRole('tab',{name:'研究总览',exact:true}).evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));});expect(hit).toBe(true);
  await nav.getByRole('tab',{name:'研究总览',exact:true}).click();await expect(page).toHaveURL(/view=research-overview/);expect(writes).toEqual([]);
});

test('primary and secondary switches preserve context and do not focus-scroll the canvas',async({page})=>{
  const writes=await fixture(page);await page.goto('/research?view=records&dataVersion=dv&featureVersion=fv');
  const nav=page.getByRole('tablist',{name:'研究工作区'});const canvas=page.locator('.workspace-research .system-tv-canvas-scroll');
  await expect(nav).toBeVisible();await canvas.evaluate(element=>{element.scrollTop=350;});
  const before=await canvas.evaluate(element=>element.scrollTop);
  // Changing to another long ordinary page must not scroll to its nav merely to focus it.
  await nav.getByRole('tab',{name:'手动实验',exact:true}).click();await expect(page).toHaveURL(/view=cycle/);
  expect(await canvas.evaluate(element=>element.scrollTop)).toBeGreaterThanOrEqual(Math.min(before,await canvas.evaluate(element=>element.scrollHeight-element.clientHeight))-2);
  const query=new URL(page.url()).searchParams;expect(query.get('dataVersion')).toBe('dv');expect(query.get('featureVersion')).toBe('fv');
  await canvas.evaluate(element=>{element.scrollTop=0;});
  await page.getByRole('tab',{name:'实验记录与报告',exact:true}).click();await expect(page).toHaveURL(/view=records/);
  await page.goBack();await expect(page).toHaveURL(/view=cycle/);await page.goForward();await expect(page).toHaveURL(/view=records/);
  for(const label of ['数据与因子','候选与证据','Alpha 工厂','研究总览']){
    await page.getByRole('tablist',{name:'研究工作区'}).getByRole('tab',{name:label,exact:true}).click();
    await expect(page.getByRole('tablist',{name:'研究工作区'}).getByRole('tab',{name:label,exact:true})).toHaveAttribute('aria-selected','true');
    expect(new URL(page.url()).searchParams.get('dataVersion')).toBe('dv');
  }
  expect(writes).toEqual([]);
});

test('390px keyboard navigation reveals the active tab horizontally without vertical focus jump',async({page},testInfo)=>{
  await page.setViewportSize({width:390,height:844});const writes=await fixture(page);await page.goto('/research?view=records');
  const nav=page.getByRole('navigation',{name:'研究工作区导航'});const tabs=nav.getByRole('tablist',{name:'研究工作区'});const canvas=page.locator('.workspace-research .system-tv-canvas-scroll');
  await expect(tabs).toBeVisible();await expect(page.getByRole('cell',{name:'fixture-23',exact:true})).toHaveCount(1);
  const toolbar=page.locator('.workspace-research .system-tv-canvas-toolbar');const toolbarBox=await toolbar.boundingBox();
  const contextBox=await page.locator('.workspace-research .system-tv-canvas-context').boundingBox();
  expect(toolbarBox!.y+toolbarBox!.height).toBeLessThanOrEqual(contextBox!.y+1);
  for(const button of await toolbar.locator('.system-tv-layout-switcher button').all()) {
    const box=await button.boundingBox();expect(box!.y).toBeGreaterThanOrEqual(toolbarBox!.y);expect(box!.y+box!.height).toBeLessThanOrEqual(toolbarBox!.y+toolbarBox!.height+1);
    expect(await button.evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));})).toBe(true);
  }
  expect(await canvas.evaluate(element=>element.scrollHeight-element.clientHeight)).toBeGreaterThan(0);
  await canvas.evaluate(element=>{element.scrollTop=400;});
  await nav.getByRole('tab',{name:'手动实验',exact:true}).evaluate(element=>(element as HTMLElement).focus({preventScroll:true}));
  const before=await canvas.evaluate(element=>element.scrollTop);expect(before).toBeGreaterThan(0);
  const top=await canvas.evaluate(element=>element.getBoundingClientRect().top);const navBounds=await nav.boundingBox();expect(navBounds!.y).toBeGreaterThanOrEqual(top-1);expect(navBounds!.y).toBeLessThanOrEqual(top+2);
  const hit=await nav.getByRole('tab',{name:'研究总览',exact:true}).evaluate(element=>{const rect=element.getBoundingClientRect();return element.contains(document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2));});expect(hit).toBe(true);
  await page.screenshot({path:testInfo.outputPath('mobile-scrolled.png')});
  const documentBefore=await page.evaluate(()=>document.scrollingElement!.scrollTop);
  await page.keyboard.press('End');
  const selected=page.getByRole('tab',{name:'候选与证据',exact:true});await expect(selected).toBeFocused();
  const after=await canvas.evaluate(element=>({scroll:element.scrollTop,max:element.scrollHeight-element.clientHeight}));
  expect(after.scroll).toBeGreaterThanOrEqual(Math.min(before,after.max)-2);
  expect(after.scroll).toBeLessThanOrEqual(before+2);
  const documentAfter=await page.evaluate(()=>{const element=document.scrollingElement!;return {scroll:element.scrollTop,max:element.scrollHeight-element.clientHeight};});
  expect(documentAfter.scroll).toBeGreaterThanOrEqual(Math.min(documentBefore,documentAfter.max)-2);
  expect(documentAfter.scroll).toBeLessThanOrEqual(documentBefore+2);
  const bounds=await selected.boundingBox();const row=await tabs.boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(row!.x-1);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(row!.x+row!.width+1);
  await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'研究总览',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowRight');await expect(page.getByRole('tab',{name:'Alpha 工厂',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowLeft');await expect(page.getByRole('tab',{name:'研究总览',exact:true})).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(writes).toEqual([]);
});

test('delayed focused-to-ordinary remount restores only the keyboard target, including secondary tabs',async({page})=>{
  const writes=await fixture(page);await page.goto('/research?view=alpha-factory');
  let release=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/research/experiments**',async route=>{await gate;return route.fulfill({json:[]});});
  await page.getByRole('tab',{name:'Alpha 工厂',exact:true}).focus();await page.keyboard.press('ArrowLeft');
  await expect(page.getByText('加载研究数据...', {exact:true})).toBeVisible();release();
  await expect(page.getByRole('tab',{name:'研究总览',exact:true})).toBeFocused();
  await page.getByRole('tab',{name:'数据与因子',exact:true}).click();
  await page.getByRole('tab',{name:'数据准备',exact:true}).focus();await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab',{name:'因子评估与快照',exact:true})).toBeFocused();
  expect(writes).toEqual([]);
});

for(const cancellation of ['other-focus','expired','history-mismatch'] as const) test('delayed keyboard focus intent cancels on '+cancellation,async({page})=>{
  const writes=await fixture(page);if(cancellation==='expired')await page.clock.install();
  await page.goto('/research?view=records');await expect(page.getByRole('cell',{name:'fixture-23',exact:true})).toHaveCount(1);
  await page.getByRole('tab',{name:'Alpha 工厂',exact:true}).click();await expect(page.getByTestId('alpha-factory-console')).toBeVisible();
  let release=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/research/experiments**',async route=>{await gate;return route.fulfill({json:[]});});
  await page.getByRole('tab',{name:'Alpha 工厂',exact:true}).focus();await page.keyboard.press('ArrowLeft');
  await expect(page.getByText('加载研究数据...', {exact:true})).toBeVisible();
  const elsewhere=page.locator('a[href="/portfolio"]').first();
  if(cancellation==='other-focus')await elsewhere.focus();
  else if(cancellation==='expired')await page.clock.fastForward(8001);
  else await page.goBack();
  release();
  if(cancellation==='history-mismatch') {await expect(page).toHaveURL(/view=alpha-factory/);await expect(page.getByRole('tab',{name:'Alpha 工厂',exact:true})).toHaveAttribute('aria-selected','true');}
  else {await expect(page.getByRole('tab',{name:'研究总览',exact:true})).toHaveAttribute('aria-selected','true');
    if(cancellation==='other-focus')await expect(elsewhere).toBeFocused();else await expect(page.getByRole('tab',{name:'研究总览',exact:true})).not.toBeFocused();}
  expect(writes).toEqual([]);
});
