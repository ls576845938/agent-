import type {BtcScalpingResearchBacktest, BtcScalpingResearchBacktestReport, BtcTrendForwardSeriesPoint, BtcTrendForwardStatusResponse, StrategyOptimizationResponse, CostStressResponse, WalkForwardResponse, PortfolioOptimizationResponse, DataQualityResponse, PromotionGateResponse, OptimizationFrameworkItem, CryptoClosureResponse, TaskResponse} from '../../lib/shared-types';
import {formatOptimizationScore, formatParams, formatTimestamp, formatPrice, scenarioClass, gateClass} from '../../lib/utils';
import {ModuleStateCard} from '../../components/ModuleStateCard';

function researchTrackLabel(value: BtcScalpingResearchBacktestReport['recommended_research_track']): string {
  if (value === 'five_minute_drift_guarded_intraday') return '5m drift-guarded';
  if (value === 'one_minute_proxy_scalping') return '1m proxy scalping';
  return '无可用轨道';
}

function metricNumber(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-';
}

function metricText(track: BtcScalpingResearchBacktest | null, key: keyof BtcScalpingResearchBacktest['metrics'], label: string): string {
  const value = track?.metrics[key];
  if (typeof value !== 'number') return `${label} -`;
  const metricKey = String(key);
  const digits = metricKey === 'profit_factor' ? 3 : metricKey === 'hit_rate' || metricKey.endsWith('_pass_rate') ? 1 : 2;
  const display = metricKey === 'hit_rate' || metricKey.endsWith('_pass_rate') ? `${(value * 100).toFixed(digits)}%` : value.toFixed(digits);
  return `${label} ${display}`;
}

function ScalpingTrackCard({track, preferred = false}: {track: BtcScalpingResearchBacktest; preferred?: boolean}) {
  const tone = track.gate_passed ? 'good' : 'bad';
  const metrics = track.metrics;
  const blockers = track.blockers.slice(0, 3);
  return (
    <article className={`scalping-track scalping-track-${tone}`}>
      <div className="scalping-track-head">
        <div>
          <span>{preferred ? '推荐' : '观测'}</span>
          <strong>{track.label}</strong>
        </div>
        <span className={`status-tag ${tone}`}>{track.gate_status}</span>
      </div>
      <div className="scalping-metrics">
        <div><span>Trades</span><strong>{metrics.trade_count ?? '-'}</strong></div>
        <div><span>Fills</span><strong>{metrics.fill_count ?? '-'}</strong></div>
        <div><span>PF</span><strong>{metricNumber(metrics.profit_factor, 3)}</strong></div>
        <div><span>Return</span><strong>{metricNumber(metrics.total_return_pct, 2)}%</strong></div>
        <div><span>WF</span><strong>{typeof metrics.walk_forward_pass_rate === 'number' ? `${(metrics.walk_forward_pass_rate * 100).toFixed(0)}%` : '-'}</strong></div>
        <div><span>Regime</span><strong>{typeof metrics.regime_pass_rate === 'number' ? `${(metrics.regime_pass_rate * 100).toFixed(0)}%` : '-'}</strong></div>
      </div>
      <div className="scalping-lock-row">
        <span>manifest {track.manifest.complete ? 'complete' : 'missing'}</span>
        <span>paper {track.manifest.paper_queue ?? 'LOCKED'}</span>
        <span>live {track.manifest.live ?? 'FROZEN'}</span>
      </div>
      {blockers.length ? (
        <div className="scalping-blockers">
          {blockers.map((blocker) => <p key={blocker}>{blocker}</p>)}
        </div>
      ) : <p className="scalping-pass-note">internal research gate passed</p>}
    </article>
  );
}

