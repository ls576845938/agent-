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

const tabs: Array<{path: string; label: string; short: string; description: string}> = [
  {path: '/', label: '美股量化', short: 'US', description: '数据、回测、纸交易门禁'},
  {path: '/research', label: '研究台', short: 'RQ', description: '证据、候选、组合复核'},
  {path: '/portfolio', label: '投资组合', short: 'PF', description: '权重、配置、风险'},
  {path: '/crypto', label: '加密策略', short: 'BTC', description: '事件回测与闭环验证'},
  {path: '/live', label: '实盘监控', short: 'LIVE', description: '冻结、对账、安全状态'},
  {path: '/strategies', label: '策略浏览', short: 'ST', description: '策略目录与默认参数'},
];

function AppShell() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void (async () => {
      setError('');
      const [healthResult, strategyResult] = await Promise.all([
        apiGet<HealthState>('/api/health').catch((e) => {
          setError(humanizeError(e));
          return null;
        }),
        apiGet<StrategyInfo[]>('/api/strategies').catch(() => []),
      ]);
      if (healthResult) setHealth(healthResult);
      setStrategies(strategyResult);
    })();
  }, []);

  const activePath = location.pathname;
  const activeTab = tabs.find(tab => tab.path === activePath) ?? tabs[0];

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-block">
          <div className="brand-mark">QS</div>
          <div>
            <p className="eyebrow">QuantStation vNext</p>
            <h1>量化研究台</h1>
          </div>
        </div>
        <nav className="app-nav" aria-label="主导航">
          {tabs.map(tab => (
            <Link
              key={tab.path}
              to={tab.path}
              className={activePath === tab.path ? 'active' : ''}
            >
              <span className="nav-code">{tab.short}</span>
              <span>
                <strong>{tab.label}</strong>
                <small>{tab.description}</small>
              </span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-status">
          <span>后端</span>
          <strong>{health?.service ?? '等待连接'}</strong>
          <span>数据源</span>
          <strong>{health?.data_source_default ?? '未知'}</strong>
        </div>
      </aside>

      <section className="workspace-shell">
        <header className="workspace-topbar">
          <div>
            <p className="eyebrow">当前页面</p>
            <h2>{activeTab.label}</h2>
            <p>{activeTab.description}</p>
          </div>
          <div className="topbar-status">
            <span className="status-chip">{health?.status ?? '待检查'}</span>
            <span className="status-chip muted">实盘冻结</span>
          </div>
        </header>

        {error ? (
          <div className="panel error-panel app-error-panel">
            <div className="panel-header"><h2>连接错误</h2></div>
            <p>{error}</p>
          </div>
        ) : null}

        <div className="workspace-content">
          <Routes>
            <Route path="/" element={<ErrorBoundary><USEquityWorkspace strategies={strategies} health={health} /></ErrorBoundary>} />
            <Route path="/crypto" element={<ErrorBoundary><CryptoWorkspace health={health} strategies={strategies} /></ErrorBoundary>} />
            <Route path="/live" element={<ErrorBoundary><LiveTradingDashboard /></ErrorBoundary>} />
            <Route path="/strategies" element={<ErrorBoundary><StrategyExplorer strategies={strategies} /></ErrorBoundary>} />
            <Route path="/research" element={<ErrorBoundary><ResearchDashboard /></ErrorBoundary>} />
            <Route path="/portfolio" element={<ErrorBoundary><PortfolioMonitor /></ErrorBoundary>} />
          </Routes>
        </div>
      </section>
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
