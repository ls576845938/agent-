# BTC 5m / 15m 遗传策略挖掘结论

票据：`BTC-INTRADAY-GA-STRATEGY-MINING-01`

变更风险：`unclassified`

基础提交：`2289d5d55cdb008a0b33a44b051c54a51f3597a2`

研究引擎提交：`b6d3a76d89bd58a177f32de483ba01ff87e04622`

结论：`complete_research_only / retained_candidate_count=0`

## 当前候选事实

- 当前策略注册表中的 `high_yield_donchian_v2` 是 `completed_1h_to_4h`、`identity_only` 候选，不具备 Demo 执行适配能力；它不是 5m/15m 策略，也不能因为历史高复利结果而直接加入 Demo。
- 既有 5m `btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1` 已冻结为失败的高频候选：90 天只有 4 个入场段，实质是稀疏事件过滤器，不应继续调参复活。
- 当前没有可直接选择的 5m 或 15m BTC Demo 策略。

## 数据与可见性

| 周期 | 固定 data version | 行数 | 区间 | manifest checksum | 只读解析 slice hash |
| --- | --- | ---: | --- | --- | --- |
| 5m | `qs-sqlite-BTCUSDT-5m-20240101T000000-bd0200707eb9` | 248,270 | 2024-01-01 至 2026-05-12 | `bd0200707eb9f595decb7b6122b88cdc87d97b95992f01c5e5afa61c53530374` | `ed290963dae286cdbad45ca86868ed07af91f785595e4f6a98c1a5ea4c59894a` |
| 15m | `qs-sqlite-BTCUSDT-15m-20240101T000000-01f96844fa1a` | 82,756 | 2024-01-01 至 2026-05-12 | `01f96844fa1a0eb906bf57ef340b5d398ac418565cf814a22d504d1529944ed1` | `6d63a13923bf79d1f7f55f9a7df41997a1cb67e1068168ff20666084e96cef5b` |

- SQLite 以 `mode=ro + PRAGMA query_only` 读取；没有刷新行情或调用网络。
- 特征只消费已完成 bar；决策发生在 bar close，成交只允许发生在下一根 bar open。
- 5m 与 15m 独立进化、独立 fold、独立候选，不把多周期相关信号伪装成分散化。

## 遗传搜索合同

- 22 个可解释 OHLCV 因子：EMA spread、动量、Donchian 位置、RSI、价格 z-score、成交量 z-score 和区间波动。
- 基因只控制 2–6 个因子及其离散权重、entry threshold 和信号平滑 bars；禁止 `eval`、任意代码和 broker 调用。
- 每周期每轮 `population=48`、`generations=16`，两周期每轮 1,536 个 population slots。
- 本票据累计 4 轮、6,144 个 population slots；前两轮暴露了“稀疏高 PF”和“满仓伪 buy-and-hold”目标函数缺陷，第三轮冻结最终适应度，第四轮只用于绑定已提交引擎并验证复现。
- 选择期使用 4 个扩展式时间 fold 和 embargo；尾部 20% 在单轮内部不参与选择。
- 由于前两轮尾部结果曾被查看并用于修正引擎，尾部窗口已降级为 `diagnostic_only_not_confirmatory_for_promotion`。未来任何确认都必须使用新的未见不可变数据版本。
- 成本按每单位 turnover 计入 fill/cash ledger：
  - base：fee 5 bps + spread 2 bps + slippage 2 bps；
  - conservative：7.5 + 3 + 4 bps；
  - stress：10 + 5 + 10 bps。
- 适应度拒绝稀疏逃避与满仓伪装：目标为至少 0.25 笔/日、1%–80% 暴露，并要求至少 3/4 个选择期 fold 为正。

## 冻结结果

| 周期 | 最优研究近失候选 | 选择期 | 尾部 base | conservative | stress | 样本密度 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5m | `btc_intraday_ga_5m_a55ebafec3da` | 4/4 fold 为正，但 0/4 达到样本密度合同 | +4.57%，PF 1.527，回撤 -2.06% | +3.08% | +0.30%，PF 1.030 | 13 笔，0.075 笔/日，暴露 0.123% | 拒绝：仍是稀疏事件，不是可验证短周期策略 |
| 15m | `btc_intraday_ga_15m_93c2780b00b9` | 3/4 fold 通过 | -14.40%，PF 0.928，回撤 -22.69% | -18.18% | -24.95%，PF 0.869 | 41 笔，0.238 笔/日，暴露 7.89% | 拒绝：尾部失效且成本越高亏损越大 |

5m 近失基因：

- `ema_spread_13_55 × -1`
- `ema_spread_21_89 × +1`
- `momentum_12 × -2`
- threshold `0.15`，smoothing `3 bars`，long-flat 1x

它可以保留为“稀疏反转事件”假设种子，但不得标记为 retained candidate、短周期交易策略或 Demo 可选策略。

15m 最优基因在新的弱势阶段直接失效，不保留为后续参数微调对象。

## 证据与安全边界

- 正式机器报告：`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-intraday-ga-strategy-mining-01/official-b6d3a76d8/btc_intraday_ga_strategy_mining_report.json`
- 中文摘要：`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-intraday-ga-strategy-mining-01/official-b6d3a76d8/btc_intraday_ga_strategy_mining_summary_cn.md`
- 候选定义：`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-intraday-ga-strategy-mining-01/official-b6d3a76d8/btc_intraday_ga_candidate_definitions.json`
- artifact hash：`41449a52b71b4f5741bed26203112d4d94e3f9e033a3dadf4cda9552f923955d`
- 5m 最优 ledger hash：`b726233aa0999a4a2ef031398a3535e5bc5d30b680f4632a74879efada2382fa`
- 15m 最优 ledger hash：`230e11df020618c11caa117019dc3dfabb0071a6a2680c4b2a5dd17ba52d4c42`
- `pnl_derived_from_fills_positions_cash=true` 仅表示离线模拟账本可对账，不等于 paper fills 或真实执行证据。
- `promotion=false`、`demo_registration=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`。

## 下一研究边界

本票据停止继续调整同一 OHLCV 基因池。若继续研究，必须另开独立假设与数据票据：

1. 由 data steward 发布 2026-05-12 之后的新未见 5m/15m 不可变版本，恢复真正的 confirmatory holdout。
2. 若研究 long-short / 永续策略，必须引入 mark、index、funding、清算缓冲和逐时可见性，不能用 spot OHLCV 冒充。
3. 若目标是高频/日内多次交易，必须增加 L2 spread/depth、延迟、排队、冲击和不成交模型；只有 OHLCV 不能证明可执行边际。
4. 只有新的假设在新未见窗口留存，才允许另开 runtime adapter 和策略注册票据；本票据不改前端候选列表和 Demo。
