import {useEffect, useRef} from 'react';
import {useLocation} from 'react-router-dom';
import {summarizeResearchRegistry, type ResearchReadFailure} from '../../lib/research-read-request';
type RecordLike = Record<string, any>;
export const researchStages = [
  {key: 'research-overview', label: '研究总览', views: [{key: 'research-overview', label: '研究总览'}]},
  {key: 'alpha-factory', label: 'Alpha 工厂', views: [{key: 'alpha-factory', label: 'Alpha 工厂'}]},
  {key: 'data', label: '数据与因子', views: [{key: 'data', label: '数据准备'}, {key: 'factors', label: '因子评估与快照'}]},
  {key: 'experiment', label: '手动实验', views: [{key: 'cycle', label: '新建实验'}, {key: 'qlib', label: 'Qlib 模型研究'}, {key: 'records', label: '实验记录与报告'}]},
  {key: 'evidence', label: '候选与证据', views: [{key: 'evidence', label: '候选证据'}, {key: 'workflow', label: '数据与门禁检查'}, {key: 'handoff', label: '候选与来源交接'}]},
];

type TabKeyEvent = {currentTarget: HTMLElement; key: string; preventDefault: () => void};
type ResearchFocusIntent = {path:'/research'; key:string; view:string; context:string; expires:number; cancel:()=>void};
let pendingResearchFocus: ResearchFocusIntent | null = null;
function focusContext(search: string) {
  const query = new URLSearchParams(search); query.delete('view'); query.sort(); return query.toString();
}
function armResearchFocus(tab: HTMLButtonElement) {
  pendingResearchFocus?.cancel();
  const key = tab.dataset.researchFocusKey, view = tab.dataset.researchView;
  if (!key || !view || window.location.pathname !== '/research') return;
  let timer: ReturnType<typeof setTimeout>;
  const cancel = () => {
    if (pendingResearchFocus === intent) pendingResearchFocus = null;
    clearTimeout(timer);
    document.removeEventListener('pointerdown', cancel, true);
    document.removeEventListener('keydown', cancel, true);
    document.removeEventListener('focusin', cancelOnOtherFocus, true);
    window.removeEventListener('blur', cancel);
  };
  const cancelOnOtherFocus = (event: FocusEvent) => {
    if (event.target !== tab && event.target !== document.body && event.target !== document.documentElement) cancel();
  };
  const intent: ResearchFocusIntent = {path:'/research',key,view,context:focusContext(window.location.search),expires:Date.now()+8000,cancel};
  pendingResearchFocus = intent;
  // One keyboard transition may unmount the old Nav while ordinary data loads.
  // Any subsequent interaction or expiry cancels it; it is never a scroll store.
  timer = setTimeout(cancel, 8000);
  document.addEventListener('pointerdown', cancel, true);
  document.addEventListener('keydown', cancel, true);
  document.addEventListener('focusin', cancelOnOtherFocus, true);
  window.addEventListener('blur', cancel);
}
function revealTabHorizontally(tab: HTMLButtonElement) {
  const row = tab.closest<HTMLElement>('[role="tablist"]');
  if (!row || row.scrollWidth <= row.clientWidth) return;
  const bounds = row.getBoundingClientRect(), target = tab.getBoundingClientRect();
  const left = bounds.left + row.clientLeft, right = left + row.clientWidth;
  if (target.left < left) row.scrollLeft -= left - target.left;
  else if (target.right > right) row.scrollLeft += target.right - right;
}

export function navigateTabs(event: TabKeyEvent, researchFocus = false) {
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
  if (index < 0) return;
  const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
    : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
    : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
  if (next >= 0) {
    event.preventDefault();
    if (researchFocus) {armResearchFocus(tabs[next]); tabs[next].focus({preventScroll:true}); revealTabHorizontally(tabs[next]);}
    else tabs[next].focus(); // Preserve the portfolio consumer's existing keyboard behavior.
    tabs[next].click();
  }
}
const navigateResearchTabs = (event: TabKeyEvent) => navigateTabs(event, true);

