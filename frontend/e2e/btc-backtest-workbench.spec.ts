import {expect, test} from '@playwright/test';

import {mockBtcTradingPage} from './btc-trading-fixtures';

const CANONICAL_STRATEGY = 'long_short_donchian_top5_okx_native';
const CANONICAL_CANDIDATE = 'okx_native_btc_ls_tf_stable_001';
const CANONICAL_SOURCE = 'def signal(bar):\n    return "controlled-canonical"\n';

type ControlledBacktestOptions = {
  backtestDelayMs?: number;
  includeMismatchedPolls?: boolean;
  transportTimeout?: boolean;
  seededRunId?: string;
  seededPayload?: Record<string, unknown>;
};

async function mockControlledBacktestApi(
  page: Parameters<typeof mockBtcTradingPage>[0],
  options: ControlledBacktestOptions = {},
) {
  const calls: Array<{method: string; pathname: string; payload?: Record<string, unknown>}> = [];
  let submitted = false;
  let pollIndex = 0;
  let pollResponses: Record<string, unknown>[] = [];
  const makeBacktest = (runId: string, payload: Record<string, unknown>) => ({
    run_id: runId,
    status: 'completed',
    created_at: '2026-07-14T02:00:00Z',
    completed_at: '2026-07-14T02:01:00Z',
    request: {
      start: payload.start,
      end: payload.end,
      capital: payload.capital,
      data_version: payload.data_version ?? '',
      strategy_id: CANONICAL_STRATEGY,
      candidate_id: CANONICAL_CANDIDATE,
      strategy_version: 'btc_long_short_donchian_top5_okx_native@1.0.0',
      run_id: runId,
    },
    report: {
      summary: {total_return_pct: 12.5, annual_return_pct: 8.2, annual_volatility_pct: 15, sharpe_ratio: 1.4, sortino_ratio: 1.8, max_drawdown_pct: -6.7, calmar_ratio: 1.2, win_rate_pct: 54, profit_factor: 1.35, trade_count: 14},
      chart: {
        equity: [{time: 1, value: 10_000}, {time: 2, value: 11_250}],
        drawdown: [{time: 1, value: 0}, {time: 2, value: -6.7}],
        candles: [
          {time: 1, open: 100, high: 102, low: 99, close: 101, volume: 10},
          {time: 2, open: 101, high: 103, low: 100, close: 102, volume: 11},
        ],
        markers: [],
      },
      strategy_details: [],
      diagnostics: {
        pnl_source: 'ledger_fills',
        ledger_equity_consistent: true,
        monthly_returns: [
          {period: '2026-07', return_pct: 1.25},
          {period: '2026-08', return_pct: 0.85},
        ],
        drawdown_periods: [{duration_bars: 2}],
        execution: {total_fees: 1.2, total_slippage: 0.4, total_cost: 1.6},
      },
      report_scope: 'research_only',
    },
    safety: {paper: false, live: false, order: false, private: false, real_order: false, transfer: false, withdraw: false, demo_start: false},
  });
  let latestBacktest: Record<string, unknown> | null = options.seededRunId
    ? makeBacktest(options.seededRunId, options.seededPayload ?? {
      start: '2026-07-01T00:00:00Z',
      end: '2026-07-31T23:00:00Z',
      capital: 10_000,
      data_version: '',
    })
    : null;
  await page.route('**/api/research/btc/strategy-source/**', async (route) => {
    await route.fulfill({json: {
      strategy_id: CANONICAL_STRATEGY,
      candidate_id: CANONICAL_CANDIDATE,
      source_ref: 'registry://btc/okx-native/canonical.py',
      content_sha256: 'a'.repeat(64),
      content: CANONICAL_SOURCE,
      sections: [{symbol: 'signal', source_ref: 'canonical.signal'}],
      canonical_signal_available: true,
    }});
  });
  await page.route('**/api/research/btc/strategy-versions**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (request.method() === 'GET' && pathname.endsWith('/strategy-versions')) {
      await route.fulfill({json: {versions: []}});
      return;
    }
    if (request.method() === 'GET' && pathname.startsWith('/api/research/btc/strategy-versions/')) {
      calls.push({method: 'GET', pathname});
      const previous = latestBacktest;
      const next = submitted && pollResponses.length
        ? (pollResponses[Math.min(pollIndex++, pollResponses.length - 1)] ?? previous)
        : previous;
      await route.fulfill({json: {
        version_id: 'swv-fixture-001',
        source_sha256: 'a'.repeat(64),
        source_content: CANONICAL_SOURCE,
        execution: {runnable: true, canonical_source_match: true},
        latest_backtest: next,
      }});
      return;
    }
    if (request.method() === 'POST' && pathname.endsWith('/strategy-versions')) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      calls.push({method: 'POST', pathname, payload});
      await route.fulfill({json: {
        version_id: 'swv-fixture-001',
        source_sha256: 'a'.repeat(64),
        source_content: CANONICAL_SOURCE,
        execution: {runnable: true, canonical_source_match: true},
      }});
      return;
    }
    if (request.method() === 'POST' && pathname.endsWith('/backtests')) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      calls.push({method: 'POST', pathname, payload});
      submitted = true;
      const completed = makeBacktest(options.includeMismatchedPolls ? 'run-timeout-001' : 'run-test-001', payload);
      latestBacktest = completed;
      if (options.includeMismatchedPolls) {
        const previous = {...makeBacktest('previous-run-001', payload), status: 'running'};
        const mismatch = {...completed, run_id: 'foreign-run-001', request: {...completed.request, candidate_id: 'foreign-candidate'}};
        pollResponses = [previous, mismatch, completed];
        latestBacktest = previous;
      }
      if (options.transportTimeout) {
        await route.fulfill({status: 408, json: {detail: 'simulated POST transport timeout'}});
        return;
      }
      if (options.backtestDelayMs) await new Promise((resolve) => setTimeout(resolve, options.backtestDelayMs));
      await route.fulfill({json: completed});
      return;
    }
    await route.fallback();
  });
  return calls;
}

