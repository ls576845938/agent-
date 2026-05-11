import type {ChartSeriesPayload, RunStatusResponse} from '../../lib/view-model';
import type {MvpStep, ReportSection, OptimizationHint, DrawdownPeriod, PeriodReturn} from '../../lib/shared-types';
import {mvpStepClass, metricClass, reportMetricClass, hintClass, formatPrice, formatTimestamp, formatIso, formatParams} from '../../lib/utils';
import LineChart from '../../components/LineChart';
import CandleChart from '../../components/CandleChart';

interface ResultsPanelProps {
  children?: unknown;
  mvpSteps: MvpStep[];
  mvpDoneCount: number;
  mvpLoading: boolean;
  mvpMessage: string;
  disableMvp: boolean;
  error: string;
  promotionGate?: {next_stage: string; manifest_id: string} | null;
  metricCards: Array<{label: string; value: string; tone: string}>;
  reportSections: ReportSection[];
  optimizationHints: OptimizationHint[];
  chart: ChartSeriesPayload | null;
  run: RunStatusResponse | null;
  viewModel: {hasResult: boolean; hasError: boolean; candleCount: number; equityPoints: number; statusTone: string};
  drawdownPeriods: DrawdownPeriod[];
  monthlyReturns: PeriodReturn[];
  blockers: {
    dataQualityBlockers: string[];
    promotionBlockers: string[];
    coverageBlockers: string[];
    blockers: string[];
  };
  onMvpAcceptance: () => void;
}

export default function ResultsPanel({
  children,
  mvpSteps, mvpDoneCount, mvpLoading, mvpMessage, disableMvp,
  error, promotionGate,
  metricCards,
  reportSections, optimizationHints,
  chart, run, viewModel,
  drawdownPeriods, monthlyReturns,
  blockers,
  onMvpAcceptance,
}: ResultsPanelProps) {
  return (
    <>
      <section className="panel mvp-panel" data-testid="crypto-results">
        <div className="panel-header"><h2>MVP 交付闭环</h2><span>已完成 {mvpDoneCount}/{mvpSteps.length}</span></div>
        <div className="mvp-command-row">
          <div><strong>{promotionGate ? promotionGate.next_stage : run?.status === 'completed' ? 'ready_for_gate' : 'research_ready'}</strong><p>{promotionGate?.manifest_id ? `Manifest ${promotionGate.manifest_id}` : '事件驱动回测结果待验收'}</p></div>
          <button type="button" className="primary-button" disabled={disableMvp} onClick={onMvpAcceptance}>{mvpLoading ? '验收中...' : '一键 MVP 验收'}</button>
        </div>
        <div className="mvp-step-grid">
          {mvpSteps.map((step, i) => (
            <div key={step.id} className={mvpStepClass(step.status)}><span>{i + 1}</span><strong>{step.label}</strong><p>{step.detail}</p></div>
          ))}
        </div>
        {mvpMessage ? <p className="data-message">{mvpMessage}</p> : null}
      </section>

      {error ? <div className="panel error-panel"><div className="panel-header"><h2>运行错误</h2></div><p>{error}</p></div> : null}

      <section className="panel insight-panel" data-testid="crypto-blockers">
        <div className="panel-header"><h3>Data quality / promotion blockers</h3><span>{blockers.blockers.length} 项</span></div>
        <div className="hint-list">
          {blockers.coverageBlockers.map((item) => <div key={item} className="hint-row hint-medium"><span>coverage</span><p>{item}</p></div>)}
          {blockers.dataQualityBlockers.map((item) => <div key={item} className="hint-row hint-high"><span>quality</span><p>{item}</p></div>)}
          {blockers.promotionBlockers.map((item) => <div key={item} className="hint-row hint-medium"><span>promotion</span><p>{item}</p></div>)}
          {!blockers.blockers.length ? <div className="hint-row"><span>ready</span><p>SQLite 覆盖、event-driven 回测和准入门都没有显式 blocker。</p></div> : null}
        </div>
      </section>

      {children}

      <section className="metrics-grid">
        {metricCards.length > 0 ? metricCards.map((card) => (
          <article key={card.label} className={metricClass(card.tone)}><span>{card.label}</span><strong>{card.value}</strong></article>
        )) : (
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
    </>
  );
}
