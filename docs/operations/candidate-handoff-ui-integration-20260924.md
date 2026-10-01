# 研究候选交接前端：独立集成审查

日期：2026-09-24；票据 `CANDIDATE-HANDOFF-UI-INTEGRATION-20260924`；角色 `integrator`；`change_risk=research_readonly_release`。

## 结论与边界

独立源码审查通过，可以作为限定 main 合入的精确候选；readiness 上限为 `quality_checked`。本结论只覆盖前端本地草稿、清单核对、精确来源重读和原 BTC 控制台接收卡，不表示服务端已经审定、绑定账户、登记运行候选或启动任何执行模式。

正式发布检查 `current_main_identity`、`canonical_browser_acceptance`、registered-main 重启后监听器与回退点验收仍为 **pending**，由主会话在限定合入 main 后完成；本工作树未启动服务、未操作 main、未执行浏览器验收，也未把这些检查提前写成 completed。

服务端候选包审定、账户绑定和注册事务未实现是完整运行部署的已知功能边界，不是继续扩大本前端集成票的授权。发布按钮保持恒禁用，账户保持 `not_bound`。

## 提交、handoff 与完整性

- approved base / rollback base：`209507ea74121e07337f838705d60533e93b5848`。
- producer deliverable：`af861f7d3ba71d28adfecc791be6e432a5f862bc`。
- producer handoff commit：`60b253b1591fc9cdd90bf0ebf05603760ef28d39`。
- producer branch：`agent/super_developer/candidate-handoff-ui-20260924`。
- integrator branch：`agent/integrator/candidate-handoff-ui-integration-20260924`；planner-created sparse worktree。
- merge commit：`b955899c54f507912cde1fa2ddfbf030fc9a6d09`，父提交精确为 approved base 与 producer handoff commit。
- envelope：`.agent/handoffs/CANDIDATE-HANDOFF-UI-20260924/candidate-handoff-ui-20260924-published.json`，`handoff.py validate` 返回 `valid`；raw envelope SHA-256 `f3499e7c74001a2a91d4a6889ce8a8c6bd0791c551162176f6fe76af3c21ceb4`。
- base → deliverable → handoff 祖先链通过；11 个声明 deliverable 的 raw Git blob SHA-256 全部逐项匹配；实际 producer diff 路径与 envelope deliverables 精确相等。
- producer blocker 原样保留：服务端注册／账户绑定未实现；正式浏览器验收待发布阶段完成。`promotion_eligible=false`、`gate_impact=none`。

## 独立代码审查

- 完整 diff 仅含前端、文档、测试和 producer handoff；保护路径扫描为空。未修改 `quant_crypto`、strategy、risk、OMS、protection、ledger、broker/private transport、security、启动器、权限、runtime artifact store/publication 或治理。
- 新接收卡只调用既有只读 GET：精确 Alpha Factory run 与精确 Qlib run。没有 `apiPost`、`fetch`、operator controller、Demo control、训练、恢复、策略切换或运行注册调用；没有查询参数时不读取草稿或研究来源。
- 工厂只接受唯一精确候选及其 final-audit Qlib 引用；0 候选显示空态，不回退训练折、第一条或相似候选。Qlib 要求 seal、run/candidate/source/data/instrument 合同一致，missing/unsafe/mismatch 均 fail closed。
- 草稿只在 `sessionStorage` 保存白名单投影，URL 只带 UUID。客户端注入的 approved/runtime/account 字段不会传播；所有权限字段重建为 false。
- 独审发现 `RegExp.test` 会把数值 ID 隐式转成字符串，攻击者若同步重算非加密 fingerprint，草稿 parser 可接受非字符串 `runId/candidateId/qlibRunId`。已在本票将 ID/UUID 校验收紧为 `typeof value === 'string'`，并增加失败优先回归；未扩大共享 schema 或后端合同。
- 原 BTC 控制台只插入独立 inbox；原目录、启动确认、策略选择和只读禁用行为保持原样。发布按钮恒禁用且文案明确“未注册 · 未启动”。

## 真实只读来源核对

通过当前 canonical 后端现有 research-readonly GET（无写入、无 private/order/live）核对：

- `/api/health`：`status=ok`、`evidence_profile=research_readonly`、`read_only=true`、`controls_disabled=true`。
- `m1-okx-qlib`：`integrity_status=passed`；candidate `qlib_manifest_0de835a36fc243c1`；summary 与 seal source 均为 `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`；model SHA-256 `8b44ef4bc97be069c21240cbf70a78b7e2f29fc182b057925328503196e16b74`；blocker `no_simulated_fills`；promotion/paper/live/private/order/execution_permission/runtime_observed 均为 false。该旧 source 如实显示为非 current-HEAD 研究证据，不改写为运行证据。
- `m1-okx-factory` 与 `af-okx-btc-20260910-integration01`：均 `integrity_status=passed` 且候选数为 0；只用于验证诚实空态，不以 mock 伪装真实候选。

未修改、复制、补算或发布这些 artifact；没有生成 ledger、promotion artifact 或 runtime artifact。

## 测试证据

| 命令 | 结果 |
| --- | --- |
| `node frontend/scripts/test-candidate-handoff.mjs`（新增严格 ID 用例、修复前） | 13 passed / 1 failed；精确复现非字符串 ID 被接受 |
| `node frontend/scripts/test-candidate-handoff.mjs`（修复后） | 14 passed / 0 failed |
| `node frontend/scripts/test-btc-readonly-workspace.mjs` | passed；原 console/tester 保留、只读零 GET/POST/timer、runtime 兼容 |
| `node frontend/scripts/test-btc-demo-start-feedback.mjs` | passed |
| `node frontend/scripts/test-trend-environment.mjs` | passed；命令自身明确不是 browser acceptance |
| `node frontend/scripts/test-donchian-offline-evidence.mjs` | 3 passed |
| `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json` | passed |
| `npm exec vite build`（frontend） | passed；5268 modules；40.52s；仅既有大 chunk 警告 |
| `git diff --check` | passed；仅 Windows LF/CRLF 提示 |

首次直接运行 focused test 因新 sparse worktree 没有本地 `node_modules` 而报 `Cannot find module 'typescript'`；随后将 worktree 的 ignored `frontend/node_modules` junction 指向注册主工作树已有依赖，再运行失败优先和完整回归。没有安装、升级或修改依赖。

## 治理与交付状态

已读：`AGENTS.md`、`docs/knowledge/README.md`、non-negotiables、`shared_pitfalls.md`、integrator profile、`delivery_risk_policy.json`、`research_readonly_release.md`、`quant-agent-preflight`、`quant-agent-handoff`。未加载原始历史踩坑日志。

active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

初始限定 dirty paths：全部 clean；无重叠 writer、无冲突、无清理／reset／覆盖其他工作树。集成 touch set 为 producer committed paths、`frontend/public/frontend-identity.json`、本报告和本票 append-only handoff。

持续 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。本集成不解锁 promotion、paper、Demo 或 live。

下一步仅是：提交本独审修正与报告，基于提交态运行 `identity:refresh` 并提交 identity，然后发布、验证并提交本票 append-only `integrated` handoff；主会话再以该精确候选执行限定 main 合入、重启和正式浏览器验收。
