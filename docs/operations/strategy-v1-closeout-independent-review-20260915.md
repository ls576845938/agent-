# V1 单策略离线闭环独立终验

## 结论

**不通过，停止在技术验收阶段。**

producer 已完成固定五阶段序列，但独立终验确定复现两个直接阻断：

1. 离线回放仍受 dispatcher 内部墙上时钟的新鲜度判断影响，不能使用一个真正固定、可跨时间重放的 observation clock。
2. 更严重的是，重启后的适配层会将已持久的 `FROZEN_UNKNOWN` / `write_path_trusted=false` / private-WS disconnected 重写为 `RUNNING` / connected，并在反向平仓后成功新开 `-0.01 contracts` 空仓。

第二项说明当前离线 fixture 能在恢复路径覆盖权威风险阻断；因此不能以底层 fail-closed 回归或五阶段绿色结果代替外层闭环验收。

本轮按冻结停止条件结束：不让 producer 继续修补，不修改 M1 白名单，不进入页面、发布、Demo、paper 或 live。

## 候选身份与边界

- approved main base：`b920d131e41ecbfe7f76f0709affbe22c8b35f5e`
- 集中验收基线：`69ef575f709609f36f754f86040822bc6eeca1c6`
- producer source：`b0defd454919b5eb319ba23d331a226fc822619f`
- producer handoff HEAD：`cdc657ab4016d43ccf7a864702f0cbafa915cb5e`
- producer handoff：`.agent/handoffs/STRATEGY-V1-CLOSEOUT-20260915/published-strategy-v1-closeout-20260915-b0defd454.json`
- change risk：`demo_execution_semantics`
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

producer handoff 对提交态 Git 对象的校验结果为 `[]`；source 是冻结基线后继。实际变更只有：

- `quant_crypto/application/donchian_offline_replay.py`
- `quant_shared/strategy_runtime/decision_envelope.py`
- `tests/contracts/test_strategy_v1_donchian_offline.py`
- `tests/fixtures/strategy_v1/offline_contract.json`
- `docs/architecture/strategy-admission-v1.md`

独立集成 cherry-pick 无冲突，未覆盖其他代理修改。

## 通过的范围

独立环境运行：

```text
py -3 -B -m pytest tests/contracts/test_strategy_v1_donchian_offline.py -p no:cacheprovider --basetemp C:/tmp/v1-closeout-independent-20260915 -q
6 passed in 77.92s
```

该结果证明：

- 固定工程 fixture 在当前时刻可完成 open long -> hold -> reversal close -> restart/same-bar open short -> exit flat。
- 四笔模拟成交、两次 OCO cancel 后最终归零；每笔 fee `-0.003 USDT`，总 fee `-0.012 USDT`，初始 `5000` 重算为 `4999.988 USDT`。
- OHLCV 只用于信号，成交价固定 `60000 USDT`；这是模拟执行假设，不是历史收益。
- funding `1 bp` 是风险成本输入；该场景没有 funding cash event，实际资金费现金流为 `0`。
- ledger 已提交、evidence 未写入的断点可从 exact input anchor 后的 lifecycle/UOW 补证，不重单。
- order intent 已持久而 post 未知时保持 `submit_pending` 并拒绝 blind retry。这仅证明 fail-closed/no-duplicate，不证明能自动恢复继续交易。

## 独立复现的阻断

### 1. 真正固定的 observation clock 不可重放

输入：固定 `decision_time_utc=2026-09-15T00:00:00Z`，固定连续 OHLCV 的 `open_long` 前缀，新的临时 state directory。

结果：

```text
ERROR OkxDemoPaperRuntimeError
okx_demo_execution_boundary_dispatch_failed:
btc_demo_dispatch_projection_blocked:
btc_exchange_exchange_status_not_ok:unknown,
btc_exchange_public_ws_status_not_connected:unknown,
btc_exchange_rest_status_not_ok:unknown,
btc_broker_truth_not_fresh,
btc_account_identity_not_verified
```

