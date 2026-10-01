import {expect, test} from '@playwright/test';

import {
  mockBtcTradingPage,
  strategyHistoryFixture,
  strategyHistoryCatalogFixture,
} from './btc-trading-fixtures';


test('StrictMode shares one in-flight BTC history catalog request', async ({page}) => {
  await mockBtcTradingPage(page);
  let catalogRequests = 0;
  await page.route('**/api/research/btc/strategy-history/catalog', async (route) => {
    catalogRequests += 1;
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({status: 200, json: strategyHistoryCatalogFixture()});
  });

  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

  await expect(page.locator('[data-testid="btc-history-link-btc_ls_tf_stable_001"]')).toBeVisible();
  await expect.poll(() => catalogRequests).toBe(1);
  await expect(page.locator('[data-testid="btc-strategy-history-catalog"]')).toContainText('4 个候选');
});


test('BTC history catalog failure can retry and clears the old error', async ({page}) => {
  await mockBtcTradingPage(page);
  let catalogRequests = 0;
  await page.route('**/api/research/btc/strategy-history/catalog', async (route) => {
    catalogRequests += 1;
    if (catalogRequests === 1) {
      await route.fulfill({status: 503, json: {detail: 'catalog temporarily unavailable'}});
      return;
    }
    await route.fulfill({status: 200, json: strategyHistoryCatalogFixture()});
  });

  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
  const retry = page.locator('[data-testid="btc-strategy-history-retry"]');
  await expect(retry).toBeVisible();
  await expect(page.locator('[data-testid="btc-strategy-history-catalog"]')).toContainText('历史目录服务暂不可用（HTTP 503）');

  await retry.click();

  await expect(page.locator('[data-testid="btc-history-link-btc_ls_tf_stable_001"]')).toBeVisible();
  await expect(page.locator('[data-testid="btc-strategy-history-retry"]')).toHaveCount(0);
  await expect.poll(() => catalogRequests).toBe(2);
});

test('identity-only strategy stays neutral and skips canonical source GET', async ({page}) => {
  await mockBtcTradingPage(page);
  let sourceGets = 0;
  await page.route('**/api/research/btc/strategy-source/**', async (route) => {
    sourceGets += 1;
    await route.fulfill({status: 409, json: {detail: 'canonical strategy source unavailable'}});
  });

  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
  const identityOnly = page.getByTestId('strategy-tree-btc-btc_high_octane_v1-identity-high-octane');
  await expect(identityOnly).toBeVisible();
  await identityOnly.click();

  const unavailable = page.getByTestId('strategy-workbench-source-unavailable');
  await expect(unavailable).toContainText('该候选仅有身份/参数与历史证据');
  await expect(unavailable).toContainText('没有可执行 canonical 源码');
  await expect(page.locator('.strategy-workbench-source-editor')).toHaveCount(0);
  await expect(page.locator('.strategy-workbench-definition')).not.toContainText('源码读取失败');
  expect(sourceGets).toBe(0);
});


test('BTC history detail 503 stays compact, Chinese, and never fabricates a report before recovery', async ({page}) => {
  await mockBtcTradingPage(page);
  let detailRequests = 0;
  await page.route('**/api/research/btc/strategy-history/long_short_donchian_top5/btc_ls_tf_stable_001', async (route) => {
    detailRequests += 1;
    if (detailRequests === 1) {
      await route.fulfill({status: 503, json: {detail: 'history report temporarily unavailable'}});
      return;
    }
    await route.fulfill({status: 200, json: strategyHistoryFixture('long_short_donchian_top5', 'btc_ls_tf_stable_001')});
  });

  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
  const performance = page.getByRole('region', {name: '回测绩效'});
  await expect(performance).toContainText('历史报告暂不可用');
  await expect(performance).toContainText('未生成占位指标、曲线或交易标记');
  await expect(performance.locator('[data-testid="strategy-workbench-report"]')).toHaveCount(0);
  await expect(performance.getByRole('button', {name: '重新读取报告'})).toBeVisible();
  await expect(page.locator('.strategy-workbench-dock')).toHaveClass(/is-collapsed/);

  await performance.getByRole('button', {name: '重新读取报告'}).click();
  await expect(page.locator('[data-testid="strategy-workbench-report"]')).toBeVisible();
  await expect.poll(() => detailRequests).toBe(2);
  expect((await performance.boundingBox())?.height).toBeGreaterThan(0);
  expect((await page.locator('.strategy-workbench-dock').boundingBox())?.height ?? 999).toBeLessThan(80);
});


