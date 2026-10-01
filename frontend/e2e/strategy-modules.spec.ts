import {test, expect} from '@playwright/test';

const registrySpec = (strategyId: string, candidateId: string, strategyVersion = `${strategyId}@1.0.0`) => ({
  strategy_id: strategyId,
  candidate_id: candidateId,
  strategy_version: strategyVersion,
  params_hash: `sha-${candidateId}`,
  instrument: 'BTC-USDT-SWAP',
  venue: 'OKX',
  timeframe: '1h',
  direction_policy: 'long_short',
  promotion_eligibility: 'blocked',
  promotion_credit_eligible: false,
  promotion_credit_allowed: false,
  adapter_fidelity: 'canonical',
  signal_data_venue: 'OKX Native public',
  execution_venue: 'OKX Demo',
  signal_instrument: 'BTC-USDT-SWAP',
  execution_instrument: 'BTC-USDT-SWAP',
  canonical_signal_available: true,
  strategy_callable: 'research_only',
  params: {window: 20, candidate: candidateId},
});

const registryFixture = {
  schema_version: 'btc_strategy_registry_api_v1',
  status: 'complete_research_only',
  decision: 'btc_strategy_registry_identity_catalog_no_auto_paper_no_live',
  default_strategy_id: 'long_short_donchian_top5',
  default_candidate_id: 'btc_ls_tf_stable_001',
  specs: [
    registrySpec('long_short_donchian_top5', 'btc_ls_tf_stable_001'),
    registrySpec('long_short_donchian_top5', 'btc_ls_tf_stable_002'),
    registrySpec('long_short_donchian_top5_okx_native', 'okx_native_btc_ls_tf_stable_001'),
    registrySpec('high_yield_donchian_v2', 'btc_high_yield_001'),
    registrySpec('high_octane_attack_sleeve_v2', 'btc_high_octane_001'),
  ],
  paper_queue_write_allowed: false,
  live_unlock_allowed: false,
  broker_or_order_allowed: false,
};

const unifiedCatalogFixture = {
  schema_version: 'strategy_history_catalog_v1',
  status: 'complete_research_only',
  records: [
    {catalog_key: 'us-etf-rotation-001', source: 'us research', domain: 'us_equity', record_kind: 'backtest', strategy_id: 'etf_rotation', candidate_id: 'us_etf_rotation_001', strategy_version: 'us_etf_rotation@1.0.0', params_hash: 'sha-us-etf-rotation', display_name: 'ETF Rotation (US)', research_status: 'COMPLETED', promotion_status: 'research_only', backtest_supported: true, paper_allowed: false, live_allowed: false},
    {catalog_key: 'cn-rules-qmt-001', source: 'cn research', domain: 'cn_equity', record_kind: 'backtest', strategy_id: 'cn_rules_qmt', candidate_id: 'cn_rules_qmt_001', strategy_version: 'cn_rules_qmt@1.0.0', params_hash: 'sha-cn-rules-qmt', display_name: 'CN Rules / QMT', research_status: 'COMPLETED', promotion_status: 'research_only', backtest_supported: true, paper_allowed: false, live_allowed: false},
  ],
};

const unifiedUsOnlyFixture = {
  schema_version: 'strategy_history_catalog_v1',
  status: 'complete_research_only',
  records: Array.from({length: 6}, (_, index) => ({
    catalog_key: `us-etf-rotation-${String(index + 1).padStart(3, '0')}`,
    source: 'us research',
    domain: 'us_equity',
    record_kind: 'backtest',
    strategy_id: 'etf_rotation',
    candidate_id: `us_etf_rotation_${String(index + 1).padStart(3, '0')}`,
    strategy_version: 'us_etf_rotation@1.0.0',
    params_hash: `sha-us-etf-rotation-${index + 1}`,
    display_name: 'ETF Rotation (US)',
    research_status: 'COMPLETED',
    promotion_status: 'research_only',
    backtest_supported: true,
    paper_allowed: false,
    live_allowed: false,
  })),
};

