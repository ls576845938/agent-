import {useEffect, useMemo, useRef, useState} from 'react';

import {apiGet, apiPost} from '../../lib/api';
import type {DemoCatalog, DemoRuntimeStatus, DemoStartAttempt, LocalKlineResponse} from './demo-types';
import {
  applyOperatorAttemptOverlays,
  canAcknowledgeOperatorAttempt,
  classifyOperatorAttemptError,
  readFailureOverlay,
} from './operator-attempt-state';
import type {OperatorAttemptOverlay} from './operator-attempt-state';

export const OPERATOR_CONTRACT_SCHEMA = 'btc_demo_operator_contract_v2' as const;
export const OPERATION_READ_MODEL_SCHEMA = 'btc_demo_operation_read_model_v2' as const;

export const OPERATOR_ACTIONS = [
  'authoritative_preflight_start',
  'refresh_account_snapshot',
  'stop_keep_position',
  'stop_and_flatten',
  'enter_cancel_only',
  'emergency_reduce_only_exit',
  'acknowledge_guardian_trip',
  'recover_guardian_after_fresh_preflight',
] as const;

export type OperatorAction = typeof OPERATOR_ACTIONS[number];
export type OperatorOperationState = 'queued' | 'running' | 'succeeded' | 'failed' | 'blocked' | 'interrupted' | 'timed_out';

export type OperatorActionProjection = {
  action: OperatorAction;
  allowed: boolean;
  execution_permission: boolean;
  blocker_codes: string[];
  reason_codes: string[];
  source: string;
  runtime_identity: string;
  state_revision: number | null;
  state_digest: string;
  as_of_utc: string;
};

export type OperatorOperationProjection = {
  schema_version: typeof OPERATION_READ_MODEL_SCHEMA;
  operation_id: string;
  action: OperatorAction;
  request_digest: string;
  state: OperatorOperationState;
  phase: string;
  blocker_codes: string[];
  created_at_utc: string;
  updated_at_utc: string;
  state_revision: number;
  result_present: boolean;
  retryable: boolean;
  replayed: boolean;
  idempotent_replay: boolean;
  acknowledged: boolean;
  acknowledged_at_utc: string | null;
  safety_flags: SafetyFlags;
  start_attempt: DemoStartAttempt | null;
};

export type SafetyFlags = {
  promotion_eligible: false;
  paper: false;
  live: false;
  private: false;
  order: false;
  real_order: false;
  transfer: false;
  withdraw: false;
};

export type GuardianReadModel = {
  schema_version?: string;
  persistence_state?: 'missing' | 'corrupt_or_unavailable' | 'tripped' | 'acknowledged' | 'cleared' | string;
  status?: 'blocked' | 'clear' | string;
  tripped?: boolean;
  acknowledged?: boolean;
  reason_codes: string[];
  generation: number;
  state_revision?: number;
  evidence_identity?: string;
  evidence_digest?: string;
  observation_digest?: string;
  last_observation_identity?: string;
  last_observation_digest?: string;
  last_observation_time_utc?: string | null;
  position?: {nonflat?: boolean; contracts?: string; side?: string};
  exposure?: {value?: string; mark_price?: string; unit?: string};
  pnl?: {realized?: string; unrealized?: string; unit?: string};
  drawdown?: {value?: string | null; unit?: string; provenance?: string};
  next_safe_action?: string;
};

export type OperatorContractProjection = {
  valid: boolean;
  schema_version: typeof OPERATOR_CONTRACT_SCHEMA;
  source: string;
  runtime_identity: string;
  source_head: string;
  state_revision: number | null;
  state_digest: string;
  as_of_utc: string;
  actions: OperatorActionProjection[];
  action_map: Record<OperatorAction, OperatorActionProjection>;
  operation: OperatorOperationProjection | null;
  safety_flags: SafetyFlags;
  blockers: string[];
  guardian?: GuardianReadModel;
  start_attempt?: DemoStartAttempt;
};

export type DemoOperatorController = {
  catalog: DemoCatalog | null;
  status: DemoRuntimeStatus | null;
  statusError: string;
  klines: LocalKlineResponse | null;
  contract: OperatorContractProjection;
  operation: OperatorOperationProjection | null;
  loading: boolean;
  bootstrapFailed: boolean;
  bootstrapError: string;
  busyActions: ReadonlySet<OperatorAction>;
  isActionBusy: (action: OperatorAction) => boolean;
  operationUnknownAction: OperatorAction | '';
  operationRejectedAction: OperatorAction | '';
  message: string;
  refresh: () => Promise<void>;
  dispatch: (action: OperatorAction, payload?: Record<string, unknown>) => Promise<void>;
  acknowledgeNewOperation: (action: OperatorAction) => Promise<boolean>;
};

