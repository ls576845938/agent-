import {createHash} from 'node:crypto';
import {expect, test, type Page, type Route} from '@playwright/test';
import {mockBtcTradingPage, strategyHistoryFixture} from './btc-trading-fixtures';

test.use({viewport: {width: 1131, height: 975}});
const sourcePattern = '**/api/research/btc/strategy-source/**';
function sourceFor(route: Route) {
  const [strategyId, candidateId] = new URL(route.request().url()).pathname.split('/').slice(-2).map(decodeURIComponent);
  const content = 'def registered_signal(frame):\n    return frame.close * 0';
  const digest = createHash('sha256').update(content).digest('hex');
  return {strategy_id: strategyId, candidate_id: candidateId, source_ref: 'quant_crypto/application/btc_strategy_registry.py', canonical_signal_available: true, content, content_sha256: digest, sections: [{symbol: 'registered_signal', source_ref: 'registry.py', content, content_sha256: digest}], safety: {paper: false, live: false, order: false, private: false, real_order: false}};
}
async function mockPage(page: Page) {
  const state = await mockBtcTradingPage(page);
  await page.route('**/api/research/btc/strategy-versions?*', route => route.fulfill({json: {versions: [], safety: {paper: false, live: false, private: false, order: false}}}));
  await page.route(sourcePattern, route => route.fulfill({json: sourceFor(route)}));
  return state;
}

test('cold load and reload resolve unknown catalog capability without clicking the tree', async ({page}) => {
  await mockPage(page);
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-workbench-source-editor')).toBeVisible();
  expect(await page.locator('.strategy-workbench-filetab').evaluate(element => element.getBoundingClientRect().height)).toBeLessThan(120);
  await page.reload();
  await expect(page.getByLabel('本机研究草稿源码')).toHaveValue(/registered_signal/);
  await expect(page.getByTestId('strategy-new-backtest-source')).toContainText('本机 SQLite');
  await expect(page.getByLabel('回测开始时间')).toBeVisible();
  await expect(page.getByRole('button', {name: '运行已注册策略回测', exact: true})).toBeDisabled();
});

test('409 source failure remains closed but an explicit retry can recover', async ({page}) => {
  await mockPage(page);
  let fail = true;
  await page.route(sourcePattern, route => fail ? route.fulfill({status: 409, json: {detail: 'identity-only source unavailable'}}) : route.fulfill({json: sourceFor(route)}));
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-workbench-source-unavailable')).toBeVisible();
  await expect(page.getByTestId('strategy-workbench-source-editor')).toHaveCount(0);
  fail = false;
  await page.getByRole('button', {name: '重新读取源码', exact: true}).click();
  await expect(page.getByTestId('strategy-workbench-source-editor')).toBeVisible();
});

for (const failure of ['identity', 'digest', 'permission']) test(`source rejects wrong ${failure}`, async ({page}) => {
  await mockPage(page);
  await page.route(sourcePattern, route => {
    const value = sourceFor(route);
    if (failure === 'identity') value.candidate_id = 'wrong';
    if (failure === 'digest') value.content_sha256 = 'f'.repeat(64);
    if (failure === 'permission') value.safety.private = true;
    return route.fulfill({json: value});
  });
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-workbench-source-unavailable')).toContainText('校验失败');
  await expect(page.getByTestId('strategy-workbench-source-editor')).toHaveCount(0);
});

test('explicit false skips source GET and late previous response cannot restore its editor', async ({page}) => {
  await mockPage(page);
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  let calls = 0;
  await page.route(sourcePattern, async route => { calls += 1; await delayed; await route.fulfill({json: sourceFor(route)}); });
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-source-loading')).toBeVisible();
  await page.getByTestId('strategy-tree-btc-btc_high_octane_v1-identity-high-octane').click();
  const before = calls;
  release();
  await expect(page.getByTestId('strategy-workbench-source-unavailable')).toContainText('没有可执行 canonical 源码');
  await expect(page.getByTestId('strategy-workbench-source-editor')).toHaveCount(0);
  expect(calls).toBe(before);
});

