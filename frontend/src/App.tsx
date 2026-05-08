import {useEffect, useState} from 'react';
import {BrowserRouter, Routes, Route, Link, useLocation} from 'react-router-dom';

import type {StrategyInfo} from './lib/view-model';
import {humanizeError} from './lib/view-model';
import {apiGet} from './lib/api';
import {ErrorBoundary} from './components/ErrorBoundary';
import CryptoWorkspace from './workspaces/CryptoWorkspace';
import USEquityWorkspace from './workspaces/USEquityWorkspace';
import LiveTradingDashboard from './workspaces/LiveTradingDashboard';
import StrategyExplorer from './workspaces/StrategyExplorer';
import ResearchDashboard from './workspaces/ResearchDashboard';
import PortfolioMonitor from './workspaces/PortfolioMonitor';

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
};

const tabs: Array<{path: string; label: string}> = [
  {path: '/', label: '美股量化'},
  {path: '/crypto', label: '加密策略'},
  {path: '/live', label: '实盘监控'},
  {path: '/strategies', label: '策略浏览'},
  {path: '/research', label: '研究台'},
  {path: '/portfolio', label: '投资组合'},
];

function AppShell() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        const [healthResult, strategyResult] = await Promise.all([
          apiGet<HealthState>('/api/health'),
          apiGet<StrategyInfo[]>('/api/strategies'),
        ]);
        setHealth(healthResult);
        setStrategies(strategyResult);
      } catch (e) {
        setError(humanizeError(e));
      }
    })();
  }, []);

  const activePath = location.pathname;

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
          <nav className="system-switch">
            {tabs.map(tab => (
              <Link
                key={tab.path}
                to={tab.path}
                className={activePath === tab.path ? 'active' : ''}
              >
                {tab.label}
              </Link>
            ))}
          </nav>
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

      <Routes>
        <Route path="/" element={<ErrorBoundary><USEquityWorkspace strategies={strategies} /></ErrorBoundary>} />
        <Route path="/crypto" element={<ErrorBoundary><CryptoWorkspace health={health} strategies={strategies} /></ErrorBoundary>} />
        <Route path="/live" element={<ErrorBoundary><LiveTradingDashboard /></ErrorBoundary>} />
        <Route path="/strategies" element={<ErrorBoundary><StrategyExplorer strategies={strategies} /></ErrorBoundary>} />
        <Route path="/research" element={<ErrorBoundary><ResearchDashboard /></ErrorBoundary>} />
        <Route path="/portfolio" element={<ErrorBoundary><PortfolioMonitor /></ErrorBoundary>} />
      </Routes>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
