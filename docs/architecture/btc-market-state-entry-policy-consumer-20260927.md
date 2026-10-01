# BTC 市场状态 entry-only 离线消费合同（2026-09-27）

## 目标与边界

本票只把已封存的市场状态描述和 `entry_path_efficiency_72h_v1` 条件政策接到原 Donchian 历史回放的**空仓新开仓**位置。原 Donchian 信号、固定合约目标、减仓、退出、反向先平、保护单、Risk、Guardian、OMS、成交和持久账本仍是原权威链。

- 没有 attachment/provider 时完全沿用原路径。
- 已有仓位时无条件保留原目标；条件政策不得阻断减仓、退出、反向先平或保护成交。
- 只有 `current_position == 0` 且原目标非零时，状态未知、身份不匹配或 72 小时路径效率低于冻结阈值才把有效目标改为零。
- 市场状态仅由当时可见、已完成的小时 K 线前缀计算。状态资产、截止时间、定义和来源绑定不一致时 fail-closed。
- 不训练、不搜参、不改变成本、策略、数据窗口或权限；不接 Demo、paper、live、private 或 order endpoint。

## 不可变来源

| 项目 | 精确来源 |
|---|---|
| 历史评估规格 | `25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json` |
| A/B 协议 | `97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02:docs/research/market-state-conditional-policy-protocol-20260927.json` |
| 状态诊断证据 | `211e5e286923f520b9ab0d039304b6b6af82114c:.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json` |
| 状态证据 blob SHA-256 | `2a4345a7d9a867cd1888addad00659583ea744911aa0b5b8486ad8c282c9c00b` |
| 分析窗口 | `[2025-09-01T00:00:00+00:00, 2026-01-02T08:00:00+00:00)`，2960 根小时事件 |
| 预热起点 | `2025-02-13T00:00:00+00:00` |

构建器从 Git blob 和已验证的 `HistorySpec` 重建 strategy/spec/data/cost/time/source 身份，不把 attachment 自述当作权威。baseline 与 conditioned 使用不同的 attachment/policy hash，恢复时不得互换。

## 运行身份与输出

建议在独立集成审查通过后使用新的、互不共享状态目录的身份：

- baseline：`donchian-market-entry-baseline-20260927`
- conditioned：`donchian-market-entry-conditioned-20260927`

历史 artifact 继续使用既有 `DonchianHistoricalReplay` 格式，并在 v2 中增加：

- 顶层 `market_entry_policy`：arm、protocol/evidence Git ref 与 blob hash、attachment、分析边界及解释等级；
- `market_state_replay`：事件数、严格绑定的可恢复流快照及最后状态；
- 每个 phase 的 `market_entry_policy`：
  - `state_version/state_definition_hash/state_source_binding_hash/state_content_hash/state_input_hash`；
  - `policy_id/policy_version/policy_hash/attachment_hash`；
  - `original_target_contracts/effective_target_contracts/applied/reason`；
  - 状态、原因、截止时间及当时持仓；
- 原有同一 phase 的 `evidence_links`：signal、target、risk、order intent、client/exchange order、fill、ledger 与 action；
- 原有 `safety`：Demo、paper、live、runtime observed、network accessed 均为 false。

因此，政策影响与 event/order/fill/ledger 使用同一事件身份，不通过日志猜测或相似记录拼接。拒绝新开仓时是明确的 `no_order`，order/fill/ledger 链接为空，不伪造成交。

## 有界执行入口与预算

以下仅是经独立审查后的运行模板，本提交不启动 A/B：

```powershell
py -3 scripts/run_btc_donchian_history.py run `
  --output-root <external-immutable-root> `
  --run-id donchian-market-entry-baseline-20260927 `
  --spec-git 25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json `
  --market-policy-protocol-git 97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02:docs/research/market-state-conditional-policy-protocol-20260927.json `
  --market-policy-evidence-git 211e5e286923f520b9ab0d039304b6b6af82114c:.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json `
  --market-policy-arm baseline
```

conditioned 只替换新的 `run-id` 和 `--market-policy-arm conditioned`。必须串行运行；每臂最多 120 分钟，两臂加最终核账总预算最多 4 小时。现有旧阶段运行约占 3.02 GiB，两臂初估新增约 6 GiB；这只是容量规划，不代替开跑前和每个批次边界的 fresh 磁盘检查。开始前及批次边界必须保持至少 20 GiB 可用空间。超预算或空间不足时在现有批次/检查点边界安全停止并报告，不改窗口或参数，不清理、复制或覆盖旧产物。

不得恢复或修改已暂停的旧 `2960 / 8760` 年度运行。A/B 使用新身份；baseline 的经济结果只可与旧 2960 阶段数值作非身份业务对照，不能复用旧账本。

## 只读投影与停止条件

本提交提供可封存的 artifact 字段，不在 GET 请求中恢复回放、重新核账或启动任务。A/B writer 完全退出且账本核验完成后，由现有 Donchian 离线读模型增加两个**固定 selector** 投影；复用现有研究详情页，不新建控制台或服务。旧市场诊断的 `policy_trial=not_started` 不得被改写，新 trial 使用独立摘要关联。

本票完成只证明 entry-only 政策已进入同一离线经济链且可被精确审计；不证明政策有效，不授予候选交易、Demo、paper 或 live 权限，也不启动 M3/M4。
