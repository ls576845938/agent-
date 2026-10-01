// Presentation only: these labels never determine action permissions.
export function guardianGuidance(guardian?: {
  tripped?: boolean;
  status?: string;
  reason_codes?: string[];
  next_safe_action?: string;
} | null): string {
  if (!guardian) return '暂时无法确认风险保护状态，请等待状态刷新。';
  if (guardian.tripped) return '风险保护已触发。请先核查账户风险，再按下方提示确认并恢复保护。';
  if (guardian.reason_codes?.includes('latch_persistence_missing')) {
    return guardian.next_safe_action === 'recover_guardian_after_fresh_preflight'
      ? '风险保护记录尚未就绪。请先完成重新预检，再恢复风险保护。'
      : '风险保护记录尚未就绪，请刷新状态并查看技术详情。';
  }
  if (guardian.status === 'clear' && !guardian.reason_codes?.length) return '未报告风险保护触发；是否允许运行仍以后端预检结果为准。';
  return '风险保护状态待确认，请查看技术详情并按后端提示处理。';
}

export function depthSourceLabel(live: boolean, fallback: boolean, fresh: boolean): string {
  return live ? '实时推送' : fallback ? (fresh ? '推送断开 · 2 秒轮询' : '盘口已过期') : '等待行情';
}
