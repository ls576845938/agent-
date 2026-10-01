import {useState} from 'react';

type Row = Record<string, any>;

const safetyFlags = ['demo_control_enabled','execution_permission','live','order','paper',
  'private','promotion','real_order','runtime_observed','transfer','withdraw'];
const trialSafetyFlags = [...safetyFlags,'network_accessed'];
const blockedSafetyFlags = ['demo_enabled','paper_enabled','live_enabled','promotion_enabled',
  'private_endpoint_accessed','real_order_submitted','network_accessed','runtime_observed'];

const groupLabels: Record<string,string> = {
  low:'低效率', mixed:'混合', directional:'方向性', unknown:'未知',
};

const validGroup = (group: Row | undefined, count: number) => !!group
  && group.roundtrips === count && group.funding_usdt == null
  && typeof group.price_pnl_usdt === 'string'
  && typeof group.fees_usdt === 'string'
  && typeof group.price_pnl_minus_fees_usdt === 'string';

const shown = (value: unknown) => value == null ? '缺失' : String(value);

const validDecisionEffect = (effect: Row | undefined) => {
  const entry=effect?.market_entry_policy;
  const state=effect?.selected_state;
  const paths=state?.path_efficiency_by_horizon;
  return !!effect && effect.phase === 'market_entry_policy'
    && typeof effect.event_id === 'string' && effect.event_id.length > 0
    && !!entry && !!state && state.asset === 'BTC-USDT-SWAP'
    && entry.state_binding_status === 'verified'
    && ['consumer_phase','exact_state_hash_join'].includes(state.projection_source)
    && ['complete','partial'].includes(state.projection_status)
    && Array.isArray(state.missing_fields)
    && state.definition_version === 'market_state_descriptive_v2'
    && state.status === entry.state_status && state.cutoff_time === entry.state_cutoff_utc
    && state.content_hash === entry.state_content_hash && state.input_hash === entry.state_input_hash
    && state.definition_hash === entry.state_definition_hash
    && state.source_binding_hash === entry.state_source_binding_hash
    && !!paths && Object.keys(paths).sort().join(',') === '168,24,72';
};