test('BTC strategy card deep-links to the exact candidate historical report', async ({page}) => {
  await mockBtcTradingPage(page);
  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

  const link = page.locator('[data-testid="btc-history-link-btc_ls_tf_stable_001"]');
  await expect(link).toContainText('查看历史回测与详细报告');
  await link.click();

  await expect(page).toHaveURL(/\/crypto\?.*strategy_id=long_short_donchian_top5/);
  await expect(page).toHaveURL(/candidate_id=btc_ls_tf_stable_001/);
  await expect(page.locator('[data-testid="btc-strategy-history-relationship"]')).toContainText('CANDIDATE MATCHED');
  await expect(page.getByText(/历史研究摘要 · 无连续 ledger\/fills\/净值曲线/)).toBeVisible();
  await expect(page.locator('[data-testid="btc-persistent-history-runs"]')).toContainText('btc-top5-history');
  await expect(page.locator('[data-testid="btc-strategy-report"]')).toBeVisible();
  await page.getByRole('button', {name: '业绩表现'}).click();
  await expect(page.locator('[data-testid="btc-historical-performance-details"]')).toContainText('20');
  await page.getByRole('button', {name: '风险与资本'}).click();
  await expect(page.locator('[data-testid="btc-historical-risk-details"]')).toContainText('bull_trend');
  await expect(page.getByText('初始资本').locator('..')).toContainText('—');
});


test('Crypto StrictMode shares delayed bootstrap and opens the exact deep-link report', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {bootstrapDelayMs: 150});
  const strategyId = 'long_short_donchian_top5';
  const candidateId = 'btc_ls_tf_stable_001';
  await page.goto(
    `/crypto?strategy_id=${strategyId}&candidate_id=${candidateId}&panel=backtest&report_tab=overview`,
    {waitUntil: 'domcontentloaded'},
  );

  await expect(page.locator('[data-testid="btc-strategy-report"]')).toBeVisible();
  await expect(page.locator('[data-testid="btc-strategy-history-relationship"]')).toContainText('CANDIDATE MATCHED');
  await page.getByRole('button', {name: '风险与资本'}).click();
  await expect(page.getByText('初始资本').locator('..')).toContainText('—');

  for (const pathname of [
    '/api/research/btc/demo-paper/catalog',
    '/api/research/btc/demo-paper/status',
    '/api/research/btc/demo-paper/klines',
  ]) {
    await expect.poll(() => mock.requests.filter((item) => item.pathname === pathname).length).toBe(1);
  }
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === `/api/research/btc/strategy-history/${strategyId}/${candidateId}`,
  ).length).toBeGreaterThanOrEqual(1);
});


test('slow or failed bootstrap siblings do not block the exact history detail', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {
    catalogDelayMs: 100,
    statusDelayMs: 3_000,
    klinesError: 'klines temporarily unavailable',
  });
  const strategyId = 'long_short_donchian_top5';
  const candidateId = 'btc_ls_tf_stable_001';
  await page.goto(
    `/crypto?strategy_id=${strategyId}&candidate_id=${candidateId}&panel=backtest&report_tab=overview`,
    {waitUntil: 'domcontentloaded'},
  );

  await expect(page.locator('[data-testid="btc-strategy-report"]')).toBeVisible({timeout: 1_500});
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === `/api/research/btc/strategy-history/${strategyId}/${candidateId}`,
  ).length).toBeGreaterThanOrEqual(1);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === '/api/research/btc/demo-paper/status',
  ).length).toBe(1);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === '/api/research/btc/demo-paper/klines',
  ).length).toBe(1);
});


