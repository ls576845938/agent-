import type {
  BtcAttackSleeveRiskStressReport,
  BtcAttackFollowupReviewReport,
  BtcAttackStrategyContinuationShortlistReport,
  BtcLeakageOverfitAuditReport,
  BtcMicroLiveExperimentPacketReport,
  BtcOperatorSummaryResponse,
  BtcPromotionGateControlReport,
  BtcResearchControlCenterResponse,
  BtcStrategyLedgerLine,
  BtcStrategyLedgerReport,
} from '../../lib/shared-types';

type Props = {
  control: BtcResearchControlCenterResponse | null;
  summary: BtcOperatorSummaryResponse | null;
  summaryLoading: boolean;
  summaryMessage: string;
  detailsLoading: boolean;
  detailsMessage: string;
  onRefreshSummary: () => void;
  onLoadDetails: () => void;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function text(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : fallback;
  return String(value);
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function pct(value: unknown, digits = 2): string {
  const numberValue = num(value);
  return numberValue === null ? '-' : `${numberValue.toFixed(digits)}%`;
}

function compact(value: unknown, maxLength = 110): string {
  if (value === null || value === undefined || value === '') return '-';
  const raw = typeof value === 'string' ? value : JSON.stringify(value);
  if (!raw) return '-';
  return raw.length > maxLength ? `${raw.slice(0, maxLength)}...` : raw;
}

function shortDate(value: unknown): string {
  return typeof value === 'string' && value ? value.slice(0, 19).replace('T', ' ') : '-';
}

function statusTone(status: unknown): 'good' | 'bad' | 'neutral' {
  const raw = String(status ?? '').toLowerCase();
  if (raw.includes('pass') || raw.includes('complete') || raw === 'ok') return 'good';
  if (raw.includes('fail') || raw.includes('block') || raw.includes('violation') || raw.includes('missing')) return 'bad';
  return 'neutral';
}

function statusText(status: unknown): string {
  const raw = String(status ?? '');
  if (!raw) return '-';
  if (raw.includes('safety_violation')) return '安全冲突，已 fail-closed';
  if (raw.includes('complete_research_only')) return '研究完成，只读';
  if (raw.includes('incomplete_research_only')) return '研究未完成，只读';
  if (raw.includes('blocked')) return '阻塞';
  if (raw.includes('missing')) return '缺失';
  return raw;
}

function gateLabel(id: string, name?: string): string {
  const known: Record<string, string> = {
    data_gate: '数据门',
    strategy_gate: '策略门',
    risk_gate: '风控门',
    execution_gate: '执行门',
    kill_switch_gate: '熔断门',
    drawdown_stress_gate: '回撤/压力门',
    leakage_overfit_gate: '未来函数/过拟合门',
    manual_review_gate: '人工复核门',
  };
  return known[id] ?? name ?? id;
}

function signalSummary(line: BtcStrategyLedgerLine): string {
  const signal = asRecord(line.latest_signal_or_exposure);
  const kind = text(signal.kind, '');
  if (kind === 'latest_top5_signals') {
    const items = asArray<Record<string, unknown>>(signal.items);
    const flatCount = items.filter((item) => text(item.exposure_side, '') === 'flat').length;
    return `Top5 信号 ${items.length} 个，空仓 ${flatCount} 个`;
  }
  if (kind === 'attack_sleeve_latest_observation') {
    const dailySignal = asRecord(signal.daily_signal);
    const exposure = asRecord(signal.theoretical_sleeve_exposure);
    return `方向 ${text(dailySignal.side)}，暴露 sleeve ${text(exposure.exposed_sleeve_count)}，-10% 后剩 ${pct(signal.remaining_after_10pct_spike_pct)}`;
  }
  if (kind === 'high_yield_observe_only') {
    return `高收益观察 ${text(signal.observation_count)} 次，最新 ${shortDate(signal.latest_decision_time)}`;
  }
  if (kind === 'raw_trend_forward_observation') {
    return `raw trend ${text(signal.status)}，观察 ${text(signal.observation_days)} 天`;
  }
  if (kind === 'auxiliary_forecast_diagnostic') {
    const researchDecision = asRecord(signal.research_decision);
    return `TimesFM 辅助：${text(researchDecision.status, '诊断中')}`;
  }
  return compact(signal, 120);
}

function keyChecks(checks: Record<string, unknown> | undefined): Array<[string, unknown]> {
  return Object.entries(checks ?? {})
    .filter(([, value]) => typeof value !== 'object' || value === null)
    .slice(0, 4);
}

function boolCn(value: unknown, fallback = '-'): string {
  if (value === true) return '是';
  if (value === false) return '否';
  return fallback;
}

function boolTone(value: unknown, trueIsBad = false): 'good' | 'bad' | 'neutral' {
  if (value === true) return trueIsBad ? 'bad' : 'good';
  if (value === false) return trueIsBad ? 'good' : 'bad';
  return 'neutral';
}

function rootCauseName(value: unknown): string {
  const id = String(value ?? '');
  const known: Record<string, string> = {
    data_wait: '数据等待',
    runtime_not_connected: 'Runtime 未接通',
    strategy_overfit: '策略过拟合/边界候选',
    strategy_overfit_or_forward_gap: '策略过拟合/观察期不足',
    manual_attestation: '人工证明缺失',
    manual_review_approval_missing: '人工审批缺失',
    operator_paper_intake_envelope_missing: 'paper准入额度未批',
    execution_evidence_missing: '执行证据不足',
    safety_fail_closed: '安全字段冲突',
  };
  return known[id] ?? text(value);
}

function operatorReason(value: unknown): string {
  const raw = text(value);
  if (raw.includes('OKX depth')) return 'OKX depth 盘口覆盖还没满 14 天，还要继续自动采集。';
  if (raw.includes('gate fill')) return 'gate fill 为 0，还没有可映射到盘口的策略成交样本。';
  if (raw.includes('depth-aware slippage')) return 'depth-aware slippage 还没通过历史验证。';
  if (raw.includes('observe-only')) return 'observe-only 观察期未满 30/60 天，不能作为 paper 证据。';
  if (raw.includes('execution replay')) return 'execution replay 还没有真实策略成交链路证据。';
  if (raw.includes('paper readiness') || raw.includes('fail-closed')) return '旧 paper readiness 与当前 gate blocked 冲突，按 fail-closed 处理。';
  if (raw.includes('manual approval')) return '人工审批缺失。';
  return raw;
}

function ReportHeader({
  title,
  status,
  generatedAt,
  children,
}: {
  title: string;
  status?: string;
  generatedAt?: string;
  children?: unknown;
}) {
  return (
    <div className="panel-header btc-section-header">
      <div>
        <h2>{title}</h2>
        {children ? <p className="panel-subtitle">{children}</p> : null}
      </div>
      <span className={`status-tag ${statusTone(status)}`}>{statusText(status)}</span>
      {generatedAt ? <small>{shortDate(generatedAt)}</small> : null}
    </div>
  );
}

function OperatorControlCenterSection({control}: {control: BtcResearchControlCenterResponse | null}) {
  const operatorSummary = asRecord(control?.operator_summary);
  const rootBlockers = asRecord(operatorSummary.root_blockers);
  const topRootCauses = asArray<Record<string, unknown>>(rootBlockers.top_root_causes);
  const dataWaitTasks = asArray<Record<string, unknown>>(rootBlockers.data_wait_items);
  const developmentTasks = asArray<Record<string, unknown>>(rootBlockers.immediate_development_items);
  const killSwitch = asRecord(operatorSummary.kill_switch);
  const attestation = asRecord(operatorSummary.attestation);
  const runtime = asRecord(operatorSummary.runtime_freshness);
  const forbidden = asRecord(operatorSummary.paper_live_forbidden);
  const forbiddenReasons = asArray<string>(forbidden.reasons);

  return (
    <section className="btc-control-section btc-operator-panel" data-testid="btc-operator-control-center">
      <ReportHeader title="Operator Control Center" status={control?.status} generatedAt={control?.generated_at_utc}>
        只做可观测：展示根因、kill switch、账号证明、runtime 新鲜度、paper/live 禁止原因；本面板不提供解锁、下单或绕过 gate 的入口。
      </ReportHeader>

      <div className="btc-operator-grid">
        <article className="btc-operator-card" data-testid="btc-root-blockers">
          <div className="btc-operator-card-head">
            <span>Root blockers</span>
            <strong>{text(rootBlockers.root_cause_count)} 个根因</strong>
          </div>
          <p>原始 blocker {text(rootBlockers.raw_blocker_count)} 个，压缩比 {text(rootBlockers.compression_ratio_raw_to_root)}。</p>
          <p>主导根因：<strong>{rootCauseName(rootBlockers.dominant_root_cause_id)}</strong></p>
          <div className="btc-operator-list">
            {topRootCauses.slice(0, 4).map((row, index) => (
              <div key={`${text(row.root_cause_id)}-${index}`} className="btc-operator-row">
                <span>{rootCauseName(row.root_cause_id ?? row.label_cn)}</span>
                <strong>{text(row.raw_blocker_count ?? row.blocker_count)} 项</strong>
              </div>
            ))}
          </div>
          <div className="btc-task-queue" data-testid="btc-root-cause-task-queue">
            <strong>数据等待项</strong>
            {(dataWaitTasks.length ? dataWaitTasks : []).slice(0, 4).map((task, index) => (
              <p key={`data-${text(task.root_cause_id)}-${index}`}>{rootCauseName(task.root_cause_id)}：{text(task.next_command)}</p>
            ))}
            <strong>可立即开发项</strong>
            {(developmentTasks.length ? developmentTasks : []).slice(0, 4).map((task, index) => (
              <p key={`dev-${text(task.root_cause_id)}-${index}`}>{rootCauseName(task.root_cause_id)}：{text(task.next_command)}</p>
            ))}
          </div>
        </article>

        <article className="btc-operator-card" data-testid="btc-kill-switch-card">
          <div className="btc-operator-card-head">
            <span>Kill switch</span>
            <strong className={`status-tag ${statusTone(killSwitch.status)}`}>{statusText(killSwitch.status)}</strong>
          </div>
          <div className="btc-operator-locks">
            <span className={`btc-lock-pill ${boolTone(killSwitch.kill_switch_engaged, true)}`}>拉闸 {boolCn(killSwitch.kill_switch_engaged)}</span>
            <span className={`btc-lock-pill ${boolTone(killSwitch.cancel_only_mode, true)}`}>cancel-only {boolCn(killSwitch.cancel_only_mode)}</span>
            <span className={`btc-lock-pill ${boolTone(killSwitch.reduce_only_mode, false)}`}>reduce-only {boolCn(killSwitch.reduce_only_mode)}</span>
            <span className={`btc-lock-pill ${boolTone(killSwitch.paper_order_intake_allowed, false)}`}>paper intake {boolCn(killSwitch.paper_order_intake_allowed)}</span>
          </div>
          <p>人工审批记录：{boolCn(killSwitch.manual_approval_recorded)}。当前只允许观察和本地校验，不允许新增订单。</p>
        </article>

        <article className="btc-operator-card" data-testid="btc-attestation-card">
          <div className="btc-operator-card-head">
            <span>API / Account Attestation</span>
            <strong className={`status-tag ${statusTone(attestation.status)}`}>{statusText(attestation.status)}</strong>
          </div>
          <div className="btc-operator-list">
            <div className="btc-operator-row"><span>withdraw=false 已证明</span><strong>{boolCn(attestation.withdraw_permission_verified_false)}</strong></div>
            <div className="btc-operator-row"><span>data/paper/live 分离</span><strong>{boolCn(attestation.data_paper_live_identifiers_unique)}</strong></div>
            <div className="btc-operator-row"><span>paper 权限证明</span><strong>{boolCn(attestation.credential_permissions_verified)}</strong></div>
            <div className="btc-operator-row"><span>人工审批</span><strong>{boolCn(attestation.manual_approval_recorded)}</strong></div>
          </div>
          <p>当前 key 只显示脱敏标识：{text(attestation.paper_key_redacted_identifier)}；页面不读取、不输出真实 key。</p>
        </article>

        <article className="btc-operator-card" data-testid="btc-runtime-card">
          <div className="btc-operator-card-head">
            <span>Runtime freshness</span>
            <strong className={`status-tag ${statusTone(runtime.status)}`}>{statusText(runtime.status)}</strong>
          </div>
          <div className="btc-operator-list">
            <div className="btc-operator-row"><span>server time offset</span><strong>{text(runtime.server_time_offset_ms)} ms</strong></div>
            <div className="btc-operator-row"><span>public WS</span><strong>{text(runtime.public_ws_status)}</strong></div>
            <div className="btc-operator-row"><span>private WS</span><strong>{text(runtime.private_ws_status)}</strong></div>
            <div className="btc-operator-row"><span>gapfill recovered</span><strong>{boolCn(runtime.ws_gapfill_recovered)}</strong></div>
            <div className="btc-operator-row"><span>paper replay ready</span><strong>{boolCn(runtime.paper_runtime_replay_ready)}</strong></div>
            <div className="btc-operator-row"><span>simulated fills</span><strong>{text(runtime.simulated_fill_count)}</strong></div>
          </div>
          <p>metadata：{text(runtime.metadata_version)}；最近市场数据：{shortDate(runtime.last_market_data_time_utc)}。</p>
        </article>

        <article className="btc-operator-card btc-operator-card-wide" data-testid="btc-paper-live-reasons">
          <div className="btc-operator-card-head">
            <span>Paper / Live 禁止原因</span>
            <strong>fail-closed</strong>
          </div>
          <div className="btc-operator-locks">
            <span className="btc-lock-pill good">paper queue false</span>
            <span className="btc-lock-pill good">paper false</span>
            <span className="btc-lock-pill good">live false</span>
            <span className="btc-lock-pill good">broker/order false</span>
          </div>
          <div className="btc-operator-list">
            {forbiddenReasons.slice(0, 6).map((reason, index) => (
              <div key={`${reason}-${index}`} className="btc-operator-row">
                <span>{index + 1}</span>
                <strong>{operatorReason(reason)}</strong>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function StrategyLedgerSection({report}: {report: BtcStrategyLedgerReport | undefined}) {
  const lines = report?.strategy_lines ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="BTC 策略台账" status={report?.status} generatedAt={report?.generated_at_utc}>
        把稳健线、高收益线、attack sleeve、早期 raw trend 和 TimesFM 辅助模型放在同一张只读表里。
      </ReportHeader>
      <div className="btc-ledger-table">
        <div className="btc-ledger-row btc-ledger-head">
          <span>策略线</span>
          <span>状态</span>
          <span>最新信号/暴露</span>
          <span>下一步</span>
        </div>
        {lines.map((line) => (
          <div key={line.strategy_id} className="btc-ledger-row">
            <div>
              <strong>{line.display_name_cn ?? line.strategy_id}</strong>
              <p>{line.bucket ?? '-'} · {line.is_auxiliary_model ? '辅助模型' : '交易策略研究'}</p>
              <small>{line.latest_report_path ?? 'missing report'}</small>
            </div>
            <div>
              <span className={`status-tag ${statusTone(line.status)}`}>{statusText(line.status)}</span>
              <p>观察 {text(line.observation_days)} 天 / {text(line.observation_count)} 次</p>
              <p>paper {line.paper_allowed ? '异常开放' : '关闭'} · live {line.live_unlock_allowed ? '异常开放' : '冻结'}</p>
            </div>
            <div>
              <p>{signalSummary(line)}</p>
              <small>{compact(line.parameter_summary, 140)}</small>
            </div>
            <div>
              <p>{line.next_action ?? '-'}</p>
              {(line.blockers ?? []).slice(0, 2).map((blocker) => <small key={blocker}>阻塞：{blocker}</small>)}
              <small>建议：{line.keep_or_retire_recommendation ?? '-'}</small>
            </div>
          </div>
        ))}
      </div>
      {!lines.length ? <p className="data-message">策略台账 artifact 缺失或为空。</p> : null}
    </section>
  );
}

function PromotionGateSection({report}: {report: BtcPromotionGateControlReport | undefined}) {
  const rows = report?.gate_matrix ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="BTC Promotion Gate 总控" status={report?.status} generatedAt={report?.generated_at_utc}>
        进入 paper 前必须通过报告当前列出的 {text(report?.gate_count ?? report?.gate_matrix?.length)} 个 gate；任何旧 approval 与当前阻塞冲突时都按 fail-closed。
      </ReportHeader>
      <div className="btc-gate-grid">
        {rows.map((row) => (
          <article key={row.gate_id} className={`btc-gate-card btc-gate-${statusTone(row.status)}`}>
            <div className="btc-gate-card-head">
              <strong>{gateLabel(row.gate_id, row.gate_name_cn)}</strong>
              <span className={`status-tag ${statusTone(row.status)}`}>{statusText(row.status)}</span>
            </div>
            <div className="btc-gate-checks">
              {keyChecks(row.checks).map(([key, value]) => (
                <div key={key}><span>{key}</span><strong>{text(value)}</strong></div>
              ))}
            </div>
            <p>{row.next_action_cn ?? '-'}</p>
            {(row.blockers ?? []).slice(0, 3).map((blocker) => <small key={blocker}>阻塞：{blocker}</small>)}
          </article>
        ))}
      </div>
      {report?.key_blockers_cn?.length ? (
        <div className="btc-warning-list">
          {report.key_blockers_cn.map((item) => <p key={item}>{item}</p>)}
        </div>
      ) : null}
    </section>
  );
}

function LeakageAuditSection({report}: {report: BtcLeakageOverfitAuditReport | undefined}) {
  const summary = report?.summary ?? {};
  const longShort = report?.long_short_top5_audit ?? {};
  const highOctane = report?.high_octane_v2_audit ?? {};
  const checks = report?.leakage_checks ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="未来函数 / 过拟合审计" status={report?.status} generatedAt={report?.generated_at_utc}>
        重点看 Long/Short Donchian Top5 和 High-Octane v2 是否只用已完成 K 线、是否未来 sentiment 可见、是否参数压线。
      </ReportHeader>
      <div className="btc-audit-grid">
        <article className="btc-audit-card">
          <span>Long/Short Donchian Top5</span>
          <strong>{text(summary.long_short_overfit_verdict)}</strong>
          <p>未来 sentiment 违规 {text(summary.long_short_future_sentiment_violation_count)} · K线违规 {text(summary.long_short_completed_bar_violation_count)}</p>
          <p>参数审计：{text(summary.long_short_parameter_mining_verdict)}</p>
          <p>收益集中：{text(summary.long_short_return_concentration_verdict)}</p>
          <small>Top 候选：{text(longShort.best_candidate_id)}</small>
        </article>
        <article className="btc-audit-card btc-audit-hot">
          <span>High-Octane / Attack Sleeve</span>
          <strong>{text(summary.high_octane_overfit_verdict)}</strong>
          <p>40% 生存阈值余量 {pct(summary.high_octane_best_margin_over_40pct_threshold, 4)}</p>
          <p>same-bar 边界：{text(summary.high_octane_capital_overlay_execution_boundary_verdict)}</p>
          <p>参数审计：{text(summary.high_octane_parameter_mining_verdict)}</p>
          <small>最佳场景：{text(highOctane.best_scenario_id)}</small>
        </article>
        <article className="btc-audit-card">
          <span>审计检查</span>
          <strong>{text(summary.check_warn_count)} 警告 / {text(summary.check_fail_count)} 失败</strong>
          <p>forward 确认：{text(summary.forward_observe_clean_confirmation_ready)}</p>
          <p>选择锁：{text(summary.forward_observe_selection_use_blocked_by_lock)}</p>
          <small>检查项 {checks.length} 个</small>
        </article>
      </div>
      <div className="btc-check-list">
        {checks.slice(0, 8).map((check, index) => (
          <div key={`${text(check.check_id)}-${index}`} className={`btc-check-row btc-check-${statusTone(check.status)}`}>
            <span>{text(check.status)}</span>
            <strong>{text(check.check_id)}</strong>
            <p>{text(check.evidence)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function AttackStressSection({report}: {report: BtcAttackSleeveRiskStressReport | undefined}) {
  const summary = report?.summary ?? {};
  const rows = report?.top_risk_rows ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="Attack Sleeve 风控压力" status={report?.status} generatedAt={report?.generated_at_utc}>
        展示严格下一根 bar 执行、isolated sleeve 强平、funding/slippage 压力和插针剩余本金。
      </ReportHeader>
      <div className="btc-risk-summary">
        <div><span>-10% 插针最低剩余本金</span><strong>{pct(summary.min_remaining_after_10pct_spike_min)}</strong><p>中位数 {pct(summary.min_remaining_after_10pct_spike_median)}</p></div>
        <div><span>严格执行</span><strong>{text(summary.strict_next_bar_execution)}</strong><p>same-bar 盈利允许：{text(summary.same_bar_profit_allowed)}</p></div>
        <div><span>强平/全灭</span><strong>{text(summary.normal_liquidation_row_count)} / {text(summary.full_wipeout_row_count)}</strong><p>hard wipeout {text(summary.hard_wipeout_row_count)}</p></div>
        <div><span>结论</span><strong>{text(report?.decision)}</strong><p>funding 近似：{text(summary.funding_approximation)}</p></div>
      </div>
      <div className="btc-risk-table">
        <div className="btc-risk-row btc-risk-head">
          <span>场景</span><span>策略</span><span>年化</span><span>回撤</span><span>-10% 剩余</span><span>最大暴露</span>
        </div>
        {rows.slice(0, 8).map((row, index) => (
          <div key={`${text(row.scenario_id)}-${text(row.policy_id)}-${index}`} className="btc-risk-row">
            <span>{text(row.policy_id)}</span>
            <span>{text(row.scenario_id)}</span>
            <span>{pct(row.annual_return_pct)}</span>
            <span>{pct(row.max_drawdown_abs_pct)}</span>
            <span>{pct(row.min_remaining_capital_pct_after_10pct_spike)}</span>
            <span>{text(row.max_concurrent_exposed_sleeves_observed)} sleeve</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function AttackContinuationSection({report}: {report: BtcAttackStrategyContinuationShortlistReport | undefined}) {
  const rows = report?.strategy_lines ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="激进/分仓滚仓继续研究短名单" status={report?.status} generatedAt={report?.generated_at_utc}>
        固化当前 4 条重点方向：原始 10x 只当危险收益天花板，High-Octane、5x 防插针和限暴露 attack 继续研究。
      </ReportHeader>
      <div className="btc-risk-summary">
        <div><span>短名单</span><strong>{text(report?.line_count)} 条</strong><p>继续研究 {text(report?.continued_research_strategy_count)} 条</p></div>
        <div><span>危险参照</span><strong>{text(report?.danger_reference_count)} 条</strong><p>不进入 observe/paper</p></div>
        <div><span>交易边界</span><strong>research-only</strong><p>paper/live/broker 全关闭</p></div>
      </div>
      <div className="btc-ledger-table">
        <div className="btc-ledger-row btc-ledger-head">
          <span>策略</span>
          <span>核心指标</span>
          <span>研究结论</span>
          <span>下一步</span>
        </div>
        {rows.slice(0, 4).map((row) => (
          <div key={text(row.strategy_id)} className="btc-ledger-row">
            <div>
              <strong>{text(row.display_name_cn)}</strong>
              <p>{text(row.research_role)} · {text(row.source_scenario_id)}</p>
            </div>
            <div>
              <p>年化 {pct(row.annual_return_pct)} / 总收益 {pct(row.total_return_pct)}</p>
              <p>回撤 {pct(row.max_drawdown_abs_pct)} · -10%后剩 {pct(row.min_remaining_after_10pct_spike_pct)}</p>
            </div>
            <div>
              <span className={`status-tag ${row.continue_research ? 'neutral' : 'bad'}`}>{row.continue_research ? '继续研究' : '危险参照'}</span>
              <p>{text(row.retention_decision)}</p>
            </div>
            <div>
              <p>{text(row.next_action)}</p>
              <small>{compact(row.primary_risk, 150)}</small>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function AttackFollowupSection({report}: {report: BtcAttackFollowupReviewReport | undefined}) {
  const summary = report?.summary ?? {};
  const rows = report?.same_window_comparison_rows ?? [];
  return (
    <section className="btc-control-section">
      <ReportHeader title="进攻线严格复核 / 5x vs 10x" status={report?.status} generatedAt={report?.generated_at_utc}>
        High-Octane 使用严格下一根 bar 压力复核；5x 防插针与实际 10x 限暴露用同窗口和 rolling-start 对比。
      </ReportHeader>
      <div className="btc-risk-summary">
        <div><span>High-Octane 原始年化</span><strong>{pct(summary.high_octane_source_annual_return_pct)}</strong><p>严格 base 后 {pct(summary.high_octane_strict_base_annual_return_pct)}</p></div>
        <div><span>High-Octane rolling</span><strong>{pct(summary.high_octane_rolling_median_total_return_pct)}</strong><p>最差 {pct(summary.high_octane_rolling_min_total_return_pct)}</p></div>
        <div><span>5x rolling 中位</span><strong>{pct(summary.defensive_5x_rolling_median_total_return_pct)}</strong><p>-10%后剩 {pct(summary.defensive_5x_min_remaining_after_10pct_spike)}</p></div>
        <div><span>10x 限暴露 rolling 中位</span><strong>{pct(summary.actual_10x_limited_rolling_median_total_return_pct)}</strong><p>-10%后剩 {pct(summary.actual_10x_limited_min_remaining_after_10pct_spike)}</p></div>
      </div>
      <div className="btc-risk-table">
        <div className="btc-risk-row btc-risk-head">
          <span>策略</span><span>场景</span><span>年化</span><span>总收益</span><span>回撤</span><span>-10%剩余</span>
        </div>
        {rows.map((row) => (
          <div key={text(row.line_id)} className="btc-risk-row">
            <span>{text(row.display_name_cn)}</span>
            <span>{text(row.scenario_id)}</span>
            <span>{pct(row.annual_return_pct)}</span>
            <span>{pct(row.total_return_pct)}</span>
            <span>{pct(row.max_drawdown_abs_pct)}</span>
            <span>{pct(row.min_remaining_capital_pct_after_10pct_spike)}</span>
          </div>
        ))}
      </div>
      <p className="data-message">{text(summary.comparison_verdict)}；{text(summary.rolling_comparison_verdict)}</p>
    </section>
  );
}

function MicroLiveExperimentSection({report}: {report: BtcMicroLiveExperimentPacketReport | undefined}) {
  const rules = report?.experiment_rules ?? {};
  const recorder = report?.observe_only_recorder ?? {};
  const signalRecords = recorder.records ?? [];
  const latest = signalRecords.length ? signalRecords[signalRecords.length - 1] : {};
  const alertOnly = report?.alert_only ?? {};
  const alerts = alertOnly.alerts ?? [];
  const rehearsal = report?.no_trade_execution_rehearsal ?? {};
  const rehearsalRows = rehearsal.rows ?? [];
  const checklist = report?.pre_live_checklist ?? {};
  const summary = report?.summary ?? {};
  return (
    <section className="btc-control-section">
      <ReportHeader title="1000 RMB 实验检查单" status={report?.status} generatedAt={report?.generated_at_utc}>
        只记录信号、只提醒、只做 no-trade 演练；不写 paper 队列，不解锁 live，不调用 broker/order。
      </ReportHeader>
      <div className="btc-risk-summary">
        <div><span>总预算 / sleeve</span><strong>{text(rules.total_budget_rmb)} RMB</strong><p>{text(rules.sleeve_count)} 个 sleeve，每个 {text(rules.sleeve_rmb)} RMB</p></div>
        <div><span>当前方向</span><strong>{text(summary.latest_direction ?? recorder.latest_direction)}</strong><p>{shortDate(summary.latest_decision_time ?? recorder.latest_decision_time)}</p></div>
        <div><span>当前风险</span><strong>{text(checklist.current_risk_level ?? summary.current_risk_level)}</strong><p>策略允许 {text(checklist.strategy_allowed_now)} / 违规 {text(checklist.rule_violation_count)} / 提醒 {text(alertOnly.alert_count)}</p></div>
        <div><span>本次最多投入</span><strong>{text(checklist.max_principal_this_signal_rmb)} RMB</strong><p>杠杆上限 {text(checklist.leverage_cap)}x</p></div>
        <div><span>-10% 插针后剩余</span><strong>{pct(summary.latest_remaining_after_10pct_spike ?? latest.remaining_principal_pct_after_10pct_spike)}</strong><p>-5% {pct(latest.remaining_principal_pct_after_5pct_spike)} / -8% {pct(latest.remaining_principal_pct_after_8pct_spike)}</p></div>
        <div><span>交易边界</span><strong>order false</strong><p>paper {text(checklist.paper_allowed)} / live {text(checklist.live_allowed)}</p></div>
      </div>
      <div className="btc-risk-table">
        <div className="btc-risk-row btc-risk-head">
          <span>记录时间</span><span>方向/触发</span><span>暴露</span><span>强平价</span><span>funding</span><span>动作</span>
        </div>
        {signalRecords.slice(-5).map((row, index) => (
          <div key={`${text(row.decision_time)}-${index}`} className="btc-risk-row">
            <span>{shortDate(row.decision_time)}</span>
            <span>{text(row.direction)} / {compact(row.strategy_triggered, 42)}</span>
            <span>{text(row.total_exposed_sleeves)} sleeve / {text(row.principal_exposed_rmb)} RMB</span>
            <span>5x {text(row.defensive_5x_liquidation_price)} / 10x {text(row.attack_10x_liquidation_price)}</span>
            <span>{text(row.funding_pressure)} / {text(row.base_cost_bps)}bps</span>
            <span>record only</span>
          </div>
        ))}
      </div>
      <div className="btc-audit-grid">
        <article className="btc-audit-card">
          <span>alert-only</span>
          <strong>{text(alertOnly.alert_count)} 条 / block {text(alertOnly.block_alert_count)}</strong>
          {alerts.slice(0, 4).map((alert) => <p key={text(alert.alert_id)}>{text(alert.severity)}：{text(alert.message_cn)}</p>)}
        </article>
        <article className="btc-audit-card">
          <span>no-trade 执行演练</span>
          <strong>{text(rehearsal.real_order_submitted)} real order</strong>
          {rehearsalRows.map((row) => (
            <p key={text(row.line_id)}>{text(row.line_id)}：盘口代理成交 {text(row.snapshot_proxy_fill_complete)}，滑点 {text(row.snapshot_proxy_slippage_bps)} bps，规则 {text(row.conforms_to_1000_rmb_rules)}</p>
          ))}
        </article>
        <article className="btc-audit-card">
          <span>暂停/冷却</span>
          <strong>{text(checklist.cooldown_or_pause_state)}</strong>
          <p>{text(checklist.operator_message_cn)}</p>
          <small>当前页面仍是 observe-only，不代表可以实盘。</small>
        </article>
      </div>
    </section>
  );
}

function DataCoverageSection({
  control,
  leakage,
  dataStatus,
}: {
  control: BtcResearchControlCenterResponse | null;
  leakage: BtcLeakageOverfitAuditReport | undefined;
  dataStatus: Record<string, unknown> | undefined;
}) {
  const coverage = asRecord(dataStatus?.coverage);
  const sqliteCoverage = asRecord(dataStatus?.current_sqlite_coverage);
  const dataCoverageAudit = leakage?.data_coverage_audit ?? {};
  const sources = control?.source_paths ?? {};
  return (
    <section className="btc-control-section">
      <ReportHeader title="BTC 数据覆盖 / 自动任务状态" status={text(dataStatus?.status, control?.status)} generatedAt={text(dataStatus?.generated_at, control?.generated_at_utc)}>
        这里展示 derivatives、depth、mark/index、liquidation 等 gate 相关数据状态；左侧 DataManager 继续只管理 K 线。
      </ReportHeader>
      <div className="btc-risk-summary">
        <div><span>市场 K 线</span><strong>{text(sqliteCoverage.row_count ?? coverage.row_count ?? dataCoverageAudit.market_1h_row_count)}</strong><p>{shortDate(sqliteCoverage.start ?? coverage.start ?? dataCoverageAudit.market_start)} - {shortDate(sqliteCoverage.end ?? coverage.end ?? dataCoverageAudit.market_end)}</p></div>
        <div><span>衍生品 sentiment</span><strong>{text(dataCoverageAudit.derivatives_row_count)}</strong><p>future sentiment 违规 {text(dataCoverageAudit.bar_replay_derivatives_available_time_violation_count)}</p></div>
        <div><span>Funding / OI</span><strong>{text(dataCoverageAudit.coverage_verdict)}</strong><p>funding 缺口 {text(dataCoverageAudit.funding_missing_count)}</p></div>
        <div><span>Liquidation</span><strong>{text(dataCoverageAudit.liquidation_source)}</strong><p>完整 1H 历史：{text(dataCoverageAudit.liquidation_one_hour_history_complete)}</p></div>
      </div>
      <div className="btc-source-grid">
        {Object.entries(sources).map(([key, value]) => (
          <div key={key}><span>{key}</span><strong>{value}</strong></div>
        ))}
      </div>
      {control?.missing_sources?.length ? <p className="data-message">缺失来源：{control.missing_sources.join(', ')}</p> : null}
    </section>
  );
}

function OperatorSummarySection({summary}: {summary: BtcOperatorSummaryResponse | null}) {
  if (!summary) {
    return (
      <section className="btc-control-section">
        <p className="data-message">等待轻量 operator summary；完整 artifact 尚未加载。</p>
        <div className="btc-risk-summary">
          <div><span>安全边界</span><strong>paper/live 全关闭</strong><p>broker/order/OMS/private 全 false</p></div>
        </div>
      </section>
    );
  }
  const taskRows = Object.entries(summary.tasks).flatMap(([category, rows]) => rows.map((row) => ({...row, category})));
  const provenanceStale = summary.snapshot.current_head_match !== true;
  return (
    <section className="btc-control-section" data-testid="btc-operator-summary">
      <ReportHeader title="Operator Summary" status={summary.status} generatedAt={summary.generated_at_utc}>
        轻量首屏只展示根因、责任人、下一动作、freshness 与证据链接；完整矩阵按需加载。
      </ReportHeader>
      {provenanceStale ? (
        <div className="btc-warning-list btc-safety-warning" data-testid="btc-stale-snapshot-banner">
          <p>证据过期 / fail-closed：snapshot commit {summary.snapshot.snapshot_commit.slice(0, 12) || '-'} 与 current HEAD {summary.snapshot.current_head.slice(0, 12) || 'unavailable'} 不匹配。</p>
        </div>
      ) : null}
      <div className="hero-status">
        {summary.state_kinds.map((state) => <span key={state} className={`status-chip ${statusTone(state) === 'bad' ? 'bad' : 'muted'}`}>{state}</span>)}
        <span className="status-chip muted">batch {summary.snapshot.aggregation_batch_id || '-'}</span>
        <span className="status-chip muted">commit {summary.snapshot.code_commit.slice(0, 10) || '-'}</span>
        <span className={`status-chip ${provenanceStale ? 'bad' : 'muted'}`}>current HEAD {summary.snapshot.current_head.slice(0, 10) || '-'}</span>
      </div>
      <div className="btc-risk-summary">
        {summary.root_causes.map((root) => (
          <div key={root.root_cause_id}>
            <span>{root.category}</span>
            <strong>{root.label}</strong>
            <p>{root.owner} · {root.next_action} · raw {root.raw_blocker_count}</p>
          </div>
        ))}
      </div>
      <div className="btc-source-grid">
        {taskRows.map((task) => (
          <div key={`${task.category}:${task.root_cause_id}`}>
            <span>{task.category}</span>
            <strong>{task.label}</strong>
            <p>{task.owner} · {task.next_action}</p>
          </div>
        ))}
      </div>
      <div className="btc-risk-summary">
        <div><span>Freshness</span><strong>{summary.freshness.status}</strong><p>stale {summary.freshness.stale_source_count} / missing {summary.freshness.missing_source_count} / mismatch {summary.freshness.mismatch_count}</p></div>
        <div><span>安全边界</span><strong>paper/live 全关闭</strong><p>broker/order/OMS/private 全 false</p></div>
        <div><span>证据链接</span><strong>{summary.evidence_links.length}</strong><p>前三根因不携带完整 blocker 矩阵</p></div>
      </div>
      <div className="btc-source-grid">
        {summary.evidence_links.map((link) => (
          <div key={link.artifact_id}><span>{link.artifact_id}</span><strong>{link.status}</strong><p>{link.logical_path}</p></div>
        ))}
      </div>
      {summary.missing_sources.length ? <p className="data-message">source missing：{summary.missing_sources.map((row) => row.artifact_id).join(', ')}</p> : null}
      {summary.safety.violations.length ? <p className="data-message">安全冲突：{summary.safety.violations.join(', ')}</p> : null}
    </section>
  );
}

export default function BtcControlCenter({
  control,
  summary: operatorSummary,
  summaryLoading,
  summaryMessage,
  detailsLoading,
  detailsMessage,
  onRefreshSummary,
  onLoadDetails,
}: Props) {
  const reports = control?.reports ?? {};
  const ledger = reports.strategy_ledger;
  const promotionGate = reports.promotion_gate_control;
  const leakage = reports.leakage_overfit_audit;
  const attackStress = reports.attack_sleeve_risk_stress;
  const attackShortlist = reports.attack_strategy_continuation_shortlist;
  const attackFollowup = reports.attack_followup_review;
  const microLive = reports.micro_live_experiment_packet;
  const dataStatus = reports.data_status as Record<string, unknown> | undefined;
  const summary = control?.summary ?? {};
  const safetyViolations = control?.safety_violations ?? [];
  return (
    <section className="btc-control-center" data-testid="btc-control-center">
      <div className="panel btc-control-hero">
        <div>
          <p className="eyebrow">BTC CONTROL CENTER</p>
          <h2>BTC 研究总控</h2>
          <p>只读汇总最新 artifact：策略台账、paper promotion gate、未来函数/过拟合审计、attack sleeve 风控压力和数据覆盖。这里不写 paper 队列，不解锁 live。</p>
        </div>
        <div className="btc-control-hero-status">
          <span className={`status-tag ${statusTone(operatorSummary?.status ?? control?.status)}`}>{statusText(operatorSummary?.status ?? control?.status ?? (summaryLoading ? 'loading' : 'missing'))}</span>
          <button type="button" className="secondary-button" disabled={summaryLoading} onClick={onRefreshSummary}>
            {summaryLoading ? '刷新中...' : '刷新摘要'}
          </button>
          <button type="button" className="secondary-button" disabled={detailsLoading} onClick={onLoadDetails}>
            {detailsLoading ? '加载中...' : control ? '刷新完整证据' : '加载完整证据'}
          </button>
        </div>
      </div>

      <OperatorSummarySection summary={operatorSummary} />

      {control ? <div className="btc-control-summary-grid">
        <div><span>策略线</span><strong>{text(summary.strategy_line_count ?? ledger?.line_count)}</strong><p>固定台账 {text(summary.fixed_strategy_line_count ?? ledger?.fixed_strategy_line_count)}</p></div>
        <div><span>Promotion Gate</span><strong>{text(summary.blocked_gate_count ?? promotionGate?.blocked_gate_count)} / {text(summary.gate_count ?? promotionGate?.gate_count)} 阻塞</strong><p>{text(promotionGate?.decision)}</p></div>
        <div><span>审计</span><strong>{text(summary.leakage_check_warn_count)} 警告 / {text(summary.leakage_check_fail_count)} 失败</strong><p>{text(leakage?.decision)}</p></div>
        <div><span>-10%压力后本金剩余</span><strong>{pct(summary.attack_min_remaining_after_10pct_spike)}</strong><p>不是 40% 价格插针 · not ready：{text(summary.attack_not_forward_observation_ready)}</p></div>
        <div><span>激进短名单</span><strong>{text(summary.attack_shortlist_continue_count)} / {text(summary.attack_shortlist_line_count)} 继续</strong><p>危险参照 {text(summary.attack_shortlist_danger_reference_count)}</p></div>
        <div><span>进攻线复核</span><strong>{pct(summary.attack_followup_strict_base_annual_return_pct)}</strong><p>5x/10x rolling {pct(summary.attack_followup_5x_rolling_median_total_return_pct)} / {pct(summary.attack_followup_10x_rolling_median_total_return_pct)}</p></div>
        <div><span>1000 RMB 检查单</span><strong>{text(summary.micro_live_current_risk_level)}</strong><p>{text(summary.micro_live_latest_direction)} / 暴露 {text(summary.micro_live_latest_principal_exposed_rmb)} RMB / alert {text(summary.micro_live_alert_count)}</p></div>
        <div><span>数据覆盖</span><strong>{text(dataStatus?.status ?? 'latest artifact')}</strong><p>缺失来源 {control?.missing_sources.length ?? 0}</p></div>
        <div><span>交易边界</span><strong>paper/live 全关闭</strong><p>broker/order/OMS 全 false</p></div>
      </div> : null}

      {summaryMessage ? <p className="data-message">{summaryMessage}</p> : null}
      {detailsMessage ? <p className="data-message">{detailsMessage}</p> : null}
      {safetyViolations.length ? (
        <div className="btc-warning-list btc-safety-warning">
          {safetyViolations.map((item) => <p key={item}>安全冲突：{item}</p>)}
        </div>
      ) : null}

      {control ? (
        <>
          <OperatorControlCenterSection control={control} />
          <StrategyLedgerSection report={ledger} />
          <AttackContinuationSection report={attackShortlist} />
          <AttackFollowupSection report={attackFollowup} />
          <MicroLiveExperimentSection report={microLive} />
          <PromotionGateSection report={promotionGate} />
          <LeakageAuditSection report={leakage} />
          <AttackStressSection report={attackStress} />
          <DataCoverageSection control={control} leakage={leakage} dataStatus={dataStatus} />
        </>
      ) : <p className="data-message">详细 artifact 尚未加载；首屏状态来自 immutable summary。</p>}
    </section>
  );
}
