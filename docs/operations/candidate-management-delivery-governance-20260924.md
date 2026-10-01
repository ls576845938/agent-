# 候选管理限定交付治理修订

2026-09-24；主会话 super_developer；change_risk=governance_control。用户明确授权只补本票交付规则、校验器和测试，独审生效后继续 research_readonly 发布，不启用管理写入/账户/交易。

Base：`55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`。planner 专属 sparse 分支 `agent/super_developer/candidate-management-delivery-governance-20260924`。开始限定路径 clean，无冲突或他人文件改写。

## 选择与范围

使用独立的 `docs/agent_playbooks/candidate_management_readonly_delivery.json` 和同名 Markdown 合同，不修改通用 `delivery_risk_policy.json` 或旧风险枚举/规则。配套 `tools/agent_governance/candidate_management_readonly_delivery.py` 只读校验精确 Git 提交/亲缘/文件哈希与独审报告；`tests/agent_governance/test_candidate_management_readonly_delivery.py` 为负例与兼容回归。其余仅本报告与本票 append-only handoff。没有业务代码、启动器、Hook 或服务变更。

固定业务审查 commit `891d79f316d3850a80578ae132a670a476d4e02b`，完整交付 SOURCE `1fc70fec77a6bac7b5699e99b503a10b92af659c`，包含 30 个提交态文件（含 BTC 精确候选加载接口）；原币种/文案独审结论保留。部署只允许 research_readonly，candidate_management profile、root/operator/auth 均不启用/配置。前端派生 identity 只允许既有刷新与核验。

不要求为只读软件发布重建交易 promotion 证据；原运行证据缺失/stale 仍 fail-closed。本合同不使管理目录成为运行目录，不授予候选有效性、账户或订单权限。

## 测试记录

失败优先：新合同模块尚不存在时，21 个新用例失败（ModuleNotFoundError）；不是在既有实现上伪造失败。

命令：main `.venv/Scripts/python.exe -m pytest -q tests/agent_governance/test_candidate_management_readonly_delivery.py tests/agent_governance/test_delivery_policy.py tests/agent_governance/test_research_release_policy.py tests/agent_governance/test_donchian_history_readonly_delivery.py -p no:cacheprovider --tb=short`。

首次 77 passed / 1 failed：既有 context test 导入 `quant_crypto` 不在默认 producer sparse 路径，非业务回归。仅 `git sparse-checkout add quant_crypto` 补只读测试依赖，不修改任何 BTC 源码；复跑 **78 passed / 38.65s**。未运行业务重训/回放、服务、浏览器或真实账户。

## 治理与交付

已读 preflight/handoff skills、AGENTS、knowledge README/non-negotiables/source-map/domain architecture、shared/super_developer playbooks、现有 delivery policy 和 research readonly 合同。context role=super_developer，scope=shared,governance，risk=governance_control。

Catalog `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；适用 GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS-001、QSYS-GATE-001、QSYS-SECURITY-001。不扫描/清理无关产物或其他代理修改。

源码 deliverable 与后续独审/集成分别通过提交和 validated handoff 绑定。治理本身不发布页面；须独立 integrator 审定、先合治理，再新上下文集成被冻结业务。此提交没有 current-main 发布/运行验收，不产生 DB、artifact、manifest 或经济账本。

管理能力、Demo、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_worker_enabled、runtime_observed 全部保持 false。main/正式服务未动；回退参考为原 base，不执行 reset。
