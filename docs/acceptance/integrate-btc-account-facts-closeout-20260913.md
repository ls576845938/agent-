# BTC 账户事实收口独立集成验收

- 票据：`INTEGRATE-BTC-ACCOUNT-FACTS-CLOSEOUT-20260913`
- 角色：`integrator`
- 变更风险：`demo_execution_semantics`
- 主基线：`0c9efaf51a95ed69bfb7f1180b4a6fbf22d85743`
- Producer 最终交付：`e76449c7a0c2355a7b604b07e76e1b56478b3e18`
- Producer 最终 handoff：`62cc702ff44809b05b6b7dc861bc8b5a0b1bb925`
- 集成分支：`agent/integrator/integrate-btc-account-facts-closeout-20260913`
- 工作树：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-account-facts-closeout-20260913`
- 结论：账户事实源码与 BTC 固定行为矩阵独立审定；专属 sparse worktree 下的后端冷启动断言仍有 1 项已定位的 Git 拓扑基线差异，因此不声明 `228 passed`。最终发布必须先在 registered main 重跑完整 228 项。

## 交付与边界

接收的最终树仅包含已批准的 BTC 账户回撤事实、runtime UOW，Demo runtime 对账、Guardian 显式单位与对应测试，以及两个 append-only producer handoff 事件。旧 `ff6bae6e0` 事件保留为历史，最终 `e76449c7a` 事件显式 supersede 它。

集成者只额外使用现有脚本刷新 `frontend/public/frontend-identity.json`，使其登记当前前端对象库存；未改页面、schema、launcher 或 guard。账户事实改动不改默认 BTC 信号、仓位、退出、T2 risk kernel、OMS 生命周期、保护单或账本经济语义。

## 独立审查与修订

初始 producer 交付 `ff6bae6e0` 被独立审查拒收，原因为：

1. `commit_ledger_uow` 只在 payload 事实非空时校验 `state_after`。限定 probe 证实 state-only 事实会被接受，恢复后 `account_risk_facts` 存在且 `blockers=()`。
2. snapshot hash 不包含采集时间，原 resolver 只校验账户与 snapshot hash，旧 fact 可附着到经济内容相同的新鲜观测。
3. 原 UOW key 仅使用 `run_id + snapshot_hash`，修复时间绑定后，正常的“相同经济内容、不同观测时刻”会与旧 key 冲突。

最终交付已在同一 producer 票据内完成最小修订：UOW payload/state 双向精确等值；Guardian 使用 `obs.observed_at_utc` 绑定 fact 观测时间；UOW identity 同时包含经济 snapshot hash 与观测时刻。同一观测重试仍幂等，新观测可单独落账，fills/bills 仍按自身 ID 去重。

## 交接验证

- `handoff.py validate`：最终 published event `valid`。
- 祖先：基线是最终 deliverable 祖先；`e76449c7a^ = f80f5d4f4`；`62cc702ff^ = e76449c7a`。
- 哈希：最终 envelope 列出的 11 个 deliverable 均从 Git object 重算 SHA-256，`11/11 match`。
- 范围：最终 producer tree 仅有 11 个已批准交付路径和历史 published event；修订提交仅 8 个审定路径；无冲突。
- `git diff --check`：通过。

## 测试

### 通过

- BTC 固定矩阵：原 8 个文件 153 项 + 账户事实 23 项，全部通过。完整合并命令的总输出为 `227 passed, 1 failed in 34.23s`，唯一失败属下述 sparse Git 拓扑差异。
- 独立限定测试：双向 payload/state 负例、旧 fact 加新观测负例、连续相同经济 poll/重试/去重正例、原子 funding UOW，`4 passed in 3.44s`。
- `node frontend/scripts/check-frontend-identity.mjs`：通过，`manifest_match=true`、`baseline_ancestor=true`、安全开关全部 false；sparse 分支上 `canonical=false` 为预期。

### 未通过与发布前置

- 固定 228 矩阵结果：`227 passed, 1 failed`。
- 唯一失败：`backend/tests/test_backend_research_readonly.py::test_cold_readonly_app_creation_avoids_runtime_and_external_side_effects`。
- 精确原因：专属 sparse worktree 的 `.git` 是指针文件；测试先全局将 `Path.open` 替换为副作用 rejector，然后 `create_app -> default_shared_data_root -> main_repository_root -> resolve_git_dirs` 需读取该 `.git` 指针，因而被 rejector 阻断。
- 归因证据：`base..integration` 对 `backend/**`、`tools/agent_governance/git_metadata.py` 和 `tools/agent_governance/shared_data.py` 都是零 diff；同一后端 52 项在 registered main 基线已有 `52 passed`记录。
- 处理：未跳过、修改或伪造测试，未扩大 touch set。只允许生成 `quality_checked` integrated event；主会话必须在 registered main 合入后先重跑完整 228 项，全通过才能启动新服务或发布 artifact。
- `node frontend/scripts/test-frontend-identity.mjs`：集成前的 failure-first 跑到 canonical-main 断言时失败，原因是 registered main 尚未包含本票据 identity 刷新。这一项同样保留为合入后 current-main 验收前置，不在历史 worktree 启动页面。

## Dirty、artifact 与运行事实

- Planner 创建时所有声明路径 clean；只有本票据已提交修改；无冲突，未覆盖其他代理 dirty。
- 未创建或修改 runtime artifact。目标外部 root `D:/vibe coding/Obsidian/量化系统/runtime-artifacts/btc-account-facts-closeout-20260913` 当前不存在，未从 2026-08-29 旧 root 复制证据。
- 未启动前后端，未访问网络、secret、private/order/live endpoint，未执行真实 Demo 账户对账。

## 治理证据与仍阻塞项

- 已读：`AGENTS.md`、`docs/knowledge/README.md`、不可妥协规则、`shared_pitfalls.md`、`integrator.toml`、`cross_agent_coordination.md`、`delivery_risk_policy.json`，以及风险、OMS、监控回放和架构边界 playbook。
- Active pitfall IDs：`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-HANDOFF-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,MONITOR-AUDIT-001,QSYS-BOUNDARY-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001`。
- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 仍 blocked/fail-closed：真实账户审定基线不存在；账户级充提/划转完整性未证明；`max_drawdown_unit` 未显式审定；真实 Demo 对账未执行；`btc_runtime_artifact_root_env_missing`。
- 安全旗标：`promotion_evidence_ready=false`；paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、demo_control 全部保持 false。

本集成事件仅表示“已审定源码树可供主会话限定合入”，不构成 promotion、Demo、paper 或 live 权限。
