# BTC 离线安全修复独立集成验收（2026-09-13）

## 结论

独立集成票据 `INTEGRATE-BTC-OFFLINE-SAFETY-20260913` 已验证并集成唯一获批 handoff set：
`published-btc-offline-safety-closeout-20260913-eae602f3e`。两项业务变化保持为生产者提交中的最小差异：

1. long/short 的 T2 保护投影统一消费 `slTriggerPx`，short 不再把 `tpTriggerPx` 当作止损；
2. 配置 `max_drawdown` 时，缺失或非有限回撤事实产生 `drawdown_unknown`，显式有限 `0` 仍为合法事实。

独立限定矩阵为 `153 passed in 7.80s`。结论只达到 `quality_checked` 的源码集成证据；不构成 Demo、paper、live、promotion、持久账本、崩溃恢复或交易所对账证据。

## 身份、交接与哈希

- change risk：`demo_execution_semantics`
- integration base：`bce2bdca83506413fcced3028b78e07fce19fbd3`
- producer business/test commit：`804831ab1e6e7d9badd9df8eb5893447eda6fb1a`
- producer deliverable commit：`eae602f3edda9f1e986451ca024d58d5d5459de9`
- producer handoff commit：`f5ea8d3b1ba087e8ad99647a0384470faa5f1c77`
- producer envelope：`.agent/handoffs/BTC-OFFLINE-SAFETY-CLOSEOUT-20260913/published-btc-offline-safety-closeout-20260913-eae602f3e.json`
- integration branch：`agent/integrator/integrate-btc-offline-safety-20260913`
- planner worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-offline-safety-20260913`
- pre-report integration HEAD：`3f958004437b0732858f2710811eff64c4075602`

`handoff.py validate` 返回 `valid`；base 是 producer deliverable 的祖先，producer handoff 的父提交是该 deliverable。envelope 中 7 个 deliverable 的 Git blob 原始字节 SHA-256 全部匹配。Windows checkout 的 CRLF 工作树字节与 Git blob 字节不同，因此以 envelope 所绑定的 Git blob 原始字节为交接哈希口径；不存在提交对象漂移。

## 独立审查与职责边界

获批业务 touch set 只有：

- `quant_crypto/application/btc_demo_production_composition.py`
- `quant_crypto/application/runtime_risk_guardian.py`
- `tests/contracts/test_btc_demo_production_composition.py`
- `tests/contracts/test_btc_shared_platform_v3_guardian_latch.py`
- `tests/contracts/test_btc_offline_strategy_safety_acceptance.py`
- `tests/contracts/test_m1_btc_behavior_freeze.py`
- `docs/acceptance/btc-offline-safety-closeout-20260913.md`

集成附加范围只有原 producer envelope、本报告与 `.agent/handoffs/INTEGRATE-BTC-OFFLINE-SAFETY-20260913/` 下的 append-only integrated 事件。

独立源码审查确认：

- 没有修改默认 BTC 策略公式、candidate、params、仓位规则、退出阈值、T2 风险宪法、OMS 生命周期、ledger 算法或交易权限合同；
- M1 冻结测试仍绑定已审定 M1 基线，只允许两个安全修复源码的精确 blob；candidate 与 params hash 断言保留；
- 新离线闭环测试实际调用注册策略的 `signal_callable`，但行情、初始仓位、回撤、成交和审计 DAG 都明确为合成工程 fixture；
- 风险减少 bundle 可被构造不代表执行授权；`execution_permission=false`、`authority_verified=false` 与 `latch_persistence_missing` 保持；
- 离线 funding ledger 重算没有调用 `runtime_store.commit_ledger_uow`，未验证持久化、原子提交、崩溃恢复或交易所对账。

## Dirty、冲突与测试

注册主工作树与 planner 集成工作树的全部声明路径在集成前均为 clean。`core.sparseCheckout=true`。没有覆盖、清理或回滚其他工作树内容；两个 producer 提交顺序 cherry-pick 无冲突。原 published envelope 作为已验证的提交态输入被保留。

独立执行：

```text
D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider \
  tests/contracts/test_btc_demo_production_composition.py \
  tests/contracts/test_btc_shared_platform_v3_guardian_latch.py \
  tests/contracts/test_btc_shared_platform_v3_risk_kernel.py \
  tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py \
  tests/contracts/test_btc_shared_platform_v3_oms_delegation.py \
  tests/contracts/test_btc_okx_demo_runtime_hardening.py \
  tests/contracts/test_m1_btc_behavior_freeze.py \
  tests/contracts/test_btc_offline_strategy_safety_acceptance.py
```

结果：`153 passed in 7.80s`。`git diff --check base..integration` 通过。

未运行：全仓测试、前端、浏览器、网络、OKX private/order/live、真实 Demo/paper/live、持久账本恢复和交易所对账。未读取 secret。

## 发布档位与仍然阻断

交付策略为 `demo_execution_semantics`，机器合同要求 `backend_restart_required=true`，并把后端证据档位命名为 `demo_quasi_live`。当前用户授权同时要求交易控制保持关闭；官方启动器的 `demo_quasi_live` 档位要求启用 Demo control，因此本集成不启动该档位，也不声称其运行验收通过。

主会话可在合入后使用 `research_readonly`、`demo_control=false` 做限制性加载与 current-main 身份检查；这只能证明只读加载隔离，不能替代 `demo_quasi_live` 执行语义证据。完整 `demo_execution_semantics` 运行发布验收继续阻断，直到另有明确授权和满足对应安全前置条件。

生产 `OkxDemoPaperRuntime` 尚无已核验的权威 drawdown 事实来源。合入后，在配置回撤上限且事实缺失时，新增风险将以 `drawdown_unknown` fail-closed；本票没有制造 `0`，也没有新增事实接线。

以下保持为 false：`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`、`demo_control_enabled`。M3、M4 不启动。

## 治理证据

- 已读：`AGENTS.md`、`docs/knowledge/README.md`、non-negotiables、shared pitfalls、integrator TOML、cross-agent coordination、delivery risk policy、domain architecture 与 replay engine，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review`。
- 仓库不存在独立 `integrator_pitfalls.md`；按既有合同使用 integrator TOML 与 cross-agent coordination，未全文读取原始事故日志。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- 没有生产 artifact、manifest、ledger 或 replay 产物；fixture 证据不能作为 current-HEAD promotion evidence。

## 下一执行动作

主会话只需验证本集成最终提交和 integrated envelope，创建指向 `bce2bdca83506413fcced3028b78e07fce19fbd3` 的回退引用，再按已授权范围发布到 registered main。合入后只允许 `research_readonly` 限制性重启和身份验收；不得据此开放 Demo control 或任何交易权限。
