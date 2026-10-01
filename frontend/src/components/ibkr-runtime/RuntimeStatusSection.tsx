import StatusBadge from '../StatusBadge';

export type RuntimeFieldTone = 'good' | 'bad' | 'neutral';

export type RuntimeStatusField = {
  label: string;
  value: string;
  detail?: string;
  tone?: RuntimeFieldTone;
  testId?: string;
};

type RuntimeStatusSectionProps = {
  title: string;
  subtitle: string;
  fields: RuntimeStatusField[];
  testId: string;
};

export function RuntimeStatusSection({title, subtitle, fields, testId}: RuntimeStatusSectionProps) {
  return (
    <section className="panel" data-testid={testId}>
      <div className="panel-header">
        <h3>{title}</h3>
        <span>{subtitle}</span>
      </div>
      <div className="safety-grid">
        {fields.map((field) => (
          <article
            className="safety-card"
            data-testid={field.testId ? `runtime-field-${field.testId}` : undefined}
            key={`${testId}-${field.label}`}
          >
            <h4>{field.label}</h4>
            <StatusBadge status={field.value} label={field.label} tone={field.tone ?? 'neutral'} />
            {field.detail ? <p className="text-muted" style={{margin: 0, overflowWrap: 'anywhere'}}>{field.detail}</p> : null}
          </article>
        ))}
      </div>
    </section>
  );
}
