export type StatusBadgeProps = {
  status: string;
  label: string;
  tone?: 'good' | 'bad' | 'neutral';
};

export default function StatusBadge({status, label, tone = 'neutral'}: StatusBadgeProps) {
  return <span className={`status-tag ${tone}`} title={label}>{status}</span>;
}
