interface LatestPortfolio {
  strategy_weights: Record<string, number>;
  expected_volatility: number;
}

const metricBoxStyle = {
  padding: 14,
  background: 'rgba(255,255,255,0.05)',
  borderRadius: 6,
};

const warningBoxStyle = {
  padding: 14,
  background: 'rgba(234,179,8,0.1)',
  borderRadius: 6,
  border: '1px solid rgba(234,179,8,0.2)',
  marginBottom: 12,
};

export default function PortfolioRisk({pf}: {pf: LatestPortfolio}) {
  const pct = (v: number) => (v * 100).toFixed(1) + '%';

  const weights = Object.values(pf.strategy_weights);
  const maxWeight = weights.length > 0 ? Math.max(...weights) : 0;
  const hasConcentrationIssue = maxWeight > 0.3;

  const warnings: {title: string; text: string}[] = [];

  if (hasConcentrationIssue) {
    warnings.push({
      title: '集中度风险',
      text: `单一策略权重 ${pct(maxWeight)} 超过 30% 阈值，建议分散配置`,
    });
  }

  warnings.push({
    title: '相关性风险',
    text: '策略间相关性分析尚未实现。建议手动检查策略重复暴露。',
  });

  return (
    <div>
      <h3 style={{margin: '0 0 16px', fontSize: '0.9rem', fontWeight: 600}}>风险指标</h3>

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: 12, marginBottom: 20,
      }}>
        <div style={metricBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>预期波动率</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#e2e8f0'}}>
            {pct(pf.expected_volatility)}
          </div>
        </div>
        <div style={metricBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>最大回撤 (估算)</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#e2e8f0'}}>
            {pct(pf.expected_volatility * 2.5)}
          </div>
        </div>
        <div style={metricBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>VaR (95%)</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#e2e8f0'}}>
            {pct(pf.expected_volatility * 1.645)}
          </div>
        </div>
      </div>

      {/* Warnings */}
      {warnings.map((w, i) => (
        <div key={i} style={warningBoxStyle}>
          <div style={{fontSize: '0.8rem', fontWeight: 600, color: '#eab308', marginBottom: 4}}>
            {w.title}
          </div>
          <div style={{fontSize: '0.8rem', color: '#94a3b8'}}>{w.text}</div>
        </div>
      ))}
    </div>
  );
}
