import StatusBadge from './StatusBadge';
import type {TaskResponse} from '../lib/shared-types';

export type TaskQueuePanelProps = {
  title: string;
  tasks: TaskResponse[];
  onRefresh: () => void;
  emptyText?: string;
};

function toneForTask(status: TaskResponse['status']): 'good' | 'bad' | 'neutral' {
  if (status === 'completed') return 'good';
  if (status === 'failed') return 'bad';
  return 'neutral';
}

function summarizeResult(result: TaskResponse['result']): string {
  if (!result || typeof result !== 'object') return '';
  const record = result as Record<string, unknown>;
  const parts: string[] = [];

  const decision = record.decision;
  if (typeof decision === 'string' && decision.trim()) {
    parts.push(`Decision ${decision.toUpperCase()}`);
  }

  const nextStage = record.next_stage;
  if (typeof nextStage === 'string' && nextStage.trim()) {
    parts.push(`Next ${nextStage}`);
  }

  const status = record.status;
  if (typeof status === 'string' && status.trim() && !parts.some((item) => item.startsWith('Status '))) {
    parts.push(`Status ${status}`);
  }

  const selectedCandidate = record.selected_candidate;
  if (selectedCandidate && typeof selectedCandidate === 'object') {
    const candidateRecord = selectedCandidate as Record<string, unknown>;
    const strategyId = candidateRecord.strategy_id;
    if (typeof strategyId === 'string' && strategyId.trim()) {
      parts.push(`Candidate ${strategyId}`);
    }
  }

  const candidateScreen = record.candidate_screen;
  if (candidateScreen && typeof candidateScreen === 'object') {
    const candidateScreenRecord = candidateScreen as Record<string, unknown>;
    const candidateCount = candidateScreenRecord.candidate_count;
    if (typeof candidateCount === 'number' && Number.isFinite(candidateCount)) {
      parts.push(`Candidates ${candidateCount}`);
    }
  }

  const sharpe = record.sharpe_ratio;
  if (typeof sharpe === 'number' && Number.isFinite(sharpe)) {
    parts.push(`Sharpe ${sharpe.toFixed(2)}`);
  }

  const eventBacktest = record.event_backtest;
  if (eventBacktest && typeof eventBacktest === 'object') {
    const eventBacktestRecord = eventBacktest as Record<string, unknown>;
    const summary = eventBacktestRecord.summary;
    if (summary && typeof summary === 'object') {
      const summaryRecord = summary as Record<string, unknown>;
      const eventSharpe = summaryRecord.sharpe_ratio;
      if (typeof eventSharpe === 'number' && Number.isFinite(eventSharpe)) {
        parts.push(`Event Sharpe ${eventSharpe.toFixed(2)}`);
      }
    }
  }

  const weightSum = record.latest_weight_sum;
  if (typeof weightSum === 'number' && Number.isFinite(weightSum)) {
    parts.push(`Weight ${weightSum.toFixed(2)}`);
  }

  const runId = record.run_id ?? record.portfolio_run_id ?? record.manifest_id;
  if (typeof runId === 'string' && runId.trim()) {
    parts.push(runId);
  }

  return parts.join(' · ');
}

function extractBlockers(task: TaskResponse): string[] {
  const blockers = Array.isArray(task.blockers) ? task.blockers.filter(Boolean) : [];
  if (blockers.length) return blockers;
  const result = task.result;
  if (!result || typeof result !== 'object') return [];
  const record = result as Record<string, unknown>;
  if (Array.isArray(record.blockers)) {
    return record.blockers.map((item) => String(item)).filter(Boolean);
  }
  if (Array.isArray(record.recommendations)) {
    return record.recommendations.map((item) => String(item)).filter(Boolean).slice(0, 2);
  }
  return [];
}

export default function TaskQueuePanel({title, tasks, onRefresh, emptyText = '暂无后台任务'}: TaskQueuePanelProps) {
  return (
    <section className="task-queue-panel">
      <div className="panel-header">
        <h3 style={{margin: 0}}>{title}</h3>
        <button type="button" className="secondary-button" onClick={onRefresh}>刷新任务</button>
      </div>
      <div className="task-queue-list">
        {tasks.length ? tasks.map((task) => {
          const blockers = extractBlockers(task);
          const summary = summarizeResult(task.result);
          return (
            <article key={task.task_id} className="task-queue-item">
              <div className="task-queue-head">
                <div>
                  <strong>{task.label}</strong>
                  <div className="task-queue-meta">
                    <span>{task.kind}</span>
                    <span>{task.stage || task.status}</span>
                    <span>{task.progress}%</span>
                  </div>
                </div>
                <StatusBadge status={task.status.toUpperCase()} label={task.label} tone={toneForTask(task.status)} />
              </div>
              <div className="task-queue-message">{task.message || 'waiting'}</div>
              {summary ? <div className="task-queue-summary">{summary}</div> : null}
              {task.error ? <div className="task-queue-error">ERROR: {task.error}</div> : null}
              {blockers.length ? (
                <div className="task-queue-blockers">
                  {blockers.slice(0, 3).map((blocker) => <div key={blocker} className="task-queue-blocker">{blocker}</div>)}
                </div>
              ) : null}
            </article>
          );
        }) : <div className="task-queue-empty">{emptyText}</div>}
      </div>
    </section>
  );
}
