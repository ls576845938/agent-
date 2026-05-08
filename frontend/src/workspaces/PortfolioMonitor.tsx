import {useEffect, useState} from 'react';

import {apiGet, ApiError} from '../lib/api';
import {LoadingSpinner} from '../components/LoadingSpinner';
import {formatPrice} from '../lib/utils';

type PortfolioHolding = {
  symbol: string;
  quantity: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_return_pct: number;
  weight_pct: number;
};

type PortfolioStatus = {
  total_equity: number;
  cash: number;
  market_value: number;
  day_pnl: number;
  day_return_pct: number;
  total_pnl: number;
  total_return_pct: number;
  holdings: PortfolioHolding[];
  updated_at: string;
};

export default function PortfolioMonitor() {
  const [data, setData] = useState<PortfolioStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const result = await apiGet<PortfolioStatus>('/api/portfolio/status');
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed to load portfolio');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchData();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingSpinner text="加载投资组合..." />;
  if (error) return (
    <main className="live-dashboard">
      <h2>投资组合</h2>
      <div className="panel error-panel">
        <div className="panel-header"><h3>连接错误</h3></div>
        <p>{error}</p>
      </div>
    </main>
  );
  if (!data) return (
    <main className="live-dashboard">
      <h2>投资组合</h2>
      <div className="panel">
        <div className="panel-header"><h3>暂无数据</h3></div>
        <p style={{padding: '12px 0', color: 'var(--muted)'}}>等待组合数据...</p>
      </div>
    </main>
  );

  const holdings = data.holdings ?? [];

  return (
    <main className="live-dashboard">
      <h2>投资组合监控</h2>
      <p style={{color: 'var(--muted)', margin: '0 0 16px'}}>
        更新于 {data.updated_at ? new Date(data.updated_at).toLocaleString('zh-CN') : '—'}
      </p>

      {/* Summary metrics */}
      <section className="metrics-grid" style={{marginBottom: 16}}>
        <div className="metric-card">
          <span>总权益</span>
          <strong>{formatPrice(data.total_equity)}</strong>
        </div>
        <div className="metric-card">
          <span>可用现金</span>
          <strong>{formatPrice(data.cash)}</strong>
        </div>
        <div className="metric-card">
          <span>市值</span>
          <strong>{formatPrice(data.market_value)}</strong>
        </div>
        <div className={`metric-card ${data.day_pnl >= 0 ? 'metric-good' : 'metric-bad'}`}>
          <span>当日 PnL</span>
          <strong>{data.day_pnl >= 0 ? '+' : ''}{formatPrice(data.day_pnl)} ({data.day_return_pct.toFixed(2)}%)</strong>
        </div>
        <div className={`metric-card ${data.total_pnl >= 0 ? 'metric-good' : 'metric-bad'}`}>
          <span>累计 PnL</span>
          <strong>{data.total_pnl >= 0 ? '+' : ''}{formatPrice(data.total_pnl)} ({data.total_return_pct.toFixed(2)}%)</strong>
        </div>
      </section>

      {/* Holdings table */}
      {holdings.length > 0 ? (
        <section className="panel">
          <div className="panel-header">
            <h3>持仓明细</h3>
            <span>{holdings.length} 只</span>
          </div>
          <div className="portfolio-table" style={{marginTop: 8}}>
            <div className="portfolio-row" style={{borderTop: 'none', color: 'var(--text)'}}>
              <span>标的</span>
              <span>数量</span>
              <span>市值</span>
              <span>盈亏</span>
            </div>
            {holdings.map(h => (
              <div key={h.symbol} className="portfolio-row">
                <span>{h.symbol}</span>
                <span>{h.quantity}</span>
                <span>{formatPrice(h.market_value)}</span>
                <span style={{color: h.unrealized_pnl >= 0 ? 'var(--good)' : 'var(--bad)'}}>
                  {h.unrealized_pnl >= 0 ? '+' : ''}{formatPrice(h.unrealized_pnl)} ({h.unrealized_return_pct.toFixed(2)}%)
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="panel">
          <div className="panel-header"><h3>持仓明细</h3></div>
          <p style={{padding: '12px 0', color: 'var(--muted)'}}>当前无持仓</p>
        </section>
      )}
    </main>
  );
}
