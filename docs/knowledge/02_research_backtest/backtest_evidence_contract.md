# Backtest Evidence Contract

来源主线：Advances in Financial Machine Learning + Trading and Exchanges + Active Portfolio Management。

## 目标

所有策略报告必须足够支持复查、复跑、拒绝或进入下一阶段。不能只交一条净值曲线。

## 报告必须包含

1. `strategy_id`
2. `research_question`
3. `economic_hypothesis`
4. `data_source`
5. `data_version`
6. `start_time` / `end_time`
7. `decision_time_rule`
8. `execution_time_rule`
9. `cost_model`
10. `slippage_model`
11. `params`
12. `params_hash`
13. `candidate_count`
14. `trial_count`
15. `selected_by`
16. `walk_forward_summary`
17. `regime_summary`
18. `parameter_stability_summary`
19. `cost_stress_summary`
20. `ledger_reconciliation`
21. `promotion_decision`

## 指标最低集合

- Total return
- Annualized return
- Annualized volatility
- Sharpe 或等价风险调整指标
- Max drawdown
- Turnover
- Average holding period
- Exposure ratio
- Number of bets, not only number of trades
- Fee paid
- Slippage paid or modeled
- Best year contribution share
- Worst year
- Capacity proxy

## Gate 语义

- `research_only`: 只能说明研究完成，不能 paper。
- `backtest_validated`: 只能说明回测证据达标，不能 live。
- `paper_candidate_ready`: 只能说明可以进入纸盘观察，不能 live。
- `paper_observing`: 纸盘积累中，不能 live。
- `live_candidate_review`: 需要人工审阅和风控签字。
- `live_enabled`: 必须显式人工批准，且默认关闭。

## 禁止自动晋级

以下情况不允许自动进入下一阶段：

- 只有 1 次回测或 1 条净值曲线。
- 样本外表现来自同一轮调参。
- 成本模型乐观且未做压力测试。
- 无 ledger 或 ledger 不能复原 PnL。
- 最大收益来自极少数交易或单一年份。
- paper 观察期不足。

