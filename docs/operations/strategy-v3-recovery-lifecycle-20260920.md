# BTC V3 离线恢复与资源生命周期：限定修复报告

日期：2026-09-20。结论：**partial_blocked**。两处原定适配层缺口有局部修复和定向证据，但 V3 连续业务仍有一个独立、确定性的账户事实阻断；不是可用版、晋级证据或发布许可。

## 身份、范围和回退

- `change_risk=demo_execution_semantics`；开发基线 `d5ccd75f510a0205a657054f6bee9ebe87131679`；注册主版核验时为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`。本票据源码最终提交 `505c6262f947217e58e1866121f3832c76fc1ba7`，不在 main；独立集成、发布、重启、Demo/paper/live 均未进行。
- 专属 planner sparse worktree：`agent/btc_developer/btc-v3-recovery-lifecycle-20260920`。`core.sparseCheckout=true`，初始限定 `safe_status` clean，未覆盖其他代理 dirty 文件。
- 本票据只改 `quant_crypto/application/qlib_offline_replay.py` 与 `tests/contracts/test_strategy_v3_unified_closeout.py`，新增本报告与 append-only handoff。策略、参数、成本、lot、冻结 fixture、共享 store、Guardian、Risk、OMS、生产 dispatcher/controller、治理及前端未改。
- 中间提交 `0699b6d52` 曾将决策快照断言的账户 `risk_eligible` 条件放宽；精确诊断发现其可能遮蔽 **unknown** 回撤事实后，已用非破坏性补丁撤回并提交 `505c6262f`。`git diff --exit-code b68338694 HEAD --` 两份业务/测试文件为零，最终对象与较早严格断言提交 `b68338694224ad87f615b3860b4d118c7cac503d` 完全相同；不以中间短测通过冒充最终安全验收。

## 本票据实际完成的局部修复

1. 离线 venue 从持久的市场观察时间和单独 `offline_clock_utc` 单调恢复，避免重启后将 `_now` 重置为首根决策前一秒。模拟维护仍经既有 dispatcher 与 cancel-all-after 模拟回执；恢复保留原持久 ACK，真正缺失、过期或失败的 ACK 继续拒绝，未直接改 ACK 或延长 TTL。明确的 fixture 决策时行情经原 collect/apply/commit 形成可审计快照，不能拿小时 K 线冒充秒级维护行情。
2. `evaluate_frozen_candidate` 异常、构造中途失败和 `close` 中途失败均释放**本实例实际取得**的 Guardian lease；保留原异常和原持久状态，不删锁、不修剪截断日志。真正并发写者仍被 `latch_concurrent_writer` 拒绝。
3. 为上述路径补 failure-first 保护测试；原连续 fixture 和批次异常恢复的定向测试通过。但这只说明局部路径得到修复，不改变下一节的端到端阻断。

## 提交态验证与终点

在 `b68338694` 的严格断言源码对象上，使用注册主版 `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --tb=short` 运行冻结矩阵：完整两份 V3 合同、`test_qlib_candidate_policy.py`、指定 V2 模型推理两项、指定 V1 离线恢复四项和 no-live 一项。JUnit：`%TEMP%\btc-v3-recovery-b68338694-matrix.xml`。**42 passed，1 failed，440.15s**；唯一失败是 `test_explicit_short_fixture_uses_same_policy_and_original_hard_exit`，第二次决策的严格 `_assert_ledger(decision_snapshot)` 拒绝 `qlib_fixture_ledger_not_current`。最终 `505c6262f` 的两份业务/测试对象与 `b68338694` 逐字节等同，故引用该次提交态矩阵，不把后续中断的重复矩阵算成结果。

单项定位：原连续开/持/重启用例 `1 passed / 157.42s`；批次写前失败恢复、截断尾拒绝与 close 异常释放 lease `3 passed / 27.30s`；新增恢复时钟、过期 ACK、构造失败、真并发四项由修复前 `3 failed, 1 passed` 转为 `4 passed / 10.26s`。这些是冻结源码前的定向结果，不与最终矩阵合算为新的通过率。

第 2 次 short 的离线诊断复现如下：前笔延迟开盘在 `2026-07-01T02:00:00Z`，模拟 submit 将 venue 推至 `02:00:00.001Z`，以 `62500` mark 已提交快照；下一决策的输入仍要求同一可见时刻以 `66000` mark 取新快照。账本 `status=reconciled`、snapshot SHA 匹配、资金费对账为真，但 `account_risk_facts.status=unknown`、`risk_eligible=false`、`blockers=[observation_timestamp_conflict]`、`external_cashflow_complete=false`、回撤值为空。这是**同刻不同权益的账户事实冲突**，不是普通亏损后的开仓资格下降。严格断言保留阻断，不能让后续 Risk/OMS 为未知事实兜底。

中间 `0699b6d52` 的 short 单项虽然曾 `1 passed / 87.79s`，它跳过了上述未知账户事实，不被接受；其后启动的重复完整矩阵已按安全审查立即中断，记为 `not_completed`，没有结果计数。完整 CLI 首次/同目录重跑也**未运行**：端到端业务既已确定阻断，不用 1392 行零成交掩盖失败。先前冻结候选 1392 条共同持久入口、22 个物理拒绝批次、零批准/零模拟成交的合同测试属于最终矩阵通过项，仍只代表研究候选被拒绝，不代表策略有效。

## 尚需独立决策的边界

解决同刻成交和下一决策的时间排序，需要另行审定冻结撮合时点／可见输入合同，或共享账户回撤事实如何表达同刻有序事件；均超出本票据 touch set。本轮不修改 fixture、把时间强行钳制到未来、补造健康状态，也不扩大生产合同。责任：架构师确定下一受限工程范围；独立 integrator 只能审查这个 **partial_blocked** 候选，不能集成为 V3 已通过。真实账户/交易所、OS 硬崩溃、服务/API/UI、固定 CLI 完整恢复、Demo/paper/live 均未验收。

本轮无外部数据、artifact、manifest 或运行账本发布；隔离测试临时状态不是 current-main 证据。`runtime_observed`、`execution_permission`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw` 均保持 `false`；未读取 secret，未访问网络、交易所、broker、private/order/live 端点。源码候选保持 `research_only / blocked / fail_closed`。

预检读取：`quant-agent-preflight`、`quant-agent-handoff`、`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、BTC developer pitfalls、delivery risk policy；当前适用 ID：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。catalog SHA-256：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。未定向加载旧事故全文。