test('TradingView strategy tester runs a local ledger backtest and overlays its fills', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await expect(tester).toContainText('多空唐奇安突破 Top5（OKX 原生）');
  await expect(tester.getByRole('button', {name: '运行本地研究回测'})).toBeEnabled();
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  await expect(page.getByRole('dialog', {name: '配置并启动回测'})).toBeVisible();
  await expect(page.getByLabel('杠杆')).toBeDisabled();
  await page.getByRole('button', {name: '确认并启动回测'}).click();

  const progress = page.getByTestId('btc-backtest-progress');
  await expect(progress.getByRole('progressbar')).toBeVisible({timeout: 500});
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuetext', /阶段进度/);
  await expect(progress.getByRole('progressbar')).toHaveAttribute('aria-valuenow', /^(8|20|55|75|92|100)$/);
  await expect(tester).toContainText('12.50%');
  await expect(tester).toContainText('run-test-001');
  await expect(page.getByRole('button', {name: '本地回测成交'})).toBeEnabled();
  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();
  expect(calls.filter((item) => item.pathname.endsWith('/backtests'))).toHaveLength(1);
  expect(calls.filter((item) => item.pathname.endsWith('/strategy-versions'))).toHaveLength(1);
  expect(calls.find((item) => item.pathname.endsWith('/backtests'))?.payload).toMatchObject({capital: 10_000, data_version: ''});
});

test('backtest confirmation exposes main progress before a slow service response', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page, {backtestDelayMs: 2_000});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  const dialog = page.getByRole('dialog', {name: '配置并启动回测'});
  await dialog.getByRole('button', {name: '确认并启动回测'}).click();

  const progress = page.getByTestId('btc-backtest-progress');
  await expect(progress).toBeVisible({timeout: 500});
  await expect(progress).toContainText(/准备|已提交|计算中/);
  await expect(dialog).toBeHidden({timeout: 1_000});
  await expect(progress).toContainText('回测完成', {timeout: 5_000});
  expect(calls.filter((item) => item.method === 'POST' && item.pathname.endsWith('/backtests'))).toHaveLength(1);
});

test('completed backtest focuses results and offers an editor restore action', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  await page.getByRole('dialog', {name: '配置并启动回测'}).getByRole('button', {name: '确认并启动回测'}).click();

  await expect(tester).toContainText('run-test-001');
  await expect(page.getByTestId('btc-backtest-progress')).toContainText('回测完成');
  await expect(tester).toBeInViewport();
  await expect(page.getByTestId('btc-strategy-editor')).toBeHidden();
  const restore = page.getByTestId('btc-backtest-editor-restore');
  await expect(restore).toContainText('策略源码编辑器已收起');
  const callsBeforeRestore = calls.length;
  await restore.getByRole('button', {name: '编辑策略 / 展开编辑器'}).click();
  await expect(page.getByTestId('btc-strategy-editor')).toBeVisible();
  await expect(page.getByRole('button', {name: '运行本地研究回测'})).toBeVisible();
  expect(calls).toHaveLength(callsBeforeRestore);
});

