import {expect, test} from '@playwright/test';
import {mockBtcTradingPage} from './btc-trading-fixtures';

test.use({viewport: {width: 1131, height: 975}});

function parameterFixture() {
  return {
    strategy_id: 'long_short_donchian_top5', status: 'historical_research_only', evidence_sha256: 'c'.repeat(64), relationship: '历史研究参数搜索',
    coverage: {published_count: 3, declared_count: 3, selection: 'all_published_long_short_rows_not_top5'},
    source: {report_sha256: 'a'.repeat(64), code_commit: 'b'.repeat(40), generated_at: '2026-06-30', sample: 'full_research_window_already_used_for_selection', freshness: 'historical_not_current_head', data: {exchange: 'binance_spot', symbol: 'BTCUSDT', base_decision_interval: '4h', bar_4h_start: '2024-01-01', bar_4h_end: '2026-06-29'}, cost_model: {base_cost_bps: 10}, execution_rule: 'next bar'},
    safety: {paper: false, live: false, private: false, order: false, promotion: false},
    rows: [
      {candidate_id: 'a', family: 'dual-ma', params: {fast_window: 10, slow_window: 60, fee: 10}, metrics: {sharpe_ratio: 1.12, annual_return_pct: 18.4, max_drawdown_pct: -14.7, sortino_ratio: 1.56}},
      {candidate_id: 'b', family: 'dual-ma', params: {fast_window: 20, slow_window: 60, fee: 10}, metrics: {sharpe_ratio: 0, annual_return_pct: 0, max_drawdown_pct: 0, sortino_ratio: null}},
      {candidate_id: 'c', family: 'dual-ma', params: {fast_window: 10, slow_window: 80, fee: 10}, metrics: {sharpe_ratio: -0.4, annual_return_pct: -8, max_drawdown_pct: -24, sortino_ratio: -0.5}},
    ],
  };
}

test('alpha and maturity filters intersect; alpha labels persist without changing readiness', async ({page}) => {
  await mockBtcTradingPage(page);
  await page.goto('/strategies');
  await page.getByLabel('Alpha 来源筛选', {exact: true}).selectOption('trend');
  await page.getByLabel('策略分类筛选', {exact: true}).selectOption('system:可运行（当前仅 Demo）');
  await expect(page.locator('.strategy-workbench-tree-item')).not.toHaveCount(0);
  await expect(page.locator('.strategy-workbench-tree-item:not(.discovery-runnable)')).toHaveCount(0);
  await page.getByLabel('目录分组方式').selectOption('alpha');
  await expect(page.locator('.strategy-workbench-tree-group > h3').first()).toContainText('统计套利策略');
  await page.getByLabel('Alpha 来源筛选', {exact: true}).selectOption('stat_arb');
  await expect(page.locator('.strategy-workbench-tree-item')).toHaveCount(0);
  await page.getByLabel('Alpha 来源筛选', {exact: true}).selectOption('trend');
  await page.getByLabel('目录分组方式').selectOption('maturity');
  await page.locator('.strategy-workbench-tree-item button').first().click();
  await page.getByText('标注当前策略的 Alpha 来源', {exact: true}).click();
  await page.getByLabel('统计套利策略', {exact: true}).check();
  await page.reload();
  await page.getByLabel('Alpha 来源筛选', {exact: true}).selectOption('stat_arb');
  await expect(page.locator('.strategy-workbench-tree-item')).not.toHaveCount(0);
  await expect(page.locator('.strategy-workbench-safety')).toContainText('ORDER / PAPER / LIVE = FALSE');
});

test('heatmap displays one metric, exact cell inspection and truthful missing results', async ({page}) => {
  const mock = await mockBtcTradingPage(page);
  await page.route('**/api/research/btc/strategy-parameter-map/**', (route) => route.fulfill({json: {...parameterFixture(), strategy_id: decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()!)}}));
  await page.goto('/strategies');
  await page.getByRole('tab', {name: '参数稳定性', exact: true}).click();
  const map = page.getByTestId('strategy-parameter-map');
  await expect(page.getByLabel('参数图横轴')).toHaveValue('fast_window');
  await expect(page.getByLabel('参数图纵轴')).toHaveValue('slow_window');
  await expect(page.getByTestId('parameter-map-coverage')).toContainText('3 / 4 格有值');
  await expect(map.locator('.parameter-map-fixed[open]')).toHaveCount(0);
  await map.getByRole('button', {name: /快均线窗口 10，.*慢均线窗口 60/}).hover();
  await expect(page.getByTestId('parameter-map-inspector')).toContainText('18.40%');
  await expect(page.getByTestId('parameter-map-inspector')).toContainText('1.56');
  await page.getByRole('tab', {name: '最大回撤', exact: true}).click();
  await expect(map.locator('.parameter-map-grid')).toContainText('-14.70%');
  await expect(map.locator('.parameter-map-legend')).toContainText('回撤更小');
  await page.getByRole('tab', {name: 'Sortino', exact: true}).click();
  await expect(map.locator('[data-cell-status="missing_metric"]')).toHaveCount(1);
  await expect(map.locator('[data-cell-status="missing"]')).toHaveCount(1);
  await expect(map).toContainText('已参与选参');
  expect(mock.requests.filter((item) => item.method === 'POST')).toEqual([]);
});

test('wrong identity parameter evidence is hidden and independent historical report remains usable', async ({page}) => {
  await mockBtcTradingPage(page);
  await page.route('**/api/research/btc/strategy-parameter-map/**', (route) => route.fulfill({json: {...parameterFixture(), strategy_id: 'wrong'}}));
  await page.goto('/strategies');
  await page.getByRole('tab', {name: '参数稳定性', exact: true}).click();
  await expect(page.getByRole('status')).toContainText('参数报告身份或权限校验失败');
  await expect(page.getByTestId('strategy-parameter-map')).toHaveCount(0);
  await page.getByRole('tab', {name: '历史回测', exact: true}).click();
  await expect(page.getByTestId('strategy-workbench-report')).toBeVisible();
});