const SAFETY_FLAG_NAMES: Array<keyof SafetyFlags> = [
  'promotion_eligible', 'paper', 'live', 'private', 'order', 'real_order', 'transfer', 'withdraw',
];
const OPERATION_STATES: OperatorOperationState[] = ['queued', 'running', 'succeeded', 'failed', 'blocked', 'interrupted', 'timed_out'];
const OPERATOR_CONTRACT_PATH = '/api/research/btc/demo-paper/operator-v2/contract';
const OPERATOR_OPERATION_PATH = '/api/research/btc/demo-paper/operator-v2/operations';
const OPERATOR_ACTION_PATH = '/api/research/btc/demo-paper/operator-v2/actions';
const DEMO_CATALOG_PATH = '/api/research/btc/demo-paper/catalog';
const DEMO_STATUS_PATH = '/api/research/btc/demo-paper/status';
const DEMO_KLINES_PATH = '/api/research/btc/demo-paper/klines?limit=2000';
const IDEMPOTENCY_PREFIX = 'btc-demo-operator-v2-idempotency:';
const SOURCE_HEAD = /^[0-9a-f]{40}$/;
const STATE_DIGEST = /^[0-9a-f]{64}$/;
const CODE = /^[a-z0-9][a-z0-9_.-]*$/;

function stableCodes(value: unknown): string[] {
  const values = Array.isArray(value) ? value : typeof value === 'string' ? [value] : [];
  return [...new Set(values
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter((item) => CODE.test(item)))].sort();
}

