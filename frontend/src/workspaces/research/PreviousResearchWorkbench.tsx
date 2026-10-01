type RecordLike = Record<string, any>;
export const researchStages = [
  {key: 'data', label: '数据与特征', hint: '确认输入', views: [{key: 'data', label: '数据准备'}, {key: 'factors', label: '因子评估与快照'}]},
  {key: 'experiment', label: '实验与回测', hint: '验证假设', views: [{key: 'cycle', label: '新建实验'}, {key: 'records', label: '实验记录与报告'}]},
  {key: 'evidence', label: '候选与证据', hint: '检查可信度', views: [{key: 'evidence', label: '候选证据'}, {key: 'workflow', label: '数据与门禁检查'}]},
  {key: 'portfolio', label: '组合与复核', hint: '评估组合', views: [{key: 'qlib', label: 'Qlib 与组合工具'}, {key: 'review', label: '组合模拟与人工复核'}]},
];

function navigateTabs(event: {currentTarget: HTMLElement; key: string; preventDefault: () => void}) {
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
  const index = tabs.indexOf(document.activeElement as HTMLButtonElement);
  if (index < 0) return;
  const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
    : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
    : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
  if (next >= 0) { event.preventDefault(); tabs[next].focus(); tabs[next].click(); }
}

export function ResearchNavigation({tab, onChange}: {tab: string; onChange: (key: string) => void}) {
  const current = researchStages.find(stage => stage.views.some(view => view.key === tab)) ?? researchStages[0];
  return <nav className="research-navigation" aria-label="研究流程">
    <div className="research-stages" role="tablist" aria-label="研究阶段" onKeyDown={navigateTabs}>
      {researchStages.map((stage, index) => <button key={stage.key} type="button" role="tab"
        aria-selected={current.key === stage.key} aria-controls="research-active-panel"
        tabIndex={current.key === stage.key ? 0 : -1} onClick={() => onChange(stage.views[0].key)}>
        <span className="research-step-index">0{index + 1}</span><span><strong>{stage.label}</strong><small>{stage.hint}</small></span>
      </button>)}
    </div>
    <div id="research-subviews" className="research-subviews" role="tablist" aria-label={current.label} onKeyDown={navigateTabs}>
      {current.views.map(view => <button id={'research-tab-' + view.key} key={view.key} role="tab" type="button"
        aria-selected={tab === view.key} aria-controls="research-active-panel" tabIndex={tab === view.key ? 0 : -1}
        onClick={() => onChange(view.key)}>{view.label}</button>)}
    </div>
  </nav>;
}

export function ResearchOverview({readFailures, readAt, experiments, candidates, manifests, qlib, portfolio, overview, root, onNavigate, busy}: {
  loading: boolean; readFailures: string[]; readAt: string; experiments: RecordLike[]; candidates: RecordLike[];
  manifests: RecordLike[]; qlib: RecordLike | null; portfolio: RecordLike | null; overview: RecordLike | null;
  root: string; onNavigate: (tab: string) => void; busy: string;
}) {
  const qlibInstalled = qlib?.dependencies?.qlib === true && qlib?.dependencies?.lightgbm === true;
  const qlibDependencyKnown = typeof qlib?.dependencies?.qlib === 'boolean' && typeof qlib?.dependencies?.lightgbm === 'boolean';
  const successfulExperiments = experiments.filter(item => item.status?.toUpperCase() === 'COMPLETED').length;
  const failedExperiments = experiments.filter(item => ['FAILED', 'ERROR'].includes(String(item.status).toUpperCase())).length;
  const next = readFailures.length ? {title: '部分状态读取失败', body: readFailures.join('、') + ' 暂不可用；空白不代表零记录，请刷新后核验。', label: '查看读取详情', view: 'data'}
    : !experiments.length ? {title: '准备第一项研究', body: '当前目录还没有实验。确认数据和研究区间，然后选择规则策略或 Qlib 模型路径。', label: '配置研究实验', view: 'cycle'}
    : failedExperiments > 0 ? {title: '有实验需要检查', body: `${failedExperiments} 个实验失败。先查看原因与输入，再决定是否重试。`, label: '查看实验记录', view: 'records'}
    : !candidates.length ? {title: '实验已有记录，候选尚未生成', body: '检查回测和评分是否完成，再生成候选与证据。', label: '查看实验结果', view: 'records'}
    : {title: '研究结果等待证据复核', body: '候选数量不代表质量通过。检查数据版本、样本外结果、成本与各项门禁。', label: '检查候选证据', view: 'evidence'};
  return <section className="research-overview" aria-label="研究状态总览">
    <div className="research-next"><div><span className="research-eyebrow">当前状态 / 下一步</span><h3>{busy ? '研究任务进行中' : next.title}</h3><p>{next.body}</p></div>
      <button type="button" className="primary" disabled={!!busy} onClick={() => onNavigate(next.view)}>{next.label} →</button></div>
    <div className="research-health">
      <div><span>服务读取</span><strong className={readFailures.length ? 'warning' : ''}>{readFailures.length ? '部分失败' : '已返回'}</strong><small>只表示接口可读取</small></div>
      <div><span>数据可用性</span><strong className="warning">按研究区间核验</strong><small>注册表通过不等于数据齐备</small></div>
      <div><span>研究执行</span><strong>{readFailures.includes('实验列表') ? '未知' : `${successfulExperiments} / ${experiments.length} 完成`}</strong><small>策略是否有效另行评估</small></div>
      <div><span>人工复核 / 交易</span><strong className="warning">独立门禁 · 未解锁</strong><small>研究结果不自动启动交易</small></div>
    </div>
    <details className="research-provenance"><summary>来源、工具与读取详情 <span>{readAt || '未读取'}</span></summary>
      <dl><div><dt>读取目录</dt><dd>{root}</dd></div>
      <div><dt>注册表结构检查</dt><dd>{overview?.registry?.integrity || '未知'}</dd></div>
      <div><dt>系统原始阶段</dt><dd>{overview?.stage || '未知'}</dd></div>
      <div><dt>Qlib / LightGBM</dt><dd>{!qlibDependencyKnown ? '未知' : qlibInstalled ? '依赖已安装，运行结果单独核验' : '缺少依赖，模型路径尚不可运行'}</dd></div>
      <div><dt>PyPortfolioOpt</dt><dd>{typeof portfolio?.dependencies?.pypfopt !== 'boolean' ? '未知' : portfolio.dependencies.pypfopt ? '依赖已安装' : '缺少依赖'}</dd></div>
      <div><dt>候选 / 策略清单</dt><dd>{readFailures.includes('候选列表') ? '未知' : candidates.length} / {readFailures.includes('策略证据') ? '未知' : manifests.length}</dd></div></dl>
      {readFailures.length > 0 && <p role="alert">读取失败：{readFailures.join('、')}。请检查服务后重新读取。</p>}
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
      <p>Qlib 使用自己的配置文件、股票池和训练 / 验证 / 测试区间，请在组合工具中单独核对。成本模型沿用现有后端配置。</p>
    </fieldset>}
    {!!errors.length && <p role="alert" className="warning">{errors.join('；')}</p>}
  </section>;
}
