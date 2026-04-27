import {FormEvent, useEffect, useMemo, useState} from 'react';

import {
  buildPortfolioRequest,
  buildSingleRequest,
  createRunViewModel,
  humanizeError,
  summarizeMetrics,
  type ChartSeriesPayload,
  type DatabaseStatusResponse,
  type DataSyncRunResponse,
  type FormState,
  type KlinePreviewResponse,
  type RunStatusResponse,
  type SchedulerStatusResponse,
  type StrategyInfo,
} from './lib/view-model';

type Mode = 'single' | 'portfolio';
type ValueEvent = {target: {value: string}};

const defaultForm: FormState = {
  source: 'fixture',
  symbol: 'BTCUSDT',
  interval: '1h',
  startDate: '2024-01-01',
  endDate: '2024-02-15',
  capital: 100000,
  commissionRate: 0.0004,
  slippage: 4,
  leverage: 1,
  positionBasis: 'equity',
  strategyId: 'trend_macd',
  dataDbPath: '',
};

type DataFormState = {
  symbol: string;
  interval: FormState['interval'];
  startDate: string;
  endDate: string;
  dbPath: string;
};

const defaultDataForm: DataFormState = {
  symbol: 'BTCUSDT',
  interval: '1m',
  startDate: '2024-01-01',
  endDate: '2024-01-03',
  dbPath: '',
};

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function formatTimestamp(unix: number): string {
  return new Date(unix * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatIso(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPrice(value: number): string {
  return value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
  });
}

function buildDateBoundary(date: string, boundary: 'start' | 'end', interval: string): string {
  if (boundary === 'start') {
    return `${date}T00:00:00Z`;
  }
  if (interval === '1d') {
    return `${date}T23:59:59Z`;
  }
  return `${date}T23:00:00Z`;
}

function metricClass(tone: string): string {
  if (tone === 'good') return 'metric-card metric-good';
  if (tone === 'bad') return 'metric-card metric-bad';
  return 'metric-card';
}

function createLinePath(points: Array<{time: number; value: number}>, width: number, height: number): string {
  if (points.length === 0) return '';
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  return points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((point.value - min) / range) * height;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
}

function LineChart({
  title,
  points,
  accentClass,
}: {
  title: string;
  points: Array<{time: number; value: number}>;
  accentClass: string;
}) {
  const width = 860;
  const height = 240;
  const path = createLinePath(points, width, height);
  const latest = points[points.length - 1];
  const first = points[0];

  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <span>
          {first && latest
            ? `${formatTimestamp(first.time)} - ${formatTimestamp(latest.time)}`
            : '暂无数据'}
        </span>
      </div>
      {points.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="line-chart">
          <path d={path} className={`line-path ${accentClass}`} />
        </svg>
      ) : (
        <div className="empty-chart">等待回测结果</div>
      )}
    </section>
  );
}

