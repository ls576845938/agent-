# TQQQ 迁移 BTC 10x 滚仓爆炸版研究

## 结论

- 状态：`complete_research_only`。
- 决策：`tqqq_btc_10x_rollover_migration_danger_reference_research_only_no_paper_no_live`。
- 这是 danger reference，不是 paper/live 候选。
- 最佳场景：`tqqq_no_rollover_3x_cost0bps`，总收益 `130.094958`%，最大回撤 `35.183318`%，margin call `0`。
- 路径依赖：`path_dependent`。
- 方向层不是固定简化规则，而是 formal Donchian top-family grid，候选数 `54`。
- 选中方向：`formal_donchian_w240_d50_200_atr3_cd12_fail1_risknone`，方向层总收益 `39.336959`%，回撤 `12.74215`%。

## 来源归因

- 1x TQQQ no_rollover 总收益：`39.329621`%。
- 3x TQQQ margin no_rollover 总收益：`121.946859`%。
- 3x TQQQ split_2 总收益：`121.946859`%。
- split_2 相比 no_rollover 最终权益增量：`0.0`。
- 主驱动：`tqqq_trend_beta_and_margin_compounding_not_split_2_rollover`。

## 数据与执行

- 交易标的：`TQQQ`；信号标的：`QQQ`。
- TQQQ 数据源：`yahoo_chart_intraday_1h_derived_4h`，覆盖 `2024-07-08` 到 `2026-07-02`。
- bar 周期：`4H derived from Yahoo 1H research fallback`，年化周期数 `504`。
- 决策时间：QQQ completed 4H bar computes raw signal only after bar_end_utc; daily EMA trend uses the prior completed session.
- 执行时间：TQQQ target exposure is effective at the next completed 4H bar open; no same-bar execution.
- 2008 无法测试，因为 TQQQ 可用数据从 2010 年开始。

## 风险边界

- 不迁移 BTC 永续 funding、mark/index、24/7 交易和强平模型。
- 3x TQQQ margin 约等于 9x Nasdaq beta，只作为极端研究上限。
- 若出现 margin call、组合归零或单一年份/单一趋势段贡献集中，必须保持 danger reference。