function pctText(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)}%` : '-';
}

function priceText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatPrice(value) : '-';
}

function exposureText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  if (value <= 0) return '空仓';
  if (value >= 0.99) return '满仓 BTC';
  return `${(value * 100).toFixed(0)}% BTC`;
}

function signalText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return value > 0 ? '动量为正' : '动量非正';
}

function shortDate(value: string | undefined): string {
  if (!value) return '-';
  return value.slice(0, 10);
}

function trendTone(report: BtcTrendForwardStatusResponse | null): 'good' | 'bad' | 'neutral' {
  if (!report) return 'neutral';
  if (report.status !== 'ok' || report.missing_sources.length) return 'bad';
  if (report.gates.live_order_allowed || report.gates.order_endpoint_used || report.gates.private_endpoint_used) return 'bad';
  return 'good';
}

function milestoneText(value: boolean | undefined): string {
  return value ? '已满' : '未满';
}

function cycleText(value: string | undefined): string {
  if (!value) return '-';
  if (value === 'SKIPPED_ALREADY_COMPLETED') return '今日已处理';
  if (value === 'WROTE_NEW_OBSERVATION') return '已写入新观察';
  return value;
}

function validationText(decision: string | undefined, status: string | undefined): string {
  const value = decision || status || '';
  if (!value) return '-';
  if (value.includes('backtest_evidence_passed')) return '回测证据通过，仍需人工复核';
  if (value.includes('strategy_backtest_validated')) return '策略验证已完成';
  return value;
}

function freezeText(volatilityStatus: string | undefined, hftStatus: string | undefined): string {
  const vol = volatilityStatus === 'frozen_deferred_not_primary' ? '波动率仓位已冻结' : `vol ${volatilityStatus ?? '-'}`;
  const hft = hftStatus === 'frozen_rejected_as_high_frequency' ? '5m 高频已冻结' : `5m ${hftStatus ?? '-'}`;
  return `${vol} · ${hft}`;
}

function buildEquityPath(series: BtcTrendForwardSeriesPoint[], field: 'strategy_equity' | 'buy_hold_equity', width = 520, height = 160): string {
  const values = series.flatMap((point) => [point.strategy_equity, point.buy_hold_equity]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const fieldValues = series.map((point) => point[field]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (values.length < 2 || fieldValues.length < 2) return '';
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const xStep = series.length > 1 ? width / (series.length - 1) : width;
  return series.map((point, index) => {
    const rawValue = point[field];
    const value = typeof rawValue === 'number' && Number.isFinite(rawValue) ? rawValue : fieldValues[fieldValues.length - 1];
    const x = index * xStep;
    const y = height - ((value - min) / span) * height;
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
}

function TrendForwardChart({series}: {series: BtcTrendForwardSeriesPoint[]}) {
  const visibleSeries = series.slice(-420);
  const strategyPath = buildEquityPath(visibleSeries, 'strategy_equity');
  const buyHoldPath = buildEquityPath(visibleSeries, 'buy_hold_equity');
  if (!strategyPath || !buyHoldPath) {
    return <div className="trend-forward-chart-empty">等待足够曲线数据</div>;
  }
  const first = visibleSeries[0];
  const last = visibleSeries[visibleSeries.length - 1];
  return (
    <div className="trend-forward-chart">
      <svg viewBox="0 0 520 160" role="img" aria-label="BTC trend strategy equity versus buy and hold">
        <line x1="0" y1="128" x2="520" y2="128" />
        <path className="trend-line-buyhold" d={buyHoldPath} />
        <path className="trend-line-strategy" d={strategyPath} />
      </svg>
      <div className="trend-forward-chart-legend">
        <span><i className="legend-strategy" />趋势策略</span>
        <span><i className="legend-buyhold" />买入持有</span>
        <span>{shortDate(first?.timestamp)} - {shortDate(last?.timestamp)}</span>
      </div>
    </div>
  );
}

function TrendForwardPanel({
  report,
  loading,
  message,
  onRefresh,
}: {
  report: BtcTrendForwardStatusResponse | null;
  loading: boolean;
  message: string;
  onRefresh: () => void;
}) {
  const tone = trendTone(report);
  const currentSignal = report?.current_signal;
  const forward = report?.forward_observation;
  const strategy = report?.strategy;
  const gates = report?.gates;
  const milestones = forward?.milestone_progress ?? {};
  const latestTarget = forward?.targets?.[forward.targets.length - 1];
  const latestSnapshot = forward?.snapshots?.[forward.snapshots.length - 1];
  return (
    <div className="trend-forward-panel" data-testid="btc-trend-forward-panel">
      <div className="panel-header">
        <div>
          <h2>BTC 日线趋势观察</h2>
          <p className="panel-subtitle">主线策略 t01：365 日时间序列动量，T+1 生效；这里只展示前向观察和研究证据，不代表实盘就绪。</p>
        </div>
        <span className={`status-tag ${tone}`}>{report?.daily_run.status ?? (loading ? 'loading' : 'missing')}</span>
      </div>

      <div className="stress-summary-grid trend-forward-summary-grid">
        <div className="optimization-best">
          <span>当前目标仓位</span>
          <strong>{exposureText(currentSignal?.target_exposure)}</strong>
          <p>{signalText(currentSignal?.raw_signal)} · close {priceText(currentSignal?.close)}</p>
        </div>
        <div className="optimization-best">
          <span>前向观察</span>
          <strong>{forward?.observation_days ?? 0} / {forward?.minimum_complete_days ?? 30} 天</strong>
          <p>30/60/90：{milestoneText(milestones['30'])} / {milestoneText(milestones['60'])} / {milestoneText(milestones['90'])}</p>
        </div>
        <div className="optimization-best">
          <span>策略验证</span>
          <strong>Sharpe {metricNumber(strategy?.selected_sharpe_ratio, 2)}</strong>
          <p>收益 {pctText(strategy?.selected_total_return_pct)} · MDD {pctText(strategy?.selected_max_drawdown_abs_pct)}</p>
        </div>
        <div className="optimization-best">
          <span>买入持有基准</span>
          <strong>Sharpe {metricNumber(strategy?.buy_hold_sharpe_ratio, 2)}</strong>
          <p>收益 {pctText(strategy?.buy_hold_total_return_pct)} · MDD {pctText(strategy?.buy_hold_max_drawdown_abs_pct)}</p>
        </div>
      </div>

      <TrendForwardChart series={report?.charts.strategy_series ?? []} />

      <div className="trend-forward-meta-grid">
        <div><span>日线样本</span><strong>{report?.daily_run.daily_rows ?? 0}</strong><p>{shortDate(report?.daily_run.sample_start)} - {shortDate(report?.daily_run.sample_end)}</p></div>
        <div><span>信号日</span><strong>{shortDate(currentSignal?.signal_timestamp)}</strong><p>生效 {shortDate(currentSignal?.effective_timestamp)}</p></div>
        <div><span>观察状态</span><strong>{forward?.status ?? '-'}</strong><p>{cycleText(report?.daily_run.roll_cycle_status || report?.daily_run.roll_status)}</p></div>
        <div><span>账本</span><strong>{forward?.target_position_count ?? 0} targets / {forward?.simulated_fill_count ?? 0} fills</strong><p>last {shortDate(latestSnapshot?.timestamp ?? latestTarget?.timestamp)}</p></div>
        <div><span>费用与回撤</span><strong>{pctText(forward?.total_return_pct, 2)}</strong><p>MDD {pctText(forward?.max_drawdown_abs_pct, 2)}</p></div>
        <div><span>交易边界</span><strong>{gates?.live_order_allowed ? '异常' : '未开放实盘'}</strong><p>private {gates?.private_endpoint_used ? 'on' : 'off'} · order {gates?.order_endpoint_used ? 'on' : 'off'}</p></div>
      </div>

      <div className="trend-forward-ledger-list">
        <div><span>reason</span><strong>{currentSignal?.reason || latestTarget?.reason || '-'}</strong></div>
        <div><span>validation</span><strong>{validationText(strategy?.validation_decision, strategy?.validation_status)}</strong></div>
        <div><span>freeze</span><strong>{freezeText(gates?.volatility_branch_status, gates?.hft_freeze_status)}</strong></div>
      </div>

      <div className="scalping-action-row">
        <button type="button" className="secondary-button" disabled={loading} onClick={onRefresh}>{loading ? '刷新中...' : '刷新趋势观察'}</button>
        <span>{message || report?.generated_at || ''}</span>
      </div>
    </div>
  );
}

interface OptimizationPanelProps {
  optimization: StrategyOptimizationResponse | null;
  optimizationLoading: boolean;
  optimizationMessage: string;
  costStress: CostStressResponse | null;
  costStressLoading: boolean;
  costStressMessage: string;
  walkForward: WalkForwardResponse | null;
  walkForwardLoading: boolean;
  walkForwardMessage: string;
  portfolioOptimization: PortfolioOptimizationResponse | null;
  portfolioOptimizationLoading: boolean;
  portfolioOptimizationMessage: string;
  dataQuality: DataQualityResponse | null;
  dataQualityLoading: boolean;
  dataQualityMessage: string;
  promotionGate: PromotionGateResponse | null;
  promotionGateLoading: boolean;
  promotionGateMessage: string;
  cryptoClosure: CryptoClosureResponse | null;
  cryptoClosureTask: TaskResponse | null;
  cryptoClosureLoading: boolean;
  cryptoClosureMessage: string;
  scalpingResearch: BtcScalpingResearchBacktestReport | null;
  scalpingResearchLoading: boolean;
  scalpingResearchMessage: string;
  trendForward: BtcTrendForwardStatusResponse | null;
  trendForwardLoading: boolean;
  trendForwardMessage: string;
  optimizationFramework: OptimizationFrameworkItem[];
  optimizedStrategyParams: Record<string, number> | null;
  onCryptoClosure: () => void;
  onRefreshScalpingResearch: () => void;
  onRefreshTrendForward: () => void;
  onOptimize: () => void;
  onCostStress: () => void;
  onWalkForward: () => void;
  onPortfolioOptimize: () => void;
  onDataQuality: () => void;
  onPromotionGate: () => void;
  onApplyWeights: () => void;
}

export default function OptimizationPanel({
  optimization, optimizationLoading, optimizationMessage,
  costStress, costStressLoading, costStressMessage,
  walkForward, walkForwardLoading, walkForwardMessage,
  portfolioOptimization, portfolioOptimizationLoading, portfolioOptimizationMessage,
  dataQuality, dataQualityLoading, dataQualityMessage,
  promotionGate, promotionGateLoading, promotionGateMessage,
  cryptoClosure, cryptoClosureTask, cryptoClosureLoading, cryptoClosureMessage,
  scalpingResearch, scalpingResearchLoading, scalpingResearchMessage,
  trendForward, trendForwardLoading, trendForwardMessage,
  optimizationFramework, optimizedStrategyParams,
  onCryptoClosure,
  onRefreshScalpingResearch,
  onRefreshTrendForward,
  onOptimize, onCostStress, onWalkForward, onPortfolioOptimize,
  onDataQuality, onPromotionGate, onApplyWeights,
}: OptimizationPanelProps) {
  const promotionGates = promotionGate?.gates ?? [];
  const promotionRecommendations = promotionGate?.recommendations ?? [];
  const promotionSummary = promotionGate?.backtest_summary;
  const btcOutcome = cryptoClosure
    ? cryptoClosure.blockers.length > 0 ? 'BLOCKED' : cryptoClosure.decision === 'pass' ? 'PASS' : 'BLOCKED'
    : cryptoClosureTask
      ? cryptoClosureTask.status.toUpperCase()
      : promotionGate
        ? promotionGate.decision === 'pass' ? 'PASS' : 'BLOCKED'
        : dataQuality?.is_usable ? 'PASS' : 'BLOCKED';
  const btcTone = cryptoClosure
    ? (cryptoClosure.blockers.length > 0 || cryptoClosure.decision !== 'pass' ? 'bad' : 'good')
    : cryptoClosureTask
      ? (cryptoClosureTask.status === 'failed' ? 'bad' : cryptoClosureTask.status === 'completed' ? 'good' : 'neutral')
      : promotionGate
        ? (promotionGate.decision === 'pass' ? 'good' : 'bad')
        : dataQuality?.is_usable ? 'good' : 'bad';
  const btcReason = cryptoClosure
    ? cryptoClosure.blockers.length > 0
      ? cryptoClosure.blockers[0]
      : cryptoClosure.recommendations[0] ?? `${cryptoClosure.next_stage} 就绪`
    : cryptoClosureTask
      ? `${cryptoClosureTask.stage || cryptoClosureTask.status} · ${cryptoClosureTask.message || '运行中'}`
    : promotionGate
      ? promotionGates.find((gate) => gate.status !== 'pass')?.message ?? promotionRecommendations[0] ?? '等待闭环评估'
      : dataQuality?.issues?.[0]?.message ?? '等待数据质量与闭环结果';
  const btcMeta = [
    {label: '任务阶段', value: cryptoClosureTask ? (cryptoClosureTask.stage || cryptoClosureTask.status) : cryptoClosure ? cryptoClosure.decision : 'WAITING'},
    {label: '任务进度', value: cryptoClosureTask ? `${cryptoClosureTask.progress}%` : '0%'},
    {label: '数据完整性', value: cryptoClosure ? String(cryptoClosure.data_integrity.status ?? '-').toUpperCase() : dataQuality ? (dataQuality.is_usable ? 'PASS' : 'BLOCKED') : 'WAITING'},
    {label: '候选数', value: cryptoClosure ? String(cryptoClosure.candidate_screen.candidate_count ?? 0) : promotionGate ? String(promotionGates.length) : '0'},
    {label: '下一阶段', value: cryptoClosure?.next_stage ?? promotionGate?.next_stage ?? '研究'},
    {label: '覆盖周期', value: cryptoClosure?.target_intervals.join(' / ') ?? '1m / 5m / 15m / 1h / 4h / 1d'},
  ];
  const scalpingOneMinute = scalpingResearch?.backtests.one_minute_proxy_scalping ?? null;
  const scalpingFiveMinute = scalpingResearch?.backtests.five_minute_drift_guarded_intraday ?? null;
  const recommendedTrack = scalpingResearch ? researchTrackLabel(scalpingResearch.recommended_research_track) : '等待加载';
  return (
    <>
      <ModuleStateCard
        id="btc"
        title="BTC"
        status={btcOutcome}
        tone={btcTone}
        reason={btcReason}
        meta={btcMeta}
        hint="闭环数据、成本压力、滚动验证与晋级门统一汇总"
        actions={[{
          label: cryptoClosureLoading ? 'BTC 生产闭环运行中...' : '启动 BTC 生产闭环',
          onClick: () => { void onCryptoClosure(); },
          disabled: cryptoClosureLoading,
          variant: 'primary',
        }]}
      />

      <TrendForwardPanel
        report={trendForward}
        loading={trendForwardLoading}
        message={trendForwardMessage}
        onRefresh={onRefreshTrendForward}
      />

      <div className="scalping-research-panel" data-testid="btc-scalping-research-panel">
        <div className="panel-header">
          <div>
            <h2>BTC 剥头皮研究回测</h2>
            <p className="panel-subtitle">{scalpingResearch?.operator_summary.current_research_answer ?? '等待最新研究回测报告'}</p>
          </div>
          <span>{scalpingResearch?.status ?? 'loading'}</span>
        </div>
        <div className="stress-summary-grid scalping-summary-grid">
          <div className="optimization-best"><span>推荐轨道</span><strong>{recommendedTrack}</strong><p>{scalpingResearch?.decision ?? '-'}</p></div>
          <div className="optimization-best"><span>5m 研究门</span><strong>{scalpingFiveMinute?.gate_passed ? '通过' : '未通过'}</strong><p>{metricText(scalpingFiveMinute, 'profit_factor', 'PF')}</p></div>
          <div className="optimization-best"><span>1m Proxy</span><strong>{scalpingOneMinute?.gate_passed ? '通过' : '失败'}</strong><p>{metricText(scalpingOneMinute, 'mean_trade_return_bps', '均值 bps')}</p></div>
          <div className="optimization-best"><span>交易状态</span><strong>{scalpingResearch?.guardrails.paper_queue ?? 'LOCKED'} / {scalpingResearch?.guardrails.live ?? 'FROZEN'}</strong><p>broker {scalpingResearch?.guardrails.broker_calls_allowed ? 'on' : 'off'} · order {scalpingResearch?.guardrails.order_endpoints_allowed ? 'on' : 'off'}</p></div>
        </div>
        <div className="scalping-track-grid">
          {scalpingFiveMinute ? <ScalpingTrackCard track={scalpingFiveMinute} preferred /> : null}
          {scalpingOneMinute ? <ScalpingTrackCard track={scalpingOneMinute} /> : null}
        </div>
        <div className="scalping-action-row">
          <button type="button" className="secondary-button" disabled={scalpingResearchLoading} onClick={onRefreshScalpingResearch}>{scalpingResearchLoading ? '刷新中...' : '刷新研究报告'}</button>
          <span>{scalpingResearchMessage || scalpingResearch?.generated_at || ''}</span>
        </div>
      </div>

      <div className="panel-header"><h2>下一步优化框架</h2><span>{optimizationFramework[0]?.title ?? ''}</span></div>
      <div className="optimization-framework">
        {optimizationFramework.map((item) => (
          <div key={item.priority} className={`optimization-step optimization-${item.status}`}><span>{item.priority}</span><div><strong>{item.title}</strong><p>{item.reason}</p></div></div>
        ))}
      </div>
      <div className="optimization-actions">
        <button type="button" className="primary-button" disabled={cryptoClosureLoading} onClick={onCryptoClosure}>{cryptoClosureLoading ? 'BTC 生产闭环运行中...' : '启动 BTC 生产闭环'}</button>
        <button type="button" className="secondary-button" disabled={optimizationLoading} onClick={onOptimize}>{optimizationLoading ? '优化中...' : '运行优先优化'}</button>
        <button type="button" className="secondary-button" disabled={costStressLoading} onClick={onCostStress}>{costStressLoading ? '中...' : '成本压力测试'}</button>
        <button type="button" className="secondary-button" disabled={walkForwardLoading} onClick={onWalkForward}>{walkForwardLoading ? '中...' : '滚动验证'}</button>
        <button type="button" className="secondary-button" disabled={portfolioOptimizationLoading} onClick={onPortfolioOptimize}>{portfolioOptimizationLoading ? '中...' : '组合优化'}</button>
        <button type="button" className="secondary-button" disabled={dataQualityLoading} onClick={onDataQuality}>{dataQualityLoading ? '中...' : '数据质量'}</button>
        <button type="button" className="secondary-button" disabled={promotionGateLoading} onClick={onPromotionGate}>{promotionGateLoading ? '中...' : '研究准入门'}</button>
        {optimizedStrategyParams ? <span>已应用：{formatParams(optimizedStrategyParams)}</span> : null}
      </div>
      {cryptoClosureMessage ? <p className="data-message">{cryptoClosureMessage}</p> : null}
      {optimizationMessage ? <p className="data-message">{optimizationMessage}</p> : null}
      {costStressMessage ? <p className="data-message">{costStressMessage}</p> : null}
      {walkForwardMessage ? <p className="data-message">{walkForwardMessage}</p> : null}
      {portfolioOptimizationMessage ? <p className="data-message">{portfolioOptimizationMessage}</p> : null}
      {dataQualityMessage ? <p className="data-message">{dataQualityMessage}</p> : null}
      {promotionGateMessage ? <p className="data-message">{promotionGateMessage}</p> : null}

      {cryptoClosure ? (
        <div className="promotion-panel" data-testid="crypto-closure-panel">
          <div className="stress-summary-grid">
            <div className="optimization-best"><span>闭环状态</span><strong>{cryptoClosure.decision.toUpperCase()}</strong><p>{cryptoClosure.next_stage}</p></div>
            <div className="optimization-best"><span>数据完整性</span><strong>{String(cryptoClosure.data_integrity.status ?? '-').toUpperCase()}</strong><p>{cryptoClosure.target_intervals.join(' / ')}</p></div>
            <div className="optimization-best"><span>选中候选</span><strong>{cryptoClosure.selected_candidate?.strategy_id ?? '-'}</strong><p>{formatParams(cryptoClosure.selected_candidate?.parameters ?? {})}</p></div>
            <div className="optimization-best"><span>事件回测</span><strong>{Number(cryptoClosure.event_backtest.summary?.sharpe_ratio ?? 0).toFixed(2)} Sharpe</strong><p>收益 {Number(cryptoClosure.event_backtest.summary?.total_return_pct ?? 0).toFixed(2)}% · 交易 {Number(cryptoClosure.event_backtest.summary?.trade_count ?? 0)}</p></div>
            <div className="optimization-best"><span>成本压力</span><strong>{Number(cryptoClosure.cost_stress.survival_rate_pct ?? 0).toFixed(0)}%</strong><p>账本 {Number(cryptoClosure.cost_stress.ledger_consistency_pct ?? 0).toFixed(0)}%</p></div>
            <div className="optimization-best"><span>滚动验证</span><strong>{Number(cryptoClosure.walk_forward.stability?.fold_pass_rate_pct ?? cryptoClosure.walk_forward.stability?.pass_rate_pct ?? 0).toFixed(0)}%</strong><p>账本 {Number(cryptoClosure.walk_forward.stability?.ledger_consistency_pct ?? 0).toFixed(0)}%</p></div>
          </div>
          {(cryptoClosure.candidate_screen.candidates ?? []).length ? (
            <div className="optimization-table">
              {(cryptoClosure.candidate_screen.candidates ?? []).slice(0, 6).map((candidate) => (
                <div key={`${candidate.strategy_id}-${candidate.rank}`} className="optimization-row">
                  <span>#{candidate.rank}</span>
                  <span>{candidate.strategy_id}</span>
                  <span>{formatOptimizationScore(candidate.score)}</span>
                  <span>{Number(candidate.validation?.sharpe_ratio ?? 0).toFixed(2)} Sharpe</span>
                  <span>{Number(candidate.validation?.max_drawdown_pct ?? 0).toFixed(2)}% MDD</span>
                  <span>{formatParams(candidate.parameters)}</span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="promotion-gate-list">
            {cryptoClosure.blockers.map((blocker) => (
              <div key={blocker} className="promotion-gate promotion-fail"><span>阻塞</span><strong>{blocker}</strong><p>保持纸交易和实盘关闭。</p></div>
            ))}
            {!cryptoClosure.blockers.length ? <div className="promotion-gate promotion-pass"><span>通过</span><strong>无显式阻断</strong><p>仍需人工复核证据包。</p></div> : null}
          </div>
          <div className="optimization-recommendations">{cryptoClosure.recommendations.map((item, index) => <p key={index}>{item}</p>)}</div>
        </div>
      ) : null}

      {/* Optimization results */}
      {optimization?.best ? (
        <div className="optimization-result-grid">
          <div className="optimization-best"><span>最佳候选</span><strong>得分 {formatOptimizationScore(optimization.best.score)}</strong><p>{formatParams(optimization.best.parameters)}</p></div>
          <div className="optimization-best"><span>样本外表现</span><strong>Sharpe {optimization.best.validation.sharpe_ratio.toFixed(2)}</strong><p>收益 {optimization.best.validation.total_return_pct.toFixed(2)}% · MDD {optimization.best.validation.max_drawdown_pct.toFixed(2)}%</p></div>
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
            <div className="optimization-best"><span>最差场景</span><strong>{costStress.worst_case?.label ?? '-'}</strong><p>收益 {costStress.worst_case?.summary.total_return_pct.toFixed(2) ?? '-'}% · MDD {costStress.worst_case?.summary.max_drawdown_pct.toFixed(2) ?? '-'}%</p></div>
            <div className="optimization-best"><span>测试参数</span><strong>{costStress.strategy_id}</strong><p>{formatParams(costStress.strategy_params)}</p></div>
          </div>
          <div className="stress-table">
            {costStress.scenarios.map((scenario) => (
              <div key={scenario.name} className={scenarioClass(scenario.survives)}><span>{scenario.survives ? '通过' : '失败'}</span><span>{scenario.label}</span><span>{scenario.summary.total_return_pct.toFixed(2)}%</span><span>{scenario.summary.sharpe_ratio.toFixed(2)} Sharpe</span><span>{scenario.summary.max_drawdown_pct.toFixed(2)}% MDD</span></div>
            ))}
          </div>
          <div className="optimization-recommendations">{costStress.recommendations.map((r, i) => <p key={i}>{r}</p>)}</div>
        </div>
      ) : null}

      {/* Walk-forward results */}
      {walkForward ? (
        <div className="walk-panel">
          <div className="stress-summary-grid">
            <div className="optimization-best"><span>OOS 通过率</span><strong>{Number(walkForward.stability.pass_rate_pct ?? walkForward.stability.fold_pass_rate_pct ?? 0).toFixed(0)}%</strong><p>{walkForward.selected_priority}</p></div>
            <div className="optimization-best"><span>OOS 中位 Sharpe</span><strong>{Number(walkForward.stability.median_oos_sharpe ?? 0).toFixed(2)}</strong><p>平均收益 {Number(walkForward.stability.avg_oos_return_pct ?? 0).toFixed(2)}%</p></div>
            <div className="optimization-best"><span>参数稳定性</span><strong>{Number(walkForward.stability.parameter_stability_pct ?? 0).toFixed(0)}%</strong><p>最差 MDD {Number(walkForward.stability.worst_oos_drawdown_pct ?? 0).toFixed(2)}%</p></div>
          </div>
          <div className="walk-table">
            {(walkForward.windows ?? []).map((w) => (
              <div key={w.fold} className={`walk-row ${w.survives ? 'stress-pass' : 'stress-fail'}`}><span>W{w.fold}</span><span>{w.survives ? '通过' : '失败'}</span><span>{formatTimestamp(w.validation_start)} - {formatTimestamp(w.validation_end)}</span><span>{w.validation.total_return_pct.toFixed(2)}%</span><span>{w.validation.sharpe_ratio.toFixed(2)} Sharpe</span><span>{w.validation.max_drawdown_pct.toFixed(2)}% MDD</span><span>{formatParams(w.selected_params)}</span></div>
            ))}
          </div>
          <div className="regime-grid">
            {(walkForward.regimes ?? []).map((r) => (
              <div key={r.name} className={`regime-card ${r.survives ? 'stress-pass' : 'stress-fail'}`}><span>{r.survives ? '通过' : '失败'}</span><strong>{r.label}</strong><p>{r.coverage_pct.toFixed(0)}% K线 · 收益 {r.summary.total_return_pct.toFixed(2)}% · MDD {r.summary.max_drawdown_pct.toFixed(2)}%</p></div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Portfolio optimization results */}
      {portfolioOptimization ? (
        <div className="portfolio-opt-panel">
          <div className="stress-summary-grid">
            <div className="optimization-best"><span>优化后 Sharpe</span><strong>{portfolioOptimization.optimized_summary.sharpe_ratio.toFixed(2)}</strong><p>变化 {portfolioOptimization.improvement.sharpe_delta.toFixed(2)}</p></div>
            <div className="optimization-best"><span>优化后收益</span><strong>{portfolioOptimization.optimized_summary.total_return_pct.toFixed(2)}%</strong><p>基线 {portfolioOptimization.baseline_summary.total_return_pct.toFixed(2)}%</p></div>
            <div className="optimization-best"><span>风险状态</span><strong>{portfolioOptimization.risk_overlay.state}</strong><p>总曝险 x{portfolioOptimization.risk_overlay.suggested_gross_multiplier.toFixed(2)}</p></div>
          </div>
          <div className="portfolio-action-row">
            <button type="button" className="secondary-button" onClick={onApplyWeights}>应用建议权重</button>
          </div>
          <div className="portfolio-table">
            {portfolioOptimization.optimized_weight_rows.map((row) => (
              <div key={row.strategy_id} className="portfolio-row"><span>{row.display_name}</span><span>{row.baseline_weight_pct.toFixed(1)}% → {row.weight_pct.toFixed(1)}%</span></div>
            ))}
          </div>
          <div className="portfolio-split-grid">
            <div><h4>风险贡献</h4><div className="risk-list">{portfolioOptimization.risk_budget.risk_contributions.map((item) => <div key={item.strategy_id} className="risk-row"><span>{item.strategy_id}</span><span>{item.risk_contribution_pct.toFixed(1)}% 风险</span></div>)}</div></div>
            <div><h4>最高相关性</h4><div className="risk-list">{portfolioOptimization.correlation_pairs.slice(0, 4).map((pair) => <div key={`${pair.left}-${pair.right}`} className="risk-row"><span>{pair.left}/{pair.right}</span><span>{pair.correlation.toFixed(2)}</span></div>)}</div></div>
          </div>
        </div>
      ) : null}

      {/* Data quality */}
      {dataQuality ? (
        <div className="data-quality-panel" data-testid="crypto-data-quality">
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
          <div className="optimization-recommendations">
            {dataQuality.is_usable ? <p>SQLite 覆盖可用于 event-driven 回测。</p> : null}
            {dataQuality.issues.filter((issue) => ['high', 'critical'].includes(String(issue.severity).toLowerCase())).map((issue) => (
              <p key={`dq-blocker-${issue.code}`}>阻断：{issue.code} - {issue.message}</p>
            ))}
          </div>
        </div>
      ) : null}

      {/* Promotion gate */}
      {promotionGate ? (
        <div className="promotion-panel" data-testid="crypto-promotion-blockers">
          <div className="stress-summary-grid">
            <div className="optimization-best"><span>晋级决策</span><strong>{promotionGate.decision.toUpperCase()}</strong><p>{promotionGate.next_stage}</p></div>
            <div className="optimization-best"><span>核心 Sharpe</span><strong>{Number(promotionSummary?.sharpe_ratio ?? 0).toFixed(2)}</strong><p>MDD {Number(promotionSummary?.max_drawdown_pct ?? 0).toFixed(2)}%</p></div>
            <div className="optimization-best"><span>Manifest</span><strong>{String(promotionGate.manifest_id ?? '-').slice(0, 8)}</strong><p>{promotionGate.manifest_path || '未持久化'}</p></div>
            <div className="optimization-best"><span>实验</span><strong>{promotionGate.experiment_record?.experiment_name ?? '-'}</strong></div>
          </div>
          <div className="promotion-gate-list">{promotionGates.map((g) => <div key={g.name} className={gateClass(g.status)}><span>{g.status.toUpperCase()}</span><strong>{g.name}</strong><p>{g.message}</p></div>)}</div>
          <div className="optimization-recommendations">
            {promotionGates.filter((g) => g.status !== 'pass').map((g) => (
              <p key={`promotion-blocker-${g.name}`}>阻断：{g.name} - {g.message}</p>
            ))}
          </div>
          <div className="optimization-recommendations">{promotionRecommendations.map((r, i) => <p key={i}>{r}</p>)}</div>
        </div>
      ) : null}
    </>
  );
}
