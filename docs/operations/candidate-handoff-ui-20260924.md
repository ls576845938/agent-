# 研究候选交接前端：生产者验收

日期：2026-09-24；票据 `CANDIDATE-HANDOFF-UI-20260924`。

## 范围与版本

- 角色：主会话按 super_developer 写任务执行；change_risk=`research_readonly_release`，gate_impact=`none`。
- 基线／精确回退依据：`209507ea74121e07337f838705d60533e93b5848`。交付源码提交由 append-only handoff 的 deliverable_commit 固定。
- 专属 sparse 工作树：`super_developer-candidate-handoff-ui-20260924`；初始限定路径 clean，未覆盖其他代理修改。注册主工作树未写入业务代码。
- 用户已授权独立审查后仅发布前端、文档与测试，以 research_readonly 验收。当前文档为生产者结果，不是独审或正式发布凭证。

## 修改职责

- research/candidate-handoff.ts：前端草稿白名单、精确身份／安全合同检查、会话存储和新鲜来源比较；不是运行 schema。
- CandidateHandoff.tsx、candidate-handoff.css：原研究页三步交接面板，核对／意向／确认，保存和导出本地清单。
- CandidateHandoffInbox.tsx：原 BTC 控制台接收卡，仅有明确草稿引用时重读研究来源，不改变原候选选择。
- AlphaFactoryConsole.tsx、QlibDecisionTrace.tsx、DemoTradingConsole.tsx：小型关联入口；原布局、组件及操作保持原样。
- test-candidate-handoff.mjs：新增行为／拒绝／SSR 回归；test-btc-readonly-workspace.mjs 只补新 import 的 identity mock 和 Router 测试上下文，原禁用断言保留。
- architecture/candidate-runtime-handoff.md：当前交互与后续服务端审定注册设计，明确区分已实现与未接通。

未修改后端、策略、风控、OMS、保护、账本、共享执行合同、启动器、权限或治理。无新增依赖；复用已有 node_modules。未创建或改写模型、数据、运行证据、ledger 或恢复点。

## 验证

在票据工作树运行：

| 命令 | 结果 |
| --- | --- |
| node frontend/scripts/test-candidate-handoff.mjs | 13 passed；失败优先初始缺模块，再完成实现；包含错身份、unsafe/missing flags、seal、重复候选、缺模型、损坏草稿、跨市场、无控制写入、SSR |
| node frontend/scripts/test-btc-readonly-workspace.mjs | passed；原 console/tester 保留、写操作禁用、无只读控制请求或轮询，兼容 runtime 模式 |
| node frontend/scripts/test-btc-demo-start-feedback.mjs | passed |
| node frontend/scripts/test-trend-environment.mjs | passed |
| node frontend/scripts/test-donchian-offline-evidence.mjs | 3 passed |
| node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json | passed；先修正仓库 React shim 不含 useId、事件类型与 key props 的类型错误 |
| npm exec vite build（frontend） | passed，5268 modules，41.51s；既有大 chunk 提示，无 Vite serve/preview |
| git diff --check（限定路径） | passed，只有仓库 LF/CRLF 提示 |

测试 harness 的新增组件间接加载 frontendIdentity 曾报错，已按现有测试模式提供 mock；不得将该初始失败隐藏成无需修改测试即通过。真实研究只读 GET 检查 m1-okx-qlib 的候选、模型 seal、安全旗标；m1-okx-factory 无候选，如实显示不可交接。未触发训练或计算。

尚未运行：独立集成审查、提交态身份刷新、正式 main 浏览器交互、重启后 identity/安全验证。由限定集成及正式发布验收补齐；构建与 SSR 不代替浏览器。

## 规则与安全

已读：AGENTS.md、quant-agent-preflight/handoff skills、knowledge README/non-negotiables、shared_pitfalls、super_developer_pitfalls、super-developer profile、delivery_risk_policy、research_readonly_release、domain_architecture_rules、浏览器使用技能。

命中：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001。

catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

持续 false：demo_control_enabled、execution_permission、runtime_observed、promotion、paper、live、private、order、real_order、transfer、withdraw。客户端确认不产生权限；发布按钮恒禁用，账户未绑定，不登记运行候选。研究完整性通过不是模型有效或可运行包完整。

剩余功能缺口归属共享交付／运行注册后端：包审定、服务端账户绑定、版本兼容和原子注册。此轮只完成前端准备与接收，不能宣称已将 Qlib 模型部署到 BTC 运行。该后端缺口不在本次授权内自动扩展。
