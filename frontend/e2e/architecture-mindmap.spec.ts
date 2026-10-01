import {expect, test} from '@playwright/test';

test.beforeEach(async ({page}) => {
  await page.route('**/api/**', async route => {
    const request = route.request();
    expect(request.method()).toBe('GET');
    const path = new URL(request.url()).pathname;
    expect(['/api/health', '/api/strategies']).toContain(path);
    await route.fulfill({json: path === '/api/health'
      ? {status: 'ok', service: 'mindmap-readonly-test', data_source_default: 'not-runtime', fastapi_available: true}
      : []});
  });
});

test('architecture opens on a real six-branch mind map with explicit evidence boundaries', async ({page}) => {
  await page.goto('/architecture');
  await expect(page.getByRole('button', {name: '总览思维导图'})).toHaveAttribute('aria-pressed', 'true');
  const mindMap = page.getByLabel('系统总览思维导图');
  await expect(mindMap).toContainText('QuantStation 全系统架构');
  await expect(mindMap.locator('.mindmap-branch')).toHaveCount(6);
  await expect(mindMap.locator('.mindmap-line--trunk')).toHaveCount(6);
  await expect(mindMap).toContainText('七层决策职责');
  await expect(mindMap).toContainText('职责序列，不等于同一 runtime 已全部贯通');
  await expect(mindMap).toContainText('市场状态 v2 已实现');
  await expect(page.getByText(/M2 历史探索没有稳定增量/)).toBeVisible();
  await expect(mindMap.locator('.mindmap-node.is-planned')).toHaveCount(0);
  await expect(mindMap).toContainText('研究结果不会自动获得交易权限');
});

test('keyboard-selecting a leaf opens the existing module evidence and can return to overview', async ({page}) => {
  await page.goto('/architecture');
  const node = page.getByTestId('atlas-node-context');
  await node.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', {name: '模块证据'})).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('模块详情')).toContainText('共享策略上下文');
  await expect(page.getByLabel('模块详情').getByRole('heading', {name: '共享策略上下文'})).toBeInViewport();
  await expect(page.getByRole('button', {name: '查看本模块清单'})).toBeVisible();
  await page.getByRole('button', {name: '总览思维导图'}).click();
  await expect(page.getByLabel('系统总览思维导图')).toBeVisible();
});

test('strategy delivery records completed V0-V3 and current candidate boundary', async ({page}) => {
  await page.goto('/architecture');
  const delivery = page.getByLabel('策略接入交付进度');
  await expect(delivery).toContainText('V0—V3 离线工程已限定结项');
  await expect(delivery).toContainText('不是 M3—M4');
  await expect(delivery.locator('.atlas-delivery-stages > li')).toHaveCount(4);
  await delivery.getByText('核查版本与范围', {exact: true}).click();
  await expect(delivery).toContainText('3fc39879d14ecab2288368afe588385cc44c08e1');
  await delivery.getByText('剩余缺口与停止条件', {exact: true}).click();
  await expect(delivery).toContainText('factory_lgbm_ast_v1');
  await expect(delivery).toContainText('默认关闭');
  await expect(delivery).toContainText('不作为真实交易准入');
  const evidenceLinks = delivery.getByRole('link');
  await expect(evidenceLinks).toHaveCount(3);
  await expect(delivery.getByRole('link', {name: '查看固定 Qlib 的历史研究与离线摘要'}))
    .toHaveAttribute('href', '/research?view=run-details&qlibRun=m1-okx-qlib');
  await expect(delivery.getByRole('link', {name: '查看 Donchian 五阶段离线决策与账本证据'}))
    .toHaveAttribute('href', '/research?view=run-details&offlineRun=donchian-v3-closeout-20260920');
  await expect(delivery.getByRole('link', {name: '查看 Donchian 已核账的自然历史阶段快照'}))
    .toHaveAttribute('href', '/research?view=run-details&offlineRun=donchian-stage-20260921');
  await expect(delivery.locator('button, form')).toHaveCount(0);
});

test('zoom, fit and reset controls are keyboard operable', async ({page}) => {
  await page.goto('/architecture');
  const output = page.getByLabel('当前缩放比例');
  const reset = page.getByRole('button', {name: '恢复 100%'});
  await reset.focus();
  await page.keyboard.press('Enter');
  await expect(output).toHaveText('100%');
  const zoomIn = page.getByRole('button', {name: '放大总图'});
  await zoomIn.focus();
  await page.keyboard.press('Enter');
  await expect(output).toHaveText('110%');
  await page.getByRole('button', {name: '适应画布'}).click();
  await expect.poll(async () => Number.parseInt(await output.textContent() ?? '', 10)).toBeLessThanOrEqual(100);
  await expect(page.getByTestId('architecture-mindmap-canvas')).toBeVisible();
});

for (const width of [390, 1131, 1440]) {
  test(`mind map keeps page width contained at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 975});
    await page.goto('/architecture');
    await expect(page.getByTestId('architecture-mindmap-viewport')).toBeVisible();
    const geometry = await page.evaluate(() => ({
      pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      localScroll: document.querySelector<HTMLElement>('[data-testid="architecture-mindmap-viewport"]')!.scrollWidth
        >= document.querySelector<HTMLElement>('[data-testid="architecture-mindmap-viewport"]')!.clientWidth,
    }));
    expect(geometry.pageOverflow).toBe(false);
    expect(geometry.localScroll).toBe(true);
  });
}