export function ResearchNavigation({tab, onChange}: {tab: string; onChange: (key: string) => void}) {
  const location = useLocation();
  const navigation = useRef<HTMLElement | null>(null);
  const secondary = useRef<HTMLDivElement | null>(null);
  const restoredFocus = useRef('');
  useEffect(() => {
    const pending = pendingResearchFocus;
    if (pending && (pending.path !== location.pathname || pending.context !== focusContext(location.search)
      || pending.view !== (new URLSearchParams(location.search).get('view') || 'research-overview') || Date.now() >= pending.expires)) pending.cancel();
    const selected = navigation.current?.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]');
    if (!selected) return;
    const intent = pendingResearchFocus;
    const matches = intent && location.pathname === '/research' && intent.context === focusContext(location.search)
      && intent.view === (new URLSearchParams(location.search).get('view') || 'research-overview');
    const target = matches ? [...Array.from(navigation.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || []),
      ...Array.from(secondary.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || [])]
      .find(button => button.dataset.researchFocusKey === intent.key && button.getAttribute('aria-selected') === 'true') : null;
    if (intent && tab === intent.view && !target) intent.cancel();
    if (target && intent) {intent.cancel(); restoredFocus.current = location.key; target.focus({preventScroll:true});}
    else if (!intent && restoredFocus.current !== location.key && location.state?.researchNavigationFocus) selected.focus({preventScroll:true});
    revealTabHorizontally(target || selected);
  }, [tab,location.key]);
  const current = researchStages.find(stage => stage.views.some(view => view.key === tab));
  return <><nav ref={navigation} className="research-navigation research-primary-navigation" aria-label="研究工作区导航">
    <div className="research-stages" role="tablist" aria-label="研究工作区" onKeyDown={navigateResearchTabs}>
      {researchStages.map((stage, index) => <button key={stage.key} id={stage.views.length === 1 ? 'research-tab-' + stage.key : undefined} type="button" role="tab"
        data-research-focus-key={'primary:'+stage.key} data-research-view={stage.views[0].key}
        aria-selected={current?.key === stage.key} aria-controls="research-active-panel"
        tabIndex={current?.key === stage.key || (!current && index === 0) ? 0 : -1} onClick={() => onChange(stage.views[0].key)}>
        <strong>{stage.label}</strong>
      </button>)}
    </div>
  </nav>
    {current && current.views.length > 1 && <div ref={secondary} id="research-subviews" className="research-subviews" role="tablist" aria-label={current.label} onKeyDown={navigateResearchTabs}>
      {current.views.map(view => <button id={'research-tab-' + view.key} key={view.key} role="tab" type="button"
        data-research-focus-key={'secondary:'+view.key} data-research-view={view.key}
        aria-selected={tab === view.key} aria-controls="research-active-panel" tabIndex={tab === view.key ? 0 : -1}
        onClick={() => onChange(view.key)}>{view.label}</button>)}
    </div>}
  </>;
}

export function ResearchOverview({readFailures, readFailureDetails, readAt, experiments, candidates, manifests, qlib, portfolio, overview, registry, root, onNavigate, busy}: {
  loading: boolean; readFailures: string[]; readFailureDetails: ResearchReadFailure[]; readAt: string; experiments: RecordLike[]; candidates: RecordLike[];
  manifests: RecordLike[]; qlib: RecordLike | null; portfolio: RecordLike | null; overview: RecordLike | null;
  registry: RecordLike | null;
  root: string; onNavigate: (tab: string) => void; busy: string;
}) {
  const provenanceRef = useRef<HTMLDetailsElement | null>(null);
  const qlibInstalled = qlib?.dependencies?.qlib === true && qlib?.dependencies?.lightgbm === true;
  const qlibDependencyKnown = typeof qlib?.dependencies?.qlib === 'boolean' && typeof qlib?.dependencies?.lightgbm === 'boolean';
  const successfulExperiments = experiments.filter(item => item.status?.toUpperCase() === 'COMPLETED').length;
  const failedExperiments = experiments.filter(item => ['FAILED', 'ERROR'].includes(String(item.status).toUpperCase())).length;
  const registrySummary = summarizeResearchRegistry(registry, overview);
  const next = readFailures.length ? {title: '部分状态读取失败', body: readFailures.join('、') + ' 暂不可用；空白不代表零记录，请刷新后核验。', label: '查看读取详情', view: 'data'}
    : !experiments.length ? {title: '准备第一项研究', body: '当前目录还没有实验。确认数据和研究区间，然后选择规则策略或 Qlib 模型路径。', label: '配置研究实验', view: 'cycle'}
    : failedExperiments > 0 ? {title: '有实验需要检查', body: `${failedExperiments} 个实验失败。先查看原因与输入，再决定是否重试。`, label: '查看实验记录', view: 'records'}
    : !candidates.length ? {title: '实验已有记录，候选尚未生成', body: '检查回测和评分是否完成，再生成候选与证据。', label: '查看实验结果', view: 'records'}
    : {title: '研究结果等待证据复核', body: '候选数量不代表质量通过。检查数据版本、样本外结果、成本与各项门禁。', label: '检查候选证据', view: 'evidence'};
  const handleNext = () => {
    if (readFailures.length && provenanceRef.current) {
      provenanceRef.current.open = true;
      provenanceRef.current.scrollIntoView({block: 'nearest'});
      provenanceRef.current.querySelector<HTMLElement>('summary')?.focus({preventScroll: true});
      return;
    }
    onNavigate(next.view);
  };
  return <section className="research-overview" aria-label="研究状态总览">
    <div className="research-next"><div><span className="research-eyebrow">当前状态 / 下一步</span><h3>{busy ? '研究任务进行中' : next.title}</h3><p>{next.body}</p></div>
      <button type="button" className="primary" disabled={!!busy} aria-controls={readFailures.length ? 'research-provenance-details' : undefined}
        onClick={handleNext}>{next.label} →</button></div>
    <div className="research-health">
      <div><span>服务读取</span><strong className={readFailures.length || registrySummary.qualification === 'blocked' ? 'warning' : ''}>{readFailures.length ? '部分失败' : registrySummary.qualification === 'blocked' ? `已返回 · ${registrySummary.status}` : '已返回'}</strong><small>只表示接口可读取，不等于证据合格</small></div>
      <div><span>数据可用性</span><strong className="warning">按研究区间核验</strong><small>注册表通过不等于数据齐备</small></div>
      <div><span>规则实验执行</span><strong>{readFailures.includes('实验列表') ? '未知' : `${successfulExperiments} / ${experiments.length} 完成`}</strong><small>不包含 Alpha 工厂 / Qlib 运行</small></div>
      <div><span>人工复核 / 交易</span><strong className="warning">独立门禁 · 未解锁</strong><small>研究结果不自动启动交易</small></div>
    </div>
    <details ref={provenanceRef} id="research-provenance-details" className="research-provenance"><summary tabIndex={-1}>来源、工具与读取详情 <span>{readAt || '未读取'}</span></summary>
      <dl><div><dt>读取目录</dt><dd>{root}</dd></div>
      <div><dt>注册表结构检查</dt><dd>{registrySummary.status}{registrySummary.notesTotal ? ` · ${registrySummary.notesTotal} 条说明` : ''}</dd></div>
      <div><dt>系统原始阶段</dt><dd>{overview?.stage || '未知'}</dd></div>
      <div><dt>Qlib / LightGBM</dt><dd>{!qlibDependencyKnown ? '未知' : qlibInstalled ? '依赖已安装，运行结果单独核验' : '缺少依赖，模型路径尚不可运行'}</dd></div>
      <div><dt>PyPortfolioOpt</dt><dd>{typeof portfolio?.dependencies?.pypfopt !== 'boolean' ? '未知' : portfolio.dependencies.pypfopt ? '依赖已安装' : '缺少依赖'}</dd></div>
      <div><dt>候选 / 策略清单</dt><dd>{readFailures.includes('候选列表') ? '未知' : candidates.length} / {readFailures.includes('策略证据') ? '未知' : manifests.length}</dd></div></dl>
      {readFailureDetails.length > 0 && <p role="alert">读取失败：{readFailureDetails.map(item => `${item.name}（${item.message}）`).join('、')}。请检查服务后重新读取。</p>}
      {registrySummary.qualification === 'blocked' && <p role="alert">注册表已返回 {registrySummary.status}：冲突仍需处理，不代表证据合格或可晋级，也不再被显示成“未知”。</p>}
      <p>此处时间是页面读取时间。市场数据截止日期、版本和完整性以每次实验的输入证据为准。</p>
    </details>
  </section>;
}

