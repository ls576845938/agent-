# 共享市场状态 v2 与单策略条件政策

状态：共享定义与历史诊断已实现；条件政策效果未验证；运行接线与交易权限未启用。

## 目标与边界

该模块回答两个相互独立的问题：

1. 在决策时点，当时可见的市场路径呈现怎样的趋势、效率、波动、冲击和切换特征？
2. 一个预先冻结、只影响新增仓位的条件政策，是否在同一策略和同一成本口径下带来稳定增量？

它不替代策略信号、仓位政策、Risk、Guardian、OMS、保护单或账本，也不在状态模型内下单。研究描述、历史分组、政策试验和运行观测必须分别记录。

## 结构

```text
版本化 OHLCV + 可见时间 + 日历
              │
              ▼
因果状态生产者 market_state_descriptive_v2
  ├─ 连续数值：方向、强度、路径效率、一致性、波动、扩缩、冲击
  ├─ 状态质量：observed / unknown + 明确原因
  ├─ 持续与切换：相同 bar 不重复计数，缺口后重新预热
  └─ 身份：定义、来源、可见窗口及内容哈希
              │
       ┌──────┴────────────┐
       ▼                   ▼
历史描述与分组             entry-only 条件政策
bar / trade / segment       默认关闭、72h效率<0.20
精确决策时间关联            只可拒绝 flat→new entry
不做最近时间拼接            持仓/减仓/退出/保护透传
       │                   │
       ▼                   ▼
提交态小证据               版本化 policy attachment
GET 只读，不补算            绑定完整基础策略/数据/成本/时间/证据
       │                   │
       └────────┬──────────┘
                ▼
        BTC 消费与固定 A/B（独立票据）
        当前尚未形成运行效果证据
```

## 阶段状态

| 阶段 | 当前结果 | 不能据此声称 |
|---|---|---|
| 状态定义 | v2 已实现并通过批量/逐根/恢复/未来追加一致性测试 | 概率模型、已验证市场择时 |
| 历史诊断 | 2960 bars、28 roundtrips、170 segments 已精确关联 | 170 个独立交易、策略有效概率 |
| 分组描述 | 18 low、9 mixed、1 directional；价格盈亏与费用可分组 | 逐组净收益，因为 funding 仅有总体 |
| 条件政策 | 72h 路径效率阈值 0.20 已预先冻结，默认关闭 | 18 次拒绝能改善收益或回撤 |
| A/B | 协议、consumer 与只读结果 schema 已冻结；真实两臂仍为 `not_started` | 政策效果已验证 |
| BTC 运行消费 | 共享 attachment 合同已提交；实际消费由 BTC 独立接线和验收 | 当前运行已启用市场状态 |
| 权限 | 所有 Demo/paper/live/private/order/transfer/withdraw 保持 false | 可部署或可交易 |

## 冻结 A/B 预算

- 两臂：原 Donchian；原 Donchian + 冻结 entry-only 政策。
- 同一 2960 小时阶段、同一 4800 小时预热、同一数据、成本、账户和基础策略。
- 共两次固定回放；训练 0 次、参数搜索 0 次。
- 一次报告后停止，不按结果调整 72 小时窗口或 0.20 阈值。
- 必须报告新开仓拒绝数、开平仓数、价格盈亏减手续费、可用时的回撤、状态覆盖、退出/保护不受影响，以及敞口与持仓时长。
- 28 次开平仓只能形成探索性证据；任何后续独立确认和晋级都需另行设计。

## 证据与读取

- 冻结协议：`docs/research/market-state-conditional-policy-protocol-20260927.json`
- 历史诊断：`.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json`
- 只读服务：`backend/app/services/donchian_stage_views.py`
- 详情展示：`frontend/src/workspaces/research/MarketStateEvidence.tsx`
- A/B 结果合同：`docs/research/market-policy-trial-read-model-v1.md`

页面 GET 只读取并校验已提交的小摘要，不打开年度运行目录、不恢复回放、不扫描大日志、不重算状态。原 Donchian 阶段证据和市场状态证据分别校验；市场证据缺失时必须明确显示不可核验，但不能篡改原阶段账本结论。

## 下一可执行动作

BTC consumer 已有提交态交付，但 A/B 尚未运行。独立集成后应使用两个冻结的新运行身份串行执行；writer 退出并核账后，把独立小摘要写入固定 trial 路径。既有页面会读取该摘要并展示实际拒绝决策、同一决策的状态身份／质量／截止时间、原／有效目标、两臂经济结果、敞口和持仓时长，无需新控制台。24/72/168 小时等数值只有在存在相同 content hash 的逐事件封存对象时才显示；当前 consumer phase 没有全量数值，必须显示为 partial/缺失，不能借用最后状态。摘要存在之前不得显示改善曲线、命中效果或“适合交易”。原 stage 的 `not_started/runtime=false` 继续以“原阶段封存时”表述，不因后续 trial 被改写。
