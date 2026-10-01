# V3 统一离线收口：有界候选与阻断报告

日期：2026-09-16。风险：`demo_execution_semantics`。票据 base：`95b0ab4c406f6d85e83d1bcb21b618d129015fd5`。本页描述的是独立 sparse 工作树内的**源码候选**，不是 `main` 当前功能、独立验收或发布。

## 业务验收结论

| 冻结结论 | 当前证据 | 判定 |
| --- | --- | --- |
| 封存 Qlib 1,392 条进入共同入口 | `QlibFixtureOfflineReplay.execute` 调用计数 1,392；每条经原 `evaluate_candidate_step`，0 批准/0 模拟成交；最多 64 条无金融副作用的拒绝提交到原 runtime store，22 条物理批次事件，逐条输入/退出状态/hash/批次序号可关联 | 局部通过；不证明 Alpha 有效或可交易 |
| 显式 fixture 正负仓与退出、成本/资金费/现金/仓位 | 原测试曾分别覆盖 long/short/退出和经济重算；本候选更新了 mark/成交价分离，尚未取得更新后全部绿的测试矩阵 | 未验收 |
| 重复、恢复和 exact ledger/fill 证据 | 写前失败重跑及尾部截断拒绝测试通过；ledger 已提交而投影中断可恢复 exact fill id 的定向测试通过。连续 long→hold→重启→反向先平用例仍失败 | **阻断** |
| 时间、身份、hash、质量、缺事实/ACK、unknown-intent | 封存输入按已核验 V2/档案版本与本行 hash 绑定；V3 adapter 对 store 的恢复 blocker 明确拒绝。跨小时重启后 dead-man ACK 过旧，当前保持 `qlib_offline_maintenance_expired`，没有放宽 TTL、风险模式或权限 | 安全失败，功能未过 |

最终断点：同一快照重启时重复提交 ledger UOW 产生的幂等冲突，已由 V3 adapter 对“已提交、精确同 hash 且原风险事实仍合格”的快照执行只读复用避免；其后连续用例仍在下一小时推进入口遇 `qlib_offline_maintenance_expired`。持久状态里的 dead-man `last_ack_utc` 停在旧时刻。不能直接写 ACK/heartbeat，不能改原 30 秒超时或回撤同刻约束来凑通过；本轮依预定停止规则封存 blocked 候选，不连锁扩大修复。

## 代码边界

- `quant_crypto/application/qlib_offline_replay.py`：封存来源进入既有 `execute`；仅无订单/无账变的拒绝按有界批次留在既有 fsync runtime 日志；重启拒绝 store blocker；exact ledger/fill 关联与政策状态投影恢复；离线维护通过原 dispatcher/模拟 ACK，成交价与 mark 分开；固定只读候选 CLI。
- `tests/contracts/test_strategy_v3_unified_closeout.py` 与原 V3 合同测试：准入计数、批次写前恢复/截断失败、dead-man 过期、安全恢复定向测试。
- `tests/fixtures/strategy_v3/offline_contract.json`：如实将同账户反向重开标为 lot 不可表示的预期拒绝；单独列 short/hard-exit 覆盖。不改策略、模型、成本、lot 或原历史研究证据。
- `docs/architecture/strategy-admission-v3.md`：明确当前 blocked 状态与批次语义。

未改 production controller、dispatcher、Risk、Guardian、OMS、store/schema、策略算法、模型、前端、权限或治理。没有连接交易所/账户；所有订单均为隔离模拟 venue。`event+1h` 决策、`event+2h` delayed OPEN 与每边 5 bps fee、6 bps 价格摩擦保留；没有用未来 OPEN 生成决策输入。

## 测试与未完成项

使用注册主工作树 `.venv` Python，在本票据 worktree 执行：

```text
python -m pytest -q tests/contracts/test_strategy_v3_qlib_offline.py tests/contracts/test_strategy_v3_unified_closeout.py --junitxml <system-temp>/v3-unified-closeout-20260916.xml
20 passed, 1 failed, 388.42 s
```

唯一失败为连续 fixture 重启反向平仓，第一轮是同刻 mark/成交价混用导致回撤 `observation_timestamp_conflict`。修正两者分离后的单项重验仍失败（55.70 s）：`btc_runtime_idempotency_conflict`。对精确已提交快照作有条件只读复用后的单项重验仍失败（54.02 s）：`qlib_offline_maintenance_expired`。因此 **20 passed 是更早代码状态，不能与后两次失败拼成最终 21 passed**；最终源码未取得完整绿矩阵。

其他定向结果：封存 1,392 条共用 `execute` 与 22 物理批次事件 `1 passed / 20.47 s`；写前批次失败后重跑和截断拒绝两项定向测试分别通过；旧 ledger→policy 投影中断 exact fill-id 测试曾 `1 passed / 7.51 s`。它们只证明各自局部合同。OS 任意硬崩溃、批准 sealed 候选后缺秒级行情的真实运行、Demo/paper/live、跨市场与正式页面均未测试。批次日志是单条 fsync 事件；截断时 store 返回 blocker、adapter 现在拒绝，不宣称无条件原子或自动修复。

## 固定入口与限制

源码中有以下仅针对已封存 V3 候选的离线/只读入口，**CLI 尚未作为完整工作流单独验收，不应作为可用版运行建议**：

```powershell
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -m quant_crypto.application.qlib_offline_replay --state-dir '<worktree 外、独立的状态目录>'
```

命令结束即停止；同目录重跑尝试恢复并核查绑定，`policy_evidence_path` 是只读报告，`runtime/events.jsonl` 才是持久决策事实。当前候选因上述 dead-man 缺口**不作为“可用 V3”交付**；执行时遇任一失败必须停，不手工改状态或清坏尾。状态目录应按策略/数据/版本隔离，不可放在 Git checkout 下。CLI 不提供任意模型、真实账户、Demo 或交易模式。

## 治理与发布状态

- 技术修复：**部分完成、有阻断**。
- 本地测试：**局部通过，完整矩阵失败**。
- 独立验收：**未开始/不得通过**。上游 handoff 曾经 validate，但本次候选尚须独立集成；Team Context 曾返回 `handoff_discovery_timeout`，主会话后来观察到发现入口恢复可用，最终仍以交付时核验为准。
- 正式发布、main 合入、服务重启、页面：**未做**。
- Gate：`research_only`/`blocked`/`fail_closed`；`execution_permission=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`runtime_observed=false`。

本票据没有通过最终业务验收。下一步只能由主会话决定是否单独授权针对重启后模拟维护 ACK/时序合同的最小修复；不得从这份局部证据自动开启 Demo、V4 或任何交易权限。

## Preflight 与来源

读取 `.agents/skills/quant-agent-preflight/SKILL.md`、`.agents/skills/quant-agent-handoff/SKILL.md`、`AGENTS.md`、`docs/knowledge/README.md`、非协商规则、shared 与 BTC developer playbook、风险交付政策及相应 BTC 架构/执行边界。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。本轮沿用上游已核验、提交态 V3 handoff，未读取其他代理 dirty。初始本票据 touch set 全 clean，未覆盖他人修改；`quant_us` 仅通过 sparse read-only 展开以便测试导入。
