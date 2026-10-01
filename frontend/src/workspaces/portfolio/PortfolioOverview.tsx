import MetricCard from '../../components/MetricCard';

interface LatestPortfolio {
  portfolio_id: string;
  date: string;
  strategy_weights: Record<string, number>;
  total_capital: number;
  expected_return: number;
  expected_volatility: number;
  symbol_exposures: Record<string, number>;
}

const sectionStyle = {
  padding: 16,
  background: 'rgba(255,255,255,0.05)',
  borderRadius: 8,
  marginBottom: 16,
};

export default function PortfolioOverview({pf}: {pf: LatestPortfolio}) {
  const pct = (v: number) => (v * 100).toFixed(1) + '%';
  const usd = (v: number) => '$' + v.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  return (
    <div>
      {/* Metric cards */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 12, marginBottom: 20,
      }}>
        <MetricCard label="总资金" value={usd(pf.total_capital)} />
        <MetricCard
          label="预期收益"
          value={pct(pf.expected_return)}
          tone={pf.expected_return >= 0 ? 'good' : 'bad'}
        />
        <MetricCard label="预期波动" value={pct(pf.expected_volatility)} />
        <MetricCard label="策略数" value={String(Object.keys(pf.strategy_weights).length)} />
      </div>

      {/* Strategy weights */}
      <div style={sectionStyle}>
        <h3 style={{margin: '0 0 12px', fontSize: '0.9rem', fontWeight: 600}}>策略权重</h3>
        <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
          {Object.entries(pf.strategy_weights).map(([name, weight]) => (
            <div key={name} style={{display: 'flex', alignItems: 'center', gap: 12}}>
              <span style={{width: 120, fontSize: '0.85rem'}}>{name}</span>
              <div style={{flex: 1, height: 8, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden'}}>
                <div style={{height: '100%', width: (weight * 100) + '%', background: '#6366f1', borderRadius: 4, transition: 'width 0.3s'}} />
              </div>
              <span style={{width: 50, textAlign: 'right', fontSize: '0.85rem'}}>{pct(weight)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Symbol exposures */}
      {Object.keys(pf.symbol_exposures).length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{margin: '0 0 12px', fontSize: '0.9rem', fontWeight: 600}}>标的敞口</h3>
          <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
            {Object.entries(pf.symbol_exposures).map(([sym, exp]) => {
              const positive = exp > 0;
              return (
                <span key={sym} style={{
                  padding: '4px 10px', fontSize: '0.8rem', borderRadius: 4,
                  background: positive ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
                  color: positive ? '#22c55e' : '#ef4444',
                }}>
                  {sym}: {pct(exp)}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
