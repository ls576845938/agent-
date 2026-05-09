import type {Candidate} from './CandidateTable';

function decisionColor(status: string): string {
  const s = status?.toUpperCase();
  if (s === 'PROMOTE_TO_REVIEW') return '#22c55e';
  if (s === 'REJECT') return '#ef4444';
  if (s === 'KEEP_WATCHING') return '#eab308';
  return '#94a3b8';
}

const overlayStyle = {
  position: 'fixed' as const,
  inset: 0,
  background: 'rgba(0,0,0,0.5)',
  zIndex: 100,
  display: 'flex',
  justifyContent: 'flex-end',
};

const panelStyle = {
  width: 480,
  maxWidth: '90vw',
  background: '#1e293b',
  borderLeft: '1px solid rgba(255,255,255,0.1)',
  padding: 24,
  overflowY: 'auto' as const,
  color: '#e2e8f0',
};

const sectionTitleStyle = {
  fontSize: '0.85rem',
  fontWeight: 600,
  color: '#94a3b8',
  marginBottom: 8,
};

const metricGridStyle = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 8,
};

const metricBoxStyle = {
  padding: '8px 10px',
  background: 'rgba(255,255,255,0.04)',
  borderRadius: 4,
};

const paramTdStyle = {
  padding: '4px 8px',
  borderBottom: '1px solid rgba(255,255,255,0.05)',
};

export default function CandidateDetail({candidate, onClose}: {
  candidate: Candidate;
  onClose: () => void;
}) {
  const scoreComponents = [
    {label: 'Alpha', value: candidate.alpha_score ?? 0, color: '#6366f1'},
    {label: '稳健', value: candidate.robustness_score ?? 0, color: '#22c55e'},
    {label: '过拟合', value: candidate.overfit_score ?? 0, color: '#f59e0b'},
    {label: '风险', value: candidate.risk_score ?? 0, color: '#ef4444'},
    {label: '换手', value: candidate.turnover_score ?? 0, color: '#8b5cf6'},
  ];
  const totalScore = scoreComponents.reduce((a, c) => a + c.value, 0) || 1;

  const metrics = [
    {label: 'CAGR', value: candidate.cagr, isPct: false},
    {label: 'Sharpe', value: candidate.sharpe, isPct: false},
    {label: 'Sortino', value: candidate.sortino, isPct: false},
    {label: 'Calmar', value: candidate.calmar, isPct: false},
    {label: '最大回撤', value: candidate.max_drawdown, isPct: true},
    {label: '胜率', value: candidate.win_rate, isPct: true},
    {label: '盈亏比', value: candidate.profit_factor, isPct: false},
  ];

  const paramsEntries = candidate.parameters ? Object.entries(candidate.parameters) : [];
  const warnings = candidate.warnings || [];

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={panelStyle} onClick={(e: any) => e.stopPropagation()}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
          <div>
            <h3 style={{margin: '0 0 4px'}}>{candidate.strategy_id}</h3>
            <p style={{margin: 0, fontSize: '0.8rem', color: '#94a3b8'}}>
              {candidate.candidate_id}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: '#94a3b8',
              fontSize: '1.2rem', cursor: 'pointer', padding: 0,
            }}
          >
            &times;
          </button>
        </div>

        <div style={{marginTop: 4, marginBottom: 16}}>
          <span style={{color: decisionColor(candidate.promotion_status), fontSize: '0.9rem', fontWeight: 600}}>
            {candidate.promotion_status}
          </span>
        </div>

        {/* Score breakdown bar */}
        <div style={{marginTop: 20}}>
          <div style={sectionTitleStyle}>评分构成</div>
          <div style={{display: 'flex', gap: 2, height: 24, borderRadius: 4, overflow: 'hidden'}}>
            {scoreComponents.map(c => (
              <div
                key={c.label}
                style={{
                  flex: c.value / totalScore,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.65rem',
                  color: '#fff',
                  background: c.color,
                }}
                title={`${c.label}: ${c.value.toFixed(3)}`}
              >
                {c.value / totalScore > 0.1 ? c.label : ''}
              </div>
            ))}
          </div>
        </div>

        {/* Key metrics */}
        <div style={{marginTop: 20}}>
          <div style={sectionTitleStyle}>关键指标</div>
          <div style={metricGridStyle}>
            {metrics.map(m => (
              <div key={m.label} style={metricBoxStyle}>
                <div style={{fontSize: '0.75rem', color: '#64748b'}}>{m.label}</div>
                <div style={{fontSize: '0.95rem', fontWeight: 600}}>
                  {m.value != null
                    ? (m.isPct ? (m.value * 100).toFixed(1) + '%' : m.value.toFixed(3))
                    : '-'}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Parameters */}
        {paramsEntries.length > 0 && (
          <div style={{marginTop: 20}}>
            <div style={sectionTitleStyle}>参数</div>
            <table style={{width: '100%', fontSize: '0.8rem', borderCollapse: 'collapse'}}>
              <tbody>
                {paramsEntries.map(([key, value]) => (
                  <tr key={key}>
                    <td style={paramTdStyle}>{key}</td>
                    <td style={paramTdStyle}>{String(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Warnings */}
        {warnings.length > 0 && (
          <div style={{marginTop: 20}}>
            <div style={sectionTitleStyle}>警告</div>
            {warnings.map((w, i) => (
              <div key={i} style={{
                padding: '6px 10px', fontSize: '0.8rem', color: '#eab308',
                background: 'rgba(234,179,8,0.1)', borderRadius: 4, marginBottom: 4,
              }}>
                {w}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
