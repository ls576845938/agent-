import type {StrategyOptimizationResponse, CostStressResponse, WalkForwardResponse, PortfolioOptimizationResponse, DataQualityResponse, PromotionGateResponse, OptimizationFrameworkItem, CryptoClosureResponse, TaskResponse} from '../../lib/shared-types';
import {formatOptimizationScore, formatParams, formatTimestamp, formatPrice, scenarioClass, gateClass} from '../../lib/utils';
import {ModuleStateCard} from '../../components/ModuleStateCard';

const btcAlphaHardening = {
  runId: '20260516T000000Z',
  paperReviewQueueLocked: true,
  liveFrozen: true,
  baselines: [
    {
      strategyId: 'btc_perp_dual_trend',
      profitFactor: 1.0996,
      sharpe: 1.5938,
      maxDrawdown: -6.8768,
      annualTurnover: 14.1611,
      walkForwardPassRate: 0.50,
      regimePassRate: 0.40,
      costStress: '100%',
      pboDsr: 'PBO 0.400 / DSR 0.345',
      gateStatus: 'candidate_gate_failed',
      failReasons: ['profit_factor', 'event_profit_factor', 'walk_forward_pass_rate', 'regime_pass_rate'],
    },
    {
      strategyId: 'btc_orderflow_pressure',
      profitFactor: 1.1053,
      sharpe: 1.6522,
      maxDrawdown: -5.7667,
      annualTurnover: 25.5021,
      walkForwardPassRate: 0.75,
      regimePassRate: 0.80,
      costStress: '100%',
      pboDsr: 'PBO 0.100 / DSR 0.065',
      gateStatus: 'candidate_gate_failed',
      failReasons: ['profit_factor', 'event_profit_factor', 'walk_forward_pass_rate', 'annual_turnover', 'dsr'],
    },
  ],
  candidates: [
    {
      strategyId: 'btc_perp_dual_trend_v2',
      profitFactor: 1.0189,
      sharpe: 0.4901,
      maxDrawdown: -7.9128,
      annualTurnover: 6.0125,
      walkForwardPassRate: 1.00,
      regimePassRate: 0.75,
      costStress: '100%',
      pboDsr: 'PBO 0.000 / DSR 1.000',
      gateStatus: 'candidate_gate_failed',
      failReasons: ['profit_factor', 'event_profit_factor'],
    },
    {
      strategyId: 'btc_orderflow_confirmed_trend_v1',
      profitFactor: 1.0030,
      sharpe: 0.0757,
      maxDrawdown: -9.0322,
      annualTurnover: 3.3873,
      walkForwardPassRate: 0.75,
      regimePassRate: 0.875,
      costStress: '100%',
      pboDsr: 'PBO 0.000 / DSR 1.000',
      gateStatus: 'candidate_gate_failed',
      failReasons: ['profit_factor', 'event_profit_factor', 'walk_forward_pass_rate'],
    },
  ],
};

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
  optimizationFramework: OptimizationFrameworkItem[];
  optimizedStrategyParams: Record<string, number> | null;
  onCryptoClosure: () => void;
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
  optimizationFramework, optimizedStrategyParams,
  onCryptoClosure,
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

      <div className="promotion-panel" data-testid="btc-alpha-hardening-panel">
        <div className="panel-header"><h2>BTC Alpha 加固</h2><span>{btcAlphaHardening.runId}</span></div>
        <div className="stress-summary-grid">
          <div className="optimization-best"><span>纸交易复核队列</span><strong>{btcAlphaHardening.paperReviewQueueLocked ? '锁定' : '待处理'}</strong><p>纸交易自动启动：否</p></div>
          <div className="optimization-best"><span>实盘状态</span><strong>{btcAlphaHardening.liveFrozen ? '冻结' : '开放'}</strong><p>实盘启用：否</p></div>
          <div className="optimization-best"><span>内部门禁</span><strong>0 / {btcAlphaHardening.candidates.length}</strong><p>PF 和账本 PF 仍低于阈值</p></div>
        </div>
        <div className="walk-table">
          {[...btcAlphaHardening.baselines, ...btcAlphaHardening.candidates].map((row) => (
            <div key={row.strategyId} className={`walk-row ${row.gateStatus === 'candidate_gate_failed' ? 'stress-fail' : 'stress-pass'}`}>
              <span>{row.strategyId}</span>
              <span>PF {row.profitFactor.toFixed(4)}</span>
              <span>Sharpe {row.sharpe.toFixed(2)}</span>
              <span>MDD {row.maxDrawdown.toFixed(2)}%</span>
              <span>换手 {(row.annualTurnover * 100).toFixed(0)}%</span>
              <span>WF {(row.walkForwardPassRate * 100).toFixed(0)}%</span>
              <span>状态 {(row.regimePassRate * 100).toFixed(0)}%</span>
              <span>成本 {row.costStress}</span>
              <span>{row.pboDsr}</span>
              <span>{row.failReasons.join(', ')}</span>
            </div>
          ))}
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
