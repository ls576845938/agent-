# M2 历史环境特征 A/B 结果

> 归档来源：本页归档自 source run HEAD `f8510e3c15dc82642b37dbb33eb58bcdb801ffaa` 的最终独立 digest review，原报告 commit 为 `9263c4bc9f8d22c66620d2f8906500c63f19e966`，handoff 容器 commit 为 `c885f3e0515e967b50afc193754ead2fd47a5c10`。下方结果保留历史计算身份，不冒充本归档提交的 current-head 运行证据。

结论：本轮没有稳定支持 M1 环境特征带来整体增量预测信息。四折中 3 折 RankIC(B-A) 为正，但四折平均为 `-0.0248725`；B 的平均 RankIC 与平均 MSE 均差于 A。这是历史探索结果，不是清洁 holdout 验收；主会话独立复核后不建议为本版 15 个环境特征追加独立确认，且 `confirmation_passed=false`。

## 实训与完整性

- 一次性 authorization-id：`root-reviewed-M2-HIST-20260913-80890a7b0-once01`。
- source run HEAD：`f8510e3c15dc82642b37dbb33eb58bcdb801ffaa`；8/8 次 fit 全部 completed，0 失败、0 重试。A 为 13 特征，B 为 28 特征。
- 8 个 trial seal 全部校验为 passed；8 份生成配置均是 120 轮上限、valid-only early stop 15。
- 每折 A/B finite coverage 和 paired coverage 均为 100%；折 1 为 146 行，折 2–4 各 145 行。
- 外部结果 manifest：`D:/vibe coding/Obsidian/量化系统/research-evidence/m2-historical-ab-20260913/result_manifest.json`，SHA-256 `5270f155ef4871bd619f00fadb1079dee1ca12f347df661dd3e377d796c5f37e`；245 个文件、64,524,445 bytes 的 size/hash 全部复核一致。`result.json` SHA-256 为 `cfab8da27ae4fafb9aaa429246d9aaea492d9a13128496657c1016b9b6134a2d`。

## 折结果

| 折 | Test UTC | RankIC A | RankIC B | B-A | MSE A | MSE B | Zero MSE |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 04-26 04:00 — 05-02 05:00 | -0.250859 | -0.117694 | +0.133164 | 0.000123291 | 0.000123242 | 0.000119917 |
| 2 | 05-02 21:00 — 05-08 21:00 | +0.459980 | +0.171571 | -0.288409 | 0.000080584 | 0.000080824 | 0.000075894 |
| 3 | 05-09 13:00 — 05-15 13:00 | -0.309378 | -0.256517 | +0.052861 | 0.000183634 | 0.000194417 | 0.000155314 |
| 4 | 05-16 05:00 — 05-22 05:00 | -0.212539 | -0.209646 | +0.002893 | 0.000047852 | 0.000049584 | 0.000044195 |

折 2 是主要失效期：B 相对 A 的 RankIC 减少 `0.288409`，抵消了其他三折的正增量。按预定 M1 168h direction 分段后，增量符号仍会在 up/down 之间翻转；样本小且不稳定，不声称存在可复现的环境优势。A、B 都在 0/4 折上优于 zero-forecast MSE。

每折都少于 168 行，不跨折拼块后完整 168bar 块为 0，因此 95% 推断区间为 null，统计结论为 inconclusive。这不否定描述结果，但禁止将它写成确认通过、套利收益或扣费净值。

## 独立复算结论

主会话对封存结果完成独立复算：245 个文件、64,524,445 bytes 的 size/hash 全部通过，8 个 trial seal、120/15 配置和 source run HEAD 均一致；从原始 bars 独立按 `shift(-14) / shift(-2)` 构造标签，并按冻结 test 边界对齐 8 份预测，共 581 个 paired observations，四折 RankIC、MSE 和 zero MSE 逐项相符。B 的四折平均 MSE 比 A 高 `2.91849%`。

独立结果意见为：本版 15 个环境特征直接加入预测未显示整体且稳定的增益，历史探索限定结项，不为本版追加独立确认；M1 旁路保留，M3/M4 不启动。该结论不证明所有环境模型无效，也不是原 BTC 策略回测或任何执行放行。

所有 `demo_control_enabled/promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 仍为 false；没有 fill、PnL、执行、M1 前端或 M3/M4 变更。
