import {useEffect, useMemo, useRef, useState} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {WorkbenchFrame} from '../components/workbench/Workbench';
import {frontendIdentity} from '../frontendIdentity';
import {ArchitectureMindMap} from './architecture/ArchitectureMindMap';
import {ArchitectureKnowledge} from './architecture/ArchitectureKnowledge';
import {BtcSystemPanorama} from './architecture/BtcSystemPanorama';
import {architectureMilestoneStatus, currentDevelopmentStatus, strategyDeliveryStatus} from './architecture/mindmap';
import {catalog, coverage, groups, moduleOf, readers} from './architecture/model';
import type {SourceRef} from './architecture/model';
import './architecture/architecture-map.css';

const number = (value: number) => value.toLocaleString('zh-CN');
function Sources({sources}: {sources: SourceRef[]}) {
  return <ul className="atlas-sources">{sources.map(source =>
    <li key={source.path + source.line}><code>{source.path}:{source.line}</code></li>)}</ul>;
}
export default function ArchitectureMapWorkspace() {
  const detailRef = useRef<HTMLElement | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [selected, setSelected] = useState('alpha');
  const [query, setQuery] = useState('');
  const [readFilter, setReadFilter] = useState('all');
  const [moduleFilter, setModuleFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [localView, setLocalView] = useState('overview');
  const view = searchParams.get('view') === 'btc-panorama' ? 'btc-panorama' : localView;
  const total = coverage(catalog.files);
  const module = catalog.modules.find(item => item.id === selected)!;
  const byModule = useMemo(() => new Map(catalog.modules.map(item =>
    [item.id, catalog.files.filter(file => moduleOf(file.path) === item.id)])), []);
  const selectedCoverage = coverage(byModule.get(selected) ?? []);
  const edges = catalog.edges.filter(edge => edge.from === selected || edge.to === selected);
  const findings = catalog.findings.filter(finding => finding.module === selected);
  const filtered = useMemo(() => catalog.files.filter(file =>
    (readFilter === 'all' || file.status === readFilter) &&
    (moduleFilter === 'all' || moduleOf(file.path) === moduleFilter) &&
    (!query || file.path.toLowerCase().includes(query.toLowerCase()))), [query, readFilter, moduleFilter]);
  const rows = filtered.slice(page * 30, (page + 1) * 30);
  const changedBaseline = frontendIdentity.source_head !== catalog.source_commit;
  const moduleName = (id: string) => catalog.modules.find(item => item.id === id)?.label ?? id;
  const setView = (nextView: string) => {
    if (nextView !== 'btc-panorama') setLocalView(nextView);
    const nextParams = new URLSearchParams(searchParams);
    if (nextView === 'btc-panorama') nextParams.set('view', nextView);
    else nextParams.delete('view');
    if (nextParams.toString() !== searchParams.toString()) setSearchParams(nextParams);
  };
  const showModuleLedger = () => {setModuleFilter(selected); setPage(0); setView('ledger');};
  const showModuleEvidence = (moduleId: string) => {setSelected(moduleId); setView('map');};
  useEffect(() => {
    if (view !== 'map' || !detailRef.current) return;
    detailRef.current.scrollIntoView({behavior: 'smooth', block: 'start'});
    detailRef.current.focus({preventScroll: true});
  }, [selected, view]);
  return <WorkbenchFrame className="architecture-workbench" testId="architecture-workspace">
    <div className="architecture-atlas">
      <header className="atlas-header">
        <div><p className="atlas-kicker">SYSTEM ATLAS / SOURCE REVIEW</p>
          <h1>架构地图</h1><p>先看职责与连接，再沿证据定位代码。</p></div>
        <span className="atlas-label">{view === 'btc-panorama'
          ? '原始快照只读 · 个人草稿可编辑且未经代码核验'
          : `只读文档 · ${total.unread === 0 ? '历史源码基准已读完 · 当前进度另行核查' : '源码审阅进行中'}`}</span>
      </header>
      <section className="atlas-boundary" aria-label="地图证据边界">
        <strong>这是源码地图，不是运行监控，也不是交易验收。</strong>
        <p>已实现 ≠ 历史测试 ≠ 已合 main／页面验收 ≠ 运行可用 ≠ 可交易。当前进度核查基线 <code>3fc39879</code>；M3—M4 未启动。</p>
        <p>审阅基准 <code>{catalog.source_commit.slice(0, 12)}</code>
          {changedBaseline ? ' · 页面代码与历史审阅基准不同；这里只显示版本化状态索引，不代表已重新通读当前全仓源码。' : ' · 页面版本与审阅基准相同，仍不证明运行状态。'}</p>
        <details data-testid="architecture-milestone-status"><summary>版本化里程碑状态 · 当前能力边界 · {architectureMilestoneStatus.asOf}</summary>
          <p>状态来源 HEAD <code>{architectureMilestoneStatus.sourceHead.slice(0, 12)}</code>；历史源码审阅基准不随本状态记录改写，M3—M4 未启动。</p>
          <ul>{architectureMilestoneStatus.rows.map(row => <li key={row.id}><strong>{row.label}</strong>
            <span>实现：{row.implementation}</span><span>测试：{row.tests}</span>
            <span>运行：{row.runtime}</span><span>交易就绪：{row.trading}</span></li>)}</ul>
          <p>证据入口：</p><ul>{architectureMilestoneStatus.evidence.map(item => <li key={item.path}><strong>{item.label}</strong> · <code>{item.path}</code></li>)}</ul>
        </details>
      </section>
      <div className="atlas-stats" aria-label="源码阅读覆盖">
        <div><strong>{number(total.read)} <small>/ {number(total.total)}</small></strong><span>文件已读至 EOF</span></div>
        <div><strong>{number(total.readLines)}</strong><span>已读源码行（含只读分工）</span></div>
        <div><strong>{number(total.unread)}</strong><span>文件未完成通读</span></div>
        <div><strong>未验证</strong><span>本轮运行行为与交易就绪</span></div>
      </div>
      <nav className="atlas-nav" aria-label="架构地图视图">
        {[['overview', '总览思维导图'], ['btc-panorama', 'BTC 系统全景'], ['knowledge', '分层架构说明'], ['map', '模块证据'], ['ledger', '阅读清单'], ['guide', '增量阅读指南']].map(([key, label]) =>
          <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)}>{label}</button>)}
      </nav>
      {view === 'overview' ? <>
        <section className="atlas-delivery" aria-label="当前开发进度" data-testid="current-development-status">
          <p className="atlas-kicker">CURRENT DEVELOPMENT / {currentDevelopmentStatus.asOf}</p>
          <h2>当前开发进度</h2>
          <p>{currentDevelopmentStatus.boundary}</p>
          <p>核查 HEAD：<code>{currentDevelopmentStatus.reviewedHead}</code>。这里没有声称重新通读全仓，也没有把历史测试改写成当前 HEAD 新跑结果。</p>
          <ol className="atlas-delivery-stages">{currentDevelopmentStatus.rows.map(row => <li key={row.id}>
            <span className="atlas-kicker">{row.id}</span><h3>{row.label}</h3>
            <p><strong>已实现：</strong>{row.implementation}</p>
            <details><summary>历史测试／合入／运行限制</summary>
              <p><strong>历史测试：</strong>{row.historicalTests}</p>
              <p><strong>合入／页面：</strong>{row.publication}</p>
              <p><strong>运行限制：</strong>{row.runtimeLimit}</p>
              <code>{row.evidence}</code>
            </details>
          </li>)}</ol>
          <p>完整说明：<code>docs/architecture/system-code-map/DEVELOPMENT-STATUS-20260929.md</code></p>
        </section>
        <section className="atlas-delivery" aria-label="策略接入交付进度" data-testid="strategy-delivery-status">
          <p className="atlas-kicker">STRATEGY DELIVERY / {strategyDeliveryStatus.asOf}</p>
          <h2>{strategyDeliveryStatus.conclusion}</h2>
          <p>{strategyDeliveryStatus.boundary}</p>
          <details><summary>核查版本与范围</summary>
            <p>按上述版本核查：<code>{strategyDeliveryStatus.reviewedHead}</code>。这是提交态进度记录，不自动随页面版本升级为运行证据。</p>
            <p>原已审源码：<code>{strategyDeliveryStatus.reviewedSource}</code>；完整依据：<code>{strategyDeliveryStatus.reportPath}</code>。</p>
            <p>本轮 Donchian 封存计算基线：<code>{strategyDeliveryStatus.closeoutSourceHead}</code>；此处不把模拟成交写成运行成交。</p>
          </details>
          <div className="atlas-delivery-paths" aria-label="两种策略来源与共同执行边界">
            {strategyDeliveryStatus.paths.map(path => <p key={path.label}><strong>{path.label}</strong><span>{path.detail}</span></p>)}
            <p>单策略、单账户分别验证；不合并两个策略的算法或目标，不新建 OMS。</p>
          </div>
          <ol className="atlas-delivery-stages">{strategyDeliveryStatus.stages.map(stage => <li key={stage.id}>
            <span className="atlas-kicker">{stage.id} · {stage.status}</span><h3>{stage.label}</h3>
            <p>{stage.implementation}</p><details><summary>验证与交付依据</summary>
              <p>{stage.verification}</p><p>{stage.publication}</p><code>{stage.evidence}</code>
            </details>
          </li>)}</ol>
          <details className="atlas-delivery-remaining"><summary>剩余缺口与停止条件</summary>
            <ul>{strategyDeliveryStatus.remaining.map(item => <li key={item}>{item}</li>)}</ul>
            <p>{strategyDeliveryStatus.nonBlockers}</p><p>{strategyDeliveryStatus.nextStep}</p>
          </details>
          <p><Link to="/research?view=run-details&qlibRun=m1-okx-qlib">查看固定 Qlib 的历史研究与离线摘要 →</Link></p>
          <p><Link to="/research?view=run-details&offlineRun=donchian-v3-closeout-20260920">查看 Donchian 五阶段离线决策与账本证据 →</Link></p>
          <p><Link to="/research?view=run-details&offlineRun=donchian-stage-20260921">查看 Donchian 已核账的自然历史阶段快照（2960 / 8760 小时，暂停）→</Link></p>
        </section>
        <ArchitectureMindMap onSelectModule={showModuleEvidence} />
      </> : null}
      {view === 'btc-panorama' ? <BtcSystemPanorama /> : null}
      {view === 'knowledge' ? <ArchitectureKnowledge selectedModule={selected} onSelectModule={setSelected} /> : null}
      {view === 'map' ? <section className="atlas-map-layout" aria-label="源码架构关系">
        <div className="atlas-map">
          <p className="atlas-help">按职责归类，不代表所有市场共用一条执行流水线。点击节点查看有出处的关系。</p>
          {groups.map(group => <section className="atlas-group" key={group} aria-label={group + '模块'}>
            <h2>{group}</h2>
            <div className="atlas-nodes">{catalog.modules.filter(item => item.group === group).map(item => {
              const state = coverage(byModule.get(item.id) ?? []);
              return <button type="button" key={item.id} className="atlas-node" aria-pressed={selected === item.id}
                onClick={() => setSelected(item.id)} data-testid={'atlas-node-' + item.id}>
                <strong>{item.label}</strong>
                <span>{state.read ? '已读 ' + state.read + ' / ' + state.total + ' 文件' : '待通读 · ' + state.total + ' 文件'}</span>
              </button>;
            })}</div>
          </section>)}
        </div>
        <aside ref={detailRef} tabIndex={-1} className="atlas-detail" aria-label="模块详情" aria-live="polite">
          <p className="atlas-kicker">{module.group} / SOURCE DETAIL</p>
          <h2>{module.label}</h2><p>{module.purpose}</p>
          <p className="atlas-caution">{module.caution}</p>
          <div className="atlas-detail-meta"><span>已读 {selectedCoverage.read} / {selectedCoverage.total} 文件</span>
            <button type="button" onClick={() => setView('knowledge')}>查看输入输出 →</button>
            <button type="button" onClick={showModuleLedger}>查看本模块清单 →</button></div>
          <h3>已记录的连接</h3>
          {edges.length ? <ul className="atlas-edges">{edges.map(edge => <li key={edge.id}>
            <strong>{moduleName(edge.from)} → {moduleName(edge.to)}</strong>
            <p>{edge.label}</p><span className="atlas-evidence-level">{edge.status === 'source_reviewed' ? '来源文件已通读 · 运行未验证' : '仅定位引用 · 调用链待通读'}</span>
            <Sources sources={edge.sources} />
          </li>)}</ul> : <p className="atlas-help">尚未登记足够证据的连接，不根据目录名称补画。</p>}
          {findings.length ? <><h3>审阅记录</h3>{findings.map(finding => <article className="atlas-finding" key={finding.id}>
            <h4>{finding.title}</h4><p>{finding.detail}</p><small>{finding.status}</small><Sources sources={finding.sources} />
          </article>)}</> : null}
          <details><summary>源码定位范围</summary><ul className="atlas-sources">{module.roots.map(root => <li key={root}><code>{root}</code></li>)}</ul></details>
        </aside>
      </section> : null}
      {view === 'ledger' ? <section className="atlas-ledger" aria-label="阅读清单">
        <h2>阅读清单</h2><p>{catalog.review_note}</p>
        <div className="atlas-filters">
          <label>文件路径<input value={query} placeholder="例如 quant_shared/runtime" onChange={(event: {target: {value: string}}) => {setQuery(event.target.value); setPage(0);}} /></label>
          <label>阅读状态<select value={readFilter} onChange={(event: {target: {value: string}}) => {setReadFilter(event.target.value); setPage(0);}}>
            <option value="all">全部状态</option><option value="fully_read">已读至 EOF</option><option value="unread">未完成通读</option></select></label>
          <label>模块<select value={moduleFilter} onChange={(event: {target: {value: string}}) => {setModuleFilter(event.target.value); setPage(0);}}>
            <option value="all">全部模块</option>{catalog.modules.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        </div>
        <p role="status">共 {number(filtered.length)} 个文件 · 第 {page + 1} / {Math.max(1, Math.ceil(filtered.length / 30))} 页</p>
        <div className="atlas-table-scroll"><table>
          <thead><tr><th>文件 / Git blob</th><th>阅读状态</th><th>覆盖范围</th><th>阅读者 / 批次</th></tr></thead>
          <tbody>{rows.map(file => <tr key={file.path}><td><code>{file.path}</code><small title={file.blob}>blob {file.blob.slice(0, 12)}</small></td>
            <td>{file.status === 'fully_read' ? '已读至 EOF' : '未完成通读'}</td>
            <td>{file.status === 'fully_read' ? file.lines ? '1–' + file.lines : '空文件' : '—'}<small>总行数 {file.lines === null ? '不透明对象' : file.lines}</small></td>
            <td>{file.reader ? readers[file.reader] ?? file.reader : '未登记'}<small>{file.batch ?? '清单记录，不计已读'}</small></td></tr>)}</tbody>
        </table></div>
        {!rows.length ? <p className="atlas-empty">没有匹配文件；可清空筛选。</p> : null}
        <div className="atlas-pagination"><button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
          <button type="button" disabled={(page + 1) * 30 >= filtered.length} onClick={() => setPage(page + 1)}>下一页</button></div>
      </section> : null}
      {view === 'guide' ? <section className="atlas-guide" aria-label="增量阅读指南">
        <h2>下次从哪里继续</h2>
        <ol><li>先读分层说明，再检查当前 Git 版本与文件差异；旧地图不等于当前运行事实。</li>
          <li>修改相关文件时仍需核对目标文件、受影响调用方与测试；blob 变化只标记需复核，不代表其余文件没有影响。</li>
          <li>读至 EOF 后记录阅读者、完整行范围、批次与 blob；搜索命中和元数据统计不计通读。</li>
          <li>把新连接绑定到具体来源行；源码判断与独立回归结果分别记录。</li></ol>
        <h3>只读差异检查</h3><pre><code>node frontend/scripts/architecture-review.mjs --ref=HEAD</code></pre>
        <p>该命令只比较 Git 提交对象，不检查工作树未提交修改。返回 changed / added / deleted / review_invalidated；
          差异或目录校验失败时非零退出。不会运行研究、连接交易所或授予权限。</p>
        <h3>单一证据源</h3><code className="atlas-source-path">frontend/src/workspaces/architecture/catalog.json</code>
        <p>页面从这份版本化清单构建；阅读说明在 <code>docs/architecture/system-code-map/README.md</code>。</p>
        <p>{catalog.scope_note}</p>
        <h3>接下来的审阅重点</h3><p>{total.unread === 0
          ? '历史基准范围已全部读完。下次只复核相关新增或变化的代码；当前进度见 2026-09-29 快照，不重读全仓、不自动启动 M3—M4。'
          : '优先补齐未读依赖链，再完成整体评估；不提前把风险清单转为工程任务。'}</p>
        <p>当前开发进度：<code>docs/architecture/system-code-map/DEVELOPMENT-STATUS-20260929.md</code>；策略接入评估：<code>{strategyDeliveryStatus.reportPath}</code>；原始重评：<code>docs/architecture/system-code-map/REASSESSMENT.md</code>。</p>
        <details><summary>本页面安全边界（不是后端授权快照）</summary><ul>{Object.keys(catalog.safety).map(key => <li key={key}><code>{key}=false</code></li>)}</ul></details>
      </section> : null}
      <footer className="atlas-footer"><span>地图用于阅读与审查 · 不触发研究、交易或证据重建</span>
        <Link to="/research">回到研究台 →</Link></footer>
    </div>
  </WorkbenchFrame>;
}
