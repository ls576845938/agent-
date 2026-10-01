import {useEffect, useMemo, useRef, useState} from 'react';
import {
  ChartBar,
  ChartLineUp,
  ClockCounterClockwise,
  Database,
  Fingerprint,
  ListBullets,
  Receipt,
  ShieldCheck,
  SlidersHorizontal,
  Table,
  TrendDown,
  WarningCircle,
} from '@phosphor-icons/react';

import {strategyPresentationName} from '../../lib/strategy-presentation';
import type {ChartSeriesPayload, RunStatusResponse, Summary} from '../../lib/view-model';
import {
  CostBreakdownChart,
  DrawdownChart,
  MonthlyReturnsChart,
  TradeOutcomeDonut,
  TradePnlChart,
} from './BacktestAnalyticsCharts';
import type {CanonicalBacktestReport, CanonicalTrade} from './canonical-report-types';
import type {BacktestSnapshot, DemoStrategySpec} from './demo-types';
import EquityPerformanceChart from './EquityPerformanceChart';
import CryptoStrategyEditor, {type CryptoBacktestConfig, type CryptoBacktestPhase} from './CryptoStrategyEditor';
import type {
  BTCStrategyHistoryResponse,
  BTCStrategyReportTab,
} from './strategy-history-types';
import {createUserBacktestRecord, upsertUserBacktestRecord} from './user-backtest-strategy-catalog';

type BacktestFormValue = {
  startDate: string;
  endDate: string;
  capital: number;
  commissionRate: number;
  slippageBps: number;
};

