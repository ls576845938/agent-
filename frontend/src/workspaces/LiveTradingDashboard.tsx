import {useEffect, useState} from 'react';
import {ModuleStateCard} from '../components/ModuleStateCard';
import StatusBadge from '../components/StatusBadge';
import MetricCard from '../components/MetricCard';
import {apiGet} from '../lib/api';
import {formatPrice} from '../lib/utils';
import type {SystemOverviewResponse} from '../lib/shared-types';

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

export default function LiveTradingDashboard() {
  const [status, setStatus] = useState<PaperStatus | null>(null);
  const [overview, setOverview] = useState<SystemOverviewResponse | null>(null);
  const [dailyResults, setDailyResults] = useState<DailyResult[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [error, setError] = useState('');

  const refresh = async () => {
    try {
      const [s, results, systemOverview] = await Promise.all([
        apiGet<PaperStatus>('/api/us/paper/status'),
        apiGet<DailyResult[]>('/api/us/paper/daily-results'),
        apiGet<SystemOverviewResponse>('/api/system/overview').catch(() => null),
      ]);
      setStatus(s);
      setDailyResults(results);
      setOverview(systemOverview);
      setLastUpdate(new Date().toLocaleTimeString('zh-CN'));
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '连接失败');
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
  const liveFreezeOutcome = overview?.execution.live_state === 'frozen' ? '通过' : '阻塞';
  const liveFreezeReason = overview?.execution.live_block_reason ?? (status?.healthy ? '当前保持冻结，等待人工审批' : '系统健康异常，保持冻结');

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

      <section className="panel" style={{marginBottom: 16}}>
        <div className="panel-header">
          <h3>状态卡</h3>
          <span>实盘冻结</span>
        </div>
        <ModuleStateCard
          id="live-freeze"
          title="实盘冻结"
          status={liveFreezeOutcome}
          tone={liveFreezeOutcome === '通过' ? 'good' : 'bad'}
          reason={liveFreezeReason}
          hint="实盘默认冻结，只有对账与审批完成后才允许进入实盘"
          meta={[
            {label: '健康', value: status?.healthy ? '通过' : '阻塞'},
            {label: '对账', value: status?.last_reconciliation_passed === null ? '未知' : status?.last_reconciliation_passed ? '通过' : '阻塞'},
            {label: '实盘状态', value: overview?.execution.live_state ?? '未知'},
            {label: '交易日', value: String(status?.days_traded ?? '—')},
          ]}
          actions={[{
            label: '手动刷新',
            onClick: () => { void refresh(); },
            variant: 'primary',
          }]}
        />
      </section>

      {/* 账户概览 */}
      <section className="metrics-grid">
        <MetricCard label="当前权益" value={status ? formatPrice(status.equity) : '—'} />
        <MetricCard label="可用现金" value={status ? formatPrice(status.cash) : '—'} />
        <MetricCard label="购买力" value={status ? formatPrice(status.buying_power) : '—'} />
        <MetricCard label="持仓数" value={String(status?.positions ?? '—')} />
        <MetricCard label="累计 PnL" value={`$${totalPnL.toFixed(2)}`} tone={totalPnL >= 0 ? 'good' : 'bad'} />
        <MetricCard label="交易日" value={String(status?.days_traded ?? '—')} />
      </section>

      {/* 安全指标 */}
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

      {/* 每日结果表 */}
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

      {/* 盈亏摘要 */}
      {dailyResults.length > 0 ? (
        <section className="panel">
          <div className="panel-header"><h3>盈亏概览</h3></div>
          <div className="metrics-grid">
            <MetricCard label="日均盈亏" value={`$${(totalPnL / dailyResults.length).toFixed(2)}`} tone={totalPnL / dailyResults.length >= 0 ? 'good' : 'bad'} />
            <MetricCard label="盈利天数" value={String(dailyResults.filter(d => d.daily_pnl > 0).length)} tone="good" />
            <MetricCard label="亏损天数" value={String(dailyResults.filter(d => d.daily_pnl < 0).length)} tone="bad" />
            <MetricCard label="胜率" value={`${(dailyResults.filter(d => d.daily_pnl > 0).length / dailyResults.length * 100).toFixed(1)}%`} tone={dailyResults.filter(d => d.daily_pnl > 0).length / dailyResults.length >= 0.5 ? 'good' : 'bad'} />
          </div>
        </section>
      ) : null}
    </main>
  );
}