function strictCodes(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  if (value.some((item) => typeof item !== 'string' || !CODE.test(item))) return null;
  return stableCodes(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isUtc(value: unknown): value is string {
  if (typeof value !== 'string' || !value.trim()) return false;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && /(?:Z|[+-]\d\d:\d\d)$/.test(value);
}

function decodeStartAttempt(value: unknown): DemoStartAttempt | null {
  if (!isRecord(value) || Object.keys(value).length === 0) return null;
  const requiredStrings = [
    'parent_operation_id', 'inner_operation_id', 'attempt_id', 'runtime_identity',
    'source_head', 'effective_policy_digest', 'risk_profile', 'expected_leverage',
    'account_identity_hash', 'created_at_utc', 'updated_at_utc',
  ];
  if (requiredStrings.some((name) => typeof value[name] !== 'string' || !(value[name] as string).trim())
    || !SOURCE_HEAD.test(value.source_head as string)
    || !STATE_DIGEST.test(value.effective_policy_digest as string)
    || !STATE_DIGEST.test(value.account_identity_hash as string)
    || !isUtc(value.created_at_utc) || !isUtc(value.updated_at_utc)
    || typeof value.current_attempt !== 'boolean'
    || typeof value.historical !== 'boolean'
    || strictCodes(value.historical_reason_codes) === null) return null;
  return {
    schema_version: typeof value.schema_version === 'string' ? value.schema_version : undefined,
    parent_operation_id: value.parent_operation_id as string,
    inner_operation_id: value.inner_operation_id as string,
    attempt_id: value.attempt_id as string,
    runtime_identity: value.runtime_identity as string,
    source_head: value.source_head as string,
    effective_policy_digest: value.effective_policy_digest as string,
    risk_profile: value.risk_profile as string,
    expected_leverage: value.expected_leverage as string,
    account_identity_hash: value.account_identity_hash as string,
    created_at_utc: value.created_at_utc as string,
    updated_at_utc: value.updated_at_utc as string,
    state: typeof value.state === 'string' ? value.state : undefined,
    phase: typeof value.phase === 'string' ? value.phase : undefined,
    current_attempt: value.current_attempt as boolean,
    historical: value.historical as boolean,
    historical_reason_codes: strictCodes(value.historical_reason_codes) as string[],
    actual_long_leverage: typeof value.actual_long_leverage === 'string' ? value.actual_long_leverage : null,
    actual_short_leverage: typeof value.actual_short_leverage === 'string' ? value.actual_short_leverage : null,
  };
}

function falseSafetyFlags(value: unknown): SafetyFlags | null {
  if (!isRecord(value)) return null;
  const flags = {} as Record<keyof SafetyFlags, false>;
  for (const name of SAFETY_FLAG_NAMES) {
    if (value[name] !== false) return null;
    flags[name] = false;
  }
  return flags as SafetyFlags;
}

function emptyAction(action: OperatorAction, blockers: string[]): OperatorActionProjection {
  return {
    action,
    allowed: false,
    execution_permission: false,
    blocker_codes: stableCodes(blockers),
    reason_codes: ['state_unavailable'],
    source: '',
    runtime_identity: '',
    state_revision: null,
    state_digest: '',
    as_of_utc: '',
  };
}

export function invalidContract(blockers: string[] = ['operator_v2_contract_invalid']): OperatorContractProjection {
  const actions = OPERATOR_ACTIONS.map((action) => emptyAction(action, blockers));
  return {
    valid: false,
    schema_version: OPERATOR_CONTRACT_SCHEMA,
    source: '',
    runtime_identity: '',
    source_head: '',
    state_revision: null,
    state_digest: '',
    as_of_utc: '',
    actions,
    action_map: Object.fromEntries(actions.map((action) => [action.action, action])) as Record<OperatorAction, OperatorActionProjection>,
    operation: null,
    safety_flags: {
      promotion_eligible: false, paper: false, live: false, private: false,
      order: false, real_order: false, transfer: false, withdraw: false,
    },
    blockers: stableCodes(blockers),
    guardian: {
      persistence_state: 'missing',
      status: 'blocked',
      tripped: false,
      acknowledged: false,
      reason_codes: stableCodes(blockers),
      generation: 0,
      next_safe_action: 'recover_guardian_after_fresh_preflight',
    },
  };
}

/** Replace any previously valid authorization with an all-denied projection. */
export function revokeOperatorContract(blocker = 'operator_v2_contract_unavailable'): OperatorContractProjection {
  return invalidContract([blocker]);
}

export function decodeOperatorOperation(value: unknown): OperatorOperationProjection | null {
  if (!isRecord(value)
    || value.schema_version !== OPERATION_READ_MODEL_SCHEMA
    || typeof value.operation_id !== 'string' || !value.operation_id.trim()
    || typeof value.action !== 'string' || !OPERATOR_ACTIONS.includes(value.action as OperatorAction)
    || typeof value.request_digest !== 'string' || !STATE_DIGEST.test(value.request_digest)
    || typeof value.state !== 'string' || !OPERATION_STATES.includes(value.state as OperatorOperationState)
    || typeof value.phase !== 'string'
    || !isUtc(value.created_at_utc) || !isUtc(value.updated_at_utc)
    || !Number.isInteger(value.state_revision) || (value.state_revision as number) < 0
    || strictCodes(value.blocker_codes) === null
    || typeof value.result_present !== 'boolean'
    || typeof value.retryable !== 'boolean'
    || typeof value.replayed !== 'boolean'
    || typeof value.idempotent_replay !== 'boolean'
    || typeof value.acknowledged !== 'boolean'
    || !(value.acknowledged_at_utc === null || isUtc(value.acknowledged_at_utc))
    || (value.acknowledged === true) !== isUtc(value.acknowledged_at_utc)) {
    return null;
  }
  const safety_flags = falseSafetyFlags(value.safety_flags);
  if (!safety_flags) return null;
  const start_attempt = decodeStartAttempt(value.start_attempt);
  if (value.start_attempt !== undefined && value.start_attempt !== null && start_attempt === null) return null;
  return {
    schema_version: OPERATION_READ_MODEL_SCHEMA,
    operation_id: value.operation_id,
    action: value.action as OperatorAction,
    request_digest: value.request_digest,
    state: value.state as OperatorOperationState,
    phase: value.phase,
    blocker_codes: strictCodes(value.blocker_codes) as string[],
    created_at_utc: value.created_at_utc,
    updated_at_utc: value.updated_at_utc,
    state_revision: value.state_revision as number,
    result_present: value.result_present as boolean,
    retryable: value.retryable as boolean,
    replayed: value.replayed as boolean,
    idempotent_replay: value.idempotent_replay as boolean,
    acknowledged: value.acknowledged as boolean,
    acknowledged_at_utc: value.acknowledged_at_utc as string | null,
    safety_flags,
    start_attempt,
  };
}

export function buildOperatorAcknowledgementPayload(
  operation: Pick<OperatorOperationProjection, 'action' | 'state_revision'>,
): {action: OperatorAction; expected_state_revision: number} {
  return {
    action: operation.action,
    expected_state_revision: operation.state_revision,
  };
}

export function resolveOperatorAcknowledgementAction(
  operation: Pick<OperatorOperationProjection, 'action'> | null,
  unknownAction: OperatorAction | '',
  rejectedAction: OperatorAction | '',
): OperatorAction | '' {
  return operation?.action || unknownAction || rejectedAction;
}

export function decodeOperatorContract(value: unknown): OperatorContractProjection {
  if (!isRecord(value) || value.schema_version !== OPERATOR_CONTRACT_SCHEMA) {
    return invalidContract(['operator_v2_contract_invalid', 'schema_version_invalid']);
  }
  const safety_flags = falseSafetyFlags(value.safety_flags);
  const actions = value.actions;
  const blockers: string[] = [];
  if (typeof value.source !== 'string' || !value.source.trim()) blockers.push('source_missing');
  if (typeof value.runtime_identity !== 'string' || !value.runtime_identity.trim()) blockers.push('runtime_identity_missing');
  if (typeof value.source_head !== 'string' || !SOURCE_HEAD.test(value.source_head)) blockers.push('source_head_invalid');
  if (!Number.isInteger(value.state_revision) || (value.state_revision as number) < 0) blockers.push('state_revision_invalid');
  if (typeof value.state_digest !== 'string' || !STATE_DIGEST.test(value.state_digest)) blockers.push('state_digest_invalid');
  if (!isUtc(value.as_of_utc)) blockers.push('as_of_utc_invalid');
  if (!safety_flags) blockers.push('safety_flag_enabled_or_missing');
  if (!Array.isArray(actions) || actions.length !== OPERATOR_ACTIONS.length) blockers.push('action_set_invalid');
  const topLevelBlockers = value.blockers === undefined ? [] : strictCodes(value.blockers);
  if (topLevelBlockers === null) blockers.push('blocker_codes_invalid');
  const rows = Array.isArray(actions) ? actions : [];
  const decoded = rows.map((row): OperatorActionProjection | null => {
    const rowBlockers = isRecord(row) ? strictCodes(row.blocker_codes) : null;
    const rowReasons = isRecord(row) ? strictCodes(row.reason_codes) : null;
    if (!isRecord(row)
      || typeof row.action !== 'string' || !OPERATOR_ACTIONS.includes(row.action as OperatorAction)
      || typeof row.allowed !== 'boolean' || typeof row.execution_permission !== 'boolean'
      || row.execution_permission !== row.allowed
      || rowBlockers === null || rowReasons === null
      || typeof row.source !== 'string' || typeof row.runtime_identity !== 'string'
      || row.source !== value.source || row.runtime_identity !== value.runtime_identity
      || row.state_revision !== value.state_revision
      || row.state_digest !== value.state_digest
      || row.as_of_utc !== value.as_of_utc) return null;
    return {
      action: row.action as OperatorAction,
      allowed: row.allowed,
      execution_permission: row.execution_permission,
      blocker_codes: rowBlockers as string[],
      reason_codes: rowReasons as string[],
      source: row.source,
      runtime_identity: row.runtime_identity,
      state_revision: row.state_revision as number | null,
      state_digest: row.state_digest as string,
      as_of_utc: row.as_of_utc as string,
    };
  });
  if (decoded.length !== OPERATOR_ACTIONS.length || decoded.some((row) => row === null)) blockers.push('action_row_invalid');
  const ordered = decoded.filter((row): row is OperatorActionProjection => row !== null);
  if (ordered.map((row) => row.action).join('|') !== OPERATOR_ACTIONS.join('|')) blockers.push('action_order_invalid');
  const operation = value.operation === null || value.operation === undefined ? null : decodeOperatorOperation(value.operation);
  if (value.operation !== null && value.operation !== undefined && !operation) blockers.push('operation_invalid');
  let guardian: GuardianReadModel | undefined;
  if (value.guardian !== undefined && !(isRecord(value.guardian) && Object.keys(value.guardian).length === 0)) {
    if (!isRecord(value.guardian)
      || strictCodes(value.guardian.reason_codes) === null
      || !Number.isInteger(value.guardian.generation)
      || (value.guardian.generation as number) < 0) {
      blockers.push('guardian_read_model_invalid');
    } else {
      guardian = {
        ...value.guardian,
        reason_codes: strictCodes(value.guardian.reason_codes) as string[],
        generation: value.guardian.generation as number,
      } as GuardianReadModel;
    }
  }
  if (blockers.length) return invalidContract(['operator_v2_contract_invalid', ...blockers]);
  return {
    valid: true,
    schema_version: OPERATOR_CONTRACT_SCHEMA,
    source: value.source as string,
    runtime_identity: value.runtime_identity as string,
    source_head: value.source_head as string,
    state_revision: value.state_revision as number,
    state_digest: value.state_digest as string,
    as_of_utc: value.as_of_utc as string,
    actions: ordered,
    action_map: Object.fromEntries(ordered.map((row) => [row.action, row])) as Record<OperatorAction, OperatorActionProjection>,
    operation,
    safety_flags: safety_flags as SafetyFlags,
    blockers: topLevelBlockers as string[],
    guardian,
  };
}

export function isTerminalOperationState(state: OperatorOperationState): boolean {
  return !isPendingState(state);
}

export function canAcknowledgeNewOperation(
  operation: OperatorOperationProjection | null,
  unknownAttempt: boolean,
): boolean {
  if (operation && isPendingState(operation.state)) return false;
  return Boolean(operation && isTerminalOperationState(operation.state)) || unknownAttempt;
}

/**
 * Decide whether the acknowledgement handler may advance one action. A
 * durable terminal operation is authoritative and must be acknowledged through
 * its fenced backend endpoint; the attempt-state helper only covers actions
 * with no durable operation. A read failure remains fail-closed even if an
 * earlier terminal projection is still cached.
 */
export function canAcknowledgeOperatorOperation(
  operation: Pick<OperatorOperationProjection, 'state'> | null,
  attemptDisposition: OperatorAttemptOverlay['disposition'] | null,
  operationReadFailure = false,
): boolean {
  if (operationReadFailure) return false;
  if (operation) return isTerminalOperationState(operation.state);
  return canAcknowledgeOperatorAttempt(null, attemptDisposition);
}

export type OperatorActionCacheSnapshot = {
  operation: Pick<OperatorOperationProjection, 'state'> | null;
  readFailure: boolean;
  overlayDisposition: OperatorAttemptOverlay['disposition'] | null;
};

/**
 * A valid contract with no durable operation is the only safe signal that a
 * terminal/read-failure cache is stale. Invalid contracts and absent durable
 * projections for queued/running operations must remain fail-closed.
 */
export function shouldReleaseAuthoritativeActionCache(
  contract: Pick<OperatorContractProjection, 'valid' | 'operation'>,
  snapshot: OperatorActionCacheSnapshot,
): boolean {
  if (!contract.valid || contract.operation !== null) return false;
  if (snapshot.operation && isPendingState(snapshot.operation.state)) return false;
  if (snapshot.overlayDisposition === 'ambiguous_unknown') return false;
  return Boolean(
    (snapshot.operation && isTerminalOperationState(snapshot.operation.state))
    || snapshot.readFailure
    || snapshot.overlayDisposition === 'read_failure'
    || snapshot.overlayDisposition === 'definitive_rejected',
  );
}

export function actionsToReleaseForAuthoritativeContract(
  contract: Pick<OperatorContractProjection, 'valid' | 'operation'>,
  snapshots: ReadonlyMap<OperatorAction, OperatorActionCacheSnapshot>,
): OperatorAction[] {
  const actions: OperatorAction[] = [];
  snapshots.forEach((snapshot, action) => {
    if (shouldReleaseAuthoritativeActionCache(contract, snapshot)) actions.push(action);
  });
  return actions;
}

/** An acknowledged terminal GET replay may be released only under a valid fence. */
export function shouldReleaseAcknowledgedOperation(
  contract: Pick<OperatorContractProjection, 'valid'>,
  operation: Pick<OperatorOperationProjection, 'acknowledged' | 'state'> | null,
): boolean {
  return Boolean(contract.valid && operation?.acknowledged === true && !isPendingState(operation.state));
}

/** Pure immutable single-flight helpers; callers own the immediate ref lock. */
export function claimActionBusy(
  current: ReadonlySet<OperatorAction>,
  action: OperatorAction,
): Set<OperatorAction> | null {
  if (current.has(action)) return null;
  const next = new Set(current);
  next.add(action);
  return next;
}

export function releaseActionBusy(
  current: ReadonlySet<OperatorAction>,
  action: OperatorAction,
): Set<OperatorAction> {
  const next = new Set(current);
  next.delete(action);
  return next;
}

function idempotencyStorageKey(action: OperatorAction): string {
  return `${IDEMPOTENCY_PREFIX}${action}`;
}

function idempotencyKey(action: OperatorAction): string {
  const key = idempotencyStorageKey(action);
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const generated = `btc-demo-v2-${action}-${window.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
    window.localStorage.setItem(key, generated);
    return generated;
  } catch {
    return `btc-demo-v2-${action}-memory`;
  }
}

function clearIdempotencyKey(action: OperatorAction): void {
  try {
    window.localStorage.removeItem(idempotencyStorageKey(action));
  } catch {
    // A storage failure must not turn an explicit acknowledgement into a POST.
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '请求失败');
}

function isPendingState(state: OperatorOperationState): boolean {
  return state === 'queued' || state === 'running';
}

export function useDemoOperatorV2({refreshToken = 0, enabled = true}: {refreshToken?: number; enabled?: boolean} = {}): DemoOperatorController {
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const [catalog, setCatalog] = useState<DemoCatalog | null>(null);
  const [status, setStatus] = useState<DemoRuntimeStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [klines, setKlines] = useState<LocalKlineResponse | null>(null);
  const [contract, setContract] = useState<OperatorContractProjection>(() => invalidContract());
  const [operation, setOperation] = useState<OperatorOperationProjection | null>(null);
  const [loading, setLoading] = useState(true);
  const [bootstrapFailed, setBootstrapFailed] = useState(false);
  const [bootstrapError, setBootstrapError] = useState('');
  const [busyActions, setBusyActions] = useState<ReadonlySet<OperatorAction>>(() => new Set());
  const [message, setMessage] = useState('');
  const [operationUnknownAction, setOperationUnknownAction] = useState<OperatorAction | ''>('');
  const [operationRejectedAction, setOperationRejectedAction] = useState<OperatorAction | ''>('');
  const actionOperations = useRef(new Map<OperatorAction, OperatorOperationProjection>());
  const busyActionsRef = useRef<Set<OperatorAction>>(new Set());
  const operationReadFailures = useRef(new Set<OperatorAction>());
  const attemptOverlays = useRef(new Map<OperatorAction, OperatorAttemptOverlay>());
  const awaitingFreshContractActions = useRef(new Set<OperatorAction>());

  const clearActionCache = useMemo(() => (action: OperatorAction): void => {
    actionOperations.current.delete(action);
    operationReadFailures.current.delete(action);
    attemptOverlays.current.delete(action);
    setOperationUnknownAction((current) => current === action ? '' : current);
    setOperationRejectedAction((current) => current === action ? '' : current);
    setOperation((current) => current?.action === action ? null : current);
    clearIdempotencyKey(action);
  }, []);

  const reconcileAuthoritativeContract = useMemo(() => (decoded: OperatorContractProjection): void => {
    if (!decoded.valid || decoded.operation !== null) return;
    const candidateActions = new Set<OperatorAction>([
      ...actionOperations.current.keys(),
      ...operationReadFailures.current,
      ...attemptOverlays.current.keys(),
    ]);
    const snapshots = new Map<OperatorAction, OperatorActionCacheSnapshot>();
    candidateActions.forEach((action) => {
      const overlay = attemptOverlays.current.get(action);
      snapshots.set(action, {
        operation: actionOperations.current.get(action) ?? null,
        readFailure: operationReadFailures.current.has(action),
        overlayDisposition: overlay?.disposition ?? null,
      });
    });
    actionsToReleaseForAuthoritativeContract(decoded, snapshots).forEach(clearActionCache);
  }, [clearActionCache]);

  const claimBusy = useMemo(() => (action: OperatorAction): boolean => {
    const next = claimActionBusy(busyActionsRef.current, action);
    if (!next) return false;
    busyActionsRef.current = next;
    setBusyActions(next);
    return true;
  }, []);

  const releaseBusy = useMemo(() => (action: OperatorAction): void => {
    const next = releaseActionBusy(busyActionsRef.current, action);
    busyActionsRef.current = next;
    setBusyActions(next);
  }, []);

  const isActionBusy = useMemo(() => (action: OperatorAction): boolean => busyActionsRef.current.has(action), []);

  const markOperationReadFailure = useMemo(() => (action: OperatorAction, blocker = 'operator_v2_operation_unavailable') => {
    operationReadFailures.current.add(action);
    setOperation(null);
    setOperationRejectedAction('');
    const overlay = readFailureOverlay(action, new Error(blocker));
    attemptOverlays.current.set(action, overlay);
    setContract((current) => applyOperatorAttemptOverlays(current, attemptOverlays.current));
    setMessage(`既有操作状态不可验证（${blocker}）；保持 fail-closed，未重复提交。`);
  }, []);

  const markAttemptFailure = useMemo(() => (action: OperatorAction, error: unknown) => {
    const classification = classifyOperatorAttemptError(error);
    const overlay = {...classification, action};
    attemptOverlays.current.set(action, overlay);
    setOperationUnknownAction(action);
    setOperationRejectedAction(classification.disposition === 'definitive_rejected' ? action : '');
    setOperation(null);
    setContract((current) => applyOperatorAttemptOverlays(current, attemptOverlays.current));
    if (classification.disposition === 'definitive_rejected') {
      setOperationUnknownAction('');
      setMessage(`操作已被后端拒绝（${classification.errorCode}）：${classification.blockerCodes.join('、') || 'operator_action_failed'}；未重试 POST。`);
    } else {
      setMessage(`操作结果无法确认（${classification.errorCode}）；保持 fail-closed，需人工确认后才能新建操作。`);
    }
  }, []);

  const refresh = useMemo(() => async () => {
    if (!enabledRef.current) return;
    setLoading(true);
    const results = await Promise.allSettled([
      apiGet<DemoCatalog>(DEMO_CATALOG_PATH, 30_000),
      apiGet<DemoRuntimeStatus>(DEMO_STATUS_PATH),
      apiGet<unknown>(OPERATOR_CONTRACT_PATH),
      apiGet<LocalKlineResponse>(DEMO_KLINES_PATH, 30_000),
    ]);
    if (!enabledRef.current) return;
    const errors: string[] = [];
    const catalogResult = results[0];
    if (catalogResult.status === 'fulfilled') setCatalog(catalogResult.value); else errors.push(errorText(catalogResult.reason));
    const statusResult = results[1];
    if (statusResult.status === 'fulfilled') {
      setStatus(statusResult.value);
      setStatusError('');
    } else {
      setStatus(null);
      setStatusError(errorText(statusResult.reason));
      errors.push(errorText(statusResult.reason));
    }
    const contractResult = results[2];
    if (contractResult.status === 'fulfilled') {
      const decoded = decodeOperatorContract(contractResult.value);
      reconcileAuthoritativeContract(decoded);
      const projected = applyOperatorAttemptOverlays(decoded, attemptOverlays.current);
      awaitingFreshContractActions.current.clear();
      setContract(projected);
      if (!decoded.valid) {
        setOperation(null);
      } else if (decoded.operation) {
        operationReadFailures.current.delete(decoded.operation.action);
        setOperationUnknownAction('');
        setOperation(decoded.operation);
        actionOperations.current.set(decoded.operation.action, decoded.operation);
      } else {
        setOperation(null);
      }
    } else {
      setContract(invalidContract(['operator_v2_contract_unavailable']));
      errors.push(errorText(contractResult.reason));
    }
    const klinesResult = results[3];
    if (klinesResult.status === 'fulfilled') setKlines(klinesResult.value); else errors.push(errorText(klinesResult.reason));
    setBootstrapFailed(errors.length > 0);
    setBootstrapError(errors.join(' · '));
    setLoading(false);
  }, [reconcileAuthoritativeContract]);

  const refreshOperatorState = useMemo(() => async (targetAction?: OperatorAction) => {
    if (!enabledRef.current) return;
    const [statusResult, contractResult] = await Promise.allSettled([
      apiGet<DemoRuntimeStatus>(DEMO_STATUS_PATH),
      apiGet<unknown>(OPERATOR_CONTRACT_PATH),
    ]);
    if (!enabledRef.current) return;
    if (statusResult.status === 'fulfilled') {
      setStatus(statusResult.value);
      setStatusError('');
    } else {
      // Status is diagnostic only; it must not revoke a separately valid V2 contract.
      setStatusError(errorText(statusResult.reason));
    }
    if (contractResult.status === 'fulfilled') {
      const decoded = decodeOperatorContract(contractResult.value);
      reconcileAuthoritativeContract(decoded);
      const projected = applyOperatorAttemptOverlays(decoded, attemptOverlays.current);
      awaitingFreshContractActions.current.clear();
      setContract(projected);
      if (!decoded.valid) {
        setOperation(null);
      } else if (decoded.operation) {
        operationReadFailures.current.delete(decoded.operation.action);
        setOperationUnknownAction('');
        setOperation(decoded.operation);
        actionOperations.current.set(decoded.operation.action, decoded.operation);
      } else {
        setOperation(null);
      }
    } else if (targetAction) {
      if (!attemptOverlays.current.has(targetAction)) {
        attemptOverlays.current.set(targetAction, readFailureOverlay(targetAction, contractResult.reason));
      }
      setContract((current) => applyOperatorAttemptOverlays(current, attemptOverlays.current));
      setOperation(null);
    } else {
      setContract(revokeOperatorContract('operator_v2_contract_unavailable'));
      setOperation(null);
    }
  }, [reconcileAuthoritativeContract]);

  const refreshKnownOperation = useMemo(() => async () => {
    if (!enabledRef.current) return;
    const known = [...actionOperations.current.values()].find((item) => isPendingState(item.state));
    if (!known) return;
    if (operationReadFailures.current.has(known.action)) return;
    try {
      const next = decodeOperatorOperation(await apiGet<unknown>(`${OPERATOR_OPERATION_PATH}/${encodeURIComponent(known.operation_id)}`));
      if (!enabledRef.current) return;
      if (!next) {
        markOperationReadFailure(known.action, 'operator_v2_operation_invalid');
        return;
      }
      operationReadFailures.current.delete(known.action);
      setOperation(next);
      actionOperations.current.set(next.action, next);
    } catch {
      if (!enabledRef.current) return;
      markOperationReadFailure(known.action);
    }
  }, [markOperationReadFailure]);

  useEffect(() => {
    enabledRef.current = enabled;
    if (enabled) void refresh();
    return () => { enabledRef.current = false; };
  }, [enabled, refresh, refreshToken]);
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => { void refreshOperatorState(); }, 5_000);
    return () => window.clearInterval(timer);
  }, [enabled, refreshOperatorState]);
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => { void refreshKnownOperation(); }, 2_000);
    return () => window.clearInterval(timer);
  }, [enabled, refreshKnownOperation]);
  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      if (!enabledRef.current) return;
      void apiGet<LocalKlineResponse>(DEMO_KLINES_PATH, 30_000)
        .then(payload => { if (enabledRef.current) setKlines(payload); })
        .catch(() => {
          // Keep the last confirmed chart frame; status/contract remain authoritative.
        });
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [enabled]);

  const dispatch = useMemo(() => async (action: OperatorAction, payload: Record<string, unknown> = {}) => {
    if (!enabledRef.current) return;
    const authorization = contract.action_map[action];
    if (!contract.valid || !authorization || authorization.allowed !== true || authorization.execution_permission !== true) {
      setMessage(`操作被后端 V2 契约拒绝：${authorization?.blocker_codes.join(',') || contract.blockers.join(',') || 'operator_v2_contract_invalid'}`);
      return;
    }
    if (awaitingFreshContractActions.current.has(action)) {
      setMessage(`操作 ${action} 已确认过上次结果；等待新的后端契约 GET 后才可新建，未重复提交。`);
      return;
    }
    const priorAttempt = attemptOverlays.current.get(action);
    if (priorAttempt) {
      setMessage(priorAttempt.disposition === 'definitive_rejected'
        ? `操作 ${action} 已被后端拒绝；先确认拒绝结果并刷新契约，未重复提交。`
        : `操作 ${action} 的上次结果无法确认；保持 fail-closed，未重复提交。`);
      return;
    }
    const known = actionOperations.current.get(action);
    if (known) {
      if (operationReadFailures.current.has(action)) {
        setMessage(`操作 ${action} 的既有状态不可验证；仅保持 GET/replay 保护，未重复提交。`);
        return;
      }
      try {
        const replay = decodeOperatorOperation(await apiGet<unknown>(`${OPERATOR_OPERATION_PATH}/${encodeURIComponent(known.operation_id)}`));
        if (!enabledRef.current) return;
        if (replay) {
          if (shouldReleaseAcknowledgedOperation(contract, replay)) {
            clearActionCache(action);
            awaitingFreshContractActions.current.add(action);
            setMessage(`操作 ${action} 已由后端确认；等待新的契约 GET 后才允许一次新的幂等提交。`);
            await refreshOperatorState(action);
          } else {
            operationReadFailures.current.delete(action);
            setOperation(replay);
            actionOperations.current.set(action, replay);
            setMessage(`操作 ${action} 已存在（${replay.state}），仅 GET/replay，未重复提交。`);
          }
        } else markOperationReadFailure(action, 'operator_v2_operation_invalid');
      } catch (error) {
        markOperationReadFailure(action);
      }
      return;
    }
    if (!claimBusy(action)) {
      setMessage(`操作 ${action} 已在执行；未重复提交。`);
      return;
    }
    setMessage('');
    try {
      // The visible V2 contract is the sole source of the optimistic
      // concurrency fence.  Caller/form payloads cannot override these
      // fields; the backend strips them before controller dispatch.
      const fencedPayload: Record<string, unknown> = {
        ...payload,
        expected_runtime_identity: contract.runtime_identity,
        expected_state_revision: contract.state_revision,
        expected_state_digest: contract.state_digest,
      };
      const guardian = contract.guardian;
      if (action === 'acknowledge_guardian_trip' || action === 'recover_guardian_after_fresh_preflight') {
        fencedPayload.expected_guardian_generation = guardian?.generation ?? 0;
        fencedPayload.expected_guardian_evidence_identity = guardian?.evidence_identity ?? '';
        fencedPayload.expected_guardian_evidence_digest = guardian?.evidence_digest ?? '';
        fencedPayload.expected_guardian_observation_digest = guardian?.observation_digest ?? '';
        fencedPayload.guardian_evidence_fence = {
          generation: guardian?.generation ?? 0,
          evidence_identity: guardian?.evidence_identity ?? '',
          evidence_digest: guardian?.evidence_digest ?? '',
          observation_digest: guardian?.observation_digest ?? '',
        };
      }
      const raw = await apiPost<unknown>(
        `${OPERATOR_ACTION_PATH}/${encodeURIComponent(action)}`,
        fencedPayload,
        20_000,
        {'Idempotency-Key': idempotencyKey(action)},
      );
      const created = decodeOperatorOperation(raw);
      if (!created) {
        markAttemptFailure(action, new Error('operator_v2_operation_invalid'));
      } else {
        setOperation(created);
        operationReadFailures.current.delete(action);
        actionOperations.current.set(action, created);
        setMessage(created.state === 'succeeded' ? `${action} 已完成。` : `${action} 已受理：${created.state}。`);
      }
      await refreshOperatorState(action);
    } catch (error) {
      markAttemptFailure(action, error);
      await refreshOperatorState(action);
    } finally {
      releaseBusy(action);
    }
  }, [claimBusy, clearActionCache, contract, markAttemptFailure, markOperationReadFailure, refreshOperatorState, releaseBusy]);

  const acknowledgeNewOperation = useMemo(() => async (action: OperatorAction): Promise<boolean> => {
    if (!enabledRef.current) return false;
    const known = actionOperations.current.get(action) ?? null;
    const attempt = attemptOverlays.current.get(action);
    if (!canAcknowledgeOperatorOperation(
      known,
      attempt?.disposition ?? null,
      operationReadFailures.current.has(action),
    )) {
      setMessage(`操作 ${action} 尚未达到可确认的新建状态；pending/unknown 仍保持 fail-closed。`);
      return false;
    }
    if (known) {
      if (!claimBusy(action)) {
        setMessage(`操作 ${action} 正在处理；未重复确认。`);
        return false;
      }
      try {
        const raw = await apiPost<unknown>(
          `${OPERATOR_OPERATION_PATH}/${encodeURIComponent(known.operation_id)}/acknowledge`,
          buildOperatorAcknowledgementPayload(known),
        );
        const acknowledged = decodeOperatorOperation(raw);
        if (!acknowledged
          || acknowledged.operation_id !== known.operation_id
          || acknowledged.action !== action
          || acknowledged.acknowledged !== true) {
          throw new Error('operator_terminal_acknowledgement_failed');
        }
      } catch {
        setMessage(`操作 ${action} 的后端终态确认失败（operator_terminal_acknowledgement_failed）；保留原幂等键与终态记录，未新建操作。`);
        return false;
      } finally {
        releaseBusy(action);
      }
    }
    actionOperations.current.delete(action);
    operationReadFailures.current.delete(action);
    attemptOverlays.current.delete(action);
    awaitingFreshContractActions.current.add(action);
    if (operationUnknownAction === action) setOperationUnknownAction('');
    if (operationRejectedAction === action) setOperationRejectedAction('');
    setOperation(null);
    clearIdempotencyKey(action);
    setMessage(`已确认 ${action} 的结果；等待新的后端契约 GET 后才可生成下一次 Idempotency-Key。`);
    void refreshOperatorState();
    return true;
  }, [claimBusy, operationRejectedAction, operationUnknownAction, refreshOperatorState, releaseBusy]);

  return {
    catalog: enabled ? catalog : null,
    status: enabled ? status : null,
    statusError: enabled ? statusError : '',
    klines: enabled ? klines : null,
    contract: enabled ? contract : invalidContract(['backend_runtime_reads_disabled']),
    operation: enabled ? operation ?? contract.operation : null,
    loading: enabled && loading,
    bootstrapFailed: enabled && bootstrapFailed,
    bootstrapError: enabled ? bootstrapError : '',
    busyActions, isActionBusy, operationUnknownAction, operationRejectedAction,
    message: enabled ? message : '', refresh, dispatch,
    acknowledgeNewOperation,
  };
}