export default function StrategyTesterReport({
  strategyCatalog,
  editorCandidateId,
  onStrategyChange,
  selectedCandidateId,
  selectedStrategyId,
  selectedStrategyVersion,
  selectedParamsHash,
  sourceLabel,
  sampleEnd,
  form,
  onFormChange,
  busy,
  onRun,
  run,
  chart,
  history,
  onRestore,
  canonicalFreshness,
  canonical,
  canonicalReport,
  historyResponse,
  historyError,
  reportTab,
  onReportTabChange,
  canRunBacktest,
  readonlyReason = '',
}: {
  strategyCatalog: DemoStrategySpec[];
  editorCandidateId: string;
  onStrategyChange: (candidateId: string) => void;
  selectedCandidateId: string;
  selectedStrategyId: string;
  selectedStrategyVersion: string;
  selectedParamsHash: string;
  sourceLabel: string;
  sampleEnd: string;
  form: BacktestFormValue;
  onFormChange: (value: BacktestFormValue) => void;
  busy: boolean;
  onRun: (config: CryptoBacktestConfig, onPhase: (phase: CryptoBacktestPhase) => void) => Promise<void>;
  run: RunStatusResponse | null;
  chart: ChartSeriesPayload | null;
  history: BacktestSnapshot[];
  onRestore: (snapshot: BacktestSnapshot) => void;
  canonicalFreshness: string;
  canonical: Record<string, unknown> | null;
  canonicalReport: CanonicalBacktestReport | null;
  historyResponse: BTCStrategyHistoryResponse | null;
  historyError: string;
  selectedHistoricalRunId: string;
  onHistoricalRunSelect: (runId: string) => void;
  reportTab: BTCStrategyReportTab;
  onReportTabChange: (tab: BTCStrategyReportTab) => void;
  canRunBacktest: boolean;
  readonlyReason?: string;
}) {
  const [showProperties, setShowProperties] = useState(false);
  const [catalogMessage, setCatalogMessage] = useState('');
  const [progressPhase, setProgressPhase] = useState<CryptoBacktestPhase>('idle');
  const [editorExpanded, setEditorExpanded] = useState(true);
  const progressTimerRef = useRef<number | null>(null);
  const clearProgressTimer = () => {
    if (progressTimerRef.current !== null) {
      window.clearTimeout(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  };
  useEffect(() => clearProgressTimer, []);
  const runWithProgress = async (config: CryptoBacktestConfig, onEditorPhase: (phase: CryptoBacktestPhase) => void) => {
    if (readonlyReason || !canRunBacktest) return;
    clearProgressTimer();
    setProgressPhase('preparing');
    setEditorExpanded(true);
    onEditorPhase('preparing');
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    const progressStartedAt = performance.now();
    progressTimerRef.current = window.setTimeout(() => {
      setProgressPhase('polling');
    }, 20_000);
    try {
      await onRun(config, (phase) => {
        setProgressPhase(phase);
        onEditorPhase(phase);
      });
      const remainingVisibleMs = Math.max(0, 900 - (performance.now() - progressStartedAt));
      if (remainingVisibleMs > 0) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, remainingVisibleMs));
      }
      setProgressPhase('completed');
      setEditorExpanded(false);
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('[data-testid="btc-strategy-tester"]')?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
      });
    } catch (error) {
      setProgressPhase('failed');
      setEditorExpanded(true);
      throw error;
    } finally {
      clearProgressTimer();
    }
  };
  const progressText: Record<Exclude<CryptoBacktestPhase, 'idle'>, string> = {
    preparing: '正在准备受控回测',
    submitting: '回测请求已提交，等待受控服务',
    computing: '受控服务计算中',
    polling: '后端仍在计算，正在只读获取结果',
    loading_results: '正在加载真实回测结果',
    completed: '回测完成，结果已就位',
    failed: '回测失败，保留 fail-closed 状态',
  };
  const progressStages: Array<{phase: CryptoBacktestPhase; label: string}> = [
    {phase: 'submitting', label: '已提交'},
    {phase: 'computing', label: '服务计算'},
    {phase: 'polling', label: 'GET-only 获取'},
    {phase: 'loading_results', label: '加载结果'},
    {phase: 'completed', label: '完成'},
  ];
  const progressValues: Record<Exclude<CryptoBacktestPhase, 'idle'>, number> = {
    preparing: 8,
    submitting: 20,
    computing: 55,
    polling: 75,
    loading_results: 92,
    completed: 100,
    failed: 100,
  };
  const progressValue = progressValues[progressPhase === 'idle' ? 'preparing' : progressPhase];
  const resultFocused = progressPhase === 'completed' && !editorExpanded;
  const diagnostics = recordValue(run?.diagnostics);
  const canonicalMetrics = recordValue(canonical?.metrics);
  const canonicalIdentity = recordValue(canonical?.strategy_identity);
  const canonicalLedger = recordValue(canonical?.ledger_binding);
  const canonicalFreshnessRecord = recordValue(canonical?.artifact_freshness);
  const canonicalChecks = recordValue(canonical?.checks);
  const canonicalSafety = recordValue(canonical?.safety);
  const canonicalRunId = textValue(canonical?.run_id);
  const reportRunId = run?.run_id ?? canonicalReport?.run_id ?? canonicalRunId;
  const pnlSource = textValue(diagnostics.pnl_source) || textValue(canonicalLedger.pnl_source) || textValue(canonicalMetrics.pnl_source);
  const ledgerConsistent = run
    ? diagnostics.ledger_equity_consistent === true
    : (canonicalLedger.ledger_equity_consistent === true || canonicalLedger.replay_consistent === true)
      && canonicalReport?.artifact_binding.ledger_equity_consistent === true;
  const reportTrades = run ? [] : canonicalReport?.series.trades ?? [];
  const reportEquity = run ? chart?.equity ?? [] : canonicalReport?.series.equity ?? [];
  const reportDrawdown = run ? chart?.drawdown ?? [] : canonicalReport?.series.drawdown ?? [];
  const monthlyReturns = run ? normalizeRunMonthlyReturns(diagnostics.monthly_returns) : canonicalReport?.series.monthly_returns ?? [];
  const reportCosts = run ? normalizeRunCosts(diagnostics) : canonicalReport?.series.costs ?? [];
  const drawdownPeriodCount = objectList(diagnostics.drawdown_periods).length;
  const runBoundaryBlockers = run ? runEvidenceBlockers(diagnostics, reportEquity, reportDrawdown, monthlyReturns, reportCosts) : [];
  const metrics = useMemo(
    () => buildReportMetrics(run?.summary ?? null, canonical, canonicalReport, form.capital, chart, {
      currentRun: Boolean(run),
      equity: reportEquity,
      trades: reportTrades,
      costs: reportCosts,
      diagnostics,
    }),
    [run?.summary, run, canonical, canonicalReport, form.capital, chart, reportEquity, reportTrades, reportCosts, diagnostics],
  );
  const noLookaheadPassed = evidenceBoolean(canonical, ['checks', 'source_no_lookahead_passed'])
    || evidenceBoolean(canonical, ['checks', 'no_lookahead_passed'])
    || evidenceBoolean(canonical, ['checks', 'no_lookahead']);
  const localNetworkFree = canonicalChecks.source_data_local_and_network_free === true;
  const currentHeadMatch = canonicalFreshnessRecord.current_head_match === true;
  const safetyFlagsVerified = [
    'paper_queue_write_allowed',
    'paper_allowed',
    'paper_order_intake_allowed',
    'live_unlock_allowed',
    'live_order_allowed',
    'broker_access_allowed',
    'broker_or_order_allowed',
    'oms_access_allowed',
    'order_endpoint_used',
    'private_endpoint_used',
    'real_order_submitted',
  ].every((key) => canonicalSafety[key] === false) && (!canonicalReport || Object.values(canonicalReport.safety).every((value) => value === false));
  const canonicalBlockers = [...new Set([
    ...runBoundaryBlockers,
    ...arrayStrings(canonical?.blockers),
    ...arrayStrings(canonical?.backtest_blockers),
    ...arrayStrings(canonical?.promotion_readiness_blockers),
    ...(canonicalReport?.blockers ?? []),
  ])];
  const chartMarkers = chart?.markers ?? [];
  const chartCandles = chart?.candles ?? [];
  const canonicalPeriod = reportPeriod(reportEquity, reportTrades);
  const displayPeriod = run ? `${form.startDate} — ${form.endDate}` : canonicalPeriod;
  const sideMetrics = useMemo(() => buildSideMetrics(reportTrades), [reportTrades]);
  const hasCanonicalLedgerSeries = Boolean(
    canonicalReport?.artifact_binding.ledger_equity_consistent
    && canonicalReport.series.equity.length > 0
    && canonicalReport.series.trades.length > 0,
  );
  const isHistoricalSummaryOnly = Boolean(historyResponse && !hasCanonicalLedgerSeries);
  const reportSource = run
    ? ledgerConsistent
      ? '当前 run · ledger equity / diagnostics'
      : '当前 run · 证据未完整对账'
    : hasCanonicalLedgerSeries
      ? `canonical ledger 证据 · ${shortHash(canonicalReport?.source_run_id ?? '')}`
      : isHistoricalSummaryOnly
        ? `历史研究摘要 · 无连续 ledger/fills/净值曲线 · ${shortHash(canonicalReport?.source_run_id ?? '')}`
        : canonical
          ? `canonical 历史摘要 · ${shortHash(canonicalRunId)}`
          : '无可用证据';
  const reportSeriesVerified = Boolean(
    canonicalReport?.status === 'complete_research_only'
    && canonicalReport.artifact_binding.manifest_sha256_verified
    && canonicalReport.artifact_binding.evidence_pack_sha256_verified
    && canonicalReport.artifact_binding.ledger_artifact_sha256_verified
    && canonicalReport.artifact_binding.fills_hash_verified
    && canonicalReport.artifact_binding.ledger_equity_consistent,
  );
  const strategyVersion = textValue(canonicalIdentity.strategy_version) || selectedStrategyVersion;
  const candidateId = textValue(canonicalIdentity.candidate_id) || selectedCandidateId;
  const paramsHash = textValue(canonicalIdentity.params_hash) || selectedParamsHash;
  const dataLineage = [
    `${textValue(canonicalIdentity.signal_data_venue) || 'signal venue unknown'}:${textValue(canonicalIdentity.signal_instrument) || 'signal instrument unknown'}`,
    `→ ${textValue(canonicalIdentity.execution_venue) || 'execution venue unknown'}:${textValue(canonicalIdentity.execution_instrument) || 'execution instrument unknown'}`,
    textValue(canonicalIdentity.timeframe),
    run ? sampleEnd || 'sample_end unknown' : canonicalPeriod,
  ].filter(Boolean).join(' · ');
  const fillsHash = textValue(canonicalLedger.fills_hash);
  const ledgerHash = textValue(canonicalLedger.ledger_hash);
  const manifestPath = textValue(recordValue(canonical?.manifest).path);
  const evidencePackPath = textValue(canonicalFreshnessRecord.evidence_pack_path);
  const evidenceFresh = reportSeriesVerified && currentHeadMatch && canonicalFreshness === 'pass';
  const hasReportEvidence = Boolean(run || canonical || canonicalReport);
  const reportModeLabel = run ? '浏览器本地研究 run' : evidenceFresh ? 'CURRENT-HEAD canonical' : hasReportEvidence ? '历史 canonical 证据' : '未加载研究证据';
  const reportModeTone = run ? 'local' : evidenceFresh ? 'pass' : 'blocked';
  const reportDataSource = run ? sourceLabel : dataLineage;
  const historyDetails = historyResponse?.details ?? null;
  const isNativeBaseline = historyResponse?.relationship === 'same_formula_historical_research_baseline';
  const userCatalogEligible = Boolean(
    run?.status === 'completed'
    && run.summary
    && selectedStrategyId
    && selectedCandidateId
    && reportRunId,
  );

  const addCurrentRunToCatalog = () => {
    if (!userCatalogEligible || !run?.summary) return;
    upsertUserBacktestRecord(createUserBacktestRecord({
      runId: run.run_id,
      strategyId: selectedStrategyId,
      candidateId: selectedCandidateId,
      displayName: `${selectedStrategyId} · ${selectedCandidateId} · ${run.run_id}`,
      metrics: run.summary,
      createdAt: run.completed_at || new Date().toISOString(),
      sourceSnapshot: 'quantstation.btc.trading-workbench.v2',
    }));
    setCatalogMessage('已加入策略浏览；重复添加会按稳定 run key 幂等更新。仅保存在当前浏览器，未同步账户。');
  };

  return (
    <div className={`tv-strategy-report ${resultFocused ? 'tv-backtest-result-focused' : 'tv-backtest-editor-expanded'}`} data-testid="btc-strategy-tester">
      {readonlyReason ? <p className="tv-console-warning" data-testid="btc-tester-readonly" role="status">{readonlyReason}</p> : null}
      {progressPhase !== 'idle' || busy ? (
        <div
          className={`crypto-backtest-progress ${progressPhase === 'completed' ? 'completed' : ''} ${progressPhase === 'failed' ? 'failed' : ''}`}
          data-testid="btc-backtest-progress"
          data-stage={progressPhase}
          role="status"
          aria-live="polite"
        >
          <div>
            <span>阶段进度 {progressValue}%</span>
            <strong>{progressText[progressPhase === 'idle' ? 'preparing' : progressPhase]}</strong>
          </div>
          <div
            className="crypto-backtest-progress-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progressValue}
            aria-valuetext={`${progressValue}% · 阶段进度；后端未提供精确计算百分比`}
            data-progress-value={progressValue}
          >
            <span style={{width: `${progressValue}%`}} />
          </div>
          <div className="crypto-backtest-progress-stages" aria-label="回测生命周期阶段">
            {progressStages.map((stage) => <span key={stage.phase} className={progressPhase === stage.phase ? 'active' : ''}>{stage.label}</span>)}
          </div>
          <small>只显示已确认生命周期阶段；服务计算百分比不可得时不伪造进度。</small>
        </div>
      ) : null}
      <div className="tv-strategy-commandbar">
        <div className="tv-strategy-command-title">
          <ChartBar size={22} weight="fill" />
          <div>
            <strong>{strategyPresentationName(selectedStrategyId, selectedStrategyId) || '策略测试器'}</strong>
            <span>{strategyVersion || selectedStrategyVersion || '等待策略目录'} · 1h · 1x · {reportModeLabel}</span>
          </div>
        </div>
        <button type="button" className="tv-report-command" onClick={() => setShowProperties((value) => !value)} aria-expanded={showProperties}>
          <SlidersHorizontal size={17} />
          证据参数 / 新回测
        </button>
        <div className="tv-report-command-static"><ClockCounterClockwise size={17} /><span>{displayPeriod}</span></div>
        <div className="tv-report-command-static"><Database size={17} /><span>{reportDataSource}</span></div>
        {userCatalogEligible ? <button type="button" className="tv-report-command" data-testid="add-backtest-to-strategy-catalog" onClick={addCurrentRunToCatalog}>加入策略浏览</button> : null}
      </div>

      {resultFocused ? <CompletedBacktestActions onEdit={() => setEditorExpanded(true)} /> : null}

      {catalogMessage ? <div className="tv-report-notice local" role="status"><ShieldCheck size={16} /><span>{catalogMessage}</span><strong>RESEARCH ONLY</strong></div> : null}

      {showProperties ? (
        <div className="tv-backtest-properties" data-testid="btc-backtest-properties">
          <div className={`tv-property-context ${reportModeTone}`}>
            <span>当前展示</span><strong>{reportModeLabel}</strong><small>{run ? 'localStorage 快照，不进入 promotion evidence' : evidenceFresh ? 'manifest / evidence pack / ledger 与当前 HEAD 一致' : '保留历史研究价值，但不得用于当前 promotion'}</small>
          </div>
          <PropertyFact label="证据区间" value={displayPeriod} />
          <PropertyFact label="初始资金" value={money(metrics.initialCapital)} />
          <PropertyFact label="成本覆盖" value={metrics.costCoverageComplete ? '手续费 / 滑点 / 冲击 / Funding' : '成本字段部分展开'} />
          <PropertyFact label="Canonical candidate" value={candidateId || '—'} mono />
          <div className="tv-local-run-heading"><strong>新建浏览器本地研究 run</strong><span>以下表单只影响新 run，不会改写上方 canonical 证据。</span></div>
          <label><span>开始日期</span><input type="date" value={form.startDate} onChange={(event: {target: {value: string}}) => onFormChange({...form, startDate: event.target.value})} /></label>
          <label><span>结束日期</span><input type="date" value={form.endDate} onChange={(event: {target: {value: string}}) => onFormChange({...form, endDate: event.target.value})} /></label>
          <label><span>初始资金</span><input type="number" min="100" value={form.capital} onChange={(event: {target: {value: string}}) => onFormChange({...form, capital: Number(event.target.value)})} /></label>
          <label><span>手续费率</span><input type="number" min="0" step="0.0001" value={form.commissionRate} onChange={(event: {target: {value: string}}) => onFormChange({...form, commissionRate: Number(event.target.value)})} /></label>
          <label><span>滑点 bps</span><input type="number" min="0" step="1" value={form.slippageBps} onChange={(event: {target: {value: string}}) => onFormChange({...form, slippageBps: Number(event.target.value)})} /></label>
          <div className="tv-property-identity"><span>Candidate</span><code>{selectedCandidateId || '—'}</code><span>Params</span><code>{shortHash(selectedParamsHash)}</code></div>
        </div>
      ) : null}

      <div className={`tv-report-notice ${reportModeTone}`}>
        {reportModeTone === 'pass' ? <ShieldCheck size={16} /> : <WarningCircle size={16} />}
        <span>
          {run
            ? ledgerConsistent
              ? '本次回测结果已通过账本一致性校验，仅供研究，不代表可以启动交易。'
              : '本次回测尚未完整对账；缺失结果保持空白，不使用行情数据代替。'
            : evidenceFresh
              ? '报告已匹配当前版本，可供研究审阅，但不代表模拟或实盘交易已就绪。'
              : isHistoricalSummaryOnly
                ? '当前仅展示历史研究摘要，未提供完整账本、逐笔成交或净值曲线。'
                : hasReportEvidence ? '当前报告属于历史研究，尚未通过当前版本核验，不能作为交易启动依据。' : '研究证据未加载；未知收益和成交不显示为零。'}
        </span>
        <strong>{reportSource}</strong>
      </div>
      {run && !chart ? (
        <div className="tv-report-notice blocked" data-testid="btc-local-backtest-chart-missing">
          <WarningCircle size={16} />
          <span>completed 摘要已恢复，但旧快照没有 chart 载荷；净值、回撤、K 线与成交曲线保持空缺，绝不使用市场 K 线补造。</span>
          <strong>CHART EVIDENCE MISSING</strong>
        </div>
      ) : null}
      {run && !selectedParamsHash ? (
        <div className="tv-report-notice blocked" data-testid="btc-local-backtest-params-unknown">
          <WarningCircle size={16} />
          <span>旧快照未记录 params hash；仅恢复策略/候选/run 身份，不声明当前参数匹配。</span>
          <strong>PARAMS IDENTITY UNKNOWN</strong>
        </div>
      ) : null}
      {historyError ? (
        <div className="tv-report-notice blocked" data-testid="btc-strategy-history-error">
          <WarningCircle size={16} />
          <span>历史报告暂不可用；不影响独立进行当前回测。</span>
          <details><summary>技术详情</summary><code>{historyError}</code></details>
        </div>
      ) : historyResponse ? (
        <div className={`tv-report-notice ${isNativeBaseline ? 'blocked' : 'local'}`} data-testid="btc-strategy-history-relationship">
          <WarningCircle size={16} />
          <span>{historyResponse.relationship_label}</span>
          <strong>{isNativeBaseline ? 'RESEARCH ONLY · NOT OKX-NATIVE BACKTEST' : 'CANDIDATE MATCHED · RESEARCH ONLY'}</strong>
        </div>
      ) : null}

      <div className={`tv-report-freshness-banner ${reportModeTone}`} data-testid="btc-report-freshness">
        <div><Fingerprint size={17} /><span>证据状态</span><strong>{reportModeLabel}</strong></div>
        <span>{currentHeadMatch ? '已匹配当前版本' : '尚未匹配当前版本'} · {canonicalBlockers.length ? `有 ${canonicalBlockers.length} 项待核验` : '仍需核验完整性'}</span>
        <small>{run ? '本地研究快照' : '仅供研究审阅'}</small>
      </div>

      <section className={`tv-key-stats ${!run && !evidenceFresh ? 'historical' : ''}`}>
        <ReportMetric label="净利润" value={money(metrics.netProfit)} suffix={percent(metrics.totalReturn)} tone={tone(metrics.totalReturn)} />
        <ReportMetric label="最大回撤" value={metrics.maxDrawdownCash === undefined ? unsignedPercent(metrics.maxDrawdownAbs) : money(metrics.maxDrawdownCash)} suffix={metrics.maxDrawdownCash === undefined ? '金额证据未展开' : unsignedPercent(metrics.maxDrawdownAbs)} tone="bad" />
        <ReportMetric label="盈利交易" value={percent(metrics.winRate)} suffix={metrics.tradeCount === undefined ? '—' : `${metrics.estimatedWinners ?? '—'} / ${metrics.tradeCount}`} tone={tone(metrics.winRate)} />
        <ReportMetric
          label="盈利因子"
          value={fixed(metrics.profitFactor, 3)}
          suffix={
            metrics.profitFactor === undefined
              ? '证据未展开'
              : isHistoricalSummaryOnly
                ? '历史 review metrics / 非 ledger'
                : 'fills / ledger'
          }
        />
      </section>

      <nav className="tv-report-tabs" aria-label="回测报告视图">
        {([
          ['overview', '概览', ChartLineUp],
          ['performance', '业绩表现', Table],
          ['trades', '交易分析', ListBullets],
          ['risk', '风险与资本', TrendDown],
          ['evidence', '证据链', Fingerprint],
        ] as const).map(([id, label, Icon]) => (
          <button key={id} type="button" className={reportTab === id ? 'active' : ''} onClick={() => onReportTabChange(id)}>
            <Icon size={15} />{label}
          </button>
        ))}
      </nav>

      <div className="tv-report-body" data-testid="btc-strategy-report">
        {reportTab === 'overview' ? (
          !run && isHistoricalSummaryOnly && historyDetails ? (
            <HistoricalSummaryOverview details={historyDetails} />
          ) : (
            <div className="tv-overview-grid">
            <section className="tv-report-card tv-equity-card">
              <div className="tv-report-card-head">
                <div><strong>策略净值与回撤</strong><span>累计收益 · 回撤柱</span></div>
                <small>
                  {run?.run_id
                    ?? (hasCanonicalLedgerSeries
                      ? 'canonical ledger series'
                      : isHistoricalSummaryOnly
                        ? 'historical research summary only'
                        : 'canonical summary only')}
                </small>
              </div>
              <EquityPerformanceChart equity={reportEquity} drawdown={reportDrawdown} />
            </section>
            <section className="tv-report-card tv-analytics-card">
              <div className="tv-report-card-head"><div><strong>逐笔盈亏与累计 PnL</strong><span>fills 配对 · funding 分配 · ledger 对账</span></div><small>{hasReportEvidence ? reportTrades.length : '—'} trades</small></div>
              {run && !reportTrades.length ? <EvidenceUnavailable text="当前 run 未公开权威闭合 fills/trades；chart marker 仅是 fill 事件，不能安全配对成逐笔 PnL。" /> : <TradePnlChart trades={reportTrades} />}
            </section>
            <section className="tv-report-card tv-analytics-card">
              <div className="tv-report-card-head"><div><strong>月度收益</strong><span>ledger 月末净值计算</span></div><small>{hasReportEvidence ? monthlyReturns.length : '—'} months</small></div>
              {run && !monthlyReturns.length ? <EvidenceUnavailable text="当前 run 未公开权威 monthly_returns；不从价格或摘要反推。" /> : <MonthlyReturnsChart returns={monthlyReturns} />}
            </section>
            <section className="tv-report-card tv-analytics-card">
              <div className="tv-report-card-head"><div><strong>成本分解</strong><span>手续费 · 滑点 · 冲击 · Funding</span></div><Receipt size={18} /></div>
              {run && !reportCosts.length ? <EvidenceUnavailable text="当前 run 未公开成本分项；未知项不当作 0。" /> : <CostBreakdownChart costs={reportCosts} />}
            </section>
            <section className="tv-report-card tv-overview-facts">
              <div className="tv-report-card-head"><div><strong>回报详情</strong><span>基于可验证字段</span></div></div>
              <ReportMetric label="预期收益 / 成交" value={money(metrics.expectedPayoff)} />
              <ReportMetric label="买入并持有" value={percent(metrics.buyHoldReturn)} />
              <ReportMetric label="策略表现优异" value={percent(metrics.outperformance)} tone={tone(metrics.outperformance)} />
              <ReportMetric label="夏普比率" value={fixed(metrics.sharpe, 3)} />
              <ReportMetric label="Sortino" value={fixed(metrics.sortino, 3)} />
              <ReportMetric label="年化波动" value={percent(metrics.annualVolatility)} />
            </section>
            <section className="tv-report-card tv-cost-breakdown">
              <div className="tv-report-card-head"><div><strong>成本数值</strong><span>不补造缺失项</span></div><Receipt size={18} /></div>
              <CostRow label="手续费" value={metrics.commissionCost} />
              <CostRow label="固定滑点" value={metrics.fixedSlippageCost} />
              <CostRow label="冲击成本" value={metrics.impactCost} />
              <CostRow label="Funding" value={metrics.fundingCost} />
              <CostRow label={metrics.totalCost === undefined ? '已知成本合计' : '总成本'} value={metrics.totalCost ?? metrics.knownCost} emphasis />
              {metrics.totalCost === undefined ? <small className="tv-report-missing-note">总成本仍缺少未公开的成本分项，未将未知项当作 0。</small> : null}
            </section>
            <section className="tv-report-card tv-report-blockers">
              <div className="tv-report-card-head"><div><strong>研究边界</strong><span>完整性须独立核验</span></div><WarningCircle size={18} /></div>
              <ResearchBoundary blockers={canonicalBlockers} sourceKnown={Boolean(reportRunId)} />
            </section>
            </div>
          )
        ) : null}

        {reportTab === 'performance' ? (
          <div className="tv-history-detail-stack">
            <section className="tv-report-table-section">
              <div className="tv-report-card-head"><div><strong>业绩表现</strong><span>做多/做空来自已验证闭合 fill cycles；无法拆分的指标保持 “—”</span></div><small>全部 / 做多 / 做空</small></div>
              <MetricTable rows={[
                ['初始资本', money(metrics.initialCapital), '—', '—'],
                ['净利润', money(metrics.netProfit), money(sideMetrics.long.netPnl), money(sideMetrics.short.netPnl)],
                ['净利润率', percent(metrics.totalReturn), '—', '—'],
                ['年化收益', percent(metrics.annualReturn), '—', '—'],
                ['年化波动', percent(metrics.annualVolatility), '—', '—'],
                ['最大回撤', percent(metrics.maxDrawdownAbs), '—', '—'],
                ['总交易', integer(metrics.tradeCount), integer(sideMetrics.long.tradeCount), integer(sideMetrics.short.tradeCount)],
                ['盈利交易', integer(metrics.estimatedWinners), integer(sideMetrics.long.winners), integer(sideMetrics.short.winners)],
                ['盈利率', percent(metrics.winRate), percent(sideMetrics.long.winRate), percent(sideMetrics.short.winRate)],
                ['平均交易 PnL', money(metrics.expectedPayoff), money(sideMetrics.long.averagePnl), money(sideMetrics.short.averagePnl)],
                ['盈利因子', fixed(metrics.profitFactor, 3), fixed(sideMetrics.long.profitFactor, 3), fixed(sideMetrics.short.profitFactor, 3)],
                ['已支付成本', money(metrics.totalCost), '—', '—'],
                ['买入并持有收益', percent(metrics.buyHoldReturn), '—', '—'],
                ['策略超额表现', percent(metrics.outperformance), '—', '—'],
              ]} />
            </section>
            {historyDetails ? <HistoricalPerformanceDetails details={historyDetails} /> : null}
          </div>
        ) : null}

        {reportTab === 'trades' ? (
          <div className="tv-trade-analysis">
            <section className="tv-trade-stat-grid">
              <ReportMetric label="总交易" value={integer(metrics.tradeCount)} />
              <ReportMetric label="盈利交易" value={integer(metrics.estimatedWinners)} tone="good" />
              <ReportMetric label="亏损交易" value={integer(metrics.estimatedLosers)} tone="bad" />
              <ReportMetric label="平均盈亏" value={money(metrics.expectedPayoff)} />
              <ReportMetric label="平均持仓 K 线" value={fixed(metrics.averageDurationBars, 1)} suffix={metrics.averageDurationBars === undefined ? '证据未展开' : 'completed 1h bars'} />
              <ReportMetric label="最大盈利 / 亏损" value={metrics.largestWinner === undefined ? '—' : `${money(metrics.largestWinner)} / ${money(metrics.largestLoser)}`} suffix="闭合交易" />
            </section>
            <section className="tv-trade-chart-grid">
              <div className="tv-report-card tv-analytics-card"><div className="tv-report-card-head"><div><strong>交易盈亏路径</strong><span>净 PnL 柱 · 累计 PnL 线</span></div></div>{run && !reportTrades.length ? <EvidenceUnavailable text="当前 run 没有权威闭合 trade cycles；不由 18 个 marker 或 K 线反推。" /> : <TradePnlChart trades={reportTrades} />}</div>
              <div className="tv-report-card tv-analytics-card"><div className="tv-report-card-head"><div><strong>交易分布</strong><span>盈利 / 亏损 / 持平</span></div></div>{run && !reportTrades.length ? <EvidenceUnavailable text="当前 run 未公开闭合交易分布证据；9/18 marker 摘要不等于闭合交易。" /> : <TradeOutcomeDonut trades={reportTrades} />}</div>
            </section>
            <section className="tv-report-table-section">
              <div className="tv-report-card-head"><div><strong>{reportTrades.length ? 'Canonical 交易清单' : '回测事件清单'}</strong><span>{reportTrades.length ? 'fills / funding / ledger 派生；不与 Demo fills 混用' : '来自当前 run chart markers'}</span></div><small>{reportTrades.length || chartMarkers.length} events</small></div>
              {reportTrades.length ? <TradeLedgerTable trades={reportTrades} /> : <EventTable markers={chartMarkers} candles={chartCandles} />}
            </section>
            {historyDetails ? <HistoricalTradeReview details={historyDetails} /> : null}
          </div>
        ) : null}

        {reportTab === 'risk' ? (
          <div className="tv-risk-grid">
            <section className="tv-report-card tv-risk-metrics">
              <div className="tv-report-card-head"><div><strong>风险调整后的表现</strong><span>run summary / canonical metrics</span></div><ShieldCheck size={18} /></div>
              <ReportMetric label="Sharpe" value={fixed(metrics.sharpe, 3)} />
              <ReportMetric label="Sortino" value={fixed(metrics.sortino, 3)} />
              <ReportMetric label="Calmar" value={fixed(metrics.calmar, 3)} />
              <ReportMetric label="最大回撤" value={percent(metrics.maxDrawdownAbs)} tone="bad" />
              <ReportMetric label="年化波动" value={percent(metrics.annualVolatility)} />
              <ReportMetric label="保证金调用" value="—" suffix="未见非零证据" />
            </section>
            <section className="tv-report-card tv-capital-metrics">
              <div className="tv-report-card-head"><div><strong>资本效率</strong><span>研究回测，不代表账户可用保证金</span></div></div>
              <ReportMetric label="初始资本" value={money(metrics.initialCapital)} />
              <ReportMetric label="净利润" value={money(metrics.netProfit)} tone={tone(metrics.netProfit)} />
              <ReportMetric label="CAGR" value={percent(metrics.annualReturn)} />
              <ReportMetric label="最大杠杆" value="1.00x" suffix="冻结参数" />
              <ReportMetric label="最大净仓" value="—" suffix="run payload 未展开" />
              <ReportMetric label="追加保证金" value="—" />
            </section>
            <section className="tv-report-card tv-risk-chart">
              <div className="tv-report-card-head"><div><strong>回撤时间线</strong><span>ledger daily equity underwater curve</span></div><small>{run && drawdownPeriodCount ? `${drawdownPeriodCount} 个已记录区间` : '同一 equity series'}</small></div>
              {run && !reportDrawdown.length ? <EvidenceUnavailable text="当前 run 未公开 ledger drawdown series；不从 K 线价格推断回撤。" /> : <DrawdownChart drawdown={reportDrawdown} />}
            </section>
            <section className="tv-report-card tv-risk-chart tv-risk-equity-chart">
              <div className="tv-report-card-head"><div><strong>累计收益与回撤</strong><span>同一 ledger equity series</span></div></div>
              <EquityPerformanceChart equity={reportEquity} drawdown={reportDrawdown} />
            </section>
            {historyDetails ? <HistoricalRiskDetails details={historyDetails} /> : null}
          </div>
        ) : null}

        {reportTab === 'evidence' ? (
          <div className="tv-evidence-report">
            <section className="tv-evidence-matrix">
              <EvidenceRow label="策略身份" value={`${strategyVersion || '—'} / ${candidateId || '—'}`} state={Boolean(strategyVersion && candidateId)} />
              <EvidenceRow label="参数 hash" value={paramsHash || '—'} state={Boolean(paramsHash)} mono />
              <EvidenceRow label="数据 lineage" value={dataLineage} state={Boolean(canonicalPeriod !== '区间未展开' && canonicalIdentity.signal_data_venue && canonicalIdentity.execution_venue)} />
              <EvidenceRow label="Run ID" value={reportRunId || 'run_id 未公开'} state={Boolean(reportRunId)} mono />
              <EvidenceRow label="PnL 来源" value={pnlSource || 'API 摘要未展开'} state={pnlSource === 'ledger_fills'} />
              <EvidenceRow label="Ledger 一致性" value={ledgerConsistent ? 'ledger_equity_consistent=true' : '未通过或未展开'} state={ledgerConsistent} />
              <EvidenceRow label="Fills / Ledger hash" value={fillsHash && ledgerHash ? `${fillsHash} / ${ledgerHash}` : 'hash 未展开'} state={Boolean(fillsHash && ledgerHash)} mono />
              <EvidenceRow label="Canonical freshness" value={canonicalFreshness} state={canonicalFreshness === 'pass' && currentHeadMatch} />
              <EvidenceRow label="HEAD binding" value={`${textValue(canonicalFreshnessRecord.code_commit) || 'unknown'} → ${textValue(canonicalFreshnessRecord.current_head) || 'unknown'}`} state={currentHeadMatch} mono />
              <EvidenceRow label="Manifest / evidence pack" value={`${manifestPath || 'manifest unknown'} / ${evidencePackPath || 'evidence pack unknown'}`} state={Boolean(manifestPath && evidencePackPath && canonicalChecks.source_artifacts_present === true)} mono />
              <EvidenceRow label="报告图表载荷" value={reportSeriesVerified ? `${canonicalReport?.source_counts.ledger_snapshot_count ?? 0} snapshots / ${canonicalReport?.source_counts.fill_count ?? 0} fills / ${canonicalReport?.source_counts.closed_trade_count ?? 0} trades` : canonicalReport?.blockers.join(' · ') || 'API 未返回'} state={reportSeriesVerified} mono />
              <EvidenceRow label="无未来函数" value={noLookaheadPassed ? 'source_no_lookahead_passed=true' : evidenceText(canonical, ['checks', 'source_no_lookahead_passed'], ['checks', 'no_lookahead'], ['lookahead', 'status'])} state={noLookaheadPassed} />
              <EvidenceRow label="本地数据 / 无网络" value={localNetworkFree ? 'source_data_local_and_network_free=true' : '未通过或未展开'} state={localNetworkFree} />
              <EvidenceRow label="手续费 / 滑点 / Funding / 冲击" value={metrics.totalCost === undefined ? '成本项未全部展开' : money(metrics.totalCost)} state={metrics.costCoverageComplete} />
              <EvidenceRow label="Paper / Live 安全旗标" value="paper=false · queue=false · broker=false · OMS=false · private/order=false · live=false · unlock=false" state={safetyFlagsVerified} />
            </section>
            <section className="tv-evidence-blocker-panel">
              <div className="tv-report-card-head"><div><strong>客观 blockers</strong><span>fail-closed，不做视觉消除</span></div><WarningCircle size={18} /></div>
              <ResearchBoundary blockers={canonicalBlockers} sourceKnown={Boolean(reportRunId)} />
            </section>
            {historyResponse ? <HistoricalSourceDetails response={historyResponse} /> : null}
          </div>
        ) : null}
      </div>

      <div className="tv-run-history-strip">
        <span><ClockCounterClockwise size={15} />浏览器本地快照 · 非正式证据</span>
        {history.length ? history.map((item) => (
          <button key={item.run.run_id} type="button" onClick={() => onRestore(item)}>
            <strong>{item.run.run_id.slice(0, 12)}</strong>
            <small>{percent(item.run.summary?.total_return_pct)}</small>
          </button>
        )) : <small>完成一次本地回测后显示；不会覆盖 canonical manifest。</small>}
      </div>
      {resultFocused ? (
        <div className="crypto-strategy-editor-restore" data-testid="btc-backtest-editor-restore">
          <span>回测结果已置于首要视图；策略源码编辑器已收起。</span>
          <button type="button" onClick={() => setEditorExpanded(true)}>编辑策略 / 展开编辑器</button>
        </div>
      ) : null}
      <div className={`crypto-strategy-editor-frame ${resultFocused ? 'collapsed' : ''}`}>
        <CryptoStrategyEditor
          strategies={strategyCatalog}
          selectedCandidateId={editorCandidateId}
          form={form}
          onFormChange={onFormChange}
          onStrategyChange={onStrategyChange}
          busy={busy}
          canRunBacktest={canRunBacktest && !readonlyReason}
          onRun={runWithProgress}
          onProgressPhase={setProgressPhase}
        />
      </div>
    </div>
  );
}

