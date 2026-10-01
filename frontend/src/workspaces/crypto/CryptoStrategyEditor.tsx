import {useEffect, useMemo, useState} from 'react';

import {apiGet, apiPost} from '../../lib/api';
import {hasCanonicalStrategySource, strategyPresentationName, strategyVariantLabel} from '../../lib/strategy-presentation';
import type {DemoStrategySpec} from './demo-types';
import './crypto-strategy-editor.css';

export type CryptoBacktestPhase =
  | 'idle'
  | 'preparing'
  | 'submitting'
  | 'computing'
  | 'polling'
  | 'loading_results'
  | 'completed'
  | 'failed';

export type CryptoBacktestConfig = {
  versionId: string;
  start: string;
  end: string;
  capital: number;
};

type StrategySourceResponse = {
  strategy_id: string;
  candidate_id: string;
  source_ref: string;
  content_sha256: string;
  content: string;
  sections: Array<{symbol: string; source_ref: string}>;
  canonical_signal_available: boolean;
};

type StrategyWorkbenchVersion = {
  version_id: string;
  source_sha256?: string;
  source_content?: string;
  execution?: {
    runnable?: boolean;
    canonical_source_match?: boolean;
    blocker?: string;
  };
};

type StrategyWorkbenchVersionList = {versions: StrategyWorkbenchVersion[]};
type ValueEvent = {target: {value: string}};

