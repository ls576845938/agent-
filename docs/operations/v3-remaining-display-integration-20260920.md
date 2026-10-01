# V3 剩余缺证展示：独立源码审查

## 结论

票据 `V3-REMAINING-DISPLAY-INTEGRATION-20260920`，角色 `integrator`，`change_risk=research_readonly_release`。批准将已审源码候选发布到注册主工作树进行限定只读验收；此结论**不等于正式页面验收通过**。后者须在实际发布 main HEAD、canonical 8765/3000 服务和真实浏览器上另记。readiness 上限 `quality_checked`。

## 提交与边界

- 集成基线/回退点：`ea5d62324caf28fb8087f915ef35e08a2d411a30`。生产者 deliverable：`6c6f70ffa2ab1207b7c5bc16905f179a23d8a5a8`；发布 handoff 提交：`c3aff85091ae1976843dd8a86d3e52a2f295d694`，事件 `published-v3-remaining-display-20260920-6c6f70ffa`。独立分支从该 main 基线以 `--no-ff` 合入一个 handoff set；合入前 main 未变化，声明路径全部 clean，无冲突或他人 dirty 覆盖。
- Git blob 原文加载 handoff 并用 `handoff.validate_handoff_against_git` 验证：schema、base→deliverable 祖先、生产者分支、五个 deliverable 的 SHA-256 均有效。deliverable 的完整净差异恰为两个 TSX、一个新增回归脚本、派生 `frontend-identity.json` 和生产者报告；其后的提交只新增该 handoff。`git diff --check` 通过。
- 两个 TSX 只把账户事实与研究阻断投影为“未知/未验证/已收到的阻断”。未对账或读取失败不能显示零订单、零成交、空仓；费用、资金费和审计缺证不能显示零；空 blocker 列表不声称研究证据完整。仅有效且已对账的明确空数组保留真实零值。完整差异未引入新请求、交易调用、启动器、治理、策略、风险、OMS、账本或权限改动。
- 本独审 touch set 仅本报告及 `.agent/handoffs/V3-REMAINING-DISPLAY-INTEGRATION-20260920/` 下追加事件；没有改生产者源码、manifest、ledger、artifact 或其他代理工作树。既有其他代理变更未合并、未清理。

## 限定验证

- `BTC_DISPLAY_TEST_REF=ea5d623... node frontend/scripts/test-btc-missing-evidence.mjs`：exit 1，准确命中旧版“当前 run 已公开的研究证据完整”断言；非环境报错。候选同一脚本：exit 0，命名展示函数 SSR 覆盖缺失、错误、未对账、真实空数组、非法张数、费用、审计及研究边界。SSR 仅 mock 图标，未 mock 展示逻辑。
- `test-btc-account-facts-view.mjs`、`test-offline-execution-summary.mjs`、`test-btc-demo-start-feedback.mjs`、`test-research-read-request.mjs`（5 项）、`test-research-rollback.mjs`：各 exit 0。独立测试以 `NODE_PATH` 只读指向注册主工作树已有的前端依赖；本 worktree 无 `node_modules`，首次无该环境变量的运行因缺 `typescript` 而未进入断言，不计入通过或预期失败。
- `node frontend/scripts/check-frontend-identity.mjs`：exit 0，`manifest_match=true`、`baseline_ancestor=true`、指纹 `09cf503eb599a8497617e90cb54f9d33e9c485ecb587a0e5669cf27ec2fc7519`；worktree `canonical=false` 为预期，不作为页面验收。独立 worktree 未重跑 tsc/build；生产者提交态报告记录二者通过，正式浏览器尚未运行。

## 治理、证据和待验收项

已读 `AGENTS.md`、knowledge README 与 non-negotiables、`shared_pitfalls.md`、integrator 角色配置、`research_readonly_release.md`、V3 限定交付合同及 `quant-agent-preflight`/`quant-agent-handoff`。context catalog hash 为 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未读取原始事故日志。

本次没有新建或验证 BTC runtime artifact、数据 manifest、ledger；历史离线摘要不是当前账户/交易证据。正式验收必须另核实际发布 commit、回退点、canonical 身份、健康与只读 profile、真实 listener、页面缺证/历史 run 展示；主会话提供这些事实后再记录 receipt。原 BTC 领域证据、私有账户/交易和 promotion 仍 blocked/fail-closed。`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 false；未读取 secrets 或调用 private/order/live 端点。