test('completed current run keeps real diagnostics visible and marks closed-trade evidence unavailable', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.getByTestId('btc-strategy-tester');
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  await page.getByRole('dialog', {name: '配置并启动回测'}).getByRole('button', {name: '确认并启动回测'}).click();
  await expect(page.getByTestId('btc-backtest-completed-actions')).toBeVisible();
  await expect(page.getByTestId('btc-backtest-completed-actions')).toContainText('再次回测');
  await expect(page.getByTestId('btc-backtest-completed-actions')).toContainText('选择其他策略');
  await expect(page.getByTestId('btc-monthly-returns-chart')).toBeVisible();
  await expect(page.getByTestId('btc-cost-breakdown-chart')).toBeVisible();
  await expect(tester).toContainText('当前 run 未公开权威闭合 fills/trades');
  await expect(tester).toContainText('research_only_registered_strategy_replay');
  expect(calls.filter((item) => item.method === 'POST' && item.pathname.endsWith('/backtests'))).toHaveLength(1);
});

test('completed backtest stays usable when local history persistence hits quota', async ({page}) => {
  await page.addInitScript(() => {
    const historyKey = 'quantstation.btc.trading-workbench.v2';
    const originalSetItem = Storage.prototype.setItem;
    const browserWindow = window as unknown as {__quantstationHistoryAttempt?: string};
    Storage.prototype.setItem = function setItem(key: string, value: string) {
      if (key === historyKey) {
        browserWindow.__quantstationHistoryAttempt = value;
        throw new DOMException('simulated localStorage quota', 'QuotaExceededError');
      }
      return originalSetItem.call(this, key, value);
    };
  });
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  await page.getByRole('dialog', {name: '配置并启动回测'}).getByRole('button', {name: '确认并启动回测'}).click();

  await expect(tester).toContainText('run-test-001');
  await expect(page.locator('[data-testid="crypto-workspace"]')).toBeVisible();
  await expect(page.getByText('页面渲染出错')).toHaveCount(0);
  await expect(page.locator('.tv-page-message')).toContainText('浏览器存储空间不足');
  expect(calls.filter((item) => item.method === 'POST' && item.pathname.endsWith('/backtests'))).toHaveLength(1);
  const attemptedSnapshot = await page.evaluate(() => {
    const value = (window as unknown as {__quantstationHistoryAttempt?: string}).__quantstationHistoryAttempt;
    return value ? JSON.parse(value) as Array<Record<string, unknown>> : [];
  });
  expect(attemptedSnapshot).toHaveLength(1);
  expect(JSON.stringify(attemptedSnapshot).length).toBeLessThan(2_000);
  expect(attemptedSnapshot[0].chart).toBeUndefined();
  expect((attemptedSnapshot[0].run as Record<string, unknown>).diagnostics).toBeUndefined();
});

test('persisted run restores its report through one identity-checked GET', async ({page}) => {
  const snapshot = [{
    run: {
      run_id: 'run-refresh-001',
      status: 'completed',
      created_at: '2026-07-01T00:00:00Z',
      completed_at: '2026-07-02T00:00:00Z',
      summary: {total_return_pct: 12.5, annual_return_pct: 8.2, annual_volatility_pct: 15, sharpe_ratio: 1.4, sortino_ratio: 1.8, max_drawdown_pct: -6.7, calmar_ratio: 1.2, win_rate_pct: 54, profit_factor: 1.35, trade_count: 14},
    },
    strategyId: CANONICAL_STRATEGY,
    candidateId: CANONICAL_CANDIDATE,
    strategyVersion: 'btc_long_short_donchian_top5_okx_native@1.0.0',
    paramsHash: 'a'.repeat(64),
    savedAt: '2026-07-02T00:00:00Z',
    versionId: 'swv-fixture-001',
    request: {start: '2026-07-01T00:00:00Z', end: '2026-07-31T23:00:00Z', capital: 10_000, dataVersion: ''},
  }];
  await page.addInitScript((value) => {
    localStorage.setItem('quantstation.btc.trading-workbench.v2', JSON.stringify(value));
  }, snapshot);
  await mockBtcTradingPage(page, {signalReady: false, canonicalFreshness: 'stale'});
  const calls = await mockControlledBacktestApi(page, {
    seededRunId: 'run-refresh-001',
    seededPayload: {start: '2026-07-01T00:00:00Z', end: '2026-07-31T23:00:00Z', capital: 10_000, data_version: ''},
  });
  await page.goto(`/crypto?strategy_id=${CANONICAL_STRATEGY}&candidate_id=${CANONICAL_CANDIDATE}&panel=backtest&local_run_id=run-refresh-001`, {waitUntil: 'domcontentloaded'});

  await expect(page.locator('[data-testid="btc-strategy-tester"]')).toContainText('run-refresh-001');
  expect(calls.filter((item) => item.method === 'POST' && item.pathname.endsWith('/backtests'))).toHaveLength(0);
  const identityGets = calls.filter((item) => item.method === 'GET' && item.pathname.endsWith('/strategy-versions/swv-fixture-001'));
  expect(identityGets.length).toBeGreaterThanOrEqual(1);
  expect(new Set(identityGets.map((item) => item.pathname)).size).toBe(1);
});

