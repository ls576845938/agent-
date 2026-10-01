# BTC 系统接入验收：合成 v1 输入样本线格式修正

## 范围与结论

本票据只修正 `tests/integrations/test_candidate_offline_lifecycle.py` 中的合成输入序列化。生产 `OfflineInputs`、候选包、策略、风险、OMS、保护、账本、认证和权限合同均未修改。

根因是 `CandidateMarketObservation` 新增 `funding_settlements` 后，测试用 `asdict()` 把空值也写入了声明为 `candidate_offline_input_v1` 的 `observations.json`。生产读取器对 v1 使用精确字段集并正确返回 `offline_observation_facts_missing_or_extra`；因此错误在测试样本，不在生产拒绝逻辑。

## 合成 v1 wire 合同

测试样本现在显式且按固定顺序只写下列字段：

1. `event_time_utc`
2. `close_price`
3. `mark_price`
4. `index_price`
5. `delayed_open_price`
6. `funding_rate`
7. `funding_cashflow_usdt`
8. `blockers`
9. `end_of_window`
10. `maintenance_facts`

`funding_settlements` 只有 v2 才能表达。v1 helper 仅在该集合确实为空时省略该字段；非空时立即抛出 `synthetic_v1_fixture_cannot_drop_funding_settlements`，不会静默丢弃资金费事实，也不会把 v2 数据降级成 v1。

## 保持不变的拒绝边界

- v1 observation 出现额外 `funding_settlements` 字段时，生产读取器仍拒绝为 `offline_observation_facts_missing_or_extra`。
- 声明为 v2 却缺少 `dataset_contract` 与 `funding_rate_history` 等必需引用时，生产读取器仍拒绝为 `offline_input_revision_mismatch`。
- 未放宽未知字段、内容摘要、输入身份、时区、资金费、manifest 或 sealed evidence 校验。

## 证据性质与安全边界

这些输入、模型及成交均为明确标记的 `synthetic_fixture`，只用于系统接入和生命周期软件验收，不是研究候选、历史收益、交易有效性或 promotion evidence。

本票据不启动训练、离线业务长矩阵、服务、页面、Demo、账户或交易。`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission` 与 `runtime_observed` 均保持 `false`。

## 验证边界

本 producer 只运行纯序列化与生产读取器严格拒绝的快速测试。完整生命周期矩阵由独立 integrator 在提交态变更上集中执行；producer 不重复运行已耗时约 29 分钟的全矩阵，也不缩短其中既有的 600 秒等待预算。
