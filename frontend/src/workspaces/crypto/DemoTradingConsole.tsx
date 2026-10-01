import {useEffect, useMemo, useRef, useState} from 'react';
import CandidateHandoffInbox from '../research/CandidateHandoffInbox';

import type {
  DemoCatalog,
  DemoRuntimeStatus,
  DemoStrategySpec,
  PrivateReadonlyObservationProjection,
} from './demo-types';
import {
  OPERATOR_ACTIONS as OPERATOR_ACTIONS_FOR_UI,
  resolveOperatorAcknowledgementAction,
} from './demo-operator-v2';
import type {DemoOperatorController, OperatorAction} from './demo-operator-v2';
import {isStartReceiptMessage, resolveStartFeedback} from './demo-start-feedback';
import {guardianGuidance} from './console-display';
import {accountFactsView, finiteAccountNumber} from './account-facts-view';
import type {CryptoWorkspaceMode} from './workspace-access';
import {
  strategyAdapterLabel,
  strategyCapabilityText,
  strategyPresentationName,
  strategyStatusLabel,
  strategyVariantLabel,
} from '../../lib/strategy-presentation';

type RecoveryStageState = 'ready' | 'waiting' | 'blocked';

type RecoveryStage = {
  key: string;
  label: string;
  state: RecoveryStageState;
  detail: string;
};

type RuntimeErrorView = {
  transport: boolean;
  message: string;
  code: string;
};

const TRANSPORT_ERROR_PATTERN = /urlerror|remote.?disconnect|disconnect|connection|tls|dns|timeout/i;

function runtimeErrorView(value: string | undefined, transientProbe = false): RuntimeErrorView {
  const raw = String(value ?? '').trim();
  if (!raw) return {transport: false, message: '', code: ''};
  const transport = TRANSPORT_ERROR_PATTERN.test(raw);
  const match = raw.match(/\b(?:URLError|[A-Za-z][A-Za-z0-9_.-]*(?:Error|Exception)|okx_[A-Za-z0-9_.-]+)\b/i);
  const code = match?.[0] ?? raw.split(/\s+/)[0];
  if (transientProbe && raw.toLowerCase().includes('private_ws_startup_probe_local_disconnect')) {
    return {transport: false, message: '正在验证断线重连', code};
  }
  return transport
    ? {transport: true, message: 'OKX Demo 网络连接失败；保持 cancel-only，请检查网络/代理后重新预检', code}
    : {transport: false, message: raw, code};
}

function runtimeErrorText(value: string | undefined, transientProbe = false): string {
  const view = runtimeErrorView(value, transientProbe);
  return view.transport && view.code ? `${view.message}（诊断：${view.code}）` : view.message;
}

function runtimeDiagnosticText(
  value: string | undefined,
  currentAttempt: boolean,
  transientProbe = false,
): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '无';
  const view = runtimeErrorView(raw, currentAttempt && transientProbe);
  if (!currentAttempt && view.transport) {
    return `历史错误（不代表当前预检）：${view.code || raw}`;
  }
  return runtimeErrorText(raw, currentAttempt && transientProbe);
}

function runtimeHealthErrorView(
  value: string | undefined,
  currentAttempt: boolean,
  transientProbe = false,
): RuntimeErrorView {
  const view = runtimeErrorView(value, currentAttempt && transientProbe);
  if (!currentAttempt && view.transport) {
    return {
      ...view,
      message: `历史错误（上一次预检记录，不代表当前网络状态）：${view.code || 'transport_error'}`,
    };
  }
  return view;
}

function failureEvidenceForProbe(
  lastError: string | undefined,
  privateWsStatus: string | undefined,
  runtimeStatus: string | undefined,
): boolean {
  const raw = String(lastError ?? '').toLowerCase();
  if (!raw.includes('private_ws_startup_probe_local_disconnect')) return false;
  const terminal = /blocked|fail|failed|stopped_after_start_failure|terminal/.test(
    `${String(privateWsStatus ?? '').toLowerCase()} ${String(runtimeStatus ?? '').toLowerCase()}`,
  );
  return !terminal;
}

const AUTHORITATIVE_REALIZED_NET_PNL_PROVENANCE = 'ledger_cash_and_fills_reconciled_v1';

