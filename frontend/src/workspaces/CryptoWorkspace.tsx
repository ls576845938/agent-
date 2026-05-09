import {FormEvent, useEffect, useMemo, useState} from 'react';

import type {ChartSeriesPayload, DataSyncRunResponse, DatabaseStatusResponse, KlinePreviewResponse, RunStatusResponse, SchedulerStatusResponse, StrategyInfo} from '../lib/view-model';
import {buildPortfolioRequest, buildSingleRequest, createRunViewModel, humanizeError, summarizeMetrics} from '../lib/view-model';
import {buildDateBoundary, diagnosticsList} from '../lib/utils';
import {apiGet, apiPost} from '../lib/api';
import type {CostStressResponse, DataQualityResponse, DrawdownPeriod, FormState, MvpStep, OptimizationHint, PeriodReturn, PortfolioOptimizationResponse, PromotionGateResponse, ReportSection, StrategyOptimizationResponse, WalkForwardResponse} from '../lib/shared-types';
import {defaultOptimizationFramework} from '../lib/shared-types';

import BacktestForm from './crypto/BacktestForm';
import DataManager from './crypto/DataManager';
import type {DataFormState} from './crypto/DataManager';
import OptimizationPanel from './crypto/OptimizationPanel';
import ResultsPanel from './crypto/ResultsPanel';

type Mode = 'single' | 'portfolio';

const defaultForm: FormState = {
  source: 'fixture', symbol: 'BTCUSDT', interval: '1h',
  startDate: '2024-01-01', endDate: '2024-02-15',
  capital: 100000, commissionRate: 0.0004, slippage: 4,
  leverage: 1, positionBasis: 'equity', strategyId: 'trend_macd', dataDbPath: '',
};

