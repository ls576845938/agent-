import {useEffect, useState} from 'react';
import StatusBadge from '../components/StatusBadge';
import {formatPrice} from '../lib/utils';

type PaperStatus = {
  equity: number; cash: number; buying_power: number;
  positions: number; kill_switch_triggered: boolean;
  kill_switch_reason: string | null; days_traded: number;
  healthy: boolean; last_reconciliation_passed: boolean | null;
};

type DailyResult = {
  date: string; starting_equity: number; ending_equity: number;
  daily_pnl: number; daily_return_pct: number;
  orders_submitted: number; orders_filled: number;
  orders_rejected: number; orders_cancelled: number;
  kill_switch_triggered: boolean; reconciliation_passed: boolean;
  reconciliation_diff: Record<string, unknown>; errors: string[];
};

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url, {headers: {'Content-Type': 'application/json'}});
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json() as Promise<T>;
}

export default function LiveTradingDashboard() {
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [dailyResults, setDailyResults] = useState<DailyResult[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [error, setError] = useState('');

  const refresh = async () => {
    try {
      const [s, results] = await Promise.all([
        fetchJson<PaperStatus>('/api/us/paper/status'),
        fetchJson<DailyResult[]>('/api/us/paper/daily-results'),
      ]);
      setStatus(s);
      setDailyResults(results);
      setLastUpdate(new Date().toLocaleTimeString('zh-CN'));
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed');
    }
  };

  useEffect(() => {
    void refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, []);

  const totalPnL = dailyResults.reduce((sum, d) => sum + d.daily_pnl, 0);
  const totalOrders = dailyResults.reduce((sum, d) => sum + d.orders_submitted, 0);
  const totalFilled = dailyResults.reduce((sum, d) => sum + d.orders_filled, 0);
  const reconPassCount = dailyResults.filter(d => d.reconciliation_passed).length;

  return (
    <main className="live-dashboard">
      <div className="dashboard-header">
        <div>
          <h2>实盘交易监控</h2>
          <p className="text-muted">自动刷新 · 15 秒间隔 · 上次更新 {lastUpdate || '—'}</p>
        </div>
        <button type="button" className="secondary-button" onClick={refresh}>手动刷新</button>
      </div>

      {error ? <p className="data-message" style={{color: 'var(--bad)'}}>{error}</p> : null}

      {/* Account overview */}
      <section className="metrics-grid">
        <article className="metric-card"><span>当前权益</span><strong>{status ? formatPrice(status.equity) : '—'}</strong></article>
        <article className="metric-card"><span>可用现金</span><strong>{status ? formatPrice(status.cash) : '—'}</strong></article>
        <article className="metric-card"><span>购买力</span><strong>{status ? formatPrice(status.buying_power) : '—'}</strong></article>
        <article className="metric-card"><span>持仓数</span><strong>{status?.positions ?? '—'}</strong></article>
        <article className="metric-card"><span>累计 PnL</span><strong className={totalPnL >= 0 ? 'metric-good' : 'metric-bad'}>${totalPnL.toFixed(2)}</strong></article>
        <article className="metric-card"><span>交易日</span><strong>{status?.days_traded ?? '—'}</strong></article>
      </section>

      {/* Safety indicators */}
      <section className="panel safety-panel">
        <div className="panel-header"><h3>安全状态</h3></div>
        <div className="safety-grid">
          <div className="safety-card">
            <h4>风控开关</h4>
            <StatusBadge
              status={status?.kill_switch_triggered ? '已触发' : '正常'}
              label="kill-switch"
              tone={status?.kill_switch_triggered ? 'bad' : 'good'}
            />
            {status?.kill_switch_reason ? <p className="text-warn">{status.kill_switch_reason}</p> : <p className="text-muted">无异常</p>}
          </div>
          <div className="safety-card">
            <h4>系统健康</h4>
            <StatusBadge
              status={status?.healthy ? '健康' : '异常'}
              label="health"
              tone={status?.healthy ? 'good' : 'bad'}
            />
            <p className="text-muted">{status?.healthy ? '所有指标正常' : '需要检查'}</p>
          </div>
          <div className="safety-card">
            <h4>最近对账</h4>
            <StatusBadge
              status={status?.last_reconciliation_passed === null ? '无数据' : status?.last_reconciliation_passed ? '通过' : '失败'}
              label="reconciliation"
              tone={status?.last_reconciliation_passed === null ? 'neutral' : status?.last_reconciliation_passed ? 'good' : 'bad'}
            />
            <p className="text-muted">对账历史: {reconPassCount}/{dailyResults.length} 通过</p>
          </div>
          <div className="safety-card">
            <h4>订单成交率</h4>
            <StatusBadge
              status={totalOrders > 0 ? `${(totalFilled / totalOrders * 100).toFixed(0)}%` : '—'}
              label="fill-rate"
              tone={totalOrders > 0 && totalFilled / totalOrders >= 0.8 ? 'good' : 'neutral'}
            />
            <p className="text-muted">{totalFilled}/{totalOrders} 成交</p>
          </div>
        </div>
      </section>

      {/* Daily results table */}
      <section className="panel">
        <div className="panel-header"><h3>每日交易记录</h3><span>最近 {dailyResults.length} 天</span></div>
        {dailyResults.length > 0 ? (
          <div className="paper-results-table">
            {dailyResults.slice(-15).reverse().map(day => (
              <div key={day.date} className={`paper-result-row ${day.reconciliation_passed ? '' : 'paper-fail'}`}>
                <span>{day.date}</span>
                <span className={day.daily_pnl >= 0 ? 'metric-good' : 'metric-bad'}>
                  ${day.daily_pnl.toFixed(2)} ({day.daily_return_pct.toFixed(2)}%)
                </span>
                <span>{day.orders_filled}/{day.orders_submitted} 成交</span>
                <span className={`status-tag ${day.reconciliation_passed ? 'good' : 'bad'}`}>
                  {day.reconciliation_passed ? '对账通过' : '对账失败'}
                </span>
                {day.errors.length > 0 ? <span className="text-warn">{day.errors.join(', ')}</span> : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted" style={{padding: 20}}>暂无交易记录。运行纸交易以生成数据。</p>
        )}
      </section>

      {/* PnL summary */}
      {dailyResults.length > 0 ? (
        <section className="panel">
          <div className="panel-header"><h3>PnL 概览</h3></div>
          <div className="metrics-grid">
            <article className="metric-card">
              <span>日均 PnL</span>
              <strong className={totalPnL / dailyResults.length >= 0 ? 'metric-good' : 'metric-bad'}>
                ${(totalPnL / dailyResults.length).toFixed(2)}
              </strong>
            </article>
            <article className="metric-card">
              <span>盈利天数</span>
              <strong className="metric-good">{dailyResults.filter(d => d.daily_pnl > 0).length}</strong>
            </article>
            <article className="metric-card">
              <span>亏损天数</span>
              <strong className="metric-bad">{dailyResults.filter(d => d.daily_pnl < 0).length}</strong>
            </article>
            <article className="metric-card">
              <span>胜率</span>
              <strong className={dailyResults.filter(d => d.daily_pnl > 0).length / dailyResults.length >= 0.5 ? 'metric-good' : 'metric-bad'}>
                {(dailyResults.filter(d => d.daily_pnl > 0).length / dailyResults.length * 100).toFixed(1)}%
              </strong>
            </article>
          </div>
        </section>
      ) : null}
    </main>
  );
}
