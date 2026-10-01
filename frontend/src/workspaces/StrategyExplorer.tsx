import {useEffect, useMemo, useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowsIn, ArrowsOut, CaretDown, ChartLineUp, FileCode, ListBullets, ShieldCheck, TerminalWindow} from '@phosphor-icons/react';

import {ApiError, apiGet, apiPost} from '../lib/api';
import {strategyPresentationName, strategySourceLabel, strategyVariantLabel} from '../lib/strategy-presentation';
import type {ChartSeriesPayload, StrategyInfo} from '../lib/view-model';
import {CostBreakdownChart, TradePnlChart} from './crypto/BacktestAnalyticsCharts';
import type {CanonicalBacktestReport, CanonicalTrade} from './crypto/canonical-report-types';
import type {LocalKlineResponse} from './crypto/demo-types';
import EquityPerformanceChart from './crypto/EquityPerformanceChart';
import StrategyDiscoveryCatalog, {type StrategyDiscoverySelection} from './crypto/StrategyDiscoveryCatalog';
import StrategyParameterHeatmap from './crypto/StrategyParameterHeatmap';
import {filterChartWindow, historicalProvenance, missingHistoricalSeries, shouldRequestSource, sourceContentHashesMatch, validStrategySource} from './crypto/strategy-history-provenance';
import {HistoricalPerformanceDetails, HistoricalRiskDetails, HistoricalTradeReview} from './crypto/StrategyTesterReport';
import type {BTCStrategyHistoryCatalog, BTCStrategyHistoryResponse} from './crypto/strategy-history-types';
import TradingViewChart, {type TradingCandle, type TradingMarker} from './crypto/TradingViewChart';
import './strategy-workbench.css';

export type StrategyExplorerProps = {strategies: StrategyInfo[]};

type WorkbenchStyle = Record<string, string | number | undefined>;
type WorkbenchNode = unknown;
type WorkbenchPointerEvent<T = Element> = {pointerId: number; clientX: number; clientY: number; currentTarget: T; preventDefault: () => void};
type WorkbenchKeyboardEvent<T = Element> = {key: string; currentTarget: T; preventDefault: () => void};
type SelectEvent = {target: {value: string}};
type DockTab = 'logs' | 'runs' | 'trades' | 'performance' | 'safety';
type FocusPanel = 'code' | 'performance' | null;
type StrategySourceSection = {symbol: string; source_ref: string; content: string; content_sha256: string};
type StrategySourceResponse = {
  strategy_id: string;
  candidate_id: string;
  source_ref: string;
  content_sha256: string;
  content: string;
  sections: StrategySourceSection[];
  canonical_signal_available: boolean;
};
type StrategyWorkbenchBacktest = {
  run_id: string;
  status: string;
  error: string;
  report: {summary: Record<string, unknown>; chart: Record<string, unknown>; report_scope: string} | null;
};
type StrategyWorkbenchVersion = {
  version_id: string;
  label: string;
  source_content: string;
  source_sha256: string;
  execution: {runnable: boolean; canonical_source_match: boolean; blocker: string};
  latest_backtest: StrategyWorkbenchBacktest | null;
  approved_research_only: boolean;
  selected_runnable_candidate: boolean;
  selection_scope: string;
};
type StrategyWorkbenchVersionList = {versions: StrategyWorkbenchVersion[]; selected_version_id: string; safety: Record<string, boolean>};

const HISTORY_CATALOG_PATH = '/api/research/btc/strategy-history/catalog';
const COMPLETED_KLINES_PATH = '/api/research/btc/demo-paper/klines?limit=2000';
const GET_TIMEOUT_MS = 30_000;
const LAYOUT_KEY = 'quantstation.strategy-workbench-layout.v1';
const DEFAULT_LAYOUT = {left: 18, code: 41, dock: 180};
const MIN_LEFT = 240;
const MAX_LEFT = 320;
const MIN_CODE = 460;
const MIN_PERFORMANCE = 420;
const MIN_DOCK = 180;
const MAX_DOCK = 360;
const SOURCE_DRAFT_KEY = 'quantstation.strategy-workbench-source-draft.v1';
const SELECTION_KEY = 'quantstation.strategy-workbench-selection.v1';

let catalogCache: BTCStrategyHistoryCatalog | null = null;
let catalogRequest: Promise<BTCStrategyHistoryCatalog> | null = null;
let klineCache: LocalKlineResponse | null = null;
let klineRequest: Promise<LocalKlineResponse> | null = null;

function loadCatalog(): Promise<BTCStrategyHistoryCatalog> {
  if (catalogCache) return Promise.resolve(catalogCache);
  if (catalogRequest) return catalogRequest;
  const request = apiGet<BTCStrategyHistoryCatalog>(HISTORY_CATALOG_PATH, GET_TIMEOUT_MS).then((payload) => {
    catalogCache = payload;
    return payload;
  });
  catalogRequest = request;
  const clear = () => { if (catalogRequest === request) catalogRequest = null; };
  void request.then(clear, clear);
  return request;
}

function loadCompletedKlines(): Promise<LocalKlineResponse> {
  if (klineCache) return Promise.resolve(klineCache);
  if (klineRequest) return klineRequest;
  const request = apiGet<LocalKlineResponse>(COMPLETED_KLINES_PATH, GET_TIMEOUT_MS).then((payload) => {
    klineCache = payload;
    return payload;
  });
  klineRequest = request;
  const clear = () => { if (klineRequest === request) klineRequest = null; };
  void request.then(clear, clear);
  return request;
}

