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
      </div>

      <div className="module-state-reason">{reason}</div>

      {meta.length ? (
        <div className="module-state-meta">
          {meta.map((item) => (
            <div key={`${id}-${item.label}`} className="module-state-meta-item">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
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
