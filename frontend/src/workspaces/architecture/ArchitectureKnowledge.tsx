import {useMemo, useState} from 'react';
import {catalog} from './model';
import {architectureKnowledge, knowledgeByModule} from './knowledge';
import {architectureMilestoneStatus} from './mindmap';
import './architecture-knowledge.css';

const moduleLabel = (id: string) => catalog.modules.find(item => item.id === id)?.label ?? id;

function TextList({items, empty}: {items: string[]; empty: string}) {
  return items.length ? <ul>{items.map(item => <li key={item}>{item}</li>)}</ul> : <p className="knowledge-empty">{empty}</p>;
}

export function ArchitectureKnowledge({selectedModule, onSelectModule}: {
  selectedModule: string;
  onSelectModule: (moduleId: string) => void;
}) {
  const [showAllCards, setShowAllCards] = useState(false);
  const module = catalog.modules.find(item => item.id === selectedModule) ?? catalog.modules[0];
  const detail = knowledgeByModule.get(module.id);
  const cards = useMemo(() => showAllCards
    ? architectureKnowledge.core_files
    : architectureKnowledge.core_files.filter(card => card.module_id === module.id), [module.id, showAllCards]);
  return <section className="architecture-knowledge" aria-label="分层架构说明">
    <header className="knowledge-header">
      <div><p className="atlas-kicker">LAYERED RESPONSIBILITY / CHANGE GUIDE</p><h2>分层架构说明</h2>
        <p>先确定模块输入输出和修改边界，再读核心入口、调用方与对应测试。</p></div>
      <span className="knowledge-current">
        版本化源码快照 · 是否变动以增量校验为准
      </span>
    </header>
    <div className="knowledge-boundary" role="note">
      <strong>职责说明 ≠ 已跑通调用链。</strong>
      <span>{architectureKnowledge.scope_note}</span>
      <span>市场状态 v2 与历史诊断已实现；entry-only 条件政策默认关闭，只作用于空仓新增风险。</span>
      <span>旧 M2 没有稳定增量；最新 A/B baseline 完成，conditioned 在 1956 / 2960 因保护双触碰歧义 fail-closed。</span>
      <span>M3—M4 未启动。所有交易安全标记保持 false。</span>
      <span>完整策略包验证、审定、USDT 绑定和登记已接通；候选离线 worker 默认关闭，仅支持 factory_lgbm_ast_v1。</span>
      <span>研究读取链 11 / 11 正式场景通过；CONFLICT、BTC 503 与来源上下文限制继续如实显示。</span>
      <span>真实账户只读验收未完成；未读取凭证、未调用 private endpoint，交易就绪保持 false。</span>
      <details><summary>当前能力与里程碑证据入口</summary><ul>{architectureMilestoneStatus.evidence.map(item =>
        <li key={item.path}><strong>{item.label}</strong> · <code>{item.path}</code></li>)}</ul></details>
    </div>
    <div className="knowledge-layout">
      <nav className="knowledge-module-index" aria-label="分层模块索引">
        {catalog.modules.map(item => <button key={item.id} type="button" aria-pressed={item.id === module.id}
          onClick={() => {onSelectModule(item.id); setShowAllCards(false);}}>
          <span>{item.group}</span><strong>{item.label}</strong>
        </button>)}
      </nav>
      <article className="knowledge-module-detail" aria-label="模块输入输出边界">
        <p className="atlas-kicker">{module.group} / {module.id}</p><h2>{module.label}</h2><p>{module.purpose}</p>
        <div className="knowledge-io-grid">
          <section><h3>输入</h3><TextList items={detail?.inputs ?? []} empty="未登记输入；不得按目录猜测。" /></section>
          <section><h3>输出</h3><TextList items={detail?.outputs ?? []} empty="未登记输出；不得按名称推断。" /></section>
          <section><h3>上游</h3><TextList items={(detail?.upstream ?? []).map(moduleLabel)} empty="当前未登记上游。" /></section>
          <section><h3>下游 / 消费者</h3><TextList items={(detail?.downstream ?? []).map(moduleLabel)} empty="当前未登记下游。" /></section>
        </div>
        <section className="knowledge-guardrail"><h3>职责边界 / 修改禁区</h3><p>{detail?.boundary ?? module.caution}</p></section>
        <section><h3>关键入口</h3><TextList items={detail?.entrypoints ?? []} empty="待按来源补充关键入口。" /></section>
        <details><summary>现有源码审阅提醒</summary><p>{module.caution}</p><TextList items={module.roots} empty="无路径范围。" /></details>
      </article>
    </div>
    <section className="knowledge-core-files" aria-label="核心文件职责卡">
      <header><div><p className="atlas-kicker">CORE FILE CARDS</p><h2>核心文件职责卡</h2>
        <p>精选跨层入口，不把普通文件复制成空泛逐文件摘要。</p></div>
        <button type="button" aria-pressed={showAllCards} onClick={() => setShowAllCards(value => !value)}>
          {showAllCards ? `仅看 ${module.label}` : `查看全部 ${architectureKnowledge.core_files.length} 张`}
        </button></header>
      {cards.length ? <div className="knowledge-card-grid">{cards.map(card => {
        const stale = card.source_commit !== architectureKnowledge.source_commit;
        return <article key={card.path} className={stale ? 'is-stale' : ''} data-testid="architecture-core-file-card">
          <div className="knowledge-card-title"><code>{card.path}</code><span>{stale ? '来源绑定异常' : '快照 blob 已绑定'}</span></div>
          <p>{card.purpose}</p><dl>
            <div><dt>入口</dt><dd>{card.entry}</dd></div>
            <div><dt>调用方 / 消费者</dt><dd>{card.consumers.join('；')}</dd></div>
            <div><dt>副作用</dt><dd>{card.side_effects}</dd></div>
            <div><dt>修改禁区</dt><dd>{card.forbidden}</dd></div>
            <div><dt>对应测试</dt><dd>{card.tests.join('；')}</dd></div>
            <div><dt>Git 来源</dt><dd><code>{card.source_blob.slice(0, 12)}</code> · <code>{card.source_commit.slice(0, 12)}</code></dd></div>
          </dl>
        </article>;
      })}</div> : <p className="knowledge-empty">本模块未列为核心卡；请按下方分组索引定位普通文件，或查看全部核心卡。</p>}
    </section>
    <section className="knowledge-file-groups" aria-label="普通文件分组索引">
      <p className="atlas-kicker">GROUPED FILE INDEX</p><h2>普通文件分组索引</h2>
      <p>分组用于缩小阅读范围，不等同于逐文件审查；修改后仍需核对目标文件、受影响调用方和测试。</p>
      <div>{architectureKnowledge.file_groups.map(group => <details key={group.id}>
        <summary><strong>{group.label}</strong><span>{group.patterns.join(' · ')}</span></summary>
        <p>{group.purpose}</p><p>关联模块：{group.modules.map(moduleLabel).join(' / ')}</p>
      </details>)}</div>
    </section>
  </section>;
}