function ResearchBoundary({blockers, sourceKnown}: {blockers: string[]; sourceKnown: boolean}) {
  return <>
    <p>{!sourceKnown
      ? '研究状态未知 · 尚未取得可核验的运行来源；不能据此报告零阻断项。'
      : '以下仅是已返回的阻断信息；无阻断项不代表研究证据完整，仍需核验版本、来源与账本。'}</p>
    {blockers.length ? <><span>已收到 {blockers.length} 项阻断</span>{blockers.map(item => <code key={item}>{item}</code>)}</> : null}
    <p>研究完成不授予 Demo / paper / live 权限。</p>
  </>;
}

function HistoricalSummaryOverview({details}: {details: BTCStrategyHistoryResponse['details']}) {
  const metrics = recordValue(details.full_metrics);
  const warnings = arrayStrings(details.warnings);
  return (
    <div className="tv-history-summary-overview" data-testid="btc-historical-summary-overview">
      <section className="tv-report-card tv-history-summary-boundary">
        <div className="tv-report-card-head">
          <div>
            <strong>历史研究摘要，不是成交账本</strong>
            <span>源快照未发布连续 ledger / fills / series；本页不伪造净值、逐笔 PnL、月度收益或现金成本曲线。</span>
          </div>
          <WarningCircle size={18} />
        </div>
        <div className="tv-history-summary-metrics">
          <ReportMetric label="年化收益" value={percent(numberValue(metrics.annual_return_pct))} />
          <ReportMetric label="总收益" value={percent(numberValue(metrics.total_return_pct))} />
          <ReportMetric label="最大回撤" value={percent(numberValue(metrics.max_drawdown_pct))} tone="bad" />
          <ReportMetric label="Sharpe" value={fixed(numberValue(metrics.sharpe_ratio), 3)} />
          <ReportMetric label="Sortino" value={fixed(numberValue(metrics.sortino_ratio), 3)} />
          <ReportMetric label="Profit factor" value={fixed(numberValue(metrics.profit_factor), 3)} />
        </div>
        <p>以下内容逐项读取历史详情中的年度归因、holdout、walk-forward、成本压力与回撤归因；paper / live 继续保持 research-only 与 fail-closed。</p>
        {warnings.length ? <div className="tv-history-summary-warnings">{warnings.map((warning) => <code key={warning}>{warning}</code>)}</div> : null}
      </section>
      <HistoricalPerformanceDetails details={details} />
      <HistoricalRiskDetails details={details} />
    </div>
  );
}