export function ResearchContext({value, onChange, open, onToggle, errors, disabled}: {
  value: {symbols: string; start: string; end: string; barSize: string; dataVersion: string; featureVersion: string};
  onChange: (key: string, value: string) => void; open: boolean; onToggle: () => void; errors: string[]; disabled: boolean;
}) {
  return <section className="research-context" aria-label="共享研究上下文">
    <div className="research-context-summary"><span>研究上下文</span><strong>{value.symbols || '未选择标的'}</strong><span>{value.barSize} · {value.start} → {value.end}</span>
      <button type="button" aria-expanded={open} aria-controls="research-context-fields" onClick={onToggle}>{open ? '收起' : '编辑上下文'}</button></div>
    {open && <fieldset id="research-context-fields" disabled={disabled}><legend>规则实验、因子评估与特征快照共享这些输入</legend>
      <label>研究标的<input value={value.symbols} onChange={(e: {target: HTMLInputElement}) => onChange('symbols', e.target.value)} placeholder="AAPL,MSFT" /></label>
      <label>研究周期<select value={value.barSize} onChange={(e: {target: HTMLSelectElement}) => onChange('barSize', e.target.value)}><option>1d</option><option>1m</option><option>5m</option><option>15m</option></select></label>
      <label>研究开始<input type="date" value={value.start} onChange={(e: {target: HTMLInputElement}) => onChange('start', e.target.value)} /></label>
      <label>研究结束<input type="date" value={value.end} onChange={(e: {target: HTMLInputElement}) => onChange('end', e.target.value)} /></label>
      <label>数据版本<input value={value.dataVersion} onChange={(e: {target: HTMLInputElement}) => onChange('dataVersion', e.target.value)} placeholder="填写可追溯版本" /></label>
      <label>特征版本<input value={value.featureVersion} onChange={(e: {target: HTMLInputElement}) => onChange('featureVersion', e.target.value)} placeholder="使用冻结特征时填写" /></label>
      <p>Qlib 使用自己的配置文件、股票池和训练 / 验证 / 测试区间，请在实验与回测的 Qlib 模型研究中单独核对。成本模型沿用现有后端配置。</p>
    </fieldset>}
    {!!errors.length && <p role="alert" className="warning">{errors.join('；')}</p>}
  </section>;
}