export default function StrategyExplorer({strategies}: StrategyExplorerProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [catalog, setCatalog] = useState<BTCStrategyHistoryCatalog | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [selected, setSelected] = useState<StrategyDiscoverySelection | null>(null);
  const [details, setDetails] = useState<BTCStrategyHistoryResponse | null>(null);
  const [detailsError, setDetailsError] = useState('');
  const [detailsRetry, setDetailsRetry] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [runChart, setRunChart] = useState<ChartSeriesPayload | null>(null);
  const [runChartError, setRunChartError] = useState('');
  const [completedKlines, setCompletedKlines] = useState<LocalKlineResponse | null>(null);
  const [completedKlinesError, setCompletedKlinesError] = useState('');
  const [source, setSource] = useState<StrategySourceResponse | null>(null);
  const [sourceError, setSourceError] = useState('');
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceRetry, setSourceRetry] = useState(0);
  const [versions, setVersions] = useState<StrategyWorkbenchVersion[]>([]);
  const [versionsError, setVersionsError] = useState('');
  const [dockTab, setDockTab] = useState<DockTab>('runs');
  const [dockCollapsed, setDockCollapsed] = useState(true);
  const [focused, setFocused] = useState<FocusPanel>(null);
  const [analysisTab, setAnalysisTab] = useState<'history' | 'parameters'>('history');
  const [layout, setLayout] = useState(readLayout);

  useEffect(() => {
    let active = true;
    setCatalogError('');
    void loadCatalog().then(
      (payload) => { if (active) setCatalog(payload); },
      (error) => { if (active) setCatalogError(historyErrorMessage(error, '历史目录')); },
    );
    return () => { active = false; };
  }, [catalogRetry]);

  useEffect(() => {
    if (selected || !catalog?.candidates[0]) return;
    const saved = readSelection();
    const candidate = (saved && catalog.candidates.find((item) => item.strategy_id === saved.strategyId && item.candidate_id === saved.candidateId)) || catalog.candidates[0];
    setSelected({
      identity: `btc:${candidate.strategy_id}:${candidate.candidate_id}`,
      displayName: strategyPresentationName(candidate.display_name, candidate.strategy_id),
      description: candidate.relationship_label,
      sources: ['BTC history catalog'],
      evidence: `research-only · ${candidate.history_run_count} history runs`,
      strategyId: candidate.strategy_id,
      candidateId: candidate.candidate_id,
      metrics: {annual: candidate.annual_return_pct, total: candidate.total_return_pct, drawdown: candidate.max_drawdown_pct},
      detailPath: historyLink(candidate.strategy_id, candidate.candidate_id),
    });
  }, [catalog, selected]);

  useEffect(() => {
    if (!selected?.strategyId || !selected.candidateId) {
      setDetails(null);
      setDetailsError('');
      setSelectedRunId('');
      return;
    }
    let active = true;
    setDetails(null);
    setDetailsError('');
    const query = selectedRunId ? `?run_id=${encodeURIComponent(selectedRunId)}` : '';
    const path = `/api/research/btc/strategy-history/${encodeURIComponent(selected.strategyId)}/${encodeURIComponent(selected.candidateId)}${query}`;
    void apiGet<BTCStrategyHistoryResponse>(path, GET_TIMEOUT_MS).then(
      (payload) => { if (active) setDetails(payload); },
      (error) => { if (active) setDetailsError(historyErrorMessage(error, '历史报告')); },
    );
    return () => { active = false; };
  }, [selected?.candidateId, selected?.strategyId, selectedRunId, detailsRetry]);

  const report = details?.canonical_report ?? null;
  const effectiveRunId = selectedRunId || details?.selected_run_id || '';
  const sourceRunId = report?.source_run_id || details?.history_runs.find((run) => run.run_id === effectiveRunId)?.source_run_id || '';

  useEffect(() => {
    if (!sourceRunId) {
      setRunChart(null);
      setRunChartError('');
      return;
    }
    let active = true;
    setRunChart(null);
    setRunChartError('');
    void apiGet<ChartSeriesPayload>(`/api/runs/${encodeURIComponent(sourceRunId)}/chart`, GET_TIMEOUT_MS).then(
      (payload) => {
        if (!active) return;
        if (isChartPayload(payload)) setRunChart(payload);
        else setRunChartError('published run chart unavailable');
      },
      (error) => { if (active) setRunChartError(historyErrorMessage(error, '历史图表')); },
    );
    return () => { active = false; };
  }, [sourceRunId]);

  useEffect(() => {
    if (!selected?.candidateId) return;
    let active = true;
    setCompletedKlinesError('');
    void loadCompletedKlines().then(
      (payload) => { if (active) setCompletedKlines(payload); },
      (error) => { if (active) setCompletedKlinesError(errorMessage(error)); },
    );
    return () => { active = false; };
  }, [selected?.candidateId]);

  useEffect(() => {
    if (!selected?.strategyId || !selected.candidateId) {
      setSource(null);
      setSourceError('');
      setSourceLoading(false);
      return;
    }
    let active = true;
    setSource(null);
    setSourceError('');
    setSourceLoading(false);
    if (!shouldRequestSource(selected)) return;
    setSourceLoading(true);
    const path = `/api/research/btc/strategy-source/${encodeURIComponent(selected.strategyId)}/${encodeURIComponent(selected.candidateId)}`;
    void apiGet<StrategySourceResponse>(path, GET_TIMEOUT_MS).then(async (payload) => {
      const valid = validStrategySource(payload, selected) && await sourceContentHashesMatch(payload);
      if (active) { setSourceLoading(false); if (valid) setSource(payload); else setSourceError('源码身份、哈希或安全校验失败；未展示或启用编辑。'); }
    }).catch((error) => { if (active) { setSourceLoading(false); setSourceError(errorMessage(error)); } });
    return () => { active = false; };
  }, [selected?.candidateId, selected?.strategyId, selected?.canonicalSignalAvailable, sourceRetry]);

  useEffect(() => {
    if (!selected?.strategyId || !selected.candidateId) {
      setVersions([]);
      setVersionsError('');
      return;
    }
    let active = true;
    setVersionsError('');
    setVersions([]);
    const query = new URLSearchParams({strategy_id: selected.strategyId, candidate_id: selected.candidateId});
    void apiGet<StrategyWorkbenchVersionList>(`/api/research/btc/strategy-versions?${query.toString()}`, GET_TIMEOUT_MS).then(
      (payload) => { if (active) setVersions(payload.versions); },
      (error) => { if (active) { setVersions([]); setVersionsError(errorMessage(error)); } },
    );
    return () => { active = false; };
  }, [selected?.candidateId, selected?.strategyId]);

  useEffect(() => {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch { /* browser preference only */ }
  }, [layout]);

  const style = useMemo(() => ({
    '--strategy-left': `${layout.left}%`,
    '--strategy-code': `${layout.code}%`,
    '--strategy-dock-height': `${dockCollapsed ? 38 : layout.dock}px`,
  }) as WorkbenchStyle, [dockCollapsed, layout]);
  const resetLayout = () => { setLayout(DEFAULT_LAYOUT); setDockCollapsed(false); setFocused(null); };
  const adjustVertical = (side: 'left' | 'code', delta: number) => {
    const width = rootRef.current?.clientWidth || 1440;
    const minLeft = MIN_LEFT / width * 100;
    const maxLeft = MAX_LEFT / width * 100;
    const minCode = MIN_CODE / width * 100;
    const minPerformance = MIN_PERFORMANCE / width * 100;
    setLayout((current) => side === 'left'
      ? {...current, left: clamp(current.left + delta, minLeft, Math.min(maxLeft, 100 - current.code - minPerformance))}
      : {...current, code: clamp(current.code + delta, minCode, 100 - current.left - minPerformance)});
  };
  const resizeVertical = (side: 'left' | 'code', event: WorkbenchPointerEvent<HTMLDivElement>) => {
    if (window.innerWidth < 1120) return;
    const startX = event.clientX;
    const width = rootRef.current?.clientWidth || 1;
    const onMove = (move: PointerEvent) => adjustVertical(side, (move.clientX - startX) / width * 100);
    const onUp = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp); };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, {once: true});
  };
  const resizeDock = (event: WorkbenchPointerEvent<HTMLDivElement>) => {
    if (window.innerWidth < 760) return;
    const startY = event.clientY;
    const startDock = layout.dock;
    const onMove = (move: PointerEvent) => setLayout((current) => ({...current, dock: clamp(startDock + startY - move.clientY, MIN_DOCK, MAX_DOCK)}));
    const onUp = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp); };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, {once: true});
  };
  const select = (value: StrategyDiscoverySelection) => {
    setSelected(value);
    setSelectedRunId('');
    setDockTab(value.candidateId ? 'runs' : 'safety');
    if (value.strategyId && value.candidateId) {
      try { localStorage.setItem(SELECTION_KEY, JSON.stringify({strategyId: value.strategyId, candidateId: value.candidateId})); } catch { /* browser preference only */ }
    }
  };

  return <main ref={rootRef} className={`strategy-workbench ${focused ? `is-focused-${focused}` : ''}`} style={style} data-testid="strategy-workbench">
    <header className="strategy-workbench-commandbar">
      <div className="strategy-workbench-command-title"><span>策略工作台</span><strong>{selected?.displayName || '选择策略'}</strong></div>
      <dl>
        <div><dt>候选 / run</dt><dd>{selected?.candidateId || '未发布'}{details?.selected_run_id ? ` · ${details.selected_run_id}` : ''}</dd></div>
        <div><dt>历史数据 / 频率</dt><dd>{historicalProvenance(details).exchange} · {historicalProvenance(details).interval}</dd></div>
        <div><dt>初始资金</dt><dd>{text(details?.canonical?.initial_capital) || '未发布'}</dd></div>
      </dl>
      <span className="strategy-workbench-safety">RESEARCH ONLY · ORDER / PAPER / LIVE = FALSE</span>
    </header>

    <section className="strategy-workbench-main">
      <aside className="strategy-workbench-pane strategy-workbench-catalog" aria-label="策略目录">
        <div className="strategy-workbench-pane-title"><span>策略 / 回测目录</span><small>{catalog?.candidates.length ?? 0} BTC candidates</small></div>
        <StrategyDiscoveryCatalog strategies={strategies} btcHistory={catalog} btcHistoryError={catalogError} presentation="tree" selectedIdentity={selected?.identity} onSelect={select} />
        <div className="strategy-workbench-history-status" data-testid="btc-strategy-history-catalog">
          {catalog ? `${catalog.candidates.length} 个候选 · ${catalog.decision}` : catalogError || '正在加载 BTC 历史目录'}
          {catalogError ? <button type="button" data-testid="btc-strategy-history-retry" onClick={() => setCatalogRetry((value) => value + 1)}>重试</button> : null}
        </div>
      </aside>
      <Splitter axis="vertical" label="调整目录与策略定义宽度" onPointerDown={(event) => resizeVertical('left', event)} onKeyDown={(event) => separatorKey(event, (delta) => adjustVertical('left', delta), resetLayout)} onReset={resetLayout} />
      <section className="strategy-workbench-pane strategy-workbench-code" aria-label="策略代码与本机研究草稿">
        <PaneTitle title="策略代码 / 本机研究草稿" icon={<FileCode size={16} />} focused={focused === 'code'} onFocus={() => setFocused((value) => value === 'code' ? null : 'code')} />
        <StrategyDefinition selection={selected} history={details} source={source?.strategy_id === selected?.strategyId && source?.candidate_id === selected?.candidateId ? source : null} sourceError={sourceError} sourceLoading={sourceLoading} onSourceRetry={() => setSourceRetry((value) => value + 1)} versions={versions} versionsError={versionsError} onVersionsChange={setVersions} />
      </section>
      <Splitter axis="vertical" label="调整策略定义与绩效宽度" onPointerDown={(event) => resizeVertical('code', event)} onKeyDown={(event) => separatorKey(event, (delta) => adjustVertical('code', delta), resetLayout)} onReset={resetLayout} />
      <section className="strategy-workbench-pane strategy-workbench-performance" aria-label="回测绩效">
        <PaneTitle title="分析 / 真实回测数据" icon={<ChartLineUp size={16} />} focused={focused === 'performance'} onFocus={() => setFocused((value) => value === 'performance' ? null : 'performance')} />
        <div className="strategy-analysis-tabs" role="tablist" aria-label="策略分析视图"><button type="button" role="tab" aria-selected={analysisTab === 'history'} onClick={() => setAnalysisTab('history')}>历史回测</button><button type="button" role="tab" aria-selected={analysisTab === 'parameters'} onClick={() => setAnalysisTab('parameters')}>参数稳定性</button></div>
        {analysisTab === 'parameters' ? <StrategyParameterHeatmap strategyId={selected?.strategyId} candidateId={selected?.candidateId} /> : <PerformancePanel key={`${selected?.identity}:${effectiveRunId}`} selection={selected} details={details} error={detailsError} report={report} selectedRunId={selectedRunId} onRunSelect={setSelectedRunId} onRetry={() => setDetailsRetry((value) => value + 1)} runChart={runChart} runChartError={runChartError} completedKlines={completedKlines} completedKlinesError={completedKlinesError} />}
      </section>
    </section>

    <Splitter axis="horizontal" label="调整底部信息栏高度" onPointerDown={resizeDock} onKeyDown={(event) => separatorKey(event, (delta) => setLayout((current) => ({...current, dock: clamp(current.dock + delta * 3, MIN_DOCK, MAX_DOCK)})), resetLayout)} onReset={resetLayout} />
    <section className={`strategy-workbench-dock ${dockCollapsed ? 'is-collapsed' : ''}`} aria-label="策略证据与记录">
      <header>
        <div className="strategy-workbench-dock-tabs" role="tablist" aria-label="策略证据标签">
          {([['logs', '日志'], ['runs', '回测记录'], ['trades', '交易明细'], ['performance', '绩效指标'], ['safety', '安全与证据']] as [DockTab, string][]).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={dockTab === key} onClick={() => { setDockCollapsed(false); setDockTab(key); }}>{label}</button>)}
        </div>
        <button type="button" className="strategy-workbench-icon-button" aria-label={dockCollapsed ? '展开底部信息栏' : '折叠底部信息栏'} onClick={() => setDockCollapsed((value) => !value)}>{dockCollapsed ? <CaretDown size={17} /> : <ArrowsIn size={17} />}</button>
      </header>
      {!dockCollapsed ? <DockContent tab={dockTab} details={details} error={detailsError} report={report} selection={selected} sourceRunId={sourceRunId} version={versions[0] || null} /> : null}
    </section>
  </main>;
}

