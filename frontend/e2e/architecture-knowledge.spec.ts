import {expect, test} from '@playwright/test';
import knowledge from '../src/workspaces/architecture/knowledge.json' with {type: 'json'};

test.beforeEach(async ({page}) => {
  await page.route('**/api/**', async route => {
    const request = route.request();
    expect(request.method()).toBe('GET');
    const path = new URL(request.url()).pathname;
    expect(['/api/health', '/api/strategies']).toContain(path);
    await route.fulfill({json: path === '/api/health'
      ? {status: 'ok', service: 'architecture-knowledge-readonly-test', data_source_default: 'not-runtime', fastapi_available: true}
      : []});
  });
});

test('layered guide exposes module boundaries and versioned core cards', async ({page}, testInfo) => {
  await page.goto('/architecture');
  await testInfo.attach('architecture-overview', {body: await page.screenshot({fullPage: true}), contentType: 'image/png'});
  await page.getByRole('button', {name: '分层架构说明'}).click();
  const guide = page.getByLabel('分层架构说明');
  await expect(guide).toContainText('职责说明 ≠ 已跑通调用链');
  await expect(guide).toContainText('市场状态 v2 与历史诊断已实现');
  await expect(guide).toContainText('conditioned 在 1956 / 2960');
  await expect(guide).toContainText('M3—M4 未启动');
  await expect(guide).toContainText('候选离线 worker 默认关闭');
  await expect(guide).toContainText('真实账户只读验收未完成');
  await expect(guide).toContainText('研究读取链 11 / 11');
  await expect(page.getByLabel('分层模块索引').getByRole('button')).toHaveCount(25);
  await expect(page.getByLabel('模块输入输出边界')).toContainText('输入');
  await expect(page.getByLabel('模块输入输出边界')).toContainText('输出');
  await expect(page.getByLabel('模块输入输出边界')).toContainText('职责边界 / 修改禁区');
  const moduleLayout = await page.evaluate(() => {
    const contrast = (foreground: string, background: string) => {
      const rgb = (value: string) => value.match(/\d+(?:\.\d+)?/g)!.slice(0, 3).map(Number);
      const luminance = (value: string) => rgb(value).map(channel => channel / 255)
        .map(channel => channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4)
        .reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
      const [high, low] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
      return (high + 0.05) / (low + 0.05);
    };
    const panel = document.querySelector<HTMLElement>('.knowledge-module-detail')!;
    const title = panel.querySelector<HTMLElement>('h2')!;
    const buttons = Array.from(document.querySelectorAll<HTMLElement>('.knowledge-module-index button'));
    const panelStyle = getComputedStyle(panel);
    const titleStyle = getComputedStyle(title);
    const first = buttons[0].getBoundingClientRect();
    const second = buttons[1].getBoundingClientRect();
    return {
      panelBackground: panelStyle.backgroundColor,
      contrast: contrast(titleStyle.color, panelStyle.backgroundColor),
      firstHeight: first.height,
      rowsOverlap: first.bottom > second.top,
    };
  });
  expect(moduleLayout.panelBackground).not.toBe('rgb(255, 255, 255)');
  expect(moduleLayout.contrast).toBeGreaterThanOrEqual(4.5);
  expect(moduleLayout.firstHeight).toBeGreaterThanOrEqual(54);
  expect(moduleLayout.rowsOverlap).toBe(false);
  await testInfo.attach('architecture-layered-guide', {body: await page.screenshot({fullPage: true}), contentType: 'image/png'});

  await page.getByRole('button', {name: `查看全部 ${knowledge.core_files.length} 张`}).click();
  await expect(page.getByTestId('architecture-core-file-card')).toHaveCount(28);
  await expect(page.getByLabel('核心文件职责卡')).toContainText(knowledge.core_files[0].source_blob.slice(0, 12));
  await expect(page.getByLabel('普通文件分组索引').locator('details')).toHaveCount(10);
  await testInfo.attach('architecture-core-file-cards', {body: await page.screenshot({fullPage: true}), contentType: 'image/png'});
});

test('module switching keeps the responsibility source separate from the old catalog', async ({page}) => {
  await page.goto('/architecture');
  await page.getByRole('button', {name: '分层架构说明'}).click();
  await page.getByLabel('分层模块索引').getByRole('button', {name: /BTC OMS／保护／账本/}).click();
  const detail = page.getByLabel('模块输入输出边界');
  await expect(detail).toContainText('OMSOrderSubmissionBundle');
  await expect(detail).toContainText('bundle 不是 permit');
  await expect(page.getByLabel('核心文件职责卡')).toContainText('quant_crypto/oms/shared_platform_v3.py');
  await page.getByRole('button', {name: '模块证据'}).click();
  await expect(page.getByLabel('模块详情')).toBeVisible();
});

for (const width of [390, 1131, 1440]) {
  test(`layered architecture remains page-contained at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 975});
    await page.goto('/architecture');
    await page.getByRole('button', {name: '分层架构说明'}).click();
    await expect(page.getByLabel('分层模块索引')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    expect(overflow).toBe(false);
  });
}
