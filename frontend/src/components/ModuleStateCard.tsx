import StatusBadge from './StatusBadge';

export type ModuleStateTone = 'good' | 'bad' | 'neutral';

export type ModuleStateAction = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: 'primary' | 'secondary';
};

export type ModuleStateCardProps = {
  key?: string;
  id: string;
  title: string;
  status: string;
  tone: ModuleStateTone;
  reason: string;
  actions?: ModuleStateAction[];
  meta?: Array<{
    label: string;
    value: string;
  }>;
  hint?: string;
};

function displayValue(value: string) {
  const labels: Record<string, string> = {
    WAITING: '等待中',
    BLOCKED: '阻塞',
    PASS: '通过',
    MISSING: '缺失',
    FROZEN: '冻结',
    LOCKED: '锁定',
    UNKNOWN: '未知',
    COMPLETED: '完成',
    READY_FOR_BACKTEST_ENTRY: '可进入回测',
    READY_FOR_PORTFOLIO_SIM: '可进入组合模拟',
  };
  return labels[value.trim().toUpperCase()] ?? value;
}

export function ModuleStateCard({
  id,
  title,
  status,
  tone,
  reason,
  actions = [],
  meta = [],
  hint,
}: ModuleStateCardProps) {
  return (
    <article className={`module-state-card module-state-${tone}`} data-testid={`module-state-${id}`}>
      <div className="module-state-header">
        <div>
          <div className="module-state-kicker">{title}</div>
          {hint ? <div className="module-state-hint">{hint}</div> : null}
        </div>
        <StatusBadge status={status} label={title} tone={tone} />
        <span className="visually-hidden">{status}</span>
      </div>

      <div className="module-state-reason">{reason}</div>

      {meta.length ? (
        <div className="module-state-meta">
          {meta.map((item) => (
            <div key={`${id}-${item.label}`} className="module-state-meta-item">
              <span>{item.label}</span>
              <strong>{displayValue(item.value)}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {actions.length ? (
        <div className="module-state-actions">
          {actions.map((action) => (
            <button
              key={`${id}-${action.label}`}
              type="button"
              className={action.variant === 'primary' ? 'primary-button' : 'secondary-button'}
              disabled={action.disabled}
              onClick={action.onClick}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}
