import {expect, test} from '@playwright/test';
import catalog from '../src/workspaces/architecture/catalog.json' with {type: 'json'};

test.beforeEach(async ({page}) => {
  await page.route('**/api/**', async route => {
    const request = route.request();
    expect(request.method()).toBe('GET');
    const path = new URL(request.url()).pathname;
    expect(['/api/health', '/api/strategies']).toContain(path);
    await route.fulfill({json: path === '/api/health'
      ? {status: 'ok', service: 'test-readonly', data_source_default: 'not-runtime', fastapi_available: true} : []});
  });
});

test('separate route records source coverage without declaring runtime readiness', async ({page}) => {
  await page.goto('/architecture');
  await expect(page.getByRole('heading', {name: '架构地图', exact: true})).toBeVisible();
  await expect(page.getByLabel('地图证据边界')).toContainText('不是运行监控');
  await expect(page.getByLabel('地图证据边界')).toContainText('核查基线 3fc39879');
  const current = page.getByTestId('current-development-status');
  await expect(current).toContainText('当前开发进度');
  await expect(current).toContainText('不是实时权限、账户或运行监控');
  await expect(current).toContainText('2960 / 8760');
  await expect(current).toContainText('conditioned 1956 / 2960');
  await expect(current).toContainText('11 / 11');
  await page.getByTestId('architecture-milestone-status').getByText(/版本化里程碑状态/).click();
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('实现：');
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('测试：');
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('运行：');
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('交易就绪：');
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('M3—M4 未启动');
  await expect(page.getByTestId('architecture-milestone-status')).toContainText('integrate-candidate-market-policy-closeout-20260927.md');
  await expect(page.getByLabel('源码阅读覆盖')).toContainText(catalog.files.length.toLocaleString('zh-CN'));
  await expect(page.getByLabel('源码阅读覆盖')).toContainText('未验证');
  await expect(page.locator('.atlas-label')).toContainText(catalog.files.every(file => file.status === 'fully_read')
    ? '历史源码基准已读完 · 当前进度另行核查' : '源码审阅进行中');
  await expect(page.getByLabel('主导航').getByRole('link', {name: /架构地图/})).toHaveClass(/active/);
  await expect(page.locator('.system-workbench')).toHaveAttribute('data-terminal-mode', 'architecture');
});

test('module selection and file search retain exact provenance and unread state', async ({page}) => {
  await page.goto('/architecture');
  await page.getByRole('button', {name: '模块证据'}).click();
  await page.getByTestId('atlas-node-context').click();
  await expect(page.getByLabel('模块详情')).toContainText('共享策略上下文');
  await page.getByRole('button', {name: '查看本模块清单'}).click();
  await page.getByLabel('文件路径').fill('quant_shared/strategy_runtime/models.py');
  const row = page.getByRole('row').filter({hasText: 'quant_shared/strategy_runtime/models.py'});
  await expect(row).toContainText('已读至 EOF');
  await expect(row).toContainText('主代理');
  const source = catalog.files.find(file => file.path === 'quant_shared/strategy_runtime/models.py')!;
  await expect(row).toContainText(source.blob.slice(0, 12));
  await page.getByLabel('文件路径').fill('');
  await page.getByRole('combobox', {name: /^模块/}).selectOption('all');
  await page.getByLabel('阅读状态').selectOption('unread');
  await expect(page.locator('tbody')).not.toContainText('已读至 EOF');
  if (catalog.files.every(file => file.status === 'fully_read')) {
    await expect(page.getByLabel('阅读清单').getByRole('status')).toContainText('共 0 个文件');
    await expect(page.getByRole('button', {name: '下一页', exact: true})).toBeDisabled();
  }
  await page.getByLabel('文件路径').fill('not-a-real-file-no-matches');
  await expect(page.getByText('没有匹配文件；可清空筛选。')).toBeVisible();
});

test('guide distinguishes committed-object drift from dirty files and permits no actions', async ({page}) => {
  await page.goto('/architecture');
  await page.getByRole('button', {name: '增量阅读指南'}).click();
  await expect(page.getByLabel('增量阅读指南')).toContainText('不检查工作树未提交修改');
  await expect(page.getByLabel('增量阅读指南')).toContainText('review_invalidated');
  await page.getByText('本页面安全边界（不是后端授权快照）').click();
  await expect(page.getByText('real_order=false', {exact: true})).toBeVisible();
  await expect(page.locator('.architecture-atlas form')).toHaveCount(0);
});

for (const width of [390, 1131, 1440]) {
  test('map and sticky navigation remain usable at ' + width, async ({page}) => {
    await page.setViewportSize({width, height: 975});
    await page.goto('/architecture');
    await page.getByRole('button', {name: '模块证据'}).click();
    await expect(page.getByTestId('atlas-node-btc_oms')).toBeVisible();
    await page.getByTestId('atlas-node-btc_oms').click();
    await page.getByRole('button', {name: '阅读清单', exact: true}).click();
    await expect(page.getByLabel('文件路径')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    expect(overflow).toBe(false);
    await page.getByRole('button', {name: '增量阅读指南'}).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', {name: '下次从哪里继续'})).toBeVisible();
  });
}
