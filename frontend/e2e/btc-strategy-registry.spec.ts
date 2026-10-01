import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

test('BTC frozen Top5 identities are selectable while overlays remain identity-only', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const console = page.locator('[data-testid="btc-demo-console"]');
  await expect(console.getByRole('button', {name: /多空唐奇安突破 Top5（OKX 原生）/})).toBeEnabled();
  await expect(console.getByRole('button', {name: /高收益唐奇安 v2/})).toBeDisabled();
  await expect(console.getByRole('button', {name: /高强度进攻分仓 v2/})).toBeDisabled();
  await expect(console).toContainText('仅身份候选；没有 Demo 执行账本');
  await expect(console).not.toContainText('Identity only');
  await expect(console.getByRole('button', {name: /高收益唐奇安 v2/})).toHaveAttribute('title', /仅身份候选；没有 Demo 执行账本/);

  const candidate = console.getByLabel(/冻结候选 · 多空唐奇安突破 Top5（OKX 原生）/);
  await expect(candidate.locator('option')).toHaveCount(2);
  await expect(candidate.locator('option').first()).toContainText('OKX 原生 · 变体 1');
  await expect(candidate.locator('option').nth(1)).toContainText('OKX 原生 · 变体 2');
  await candidate.selectOption('okx_native_btc_ls_tf_stable_002');
  await expect(candidate).toHaveValue('okx_native_btc_ls_tf_stable_002');
  await expect(page.locator('[data-testid="btc-strategy-tester"]')).toContainText('CURRENT-HEAD canonical');
  await expect(page.locator('.tv-chart-source')).toContainText('OKX SWAP · completed 1h');
});
