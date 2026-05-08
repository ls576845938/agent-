import {useEffect, useState} from 'react';

import LineChart from '../components/LineChart';
import StatusBadge from '../components/StatusBadge';
import type {StrategyInfo} from '../lib/view-model';
import {buildDateBoundary, formatPrice, mvpStepClass} from '../lib/utils';
import type {EventDrivenCostStressResponse, MvpStep, ValueEvent} from '../lib/shared-types';

type USEquityFormState = {
  symbol: string;
  barSize: '1m' | '2m' | '5m' | '15m' | '30m' | '1h' | '1d';
  startDate: string;
  endDate: string;
  dataRoot: string;
  strategyId: string;
  ledgerDir: string;
};

const defaultUSForm: USEquityFormState = {
  symbol: 'AAPL', barSize: '1d',
  startDate: '2024-01-01', endDate: '2024-06-01',
  dataRoot: 'data', strategyId: 'trend_momentum',
  ledgerDir: 'data/ledger/paper',
};

type USEquitySyncResponse = {run_id: string; status: string; symbol: string; bar_size: string; rows_received: number; rows_cleaned: number};
type USFeatureBuildResponse = {run_id: string; status: string; rows_written: number; version: string};
type USEventBacktestResponse = {run_id: string; status: string; summary: Record<string, number>; order_count: number; fill_count: number; snapshot_count: number; event_count: number};
type USReconciliationResponse = {status: string; break_count: number; breaks: Array<{symbol: string; local_quantity: number; broker_quantity: number}>; halt_new_orders?: boolean; alert_sent?: boolean; cash_diff?: number; position_diffs?: Record<string, unknown>; order_diffs?: Record<string, unknown>; fill_diffs?: Record<string, unknown>; report_path?: string};
type USQualityReportResponse = {symbol: string; data_version: string; total_issues: number; has_issues: boolean; reports: Array<{report_type: string; issues_found: number; details: Array<Record<string, unknown>>}>};
type USUnifiedBacktestResponse = {run_id: string; status: string; summary: Record<string, number>; equity_consistent: boolean; equity_consistency_msg: string; order_count: number; fill_count: number; snapshot_count: number; event_count: number; ledger_final_equity: number; ledger_total_fees: number; equity_curve: Array<{time: number; value: number}>; drawdown_curve: Array<{time: number; value: number}>};
type USPaperStatusResponse = {equity: number; cash: number; buying_power: number; positions: number; kill_switch_triggered: boolean; kill_switch_reason: string | null; days_traded: number; healthy: boolean; last_reconciliation_passed: boolean | null};
type USPaperDayResultResponse = {date: string; starting_equity: number; ending_equity: number; daily_pnl: number; daily_return_pct: number; orders_submitted: number; orders_filled: number; orders_rejected: number; orders_cancelled: number; kill_switch_triggered: boolean; reconciliation_passed: boolean; reconciliation_diff: Record<string, unknown>; errors: string[]};
type PaperBacktestResponse = {status: string; days_processed: number; total_pnl: number; final_equity: number; healthy: boolean; kill_switch_triggered: boolean; daily_results: USPaperDayResultResponse[]};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {...init, headers: {'Content-Type': 'application/json', ...(init?.headers ?? {})}});
  if (!response.ok) { const message = await response.text(); throw new Error(message || `Failed: ${response.status}`); }
  return response.json() as Promise<T>;
}

export type USEquityWorkspaceProps = {
  strategies: StrategyInfo[];
};

