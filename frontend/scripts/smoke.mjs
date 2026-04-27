import assert from 'node:assert/strict';

import {
  buildPortfolioRequest,
  buildSingleRequest,
  createRunViewModel,
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
