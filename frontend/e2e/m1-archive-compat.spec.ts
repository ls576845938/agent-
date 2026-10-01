import {expect, test} from '@playwright/test';

const flags = {
  promotion:false,paper:false,live:false,private:false,order:false,real_order:false,
  transfer:false,withdraw:false,execution_permission:false,runtime_observed:false,
};
const provenance = {
  storage:'immutable_shared_data',
  dataset_id:'m1-trend-environment-acceptance',
  dataset_version:'m1-okx-59f5eb861-20260911',
  manifest_git_spec:'165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json',
  logical_run:'qlib_runs/m1-okx-qlib',
  consumer_read_only:true,
  historical_reconstructed_availability:true,
};

test('StrictMode loads the immutable M1 detail and both pickers once, in order', async ({page}) => {
  const calls:string[] = [];
  const writes:string[] = [];
  let active = 0;
  let maxActive = 0;
  page.on('request', request => {if (request.method() !== 'GET') writes.push(`${request.method()} ${request.url()}`);});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const tracked = path === '/api/integrations/qlib/runs/m1-okx-qlib'
      || path === '/api/integrations/qlib/runs'
      || path === '/api/research/alpha-factory';
    if (tracked) {
      calls.push(path); active += 1; maxActive = Math.max(maxActive, active);
      await new Promise(resolve => setTimeout(resolve, 60));
      active -= 1;
    }
    if (path === '/api/integrations/qlib/runs/m1-okx-qlib') {
      await route.fulfill({json:{
        ...flags, integrity_status:'passed', seal:{source_head:'historical-m1'},
        summary:{run_id:'m1-okx-qlib',paths:{run_root:'shared-data://m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911/qlib_runs/m1-okx-qlib'},evidence_provenance:provenance},
        dataset_manifest:{data_version:'m1-okx-59f5eb861-20260911'},
      }});
    } else if (path === '/api/integrations/qlib/runs') {
      await route.fulfill({json:{runs:[{run_id:'m1-okx-qlib'}]}});
    } else if (path === '/api/research/alpha-factory') {
      await route.fulfill({json:{...flags,profiles:[],runs:[{run_id:'m1-okx-factory'}]}});
    } else {
      await route.fulfill({json:{status:'ok'}});
    }
  });

  await page.goto('/research?view=run-details&qlibRun=m1-okx-qlib');
  await expect(page.getByTestId('qlib-run-summary')).toContainText('研究产物已封印');
  await expect(page.getByRole('combobox',{name:'选择精确研究运行'})).toContainText('Alpha 工厂 · m1-okx-factory');
  await expect(page.getByRole('alert').filter({hasText:'来源目录不匹配'})).toHaveCount(0);
  await expect(page.getByText('部分运行目录读取失败')).toHaveCount(0);
  expect(calls).toEqual([
    '/api/integrations/qlib/runs/m1-okx-qlib',
    '/api/integrations/qlib/runs',
    '/api/research/alpha-factory',
  ]);
  expect(maxActive).toBe(1);
  expect(writes).toEqual([]);
});

test('wrong immutable provenance remains hidden', async ({page}) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/integrations/qlib/runs/m1-okx-qlib') {
      await route.fulfill({json:{
        ...flags, integrity_status:'passed',
        summary:{run_id:'m1-okx-qlib',paths:{run_root:'shared-data://other/archive/qlib_runs/m1-okx-qlib'},evidence_provenance:{...provenance,dataset_version:'other'}},
      }});
    } else if (path === '/api/integrations/qlib/runs') await route.fulfill({json:{runs:[]}});
    else if (path === '/api/research/alpha-factory') await route.fulfill({json:{...flags,profiles:[],runs:[]}});
    else await route.fulfill({json:{status:'ok'}});
  });
  await page.goto('/research?view=run-details&qlibRun=m1-okx-qlib');
  await expect(page.getByRole('alert').filter({hasText:'来源目录不匹配'})).toBeVisible();
  await expect(page.getByTestId('qlib-run-summary')).toContainText('运行事实尚未匹配');
});

test('a successful Qlib directory is visible while the later factory directory is still pending', async ({page}) => {
  let releaseFactory: (() => void) | undefined;
  let markFactoryStarted!: () => void;
  const factoryStarted = new Promise<void>(resolve => {markFactoryStarted = resolve;});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/integrations/qlib/runs') {
      await route.fulfill({json:{runs:[{run_id:'local-q1'}]}});
    } else if (path === '/api/research/alpha-factory') {
      await new Promise<void>(resolve => {releaseFactory = resolve;markFactoryStarted();});
      await route.fulfill({status:408,json:{detail:'bounded timeout'}});
    } else await route.fulfill({json:{status:'ok'}});
  });
  await page.goto('/research?view=run-details');
  await expect(page.getByRole('combobox',{name:'选择精确研究运行'})).toContainText('Qlib · local-q1');
  await expect(page.getByText('部分运行目录读取失败')).toHaveCount(0);
  await factoryStarted;
  expect(releaseFactory).toBeDefined();
  releaseFactory!();
  await expect(page.getByText('部分运行目录读取失败')).toBeVisible();
});

test('read-only factory details do not duplicate parent and child archive reads', async ({page}) => {
  const calls:string[] = [];
  const writes:string[] = [];
  let active = 0;
  let maxActive = 0;
  page.on('request', request => {if (request.method() !== 'GET') writes.push(`${request.method()} ${request.url()}`);});
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const tracked = path === '/api/research/alpha-factory/runs/m1-okx-factory'
      || path === '/api/integrations/qlib/runs'
      || path === '/api/research/alpha-factory';
    if (tracked) {
      calls.push(path); active += 1; maxActive = Math.max(maxActive, active);
      await new Promise(resolve => setTimeout(resolve, 60)); active -= 1;
    }
    if (path === '/api/research/alpha-factory/runs/m1-okx-factory') {
      await route.fulfill({json:{...flags,run_id:'m1-okx-factory',status:'completed',integrity_status:'passed',decision:'rejected',stages:{},blockers:['fixture_rejected']}});
    } else if (path === '/api/integrations/qlib/runs') {
      await route.fulfill({json:{runs:[{run_id:'m1-okx-qlib'}]}});
    } else if (path === '/api/research/alpha-factory') {
      await route.fulfill({json:{...flags,profiles:[],runs:[{run_id:'m1-okx-factory'}]}});
    } else await route.fulfill({json:{status:'ok'}});
  });
  await page.goto('/research?view=run-details&factoryRun=m1-okx-factory');
  await expect(page.getByTestId('factory-run-conclusion')).toContainText('m1-okx-factory');
  await expect(page.getByTestId('factory-run-conclusion')).toContainText('计算完成');
  await expect(page.getByRole('combobox',{name:'选择精确研究运行'})).toContainText('Qlib · m1-okx-qlib');
  await expect(page.getByRole('combobox',{name:'选择精确研究运行'})).toContainText('Alpha 工厂 · m1-okx-factory');
  expect(calls).toEqual([
    '/api/research/alpha-factory/runs/m1-okx-factory',
    '/api/integrations/qlib/runs',
    '/api/research/alpha-factory',
  ]);
  expect(maxActive).toBe(1);
  expect(writes).toEqual([]);
});