test('historical provenance, real aggregate output and chart-only window are separate', async ({page}) => {
  const state = await mockPage(page);
  await page.route('**/api/research/btc/strategy-history/*/*', route => {
    const [strategy, candidate] = new URL(route.request().url()).pathname.split('/').slice(-2).map(decodeURIComponent);
    const history = strategyHistoryFixture(strategy, candidate);
    history.source.data = {...history.source.data, source_interval: '1h', decision_interval: '4h', bar_4h_start: '2024-01-01T03:59:59.999Z', bar_4h_end: '2026-06-28T23:59:59.999Z'} as typeof history.source.data;
    return route.fulfill({json: history});
  });
  await page.route('**/api/runs/*/chart', route => route.fulfill({status: 404, json: {detail: 'not published'}}));
  await page.route('**/api/research/btc/demo-paper/klines?*', route => route.fulfill({json: {
    read_only: true, source_kind: 'okx_reference', sample_end: '2024-01-03T13:00:00Z', freshness_status: 'stale',
    rows: [1, 2, 3].map(day => ({exchange: 'okx_swap', symbol: 'BTC-USDT-SWAP', interval: '1h', open_time_ms: Date.parse(`2024-01-0${day}T12:00:00Z`), open: 100, high: 101, low: 99, close: 100, volume: 1})),
  }}));
  await page.goto('/strategies');
  const provenance = page.getByTestId('strategy-history-provenance');
  await expect(provenance).toContainText('Binance 现货');
  await expect(provenance).toContainText('1h → 4h');
  await expect(provenance).toContainText('2026-06-28');
  await expect(page.getByTestId('strategy-history-missing-series')).toContainText('不是页面还在等待输出');
  await expect(page.getByTestId('strategy-published-output')).toContainText('37.18%');
  await expect(page.getByTestId('strategy-marker-alignment')).toContainText('参考行情不叠加历史成交');
  const metrics = await page.locator('.strategy-workbench-performance-body > .strategy-workbench-kpis').innerText();
  await expect(page.getByTestId('strategy-chart-window')).toContainText('当前显示 3 根');
  const reads = state.requests.length;
  await page.getByLabel('K线显示开始', {exact: true}).fill('2024-01-02');
  await page.getByLabel('K线显示结束', {exact: true}).fill('2024-01-02');
  await expect(page.getByTestId('strategy-chart-window')).toContainText('当前显示 1 根');
  await expect(page.locator('.strategy-workbench-performance-body > .strategy-workbench-kpis')).toHaveText(metrics, {useInnerText: true});
  await page.getByLabel('K线显示开始', {exact: true}).fill('2030-01-01');
  await expect(page.getByTestId('strategy-chart-window')).toContainText('当前显示 0 根');
  await expect(page.getByTestId('strategy-workbench-candle')).toHaveCount(0);
  expect(state.requests.length).toBe(reads);
  expect(state.requests.filter(item => item.method === 'POST')).toEqual([]);
});

test('partial series stays explicit; complete published equity and drawdown render', async ({page}) => {
  await mockPage(page);
  let complete = false;
  await page.route('**/api/research/btc/strategy-history/*/*', route => {
    const [strategy, candidate] = new URL(route.request().url()).pathname.split('/').slice(-2).map(decodeURIComponent);
    const history = strategyHistoryFixture(strategy, candidate);
    history.canonical_report.series.equity = [{time: 1704110400, value: 100}, {time: 1704196800, value: 101}];
    if (complete) history.canonical_report.series.drawdown = [{time: 1704110400, value: 0}, {time: 1704196800, value: 0}];
    return route.fulfill({json: history});
  });
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-history-missing-series')).toContainText('尚未发布：连续回撤');
  await expect(page.getByTestId('strategy-workbench-equity-panel')).toHaveCount(0);
  complete = true;
  await page.reload();
  await expect(page.getByTestId('strategy-workbench-equity-panel')).toBeVisible();
  await expect(page.getByTestId('strategy-history-missing-series')).toContainText('月度收益序列、完整成交账本、现金成本分项');
});

test('new backtest dates use the existing allowlisted payload and do not replace historical metrics', async ({page}) => {
  await mockPage(page);
  const posts: Array<{path: string; payload: Record<string, unknown>}> = [];
  await page.route('**/api/research/btc/strategy-versions', route => {
    const payload = route.request().postDataJSON();
    posts.push({path: new URL(route.request().url()).pathname, payload});
    return route.fulfill({json: {version_id: 'swv_test', label: 'test', source_content: payload.source_content, source_sha256: payload.base_source_sha256, execution: {runnable: true, canonical_source_match: true, blocker: ''}, latest_backtest: null, approved_research_only: false, selected_runnable_candidate: false, selection_scope: ''}});
  });
  await page.route('**/api/research/btc/strategy-versions/swv_test/backtests', route => {
    posts.push({path: new URL(route.request().url()).pathname, payload: route.request().postDataJSON()});
    return route.fulfill({json: {run_id: 'swr_test', status: 'completed', error: '', report: {summary: {total_return: 0.01}, chart: {}, report_scope: 'research_only_registered_strategy_replay'}}});
  });
  await page.goto('/strategies');
  await expect(page.getByTestId('strategy-workbench-source-editor')).toBeVisible();
  await expect(page.getByTestId('strategy-history-provenance')).toBeVisible();
  const metrics = await page.locator('.strategy-workbench-performance-body > .strategy-workbench-kpis').innerText();
  await page.getByRole('button', {name: '保存为不可变研究版本', exact: true}).click();
  await page.getByLabel('回测开始时间', {exact: true}).fill('2024-02-01T00:00:00Z');
  await page.getByLabel('回测结束时间', {exact: true}).fill('2024-03-01T00:00:00Z');
  await page.getByRole('button', {name: '运行已注册策略回测', exact: true}).click();
  await expect(page.getByTestId('strategy-workbench-version-report')).toContainText('completed');
  expect(posts).toHaveLength(2);
  expect(posts[1].payload).toEqual({start: '2024-02-01T00:00:00Z', end: '2024-03-01T00:00:00Z', capital: 100000, data_version: ''});
  await expect(page.locator('.strategy-workbench-performance-body > .strategy-workbench-kpis')).toHaveText(metrics, {useInnerText: true});
  await expect(page.locator('.strategy-workbench-safety')).toContainText('ORDER / PAPER / LIVE = FALSE');
});
