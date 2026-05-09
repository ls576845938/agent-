import {useEffect, useState} from 'react';

import {apiGet} from '../lib/api';
import {LoadingSpinner} from '../components/LoadingSpinner';
import ExperimentList from './research/ExperimentList';
import CandidateTable from './research/CandidateTable';
import ExperimentReport from './research/ExperimentReport';

interface Experiment {
  experiment_id: string;
  strategy_id: string;
  strategy_family: string;
  symbols: string[];
  status: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

interface Candidate {
  candidate_id: string;
  experiment_id: string;
  strategy_id: string;
  strategy_family?: string;
  promotion_status: string;
  robustness_score: number;
  overfit_score: number;
  alpha_score: number;
  risk_score: number;
  turnover_score: number;
  score?: number;
  sharpe?: number;
  max_drawdown?: number;
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

const tabs = [
  {key: 'experiments', label: '实验列表'},
  {key: 'candidates', label: '候选排名'},
  {key: 'report', label: '实验报告'},
];

export default function ResearchDashboard() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('experiments');
  const [selectedExp, setSelectedExp] = useState<Experiment | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [exps, cands] = await Promise.all([
          apiGet<Experiment[]>('/api/research/experiments').catch(() => [] as Experiment[]),
          apiGet<Candidate[]>('/api/research/candidates').catch(() => [] as Candidate[]),
        ]);
        if (!cancelled) {
          setExperiments(exps || []);
          setCandidates(cands || []);
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingSpinner text="加载研究数据..." />;
  if (error) return (
    <div style={{padding: 24}}>
      <h2>研究台</h2>
      <div style={{color: '#ef4444', padding: 16, background: 'rgba(239,68,68,0.1)', borderRadius: 8}}>
        连接错误: {error}
      </div>
    </div>
  );

  const candidatesForExp = selectedExp
    ? candidates.filter(c => c.experiment_id === selectedExp.experiment_id)
    : candidates;

  return (
    <div style={{padding: 24, color: '#e2e8f0'}}>
      <h2 style={{margin: '0 0 4px'}}>研究台</h2>
      <p style={{color: '#94a3b8', margin: '0 0 20px', fontSize: '0.875rem'}}>
        实验管理 · 候选策略 · 晋升门控
      </p>

      {/* Tab navigation */}
      <div style={{display: 'flex', gap: 4, borderBottom: '1px solid rgba(255,255,255,0.1)', marginBottom: 20}}>
        {tabs.map(t => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '8px 16px',
                fontSize: '0.85rem',
                borderRadius: '4px 4px 0 0',
                border: 'none',
                background: active ? 'rgba(99,102,241,0.2)' : 'transparent',
                color: active ? '#a5b4fc' : '#94a3b8',
                cursor: 'pointer',
                borderBottom: active ? '2px solid #6366f1' : '2px solid transparent',
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {tab === 'experiments' && (
        <ExperimentList
          experiments={experiments}
          onSelectExperiment={setSelectedExp}
        />
      )}
      {tab === 'candidates' && (
        <CandidateTable candidates={candidatesForExp} />
      )}
      {tab === 'report' && (
        <ExperimentReport
          experiments={experiments}
          candidates={candidatesForExp}
          selectedExpId={selectedExp?.experiment_id}
        />
      )}
    </div>
  );
}
