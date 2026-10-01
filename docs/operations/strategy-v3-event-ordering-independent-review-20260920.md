# BTC V3 事件顺序：独立源码审查

日期：2026-09-20。票据：`BTC-V3-EVENT-ORDERING-INTEGRATION-20260920`。`change_risk=demo_execution_semantics`。

## 结论与边界

**限定源码候选验收通过（`quality_checked`），不是 V3 正式发布或交易准入。** 独审确认：原 short 固定参数与价格、权威账户事实和账本校验未放宽；前笔成交 `.001`、下次可见行情 `.002` 的处理时槽有版本化、持久化和精确决策关联；时槽已提交但尚未写入行情的可控中断可以恢复同一已绑定行情，再经过原恢复、ACK、Guardian、账本和 `risk_eligible` 校验。无重复时槽或重复成交。源行情、forecast、成本、策略和生产执行链未改。

此结论只接收同一 producer 票据的最终提交集；没有合入注册 main、重启服务、发布页面、访问账户或执行交易。注册 main 仍为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`。独审工作树为 planner 创建的 sparse `agent/integrator/btc-v3-event-ordering-integration-20260920`，本票据基线 `40bd976814c3fc4478efd0e9d85b037e72f91c72`；上轮被拒绝的开发基线为 `9dad24a4a9467a126a8692737409f776db4bd69f`。最终业务源码提交 `8a17c18143916a4b8b8f35d62d024feca9f0ede2`，最终 producer 报告提交 `6c13319ecf4d7035f234d30f24a6154562c63eba`，交接 HEAD `e6b65d55dcbfae66c924576dc07ce20dfe52eab7`。三者的 adapter、事件测试和离线合同 Git blob 完全一致。

## 提交态与改动审查

- 最终 `published-btc-v3-event-ordering-final-20260920-6c13319ec` 交接经过 `handoff.py validate`，状态 `valid`；Git 祖先、原始对象 SHA-256、schema、依赖、`quality_checked` 和安全旗标均核对。它 supersede 同票的临时恢复交接；早期 `73770b0bc` 的测试成绩只适用于早期源码。
- 最终净触点仅 `quant_crypto/application/qlib_offline_replay.py`、`tests/contracts/test_strategy_v3_event_ordering.py`、`tests/fixtures/strategy_v3/offline_contract.json` 及 producer 报告/append-only 交接。`_assert_ledger` 的 `risk_eligible` 必须为 true、原时间/身份和账户事实拒绝逻辑、原 ACK/Guardian 校验均保留。没有改生产策略、Risk、Guardian、OMS、保护单、账本、模型、参数、价格或成本。
- 新合同只把模拟**处理顺序**与源时间分开：源时间不变，前笔成交之后安排有界观察时槽；超过既定 2ms 旧边界拒绝，不能无限平移陈旧数据。同事件复用已持久化的时槽，换事件 ID、源边界或合同摘要拒绝。恢复分支只在已绑定 event 的时槽存在时恢复该可见 market 和幂等 funding，随后仍走原权威恢复校验；这不是补造健康、CAA ACK 或成交。
- 初始与每次 fast-forward 前限定 `safe_status` 均 `clean`，无重叠 dirty 或冲突；没有覆盖其他代理文件。独审仅快进本分支的已验证生产提交，并写本报告及本票据交接。

## 独立验证与已知限制

使用注册主版 `.venv/Scripts/python.exe`，导入来源确认为本独审工作树，测试没有网络或训练。初版提交 `40bd976814c3fc4478efd0e9d85b037e72f91c72` 的事件文件与 9 项恢复/过期 ACK/批次/lease 安全选择器：**17 passed / 149.94s**。这不是修订版通过数。

独立故障注入曾在初版复现真实缺口：short 开仓后第二决策持久化 `.002` 时槽，但在 `set_market` 前中断；重启执行原 66000 mark 的 hard exit，返回 `qlib_fixture_ledger_not_current`，账户事实 `risk_eligible=false`、`observation_timestamp_conflict`。当时 submit/fill 均仍为 1，说明安全拒绝有效，但不能称恢复完成。该复现状态位于隔离临时目录 `qs-v3-slot-interrupt-2z13ntiv`，不是运行账本。

修订提交经同票交接和对象 hash 核准后，独审树在固定 HEAD `0c555e20d9f4e42a1c8eb6d121dfae6fa3beea71` 运行：

```text
<canonical .venv python> -B -m pytest -q -p no:cacheprovider --tb=short \
  --basetemp C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-integrator-20260920-revised \
  tests/contracts/test_strategy_v3_event_ordering.py::test_interrupted_slot_restores_bound_market_before_account_reconciliation \
  tests/contracts/test_strategy_v3_qlib_offline.py::test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart \
  tests/contracts/test_strategy_v3_unified_closeout.py::test_clean_stop_with_expired_ack_cannot_resume_as_healthy \
  tests/contracts/test_strategy_v3_unified_closeout.py::test_expired_dead_man_cannot_become_fresh_by_offline_clock_write \
  tests/contracts/test_strategy_v3_unified_closeout.py::test_torn_sealed_batch_stays_fail_closed
```

结果 **5 passed / 370.60s**，包括先前未覆盖的同一中断窗口、原非零跨重启业务用例及负向安全用例。修订后的新增测试还要求时槽不增加、重复调用结果一致、原 short 最终 2 单/2 成交/归零且 `risk_eligible=true`。

生产方最终 52 项矩阵为 **51 passed / 1 failed / 708.67s**，不可写成 52/52。唯一失败用例在运行中被 handoff-only HEAD 从 `8a17c1814` 改为 `0c555e20d`，原 dispatcher 按源 HEAD 身份拒绝 CAA 续期，报 `btc_demo_dispatch_source_head_mismatch` → `maintenance_ack_failed`；业务 blobs 未变。该用例已由上述固定 HEAD 独立重跑通过。生产方 CLI 在 `0c555e20d` 首次及同目录重跑均 1392 逻辑决策、22 物理批次、0 批准、0 成交，证据 SHA-256 相同；这是生产方隔离证据，独审未重复 CLI。没有重新运行完整 52 项固定 HEAD 矩阵，也未验收 OS 硬崩溃、服务/API/UI、真实账户或交易所。不能以分段结果冒充一轮 52/52，也不能用 fixture 成交证明封存 Qlib 候选有效。

## 预检、交接与下一门槛

读取 `AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role config、delivery risk policy、三个仓库技能 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`。context packet catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`，未需展开旧事故日志。Team Context 可用；最终交接另行显式验证，不以发现结果替代验证。

本票无新 artifact/manifest/运行账本发布；隔离测试和 CLI 产物不属于 current-main promotion evidence。`runtime_observed=false`、`execution_permission=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`。研究候选仍为零批准、零成交；真实可用性和有效性均未被证明。后续若需主版发布、服务重启及页面验收，必须另行审定交付；源码独审不自动开 Demo 或 M3–M4。
