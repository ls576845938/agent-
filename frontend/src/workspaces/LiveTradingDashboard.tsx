import {useEffect, useState} from 'react';
import {
  formatFreshness,
  formatRuntimeBoolean,
  formatRuntimeLabel,
  formatRuntimeBlocker,
  IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS,
  createUnavailableIbkrRuntimeStatus,
  isIbkrRuntimeBlocked,
  isReconciliationPass,
  loadIbkrRuntimeStatus,
  type IbkrRuntimeStatus,
  type IbkrRuntimeStatusResult,
  type RuntimeBool,
} from '../lib/ibkr-runtime-api';
import {RuntimeBanner} from '../components/ibkr-runtime/RuntimeBanner';
import {RuntimeStatusSection, type RuntimeFieldTone, type RuntimeStatusField} from '../components/ibkr-runtime/RuntimeStatusSection';
import {
  WorkbenchFlow,
  WorkbenchFrame,
  WorkbenchHeader,
} from '../components/workbench/Workbench';

function countLabel(value: number | null): string {
  return value === null ? '未知' : String(value);
}

function moneyLabel(value: number | null): string {
  return value === null ? '未知' : `$${value.toFixed(2)}`;
}

function numberLabel(value: number | null): string {
  return value === null ? '未知' : String(value);
}

function ageLabel(value: number | null, staleAfterSeconds: number): string {
  if (value === null) return '未知';
  if (value > staleAfterSeconds) return `已过期 · ${Math.floor(value)} 秒`;
  return `${Math.floor(value)} 秒`;
}

function freshnessField(
  timestamp: string | null,
  staleAfterSeconds: number,
  now: number,
): {value: string; detail: string; tone: RuntimeFieldTone} {
  const freshness = formatFreshness(timestamp, staleAfterSeconds, now);
  return {
    value: freshness.label,
    detail: freshness.absolute,
    tone: freshness.known && !freshness.stale ? 'good' : freshness.known ? 'bad' : 'neutral',
  };
}

function boolField(
  value: RuntimeBool,
  trueLabel: string,
  falseLabel: string,
  trueTone: RuntimeFieldTone,
  falseTone: RuntimeFieldTone,
): {value: string; tone: RuntimeFieldTone} {
  return {
    value: formatRuntimeBoolean(value, trueLabel, falseLabel),
    tone: value === true ? trueTone : value === false ? falseTone : 'neutral',
  };
}

function paperPortLabel(port: number | null): {value: string; tone: RuntimeFieldTone; detail?: string} {
  if (port === null) return {value: '未知', tone: 'neutral'};
  if (port === 4001 || port === 7496) {
    return {value: '实盘端口已拒绝', tone: 'bad', detail: `收到端口 ${port}；实盘端点保持关闭`};
  }
  if (port === 4002 || port === 7497) return {value: `${port} · Paper`, tone: 'good'};
  return {value: String(port), tone: 'neutral', detail: '端口不在批准的 Paper 集合中'};
}

function snapshotForResult(result: IbkrRuntimeStatusResult): IbkrRuntimeStatus {
  return result.kind === 'available' ? result.snapshot : createUnavailableIbkrRuntimeStatus(result.message);
}

function statusTone(status: string, goodValues: string[] = ['pass', 'passed', 'ready', 'connected', 'subscribed']): RuntimeFieldTone {
  const normalized = status.toLowerCase();
  if (goodValues.includes(normalized)) return 'good';
  if (['fail', 'failed', 'stale', 'disconnected', 'blocked', 'unknown', 'halted'].includes(normalized)) return 'bad';
  return 'neutral';
}

