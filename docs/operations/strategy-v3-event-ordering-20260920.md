# BTC V3 离线边界事件排序：限定源码验收

日期：2026-09-20。票据：`BTC-V3-EVENT-ORDERING-20260920`。

## 身份、范围与结论

本票据仅修正离线成交、行情观察及下一决策的处理顺序，`change_risk=demo_execution_semantics`。基线为上一轮独立拒绝报告提交 `9dad24a4a9467a126a8692737409f776db4bd69f`；首版源码为 `1b56263c8a5a5e1503395812acf7c4b736fe2fa4`，同票独审发现受控中断窗口后，最终源码修订为 `8a17c18143916a4b8b8f35d62d024feca9f0ede2`，handoff-only HEAD 为 `0c555e20d9f4e42a1c8eb6d121dfae6fa3beea71`。注册 main 保持 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`，未合入或发布。可回到本票据基线重新建立候选，不覆盖旧证据。

**源码验证结论：限定排序及其受控中断恢复已通过业务复验，待独立审定报告封存。** 首版为 51 passed；最终矩阵如实记录为 51 passed / 1 次版本变更干扰失败，受干扰用例及 4 项关键用例随后在固定版本下独立复验为 5 passed。不得改写成“某一次最终完整矩阵 52/52 全绿”，更不得描述为 V3 正式发布完成。

工作树由 planner 创建：`agent/btc_developer/btc-v3-event-ordering-20260920`，sparse=true。初始限定路径 clean，无覆盖其他代理修改；`quant_us` 仅为依赖导入而只读展开。

唯一 touch set：

- `quant_crypto/application/qlib_offline_replay.py`：离线观察时间分配、持久顺序记录及决策证据关联。
- `tests/contracts/test_strategy_v3_event_ordering.py`：新增保护测试；复用不修改原 short 业务验收。
- `tests/fixtures/strategy_v3/offline_contract.json`：只增加版本化事件顺序，不改模型、策略、参数、价格、成本或单位。
- 本报告与 `.agent/handoffs/BTC-V3-EVENT-ORDERING-20260920/**`：源码交付证据。

## 根因与固定语义

原模拟器在下单时将成交处理时间推进 1ms；上一笔成交确认和下一小时新行情原先被压在同一处理时刻。62500 与 66000 两个 mark 导出不同权益，却宣称相同观察时间，使权威账户事实明确返回 `observation_timestamp_conflict / risk_eligible=false`。账本对齐不能代替账户事实有效。

本轮不改权威回撤合同，也不关闭 `_assert_ledger` 的 `risk_eligible` 校验。冻结 `qlib_offline_event_order_v1`：

> 上一笔模拟成交及账本确认 → 本次可见行情观察 → 本次决策 → 按既有规则等待后续成交。

原始行情、forecast、有效期及资金费源时间不动；单独记录 `source_decision_time_utc` 与 `observation_processing_time_utc`。例如边界 02:00:00，前笔成交仍在 02:00:00.001，本次行情观察在 02:00:00.002。这仅是显式模拟处理顺序，不宣称历史数据真的有毫秒精度。

新观察不早于其源时间且严格晚于上次处理时间。只接受既有边界最多 2ms 的偏移；更早事件拒绝，不把陈旧数据任意平移成当前。每个决策持久记录一次观察时槽，准确绑定原 event ID 和顺序合同摘要。恢复复用原槽；同一源边界换身份、已超出原槽的恢复、合同篡改均拒绝。时钟推进仍使用原维护事实及真实模拟 CAA 回执流程，不补造 ACK、健康状态或延长过期阈值。

非零 fixture 决策证据引用同一持久时槽；已封存真实候选的零风险拒绝批处理保持原路径，不把 22 个物理批次扩成 1392 次完整账户维护。

独审另以 fault injection 证明：slot 已提交但 market 尚未应用时中断，恢复会先用旧 mark 在新时槽对账，随后新 mark 再次造成同刻权益冲突。原 51 项与独立 17 项绿测均未覆盖它，不能忽略。最终修订仅在 `execute` 的恢复分支增加 20 行：先验证已经封存的 input_binding/event_id，严格复用该 event 的持久时槽，还原其可见 market 和幂等 funding，然后才调用原 `_resume_after_verified_recovery`。原账户、账本、ACK/过期和 Guardian 校验原样执行；不重分配时槽、不补造健康状态、不重放订单。新增回归要求非零 short 在此中断后按原规则完成退出，slots 完全相同、重复 execute 结果相同、总计两单两成交归零且 `risk_eligible=true`。

## 验证记录

统一 Python 为注册主版 `.venv/Scripts/python.exe`，从本票据工作树运行，`-B -m pytest -q -p no:cacheprovider --tb=short`。测试禁止网络与训练。

1. Failure-first：新文件最初 7 项全部失败（缺顺序函数、持久时槽和合同），8.32s。
2. 定向修复：当时的新文件 7 项加原 `test_explicit_short_fixture_uses_same_policy_and_original_hard_exit`：**8 passed / 90.95s**。策略、价格、原业务断言未修改。
3. 提交态固定矩阵：**51 passed / 592.83s，exit=0**。完整 `tests/contracts/test_strategy_v3_qlib_offline.py`、`tests/contracts/test_strategy_v3_unified_closeout.py`、`tests/contracts/test_strategy_v3_event_ordering.py`、`tests/integrations/test_qlib_candidate_policy.py`；`tests/integrations/test_qlib_frozen_inference.py` 的 V2 两项 `test_full_sealed_feature_raw_and_calibrated_prediction_parity`、`test_v2_never_returns_execution_objects`；`tests/contracts/test_strategy_v1_donchian_offline.py` 的 V1 四项 `test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable`、`test_restart_preserves_persisted_tripped_guardian_latch`、`test_ledger_committed_before_evidence_is_recovered_without_resubmit`、`test_intent_persisted_before_post_remains_unknown_and_never_blind_retries`；`tests/integrations/test_no_live_side_effects.py` 的一项 `test_qlib_adapter_sources_never_emit_paper_or_live_ready_states`。命令使用上述统一 Python/pytest 参数，追加 `--basetemp C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-matrix-1b56263c8`；指定单项以 `文件路径::用例名` 传入。
4. 新增的账户事实证据测试直接调用原 short 验收，同时检验各次严格账本检查的 `risk_eligible=true`，以及 .001 成交和 .002 行情观察确实进入同一版本的决策证据。
5. 固定 CLI 首次及同目录重跑均 exit=0：`python -B -m quant_crypto.application.qlib_offline_replay --state-dir C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-cli-1b56263c8`。两次均为 1392 条决策、1392 条逻辑事件、22 个物理拒绝批次、0 批准、0 成交。两次 `candidate_policy_evidence.jsonl` SHA-256 均为 `060076991c3434691a966a43b5555e76e927cb29812a6910693d5fb4b6754909`，精确 source identity 绑定 `1b56263c8a5a5e1503395812acf7c4b736fe2fa4`，十项 permissions 全 false。不以真实候选零成交替代非零业务验收。

矩阵临时账本目录：`C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-matrix-1b56263c8`。这是本源码提交的隔离模拟证据，不是 current-main artifact 或真实账户账本。测试输出与后续独立结果分别记录，不混合计数。

### 同票恢复修订的单独证据

- 新增 `test_interrupted_slot_restores_bound_market_before_account_reconciliation`：修复前 **1 failed /54.85s**，实际错误为严格账本断言拒绝；修复后 **1 passed /106.78s**。这是受控异常及正常关闭后重启，不宣称覆盖任意 OS 硬崩溃。
- 最终完整矩阵增加这一项，共 52 项，**51 passed / 1 failed /708.67s**。命令沿用上一节精确矩阵，仅 basetemp 改为 `C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-matrix-8a17c1814`。启动时 HEAD=8a17c1814，执行中生产方提交 handoff-only 0c555e20d，污染了 `test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart`。traceback 原因为 dispatcher 的 `btc_demo_dispatch_source_head_mismatch`，经 CAA 续期传播成 `qlib_offline_maintenance_ack_failed`，不是本次事件排序或账本数值失败。这是主会话验证流程失误，不是允许放松代码身份的理由；最终业务/测试 blobs 通过 `git diff --exit-code 8a17c1814 0c555e20d --` 三项源码/测试/合同逐一确认不变。该轮结果照实保留。
- 独立 integrator 在自己的树冻结 HEAD=`0c555e20d9f4e42a1c8eb6d121dfae6fa3beea71`，独立复验 **5 passed /370.60s**：上述受污染的原 nonzero 跨重启用例、新增 slot→market 受控中断恢复、两项过期 ACK 拒绝以及截断 batch fail-closed。由此关闭该唯一验证干扰；不再为改进汇总数字重复整轮矩阵，不修改任何预期或身份校验。独审原首版 17 passed 与另行 fault injection 失败是历史记录，不能混成最终版本计数。
- 最终 CLI 使用 `C:/Users/李烁18353780778/AppData/Local/Temp/qs-v3-order-cli-final-0c555e20d`，首次和重复运行均 exit=0，1392/22/0批准/0成交，十项权限均 false。两次证据 SHA-256 同为 `c1322f5d56dd4a3f5bba242e2789d573d489b44210ce6e017968c5d639c99741`。CLI 运行与账本身份绑定 `0c555e20d9f4e42a1c8eb6d121dfae6fa3beea71`，其业务/测试对象与 `8a17c18143916a4b8b8f35d62d024feca9f0ede2` 精确相同。

## 安全边界与停止点

未改共享 schema、生产策略/风控/Guardian/OMS/保护/账本、费用或仓位算法、治理、前端、服务、权限；未读取 secret，未调用账户、网络或交易所。历史研究证据未改写。

`runtime_observed=false`、`execution_permission=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`。本轮源码审查不会自动授权 main merge、后台重启、页面发布或任何交易阶段；交付策略中重启要求属于后续获授权部署，本轮不部署。

未验收：任意 OS 硬崩溃、真实账户与交易所、服务/API/UI、Demo/paper/live。冻结候选无成交是其原结论，不是策略有效性证明。独立 integrator 审查通过才可称本票据源码验收通过；不自动启动后续阶段。若出现范围外确定性缺陷，只报告断点，不续开新票据。

预检读取：quant-agent-preflight、quant-gate-evidence-review、quant-agent-handoff；AGENTS、knowledge README、non-negotiables、shared/BTC developer pitfalls、delivery risk policy；架构边界、execution microstructure、backtest evidence、audit trail、forecast-to-portfolio 规则。当前 packet active IDs：`BACKTEST-COST-001`、`BTC-NONFLAT-001`、`BTC-OMS-001`、`BTC-PERP-001`、`BTC-WS-001`、`DATA-BTC-FINAL-001`、`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-LEDGER-001`、`QSYS-SECURITY-001`、`REPLAY-ISOLATION-001`、`RESEARCH-HOLDOUT-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。未另行展开旧事故日志。
