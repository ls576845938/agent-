import {DONCHIAN_OFFLINE_RUN} from './research-run-links';

type Row = Record<string, any>;
const flags = ['demo_control_enabled','execution_permission','live','order','paper',
  'private','promotion','real_order','runtime_observed','transfer','withdraw'];
const phaseNames: Record<string,string> = {
  primary:'开多', hold:'持有，不产生新订单', reversal_close:'反向前先平多',
  reversal_open:'反向开空', exit:'退出归零',
};

export default function DonchianOfflineEvidence({evidence,runId}:{evidence:Row|null|undefined;runId:string}) {
  const valid = evidence?.selector === runId && runId === DONCHIAN_OFFLINE_RUN
    && evidence?.status === 'sealed_offline_summary'
    && evidence?.truth_kind === 'offline_execution_simulation'
    && evidence?.identity?.run_id === 'v3donchian01'
    && evidence?.read_only === true
    && flags.every(flag => evidence?.permissions?.[flag] === false);
  if (!valid) return <section className="research-intro-card" data-testid="donchian-offline-evidence">
    <h3>Donchian 离线证据 · 尚未绑定</h3>
    <p>{evidence?.status === 'blocked' ? '封存摘要缺失或校验失败。' :
      evidence?.status === 'not_bound' ? '所选编号未绑定该策略版本。' :
      '没有精确核验的封存证据。'}未读取其他运行替代。</p>
  </section>;
  const e=evidence!;
  return <section className="research-intro-card" data-testid="donchian-offline-evidence" aria-label="Donchian 离线决策与经济证据">
    <span className="research-eyebrow">V3 / Donchian / 确定性离线测试</span>
    <h3>原策略五阶段纵向闭环</h3>
    <p>这是固定测试行情和模拟账户的验证，不是自然历史收益、真实账户或运行成交。页面只读，不执行、恢复或授权交易。</p>
    <p>决策 {e.counts.decisions} · 模拟订单 {e.counts.orders} · 模拟成交 {e.counts.fills} · 决策关联账本事件 {e.counts.ledger_events}</p>
    <dl>
      <dt>策略与参数</dt><dd>{e.identity.strategy_version} · <code>{e.identity.params_hash}</code></dd>
      <dt>计算源码与数据版本</dt><dd><code>{e.source_head}</code> · {e.identity.data_version}</dd>
      <dt>输入与成交价</dt><dd>行情仅用于信号（{e.scenario.market_data_usage}）；模拟器固定成交价 {e.scenario.simulated_execution_price} USDT，不是该行情的成交回报。</dd>
      <dt>模拟账户结果</dt><dd>末期权益 {e.final.equity_usdt} USDT · 仓位 {e.final.position_contracts} 张 · 手续费现金流 {e.final.fee_cashflow_usdt} USDT · 实际资金费现金流 {e.final.funding_cashflow_usdt} USDT</dd>
      <dt>输入封存</dt><dd><code>{e.fixture_path} · {e.fixture_sha256}</code></dd>
    </dl>
    <details open><summary>逐次决策：信号 → 风控 → 订单 → 成交 → 持久账本</summary>
      {e.stages.map((row:Row) => {const links=row.evidence.links;return <article key={row.evidence.decision_id} className="research-intro-card">
        <h4>{phaseNames[row.phase] || row.phase} · {row.completed_bar_close_utc}</h4>
        <p>决策 <code>{row.evidence.decision_id}</code> · 输入 <code>{row.evidence.input_digest}</code></p>
        <p>信号 {row.signal?.direction || row.signal?.raw_signal || '未给出方向'} · 目标 {row.target_position?.target_quantity ?? row.signal?.target_contracts ?? '未知'} 张 · 风控 {row.risk_decision?.approved === true ? '通过' : '本次无新增订单'}</p>
        {row.phase === 'hold' ? <p>持有阶段：无新订单、无新成交、无新账本事件；沿用已存在的模拟仓位。</p> : <>
          <p>动作 {row.order_plan?.action} · 意图 <code>{links.order_intent_id}</code> · 客户单 <code>{links.client_order_id}</code> · 模拟订单 <code>{links.exchange_order_id}</code></p>
          <p>模拟成交 {row.fills.map((fill:Row)=><span key={fill.fill_id}><code>{fill.fill_id}</code> · {fill.size} 张 @ {fill.price} USDT · 手续费 {fill.fee} USDT</span>)}</p>
          <p>账本事件 #{row.ledger.sequence} <code>{row.ledger.event_id}</code> · 哈希 <code>{row.ledger.event_hash}</code></p>
        </>}
        <p>本次后权益 {row.after.equity_usdt} USDT · 仓位 {row.after.position_contracts} 张</p>
      </article>;})}
    </details>
    <details><summary>版本与封存校验</summary>
      <p>策略包 <code>{e.identity.package_digest}</code> · 运行身份 <code>{e.identity.identity_digest}</code></p>
      <p>摘要 SHA-256 <code>{e.summary_sha256}</code> · 发布引用 <code>{e.manifest_ref}</code></p>
      <p>{e.historical_source ? '计算源码为历史版本；当前页面读取其提交态证据。' : '计算源码与当前提交相同。'}</p>
    </details>
  </section>;
}
