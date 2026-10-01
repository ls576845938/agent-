# BTC 原策略离线安全收口验收（2026-09-13）

## 结论

本票完成两项限定安全修复，并以同一次合成工程决策验证：持有多仓 → 默认注册策略仍输出 LONG → 既有 drawdown stop 将目标降为 0 → 实际 T2/T3 形成减仓计划 → 内存 `BTCPaperOMS` 模拟成交 → fills、funding、fees、cash、position 和 PnL 账本一致回放。

这不是默认策略从历史开仓到退出的完整收益回测，也不是交易所、Demo、paper 或 live 运行证据。初始仓位、成本价、回撤、行情与成交均为 `fixture=true / engineering_only=true`；11 节点 DAG 是验收测试内组装的可追溯记录，不是生产运行自动发布的 artifact。

## 变更边界

- `quant_crypto/application/btc_demo_production_composition.py`
  - T2 对 long/short 都只投影 `slTriggerPx`；short 仍以 BUY 平仓，但保护触发价取入场价上方的止损，不再把下方止盈当止损。
- `quant_crypto/application/runtime_risk_guardian.py`
  - 配置 `max_drawdown` 时，缺失、NaN 或无穷回撤事实统一产生 `drawdown_unknown` 并 fail-closed；显式合法 `0` 仍是已知事实。
- 合同测试
  - 新增 short/long 止损映射、未知回撤与显式 0、同一次默认策略决策到模拟 OMS/账本的工程验收。
  - M1 历史冻结改为绑定已审定提交 `c1d11987d28f06bb0fe89b2c289e88d07522790d`，只允许上述两个源码文件的精确 blob 差异；默认 candidate 与 params hash 断言保持不变。

未修改默认 BTC 信号公式、候选、参数、仓位规则、退出阈值、T2 风险宪法、OMS 生命周期、ledger 计算或权限合同。

## 失败优先证据

修复前新增的 6 项定向断言结果：`4 failed, 2 passed in 4.56s`。

- short T2 投影得到止盈 `588.0`，预期止损 `606.0`；long 原映射正确。
- `drawdown=None / NaN / Inf` 被错误放行；显式 `0` 原语义正确。

应用最小业务修复后，同一 6 项断言：`6 passed in 5.71s`。

组合与 Guardian 两个完整合同文件随后出现 1 项既有 opening fixture 失败，因为合成账本没有给出回撤事实。只在测试 helper 中加入默认的显式合成 `drawdown=0.0`；生产代码、生产快照和生产账本没有补 0。复测：`58 passed in 6.90s`。

## 同一决策工程闭环

入口：`tests/contracts/test_btc_offline_strategy_safety_acceptance.py`。

1. 从 `btc_strategy_registry` 获取 `long_short_donchian_top5_okx_native`，实际调用注册的 `spec.signal_callable(frame, "1h")`。
2. 5,200 根合成完成 1h K 线完成 4h/日线暖机并触发真实 Donchian LONG；不是手造方向后冒充策略输出。
3. 由同一 signal 生成 forecast；质量字段使用中性、单样本工程 fixture，只为通过既有合同，不表示预测有效性。
4. 同一 forecast 在显式 `current_drawdown_pct=10%`、阈值 `5%` 下产生 target=0、`risk_drawdown_stop`、`order_generation_allowed=false`。
5. 同一 signal/target/intent 进入 `BtcDemoProductionComposition`；实际 T2 assessment 批准风险减少，T3 形成全平 reduction plan。Guardian latch 仍为 `latch_persistence_missing`，所有 execution permission 继续为 false。
6. `BTCPaperOMS.mark_risk_checked` 消费的是上一步真实 `bundle.risk_assessment.approved`，不是 replay row 中的布尔自证。随后仅在内存中模拟 submitted、accepted、filled、reconciled，未调用传输层。
7. 交易数量严格换算：`0.01 contracts × 0.01 BTC/contract = 0.0001 BTC`。账本回放得到：
   - exit fee：`0.003 USDT`；
   - price PnL：`0.1 USDT`；
   - funding PnL：`-0.000595 USDT`；
   - total fee PnL：`-0.00595 USDT`；
   - total PnL / flat cash：`0.093455 USDT`；
   - 最终 BTC 仓位：`0`，且 `cash + position_value = total_pnl`。
