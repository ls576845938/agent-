export function normalizeWeights(weightMap) {
  const positiveEntries = Object.entries(weightMap).filter(([, value]) => value > 0);
  const total = positiveEntries.reduce((sum, [, value]) => sum + value, 0);
  if (total <= 0) {
    return {};
  }

  return Object.fromEntries(
    positiveEntries.map(([strategyId, value]) => [
      strategyId,
      Number((value / total).toFixed(6)),
    ]),
  );
}

function buildIsoBoundary(date, boundary, interval) {
  if (boundary === 'start') {
    return `${date}T00:00:00Z`;
  }

  if (interval === '1d') {
    return `${date}T23:59:59Z`;
  }

  return `${date}T23:00:00Z`;
}

function buildBasePayload(form) {
  return {
    source: form.source,
    symbol: form.symbol,
    interval: form.interval,
    start: buildIsoBoundary(form.startDate, 'start', form.interval),
    end: buildIsoBoundary(form.endDate, 'end', form.interval),
    capital: form.capital,
    commission_rate: form.commissionRate,
    slippage: form.slippage,
    leverage: form.leverage,
    position_basis: form.positionBasis,
    data_db_path: form.dataDbPath ?? '',
  };
}

export function buildSingleRequest(form) {
  return {
    ...buildBasePayload(form),
    strategy_id: form.strategyId,
    strategy_params: {},
  };
}

export function buildPortfolioRequest(form, weightMap) {
  const normalized = normalizeWeights(weightMap);
  return {
    ...buildBasePayload(form),
    weights: Object.entries(normalized).map(([strategy_id, weight]) => ({
      strategy_id,
      weight,
    })),
  };
}

export function summarizeMetrics(summary) {
  if (!summary) {
    return [];
  }

  return [
    {label: '总收益', value: `${summary.total_return_pct.toFixed(2)}%`, tone: summary.total_return_pct >= 0 ? 'good' : 'bad'},
    {label: '年化收益', value: `${summary.annual_return_pct.toFixed(2)}%`, tone: summary.annual_return_pct >= 0 ? 'good' : 'bad'},
    {label: '年化波动', value: `${summary.annual_volatility_pct.toFixed(2)}%`, tone: 'neutral'},
    {label: '夏普', value: summary.sharpe_ratio.toFixed(2), tone: summary.sharpe_ratio >= 1 ? 'good' : 'neutral'},
    {label: '最大回撤', value: `${summary.max_drawdown_pct.toFixed(2)}%`, tone: 'bad'},
    {label: '胜率', value: `${summary.win_rate_pct.toFixed(2)}%`, tone: 'neutral'},
    {label: 'Profit Factor', value: summary.profit_factor.toFixed(2), tone: summary.profit_factor >= 1 ? 'good' : 'bad'},
    {label: '交易次数', value: String(summary.trade_count), tone: 'neutral'},
  ];
}

export function humanizeError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return '请求失败，请检查后端服务与参数。';
}

export function createRunViewModel(run, chart) {
  return {
    hasResult: Boolean(run?.summary && chart),
    hasError: Boolean(run?.error),
    candleCount: chart?.candles.length ?? 0,
    equityPoints: chart?.equity.length ?? 0,
    statusTone: run?.status === 'completed' ? 'good' : run?.status === 'failed' ? 'bad' : 'neutral',
  };
}
