import {useEffect, useState} from 'react';

import {apiGet, ApiError} from '../lib/api';
import {LoadingSpinner} from '../components/LoadingSpinner';

type Experiment = {
  experiment_id: string;
  experiment_name: string;
  strategy_id: string;
  status: string;
  created_at: string;
  updated_at?: string;
  stage?: string;
};

type Candidate = {
  candidate_id: string;
  strategy_id: string;
  score: number;
  stage: string;
  status: string;
  created_at: string;
};

type ResearchState = {
  experiments: Experiment[];
  candidates: Candidate[];
};

export default function ResearchDashboard() {
  const [data, setData] = useState<ResearchState | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const [experiments, candidates] = await Promise.all([
          apiGet<Experiment[]>('/api/research/experiments').catch(() => [] as Experiment[]),
          apiGet<Candidate[]>('/api/research/candidates').catch(() => [] as Candidate[]),
        ]);
        if (!cancelled) setData({experiments, candidates});
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : 'Failed to load research data');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void fetchData();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <LoadingSpinner text="加载研究数据..." />;
  if (error) return (
    <main className="live-dashboard">
      <h2>研究台</h2>
      <div className="panel error-panel">
        <div className="panel-header"><h3>连接错误</h3></div>
        <p>{error}</p>
      </div>
    </main>
  );
  if (!data || (data.experiments.length === 0 && data.candidates.length === 0)) return (
    <main className="live-dashboard">
      <h2>研究台</h2>
      <div className="panel">
        <div className="panel-header"><h3>暂无数据</h3></div>
        <p style={{padding: '12px 0', color: 'var(--muted)'}}>尚未找到实验记录或候选策略。运行研究管道以生成数据。</p>
      </div>
    </main>
  );

  return (
    <main className="live-dashboard">
      <h2>研究台</h2>
      <p style={{color: 'var(--muted)', margin: '0 0 16px'}}>实验管理 · 候选策略 · 晋升门控</p>

      {/* Experiments */}
      {data.experiments.length > 0 && (
        <section className="panel" style={{marginBottom: 16}}>
          <div className="panel-header">
            <h3>实验记录</h3>
            <span>{data.experiments.length} 项</span>
          </div>
          <div className="paper-results-table">
            {data.experiments.map(exp => (
              <div key={exp.experiment_id} className="paper-result-row">
                <span>{exp.experiment_name || exp.experiment_id}</span>
                <span className="status-tag neutral">{exp.status}</span>
                <span>{exp.strategy_id}</span>
                <span>{exp.stage || '—'}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Candidates */}
      {data.candidates.length > 0 && (
        <section className="panel">
          <div className="panel-header">
            <h3>晋升候选</h3>
            <span>{data.candidates.length} 项</span>
          </div>
          <div className="strategy-grid">
            {data.candidates.map(c => (
              <div key={c.candidate_id} className="strategy-card">
                <div className="strategy-card-header">
                  <strong>{c.strategy_id}</strong>
                  <span className={`status-tag ${c.status === 'pass' ? 'good' : c.status === 'fail' ? 'bad' : 'neutral'}`}>
                    {c.stage}
                  </span>
                </div>
                <p>分数: {c.score.toFixed(3)}</p>
                <p style={{fontSize: '0.75rem', color: 'var(--muted)'}}>
                  创建: {new Date(c.created_at).toLocaleDateString('zh-CN')}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
