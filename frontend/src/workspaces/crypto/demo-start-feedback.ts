import type {OperatorAction, OperatorOperationProjection} from './demo-operator-v2';

type StartFeedback = {
  kind: 'pending' | 'unknown' | 'failed' | 'succeeded';
  title: string;
  detail: string;
  guidance: string;
};

const PHASE_LABELS: Record<string, string> = {
  requested: '等待处理', local_runtime_check: '检查本机运行条件',
  credentials_demo_identity: '核对模拟账户身份', account_positions_orders_oco: '核对账户、仓位和挂单',
  ledger: '核对账本', private_ws: '建立账户实时连接', broker_truth: '核对交易所最新状态',
  dead_man: '启用断线保护', worker: '启动策略进程', running: '运行中',
  completed: '已完成', succeeded: '已完成', blocked: '被安全检查阻止',
  failed: '未成功完成', interrupted: '操作中断', timed_out: '操作超时',
};

export function isStartReceiptMessage(message: string): boolean {
  return message.startsWith('authoritative_preflight_start 已受理：')
    || message === 'authoritative_preflight_start 已完成。';
}

// Presentation only. Never infer execution permission from a request receipt,
// runtime inactivity, or the last POST message; polling owns the operation truth.
export function resolveStartFeedback(input: {
  operation: Pick<OperatorOperationProjection, 'action' | 'state' | 'phase' | 'blocker_codes' | 'acknowledged'> | null;
  unknownAction: OperatorAction | '';
  rejectedAction: OperatorAction | '';
  busy: boolean;
  attempted: boolean;
  message: string;
}): StartFeedback | null {
  const start = 'authoritative_preflight_start';
  const operation = input.operation;
  if (input.unknownAction === start) {
    return {kind: 'unknown', title: '预检结果暂未确认', detail: '暂时无法核实后端操作状态。',
      guidance: '请等待状态查询恢复；不要把网络中断当成失败，也不要重复提交启动。'};
  }
  if (operation) {
    if (operation.action !== start || operation.acknowledged) return null;
    const phase = PHASE_LABELS[operation.phase] || '等待后端阶段信息';
    if (operation.state === 'queued' || operation.state === 'running') {
      return {kind: 'pending', title: operation.state === 'queued' ? '预检已受理 · 排队中' : '权威预检进行中',
        detail: `当前阶段：${phase}`, guidance: '后端仍在检查账户、仓位及保护条件。已受理不代表启动成功，请等待最终结果，勿重复提交。'};
    }
    if (operation.state === 'succeeded') {
      return {kind: 'succeeded', title: '权威预检操作已完成', detail: `最终阶段：${phase}`,
        guidance: '当前是否运行及订单权限，以最新后端状态为准。'};
    }
    const leverageBlocked = operation.blocker_codes.includes('okx_demo_paper_exact_isolated_1x_leverage_required');
    if (operation.blocker_codes.includes('okx_demo_private_ws_startup_reconnect_probe_failed')) {
      return {kind: 'failed', title: '预检未通过 · 账户实时连接核验失败',
        detail: '重新连接或连接后的账户快照核对未完成，策略未获准启动。',
        guidance: '这不是杠杆校验错误。请查看技术诊断中的具体阶段；超时不能视为成功，必须完成新的连接和账户核对后才能恢复运行。'};
    }
    const writerLockBlocked = operation.blocker_codes.includes('okx_demo_fault_drill_runtime_root_writer_lock_unavailable');
    if (writerLockBlocked) {
      return {kind: 'failed', title: '预检未通过 · 运行目录被占用',
        detail: '后端无法取得运行目录的独占写入锁，启动已停止。',
        guidance: '请先排查重复进程或线程占用，确认策略已停止后重启服务；不要删除锁文件或反复点击启动。修复后确认本次结果，再由人工重新预检。'};
    }
    if (operation.state === 'timed_out') {
      return {kind: 'failed', title: '预检未通过 · 操作超时',
        detail: '本次预检未在规定时间内完成，不能视为启动成功。',
        guidance: '请先检查技术诊断中的失败原因；确认后台操作已结束后再确认本次结果，勿连续重复启动。'};
    }
    return {kind: 'failed', title: leverageBlocked ? '预检未通过 · 逐仓杠杆校验' : `预检未通过 · ${phase}`,
      detail: operation.blocker_codes.join('；') || `后端操作状态：${operation.state}`,
      guidance: leverageBlocked
        ? '后端未确认 BTC-USDT-SWAP 为逐仓、且多空两侧均为 1 倍；不能据此推断实际杠杆。请在 OKX 模拟盘核对账户设置及杠杆信息，确认本次终态后刷新账户快照，再重新预检。订单权限不会因此放开。'
        : '本次操作未成功完成；请按后端原因处理，确认本次终态后再人工重试。当前权限仍以后端安全状态为准。'};
  }
  if (input.rejectedAction === start) {
    return {kind: 'failed', title: '预检请求被拒绝', detail: input.message,
      guidance: '请处理拒绝原因，再确认结果并重新人工预检；不会自动重试启动。'};
  }
  if (input.attempted && input.busy) {
    return {kind: 'pending', title: '正在提交权威预检', detail: '等待后端操作回执。',
      guidance: '尚未确认启动结果，请勿重复提交。'};
  }
  return null;
}
