# Agent Workflow Pitfall Log

本文件记录代理治理、Codex 配置、上下文和多代理协作事故。它是追加式历史事实源，不是每个任务的全文必读文件；当前有效规则由 `pitfall_catalog.json` 选择。

## 2026-07-10 外层 workspace 启动不会自动加载内层项目配置

- 场景：Codex 任务从 `D:\vibe coding\Obsidian\量化系统` 启动，而真实 Git 仓库和 `.codex/agents/` 位于 `agent-`。
- 风险：任务只加载外层 bootstrap；在会话中执行 `cd agent-` 不会重建启动时的 instruction/config chain，导致角色、hooks 和并发限制未生效。
- 处理：量化任务必须直接以 `agent-` 为 workspace/CWD 新建；外层 `AGENTS.md` 只保留引导，不复制项目角色规则。
- 验证：`tests/agent_governance/test_governance_contract.py::test_outer_workspace_is_only_a_bootstrap`。

## 2026-07-10 每轮全文读取原始踩坑日志造成上下文污染

- 场景：BTC 原始日志已有 122 条、约 189 KB，美股日志已有 37 条、约 38 KB，旧规则要求每个相关任务全部重读。
- 风险：稳定规则、历史状态、旧命令和大量测试输出同时进入主上下文，真正的任务边界被淹没；日志越认真维护，代理越可能在后期忽略它。
- 处理：保留原始日志作为追加式事故历史；建立带 ID、roles、scopes、status、source、regression test 的 active catalog；任务只注入匹配规则并按 source 定向读取原始条目。
- 验证：`tests/agent_governance/test_context_packet.py` 和 `test_pitfall_catalog_is_traceable`。

## 2026-07-10 全局 Ultra 与并行写代理会放大共享 worktree 冲突

- 场景：全局使用 GPT-5.6 Sol Ultra，旧项目配置允许五个线程，旧 Phase F.5 prompt 同时启动多个 workspace-write agent。
- 风险：每个顶层任务都可能再派生写代理，导致同一代码、SQLite、latest artifact 和 Git index 被并发修改；仅靠“不要改同一文件”的提示不能提供隔离。
- 处理：项目默认 `high`、`max_threads=3`、`max_depth=1`；架构师/研究员只读；写代理不得派生写子代理，并使用独立 worktree。
- 验证：`tests/agent_governance/test_governance_contract.py::test_project_config_bounds_parallelism_and_enables_hooks` 和 `test_writer_worktree_plan_stays_under_dedicated_parent`。

## 2026-07-10 AGENTS 不应混入模型参数、Sprint 矩阵和当前系统状态

- 场景：仓库 `AGENTS.md` 同时包含美股单系统目标、旧 3/5 agent 矩阵、reasoning 表、Phase 优先级和“Frontend is good enough”等动态判断。
- 风险：业务推进后这些内容静默过期，并与 `.codex/agents/*.toml` 的真实运行配置形成两个控制面。
- 处理：`AGENTS.md` 只保留稳定授权、量化硬规则、启动路由、多代理边界和交付合同；模型/effort/sandbox 放入 agent TOML，当前状态放入 current-HEAD artifacts。
- 验证：`tests/agent_governance/test_governance_contract.py::test_agents_contract_is_stable_and_not_status_driven`。

## 2026-07-21 全量 Git diff 与 LFS clean filter 写爆仓库盘

