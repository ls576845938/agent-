import {FormEvent, useEffect, useMemo, useRef, useState} from 'react';

import type {ChartSeriesPayload, DataSyncRunResponse, DatabaseStatusResponse, KlinePreviewResponse, RunStatusResponse, SchedulerStatusResponse, StrategyInfo, Summary} from '../lib/view-model';
import {buildPortfolioRequest, buildSingleRequest, createRunViewModel, humanizeError, summarizeMetrics} from '../lib/view-model';
import {buildDateBoundary, diagnosticsList, formatParams, formatOptimizationScore, formatPrice, formatIso, formatTimestamp, gateClass, hintClass, metricClass, mvpStepClass, reportMetricClass, scenarioClass} from '../lib/utils';
import LineChart from '../components/LineChart';
import CandleChart from '../components/CandleChart';
import type {CostStressResponse, DataQualityResponse, DrawdownPeriod, FormState, MvpStep, OptimizationFrameworkItem, OptimizationHint, PeriodReturn, PortfolioOptimizationResponse, PromotionGateResponse, ReportSection, StrategyOptimizationResponse, WalkForwardResponse, ValueEvent} from '../lib/shared-types';
import {defaultOptimizationFramework} from '../lib/shared-types';

type Mode = 'single' | 'portfolio';

const defaultForm: FormState = {
  source: 'fixture', symbol: 'BTCUSDT', interval: '1h',
  startDate: '2024-01-01', endDate: '2024-02-15',
  capital: 100000, commissionRate: 0.0004, slippage: 4,
  leverage: 1, positionBasis: 'equity', strategyId: 'trend_macd', dataDbPath: '',
};

type DataFormState = {
  symbol: string; interval: FormState['interval'];
  startDate: string; endDate: string; dbPath: string;
};

const defaultDataForm: DataFormState = {
  symbol: 'BTCUSDT', interval: '1m',
  startDate: '2024-01-01', endDate: '2024-01-03', dbPath: '',
};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {'Content-Type': 'application/json', ...(init?.headers ?? {})},
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export type CryptoWorkspaceProps = {
  health: {service: string; data_source_default: string} | null;
  strategies: StrategyInfo[];
};