function PaneTitle({title, icon, focused, onFocus}: {title: string; icon: WorkbenchNode; focused: boolean; onFocus: () => void}) {
  return <header className="strategy-workbench-pane-title"><span>{icon}{title}</span><button type="button" className="strategy-workbench-icon-button" aria-label={focused ? `退出${title}聚焦` : `聚焦${title}`} onClick={onFocus}>{focused ? <ArrowsOut size={16} /> : <ArrowsIn size={16} />}</button></header>;
}

function Splitter({axis, label, onPointerDown, onKeyDown, onReset}: {axis: 'vertical' | 'horizontal'; label: string; onPointerDown: (event: WorkbenchPointerEvent<HTMLDivElement>) => void; onKeyDown: (event: WorkbenchKeyboardEvent<HTMLDivElement>) => void; onReset: () => void}) {
  return <div className={`strategy-workbench-splitter ${axis}`} role="separator" aria-label={label} aria-orientation={axis === 'vertical' ? 'vertical' : 'horizontal'} tabIndex={0} onPointerDown={onPointerDown} onKeyDown={onKeyDown} onDoubleClick={(event: WorkbenchPointerEvent<HTMLDivElement>) => { event.currentTarget.blur(); onReset(); }} />;
}

function StrategyDefinition({selection, history, source, sourceError, sourceLoading, onSourceRetry, versions, versionsError, onVersionsChange}: {selection: StrategyDiscoverySelection | null; history: BTCStrategyHistoryResponse | null; source: StrategySourceResponse | null; sourceError: string; sourceLoading: boolean; onSourceRetry: () => void; versions: StrategyWorkbenchVersion[]; versionsError: string; onVersionsChange: (versions: StrategyWorkbenchVersion[]) => void}) {
  const params = history?.details.params;
  if (!selection) return <Empty title="选择一个策略目录项" detail="真实目录数据到达后才展示策略定义与历史回测。" />;
  const sourcePending = sourceLoading || (shouldRequestSource(selection) && !source && !sourceError);
  return <div className="strategy-workbench-definition">
    <div className="strategy-workbench-filetab"><FileCode size={14} />{source?.source_ref || 'strategy.identity'} · 当前源码<span>{source ? '标准源码只读 · 本地草稿可编辑' : sourcePending ? '正在读取注册源码' : '源码暂不可用'}</span></div>
    <h1>{selection.displayName}</h1><p>{selection.description}</p>
    <p className="strategy-workbench-variant">变体：{selection.variantLabel || strategyVariantLabel(selection.candidateId, selection.strategyId)} · {selection.capabilityText || '能力状态：未知'}</p>
    <dl className="strategy-workbench-metadata">
      <div><dt>稳定身份</dt><dd><code>{selection.identity}</code></dd></div>
      <div><dt>目录来源</dt><dd>{selection.sources.map(strategySourceLabel).join(' + ') || '未发布'}</dd></div>
      <div><dt>历史报告代码版本</dt><dd>{history?.source.source_code_commit || '未发布'}（不等于下方当前注册源码）</dd></div>
      <div><dt>报告 SHA</dt><dd><code>{history?.source.report_sha256 || '未发布'}</code></dd></div>
      <div><dt>证据</dt><dd>{selection.evidence || '未发布'}</dd></div>
    </dl>
    {source ? <SourceDraftEditor source={source} version={versions[0] || null} versionsError={versionsError} onVersionChange={(version) => onVersionsChange([version, ...versions.filter((item) => item.version_id !== version.version_id)])} /> : sourcePending ? <section aria-live="polite" className="strategy-workbench-source-unavailable" data-testid="strategy-source-loading">正在通过只读接口核验该候选的当前注册源码…</section> : <section className="strategy-workbench-source-unavailable" data-testid="strategy-workbench-source-unavailable"><FileCode size={20} /><div><strong>{selection.canonicalSignalAvailable === false ? '该候选仅有身份/参数与历史证据' : '当前注册源码尚未取得'}</strong><span>{selection.canonicalSignalAvailable === false ? '没有可执行 canonical 源码；代码编辑与回测保持禁用。' : sourceError || '等待只读接口核验；不会用历史参数生成源码。'}</span>{shouldRequestSource(selection) ? <button type="button" onClick={onSourceRetry}>重新读取源码</button> : null}</div></section>}
    <section className="strategy-workbench-params"><h2>已发布参数</h2>{params && Object.keys(params).length ? <pre>{JSON.stringify(params, null, 2)}</pre> : <p>未发布</p>}</section>
  </div>;
}

