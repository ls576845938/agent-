import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

test('BTC Demo summary loads stopped and preserves fail-closed blockers', async ({page}) => {
  await mockBtcTradingPage(page, {
    signalReady: false,
    runtimeStatus: 'blocked_fail_closed',
    runtimeBlockers: ['fresh_completed_1h_signal_data_missing', 'runtime_non_empty_fill_sample_missing'],
  });
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console).toContainText('blocked_fail_closed');
  await expect(console).toContainText('fresh_completed_1h_signal_data_missing');
  await expect(console).toContainText('Fail-closed blockers');
  await expect(console.getByRole('button', {name: '启动 Demo 策略'})).toBeDisabled();
  await expect(console).toContainText('实盘、转账、提现和权限升级始终禁用');
});

test('newer reconciliation response replaces the stale Demo account snapshot', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {signalReady: true, initialEquity: '1000.50', reconciledEquity: '1200.75'});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console).toContainText('1,000.50 USDT');
  await console.getByRole('button', {name: '刷新账户对账'}).click();
  await expect(console).toContainText('1,200.75 USDT');
  await expect(console).toContainText('账户、仓位、订单、成交与费用已对账');
  expect(mock.calls.at(-1)).toEqual({pathname: '/api/research/btc/demo-paper/reconcile', payload: {confirmation_text: 'BTC DEMO'}});
});

test('BTC Demo console reports backend unavailable without unlocking execution', async ({page}) => {
  await mockBtcTradingPage(page, {
    signalReady: false,
    catalogError: 'backend unavailable',
    statusError: 'backend unavailable',
    klinesError: 'backend unavailable',
  });
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  await expect(page.locator('.tv-page-message')).toContainText('backend unavailable');
  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console.getByRole('button', {name: '启动 Demo 策略'})).toBeDisabled();
  await expect(console).toContainText('实盘、转账、提现和权限升级始终禁用');
  await expect(page.locator('.tv-research-disclaimer')).toContainText('实盘能力始终关闭');
});

test('BTC Demo safety summary remains readable on mobile without horizontal overflow', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockBtcTradingPage(page, {
    signalReady: false,
    runtimeStatus: 'blocked_fail_closed',
    runtimeBlockers: ['fresh_completed_1h_signal_data_missing'],
  });
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console).toContainText('Demo 启动阻塞');
  await expect(console).toContainText('实盘、转账、提现和权限升级始终禁用');
  const hasOverflow = await console.evaluate((element) => element.scrollWidth > element.clientWidth + 1);
  expect(hasOverflow).toBe(false);
});