export default function LiveTradingDashboard() {
  const [runtime, setRuntime] = useState<IbkrRuntimeStatusResult>(() => ({
    kind: 'unavailable',
    message: '正在读取 IBKR 运行时状态',
    fetched_at: new Date().toISOString(),
  }));
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const refresh = async () => {
    setRefreshing(true);
    const result = await loadIbkrRuntimeStatus();
    setRuntime(result);
    setLastRefresh(new Date().toISOString());
    setRefreshing(false);
  };

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => {
      void refresh();
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  const snapshot = snapshotForResult(runtime);
  const blocked = runtime.kind === 'unavailable' || isIbkrRuntimeBlocked(snapshot);
  const bannerTitle = runtime.kind === 'unavailable' ? '状态不可用' : blocked ? '新订单已阻断' : '运行时就绪';
  const now = Date.now();
  const heartbeat = freshnessField(
    snapshot.gateway.last_heartbeat_at,
    IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.heartbeat,
    now,
  );
  const marketTick = freshnessField(
    snapshot.market_data.last_tick_at,
    IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.marketData,
    now,
  );
  const brokerSnapshot = freshnessField(
    snapshot.broker_truth.snapshot_at,
    IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.brokerTruth,
    now,
  );
  const reconciliationRun = freshnessField(
    snapshot.reconciliation.last_run_at,
    IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.reconciliation,
    now,
  );
  const connection = boolField(snapshot.gateway.connected, '已连接', '已断开', 'good', 'bad');
  const blockNewOrders = boolField(snapshot.block_new_orders, '已阻断', '未阻断', 'bad', 'good');
  const accountVerified = boolField(snapshot.account.verified, '已验证', '未验证', 'good', 'bad');
  const killSwitch = boolField(snapshot.kill_switch.tripped, '已触发', '正常', 'bad', 'good');
  const marketHealthy = boolField(snapshot.market_data.healthy, '健康', '不健康', 'good', 'bad');
  const sequenceGap = boolField(snapshot.market_data.sequence_gap, '发现缺口', '无缺口', 'bad', 'good');
  const brokerFresh = boolField(snapshot.broker_truth.fresh, '新鲜', '已过期', 'good', 'bad');
  const cashMismatch = boolField(snapshot.reconciliation.cash_mismatch, '不一致', '一致', 'bad', 'good');
  const recoveryAck = boolField(snapshot.recovery.requires_operator_ack, '需要确认', '无需确认', 'bad', 'good');
  const ackStatus = boolField(snapshot.recovery.operator_acknowledged, '已确认', '未确认', 'good', 'bad');
  const port = paperPortLabel(snapshot.gateway.paper_port);

  const systemFields: RuntimeStatusField[] = [
    {label: '运行时状态', value: formatRuntimeLabel(snapshot.runtime_state), tone: statusTone(snapshot.runtime_state), testId: 'runtime-state'},
    {label: '交易模式', value: formatRuntimeLabel(snapshot.trading_mode), tone: snapshot.trading_mode === 'normal' ? 'good' : 'bad', testId: 'trading-mode'},
    {label: '新订单权限', value: blockNewOrders.value, tone: blockNewOrders.tone, detail: '未知或不可用时始终保持阻断', testId: 'block-new-orders'},
    {label: '熔断开关', value: killSwitch.value, tone: killSwitch.tone, detail: snapshot.kill_switch.reason ?? '未提供原因', testId: 'kill-switch'},
    {label: '账户', value: accountVerified.value, tone: accountVerified.tone, detail: '不显示原始账户号码', testId: 'account'},
  ];

  const gatewayFields: RuntimeStatusField[] = [
    {label: '连接状态', value: connection.value, tone: connection.tone, testId: 'gateway-connected'},
    {label: '最近心跳', value: heartbeat.value, tone: heartbeat.tone, detail: heartbeat.detail, testId: 'gateway-heartbeat'},
    {label: '心跳年龄', value: ageLabel(snapshot.gateway.heartbeat_age_seconds, IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.heartbeat), tone: snapshot.gateway.heartbeat_age_seconds === null ? 'neutral' : snapshot.gateway.heartbeat_age_seconds > IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.heartbeat ? 'bad' : 'good', testId: 'gateway-heartbeat-age'},
    {label: '客户端 ID', value: snapshot.gateway.client_id === null ? '未知' : String(snapshot.gateway.client_id), tone: snapshot.gateway.client_id === null ? 'neutral' : 'good', testId: 'gateway-client-id'},
    {label: 'Paper 端口', value: port.value, tone: port.tone, detail: port.detail, testId: 'gateway-paper-port'},
    {label: '连接纪元', value: numberLabel(snapshot.gateway.connection_epoch), tone: snapshot.gateway.connection_epoch === null ? 'neutral' : 'good', testId: 'gateway-epoch'},
    {label: '重连次数', value: numberLabel(snapshot.gateway.reconnect_attempts), tone: snapshot.gateway.reconnect_attempts === null ? 'neutral' : snapshot.gateway.reconnect_attempts > 0 ? 'bad' : 'good', testId: 'gateway-reconnect-attempts'},
    {label: '最近错误', value: snapshot.gateway.last_error ? '有错误' : '无错误', tone: snapshot.gateway.last_error ? 'bad' : 'good', detail: snapshot.gateway.last_error ?? '未提供错误', testId: 'gateway-last-error'},
  ];

  const marketFields: RuntimeStatusField[] = [
    {label: '订阅状态', value: formatRuntimeLabel(snapshot.market_data.subscription_status), tone: marketHealthy.tone, detail: marketHealthy.value, testId: 'market-subscription'},
    {label: '订阅纪元', value: numberLabel(snapshot.market_data.subscription_epoch), tone: snapshot.market_data.subscription_epoch === null ? 'neutral' : 'good', testId: 'market-epoch'},
    {label: '最近行情', value: marketTick.value, tone: marketTick.tone, detail: marketTick.detail, testId: 'market-last-tick'},
    {label: '行情年龄', value: ageLabel(snapshot.market_data.last_tick_age_seconds, IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.marketData), tone: snapshot.market_data.last_tick_age_seconds === null ? 'neutral' : snapshot.market_data.last_tick_age_seconds > IBKR_RUNTIME_STALE_THRESHOLDS_SECONDS.marketData ? 'bad' : 'good', testId: 'market-last-tick-age'},
    {label: '序列缺口', value: sequenceGap.value, tone: sequenceGap.tone, testId: 'market-sequence-gap'},
  ];

  const brokerTruthFields: RuntimeStatusField[] = [
    {label: '未结订单', value: countLabel(snapshot.broker_truth.open_orders_count), tone: snapshot.broker_truth.open_orders_count === null ? 'neutral' : 'good', testId: 'broker-open-orders'},
    {label: '成交数', value: countLabel(snapshot.broker_truth.executions_count), tone: snapshot.broker_truth.executions_count === null ? 'neutral' : 'good', testId: 'broker-executions'},
    {label: '持仓数', value: countLabel(snapshot.broker_truth.positions_count), tone: snapshot.broker_truth.positions_count === null ? 'neutral' : 'good', testId: 'broker-positions'},
    {label: '现金快照', value: moneyLabel(snapshot.broker_truth.cash), tone: snapshot.broker_truth.cash === null ? 'neutral' : 'good', detail: '来自 Broker 事实；不暴露账户号码', testId: 'broker-cash'},
    {label: '快照年龄', value: brokerSnapshot.value, tone: brokerSnapshot.tone, detail: brokerSnapshot.detail, testId: 'broker-snapshot-age'},
    {label: '新鲜度', value: brokerFresh.value, tone: brokerFresh.tone, testId: 'broker-freshness'},
  ];

  const reconciliationFields: RuntimeStatusField[] = [
    {label: '状态', value: formatRuntimeLabel(snapshot.reconciliation.status), tone: statusTone(snapshot.reconciliation.status), testId: 'reconciliation-status'},
    {label: '未知订单', value: countLabel(snapshot.reconciliation.unknown_orders), tone: snapshot.reconciliation.unknown_orders === 0 ? 'good' : snapshot.reconciliation.unknown_orders === null ? 'neutral' : 'bad', testId: 'reconciliation-unknown-orders'},
    {label: '未知成交', value: countLabel(snapshot.reconciliation.unknown_executions), tone: snapshot.reconciliation.unknown_executions === 0 ? 'good' : snapshot.reconciliation.unknown_executions === null ? 'neutral' : 'bad', testId: 'reconciliation-unknown-executions'},
    {label: '持仓不一致', value: countLabel(snapshot.reconciliation.position_mismatches), tone: snapshot.reconciliation.position_mismatches === 0 ? 'good' : snapshot.reconciliation.position_mismatches === null ? 'neutral' : 'bad', testId: 'reconciliation-position-mismatch'},
    {label: '现金不一致', value: cashMismatch.value, tone: cashMismatch.tone, testId: 'reconciliation-cash-mismatch'},
    {label: '最近对账', value: reconciliationRun.value, tone: reconciliationRun.tone, detail: reconciliationRun.detail, testId: 'reconciliation-last-run'},
  ];

  const recoveryFields: RuntimeStatusField[] = [
    {label: '恢复状态', value: formatRuntimeLabel(snapshot.recovery.state), tone: statusTone(snapshot.recovery.state, ['ready', 'recovered']), testId: 'recovery-state'},
    {label: '需要确认', value: recoveryAck.value, tone: recoveryAck.tone, testId: 'recovery-requires-ack'},
    {label: '确认状态', value: ackStatus.value, tone: ackStatus.tone, testId: 'recovery-ack-status'},
    {label: '当前阻断项', value: snapshot.blockers.length ? `${snapshot.blockers.length} 项阻断` : '无', tone: snapshot.blockers.length ? 'bad' : 'good', detail: snapshot.blockers.length ? snapshot.blockers.map(formatRuntimeBlocker).join(' · ') : '运行时接口未报告阻断项', testId: 'recovery-blockers'},
  ];

  return (
    <WorkbenchFrame className="live-dashboard execution-workbench" testId="ibkr-trading-operations-center">
      <RuntimeBanner result={runtime} />

      <WorkbenchHeader
        code="IBKR"
        eyebrow="交易运维中心 / 只读"
        title="IBKR 运行操作中心"
        description="只读消费 IBKR runtime-status API，首屏呈现 Gateway、行情、Broker Truth、对账与恢复状态。"
        status={bannerTitle}
        statusTone={blocked ? 'bad' : 'good'}
        secondaryStatus="15 秒刷新 · 颜色不是唯一状态信息"
        meta={[
          {label: '运行时 API', value: runtime.kind === 'available' ? '可用' : '不可用', tone: runtime.kind === 'available' ? 'info' : 'bad'},
          {label: 'Paper / Live', value: '仅 Paper 校验', tone: 'warn'},
          {label: '实盘就绪', value: 'FALSE', tone: 'bad'},
          {label: '私有 / 订单', value: 'FALSE', tone: 'bad'},
          {label: '最近刷新', value: lastRefresh ?? '—'},
        ]}
        actions={(
          <button type="button" className="secondary-button" disabled={refreshing} onClick={() => { void refresh(); }}>
            {refreshing ? '读取中…' : '刷新只读状态'}
          </button>
        )}
      />

      <WorkbenchFlow
        items={[
          {label: '系统', value: formatRuntimeLabel(snapshot.runtime_state), tone: blocked ? 'warn' : 'good'},
          {label: '网关', value: connection.value, tone: connection.tone === 'good' ? 'good' : 'warn'},
          {label: '行情', value: marketHealthy.value, tone: marketHealthy.tone === 'good' ? 'good' : 'warn'},
          {label: 'Broker 事实', value: brokerFresh.value, tone: brokerFresh.tone === 'good' ? 'good' : 'warn'},
          {label: '对账', value: formatRuntimeLabel(snapshot.reconciliation.status), tone: statusTone(snapshot.reconciliation.status)},
          {label: '恢复', value: formatRuntimeLabel(snapshot.recovery.state), tone: snapshot.recovery.requires_operator_ack === false ? 'good' : 'warn'},
        ]}
      />

      <RuntimeStatusSection title="系统状态" subtitle="运行时权威 · 故障闭锁" fields={systemFields} testId="runtime-system-state" />
      <RuntimeStatusSection title="IBKR 网关" subtitle="传输 / 心跳 / 会话" fields={gatewayFields} testId="runtime-gateway" />
      <RuntimeStatusSection title="行情数据" subtitle="订阅 / 纪元 / 新鲜度" fields={marketFields} testId="runtime-market-data" />
      <RuntimeStatusSection title="Broker 事实" subtitle="Broker 快照 · 不显示原始账户号码" fields={brokerTruthFields} testId="runtime-broker-truth" />
      <RuntimeStatusSection title="对账" subtitle="订单 / 成交 / 持仓 / 现金" fields={reconciliationFields} testId="runtime-reconciliation" />
      <RuntimeStatusSection title="恢复" subtitle="异常恢复后需要人工确认" fields={recoveryFields} testId="runtime-recovery" />

      <section className="panel" data-testid="runtime-blockers">
        <div className="panel-header">
          <h3>当前阻断项</h3>
          <span>{snapshot.blockers.length ? '故障闭锁' : '无阻断项'}</span>
        </div>
        {snapshot.blockers.length ? (
          <ul style={{margin: 0, paddingLeft: 22}}>
            {snapshot.blockers.map((blocker, index) => <li key={`${blocker}-${index}`} title={blocker} style={{marginBottom: 6}}>{formatRuntimeBlocker(blocker)}</li>)}
          </ul>
        ) : (
          <p className="text-muted" style={{margin: 0}}>运行时接口未报告阻断项；这不会解锁实盘或订单权限。</p>
        )}
      </section>

      <RuntimeStatusSection
        title="安全旗标"
        subtitle="当前任务合同 · 永不自动解锁"
        testId="runtime-safety-flags"
        fields={[
          {label: '实盘就绪', value: 'FALSE', tone: 'bad', detail: '仅 research-only / Paper 校验'},
          {label: 'Broker 访问', value: 'FALSE', tone: 'bad', detail: '此页面不会发起 Broker 连接'},
          {label: '私有端点', value: 'FALSE', tone: 'bad', detail: '仅读取运行时状态'},
          {label: '订单端点', value: 'FALSE', tone: 'bad', detail: '不存在下单或撤单动作'},
        ]}
      />
    </WorkbenchFrame>
  );
}
