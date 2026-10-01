import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

test('BTC workspace exposes a dense Supercharts layout and full strategy report', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true, canonicalFreshness: 'pass'});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const sidebarBox = await page.locator('.app-sidebar-compact').boundingBox();
  expect(sidebarBox?.width).toBeLessThanOrEqual(196);
  await expect(page.getByRole('button', {name: '指标'})).toBeVisible();
  await expect(page.getByRole('button', {name: '提醒'})).toBeVisible();
  await expect(page.getByRole('button', {name: '回放'})).toBeVisible();
  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();

  await page.getByRole('button', {name: '指标'}).click();
  const indicatorMenu = page.locator('[data-testid="btc-indicator-menu"]');
  await expect(indicatorMenu).toContainText('Donchian 120h 通道');
  await indicatorMenu.getByText('成交量', {exact: true}).click();
  await page.getByRole('button', {name: '指标'}).click();

  const report = page.locator('[data-testid="btc-strategy-tester"]');
  await expect(report).toContainText('净利润');
  await expect(report).toContainText('最大回撤');
  await expect(report).toContainText('盈利交易');
  await expect(report).toContainText('盈利因子');

  await report.getByRole('button', {name: '证据参数 / 新回测'}).click();
  await expect(page.locator('[data-testid="btc-backtest-properties"]')).toContainText('手续费率');
  await report.getByRole('button', {name: '业绩表现'}).click();
  await expect(report.locator('.tv-report-table')).toContainText('策略超额表现');
  await report.getByRole('button', {name: '交易分析'}).click();
  await expect(report).toContainText('Canonical 交易清单');
  await report.getByRole('button', {name: '风险与资本'}).click();
  await expect(report).toContainText('资本效率');
  await report.getByRole('button', {name: '证据链'}).click();
  await expect(report).toContainText('paper=false');
  await expect(report).toContainText('BLOCKED / UNKNOWN');

  await page.getByRole('button', {name: 'Demo 控制台'}).click();
  await expect(page.locator('[data-testid="btc-demo-console"]')).toHaveCount(0);
  await page.getByRole('button', {name: 'Demo 控制台'}).click();
  await expect(page.locator('[data-testid="btc-demo-console"]')).toContainText('OKX 模拟盘');

  await report.getByRole('button', {name: '运行本地研究回测'}).click();
  await report.getByRole('button', {name: '概览'}).click();
  await expect(page.locator('[data-testid="btc-equity-chart"] canvas').first()).toBeVisible();
  await expect(report).toContainText('run-test-001');
});

test('BTC trading chart mounts after market candles arrive before delayed bootstrap completes', async ({page}) => {
  let releaseKlines!: () => void;
  const klinesGate = new Promise<void>((resolve) => { releaseKlines = resolve; });
  await mockBtcTradingPage(page, {
    signalReady: true,
    canonicalFreshness: 'pass',
    klinesDelayMs: 250,
    catalogError: 'catalog intentionally unavailable while chart bootstraps',
    statusError: 'status intentionally unavailable while chart bootstraps',
  });
  await page.route('**/api/research/btc/demo-paper/market-view**', async (route) => {
    return route.fulfill({
      json: {
        schema_version: 'okx_public_market_view_v1',
        source_kind: 'okx_public_market_view_v1',
        instrument_id: 'BTC-USDT-SWAP',
        timeframe: '1m',
        read_only: true,
        public_only: true,
        private_endpoint_used: false,
        order_endpoint_used: false,
        strategy_signal_compatible: false,
        persisted_market_rows: false,
        captured_at_ms: 1783994400000,
        cache_age_ms: 0,
        stale: false,
        last_error_code: '',
        ticker: {bid: '62031', ask: '62033', last: '62032', timestamp_ms: 1783994400000},
        candles: [{
          open_time_ms: 1783994340000,
          open: 62020,
          high: 62040,
          low: 62010,
          close: 62032,
          volume: 12,
          confirmed: false,
          in_progress: true,
        }],
        depth: null,
      },
    });
  });
  await page.route('**/api/research/btc/demo-paper/klines**', async (route) => {
    await klinesGate;
    await route.fallback();
  });
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  await expect(page.locator('.tv-chart-source')).toContainText('1 / 1 bars');
  await expect(page.locator('.tv-chart-source')).toContainText('live');
  await expect(page.getByRole('button', {name: '市场 K 线', exact: true})).toHaveClass(/active/);
  await expect(page.locator('.tv-chart-empty')).toContainText('正在读取本地 completed 1h K 线');
  releaseKlines();
  await expect(page.locator('.tv-chart-empty')).toBeHidden();

  const chart = page.locator('[data-testid="btc-trading-chart"]');
  await expect(chart).toBeVisible();
  await expect(chart.locator('canvas').first()).toBeVisible();
  await expect(chart.locator('.tv-lightweight-charts')).toHaveCount(1);
  await expect.poll(() => chart.locator(':scope > *').count()).toBeGreaterThan(0);

  await page.getByRole('button', {name: '图表类型'}).click();
  await page.getByRole('button', {name: '收盘线'}).click();
  await expect(chart.locator('.tv-lightweight-charts')).toHaveCount(1);
  await page.getByRole('button', {name: '图表类型'}).click();
  await page.getByRole('button', {name: '蜡烛图'}).click();
  await expect(chart.locator('.tv-lightweight-charts')).toHaveCount(1);
});
