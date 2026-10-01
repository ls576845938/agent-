import {DataTable, type Column} from '../../components/DataTable';

interface Experiment {
  experiment_id: string;
  strategy_id?: string;
  status: string;
  created_at: string;
}

interface Candidate {
  candidate_id: string;
  strategy_id: string;
  score?: number;
  rank?: number;
  created_at: string;
}

const summaryBoxStyle = {
  padding: 14,
  background: 'rgba(255,255,255,0.05)',
  borderRadius: 6,
};

export default function ExperimentReport({experiments, candidates, selectedExpId}: {
  experiments: Experiment[];
  candidates: Candidate[];
  selectedExpId?: string;
}) {
  const total = experiments.length;
  const success = experiments.filter(e => e.status === 'completed').length;
  const failed = experiments.filter(e => e.status === 'failed').length;
  const topScore = candidates.length > 0
    ? Math.max(...candidates.map(c => c.score ?? 0))
    : 0;

  const topCandidates = [...candidates]
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    .slice(0, 10);

  const scoreDistribution = candidates.length > 0
    ? {
        '0-0.2': candidates.filter(c => (c.score ?? 0) < 0.2).length,
        '0.2-0.4': candidates.filter(c => {
          const s = c.score ?? 0;
          return s >= 0.2 && s < 0.4;
        }).length,
        '0.4-0.6': candidates.filter(c => {
          const s = c.score ?? 0;
          return s >= 0.4 && s < 0.6;
        }).length,
        '0.6-0.8': candidates.filter(c => {
          const s = c.score ?? 0;
          return s >= 0.6 && s < 0.8;
        }).length,
        '0.8-1.0': candidates.filter(c => (c.score ?? 0) >= 0.8).length,
      }
    : null;

  const topColumns: Column[] = [
    {key: 'rank', label: '排名', width: '60px'},
    {key: 'candidate_id', label: '候选ID', width: '160px'},
    {key: 'strategy_id', label: '策略'},
    {key: 'score', label: '评分', sortable: true, render: (v) => v != null ? (v as number).toFixed(3) : '-'},
  ];

  return (
    <div>
      <h3 style={{margin: '0 0 16px'}}>实验报告</h3>

      <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 20}}>
        <div style={summaryBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>实验总数</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#e2e8f0'}}>{total}</div>
        </div>
        <div style={summaryBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>成功</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#22c55e'}}>{success}</div>
        </div>
        <div style={summaryBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>失败</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#ef4444'}}>{failed}</div>
        </div>
        <div style={summaryBoxStyle}>
          <div style={{fontSize: '0.8rem', color: '#94a3b8', marginBottom: 4}}>最高评分</div>
          <div style={{fontSize: '1.2rem', fontWeight: 700, color: '#a5b4fc'}}>{topScore.toFixed(3)}</div>
        </div>
      </div>

      {/* Score distribution */}
      {scoreDistribution && (
        <div style={{marginBottom: 20, padding: 16, background: 'rgba(255,255,255,0.05)', borderRadius: 8}}>
          <h4 style={{margin: '0 0 12px', fontSize: '0.9rem'}}>评分分布</h4>
          <div style={{display: 'flex', gap: 8, alignItems: 'flex-end', height: 80}}>
            {Object.entries(scoreDistribution).map(([bucket, count]) => {
              const values = Object.values(scoreDistribution);
              const maxCount = Math.max(...values);
              const pctHeight = maxCount > 0 ? (count / maxCount) * 100 : 0;
              return (
                <div key={bucket} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center'}}>
                  <div style={{
                    width: '100%',
                    height: `${Math.max(pctHeight, count > 0 ? 4 : 0)}%`,
                    background: '#6366f1',
                    borderRadius: '4px 4px 0 0',
                    transition: 'height 0.3s',
                  }} />
                  <span style={{fontSize: '0.65rem', color: '#94a3b8', marginTop: 4}}>{bucket}</span>
                  <span style={{fontSize: '0.65rem', color: '#64748b'}}>{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Top 10 */}
      <div style={{marginBottom: 16, padding: 16, background: 'rgba(255,255,255,0.05)', borderRadius: 8}}>
        <h4 style={{margin: '0 0 12px', fontSize: '0.9rem'}}>Top 10 候选</h4>
        <DataTable
          columns={topColumns}
          data={topCandidates as unknown as Record<string, unknown>[]}
          emptyText="暂无候选数据"
        />
      </div>

      {/* Download */}
      {selectedExpId ? (
        <button
          style={{
            padding: '8px 16px', fontSize: '0.85rem', borderRadius: 4,
            border: '1px solid rgba(99,102,241,0.4)',
            background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', cursor: 'pointer',
          }}
          onClick={() => window.open(`/api/research/experiments/${selectedExpId}/report`, '_blank')}
        >
          下载报告
        </button>
      ) : (
        <p style={{fontSize: '0.8rem', color: '#64748b'}}>在实验列表中选择一个实验以启用报告下载</p>
      )}
    </div>
  );
}
