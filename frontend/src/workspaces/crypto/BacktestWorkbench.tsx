import {useEffect, useMemo, useState} from 'react';

import type {ChartSeriesPayload, RunStatusResponse} from '../../lib/view-model';
import {formatIso} from '../../lib/utils';
import CanonicalEvidencePanel from './CanonicalEvidencePanel';
import {LightweightAreaChart, LightweightCandlestickChart} from './LightweightBacktestCharts';

const HISTORY_KEY = 'quantstation.btc.backtest-workbench.v1';
const MAX_HISTORY = 12;
const MAX_COMPARE = 4;

type RunSnapshot = {
  run: RunStatusResponse;
  chart: ChartSeriesPayload;
  candidateId: string;
  strategyVersion: string;
  savedAt: string;
};

type StrategyIdentity = {candidateId: string; strategyVersion: string};

function readHistory(): RunSnapshot[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((item) => item?.run?.run_id && item?.chart) : [];
  } catch {
    return [];
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function textValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, {maximumFractionDigits: 6}) : '未提供';
  return String(value);
}

function nested(source: Record<string, unknown>, ...path: string[]): unknown {
  let current: unknown = source;
  for (const key of path) current = record(current)[key];
  return current;
}

export default function BacktestWorkbench({
  run,
  chart,
  strategyIdentity,
  onRestore,
}: {
  run: RunStatusResponse | null;
  chart: ChartSeriesPayload | null;
  strategyIdentity: StrategyIdentity;
  onRestore: (run: RunStatusResponse, chart: ChartSeriesPayload) => void;
}) {
  const [history, setHistory] = useState<RunSnapshot[]>(() => readHistory());
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    if (!run || run.status !== 'completed' || !chart) return;
    const snapshot: RunSnapshot = {
      run,
      chart,
      candidateId: strategyIdentity.candidateId,
      strategyVersion: strategyIdentity.strategyVersion,
      savedAt: new Date().toISOString(),
    };
    setHistory((current) => {
      const next = [snapshot, ...current.filter((item) => item.run.run_id !== run.run_id)].slice(0, MAX_HISTORY);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      return next;
    });
  }, [chart, run, strategyIdentity.candidateId, strategyIdentity.strategyVersion]);

  const compareRuns = useMemo(() => history.filter((item) => selectedIds.includes(item.run.run_id)), [history, selectedIds]);
  const diagnostics = record(run?.diagnostics);
  const identity = record(diagnostics.btc_strategy_identity);
  const quantstats = record(diagnostics.quantstats_ledger_profile);
  const quantstatsMetrics = record(quantstats.quantstats_metrics);
  const internalMetrics = record(quantstats.metrics);
  const quantstatsCrosscheck = record(quantstats.crosscheck);
  const evidence = [
    ['策略身份 manifest', diagnostics.btc_run_manifest_path],
    ['回测 manifest', diagnostics.manifest_path],
    ['账本 artifact', diagnostics.ledger_artifact_path],
  ].filter(([, value]) => typeof value === 'string' && value);
  const diagnosticsRows = [
    ['资金费现金流', diagnostics.funding_cashflow ?? nested(diagnostics, 'funding', 'cashflow')],
    ['Mark Price', diagnostics.mark_price ?? nested(diagnostics, 'perpetual', 'mark_price')],
    ['Index Price', diagnostics.index_price ?? nested(diagnostics, 'perpetual', 'index_price')],
    ['清算缓冲 bps', diagnostics.liquidation_buffer_bps ?? nested(diagnostics, 'risk', 'liquidation_buffer_bps')],
    ['账本总费用', diagnostics.ledger_total_fees],
    ['成本拖累 %', nested(diagnostics, 'execution', 'cost_drag_pct')],
  ];

  const toggleCompare = (runId: string) => {
    setSelectedIds((current) => {
      if (current.includes(runId)) return current.filter((item) => item !== runId);
      if (current.length >= MAX_COMPARE) return current;
      return [...current, runId];
    });
  };

  return (
    <section className="backtest-workbench" data-testid="btc-backtest-workbench">
      <CanonicalEvidencePanel />
      <section className="panel workbench-identity-panel">
        <div className="panel-header"><h2>Backtest Workbench</h2><span>研究证据 · 非交易界面</span></div>
        <div className="workbench-identity-grid">
          <div><span>Run ID</span><strong>{run?.run_id ?? '等待回测'}</strong></div>
          <div><span>Candidate</span><strong>{textValue(identity.candidate_id ?? strategyIdentity.candidateId)}</strong></div>
          <div><span>Strategy Version</span><strong>{textValue(identity.strategy_version ?? strategyIdentity.strategyVersion)}</strong></div>
          <div><span>Data Version</span><strong>{textValue(diagnostics.data_version)}</strong></div>
          <div><span>PnL Source</span><strong>{textValue(diagnostics.pnl_source)}</strong></div>
          <div><span>Ledger Reconciled</span><strong>{textValue(diagnostics.ledger_equity_consistent)}</strong></div>
        </div>
        <p className="data-message">PnL 仅接受 fills / positions / cash ledger 路径；paper、live、broker、order、OMS、private endpoint 均未启用。</p>
        {run ? <div className="workbench-evidence-actions"><a className="secondary-button" href={`/api/runs/${run.run_id}/evidence`} target="_blank" rel="noreferrer">打开运行证据 JSON</a><a className="secondary-button" href={`/api/runs/${run.run_id}/chart`} target="_blank" rel="noreferrer">打开图表数据 JSON</a></div> : null}
      </section>

      <div className="workbench-chart-grid">
        <LightweightAreaChart title="权益曲线" points={chart?.equity ?? []} color="#38bdf8" />
        <LightweightAreaChart title="回撤曲线" points={chart?.drawdown ?? []} color="#f97316" />
        <LightweightAreaChart title="换手率" points={chart?.turnover ?? []} color="#a78bfa" />
        <LightweightAreaChart title="动态杠杆" points={chart?.leverage ?? []} color="#ef4444" />
      </div>
      <LightweightCandlestickChart candles={chart?.candles ?? []} markers={chart?.markers ?? []} />

      <section className="analysis-grid workbench-analysis-grid">
        <article className="panel table-panel">
          <div className="panel-header"><h3>永续与成本归因</h3><span>缺失即明确缺失</span></div>
          <div className="detail-table">{diagnosticsRows.map(([label, value]) => <div key={String(label)} className="detail-row"><span>{label}</span><span>{textValue(value)}</span></div>)}</div>
        </article>
        <article className="panel table-panel" data-testid="quantstats-crosscheck">
          <div className="panel-header"><h3>QuantStats 账本交叉校验</h3><span>{textValue(quantstats.status)}</span></div>
          <p className="data-message">第三方指标仅作 cross-check，不是 canonical PnL，也不拥有 promotion 权限。</p>
          <div className="detail-table">
            <div className="detail-row"><span>输入来源</span><span>{textValue(quantstats.pnl_source)}</span></div>
            <div className="detail-row"><span>内部收益</span><span>{textValue(internalMetrics.total_return_pct)}%</span></div>
            <div className="detail-row"><span>QS CAGR</span><span>{textValue(quantstatsMetrics.cagr)}</span></div>
            <div className="detail-row"><span>QS Sharpe</span><span>{textValue(quantstatsMetrics.sharpe)}</span></div>
            <div className="detail-row"><span>QS Max DD</span><span>{textValue(quantstatsMetrics.max_drawdown)}</span></div>
            <div className="detail-row"><span>差异状态</span><span>{textValue(quantstatsCrosscheck.status)}</span></div>
            <div className="detail-row"><span>差异误差</span><span>{textValue(quantstatsCrosscheck.error)}</span></div>
          </div>
        </article>
      </section>

      <section className="panel workbench-evidence-panel">
        <div className="panel-header"><h3>证据链接</h3><span>{evidence.length} 项</span></div>
        {evidence.length ? <div className="detail-table">{evidence.map(([label, value]) => <div key={String(label)} className="detail-row evidence-row"><span>{label}</span><code>{String(value)}</code></div>)}</div> : <p className="chart-empty-state">当前运行尚未提供 artifact 路径。</p>}
      </section>

      <section className="panel workbench-history-panel">
        <div className="panel-header"><h3>历史运行与对比</h3><span>选择 2–4 个运行</span></div>
        <div className="workbench-history-list">
          {history.map((item) => (
            <div className="workbench-history-row" key={item.run.run_id}>
              <label><input type="checkbox" checked={selectedIds.includes(item.run.run_id)} disabled={!selectedIds.includes(item.run.run_id) && selectedIds.length >= MAX_COMPARE} onChange={() => toggleCompare(item.run.run_id)} /><span>{item.run.run_id.slice(0, 12)}</span></label>
              <span>{item.candidateId || 'identity unavailable'}</span>
              <span>{formatIso(item.savedAt)}</span>
              <button type="button" className="secondary-button" onClick={() => onRestore(item.run, item.chart)}>恢复</button>
            </div>
          ))}
          {!history.length ? <p className="chart-empty-state">完成一次回测后，浏览器会保存最多 {MAX_HISTORY} 个只读快照。</p> : null}
        </div>
        {compareRuns.length >= 2 ? (
          <div className="workbench-compare-wrap" data-testid="backtest-run-compare">
            <table className="workbench-compare-table">
              <thead><tr><th>指标</th>{compareRuns.map((item) => <th key={item.run.run_id}>{item.run.run_id.slice(0, 8)}</th>)}</tr></thead>
              <tbody>
                <tr><td>总收益 %</td>{compareRuns.map((item) => <td key={item.run.run_id}>{item.run.summary?.total_return_pct.toFixed(2) ?? '-'}</td>)}</tr>
                <tr><td>Sharpe</td>{compareRuns.map((item) => <td key={item.run.run_id}>{item.run.summary?.sharpe_ratio.toFixed(2) ?? '-'}</td>)}</tr>
                <tr><td>最大回撤 %</td>{compareRuns.map((item) => <td key={item.run.run_id}>{item.run.summary?.max_drawdown_pct.toFixed(2) ?? '-'}</td>)}</tr>
                <tr><td>交易数</td>{compareRuns.map((item) => <td key={item.run.run_id}>{item.run.summary?.trade_count ?? '-'}</td>)}</tr>
                <tr><td>账本一致</td>{compareRuns.map((item) => <td key={item.run.run_id}>{textValue(item.run.diagnostics?.ledger_equity_consistent)}</td>)}</tr>
              </tbody>
            </table>
          </div>
        ) : <p className="data-message">至少选择两个历史运行后显示并排比较；最多四个。</p>}
      </section>
    </section>
  );
}
