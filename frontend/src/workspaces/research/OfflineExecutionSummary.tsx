type Row = Record<string, any>;
const flags=['execution_permission','live','order','paper','private','promotion','real_order','runtime_observed','transfer','withdraw'];

export default function OfflineExecutionSummary({evidence,runId}:{evidence:Row|null|undefined;runId:string}) {
  const valid=evidence?.status==='sealed_offline_summary' && evidence.truth_kind==='offline_execution_simulation'
    && evidence.research_binding?.qlib_run_id===runId && flags.every(key=>evidence.permissions?.[key]===false);
  if(!valid) return <section className="research-intro-card" data-testid="offline-execution-summary"><h3>离线执行模拟 · 尚未绑定</h3>
    <p>{evidence?.status==='blocked' ? '摘要缺失或校验失败；未用其他运行替代。' : '没有精确关联的封存摘要；不以历史研究模拟替代执行证据。'}</p></section>;
  const e=evidence!;
  return <section className="research-intro-card" data-testid="offline-execution-summary" aria-label="V3 离线执行封存摘要">
    <span className="research-eyebrow">V3 / 离线执行模拟 / 封存摘要</span>
    <h3>{e.replay_id}</h3>
    <p>只读历史版本 · 真实账户未绑定 · 不启动、恢复或授权交易。</p>
    <p>决策 {e.counts.decisions} 条 · 拒绝批次 {e.counts.rejected_batches} · 获准 {e.counts.approved} · 模拟订单 {e.counts.submitted_orders} · 模拟成交 {e.counts.fills}</p>
    <p>零成交：未验证非零成交、部分成交或有仓位恢复。所有拒绝保留，未修改策略来制造成交。</p>
    <dl>
      <dt>策略 / 候选</dt><dd>{e.research_binding.strategy_version} / {e.research_binding.candidate_id}</dd>
      <dt>计算代码版本（不是当前页面版本）</dt><dd><code>{e.source_head}</code></dd>
      <dt>数据版本</dt><dd>{e.research_binding.data_version}</dd>
      <dt>决策覆盖（行情时间）</dt><dd>{e.decision_start} → {e.decision_end}</dd>
      <dt>模拟账户观察</dt><dd>{e.account_observed_at}（初始模拟账户，不是决策末期账户快照）</dd>
      <dt>封存时经济重算</dt><dd>权益 {e.ledger.final_equity_usdt} USDT · 仓位 {e.ledger.position_contracts} 张 · 手续费现金流 {e.ledger.fee_cashflow_usdt} · 资金费现金流 {e.ledger.funding_cashflow_usdt} USDT</dd>
    </dl>
    <details><summary>精确决策与账本引用（仅首尾预览）</summary>
      <p>封存时核验全部决策链接。拒绝决策未产生订单，共用未变化的初始模拟账本；本页不实时读取账本。</p>
      <p>账本事件 {e.ledger_event_sequence} · <code>{e.ledger_event_hash}</code></p>
      {e.samples.map((row:Row)=><article key={row.decision_id}><h4>{row.event_time}</h4>
        <p>决策 <code>{row.decision_id}</code></p><p>目标 {row.target_quantity_btc} BTC（候选提出，未获准执行）</p>
        <p>规则原因：{row.reasons.join('、') || '无'}；执行阻断：{row.execution_blockers.join('、') || '无'}</p>
        <p>事件 {row.runtime_batch_event_sequence} / <code>{row.runtime_decision_event_id}</code></p>
        <p>决策校验 <code>{row.runtime_decision_hash}</code></p>
      </article>)}
      <p>模型 <code>{e.model_sha256}</code></p><p>交付包 <code>{e.package_sha256}</code></p>
      <p>摘要校验 <code>{e.summary_sha256 || '由提交态摘要封印校验'}</code></p>
      <p>发布引用 <code>{e.manifest_ref || '提交态 Git 摘要'}</code></p>
    </details>
  </section>;
}
