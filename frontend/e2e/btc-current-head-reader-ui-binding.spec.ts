import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';


test('BTC current-head panel is GET-only and keeps every readiness flag false', async ({page}) => {
  const mock = await mockBtcTradingPage(page);

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');
  await expect(panel).toContainText('pending_next_stage_gate');
  await expect(panel).toContainText('blockers=184');
  await expect(panel).toContainText('required=17');
  await expect(panel).toContainText('required preserved=true');
  await expect(panel).toContainText('safety false=49/49');
  await expect(panel).toContainText('gate=blocked_fail_closed_no_paper_no_live');
  await expect(panel).toContainText('btc_okx_websocket_client_dependency_missing');
  await expect(panel).toContainText('promotion_evidence_ready=false');
  await expect(panel).toContainText('paper_ready=false');
  await expect(panel).toContainText('live_ready=false');

  const requests = mock.requests.filter(
    item => item.pathname === '/api/research/btc/domain-read-model',
  );
  expect(requests).toEqual([
    {method: 'GET', pathname: '/api/research/btc/domain-read-model'},
  ]);
  expect(mock.calls.some(item => item.pathname.includes('domain-read-model'))).toBe(false);
});

test('BTC current-head GET dedupes StrictMode in-flight work and refetches after remount', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {
    domainReadModelRequiredBlockerContract: 'quality',
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');

  const domainRequests = () => mock.requests.filter(
    item => item.pathname === '/api/research/btc/domain-read-model',
  );
  expect(domainRequests()).toEqual([
    {method: 'GET', pathname: '/api/research/btc/domain-read-model'},
  ]);

  await page.getByRole('link', {name: /研究台/}).click();
  await expect(page).toHaveURL(/\/research$/);
  await page.getByRole('link', {name: /加密策略/}).click();
  await expect(page).toHaveURL(/\/crypto$/);
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');

  expect(domainRequests()).toEqual([
    {method: 'GET', pathname: '/api/research/btc/domain-read-model'},
    {method: 'GET', pathname: '/api/research/btc/domain-read-model'},
  ]);
});

test('BTC current-head panel accepts the exact quality L2 contract and preserves blockers', async ({page}) => {
  await mockBtcTradingPage(page, {
    domainReadModelRequiredBlockerContract: 'quality',
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');
  await expect(panel).not.toContainText('CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(panel).toContainText('blockers=183');
  await expect(panel).toContainText('required=17');
  await expect(panel).toContainText('required preserved=true');
  await expect(panel).toContainText('btc_okx_l2_history_below_30_natural_days');
  await expect(panel).toContainText('gate=blocked_fail_closed_no_paper_no_live');
  await expect(panel).toContainText('promotion_evidence_ready=false');
  await expect(panel).toContainText('paper_ready=false');
  await expect(panel).toContainText('live_ready=false');
});

test('BTC current-head panel accepts the exact current-head rebuild contract', async ({page}) => {
  await mockBtcTradingPage(page, {
    domainReadModelRequiredBlockerContract: 'current-head-rebuild',
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');
  await expect(panel).not.toContainText('CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(panel).toContainText('blockers=10');
  await expect(panel).toContainText('required=10');
  await expect(panel).toContainText('required preserved=true');
  await expect(panel).toContainText('btc_okx_native:promotion_evidence_current_head_rebuild_required');
  await expect(panel).toContainText('gate=blocked_fail_closed_no_paper_no_live');
  await expect(panel).toContainText('promotion_evidence_ready=false');
  await expect(panel).toContainText('paper_ready=false');
  await expect(panel).toContainText('live_ready=false');
});

for (const tamper of [
  'missing',
  'extra',
  'reordered',
  'sha',
  'count',
  'preserved',
  'payload',
] as const) {
  test(`BTC current-head panel rejects current-head rebuild ${tamper} contract drift`, async ({page}) => {
    await mockBtcTradingPage(page, {
      domainReadModelRequiredBlockerContract: 'current-head-rebuild',
      domainReadModelRequiredBlockerTamper: tamper,
    });

    await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

    const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
    await expect(panel).toContainText('BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE');
    await expect(panel).toContainText('gate=blocked_fail_closed_no_paper_no_live');
    await expect(panel).toContainText('promotion_evidence_ready=false');
    await expect(panel).toContainText('paper_ready=false');
    await expect(panel).toContainText('live_ready=false');
  });
}

for (const tamper of [
  'missing',
  'extra',
  'reordered',
  'sha',
  'count',
  'preserved',
  'payload',
] as const) {
  test(`BTC current-head panel rejects quality L2 ${tamper} contract drift`, async ({page}) => {
    await mockBtcTradingPage(page, {
      domainReadModelRequiredBlockerContract: 'quality',
      domainReadModelRequiredBlockerTamper: tamper,
    });

    await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

    const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
    await expect(panel).toContainText('BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE');
    await expect(panel).toContainText('gate=blocked_fail_closed_no_paper_no_live');
    await expect(panel).toContainText('promotion_evidence_ready=false');
    await expect(panel).toContainText('paper_ready=false');
    await expect(panel).toContainText('live_ready=false');
  });
}

test('BTC current-head evidence remains available when unrelated BTC requests fail', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {
    catalogError: 'catalog timeout',
    statusError: 'status timeout',
    klinesError: 'klines timeout',
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('CURRENT HEAD · BLOCKED FAIL-CLOSED');
  await expect(panel).toContainText('promotion_evidence_ready=false');
  await expect(panel).not.toContainText('CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(page.getByText(/demo-paper\/catalog: 503/)).toBeVisible();

  const requests = mock.requests.filter(
    item => item.pathname === '/api/research/btc/domain-read-model',
  );
  expect(requests).toEqual([
    {method: 'GET', pathname: '/api/research/btc/domain-read-model'},
  ]);
});


test('BTC current-head panel blocks unsafe or mismatched evidence', async ({page}) => {
  await mockBtcTradingPage(page, {
    domainReadModelUnsafe: true,
    domainReadModelHead: 'f'.repeat(40),
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(panel).toContainText('frontend match=false');
  await expect(panel).toContainText('promotion_evidence_ready=true');
});


test('BTC current-head panel rejects synthetic 49-key safety fixtures', async ({page}) => {
  await mockBtcTradingPage(page, {
    domainReadModelSyntheticSafetyKeys: true,
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(panel).toContainText('safety false=49/49');
});


test('BTC current-head panel rejects reordered blockers or noncanonical gate', async ({page}) => {
  await mockBtcTradingPage(page, {
    domainReadModelInvalidRequiredBlockers: true,
    domainReadModelInvalidGateDecision: true,
  });

  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const panel = page.locator('[data-testid="btc-current-head-domain-read-model"]');
  await expect(panel).toContainText('BLOCKED · CONTRACT UNAVAILABLE OR UNSAFE');
  await expect(panel).toContainText('gate=blocked');
});
