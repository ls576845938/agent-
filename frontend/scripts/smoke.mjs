import assert from 'node:assert/strict';

import {
  buildCryptoResamplePlan,
  buildPortfolioRequest,
  buildSingleRequest,
  collectCryptoBlockers,
  createRunViewModel,
  summarizeCryptoCoverage,
  normalizeWeights,
  summarizeMetrics,
} from '../src/lib/view-model.js';

const baseForm = {
  source: 'fixture',
  symbol: 'BTCUSDT',
  interval: '1h',
  startDate: '2024-01-01',
  endDate: '2024-02-01',
  capital: 100000,
  commissionRate: 0.0004,
  slippage: 4,
  leverage: 1,
  positionBasis: 'equity',
  strategyId: 'trend_macd',
};

const normalized = normalizeWeights({
  trend_macd: 0.5,
  reversion_rsi: 0.25,
  donchian_breakout: 0.25,
});

assert.equal(
  Object.values(normalized).reduce((sum, value) => sum + value, 0).toFixed(6),
  '1.000000',
);

const singlePayload = buildSingleRequest(baseForm);
assert.equal(singlePayload.strategy_id, 'trend_macd');
assert.match(singlePayload.start, /2024-01-01T00:00:00/);
assert.match(singlePayload.end, /2024-02-01T23:00:00/);

const portfolioPayload = buildPortfolioRequest(baseForm, {
  trend_macd: 0.4,
  reversion_rsi: 0,
  donchian_breakout: 0.6,
});
assert.equal(portfolioPayload.weights.length, 2);
assert.equal(portfolioPayload.weights[1].weight, 0.6);

const summary = {
  total_return_pct: 12.3,
  annual_return_pct: 45.6,
  annual_volatility_pct: 18.2,
  sharpe_ratio: 1.8,
  sortino_ratio: 2.4,
  max_drawdown_pct: -7.2,
  calmar_ratio: 6.3,
  win_rate_pct: 54,
  profit_factor: 1.22,
  trade_count: 18,
};
const coverageSummary = summarizeCryptoCoverage([
  {exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '1m', rows: 120, updated_at: '2026-05-10T00:00:00Z'},
  {exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '5m', rows: 24, updated_at: '2026-05-10T00:10:00Z'},
]);
assert.equal(coverageSummary.covered_intervals, 2);
assert.equal(coverageSummary.missing_intervals.includes('1d'), true);
assert.equal(coverageSummary.total_rows, 144);

const resamplePlan = buildCryptoResamplePlan([
  {exchange: 'binance_spot', symbol: 'BTCUSDT', interval: '1m', rows: 120, updated_at: '2026-05-10T00:00:00Z'},
], 'BTCUSDT', 'data/market_data.sqlite');
assert.equal(resamplePlan.length, 6);
assert.equal(resamplePlan[1].action.includes('1m -> 5m'), true);

const blockers = collectCryptoBlockers(
  {
    status: 'FAIL',
    selected_priority: 'data',
    framework: [],
    source: 'sqlite',
    actual_source: 'sqlite',
    symbol: 'BTCUSDT',
    interval: '1h',
    row_count: 10,
    raw_row_count: 10,
    expected_rows: 100,
    coverage_pct: 10,
    missing_bars: 90,
    duplicate_timestamps: 0,
    cleaning_loss_rows: 0,
    invalid_ohlc: 1,
    non_positive_prices: 0,
    non_positive_volume: 0,
    large_price_jumps: 0,
    volume_anomalies: 0,
    max_gap_bars: 0,
    max_price_jump_pct: 0,
    quality_score: 10,
    is_usable: false,
    fingerprint: 'demo',
    data_version: 'v1',
    issues: [{severity: 'high', code: 'missing_bars', message: 'missing bars'}],
  },
  {
    status: 'pass',
    selected_priority: 'gate',
    framework: [],
    decision: 'fail',
    next_stage: 'research_ready',
    manifest_id: 'manifest-1',
    manifest_path: '',
    strategy_version: 'v1',
    experiment_record: {},
    data_quality: {},
    backtest_summary: summary,
    gates: [{name: 'data_quality', status: 'fail', message: 'coverage below threshold', metrics: {}, threshold: '>=95%'}],
    recommendations: [],
  },
);
assert.equal(blockers.blockers.length > 0, true);

const cards = summarizeMetrics(summary);
const viewModel = createRunViewModel(
  {
    run_id: 'abc',
    mode: 'single',
    status: 'completed',
    created_at: new Date().toISOString(),
    summary,
    diagnostics: {},
    latest_weights: [],
    strategy_details: [],
  },
  {
    candles: [{time: 1, open: 1, high: 2, low: 0.5, close: 1.5}],
    markers: [],
    equity: [{time: 1, value: 100000}],
    drawdown: [{time: 1, value: 0}],
    exposure: [{time: 1, value: 0}],
    net_units: [{time: 1, value: 0}],
  },
);

assert.equal(cards.length >= 6, true);
assert.equal(viewModel.hasResult, true);
assert.equal(viewModel.candleCount, 1);

console.log('frontend smoke checks passed');