export function HistoricalPerformanceDetails({details}: {details: BTCStrategyHistoryResponse['details']}) {
  const annual = objectList(details.annual_attribution.segments);
  const folds = objectList(details.walk_forward.folds);
  const scenarios = objectList(details.cost_stress.scenarios);
  const holdoutMetrics = recordValue(details.confirmation_holdout.metrics);
  return (
    <div className="tv-history-detail-grid" data-testid="btc-historical-performance-details">
      <section className="tv-report-table-section">
        <div className="tv-report-card-head"><div><strong>逐年表现</strong><span>Top5 review annual attribution</span></div><small>{annual.length} years</small></div>
        <SimpleHistoryTable
          headers={['年份', '总收益', '年化收益', '最大回撤', 'Sharpe', '状态']}
          rows={annual.map((item) => {
            const values = recordValue(item.metrics);
            return [
              textValue(item.year),
              percent(numberValue(values.total_return_pct)),
              percent(numberValue(values.annual_return_pct)),
              percent(numberValue(values.max_drawdown_pct)),
              fixed(numberValue(values.sharpe_ratio), 3),
              item.passed === true ? 'PASS' : 'BLOCKED',
            ];
          })}
        />
      </section>
      <section className="tv-report-card">
        <div className="tv-report-card-head"><div><strong>Holdout / Walk-forward</strong><span>不把 post-selection review 称为全新未见样本</span></div></div>
        <ReportMetric label="Holdout" value={details.confirmation_holdout.passed === true ? 'PASS' : 'BLOCKED'} suffix={percent(numberValue(holdoutMetrics.total_return_pct))} />
        <ReportMetric label="Walk-forward pass rate" value={percent(numberValue(details.walk_forward.pass_rate) === undefined ? undefined : numberValue(details.walk_forward.pass_rate)! * 100)} suffix={`${folds.length} folds`} />
        <ReportMetric label="Pre-selection clean" value={details.review_design.clean_pre_selection_holdout === true ? 'YES' : 'NO'} suffix={details.review_design.clean_pre_selection_holdout === true ? '' : 'research_only'} />
      </section>
      <section className="tv-report-table-section">
        <div className="tv-report-card-head"><div><strong>成本压力</strong><span>报告原始场景，不换算为现金成本</span></div><small>{scenarios.length} scenarios</small></div>
        <SimpleHistoryTable
          headers={['成本 bps', '总收益', '最大回撤', '存活']}
          rows={scenarios.map((item) => {
            const values = recordValue(item.metrics);
            return [
              textValue(item.cost_bps),
              percent(numberValue(values.total_return_pct)),
              percent(numberValue(values.max_drawdown_pct)),
              item.survives === true || item.passed === true ? 'YES' : 'NO',
            ];
          })}
        />
      </section>
    </div>
  );
}

