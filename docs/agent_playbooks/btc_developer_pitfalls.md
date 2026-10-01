# BTC Developer Pitfall Rules

适用代理：btc程序员、BTC developer、负责 BTC 趋势/永续/paper gate 的程序员。

## 职责边界

- 负责 BTC 专用数据消费、策略接口、永续成本模型、风险、paper OMS、exchange rule preflight、replay、monitoring 和 gate artifact。
- 不访问真实 private/order/live endpoint。
- 不读取或输出 OKX/Binance API key、secret、passphrase、token。
- 不把 BTC 专用状态随意塞进美股共享枚举或共享执行语义。

## 必读文件

- `docs/agent_playbooks/pitfall_catalog.json` 中匹配 `btc_developer` 和任务 scope 的 active rules
- `docs/agent_playbooks/shared_pitfalls.md`
- 本文件
- `docs/knowledge/02_research_backtest/`
- `docs/knowledge/03_portfolio_risk/`
- `docs/knowledge/04_execution_oms/`
- `docs/knowledge/05_monitoring_replay/`
- `docs/knowledge/07_crypto_market_structure/`
- `docs/knowledge/08_live_trading_sre/`
- `docs/knowledge/09_exchange_api_security/`
- `docs/knowledge/10_btc_trend_strategy_playbook/`
- 命中具体 source 或调查历史事故时，再定向读取 `docs/btc_development_pitfall_log.md`

## BTC 专项硬线

- BTC 永续必须显式建模 funding、mark price、index price、liquidation buffer、杠杆和保证金模式。
- tick/step/min-notional 必须来自 venue rules；precision 只能作诊断，不能替代交易所过滤器。
- Forecast -> TargetPosition 必须包含 cost estimate、risk state、risk decision，不能直接生成真实订单。
- Paper OMS 用 BTC 专用 lifecycle/status，记录 append-only event history 和 idempotency key。
- Execution quality 读取 lifecycle event history，不只看最终 reconciled 状态。
- Audit DAG 必须固定顺序并校验依赖，不只是 artifact hash。
- Replay engine 不得自己读 latest/current/live。

## Gate / Artifact 规则

- 当前空仓 heartbeat 是健康运行状态，但不是 paper gate 通过。
- 当前没有理论订单时，必须显示“等待非空样本”，不能把它写成交易所规则失败，也不能当作成交证据。
- 一旦非空样本出现，自动捕获链必须生成 theoretical order、risk decision、OMS lifecycle、simulated fill、funding cashflow、liquidation buffer、depth fill mapping。
- historical simulated fill 或 diagnostic drill 不能替代当前 paper runtime 证据。
- kill-switch、cancel-only、reconciliation、incident review 必须有 failure-injection 演练证据。
- micro-live preflight 独立 fail-closed；即使上游全绿，也需要人工批准、最大本金、凭证权限和运行包络。

## OKX / 交易所规则

- WebSocket 要有断线重连、gapfill、sequence 校验、私有流对账设计；未证明时保持 blocked。
- 账户模式、仓位模式、保证金模式、限频预算、paper credential permission 都必须用人工证明 artifact 证明。
- 证明文件不允许包含 API key、secret、passphrase、token 或敏感截图。
- server time offset 超阈值时继续 fail-closed。
- outage、cancel-only、fail-closed 状态不能被 dashboard 文案掩盖。

## 测试要求

优先补合同测试和 gate artifact 回归测试：

- no-lookahead / bar replay / holdout lock。
- funding、mark/index、liquidation buffer、cost model。
- risk state 阻断、kill-switch、cancel-only。
- OMS lifecycle、partial fill、reject、cancel、reconciliation。
- audit DAG、replay diff、incident artifact。
- micro-live preflight 和 dashboard 自引用 blocker 稳定性。
