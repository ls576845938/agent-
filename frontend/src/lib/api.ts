const BASE = '';  // vite proxy handles routing

export type BtcDemoOperatorErrorV2 = {
  schema_version: 'btc_demo_operator_error_v2';
  error_code: string;
  allowed: false;
  execution_permission: false;
  blocker_codes: string[];
  reason_codes: string[];
  safety_flags: {
    promotion_eligible: false;
    paper: false;
    live: false;
    private: false;
    order: false;
    real_order: false;
    transfer: false;
    withdraw: false;
  };
};

const OPERATOR_CODE = /^[a-z0-9][a-z0-9_.-]*$/;
const OPERATOR_SAFETY_FLAGS = ['promotion_eligible', 'paper', 'live', 'private', 'order', 'real_order', 'transfer', 'withdraw'] as const;

function operatorCodes(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || !OPERATOR_CODE.test(item))) return null;
  return [...new Set(value as string[])].sort();
}

function falseOperatorSafetyFlags(value: unknown): BtcDemoOperatorErrorV2['safety_flags'] | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const flags = value as Record<string, unknown>;
  if (OPERATOR_SAFETY_FLAGS.some((name) => flags[name] !== false)) return null;
  return {
    promotion_eligible: false, paper: false, live: false, private: false,
    order: false, real_order: false, transfer: false, withdraw: false,
  };
}

export function decodeBtcDemoOperatorError(value: unknown): BtcDemoOperatorErrorV2 | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const payload = value as Record<string, unknown>;
  const blockerCodes = operatorCodes(payload.blocker_codes);
  const reasonCodes = operatorCodes(payload.reason_codes);
  const safetyFlags = falseOperatorSafetyFlags(payload.safety_flags);
  if (payload.schema_version !== 'btc_demo_operator_error_v2'
    || typeof payload.error_code !== 'string' || !OPERATOR_CODE.test(payload.error_code)
    || payload.allowed !== false || payload.execution_permission !== false
    || blockerCodes === null || reasonCodes === null || safetyFlags === null) return null;
  return {
    schema_version: 'btc_demo_operator_error_v2',
    error_code: payload.error_code,
    allowed: false,
    execution_permission: false,
    blocker_codes: blockerCodes,
    reason_codes: reasonCodes,
    safety_flags: safetyFlags,
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail = '',
    public operatorError: BtcDemoOperatorErrorV2 | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function normalizeErrorDetail(value: unknown): string {
  const detail = typeof value === 'string'
    ? value
    : Array.isArray(value)
      ? value.map((item) => typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : '').filter(Boolean).join('; ')
      : '';
  return detail.replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim().slice(0, 512);
}

async function responseError(method: 'GET' | 'POST', path: string, response: Response): Promise<ApiError> {
  let detail = '';
  let operatorError: BtcDemoOperatorErrorV2 | null = null;
  try {
    const payload = await response.json() as unknown;
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      detail = normalizeErrorDetail((payload as {detail?: unknown}).detail);
    }
    // Only a trusted 4xx operator envelope is definitive.  Timeouts and all
    // 5xx responses remain ambiguous even if a server happens to echo fields.
    if (response.status >= 400 && response.status < 500 && response.status !== 408) {
      operatorError = decodeBtcDemoOperatorError(payload);
    }
  } catch {
    detail = '';
  }
  const suffix = detail ? ` · ${detail}` : '';
  return new ApiError(response.status, `${method} ${path}: ${response.status}${suffix}`, detail, operatorError);
}

export type ApiGetOptions = {
  timeoutMs?: number;
  signal?: AbortSignal;
};

export async function apiGet<T>(path: string, timeoutOrOptions: number | ApiGetOptions = 20000): Promise<T> {
  const options = typeof timeoutOrOptions === 'number' ? {timeoutMs: timeoutOrOptions} : timeoutOrOptions;
  const timeoutMs = options.timeoutMs ?? 20000;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const cancelFromCaller = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener('abort', cancelFromCaller, {once: true});
  try {
    if (options.signal?.aborted) cancelFromCaller();
    const res = await fetch(BASE + path, {signal: controller.signal});
    if (!res.ok) throw await responseError('GET', path, res);
    // Keep the deadline and caller cancellation active while a large JSON body
    // is downloaded and parsed, not only until response headers arrive.
    return await res.json() as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (timedOut) throw new ApiError(408, `GET ${path}: timeout after ${timeoutMs}ms`);
      throw error;
    }
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', cancelFromCaller);
  }
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  timeoutMs = 20000,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', ...(extraHeaders ?? {})},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(408, `POST ${path}: timeout after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw await responseError('POST', path, res);
  return res.json() as Promise<T>;
}

export async function apiPostRaw(path: string, body?: unknown): Promise<Response> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  return res;  // caller checks .ok
}