export default function DemoTradingConsole({
  workspaceMode = 'runtime',
  operatorController,
  catalog,
  status,
  statusError,
  privateReadonlyObservation,
  privateReadonlyObservationError,
  selectedCandidateId,
  onCandidateChange,
  onStrategyChange,
  runtimeSignalLoading,
  runtimeSignalReady,
  runtimeSignalBlocker,
  promotionReadinessLoading,
  promotionReadinessBlockers,
}: {
  workspaceMode?: CryptoWorkspaceMode;
  operatorController: DemoOperatorController;
  catalog: DemoCatalog | null;
  status: DemoRuntimeStatus | null;
  statusError: string;
  privateReadonlyObservation: PrivateReadonlyObservationProjection | null;
  privateReadonlyObservationError: string;
  selectedCandidateId: string;
  onCandidateChange: (candidateId: string) => void;
  onStrategyChange: (strategyId: string) => void;
  runtimeSignalLoading: boolean;
  runtimeSignalReady: boolean;
  runtimeSignalBlocker: string;
  promotionReadinessLoading: boolean;
  promotionReadinessBlockers: string[];
}) {
  // Display restriction only; the existing disabled controller and backend
  // contract remain the authority. Keep the original console mounted.
  const runtimeReadsEnabled = workspaceMode === 'runtime';
  const modeLabel = workspaceMode === 'research_readonly' ? '研究只读' : '后端模式尚未确认';
  const modeReason = `${modeLabel}：运行操作未开放，账户与运行状态未读取。`;
  const [confirmationText, setConfirmationText] = useState('');
  const [checks, setChecks] = useState({
    demo: false,
    autoOrders: false,
    limits: false,
    cancelOnly: false,
    dedicatedAccount: false,
    p0Protection: false,
  });
  const [startValidationMessage, setStartValidationMessage] = useState('');
  const [recoveryAttempted, setRecoveryAttempted] = useState(false);
  const [flattenConfirmOpen, setFlattenConfirmOpen] = useState(false);
  const [flattenConfirmation, setFlattenConfirmation] = useState('');
  const [emergencyConfirmOpen, setEmergencyConfirmOpen] = useState(false);
  const [emergencyConfirmation, setEmergencyConfirmation] = useState('');
  const flattenTriggerRef = useRef<HTMLButtonElement | null>(null);
  const emergencyTriggerRef = useRef<HTMLButtonElement | null>(null);
  const flattenDialogRef = useRef<HTMLDialogElement | null>(null);
  const emergencyDialogRef = useRef<HTMLDialogElement | null>(null);
  const flattenInputRef = useRef<HTMLInputElement | null>(null);
  const emergencyInputRef = useRef<HTMLInputElement | null>(null);
  const previousFlattenConfirmOpen = useRef(false);
  const previousEmergencyConfirmOpen = useRef(false);
  const contract = operatorController.contract;
  const guardian = contract.guardian ?? status?.guardian;
  const actionAuthorization = (action: OperatorAction) => contract.action_map[action];
  const actionAllowed = (action: OperatorAction) => runtimeReadsEnabled && contract.valid && actionAuthorization(action)?.allowed === true;
  const actionHelpId = (action: OperatorAction) => `btc-demo-action-help-${action.replace(/_/g, '-')}`;
  const actionReasonText = (action: OperatorAction) => {
    if (!runtimeReadsEnabled) return modeReason;
    const row = actionAuthorization(action);
    const details = row ? [...row.blocker_codes, ...row.reason_codes] : contract.blockers;
    const busy = operatorController.isActionBusy(action) ? ['action_busy'] : [];
    const unique = [...new Set([...details, ...busy])];
    return unique.join('、') || '服务端未提供额外阻塞原因';
  };
  const message = operatorController.message;
  const selectable = useMemo(
    () => (catalog?.strategies ?? []).filter((item) => item.demo_selectable),
    [catalog?.strategies],
  );
  const selected = selectable.find((item) => item.candidate_id === selectedCandidateId) ?? selectable[0] ?? null;
  const strategyLines = useMemo(() => {
    const byLine = new Map<string, DemoStrategySpec[]>();
    (catalog?.strategies ?? []).forEach((item) => {
      byLine.set(item.strategy_id, [...(byLine.get(item.strategy_id) ?? []), item]);
    });
    return [...byLine.values()].map((items) => items.find((item) => item.demo_selectable) ?? items[0]);
  }, [catalog?.strategies]);
  const selectedStrategyId = selected?.strategy_id ?? '';
  const lineCandidates = selectable.filter((item) => item.strategy_id === selectedStrategyId);
  const expectedConfirmation = catalog?.confirmation_text ?? 'BTC DEMO';
  const missingConfirmations = [
    !checks.demo ? '仅连接 OKX Demo、禁止实盘' : '',
    !checks.autoOrders ? '允许策略经 Risk 与 OMS 自动下单/平仓' : '',
    !checks.limits ? '接受服务端返回的 Demo 限额' : '',
    !checks.cancelOnly ? '异常立即进入 cancel-only' : '',
    !checks.dedicatedAccount ? '专用 Demo 账户' : '',
    !checks.p0Protection ? 'P0 服务端保护与 dead-man' : '',
    confirmationText !== expectedConfirmation ? `输入 ${expectedConfirmation}` : '',
  ].filter(Boolean);
  const allConfirmed = missingConfirmations.length === 0;
  const runtime = status?.runtime;
  const observation = status?.observation;
  const privateWs = status?.private_ws;
  const ledgerReconciliation = status?.ledger_reconciliation;
  const operatorControl = status?.operator_control;
  const startAttempt = operatorControl?.start_attempt
    ?? status?.start_attempt
    ?? operatorController.operation?.start_attempt
    ?? null;
  const operatorContractReady = contract.valid;
  const currentAttempt = operatorControl?.incident.current_attempt !== false;
  const exchange = status?.exchange;
  // Control availability comes from one backend contract only.  Raw runtime
  // fields remain visible as diagnostics, but never enable an operator action.
  const isActive = runtime?.active === true;
  const strictObservationHours = observation?.consecutive_hours ?? 0;
  const observationHours = observation?.cumulative_observation_hours ?? strictObservationHours;
  const observationHoursRemaining = Math.max(0, 25 - observationHours);
  const observationProgressPercent = Math.min(100, Math.max(0, (observationHours / 25) * 100));
  const cumulativeWindowComplete = observation?.cumulative_window_25h_complete
    ?? observation?.window_complete
    ?? false;
  const cumulativeBlockers = observation?.cumulative_blockers ?? observation?.blockers ?? [];
  const observationAccumulating = runtime?.active === true
    && runtime.worker_alive === true
    && runtime.opening_allowed === true
    && runtime.cancel_only === false;
  const privateObservationRunning = privateReadonlyObservation?.runner_active === true;
  const privateObservationHeadMatch = privateReadonlyObservation?.head_match === true;
  const privateObservationHours = privateReadonlyObservation?.progress.progress_hours ?? 0;
  const privateObservationPercent = Math.min(100, Math.max(0, (privateObservationHours / 25) * 100));
  const position = exchange?.positions?.find((item) => Number(item.contracts) !== 0);
  const actualLongLeverage = startAttempt?.actual_long_leverage
    ?? exchange?.positions?.find((item) => item.position_side === 'long')?.leverage
    ?? 'unknown';
  const actualShortLeverage = startAttempt?.actual_short_leverage
    ?? exchange?.positions?.find((item) => item.position_side === 'short')?.leverage
    ?? 'unknown';
  const runtimeTone = operatorControl?.incident.severity === 'critical' || operatorControl?.incident.severity === 'danger'
    ? 'danger'
    : operatorControl?.incident.severity === 'warning'
      ? 'warning'
      : operatorControl?.lifecycle === 'running'
        ? 'running'
        : 'stopped';
  const catalogLoading = runtimeReadsEnabled && catalog === null;
  const runtimeStatusLoading = runtimeReadsEnabled && status === null;
  const demoEnvironmentReady = catalog?.environment === 'OKX Demo' && catalog.instrument_id === 'BTC-USDT-SWAP';
  const limitPerOrder = status?.limits?.order_contracts ?? status?.limits?.max_order_contracts ?? '未提供';
  const limitNet = status?.limits?.max_net_contracts ?? '未提供';
  const limitNotional = status?.limits?.max_notional_usdt ?? '未提供';
  const ledgerReady = ledgerReconciliation?.status === 'reconciled'
    && ledgerReconciliation.current_state_exchange_snapshot_match === true
    && ledgerReconciliation.funding_cashflow_reconciled === true;
  const accountView = accountFactsView(exchange, !statusError && ledgerReady);
  const failureEvidence = [
    runtime?.last_error ?? '',
    ...(runtime?.blockers ?? []),
    ...(privateWs?.blockers ?? []),
  ].filter(Boolean);
  const transientPrivateWsProbe = currentAttempt && failureEvidenceForProbe(
    runtime?.last_error,
    privateWs?.status,
    runtime?.status,
  );
  const runtimeStartPathAvailable = actionAllowed('authoritative_preflight_start');
  const controlContractBlockers = runtimeReadsEnabled ? [
    !operatorContractReady ? `V2 控制契约不可用：${contract.blockers.join('、') || 'operator_v2_contract_invalid'}` : '',
    operatorContractReady && !runtimeStartPathAvailable
      ? actionAuthorization('authoritative_preflight_start')?.blocker_codes.join('、') || 'server_denied'
      : '',
  ].filter(Boolean) : [];
  // The current runtime normally does not publish one reconciled,
  // provenance-bound realised net-PnL field. A future projection may be
  // rendered only when it explicitly carries both value and provenance.
  const ledgerProjection = ledgerReconciliation as Record<string, unknown> | undefined;
  const realizedPnlCandidate = ledgerProjection?.authoritative_realized_net_pnl;
  const realizedPnlProvenance = ledgerProjection?.authoritative_realized_net_pnl_provenance;
  const authoritativeRealizedNetPnl = accountView.usable
    && realizedPnlProvenance === AUTHORITATIVE_REALIZED_NET_PNL_PROVENANCE
    && finiteAccountNumber(realizedPnlCandidate) !== null
    ? finiteAccountNumber(realizedPnlCandidate)
    : null;
  const markToMarketPnl = accountView.usable && position
    ? finiteAccountNumber(position.unrealized_pnl)
    : null;
  // The backend operator contract remains the sole source of stage truth while
  // /start is in flight.  A busy action must not turn an already READY stage
  // into a synthetic WAITING state or hide a concrete BLOCKED step.
  const recoveryStages: RecoveryStage[] = operatorControl?.preflight_stages ?? [];
  const operationIsTerminal = Boolean(operatorController.operation
    && operatorController.operation.state !== 'queued'
    && operatorController.operation.state !== 'running');
  const acknowledgementAction = resolveOperatorAcknowledgementAction(
    operatorController.operation,
    operatorController.operationUnknownAction,
    operatorController.operationRejectedAction,
  );
  const acknowledgementBusy = acknowledgementAction
    ? operatorController.isActionBusy(acknowledgementAction)
    : false;
  const startFeedback = resolveStartFeedback({
    operation: operatorController.operation,
    unknownAction: operatorController.operationUnknownAction,
    rejectedAction: operatorController.operationRejectedAction,
    busy: operatorController.isActionBusy('authoritative_preflight_start'),
    attempted: recoveryAttempted,
    message,
  });
  const promotionItems = useMemo(
    () => promotionReadinessBlockers.map(promotionReadinessItem),
    [promotionReadinessBlockers],
  );
  const statusErrorView = runtimeErrorView(statusError);
  const transportStatusError = statusErrorView.transport;
  const statusErrorLabel = transportStatusError
    ? statusErrorView.message
    : 'Demo 状态接口不可用，未计入当前小时';
  const statusErrorCode = statusErrorView.code || 'transport_error';
  const runtimeLastErrorView = runtimeHealthErrorView(runtime?.last_error, currentAttempt, transientPrivateWsProbe);
  const authorityUpdatedAt = accountView.usable ? exchange?.captured_at_utc : undefined;
  const authorityPosition = accountView.position;
  const protectionStatus = accountView.protection;

  const toggle = (key: keyof typeof checks) => {
    setStartValidationMessage('');
    setChecks((current) => ({...current, [key]: !current[key]}));
  };
  const start = async () => {
    if (!runtimeStartPathAvailable || operatorController.isActionBusy('authoritative_preflight_start')) return;
    if (!catalog || !selected) {
      setStartValidationMessage('还缺 1 项：等待后端策略目录与可执行候选');
      return;
    }
    const missing = missingConfirmations;
    if (missing.length) {
      setStartValidationMessage(`还缺 ${missing.length} 项：${missing.join('；')}`);
      const firstMissingIndex = [
        !checks.demo,
        !checks.autoOrders,
        !checks.limits,
        !checks.cancelOnly,
        !checks.dedicatedAccount,
        !checks.p0Protection,
        confirmationText !== expectedConfirmation,
      ].findIndex(Boolean);
      const target = document.querySelector<HTMLElement>(
        firstMissingIndex === 6
          ? '[data-testid="btc-demo-confirmation-text"]'
          : `[data-testid="btc-demo-confirm-${['demo', 'auto-orders', 'limits', 'cancel-only', 'dedicated-account', 'p0-protection'][firstMissingIndex]}"]`,
      );
      target?.focus({preventScroll: true});
      target?.scrollIntoView({block: 'center'});
      return;
    }
    setStartValidationMessage('');
    setRecoveryAttempted(true);
    await operatorController.dispatch('authoritative_preflight_start', {
      strategy_id: selected.strategy_id,
      candidate_id: selected.candidate_id,
      strategy_version: selected.strategy_version,
      instrument_id: catalog.instrument_id,
      confirmation_text: catalog.confirmation_text,
      confirm_demo_only: checks.demo,
      confirm_automatic_orders: checks.autoOrders,
      confirm_risk_limits: checks.limits,
      confirm_cancel_only_on_error: checks.cancelOnly,
      confirm_dedicated_demo_account: checks.dedicatedAccount,
    });
  };

  useEffect(() => {
    if (!flattenConfirmOpen && !emergencyConfirmOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setFlattenConfirmOpen(false);
        setEmergencyConfirmOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [flattenConfirmOpen, emergencyConfirmOpen]);

  useEffect(() => {
    if (flattenConfirmOpen) {
      flattenInputRef.current?.focus({preventScroll: true});
    } else if (previousFlattenConfirmOpen.current) {
      flattenTriggerRef.current?.focus({preventScroll: true});
    }
    previousFlattenConfirmOpen.current = flattenConfirmOpen;
  }, [flattenConfirmOpen]);

  useEffect(() => {
    if (emergencyConfirmOpen) {
      emergencyInputRef.current?.focus({preventScroll: true});
    } else if (previousEmergencyConfirmOpen.current) {
      emergencyTriggerRef.current?.focus({preventScroll: true});
    }
    previousEmergencyConfirmOpen.current = emergencyConfirmOpen;
  }, [emergencyConfirmOpen]);

  return (
    <aside className="tv-demo-console" data-testid="btc-demo-console">
      <div className="tv-console-head">
        <div>
          <span className="tv-kicker">模拟交易</span>
          <h2>OKX 模拟盘</h2>
        </div>
        <span className={`tv-runtime-pill ${runtimeTone}`}><i />{!runtimeReadsEnabled ? modeLabel : operatorControl?.lifecycle_label ?? '控制契约不可用'}</span>
      </div>
      <CandidateHandoffInbox />
      <section
        className={`tv-operator-control ${!runtimeReadsEnabled ? 'warning' : operatorControl?.incident.severity ?? 'critical'}`}
        data-testid="btc-demo-operator-control"
      >
        <div className="tv-operator-control-copy">
          <span>当前影响</span>
          <strong>{!runtimeReadsEnabled ? modeLabel : operatorControl?.incident.title ?? '后端统一运行控制契约不可用'}</strong>
          <p>{!runtimeReadsEnabled ? modeReason : operatorControl?.incident.summary ?? '无法确认后端运行状态，暂不允许启动。'}</p>
        </div>
        <div className="tv-operator-control-tags">
          <span>{operatorControl?.lifecycle_label ?? '状态未知'}</span>
          <span>{operatorControl?.incident.impact_label ?? '禁止启动'}</span>
          <span>{operatorControl?.safe_mode_label === 'Cancel-only' ? '仅允许撤单' : operatorControl?.safe_mode_label === 'Fail-closed' || !operatorControl?.safe_mode_label ? '安全阻止' : operatorControl.safe_mode_label}</span>
        </div>
        <details data-testid="btc-demo-technical-details">
          <summary>技术详情</summary>
        <div className="tv-operator-control-tags" data-testid="btc-demo-operator-v2-identity">
          <span>V2 {contract.valid ? 'valid' : 'invalid'}</span>
          <span>revision {contract.state_revision ?? '—'}</span>
          <span>runtime {contract.runtime_identity || 'unavailable'}</span>
          <span>as_of {contract.as_of_utc || 'unavailable'}</span>
          <span>operation {operatorController.operation?.state ?? (operatorController.operationRejectedAction ? 'rejected' : operatorController.operationUnknownAction ? 'unknown' : 'none')}</span>
        </div>
        <div className="tv-operator-control-tags" data-testid="btc-demo-start-attempt-binding">
          <span>risk {startAttempt?.risk_profile ?? status?.risk_profile?.name ?? 'unknown'}</span>
          <span>expected leverage {startAttempt?.expected_leverage ?? status?.risk_profile?.max_configured_leverage ?? 'unknown'}</span>
          <span>actual long / short {actualLongLeverage} / {actualShortLeverage}</span>
          <span>attempt {startAttempt?.current_attempt === true ? 'current' : startAttempt?.historical === true ? 'historical' : 'unknown'}</span>
          <span>history {operatorControl?.historical_start_attempts?.length ?? (runtimeReadsEnabled ? 0 : '未知')}</span>
          <span>policy {startAttempt?.effective_policy_digest ? startAttempt.effective_policy_digest.slice(0, 12) : 'unknown'}</span>
          <span>created {startAttempt?.created_at_utc ? formatTime(startAttempt.created_at_utc) : 'unknown'}</span>
          <span>updated {startAttempt?.updated_at_utc ? formatTime(startAttempt.updated_at_utc) : 'unknown'}</span>
        </div>
        <details data-testid="btc-demo-operator-v2-blockers">
          <summary>操作受限原因</summary>
          {Object.values(contract.action_map).map((row) => (
            <code key={row.action}>{row.action}: {[...row.blocker_codes, ...row.reason_codes].join(',') || 'none'}</code>
          ))}
        </details>
        {operatorControl?.incident.reason_codes.length ? (
          <details>
            <summary>查看技术诊断</summary>
            {operatorControl.incident.reason_codes.map((reason) => <code key={reason}>{reason}</code>)}
          </details>
        ) : null}
        </details>
      </section>
      <section className="tv-guardian-risk-bar" data-testid="btc-demo-guardian-risk-bar" aria-label="Guardian 风险状态">
        <div className="tv-section-title"><span>风险保护状态</span><small>后端确认结果</small></div>
        <div className="tv-runtime-health-grid">
          <RuntimeFact label="保护记录" value={guardian?.persistence_state === 'missing' || !guardian?.persistence_state ? '尚未就绪' : '查看技术详情'} tone={guardian?.status === 'clear' ? 'pass' : 'blocked'} />
          <RuntimeFact label="风险触发 / 确认" value={`${guardian?.tripped ? '已触发' : guardian?.status === 'clear' ? '未触发' : '待确认'} / ${guardian?.acknowledged ? '已确认' : '未确认'}`} tone={guardian?.tripped || guardian?.status !== 'clear' ? 'blocked' : 'pass'} />
          <RuntimeFact label="权威仓位" value={`${guardian?.position?.side ?? 'unknown'} ${guardian?.position?.contracts ?? '—'} 张`} />
          <RuntimeFact label="盈亏 / 回撤" value={`${guardian?.pnl?.realized ?? '暂无数据'} / ${guardian?.drawdown?.value ?? '暂无数据'} ${guardian?.pnl?.unit ?? 'USDT'}`} />
          <RuntimeFact label="最近健康观测" value={guardian?.last_observation_time_utc ? formatTime(guardian.last_observation_time_utc) : '暂无数据'} />
        </div>
        <p className="tv-console-warning">{!runtimeReadsEnabled && !guardian ? '保护状态未读取，不推断账户健康或故障。' : guardianGuidance(guardian)}</p>
        <details><summary>风险诊断详情</summary>
          <p>原因：{(guardian?.reason_codes ?? ['latch_persistence_missing']).join('、')}；后端建议：{guardian?.next_safe_action ?? '未提供'}</p>
          <p>记录状态：{guardian?.persistence_state ?? 'missing'}；版本：{guardian?.generation ?? '—'}；观测标识：{guardian?.last_observation_digest ?? '未提供'}</p>
        </details>
      </section>
      <div className="tv-demo-authority-bar" data-testid="btc-demo-authority-bar">
        <div><span>权威仓位</span><strong>{authorityPosition}</strong></div>
        <div><span>均价 / Mark</span><strong>{accountView.usable ? `${formatNumber(position?.average_price, 1)} / ${formatNumber(position?.mark_price ?? exchange?.mark?.mark_price, 1)}` : '未知 / 未知'}</strong></div>
        <div><span>已实现 / 未实现</span><strong>{authoritativeRealizedNetPnl === null ? '不可用' : `${authoritativeRealizedNetPnl.toFixed(4)} USDT`} / {markToMarketPnl === null ? '不可用' : `${markToMarketPnl.toFixed(4)} USDT`}</strong></div>
        <div><span>挂单 / 保护单 / 更新时间</span><strong>{accountView.pendingOrders} / {protectionStatus} · {formatTime(authorityUpdatedAt)}</strong></div>
        <small>{accountView.usable ? '来源：Private REST + Private WS + ledger 对账；仅 Demo 已返回快照，不代表实时连接正常' : '账户事实缺失或未完成对账；不能推断空仓、零挂单或零成交'}</small>
      </div>

      <section
        className="tv-console-section tv-observation-progress tv-private-observation-progress"
        data-testid="btc-private-readonly-observation-progress"
      >
        <div className="tv-observation-details">
          <strong>独立 Private Readonly 25h 观察</strong>
          <span>独立 runner 的 GET-only 脱敏投影；不会启动或重启观察进程</span>
        </div>
        <div className="tv-observation-progress-summary">
          <strong>{privateReadonlyObservation ? `${privateObservationHours.toFixed(2)} / 25` : '— / 25'}</strong>
          <span>{privateReadonlyObservation
            ? `完整收据 ${privateReadonlyObservation.progress.completed_hours} 小时；剩余 ${privateReadonlyObservation.progress.remaining_hours.toFixed(2)} 小时`
            : '只读投影不可用，不从 Demo runtime 推测进度'}</span>
        </div>
        <div
          className="tv-observation-progress-track"
          role="progressbar"
          aria-label="独立 Private Readonly 25 小时观察进度"
          aria-valuemin={0}
          aria-valuemax={25}
          aria-valuenow={privateObservationHours}
          aria-valuetext={`${privateObservationHours.toFixed(2)} / 25 小时`}
        >
          <i style={{width: `${privateObservationPercent}%`}} />
        </div>
        <div className={`tv-observation-runtime-state ${privateObservationRunning ? 'running' : 'stopped'}`}>
          <i />
          <strong>{privateObservationRunning
            ? (privateObservationHeadMatch ? '独立只读 runner 正在观察' : 'runner 正在观察，但仅属历史 HEAD 证据')
            : '独立只读观察未处于新鲜运行态'}</strong>
          <span>{privateReadonlyObservation
            ? `${privateReadonlyObservation.run_id} · runner ${privateReadonlyObservation.source_head.slice(0, 12)} · current ${privateReadonlyObservation.current_head.slice(0, 12) || 'unknown'} · revision ${privateReadonlyObservation.state_revision}`
            : (privateReadonlyObservationError || '等待后端只读投影')}</span>
        </div>
        <div className="tv-observation-facts">
          <RuntimeFact label="最后观测" value={formatTime(privateReadonlyObservation?.last_observed_at_utc)} />
          <RuntimeFact label="Receipt 数" value={String(privateReadonlyObservation?.progress.receipt_count ?? (runtimeReadsEnabled ? 0 : '未知'))} />
          <RuntimeFact label="Private WS" value={!runtimeReadsEnabled && !privateReadonlyObservation ? '未知 · 未读取' : privateReadonlyObservation?.private_ws.connected && privateReadonlyObservation.private_ws.listener_alive ? 'connected / alive' : 'not healthy'} />
          <RuntimeFact label="REST / WS 对账" value={privateReadonlyObservation?.reconciliation.snapshot_reconciled && privateReadonlyObservation.private_ws.reconciled ? 'reconciled' : 'not proven'} />
          <RuntimeFact label="Funding" value={privateReadonlyObservation?.reconciliation.funding_reconciled ? 'reconciled' : 'not proven'} />
          <RuntimeFact label="HEAD 绑定" value={!runtimeReadsEnabled && !privateReadonlyObservation ? '未知 · 未读取' : privateObservationHeadMatch ? 'current HEAD' : 'historical / mismatch'} />
          <RuntimeFact label="安全边界" value="order / live / transfer / withdraw = false" />
        </div>
        {(privateReadonlyObservation?.blockers.length || privateReadonlyObservation?.gap_flags.length) ? (
          <small className="tv-observation-receipt-note">
            当前阻塞/缺口：{[...(privateReadonlyObservation?.blockers ?? []), ...(privateReadonlyObservation?.gap_flags ?? [])].join('、')}
          </small>
        ) : null}
        <small className="tv-observation-receipt-note">
          此卡只显示外部 runner 的脱敏只读进度；gate_eligible=false，25 小时完成仍不等于 promotion、paper 或 live ready。
        </small>
      </section>

      <details className="tv-console-section tv-observation-progress" data-testid="btc-demo-observation-progress">
        <summary>
          <strong>历史观察证据（不作为当前 Demo 启动门槛）</strong>
          <span>当前 runtime 状态接口计数：{status ? `${observationHours} / 25` : '— / 25'}；外部不可变封存证据独立保存</span>
        </summary>
        <div className="tv-observation-details">
        <div className="tv-section-title"><span>当前 runtime 观察计数</span><small>跨重启累计有效 UTC 小时；不替代连续观察门槛</small></div>
        <div className="tv-observation-progress-summary">
          <strong>{status ? `${observationHours} / 25` : '— / 25'}</strong>
          <span>{status ? (observationHoursRemaining > 0 ? `还需 ${observationHoursRemaining} 个完整小时` : '已达到 25 个完整小时') : '状态接口不可用，未计入当前小时'}</span>
        </div>
        <small className="tv-observation-receipt-note">当前 runtime 计数与外部不可变封存证据相互独立；这里只展示状态接口返回的 hash-chain 收据事实，不会把 0 / 25 伪装成历史已完成，也不会解锁晋级。</small>
        <div
          className="tv-observation-progress-track"
          role="progressbar"
          aria-label="25 小时累计进度"
          aria-valuemin={0}
          aria-valuemax={25}
          aria-valuenow={status ? observationHours : 0}
          aria-valuetext={status ? `${observationHours} / 25 个累计有效小时` : '状态接口不可用，未计入当前小时'}
        >
          <i style={{width: `${status ? observationProgressPercent : 0}%`}} />
        </div>
        <div className={`tv-observation-runtime-state ${observationAccumulating ? 'running' : 'stopped'}`}>
          <i />
          <strong>{observationAccumulating ? '正在累计完整小时' : '累计已停止，当前小时不计入'}</strong>
          <span>active {yesNo(runtime?.active)} · worker {yesNo(runtime?.worker_alive)} · opening {yesNo(runtime?.opening_allowed)} · cancel-only {yesNo(runtime?.cancel_only)}</span>
        </div>
        {statusError ? (
          <div className="tv-runtime-error" data-testid="btc-demo-status-error">
            <strong>{statusErrorLabel}</strong>
            <code title={statusError}>诊断：{statusErrorCode}</code>
            <span>前端会自动重试；在成功读取前保持 fail-closed，不把缺失状态当成 0/25。</span>
          </div>
        ) : null}
        <div className="tv-observation-facts">
          <RuntimeFact label="Receipt 数" value={String(observation?.observation_receipt_count ?? (runtimeReadsEnabled ? 0 : '未知'))} />
          <RuntimeFact label="最后完整观察小时" value={formatTime(observation?.last_observation_hour_utc)} />
          <RuntimeFact label="累计目标完成" value={cumulativeWindowComplete ? '是' : '否'} tone={cumulativeWindowComplete ? 'pass' : 'blocked'} />
          <RuntimeFact label="严格连续小时" value={!runtimeReadsEnabled && !observation ? '未知 / 25' : `${strictObservationHours} / 25`} tone={strictObservationHours >= 25 ? 'pass' : 'blocked'} />
          <RuntimeFact label="Last heartbeat" value={formatTime(runtime?.last_heartbeat_utc)} tone={runtime?.last_heartbeat_utc ? 'pass' : 'unknown'} />
          <RuntimeFact label="Last reconcile" value={formatTime(runtime?.last_reconciled_at_utc)} tone={runtime?.last_reconciled_at_utc ? 'pass' : 'unknown'} />
          <RuntimeFact label={currentAttempt ? 'Runtime error' : '历史 Runtime 错误'} value={!runtimeReadsEnabled && !runtime ? '未知 · 未读取' : runtimeDiagnosticText(runtime?.last_error, currentAttempt, transientPrivateWsProbe)} tone={!runtimeReadsEnabled && !runtime ? 'unknown' : runtime?.last_error ? 'blocked' : 'pass'} />
          <RuntimeFact label={currentAttempt ? 'Runtime blocker' : '历史 Runtime blocker'} value={!runtimeReadsEnabled && !runtime ? '未知 · 未读取' : runtimeDiagnosticText(runtime?.blockers?.[0], currentAttempt, transientPrivateWsProbe)} tone={!runtimeReadsEnabled && !runtime ? 'unknown' : runtime?.blockers?.length ? 'blocked' : 'pass'} />
          <RuntimeFact label={currentAttempt ? '累计观察 blocker' : '历史观察 blocker'} value={!runtimeReadsEnabled && !observation ? '未知 · 未读取' : runtimeDiagnosticText(cumulativeBlockers[0], currentAttempt, transientPrivateWsProbe)} tone={!runtimeReadsEnabled && !observation ? 'unknown' : cumulativeBlockers.length ? 'blocked' : 'pass'} />
          <RuntimeFact label="账户快照订单 / 成交" value={`${accountView.orders} / ${accountView.fills}`} />
          <RuntimeFact label="Funding bills" value={accountView.fundingBills} />
          <RuntimeFact label="Private WS" value={!runtimeReadsEnabled && !privateWs ? '未知 · 未读取' : privateWs?.connected ? 'connected' : 'disconnected'} tone={!runtimeReadsEnabled && !privateWs ? 'unknown' : privateWs?.connected ? 'pass' : 'blocked'} />
          <RuntimeFact label="WS listener" value={!runtimeReadsEnabled && !privateWs ? '未知 · 未读取' : privateWs?.listener_alive ? 'alive' : 'stopped'} tone={!runtimeReadsEnabled && !privateWs ? 'unknown' : privateWs?.listener_alive ? 'pass' : 'blocked'} />
          <RuntimeFact label="Ledger reconciliation" value={ledgerReconciliation?.status ?? 'not_observed'} tone={ledgerReconciliation?.status === 'reconciled' ? 'pass' : 'blocked'} />
        </div>
        </div>
      </details>

      <div className="tv-console-section">
        <div className="tv-section-title"><span>策略线</span><small>仅冻结身份可选</small></div>
        <div className="tv-strategy-lines">
          {strategyLines.map((item) => (
            <button
              key={item.strategy_id}
              type="button"
              className={item.demo_selectable ? `selectable ${selectedStrategyId === item.strategy_id ? 'active' : ''}` : 'locked'}
              disabled={!runtimeReadsEnabled || !item.demo_selectable || isActive}
              title={item.demo_selectable
                ? `${strategyAdapterLabel(item.adapter_fidelity)} · ${strategyCapabilityText({canonicalSignalAvailable: item.canonical_signal_available, demoSelectable: item.demo_selectable, adapterFidelity: item.adapter_fidelity})} · 点击选择策略线`
                : `${strategyStatusLabel(item.demo_blocker || (item.adapter_fidelity === 'identity_only' ? 'identity_only_no_demo_execution_ledger' : 'blocked'))}（诊断：${item.demo_blocker || item.adapter_fidelity || 'blocked'}）`}
              aria-pressed={selectedStrategyId === item.strategy_id}
              onClick={() => onStrategyChange(item.strategy_id)}
            >
              <span>{strategyPresentationName(item.display_name, item.strategy_id)}</span>
              <small>{item.demo_selectable
                ? selectedStrategyId === item.strategy_id ? '已选择' : 'Demo 可执行'
                : `${strategyStatusLabel(item.demo_blocker || (item.adapter_fidelity === 'identity_only' ? 'identity_only_no_demo_execution_ledger' : 'blocked'))} · Demo 不可选`}</small>
            </button>
          ))}
        </div>
        <label className="tv-field">
          <span>冻结候选 · {strategyPresentationName(selected?.display_name, selected?.strategy_id) || '等待策略目录'}</span>
          <select value={selected?.candidate_id ?? ''} onChange={(event: {target: {value: string}}) => onCandidateChange(event.target.value)} disabled={!runtimeReadsEnabled || isActive}>
            {!lineCandidates.length ? <option value="">{!runtimeReadsEnabled ? '候选目录未加载 · 当前只读' : '等待策略目录'}</option> : null}
            {lineCandidates.map((item, index) => <option key={item.candidate_id} value={item.candidate_id}>#{index + 1} · {strategyPresentationName(item.display_name, item.strategy_id)} · {strategyVariantLabel(item.candidate_id, item.strategy_id)} · {shortCandidate(item.candidate_id)}</option>)}
          </select>
        </label>
        <div className="tv-identity-note">
          <strong>{selected?.strategy_version ?? '等待目录'}</strong>
          <code>{selected?.params_hash?.slice(0, 16) ?? '—'}</code>
        </div>
      </div>

      <div className="tv-console-section">
        <div className="tv-section-title"><span>授权限额</span><small>服务端不可放宽</small></div>
        <div className="tv-limit-grid">
          <div><span>环境</span><strong>OKX Demo</strong></div>
          <div><span>合约</span><strong>BTC-USDT-SWAP</strong></div>
          <div><span>保证金</span><strong>逐仓</strong></div>
          <div><span>单次</span><strong>{limitPerOrder}（服务端）</strong></div>
          <div><span>最大净仓</span><strong>{limitNet}（服务端）</strong></div>
          <div><span>单笔名义</span><strong>{limitNotional}（服务端）</strong></div>
        </div>
        <p className="tv-console-warning">P0 服务端保护与 dead-man 仅展示权威快照；前端不硬编码保护数值，也不会解锁实盘。</p>
      </div>

      <div className="tv-console-section tv-account-strip">
        <div><span>Demo 权益</span><strong>{accountView.usable ? `${formatNumber(exchange?.balance?.equity_usdt, 2)} USDT` : '未知'}</strong></div>
        <div><span>当前仓位</span><strong>{authorityPosition}</strong></div>
        <div><span>Mark</span><strong>{accountView.usable ? formatNumber(exchange?.mark?.mark_price, 1) : '未知'}</strong></div>
        <div><span>已实现净收益（权威账本）</span><strong>{authoritativeRealizedNetPnl === null ? 'unavailable · 等待权威账本投影' : `${authoritativeRealizedNetPnl.toFixed(4)} USDT`}</strong></div>
        <div><span>未实现（Mark-to-market）</span><strong>{markToMarketPnl === null ? 'unavailable' : `${markToMarketPnl.toFixed(4)} USDT`}</strong></div>
      </div>

      <div className="tv-console-section tv-runtime-health" data-testid="btc-runtime-health">
        <div className="tv-section-title"><span>运行健康</span><small>只读状态，不自动解锁</small></div>
        <div className="tv-runtime-health-grid">
          <RuntimeFact label="Run ID" value={runtime?.run_id || (runtimeReadsEnabled ? '未启动' : '未知 · 未读取')} mono />
          <RuntimeFact label="开仓状态" value={runtime?.opening_allowed ? '允许（Demo 限额内）' : '禁止开仓'} tone={runtime?.opening_allowed ? 'pass' : 'blocked'} />
          <RuntimeFact label="Heartbeat" value={formatTime(runtime?.last_heartbeat_utc)} tone={runtime?.last_heartbeat_utc ? 'pass' : 'unknown'} />
          <RuntimeFact label="最近对账" value={formatTime(runtime?.last_reconciled_at_utc)} tone={runtime?.last_reconciled_at_utc ? 'pass' : 'unknown'} />
          <RuntimeFact label="最近 completed bar" value={formatTime(runtime?.last_processed_bar_close_utc)} tone={runtime?.last_processed_bar_close_utc ? 'pass' : 'unknown'} />
          <RuntimeFact label="私有 WS / gapfill" value="Promotion 待验证" />
          <RuntimeFact label="Depth fill mapping" value="Promotion 待积累" />
          <RuntimeFact label="账户快照成交条数" value={accountView.fills} tone="unknown" />
        </div>
        {runtime?.last_error ? (
          <details className="tv-runtime-diagnostics">
            <summary>Runtime 技术诊断</summary>
            <strong>{runtimeLastErrorView.message}</strong>
            <code title={runtime.last_error}>{runtimeLastErrorView.code}</code>
          </details>
        ) : null}
      </div>

      <div className="tv-console-section tv-operational-readiness" data-testid="btc-demo-start-gates">
        <div className="tv-section-title"><span>Demo 启动条件</span><small>只决定受限模拟盘</small></div>
        <ReadinessItem label="冻结策略可执行" ready={runtimeReadsEnabled && Boolean(selected?.demo_selectable)} waiting={catalogLoading} detail={!runtimeReadsEnabled ? '当前模式未加载 Demo 候选' : catalogLoading ? '正在读取冻结策略目录' : selected?.demo_selectable ? '策略身份已冻结且目录允许 Demo' : '未选择可执行策略'} />
        <ReadinessItem label="OKX Demo 环境" ready={runtimeReadsEnabled && demoEnvironmentReady} waiting={catalogLoading} detail={!runtimeReadsEnabled ? '未读取 Demo 环境状态' : catalogLoading ? '正在核验 Demo 环境与合约' : demoEnvironmentReady ? 'BTC-USDT-SWAP · isolated · Demo only' : '环境或合约不匹配'} />
        <ReadinessItem
          label="后端统一 Runtime 控制契约"
          ready={runtimeReadsEnabled && operatorContractReady}
          waiting={runtimeStatusLoading}
          detail={!runtimeReadsEnabled ? '当前模式未开放运行控制' : runtimeStatusLoading
            ? '正在读取后端状态；前端不会提前推导启动权限'
            : operatorContractReady
              ? '生命周期、故障分类与允许操作均由后端发布'
              : '控制契约缺失；保持 fail-closed'}
        />
        <ReadinessItem
          label="completed 1h 信号（图表 / 历史提示）"
          ready={runtimeSignalReady}
          waiting={runtimeSignalLoading}
          detail={runtimeSignalLoading
            ? '正在读取图表与回测数据；不参与 Demo 启动判定'
            : runtimeSignalReady
              ? '图表 freshness 合同通过；仅用于图表与回测'
              : `图表 freshness 未通过；仅影响图表与回测，不影响 Demo 启动（${runtimeSignalBlocker || 'OKX Native 后端负责最终预检'}）`}
        />
        <ReadinessItem label="操作员限额确认" ready={allConfirmed} waiting={!allConfirmed} detail={allConfirmed ? 'Demo、自动订单、硬限额、cancel-only、专用账户与 P0 保护已确认' : '完成下方六项确认并输入确认文本'} />
      </div>

      <div className="tv-console-section tv-operational-readiness" data-testid="btc-demo-recovery-flow">
        <div className="tv-section-title"><span>权威重新预检链</span><small>复用现有安全 /start；串行、fail-closed</small></div>
        {recoveryStages.length ? recoveryStages.map((item) => (
          <ReadinessItem
            key={item.key}
            label={item.label}
            ready={item.state === 'ready'}
            waiting={item.state === 'waiting'}
            detail={item.detail}
          />
        )) : <ReadinessItem label="统一控制契约" ready={false} waiting={runtimeStatusLoading} detail="等待后端发布预检步骤；前端不会自行拼装通过条件" />}
      </div>

      <div className="tv-console-section tv-operational-readiness tv-promotion-readiness" data-testid="btc-promotion-observation-gates">
        <div className="tv-section-title"><span>未来 Promotion 条件</span><small>不阻止 Demo 启动</small></div>
        <p className="tv-promotion-note">这些项目由 Demo 自然运行、长期观察或人工审批产生，只影响未来晋级，不参与当前“启动 Demo 策略”按钮判定。</p>
        {promotionReadinessLoading ? (
          <ReadinessItem label="Promotion 证据" ready={false} waiting detail="正在读取 current-HEAD promotion evidence；不影响 Demo 启动" />
        ) : promotionItems.length ? promotionItems.map((item) => (
          <ReadinessItem key={item.key} label={item.label} ready={false} waiting detail={item.detail} />
        )) : <ReadinessItem label="Promotion 证据" ready={false} waiting detail="当前未报告待积累项；仍需独立 gate 与人工授权" />}
      </div>

      <div className="tv-console-section tv-confirm-box" data-testid="btc-demo-start-confirmation">
          <div className="tv-section-title"><span>启动确认</span><small>不会自动启动</small></div>
          <label><input data-testid="btc-demo-confirm-demo" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.demo} onChange={() => toggle('demo')} /><span>只连接 OKX Demo，禁止实盘</span></label>
          <label><input data-testid="btc-demo-confirm-auto-orders" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.autoOrders} onChange={() => toggle('autoOrders')} /><span>允许策略经 Risk 与 OMS 自动下单/平仓</span></label>
           <label><input data-testid="btc-demo-confirm-limits" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.limits} onChange={() => toggle('limits')} /><span>接受服务端返回的 Demo 限额（未提供时保持阻塞）</span></label>
          <label><input data-testid="btc-demo-confirm-cancel-only" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.cancelOnly} onChange={() => toggle('cancelOnly')} /><span>异常立即停止开仓并进入 cancel-only</span></label>
          <label><input data-testid="btc-demo-confirm-dedicated-account" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.dedicatedAccount} onChange={() => toggle('dedicatedAccount')} /><span>确认这是专用 Demo 账户，不与其他 worker 共用</span></label>
          <label><input data-testid="btc-demo-confirm-p0-protection" type="checkbox" disabled={!runtimeReadsEnabled} checked={checks.p0Protection} onChange={() => toggle('p0Protection')} /><span>确认 P0 服务端保护与 dead-man；只保护 Demo，不会解锁实盘</span></label>
          <label className="tv-field">
            <span>输入 {catalog?.confirmation_text ?? 'BTC DEMO'} 确认</span>
            <input data-testid="btc-demo-confirmation-text" disabled={!runtimeReadsEnabled} value={confirmationText} onChange={(event: {target: {value: string}}) => { setStartValidationMessage(''); setConfirmationText(event.target.value); }} placeholder="BTC DEMO" autoComplete="off" />
          </label>
          <div className="tv-console-message" data-testid="btc-demo-confirmation-readiness" aria-live="polite">
            <strong>{allConfirmed ? '人工确认已完成' : `还需 ${missingConfirmations.length} 项确认`}</strong>
            <span>{allConfirmed ? '按钮现已可用；点击后仍由后端执行完整权威预检。' : missingConfirmations.join('；')}</span>
          </div>
      </div>

       {startValidationMessage ? (
         <div className="tv-console-message" data-testid="btc-demo-start-confirmation-feedback" role="alert">
           <strong>{startValidationMessage.split('：')[0]}</strong>
           <span>{startValidationMessage.includes('：') ? startValidationMessage.slice(startValidationMessage.indexOf('：') + 1) : startValidationMessage}</span>
         </div>
       ) : null}

      {controlContractBlockers.length ? (
        <div className="tv-console-message" data-testid="btc-demo-start-blocker">
          <strong>当前暂不能启动</strong>
          <span>{operatorController.operation?.state === 'running' || operatorController.operation?.state === 'queued' ? '上一次操作仍在处理中，请等待结果。' : '请先处理下方预检结果并确认上次操作；系统不会自动重试。'}</span>
          <details><summary>技术诊断</summary><code>{controlContractBlockers.join('；')}</code></details>
        </div>
      ) : null}
      {statusError && transportStatusError ? (
        <div className="tv-runtime-error" data-testid="btc-demo-transport-error">
          <strong>{statusErrorLabel}</strong>
          <code title={statusError}>诊断：{statusErrorCode}</code>
          <span>未自动重试订单或 /start；请在网络恢复后重新预检。</span>
        </div>
      ) : null}

       <div className="tv-console-actions" data-testid="btc-demo-operator-v2-actions">
         {OPERATOR_ACTIONS_FOR_UI.map((action) => <span key={action} id={actionHelpId(action)} className="sr-only">{actionReasonText(action)}</span>)}
         <button type="button" className="tv-primary-action" aria-describedby={actionHelpId('authoritative_preflight_start')} disabled={!runtimeStartPathAvailable || !allConfirmed || !catalog || !selected || operatorController.isActionBusy('authoritative_preflight_start')} onClick={() => void start()}>
           {operatorController.isActionBusy('authoritative_preflight_start') ? '正在执行权威预检…' : '权威预检并启动'}
         </button>
         <button type="button" className="tv-secondary-action" aria-describedby={actionHelpId('refresh_account_snapshot')} disabled={operatorController.isActionBusy('refresh_account_snapshot') || !actionAllowed('refresh_account_snapshot')} onClick={() => { setRecoveryAttempted(false); void operatorController.dispatch('refresh_account_snapshot'); }}>
           {operatorController.isActionBusy('refresh_account_snapshot') ? '正在刷新…' : '刷新账户快照'}
         </button>
         <button type="button" className="tv-stop-action" aria-describedby={actionHelpId('stop_keep_position')} disabled={operatorController.isActionBusy('stop_keep_position') || !actionAllowed('stop_keep_position')} onClick={() => void operatorController.dispatch('stop_keep_position', {confirmation_text: 'STOP KEEP POSITION'})}>
           {operatorController.isActionBusy('stop_keep_position') ? '正在停止…' : '停止策略（保留仓位）'}
         </button>
         <button type="button" className="tv-flatten-action" data-testid="btc-demo-stop-and-flatten" aria-describedby={actionHelpId('stop_and_flatten')} disabled={operatorController.isActionBusy('stop_and_flatten') || !actionAllowed('stop_and_flatten')} onClick={() => { setFlattenConfirmation(''); setFlattenConfirmOpen(true); }} ref={flattenTriggerRef}>
           {operatorController.isActionBusy('stop_and_flatten') ? '正在危险减仓…' : '危险：停止并减仓'}
         </button>
         <button type="button" className="tv-emergency-action" aria-describedby={actionHelpId('enter_cancel_only')} disabled={operatorController.isActionBusy('enter_cancel_only') || !actionAllowed('enter_cancel_only')} onClick={() => void operatorController.dispatch('enter_cancel_only', {confirmation_text: 'CANCEL ONLY'})}>
           {operatorController.isActionBusy('enter_cancel_only') ? '正在冻结…' : '进入 Cancel-only'}
         </button>
         <button type="button" className="tv-emergency-action" data-testid="btc-demo-emergency-reduce-only-exit" aria-describedby={actionHelpId('emergency_reduce_only_exit')} disabled={operatorController.isActionBusy('emergency_reduce_only_exit') || !actionAllowed('emergency_reduce_only_exit')} onClick={() => { setEmergencyConfirmation(''); setEmergencyConfirmOpen(true); }} ref={emergencyTriggerRef}>
           {operatorController.isActionBusy('emergency_reduce_only_exit') ? '正在危险减仓…' : '危险：紧急减仓退出'}
         </button>
         <button
           type="button"
           className="tv-emergency-action"
           data-testid="btc-demo-guardian-acknowledge"
           aria-describedby={actionHelpId('acknowledge_guardian_trip')}
           disabled={operatorController.isActionBusy('acknowledge_guardian_trip') || !actionAllowed('acknowledge_guardian_trip')}
           onClick={() => {
             if (window.confirm('确认已阅读 Guardian 风险并记录人工确认？')) {
               void operatorController.dispatch('acknowledge_guardian_trip', {acknowledgement_id: `guardian-ack-${Date.now()}`, confirmation_text: 'ACK GUARDIAN'});
             }
           }}
         >
           {operatorController.isActionBusy('acknowledge_guardian_trip') ? '正在确认 Guardian…' : '确认 Guardian 风险'}
         </button>
         <button
           type="button"
           className="tv-emergency-action"
           data-testid="btc-demo-guardian-recover"
           aria-describedby={actionHelpId('recover_guardian_after_fresh_preflight')}
           disabled={operatorController.isActionBusy('recover_guardian_after_fresh_preflight') || !actionAllowed('recover_guardian_after_fresh_preflight')}
           onClick={() => {
             if (window.confirm('确认已完成本次新鲜权威预检，并按后端事实恢复 Guardian？')) {
               void operatorController.dispatch('recover_guardian_after_fresh_preflight', {confirmation_text: 'RECOVER GUARDIAN'});
             }
           }}
         >
           {operatorController.isActionBusy('recover_guardian_after_fresh_preflight') ? '正在恢复 Guardian…' : '恢复 Guardian（新鲜预检）'}
         </button>
       {(operatorController.operation || operatorController.operationUnknownAction || operatorController.operationRejectedAction) ? (
         <button
             type="button"
             className="tv-secondary-action"
             data-testid="btc-demo-operator-v2-acknowledge-next"
             disabled={!runtimeReadsEnabled || acknowledgementBusy || Boolean(operatorController.operation && (operatorController.operation.state === 'queued' || operatorController.operation.state === 'running'))}
             onClick={() => { if (acknowledgementAction) void operatorController.acknowledgeNewOperation(acknowledgementAction); }}
           >
             {acknowledgementBusy
               ? '正在确认后端终态…'
               : operatorController.operationUnknownAction
               ? '确认未知结果后新建操作'
               : operatorController.operationRejectedAction
                 ? '确认后端拒绝并新建操作'
                 : '确认后端终态并新建下一次操作'}
           </button>
       ) : null}
       </div>

       {operatorController.operation && operationIsTerminal && !operatorController.operation.acknowledged ? (
         <div className={operatorController.operation.state === 'succeeded' ? 'tv-console-message' : 'tv-runtime-error'} data-testid="btc-demo-operator-terminal-operation">
           <strong>上次操作已结束，需后端持久确认</strong>
           <details><summary>技术诊断</summary><code>state={operatorController.operation.state} · phase={operatorController.operation.phase} · blockers={operatorController.operation.blocker_codes.join(',') || 'none'}</code></details>
           <span>请确认本次结果后再发起新操作；已经获得后端授权的保护动作仍可独立使用。</span>
         </div>
       ) : null}

       {flattenConfirmOpen ? (
         <dialog ref={flattenDialogRef} open className="tv-flatten-confirm" aria-modal="true" aria-labelledby="btc-demo-flatten-title" aria-describedby="btc-demo-flatten-description" data-testid="btc-demo-flatten-confirm" onKeyDown={(event: KeyboardEvent) => { if (event.key === 'Escape') setFlattenConfirmOpen(false); }}>
          <strong id="btc-demo-flatten-title">确认危险停止并减仓</strong>
          <p id="btc-demo-flatten-description">将停止策略生成新订单，并仅按后端重新采集的权威仓位执行一次等量 reduce-only 退出。当前待减仓位：{authorityPosition}；前端数量不会被信任。</p>
          <label className="tv-field">
            <span>输入 STOP AND FLATTEN 确认</span>
            <input ref={flattenInputRef} value={flattenConfirmation} onChange={(event: {target: {value: string}}) => setFlattenConfirmation(event.target.value)} autoComplete="off" aria-describedby="btc-demo-flatten-description" />
          </label>
          <div className="tv-flatten-confirm-actions">
            <button type="button" className="tv-secondary-action" onClick={() => setFlattenConfirmOpen(false)}>取消</button>
            <button
              type="button"
              className="tv-flatten-action"
              disabled={flattenConfirmation !== 'STOP AND FLATTEN' || operatorController.isActionBusy('stop_and_flatten')}
              onClick={async () => {
                setFlattenConfirmOpen(false);
                await operatorController.dispatch('stop_and_flatten', {confirmation_text: 'STOP AND FLATTEN'});
              }}
            >
              确认危险停止并减仓
            </button>
          </div>
        </dialog>
       ) : null}

       {emergencyConfirmOpen ? (
         <dialog ref={emergencyDialogRef} open className="tv-flatten-confirm" role="dialog" aria-modal="true" aria-labelledby="btc-demo-emergency-title" aria-describedby="btc-demo-emergency-description" data-testid="btc-demo-emergency-confirm" onKeyDown={(event: KeyboardEvent) => { if (event.key === 'Escape') setEmergencyConfirmOpen(false); }}>
           <strong id="btc-demo-emergency-title">确认危险紧急减仓</strong>
           <p id="btc-demo-emergency-description">仅在服务端 V2 明确授权时执行；前端不计算数量、不改变风险方向。</p>
           <label className="tv-field">
             <span>输入 EMERGENCY EXIT 确认</span>
             <input ref={emergencyInputRef} value={emergencyConfirmation} onChange={(event: {target: {value: string}}) => setEmergencyConfirmation(event.target.value)} autoComplete="off" aria-describedby="btc-demo-emergency-description" />
           </label>
           <div className="tv-flatten-confirm-actions">
             <button type="button" className="tv-secondary-action" onClick={() => setEmergencyConfirmOpen(false)}>取消</button>
             <button type="button" className="tv-emergency-action" disabled={emergencyConfirmation !== 'EMERGENCY EXIT' || operatorController.isActionBusy('emergency_reduce_only_exit')} onClick={async () => { setEmergencyConfirmOpen(false); await operatorController.dispatch('emergency_reduce_only_exit', {confirmation_text: 'EMERGENCY EXIT'}); }}>确认危险紧急减仓</button>
           </div>
         </dialog>
       ) : null}

      <p className="tv-console-warning">“刷新账户快照”只更新账户和账本，不启动账户实时连接，也不解除仅撤单状态；恢复运行仍需人工重新预检。</p>
      <p className="tv-console-warning">“停止策略（保留仓位）”不会平仓；减仓退出是独立危险动作，必须二次确认，且只允许减少现有仓位。实盘、转账、提现和权限升级始终禁用。</p>
      {!runtimeSignalLoading && !runtimeSignalReady ? <div className="tv-console-message">图表 / 历史数据提示：{runtimeSignalBlocker || 'freshness 未通过'}；仅影响图表与回测，不影响 Demo 启动，OKX Native 后端负责最终预检。</div> : null}
      {startFeedback ? (
        <div className={startFeedback.kind === 'failed' ? 'tv-runtime-error' : 'tv-console-message'}
          data-testid={startFeedback.kind === 'failed' ? 'btc-demo-recovery-failure' : 'btc-demo-recovery-status'}
          aria-live="polite" role="status">
          <strong>{startFeedback.title}</strong>
          <p>{startFeedback.detail}</p>
          <span>{startFeedback.guidance}</span>
        </div>
      ) : null}
      {message && (!startFeedback || !isStartReceiptMessage(message)) ? <div className="tv-console-message" aria-live="polite" role="status">{message}</div> : null}
      {runtime?.blockers?.length ? (
        <details className="tv-blocker-list">
          <summary>技术诊断代码（{runtime.blockers.length}）</summary>
          {runtime.blockers.slice(0, 5).map((item) => <code key={item}>{runtimeErrorText(item, transientPrivateWsProbe)}</code>)}
        </details>
      ) : null}
    </aside>
  );
}