原因是 `BTCDemoExecutionDispatcher.dispatch()` 仍直接使用 `utc_now()` 计算 30/120 秒新鲜度，而 producer 测试 fixture 使用 `datetime.now(timezone.utc)` 捕获当前时刻。因此它是「当前时刻可运行的工程 fixture」，不是「使用已封存时钟可跨时间重现」。

### 2. 持久风险阻断在重启后被改写，并开出新风险

独立诊断步骤：

1. 完成 open long -> hold -> reversal close，当时仓位 `0.00`、submit `2`。
2. 在持久 runtime state 中明确写入 `risk_control.mode=FROZEN_UNKNOWN`、`write_path_trusted=false`、private-WS disconnected/reconciling。
3. 重启同一 run/state，恢复结果仍显示 `FROZEN_UNKNOWN` 与 private-WS `connected=false`。
4. 再处理同一 `reverse_to_short` 前缀。

实际输出：

```text
CLOSED reversal_close 0.00 2
BEFORE FROZEN_UNKNOWN False
RESULT reversal_open -0.01 3 RUNNING True
```

`_resume_after_verified_recovery()` 通过 `_set_explicit_offline_runtime_facts(active=True)` 重写风险和 private-WS 事实；新 runner 还重新创建未 trip 的 `InMemoryGuardianLatchStore`。这不是一个单纯的显示缺口，而是会影响离线执行证据强度的新风险恢复语义缺口。

## M1 精确冻结

独立复跑：

```text
py -3 -B -m pytest tests/contracts/test_m1_btc_behavior_freeze.py::test_m1_history_stays_frozen_with_only_reviewed_post_m1_safety_fixes -p no:cacheprovider --basetemp C:/tmp/v1-closeout-m1-independent-20260915 -q
1 failed in 5.09s
```

失败为新保护路径未进入 M1 精确 blob 登记。由于本次整体技术验收未通过，独立审查**不批准**更新该登记；历史 base、测试和白名单原样保留。

## 未独立重跑项

- producer 报告的 V0/BTC 兼容子集 `219 passed` 已读取，但在独立终验确定实质阻断后未重跑。
- 部分成交、拒单、一般 cancel-response-loss 和 conflicting-fill 的新纵向场景未运行；保留为已知覆盖限制，不自动开工程票。
- 前端、服务启动、只读页面、Demo、paper、private/order/live 和 promotion 均未运行。

## 下一步限定方向（未开票、未自动执行）

如果架构师后续单独批准修复，范围应仅限：

1. 为 dispatcher 新鲜度判定提供默认仍为 `utc_now()` 的可注入时钟，离线候选显式绑定封存 observation clock；默认 Demo 语义不变。影响路径预计为 `quant_crypto/runtime/control_plane.py`、离线 adapter 及其限定测试。
2. 禁止恢复路径无条件重写持久风险/WS/Guardian 阻断；只有全新 fixture bootstrap 可注入健康事实，恢复必须保留或经独立权威证据解除阻断。影响路径预计为离线 adapter、持久 latch/facts 接线及 V1 固定测试。

修复后仍必须使用本次已冻结的业务序列、成本、身份、故障点和停止规则重新审查；不得因本报告自动开启新修复轮次。

## 安全与 gate

- 未修改策略、参数、成本、Guardian、风控阈值、OMS、账本、启动器、前端或权限。
- 未读 secret/账户，未访问网络、broker/exchange、private/order/live endpoint，未提交真实订单。
- `quality_checked` 切片不是 promotion evidence。promotion、Demo、paper、live、private、order、real order、transfer、withdraw 及 `runtime_observed` 均保持 `false`。
- 技术验收未通过，因此不允许生成 source-review passed receipt，不允许进入只读页面或正式发布。

## 预检记录

- 角色：`integrator`；工作树由 planner 从指定 base 创建，`sparseCheckout=true`。
- 所有声明路径初始 `safe_status=clean`。
- 已读：`AGENTS.md`、`docs/knowledge/README.md`、`quant_system_non_negotiables.md`、`shared_pitfalls.md`、`domain_architecture_rules.md`、integrator profile，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review` 技能。
- active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
