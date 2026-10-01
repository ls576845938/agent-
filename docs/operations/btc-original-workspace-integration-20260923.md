# BTC 原控制台工作区限定集成审查

## 票据与范围

- 票据：`BTC-ORIGINAL-WORKSPACE-INTEGRATION-20260923`；角色：`integrator`。
- 变更风险：`research_readonly_release`；批准基线：`b68ee020f440519589928d005abe89c687da4662`。
- 上游源提交：`98e3063b2ce1ed471bf948da188391fc9818a310`；交付提交：`29eba31e308e3e4508b8b148e32ca93846dafdda`；交接提交：`8e069f405872769200d6d8386c184e031202a34c`。
- 上游交接：`.agent/handoffs/BTC-ORIGINAL-WORKSPACE-RESTORE-20260923/published-btc-original-workspace-29eba31e3.json`，`handoff.py validate` 返回 `valid`。
- 独立 sparse 工作树：`integrator-btc-original-workspace-integration-20260923`；初始限定路径全部 clean，无重叠写者。

本票只集成已批准的六项交付：恢复原 BTC 控制台、策略测试器和底部工作区入口；以显示层只读模式禁用未经授权的交互并如实显示未知事实；保留既有公共行情读取。未修改后端、策略、仓位、退出、风险、OMS、保护、账本、broker/private transport、安全权限、启动器或治理规则。

## 独立审查结论

1. Git 祖先关系为 `base -> source -> deliverable -> handoff`；六个交付文件的 SHA-256 与 envelope 完全一致。
2. 完整限定 diff 仅包含三项前端组件、一个回归脚本、一个派生 identity 和一个生产者报告；没有受保护执行路径。
3. `CryptoWorkspace` 在所有模式挂载原 `DemoTradingConsole` 和 `StrategyTesterReport`，但 Demo operator hook 仍仅在 `access.demoRuntime=true` 时启用。公共行情的 `publicMarket` 路径和流控制未改变。
4. 控制台新增的 `workspaceMode` 只收紧操作：非 runtime 模式下所有 action、候选选择、确认框及确认输入保持禁用；缺失账户、观察、WS、运行与报告事实显示未知。默认 runtime 模式兼容旧行为。
5. 测试器在只读模式保留原布局、标签和编辑器，但 UI 与事件入口双重拒绝新回测；没有训练、恢复、账本写入或网络副作用。
6. cherry-pick 后，派生 identity 的 `baseline_commit` 从生产者源提交归一为等价的集成源提交 `68708de0831d30372a34360ebda5497c73e0148f`；对象 ID 与指纹 `162861bc01e6fc60a90386cc53be72b930bb3ce941ac40d9a19d84d4089f4e2e` 均未改变，`identity:check` 通过。

结论：执行语义不变，权限只收紧；允许以 `research_readonly` 限定发布到 registered main。readiness 上限仍是 `quality_checked`，不是 promotion evidence。

## 独立验证

- 八个前端 Node 回归：`test-btc-readonly-workspace.mjs`、`test-btc-operator-v2-contract.mjs`、`test-btc-operator-cleanup.mjs`、`test-btc-operator-attempt-state.mjs`、`test-btc-account-facts-view.mjs`、`test-btc-missing-evidence.mjs`、`test-btc-public-depth-ux.mjs`、`test-btc-chart-navigation.mjs`：全部通过。
- `frontend/node_modules/.bin/tsc.cmd --noEmit --project frontend/tsconfig.json`：通过。
- `npm.cmd run build`：通过；仅有既有 bundle-size warning。
- `npm.cmd run identity:check`：通过；manifest match 与 baseline ancestry 均为 true。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_okx_public_display_stream.py tests/agent_governance/test_research_release_policy.py`：`57 passed`。
- `git diff --check`：通过。

未运行全仓测试；本票没有数据、模型、运行产物、ledger 或 schema 改动。正式浏览器验收由 registered main 发布并重启后执行，不能由 SSR 或构建替代。

## 发布与安全边界

- 回退点固定为 `b68ee020f440519589928d005abe89c687da4662`；发布前创建带该对象的 rollback tag。
- 只使用仓库 canonical launchers 重启 `8765/3000`，并核验 backend/frontend identity、真实 listener、`canonical=true`、`runtime_stale=false`、`research_readonly`、`read_only=true`、`controls_disabled=true`。
- 不重建 BTC runtime/promotion artifact，不恢复暂停的年度评估；既有 runtime artifact 503 和账户事实缺失继续如实暴露。
- `demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 全部保持 false。

## 治理记录

读取：`quant-agent-preflight`、`quant-agent-handoff`、`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator profile、delivery risk policy、research readonly release contract。未读取原始事故日志。

catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