function formatNumber(value: string | undefined, digits: number): string {
  const number = finiteAccountNumber(value);
  return number !== null ? number.toLocaleString('zh-CN', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '未知';
}

function RuntimeFact({label, value, tone = 'unknown', mono = false}: {label: string; value: string; tone?: 'pass' | 'blocked' | 'unknown'; mono?: boolean}) {
  return <div className={`tv-runtime-fact ${tone}`}><span>{label}</span><strong className={mono ? 'mono' : ''} title={value}>{value}</strong></div>;
}

function ReadinessItem({label, ready, detail, waiting = false}: {label: string; ready: boolean; detail: string; waiting?: boolean; key?: string}) {
  const state = ready ? 'ready' : waiting ? 'waiting' : 'blocked';
  return <div className={state}><i /><span>{label}</span><strong>{ready ? 'PASS' : waiting ? 'WAITING' : 'BLOCKED'}</strong><small>{detail}</small></div>;
}

function promotionReadinessItem(blocker: string): {key: string; label: string; detail: string} {
  if (blocker.includes('historical_timestamp_aligned_depth_fill_mapping_missing') || blocker.includes('depth_fill_mapping')) {
    return {key: blocker, label: '历史时点盘口 → 成交映射', detail: '等待时间对齐的 L2 与 fill 样本；不作为 Demo 启动前置'};
  }
  if (blocker.includes('natural_strategy_runtime_non_flat_fill_sample_missing')) {
    return {key: blocker, label: '自然策略非空成交样本', detail: '由 Demo 运行等待真实策略信号自然产生'};
  }
  if (blocker.includes('funding_cashflow_not_observed_in_demo_runtime') || blocker.includes('cost_and_funding_validation_missing')) {
    return {key: blocker, label: 'Demo Funding 与成本观察', detail: '等待持仓跨 funding 时点后形成现金流证据'};
  }
  if (blocker.includes('private_ws_runtime_reconciliation_observation_incomplete')) {
    return {key: blocker, label: '私有 WS 对账观察', detail: '等待 reconnect、gapfill 与 reconciliation 运行样本'};
  }
  if (blocker.includes('30_60_day_observation_window_incomplete')) {
    return {key: blocker, label: '30 / 60 天观察窗口', detail: '仅影响未来 Promotion，不影响受限 Demo 启动'};
  }
  if (blocker.includes('manual_promotion_approval_missing')) {
    return {key: blocker, label: '人工 Promotion 审批', detail: '必须由授权人员签署，系统不得代签'};
  }
  if (blocker.includes('current_head_mismatch') || blocker.includes('dirty_snapshot_mismatch')) {
    return {key: blocker, label: 'Promotion artifact freshness', detail: blocker};
  }
  return {key: blocker, label: 'Promotion 待积累证据', detail: blocker};
}

function formatTime(value: string | undefined): string {
  if (!value) return '未记录';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', {hour12: false});
}

function yesNo(value: boolean | undefined): string {
  return value ? 'yes' : 'no';
}

function shortCandidate(value: string): string {
  return value.length > 26 ? `${value.slice(0, 16)}…${value.slice(-7)}` : value;
}
