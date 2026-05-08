export type StatusBadgeProps = {
  status: string;
  label: string;
  tone?: string;
};

export default function StatusBadge({status, label, tone = 'neutral'}: StatusBadgeProps) {
  return <span className={`status-tag ${tone}`} title={label}>{status}</span>;
}