8. 验收内组装 data → feature → signal → forecast → target → risk → order → fill → ledger → pnl → report 的 11 节点 DAG；同一 run、strategy、data、decision、signal、forecast、target、risk、order、fill 标识可追溯，`validate() == []`。

第 7 步调用的是现有 `quant_crypto.backtest.funding_ledger.replay_perpetual_fill_position_cash_ledger` 离线重算。它没有调用 `runtime_store.commit_ledger_uow`，因此没有验收持久化、原子提交、崩溃恢复或交易所对账；第 8 步的手工验收 DAG 也不代表生产整链已自动打通。

## 回归结果

基线（主会话在修复前、main `bce2bdca83506413fcced3028b78e07fce19fbd3` 独立执行）：7 个既有合同文件 `146 passed in 16.70s`。该基线没有覆盖两项疑点，不能作为已修证明。

本票最终限定矩阵：

```text
python -B -m pytest -q -p no:cacheprovider \
  tests/contracts/test_btc_demo_production_composition.py \
  tests/contracts/test_btc_shared_platform_v3_guardian_latch.py \
  tests/contracts/test_btc_shared_platform_v3_risk_kernel.py \
  tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py \
  tests/contracts/test_btc_shared_platform_v3_oms_delegation.py \
  tests/contracts/test_btc_okx_demo_runtime_hardening.py \
  tests/contracts/test_m1_btc_behavior_freeze.py \
  tests/contracts/test_btc_offline_strategy_safety_acceptance.py
```

最终复测结果：`153 passed in 31.87s`（此前同矩阵一次为 `31.39s`）。

未运行全仓测试、前后端服务、浏览器、网络、OKX 私有接口、订单接口或真实 Demo/paper/live。未读取 secret。

## 仍然阻断与安全旗标

- 当前生产 `OkxDemoPaperRuntime` 未核验到权威 drawdown 输出；composition 只会从 ledger 的 `drawdown` 或 account 的 `drawdown` 消费现成事实。配置回撤上限而来源缺失时，现在会 `drawdown_unknown` 阻断新增风险。
- 本票没有为生产来源制造 `0`，也没有新增回撤事实接线。若后续需要开启新增风险，应由独立票据定义基于 fills/positions/cash/equity 历史的权威回撤口径、持久化与重放合同。
- 已验证的风险减仓路径仍可构造 reduction bundle；Guardian/latch 绝不因此授予执行权限。
- 没有消费 M1 趋势环境特征，也没有改变默认策略决策。
- `research_only=true`；`fixture=true`；`engineering_only=true`；`promotion_evidence_ready=false`；`paper_enabled=false`；`live_enabled=false`；`execution_permission=false`。
- `change_risk=demo_execution_semantics`，必须由独立 integrator 复核并集成；本 producer 不修改 main、不启动服务、不解锁 M3/M4。

## 治理证据

- base：`bce2bdca83506413fcced3028b78e07fce19fbd3`
- worktree：planner 创建的 sparse worktree；`core.sparseCheckout=true`
- 初始 touch set 状态：7 个声明路径均 clean；未覆盖或回滚其他代理文件。
- playbook：`AGENTS.md`、知识入口与不可协商规则、共享与 BTC developer pitfalls、delivery risk policy，以及研究、组合风险、执行 OMS、监控回放、加密市场结构与交易安全相关知识目录。
- active pitfall IDs：`BACKTEST-COST-001`、`BTC-NONFLAT-001`、`BTC-OMS-001`、`BTC-PERP-001`、`BTC-WS-001`、`DATA-BTC-FINAL-001`、`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-LEDGER-001`、`QSYS-SECURITY-001`、`REPLAY-ISOLATION-001`、`RESEARCH-HOLDOUT-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- 没有消费外部 artifact/manifest/ledger 文件；工程账本与 DAG 仅存在于测试内存，不能宣称 current-HEAD promotion freshness。