function SourceDraftEditor({source, version, versionsError, onVersionChange}: {source: StrategySourceResponse; version: StrategyWorkbenchVersion | null; versionsError: string; onVersionChange: (version: StrategyWorkbenchVersion) => void}) {
  const draftKey = `${SOURCE_DRAFT_KEY}:${source.strategy_id}:${source.candidate_id}:${source.content_sha256}`;
  const [draft, setDraft] = useState(source.content);
  const [saved, setSaved] = useState(false);
  const [label, setLabel] = useState('本机研究版本');
  const [backtestStart, setBacktestStart] = useState('2024-01-01T00:00:00Z');
  const [backtestEnd, setBacktestEnd] = useState('2025-01-01T00:00:00Z');
  const [action, setAction] = useState('');
  const [actionError, setActionError] = useState('');
  useEffect(() => {
    let restored = source.content;
    try { restored = localStorage.getItem(draftKey) || source.content; } catch { /* browser draft is optional */ }
    setDraft(restored);
    setSaved(restored !== source.content);
  }, [draftKey, source.content]);
  const lines = draft.split('\n');
  const saveVersion = async () => {
    setAction('正在保存不可变研究版本…'); setActionError('');
    try {
      const created = await apiPost<StrategyWorkbenchVersion>('/api/research/btc/strategy-versions', {strategy_id: source.strategy_id, candidate_id: source.candidate_id, base_source_sha256: source.content_sha256, source_content: draft, label});
      onVersionChange(created); setAction(`已保存 ${created.version_id}`);
    } catch (error) { setAction(''); setActionError(errorMessage(error)); }
  };
  const runBacktest = async () => {
    if (!version) return;
    setAction('正在调用 allowlisted registered backtest…'); setActionError('');
    try {
      const run = await apiPost<StrategyWorkbenchBacktest>(`/api/research/btc/strategy-versions/${encodeURIComponent(version.version_id)}/backtests`, {start: backtestStart, end: backtestEnd, capital: 100000, data_version: ''});
      onVersionChange({...version, latest_backtest: run}); setAction(run.status === 'completed' ? `回测完成 ${run.run_id}` : `回测失败 ${run.run_id}`);
    } catch (error) { setAction(''); setActionError(errorMessage(error)); }
  };
  const approve = async () => {
    if (!version) return;
    setAction('正在记录研究批准…'); setActionError('');
    try { const next = await apiPost<StrategyWorkbenchVersion>(`/api/research/btc/strategy-versions/${encodeURIComponent(version.version_id)}/approve`, {confirmation: 'APPROVE RESEARCH VERSION'}); onVersionChange(next); setAction('已批准为 research-only 候选。'); } catch (error) { setAction(''); setActionError(errorMessage(error)); }
  };
  const selectCandidate = async () => {
    if (!version) return;
    setAction('正在记录可运行候选选择…'); setActionError('');
    try { const next = await apiPost<StrategyWorkbenchVersion>(`/api/research/btc/strategy-versions/${encodeURIComponent(version.version_id)}/select-runnable`, {confirmation: 'SELECT RUNNABLE CANDIDATE'}); onVersionChange(next); setAction('已选择为后续 Demo 读取候选；未启动 Demo。'); } catch (error) { setAction(''); setActionError(errorMessage(error)); }
  };
  const runnable = version?.execution.runnable === true;
  return <section className="strategy-workbench-source-editor" data-testid="strategy-workbench-source-editor">
    <header><span>CANONICAL SOURCE READ ONLY · LOCAL DRAFT EDITABLE · NOT EXECUTABLE</span><code>{source.content_sha256}</code></header>
    <div className="strategy-workbench-source-sections">{source.sections.map((section) => <span key={section.symbol}><code>{section.symbol}</code> · {section.source_ref}</span>)}</div>
    <div className="strategy-workbench-code-surface"><ol aria-hidden="true">{lines.map((_, index) => <li key={index}>{index + 1}</li>)}</ol><textarea aria-label="本机研究草稿源码" value={draft} onChange={(event: {target: {value: string}}) => { setDraft(event.target.value); setSaved(false); }} spellCheck={false} /></div>
    <footer><button type="button" onClick={() => { try { localStorage.setItem(draftKey, draft); setSaved(true); } catch { setSaved(false); } }}>保存本机草稿</button><button type="button" onClick={() => { try { localStorage.removeItem(draftKey); } catch { /* browser draft is optional */ } setDraft(source.content); setSaved(false); }}>重置到 current source</button><small>{saved ? 'LOCAL DRAFT 已保存到此浏览器。' : '草稿未保存；不会修改受控 Python、回测或交易。'}</small></footer>
    <section className="strategy-workbench-version-flow" data-testid="strategy-workbench-version-flow">
      <header><strong>新回测设置 / 已注册策略</strong><span>独立创建新运行，不会更改右侧历史报告；编辑源码不会被执行。</span></header>
      <div className="strategy-workbench-provenance" data-testid="strategy-new-backtest-source"><strong>数据绑定：本机 SQLite · Binance 现货 · BTCUSDT · 1h</strong><p>当前 runner 读取配置的本机行情库中的当前数据；这里不能切换为 OKX 或在线下载，缺失区间须由数据任务先准备。默认 data_version 是描述性标识，不是内容哈希或冻结快照。</p><p>下方时间为新回测 UTC 区间，初始资金 100,000、杠杆 1×；不控制右侧历史报告或参考 K 线。先保存未修改的注册源码版本才能运行；当前库数据不保证重现旧报告。</p></div>
      <div className="strategy-workbench-version-create"><label>版本名称<input aria-label="研究版本名称" value={label} onChange={(event: SelectEvent) => setLabel(event.target.value)} maxLength={120} /></label><button type="button" onClick={() => void saveVersion()}>保存为不可变研究版本</button></div>
      {version ? <div className="strategy-workbench-version-status"><code>{version.version_id}</code><span>{runnable ? 'CANONICAL SOURCE MATCH · RUNNABLE' : `DRAFT ONLY · ${version.execution.blocker || 'not runnable'}`}</span><small>{version.selected_runnable_candidate ? '已选择为后续 Demo 读取候选；Demo 未启动。' : version.approved_research_only ? '已批准为 research-only 候选；尚未选择。' : '未批准；保持 research-only。'}</small></div> : <p>尚无不可变版本。先保存当前 canonical 或本机草稿。</p>}
      <div className="strategy-workbench-version-actions"><label>开始<input aria-label="回测开始时间" value={backtestStart} onChange={(event: SelectEvent) => setBacktestStart(event.target.value)} /></label><label>结束<input aria-label="回测结束时间" value={backtestEnd} onChange={(event: SelectEvent) => setBacktestEnd(event.target.value)} /></label><button type="button" disabled={!runnable} onClick={() => void runBacktest()}>运行已注册策略回测</button><button type="button" disabled={!version?.latest_backtest || version.latest_backtest.status !== 'completed'} onClick={() => void approve()}>批准 research-only 候选</button><button type="button" disabled={!version?.approved_research_only} onClick={() => void selectCandidate()}>选择可运行候选</button></div>
      {version?.latest_backtest ? <div className="strategy-workbench-version-report" data-testid="strategy-workbench-version-report"><strong>{version.latest_backtest.status} · {version.latest_backtest.run_id}</strong>{version.latest_backtest.report ? <MetricGrid entries={Object.entries(version.latest_backtest.report.summary).slice(0, 8)} /> : <span>{version.latest_backtest.error || '报告未发布'}</span>}</div> : null}
      {action ? <p className="strategy-workbench-version-action">{action}</p> : null}{actionError || versionsError ? <p className="strategy-workbench-version-error">{actionError || versionsError}</p> : null}
      <small className="strategy-workbench-version-safety">仅调用已注册策略 runner；不 eval/exec 草稿。paper/live/order/private/transfer/withdraw/demo_start=false。</small>
    </section>
  </section>;
}

