import {useEffect, useState} from 'react';

import {apiGet} from '../lib/api';
import {LoadingSpinner} from '../components/LoadingSpinner';
import PortfolioOverview from './portfolio/PortfolioOverview';
import PortfolioAllocation from './portfolio/PortfolioAllocation';
import PortfolioRisk from './portfolio/PortfolioRisk';

interface PortfolioData {
  status: string;
  portfolio_count: number;
  latest_portfolio: {
    portfolio_id: string;
    date: string;
    strategy_weights: Record<string, number>;
    total_capital: number;
    expected_return: number;
    expected_volatility: number;
    symbol_exposures: Record<string, number>;
  } | null;
}

const tabs = [
  {key: 'overview', label: '总览'},
  {key: 'allocation', label: '配置'},
  {key: 'risk', label: '风险'},
];

function withTimeout<T>(promise: Promise<T>, fallback: T, ms = 3500): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<T>((resolve) => {
    timer = setTimeout(() => resolve(fallback), ms);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

export default function PortfolioMonitor() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await withTimeout(
          apiGet<PortfolioData>('/api/portfolio/status'),
          {status: 'timeout', portfolio_count: 0, latest_portfolio: null},
        );
        if (!cancelled) setData(result);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingSpinner text="加载投资组合..." />;
  if (error) return (
    <div className="portfolio-monitor">
      <h2>投资组合</h2>
      <div style={{color: '#ef4444', padding: 16, background: 'rgba(239,68,68,0.1)', borderRadius: 8}}>
        连接错误：{error}
      </div>
    </div>
  );

  const pf = data?.latest_portfolio ?? null;

  return (
    <div className="portfolio-monitor">
      <h2 style={{margin: '0 0 4px'}}>投资组合监控</h2>
      <p style={{color: '#94a3b8', margin: '0 0 20px', fontSize: '0.875rem'}}>
        {pf ? `${pf.portfolio_id} · ${pf.date?.slice(0, 10)}` : ''}
      </p>

      {/* 页签导航 */}
      <div style={{display: 'flex', gap: 4, borderBottom: '1px solid rgba(255,255,255,0.1)', marginBottom: 20}}>
        {tabs.map(t => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '8px 16px',
                fontSize: '0.85rem',
                borderRadius: '4px 4px 0 0',
                border: 'none',
                background: active ? 'rgba(99,102,241,0.2)' : 'transparent',
                color: active ? '#a5b4fc' : '#94a3b8',
                cursor: 'pointer',
                borderBottom: active ? '2px solid #6366f1' : '2px solid transparent',
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {!pf ? (
        <div style={{padding: 30, textAlign: 'center', color: '#94a3b8', background: 'rgba(255,255,255,0.05)', borderRadius: 8}}>
          暂无投资组合数据
        </div>
      ) : (
        <>
          {tab === 'overview' && <PortfolioOverview pf={pf} />}
          {tab === 'allocation' && <PortfolioAllocation pf={pf} />}
          {tab === 'risk' && <PortfolioRisk pf={pf} />}
        </>
      )}
    </div>
  );
}
