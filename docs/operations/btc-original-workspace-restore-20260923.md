# BTC 原控制台和底部工作区恢复

## 范围与版本

- 票据：BTC-ORIGINAL-WORKSPACE-RESTORE-20260923；角色：super_developer。
- change_risk：research_readonly_release；base/main：b68ee020f440519589928d005abe89c687da4662。
- 专属 sparse 工作树：super_developer-btc-original-workspace-restore-20260923。
- 用户要求：恢复原控制台、策略测试器和底部入口；简短只读提示、禁用未授权操作、缺失事实显示未知；保留公共行情修复。
- 初始声明路径 clean；只编辑本工作树，没有覆盖其他任务文件。未修改 main、后端、CSS、权限、启动器、策略、风险、OMS、保护或账本。

## 改动职责

- CryptoWorkspace.tsx：重新挂载原 DemoTradingConsole、StrategyTesterReport；恢复 Demo 控制台按钮；移除替代页面。所有 public-market 路径、health 判定、Demo polling/SSE/operator 禁用分支保持不变。
- DemoTradingConsole.tsx：保留原栏目、限额、风险、账户、观察、策略及操作区域；新增仅收紧的显示模式。research_readonly/unavailable 下控制、确认和候选选择禁用，未读取事实显示未知；默认 runtime 模式继续沿用原后端权威合同。
- StrategyTesterReport.tsx：保留报告标签、图表、编辑器和历史入口；增加一行只读说明；禁用新回测并在事件入口再次拒绝。缺少证据不标成历史有效报告，不把缺失交易数/月数显示为零。
- test-btc-readonly-workspace.mjs：对真实组件 SSR 验证栏目、原底部组件、缺失事实、禁用按钮、宽松旧 controller 不可覆盖只读限制、原 runtime 兼容及零副作用。
- frontend-identity.json：源提交后仅通过既有 identity:refresh 刷新派生指纹。

## 测试

失败优先：新回归在修改前因替代面板 ReadonlyRuntimeNotice/ReadonlyResearchLinks 仍存在而失败。

已通过：

1. node frontend/scripts/test-btc-readonly-workspace.mjs（真实控制台及测试器 SSR；research_readonly/unavailable；宽松 controller 限制；原 runtime 四个 GET 兼容）。
2. node frontend/scripts/test-btc-operator-v2-contract.mjs。
3. node frontend/scripts/test-btc-operator-cleanup.mjs。
4. node frontend/scripts/test-btc-operator-attempt-state.mjs。
5. node frontend/scripts/test-btc-account-facts-view.mjs。
6. node frontend/scripts/test-btc-missing-evidence.mjs。
7. node frontend/scripts/test-btc-public-depth-ux.mjs。
8. node frontend/scripts/test-btc-chart-navigation.mjs。
9. frontend/node_modules/.bin/tsc.cmd --noEmit --project frontend/tsconfig.json。
10. frontend/node_modules/.bin/vite.cmd build（frontend 为 cwd；只有既有 bundle size warning）。末次缺失诊断文字调整后重新通过 SSR、cleanup 与类型检查；独立集成需重新构建最终提交。
11. git diff --check -- frontend。

测试加载器开发时遇到 Node 24 下 Phosphor CJS 入口和 CSS 转译问题，仅修复测试加载器为真实 ESM 图标及忽略样式导入，没有修改依赖或业务组件以绕过测试。

后端兼容回归：`py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_okx_public_display_stream.py tests/agent_governance/test_research_release_policy.py`：57 passed in 24.23s。提交态 identity 校验随交付执行。正式页面验收必须在独立审查、main 限定发布后进行；本报告不将 SSR 或构建等同正式页面通过。

## 交付及安全边界

交付要求：提交态源、派生 identity、validated append-only handoff；独立 integrator 审查完整限定 diff 后按现有 research_readonly 路径发布，保留 base 回退点。Team Context 暂时出现 handoff discovery/cat-file timeout；在恢复前不消费跨代理交付或合入发布，不改超时/治理规则绕过。

无新数据、runtime artifact、ledger、manifest 或回放输出；不重新核账，不恢复暂停的 2960/8760 年度评估。历史证据来源不变。生产 BTC 的原有 503、账户未读取不是本次页面恢复的修复范围。

readiness 上限 quality_checked，不是 promotion evidence。Demo、paper、live、promotion、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 保持 false。不读取密钥，不调用私有账户/交易接口。

## 治理记录

已读 quant-agent-preflight、quant-agent-handoff、AGENTS、knowledge README/non-negotiables/source map/domain architecture、shared/architect/super_developer pitfalls、super-developer profile、delivery risk policy 和 research_readonly_release。

catalog hash：6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。

context_packet 显式采用 super_developer + shared/research/gate + research_readonly_release；active IDs：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001。

未全文读取原始事故日志。其余历史未合并任务不消费、不合并。本次 schema、执行顺序和安全权限无变化。
