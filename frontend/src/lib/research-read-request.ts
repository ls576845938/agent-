export type ResearchReadFailureKind = 'deadline' | 'cancelled' | 'http' | 'network' | 'unknown';

export type ResearchReadFailure = {
  name: string;
  kind: ResearchReadFailureKind;
  message: string;
};

type ResearchReadClock = {
  setTimeout: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  clearTimeout: (timer: ReturnType<typeof setTimeout>) => void;
};

type ResearchReadOptions = {
  deadlineMs?: number;
  releaseGraceMs?: number;
  clock?: ResearchReadClock;
};

export type ResearchReadLease<T> = {
  key: string;
  promise: Promise<T>;
  release: () => void;
};

type InFlightEntry<T> = {
  controller: AbortController;
  promise: Promise<T>;
  consumers: number;
  settled: boolean;
  clock: ResearchReadClock;
  deadlineTimer: ReturnType<typeof setTimeout>;
  releaseTimer?: ReturnType<typeof setTimeout>;
};

const DEADLINE_REASON = {code: 'research_read_deadline'} as const;
const RELEASED_REASON = {code: 'research_read_released'} as const;
const defaultClock: ResearchReadClock = {
  setTimeout: (callback, delay) => setTimeout(callback, delay),
  clearTimeout: (timer) => clearTimeout(timer),
};
const inFlightReads = new Map<string, InFlightEntry<unknown>>();

function reasonCode(signal?: AbortSignal): string {
  const reason = signal?.reason;
  if (!reason || typeof reason !== 'object' || !('code' in reason)) return '';
  return String((reason as {code?: unknown}).code || '');
}

/**
 * Shares only an identical in-flight research read. It is not a result cache:
 * settled entries are removed immediately and a new refresh always reads again.
 */
export function acquireResearchRead<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  options: ResearchReadOptions = {},
): ResearchReadLease<T> {
  const deadlineMs = options.deadlineMs ?? 12_000;
  const releaseGraceMs = options.releaseGraceMs ?? 1;
  const clock = options.clock ?? defaultClock;
  let entry = inFlightReads.get(key) as InFlightEntry<T> | undefined;

  if (!entry) {
    const controller = new AbortController();
    entry = {
      controller,
      promise: Promise.resolve(undefined as T),
      consumers: 0,
      settled: false,
      clock,
      deadlineTimer: undefined as unknown as ReturnType<typeof setTimeout>,
    };
    const created = entry;
    created.deadlineTimer = clock.setTimeout(() => {
      if (!created.settled) created.controller.abort(DEADLINE_REASON);
    }, deadlineMs);
    created.promise = Promise.resolve()
      .then(() => load(created.controller.signal))
      .finally(() => {
        created.settled = true;
        created.clock.clearTimeout(created.deadlineTimer);
        if (created.releaseTimer) created.clock.clearTimeout(created.releaseTimer);
        if (inFlightReads.get(key) === created) inFlightReads.delete(key);
      });
    inFlightReads.set(key, created as InFlightEntry<unknown>);
  }

  if (entry.releaseTimer) {
    entry.clock.clearTimeout(entry.releaseTimer);
    entry.releaseTimer = undefined;
  }
  entry.consumers += 1;
  let released = false;

  return {
    key,
    promise: entry.promise,
    release: () => {
      if (released) return;
      released = true;
      entry!.consumers = Math.max(0, entry!.consumers - 1);
      if (entry!.consumers || entry!.settled || entry!.releaseTimer) return;
      entry!.releaseTimer = entry!.clock.setTimeout(() => {
        entry!.releaseTimer = undefined;
        if (!entry!.consumers && !entry!.settled) entry!.controller.abort(RELEASED_REASON);
      }, releaseGraceMs);
    },
  };
}

export function classifyResearchReadError(error: unknown, signal?: AbortSignal): Omit<ResearchReadFailure, 'name'> {
  const code = reasonCode(signal);
  if (code === DEADLINE_REASON.code) return {kind: 'deadline', message: '超过 12 秒读取截止时间'};
  if (code === RELEASED_REASON.code) return {kind: 'cancelled', message: '来源已切换，旧读取已取消'};

  const value = error && typeof error === 'object' ? error as {name?: unknown; status?: unknown} : null;
  if (value?.status === 408) return {kind: 'deadline', message: '读取超过接口截止时间'};
  if (typeof value?.status === 'number') return {kind: 'http', message: `服务返回 HTTP ${value.status}`};
  if (value?.name === 'AbortError') return {kind: 'cancelled', message: '读取已取消'};
  if (error instanceof TypeError) return {kind: 'network', message: '网络或代理读取失败'};
  return {kind: 'unknown', message: '读取失败，原因未分类'};
}

function noteText(value: unknown): string {
  if (typeof value === 'string') return value.trim().slice(0, 180);
  try {
    return JSON.stringify(value).slice(0, 180);
  } catch {
    return '';
  }
}

export function summarizeResearchRegistry(registry: unknown, overview?: unknown): {
  status: string;
  qualification: 'readable' | 'blocked' | 'unknown';
  notes: string[];
  notesTotal: number;
} {
  const row = registry && typeof registry === 'object' && !Array.isArray(registry)
    ? registry as Record<string, unknown> : {};
  const system = overview && typeof overview === 'object' && !Array.isArray(overview)
    ? overview as {registry?: {integrity?: unknown}} : {};
  const rawStatus = row.registry_integrity_status ?? row.registry_status ?? row.state ?? row.status
    ?? system.registry?.integrity;
  const status = typeof rawStatus === 'string' && rawStatus.trim() ? rawStatus.trim().toUpperCase() : 'UNKNOWN';
  const rawNotes = Array.isArray(row.registry_notes) ? row.registry_notes : [];
  const notes = rawNotes.map(noteText).filter(Boolean).slice(0, 3);
  const blocked = ['CONFLICT', 'BLOCKED', 'FAIL', 'FAILED', 'ERROR', 'CORRUPT'].includes(status);
  return {
    status,
    qualification: status === 'UNKNOWN' ? 'unknown' : blocked ? 'blocked' : 'readable',
    notes,
    notesTotal: rawNotes.length,
  };
}
