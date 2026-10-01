# Donchian 市场状态条件政策 A/B 只读投影 v1

状态：读模型与页面槽位已定义；完整两臂结果仍未形成。baseline 完成 `2960 / 2960`，conditioned 在 `1956 / 2960` 因同一小时 K 线保护价位双触达而 fail-closed；因此只能封存阻断事实，没有实际政策效果结论。

## 固定身份

- trial：`donchian-stage-market-policy-trial-20260927-v1`
- baseline run：`donchian-market-entry-baseline-20260927`
- conditioned run：`donchian-market-entry-conditioned-20260927`
- consumer execution source：`f2455bfbcafd15404bb4ff98dd6bb925728d0339`（页面发布 HEAD 可不同，不得代替计算来源）
- 协议：`97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02:docs/research/market-state-conditional-policy-protocol-20260927.json`
- 状态证据：`211e5e286923f520b9ab0d039304b6b6af82114c:.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json`
- 未来小摘要固定路径：`.agent/market_state_evidence/donchian-stage-market-policy-trial-v1.json`

该路径与原 2960 小时阶段摘要不同。A/B 结果不得覆盖原 `policy_trial=not_started` 事实，也不得使用旧年度运行身份。

## 写入前提

只有两臂 writer 全部退出且账本核验完成后，才可由离线发布步骤生成小摘要。两臂均完整时可封存 `market_policy_trial_report_v1`；任一臂 fail-closed 时，原始封存为 `market_policy_trial_blocked_report_v1`，页面只消费绑定该文件与两份 ledger receipt hash 的 `market_policy_trial_blocked_read_model_v1`。该小投影仅包含阻断断点、进度、终态持仓、核账绑定和 48 phase 计数，不包含 comparison 差额或 effect 结论。GET 只从当前 Git 提交读取该投影，禁止打开运行目录、扫描日志、恢复回放或重新核账。

小摘要必须绑定：

- 固定 trial、两臂 run ID、consumer commit；
- 原策略、规格、数据、成本、时间、模拟账户及 attachment 身份；
- 状态定义、来源、内容及输入 hash；
- 每臂事件数、入场提议/拒绝/执行、开平仓、敞口合约小时、持仓小时；
- 每臂源 artifact、账本核验回执的 SHA-256，以及 writer 退出和核账时间；
- 价格盈亏、手续费、资金费、净额及账本计算的最大回撤；
- 恢复/去重/末仓/账本核验结果；
- 每条实际拒绝决策的 `event_id`、`market_entry_policy`、`selected_state` 和 `evidence_links`；
- 每条拒绝决策的 `state_binding_status` 必须为 `verified`；退出、减仓或 sidecar 不可用时的 non-entry 透传记录不属于 `decision_effects`；
- `selected_state` 必须与 policy 中的 definition/source/input/content hash、质量原因和因果截止时间精确一致。若存在按同一 content hash 封存的完整状态对象，可携带 24/72/168 小时路径效率、方向、归一化趋势强度、多尺度一致性、波动及历史相对位置、扩缩、冲击、持续性和切换频率；否则必须记录 `projection_source=consumer_phase`、`projection_status=partial`，把取不到的指标保持为 `null` 并逐项列入 `missing_fields`。

被政策拒绝的新增仓位必须为 `no_order`，order intent、订单、成交和账本链接均为空；已有仓位、退出、减仓与保护不能被政策覆盖。

## 页面解释

没有小摘要时内部兼容状态仍为 `not_started`，页面解释为“尚无已封存 A/B 结果”，不得据此推断后台任务是否启动；文件存在但校验失败时显示 `blocked`，绝不回退到测试 fixture、旧分组或近似运行。完整两臂报告只在两臂均完成时展示对照数字。合法阻断报告则只展示每臂进度、精确断点、核账状态与保留的终态持仓；不展示完整 A/B 差额，不宣称改善。

当前冻结 consumer `f2455bfbcafd15404bb4ff98dd6bb925728d0339` 的 phase 持久化精确状态 hash、status/reasons/cutoff 与 policy decision，但不持久化每个历史 phase 的完整 `MarketStateV2` 数值；`market_state_replay.last_observation` 只代表最近状态，禁止填到较早 phase。因此本次两臂 exporter 应诚实输出 `consumer_phase/partial`，多尺度数值为 `null + missing_fields`。只有未来另有不可变逐事件状态对象并能按 content hash 精确连接时，才可使用 `exact_state_hash_join/complete`；GET 永不补算。

原 2960 小时阶段摘要内的 `policy_trial=not_started` 与 `runtime=false` 是**原阶段封存时**的历史事实。后续独立 A/B 小摘要即使完成，也不会改写它；页面必须用历史时态解释两份证据，不能造成自相矛盾。

`decision_effects` 只列政策实际拒绝的新入场，不是全部策略决策。未受政策影响的持仓、退出、保护、订单和账本关系仍以两臂原始封存及核账回执为权威；只读投影不得因为状态值缺失而隐藏这些关系。

本次 conditioned 臂在 `2025-11-21T12:00:00+00:00` 触发 `ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous`，以 `-0.01` 张终态持仓 fail-closed 停止；没有伪平仓，也没有按有利的盘中路径选择成交顺序。因此本次不存在完整政策效果估计，更不支持晋级、Demo、paper 或 live。
