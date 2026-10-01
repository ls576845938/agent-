import {expect, test} from '@playwright/test';

import {mockBtcTradingPage, strategyHistoryFixture} from './btc-trading-fixtures';

const candidate = 'btc_ls_tf_stable_001';
const strategy = 'long_short_donchian_top5';

test.describe('strategy workbench PTrade fidelity', () => {
  test('renders a dense three-panel chart workspace from GET-only published evidence', async ({page}) => {
    const mock = await mockBtcTradingPage(page);
    await mockPublishedHistory(page);
    await mockStrategySource(page);
    await page.route('**/api/runs/**/chart', async (route) => route.fulfill({json: publishedChart()}));
    await page.setViewportSize({width: 1440, height: 960});
    await page.goto('/strategies', {waitUntil: 'domcontentloaded'});

    await page.getByTestId(`strategy-tree-btc-${strategy}-${candidate}`).click();
    const workbench = page.getByTestId('strategy-workbench');
    await expect(workbench).toBeVisible();
    const terminalVisual = await workbench.evaluate((element) => {
      const root = getComputedStyle(element);
      const title = element.querySelector('.strategy-workbench-pane-title');
      const splitter = element.querySelector('.strategy-workbench-splitter.vertical');
      return {
        canvas: root.getPropertyValue('--swb-canvas').trim(),
        border: root.getPropertyValue('--swb-border').trim(),
        accent: root.getPropertyValue('--swb-accent').trim(),
        titleHeight: title ? getComputedStyle(title).minHeight : '',
        splitterWidth: splitter ? getComputedStyle(splitter).width : '',
        splitterMark: splitter ? getComputedStyle(splitter, '::after').backgroundColor : '',
      };
    });
    expect(terminalVisual).toEqual({
      canvas: '#080d15', border: '#29364a', accent: '#5b9cff',
      titleHeight: '38px', splitterWidth: '6px', splitterMark: 'rgb(104, 128, 159)',
    });
    await expect(page.getByRole('separator')).toHaveCount(3);
    await expect(page.getByRole('heading', {name: '策略代码 / 本机研究草稿'})).toHaveCount(0);
    await expect(page.getByText('策略代码 / 本机研究草稿')).toBeVisible();
    await expect(page.getByText('策略定义 / 只读源码')).toHaveCount(0);
    await expect(page.getByTestId('strategy-workbench-report')).toBeVisible();
    await expect(page.getByTestId('strategy-workbench-source-editor')).toBeVisible();
    await expect(page.getByLabel('本机研究草稿源码')).toBeEditable();
    await expect(page.getByLabel('本机研究草稿源码')).toContainText('def generate_top5_signal');
    await expect(page.getByTestId('strategy-workbench-source-editor')).toContainText('_signal_symmetric_donchian');
    const codeSurface = await page.locator('.strategy-workbench-code-surface').boundingBox();
    expect(codeSurface?.height ?? 0).toBeGreaterThanOrEqual(300);
    await expect(page.locator('.strategy-workbench-source-editor button').nth(0)).toBeVisible();
    await expect(page.locator('.strategy-workbench-source-editor button').nth(1)).toBeVisible();
    const treeGroupBoxes = await page.locator('[data-testid="strategy-discovery-catalog"] .strategy-workbench-tree-groups > .strategy-workbench-tree-group').evaluateAll((groups) => groups.map((group) => { const box = group.getBoundingClientRect(); return {top: box.top, bottom: box.bottom}; }));
    expect(treeGroupBoxes.every((box, index) => index === 0 || box.top >= treeGroupBoxes[index - 1].bottom - 1)).toBe(true);
    const selectedItem = page.getByTestId(`strategy-tree-btc-${strategy}-${candidate}`);
    await expect(selectedItem.locator('strong')).toContainText('多空唐奇安突破 Top5');
    const selectedText = await selectedItem.locator('strong').evaluate((element) => ({text: element.textContent || '', clipped: element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).whiteSpace === 'nowrap'}));
    expect(selectedText.text).toContain('多空唐奇安突破 Top5');
    expect(selectedText.clipped).toBe(false);
    await expect(page.getByTestId('strategy-workbench-candle').locator('canvas').first()).toBeVisible();
    await expect(page.getByTestId('strategy-marker-alignment')).toContainText('canonical 交易 2/2 · 历史复核 0/2');
    await expect(page.getByTestId('strategy-marker-alignment')).not.toContainText('已发布标记 2/2');
    await expect(page.getByTestId('strategy-workbench-market-indicators')).toContainText('Donchian · 成交量未发布');
    await expect(page.getByTestId('strategy-workbench-market-source')).toContainText('published_run_chart');
    await expect(page.getByTestId('strategy-workbench-run-table')).toBeVisible();
    const dockInside = await workbench.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const dock = element.querySelector('.strategy-workbench-dock')?.getBoundingClientRect();
      return Boolean(dock && dock.bottom <= box.bottom + 1 && dock.top >= box.top);
    });
    expect(dockInside).toBe(true);
    const leftValue = await workbench.evaluate((element) => getComputedStyle(element).getPropertyValue('--strategy-left').trim());
    expect(leftValue).toBe('18%');
    const panelsInside = await page.evaluate(() => Object.fromEntries([
      ['candle', '[data-testid="strategy-workbench-candle"]'],
      ['equity', '[data-testid="btc-equity-chart"]'],
      ['tradePnl', '[data-testid="btc-trade-pnl-chart"]'],
      ['cost', '[data-testid="btc-cost-breakdown-chart"]'],
      ['dock', '.strategy-workbench-dock'],
    ].map(([name, selector]) => {
      const box = document.querySelector(selector)?.getBoundingClientRect();
      return [name, Boolean(box && box.top >= 0 && box.bottom <= window.innerHeight)];
    })));
    expect(panelsInside).toEqual({candle: true, equity: true, tradePnl: true, cost: true, dock: true});
    const paneLayout = await page.evaluate(() => {
      const pane = document.querySelector('.strategy-workbench-performance')?.getBoundingClientRect();
      const dock = document.querySelector('.strategy-workbench-dock')?.getBoundingClientRect();
      const boxes = ['.strategy-workbench-kpis', '[data-testid="strategy-workbench-market"]', '[data-testid="btc-equity-chart"]', '.strategy-workbench-dock-body', '[data-testid="strategy-workbench-run-table"]'].map((selector) => document.querySelector(selector)?.getBoundingClientRect());
      const inside = (box: DOMRect | undefined, parent: DOMRect | undefined) => Boolean(box && parent && box.top >= parent.top - 1 && box.bottom <= parent.bottom + 1 && box.left >= parent.left - 1 && box.right <= parent.right + 1);
      return {kpis: inside(boxes[0], pane), market: inside(boxes[1], pane), equity: inside(boxes[2], pane), dock: inside(boxes[3], dock), dockRow: inside(boxes[4], dock)};
    });
    expect(paneLayout).toEqual({kpis: true, market: true, equity: true, dock: true, dockRow: true});
    expect(mock.requests.filter((item) => item.method !== 'GET')).toEqual([]);
    await expect(page.getByText(/ORDER \/ PAPER \/ LIVE = FALSE/)).toBeVisible();
    await page.getByRole('tab', {name: '绩效指标'}).click();
    await expect(page.getByTestId('btc-historical-performance-details')).toBeVisible();
    await page.getByRole('tab', {name: '交易明细'}).click();
    await expect(page.getByTestId('btc-historical-trade-review')).toBeVisible();
    await expect(page.getByRole('button', {name: /启动|下单|撤单|执行/i})).toHaveCount(0);
  });

  test('persists keyboard splitter changes and updates the selected run view', async ({page}) => {
    await mockBtcTradingPage(page);
    await mockPublishedHistory(page);
    await mockStrategySource(page);
    await page.route('**/api/runs/**/chart', async (route) => route.fulfill({json: publishedChart()}));
    await page.setViewportSize({width: 1440, height: 900});
    await page.addInitScript(() => localStorage.setItem('quantstation.strategy-workbench-layout.v1', JSON.stringify({left: 18, code: 41, dock: 220})));
    await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
    await page.getByTestId(`strategy-tree-btc-${strategy}-${candidate}`).click();
    const codeSurface = await page.locator('.strategy-workbench-code-surface').boundingBox();
    expect(codeSurface?.height ?? 0).toBeGreaterThanOrEqual(300);
    await expect(page.locator('.strategy-workbench-source-editor button').nth(0)).toBeVisible();
    await expect(page.locator('.strategy-workbench-source-editor button').nth(1)).toBeVisible();

    const firstSplitter = page.getByRole('separator', {name: '调整目录与策略定义宽度'});
    await firstSplitter.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => page.getByTestId('strategy-workbench').evaluate((element) => getComputedStyle(element).getPropertyValue('--strategy-left').trim())).toBe('19%');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('quantstation.strategy-workbench-layout.v1'))).toContain('"left":19');
    await page.getByLabel('本机研究草稿源码').fill('def generate_top5_signal():\n    return 1\n# local note');
    await page.getByRole('button', {name: '保存本机草稿'}).click();
    await page.reload({waitUntil: 'domcontentloaded'});
    await expect(page.getByLabel('本机研究草稿源码')).toContainText('# local note');
    await page.getByRole('button', {name: '重置到 current source'}).click();
    await expect(page.getByLabel('本机研究草稿源码')).not.toContainText('# local note');
    await expect(page.getByTestId('strategy-workbench-report')).toBeVisible();
    await expect(page.getByTestId('btc-equity-chart')).toBeVisible();
    await page.setViewportSize({width: 1180, height: 900});
    await page.waitForTimeout(250);
    const rootBox = await page.getByTestId('strategy-workbench').boundingBox();
    const catalogBox = await page.locator('.strategy-workbench-catalog').boundingBox();
    const codeBox = await page.locator('.strategy-workbench-code').boundingBox();
    const performanceBox = await page.locator('.strategy-workbench-performance').boundingBox();
    expect(rootBox && catalogBox && codeBox && performanceBox).toBeTruthy();
    if (rootBox && catalogBox && codeBox && performanceBox) {
      expect(catalogBox.x).toBeGreaterThanOrEqual(rootBox.x);
      expect(catalogBox.x + catalogBox.width).toBeLessThanOrEqual(codeBox.x);
      expect(codeBox.x + codeBox.width).toBeLessThanOrEqual(performanceBox.x);
      expect(performanceBox.x + performanceBox.width).toBeLessThanOrEqual(rootBox.x + rootBox.width + 1);
    }
    const mediumPaneLayout = await page.evaluate(() => {
      const pane = document.querySelector('.strategy-workbench-performance')?.getBoundingClientRect();
      const dock = document.querySelector('.strategy-workbench-dock')?.getBoundingClientRect();
      const boxes = ['.strategy-workbench-kpis', '[data-testid="strategy-workbench-market"]', '[data-testid="btc-equity-chart"]', '.strategy-workbench-dock-body', '[data-testid="strategy-workbench-run-table"]'].map((selector) => document.querySelector(selector)?.getBoundingClientRect());
      const inside = (box: DOMRect | undefined, parent: DOMRect | undefined) => Boolean(box && parent && box.top >= parent.top - 1 && box.bottom <= parent.bottom + 1 && box.left >= parent.left - 1 && box.right <= parent.right + 1);
      return {kpis: inside(boxes[0], pane), market: inside(boxes[1], pane), equity: inside(boxes[2], pane), dock: inside(boxes[3], dock), dockRow: inside(boxes[4], dock)};
    });
    expect(mediumPaneLayout).toEqual({kpis: true, market: true, equity: true, dock: true, dockRow: true});
    await page.getByRole('tab', {name: '交易明细'}).click();
    await expect(page.getByTestId('strategy-workbench-trade-table')).toBeVisible();
    await page.getByRole('button', {name: '折叠底部信息栏'}).click();
    await expect(page.getByRole('button', {name: '展开底部信息栏'})).toBeVisible();
  });

  test('keeps missing chart, stale fallback, and unaligned trades explicit', async ({page}) => {
    await mockBtcTradingPage(page);
    await mockStrategySource(page, 409);
    const observed503Paths: string[] = [];
    await page.route('**/api/runs/**/chart', async (route) => {
      observed503Paths.push(new URL(route.request().url()).pathname);
      return route.fulfill({status: 503, json: {detail: 'chart unavailable'}});
    });
    await page.route('**/api/research/btc/demo-paper/klines**', async (route) => {
      observed503Paths.push(new URL(route.request().url()).pathname);
      return route.fulfill({status: 503, json: {detail: 'completed bar unavailable'}});
    });
    await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
    await page.getByTestId(`strategy-tree-btc-${strategy}-${candidate}`).click();

    await expect(page.getByText('K 线未发布')).toBeVisible();
    await expect(page.getByTestId('strategy-workbench-market-indicators')).toContainText('Donchian 数据不足 · 成交量未发布');
    await expect(page.getByTestId('strategy-marker-alignment')).toContainText('已发布标记未发布');
    await expect(page.getByTestId('strategy-workbench-source-unavailable')).toContainText('HTTP 409');
    await expect(page.getByText(/不会补造 K 线、指标或交易标记/)).toBeVisible();
    await expect.poll(() => observed503Paths).toEqual(expect.arrayContaining([
      expect.stringMatching(/^\/api\/runs\/.+\/chart$/),
      '/api/research/btc/demo-paper/klines',
    ]));
    await page.getByRole('tab', {name: '日志'}).click();
    await expect(page.getByTestId('strategy-workbench-log-unavailable')).toContainText('不能冒充日志');
    await expect(page.getByRole('button', {name: /启动|下单|撤单|执行/i})).toHaveCount(0);
  });
  test('persists a research version and only runs the registered canonical replay', async ({page}) => {
    await mockBtcTradingPage(page);
    await mockPublishedHistory(page);
    await mockStrategySource(page);
    const calls = await mockStrategyVersions(page);
    await page.route('**/api/runs/**/chart', async (route) => route.fulfill({json: publishedChart()}));
    await page.goto('/strategies', {waitUntil: 'domcontentloaded'});
    await page.getByTestId(`strategy-tree-btc-${strategy}-${candidate}`).click();

    await page.getByRole('button', {name: '保存为不可变研究版本'}).click();
    await expect(page.getByText('CANONICAL SOURCE MATCH · RUNNABLE')).toBeVisible();
    await page.reload({waitUntil: 'domcontentloaded'});
    await expect(page.getByText('CANONICAL SOURCE MATCH · RUNNABLE')).toBeVisible();
    await page.getByRole('button', {name: '运行已注册策略回测'}).click();
    await expect(page.getByTestId('strategy-workbench-version-report')).toContainText('completed');
    await page.getByRole('button', {name: '批准 research-only 候选'}).click();
    await page.getByRole('button', {name: '选择可运行候选'}).click();
    await expect(page.getByText('已选择为后续 Demo 读取候选；Demo 未启动。')).toBeVisible();

    expect(calls.map((call) => call.path)).toEqual([
      '/api/research/btc/strategy-versions',
      '/api/research/btc/strategy-versions/swv_fixture_0001/backtests',
      '/api/research/btc/strategy-versions/swv_fixture_0001/approve',
      '/api/research/btc/strategy-versions/swv_fixture_0001/select-runnable',
    ]);
    expect(calls.every((call) => call.body.source_content === undefined || call.path === '/api/research/btc/strategy-versions')).toBe(true);
    await expect(page.getByRole('button', {name: /启动|下单|撤单|Demo/i})).toHaveCount(0);
  });
});

