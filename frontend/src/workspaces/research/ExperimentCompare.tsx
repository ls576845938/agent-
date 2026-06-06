import {useEffect, useMemo, useState} from 'react';

import {LoadingSpinner} from '../../components/LoadingSpinner';
import {DataTable, type Column} from '../../components/DataTable';
import {researchApi} from '../../lib/research-api';

interface Candidate {
  candidate_id: string;
  experiment_id: string;
  strategy_id: string;
  score?: number;
  sharpe?: number;
  rank?: number;
  created_at: string;
}

interface CompareRow {
  rank: number;
  candidate_id: string;
  strategy_id: string;
  score: number;
  sharpe: number;
  expLabel: string;
  experiment_id: string;
}

export default function ExperimentCompare() {
  const [experiments, setExperiments] = useState<Array<{experiment_id: string}>>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [compareData, setCompareData] = useState<Record<string, any[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const exps = await researchApi.listExperiments();
        if (!cancelled) setExperiments(exps || []);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载实验失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleToggle = (id: string) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const handleCompare = async () => {
    if (selected.length < 2) return;
    setComparing(true);
    setError('');
    try {
      const result = await researchApi.compareExperiments(selected);
      setCompareData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '对比失败');
    } finally {
      setComparing(false);
    }
  };

  const expandedData = useMemo<CompareRow[]>(() => {
    if (!compareData) return [];
    const rows: CompareRow[] = [];
    Object.entries(compareData).forEach(([expId, candidates]) => {
      const cands = (candidates as any[]) || [];
      cands.forEach((c: any, idx: number) => {
        rows.push({
          rank: c.rank ?? idx + 1,
          candidate_id: c.candidate_id,
          strategy_id: c.strategy_id,
          score: c.score ?? 0,
          sharpe: c.sharpe ?? 0,
          expLabel: expId.slice(0, 12),
          experiment_id: expId,
        });
      });
    });
    return rows;
  }, [compareData]);

  const fromApi = useMemo<CompareRow[]>(() => {
    if (compareData) return expandedData;
    return [];
  }, [compareData, expandedData]);

  const columns: Column[] = [
    {key: 'expLabel', label: '实验', sortable: true},
    {key: 'rank', label: '排名', sortable: true, width: '60px'},
    {key: 'candidate_id', label: '候选ID', sortable: true, width: '160px'},
    {key: 'strategy_id', label: '策略', sortable: true},
    {key: 'score', label: '评分', sortable: true, render: (v) => v != null ? (v as number).toFixed(3) : '-'},
    {key: 'sharpe', label: 'Sharpe', sortable: true, render: (v) => v != null ? (v as number).toFixed(2) : '-'},
  ];

  if (loading) return <LoadingSpinner text="加载实验列表..." />;

  return (
    <div>
      <h3 style={{margin: '0 0 16px'}}>实验对比</h3>

      {/* Selection */}
      <div style={{marginBottom: 16}}>
        <div style={{fontSize: '0.85rem', color: '#94a3b8', marginBottom: 8}}>
          选择 2 个以上实验进行对比
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
          {experiments.map((exp) => {
            const active = selected.includes(exp.experiment_id);
            return (
              <button
                key={exp.experiment_id}
                onClick={() => handleToggle(exp.experiment_id)}
                style={{
                  padding: '4px 12px',
                  fontSize: '0.8rem',
                  borderRadius: 16,
                  border: active
                    ? '1px solid #6366f1'
                    : '1px solid rgba(255,255,255,0.15)',
                  background: active
                    ? 'rgba(99,102,241,0.2)'
                    : 'rgba(255,255,255,0.06)',
                  color: active ? '#a5b4fc' : '#e2e8f0',
                  cursor: 'pointer',
                }}
              >
                {exp.experiment_id}
              </button>
            );
          })}
        </div>
      </div>

      <button
        disabled={selected.length < 2 || comparing}
        onClick={handleCompare}
        style={{
          padding: '8px 20px',
          fontSize: '0.85rem',
          borderRadius: 4,
          border: '1px solid rgba(99,102,241,0.4)',
          background: selected.length < 2
            ? 'rgba(255,255,255,0.06)'
            : 'rgba(99,102,241,0.15)',
          color: selected.length < 2 ? '#64748b' : '#a5b4fc',
          cursor: selected.length < 2 ? 'not-allowed' : 'pointer',
          marginBottom: 20,
        }}
      >
        {comparing ? '对比中...' : `对比所选 (${selected.length})`}
      </button>

      {error && (
        <div style={{
          padding: '8px 12px', fontSize: '0.85rem', color: '#ef4444',
          background: 'rgba(239,68,68,0.1)', borderRadius: 4, marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      {/* Results table */}
      {fromApi.length > 0 && (
        <div>
          <div style={{marginBottom: 12, fontSize: '0.85rem', color: '#94a3b8'}}>
            共 {fromApi.length} 条候选记录
          </div>
          <DataTable
            columns={columns}
            data={fromApi as unknown as Record<string, unknown>[]}
            emptyText="无对比数据"
          />
        </div>
      )}

      {!compareData && !comparing && selected.length >= 2 && (
        <p style={{fontSize: '0.8rem', color: '#64748b'}}>点击"对比所选"查看结果</p>
      )}
    </div>
  );
}
