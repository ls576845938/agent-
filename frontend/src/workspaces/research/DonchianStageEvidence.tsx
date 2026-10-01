import {DONCHIAN_STAGE_RUN} from './research-run-links';
import MarketStateEvidence from './MarketStateEvidence';

type Row = Record<string, any>;
const flags = ['demo_control_enabled','execution_permission','live','order','paper',
  'private','promotion','real_order','runtime_observed','transfer','withdraw'];
const unverified: Record<string,string> = {
  remaining_5800_hours:'剩余 5800 小时', annual_performance:'全年表现',
  uninterrupted_vs_resumed_annual_equivalence:'连续运行与分批恢复的全年一致性',
  arbitrary_crash_recovery_in_this_run:'本次运行任意崩溃点恢复',
  fresh_repeated_event_injection:'本次新注入的重复事件',
  live_or_demo_exchange_reconciliation:'Demo／真实交易所对账',
  independent_confirmation_or_promotion:'独立确认与晋级',
  formal_frontend_acceptance_of_this_stage_run:'本阶段正式页面验收',
  intrabar_exact_fill_time_or_drawdown:'盘中精确成交时间或最大回撤',
};

export default function DonchianStageEvidence({evidence,runId}:{evidence:Row|null|undefined;runId:string}) {
  const valid = evidence?.selector === runId && runId === DONCHIAN_STAGE_RUN
    && evidence?.identity?.run_id === 'donchian-effective-time-20250901-20260901'
    && evidence?.status === 'stage_baseline_reconciled_research_only'
    && evidence?.truth_kind === 'offline_execution_simulation'
    && evidence?.progress?.paused === true && evidence?.progress?.processed_hours === 2960
    && evidence?.progress?.planned_hours === 8760
    && evidence?.read_only === true && evidence?.historical_source === true
    && evidence?.source_head !== evidence?.publication_head
    && evidence?.counts?.primary_decisions === 30 && evidence?.counts?.protective_exits === 26
    && evidence?.decision_links?.length === 30 && evidence?.roundtrips?.length === 28
    && evidence?.decision_links?.every((row:Row) => row?.ledger_event_id && row?.ledger_event_hash
      && row?.signal_id && row?.target_position_id && row?.risk_check_id && row?.order_intent_id
      && row?.client_order_id && row?.exchange_order_id && Array.isArray(row?.fill_ids))
    && evidence?.roundtrips?.every((row:Row) => row?.open_fill_id && row?.close_fill_id && row?.exit_type)
    && Array.isArray(evidence?.not_verified) && evidence?.economics?.cash_usdt != null
    && evidence?.execution_assumptions?.taker_fee_bps === '5'
    && evidence?.identity?.cost_policy_hash && evidence?.identity?.spec_git
    && flags.every(flag => evidence?.permissions?.[flag] === false);
  if (!valid) return <section className="research-intro-card" data-testid="donchian-stage-evidence">
    <h3>Donchian 历史阶段证据 · 尚未绑定</h3>
    <p>{evidence?.status === 'blocked' ? '提交态封存缺失或校验失败。' :
      evidence?.status === 'not_bound' ? '所选编号未登记。' :
      '缺少精确核验的阶段证据。'}不读取运行目录，也不寻找相似记录替代。</p>
  </section>;
  const e=evidence!;
  return <section className="research-intro-card" data-testid="donchian-stage-evidence" aria-label="Donchian 历史模拟阶段证据">
    <span className="research-eyebrow">HISTORICAL / OFFLINE SIMULATION / RESEARCH ONLY</span>
    <h3>原 Donchian 真实历史业务基线 · 暂停快照</h3>
    <p>这是已核账的历史模拟，不是交易所实际成交、全年评估或独立确认；运行停在 {e.progress.processed_hours} / {e.progress.planned_hours} 小时（余 {e.progress.planned_hours-e.progress.processed_hours} 小时）。页面只读，不恢复运行或授权交易。</p>
    <dl>
      <dt>历史范围</dt><dd>{e.progress.historical_event_start_utc} 至 {e.progress.last_event_end_utc}（原始时间均带 UTC 偏移）；暂停记录 {e.progress.paused_at_utc}</dd>
      <dt>身份与来源</dt><dd>{e.identity.strategy_id} · {e.identity.strategy_version} · 数据 {e.identity.dataset_version}<br/>计算源码 <code>{e.source_head}</code><br/>页面发布源码 <code>{e.publication_head}</code>；二者不同，历史结果不会被重新计算为当前运行。</dd>
      <dt>完成范围</dt><dd>{e.counts.decisions} 次决策 · {e.counts.orders} 个模拟订单 / {e.counts.fills} 笔模拟成交 · {e.counts.roundtrips} 次开平仓 · {e.counts.funding_bills} 条资金费（{e.counts.nonzero_funding_bills} 条非零）</dd>
      <dt>模拟账户</dt><dd>初始 {e.identity.initial_equity_usdt} USDT → 现金／权益 {e.economics.cash_usdt} USDT；当前 {e.economics.position_contracts} 张，未实现盈亏 {e.economics.unrealized_pnl_usdt} USDT</dd>
      <dt>账本复核</dt><dd>价格盈亏 {e.economics.price_pnl_usdt}、手续费现金流 {e.economics.fee_cashflow_usdt}、资金费现金流 {e.economics.funding_cashflow_usdt}，净额 {e.economics.net_usdt} USDT。来源为已提交持久 UOW 的只读重放，不是曲线估计。</dd>
      <dt>固定约束</dt><dd>{e.identity.order_contracts} 张 × {e.identity.contract_value_btc} BTC/张 = 0.0001 BTC；名义上限 {e.identity.nominal_cap_usdt} USDT，亏损门槛 {e.identity.loss_threshold_usdt} USDT。</dd>
      <dt>成本与撮合假设</dt><dd>taker 手续费 {e.execution_assumptions.taker_fee_bps} bps；半侧价差 {e.execution_assumptions.half_spread_bps} bps，已反映在成交价，不重复扣减。资金费以先前可见小时 mark 收盘近似；买卖两侧各假定 {e.execution_assumptions.assumed_depth_contracts_each_side} 张合约深度，未建模队列与市场冲击。盘中精确成交时刻未知；双触顺序无法证明时阻断。</dd>
    </dl>
    <MarketStateEvidence evidence={e.market_state_evidence}/>
    <details><summary>30 条主决策 → 风控／意图／模拟成交／账本引用（仅 ID，无原始信号数值）</summary>
      {e.decision_links.map((row:Row) => <article key={row.client_order_id} className="research-intro-card">
        <h4>{row.event_time_utc} · 客户单 <code>{row.client_order_id}</code></h4>
        <p>信号 <code>{row.signal_id}</code> → 目标 <code>{row.target_position_id}</code> → 风控 <code>{row.risk_check_id}</code> → 意图 <code>{row.order_intent_id}</code></p>
        <p>模拟订单 <code>{row.exchange_order_id}</code> · 模拟成交 <code>{row.fill_ids.join(', ')}</code></p>
        <p>持久账本事件 <code style={{overflowWrap:'anywhere'}}>{row.ledger_event_id}</code> · 哈希 <code style={{overflowWrap:'anywhere'}}>{row.ledger_event_hash}</code></p>
      </article>)}
    </details>
    <details><summary>28 次开平仓及 26 次保护退出（保护退出不补造策略主决策 ID）</summary>
      <p>主决策关联 30 笔成交；另 26 笔为保护退出。开平仓记录只展示回执已核对的成交 ID、价格盈亏、费用与退出类型，盘中精确成交时刻并未验证。</p>
      {e.roundtrips.map((row:Row) => <article key={row.open_fill_id} className="research-intro-card">
        <h4>{row.side} · {row.entry_utc} → {row.exit_window_start_utc} 至 {row.exit_window_end_utc}</h4>
        <p>开仓成交 <code>{row.open_fill_id}</code> · 平仓成交 <code>{row.close_fill_id}</code> · {row.exit_type}</p>
        <p>价格盈亏 {row.price_pnl_usdt} USDT · 双边费用 {row.fees_usdt} USDT · 入场名义 {row.entry_notional_usdt} USDT</p>
      </article>)}
    </details>
    <details><summary>封存与未验证范围</summary>
      <p>参数 SHA-256 <code style={{overflowWrap:'anywhere'}}>{e.identity.params_hash}</code> · 数据 manifest <code style={{overflowWrap:'anywhere'}}>{e.identity.manifest_git_spec}</code> / <code>{e.identity.manifest_sha256}</code></p>
      <p>年度规格 <code style={{overflowWrap:'anywhere'}}>{e.identity.spec_git}</code> · 对象 SHA-256 <code>{e.identity.spec_blob_sha256}</code> · 规格摘要 <code>{e.identity.spec_digest}</code>；原计划评估结束 {e.identity.planned_evaluation_end_utc}，并非本快照已处理到该时刻。</p>
      <p>费用政策 <code>{e.identity.cost_policy_hash}</code> · 撮合政策 <code>{e.identity.matching_policy_hash}</code> · 保护政策 <code>{e.identity.protection_policy_hash}</code> · 保护生效时间政策 <code>{e.identity.protection_time_policy_hash}</code></p>
      <p>原机器回执 SHA-256 <code>{e.source_receipt_sha256}</code> · 原报告 SHA-256 <code>{e.source_report_sha256}</code> · 提交态小封存 SHA-256 <code>{e.snapshot_sha256}</code></p>
      <p>提交引用 <code>{e.manifest_ref}</code>；核验完成 {e.verification_finished_at_utc}。未从运行目录读取原始日志。</p>
      <p>未验证：{e.not_verified.map((code:string) => unverified[code] || code).join('、')}。M3／M4、Demo、paper、live 和真实订单仍未开放。</p>
    </details>
  </section>;
}