export function HistoricalTradeReview({details}: {details: BTCStrategyHistoryResponse['details']}) {
  const concentration = details.return_concentration;
  const best = objectList(concentration.best_trades);
  const worst = objectList(concentration.worst_trades);
  const rows: Array<Record<string, unknown> & {review: string}> = [
    ...best.map((item): Record<string, unknown> & {review: string} => ({...item, review: 'Best'})),
    ...worst.map((item): Record<string, unknown> & {review: string} => ({...item, review: 'Worst'})),
  ];
  return (
    <section className="tv-report-table-section" data-testid="btc-historical-trade-review">
      <div className="tv-report-card-head"><div><strong>历史交易集中度审查</strong><span>仅有 review-level trade summary；连续 ledger/fills 不可用时不合成交易</span></div><small>{textValue(concentration.trade_count)} reviewed</small></div>
      <SimpleHistoryTable
        headers={['分组', '方向', '开始', '结束', '收益', '成本', 'bars']}
        rows={rows.map((item) => [
          item.review,
          textValue(item['side']),
          formatIsoText(textValue(item['start'])),
          formatIsoText(textValue(item['end'])),
          percent(numberValue(item['total_return_pct'])),
          percent(numberValue(item['cost_return_pct'])),
          textValue(item['bar_count']),
        ])}
      />
      {!rows.length ? <p className="tv-report-empty">该历史快照未展开 trade review；没有伪造逐笔成交或净值曲线。</p> : null}
    </section>
  );
}