test('BTC 10x ten-sleeve rollover archive is prominent, exact, read-only, and isolated from Demo', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

  const card = page.getByTestId('btc-rollover-archive-card');
  await expect(card).toContainText('BTC 10x 十仓滚仓爆炸版（历史危险参照）');
  await expect(card).toContainText('br_split_2_on_double_lev10p0');
  await expect(card).toContainText('1,510,327.760228%');
  await expect(card).toContainText('4,648.314318%');
  await expect(card).toContainText('49.504493%');
  await expect(card).toContainText('all-dead');
  await expect(card).toContainText('RESEARCH ONLY · NO PAPER · NO LIVE');

  await card.getByTestId('btc-rollover-archive-link').click();
  await expect(page).toHaveURL(/research_archive=btc_10x_rollover_10sleeve/);
  const detail = page.getByTestId('btc-rollover-archive-detail');
  await expect(detail).toContainText('拆仓增量');
  await expect(detail).toContainText('Rolling starts：29');
  await expect(detail).toContainText('56.856895');
  await expect(detail).toContainText('high_octane_attack_sleeve_v2');
  await expect(detail).toContainText('后续派生不是原始万倍对象');
  await expect(detail).toContainText('非 current-HEAD immutable · 非 promotion evidence');
  await expect(detail).toContainText('docs/research/btc_10x_rollover_and_donchian_direction_origin.md');
  await expect(page.getByTestId('btc-demo-console')).toHaveCount(0);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});


test('strategy discovery merges stable identities and keeps danger archive out of runnable classification', async ({page}) => {
  await mockBtcTradingPage(page);
  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

  const merged = page.locator('[data-strategy-identity="btc:long_short_donchian_top5:btc_ls_tf_stable_001"]');
  await expect(merged).toHaveCount(1);
  await expect(merged).toContainText('BTC 策略注册表 + BTC Demo 目录 + BTC 历史目录');
  await expect(merged).toContainText('系统安全');
  await expect(merged).toContainText('研究只读 · 纸盘/实盘/订单/私有接口均禁用');
  await expect(merged).toContainText('变体：变体 1');
  await expect(merged).toContainText('信号：可用');
  await expect(merged).toContainText('回测：支持');
  await expect(merged).not.toContainText('canonical_signal');
  const okxNativeVariants = page.locator('[data-strategy-identity^="btc:long_short_donchian_top5_okx_native:"]');
  await expect(okxNativeVariants).toHaveCount(2);
  await expect(okxNativeVariants.first()).toContainText('变体：OKX 原生 · 变体 1');
  await expect(okxNativeVariants.nth(1)).toContainText('变体：OKX 原生 · 变体 2');
  await expect(page.getByTestId('strategy-source-coverage')).toContainText('6 条美股可信运行');
  await expect(page.locator('[data-strategy-identity^="catalog:us:"]')).toHaveCount(6);
  await expect(page.locator('[data-strategy-identity^="catalog:us:"]').first()).toContainText('晋级状态=已阻断');
  await expect(page.locator('[data-strategy-identity^="catalog:us:"]').first()).toContainText('新鲜度=已核验 Git 对象（未达到晋级条件）');
  await expect(page.locator('[data-strategy-identity^="catalog:us:"]').first()).toContainText('12%');
  await expect(page.locator('[data-strategy-identity^="catalog:us:"]').first()).toContainText('详细回测未由当前可用源发布');

  await page.getByLabel('策略分类筛选').selectOption({label: '系统 · 可运行（当前仅 Demo）'});
  await expect(page.locator('[data-strategy-identity^="archive:"]')).toHaveCount(0);
  await expect(page.locator('.strategy-discovery-grid .discovery-runnable')).not.toHaveCount(0);
});


