import {useState, useMemo} from 'react';

import {DataTable, type Column} from '../../components/DataTable';
import CandidateDetail from './CandidateDetail';

export interface Candidate {
  candidate_id: string;
  experiment_id: string;
  strategy_id: string;
  strategy_family?: string;
  promotion_status: string;
  score?: number;
  sharpe?: number;
  max_drawdown?: number;
  turnover_score: number;
  robustness_score?: number;
  overfit_score?: number;
  alpha_score?: number;
  risk_score?: number;
  rank?: number;
  parameters?: Record<string, number>;
  warnings?: string[];
  cagr?: number;
  sortino?: number;
  calmar?: number;
  win_rate?: number;
  profit_factor?: number;
  created_at: string;
}

function decisionColor(status: string): string {
  const s = status?.toUpperCase();
  if (s === 'PROMOTE_TO_REVIEW') return '#22c55e';
  if (s === 'REJECT') return '#ef4444';
  if (s === 'KEEP_WATCHING') return '#eab308';
  return '#94a3b8';
}

function decisionLabel(status: string): string {
  const labels: Record<string, string> = {
    PROMOTE_TO_REVIEW: '晋升审查',
    REJECT: '拒绝',
    KEEP_WATCHING: '持续观察',
    READY_FOR_PAPER_REVIEW: '可进入纸交易复核',
    PAPER_ELIGIBLE: '纸交易合格',
    READY_FOR_PORTFOLIO_SIM: '可进入组合模拟',
    PAPER_REVIEW_CANDIDATE: '纸交易复核候选',
  };
  return labels[status?.toUpperCase()] ?? status;
}

const filterInputStyle = {
  padding: '6px 10px',
  fontSize: '0.8rem',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.15)',
  background: 'rgba(255,255,255,0.06)',
  color: '#e2e8f0',
  outline: 'none' as const,
};

export default function CandidateTable({
  candidates,
  onCreatePaperReview,
}: {
  candidates: Candidate[];
  onCreatePaperReview?: (candidateId: string) => void;
}) {
  const [filterFamily, setFilterFamily] = useState('');
  const [filterDecision, setFilterDecision] = useState('');
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);

  const filtered = useMemo(() => {
    let result = candidates;
    if (filterFamily) {
      result = result.filter(c => c.strategy_family?.includes(filterFamily));
    }
    if (filterDecision) {
      result = result.filter(c => c.promotion_status === filterDecision);
    }
    return result;
  }, [candidates, filterFamily, filterDecision]);

  const columns: Column[] = [
    {key: 'rank', label: '排名', sortable: true, width: '60px'},
    {key: 'candidate_id', label: '候选ID', sortable: true, width: '160px'},
    {key: 'strategy_id', label: '策略', sortable: true},
    {key: 'score', label: '评分', sortable: true, render: (v) => v != null ? (v as number).toFixed(3) : '-'},
    {key: 'sharpe', label: 'Sharpe', sortable: true, render: (v) => v != null ? (v as number).toFixed(2) : '-'},
    {key: 'max_drawdown', label: '最大回撤', sortable: true, render: (v) => v != null ? ((v as number) * 100).toFixed(1) + '%' : '-'},
    {key: 'turnover_score', label: '换手率', sortable: true, render: (v) => v != null ? ((v as number) * 100).toFixed(1) + '%' : '-'},
    {key: 'promotion_status', label: '决策', sortable: true, render: (v, row) => {
      const status = (v ?? row.promotion_status) as string;
      return <span style={{color: decisionColor(status), fontWeight: 600}}>{decisionLabel(status) || '-'}</span>;
    }},
  ];

  return (
    <div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12}}>
        <h3 style={{margin: 0}}>候选排名</h3>
        <span style={{fontSize: '0.8rem', color: '#94a3b8'}}>{candidates.length} 项</span>
      </div>

      <div style={{display: 'flex', gap: 12, marginBottom: 12, alignItems: 'center'}}>
        <input
          style={filterInputStyle}
          placeholder="策略家族过滤..."
          value={filterFamily}
          onChange={(e: any) => setFilterFamily(e.target.value)}
        />
        <select
          style={filterInputStyle}
          value={filterDecision}
          onChange={(e: any) => setFilterDecision(e.target.value)}
        >
          <option value="">全部决策</option>
          <option value="PROMOTE_TO_REVIEW">晋升审查</option>
          <option value="REJECT">拒绝</option>
          <option value="KEEP_WATCHING">持续观察</option>
        </select>
      </div>

      <DataTable
        columns={columns}
        data={filtered as unknown as Record<string, unknown>[]}
        onRowClick={row => setSelectedCandidate(row as unknown as Candidate)}
        emptyText="暂无候选策略。运行评分管道以生成候选。"
      />

      {selectedCandidate && (
        <CandidateDetail
          candidate={selectedCandidate}
          onClose={() => setSelectedCandidate(null)}
          onCreatePaperReview={onCreatePaperReview}
        />
      )}
    </div>
  );
}