export default function CryptoWorkspace({health, strategies}: CryptoWorkspaceProps) {
  const [mode, setMode] = useState<Mode>('portfolio');
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
  const [optimization, setOptimization] = useState<StrategyOptimizationResponse | null>(null);
  const [optimizationLoading, setOptimizationLoading] = useState(false);
  const [optimizationMessage, setOptimizationMessage] = useState('');
  const [optimizedStrategyParams, setOptimizedStrategyParams] = useState<Record<string, number> | null>(null);
  const [costStress, setCostStress] = useState<CostStressResponse | null>(null);
  const [costStressLoading, setCostStressLoading] = useState(false);
  const [costStressMessage, setCostStressMessage] = useState('');
  const [walkForward, setWalkForward] = useState<WalkForwardResponse | null>(null);
  const [walkForwardLoading, setWalkForwardLoading] = useState(false);
  const [walkForwardMessage, setWalkForwardMessage] = useState('');
  const [portfolioOptimization, setPortfolioOptimization] = useState<PortfolioOptimizationResponse | null>(null);
  const [portfolioOptimizationLoading, setPortfolioOptimizationLoading] = useState(false);
  const [portfolioOptimizationMessage, setPortfolioOptimizationMessage] = useState('');
  const [dataQuality, setDataQuality] = useState<DataQualityResponse | null>(null);
  const [dataQualityLoading, setDataQualityLoading] = useState(false);
  const [dataQualityMessage, setDataQualityMessage] = useState('');
  const [promotionGate, setPromotionGate] = useState<PromotionGateResponse | null>(null);
  const [promotionGateLoading, setPromotionGateLoading] = useState(false);
  const [promotionGateMessage, setPromotionGateMessage] = useState('');
  const [mvpLoading, setMvpLoading] = useState(false);
  const [mvpMessage, setMvpMessage] = useState('');
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setWeightMap(Object.fromEntries(strategies.map((s) => [s.id, s.default_weight])));
  }, [strategies]);

  const refreshDataPanel = async (nextForm: DataFormState = dataForm) => {
    const baseParams = new URLSearchParams();
    if (nextForm.dbPath) baseParams.set('db_path', nextForm.dbPath);
    const previewParams = new URLSearchParams(baseParams);
    previewParams.set('symbol', nextForm.symbol);
    previewParams.set('interval', nextForm.interval);
    previewParams.set('limit', '16');
    const runsParams = new URLSearchParams(baseParams);
    runsParams.set('limit', '6');
    const [db, preview, runs, sched] = await Promise.all([
      fetchJson<DatabaseStatusResponse>(`/api/data/database?${baseParams.toString()}`),
      fetchJson<KlinePreviewResponse>(`/api/data/klines?${previewParams.toString()}`),
      fetchJson<DataSyncRunResponse[]>(`/api/data/sync-runs?${runsParams.toString()}`),
      fetchJson<SchedulerStatusResponse>('/api/data/scheduler'),
    ]);
    setDatabase(db); setKlinePreview(preview); setSyncRuns(runs); setScheduler(sched);
  };

  useEffect(() => { void refreshDataPanel(defaultDataForm); }, []);

  const metricCards = useMemo(() => summarizeMetrics(run?.summary), [run]);
  const viewModel = useMemo(() => createRunViewModel(run, chart), [run, chart]);
  const reportSections = useMemo(() => diagnosticsList<ReportSection>(run?.diagnostics, 'report_sections').sort((a, b) => a.priority - b.priority), [run]);
  const optimizationHints = useMemo(() => diagnosticsList<OptimizationHint>(run?.diagnostics, 'optimization_hints'), [run]);
  const drawdownPeriods = useMemo(() => diagnosticsList<DrawdownPeriod>(run?.diagnostics, 'drawdown_periods'), [run]);
  const monthlyReturns = useMemo(() => diagnosticsList<PeriodReturn>(run?.diagnostics, 'monthly_returns'), [run]);
  const optimizationFramework = promotionGate?.framework ?? dataQuality?.framework ?? portfolioOptimization?.framework ?? walkForward?.framework ?? costStress?.framework ?? optimization?.framework ?? defaultOptimizationFramework;

  const mvpSteps = useMemo<MvpStep[]>(() => {
    const gateFails = promotionGate?.gates.filter((g) => g.status === 'fail').length ?? 0;
    const gateWarns = promotionGate?.gates.filter((g) => g.status === 'warn').length ?? 0;
    const completedSummary = run?.status === 'completed' ? run.summary : null;
    return [
      {id: 'data_quality', label: '数据质量', status: dataQualityLoading || (mvpLoading && !dataQuality) ? 'active' : dataQuality ? (dataQuality.is_usable ? 'done' : 'fail') : 'pending', detail: dataQuality ? `Score ${dataQuality.quality_score.toFixed(0)} · ${dataQuality.coverage_pct.toFixed(1)}%` : '等待检查'},
      {id: 'backtest', label: '回测执行', status: loading || (mvpLoading && !run) ? 'active' : completedSummary ? 'done' : run?.status === 'failed' ? 'fail' : 'pending', detail: completedSummary ? `Return ${completedSummary.total_return_pct.toFixed(2)}% · Sharpe ${completedSummary.sharpe_ratio.toFixed(2)}` : '等待生成'},
      {id: 'visual_report', label: '图表报告', status: chart ? 'done' : run?.status === 'completed' ? 'warn' : 'pending', detail: chart ? `${chart.candles.length} 根K线 · ${chart.markers.length} 个标记` : '等待生成'},
      {id: 'promotion_gate', label: '准入门', status: promotionGateLoading || (mvpLoading && !promotionGate) ? 'active' : promotionGate ? (promotionGate.decision === 'fail' ? 'fail' : promotionGate.decision === 'warn' ? 'warn' : 'done') : 'pending', detail: promotionGate ? `Decision ${promotionGate.decision.toUpperCase()} · ${gateWarns}w · ${gateFails}f` : '等待综合评估'},
      {id: 'experiment_registry', label: '实验登记', status: promotionGate?.experiment_record.registry_path ? 'done' : promotionGate ? 'warn' : 'pending', detail: promotionGate?.experiment_record.registry_path ?? '等待登记'},
    ];
  }, [chart, dataQuality, dataQualityLoading, loading, mvpLoading, promotionGate, promotionGateLoading, run]);

  const mvpDoneCount = mvpSteps.filter((s) => s.status === 'done').length;

  const buildPromotionGateRequest = () => ({
    mode, source: form.source, symbol: form.symbol, interval: form.interval,
    start: buildDateBoundary(form.startDate, 'start', form.interval),
    end: buildDateBoundary(form.endDate, 'end', form.interval),
    capital: form.capital, commission_rate: form.commissionRate,
    slippage: form.slippage, leverage: form.leverage,
    position_basis: form.positionBasis, data_db_path: form.dataDbPath,
    strategy_id: form.strategyId, strategy_params: optimizedStrategyParams ?? {},
    weights: Object.entries(weightMap).filter(([, w]) => w > 0).map(([id, w]) => ({strategy_id: id, weight: w})),
    skip_deep_checks: false, persist_manifest: true, register_experiment: true,
    experiment_name: `${form.symbol.toLowerCase()}_${mode}_promotion_gate`,
    notes: 'Created from QuantStation MVP acceptance flow.',
  });

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true); setError('');
    try {
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload = mode === 'single' ? {...buildSingleRequest(form), strategy_params: optimizedStrategyParams ?? {}} : buildPortfolioRequest(form, weightMap);
      const nextRun = await fetchJson<RunStatusResponse>(endpoint, {method: 'POST', body: JSON.stringify(payload)});
      setRun(nextRun);
      if (nextRun.status === 'completed') {
        const nextChart = await fetchJson<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
        setChart(nextChart);
      } else { setChart(null); setError(nextRun.error ?? '运行失败'); }
    } catch (e) { setError(humanizeError(e)); setChart(null); }
    finally { setLoading(false); }
  };

  const handleMvpAcceptance = async () => {
    setMvpLoading(true); setMvpMessage('MVP 验收：数据质量检查中...'); setError('');
    try {
      const quality = await fetchJson<DataQualityResponse>('/api/data/quality', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        data_db_path: form.dataDbPath,
      })});
      setDataQuality(quality);
      setDataQualityMessage(`数据质量 Score ${quality.quality_score.toFixed(0)}，覆盖 ${quality.coverage_pct.toFixed(2)}%`);
      if (!quality.is_usable) throw new Error('数据质量阻断级问题');

      setMvpMessage('回测运行中...');
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload = mode === 'single' ? {...buildSingleRequest(form), strategy_params: optimizedStrategyParams ?? {}} : buildPortfolioRequest(form, weightMap);
      const nextRun = await fetchJson<RunStatusResponse>(endpoint, {method: 'POST', body: JSON.stringify(payload)});
      setRun(nextRun);
      if (nextRun.status !== 'completed') throw new Error(nextRun.error ?? '回测失败');
      const nextChart = await fetchJson<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
      setChart(nextChart);

      setMvpMessage('准入门评估中...');
      const gate = await fetchJson<PromotionGateResponse>('/api/research/promotion-gate', {method: 'POST', body: JSON.stringify(buildPromotionGateRequest())});
      setPromotionGate(gate);
      setPromotionGateMessage(`准入门 Decision ${gate.decision.toUpperCase()}，下一阶段 ${gate.next_stage}`);
      setMvpMessage(`MVP 验收完成：${gate.decision.toUpperCase()}`);
    } catch (e) { const msg = humanizeError(e); setMvpMessage(msg); setError(msg); }
    finally { setMvpLoading(false); }
  };

  const handlePriorityOptimization = async () => {
    setOptimizationLoading(true); setOptimizationMessage(''); setError('');
    try {
      const result = await fetchJson<StrategyOptimizationResponse>('/api/backtests/optimize', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, max_candidates: 12,
      })});
      setOptimization(result);
      setOptimizationMessage(`已完成 ${result.candidates.length} 组候选，优先方向 ${result.selected_priority}`);
      if (result.best?.parameters) {
        setOptimizedStrategyParams(result.best.parameters);
        setForm((c) => ({...c, strategyId: result.best?.strategy_id ?? c.strategyId}));
      }
    } catch (e) { setOptimizationMessage(humanizeError(e)); }
    finally { setOptimizationLoading(false); }
  };

  const handleCostStress = async () => {
    setCostStressLoading(true); setCostStressMessage(''); setError('');
    try {
      const result = await fetchJson<CostStressResponse>('/api/backtests/cost-stress', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, strategy_params: optimizedStrategyParams ?? {},
      })});
      setCostStress(result);
      setCostStressMessage(`压力测试完成：${result.survival_rate_pct.toFixed(0)}% 生存率`);
    } catch (e) { setCostStressMessage(humanizeError(e)); }
    finally { setCostStressLoading(false); }
  };

  const handleWalkForward = async () => {
    setWalkForwardLoading(true); setWalkForwardMessage(''); setError('');
    try {
      const result = await fetchJson<WalkForwardResponse>('/api/backtests/walk-forward', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, strategy_params: optimizedStrategyParams ?? {},
      })});
      setWalkForward(result);
      setWalkForwardMessage(`Walk-forward: OOS pass rate ${result.stability.pass_rate_pct.toFixed(0)}%`);
    } catch (e) { setWalkForwardMessage(humanizeError(e)); }
    finally { setWalkForwardLoading(false); }
  };

  const handlePortfolioOptimization = async () => {
    setPortfolioOptimizationLoading(true); setPortfolioOptimizationMessage(''); setError('');
    try {
      const normalized = Object.fromEntries(Object.entries(weightMap).filter(([, w]) => w > 0));
      const result = await fetchJson<PortfolioOptimizationResponse>('/api/backtests/portfolio-optimize', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_ids: Object.keys(normalized),
        baseline_weights: Object.values(normalized),
      })});
      setPortfolioOptimization(result);
      setPortfolioOptimizationMessage(`组合优化完成：Sharpe delta ${result.improvement.sharpe_delta.toFixed(2)}`);
    } catch (e) { setPortfolioOptimizationMessage(humanizeError(e)); }
    finally { setPortfolioOptimizationLoading(false); }
  };

  const handleDataQuality = async () => {
    setDataQualityLoading(true); setDataQualityMessage(''); setError('');
    try {
      const result = await fetchJson<DataQualityResponse>('/api/data/quality', {method: 'POST', body: JSON.stringify({
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        data_db_path: form.dataDbPath,
      })});
      setDataQuality(result);
      setDataQualityMessage(`数据质量 Score ${result.quality_score.toFixed(0)}，覆盖 ${result.coverage_pct.toFixed(2)}%`);
    } catch (e) { setDataQualityMessage(humanizeError(e)); }
    finally { setDataQualityLoading(false); }
  };

  const handlePromotionGate = async () => {
    setPromotionGateLoading(true); setPromotionGateMessage(''); setError('');
    try {
      const result = await fetchJson<PromotionGateResponse>('/api/research/promotion-gate', {method: 'POST', body: JSON.stringify(buildPromotionGateRequest())});
      setPromotionGate(result);
      setPromotionGateMessage(`准入门 Decision ${result.decision.toUpperCase()}，下一阶段 ${result.next_stage}`);
    } catch (e) { setPromotionGateMessage(humanizeError(e)); }
    finally { setPromotionGateLoading(false); }
  };

  const handleDataSync = async () => {
    setDataLoading(true); setDataMessage(''); setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/sync', {method: 'POST', body: JSON.stringify({
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval,
        start: buildDateBoundary(dataForm.startDate, 'start', dataForm.interval),
        end: buildDateBoundary(dataForm.endDate, 'end', dataForm.interval),
        db_path: dataForm.dbPath, limit: 1000, closed_only: true,
      })});
      setDataMessage(`下载完成：写入 ${nextRun.rows_written} K 线`);
      setForm((c) => ({...c, source: 'sqlite', symbol: dataForm.symbol, interval: dataForm.interval, startDate: dataForm.startDate, endDate: dataForm.endDate, dataDbPath: dataForm.dbPath}));
      await refreshDataPanel(dataForm);
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleUpdateLatest = async () => {
    setDataLoading(true); setDataMessage(''); setError('');
    try {
      const nextRun = await fetchJson<DataSyncRunResponse>('/api/data/update-latest', {method: 'POST', body: JSON.stringify({
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval, db_path: dataForm.dbPath, lookback_days: 30, limit: 1000,
      })});
      setDataMessage(`增量更新完成：写入 ${nextRun.rows_written} K 线`);
      setForm((c) => ({...c, source: 'sqlite', symbol: dataForm.symbol, interval: dataForm.interval, dataDbPath: dataForm.dbPath}));
      await refreshDataPanel(dataForm);
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleStartScheduler = async () => {
    setDataLoading(true); setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/start', {method: 'POST', body: JSON.stringify({
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval, db_path: dataForm.dbPath, lookback_days: 30, interval_seconds: 86400, run_immediately: true,
      })});
      setScheduler(nextStatus); setDataMessage('日更任务已启动');
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleStopScheduler = async () => {
    setDataLoading(true); setDataMessage('');
    try {
      const nextStatus = await fetchJson<SchedulerStatusResponse>('/api/data/scheduler/stop', {method: 'POST'});
      setScheduler(nextStatus); setDataMessage('日更任务已停止');
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleApplyPortfolioWeights = () => {
    if (!portfolioOptimization) return;
    const next = {...weightMap};
    for (const row of portfolioOptimization.optimized_weight_rows) {
      next[row.strategy_id] = row.weight_pct / 100;
    }
    setWeightMap(next);
  };

  return (
    <main className="layout">
      <aside className="side-column">
        <form className="panel control-panel" onSubmit={handleSubmit}>
          <div className="panel-header">
            <h2>运行配置</h2>
            <div className="mode-toggle">
              <button type="button" className={mode === 'portfolio' ? 'active' : ''} onClick={() => setMode('portfolio')}>组合回测</button>
              <button type="button" className={mode === 'single' ? 'active' : ''} onClick={() => setMode('single')}>单策略</button>
            </div>
          </div>
          <div className="form-grid">
            <label>数据源
              <select value={form.source} onChange={(e: ValueEvent) => setForm({...form, source: e.target.value as FormState['source']})}>
                <option value="fixture">Fixture</option><option value="auto">Auto</option><option value="sqlite">SQLite</option>
              </select>
            </label>
            <label>标的<input value={form.symbol} onChange={(e: ValueEvent) => setForm({...form, symbol: e.target.value})} /></label>
            <label>周期
              <select value={form.interval} onChange={(e: ValueEvent) => setForm({...form, interval: e.target.value as FormState['interval']})}>
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((i) => <option key={i} value={i}>{i}</option>)}
              </select>
            </label>
            <label>资金基准
              <select value={form.positionBasis} onChange={(e: ValueEvent) => setForm({...form, positionBasis: e.target.value as FormState['positionBasis']})}>
                <option value="equity">动态权益</option><option value="capital">固定本金</option>
              </select>
            </label>
            <label>开始日期<input type="date" value={form.startDate} onChange={(e: ValueEvent) => setForm({...form, startDate: e.target.value})} /></label>
            <label>结束日期<input type="date" value={form.endDate} onChange={(e: ValueEvent) => setForm({...form, endDate: e.target.value})} /></label>
            <label>初始资金<input type="number" value={form.capital} onChange={(e: ValueEvent) => setForm({...form, capital: Number(e.target.value)})} /></label>
            <label>杠杆<input type="number" step="0.1" value={form.leverage} onChange={(e: ValueEvent) => setForm({...form, leverage: Number(e.target.value)})} /></label>
            <label>手续费率<input type="number" step="0.0001" value={form.commissionRate} onChange={(e: ValueEvent) => setForm({...form, commissionRate: Number(e.target.value)})} /></label>
            <label>滑点<input type="number" step="0.1" value={form.slippage} onChange={(e: ValueEvent) => setForm({...form, slippage: Number(e.target.value)})} /></label>
            <label className="wide-grid-field">SQLite 数据库
              <input value={form.dataDbPath} placeholder="留空使用默认库" onChange={(e: ValueEvent) => setForm({...form, dataDbPath: e.target.value})} />
            </label>
          </div>
          {mode === 'single' ? (
            <label className="wide-field">策略
              <select value={form.strategyId} onChange={(e: ValueEvent) => { setOptimizedStrategyParams(null); setForm({...form, strategyId: e.target.value}); }}>
                {strategies.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
              </select>
            </label>
          ) : (
            <div className="weights-panel">
              <div className="weights-header"><h3>组合权重</h3><span>归一化正权重</span></div>
              {strategies.map((s) => (
                <div key={s.id} className="weight-row">
                  <div><strong>{s.display_name}</strong><p>{s.description}</p></div>
                  <input type="number" step="0.01" min="0" value={weightMap[s.id] ?? 0} onChange={(e: ValueEvent) => setWeightMap({...weightMap, [s.id]: Number(e.target.value)})} />
                </div>
              ))}
            </div>
          )}
          <button type="submit" className="primary-button" disabled={loading}>{loading ? '运行中...' : '启动回测'}</button>
        </form>

        <section className="panel data-panel">
          <div className="panel-header"><h2>数据管理</h2><span>{database?.initialized ? 'SQLite 已就绪' : '等待初始化'}</span></div>
          <div className="data-status-grid">
            <div><span>数据库</span><strong>{database?.exists ? '已创建' : '未创建'}</strong></div>
            <div><span>覆盖组合</span><strong>{database?.coverage.length ?? 0}</strong></div>
            <div><span>日更任务</span><strong>{scheduler?.running ? '运行中' : '停止'}</strong></div>
          </div>
          <label className="wide-field">数据库路径
            <input value={dataForm.dbPath} placeholder={database?.db_path ?? '留空使用默认库'} onChange={(e: ValueEvent) => {
              const n = {...dataForm, dbPath: e.target.value}; setDataForm(n); setForm((c) => ({...c, dataDbPath: e.target.value}));
            }} />
          </label>
          <div className="form-grid data-form-grid">
            <label>标的<input value={dataForm.symbol} onChange={(e: ValueEvent) => setDataForm({...dataForm, symbol: e.target.value.toUpperCase()})} /></label>
            <label>周期
              <select value={dataForm.interval} onChange={(e: ValueEvent) => setDataForm({...dataForm, interval: e.target.value as FormState['interval']})}>
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((i) => <option key={i} value={i}>{i}</option>)}
              </select>
            </label>
            <label>下载开始<input type="date" value={dataForm.startDate} onChange={(e: ValueEvent) => setDataForm({...dataForm, startDate: e.target.value})} /></label>
            <label>下载结束<input type="date" value={dataForm.endDate} onChange={(e: ValueEvent) => setDataForm({...dataForm, endDate: e.target.value})} /></label>
          </div>
          <div className="data-actions">
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleDataSync}>下载区间</button>
            <button type="button" className="secondary-button" disabled={dataLoading} onClick={handleUpdateLatest}>更新到最新</button>
            <button type="button" className="secondary-button" disabled={dataLoading || scheduler?.running} onClick={handleStartScheduler}>启动日更</button>
            <button type="button" className="secondary-button danger" disabled={dataLoading || !scheduler?.running} onClick={handleStopScheduler}>停止日更</button>
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
          <div className="panel-header compact-header"><h3>数据库预览</h3><button type="button" className="ghost-button" onClick={() => refreshDataPanel(dataForm)}>刷新</button></div>
          <div className="table-scroll">
            <table className="data-table"><thead><tr><th>时间</th><th>开</th><th>高</th><th>低</th><th>收</th><th>量</th></tr></thead>
              <tbody>{(klinePreview?.rows ?? []).map((row) => (
                <tr key={row.open_time_ms}><td>{formatIso(row.time)}</td><td>{formatPrice(row.open)}</td><td>{formatPrice(row.high)}</td><td>{formatPrice(row.low)}</td><td>{formatPrice(row.close)}</td><td>{row.volume.toFixed(3)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <div className="sync-log">
            {syncRuns.map((item) => (
              <div key={item.run_id} className="sync-row">
                <span className={`status-tag ${item.status === 'completed' ? 'good' : item.status === 'failed' ? 'bad' : 'neutral'}`}>{item.status}</span>
                <span>{item.symbol} {item.interval}</span>
                <span>{item.rows_written.toLocaleString('en-US')} 根</span>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <section className="results-column">
        <section className="panel mvp-panel">
          <div className="panel-header"><h2>MVP 交付闭环</h2><span>已完成 {mvpDoneCount}/{mvpSteps.length}</span></div>
          <div className="mvp-command-row">
            <div><strong>{promotionGate ? promotionGate.next_stage : run?.status === 'completed' ? 'ready_for_gate' : 'research_ready'}</strong><p>{promotionGate?.manifest_id ? `Manifest ${promotionGate.manifest_id}` : '最小闭环待验收'}</p></div>
            <button type="button" className="primary-button" disabled={mvpLoading || loading} onClick={handleMvpAcceptance}>{mvpLoading ? '验收中...' : '一键 MVP 验收'}</button>
          </div>
          <div className="mvp-step-grid">
            {mvpSteps.map((step, i) => (
              <div key={step.id} className={mvpStepClass(step.status)}><span>{i + 1}</span><strong>{step.label}</strong><p>{step.detail}</p></div>
            ))}
          </div>
          {mvpMessage ? <p className="data-message">{mvpMessage}</p> : null}
        </section>

        {error ? <div className="panel error-panel"><div className="panel-header"><h2>运行错误</h2></div><p>{error}</p></div> : null}

        <section className="panel optimization-panel">
          <div className="panel-header"><h2>下一步优化框架</h2><span>{optimizationFramework[0]?.title ?? ''}</span></div>
          <div className="optimization-framework">
            {optimizationFramework.map((item) => (
              <div key={item.priority} className={`optimization-step optimization-${item.status}`}><span>{item.priority}</span><div><strong>{item.title}</strong><p>{item.reason}</p></div></div>
            ))}
          </div>
          <div className="optimization-actions">
            <button type="button" className="secondary-button" disabled={optimizationLoading} onClick={handlePriorityOptimization}>{optimizationLoading ? '优化中...' : '运行优先优化'}</button>
            <button type="button" className="secondary-button" disabled={costStressLoading} onClick={handleCostStress}>{costStressLoading ? '中...' : '成本压力测试'}</button>
            <button type="button" className="secondary-button" disabled={walkForwardLoading} onClick={handleWalkForward}>{walkForwardLoading ? '中...' : 'Walk-forward'}</button>
            <button type="button" className="secondary-button" disabled={portfolioOptimizationLoading} onClick={handlePortfolioOptimization}>{portfolioOptimizationLoading ? '中...' : '组合优化'}</button>
            <button type="button" className="secondary-button" disabled={dataQualityLoading} onClick={handleDataQuality}>{dataQualityLoading ? '中...' : '数据质量'}</button>
            <button type="button" className="secondary-button" disabled={promotionGateLoading} onClick={handlePromotionGate}>{promotionGateLoading ? '中...' : '研究准入门'}</button>
            {optimizedStrategyParams ? <span>已应用：{formatParams(optimizedStrategyParams)}</span> : null}
          </div>
          {optimizationMessage ? <p className="data-message">{optimizationMessage}</p> : null}
          {costStressMessage ? <p className="data-message">{costStressMessage}</p> : null}
          {walkForwardMessage ? <p className="data-message">{walkForwardMessage}</p> : null}
          {portfolioOptimizationMessage ? <p className="data-message">{portfolioOptimizationMessage}</p> : null}
          {dataQualityMessage ? <p className="data-message">{dataQualityMessage}</p> : null}
          {promotionGateMessage ? <p className="data-message">{promotionGateMessage}</p> : null}

          {/* Optimization results */}
          {optimization?.best ? (
            <div className="optimization-result-grid">
              <div className="optimization-best"><span>最佳候选</span><strong>Score {formatOptimizationScore(optimization.best.score)}</strong><p>{formatParams(optimization.best.parameters)}</p></div>
              <div className="optimization-best"><span>样本外表现</span><strong>Sharpe {optimization.best.validation.sharpe_ratio.toFixed(2)}</strong><p>Return {optimization.best.validation.total_return_pct.toFixed(2)}% · MDD {optimization.best.validation.max_drawdown_pct.toFixed(2)}%</p></div>
              <div className="optimization-best"><span>切分</span><strong>{optimization.split.train_rows} / {optimization.split.validation_rows}</strong><p>{formatTimestamp(optimization.split.train_start)} - {formatTimestamp(optimization.split.validation_end)}</p></div>
            </div>
          ) : null}
          {optimization?.candidates.length ? (
            <div className="optimization-table">
              {optimization.candidates.slice(0, 5).map((c) => (
                <div key={c.rank} className="optimization-row"><span>#{c.rank}</span><span>{formatOptimizationScore(c.score)}</span><span>{c.validation.sharpe_ratio.toFixed(2)} Sharpe</span><span>{c.validation.max_drawdown_pct.toFixed(2)}% MDD</span><span>{formatParams(c.parameters)}</span></div>
              ))}
            </div>
          ) : null}

          {/* Cost stress results */}
          {costStress ? (
            <div className="stress-panel">
              <div className="stress-summary-grid">
                <div className="optimization-best"><span>压力存活率</span><strong>{costStress.survival_rate_pct.toFixed(0)}%</strong><p>{costStress.selected_priority}</p></div>
                <div className="optimization-best"><span>最差场景</span><strong>{costStress.worst_case?.label ?? '-'}</strong><p>Return {costStress.worst_case?.summary.total_return_pct.toFixed(2) ?? '-'}% · MDD {costStress.worst_case?.summary.max_drawdown_pct.toFixed(2) ?? '-'}%</p></div>
                <div className="optimization-best"><span>测试参数</span><strong>{costStress.strategy_id}</strong><p>{formatParams(costStress.strategy_params)}</p></div>
              </div>
              <div className="stress-table">
                {costStress.scenarios.map((scenario) => (
                  <div key={scenario.name} className={scenarioClass(scenario.survives)}><span>{scenario.survives ? 'PASS' : 'FAIL'}</span><span>{scenario.label}</span><span>{scenario.summary.total_return_pct.toFixed(2)}%</span><span>{scenario.summary.sharpe_ratio.toFixed(2)} Sharpe</span><span>{scenario.summary.max_drawdown_pct.toFixed(2)}% MDD</span></div>
                ))}
              </div>
              <div className="optimization-recommendations">{costStress.recommendations.map((r, i) => <p key={i}>{r}</p>)}</div>
            </div>
          ) : null}

          {/* Walk-forward results */}
          {walkForward ? (
            <div className="walk-panel">
              <div className="stress-summary-grid">
                <div className="optimization-best"><span>OOS 通过率</span><strong>{walkForward.stability.pass_rate_pct.toFixed(0)}%</strong><p>{walkForward.selected_priority}</p></div>
                <div className="optimization-best"><span>OOS 中位 Sharpe</span><strong>{walkForward.stability.median_oos_sharpe.toFixed(2)}</strong><p>Avg Return {walkForward.stability.avg_oos_return_pct.toFixed(2)}%</p></div>
                <div className="optimization-best"><span>参数稳定性</span><strong>{walkForward.stability.parameter_stability_pct.toFixed(0)}%</strong><p>Worst MDD {walkForward.stability.worst_oos_drawdown_pct.toFixed(2)}%</p></div>
              </div>
              <div className="walk-table">
                {walkForward.windows.map((w) => (
                  <div key={w.fold} className={`walk-row ${w.survives ? 'stress-pass' : 'stress-fail'}`}><span>W{w.fold}</span><span>{w.survives ? 'PASS' : 'FAIL'}</span><span>{formatTimestamp(w.validation_start)} - {formatTimestamp(w.validation_end)}</span><span>{w.validation.total_return_pct.toFixed(2)}%</span><span>{w.validation.sharpe_ratio.toFixed(2)} Sharpe</span><span>{w.validation.max_drawdown_pct.toFixed(2)}% MDD</span><span>{formatParams(w.selected_params)}</span></div>
                ))}
              </div>
              <div className="regime-grid">
                {walkForward.regimes.map((r) => (
                  <div key={r.name} className={`regime-card ${r.survives ? 'stress-pass' : 'stress-fail'}`}><span>{r.survives ? 'PASS' : 'FAIL'}</span><strong>{r.label}</strong><p>{r.coverage_pct.toFixed(0)}% bars · Return {r.summary.total_return_pct.toFixed(2)}% · MDD {r.summary.max_drawdown_pct.toFixed(2)}%</p></div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Portfolio optimization results */}
          {portfolioOptimization ? (
            <div className="portfolio-opt-panel">
              <div className="stress-summary-grid">
                <div className="optimization-best"><span>优化后 Sharpe</span><strong>{portfolioOptimization.optimized_summary.sharpe_ratio.toFixed(2)}</strong><p>Delta {portfolioOptimization.improvement.sharpe_delta.toFixed(2)}</p></div>
                <div className="optimization-best"><span>优化后收益</span><strong>{portfolioOptimization.optimized_summary.total_return_pct.toFixed(2)}%</strong><p>Baseline {portfolioOptimization.baseline_summary.total_return_pct.toFixed(2)}%</p></div>
                <div className="optimization-best"><span>风险状态</span><strong>{portfolioOptimization.risk_overlay.state}</strong><p>Gross x{portfolioOptimization.risk_overlay.suggested_gross_multiplier.toFixed(2)}</p></div>
              </div>
              <div className="portfolio-action-row">
                <button type="button" className="secondary-button" onClick={handleApplyPortfolioWeights}>应用建议权重</button>
              </div>
              <div className="portfolio-table">
                {portfolioOptimization.optimized_weight_rows.map((row) => (
                  <div key={row.strategy_id} className="portfolio-row"><span>{row.display_name}</span><span>{row.baseline_weight_pct.toFixed(1)}% → {row.weight_pct.toFixed(1)}%</span></div>
                ))}
              </div>
              <div className="portfolio-split-grid">
                <div><h4>风险贡献</h4><div className="risk-list">{portfolioOptimization.risk_budget.risk_contributions.map((item) => <div key={item.strategy_id} className="risk-row"><span>{item.strategy_id}</span><span>{item.risk_contribution_pct.toFixed(1)}% risk</span></div>)}</div></div>
                <div><h4>最高相关性</h4><div className="risk-list">{portfolioOptimization.correlation_pairs.slice(0, 4).map((pair) => <div key={`${pair.left}-${pair.right}`} className="risk-row"><span>{pair.left}/{pair.right}</span><span>{pair.correlation.toFixed(2)}</span></div>)}</div></div>
              </div>
            </div>
          ) : null}

          {/* Data quality */}
          {dataQuality ? (
            <div className="data-quality-panel">
              <div className="stress-summary-grid">
                <div className="optimization-best"><span>质量分数</span><strong>{dataQuality.quality_score.toFixed(0)}</strong><p>{dataQuality.is_usable ? '可用' : '阻断'}</p></div>
                <div className="optimization-best"><span>覆盖率</span><strong>{dataQuality.coverage_pct.toFixed(2)}%</strong><p>{dataQuality.row_count.toLocaleString('en-US')} / {dataQuality.expected_rows.toLocaleString('en-US')}</p></div>
                <div className="optimization-best"><span>数据版本</span><strong>{dataQuality.actual_source}</strong><p>{dataQuality.data_version}</p></div>
              </div>
              <div className="quality-metrics-grid">
                <div><span>缺失K线</span><strong>{dataQuality.missing_bars}</strong></div>
                <div><span>重复时间戳</span><strong>{dataQuality.duplicate_timestamps}</strong></div>
                <div><span>OHLC异常</span><strong>{dataQuality.invalid_ohlc}</strong></div>
                <div><span>价格跳变</span><strong>{dataQuality.large_price_jumps}</strong></div>
              </div>
              <div className="quality-issue-list">{dataQuality.issues.map((issue) => <div key={`${issue.code}-${issue.message}`} className={`quality-issue quality-${issue.severity}`}><span>{issue.severity}</span><strong>{issue.code}</strong><p>{issue.message}</p></div>)}</div>
            </div>
          ) : null}

          {/* Promotion gate */}
          {promotionGate ? (
            <div className="promotion-panel">
              <div className="stress-summary-grid">
                <div className="optimization-best"><span>晋级决策</span><strong>{promotionGate.decision.toUpperCase()}</strong><p>{promotionGate.next_stage}</p></div>
                <div className="optimization-best"><span>核心 Sharpe</span><strong>{promotionGate.backtest_summary.sharpe_ratio.toFixed(2)}</strong><p>MDD {promotionGate.backtest_summary.max_drawdown_pct.toFixed(2)}%</p></div>
                <div className="optimization-best"><span>Manifest</span><strong>{promotionGate.manifest_id.slice(0, 8)}</strong><p>{promotionGate.manifest_path || 'not persisted'}</p></div>
                <div className="optimization-best"><span>实验</span><strong>{promotionGate.experiment_record.experiment_name ?? '-'}</strong></div>
              </div>
              <div className="promotion-gate-list">{promotionGate.gates.map((g) => <div key={g.name} className={gateClass(g.status)}><span>{g.status.toUpperCase()}</span><strong>{g.name}</strong><p>{g.message}</p></div>)}</div>
              <div className="optimization-recommendations">{promotionGate.recommendations.map((r, i) => <p key={i}>{r}</p>)}</div>
            </div>
          ) : null}
        </section>

        <section className="metrics-grid">
          {metricCards.length > 0 ? metricCards.map((card) => <article key={card.label} className={metricClass(card.tone)}><span>{card.label}</span><strong>{card.value}</strong></article>) : (
            <article className="panel metrics-placeholder"><h3>回测结果会显示在这里</h3><p>运行单策略或组合回测获取绩效卡片</p></article>
          )}
        </section>

        {reportSections.length > 0 ? (
          <section className="report-stack">
            {reportSections.map((section) => (
              <article key={section.title} className="panel report-section">
                <div className="report-section-header"><span className="report-priority">{section.priority}</span><div><h3>{section.title}</h3>{section.subtitle ? <p>{section.subtitle}</p> : null}</div></div>
                <div className="report-metrics">{section.metrics.map((m) => <div key={m.label} className={reportMetricClass(m.tone)}><span>{m.label}</span><strong>{m.display}</strong></div>)}</div>
              </article>
            ))}
          </section>
        ) : null}

        {optimizationHints.length > 0 ? (
          <section className="panel insight-panel">
            <div className="panel-header"><h3>优化优先级</h3><span>{optimizationHints.length} 条</span></div>
            <div className="hint-list">{optimizationHints.map((hint, i) => <div key={`${hint.severity}-${i}`} className={hintClass(hint.severity)}><span>{hint.severity}</span><p>{hint.message}</p></div>)}</div>
          </section>
        ) : null}

        <div className="charts-grid">
          <LineChart title="权益曲线" points={chart?.equity ?? []} accentClass="line-accent" />
          <LineChart title="回撤曲线" points={chart?.drawdown ?? []} accentClass="line-accent-secondary" />
          <LineChart title="换手率" points={chart?.turnover ?? []} accentClass="line-accent-muted" />
          <LineChart title="动态杠杆" points={chart?.leverage ?? []} accentClass="line-accent-risk" />
        </div>

        <CandleChart candles={chart?.candles ?? []} markers={chart?.markers ?? []} />

        {(drawdownPeriods.length > 0 || monthlyReturns.length > 0) ? (
          <section className="analysis-grid">
            <article className="panel table-panel">
              <div className="panel-header"><h3>Top 回撤区间</h3><span>按深度排序</span></div>
              <div className="detail-table">{drawdownPeriods.map((item, i) => <div key={`${item.start_time}-${i}`} className="detail-row drawdown-row"><span>{formatTimestamp(item.start_time)} - {formatTimestamp(item.end_time)}</span><span>{item.depth_pct.toFixed(2)}% · {item.duration_bars} bars</span></div>)}</div>
            </article>
            <article className="panel table-panel">
              <div className="panel-header"><h3>月度收益</h3><span>最近 {monthlyReturns.length} 月</span></div>
              <div className="monthly-grid">{monthlyReturns.map((item) => <div key={item.period} className={item.return_pct >= 0 ? 'month-cell month-up' : 'month-cell month-down'}><span>{item.period}</span><strong>{item.return_pct.toFixed(2)}%</strong></div>)}</div>
            </article>
          </section>
        ) : null}

        <section className="panel detail-panel">
          <div className="panel-header"><h3>运行详情</h3><span className={`status-tag ${viewModel.statusTone}`}>{run?.status ?? 'idle'}</span></div>
          <div className="detail-grid">
            <div><h4>策略表现</h4><div className="detail-table">{(run?.strategy_details ?? []).map((item) => <div key={String(item.strategy_id)} className="detail-row"><span>{String(item.display_name)}</span><span>{Number(item.total_return_pct ?? 0).toFixed(2)}%</span></div>)}</div></div>
            <div><h4>最新组合权重</h4><div className="detail-table">{(run?.latest_weights ?? []).map((item) => <div key={String(item.strategy_id)} className="detail-row"><span>{String(item.display_name)}</span><span>{(Number(item.weight ?? 0) * 100).toFixed(2)}%</span></div>)}</div></div>
          </div>
        </section>
      </section>
    </main>
  );
}