test('versioned user categories create, assign, persist, rename, delete, and never edit system safety', async ({page}) => {
  await mockBtcTradingPage(page);
  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
  const identity = 'archive:br_split_2_on_double_lev10p0';
  let card = page.locator(`[data-strategy-identity="${identity}"]`);

  await page.getByLabel('新建用户分类名称').fill('重点复核');
  await page.getByRole('button', {name: '新建分类'}).click();
  await card.getByLabel(/调整用户分类/).selectOption({label: '重点复核'});
  await expect(card).toContainText('用户分类 重点复核');
  await page.reload({waitUntil: 'domcontentloaded'});

  card = page.locator(`[data-strategy-identity="${identity}"]`);
  await expect(card).toContainText('用户分类 重点复核');
  await expect(card).toContainText('历史危险参照');
  await expect(card).toContainText('研究只读 · 纸盘/实盘/订单/私有接口均禁用');

  const editor = page.getByTestId('strategy-user-category-editor');
  await editor.getByLabel('重命名分类 重点复核').fill('仅观察');
  await editor.getByRole('button', {name: '保存重命名'}).click();
  await expect(card).toContainText('用户分类 仅观察');
  await editor.getByRole('button', {name: '删除分类'}).click();
  await expect(card).toContainText('用户分类 未分类');
  await expect(card).toContainText('历史危险参照');
});


test('a missing strategy source is explicit while other discovered sources remain visible', async ({page}) => {
  await mockBtcTradingPage(page, {catalogError: 'registry unavailable'});
  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

  const coverage = page.getByTestId('strategy-source-coverage');
  await expect(coverage).toContainText('BTC Demo 目录');
  await expect(coverage).toContainText('缺失');
  await expect(page.getByTestId('btc-rollover-archive-card')).toBeVisible();
  await expect(page.locator('[data-strategy-identity^="archive:"]')).toBeVisible();
});


test('Demo catalog can remain unavailable while an exact history detail renders read-only', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {catalogError: 'demo catalog intentionally unavailable'});
  const strategyId = 'long_short_donchian_top5';
  const candidateId = 'btc_ls_tf_stable_001';

  await page.goto(
    `/crypto?strategy_id=${strategyId}&candidate_id=${candidateId}&panel=backtest&report_tab=overview`,
    {waitUntil: 'domcontentloaded'},
  );

  await expect(page.locator('[data-testid="btc-strategy-history-relationship"]')).toContainText('CANDIDATE MATCHED');
  await expect(page.locator('[data-testid="btc-historical-summary-overview"]')).toBeVisible();
  await expect(page.locator('[data-testid="btc-strategy-history-error"]')).toHaveCount(0);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === `/api/research/btc/strategy-history/${strategyId}/${candidateId}`,
  ).length).toBeGreaterThanOrEqual(1);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});


test('unavailable current-HEAD contract stays compact and fail-closed beside readable history', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {domainReadModelError: 'current-head contract unavailable'});
  await page.goto(
    '/crypto?strategy_id=long_short_donchian_top5&candidate_id=btc_ls_tf_stable_001&panel=backtest&report_tab=overview',
    {waitUntil: 'domcontentloaded'},
  );

  const contract = page.getByTestId('btc-current-head-domain-read-model');
  await expect(contract).toContainText('promotion/current-HEAD contract unavailable');
  await expect(contract).toContainText('历史研究报告仍可只读查看，不解锁任何执行');
  expect((await contract.boundingBox())?.height).toBeLessThan(180);
  await expect(page.getByTestId('btc-historical-summary-overview')).toBeVisible();
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});


test('history-only identity bypasses Demo selection and overview uses published details instead of empty charts', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  const strategyId = 'btc_history_archive_v1';
  const candidateId = 'history-only-candidate-001';
  const payload = strategyHistoryFixture(strategyId, candidateId);
  await page.route(`**/api/research/btc/strategy-history/${strategyId}/${candidateId}`, async (route) => {
    await route.fulfill({status: 200, json: payload});
  });

  await page.goto(
    `/crypto?strategy_id=${strategyId}&candidate_id=${candidateId}&panel=backtest&report_tab=overview`,
    {waitUntil: 'domcontentloaded'},
  );

  const overview = page.locator('[data-testid="btc-historical-summary-overview"]');
  await expect(overview).toContainText('源快照未发布连续 ledger / fills / series');
  await expect(overview).toContainText('年化收益');
  await expect(overview).toContainText('逐年表现');
  await expect(overview).toContainText('Holdout');
  await expect(overview).toContainText('Walk-forward');
  await expect(overview).toContainText('成本压力');
  await expect(page.locator('[data-testid="btc-equity-chart"]')).toHaveCount(0);
  await expect(page.getByTestId('btc-demo-console').getByRole('combobox')).not.toHaveValue(candidateId);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});


