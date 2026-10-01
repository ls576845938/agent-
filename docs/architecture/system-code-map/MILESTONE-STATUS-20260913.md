# M1 / M2 里程碑状态

- as-of：`2026-09-13`
- 状态核查基准：`9ce39a517f6d4cb825a3b4aeb9993db5c2c0162d`
- 用途：将当前里程碑状态与历史源码审阅快照分开。本页不是 promotion evidence，不授予任何交易权限。

## 状态矩阵

| 范围 | 已实现 | 已测试 | 已运行验证 | 尚未完成 |
| --- | --- | --- | --- | --- |
| M1 趋势环境旁路 | 资产中性、历史因果环境观测，Qlib / Alpha Factory sidecar，版本化证据与只读页面关联 | 限定工程验收：Python `205/205`，前端定向 `27/27` | 已验证历史研究生产者与证据链；不是真实交易运行 | 未证明 Alpha 增益；未接入默认信号、仓位、退出、Risk、OMS、保护单或账本决策 |
| M2 历史环境特征 A/B | 冻结两臂、四折、最多八次训练的历史探索对照 | 8/8 fit completed，0 失败，0 重试；245 个封存文件的 size/hash 已独立复核 | 已使用 source run HEAD `f8510e3c15dc82642b37dbb33eb58bcdb801ffaa` 完成历史探索 | 不是清洁 confirmatory holdout；本版不晋级、不追加搜索；M3—M4 未启动 |
| BTC 账户事实／账本恢复 | 版本化账户回撤事实、持久 UOW、经济重放和 fail-closed 对账合同；显式 baseline 入口、完整 account bills/cashflow provenance 和 Guardian `max_drawdown_unit` 装配已发布 | current-main 发布验收汇总 `270 passed`；另有 `4 failed`，均为既有旧 fixture 未提供审定 drawdown unit/account fact，未通过放宽 Guardian 修绿 | 未开始真实账户只读验收；未读凭证，未调用 private endpoint | 真实 registry、人工批准、全账户封存 snapshot、完整 bills 页与 baseline 登记仍未验收；不代表 promotion、paper 或 live ready |

## M2 结果与停止结论

M2 是探索性增量证据，不是原 BTC 策略收益回测，也不是执行验收。四折中 3 折的 RankIC 增量为正，但平均 RankIC 增量为 `-0.0248725`，B 臂平均 MSE 比 A 臂高 `2.91849%`；第 2 折的 `-0.288409` 抵消其他折改善。每折少于 168 个小时样本，完整 168bar block 为 0，统计推断为 `inconclusive`。

因此本版 15 个环境特征保留为 M1 旁路证据，不进入默认决策，不为了改出正结果继续搜索。这不证明所有市场环境模型都无效。

## 精确来源

- M1 独立结项：`docs/operations/m1-closeout-m2-validation-integration-20260912.md`，交付 commit `c3a1f0b7779d175327d961aa6cd4555c2cb8d116`。
- M2 实际计算 HEAD：`f8510e3c15dc82642b37dbb33eb58bcdb801ffaa`。最终 digest review commit：`9263c4bc9f8d22c66620d2f8906500c63f19e966`；handoff 容器 commit：`c885f3e0515e967b50afc193754ead2fd47a5c10`。
- M2 外部封存 manifest：`D:/vibe coding/Obsidian/量化系统/research-evidence/m2-historical-ab-20260913/result_manifest.json`，SHA-256 `5270f155ef4871bd619f00fadb1079dee1ca12f347df661dd3e377d796c5f37e`。
- M2 外部封存 result：`D:/vibe coding/Obsidian/量化系统/research-evidence/m2-historical-ab-20260913/result.json`，SHA-256 `cfab8da27ae4fafb9aaa429246d9aaea492d9a13128496657c1016b9b6134a2d`。
- 已验证 handoff：`.agent/handoffs/M2-HISTORICAL-ENVIRONMENT-AB-20260913/superseded-result-digest-review-9263c4bc9.json`，`status=valid`；它保留原研究的 `quality_checked`上限、`promotion_eligible=false` 和完整 blockers。
- BTC 账户事实入口独立集成审查：`docs/acceptance/integrate-btc-account-facts-entry-wiring-20260913.md`。其中定向核心合同为 `61 passed / 4 failed`；4 个失败是同一组既有旧 fixture，不是入口功能回归。
- BTC 账户事实入口 current-main 发布验收：`output/playwright/account-facts-entry-release-20260913/release-acceptance.md`，汇总 `270 passed / 4 failed`。该运行证据不替代真实账户只读验收。

## BTC 下一道门的实际状态

账户事实入口接线已发布，不再把下列项目列作“尚未接齐”：显式 baseline 操作入口、完整 account bills/cashflow provenance、Guardian `max_drawdown_unit` 装配。它们已通过离线工程与 current-main 发布测试，但这只是实现和测试层状态。

真实账户只读验收仍未执行：没有读取凭证，没有调用 private endpoint，也没有真实 registry、人工批准、全账户封存 snapshot、完整 bills 页或 baseline 登记结果。现有 4 个旧 fixture failure 继续如实保留；不得据此放宽 `max_drawdown_unit_unknown` / `drawdown_unknown` 的 fail-closed 行为。缺 receipt 也仍只是运行前置之一，不能自动完成账户事实验收或打开交易权限。

## 权限和页面边界

本次只是状态归档与只读页面投影，不刷新 BTC runtime artifact，不使用历史研究证据声称 current-head 执行已验收。`demo_control_enabled/promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 全部保持 `false`。