function PerformancePanel({selection, details, error, report, selectedRunId, onRunSelect, onRetry, runChart, runChartError, completedKlines, completedKlinesError}: {key?: string; selection: StrategyDiscoverySelection | null; details: BTCStrategyHistoryResponse | null; error: string; report: CanonicalBacktestReport | null; selectedRunId: string; onRunSelect: (runId: string) => void; onRetry: () => void; runChart: ChartSeriesPayload | null; runChartError: string; completedKlines: LocalKlineResponse | null; completedKlinesError: string}) {
  const [chartSource, setChartSource] = useState<'auto' | 'run' | 'reference'>('auto');
  const [chartStart, setChartStart] = useState('');
  const [chartEnd, setChartEnd] = useState('');
  if (!selection) return <Empty title="未选择历史候选" detail="通用策略没有报告时，页面不会生成收益曲线或交易明细。" />;
  if (!selection.candidateId) return <Empty title="没有已发布历史报告" detail="该策略仅有统一目录元数据。" link={selection.detailPath} />;
  if (error) {
    const unavailable = error.includes('503');
    return <Empty
      title={unavailable ? '历史报告暂不可用' : '历史报告不可用'}
      detail={unavailable ? '历史报告目录未配置、尚未发布或暂不可读取（HTTP 503）。请检查报告配置后重新读取。未生成占位指标、曲线或交易标记。' : '读取历史报告失败；未生成占位指标、曲线或交易标记。'}
      retry={onRetry}
    />;
  }
  if (!details || !report) return <Empty title="正在加载历史报告" detail="GET 详情中；摘要不会冒充连续 ledger、fills 或完整 series。" />;
  const loadedMarket = chooseMarketChart(runChart, completedKlines, chartSource);
  const windowed = filterChartWindow(loadedMarket.candles, chartStart, chartEnd);
  const market = {...loadedMarket, candles: windowed.candles};
  const provenance = historicalProvenance(details);
  const missingSeries = missingHistoricalSeries(report.series);
  const canonical = canonicalTradeMarkers(report.series.trades, market.candles);
  const published = publishedMarkers(runChart, market.candles);
  const review = historicalReviewMarkers(details.details.return_concentration, market.candles);
  const baseMarkers = canonical.total ? canonical.markers : published;
  const markers = market.isReference ? [] : [...baseMarkers, ...review.markers];
  const publishedLabel = runChart?.markers.length ? `已发布标记 ${published.length}/${runChart.markers.length}` : '';
  const markerLabel = market.isReference ? '参考行情不叠加历史成交；交易复核见下方表格' : `${canonical.total ? `canonical 交易 ${canonical.aligned}/${canonical.total}` : publishedLabel || '已发布标记未发布'} · 历史复核 ${review.aligned}/${review.total}（非 canonical fills）`;
  const donchianAvailable = market.candles.length >= 120;
  const marketIndicators = `${donchianAvailable ? '参考 Donchian（120 根，非策略参数）' : '参考 Donchian 数据不足'} · ${market.hasVolume ? '成交量' : '成交量未发布'}`;
  const metrics = report.derived_metrics;
  return <div className="strategy-workbench-performance-body" data-testid="strategy-workbench-report">
    <div className="strategy-workbench-run-select"><label>历史 run<select value={selectedRunId || details.selected_run_id} onChange={(event: SelectEvent) => onRunSelect(event.target.value)}>{details.history_runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.label || run.run_id}</option>)}</select></label><Link to={historyLink(details.strategy_id, details.candidate_id)}>查看完整历史回测与详细报告</Link></div>
    <section className="strategy-workbench-provenance" data-testid="strategy-history-provenance">
      <strong>这些回测结果从哪里来？</strong><p>以下指标读取已发布历史报告，不是在打开页面时临时回测。{details.relationship_label}</p>
      <dl><div><dt>历史行情来源</dt><dd>{provenance.exchange} · {provenance.symbol}</dd></div><div><dt>原始 / 决策频率</dt><dd>{provenance.interval}</dd></div><div><dt>首个完整决策 bar</dt><dd>{provenance.start}</dd></div><div><dt>最后完整决策 bar</dt><dd>{provenance.end}</dd></div><div><dt>成交模型</dt><dd>{provenance.execution}</dd></div><div><dt>报告生成时间</dt><dd>{provenance.generated}</dd></div></dl>
      <p>历史区间与数据源是这份报告的固定条件。切换下方 K 线视窗不会重算收益；改变回测条件需要在源码面板的“新回测设置”中创建新运行。</p>
      <details><summary>报告版本与证据</summary><p>历史代码：{provenance.code} · 报告 SHA-256：<code>{provenance.reportHash}</code></p><p>历史研究 / 已参与选参；不是 current-HEAD 重跑结果或交易准入证据。</p></details>
    </section>
    <MetricGrid entries={fullMetricEntries(details.details.full_metrics, metrics as Record<string, unknown>, report)} />
    <section className="strategy-workbench-chart-controls" aria-label="K线来源与显示区间">
      <label>K 线来源<select aria-label="K线来源" value={chartSource} onChange={(event: SelectEvent) => { setChartSource(event.target.value as 'auto' | 'run' | 'reference'); setChartStart(''); setChartEnd(''); }}><option value="auto">自动：优先运行 K 线，否则参考行情</option><option value="run" disabled={!runChart?.candles.length}>该历史 run 已发布 K 线{!runChart?.candles.length ? '（未发布）' : ''}</option><option value="reference" disabled={!completedKlines?.rows.length}>本机参考行情（非该报告输入）</option></select></label>
      <label>显示开始（UTC）<input type="date" aria-label="K线显示开始" value={chartStart} onChange={(event: SelectEvent) => setChartStart(event.target.value)} /></label><label>显示结束（UTC）<input type="date" aria-label="K线显示结束" value={chartEnd} onChange={(event: SelectEvent) => setChartEnd(event.target.value)} /></label><button type="button" onClick={() => { setChartStart(''); setChartEnd(''); }}>显示全部已载入 K 线</button>
      <p data-testid="strategy-chart-window">仅筛选已载入的 {loadedMarket.candles.length} 根 K 线，当前显示 {market.candles.length} 根；不下载、不回测、不改变上方指标。</p>
      <p>{market.isReference ? '当前为独立参考行情，不是上方历史报告的 Binance 输入，不能用它验证上述收益。' : '当前图由所选 run 端点发布；仅改变显示区间。'} {loadedMarket.candles.length ? `已载入 UTC：${new Date(loadedMarket.candles[0].time * 1000).toISOString()} — ${new Date(loadedMarket.candles[loadedMarket.candles.length - 1].time * 1000).toISOString()}` : ''}</p>
    </section>
    <section className="strategy-workbench-market" data-testid="strategy-workbench-market"><header><span data-testid="strategy-workbench-market-indicators">BTC K 线 · {marketIndicators}</span><small data-testid="strategy-workbench-market-source">{market.label}</small><strong data-testid="strategy-marker-alignment">{markerLabel}</strong></header>{market.candles.length ? <div className="strategy-workbench-candle" data-testid="strategy-workbench-candle"><TradingViewChart candles={market.candles} markers={markers} loading={false} showVolume={market.hasVolume} showDonchian={donchianAvailable} showMarkers={!market.isReference} /></div> : <Empty title={loadedMarket.candles.length ? '该显示区间没有已载入 K 线' : 'K 线未发布'} detail={windowed.error || (loadedMarket.candles.length ? '请调整显示区间；页面不会用其他日期补齐，历史报告指标保持不变。' : unavailableChartDetail(runChartError, completedKlinesError))} />}</section>
    {report.series.equity.length && report.series.drawdown.length ? <div className="strategy-workbench-equity-panel" data-testid="strategy-workbench-equity-panel"><EquityPerformanceChart equity={report.series.equity} drawdown={report.series.drawdown} /></div> : null}
    {missingSeries.length ? <section className="strategy-workbench-provenance" data-testid="strategy-history-missing-series"><strong>历史报告尚缺哪些输出？</strong><p>该历史报告尚未发布：{missingSeries.join('、')}。已有统计指标与部分复核结果不等于这些序列；不是页面还在等待输出，不能从总收益或参考 K 线反推曲线。</p><p>下面展示实际已发布的逐年表现、成本压力和交易复核。补齐缺项需要另行生成带账本的新回测报告，不会覆盖或冒充这份历史报告。</p></section> : null}
    {report.series.trades.length || report.series.costs.length ? <div className="strategy-workbench-chart-row">{report.series.trades.length ? <TradePnlChart trades={report.series.trades} /> : null}{report.series.costs.length ? <CostBreakdownChart costs={report.series.costs} /> : null}</div> : null}
    <section className="strategy-workbench-published-output" data-testid="strategy-published-output"><details open><summary>已发布输出：逐年表现与成本压力</summary><HistoricalPerformanceDetails details={details.details} /></details><details><summary>已发布输出：历史交易复核（不是完整成交账本）</summary><HistoricalTradeReview details={details.details} /></details></section>
  </div>;
}