test('failed crypto catalog bootstrap retries without caching the rejection', async ({page}) => {
  const mock = await mockBtcTradingPage(page, {catalogFailuresBeforeSuccess: 1});
  const strategyId = 'long_short_donchian_top5';
  const candidateId = 'btc_ls_tf_stable_001';
  await page.goto(
    `/crypto?strategy_id=${strategyId}&candidate_id=${candidateId}&panel=backtest&report_tab=overview`,
    {waitUntil: 'domcontentloaded'},
  );

  const retry = page.locator('[data-testid="btc-crypto-bootstrap-retry"]');
  await expect(retry).toBeVisible();
  await retry.click();

  await expect(page.locator('[data-testid="btc-strategy-report"]')).toBeVisible();
  await expect(retry).toHaveCount(0);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === '/api/research/btc/demo-paper/catalog',
  ).length).toBe(2);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname === `/api/research/btc/strategy-history/${strategyId}/${candidateId}`,
  ).length).toBe(1);
});


test('completed local backtest imports idempotently without user-entered metrics or permissions', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.addInitScript(() => {
    const summary = {
      total_return_pct: 18.5,
      annual_return_pct: 12.25,
      annual_volatility_pct: 9.5,
      sharpe_ratio: 1.21,
      sortino_ratio: 1.44,
      max_drawdown_pct: -7.75,
      calmar_ratio: 1.58,
      win_rate_pct: 54,
      profit_factor: 1.3,
      trade_count: 42,
    };
    localStorage.setItem('quantstation.btc.trading-workbench.v2', JSON.stringify([
      {
        strategyId: 'local_completed_strategy',
        candidateId: 'candidate_local_001',
        strategyVersion: 'local_completed_strategy_v1',
        paramsHash: 'e'.repeat(64),
        savedAt: '2026-08-01T00:00:00Z',
        run: {
          run_id: 'local-run-completed-001',
          mode: 'backtest',
          status: 'completed',
          created_at: '2026-08-01T00:00:00Z',
          completed_at: '2026-08-01T01:00:00Z',
          summary,
          latest_weights: [],
          strategy_details: [],
          diagnostics: {btc_strategy_identity: {strategy_id: 'local_completed_strategy', candidate_id: 'candidate_local_001'}},
        },
        chart: {
          candles: [
            {time: 1785542400, open: 100, high: 103, low: 99, close: 102},
            {time: 1785546000, open: 102, high: 105, low: 101, close: 104},
          ],
          markers: [{time: 1785542400, position: 'belowBar', color: '#16c784', shape: 'arrowUp', text: 'local fill'}],
          equity: [{time: 1785542400, value: 100_000}, {time: 1785546000, value: 118_500}],
          drawdown: [{time: 1785542400, value: 0}, {time: 1785546000, value: -7.75}],
          exposure: [{time: 1785542400, value: 0}, {time: 1785546000, value: 1}],
          net_units: [{time: 1785542400, value: 0}, {time: 1785546000, value: 1}],
          turnover: [{time: 1785542400, value: 0}, {time: 1785546000, value: 1}],
          leverage: [{time: 1785542400, value: 0}, {time: 1785546000, value: 1}],
        },
      },
      {
        strategyId: 'local_failed_strategy',
        candidateId: 'candidate_local_failed',
        savedAt: '2026-08-01T00:00:00Z',
        run: {
          run_id: 'local-run-failed-001',
          status: 'failed',
          summary,
          diagnostics: {btc_strategy_identity: {strategy_id: 'local_failed_strategy', candidate_id: 'candidate_local_failed'}},
        },
      },
    ]));
  });

  await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
  const importer = page.getByTestId('strategy-local-backtest-import');
  const select = importer.getByLabel('选择本机已完成回测');
  await expect(select.locator('option')).toHaveCount(2);
  await expect(select).not.toContainText('local_failed_strategy');
  await select.selectOption('user:btc:local_completed_strategy:candidate_local_001:local-run-completed-001');
  await importer.getByLabel('导入后的显示名').fill('我的完成回测');
  await importer.getByRole('button', {name: '导入策略浏览'}).click();
  await importer.getByRole('button', {name: '导入策略浏览'}).click();

  const card = page.locator('[data-strategy-identity="user-backtest:user:btc:local_completed_strategy:candidate_local_001:local-run-completed-001"]');
  await expect(card).toContainText('我的完成回测');
  await expect(card).toContainText('研究展示');
  await expect(card).toContainText('研究只读 · 纸盘/实盘/订单/私有接口均禁用');
  await expect(card.getByRole('link', {name: '查看历史回测与详细报告'})).toHaveAttribute('href', /local_run_id=local-run-completed-001/);
  await expect.poll(() => page.evaluate(() => {
    const payload = JSON.parse(localStorage.getItem('quantstation.user-backtest-strategy-catalog.v1') || '{}');
    return payload.records?.length;
  })).toBe(1);

  await card.getByRole('link', {name: '查看历史回测与详细报告'}).click();

  await expect(page).toHaveURL(/local_run_id=local-run-completed-001/);
  const report = page.getByTestId('btc-strategy-tester');
  await expect(report).toContainText('浏览器本地研究 run');
  await expect(report).toContainText('18.50%');
  await expect(report).toContainText('7.75%');
  await expect(report).toContainText('1.210');
  await expect(page.getByTestId('add-backtest-to-strategy-catalog')).toBeVisible();
  await page.getByTestId('add-backtest-to-strategy-catalog').click();
  await page.getByTestId('add-backtest-to-strategy-catalog').click();

  await expect.poll(() => page.evaluate(() => {
    const payload = JSON.parse(localStorage.getItem('quantstation.user-backtest-strategy-catalog.v1') || '{}');
    return payload.records?.length;
  })).toBe(1);
  expect(mock.requests.filter((item) => (
    item.method === 'GET'
    && item.pathname === '/api/research/btc/strategy-history/local_completed_strategy/candidate_local_001'
  ))).toEqual([]);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);

  await page.getByTestId('btc-demo-console').getByRole('combobox').first().selectOption('btc_ls_tf_stable_001');
  await expect(page).not.toHaveURL(/local_run_id=/);
  await expect(report).not.toContainText('浏览器本地研究 run');
  await expect.poll(() => mock.requests.filter((item) => (
    item.method === 'GET'
    && item.pathname === '/api/research/btc/strategy-history/long_short_donchian_top5/btc_ls_tf_stable_001'
  )).length).toBeGreaterThanOrEqual(1);
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});