test('research-only backtest is independent from Demo completed-1h freshness', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: false, canonicalFreshness: 'stale'});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  const runButton = tester.getByRole('button', {name: '运行本地研究回测'});
  await expect(runButton).toBeEnabled();
  await runButton.click();
  await expect(page.getByRole('dialog', {name: '配置并启动回测'})).toBeVisible();
  expect(calls).toHaveLength(0);
});

test('backtest POST timeout settles one matching new run through GET-only polling', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: false, canonicalFreshness: 'stale'});
  const calls = await mockControlledBacktestApi(page, {transportTimeout: true, includeMismatchedPolls: true});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});

  const tester = page.locator('[data-testid="btc-strategy-tester"]');
  await tester.getByRole('button', {name: '运行本地研究回测'}).click();
  const dialog = page.getByRole('dialog', {name: '配置并启动回测'});
  await dialog.getByRole('button', {name: '确认并启动回测'}).click();
  await expect(page.getByText('后端仍在计算，正在只读确认结果', {exact: false})).toBeVisible({timeout: 25_000});
  await expect(page.getByTestId('btc-backtest-progress')).toContainText('回测完成', {timeout: 35_000});
  await expect(tester).toContainText('run-timeout-');
  expect(calls.filter((item) => item.method === 'POST' && item.pathname.endsWith('/backtests'))).toHaveLength(1);
  expect(calls.filter((item) => item.method === 'GET' && item.pathname.includes('/strategy-versions/'))).toHaveLength(4);
});

test('edited crypto strategy draft remains local and fail-closed before any controlled backtest POST', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  const calls = await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  const editor = page.getByTestId('btc-strategy-editor');
  const source = editor.getByLabel('本机研究草稿源码');
  await source.fill(`${CANONICAL_SOURCE}\n# local research note`);
  await expect(editor).toContainText('先重置到已注册源码');
  await expect(editor.getByRole('button', {name: '运行本地研究回测'})).toBeDisabled();
  expect(calls).toHaveLength(0);
});

test('crypto strategy tester keeps the bottom tabs in normal flow', async ({page}) => {
  await mockBtcTradingPage(page, {signalReady: true});
  await mockControlledBacktestApi(page);
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await expect(page.locator('.tv-bottom-tabs')).toHaveCSS('position', 'static');
});

test('TradingView BTC workbench remains usable at mobile width and 200 percent zoom', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockBtcTradingPage(page, {signalReady: true, runtimeBlockers: ['runtime_non_empty_fill_sample_missing']});
  await page.goto('/crypto', {waitUntil: 'domcontentloaded'});
  await page.evaluate(() => { document.documentElement.style.zoom = '2'; });

  const workspace = page.locator('[data-testid="crypto-workspace"]');
  await expect(page.locator('[data-testid="btc-trading-chart"] canvas').first()).toBeVisible();
  await expect(page.locator('[data-testid="btc-demo-console"]')).toContainText('completed 1h 信号（图表 / 历史提示）PASS');
  const widths = await workspace.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    sections: [...element.children].map((node) => ({
      className: node.className,
      clientWidth: (node as HTMLElement).clientWidth,
      scrollWidth: (node as HTMLElement).scrollWidth,
    })),
  }));
  const nonReportSections = widths.sections.filter((section) => !section.className.split(/\s+/).includes('panel'));
  expect(nonReportSections.every((section) => section.scrollWidth <= section.clientWidth + 1), JSON.stringify(widths, null, 2)).toBe(true);
});
