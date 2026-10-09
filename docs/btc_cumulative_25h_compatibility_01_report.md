# BTC-CUMULATIVE-25H-COMPATIBILITY-01 证据报告

## Result

本票据不重新累计 25 小时。基于现有 OKX Demo 自然运行 receipts、hash-chain events、checkpoint/state 与 ledger/reconciliation snapshot，完成了仓库外 append-only immutable 归档和逐段 current-HEAD Git blob 复核。

- 归档 receipt：25 条，全部 `counts_toward_25_hour_window=true`、`fixture=false`、`backfilled=false`，receipt payload hash 与前序 receipt 链均通过；首/末 receipt hash 分别为 `70cc7096342fd9f5f35637d6bc9ff0a85478f1e5ff05a4d6d7091b5431b4ce4d` / `ae4caecdbdd584ea003929d1653f6b3841b473c2d11d91fc2c08c984a7bc8c94`。
- 累计小时与严格连续小时分开：累计 qualifying=25；跨时间范围存在 10 个缺口；最大严格连续=14；`strict_consecutive_25h=false`，不可声称严格连续 25 小时。
- 跨 HEAD：24 小时兼容、1 小时 conditional。第 1 段的 `okx_demo_paper_runtime.py` 包含从 lifecycle 与 committed ledger UOW 恢复 client-order identity 的执行语义差异，且该段实际有执行相关事件；保留为 conditional，不靠 JSON、fixture、caller path、allowlist 或重新等待自然小时闭合。
- 最终状态：`blocked_fail_closed`，decision=`compatibility_unproven_keep_observation_blocker`。本报告不是 promotion unlock，也没有重建 gate/read-model。

## Architecture and evidence lineage

读取路径为：真实 Temp runtime source → 归档 `source_snapshots/`（字节级复制）→ 25 个按 receipt hash 命名的 canonical receipt 文件 → 独立 verification envelope → manifest。归档目录只允许新目录创建，目标存在即失败；没有覆盖旧目录、latest pointer 或仓库内运行数据库。

权威归档（本票据）为：

`D:\vibe coding\Obsidian\量化系统\immutable-evidence\btc-demo-observation-compatibility\btc-cumulative-25h-compatibility-01-160a482-20260808T112140Z-verified`

- owner marker：根目录 `.quant_btc_evidence_owner.json`，SHA-256=`843151021c5cdc1e5d6576eba5d7db599034b379951f088fbc92ff12c17db076`，`immutable_archives_only=true`。
- `manifest.json` SHA-256=`288894e6f97a5bd0b9be83be85f40a421c352b31f3411c3e62873dd758be5a04`。
- `verification.json` SHA-256=`262b405a64de7e53766b167232f7479b41bc4e98420536dfc1c2b3f849a495d4`；独立重读校验结果 `pass`。
- source path：`C:\Users\LOCAL_USER\AppData\Local\Temp\quant-system\btc_demo_paper_runtime\observation\hourly_observation_receipts.jsonl`、同一 runtime root 下的 `events.jsonl`、`state.json`；三份 source snapshot 与归档字节一致。
- strategy/data/runtime identity：`btc_long_short_donchian_top5_okx_native@1.0.0` / `okx_public_candles_1h_v1` / `okx_demo_paper_runtime_v1`。

### Receipt/event/ledger identity

- receipt ledger 文件 SHA-256=`80b9835e40fe2bc50606488301f1db3f4ff1b008a45331dcbbc3d109568b9ee5`；canonical receipt-list payload SHA-256=`ddbb04994921af202862a0ed68b703591f0f516dd03abfc474f591e1c75da06`。
- event log 文件 SHA-256=`d11fee0834f9fab84672804661b35656ed4af913e77b585558b6d3c9729f064a`；198 个 event，sequence 1..198 连续，末 event hash=`eadc10f3597881bad36742ea61001d7553b1d4cb2e687f238b40f93faa61af44`。
- state 文件 SHA-256=`327d03f26c836d55be9016d015ff69b9b81bc737294fadef908e70bf8994d5b0`；checkpoint hash=`ae302bc02bc4cefad23eecce17f95444d20582c5947bdbe0bb6fd2f591e440ea`，checkpoint 与 event 链末端一致。
- final-flat state canonical SHA-256=`52270413d747a1cf59ceee89804f8fa6b1de341e9875e111e82f36ee50b14105`。
- reconciliation snapshot：`status=reconciled`，orders=2、fills=2、positions=0、pending orders=0、funding bills=1，exchange snapshot match=true，`promotion_evidence_ready=false`，`fixture=false`。exchange snapshot SHA-256=`7e8318c4f3df06b4f6a4d4a95856c027ee7c974ca4233d3106b3d93d5688622f`。

### Cross-HEAD proof

以 base/current HEAD `160a4820377260cfa1118c0f2e8ae90c7a3533da` 为目标，逐段从 receipts 实际 `source_head` 分组；每段均通过 `git merge-base --is-ancestor`，并对 12 个执行语义相关 protected paths 逐一比较 source/current Git blob SHA-1。结论不是由 receipt 自报字段单独推出：

