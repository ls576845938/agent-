export function formatTimestamp(unix: number): string {
  return new Date(unix * 1000).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

export function formatIso(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

export function formatPrice(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export function formatParams(params?: Record<string, number> | null): string {
  if (!params) return '-';
  const entries = Object.entries(params);
  if (entries.length === 0) return 'default';
  return entries.map(([key, value]) => `${key}=${value}`).join(', ');
}

export function formatOptimizationScore(value?: number): string {
  return typeof value === 'number' ? value.toFixed(3) : '-';
}

export function buildDateBoundary(date: string, boundary: 'start' | 'end', interval: string): string {
  if (boundary === 'start') return `${date}T00:00:00Z`;
  if (interval === '1d') return `${date}T23:59:59Z`;
  return `${date}T23:00:00Z`;
}

export function metricClass(tone: string): string {
  if (tone === 'good') return 'metric-card metric-good';
  if (tone === 'bad') return 'metric-card metric-bad';
  return 'metric-card';
}

export function reportMetricClass(tone?: string): string {
  if (tone === 'good') return 'report-metric metric-good';
  if (tone === 'bad') return 'report-metric metric-bad';
  return 'report-metric';
}

export function hintClass(severity: string): string {
  if (severity === 'high') return 'hint-row hint-high';
  if (severity === 'medium') return 'hint-row hint-medium';
  return 'hint-row';
}

export function scenarioClass(survives: boolean): string {
  return survives ? 'stress-row stress-pass' : 'stress-row stress-fail';
}

export function gateClass(status: string): string {
  return `promotion-gate-row promotion-${status}`;
}

export function mvpStepClass(status: string): string {
  return `mvp-step mvp-${status}`;
}

export function diagnosticsList<T>(diagnostics: Record<string, unknown> | undefined, key: string): T[] {
  const value = diagnostics?.[key];
  return Array.isArray(value) ? (value as T[]) : [];
}

export function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function floorTimestampToInterval(unix: number, interval: number): number {
  return Math.floor(unix / interval) * interval;
}