function publishedChart() {
  const start = Math.floor(Date.UTC(2026, 3, 14, 8) / 1000);
  const candles = Array.from({length: 168}, (_, index) => ({
    time: start + index * 3600,
    open: 72_000 + index * 10,
    high: 72_060 + index * 10,
    low: 71_940 + index * 10,
    close: 72_020 + index * 10,
  }));
  return {
    candles,
    markers: [
      {time: candles[108].time, position: 'belowBar', color: '#22c55e', shape: 'arrowUp', text: 'published BUY'},
      {time: candles[144].time, position: 'aboveBar', color: '#ef4444', shape: 'arrowDown', text: 'published SELL'},
    ],
    equity: candles.map((candle, index) => ({time: candle.time, value: 10_000 + index * 10})),
    drawdown: candles.map((candle, index) => ({time: candle.time, value: -index / 20})),
    exposure: [], net_units: [], turnover: [], leverage: [],
  };
}

async function mockPublishedHistory(page: Parameters<typeof mockBtcTradingPage>[0]) {
  await page.route(`**/api/research/btc/strategy-history/${strategy}/${candidate}**`, async (route) => {
    const chart = publishedChart();
    const payload = strategyHistoryFixture(strategy, candidate);
    payload.canonical_report.series = {
      equity: chart.equity,
      drawdown: chart.drawdown,
      monthly_returns: [],
      trades: [{trade_number: 1, direction: 'long', entry_time: chart.candles[108].time, exit_time: chart.candles[144].time, entry_price: chart.candles[108].close, exit_price: chart.candles[144].close, quantity: 0.01, gross_pnl: 12, commission: 1, funding_cashflow: 0, net_pnl: 11, cumulative_pnl: 11, return_pct: 1, duration_bars: 36}],
      costs: [{key: 'commission', label: '手续费', value: 1}, {key: 'funding', label: 'Funding', value: 0.1}],
    };
    return route.fulfill({json: payload});
  });
}

