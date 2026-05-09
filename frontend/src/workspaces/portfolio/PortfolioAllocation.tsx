import {DataTable, type Column} from '../../components/DataTable';

interface LatestPortfolio {
  portfolio_id: string;
  strategy_weights: Record<string, number>;
}

const selectStyle = {
  padding: '6px 10px',
  fontSize: '0.85rem',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.15)',
  background: 'rgba(255,255,255,0.06)',
  color: '#e2e8f0',
  outline: 'none' as const,
};

const rebalanceBtnStyle = {
  padding: '8px 16px',
  fontSize: '0.85rem',
  borderRadius: 4,
  border: '1px solid rgba(99,102,241,0.4)',
  background: 'rgba(99,102,241,0.15)',
  color: '#a5b4fc',
  cursor: 'pointer' as const,
  marginLeft: 'auto' as const,
};

const methods = ['equal_weight', 'risk_parity', 'mean_variance', 'min_volatility'];

export default function PortfolioAllocation({pf}: {pf: LatestPortfolio}) {
  const pct = (v: number) => (v * 100).toFixed(1) + '%';

  const weightData = Object.entries(pf.strategy_weights).map(([name, weight], i) => ({
    name,
    weight,
    rank: i + 1,
  }));

  const columns: Column[] = [
    {key: 'rank', label: '排名', width: '60px'},
    {key: 'name', label: '策略', sortable: true},
    {key: 'weight', label: '权重', sortable: true, render: (v) => {
      const w = v as number;
      return (
        <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
          <div style={{flex: 1, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden'}}>
            <div style={{height: '100%', width: (w * 100) + '%', background: '#6366f1', borderRadius: 3, transition: 'width 0.3s'}} />
          </div>
          <span>{pct(w)}</span>
        </div>
      );
    }},
  ];

  return (
    <div>
      <div style={{
        display: 'flex', gap: 12, alignItems: 'center',
        marginBottom: 16, padding: 16, background: 'rgba(255,255,255,0.05)', borderRadius: 8,
      }}>
        <label style={{fontSize: '0.85rem', color: '#94a3b8'}}>配置方法</label>
        <select style={selectStyle} defaultValue={methods[0]}>
          {methods.map(m => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <button
          style={rebalanceBtnStyle}
          onClick={() => {/* rebalance placeholder */}}
        >
          Rebalance
        </button>
      </div>

      <div style={{padding: 16, background: 'rgba(255,255,255,0.05)', borderRadius: 8}}>
        <h3 style={{margin: '0 0 12px', fontSize: '0.9rem', fontWeight: 600}}>策略配置</h3>
        <DataTable
          columns={columns}
          data={weightData as unknown as Record<string, unknown>[]}
          emptyText="暂无策略配置"
        />
      </div>
    </div>
  );
}
