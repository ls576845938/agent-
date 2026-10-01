import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

test('Crypto workspace exposes K-lines, reconciled trading history, positions, costs, and audit', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();
  await expect(page.locator('.tv-chart-navigation')).toHaveCount(0);
  await expect.poll(async () => Number(
    await page.getByTestId('btc-market-summary').getAttribute('data-market-ticker-timestamp'),
  )).toBeGreaterThan(Date.UTC(2026, 6, 14, 15, 0, 2));
  await expect(page.locator('.tv-chart-foot')).toContainText('K 线：PASS');
  await expect(page.locator('.tv-chart-foot')).toContainText('Schema 写入：NO');

  await page.getByRole('button', {name: /订单 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('btc-demo-client-001');
  await page.getByRole('button', {name: /成交 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('demo-fill-001');
  await page.getByRole('button', {name: /仓位 1/}).click();
  await expect(page.locator('.tv-data-table')).toContainText('62032');
  await page.getByRole('button', {name: '费用与资金费'}).click();
  await expect(page.locator('.tv-cost-grid')).toContainText('5.000 bps');
  await expect(page.locator('.tv-cost-grid')).toContainText('Funding 样本');
  await page.getByRole('button', {name: '审计'}).click();
  await expect(page.locator('.tv-audit-list')).toContainText('成交已对账');
  await expect(page.locator('.tv-research-disclaimer')).toContainText('研究回测与受限 OKX Demo runtime 是两条隔离链路');
});

test('native chart zoom and pan work without a floating navigation toolbar at 1131px', async ({page}) => {
  await page.setViewportSize({width: 1131, height: 975});
  await mockBtcTradingPage(page, {signalReady: true});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const chart = page.getByTestId('btc-trading-chart');
  const span = async () => Number(await chart.getAttribute('data-visible-logical-span'));
  const center = async () => Number(await chart.getAttribute('data-visible-logical-center'));
  await expect(chart.locator('canvas').first()).toBeVisible();
  await expect(page.locator('.tv-chart-navigation')).toHaveCount(0);
  await expect(page.getByTestId('btc-chart-zoom-out')).toHaveCount(0);
  await expect.poll(span).toBeGreaterThan(0);
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  expect(box).not.toBeNull();
  const x = box!.x + box!.width * 0.45;
  const y = box!.y + box!.height * 0.4;
  const initial = await span();
  await page.mouse.move(x, y);
  for (let step = 0; step < 8; step++) await page.mouse.wheel(0, -120);
  await expect.poll(span).toBeLessThan(initial);
  const zoomed = await span();
  for (let step = 0; step < 8; step++) await page.mouse.wheel(0, 120);
  await expect.poll(span).toBeGreaterThan(zoomed);
  // Allow more than width/3 visible candles: the previous 3px floor blocked this.
  for (let step = 0; step < 8; step++) await page.mouse.wheel(0, 120);
  await expect.poll(span).toBeGreaterThan(box!.width / 3);
  for (let step = 0; step < 24; step++) await page.mouse.wheel(0, -120);
  await expect.poll(span).toBeLessThan(box!.width / 3);
  const beforePan = await center();
  await page.mouse.down();
  await page.mouse.move(x + 65, y, {steps: 10});
  await page.mouse.up();
  await expect.poll(async () => Math.abs(await center() - beforePan)).toBeGreaterThan(1);
  const beforeTick = await span();
  const tickerBefore = Number(await page.getByTestId('btc-market-summary')
    .getAttribute('data-market-ticker-timestamp'));
  await expect.poll(async () => Number(await page.getByTestId('btc-market-summary')
    .getAttribute('data-market-ticker-timestamp'))).toBeGreaterThan(tickerBefore);
  expect(Math.abs(await span() - beforeTick)).toBeLessThan(1);
  await chart.dblclick({position: {x: box!.width * 0.45, y: box!.height * 0.4}});
  await expect.poll(async () => Math.abs(await span() - initial)).toBeLessThan(1);
});

test('responsive market layout keeps the chart visible and projects the independent 25h observer', async ({page}) => {
  await page.setViewportSize({width: 1131, height: 975});
  await mockBtcTradingPage(page, {signalReady: true});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const chart = page.locator('.tv-chart-stack');
  const depth = page.getByTestId('btc-public-depth');
  await expect(chart.locator('canvas').first()).toBeVisible();
  await expect(depth).toBeVisible();
  await expect(page.getByTestId('btc-private-readonly-observation-progress')).toContainText(
    '独立 Private Readonly 25h 观察',
  );
  await expect(page.getByTestId('btc-private-readonly-observation-progress')).toContainText('0.50 / 25');
  await expect(page.getByTestId('btc-private-readonly-observation-progress')).toContainText('current HEAD');
  await expect(page.getByTestId('btc-private-readonly-observation-progress')).toContainText('gate_eligible=false');

  const chartBox = await chart.boundingBox();
  const depthBox = await depth.boundingBox();
  const chartFootBox = await page.locator('.tv-chart-foot').boundingBox();
  const testerSeparatorBox = await page.getByTestId('btc-strategy-tester-separator').boundingBox();
  expect(chartBox?.width ?? 0).toBeGreaterThan(320);
  expect(chartBox?.height ?? 0).toBeGreaterThan(120);
  expect(depthBox?.width ?? 0).toBeGreaterThan(180);
  expect(Math.abs((chartBox?.y ?? 0) - (depthBox?.y ?? 0))).toBeLessThan(4);
  expect(Math.abs((testerSeparatorBox?.y ?? 0) - (
    (chartFootBox?.y ?? 0) + (chartFootBox?.height ?? 0)
  ))).toBeLessThan(4);

  const compactFontSize = await page.getByTestId('crypto-workspace').evaluate((element) => (
    Number.parseFloat(window.getComputedStyle(element).fontSize)
  ));
  expect(compactFontSize).toBeGreaterThanOrEqual(12);
  expect(compactFontSize).toBeLessThan(13);

  await page.setViewportSize({width: 1600, height: 1200});
  await expect.poll(async () => page.getByTestId('crypto-workspace').evaluate((element) => (
    Number.parseFloat(window.getComputedStyle(element).fontSize)
  ))).toBeGreaterThan(compactFontSize + 3);

  await page.getByTitle('图表全屏').click();
  await expect(page.getByTestId('crypto-workspace')).toHaveClass(/chart-expanded/);
  const expandedChartBox = await chart.boundingBox();
  const expandedPanelBox = await page.locator('.tv-chart-panel').boundingBox();
  const workspaceBox = await page.getByTestId('crypto-workspace').boundingBox();
  expect(expandedChartBox?.width ?? 0).toBeGreaterThan(650);
  expect(expandedChartBox?.height ?? 0).toBeGreaterThan(420);
  expect(expandedPanelBox?.width ?? 0).toBeGreaterThan((workspaceBox?.width ?? 0) * 0.85);
  expect((workspaceBox?.x ?? 0) + (workspaceBox?.width ?? 0) - (
    (expandedPanelBox?.x ?? 0) + (expandedPanelBox?.width ?? 0)
  )).toBeLessThan(8);
  await expect(chart.locator('canvas').first()).toBeVisible();
});
