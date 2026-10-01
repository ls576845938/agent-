import {useEffect, useState} from 'react';

import {apiGet} from '../../lib/api';

type CanonicalEvidenceSummary = {
  status: string;
  run_id: string;
  strategy_identity: Record<string, unknown>;
  metrics: Record<string, unknown>;
  cost_components: Record<string, unknown>;
  ledger_binding: Record<string, unknown>;
  artifact_freshness: Record<string, unknown>;
  backtest_blockers: string[];
  promotion_readiness_blockers: string[];
  safety: Record<string, boolean>;
};

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供';
  if (typeof value === 'number') return value.toLocaleString(undefined, {maximumFractionDigits: 6});
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

export default function CanonicalEvidencePanel() {
  const [summary, setSummary] = useState<CanonicalEvidenceSummary | null>(null);
  const [message, setMessage] = useState('正在读取 latest canonical evidence pointer...');

  useEffect(() => {
    let active = true;
    void apiGet<CanonicalEvidenceSummary>('/api/research/btc/canonical-backtest/latest', 4000)
      .then((payload) => {
        if (!active) return;
        setSummary(payload);
        setMessage('');
      })
      .catch((error) => {
        if (!active) return;
        setMessage(error instanceof Error ? error.message : String(error));
      });
    return () => { active = false; };
  }, []);

  const identity = summary?.strategy_identity ?? {};
  const metrics = summary?.metrics ?? {};
  const costs = summary?.cost_components ?? {};
  const ledger = summary?.ledger_binding ?? {};
  const freshness = summary?.artifact_freshness ?? {};
  const safetyEnabled = Object.entries(summary?.safety ?? {}).filter(([, value]) => value === true);

  return (
    <section className="panel workbench-evidence-panel" data-testid="canonical-btc-evidence-panel">
      <div className="panel-header">
        <h3>Latest Canonical Backtest Evidence</h3>
        <span className={summary?.status === 'complete_research_only' ? 'status-chip ok' : 'status-chip danger'}>
          {summary?.status ?? '加载中'}
        </span>
      </div>
      {message ? <p className="data-message">{message}</p> : null}
      <p className="data-message">只读研究证据；不触发回测重建，不拥有 paper/live/order/broker 权限。</p>
      <div className="workbench-identity-grid">
        <div><span>Run ID</span><strong>{text(summary?.run_id)}</strong></div>
        <div><span>Candidate</span><strong>{text(identity.candidate_id)}</strong></div>
        <div><span>Strategy Version</span><strong>{text(identity.strategy_version)}</strong></div>
        <div><span>Params Hash</span><strong>{text(identity.params_hash)}</strong></div>
        <div><span>Signal Venue</span><strong>{text(identity.signal_data_venue)}</strong></div>
        <div><span>Theoretical Execution</span><strong>{text(identity.execution_venue)}</strong></div>
        <div><span>Total Return</span><strong>{text(metrics.total_return_pct)}%</strong></div>
        <div><span>Max Drawdown</span><strong>{text(metrics.max_drawdown_pct)}%</strong></div>
        <div><span>Commission</span><strong>{text(costs.commission_cost)}</strong></div>
        <div><span>Slippage</span><strong>{text(costs.fixed_slippage_cost)}</strong></div>
        <div><span>Market Impact</span><strong>{text(costs.market_impact_cost)}</strong></div>
        <div><span>Funding Cashflow</span><strong>{text(costs.funding_cashflow)}</strong></div>
        <div><span>Ledger Source</span><strong>{text(ledger.pnl_source)}</strong></div>
        <div><span>Ledger Consistent</span><strong>{text(ledger.ledger_equity_consistent)}</strong></div>
        <div><span>Freshness</span><strong>{text(freshness.status)}</strong></div>
        <div><span>Safety Flags Enabled</span><strong>{safetyEnabled.length}</strong></div>
      </div>
      <div className="detail-grid">
        <div>
          <h4>Backtest blockers</h4>
          <div className="detail-table">
            {(summary?.backtest_blockers ?? []).map((blocker) => <div className="detail-row" key={blocker}><code>{blocker}</code></div>)}
            {!summary?.backtest_blockers?.length ? <p className="data-message">canonical research checks 已通过。</p> : null}
          </div>
        </div>
        <div>
          <h4>Promotion readiness blockers</h4>
          <div className="detail-table">
            {(summary?.promotion_readiness_blockers ?? []).map((blocker) => <div className="detail-row" key={blocker}><code>{blocker}</code></div>)}
          </div>
        </div>
      </div>
    </section>
  );
}