export function HistoricalRiskDetails({details}: {details: BTCStrategyHistoryResponse['details']}) {
  const regimes = objectList(details.market_regime_attribution.segments);
  const drawdown = details.max_drawdown_attribution;
  return (
    <div className="tv-history-detail-grid" data-testid="btc-historical-risk-details">
      <section className="tv-report-table-section">
        <div className="tv-report-card-head"><div><strong>市场状态归因</strong><span>research review segments</span></div><small>{regimes.length} regimes</small></div>
        <SimpleHistoryTable
          headers={['状态', '总收益', '最大回撤', '暴露', '通过']}
          rows={regimes.map((item) => {
            const values = recordValue(item.metrics);
            return [
              textValue(item.regime_label),
              percent(numberValue(values.total_return_pct)),
              percent(numberValue(values.max_drawdown_pct)),
              percent(numberValue(values.average_exposure) === undefined ? undefined : numberValue(values.average_exposure)! * 100),
              item.passed === true ? 'PASS' : 'BLOCKED',
            ];
          })}
        />
      </section>
      <section className="tv-report-card">
        <div className="tv-report-card-head"><div><strong>最大回撤归因</strong><span>不替代 ledger underwater series</span></div></div>
        <ReportMetric label="最大回撤" value={percent(numberValue(drawdown.max_drawdown_pct))} tone="bad" />
        <PropertyFact label="峰值时间" value={formatIsoText(textValue(drawdown.peak_time))} />
        <PropertyFact label="谷值时间" value={formatIsoText(textValue(drawdown.trough_time))} />
        <PropertyFact label="区间 bars" value={textValue(drawdown.bar_count || '—')} />
      </section>
    </div>
  );
}

function HistoricalSourceDetails({response}: {response: BTCStrategyHistoryResponse}) {
  const safetyFalse = Object.values(response.safety).every((value) => value === false);
  return (
    <section className="tv-evidence-matrix" data-testid="btc-historical-source-details">
      <EvidenceRow label="历史映射" value={`${response.relationship} · ${response.relationship_label}`} state={response.relationship === 'exact_candidate_historical_research_report'} />
      <EvidenceRow label="External snapshot" value={response.source.report_path} state={response.source.report_path.startsWith('artifacts/btc_strategy_history/runs/')} mono />
      <EvidenceRow label="Snapshot SHA-256" value={response.source.report_sha256} state={response.source.report_sha256.length === 64} mono />
      <EvidenceRow label="源代码身份" value={response.source.source_code_commit || 'unknown'} state={Boolean(response.source.source_code_commit)} mono />
      <EvidenceRow label="研究状态" value={response.research_status} state={false} />
      <EvidenceRow label="交易安全旗标" value="全部 false" state={safetyFalse} />
    </section>
  );
}

function SimpleHistoryTable({headers, rows}: {headers: string[]; rows: string[][]}) {
  return (
    <div className="tv-report-table-wrap">
      <table className="tv-report-table">
        <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>{rows.map((row, rowIndex) => <tr key={`${rowIndex}-${row.join('|')}`}>{row.map((cell, index) => <td key={`${rowIndex}-${index}`}>{cell || '—'}</td>)}</tr>)}</tbody>
      </table>
      {!rows.length ? <p className="tv-report-empty">历史快照未展开该明细。</p> : null}
    </div>
  );
}

function ReportMetric({label, value, suffix = '', tone: colorTone = ''}: {label: string; value: string; suffix?: string; tone?: string}) {
  return <div className={`tv-report-metric ${colorTone}`}><span>{label}</span><strong>{value}</strong>{suffix ? <small>{suffix}</small> : null}</div>;
}

function CompletedBacktestActions({onEdit}: {onEdit: () => void}) {
  const openEditor = (focusSelector = false) => {
    onEdit();
    window.requestAnimationFrame(() => {
      const editor = document.querySelector<HTMLElement>('[data-testid="btc-strategy-editor"]');
      editor?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
      if (focusSelector) editor?.querySelector<HTMLSelectElement>('select[aria-label="策略名"]')?.focus();
    });
  };
  return (
    <div className="crypto-backtest-completed-actions" data-testid="btc-backtest-completed-actions">
      <div>
        <span className="crypto-backtest-completed-kicker">NEXT RESEARCH RUN</span>
        <strong>继续比较策略</strong>
        <small>当前结果已置顶；以下操作只展开现有受控策略编辑器，不会重复请求。</small>
      </div>
      <div className="crypto-backtest-completed-buttons">
        <button type="button" className="primary" onClick={() => openEditor(false)}>再次回测</button>
        <button type="button" onClick={() => openEditor(true)}>选择其他策略</button>
        <button type="button" onClick={() => openEditor(false)}>编辑策略</button>
      </div>
    </div>
  );
}

function EvidenceUnavailable({text}: {text: string}) {
  return <p className="tv-report-empty tv-report-evidence-unavailable">无数据：{text}</p>;
}

function PropertyFact({label, value, mono = false}: {label: string; value: string; mono?: boolean}) {
  return <div className="tv-property-fact"><span>{label}</span><strong className={mono ? 'mono' : ''} title={value}>{value}</strong></div>;
}