type CryptoStrategyEditorProps = {
  strategies: DemoStrategySpec[];
  selectedCandidateId: string;
  form: {startDate: string; endDate: string; capital: number; commissionRate: number; slippageBps: number};
  onFormChange: (value: {startDate: string; endDate: string; capital: number; commissionRate: number; slippageBps: number}) => void;
  onStrategyChange: (candidateId: string) => void;
  busy: boolean;
  canRunBacktest: boolean;
  onRun: (config: CryptoBacktestConfig, onPhase: (phase: CryptoBacktestPhase) => void) => Promise<void>;
  onProgressPhase?: (phase: CryptoBacktestPhase) => void;
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function todayOffset(days: number): string {
  const value = new Date(Date.now() - days * 86_400_000);
  return value.toISOString().slice(0, 10);
}

export default function CryptoStrategyEditor({
  strategies,
  selectedCandidateId,
  form,
  onFormChange,
  onStrategyChange,
  busy,
  canRunBacktest,
  onRun,
  onProgressPhase,
}: CryptoStrategyEditorProps) {
  const spec = useMemo(
    () => strategies.find((item) => item.candidate_id === selectedCandidateId) ?? null,
    [selectedCandidateId, strategies],
  );
  const identityOnly = Boolean(spec && !hasCanonicalStrategySource(spec));
  const [source, setSource] = useState<StrategySourceResponse | null>(null);
  const [versions, setVersions] = useState<StrategyWorkbenchVersion[]>([]);
  const [sourceError, setSourceError] = useState('');
  const [draft, setDraft] = useState('');
  const [draftSaved, setDraftSaved] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [phase, setPhase] = useState<CryptoBacktestPhase>('idle');
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    if (!spec) {
      setSource(null);
      setVersions([]);
      setDraft('');
      setSourceError('');
      return;
    }
    let active = true;
    setSource(null);
    setVersions([]);
    setSourceError('');
    setActionError('');
    setPhase('idle');
    if (!hasCanonicalStrategySource(spec)) {
      setDraft('');
      setDraftSaved(false);
      return;
    }
    const sourcePath = `/api/research/btc/strategy-source/${encodeURIComponent(spec.strategy_id)}/${encodeURIComponent(spec.candidate_id)}`;
    const query = new URLSearchParams({strategy_id: spec.strategy_id, candidate_id: spec.candidate_id});
    void Promise.all([
      apiGet<StrategySourceResponse>(sourcePath, 15_000),
      apiGet<StrategyWorkbenchVersionList>(`/api/research/btc/strategy-versions?${query.toString()}`, 15_000),
    ]).then(([nextSource, nextVersions]) => {
      if (!active) return;
      setSource(nextSource);
      setVersions(nextVersions.versions ?? []);
      let restored = nextSource.content;
      try {
        restored = localStorage.getItem(`quantstation.crypto.strategy-editor-draft.v1:${nextSource.strategy_id}:${nextSource.candidate_id}:${nextSource.content_sha256}`) || nextSource.content;
      } catch {
        // Browser-local drafts are optional; canonical source remains authoritative.
      }
      setDraft(restored);
      setDraftSaved(restored !== nextSource.content);
    }).catch((error) => {
      if (active) {
        setSourceError(errorText(error));
        setDraft('');
      }
    });
    return () => { active = false; };
  }, [spec]);

  const canonicalSource = source?.content ?? '';
  const draftChanged = Boolean(source && draft !== canonicalSource);
  const sourceRunnable = Boolean(source?.canonical_signal_available && !draftChanged);
  const startBlocked = identityOnly || !spec || !source || !sourceRunnable || !canRunBacktest || busy;
  const effectiveStart = form.startDate || todayOffset(730);
  const effectiveEnd = form.endDate || todayOffset(0);
  const validRange = effectiveStart.length === 10 && effectiveEnd.length === 10 && effectiveStart <= effectiveEnd;
  const validCapital = Number.isFinite(form.capital) && form.capital >= 100;
  const canConfirm = !startBlocked && validRange && validCapital && !actionError;
  const lines = draft.split('\n');

  const resetDraft = () => {
    if (!source) return;
    setDraft(source.content);
    setDraftSaved(false);
    try {
      localStorage.removeItem(`quantstation.crypto.strategy-editor-draft.v1:${source.strategy_id}:${source.candidate_id}:${source.content_sha256}`);
    } catch {
      // Browser-local storage is best effort only.
    }
  };

  const saveDraft = () => {
    if (!source) return;
    try {
      localStorage.setItem(`quantstation.crypto.strategy-editor-draft.v1:${source.strategy_id}:${source.candidate_id}:${source.content_sha256}`, draft);
      setDraftSaved(true);
    } catch {
      setDraftSaved(false);
    }
  };

  const openDialog = () => {
    setActionError('');
    setPhase('idle');
    setDialogOpen(true);
    onProgressPhase?.('idle');
  };

  const confirmRun = async () => {
    if (!spec || !source || !canConfirm) return;
    setActionError('');
    onProgressPhase?.('preparing');
    setPhase('submitting');
    onProgressPhase?.('submitting');
    setDialogOpen(false);
    try {
      let version = versions.find((item) => (
        item.execution?.runnable === true
        && item.source_sha256 === source.content_sha256
        && (!item.source_content || item.source_content === source.content)
      ));
      if (!version) {
        version = await apiPost<StrategyWorkbenchVersion>('/api/research/btc/strategy-versions', {
          strategy_id: source.strategy_id,
          candidate_id: source.candidate_id,
          base_source_sha256: source.content_sha256,
          source_content: source.content,
          label: 'Crypto 受控 canonical 回测',
        });
        setVersions((current) => [version as StrategyWorkbenchVersion, ...current.filter((item) => item.version_id !== version?.version_id)]);
      }
      if (version.execution?.runnable !== true) {
        throw new Error(version.execution?.blocker || '当前源码版本未被服务认定为 canonical runnable；已 fail-closed。');
      }
      onFormChange({...form, startDate: effectiveStart, endDate: effectiveEnd, capital: form.capital});
      await onRun({versionId: version.version_id, start: effectiveStart, end: effectiveEnd, capital: form.capital}, setPhase);
      setDialogOpen(false);
    } catch (error) {
      setPhase('failed');
      onProgressPhase?.('failed');
      setDialogOpen(true);
      setActionError(errorText(error));
    }
  };

  return (
    <section className="crypto-strategy-editor" data-testid="btc-strategy-editor">
      <header className="crypto-strategy-editor-header">
        <div>
          <span className="crypto-strategy-editor-kicker">策略研究 · 受控回测</span>
          <strong>策略测试器</strong>
          <small>仅运行已注册策略；编辑草稿不会直接执行。</small>
        </div>
        <label className="crypto-strategy-editor-selector">
          <span>策略目录</span>
          <select aria-label="策略名" value={selectedCandidateId} onChange={(event: ValueEvent) => onStrategyChange(event.target.value)}>
            <option value="">选择已注册策略</option>
            {strategies.map((item) => <option key={item.candidate_id} value={item.candidate_id}>{strategyPresentationName(item.display_name, item.strategy_id) || item.candidate_id} · {strategyVariantLabel(item.candidate_id, item.strategy_id)}</option>)}
          </select>
        </label>
        <button type="button" className="crypto-strategy-editor-start" aria-label="运行本地研究回测" disabled={startBlocked} onClick={openDialog}>
          {busy ? '回测执行中…' : '开始回测'}
        </button>
      </header>

      {identityOnly ? <p className="crypto-strategy-editor-info" data-testid="strategy-source-identity-only" role="status">该候选仅有身份/参数与历史证据，没有可执行 canonical 源码；编辑和回测已禁用。</p> : null}
      {!identityOnly && sourceError ? <p className="crypto-strategy-editor-error" role="alert">源码读取失败：{sourceError}</p> : null}
      {draftChanged ? <p className="crypto-strategy-editor-warning" role="status">当前草稿与已注册源码不同；为保持受控执行，请先重置到已注册源码，或未来单独建设受限策略 DSL/sandbox。</p> : null}
      {!canRunBacktest ? <p className="crypto-strategy-editor-warning" role="status">当前策略目录或受控回测服务尚未就绪；回测入口保持禁用，不伪造运行。</p> : null}

      <details className="crypto-strategy-editor-meta">
        <summary>策略技术详情</summary>
        <div><span>策略标识 <code>{spec?.candidate_id || '—'}</code></span></div>
        <div><span>策略版本 <code>{spec?.strategy_version || '—'}</code></span></div>
        <div><span>源码校验值 <code>{source?.content_sha256 || '—'}</code></span></div>
      </details>
      <div className="crypto-strategy-editor-code">
        <ol aria-hidden="true">{lines.map((_, index) => <li key={index}>{index + 1}</li>)}</ol>
        <textarea aria-label="本机研究草稿源码" value={draft} onChange={(event: ValueEvent) => { setDraft(event.target.value); setDraftSaved(false); }} spellCheck={false} disabled={!source} />
      </div>
      <footer className="crypto-strategy-editor-footer">
        <span>{draftSaved ? '本机草稿已保存' : '草稿仅保存在本浏览器'}</span>
        <div>
          <button type="button" onClick={saveDraft} disabled={!source}>保存本机草稿</button>
          <button type="button" onClick={resetDraft} disabled={!source || !draftChanged}>重置到已注册源码</button>
        </div>
      </footer>

      {dialogOpen ? (
        <div className="crypto-strategy-editor-modal-backdrop" role="presentation">
          <section className="crypto-strategy-editor-modal" role="dialog" aria-modal="true" aria-label="配置并启动回测">
            <header><div><span className="crypto-strategy-editor-kicker">CONTROLLED RESEARCH RUN</span><h3>配置并启动回测</h3></div><button type="button" aria-label="关闭配置" onClick={() => { if (!busy) setDialogOpen(false); }}>×</button></header>
            <div className="crypto-strategy-editor-config-grid">
              <div className="crypto-strategy-editor-summary"><strong>当前策略</strong><code>{strategyPresentationName(spec?.display_name, spec?.strategy_id) || spec?.candidate_id || '—'} · {strategyVariantLabel(spec?.candidate_id, spec?.strategy_id)}</code><span>{spec?.strategy_version || '—'}</span><small>源码必须与 catalog canonical byte-for-byte 一致。</small></div>
              <label>交易方向<input aria-label="交易方向" disabled value={spec?.direction_policy || '由策略合同决定'} readOnly /></label>
              <label>交易标的<input aria-label="交易标的" disabled value="BTC-USDT-SWAP" readOnly /></label>
              <label>K线周期<input aria-label="K线周期" disabled value={spec?.timeframe || '1h'} readOnly /></label>
              <label>杠杆<input aria-label="杠杆" disabled value="由受控服务决定" readOnly /></label>
              <label>下单金额 / 仓位<input aria-label="下单金额 / 仓位" disabled value="由策略合同决定" readOnly /></label>
              <label>手续费<input aria-label="手续费" disabled value="由数据/服务合同读取" readOnly /></label>
              <label>滑点<input aria-label="滑点" disabled value="由数据/服务合同读取" readOnly /></label>
              <label>复利<input aria-label="复利" disabled value="当前接口未开放" readOnly /></label>
              <label>回测开始<input aria-label="回测开始" type="date" value={effectiveStart} onChange={(event: ValueEvent) => onFormChange({...form, startDate: event.target.value})} /></label>
              <label>回测结束<input aria-label="回测结束" type="date" value={effectiveEnd} onChange={(event: ValueEvent) => onFormChange({...form, endDate: event.target.value})} /></label>
              <label>初始资金<input aria-label="初始资金" type="number" min="100" value={form.capital} onChange={(event: ValueEvent) => onFormChange({...form, capital: Number(event.target.value)})} /></label>
            </div>
            {!validRange ? <p className="crypto-strategy-editor-error">回测区间无效：开始日期必须不晚于结束日期。</p> : null}
            {!validCapital ? <p className="crypto-strategy-editor-error">初始资金必须是至少 100 的有限数值。</p> : null}
            {actionError ? <p className="crypto-strategy-editor-error" role="alert">回测未启动：{actionError}</p> : null}
            <div className="crypto-strategy-editor-lifecycle" data-testid="btc-backtest-lifecycle" aria-live="polite">
              {phase === 'idle' ? '等待确认' : phase === 'preparing' ? '正在准备受控回测' : phase === 'submitting' ? '正在提交受控回测请求' : phase === 'computing' ? '受控服务计算中' : phase === 'polling' ? '后端仍在计算，正在只读获取结果' : phase === 'loading_results' ? '正在加载真实回测结果' : phase === 'completed' ? '回测完成' : '回测失败'}
            </div>
            <footer><span>只读 research-only；不启动 Demo、不触碰订单或 private endpoint。</span><div><button type="button" onClick={() => { if (!busy) setDialogOpen(false); }}>取消</button><button type="button" className="crypto-strategy-editor-confirm" disabled={!canConfirm} onClick={() => void confirmRun()}>确认并启动回测</button></div></footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}
