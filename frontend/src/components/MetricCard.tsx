import {metricClass} from '../lib/utils';

export type MetricCardProps = {
  label: string;
  value: string;
  tone?: string;
};

export default function MetricCard({label, value, tone = 'neutral'}: MetricCardProps) {
  return (
    <article className={metricClass(tone)}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
