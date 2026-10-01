# 候选离线诊断准入分离（2026-09-26）

## 目标与边界

本票只把“完整、可复现的包可进入隔离离线诊断管理”与“研究通过／可交易”分开。原候选包、原研究结论和原始 `admission_blockers` 不被改写；Demo、paper、live、private、order、execution 与 promotion 权限继续为 `false`。

## 准入规则

- 新建交接记录保存版本化 `strategy_delivery_diagnostic_admission_v1`，绑定包摘要、目标、消费端 HEAD 和决定摘要。
- `offline` 目标仅允许 `no_simulated_fills` 与 `research_admission_not_proven` 作为诊断型研究阻断；页面和记录继续展示这些原因。
- 该决定仅适用于 `offline`；即使某个包声明支持 Demo，也不能借用这个诊断准入。
- 校准质量、未平仓、挂单、完整性、身份、来源 hash、合同、适配器、结算币种以及任何未知原因仍是硬阻断。
- 无版本化决定的旧记录沿用原严格校验；已有拒绝记录不会翻转。审定摘要显式绑定诊断决定，篡改或重编译漂移均拒绝。
- 登记仍返回 `start_allowed=false`，登记不表示运行成功或交易授权。

## 当前离线 worker 限制

候选管理准入与实际 worker 支持继续分开。当前后台 worker 只声明支持 `factory_lgbm_ast_v1`。历史 M1 Qlib v2 包 `btc_frozen_qlib_offline_v1` 可以如实形成新的诊断管理记录，但当前入口不得启动它；服务端在创建作业、占用账户／状态或派发线程前返回 `offline_runtime_adapter_unsupported`，前端依据服务端 `supported_adapter_ids` 禁用启动。

因此本票不是“任意研究较差候选都可运行”，也没有补建 v2 执行适配器。

它也不表示“完整交易生命周期已完成”：当前 registered 离线路径在保护价触发时仍按既有设计阻断并保留状态。本票不实现保护成交，不修改执行语义。

## 验收口径

- 两项允许原因可贯通新记录的 create → bind → review → register → resolve，研究 blocker 和全套 false 权限保持。
- 坏 hash、错误身份、缺合同、未知 blocker、币种不符继续 fail-closed。
- 旧记录、旧拒绝和旧幂等回执不因代码升级获得新准入。
- 不写真实候选库、不启动回放、不访问账户、交易所或密钥。
