import {useState} from 'react';

import {DataTable, type Column} from '../../components/DataTable';
import StatusBadge from '../../components/StatusBadge';
import {apiPost} from '../../lib/api';

interface Experiment {
  experiment_id: string;
  strategy_id: string;
  strategy_family: string;
  symbols: string[];
  status: string;
  strategy_count?: number;
  start_date: string;
  end_date: string;
  created_at: string;
}

const btnStyle = {
  padding: '4px 10px',
  fontSize: '0.8rem',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.15)',
  background: 'rgba(255,255,255,0.06)',
  color: '#e2e8f0',
  cursor: 'pointer' as const,
};

const btnPrimaryStyle = {
  padding: '4px 10px',
  fontSize: '0.8rem',
  borderRadius: 4,
  border: '1px solid rgba(99,102,241,0.4)',
  background: 'rgba(99,102,241,0.15)',
  color: '#a5b4fc',
  cursor: 'pointer' as const,
};

export default function ExperimentList({experiments, onSelectExperiment}: {
  experiments: Experiment[];
  onSelectExperiment?: (exp: Experiment) => void;
}) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const handleAction = async (id: string, action: 'run' | 'score') => {
    setActionLoading(`${id}-${action}`);
    try {
      await apiPost(`/api/research/experiments/${id}/${action}`);
    } catch {
      // action failed silently; user can retry
    } finally {
      setActionLoading(null);
    }
  };

  const columns: Column[] = [
    {key: 'experiment_id', label: '实验ID', sortable: true, width: '200px'},
    {key: 'strategy_id', label: '策略', sortable: true},
    {key: 'status', label: '状态', sortable: true, render: (_v, row) => (
      <StatusBadge status={row.status as string} label={row.status as string} />
    )},
    {key: 'created_at', label: '创建时间', sortable: true, render: (v) => {
      const val = v as string | undefined;
      return val?.slice(0, 10) || '-';
    }},
    {key: 'actions', label: '操作', render: (_v, row) => {
      const exp = row as unknown as Experiment;
      const runLoading = actionLoading === `${exp.experiment_id}-run`;
      const scoreLoading = actionLoading === `${exp.experiment_id}-score`;
      return (
        <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
          <button
            style={btnStyle}
            disabled={runLoading}
            onClick={(e: any) => { e.stopPropagation(); handleAction(exp.experiment_id, 'run'); }}
          >
            {runLoading ? '运行中...' : '运行'}
          </button>
          <button
            style={btnStyle}
            disabled={scoreLoading}
            onClick={(e: any) => { e.stopPropagation(); handleAction(exp.experiment_id, 'score'); }}
          >
            {scoreLoading ? '评分中...' : '评分'}
          </button>
        </div>
      );
    }},
  ];

  return (
    <div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12}}>
        <h3 style={{margin: 0}}>实验列表</h3>
        <button style={btnPrimaryStyle}>新建实验</button>
      </div>
      <DataTable
        columns={columns}
        data={experiments as unknown as Record<string, unknown>[]}
        onRowClick={onSelectExperiment as unknown as (row: Record<string, unknown>) => void}
        emptyText="尚未创建实验。运行研究管道以生成数据。"
      />
    </div>
  );
}