test('legacy latest v2 wins the same run over v1 and restores a real summary without inventing a chart', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.addInitScript(() => {
    const summary = (totalReturn: number) => ({
      total_return_pct: totalReturn,
      annual_return_pct: 10,
      annual_volatility_pct: 8,
      sharpe_ratio: 1.25,
      sortino_ratio: 1.5,
      max_drawdown_pct: -6,
      calmar_ratio: 1.6,
      win_rate_pct: 52,
      profit_factor: 1.2,
      trade_count: 24,
    });
    const identity = {
      strategy_id: 'legacy_summary_strategy',
      candidate_id: 'legacy_summary_candidate',
      strategy_version: 'legacy-v2',
      params_hash: 'a'.repeat(64),
    };
    localStorage.setItem('quantstation.btc.backtest.latest.v2', JSON.stringify({
      saved_at: '2026-08-02T00:00:00Z',
      run: {
        run_id: 'legacy-summary-run',
        status: 'completed',
        summary: summary(22.22),
        diagnostics: {btc_strategy_identity: identity},
      },
    }));
    localStorage.setItem('quantstation.btc.backtest.latest.v1', JSON.stringify([{
      strategyId: identity.strategy_id,
      candidateId: identity.candidate_id,
      strategyVersion: 'legacy-v1',
      paramsHash: identity.params_hash,
      run: {
        run_id: 'legacy-summary-run',
        status: 'completed',
        summary: summary(1.11),
        diagnostics: {btc_strategy_identity: identity},
      },
      chart: {
        candles: [{time: 1, open: 1, high: 1, low: 1, close: 1}],
        markers: [], equity: [{time: 1, value: 1}], drawdown: [], exposure: [], net_units: [], turnover: [], leverage: [],
      },
    }]));
  });

  await page.goto('/crypto?strategy_id=legacy_summary_strategy&candidate_id=legacy_summary_candidate&panel=backtest&local_run_id=legacy-summary-run', {waitUntil: 'domcontentloaded'});
  const report = page.getByTestId('btc-strategy-tester');
  await expect(report).toContainText('22.22%');
  await expect(page.getByTestId('btc-local-backtest-chart-missing')).toContainText('CHART EVIDENCE MISSING');
  await expect(page.getByRole('button', {name: '本地回测成交'})).toBeDisabled();
  await expect(page.getByRole('button', {name: '市场 K 线'})).toHaveClass(/active/);
  await expect(page.locator('.tv-chart-source')).not.toContainText('legacy-summary-run');
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});