const defaultDataForm: DataFormState = {
  symbol: 'BTCUSDT', interval: '1m',
  startDate: '2024-01-01', endDate: '2024-01-03', dbPath: '',
};

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
      apiGet<DatabaseStatusResponse>(`/api/data/database?${baseParams.toString()}`),
      apiGet<KlinePreviewResponse>(`/api/data/klines?${previewParams.toString()}`),
      apiGet<DataSyncRunResponse[]>(`/api/data/sync-runs?${runsParams.toString()}`),
      apiGet<SchedulerStatusResponse>('/api/data/scheduler'),
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
    const gateFails = (promotionGate?.gates ?? []).filter((g: {status: string}) => g.status === 'fail').length;
    const gateWarns = (promotionGate?.gates ?? []).filter((g: {status: string}) => g.status === 'warn').length;
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
      const nextRun = await apiPost<RunStatusResponse>(endpoint, payload);
      setRun(nextRun);
      if (nextRun.status === 'completed') {
        const nextChart = await apiGet<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
        setChart(nextChart);
      } else { setChart(null); setError(nextRun.error ?? '运行失败'); }
    } catch (e) { setError(humanizeError(e)); setChart(null); }
    finally { setLoading(false); }
  };

  const handleMvpAcceptance = async () => {
    setMvpLoading(true); setMvpMessage('MVP 验收：数据质量检查中...'); setError('');
    try {
      const quality = await apiPost<DataQualityResponse>('/api/data/quality', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        data_db_path: form.dataDbPath,
      });
      setDataQuality(quality);
      setDataQualityMessage(`数据质量 Score ${quality.quality_score.toFixed(0)}，覆盖 ${quality.coverage_pct.toFixed(2)}%`);
      if (!quality.is_usable) throw new Error('数据质量阻断级问题');

      setMvpMessage('回测运行中...');
      const endpoint = mode === 'single' ? '/api/backtests/single' : '/api/backtests/portfolio';
      const payload = mode === 'single' ? {...buildSingleRequest(form), strategy_params: optimizedStrategyParams ?? {}} : buildPortfolioRequest(form, weightMap);
      const nextRun = await apiPost<RunStatusResponse>(endpoint, payload);
      setRun(nextRun);
      if (nextRun.status !== 'completed') throw new Error(nextRun.error ?? '回测失败');
      const nextChart = await apiGet<ChartSeriesPayload>(`/api/runs/${nextRun.run_id}/chart`);
      setChart(nextChart);

      setMvpMessage('准入门评估中...');
      const gate = await apiPost<PromotionGateResponse>('/api/research/promotion-gate', buildPromotionGateRequest());
      setPromotionGate(gate);
      setPromotionGateMessage(`准入门 Decision ${gate.decision.toUpperCase()}，下一阶段 ${gate.next_stage}`);
      setMvpMessage(`MVP 验收完成：${gate.decision.toUpperCase()}`);
    } catch (e) { const msg = humanizeError(e); setMvpMessage(msg); setError(msg); }
    finally { setMvpLoading(false); }
  };

  const handlePriorityOptimization = async () => {
    setOptimizationLoading(true); setOptimizationMessage(''); setError('');
    try {
      const result = await apiPost<StrategyOptimizationResponse>('/api/backtests/optimize', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, max_candidates: 12,
      });
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
      const result = await apiPost<CostStressResponse>('/api/backtests/cost-stress', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, strategy_params: optimizedStrategyParams ?? {},
      });
      setCostStress(result);
      setCostStressMessage(`压力测试完成：${result.survival_rate_pct.toFixed(0)}% 生存率`);
    } catch (e) { setCostStressMessage(humanizeError(e)); }
    finally { setCostStressLoading(false); }
  };

  const handleWalkForward = async () => {
    setWalkForwardLoading(true); setWalkForwardMessage(''); setError('');
    try {
      const result = await apiPost<WalkForwardResponse>('/api/backtests/walk-forward', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_id: form.strategyId, strategy_params: optimizedStrategyParams ?? {},
      });
      setWalkForward(result);
      setWalkForwardMessage(`Walk-forward: OOS pass rate ${result.stability.pass_rate_pct.toFixed(0)}%`);
    } catch (e) { setWalkForwardMessage(humanizeError(e)); }
    finally { setWalkForwardLoading(false); }
  };

  const handlePortfolioOptimization = async () => {
    setPortfolioOptimizationLoading(true); setPortfolioOptimizationMessage(''); setError('');
    try {
      const normalized = Object.fromEntries(Object.entries(weightMap).filter(([, w]) => w > 0));
      const result = await apiPost<PortfolioOptimizationResponse>('/api/backtests/portfolio-optimize', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        capital: form.capital, commission_rate: form.commissionRate,
        slippage: form.slippage, leverage: form.leverage,
        position_basis: form.positionBasis, data_db_path: form.dataDbPath,
        strategy_ids: Object.keys(normalized),
        baseline_weights: Object.values(normalized),
      });
      setPortfolioOptimization(result);
      setPortfolioOptimizationMessage(`组合优化完成：Sharpe delta ${result.improvement.sharpe_delta.toFixed(2)}`);
    } catch (e) { setPortfolioOptimizationMessage(humanizeError(e)); }
    finally { setPortfolioOptimizationLoading(false); }
  };

  const handleDataQuality = async () => {
    setDataQualityLoading(true); setDataQualityMessage(''); setError('');
    try {
      const result = await apiPost<DataQualityResponse>('/api/data/quality', {
        source: form.source, symbol: form.symbol, interval: form.interval,
        start: buildDateBoundary(form.startDate, 'start', form.interval),
        end: buildDateBoundary(form.endDate, 'end', form.interval),
        data_db_path: form.dataDbPath,
      });
      setDataQuality(result);
      setDataQualityMessage(`数据质量 Score ${result.quality_score.toFixed(0)}，覆盖 ${result.coverage_pct.toFixed(2)}%`);
    } catch (e) { setDataQualityMessage(humanizeError(e)); }
    finally { setDataQualityLoading(false); }
  };

  const handlePromotionGate = async () => {
    setPromotionGateLoading(true); setPromotionGateMessage(''); setError('');
    try {
      const result = await apiPost<PromotionGateResponse>('/api/research/promotion-gate', buildPromotionGateRequest());
      setPromotionGate(result);
      setPromotionGateMessage(`准入门 Decision ${result.decision.toUpperCase()}，下一阶段 ${result.next_stage}`);
    } catch (e) { setPromotionGateMessage(humanizeError(e)); }
    finally { setPromotionGateLoading(false); }
  };

  const handleDataSync = async () => {
    setDataLoading(true); setDataMessage(''); setError('');
    try {
      const nextRun = await apiPost<DataSyncRunResponse>('/api/data/sync', {
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval,
        start: buildDateBoundary(dataForm.startDate, 'start', dataForm.interval),
        end: buildDateBoundary(dataForm.endDate, 'end', dataForm.interval),
        db_path: dataForm.dbPath, limit: 1000, closed_only: true,
      });
      setDataMessage(`下载完成：写入 ${nextRun.rows_written} K 线`);
      setForm((c) => ({...c, source: 'sqlite', symbol: dataForm.symbol, interval: dataForm.interval, startDate: dataForm.startDate, endDate: dataForm.endDate, dataDbPath: dataForm.dbPath}));
      await refreshDataPanel(dataForm);
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleUpdateLatest = async () => {
    setDataLoading(true); setDataMessage(''); setError('');
    try {
      const nextRun = await apiPost<DataSyncRunResponse>('/api/data/update-latest', {
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval, db_path: dataForm.dbPath, lookback_days: 30, limit: 1000,
      });
      setDataMessage(`增量更新完成：写入 ${nextRun.rows_written} K 线`);
      setForm((c) => ({...c, source: 'sqlite', symbol: dataForm.symbol, interval: dataForm.interval, dataDbPath: dataForm.dbPath}));
      await refreshDataPanel(dataForm);
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleStartScheduler = async () => {
    setDataLoading(true); setDataMessage('');
    try {
      const nextStatus = await apiPost<SchedulerStatusResponse>('/api/data/scheduler/start', {
        exchange: 'binance_spot', symbol: dataForm.symbol, interval: dataForm.interval, db_path: dataForm.dbPath, lookback_days: 30, interval_seconds: 86400, run_immediately: true,
      });
      setScheduler(nextStatus); setDataMessage('日更任务已启动');
    } catch (e) { setDataMessage(humanizeError(e)); }
    finally { setDataLoading(false); }
  };

  const handleStopScheduler = async () => {
    setDataLoading(true); setDataMessage('');
    try {
      const nextStatus = await apiPost<SchedulerStatusResponse>('/api/data/scheduler/stop');
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

  const handleChangeForm = (next: FormState) => {
    if (next.strategyId !== form.strategyId) {
      setOptimizedStrategyParams(null);
    }
    setForm(next);
  };

  const handleChangeDataForm = (next: DataFormState) => {
    setDataForm(next);
    setForm((c) => ({...c, dataDbPath: next.dbPath}));
  };

  return (
    <main className="layout">
      <aside className="side-column">
        <BacktestForm
          form={form}
          mode={mode}
          strategies={strategies}
          weightMap={weightMap}
          loading={loading}
          optimizedStrategyParams={optimizedStrategyParams}
          onChangeForm={handleChangeForm}
          onChangeMode={setMode}
          onChangeWeightMap={setWeightMap}
          onSubmit={handleSubmit}
        />
        <DataManager
          dataForm={dataForm}
          database={database}
          klinePreview={klinePreview}
          syncRuns={syncRuns}
          scheduler={scheduler}
          dataLoading={dataLoading}
          dataMessage={dataMessage}
          onChangeDataForm={handleChangeDataForm}
          onRefresh={() => refreshDataPanel(dataForm)}
          onSync={handleDataSync}
          onUpdateLatest={handleUpdateLatest}
          onStartScheduler={handleStartScheduler}
          onStopScheduler={handleStopScheduler}
        />
      </aside>

      <section className="results-column">
        <ResultsPanel
          mvpSteps={mvpSteps}
          mvpDoneCount={mvpDoneCount}
          mvpLoading={mvpLoading}
          mvpMessage={mvpMessage}
          disableMvp={mvpLoading || loading}
          error={error}
          promotionGate={promotionGate}
          metricCards={metricCards}
          reportSections={reportSections}
          optimizationHints={optimizationHints}
          chart={chart}
          run={run}
          viewModel={viewModel}
          drawdownPeriods={drawdownPeriods}
          monthlyReturns={monthlyReturns}
          onMvpAcceptance={handleMvpAcceptance}
        >
          <section className="panel optimization-panel">
            <OptimizationPanel
              optimization={optimization}
              optimizationLoading={optimizationLoading}
              optimizationMessage={optimizationMessage}
              costStress={costStress}
              costStressLoading={costStressLoading}
              costStressMessage={costStressMessage}
              walkForward={walkForward}
              walkForwardLoading={walkForwardLoading}
              walkForwardMessage={walkForwardMessage}
              portfolioOptimization={portfolioOptimization}
              portfolioOptimizationLoading={portfolioOptimizationLoading}
              portfolioOptimizationMessage={portfolioOptimizationMessage}
              dataQuality={dataQuality}
              dataQualityLoading={dataQualityLoading}
              dataQualityMessage={dataQualityMessage}
              promotionGate={promotionGate}
              promotionGateLoading={promotionGateLoading}
              promotionGateMessage={promotionGateMessage}
              optimizationFramework={optimizationFramework}
              optimizedStrategyParams={optimizedStrategyParams}
              onOptimize={handlePriorityOptimization}
              onCostStress={handleCostStress}
              onWalkForward={handleWalkForward}
              onPortfolioOptimize={handlePortfolioOptimization}
              onDataQuality={handleDataQuality}
              onPromotionGate={handlePromotionGate}
              onApplyWeights={handleApplyPortfolioWeights}
            />
          </section>
        </ResultsPanel>
      </section>
    </main>
  );
}
