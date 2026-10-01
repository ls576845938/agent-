import {useEffect, useState} from 'react';
import {BrowserRouter, Routes, Route, Link, useLocation} from 'react-router-dom';

import type {StrategyInfo} from './lib/view-model';
import {humanizeError} from './lib/view-model';
import {apiGet} from './lib/api';
import {frontendIdentity, frontendFingerprintShort} from './frontendIdentity';
import {ErrorBoundary} from './components/ErrorBoundary';
import CryptoWorkspace from './workspaces/CryptoWorkspace';
import CNEquityWorkspace from './workspaces/CNEquityWorkspace';
import USEquityWorkspace from './workspaces/USEquityWorkspace';
import ExecutionSafetyRoute from './workspaces/ExecutionSafetyRoute';
import StrategyExplorer from './workspaces/StrategyExplorer';
import StrategyModulesWorkspace from './workspaces/StrategyModulesWorkspace';
import ResearchDashboard from './workspaces/ResearchDashboard';
import PortfolioMonitor from './workspaces/PortfolioMonitor';

function ArchitectureRoute() {
  const [MapPage, setMapPage] = useState<typeof import('./workspaces/ArchitectureMapWorkspace').default | null>(null);
  const [loadError, setLoadError] = useState(false);
  useEffect(() => {
    let active = true;
    void import('./workspaces/ArchitectureMapWorkspace')
      .then(module => {if (active) setMapPage(() => module.default);})
      .catch(() => {if (active) setLoadError(true);});
    return () => {active = false;};
  }, []);
  if (loadError) return <p role="alert">架构地图加载失败，请刷新页面重试。</p>;
  return MapPage ? <MapPage /> : <p role="status">正在加载源码地图…</p>;
}

type HealthState = {
  status: string;
  service: string;
  data_source_default: string;
  fastapi_available: boolean;
  evidence_profile?: string;
  read_only?: boolean;
  controls_disabled?: boolean;
};

const tabs: Array<{path: string; label: string; short: string; description: string}> = [
  {path: '/', label: '美股量化', short: 'US', description: '数据、回测、纸交易门禁'},
  {path: '/cn-equity', label: 'A 股量化', short: 'CN', description: '证据、规则与执行门禁'},
  {path: '/research', label: '研究台', short: 'RQ', description: '实验、候选、研究交接'},
  {path: '/portfolio', label: '投资组合', short: 'PF', description: '权重、配置、风险'},
  {path: '/crypto', label: '加密策略', short: 'BTC', description: '事件回测与闭环验证'},
  {path: '/live', label: '执行安全中心', short: 'SAFE', description: '美股 paper 与 BTC gate 边界'},
  {path: '/strategies', label: '策略浏览', short: 'ST', description: '策略目录与默认参数'},
  {path: '/strategy-modules', label: '策略模块', short: 'SM', description: '策略解构与验证地图'},
  {path: '/architecture', label: '架构地图', short: 'MAP', description: '源码关系、阅读清单与证据边界'},
];

function AppShell() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthState | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [error, setError] = useState('');
  const [cryptoSidebarCollapsed, setCryptoSidebarCollapsed] = useState(false);

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
  const isCryptoWorkspace = activePath === '/crypto';

  return (
    <div className={`app-shell ${isCryptoWorkspace ? 'crypto-app-shell' : 'non-crypto-workbench-shell'} ${isCryptoWorkspace && cryptoSidebarCollapsed ? 'crypto-sidebar-collapsed' : ''}`}>
      <aside className={`app-sidebar ${isCryptoWorkspace ? 'app-sidebar-compact' : ''}`}>
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
              title={`${tab.label} · ${tab.description}`}
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
          <span>前端</span>
          <strong
            data-testid="frontend-version-fingerprint"
            data-canonical={String(frontendIdentity.canonical)}
            title={`${frontendIdentity.release_id} · ${frontendIdentity.source_head} · ${frontendIdentity.fingerprint}`}
          >
            {frontendIdentity.canonical ? 'MAIN' : 'PREVIEW'} · {frontendFingerprintShort}
          </strong>
        </div>
      </aside>

      <section className="workspace-shell">
        {isCryptoWorkspace ? (
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
        ) : null}

        {error ? (
          <div className="panel error-panel app-error-panel">
            <div className="panel-header"><h2>连接错误</h2></div>
            <p>{error}</p>
          </div>
        ) : null}

        <div className="workspace-content">
          <Routes>
            <Route path="/" element={<ErrorBoundary><USEquityWorkspace strategies={strategies} health={health} /></ErrorBoundary>} />
            <Route path="/cn-equity" element={<ErrorBoundary><CNEquityWorkspace /></ErrorBoundary>} />
            <Route path="/crypto" element={<ErrorBoundary><CryptoWorkspace key={`${health?.evidence_profile ?? 'unknown'}:${health?.read_only}:${health?.controls_disabled}`} health={health} strategies={strategies} onToggleSidebar={() => setCryptoSidebarCollapsed((value) => !value)} /></ErrorBoundary>} />
            <Route path="/live" element={<ErrorBoundary><ExecutionSafetyRoute /></ErrorBoundary>} />
            <Route path="/strategies" element={<ErrorBoundary><StrategyExplorer strategies={strategies} /></ErrorBoundary>} />
            <Route path="/strategy-modules" element={<ErrorBoundary><StrategyModulesWorkspace /></ErrorBoundary>} />
            <Route path="/research" element={<ErrorBoundary><ResearchDashboard /></ErrorBoundary>} />
            <Route path="/portfolio" element={<ErrorBoundary><PortfolioMonitor /></ErrorBoundary>} />
            <Route path="/architecture" element={<ErrorBoundary><ArchitectureRoute /></ErrorBoundary>} />
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