test.describe('strategy modules comparison map', () => {
  test.beforeEach(async ({page}) => {
    await page.route('**/api/**', async (route) => {
      if (route.request().method() !== 'GET') return route.fulfill({status: 405, json: {detail: 'strategy modules is read-only'}});
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/research/btc/strategy-registry') return route.fulfill({json: registryFixture});
      if (pathname === '/api/research/strategy-history/catalog') return route.fulfill({json: unifiedCatalogFixture});
      return route.fulfill({json: {status: 'unavailable', read_only: true}});
    });
  });

  test('keeps the existing navigation and adds the strategy modules route', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    const nav = page.getByRole('navigation', {name: '主导航'});
    await expect(nav.getByRole('link', {name: /策略模块/})).toHaveAttribute('href', '/strategy-modules');
    await expect(nav.getByRole('link', {name: /美股量化/})).toHaveAttribute('href', '/');
    await expect(nav.getByRole('link', {name: /A 股量化/})).toHaveAttribute('href', '/cn-equity');
    await expect(nav.getByRole('link', {name: /加密策略/})).toHaveAttribute('href', '/crypto');
    await expect(nav.getByRole('link', {name: /策略浏览/})).toHaveAttribute('href', '/strategies');
    await expect(nav.getByRole('link', {name: /策略模块/})).toHaveClass(/active/);
  });

  test('defaults to crypto, BTC-USDT-SWAP and a real registered BTC strategy', async ({page}) => {
    const methods: string[] = [];
    const urls: string[] = [];
    page.on('request', request => { methods.push(request.method()); urls.push(request.url()); });
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await expect(page.getByTestId('strategy-market-crypto')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('strategy-instrument-select')).toHaveValue('btc-usdt-swap');
    await expect(page.getByTestId('strategy-selector')).toHaveValue('long_short_donchian_top5::btc_ls_tf_stable_001');
    await expect(page.getByTestId('strategy-selector').locator('option')).toHaveCount(5);
    const optionValues = await page.getByTestId('strategy-selector').locator('option').evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value));
    expect(optionValues).toEqual([
      'long_short_donchian_top5::btc_ls_tf_stable_001',
      'long_short_donchian_top5::btc_ls_tf_stable_002',
      'long_short_donchian_top5_okx_native::okx_native_btc_ls_tf_stable_001',
      'high_yield_donchian_v2::btc_high_yield_001',
      'high_octane_attack_sleeve_v2::btc_high_octane_001',
    ]);
    await expect(page.getByTestId('strategy-modules-main')).toContainText('多空唐奇安突破 Top5');
    await expect(page.getByTestId('strategy-real-identity')).toContainText('candidate_id：btc_ls_tf_stable_001');
    await expect(page.getByTestId('strategy-real-identity')).toContainText('strategy_version：long_short_donchian_top5@1.0.0');
    await expect(page.getByTestId('strategy-market-state-visuals')).toBeVisible();
    await expect(page.locator('[data-testid^="strategy-market-state-card-"]')).toHaveCount(4);
    await expect(page.locator('[data-testid^="strategy-market-state-flow-node-"]')).toHaveCount(4);
    await expect(page.getByTestId('strategy-market-state-result')).toContainText('当前得到的成果');
    await expect(page.getByTestId('strategy-market-state-gaps')).toContainText('还需要补什么');
    await expect(page.getByTestId('strategy-modules-safety')).toContainText('POST 0');
    expect(methods.filter(method => method === 'POST')).toEqual([]);
    const apiUrls = urls.filter(url => {
      try { return new URL(url).pathname.startsWith('/api/'); } catch { return false; }
    });
    expect(apiUrls.filter(url => /private|order|live/i.test(new URL(url).pathname))).toEqual([]);
  });

  test('shows loading state before the real BTC registry resolves', async ({page}) => {
    await page.route('**/api/research/btc/strategy-registry', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 250));
      return route.fulfill({json: registryFixture});
    });
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await expect(page.getByTestId('strategy-catalog-state')).toContainText('正在加载真实策略目录');
    await expect(page.getByTestId('strategy-selector')).toBeDisabled();
    await expect(page.getByTestId('strategy-selector')).toHaveValue('');
    await expect(page.getByTestId('strategy-real-identity')).toHaveCount(0);
  });

  test('fails closed on registry 503 without hardcoded BTC entries', async ({page}) => {
    await page.route('**/api/research/btc/strategy-registry', async (route) => route.fulfill({status: 503, json: {detail: 'registry unavailable'}}));
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await expect(page.getByTestId('strategy-catalog-state')).toContainText('真实策略目录暂不可用');
    await expect(page.getByTestId('strategy-catalog-state')).toContainText('503');
    await expect(page.getByTestId('strategy-selector')).toBeDisabled();
    await expect(page.getByTestId('strategy-modules-workspace')).not.toContainText('BTC 低换手趋势');
    await expect(page.getByTestId('strategy-modules-workspace')).not.toContainText('BTC 趋势回撤');
  });

  test('shows an honest empty selector when a cross-market catalog has no records', async ({page}) => {
    await page.route('**/api/research/strategy-history/catalog', async (route) => route.fulfill({json: {schema_version: 'strategy_history_catalog_v1', status: 'complete_research_only', records: []}}));
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await page.getByTestId('strategy-market-us').click();
    await expect(page.getByTestId('strategy-catalog-state')).toContainText('当前没有已发布真实策略');
    await expect(page.getByTestId('strategy-selector')).toBeDisabled();
    await expect(page.getByTestId('strategy-selector').locator('option')).toHaveText('当前没有已发布真实策略');
  });

  test('filters unified history candidates by market and fails closed when CN has no records', async ({page}) => {
    await page.route('**/api/research/strategy-history/catalog', async (route) => route.fulfill({json: unifiedUsOnlyFixture}));
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await page.getByTestId('strategy-market-us').click();
    await expect(page.getByTestId('strategy-selector').locator('option')).toHaveCount(6);
    await page.getByTestId('strategy-market-cn').click();
    await expect(page.getByTestId('strategy-catalog-state')).toContainText('当前没有已发布真实策略');
    await expect(page.getByTestId('strategy-selector')).toBeDisabled();
    await expect(page.getByTestId('strategy-selector').locator('option')).toHaveText('当前没有已发布真实策略');
    await expect(page.getByTestId('strategy-modules-workspace')).not.toContainText('ETF Rotation (US)');
  });

  test('exposes exactly six modules in the required order', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    const cards = page.locator('[data-testid^="strategy-module-card-"]');
    await expect(cards).toHaveCount(6);
    await expect(page.getByTestId('strategy-module-flow')).toHaveAttribute('data-module-grid', '2x3');
    for (const [index, label] of ['超额收益来源假设', '适用的市场状态', '策略失效条件', '失效检测', '仓位管理', '退出机制'].entries()) {
      await expect(cards.nth(index)).toContainText(label);
    }
    const boxes = await Promise.all(Array.from({length: 6}, (_, index) => cards.nth(index).boundingBox()));
    expect(boxes.every(Boolean)).toBe(true);
    const widths = boxes.filter((box): box is NonNullable<typeof box> => Boolean(box)).map(box => box.width);
    expect(Math.max(...widths) - Math.min(...widths)).toBeLessThan(2);
    expect(Math.abs((boxes[2]?.x ?? 0) - (boxes[0]?.x ?? 0))).toBeLessThan(2);
    expect(Math.abs((boxes[4]?.x ?? 0) - (boxes[0]?.x ?? 0))).toBeLessThan(2);
    expect(Math.abs((boxes[3]?.x ?? 0) - (boxes[1]?.x ?? 0))).toBeLessThan(2);
    expect(Math.abs((boxes[5]?.x ?? 0) - (boxes[1]?.x ?? 0))).toBeLessThan(2);
    expect((boxes[2]?.y ?? 0)).toBeGreaterThan(boxes[0]?.y ?? 0);
    expect((boxes[4]?.y ?? 0)).toBeGreaterThan(boxes[2]?.y ?? 0);
    await expect(page.getByTestId('strategy-module-flow')).not.toContainText('入场机制');
    await expect(page.getByTestId('strategy-module-flow')).not.toContainText('验证证据');
    await expect(page.getByTestId('strategy-modules-main')).toContainText('06 个模块');
  });

  test('shows shared and strategy-specific ownership labels', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await expect(page.getByTestId('strategy-module-card-position')).toHaveAttribute('data-module-scope', 'shared');
    await expect(page.getByTestId('strategy-module-card-failure-detection')).toHaveAttribute('data-module-scope', 'shared');
    await expect(page.getByTestId('strategy-module-card-hypothesis')).toHaveAttribute('data-module-scope', 'unique');
    await expect(page.getByTestId('strategy-module-flow')).toContainText('本标的共享');
    await expect(page.getByTestId('strategy-module-flow')).toContainText('策略独有');
    await expect(page.getByTestId('strategy-detail-scope')).toContainText('本标的共享');
    await expect(page.getByTestId('strategy-market-state-visuals')).toBeVisible();
  });

  test('switches the concrete strategy while preserving shared risk modules', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await page.getByTestId('strategy-module-card-hypothesis').click();
    const beforeHypothesis = await page.getByTestId('strategy-module-detail').innerText();
    await page.getByTestId('strategy-selector').selectOption('long_short_donchian_top5::btc_ls_tf_stable_002');
    await expect(page.getByTestId('strategy-real-identity')).toContainText('candidate_id：btc_ls_tf_stable_002');
    await expect(page.getByTestId('strategy-module-detail')).not.toHaveText(beforeHypothesis);
    await page.getByTestId('strategy-module-card-exit').click();
    const afterExit = await page.getByTestId('strategy-module-detail').innerText();
    await page.getByTestId('strategy-selector').selectOption('high_yield_donchian_v2::btc_high_yield_001');
    await expect(page.getByTestId('strategy-module-detail')).not.toHaveText(afterExit);
    await expect(page.getByTestId('strategy-real-identity')).toContainText('candidate_id：btc_high_yield_001');
    await page.getByTestId('strategy-module-card-position').click();
    await expect(page.getByTestId('strategy-detail-scope')).toContainText('同一 BTC-USDT-SWAP 标的共享');
    await page.getByTestId('strategy-module-card-failure-detection').click();
    await expect(page.getByTestId('strategy-detail-scope')).toContainText('同一标的共享');
  });

  test('changes the right detail when each module is selected', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    const detail = page.getByTestId('strategy-module-detail');
    for (const [key, label] of [
      ['hypothesis', '超额收益来源假设'], ['market-state', '适用的市场状态'], ['failure-condition', '策略失效条件'],
      ['failure-detection', '失效检测'], ['position', '仓位管理'], ['exit', '退出机制'],
    ] as const) {
      await page.getByTestId(`strategy-module-card-${key}`).click();
      await expect(detail).toContainText(label);
      if (key === 'market-state') {
        await expect(page.getByTestId('strategy-market-state-visuals')).toBeVisible();
      } else {
        await expect(page.getByTestId('strategy-rich-module')).toBeVisible();
        await expect(page.locator('.strategy-modules-detail-steps')).toBeVisible();
      }
    }
  });

  test('switches market and strategy direction without inventing a concrete family strategy', async ({page}) => {
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    await page.getByTestId('strategy-market-us').click();
    await expect(page.getByTestId('strategy-instrument-select')).toHaveValue('us-research-universe');
    await expect(page.getByTestId('strategy-family-us-factors')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByTestId('strategy-selector')).toContainText('美股 ETF 轮动');
    await expect(page.getByTestId('strategy-real-identity')).toContainText('candidate_id：us_etf_rotation_001');
    await page.getByTestId('strategy-market-cn').click();
    await expect(page.getByTestId('strategy-instrument-select')).toHaveValue('cn-research-universe');
    await expect(page.getByTestId('strategy-family-cn-pit')).toHaveAttribute('aria-selected', 'true');
    await page.getByTestId('strategy-family-cn-rules').click();
    await expect(page.getByTestId('strategy-selector')).toContainText('CN Rules / QMT');
    await expect(page.getByTestId('strategy-selector').locator('option:checked')).toContainText('CN Rules / QMT');
    await expect(page.getByTestId('strategy-real-identity')).toContainText('candidate_id：cn_rules_qmt_001');
  });

  test('keeps a 32/68 desktop split and stacks panels on mobile', async ({page}) => {
    await page.setViewportSize({width: 1440, height: 960});
    await page.goto('/strategy-modules', {waitUntil: 'domcontentloaded'});
    const main = page.getByTestId('strategy-modules-main');
    await expect(main).toHaveAttribute('data-left-ratio', '32');
    await expect(main).toHaveAttribute('data-right-ratio', '68');
    const left = await page.locator('.strategy-modules-flow-panel').boundingBox();
    const right = await page.locator('.strategy-modules-detail-panel').boundingBox();
    const ratio = (left?.width ?? 0) / ((left?.width ?? 0) + (right?.width ?? 0));
    expect(ratio).toBeGreaterThan(0.30);
    expect(ratio).toBeLessThan(0.34);
    await page.setViewportSize({width: 760, height: 900});
    const mobileLeft = await page.locator('.strategy-modules-flow-panel').boundingBox();
    const mobileRight = await page.locator('.strategy-modules-detail-panel').boundingBox();
    expect(mobileLeft?.width).toBeGreaterThan(680);
    expect(mobileRight?.width).toBeGreaterThan(680);
    expect(mobileRight?.y).toBeGreaterThan(mobileLeft?.y ?? 0);
  });
});
