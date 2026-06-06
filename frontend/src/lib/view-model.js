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

export const cryptoIntervalOrder = ['1m', '5m', '15m', '1h', '4h', '1d'];

function intervalRank(interval) {
  const index = cryptoIntervalOrder.indexOf(interval);
  return index >= 0 ? index : cryptoIntervalOrder.length;
}

function dedupe(values) {
  return [...new Set(values.filter((value) => Boolean(String(value).trim())))];
}

function toIsoOrNull(value) {
  if (!value) return null;
  const timestamp = typeof value === 'string' ? Date.parse(value) : Number(value);
  if (!Number.isFinite(timestamp)) return String(value);
  return new Date(timestamp).toISOString();
}

export function summarizeCryptoCoverage(coverage) {
  const sorted = [...coverage].sort((left, right) => intervalRank(left.interval) - intervalRank(right.interval));
  const coveredIntervals = sorted.map((item) => item.interval);
  const missingIntervals = cryptoIntervalOrder.filter((interval) => !coveredIntervals.includes(interval));
  const totalRows = sorted.reduce((sum, item) => sum + Number(item.rows ?? 0), 0);
  const latestUpdatedAt = sorted.reduce((latest, item) => {
    const next = toIsoOrNull(item.updated_at);
    if (!next) return latest;
    if (!latest) return next;
    return Date.parse(next) > Date.parse(latest) ? next : latest;
  }, null);

  return {
    total_rows: totalRows,
    covered_intervals: sorted.length,
    missing_intervals: missingIntervals,
    latest_updated_at: latestUpdatedAt,
    intervals: sorted,
  };
}

export function buildCryptoResamplePlan(coverage, symbol = 'BTCUSDT', dbPath = '', exchange = 'binance_spot') {
  const coverageByInterval = new Map(coverage.map((item) => [item.interval, item]));
  return cryptoIntervalOrder.map((interval) => {
    const item = coverageByInterval.get(interval);
    const sourceInterval = interval === '1m' ? '1m' : '1m';
    const status = item ? 'ready' : interval === '1m' ? 'seed' : 'missing';
    return {
      exchange: item?.exchange ?? exchange,
      symbol: item?.symbol ?? symbol,
      source_interval: sourceInterval,
      target_interval: interval,
      rows: Number(item?.rows ?? 0),
      start: item?.start ?? null,
      end: item?.end ?? null,
      updated_at: item?.updated_at ?? null,
      status,
      action: interval === '1m' ? '刷新 1m SQLite 证据' : `触发 1m -> ${interval} 重采样`,
      db_path: dbPath,
    };
  });
}

export function collectCryptoBlockers(dataQuality, promotionGate) {
  const dataQualityBlockers = [];
  const promotionBlockers = [];
  const coverageBlockers = [];

  if (!dataQuality) {
    dataQualityBlockers.push('数据质量检查尚未运行');
  } else {
    if (!dataQuality.is_usable) {
      dataQualityBlockers.push(`quality_score ${Number(dataQuality.quality_score ?? 0).toFixed(0)} / coverage ${Number(dataQuality.coverage_pct ?? 0).toFixed(2)}%`);
    }

    const issues = Array.isArray(dataQuality.issues) ? dataQuality.issues : [];
    for (const issue of issues) {
      const severity = String(issue?.severity ?? '').toLowerCase();
      if (severity === 'high' || severity === 'critical') {
        dataQualityBlockers.push(`${issue?.code ?? 'issue'}: ${issue?.message ?? ''}`.trim());
      }
    }

    if (Number(dataQuality.coverage_pct ?? 0) < 95) {
      coverageBlockers.push(`coverage ${Number(dataQuality.coverage_pct ?? 0).toFixed(2)}% < 95%`);
    }
    if (Number(dataQuality.missing_bars ?? 0) > 0) {
      coverageBlockers.push(`${dataQuality.missing_bars} missing bars`);
    }
    if (Number(dataQuality.invalid_ohlc ?? 0) > 0) {
      coverageBlockers.push(`${dataQuality.invalid_ohlc} invalid OHLC rows`);
    }
  }

  if (!promotionGate) {
    promotionBlockers.push('promotion gate 尚未运行');
  } else {
    const gates = Array.isArray(promotionGate.gates) ? promotionGate.gates : [];
    for (const gate of gates) {
      if (String(gate?.status ?? '') !== 'pass') {
        promotionBlockers.push(`${gate?.name ?? 'gate'}: ${gate?.message ?? ''}`.trim());
      }
    }

    if (promotionGate.decision !== 'pass') {
      promotionBlockers.push(`decision=${promotionGate.decision.toUpperCase()} next_stage=${promotionGate.next_stage}`);
    }
  }

  return {
    dataQualityBlockers: dedupe(dataQualityBlockers),
    promotionBlockers: dedupe(promotionBlockers),
    coverageBlockers: dedupe(coverageBlockers),
    blockers: dedupe([...dataQualityBlockers, ...coverageBlockers, ...promotionBlockers]),
  };
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