function CostRow({label, value, emphasis = false}: {label: string; value?: number; emphasis?: boolean}) {
  return <div className={emphasis ? 'emphasis' : ''}><span>{label}</span><strong>{value === undefined ? '无数据' : money(value)}</strong>{value === undefined ? <small>当前 run 未公开该成本字段</small> : null}</div>;
}

function MetricTable({rows}: {rows: string[][]}) {
  return (
    <div className="tv-report-table-wrap"><table className="tv-report-table"><thead><tr><th>指标</th><th>全部</th><th>做多</th><th>做空</th></tr></thead><tbody>{rows.map((row) => <tr key={row[0]}>{row.map((cell, index) => <td key={`${row[0]}-${index}`}>{cell}</td>)}</tr>)}</tbody></table></div>
  );
}

function EventTable({markers, candles}: {markers: ChartSeriesPayload['markers']; candles: ChartSeriesPayload['candles']}) {
  if (!markers.length) return <p className="tv-report-empty">当前证据未公开可逐笔重放的 chart marker；Demo 成交请查看“成交”页签。</p>;
  const closeByTime = new Map(candles.map((item) => [item.time, item.close]));
  return (
    <div className="tv-report-table-wrap"><table className="tv-report-table"><thead><tr><th>#</th><th>类型</th><th>日期和时间</th><th>信号 / 事件</th><th>参考收盘价</th><th>来源</th></tr></thead><tbody>{markers.map((marker, index) => <tr key={`${marker.time}-${index}`}><td>{index + 1}</td><td className={marker.position === 'belowBar' ? 'good' : 'bad'}>{marker.position === 'belowBar' ? '做多侧' : '做空侧'}</td><td>{formatTime(marker.time)}</td><td>{marker.text || 'marker'}</td><td>{price(closeByTime.get(marker.time))}</td><td>backtest chart marker</td></tr>)}</tbody></table></div>
  );
}

function TradeLedgerTable({trades}: {trades: CanonicalTrade[]}) {
  return (
    <div className="tv-report-table-wrap"><table className="tv-report-table"><thead><tr><th>#</th><th>方向</th><th>入场 / 出场</th><th>价格</th><th>数量</th><th>Funding</th><th>手续费</th><th>净 PnL</th><th>累计 PnL</th></tr></thead><tbody>{trades.map((trade) => <tr key={trade.trade_number}><td>{trade.trade_number}</td><td className={trade.direction === 'long' ? 'good' : 'bad'}>{trade.direction === 'long' ? '做多' : '做空'}</td><td>{formatTime(trade.entry_time)}<br />{formatTime(trade.exit_time)}</td><td>{price(trade.entry_price)}<br />{price(trade.exit_price)}</td><td>{trade.quantity.toFixed(6)}<br /><small>{trade.duration_bars} bars</small></td><td className={trade.funding_cashflow === undefined ? '' : trade.funding_cashflow >= 0 ? 'good' : 'bad'}>{trade.funding_cashflow === undefined ? '无数据' : money(trade.funding_cashflow)}</td><td>{money(trade.commission)}</td><td className={trade.net_pnl >= 0 ? 'good' : 'bad'}>{money(trade.net_pnl)}<br /><small>{percent(trade.return_pct)}</small></td><td className={trade.cumulative_pnl >= 0 ? 'good' : 'bad'}>{money(trade.cumulative_pnl)}</td></tr>)}</tbody></table></div>
  );
}

function EvidenceRow({label, value, state, mono = false}: {label: string; value: string; state: boolean; mono?: boolean}) {
  return <div><span>{label}</span><strong className={mono ? 'mono' : ''}>{value}</strong><small className={state ? 'pass' : 'blocked'}>{state ? 'VERIFIED' : 'BLOCKED / UNKNOWN'}</small></div>;
}

function normalizeRunMonthlyReturns(value: unknown): CanonicalBacktestReport['series']['monthly_returns'] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const record = recordValue(item);
    const rawPeriod = textValue(record.period ?? record.month ?? record.time);
    const parsed = firstNumber(record.value, record.return_pct);
    if (!rawPeriod || parsed === undefined) return [];
    const timestamp = Number.isFinite(Number(record.time))
      ? Number(record.time)
      : Date.parse(rawPeriod) / 1000;
    if (!Number.isFinite(timestamp)) return [];
    return [{time: timestamp, value: parsed, month: rawPeriod.slice(0, 7)}];
  });
}

function normalizeRunCosts(diagnostics: Record<string, unknown>): CanonicalBacktestReport['series']['costs'] {
  const execution = recordValue(diagnostics.execution);
  const costs = recordValue(diagnostics.costs);
  const components = recordValue(diagnostics.cost_components);
  const candidates: Array<{key: string; label: string; values: unknown[]}> = [
    {key: 'commission_cost', label: '手续费', values: [components.commission_cost, costs.realized_commission, diagnostics.ledger_total_fees, execution.total_fees]},
    {key: 'fixed_slippage_cost', label: '固定滑点', values: [components.fixed_slippage_cost, costs.realized_slippage_cost, execution.total_slippage, diagnostics.ledger_total_slippage]},
    {key: 'market_impact_cost', label: '冲击成本', values: [components.market_impact_cost, execution.market_impact_cost]},
    {key: 'funding_cashflow', label: 'Funding', values: [components.funding_cashflow, components.funding_cost, execution.funding_cashflow]},
  ];
  return candidates.flatMap((candidate) => {
    const value = firstNumber(...candidate.values);
    return value === undefined ? [] : [{key: candidate.key, label: candidate.label, value}];
  });
}

function runEvidenceBlockers(
  diagnostics: Record<string, unknown>,
  equity: ChartSeriesPayload['equity'],
  drawdown: ChartSeriesPayload['drawdown'],
  monthlyReturns: CanonicalBacktestReport['series']['monthly_returns'],
  costs: CanonicalBacktestReport['series']['costs'],
): string[] {
  const blockers = ['research_only_registered_strategy_replay', 'promotion_evidence_not_granted'];
  if (diagnostics.ledger_equity_consistent !== true) blockers.push('current_run_ledger_equity_not_verified');
  if (diagnostics.pnl_source !== 'ledger_fills') blockers.push('current_run_pnl_source_not_ledger_fills');
  if (!equity.length) blockers.push('current_run_ledger_equity_series_missing');
  if (!drawdown.length) blockers.push('current_run_ledger_drawdown_series_missing');
  if (!monthlyReturns.length) blockers.push('current_run_monthly_returns_not_exposed');
  if (!costs.length) blockers.push('current_run_cost_components_not_exposed');
  return blockers;
}

