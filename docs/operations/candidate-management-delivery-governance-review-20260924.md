# 候选管理限定交付治理独立审查

日期：2026-09-24  
角色：`integrator`  
结论：**通过，仅允许后续在新鲜上下文中集成被冻结的候选管理源码，并以 `research_readonly` 做正式发布验收。**

## 审查对象

- main 基线：`55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`
- 治理源码：`c245b7f35f37c3e8941fd885c2617e2bc7a12f03`
- 治理 handoff：`6d518de377b56c359422a41db105b2cd3210a817`
- 冻结业务审定：`891d79f316d3850a80578ae132a670a476d4e02b`
- 冻结业务 SOURCE：`1fc70fec77a6bac7b5699e99b503a10b92af659c`
- 治理合同哈希：`ab7389e7d54cb5d825ce703b7c846f4a37bd59a7135adc7f3dad30b23c84a23d`
- 上游事件：`candidate-management-governance-source-20260924-01`，`handoff.py validate` 返回 `valid`

治理变更仅包含 5 个新文件：独立 sidecar JSON/Markdown 合同、无副作用校验器、回归测试和 producer 报告。通用 `delivery_risk_policy.json`、启动器、Hook、角色配置和业务代码未改动。

## 独立核验

1. 交接与亲缘
   - `55f039ae...` 是 `c245b7f3...` 祖先，`c245b7f3...` 是 `6d518de3...` 祖先。
   - `891d79f3...` 是 `1fc70fec...` 祖先；业务币种／文案修复和独审 handoff 均通过 `handoff.py validate`。
   - `frozen_source()` 对 base→SOURCE 的 30 文件集合及逐文件 SHA-256 校验通过；源码、审定结果或任一文件漂移都会阻断。

2. 证据不可由布尔值伪造
   - `checks=true` 仅是必要形状；治理独审和业务集成必须引用已提交报告的 commit/path/SHA-256，且 Git 亲缘与允许 delta 必须通过。
   - 伪造报告哈希、陌生字段、非布尔值、未知阶段、错误版本或未审 delta 均被负例拒绝。

3. 权限与发布边界
   - 正式部署阶段额外要求 main 精确等于 target commit，且回退 tag `codex/candidate-management-before-release-20260924` 必须精确指向原 base；本次治理审查未创建 tag、未发布服务。
   - `candidate_management_enabled`、management root/operator/auth、Demo、promotion、paper、live、private、order、real_order、transfer、withdraw、execution permission、runtime worker/observed 必须是字面量 `false`；缺失、多余或使用 `0`/`"false"` 均会阻断。
   - `research_readonly` 不构造 candidate router，不配置候选管理 root/operator/auth；现有共享 Web API 认证不在本票读取或变更范围。

## 测试

```text
.venv/Scripts/python.exe -B -X utf8 -m pytest -q
  tests/agent_governance/test_candidate_management_readonly_delivery.py
  tests/agent_governance/test_delivery_policy.py
  tests/agent_governance/test_research_release_policy.py
  tests/agent_governance/test_donchian_history_readonly_delivery.py
  -p no:cacheprovider --tb=short --basetemp <isolated>

78 passed in 37.94s
```

额外独立探针：两条业务 handoff 有效；`frozen_source=valid`；已审业务 commit 到 SOURCE 的亲缘有效；治理 diff 仅 5 文件。

## 决定与剩余阻断

本治理合同可以先行合入 main，但仅使后续独立业务集成与 `research_readonly` 验收获得一条有边界的合法路径。它不得与业务代码在同一未刷新上下文中一次发布。

未完成项：治理 main 生效、新 integrator 上下文中合成冻结业务 SOURCE、限定 main 发布、current-main 身份／listener／health／浏览器验收。候选管理目录仍未接运行入口，不创建管理 SQLite，不读账户或密钥。

安全标志继续保持：`candidate_management_enabled=false`、`management_root_configured=false`、`management_operator_configured=false`、`management_auth_configured=false`、`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_worker_enabled=false`、`runtime_observed=false`。

