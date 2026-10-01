# BTC-5M-TREND-FAMILY-GA-SEARCH-02

## 结论

本票据完成了 5m 趋势假设的 typed/hierarchical GA、不可变 selection-prefix 数据绑定和一次冻结官方搜索。结果为：

> `complete_research_only / reject_selection_batch_holdout_not_read`

没有候选通过预注册 selection gate，不登记 Demo 策略，也不进入 paper、promotion 或 live。未见尾段没有出现在消费者输入中：`holdout_bytes_read=0`、`holdout_rows_decoded=0`、`holdout_strategy_metrics_read=false`。

## 第一性原理架构

只搜索两个相互独立的经济假设家族：

1. `breakout_retest_continuation`：既往通道突破、HTF 趋势/质量过滤、5m 回踩确认、语义失效和时间退出；不强制压缩状态。
2. `directional_efficiency_continuation`：路径效率比率过滤 EMA 方向/斜率，再由 5m continuation 触发入场，目的是减少震荡期均线 whipsaw。

两类 genome 使用不同 dataclass，只包含各自 active genes。交叉、变异、邻域都严格限制在家族内；跨家族只进行统一 Pareto 比较。固定 EMA 12/48 crossover 仅作为 negative control，不进入 genome、试验计数或冠军选择。

策略链保持：

`经济假设 -> 适用状态 -> completed 5m close 入场事件 -> 失效检测/时间退出 -> 固定仓位 -> 固定风险 -> next-open fill -> position/cash ledger`

固定仓位和风险全部位于 genome 外：1x 上限、12-bar sizing 更新、15% no-trade band、bar hard-stop proxy、4% 日内暂停和 15% sticky strategy-loss gate。研究硬止损不是交易所托管保护单。

## 数据隔离

- dependency event：`published-btc-5m-qcv2r1-selection-prefix-01-8748a1775`
- data deliverable：`8748a177561e66537b597c8c6537bb69092adef0`
- handoff tip：`ad4e14258f49a4c3e79066560a3bce0da0624880`
- dataset version：`btc-5m-qcv2r1-selection-prefix-248270-parent76e8654c-mainbcc31f0b-corr01`
- manifest Git blob SHA-256：`0c38ae5cd13fb47f074573047c68b3a6da1ca237b2ef75c9e5fcb651c8dd35d3`
- prefix payload SHA-256：`b00557b75b3b4049bde1c09bfa69d31a8856993bb9f4fbdc71cfb49078b8f9b5`
- aggregate SHA-256：`ac599353f65ee31b4a40b1d516c8ad244fc9f30c1a098403167fdbc6e0774741`
- prefix bytes：`89,831,446`
- selection rows：`248,270`
- coverage：`2024-01-01T00:00:00Z` 至 `2026-05-12T01:05:00Z`

消费者拒绝完整 qcv2r1 partition；只接受上述 committed shared manifest、selection-prefix attestation 和精确 payload。resolver 校验后仅解码 prefix 文件。上游 attestation 明确记录 `application_bytes_after_boundary=0`、`holdout_row_decoded=false`、`strategy_metrics_read=false`。

## 冻结验证设计

- engine code commit：`b2499b3f0ab03f67272aead61de4b54e4993d2a9`
- frozen prereg commit：`c93a887c4bde937f7d84a47f6860d1e4df05bcdf`
- seed：`20260827`
- family population：每家族 24
- generations：6
- planned slots：288
- 参数邻域上限：12
- prior unique trials：1,587
- 新增 unique trials 上限：300
- 累计上限：1,887
- walk-forward：4 folds
- maximum lookback：192 bars
- event memory：288 bars
- embargo：480 bars，等于 lookback + event memory
- 每折从空仓开始，只统计验证窗口内新 entry
- 三档 round-trip 成本：10 / 16.5 / 30 bps，全部进入 Pareto 和 fold gate
- 成交：completed close 决策、next open fill
- PnL：fill/position/cash ledger 推导

