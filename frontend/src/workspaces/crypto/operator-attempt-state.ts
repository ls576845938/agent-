import {ApiError} from '../../lib/api';
import type {OperatorAction, OperatorContractProjection} from './demo-operator-v2';

export const OPERATOR_ATTEMPT_STATE_SCHEMA = 'btc_demo_operator_attempt_state_v1' as const;

export type OperatorAttemptDisposition = 'definitive_rejected' | 'ambiguous_unknown' | 'read_failure';

export type OperatorAttemptOverlay = {
  action: OperatorAction;
  disposition: OperatorAttemptDisposition;
  errorCode: string;
  blockerCodes: string[];
  reasonCodes: string[];
  message: string;
};

export type OperatorAttemptClassification = Omit<OperatorAttemptOverlay, 'action'>;

const CODE = /^[a-z0-9][a-z0-9_.-]*$/;

function stableCodes(value: unknown): string[] {
  const values = Array.isArray(value) ? value : typeof value === 'string' ? [value] : [];
  return [...new Set(values
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim().toLowerCase())
    .filter((item) => CODE.test(item)))].sort();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '请求失败');
}

export function classifyOperatorAttemptError(error: unknown): OperatorAttemptClassification {
  if (error instanceof ApiError && error.operatorError && error.status >= 400 && error.status < 500 && error.status !== 408) {
    return {
      disposition: 'definitive_rejected',
      errorCode: error.operatorError.error_code,
      blockerCodes: error.operatorError.blocker_codes,
      reasonCodes: error.operatorError.reason_codes,
      message: error.message,
    };
  }
  return {
    disposition: 'ambiguous_unknown',
    errorCode: error instanceof ApiError && error.status === 408 ? 'operator_transport_timeout' : 'operator_result_unknown',
    blockerCodes: ['operator_result_unknown'],
    reasonCodes: ['query_status_before_retry'],
    message: errorMessage(error),
  };
}

export function readFailureOverlay(action: OperatorAction, error: unknown): OperatorAttemptOverlay {
  return {
    action,
    disposition: 'read_failure',
    errorCode: 'operator_operation_read_failed',
    blockerCodes: ['operator_operation_read_failed'],
    reasonCodes: ['query_status_before_retry'],
    message: errorMessage(error),
  };
}

export function applyOperatorAttemptOverlay(
  contract: OperatorContractProjection,
  overlay: OperatorAttemptOverlay,
): OperatorContractProjection {
  if (!contract.valid) return contract;
  const row = contract.action_map[overlay.action];
  if (!row) return contract;
  const blockerCodes = stableCodes([...row.blocker_codes, ...overlay.blockerCodes]);
  const reasonCodes = stableCodes([...row.reason_codes, ...overlay.reasonCodes, overlay.errorCode]);
  const denied = {
    ...row,
    allowed: false,
    execution_permission: false,
    blocker_codes: blockerCodes,
    reason_codes: reasonCodes,
  };
  const actions = contract.actions.map((item) => item.action === overlay.action ? denied : item);
  return {
    ...contract,
    actions,
    action_map: {...contract.action_map, [overlay.action]: denied},
  };
}

export function applyOperatorAttemptOverlays(
  contract: OperatorContractProjection,
  overlays: ReadonlyMap<OperatorAction, OperatorAttemptOverlay>,
): OperatorContractProjection {
  let current = contract;
  overlays.forEach((overlay) => {
    current = applyOperatorAttemptOverlay(current, overlay);
  });
  return current;
}

export function canAcknowledgeOperatorAttempt(
  operationState: string | null,
  disposition: OperatorAttemptDisposition | null,
): boolean {
  if (operationState === 'queued' || operationState === 'running') return false;
  return disposition === 'definitive_rejected' || disposition === 'ambiguous_unknown' || disposition === 'read_failure';
}
