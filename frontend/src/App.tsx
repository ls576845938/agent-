import {FormEvent, useEffect, useState} from 'react';

import type {StrategyInfo} from './lib/view-model';
import {humanizeError} from './lib/view-model';
import CryptoWorkspace from './workspaces/CryptoWorkspace';
import USEquityWorkspace from './workspaces/USEquityWorkspace';
import LiveTradingDashboard from './workspaces/LiveTradingDashboard';
import StrategyExplorer from './workspaces/StrategyExplorer';

type TabId = 'crypto' | 'us_equity' | 'live' | 'strategies';

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
};

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}});
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

const tabs: Array<{id: TabId; label: string}> = [
  {id: 'crypto', label: '加密策略'},
  {id: 'us_equity', label: '美股量化'},
  {id: 'live', label: '实盘监控'},
  {id: 'strategies', label: '策略浏览'},
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('us_equity');
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        const [healthResult, strategyResult] = await Promise.all([
          fetchJson<HealthState>('/api/health'),
          fetchJson<StrategyInfo[]>('/api/strategies'),
        ]);
        setHealth(healthResult);
        setStrategies(strategyResult);
      } catch (e) {
        setError(humanizeError(e));
      }
    })();
  }, []);

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />

      <header className="hero">
        <div>
          <p className="eyebrow">QuantStation vNext</p>
          <h1>量化投研与实盘监控控制台</h1>
          <p className="hero-copy">策略回测 · 数据管道 · 模拟交易 · 实盘监控 · 风险管控 — 一体工作台</p>
        </div>
        <div className="hero-actions">
          <div className="system-switch">
            {tabs.map(tab => (
              <button
                key={tab.id}
                type="button"
                className={activeTab === tab.id ? 'active' : ''}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="hero-status">
            <span className="status-chip">{health?.service ?? '等待后端'}</span>
            <span className="status-chip muted">数据源 {health?.data_source_default ?? 'unknown'}</span>
          </div>
        </div>
      </header>

      {error ? (
        <div className="panel error-panel" style={{margin: '0 16px 16px'}}>
          <div className="panel-header"><h2>连接错误</h2></div>
          <p>{error}</p>
        </div>
      ) : null}

      {activeTab === 'crypto' && <CryptoWorkspace health={health} strategies={strategies} />}
      {activeTab === 'us_equity' && <USEquityWorkspace strategies={strategies} />}
      {activeTab === 'live' && <LiveTradingDashboard />}
      {activeTab === 'strategies' && <StrategyExplorer strategies={strategies} />}
    </div>
  );
}
