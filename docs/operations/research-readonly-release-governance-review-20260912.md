# 研究只读发布治理：独立审查与审定

状态：**通过独立治理审查**。本审定只确认治理合同达到 `quality_checked`，并允许后继全新 M1 生产者从本审定提交建立执行上下文；尚未合入 registered main，因而尚未全局生效，也不代表 M1 已发布。

## 身份、范围与工作树

- 角色：短生命周期 `integrator`；`change_risk=governance_control`。
- 注册 main/base：`c1d11987d28f06bb0fe89b2c289e88d07522790d`。
- 批准 producer branch：`agent/super_developer/research-readonly-release-governance-20260912`；deliverable=`bfa5966c9f6709e75f5fc197c1c42173a81221f4`；published final=`ab4813c8ef8fba92b8f677584a8878721079dcdf`。
- integration branch：`agent/integrator/research-release-gov-review-20260912`。用户指定的长 task id 被 planner 的 49 字符合同拒绝，未创建工作树；随后使用等义合规 slug 从精确 base 创建 planner sparse worktree。两次检查 `core.sparseCheckout=true` 后才执行 diff、合入和写入。
- 精确 touch set：producer 的 8 个治理文件、其 published envelope、本审查报告和本票据 append-only integrated event。未修改业务、服务、数据、策略、风控、OMS、账本、launcher、hook/trust 或运行 artifact。
- 初始限定 `safe_status.py`：上述 producer 路径、handoff 目录与审查报告路径全部 clean；未发现重叠 dirty 文件，未覆盖、回滚或清理其他代理改动。

## Handoff、提交与哈希

- `handoff.py validate` 对 Git commit archive 中的 `published-research-readonly-release-governance-20260912-bfa5966c9` 返回 `status=valid`。首次临时归档准备因 PowerShell `New-Item -LiteralPath` 参数不可用而未创建输入，validator 对缺失文件按预期 fail-closed；改用同一显式临时目录的受支持参数后验证通过，未消费 producer 未提交路径。
- base 是 producer final 的祖先，deliverable 是 producer final 的直接祖先；producer final 只比 deliverable 多 published envelope。main 在合入前后均保持 `c1d11987…`。
- 8 个 envelope deliverable 的 Git blob SHA-256 全部匹配，无 missing manifest/schema。integration 分支仅以 `git merge --ff-only ab4813c8…` 接收批准集合，无冲突。
- catalog 规则数量不变，仅 `GOV-OBJECTIVE-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-PITFALL-001`、`DATA-FRESHNESS-001`、`DATA-BTC-FINAL-001`、`DATA-US-PIT-001` 的 `applicability.change_risks` 加入新类别；修订后 canonical catalog hash=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

## 独立语义审查结论

1. 新类别 `research_readonly_release` 只能通过明确 CLI/票据选择；`infer_change_risk` 与 base 的 AST 完全一致，AST SHA-256 均为 `36db7db707060f72ddad32c47b39d722afdc02d1fc28a2eb57a90c6f3452b34d`。
2. base 的 7 个既有类别逐对象完全不变，默认仍为 `unclassified`。新类别固定独立 integrator、current-main identity、sealed evidence、immutable resolver、真实 canonical browser acceptance、rollback point 与 fresh context；`fast_forward_main_allowed=false`、`backend_restart_required=true`、readiness 上限为 `quality_checked`。
3. `promotion_artifact_rebuild_required=false` 只适用于纯研究只读发布，不抹除 BTC root/503、领域 read model、promotion gate 或其他运行 blocker，也不派生 Demo `integrated_fastpath`。
4. receipt 校验器只验证 reviewer-supplied 记录；文档明确要求真实 Git diff、逐文件 hash、版本身份、manifest/seal 和浏览器证据。单纯填充 true 不构成真实验收。
5. 必需 checks 只能为布尔 true；Demo control、promotion、paper、live、private、order、real order、transfer、withdraw、execution permission、runtime observed 必须严格为布尔 false。未知能力、保护路径、非规范路径、缺失证据或错误 profile 均 fail-closed。
6. Team Context 继续显示本治理 published 事件的 3 个 blocker，以及 CN/US read model missing、BTC runtime artifact root unavailable；`promotion_eligible=false`、`gate_impact=none`。代码没有隐藏领域 blocker、修改 hook 或改变服务/交易语义。

## 独立验证

- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/agent_governance/test_research_release_policy.py tests/agent_governance/test_delivery_policy.py tests/agent_governance/test_context_packet.py tests/agent_governance/test_team_context.py tests/agent_governance/test_hooks.py tests/agent_governance/test_governance_contract.py tests/agent_governance/test_context_scalability.py` → **80 passed in 81.18s**。
- `git diff --check c1d11987…HEAD --` → passed。
- 机器比较：既有 policy 对象不变；`infer_change_risk` AST 相等；catalog 仅 6 项 applicability 变化；8 个 deliverable hash mismatch=0；context packet 返回新 catalog hash、固定边界、required checks 和 required false flags。
- Team Context read-only 构建保留 50 个 discovery blocker、14 个历史 invalid handoff 和 3 个领域 read-model blocker；这些不属于本治理票据的修复范围，也未被隐藏或升级为新工程范围。

未运行 M1 重训、M1 业务测试、真实浏览器、服务启动/停止、backend restart、promotion/runtime artifact builder、private/order/live endpoint 或任何密钥访问；它们不属于本治理审查。

## 审定、阻塞与下一入口

审定结论：producer 治理提交集通过，当前审定 commit 可作为后继新 M1 执行上下文的精确 base。后继任务必须读取本审定规则，显式运行 `context_packet.py --change-risk research_readonly_release --scope shared --scope research --scope gate`，在独立 sparse worktree 完成 M1 的提交态 manifest/seal、只读数据发现、独立 diff/hash/identity 审查、registered-main 发布、canonical `research_readonly` 启动与真实浏览器验收。

本阶段仍有且仅有以下发布阻塞：治理提交尚未进入 registered main；后继 fresh M1 上下文与业务验收尚未完成；最终发布 integrator 尚未按“治理→M1”顺序把两个分离票据集成到 main。为避免现有 backend 因 main drift 进入 409，本票据不更新 main、不重启服务。

`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`、`demo_control_enabled=false`。治理通过不解锁任何交易、paper、private、order 或 live 权限。

## 治理依据

已读 `AGENTS.md`、`docs/knowledge/README.md`、non-negotiables、shared pitfalls、integrator role、delivery risk policy、`quant-agent-preflight`、`quant-agent-handoff`、新研究只读发布 playbook 和 producer 治理报告。preflight 原 catalog hash=`127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。

命中/保持适用：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未全文读取原始事故日志。
