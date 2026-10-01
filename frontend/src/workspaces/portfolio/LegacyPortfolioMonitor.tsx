import {useEffect, useState} from 'react';

import {apiGet} from '../../lib/api';
import {LoadingSpinner} from '../../components/LoadingSpinner';
import {
  WorkbenchEmptyState,
  WorkbenchFrame,
  WorkbenchHeader,
  WorkbenchPanel,
  WorkbenchTabs,
} from '../../components/workbench/Workbench';
import PortfolioOverview from './PortfolioOverview';
import PortfolioAllocation from './PortfolioAllocation';
import PortfolioRisk from './PortfolioRisk';

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
  {key: 'overview', label: '组合总览', status: '权重 / 敞口', detail: 'Forecast → TargetPosition'},
  {key: 'allocation', label: '配置优化', status: '目标权重', detail: '约束 / 再平衡'},
  {key: 'risk', label: '风险预算', status: 'RiskDecision', detail: '波动 / 集中度 / VaR'},
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

export default function LegacyPortfolioMonitor() {
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

  if (loading) {
    return (
      <WorkbenchFrame className="portfolio-monitor portfolio-workbench">
        <WorkbenchHeader
          code="PF"
          eyebrow="Portfolio / Risk"
          title="投资组合监控"
          description="Forecast 转目标仓位，经过组合约束与风险预算后输出可审计的 TargetPosition。"
          status="加载中"
          statusTone="info"
          secondaryStatus="LIVE LOCKED"
        />
        <WorkbenchPanel title="正在读取组合状态" kicker="Portfolio State">
          <LoadingSpinner text="加载投资组合..." />
        </WorkbenchPanel>
      </WorkbenchFrame>
    );
  }

  if (error) {
    return (
      <WorkbenchFrame className="portfolio-monitor portfolio-workbench">
        <WorkbenchHeader
          code="PF"
          eyebrow="Portfolio / Risk"
          title="投资组合监控"
          description="组合数据异常时保持只读并阻止后续执行链。"
          status="BLOCKED"
          statusTone="bad"
          secondaryStatus="LIVE LOCKED"
        />
        <WorkbenchPanel title="连接错误" kicker="Fail Closed">
          <WorkbenchEmptyState title="无法读取组合状态">{error}</WorkbenchEmptyState>
        </WorkbenchPanel>
      </WorkbenchFrame>
    );
  }

  const pf = data?.latest_portfolio ?? null;
  const portfolioStateLoaded = data?.status === 'ok' && Boolean(pf);

  return (
    <WorkbenchFrame className="portfolio-monitor portfolio-workbench">
      <WorkbenchHeader
        code="PF"
        eyebrow="Portfolio / Risk"
        title="投资组合监控"
        description="Forecast → TargetPosition → RiskDecision；组合层不生成订单，也不会绕过执行门禁。"
        status={portfolioStateLoaded ? 'STATE LOADED' : 'BLOCKED / NO DATA'}
        statusTone={portfolioStateLoaded ? 'info' : 'bad'}
        secondaryStatus="LIVE LOCKED"
        meta={[
          {label: '组合 ID', value: pf?.portfolio_id ?? '—', tone: pf ? 'info' : 'neutral'},
          {label: 'AS OF', value: pf?.date?.slice(0, 10) ?? '—'},
          {label: '策略数量', value: pf ? Object.keys(pf.strategy_weights).length : data?.portfolio_count ?? 0},
          {label: '目标资金', value: pf ? `$${pf.total_capital.toLocaleString('en-US')}` : '—'},
          {label: '预期波动', value: pf ? `${(pf.expected_volatility * 100).toFixed(1)}%` : '—', tone: 'warn'},
          {label: '执行权限', value: '未授予', tone: 'good'},
        ]}
      />

      <WorkbenchTabs
        items={tabs}
        activeKey={tab}
        onChange={setTab}
        ariaLabel="投资组合工作流"
      />

      {!pf ? (
        <WorkbenchPanel title="组合状态" kicker="Portfolio State" meta="只读">
          <WorkbenchEmptyState title="暂无投资组合数据">
            等待研究层发布 Forecast 和组合层生成 TargetPosition；页面不会用 fixture 自动解锁后续流程。
          </WorkbenchEmptyState>
        </WorkbenchPanel>
      ) : (
        <WorkbenchPanel
          title={tabs.find(item => item.key === tab)?.label}
          kicker="Portfolio Workbench"
          meta={`${pf.portfolio_id} · ${pf.date?.slice(0, 10)}`}
        >
          {tab === 'overview' && <PortfolioOverview pf={pf} />}
          {tab === 'allocation' && <PortfolioAllocation pf={pf} />}
          {tab === 'risk' && <PortfolioRisk pf={pf} />}
        </WorkbenchPanel>
      )}
    </WorkbenchFrame>
  );
}