function buildReportMetrics(
  summary: Summary | null,
  canonical: Record<string, unknown> | null,
  canonicalReport: CanonicalBacktestReport | null,
  capital: number,
  chart: ChartSeriesPayload | null,
  runEvidence?: {
    currentRun: boolean;
    equity: ChartSeriesPayload['equity'];
    trades: CanonicalTrade[];
    costs: Array<{key: string; label: string; value: number}>;
    diagnostics: Record<string, unknown>;
  },
) {
  const canonicalMetrics = recordValue(canonical?.metrics);
  const directCostComponents = recordValue(canonical?.cost_components);
  const runCostComponents = Object.fromEntries((runEvidence?.costs ?? []).map((item) => [item.key, item.value]));
  const costComponents = runEvidence?.currentRun
    ? runCostComponents
    : Object.keys(directCostComponents).length
    ? directCostComponents
    : recordValue(recordValue(canonical?.cost_model).components);
  const derivedMetrics = canonicalReport?.derived_metrics ?? {};
  const currentRun = runEvidence?.currentRun === true;
  const runLedgerConsistent = runEvidence?.diagnostics.ledger_equity_consistent === true;
  const runEquity = runEvidence?.equity ?? [];
  const equityInitial = firstNumber(runEquity[0]?.value);
  const equityFinal = firstNumber(runEquity.at(-1)?.value);
  const runNetProfit = runLedgerConsistent && equityInitial !== undefined && equityFinal !== undefined
    ? equityFinal - equityInitial
    : firstNumber(recordValue(runEvidence?.diagnostics.pnl).final_pnl);
  const runTotalReturn = runLedgerConsistent && equityInitial !== undefined && equityInitial !== 0 && runNetProfit !== undefined
    ? runNetProfit / equityInitial * 100
    : undefined;
  const totalReturn = currentRun
    ? runTotalReturn
    : firstNumber(summary?.total_return_pct, canonicalMetrics.total_return_pct);
  const annualReturn = firstNumber(summary?.annual_return_pct, canonicalMetrics.cagr_pct, canonicalMetrics.annual_return_pct);
  const maxDrawdown = currentRun
    ? firstNumber(runEvidence?.diagnostics.max_drawdown_pct, summary?.max_drawdown_pct)
    : firstNumber(summary?.max_drawdown_pct, canonicalMetrics.max_drawdown_pct);
  const maxDrawdownAbs = maxDrawdown === undefined ? undefined : Math.abs(maxDrawdown);
  // A marker/fill count is not a closed trade count.  For a current run we
  // only show trade metrics when an authoritative closed-trade series exists.
  const tradeCount = currentRun
    ? (runEvidence?.trades.length ? runEvidence.trades.length : undefined)
    : firstNumber(summary?.trade_count, derivedMetrics.trade_count, canonicalMetrics.trade_count);
  const winRate = currentRun
    ? (runEvidence?.trades.length ? runEvidence.trades.filter((trade) => trade.net_pnl > 0).length / runEvidence.trades.length * 100 : undefined)
    : firstNumber(summary?.win_rate_pct, derivedMetrics.win_rate_pct, canonicalMetrics.win_rate_pct);
  const estimatedWinners = firstNumber(derivedMetrics.winning_trade_count, tradeCount !== undefined && winRate !== undefined ? Math.round(tradeCount * winRate / 100) : undefined);
  const commissionCost = firstNumber(costComponents.commission_cost, runEvidence?.diagnostics.ledger_total_fees, recordValue(canonical?.diagnostics).ledger_total_fees);
  const fixedSlippageCost = firstNumber(costComponents.fixed_slippage_cost, runEvidence?.diagnostics.total_slippage, runEvidence?.diagnostics.ledger_total_slippage);
  const impactCost = firstNumber(costComponents.market_impact_cost);
  const fundingCashflow = firstNumber(costComponents.funding_cashflow, costComponents.funding_cost);
  const fundingCost = fundingCashflow === undefined ? undefined : Math.max(0, -fundingCashflow) || fundingCashflow;
  const costValues = [commissionCost, fixedSlippageCost, impactCost, fundingCost];
  const knownCost = costValues.some((value) => value !== undefined)
    ? costValues.reduce<number>((sum, value) => sum + (value ?? 0), 0)
    : undefined;
  const totalCost = currentRun
    ? firstNumber(runEvidence?.diagnostics.total_cost, recordValue(runEvidence?.diagnostics.execution).total_cost)
    : knownCost;
  const buyHoldReturn = computeBuyHold(chart?.candles ?? []);
  const initialCapital = currentRun ? firstNumber(equityInitial, capital) : summary ? capital : firstNumber(canonicalMetrics.initial_equity);
  const netProfit = currentRun
    ? runNetProfit
    : summary
      ? totalReturn === undefined ? undefined : capital * totalReturn / 100
    : firstNumber(canonicalMetrics.net_pnl);
  const currentTradeMetrics = currentRun && !runEvidence?.trades.length;
  return {
    initialCapital,
    totalReturn,
    annualReturn,
    annualVolatility: firstNumber(summary?.annual_volatility_pct, canonicalMetrics.annual_volatility_pct),
    maxDrawdownAbs,
    maxDrawdownCash: firstNumber(canonicalMetrics.max_drawdown_cash),
    winRate,
    tradeCount,
    estimatedWinners,
    estimatedLosers: tradeCount !== undefined && estimatedWinners !== undefined ? Math.max(0, tradeCount - estimatedWinners) : undefined,
    profitFactor: currentTradeMetrics ? undefined : firstNumber(summary?.profit_factor, derivedMetrics.profit_factor, canonicalMetrics.profit_factor),
    sharpe: firstNumber(summary?.sharpe_ratio, canonicalMetrics.annualized_sharpe, canonicalMetrics.sharpe_ratio),
    sortino: firstNumber(summary?.sortino_ratio, canonicalMetrics.sortino_ratio),
    calmar: firstNumber(summary?.calmar_ratio, canonicalMetrics.calmar_ratio),
    netProfit,
    expectedPayoff: netProfit !== undefined && tradeCount ? netProfit / tradeCount : undefined,
    largestWinner: firstNumber(derivedMetrics.largest_winner),
    largestLoser: firstNumber(derivedMetrics.largest_loser),
    averageDurationBars: firstNumber(derivedMetrics.average_duration_bars),
    buyHoldReturn,
    outperformance: totalReturn !== undefined && buyHoldReturn !== undefined ? totalReturn - buyHoldReturn : undefined,
    commissionCost,
    fixedSlippageCost,
    impactCost,
    fundingCost,
    knownCost,
    totalCost,
    costCoverageComplete: currentRun ? Boolean(totalCost !== undefined && costValues.every((value) => value !== undefined)) : costValues.every((value) => value !== undefined),
  };
}

function buildSideMetrics(trades: CanonicalTrade[]) {
  return {
    long: summarizeTrades(trades.filter((trade) => trade.direction === 'long')),
    short: summarizeTrades(trades.filter((trade) => trade.direction === 'short')),
  };
}

function summarizeTrades(trades: CanonicalTrade[]) {
  const pnls = trades.map((trade) => trade.net_pnl);
  const winners = pnls.filter((value) => value > 0);
  const losers = pnls.filter((value) => value < 0);
  const grossLoss = Math.abs(losers.reduce((sum, value) => sum + value, 0));
  return {
    tradeCount: trades.length || undefined,
    winners: winners.length || (trades.length ? 0 : undefined),
    netPnl: trades.length ? pnls.reduce((sum, value) => sum + value, 0) : undefined,
    winRate: trades.length ? winners.length / trades.length * 100 : undefined,
    averagePnl: trades.length ? pnls.reduce((sum, value) => sum + value, 0) / trades.length : undefined,
    profitFactor: trades.length && grossLoss ? winners.reduce((sum, value) => sum + value, 0) / grossLoss : undefined,
  };
}

function computeBuyHold(candles: ChartSeriesPayload['candles']): number | undefined {
  const first = candles[0]?.close;
  const last = candles.at(-1)?.close;
  return Number.isFinite(first) && Number.isFinite(last) && first !== 0 ? (Number(last) / Number(first) - 1) * 100 : undefined;
}

function reportPeriod(equity: CanonicalBacktestReport['series']['equity'], trades: CanonicalTrade[]): string {
  const times = [
    ...equity.map((item) => item.time),
    ...trades.flatMap((trade) => [trade.entry_time, trade.exit_time]),
  ].filter(Number.isFinite);
  if (!times.length) return '区间未展开';
  return `${formatDate(Math.min(...times))} — ${formatDate(Math.max(...times))}`;
}

function formatDate(value: number): string {
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toISOString().slice(0, 10);
}

function evidenceText(source: Record<string, unknown> | null, ...paths: string[][]): string {
  for (const path of paths) {
    let current: unknown = source;
    for (const key of path) current = current && typeof current === 'object' && !Array.isArray(current) ? (current as Record<string, unknown>)[key] : undefined;
    if (current !== undefined && current !== null && current !== '') return String(current);
  }
  return 'API 摘要未展开';
}

function evidenceBoolean(source: Record<string, unknown> | null, path: string[]): boolean {
  let current: unknown = source;
  for (const key of path) current = current && typeof current === 'object' && !Array.isArray(current) ? (current as Record<string, unknown>)[key] : undefined;
  return current === true || current === 'pass' || current === 'verified';
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = Number(value);
    if (value !== '' && value !== null && value !== undefined && Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function arrayStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function textValue(value: unknown): string {
  return value === undefined || value === null ? '' : String(value);
}

function objectList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function numberValue(value: unknown): number | undefined {
  const parsed = Number(value);
  return value !== '' && value !== null && value !== undefined && Number.isFinite(parsed) ? parsed : undefined;
}

function formatIsoText(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString().replace('.000Z', 'Z');
}

function shortHash(value: string): string {
  return value ? `${value.slice(0, 12)}…${value.slice(-6)}` : '—';
}

function money(value: number | undefined): string {
  return Number.isFinite(value) ? `${Number(value).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} USDT` : '—';
}

function percent(value: number | undefined): string {
  return Number.isFinite(value) ? `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}%` : '—';
}

function unsignedPercent(value: number | undefined): string {
  return Number.isFinite(value) ? `${Math.abs(Number(value)).toFixed(2)}%` : '—';
}

function fixed(value: number | undefined, digits = 2): string {
  return Number.isFinite(value) ? Number(value).toFixed(digits) : '—';
}

function integer(value: number | undefined): string {
  return Number.isFinite(value) ? String(Math.round(Number(value))) : '—';
}

function tone(value: number | undefined): string {
  if (!Number.isFinite(value) || Number(value) === 0) return '';
  return Number(value) > 0 ? 'good' : 'bad';
}

function price(value: number | undefined): string {
  return Number.isFinite(value) ? Number(value).toLocaleString('zh-CN', {minimumFractionDigits: 1, maximumFractionDigits: 1}) : '—';
}

function formatTime(value: number): string {
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {hour12: false});
}
