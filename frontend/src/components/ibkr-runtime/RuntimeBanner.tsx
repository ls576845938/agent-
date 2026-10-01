import {ShieldCheck, WarningCircle} from '@phosphor-icons/react';
import {
  createUnavailableIbkrRuntimeStatus,
  runtimeBanner,
  type IbkrRuntimeStatusResult,
} from '../../lib/ibkr-runtime-api';

type RuntimeBannerProps = {
  result: IbkrRuntimeStatusResult;
};

export function RuntimeBanner({result}: RuntimeBannerProps) {
  const unavailable = result.kind === 'unavailable';
  const snapshot = unavailable ? createUnavailableIbkrRuntimeStatus(result.message) : result.snapshot;
  const copy = unavailable
    ? {
        title: 'IBKR 运行时状态不可用',
        detail: '新订单已阻断 · 无法验证运行时事实',
        blocked: true,
      }
    : runtimeBanner(snapshot);

  const backgroundColor = copy.blocked ? 'rgba(176, 44, 57, 0.2)' : 'rgba(44, 139, 91, 0.2)';
  const borderColor = copy.blocked ? 'rgba(255, 108, 118, 0.75)' : 'rgba(98, 219, 154, 0.75)';
  const Icon = copy.blocked ? WarningCircle : ShieldCheck;

  return (
    <section
      className="runtime-banner"
      data-testid="runtime-banner"
      data-runtime-kind={result.kind}
      data-runtime-blocked={String(copy.blocked)}
      role="status"
      aria-live="polite"
      style={{
        alignItems: 'center',
        backgroundColor,
        border: `1px solid ${borderColor}`,
        borderRadius: 10,
        color: copy.blocked ? '#ffd9dc' : '#d8ffe9',
        display: 'flex',
        gap: 12,
        justifyContent: 'space-between',
        padding: '14px 16px',
        position: 'sticky',
        top: 0,
        zIndex: 20,
      }}
    >
      <div style={{alignItems: 'center', display: 'flex', gap: 10, minWidth: 0}}>
        <Icon aria-hidden="true" size={22} weight="bold" />
        <div style={{minWidth: 0}}>
          <strong style={{display: 'block', fontSize: '1rem', letterSpacing: '0.04em'}}>{copy.title}</strong>
          <span style={{display: 'block', fontSize: '0.82rem', marginTop: 3, opacity: 0.92}}>{copy.detail}</span>
        </div>
      </div>
      <span
        aria-label={unavailable ? 'IBKR 运行时状态不可用' : copy.blocked ? '运行时已阻断' : '运行时已就绪'}
        style={{
          border: `1px solid ${borderColor}`,
          borderRadius: 999,
          flexShrink: 0,
          fontSize: '0.72rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          padding: '4px 8px',
          textTransform: 'uppercase',
        }}
      >
        {unavailable ? '不可用' : copy.blocked ? '已阻断' : '就绪'}
      </span>
    </section>
  );
}
