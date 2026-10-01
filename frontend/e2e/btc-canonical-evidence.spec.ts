import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

test('current-HEAD OKX native evidence unlocks research views without starting execution', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {
    signalReady: true,
    canonicalFreshness: 'pass',
    runtimeStatus: 'stopped',
    runtimeBlockers: ['runtime_non_empty_fill_sample_missing', 'depth_fill_mapping_missing'],
  });
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();
  await expect(page.locator('.tv-chart-source')).toContainText('OKX SWAP · completed 1h · SHA verified');
  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await expect(tester).toContainText('12.83%');
  await expect(tester).toContainText('4.40%');
  await expect(tester).toContainText('CURRENT-HEAD canonical');
  await expect(tester.getByRole('button', {name: '运行本地研究回测'})).toBeEnabled();
  await expect(page.locator('.tv-research-disclaimer')).toContainText('不表示 paper/live ready');
  expect(mock.calls).toHaveLength(0);
});