async function mockStrategySource(page: Parameters<typeof mockBtcTradingPage>[0], status = 200) {
  await page.route('**/api/research/btc/strategy-source/**', async (route) => {
    if (status !== 200 || !route.request().url().includes(`/${strategy}/${candidate}`)) return route.fulfill({status: 409, json: {detail: 'canonical strategy source unavailable'}});
    const signal = 'def generate_top5_signal(frame, interval):\n    return raw_long_short_trend_signal(frame)';
    const helper = 'def raw_long_short_trend_signal(frame):\n    return frame';
    const donchian = 'def _signal_symmetric_donchian(params):\n    return high.shift(1).rolling(int(params["entry_window"])).max(), low.shift(1).rolling(int(params["exit_window"])).min()';
    return route.fulfill({json: {
      strategy_id: strategy,
      candidate_id: candidate,
      source_ref: 'quant_crypto/application/btc_strategy_registry.py',
      content_sha256: 'a'.repeat(64),
      content: `${signal}\n\n${helper}\n\n${donchian}`,
      canonical_signal_available: true,
      sections: [
        {symbol: 'generate_top5_signal', source_ref: 'quant_crypto/application/btc_strategy_registry.py', content: signal, content_sha256: 'b'.repeat(64)},
        {symbol: 'raw_long_short_trend_signal', source_ref: 'quant_crypto/research/long_short_trend_following_lab.py', content: helper, content_sha256: 'c'.repeat(64)},
        {symbol: '_signal_symmetric_donchian', source_ref: 'quant_crypto/research/long_short_trend_following_lab.py', content: donchian, content_sha256: 'd'.repeat(64)},
      ],
    }});
  });
}