每个 fold 的预注册门禁为：适用状态不少于 288 bars、独立 bets 不少于 8、有效 bets 不少于 4.8；base/conservative/stress 均须正收益，PF 分别不低于 1.05/1.02/1.00，最大回撤均不低于 -20%。候选还必须至少 3/4 folds 通过、pooled effective bets 不少于 30、多重检验修正后 mean bet return 为正且参数邻域通过。

## 官方搜索结果

- artifact path：`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-5m-trend-family-ga-search-02/official-c93a887c4bde`
- report semantic hash：`f0b4830484bc4c0f9d905e025e838d73bfaf51a463b3afe441b0e530bef8120b`
- report file SHA-256：`1721963d6ea695c781f42f0fb7b2debd92c8345d0d4b8851ff964cbf6b7e10ef`
- candidate lock file SHA-256：`d3b275ae083d0a9f29e0eed48ce6bc777e735f965dd25d6ddd11092a260807cc`
- candidate definitions file SHA-256：`d9818df15f9cec27997872e1307a1bdc35f7192eb6cdf7ae8fe323bcb5340dc5`
- 实际 GA unique trials：245
- 同家族邻域新增：8
- 本轮新增 unique trials：253
- 累计 unique trials：1,840

排名首位为 `btc_5m_trend_0c84964f7fc0`，genome hash `0c84964f7fc0422a71497ed1f82d0268365c3308f2c14afb31c120e98b0991a3`，属于 `directional_efficiency_continuation`。其 active genes 为：ER 96 bars、threshold 0.55、EMA 24/96、slope 6、continuation 48、exit 24、ATR 24、entry buffer 0.25 ATR、max hold 24、cooldown 6。

该候选四折均没有达到入场条件：每折 `entries=0`、`fills=0`、`independent_bets=0`、`effective_bets=0`，因此四折均不适用且不通过。它作为 Pareto 排名首位表示：在本轮所有成本后为负的活跃候选面前，算法偏向了零风险 abstention；这不是 Alpha、不是合格策略，也没有绕过适用性门禁。

参数邻域共 10 个实际生成项（8 个属于零收益/零交易平台），因为 baseline median return 不为正，稳定性仍为 fail。最终阻断原因：

- `passed_folds_below_3_of_4`
- `pooled_effective_bets_below_30`
- `multiple_testing_deflated_mean_bet_return_non_positive`
- `parameter_neighborhood_stability_failed`

固定 EMA 12/48 negative control 的四折基础成本收益分别为 `-15.183243%`、`-15.102786%`、`-15.215205%`、`-15.105636%`，PF 为 `0.8622 / 0.8926 / 0.6932 / 0.8486`。它没有参与冠军选择。

## 来源边界

以下文献只用于预注册经济假设或负对照背景，不被描述为当前数据上的现成 edge：

- `https://doi.org/10.1016/j.frl.2019.08.011`：trading-range breakout 假设。
- `https://doi.org/10.3390/risks8020044`：5m moving-average 规则的负面对照。
- `https://ssrn.com/abstract=4080253`：intraday momentum/reversal 对 jump、liquidity 和 regime 的依赖。
- `https://ssrn.com/abstract=3416106`：5m realized-volatility 测量背景。
- `https://arxiv.org/abs/2009.12155`：crypto walk-forward trend-following 的低频背景。

## 阻塞与下一步

本批次不能揭示未见尾段。后续若继续研究，应该另开预注册票据并解决“全折零交易候选占据 Pareto 首位”的可解释性/候选报告问题，同时保留最低适用状态和独立 bet 门禁；不得回写本轮门槛，也不得把本轮未见集用于调参。

L2、排队、未成交、市场冲击、资金费、mark/index、强平和交易所托管保护单仍未证明。这些不是本轮 selection-only Alpha 筛选的前置阻塞，但在任何 paper/promotion/live 之前必须另行解决。

`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`。