/** Render only a backend-validated, committed small projection. Never computes or runs a policy. */
export default function MarketStateEvidence({evidence}:{evidence:Row|null|undefined}) {
  const [selectedEventId,setSelectedEventId]=useState('');
  const description=evidence?.description;
  const stratification=evidence?.stratification;
  const trial=evidence?.policy_trial;
  const sealedTrial=evidence?.policy_trial_evidence;
  const runtime=evidence?.runtime_status;
  const units=stratification?.sample_units;
  const groups=stratification?.trade_groups;
  const valid=evidence?.schema_version === 'market_state_stage_diagnostic_v1'
    && evidence?.status === 'completed_exploratory_research_only'
    && evidence?.truth_kind === 'historical_market_state_diagnostic'
    && evidence?.usage === 'description_and_precommitted_entry_policy_design_only'
    && evidence?.read_only === true
    && description?.definition_version === 'market_state_descriptive_v2'
    && description?.observed_bars === 2960 && description?.unknown_bars === 0
    && units?.bars === 2960 && units?.roundtrips === 28
    && units?.contiguous_state_segments === 170
    && stratification?.entry_join?.matched_roundtrips === 28
    && stratification?.entry_join?.nearest_time_matching === false
    && validGroup(groups?.low,18) && validGroup(groups?.mixed,9)
    && validGroup(groups?.directional,1) && validGroup(groups?.unknown,0)
    && stratification?.funding?.allocation === 'unavailable_per_trade'
    && stratification?.prediction_metrics?.ic === 'not_applicable'
    && stratification?.prediction_metrics?.rank_ic === 'not_applicable'
    && trial?.status === 'not_started' && trial?.effect_verified === false
    && trial?.counterfactual_entry_count_only === 18
    && runtime?.attachment_consumed_by_btc_runtime === false
    && runtime?.entry_policy_enabled === false
    && runtime?.execution_effect_observed === false
    && safetyFlags.every(flag => evidence?.[flag] === false);

  if (!valid) return <section className="research-intro-card" data-testid="market-state-evidence">
    <h3>市场状态证据不可核验</h3>
    <p>{evidence?.status === 'blocked' ? '独立封存缺失或校验失败。' :
      '没有与所选历史运行精确绑定的提交态证据。'}不会在页面请求中补算，也不会借用其他运行。</p>
  </section>;

  const optional=description.optional_input_coverage || {};
  const baseline=sealedTrial?.arms?.original_donchian;
  const policyArm=sealedTrial?.arms?.original_donchian_plus_frozen_entry_policy;
  const comparison=sealedTrial?.comparison;
  const decisionEffects=Array.isArray(sealedTrial?.decision_effects) ? sealedTrial.decision_effects : [];
  const validSealedTrial=sealedTrial?.schema_version === 'market_policy_trial_report_v1'
    && sealedTrial?.trial_id === 'donchian-stage-market-policy-trial-20260927-v1'
    && sealedTrial?.status === 'completed_exploratory_research_only'
    && sealedTrial?.truth_kind === 'offline_policy_ab_replay'
    && sealedTrial?.usage === 'policy_effect_estimation_only_not_promotion'
    && sealedTrial?.read_only === true && sealedTrial?.effect_verified === true
    && baseline?.arm_id === 'original_donchian' && baseline?.processed_events === 2960
    && baseline?.new_entries_rejected === 0
    && policyArm?.arm_id === 'original_donchian_plus_frozen_entry_policy'
    && policyArm?.processed_events === 2960
    && policyArm?.new_entries_rejected === decisionEffects.length
    && decisionEffects.length > 0 && decisionEffects.every(validDecisionEffect)
    && comparison?.effect_interpretation === 'exploratory_only'
    && comparison?.improvement_claim_supported === false && comparison?.promotion_supported === false
    && sealedTrial?.invariants?.same_base_strategy === true
    && sealedTrial?.invariants?.same_data === true && sealedTrial?.invariants?.same_cost === true
    && sealedTrial?.invariants?.same_time_contract === true
    && sealedTrial?.invariants?.same_simulated_account === true
    && sealedTrial?.invariants?.no_training === true
    && sealedTrial?.invariants?.no_parameter_search === true
    && sealedTrial?.invariants?.entry_policy_only_changed_new_entry === true
    && sealedTrial?.invariants?.existing_position_exit_and_protection_not_overridden === true
    && trialSafetyFlags.every(flag => sealedTrial?.[flag] === false);
  const validBlockedTrial=sealedTrial?.schema_version === 'market_policy_trial_blocked_read_model_v1'
    && sealedTrial?.trial_id === 'donchian-stage-market-policy-trial-20260927-v1'
    && sealedTrial?.status === 'blocked_fail_closed'
    && sealedTrial?.truth_kind === 'sealed_blocked_stage_read_model'
    && sealedTrial?.usage === 'blocked_stage_diagnostic_only_not_effect_estimation_not_promotion'
    && sealedTrial?.read_only === true && sealedTrial?.effect_verified === false
    && baseline?.arm_id === 'original_donchian' && baseline?.status === 'completed'
    && baseline?.processed_events === 2960 && baseline?.expected_events === 2960
    && baseline?.ledger_receipt?.reconciled === true
    && baseline?.terminal_position?.position_contracts === '0'
    && baseline?.terminal_position?.status === 'flat'
    && policyArm?.arm_id === 'original_donchian_plus_frozen_entry_policy'
    && policyArm?.status === 'blocked_fail_closed'
    && policyArm?.processed_events === 1956 && policyArm?.expected_events === 2960
    && policyArm?.ledger_receipt?.reconciled === true
    && policyArm?.terminal_position?.position_contracts === '-0.01'
    && policyArm?.terminal_position?.status === 'nonflat_blocked_preserved'
    && policyArm?.blockers?.length === 1
    && policyArm.blockers[0] === 'ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous'
    && policyArm?.blocked_event_time_utc === '2025-11-21T20:00:00+08:00'
    && sealedTrial?.rejected_entry_phase_count === 48
    && Array.isArray(sealedTrial?.limitations)
    && sealedTrial.limitations.includes('conditioned_arm_incomplete_1956_of_2960')
    && sealedTrial.limitations.includes('intrabar_protection_double_touch_order_unknown_fail_closed')
    && sealedTrial.limitations.includes('no_complete_ab_effect_estimate')
    && sealedTrial.limitations.includes('exploratory_only_not_promotion_evidence')
    && blockedSafetyFlags.every(flag => sealedTrial?.safety?.[flag] === false);
  const selectedEffect=validSealedTrial
    ? decisionEffects.find((effect:Row)=>effect.event_id===selectedEventId) || decisionEffects[0]
    : null;
  const selectedState=selectedEffect?.selected_state;
  const selectedEntry=selectedEffect?.market_entry_policy;
  const selectedPaths=selectedState?.path_efficiency_by_horizon || {};
  return <section className="research-intro-card" data-testid="market-state-evidence" aria-label="统一市场状态历史诊断">
    <span className="research-eyebrow">MARKET STATE V2 / HISTORICAL DIAGNOSTIC / READ ONLY</span>
    <h3>统一市场状态 · 描述与分组证据</h3>
    <p>这是同一段历史行情的因果状态描述，不是实时运行观测，也不是策略有效性或交易准入结论。状态标签只用于解释：低效率 &lt; 0.20、混合 &lt; 0.40、方向性 ≥ 0.40。</p>
    <dl>
      <dt>三种样本单位</dt><dd>{units.bars} 根状态观测 · {units.roundtrips} 次开平仓 · {units.contiguous_state_segments} 个连续状态片段。三者不能互换；170 个片段不是 170 笔独立交易。</dd>
      <dt>入场时状态</dt><dd>{groupLabels.low} {groups.low.roundtrips} · {groupLabels.mixed} {groups.mixed.roundtrips} · {groupLabels.directional} {groups.directional.roundtrips}。这些计数不能解释为概率、胜率或独立样本。</dd>
      <dt>精确关联</dt><dd>以开仓成交 ID 找到唯一主决策成交，再按精确事件时间关联状态；没有使用最近时间拼接。</dd>
      <dt>缺失输入</dt><dd>{optional.funding === 'missing_from_state_input' && optional.open_interest === 'missing_from_state_input' && optional.depth === 'missing_from_state_input'
        ? '资金费、OI、深度均未进入本次状态输入；没有补造数值。' : '可选输入覆盖不可核验。'}</dd>
      <dt>预测指标</dt><dd>Donchian 是规则策略，没有预测序列；IC／Rank IC 不适用。</dd>
      <dt>资金费边界</dt><dd>资金费仅有总体 {stratification.funding.total_only_usdt} USDT，无法逐笔分配；下表只比较价格盈亏减手续费。</dd>
    </dl>
    <div className="qlib-layer-grid">
      {(['low','mixed','directional'] as const).map(label => <article key={label}>
        <h4>{groupLabels[label]} · {groups[label].roundtrips} 次开平仓</h4>
        <p>价格盈亏 {groups[label].price_pnl_usdt} USDT</p>
        <p>手续费 {groups[label].fees_usdt} USDT</p>
        <p>价格盈亏减手续费 {groups[label].price_pnl_minus_fees_usdt} USDT</p>
        <p>逐笔资金费：不可分配</p>
      </article>)}
    </div>
    <section className="research-intro-card" aria-label="市场状态条件政策状态">
      <h4>预先冻结的入场政策</h4>
      <p>假设：当前空仓且原策略产生非零目标时，若 72 小时路径效率未知或低于 0.20，则只拒绝本次新增仓位；已有持仓、减仓、退出和保护义务不受影响。</p>
      <p><strong>历史时态：</strong>原阶段封存时 <code>policy_trial=not_started</code>、运行时未消费；后续独立 A/B（如存在）是另一份只读封存，不会改写原阶段证据。</p>
      {validSealedTrial ? <>
        <h4>固定 A/B 已完成 · 探索性证据</h4>
        <div className="qlib-layer-grid">
          <article><h4>原 Donchian</h4><p>新增提议 {baseline.new_entries_proposed} · 拒绝 {baseline.new_entries_rejected} · 执行 {baseline.new_entries_executed}</p><p>开平仓 {baseline.roundtrips} · 净额 {baseline.net_usdt} USDT · 最大回撤 {baseline.max_drawdown_usdt} USDT</p></article>
          <article><h4>条件政策臂</h4><p>新增提议 {policyArm.new_entries_proposed} · 拒绝新增 {policyArm.new_entries_rejected} · 执行 {policyArm.new_entries_executed}</p><p>开平仓 {policyArm.roundtrips} · 净额 {policyArm.net_usdt} USDT · 最大回撤 {policyArm.max_drawdown_usdt} USDT</p></article>
        </div>
        <p>敞口 {baseline.exposure_contract_hours} → {policyArm.exposure_contract_hours} 合约小时；持仓 {baseline.holding_hours} → {policyArm.holding_hours} 小时。</p>
        <p>净额差 {comparison.net_usdt_delta} USDT · 最大回撤差 {comparison.max_drawdown_usdt_delta} USDT · 开平仓差 {comparison.roundtrips_delta}。</p>
        <p>{sealedTrial.decision_effects.length} 条拒绝决策已绑定到原信号、目标和状态哈希，且没有生成订单、成交或账本事件。</p>
        <section aria-label="拒绝决策明细">
          <h4>拒绝决策明细 · 同一次决策的多尺度状态</h4>
          <label htmlFor="market-policy-decision">选择决策</label>
          <select id="market-policy-decision" value={selectedEffect?.event_id || ''}
            onChange={(event:{target:{value:string}})=>setSelectedEventId(event.target.value)}>
            {decisionEffects.map((effect:Row)=><option key={effect.event_id} value={effect.event_id}>
              {effect.event_id} · {shown(effect.selected_state?.decision_time)}
            </option>)}
          </select>
          <dl>
            <dt>资产／决策时间</dt><dd>{shown(selectedState?.asset)} · {shown(selectedState?.decision_time)}</dd>
            <dt>数值投影</dt><dd>{shown(selectedState?.projection_source)} · {shown(selectedState?.projection_status)}{selectedState?.missing_fields?.length ? ` · 缺失 ${selectedState.missing_fields.join('、')}` : ' · 完整'}</dd>
            <dt>状态质量</dt><dd>质量 {shown(selectedState?.status)} · 原因 {selectedState?.reasons?.length ? selectedState.reasons.join('、') : '无'} · 截止 {shown(selectedState?.cutoff_time)}</dd>
            <dt>多尺度路径效率</dt><dd>24h {shown(selectedPaths['24'])} · 72h {shown(selectedPaths['72'])} · 168h {shown(selectedPaths['168'])}</dd>
            <dt>方向</dt><dd>方向 {shown(selectedState?.direction_label)} · 方向分数 {shown(selectedState?.direction_score)} · 归一化强度 {shown(selectedState?.normalized_trend_strength)}</dd>
            <dt>波动</dt><dd>Bar 波动 {shown(selectedState?.bar_volatility)} · 年化 {shown(selectedState?.annualized_volatility)} · 历史相对位置 {shown(selectedState?.volatility_relative_position)}</dd>
            <dt>冲击／扩缩</dt><dd>冲击 {shown(selectedState?.shock_score)} · 扩缩 {shown(selectedState?.volatility_expansion_ratio)}（{shown(selectedState?.volatility_regime)}）</dd>
            <dt>目标处理</dt><dd>目标 {shown(selectedEntry?.original_target_contracts)} → {shown(selectedEntry?.effective_target_contracts)} · {shown(selectedEntry?.reason)}</dd>
          </dl>
          <p>空值显示为“缺失”，不会补成 0 或“正常”。<code>consumer_phase</code> 只证明当时的状态身份、质量和截止时间；若没有按 content hash 精确封存的完整状态对象，多尺度数值必须保持缺失，绝不借用最后状态或最近时点。本清单只投影政策实际拒绝的新入场；其他订单、退出、保护和账本关系仍以两臂原始封存及核账回执为准。</p>
        </section>
        <p><strong>只能作为探索性增量证据：</strong>必须同时考虑敞口与持仓时长变化，不能单凭净额或回撤差宣布改善；不支持晋级、Demo、paper 或 live。</p>
      </> : validBlockedTrial ? <>
        <h4>固定 A/B 未完成 · 安全阻断</h4>
        <div className="qlib-layer-grid">
          <article><h4>原 Donchian</h4><p>{baseline.processed_events} / {baseline.expected_events} 事件 · 账本已核对</p><p>终态持仓 {baseline.terminal_position.position_contracts} 张（已结清）</p></article>
          <article><h4>条件政策臂</h4><p>{policyArm.processed_events} / {policyArm.expected_events} 事件 · 失败关闭</p><p>阻断时间 {policyArm.blocked_event_time_utc}</p></article>
        </div>
        <p><strong>阻断原因：</strong>同一小时 K 线内保护价位双触达，无法确定先后；系统没有选择有利成交顺序，而是停止条件臂。</p>
        <p>条件政策臂终态持仓 {policyArm.terminal_position.position_contracts} 张已保留，未伪平仓；其账本、资金费与快照已核对。</p>
        <p>{sealedTrial.rejected_entry_phase_count} 条政策拒绝 phase 已在原封存中通过身份、partial/null 和状态绑定校验；本页仅展示封存计数，没有将旧 28 笔交易状态拼接为新 phase 钻取。</p>
        <p><strong>没有完整政策效果结论。</strong>两臂没有共同完成预定的 2960 事件，因此不计算完整 A/B 差额，不支持改善、晋级或交易授权声明。</p>
      </> : sealedTrial?.status === 'blocked' ? <p role="status"><strong>A/B 封存不可核验。</strong>已阻断展示，不使用测试 fixture、旧分组或相似运行替代真实结果。</p> : <>
        <p><strong>当前尚无已封存 A/B 结果；这不代表后台任务未运行。</strong>原阶段封存不包含政策试验结果，效果尚未验证。历史标签显示有 {trial.counterfactual_entry_count_only} 次入场可能被拒绝，这只是事后计数，不代表少交易后表现改善，也没有重算新的成交、持仓、资金费或账本。</p>
        <p>固定预算：{trial.budget.fixed_replays} 个回放臂 · 训练 {trial.budget.training_runs} 次 · 搜参 {trial.budget.parameter_searches} 次。正式 A/B 必须同时比较敞口与持仓时长，不能把风险暴露减少直接解释为识别能力提高。</p>
      </>}
      <p><strong>{validSealedTrial || validBlockedTrial ? '生产／默认运行未消费：' : '原阶段封存时未消费：'}</strong>{validSealedTrial || validBlockedTrial
        ? 'attachment 只在隔离历史 A/B 中消费；默认 BTC 运行仍未启用 entry policy。'
        : 'attachment 未接入本次 BTC 运行，entry policy 未启用，执行效果未观测；'}Demo、paper、live、账户和订单权限均保持关闭。</p>
    </section>
    <details><summary>版本与只读封存</summary><pre>{JSON.stringify({
      definition_version:description.definition_version,
      definition_hash:description.definition_hash,
      series_content_hash:description.series_content_hash,
      source_binding_hash:description.source_binding_hash,
      protocol:evidence.protocol,
      artifact_sha256:evidence.artifact_sha256,
      manifest_ref:evidence.manifest_ref,
    },null,2)}</pre></details>
  </section>;
}