- 场景：完整 worktree 展开了历史 LFS artifacts；Codex 后台对长任务基线执行全量 diff，普通 `git status --porcelain` 也触发 LFS clean filter，把工作文件重复写入 `.git/lfs/tmp`。
- 风险：单轮 diff 可生成数十 GB 临时文件，挤满 D 盘；数据采集、artifact 重建和 Git 操作随后出现半写入、超时或不新鲜证据。`GIT_LFS_SKIP_SMUDGE` 只能阻止 checkout 下载，不能替代 sparse checkout 或停止 clean filter 扫描。
- 处理：writer worktree 默认 sparse 且排除 `data/`、`artifacts/`、`mlruns/`；repo-local LFS 使用 skip-smudge；主运行 SQLite 移到仓库外单写者 staging 并从 Git 索引移除；低于 50 GB 禁止完整 worktree，低于 20 GB 停止采集和 artifact 重建；自动化禁止执行全仓 dirty 扫描。
- 验证：`tests/agent_governance/test_disk_guard.py`、`tests/agent_governance/test_hooks.py::test_pre_tool_guard_enforces_disk_watermarks_and_runtime_db_boundary`，以及 BTC automation low-disk receipt。

## 2026-07-28 常驻角色使用 Codex-managed worktree 导致 C 盘膨胀和跨盘审批

- 场景：六个常驻角色任务以 Worktree 环境启动，Codex 将托管工作树创建在默认 `$CODEX_HOME/worktrees`；写代理随后又按仓库规则在 D 盘创建票据 worktree。
- 风险：同一角色同时存在 C 盘任务工作树和 D 盘票据工作树，重复占用空间；原任务的 `workspace-write` 根不覆盖 D 盘票据 worktree，数据师和 BTC 程序员在正常读写、测试或提交时反复请求批准；角色任务仍绑定创建时的旧 sandbox，配置更新不会热生效。
- 处理：常驻角色任务统一从 `agent-` 项目以 Local 环境启动，只作为调度和票据入口；写代理不得修改注册主工作树，具体票据继续由 `worktree_plan.py` 在 D 盘同级 `worktrees/` 创建 sparse worktree。项目启用 `approval_policy = "never"` 和 `danger-full-access` 消除跨盘机械审批，各角色规则继续限制 touch set、secret、private/order/live、破坏性操作和 promotion gate。
- 验证：`tests/agent_governance/test_governance_contract.py::test_project_config_bounds_parallelism_and_enables_hooks`、`test_agents_contract_is_stable_and_not_status_driven` 和 `test_only_canonical_agent_profiles_are_active`；旧任务归档后，从当前 main 重建六个 Local 常驻角色任务并核验其 CWD 和权限快照。

## 2026-07-29 运行 blocker 被错误升级为无限工程票据

- 场景：运行/观察链路已经有 current-HEAD 持久入口、单写者、fail-closed 和可恢复状态，但 Team Context 对缺少 category 的 blocker 默认标成 engineering；clock/W32/NTP、网络/TLS/DNS/10054、自然观察覆盖和人工审批问题因此反复生成代码修复、handoff、集成或 gate 重建建议。目标从长期窗口调整为短期 milestone 后，旧 blocker inventory 仍继续驱动当前工作。
- 风险：环境波动和自然时间被误当成代码缺陷，显式修复请求不断扩展 producer/integration 票据；旧 artifact 被误述为满足新目标；工程吞吐被循环重建消耗，并可能在“快路径”名义下侵蚀 security、risk、OMS、ledger、private/order/live 与 fail-closed 边界。
- 处理：active user objective / current milestone 作为工作选择边界，完整 blocker inventory 只保留为风险清单。分类缺失时从 code/owner 区分 runtime_clock、runtime_network、natural_time、manual_approval、data_steward、integrator、engineering 和 unclassified；非工程 runtime 只恢复环境、继续既有重试或等待且冻结代码，未知 blocker 先分类并等待用户范围。只有 current-HEAD deterministic/reproducible code defect、现有入口无法表达目标或用户明确授权新范围时才开最小工程票据；每个显式修复请求默认最多一个 producer ticket 与一个 integration ticket。
- 验证：`tests/agent_governance/test_team_context.py` 覆盖 clock/network/natural-time/manual-approval/明确 dependency/unknown blocker；`tests/agent_governance/test_governance_contract.py` 与 `tests/agent_governance/cases/agent_workflow_cases.json` 固化目标边界、熔断和 architect runtime-operation 规则选择。