function DockContent({tab, details, error, report, selection, sourceRunId, version}: {tab: DockTab; details: BTCStrategyHistoryResponse | null; error: string; report: CanonicalBacktestReport | null; selection: StrategyDiscoverySelection | null; sourceRunId: string; version: StrategyWorkbenchVersion | null}) {
  if (error) return <div className="strategy-workbench-dock-body">历史详情不可用：{error}</div>;
  if (tab === 'logs') return <div className="strategy-workbench-dock-body strategy-workbench-unavailable" data-testid="strategy-workbench-log-unavailable"><TerminalWindow size={18} /><p>{version?.latest_backtest ? `已注册 runner 状态：${version.latest_backtest.status}。` : '运行输出未通过只读 history 接口发布。'} blocker 仅在“安全与证据”页展示，不能冒充日志。</p></div>;
  if (tab === 'runs') return <div className="strategy-workbench-dock-body"><ListBullets size={18} />{version?.latest_backtest ? <table data-testid="strategy-workbench-version-run-table"><thead><tr><th>version</th><th>run_id</th><th>status</th><th>scope</th></tr></thead><tbody><tr><td><code>{version.version_id}</code></td><td><code>{version.latest_backtest.run_id}</code></td><td>{version.latest_backtest.status}</td><td>research-only registered replay</td></tr></tbody></table> : null}{details?.history_runs.length ? <table data-testid="strategy-workbench-run-table"><thead><tr><th>run_id</th><th>status</th><th>time</th><th>report hash</th></tr></thead><tbody>{details.history_runs.map((run) => <tr key={run.run_id}><td><code>{run.run_id}</code></td><td>{run.status}</td><td>{run.generated_at_utc || 'unavailable'}</td><td><code>{run.report_sha256 || 'unavailable'}</code></td></tr>)}</tbody></table> : <p>链路未发布历史 run。</p>}</div>;
  if (tab === 'trades') return <div className="strategy-workbench-dock-body strategy-workbench-history-review">{details ? <HistoricalTradeReview details={details.details} /> : null}{report?.series.trades.length ? <table data-testid="strategy-workbench-trade-table"><thead><tr><th>#</th><th>side</th><th>entry</th><th>exit</th><th>net PnL</th></tr></thead><tbody>{report.series.trades.slice(0, 48).map((trade) => <tr key={trade.trade_number}><td>{trade.trade_number}</td><td>{trade.direction}</td><td>{formatTime(trade.entry_time)}</td><td>{formatTime(trade.exit_time)}</td><td>{numeric(trade.net_pnl)}</td></tr>)}</tbody></table> : <p>未发布可验证的 fills / 交易明细。</p>}</div>;
  if (tab === 'performance') return <div className="strategy-workbench-dock-body strategy-workbench-history-review">{version?.latest_backtest?.report ? <MetricGrid entries={Object.entries(version.latest_backtest.report.summary)} /> : null}{details ? <HistoricalPerformanceDetails details={details.details} /> : <MetricGrid entries={report ? [['Run', report.run_id], ['状态', report.status], ['决策', report.decision], ['成本项', report.series.costs.length]] : [['绩效', '未发布']]} />}</div>;
  return <div className="strategy-workbench-dock-body strategy-workbench-history-review"><ShieldCheck size={18} /><dl><div><dt>策略</dt><dd>{selection?.identity || '未选择'}</dd></div><div><dt>安全</dt><dd>research-only · paper/live/order/private=false</dd></div><div><dt>版本候选</dt><dd>{version?.selected_runnable_candidate ? `selected · ${version.selection_scope}` : '未选择；不触发 Demo。'}</dd></div><div><dt>阻断项</dt><dd>{details?.blockers.join('；') || 'unavailable'}</dd></div><div><dt>证据链</dt><dd>{details?.source.report_sha256 || '未发布'}</dd></div><div><dt>chart source</dt><dd>{sourceRunId || '未发布'}</dd></div></dl>{details ? <HistoricalRiskDetails details={details.details} /> : null}</div>;
}

function MetricGrid({entries}: {entries: [string, unknown][]}) { return <dl className="strategy-workbench-kpis">{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{String(value ?? '未发布')}</dd></div>)}</dl>; }
function Empty({title, detail, link, retry}: {title: string; detail: string; link?: string; retry?: () => void}) { return <div className="strategy-workbench-empty"><ChartLineUp size={26} /><strong>{title}</strong><span>{detail}</span>{retry ? <button type="button" onClick={retry}>重新读取报告</button> : null}{link ? <Link to={link}>查看完整历史回测与详细报告</Link> : null}</div>; }
function historyLink(strategyId: string, candidateId: string) { return `/crypto?${new URLSearchParams({strategy_id: strategyId, candidate_id: candidateId, panel: 'backtest', report_tab: 'overview'}).toString()}`; }
function readSelection(): {strategyId: string; candidateId: string} | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(SELECTION_KEY) || 'null');
    if (typeof parsed?.strategyId === 'string' && typeof parsed?.candidateId === 'string') return {strategyId: parsed.strategyId, candidateId: parsed.candidateId};
  } catch { /* browser preference only */ }
  return null;
}
function readLayout() { try { const parsed = JSON.parse(localStorage.getItem(LAYOUT_KEY) || 'null'); if (typeof parsed?.left === 'number' && typeof parsed?.code === 'number' && typeof parsed?.dock === 'number') return {left: parsed.left, code: parsed.code, dock: parsed.dock}; } catch { /* defaults */ } return DEFAULT_LAYOUT; }
function clamp(value: number, min: number, max: number) { return Math.min(max, Math.max(min, value)); }
function separatorKey(event: WorkbenchKeyboardEvent<HTMLDivElement>, adjust: (delta: number) => void, reset: () => void) { if (event.key === 'Home') { event.preventDefault(); reset(); } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') { event.preventDefault(); adjust(-1); } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') { event.preventDefault(); adjust(1); } }
function text(value: unknown) { return typeof value === 'string' && value.trim() ? value : ''; }
function numeric(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US', {maximumFractionDigits: 4}) : '未发布'; }
function percent(value: unknown) { return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)}%` : '未发布'; }
function formatTime(value: number) { return Number.isFinite(value) ? new Date(value * 1000).toISOString().replace('T', ' ').slice(0, 16) : 'unavailable'; }
function errorMessage(error: unknown) { return error instanceof ApiError ? `HTTP ${error.status}: ${error.message}` : error instanceof Error ? error.message : String(error); }
function historyErrorMessage(error: unknown, subject: string) {
  if (error instanceof ApiError && error.status === 503) return `${subject}服务暂不可用（HTTP 503）`;
  return errorMessage(error);
}
function unavailableChartDetail(runChartError: string, completedKlinesError: string) {
  const safety = '不会补造 K 线、指标或交易标记。';
  const errors = [runChartError, completedKlinesError].filter(Boolean);
  return errors.length ? `${errors.join('；')}；${safety}` : `run chart 与已完成 bar 均不可用；${safety}`;
}
function fullMetricEntries(fullMetrics: Record<string, unknown>, derived: Record<string, unknown>, report: CanonicalBacktestReport): [string, unknown][] {
  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = fullMetrics[key] ?? derived[key];
      if (value !== undefined && value !== null) return value;
    }
    return undefined;
  };
  return [
    ['总收益', percent(pick('total_return_pct'))],
    ['年化收益', percent(pick('annual_return_pct'))],
    ['年化波动', percent(pick('annual_volatility_pct', 'volatility_pct'))],
    ['Alpha / Benchmark', `${percent(pick('alpha_pct', 'alpha'))} / ${percent(pick('benchmark_return_pct', 'benchmark_return_pct'))}`],
    ['最大回撤', percent(pick('max_drawdown_pct') ?? maxDrawdown(report))],
    ['Sharpe', numeric(pick('sharpe_ratio'))],
    ['Sortino', numeric(pick('sortino_ratio'))],
    ['Calmar', numeric(pick('calmar_ratio'))],
    ['胜率', percent(pick('win_rate_pct'))],
    ['Profit factor', numeric(pick('profit_factor'))],
    ['交易数 / 暴露', `${numeric(pick('trade_count'))} / ${percent(pick('average_exposure_pct', 'exposure_pct'))}`],
  ];
}
function historicalReviewMarkers(value: unknown, candles: TradingCandle[]) {
  const payload = typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
  const sets: Array<[string, unknown]> = [['Best', payload.best_trades], ['Worst', payload.worst_trades]];
  const candleTimes = new Set(candles.map((candle) => candle.time));
  const markers: TradingMarker[] = [];
  let aligned = 0;
  let total = 0;
  for (const [review, values] of sets) {
    if (!Array.isArray(values)) continue;
    for (const value of values) {
      if (typeof value !== 'object' || value === null) continue;
      const trade = value as Record<string, unknown>;
      const side = trade.side === 'short' ? 'short' : 'long';
      for (const [field, kind] of [['start', 'entry'], ['end', 'exit']] as [string, string][]) {
        if (trade[field] === undefined || trade[field] === null || trade[field] === '') continue;
        total += 1;
        const time = reviewTimestamp(trade[field]);
        if (!time || !candleTimes.has(time)) continue;
        aligned += 1;
        const entry = kind === 'entry';
        markers.push({
          time,
          position: entry === (side === 'long') ? 'belowBar' : 'aboveBar',
          color: review === 'Best' ? '#38bdf8' : '#a78bfa',
          shape: entry === (side === 'long') ? 'arrowUp' : 'arrowDown',
          text: `历史复核 ${review} ${kind}（非 canonical fill）`,
        });
      }
    }
  }
  return {markers, aligned, total};
}
function reviewTimestamp(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return alignToHour(value > 10_000_000_000 ? value / 1000 : value);
  if (typeof value !== 'string' || !value.trim()) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? alignToHour(parsed / 1000) : 0;
}
function maxDrawdown(report: CanonicalBacktestReport) { return report.series.drawdown.reduce((minimum, point) => Math.min(minimum, point.value), 0); }
function isChartPayload(payload: ChartSeriesPayload) { return Array.isArray(payload.candles) && payload.candles.every((candle) => Number.isFinite(candle.time) && Number.isFinite(candle.open) && Number.isFinite(candle.high) && Number.isFinite(candle.low) && Number.isFinite(candle.close)); }
function chooseMarketChart(runChart: ChartSeriesPayload | null, kline: LocalKlineResponse | null, choice: 'auto' | 'run' | 'reference') {
  if (choice !== 'reference' && runChart?.candles.length) return {candles: runChart.candles.map((candle) => ({...candle})), hasVolume: false, isReference: false, label: '该 run 已发布 K 线 · source_kind=published_run_chart · freshness=由 run 端点发布'};
  if (choice !== 'run' && kline?.rows.length) return {candles: kline.rows.map((row) => ({time: Math.floor(row.open_time_ms / 1000), open: row.open, high: row.high, low: row.low, close: row.close, volume: row.volume})), hasVolume: true, isReference: true, label: `本机参考行情：${kline.rows[0].exchange} · ${kline.rows[0].symbol} · ${kline.rows[0].interval} · source_kind=${kline.source_kind} · sample_end=${kline.sample_end} · freshness=${kline.freshness_status}`};
  return {candles: [] as TradingCandle[], hasVolume: false, isReference: false, label: 'source_kind=unavailable · sample_end=unavailable · freshness=unavailable'};
}
function canonicalTradeMarkers(trades: CanonicalTrade[], candles: TradingCandle[]) {
  const candleTimes = new Set(candles.map((candle) => candle.time));
  const markers: TradingMarker[] = [];
  let aligned = 0;
  for (const trade of trades) {
    const entry = alignToHour(trade.entry_time);
    const exit = alignToHour(trade.exit_time);
    if (candleTimes.has(entry)) { aligned += 1; markers.push({time: entry, position: trade.direction === 'long' ? 'belowBar' : 'aboveBar', color: trade.direction === 'long' ? '#22c55e' : '#ef4444', shape: trade.direction === 'long' ? 'arrowUp' : 'arrowDown', text: `T${trade.trade_number} entry`}); }
    if (candleTimes.has(exit)) { aligned += 1; markers.push({time: exit, position: trade.direction === 'long' ? 'aboveBar' : 'belowBar', color: '#f59e0b', shape: trade.direction === 'long' ? 'arrowDown' : 'arrowUp', text: `T${trade.trade_number} exit`}); }
  }
  return {markers, aligned, total: trades.length * 2};
}
function publishedMarkers(chart: ChartSeriesPayload | null, candles: TradingCandle[]) {
  const candleTimes = new Set(candles.map((candle) => candle.time));
  return (chart?.markers || []).flatMap((marker) => {
    if (!candleTimes.has(marker.time) || (marker.position !== 'aboveBar' && marker.position !== 'belowBar') || (marker.shape !== 'arrowUp' && marker.shape !== 'arrowDown')) return [];
    return [{time: marker.time, position: marker.position, shape: marker.shape, color: marker.color || '#5d9cff', text: marker.text || 'published marker'} as TradingMarker];
  });
}
function alignToHour(timestamp: number) { return Math.floor(timestamp / 3600) * 3600; }
