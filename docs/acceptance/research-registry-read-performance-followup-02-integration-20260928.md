# 研究注册表读取性能 follow-up-02 独立集成审查

- 票据：`RESEARCH-REGISTRY-READ-PERFORMANCE-20260928`
- `change_risk`：`research_readonly_release`
- 基线：`c982620431ddcccce5db27b301763602b1ee108d`
- 生产者交付：`75ebeb543e1527f1ead4318a4817bd268f46a487`
- 生产者事件：`published-research-registry-read-performance-followup-02-75ebeb543`
- 独立业务集成：`783634960fc30963e9f6986ae367d1bfe6711c0c`
- readiness 上限：`quality_checked`

## 结论

独立审查通过源码集成，正式发布验收仍未通过。本修订只改变研究证据注册表在一次请求内解析路径的方式，不改变证据发现集合、完整性校验、冲突判定、全量文件哈希、API 合同、12 秒页面预算或任何交易语义。

本次两文件变化符合既有 `research_readonly_release`：

- `quant_us/research/evidence_registry.py`：根目录只解析一次，同一父目录只在请求内解析一次；文件为 reparse/symlink 时仍执行完整 `resolve`，随后继续原有 `stat`、索引摘要、发现集合、指纹、按需文件哈希与冲突校验。
- `tests/research/test_evidence_registry.py`：覆盖父目录复用、边界等价、父／叶 reparse 越界拒绝和叶 reparse 强制完整解析。

没有修改治理、前端、策略、仓位、退出、风险、OMS、保护、账本、启动器、权限或超时。生产者早期 `9c73a40d...`／follow-up-01 因交付差异混入旧无效事件而被拒绝；只消费从 `c982...` 干净生成、精确两文件的 follow-up-02。

## 独立验证

1. Git 与交接：follow-up-02 envelope 对 Git 校验有效；`c982...75eb...` 精确只有上述两文件；集成工作树 sparse 且限定路径 clean。
2. 注册表/API 回归：`22 passed, 1 skipped in 26.72s`。skip 是 Windows 当前用户无 symlink 创建权限，平台无关 reparse 覆盖通过。
3. Qlib/只读归档兼容：`29 passed, 1 warning in 33.54s`；warning 为既有 Starlette TestClient 弃用提示。
4. 真实数据 12 路 TestClient 预验证：使用集成源码，但显式将服务器拥有的 repo/data/QLib root 绑定到注册主工作树；`QS_BACKEND_EVIDENCE_PROFILE=research_readonly`、fixture fallback 和 Demo 控制均为 false。12 路并发 wall `9.428s < 12s`，全部 HTTP 200；注册表 `9.303s`、`10731 bytes`、`registry_status=conflict`、`registry_integrity_status=CONFLICT`；Qlib `6.604s`、`23838 bytes`、`17` 个运行。原有冲突没有被掩盖。

早先 `1.496s` 和 `1.857s` 测量使用了集成工作树的空 `data/artifacts`，返回 `MISSING`／不完整 Qlib，已作废且不得作为验收证据。上述 `9.428s` 仅是完整应用和真实数据的 TestClient 发布前预验证，不能替代正式 main 的 8765 并发请求和浏览器验收。

## 仍需完成

- 按现有 `research_readonly_release` 以普通独立集成 merge 发布，不走 fast-forward 快路径；新回退点必须精确指向 `c982620431ddcccce5db27b301763602b1ee108d`。
- 官方启动器以 `research_readonly`、`QS_ALLOW_FIXTURE_FALLBACK=false`、`QS_BTC_DEMO_CONTROL_ENABLED=false` 重启 8765/3000。
- 后端与前端 identity 必须绑定最终 merge HEAD、`canonical=true`、`runtime_stale=false`。
- 正式 8765 的同页 12 路并发仍须在原 `12000ms` deadline 内完成；浏览器须打开真实封存运行并验证按钮、缺失／冲突／blocked 状态。
- 当前 A/B 仍是 baseline `2960/2960` 完成、conditioned `1956/2960` 因日内保护双触发歧义 fail-closed，末端空头 `-0.01` 张保留；不得宣称效果结论。
- 候选管理、管理写入、Demo、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 继续为 false。

## 治理与范围记录

- 读取：`AGENTS.md`、`docs/knowledge/README.md`、全局不可违反规则、`shared_pitfalls.md`、integrator 角色合同、`research_readonly_release.md`、量化 preflight/handoff 技能。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`；advisory `GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 未读取原始事故日志；未访问账户、密钥、交易所、private/order/live endpoint；未写数据、artifact、ledger 或正式服务。
