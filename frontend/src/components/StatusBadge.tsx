export type StatusBadgeProps = {
  status: string;
  label: string;
  tone?: 'good' | 'bad' | 'neutral';
};

const STATUS_LABELS: Record<string, string> = {
  PASS: '通过',
  PASSED: '通过',
  FAIL: '失败',
  FAILED: '失败',
  BLOCKED: '阻塞',
  WARN: '警告',
  WARNING: '警告',
  READY: '就绪',
  READY_FOR_BACKTEST_ENTRY: '可进入回测',
  COMPLETED: '完成',
  COMPLETE: '完成',
  RUNNING: '运行中',
  QUEUED: '排队中',
  PENDING: '待处理',
  MISSING: '缺失',
  UNKNOWN: '未知',
  INSTALLED: '已安装',
  OK: '正常',
  CLEAR: '正常',
  ERROR: '错误',
  REJECTED: '拒绝',
  FROZEN: '冻结',
  OPEN: '开放',
  HALTED: '已暂停',
};

function displayStatus(status: string) {
  const normalized = status.trim().replace(/\s+/g, '_').toUpperCase();
  if (STATUS_LABELS[normalized]) return STATUS_LABELS[normalized];
  return status
    .replace(/\bfrozen\b/gi, '冻结')
    .replace(/\bmissing\b/gi, '缺失')
    .replace(/\bwaiting\b/gi, '等待中')
    .replace(/\blocked\b/gi, '锁定')
    .replace(/\bconfirmed\b/gi, '已确认')
    .replace(/\blive\b/gi, '实盘');
}

export default function StatusBadge({status, label, tone = 'neutral'}: StatusBadgeProps) {
  return <span className={`status-tag ${tone}`} title={label}>{displayStatus(status)}</span>;
}
