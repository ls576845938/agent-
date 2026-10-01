# BTC V3 离线恢复与锁生命周期：独立验收

日期：2026-09-20。独审结论：`partial_blocked`，拒绝将本候选认定为 V3 完成或可用版。局部恢复/安全测试通过，冻结的 short 硬退出业务链仍失败。本轮按已定停止规则结束，不在集成工作树修改业务或测试源码。

## 审查对象

- 风险类别 `demo_execution_semantics`；审查差异基线 `d5ccd75f510a0205a657054f6bee9ebe87131679`。生产者源码及报告提交 `0c7317ce879667f1ebbc15e8afb5f14a6ee99125`，handoff-only 提交及**实际测试源码 HEAD** `50c03234cb8d2d87105fbccfd99e72b7f23b8b01`。它们都不是当前主版。
- 使用 planner 创建独立 sparse worktree：`agent/integrator/btc-v3-recovery-lifecycle-integration-20260920`；`core.sparseCheckout=true`。最终源码相对审查基线只改变 `quant_crypto/application/qlib_offline_replay.py`、`tests/contracts/test_strategy_v3_unified_closeout.py`，并新增生产者报告。生产者的中间 `0699b6d52` 放宽断言已撤回：最终两份源码/测试文件的 Git blob 均与严格版本 `b68338694224ad87f615b3860b4d118c7cac503d` 一致。
- 生产者交接 `.agent/handoffs/BTC-V3-RECOVERY-LIFECYCLE-20260920/published-btc-v3-recovery-lifecycle-partial-blocked-20260920-0c7317ce8.json` 在提交态验证为 `valid`；三项 deliverable 的 SHA-256 均以 `git show 0c7317ce8:<path>` 原始 Git 对象字节独立核对为 `match`。Python 使用注册主版 `.venv/Scripts/python.exe`，`qlib_offline_replay` 的导入来源是本独立 worktree。
- 本集成票仅写本独审报告与一条 append-only `rejected` handoff。触及的生产者文件、报告和本票输出路径在测试前限定 `safe_status` 均 clean；没有读取或覆盖其他代理的未提交文件。

## 独立最小矩阵

| 测试 | 本独审结果 | 结论 |
| --- | --- | --- |
| 原 `test_explicit_short_fixture_uses_same_policy_and_original_hard_exit` | `1 failed in 50.64s`，第二次决策在 `execute → _assert_ledger(decision_snapshot)` 抛 `qlib_fixture_ledger_not_current` | 冻结 short 硬退出业务链未通过，V3 不合格 |
| 新 V3 合同中 8 个选择器：批次写前异常重跑、截断尾阻断、过期 ACK 拒绝、恢复时钟、clean stop 过期拒绝、构造失败释放本实例 lease、真并发写者拒绝、close 失败释放 lease | `8 passed in 28.05s` | 仅这八个定向合同通过；不能替代上面的业务链 |

本轮独审总计 **8 passed、1 failed**。生产者此前在较早源码上的 `42 passed、1 failed` 是另一份矩阵，不与本独审计数合并。完整两份 V3 合同、candidate_policy、V1/V2/no-live 兼容、CLI 首跑/同状态目录恢复、OS 硬崩溃、服务/API/UI 与真实运行均**未在本独审运行**。两个独立临时目录分别为 `%LOCALAPPDATA%/Temp/v3-recovery-integrator-20260920-short` 和 `...-safety`。

两次命令执行前均设置 `MLFLOW_DISABLE_AGENT_HINT=1`；精确命令为：

```powershell
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-recovery-integrator-20260920-short" tests/contracts/test_strategy_v3_qlib_offline.py::test_explicit_short_fixture_uses_same_policy_and_original_hard_exit
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-recovery-integrator-20260920-safety" tests/contracts/test_strategy_v3_unified_closeout.py::test_sealed_batch_failure_before_append_can_resume_without_duplication tests/contracts/test_strategy_v3_unified_closeout.py::test_torn_sealed_batch_stays_fail_closed tests/contracts/test_strategy_v3_unified_closeout.py::test_expired_dead_man_cannot_become_fresh_by_offline_clock_write tests/contracts/test_strategy_v3_unified_closeout.py::test_restart_uses_last_observed_clock_without_rewriting_ack tests/contracts/test_strategy_v3_unified_closeout.py::test_clean_stop_with_expired_ack_cannot_resume_as_healthy tests/contracts/test_strategy_v3_unified_closeout.py::test_constructor_failure_releases_only_its_guardian_lease tests/contracts/test_strategy_v3_unified_closeout.py::test_genuine_concurrent_guardian_writer_remains_rejected tests/contracts/test_strategy_v3_unified_closeout.py::test_close_failure_releases_own_guardian_lease
```

## 阻断与安全边界

生产者的隔离诊断将 short 失败定位于同一 `2026-07-01T02:00:00.001Z`：前笔成交后 62500 mark 的账户快照，接着以 66000 mark 记录下一决策，导致 `account_risk_facts.status=unknown`、`risk_eligible=false` 和 `observation_timestamp_conflict`。本独审动态复现到严格 `_assert_ledger` 拒绝；上述具体 unknown 字段来自已提交生产者报告，并非本轮新增动态探针。

源码合同说明不能为通过 short 测试而删除风险事实断言。`account_risk_facts` 对同刻不同经济快照生成 unknown，未知也涵盖账户身份、现金流、时序等错误；共享 BTC composition 将该事实交给 Guardian，Guardian 对无法绑定的回撤返回 `drawdown_fact_unknown` 并 trip。OMS 对有严格证明的减仓存在单独规则，但不能把它当作 V3 适配层忽略 unknown 的许可。中间版本 `require_risk_eligible=False` 未进入最终源码。

下一步若决定处理，须先审定离线成交与下一决策的单调时点/可见输入合同，再另行限定修复与验收；本票不自动衍生下一轮。当前仍是 source-only `research_only / blocked / fail_closed`。注册主版仍为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`；未合入 main、发布、重启、变更页面或调用账户、交易所、网络、private/order/live 端点。没有产生 current-main 的 V3 artifact、manifest 或运行账本。`runtime_observed`、`execution_permission`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw` 维持 `false`。

本票据预检读取 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`、`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role contract 与交付风险政策；项目没有单独的 `integrator_pitfalls.md`。活动规则为 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`；catalog SHA-256 为 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。未定向读取历史事故全文、未修改共享 schema、生产权威链或依赖顺序。