async function mockStrategyVersions(page: Parameters<typeof mockBtcTradingPage>[0]) {
  type Call = {path: string; body: Record<string, unknown>};
  type MockVersion = {
    version_id: string; created_at: string; strategy_id: string; candidate_id: string; strategy_version: string; label: string;
    base_source_sha256: string; source_sha256: string; source_content: string;
    execution: {canonical_source_match: boolean; allowlisted_runner_only: boolean; arbitrary_python_execution: boolean; runnable: boolean; blocker: string};
    latest_backtest: null | {run_id: string; status: string; error: string; report: {summary: Record<string, number>; chart: {equity: Array<{time: number; value: number}>; drawdown: Array<{time: number; value: number}>}; strategy_details: unknown[]}; safety: Record<string, boolean>};
    approved_research_only: boolean; selected_runnable_candidate: boolean; selection_scope: string; safety: Record<string, boolean>;
  };
  const calls: Call[] = [];
  let version: MockVersion | null = null;
  const safety = {paper: false, live: false, order: false, private: false, real_order: false, transfer: false, withdraw: false, demo_start: false};
  const projection = () => version || null;
  await page.route('**/api/research/btc/strategy-versions**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET') {
      if (path.endsWith('/strategy-versions')) return route.fulfill({json: {versions: version ? [projection()] : [], selected_version_id: version?.selected_runnable_candidate ? version.version_id : '', safety}});
      return route.fulfill({json: projection() || {detail: 'version unavailable'}, status: version ? 200 : 404});
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    calls.push({path, body});
    if (path.endsWith('/strategy-versions')) {
      version = {
        version_id: 'swv_fixture_0001', created_at: '2026-08-14T00:00:00Z', strategy_id: strategy, candidate_id: candidate,
        strategy_version: 'fixture', label: String(body.label || ''), base_source_sha256: 'a'.repeat(64), source_sha256: 'a'.repeat(64), source_content: String(body.source_content || ''),
        execution: {canonical_source_match: true, allowlisted_runner_only: true, arbitrary_python_execution: false, runnable: true, blocker: ''},
        latest_backtest: null, approved_research_only: false, selected_runnable_candidate: false, selection_scope: '', safety,
      };
    } else if (path.endsWith('/backtests') && version) {
      version = {...version, latest_backtest: {run_id: 'swr_fixture_0001', status: 'completed', error: '', report: {summary: {total_return_pct: 10, annual_return_pct: 8, max_drawdown_pct: -4, sharpe_ratio: 1.2, trade_count: 8}, chart: {equity: [{time: 1, value: 100}], drawdown: [{time: 1, value: 0}]}, strategy_details: []}, safety}};
      return route.fulfill({json: version.latest_backtest});
    } else if (path.endsWith('/approve') && version) {
      version = {...version, approved_research_only: true};
    } else if (path.endsWith('/select-runnable') && version) {
      version = {...version, selected_runnable_candidate: true, selection_scope: 'future_demo_reader_requires_separate_runtime_admission'};
    }
    return route.fulfill({json: projection()});
  });
  return calls;
}