test('historical strategy fixture does not manufacture ledger capital or PnL', () => {
  const payload = strategyHistoryFixture(
    'long_short_donchian_top5',
    'btc_ls_tf_stable_001',
  );
  expect(payload.canonical.metrics).not.toHaveProperty('initial_equity');
  expect(payload.canonical.metrics.final_equity).toBe(54056.72055);
  expect(payload.canonical.metrics).not.toHaveProperty('net_pnl');
  expect(payload.canonical.metrics).not.toHaveProperty('pnl_source');
  expect(payload.canonical).not.toHaveProperty('ledger_binding');
  expect(payload.canonical.metrics).toEqual(payload.details.full_metrics);
  expect(payload.canonical.cost_model).toEqual({
    units: 'return_pct',
    trading_cost_return_pct: -4,
    fee_return_pct: 4,
    funding_return_pct: 0.143296,
    cash_cost_components_available: false,
  });
  expect(payload.canonical_report.series).toEqual({
    equity: [],
    drawdown: [],
    monthly_returns: [],
    trades: [],
    costs: [],
  });
});


test('candidate selection refetches history and isolates local run identity', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.goto(
    '/crypto?strategy_id=long_short_donchian_top5&candidate_id=btc_ls_tf_stable_001&panel=backtest&report_tab=overview',
    {waitUntil: 'domcontentloaded'},
  );
  await expect(page.locator('[data-testid="btc-persistent-history-runs"]')).toContainText('btc-top5-history');

  const select = page.locator('[data-testid="btc-demo-console"] select').first();
  await select.selectOption('btc_ls_tf_stable_002');

  await expect(page).toHaveURL(/candidate_id=btc_ls_tf_stable_002/);
  await expect.poll(() => mock.requests.filter(
    (item) => item.pathname.endsWith('/long_short_donchian_top5/btc_ls_tf_stable_002'),
  ).length).toBe(1);
  await expect(page.locator('[data-testid="btc-strategy-history-error"]')).toHaveCount(0);
});


test('history response identity mismatch is hidden fail-closed', async ({page}) => {
  await mockBtcTradingPage(page, {historyIdentityMismatch: true});
  await page.goto(
    '/crypto?strategy_id=long_short_donchian_top5&candidate_id=btc_ls_tf_stable_001&panel=backtest',
    {waitUntil: 'domcontentloaded'},
  );

  const error = page.locator('[data-testid="btc-strategy-history-error"]');
  await expect(error).toContainText('response identity mismatch');
  await expect(error).toContainText('IDENTITY FAIL-CLOSED');
  await expect(page.locator('[data-testid="btc-persistent-history-runs"] button')).toHaveCount(0);
});