export default function USEquityWorkspace({strategies}: USEquityWorkspaceProps) {
  const [usForm, setUSForm] = useState<USEquityFormState>(() => ({
    ...defaultUSForm,
    strategyId: strategies[0]?.id ?? defaultUSForm.strategyId,
  }));
  const [usLoading, setUSLoading] = useState(false);
  const [usMessage, setUSMessage] = useState('');
  const [usSync, setUSSync] = useState<USEquitySyncResponse | null>(null);
  const [usFeature, setUSFeature] = useState<USFeatureBuildResponse | null>(null);
  const [usBacktest, setUSBacktest] = useState<USEventBacktestResponse | null>(null);
  const [usReconcile, setUSReconcile] = useState<USReconciliationResponse | null>(null);
  const [usQualityReport, setUSQualityReport] = useState<USQualityReportResponse | null>(null);
  const [usUnifiedBacktest, setUSUnifiedBacktest] = useState<USUnifiedBacktestResponse | null>(null);
  const [usPaperStatus, setUSPaperStatus] = useState<USPaperStatusResponse | null>(null);
  const [usPaperDailyResults, setUSPaperDailyResults] = useState<USPaperDayResultResponse[]>([]);
  const [paperBacktest, setPaperBacktest] = useState<PaperBacktestResponse | null>(null);
  const [edCostStress, setEDCostStress] = useState<EventDrivenCostStressResponse | null>(null);
  const [promotionGateResult, setPromotionGateResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (strategies.length > 0 && !strategies.find(s => s.id === usForm.strategyId)) {
      setUSForm(f => ({...f, strategyId: strategies[0].id}));
    }
  }, [strategies]);

  const handleUSDataSync = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USEquitySyncResponse>('/api/us/data/sync', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot,
      })});
      setUSSync(result); setUSMessage(`同步完成：清洗 ${result.rows_cleaned} 行`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '同步失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSBuildFeatures = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USFeatureBuildResponse>('/api/us/features/build', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot, version: 'v1', universe: 'default', auto_sync: true,
      })});
      setUSFeature(result); setUSMessage(`因子构建完成：写入 ${result.rows_written} 行`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '构建失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSBacktest = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USEventBacktestResponse>('/api/us/backtests/event', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot, auto_sync: true,
      })});
      setUSBacktest(result); setUSMessage(`事件回测完成：${result.fill_count} 成交 / ${result.order_count} 订单`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '回测失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSReconcile = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USReconciliationResponse>('/api/us/reconcile', {method: 'POST', body: JSON.stringify({ledger_dir: usForm.ledgerDir, tolerance: 0.000001})});
      setUSReconcile(result); setUSMessage(result.status === 'clean' ? '对账一致' : `发现 ${result.break_count} 个差异`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '对账失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSUnifiedBacktest = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USUnifiedBacktestResponse>('/api/us/backtests/unified', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot, auto_sync: true,
      })});
      setUSUnifiedBacktest(result); setUSMessage(result.equity_consistent ? '权益验证 PASS' : '权益验证 FAIL');
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '回测失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSPaperRunDay = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      await fetchJson<USPaperDayResultResponse>('/api/us/paper/run-day', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        strategy_id: usForm.strategyId, target_date: usForm.startDate, data_root: usForm.dataRoot, capital: 100000,
      })});
      handleUSPaperStatus(); handleUSPaperDailyResults();
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '运行失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSPaperStatus = async () => {
    try {
      const result = await fetchJson<USPaperStatusResponse>('/api/us/paper/status');
      setUSPaperStatus(result);
    } catch { /* silent */ }
  };

  const handleUSPaperDailyResults = async () => {
    try {
      const results = await fetchJson<USPaperDayResultResponse[]>('/api/us/paper/daily-results');
      setUSPaperDailyResults(results);
    } catch { /* silent */ }
  };

  const handleUSPaperBacktest = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<PaperBacktestResponse>('/api/us/paper/backtest', {method: 'POST', body: JSON.stringify({
        vendor: 'yfinance', asset_class: 'equity', symbol: usForm.symbol, bar_size: usForm.barSize,
        strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        data_root: usForm.dataRoot, capital: 100000, auto_sync: true,
      })});
      setPaperBacktest(result); setUSMessage(`纸交易回测：${result.days_processed} 天 PnL $${result.total_pnl.toFixed(2)}`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '回测失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSQualityReport = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<USQualityReportResponse>('/api/us/data/quality-report', {method: 'POST', body: JSON.stringify({
        symbol: usForm.symbol, start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize), data_root: usForm.dataRoot,
      })});
      setUSQualityReport(result); setUSMessage(result.has_issues ? `发现 ${result.total_issues} 个问题` : '数据质量通过');
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '检查失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSCostStressED = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<EventDrivenCostStressResponse>('/api/backtests/cost-stress/event-driven', {method: 'POST', body: JSON.stringify({
        source: 'fixture', symbol: usForm.symbol, interval: '1h', strategy_id: usForm.strategyId,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000, max_scenarios: 5,
      })});
      setEDCostStress(result); setUSMessage(`成本压力 ${result.survival_rate_pct.toFixed(0)}% 生存率`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSWalkForward = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<{stability: Record<string, unknown>; windows: Array<unknown>}>('/api/backtests/walk-forward', {method: 'POST', body: JSON.stringify({
        source: 'yfinance', symbol: usForm.symbol, interval: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000, commission_rate: 0.0001, strategy_id: usForm.strategyId, data_root: usForm.dataRoot,
      })});
      setUSMessage(`Walk-Forward: pass_rate ${((result.stability.pass_rate_pct ?? 0) as number).toFixed(0)}%, ${(result.windows as Array<unknown>).length} windows`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSPromotionGate = async () => {
    setUSLoading(true); setUSMessage('');
    try {
      const result = await fetchJson<{decision: string; next_stage: string; gates: Array<{name: string; status: string}>}>('/api/research/promotion-gate', {method: 'POST', body: JSON.stringify({
        strategy_id: usForm.strategyId, symbol: usForm.symbol, interval: usForm.barSize,
        start: buildDateBoundary(usForm.startDate, 'start', usForm.barSize),
        end: buildDateBoundary(usForm.endDate, 'end', usForm.barSize),
        capital: 100000, source: 'yfinance', data_root: usForm.dataRoot, skip_deep_checks: false,
      })});
      setPromotionGateResult(result as unknown as Record<string, unknown>);
      const passed = result.gates.filter(g => g.status === 'pass').length;
      setUSMessage(`Promotion Gate: ${result.decision} → ${result.next_stage} (${passed}/${result.gates.length} pass)`);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '失败'); }
    finally { setUSLoading(false); }
  };

  const handleUSPaperReset = async () => {
    setUSLoading(true);
    try {
      await fetchJson<{status: string}>('/api/us/paper/reset', {method: 'POST'});
      setUSMessage('纸交易已重置');
      setPaperBacktest(null); setUSPaperStatus(null); setUSPaperDailyResults([]);
    } catch (e: unknown) { setUSMessage(e instanceof Error ? e.message : '重置失败'); }
    finally { setUSLoading(false); }
  };

  const workflowSteps: MvpStep[] = [
    {id: 'data', label: '数据同步', status: usSync ? 'done' : 'pending', detail: usSync ? `${usSync.rows_cleaned} 行清洗` : '等待同步'},
    {id: 'features', label: '因子构建', status: usFeature ? 'done' : usSync ? 'warn' : 'pending', detail: usFeature ? `${usFeature.rows_written} 行` : '等待构建'},
    {id: 'backtest', label: '事件回测', status: usBacktest ? 'done' : usFeature ? 'warn' : 'pending', detail: usBacktest ? `${usBacktest.fill_count} 笔成交` : '等待回测'},
    {id: 'unified', label: '权益验证', status: usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? 'done' : 'fail') : usBacktest ? 'warn' : 'pending', detail: usUnifiedBacktest ? (usUnifiedBacktest.equity_consistent ? '一致' : '不一致') : '等待验证'},
    {id: 'paper', label: '纸交易', status: usPaperStatus?.days_traded && usPaperStatus.days_traded > 0 ? (usPaperStatus.healthy ? 'done' : 'warn') : usUnifiedBacktest ? 'warn' : 'pending', detail: usPaperStatus ? `${usPaperStatus.days_traded} 天 ${usPaperStatus.healthy ? '健康' : '异常'}` : '等待运行'},
  ];

  return (
    <main className="us-workspace">
      <section className="panel us-command-panel">
        <div className="panel-header"><h2>美股任务配置</h2><span>{usBacktest?.status ?? 'event chain'}</span></div>

        <div className="form-grid us-form-grid">
          <label>标的<input value={usForm.symbol} onChange={(e: ValueEvent) => setUSForm({...usForm, symbol: e.target.value.toUpperCase()})} /></label>
          <label>周期
            <select value={usForm.barSize} onChange={(e: ValueEvent) => setUSForm({...usForm, barSize: e.target.value as USEquityFormState['barSize']})}>
              {['1d', '1h', '30m', '15m', '5m', '2m', '1m'].map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label>开始日期<input type="date" value={usForm.startDate} onChange={(e: ValueEvent) => setUSForm({...usForm, startDate: e.target.value})} /></label>
          <label>结束日期<input type="date" value={usForm.endDate} onChange={(e: ValueEvent) => setUSForm({...usForm, endDate: e.target.value})} /></label>
          <label className="wide-grid-field">数据湖根目录<input value={usForm.dataRoot} onChange={(e: ValueEvent) => setUSForm({...usForm, dataRoot: e.target.value})} /></label>
          <label>策略
            <select value={usForm.strategyId} onChange={(e: ValueEvent) => setUSForm({...usForm, strategyId: e.target.value})}>
              {strategies.map(s => <option key={s.id} value={s.id}>{s.display_name}</option>)}
            </select>
          </label>
          <label>Ledger<input value={usForm.ledgerDir} onChange={(e: ValueEvent) => setUSForm({...usForm, ledgerDir: e.target.value})} /></label>
        </div>

        <div className="data-actions us-actions">
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSDataSync}>同步数据湖</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBuildFeatures}>构建因子</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSBacktest}>事件回测</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSReconcile}>持仓核对</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSUnifiedBacktest}>统一回测</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperRunDay}>纸交易（日）</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPaperBacktest}>纸交易回测</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSQualityReport}>数据质量</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSCostStressED}>成本压力</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSWalkForward}>Walk-Forward</button>
          <button type="button" className="secondary-button" disabled={usLoading} onClick={handleUSPromotionGate}>晋升门</button>
          <button type="button" className="secondary-button danger" disabled={usLoading} onClick={handleUSPaperReset}>重置</button>
        </div>

        {usMessage ? <p className="data-message">{usMessage}</p> : null}
      </section>

      <section className="panel mvp-panel">
        <div className="panel-header"><h2>美股工作流</h2><span>同步 → 回测 → 验证 → 纸交易</span></div>
        <div className="mvp-step-grid">
          {workflowSteps.map((step, i) => (
            <div key={step.id} className={mvpStepClass(step.status)}><span>{i + 1}</span><strong>{step.label}</strong><p>{step.detail}</p></div>
          ))}
        </div>
      </section>

      <section className="panel us-output-panel">
        <div className="panel-header"><h2>链路状态</h2><span>{usLoading ? 'running' : 'idle'}</span></div>
        <div className="us-stage-grid">
          <div><span>清洗数据</span><strong>{usSync ? `${usSync.rows_cleaned}/${usSync.rows_received}` : '-'}</strong></div>
          <div><span>因子行数</span><strong>{usFeature?.rows_written ?? '-'}</strong></div>
          <div><span>事件/成交</span><strong>{usBacktest ? `${usBacktest.event_count}/${usBacktest.fill_count}` : '-'}</strong></div>
          <div><span>对账</span><strong>{usReconcile ? `${usReconcile.status} (${usReconcile.break_count})` : '-'}</strong></div>
        </div>
        <div className="us-mini-metrics">
          <div><span>总收益</span><strong>{usBacktest ? `${(usBacktest.summary.total_return_pct ?? 0).toFixed(2)}%` : '-'}</strong></div>
          <div><span>Sharpe</span><strong>{usBacktest ? (usBacktest.summary.sharpe_ratio ?? 0).toFixed(2) : '-'}</strong></div>
          <div><span>最大回撤</span><strong>{usBacktest ? `${(usBacktest.summary.max_drawdown_pct ?? 0).toFixed(2)}%` : '-'}</strong></div>
        </div>
      </section>

      {/* Unified backtest with charts */}
      {usUnifiedBacktest ? (
        <section className="panel us-unified-section">
          <div className="panel-header">
            <h3>统一回测结果</h3>
            <StatusBadge status={usUnifiedBacktest.equity_consistent ? '权益验证 PASS' : '权益验证 FAIL'} label="验证" tone={usUnifiedBacktest.equity_consistent ? 'good' : 'bad'} />
          </div>
          <div className="us-mini-metrics">
            <div><span>总收益</span><strong className={(usUnifiedBacktest.summary.total_return_pct ?? 0) >= 0 ? 'metric-good' : 'metric-bad'}>{(usUnifiedBacktest.summary.total_return_pct ?? 0).toFixed(2)}%</strong></div>
            <div><span>Sharpe</span><strong>{(usUnifiedBacktest.summary.sharpe_ratio ?? 0).toFixed(2)}</strong></div>
            <div><span>回撤</span><strong>{(usUnifiedBacktest.summary.max_drawdown_pct ?? 0).toFixed(2)}%</strong></div>
            <div><span>账本权益</span><strong>{formatPrice(usUnifiedBacktest.ledger_final_equity)}</strong></div>
          </div>
          <div className="us-stage-grid">
            <div><span>订单/成交</span><strong>{usUnifiedBacktest.order_count}/{usUnifiedBacktest.fill_count}</strong></div>
            <div><span>快照/事件</span><strong>{usUnifiedBacktest.snapshot_count}/{usUnifiedBacktest.event_count}</strong></div>
            <div><span>总费用</span><strong>{formatPrice(usUnifiedBacktest.ledger_total_fees)}</strong></div>
            <div><span>验证</span><strong style={{color: usUnifiedBacktest.equity_consistent ? 'var(--good)' : 'var(--bad)'}}>{usUnifiedBacktest.equity_consistent ? '一致' : '不一致'}</strong></div>
          </div>
          <p className="data-message">{usUnifiedBacktest.equity_consistency_msg}</p>
          {usUnifiedBacktest.equity_curve.length > 1 ? (
            <div className="charts-grid" style={{marginTop: 14}}>
              <LineChart title="美股权益曲线" points={usUnifiedBacktest.equity_curve} accentClass="line-accent" />
              <LineChart title="美股回撤曲线" points={usUnifiedBacktest.drawdown_curve} accentClass="line-accent-secondary" />
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Paper status */}
      {usPaperStatus ? (
        <section className="us-paper-section panel">
          <div className="panel-header"><h3>纸交易状态</h3><StatusBadge status={usPaperStatus.healthy ? '健康' : '异常'} label="健康" tone={usPaperStatus.healthy ? 'good' : 'bad'} /></div>
          <div className="us-mini-metrics">
            <div><span>权益</span><strong>{formatPrice(usPaperStatus.equity)}</strong></div>
            <div><span>现金</span><strong>{formatPrice(usPaperStatus.cash)}</strong></div>
            <div><span>购买力</span><strong>{formatPrice(usPaperStatus.buying_power)}</strong></div>
            <div><span>持仓数</span><strong>{usPaperStatus.positions}</strong></div>
          </div>
          <div className="us-stage-grid">
            <div><span>交易日数</span><strong>{usPaperStatus.days_traded}</strong></div>
            <div><span>风控</span><strong style={{color: usPaperStatus.kill_switch_triggered ? 'var(--bad)' : 'var(--good)'}}>{usPaperStatus.kill_switch_triggered ? '已触发' : '正常'}</strong></div>
            <div><span>上次对账</span><strong>{usPaperStatus.last_reconciliation_passed === null ? '-' : usPaperStatus.last_reconciliation_passed ? '通过' : '失败'}</strong></div>
          </div>
          {usPaperStatus.kill_switch_reason ? <p className="data-message">风控原因：{usPaperStatus.kill_switch_reason}</p> : null}
        </section>
      ) : null}

      {/* Paper daily results */}
      {usPaperDailyResults.length > 0 ? (
        <div className="us-paper-results-section panel">
          <div className="panel-header"><h3>纸交易每日结果</h3><span>最近 {Math.min(usPaperDailyResults.length, 10)} 天</span></div>
          <div className="paper-results-table">
            {usPaperDailyResults.slice(-10).reverse().map(day => (
              <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                <span>{day.date}</span>
                <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>${day.daily_pnl.toFixed(2)}</span>
                <span className={`status-tag ${day.reconciliation_passed ? 'good' : 'bad'}`}>{day.reconciliation_passed ? '对账通过' : '对账失败'}</span>
                <span>{day.orders_filled}/{day.orders_submitted} 成交</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Paper backtest summary */}
      {paperBacktest ? (
        <section className="us-unified-section panel">
          <div className="panel-header"><h3>纸交易回测汇总</h3><StatusBadge status={paperBacktest.healthy ? '健康' : '异常'} label="" tone={paperBacktest.healthy ? 'good' : 'bad'} /></div>
          <div className="us-mini-metrics">
            <div><span>总 PnL</span><strong className={paperBacktest.total_pnl >= 0 ? 'metric-good' : 'metric-bad'}>${paperBacktest.total_pnl.toFixed(2)}</strong></div>
            <div><span>最终权益</span><strong>{formatPrice(paperBacktest.final_equity)}</strong></div>
            <div><span>处理天数</span><strong>{paperBacktest.days_processed}</strong></div>
          </div>
        </section>
      ) : null}

      {/* Cost stress */}
      {edCostStress ? (
        <section className="us-unified-section panel">
          <div className="panel-header"><h3>成本压力测试</h3><StatusBadge status={`${edCostStress.survival_rate_pct.toFixed(0)}% 生存`} label="" tone={edCostStress.survival_rate_pct >= 50 ? 'good' : 'bad'} /></div>
          <div className="us-stage-grid">
            <div><span>引擎</span><strong>{edCostStress.engine}</strong></div>
            <div><span>基准成交</span><strong>{edCostStress.baseline_fill_count}</strong></div>
            <div><span>策略</span><strong>{edCostStress.strategy_id}</strong></div>
          </div>
          <div className="paper-results-table">
            {edCostStress.scenarios.map(s => (
              <div key={s.name} className={`paper-result-row ${s.survives ? '' : 'paper-fail'}`}>
                <span>{s.name}</span>
                <span className={s.total_return_pct >= 0 ? 'metric-good' : 'metric-bad'}>{s.total_return_pct?.toFixed(2) ?? '-'}%</span>
                <span>Sharpe: {s.sharpe_ratio?.toFixed(2) ?? '-'}</span>
                <span>成交: {s.fill_count ?? '-'}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {/* Quality report */}
      {usQualityReport ? (
        <section className="panel quality-panel">
          <div className="panel-header"><h3>数据质量 — {usQualityReport.symbol}</h3><span className={usQualityReport.has_issues ? 'status-warn' : 'status-ok'}>{usQualityReport.has_issues ? `${usQualityReport.total_issues} 问题` : '通过'}</span></div>
          <table className="quality-table"><thead><tr><th>检查项</th><th>问题数</th><th>详情</th></tr></thead>
            <tbody>{usQualityReport.reports.map(r => <tr key={r.report_type}><td>{r.report_type}</td><td className={r.issues_found > 0 ? 'text-warn' : 'text-ok'}>{r.issues_found}</td><td className="text-muted">{r.details.slice(0, 3).map(d => JSON.stringify(d)).join(', ') || '-'}</td></tr>)}</tbody>
          </table>
        </section>
      ) : null}

      {/* Reconciliation */}
      {usReconcile ? (
        <section className="panel recon-panel">
          <div className="panel-header"><h3>持仓核对</h3><span className={usReconcile.status === 'clean' ? 'status-ok' : 'status-err'}>{usReconcile.status === 'clean' ? '一致' : '差异'}{usReconcile.halt_new_orders ? ' — 已暂停' : ''}</span></div>
          {usReconcile.status !== 'clean' ? (
            <div className="recon-details">
              {usReconcile.cash_diff !== undefined && usReconcile.cash_diff !== 0 ? <p>现金差异: ${usReconcile.cash_diff.toFixed(2)}</p> : null}
              {usReconcile.position_diffs && Object.keys(usReconcile.position_diffs).length > 0 ? <p>持仓差异: {Object.keys(usReconcile.position_diffs).join(', ')}</p> : null}
              {usReconcile.report_path ? <p className="text-muted">报告: {usReconcile.report_path}</p> : null}
              {usReconcile.alert_sent ? <p className="text-warn">已发送告警</p> : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* Promotion gate */}
      {promotionGateResult ? (
        <section className="panel">
          <div className="panel-header"><h3>晋升门</h3><span>{promotionGateResult.decision as string} → {promotionGateResult.next_stage as string}</span></div>
          <div className="promotion-gate-list">
            {(promotionGateResult.gates as Array<{name: string; status: string; message: string}>).map(g => (
              <div key={g.name} className={`promotion-gate-row promotion-${g.status}`}><span>{g.status.toUpperCase()}</span><strong>{g.name}</strong><p>{g.message}</p></div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