function CandleChart({
  candles,
  markers,
}: {
  candles: ChartSeriesPayload['candles'];
  markers: ChartSeriesPayload['markers'];
}) {
  const width = 860;
  const height = 360;
  const visibleCandles = candles.slice(-120);
  const visibleTimes = new Set(visibleCandles.map((candle) => candle.time));
  const visibleMarkers = markers.filter((marker) => visibleTimes.has(marker.time));

  if (visibleCandles.length === 0) {
    return (
      <section className="panel chart-panel">
        <div className="panel-header">
          <h3>K 线与调仓标记</h3>
          <span>暂无数据</span>
        </div>
        <div className="empty-chart">等待回测结果</div>
      </section>
    );
  }

  const lows = visibleCandles.map((candle) => candle.low);
  const highs = visibleCandles.map((candle) => candle.high);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const candleWidth = width / visibleCandles.length;

  const scaleY = (value: number) => height - ((value - min) / range) * height;
  const xForIndex = (index: number) => index * candleWidth + candleWidth / 2;

  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <h3>K 线与调仓标记</h3>
        <span>最近 {visibleCandles.length} 根</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="candle-chart">
        {visibleCandles.map((candle, index) => {
          const x = xForIndex(index);
          const openY = scaleY(candle.open);
          const closeY = scaleY(candle.close);
          const highY = scaleY(candle.high);
          const lowY = scaleY(candle.low);
          const rising = candle.close >= candle.open;
          const bodyTop = Math.min(openY, closeY);
          const bodyHeight = Math.max(2, Math.abs(closeY - openY));

          return (
            <g key={candle.time}>
              <line className="wick" x1={x} y1={highY} x2={x} y2={lowY} />
              <rect
                className={rising ? 'candle-body candle-up' : 'candle-body candle-down'}
                x={x - candleWidth * 0.28}
                y={bodyTop}
                width={candleWidth * 0.56}
                height={bodyHeight}
                rx={1.5}
              />
            </g>
          );
        })}
        {visibleMarkers.map((marker) => {
          const index = visibleCandles.findIndex((candle) => candle.time === marker.time);
          if (index < 0) return null;
          const candle = visibleCandles[index];
          const x = xForIndex(index);
          const y = marker.position === 'aboveBar' ? scaleY(candle.high) - 14 : scaleY(candle.low) + 14;
          const points =
            marker.position === 'aboveBar'
              ? `${x},${y - 10} ${x - 7},${y + 4} ${x + 7},${y + 4}`
              : `${x},${y + 10} ${x - 7},${y - 4} ${x + 7},${y - 4}`;
          return <polygon key={`${marker.time}-${marker.text}`} points={points} fill={marker.color} className="marker" />;
        })}
      </svg>
      <div className="marker-list">
        {visibleMarkers.slice(-4).map((marker) => (
          <div key={`${marker.time}-${marker.text}`} className="marker-pill">
            <span className="marker-dot" style={{backgroundColor: marker.color}} />
            <span>{formatTimestamp(marker.time)}</span>
            <span>{marker.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const [mode, setMode] = useState<Mode>('portfolio');
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [form, setForm] = useState<FormState>(defaultForm);
  const [weightMap, setWeightMap] = useState<Record<string, number>>({});
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [chart, setChart] = useState<ChartSeriesPayload | null>(null);
  const [dataForm, setDataForm] = useState<DataFormState>(defaultDataForm);
  const [database, setDatabase] = useState<DatabaseStatusResponse | null>(null);
  const [klinePreview, setKlinePreview] = useState<KlinePreviewResponse | null>(null);
  const [syncRuns, setSyncRuns] = useState<DataSyncRunResponse[]>([]);
  const [scheduler, setScheduler] = useState<SchedulerStatusResponse | null>(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataMessage, setDataMessage] = useState('');
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const refreshDataPanel = async (nextForm: DataFormState = dataForm) => {
    const baseParams = new URLSearchParams();
    if (nextForm.dbPath) baseParams.set('db_path', nextForm.dbPath);

    const previewParams = new URLSearchParams(baseParams);
    previewParams.set('symbol', nextForm.symbol);
    previewParams.set('interval', nextForm.interval);
    previewParams.set('limit', '16');

    const runsParams = new URLSearchParams(baseParams);
    runsParams.set('limit', '6');

    const [databaseResult, previewResult, runsResult, schedulerResult] = await Promise.all([
      fetchJson<DatabaseStatusResponse>(`/api/data/database?${baseParams.toString()}`),
      fetchJson<KlinePreviewResponse>(`/api/data/klines?${previewParams.toString()}`),
      fetchJson<DataSyncRunResponse[]>(`/api/data/sync-runs?${runsParams.toString()}`),
      fetchJson<SchedulerStatusResponse>('/api/data/scheduler'),
    ]);
    setDatabase(databaseResult);
    setKlinePreview(previewResult);
    setSyncRuns(runsResult);
    setScheduler(schedulerResult);
  };

  useEffect(() => {
    void (async () => {
      try {
        const [healthResult, strategyResult] = await Promise.all([
          fetchJson<HealthState>('/api/health'),
          fetchJson<StrategyInfo[]>('/api/strategies'),
        ]);
        setHealth(healthResult);
        setStrategies(strategyResult);
        setForm((current) => ({
          ...current,
          strategyId: strategyResult[0]?.id ?? current.strategyId,
        }));
        setWeightMap(
          Object.fromEntries(
            strategyResult.map((strategy) => [strategy.id, strategy.default_weight]),
          ),
        );
        await refreshDataPanel(defaultDataForm);
      } catch (caughtError) {
        setError(humanizeError(caughtError));
      }
    })();
  }, []);

  const metricCards = useMemo(() => summarizeMetrics(run?.summary), [run]);
  const viewModel = useMemo(() => createRunViewModel(run, chart), [run, chart]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');

    try {
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload =
        mode === 'single' ? buildSingleRequest(form) : buildPortfolioRequest(form, weightMap);
      const nextRun = await fetchJson<RunStatusResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setRun(nextRun);

      if (nextRun.status === 'completed') {
        const nextChart = await fetchJson<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
        setChart(nextChart);
      } else {
        setChart(null);
        setError(nextRun.error ?? '运行失败');
      }
    } catch (caughtError) {
      setError(humanizeError(caughtError));
      setChart(null);
    } finally {
      setLoading(false);
    }
  };

  const handleDataSync = async () => {
    setDataLoading(true);
    setDataMessage('');
    setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/sync', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          start: buildDateBoundary(dataForm.startDate, 'start', dataForm.interval),
          end: buildDateBoundary(dataForm.endDate, 'end', dataForm.interval),
          db_path: dataForm.dbPath,
          limit: 1000,
          closed_only: true,
        }),
      });
      setDataMessage(`下载完成：写入 ${nextRun.rows_written} 根 K 线，请求 ${nextRun.requests} 次。`);
      setForm((current) => ({
        ...current,
        source: 'sqlite',
        symbol: dataForm.symbol,
        interval: dataForm.interval,
        startDate: dataForm.startDate,
        endDate: dataForm.endDate,
        dataDbPath: dataForm.dbPath,
      }));
      await refreshDataPanel(dataForm);
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleUpdateLatest = async () => {
    setDataLoading(true);
    setDataMessage('');
    setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/update-latest', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          db_path: dataForm.dbPath,
          lookback_days: 30,
          limit: 1000,
        }),
      });
      setDataMessage(`增量更新完成：写入 ${nextRun.rows_written} 根 K 线。`);
      setForm((current) => ({
        ...current,
        source: 'sqlite',
        symbol: dataForm.symbol,
        interval: dataForm.interval,
        dataDbPath: dataForm.dbPath,
      }));
      await refreshDataPanel(dataForm);
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleStartScheduler = async () => {
    setDataLoading(true);
    setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/start', {
        method: 'POST',
        body: JSON.stringify({
          exchange: 'binance_spot',
          symbol: dataForm.symbol,
          interval: dataForm.interval,
          db_path: dataForm.dbPath,
          lookback_days: 30,
          interval_seconds: 86400,
          run_immediately: true,
        }),
      });
      setScheduler(nextStatus);
      setDataMessage('日更任务已启动。');
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  const handleStopScheduler = async () => {
    setDataLoading(true);
    setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/stop', {
        method: 'POST',
      });
      setScheduler(nextStatus);
      setDataMessage('日更任务已停止。');
    } catch (caughtError) {
      setDataMessage(humanizeError(caughtError));
    } finally {
      setDataLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <header className="hero">
        <div>
          <p className="eyebrow">QuantStation vNext</p>
          <h1>比特币多策略投研控制台</h1>
          <p className="hero-copy">
            单策略回测、组合净敞口推演、风险缩放与调仓复盘现在收敛到同一条链路里。
          </p>
        </div>
        <div className="hero-status">
          <span className="status-chip">{health?.service ?? '等待后端'}</span>
          <span className="status-chip muted">默认数据源 {health?.data_source_default ?? 'unknown'}</span>
        </div>
      </header>

      <main className="layout">
        <aside className="side-column">
        <form className="panel control-panel" onSubmit={handleSubmit}>
          <div className="panel-header">
            <h2>运行配置</h2>
            <div className="mode-toggle">
              <button type="button" className={mode === 'portfolio' ? 'active' : ''} onClick={() => setMode('portfolio')}>
                组合回测
              </button>
              <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => setMode('single')}>
                单策略
              </button>
            </div>
          </div>

          <div className="form-grid">
            <label>
              数据源
              <select value={form.source} onChange={(event: ValueEvent) => setForm({...form, source: event.target.value as FormState['source']})}>
                <option value="fixture">Fixture</option>
                <option value="auto">Auto</option>
                <option value="sqlite">SQLite</option>
              </select>
            </label>
            <label>
              标的
              <input value={form.symbol} onChange={(event: ValueEvent) => setForm({...form, symbol: event.target.value})} />
            </label>
            <label>
              周期
              <select value={form.interval} onChange={(event: ValueEvent) => setForm({...form, interval: event.target.value as FormState['interval']})}>
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((interval) => (
                  <option key={interval} value={interval}>
                    {interval}
                  </option>
                ))}
              </select>
            </label>
            <label>
              资金基准
              <select
                value={form.positionBasis}
                onChange={(event: ValueEvent) => setForm({...form, positionBasis: event.target.value as FormState['positionBasis']})}
              >
                <option value="equity">动态权益</option>
                <option value="capital">固定本金</option>
              </select>
            </label>
            <label>
              开始日期
              <input type="date" value={form.startDate} onChange={(event: ValueEvent) => setForm({...form, startDate: event.target.value})} />
            </label>
            <label>
              结束日期
              <input type="date" value={form.endDate} onChange={(event: ValueEvent) => setForm({...form, endDate: event.target.value})} />
            </label>
            <label>
              初始资金
              <input type="number" value={form.capital} onChange={(event: ValueEvent) => setForm({...form, capital: Number(event.target.value)})} />
            </label>
            <label>
              杠杆
              <input type="number" step="0.1" value={form.leverage} onChange={(event: ValueEvent) => setForm({...form, leverage: Number(event.target.value)})} />
            </label>
            <label>
              手续费率
              <input
                type="number"
                step="0.0001"
                value={form.commissionRate}
                onChange={(event: ValueEvent) => setForm({...form, commissionRate: Number(event.target.value)})}
              />
            </label>
            <label>
              滑点
              <input type="number" step="0.1" value={form.slippage} onChange={(event: ValueEvent) => setForm({...form, slippage: Number(event.target.value)})} />
            </label>
            <label className="wide-grid-field">
              SQLite 数据库
              <input
                value={form.dataDbPath}
                placeholder="留空使用后端默认库"
                onChange={(event: ValueEvent) => setForm({...form, dataDbPath: event.target.value})}
              />
            </label>
          </div>

          {mode === 'single' ? (
            <label className="wide-field">
              策略
              <select value={form.strategyId} onChange={(event: ValueEvent) => setForm({...form, strategyId: event.target.value})}>
                {strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.display_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="weights-panel">
              <div className="weights-header">
                <h3>组合权重编辑</h3>
                <span>系统会自动归一化正权重</span>
              </div>
              {strategies.map((strategy) => (
                <div key={strategy.id} className="weight-row">
                  <div>
                    <strong>{strategy.display_name}</strong>
                    <p>{strategy.description}</p>
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={weightMap[strategy.id] ?? 0}
                    onChange={(event: ValueEvent) =>
                      setWeightMap({
                        ...weightMap,
                        [strategy.id]: Number(event.target.value),
                      })
                    }
                  />
                </div>
              ))}
            </div>
          )}

          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? '运行中...' : '启动回测'}
          </button>
        </form>

        <section className="panel data-panel">
          <div className="panel-header">
            <h2>数据管理</h2>
            <span>{database?.initialized ? 'SQLite 已就绪' : '等待初始化'}</span>
          </div>

          <div className="data-status-grid">
            <div>
              <span>数据库</span>
              <strong>{database?.exists ? '已创建' : '未创建'}</strong>
            </div>
            <div>
              <span>覆盖组合</span>
              <strong>{database?.coverage.length ?? 0}</strong>
            </div>
            <div>
              <span>日更任务</span>
              <strong>{scheduler?.running ? '运行中' : '停止'}</strong>
            </div>
          </div>

          <label className="wide-field">
            数据库路径
            <input
              value={dataForm.dbPath}
              placeholder={database?.db_path ?? '留空使用后端默认库'}
              onChange={(event: ValueEvent) => {
                const nextForm = {...dataForm, dbPath: event.target.value};
                setDataForm(nextForm);
                setForm((current) => ({...current, dataDbPath: event.target.value}));
              }}
            />
          </label>

          <div className="form-grid data-form-grid">
            <label>
              标的
              <input
                value={dataForm.symbol}
                onChange={(event: ValueEvent) => setDataForm({...dataForm, symbol: event.target.value.toUpperCase()})}
              />
            </label>
            <label>
              周期
              <select
                value={dataForm.interval}
                onChange={(event: ValueEvent) => setDataForm({...dataForm, interval: event.target.value as FormState['interval']})}
              >
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((interval) => (
                  <option key={interval} value={interval}>
                    {interval}
                  </option>
                ))}
              </select>
            </label>
            <label>
              下载开始
              <input type="date" value={dataForm.startDate} onChange={(event: ValueEvent) => setDataForm({...dataForm, startDate: event.target.value})} />
            </label>
            <label>
              下载结束
              <input type="date" value={dataForm.endDate} onChange={(event: ValueEvent) => setDataForm({...dataForm, endDate: event.target.value})} />
            </label>
          </div>

          <div className="data-actions">
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleDataSync}>
              下载区间
            </button>
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleUpdateLatest}>
              更新到最新
            </button>
            <button type="button" className="secondary-button" disabled={dataLoading || scheduler?.running} onClick={handleStartScheduler}>
              启动日更
            </button>
            <button type="button" className="secondary-button danger" disabled={dataLoading || !scheduler?.running} onClick={handleStopScheduler}>
              停止日更
            </button>
          </div>

          {dataMessage ? <p className="data-message">{dataMessage}</p> : null}

          <div className="coverage-list">
            {(database?.coverage ?? []).slice(0, 4).map((item) => (
              <div key={`${item.exchange}-${item.symbol}-${item.interval}`} className="coverage-row">
                <strong>{item.symbol} {item.interval}</strong>
                <span>{item.rows.toLocaleString('en-US')} 根</span>
                <span>{formatIso(item.start)} - {formatIso(item.end)}</span>
              </div>
            ))}
          </div>

          <div className="panel-header compact-header">
            <h3>数据库预览</h3>
            <button type="button" className="ghost-button" onClick={() => void refreshDataPanel(dataForm)}>
              刷新
            </button>
          </div>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>开</th>
                  <th>高</th>
                  <th>低</th>
                  <th>收</th>
                  <th>量</th>
                </tr>
              </thead>
              <tbody>
                {(klinePreview?.rows ?? []).map((row) => (
                  <tr key={row.open_time_ms}>
                    <td>{formatIso(row.time)}</td>
                    <td>{formatPrice(row.open)}</td>
                    <td>{formatPrice(row.high)}</td>
                    <td>{formatPrice(row.low)}</td>
                    <td>{formatPrice(row.close)}</td>
                    <td>{row.volume.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sync-log">
            {syncRuns.map((item) => (
              <div key={item.run_id} className="sync-row">
                <span className={`status-tag ${item.status === 'completed' ? 'good' : item.status === 'failed' ? 'bad' : 'neutral'}`}>
                  {item.status}
                </span>
                <span>{item.symbol} {item.interval}</span>
                <span>{item.rows_written.toLocaleString('en-US')} 根</span>
              </div>
            ))}
          </div>
        </section>
        </aside>

        <section className="results-column">
          {error ? (
            <div className="panel error-panel">
              <div className="panel-header">
                <h2>运行错误</h2>
              </div>
              <p>{error}</p>
            </div>
          ) : null}

          <section className="metrics-grid">
            {metricCards.length > 0 ? (
              metricCards.map((card) => (
                <article key={card.label} className={metricClass(card.tone)}>
                  <span>{card.label}</span>
                  <strong>{card.value}</strong>
                </article>
              ))
            ) : (
              <article className="panel metrics-placeholder">
                <h3>回测结果会显示在这里</h3>
                <p>先运行一次单策略或组合回测，系统会返回绩效卡片、净值、回撤和 K 线标记。</p>
              </article>
            )}
          </section>

          <div className="charts-grid">
            <LineChart title="权益曲线" points={chart?.equity ?? []} accentClass="line-accent" />
            <LineChart title="回撤曲线" points={chart?.drawdown ?? []} accentClass="line-accent-secondary" />
          </div>

          <CandleChart candles={chart?.candles ?? []} markers={chart?.markers ?? []} />

          <section className="panel detail-panel">
            <div className="panel-header">
              <h3>运行详情</h3>
              <span className={`status-tag ${viewModel.statusTone}`}>{run?.status ?? 'idle'}</span>
            </div>
            <div className="detail-grid">
              <div>
                <h4>策略表现</h4>
                <div className="detail-table">
                  {(run?.strategy_details ?? []).map((item) => (
                    <div key={String(item.strategy_id)} className="detail-row">
                      <span>{String(item.display_name)}</span>
                      <span>{Number(item.total_return_pct ?? 0).toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h4>最新组合权重</h4>
                <div className="detail-table">
                  {(run?.latest_weights ?? []).map((item) => (
                    <div key={String(item.strategy_id)} className="detail-row">
                      <span>{String(item.display_name)}</span>
                      <span>{(Number(item.weight ?? 0) * 100).toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>
        </section>
      </main>
    </div>
  );
}
