import {test,expect,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

// The committed fixture is a deterministic software exercise, not a market PnL claim.
const sealed=JSON.parse(readFileSync(fileURLToPath(new URL('../../.agent/offline_evidence/donchian-v3-closeout-20260920.json',import.meta.url)),'utf8'));
const id='donchian-v3-closeout-20260920';
const evidence={...sealed.summary,summary_sha256:sealed.sha256,read_only:true,
  historical_source:true,manifest_ref:'committed:receipt'};
const stageSnapshot=JSON.parse(readFileSync(fileURLToPath(new URL('../../.agent/offline_evidence/donchian-stage-20260921.json',import.meta.url)),'utf8'));
const stageId='donchian-stage-20260921';
const stageEvidence={...stageSnapshot,read_only:true,historical_source:true,
  publication_head:'e2e7496acaa16b9fd5eda37dd65ea328a18ab032',
  snapshot_sha256:'ff5d5ad93538a4b74a2b3da1c7f76cad963e4a25195ff56373ad83c7806cce01',
  manifest_ref:'committed:stage'};

async function fixture(page:Page,offline:unknown=evidence) {
  const posts:string[]=[];
  page.on('request',request=>{if(request.method()!=='GET')posts.push(request.url());});
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/research/btc/strategy-registry')return route.fulfill({json:{
      schema_version:'btc_strategy_registry_api_v1',paper_queue_write_allowed:false,
      live_unlock_allowed:false,broker_or_order_allowed:false,specs:[],
      offline_evidence:offline,
    }});
    if(url.pathname==='/api/integrations/qlib/runs')return route.fulfill({json:{runs:[{run_id:'m1-okx-qlib'}]}});
    if(url.pathname.startsWith('/api/integrations/qlib/runs/'))return route.fulfill({json:{
      summary:{run_id:'m1-okx-qlib',paths:{run_root:'artifacts/qlib_runs/m1-okx-qlib'}},
      integrity_status:'blocked',promotion:false,paper:false,live:false,private:false,order:false,
      real_order:false,transfer:false,withdraw:false,execution_permission:false,runtime_observed:false,
    }});
    if(url.pathname==='/api/research/alpha-factory')return route.fulfill({json:{runs:[],profiles:[]}});
    return route.fulfill({json:{}});
  });
  return posts;
}

test('one offline run shows five precise decisions and no real execution',async({page})=>{
  const posts=await fixture(page);
  await page.goto(`/research?view=run-details&offlineRun=${id}`);
  const card=page.getByTestId('donchian-offline-evidence');
  await expect(card).toContainText('原策略五阶段纵向闭环');
  await expect(card).toContainText('模拟成交 4');
  await expect(card).toContainText('固定成交价 60000');
  await expect(card).toContainText('实际资金费现金流 0 USDT');
  await expect(card).toContainText('持有阶段：无新订单、无新成交、无新账本事件');
  for(const row of evidence.stages)await expect(card).toContainText(row.evidence.decision_id);
  await expect(page.getByRole('region',{name:'实际运行证据'})).toContainText('未绑定');
  expect(posts).toEqual([]);
});

test('mixed, duplicate, unknown or unsafe offline evidence fails closed',async({page})=>{
  const posts=await fixture(page);
  for(const query of [
    `offlineRun=${id}&qlibRun=m1-okx-qlib`,
    `offlineRun=${id}&offlineRun=${id}`,
    'offlineRun=latest',
    'offlineRun=../other',
  ]) {
    await page.goto('/research?view=run-details&'+query);
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByTestId('donchian-offline-evidence')).toHaveCount(0);
  }
  await page.unrouteAll({behavior:'ignoreErrors'});
  await fixture(page,{...evidence,permissions:{...evidence.permissions,order:true}});
  await page.goto(`/research?view=run-details&offlineRun=${id}`);
  await expect(page.getByRole('alert')).toContainText('安全合同不匹配');
  await expect(page.getByTestId('donchian-offline-evidence')).toHaveCount(0);
  expect(posts).toEqual([]);
});

test('late offline response cannot replace a selected Qlib run',async({page})=>{
  const posts=await fixture(page);
  let release=()=>{};
  const delayed=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/research/btc/strategy-registry?*',async route=>{
    await delayed;
    try {
      await route.fulfill({json:{schema_version:'btc_strategy_registry_api_v1',
        paper_queue_write_allowed:false,live_unlock_allowed:false,
        broker_or_order_allowed:false,specs:[],offline_evidence:evidence}});
    } catch {
      // Switching runs cancels the stale request; no fallback response is required.
    }
  });
  await page.goto(`/research?view=run-details&offlineRun=${id}`);
  await page.getByRole('combobox',{name:'选择精确研究运行'}).selectOption('qlib:m1-okx-qlib');
  await expect(page).toHaveURL(/qlibRun=m1-okx-qlib/);
  expect(new URL(page.url()).searchParams.get('offlineRun')).toBeNull();
  await expect(page.getByTestId('qlib-run-summary')).toBeVisible();
  release();
  await expect(page.getByTestId('donchian-offline-evidence')).toHaveCount(0);
  expect(posts).toEqual([]);
});

test('paused natural-history stage is separate from fixture and actual execution',async({page})=>{
  const posts=await fixture(page,stageEvidence);
  await page.goto(`/research?view=run-details&offlineRun=${stageId}`);
  const card=page.getByTestId('donchian-stage-evidence');
  await expect(card).toContainText('2960 / 8760');
  await expect(card).toContainText('历史模拟');
  await expect(card).toContainText('30 条主决策');
  await expect(card).toContainText('26 次保护退出');
  await expect(card).toContainText('半侧价差 0.5 bps');
  await expect(card).toContainText(stageEvidence.source_head);
  await expect(card).toContainText(stageEvidence.publication_head);
  await expect(page.getByTestId('donchian-offline-evidence')).toHaveCount(0);
  await expect(page.getByRole('region',{name:'实际运行证据'})).toContainText('未绑定');
  await card.getByText(/30 条主决策/).click();
  await expect(card).toContainText(stageEvidence.decision_links[0].ledger_event_hash);
  expect(posts).toEqual([]);
});

test('stage selector switch and wrong source fail closed without stale data',async({page})=>{
  const posts=await fixture(page,stageEvidence);
  await page.goto(`/research?view=run-details&offlineRun=${stageId}`);
  await expect(page.getByTestId('donchian-stage-evidence')).toContainText('2960 / 8760');
  await page.getByRole('combobox',{name:'选择精确研究运行'}).selectOption('offline:'+id);
  await expect(page).toHaveURL(/offlineRun=donchian-v3-closeout-20260920/);
  await expect(page.getByTestId('donchian-stage-evidence')).toHaveCount(0);
  await expect(page.getByTestId('donchian-offline-evidence')).toContainText('尚未绑定');
  await page.goto(`/research?view=run-details&offlineRun=${stageId}&qlibRun=m1-okx-qlib`);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('donchian-stage-evidence')).toHaveCount(0);
  expect(posts).toEqual([]);
});