| 段 | source HEAD | receipt 数 | blob/语义事实 | 结论 |
|---|---|---:|---|---|
| 1 | `d3f1e3f7f770bfdf35336257cf1eaecc18f3d6b6` | 1 | `okx_demo_paper_runtime.py` blob 不同；实际 diff 含 recovered client-order identity + ledger UOW 交集，窗口有 4 events | conditional；需 `response_loss_clordid_disambiguation`、`full_reconnect_ledger_stable_projection`、`oco_identity_stable`、`ledger_hash_projection_stable` 等 current-head P0 drill |
| 2 | `30b3613aa0d4774ba74cc0995e176b0ff02eee63` | 13 | 仅 runtime observation projection/cumulative counter 增量；无 recovered order identity；窗口 28 events | compatible（13） |
| 3 | `52781090f6430d0cc8cf5a880ea36b95d5f64bd5` | 1 | 同为只读 observation projection 增量；窗口 16 events，含 ledger/reconciliation 类型 | compatible（1） |
| 4 | `1097efa82c86164310c31c709764052091ade196` | 10 | 12 个 protected blobs 全相同；窗口 38 events | compatible（10） |

因此 compatibility cumulative=24，conditional=1；阻塞项为：

- `segment_1:execution_semantics_diff:clordid_or_ledger_recovery`
- `segment_1:execution_semantics_diff_reachable_in_observation_segment`
- `segment_1:fault_drill_remediation:fault_drill_pack_missing`
- `compatibility_cumulative_observation_below_25`

## Files changed and interfaces

本 worktree 未修改 BTC runtime、OMS、strategy、ledger、gate、backend、frontend 或 shared schema；没有生产接口变更。唯一仓库 deliverable 是本报告，描述 external artifact 与复核边界；external immutable artifact 不进入 Git。append-only handoff 另存于 `.agent/handoffs/BTC-CUMULATIVE-25H-COMPATIBILITY-01/`，仅引用本报告 commit。

Touch set：

- `docs/btc_cumulative_25h_compatibility_01_report.md`：证据报告与复核结果。
- `.agent/handoffs/BTC-CUMULATIVE-25H-COMPATIBILITY-01/`：发布后 handoff envelope；不改历史 handoff。

## Safety behavior

本任务只读真实本地证据并复制到 external root；没有启动/停止 Demo、网络请求、OKX private/order/live/transfer/withdraw endpoint、真实订单或 secret 读取。归档与 handoff 保持：`network_used=false`、`secret_read=false`、`private_endpoint_allowed=false`、`order_endpoint_allowed=false`、`paper_allowed=false`、`live_allowed=false`、`withdraw_allowed=false`、`promotion_allowed=false`、`runtime_latest_pointer_updated=false`。`data/paper_ledger/paper_runtime_audit.jsonl` 未修改。

## Tests and validation

- `quant-agent-preflight`：通过；`context_packet` catalog hash=`127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。
- planner：指定 task-id 目录已存在，保留旧 worktree 后使用独立 sparse task-id `btc-cumulative-25h-compatibility-01-current`；HEAD/base 均为 `160a4820377260cfa1118c0f2e8ae90c7a3533da`，初始 dirty paths=none。
- `safe_status.py`（`quant_crypto`、`tools`、`tests`、`.agent/handoffs`）：clean。
- 独立 archive validator：`pass`；manifest self-hash、owner marker、逐文件 SHA-256、25 条 receipt、198 条 event chain、checkpoint、reconciliation、cross-HEAD blobs 全部复核通过。
- `py -3 -m pytest -q tests/contracts/test_btc_demo_observation_accumulator.py --basetemp D:\vibe coding\Obsidian\量化系统\test-artifacts\btc-cumulative-25h-compatibility-01-1121`：14 passed。
- `py -3 -m pytest -q tests/contracts/test_btc_okx_demo_paper_runtime.py --basetemp D:\vibe coding\Obsidian\量化系统\test-artifacts\btc-cumulative-25h-compatibility-01-1121-runtime`：198 passed。

未运行/不属于本票据：Demo 重启或自然时间等待、五项 current-head P0 fault drill、backend/frontend/browser acceptance、promotion/read-model rebuild、paper/live、任何 broker/exchange endpoint。

## Integration notes and risks

- base commit=`160a4820377260cfa1118c0f2e8ae90c7a3533da`；deliverable branch=`agent/btc_developer/btc-cumulative-25h-compatibility-01-current`；worktree=`D:\vibe coding\Obsidian\量化系统\worktrees\btc_developer-btc-cumulative-25h-compatibility-01-current`。不合并、不 push、不修改 registered main。
- planner 原 task-id 的旧目录与旧 commit 未作为本轮交付消费；Team Context 中发现的旧 handoff 也未消费。外部 root 中本票据权威目录是 `...112140Z-verified`；同 root 的早期 create-only draft 不在本 handoff 引用范围。
- `change_risk=promotion_evidence` 的交付合同要求 independent integrator、current-HEAD gate/read-model rebuild 和 backend restart；本票据没有获得这些条件，故保持 gate blocked/fail-closed。
- 最大风险是第 1 段执行语义等价尚未被 current-head P0 drill 闭合，以及严格连续小时只有 14；不得将“累计 25”描述为“连续 25”或 ready。

读取的 playbook/规则：`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/btc_developer_pitfalls.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`.codex/agents/btc-developer.toml`、`quant-agent-preflight`、`quant-agent-handoff`。命中 pitfall IDs：`BTC-NONFLAT-001`、`BTC-OMS-001`、`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-ARTIFACT-001`、`QSYS-GATE-001`、`QSYS-LEDGER-001`、`REPLAY-ISOLATION-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

所有 blocked/fail-closed gate：compatibility cumulative 未达到 25（24+1 conditional）、strict consecutive 25h、promotion evidence、paper/live unlock、private/order/live permission、latest artifact/read-model freshness。上述安全 flags 全部保持 false。
