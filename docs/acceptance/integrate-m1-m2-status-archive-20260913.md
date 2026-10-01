# M1 / M2 状态归档独立集成验收

- 票据：`INTEGRATE-M1-M2-STATUS-ARCHIVE-20260913`
- 角色：`integrator`
- change risk：`research_readonly_release`
- base / rollback point：`b02836ce1415693471c0bc263a164160b27736d9`
- 上游 deliverable：`71e095d6b9f09e3248eb5145a8dbef59f9b6a915`
- 上游 handoff commit：`635e443bb6ffffb7043e5c2e167ace660c0544c7`
- 本地顺序 cherry-pick：`3878fdc53`、`146d6d97d`
- readiness ceiling：`quality_checked`
- gate impact：`evidence_only`

## 独立结论

批准合入本票限定状态归档。完整差异只包含 16 个文档、架构只读页面和对应测试文件，以及原 published handoff；另机械刷新 `frontend/public/frontend-identity.json` 并新增本验收与 integrated handoff。没有修改默认 BTC 信号、仓位、退出、Risk、OMS、保护单、账本、broker/private transport、运行产物、权限或治理规则。

归档后的事实边界正确：M1 已完成限定工程结项，但仍是研究 sidecar；M2 已完成 8/8 历史探索对照，本版增量不稳定、不晋级、不追加搜索；M3—M4 未启动；真实账户只读验收仍未开始。页面中的 `source_mapped` 只表示职责源码已定位，页面同时明确“职责序列不等于同一 runtime 已贯通”；它不是 `runtime_verified`。

`catalog.json` 和 `knowledge.json` 继续保留各自历史 `source_commit`，没有把历史 EOF 阅读快照改写为当前源码复核。M2 报告保留实际计算 HEAD `f8510e3c15dc82642b37dbb33eb58bcdb801ffaa`、最终 review commit `9263c4bc9f8d22c66620d2f8906500c63f19e966`、外部封存 hash 和探索性 as-of；没有冒充 current-HEAD 运行证据。

## Git、handoff 与封存证据

- planner 创建的专属 sparse worktree 已确认 `core.sparseCheckout=true`；创建时 HEAD 精确等于 base。
- base 是 deliverable 的直接父提交；handoff commit 是 deliverable 的直接子提交。两个提交按普通 cherry-pick 顺序无冲突落到集成分支。
- published envelope `published-m1-m2-status-archive-20260913-71e095d6b` 校验为 `valid`；其依赖 `superseded-result-digest-review-9263c4bc9` 也校验为 `valid`。
- published envelope 声明的 5 个 deliverable SHA-256 全部与 Git 提交对象精确相等；依赖 handoff 声明的 2 个 M2 结果文件 SHA-256 也精确相等。
- 外部 M2 `result_manifest.json` SHA-256 为 `5270f155ef4871bd619f00fadb1079dee1ca12f347df661dd3e377d796c5f37e`，`result.json` SHA-256 为 `cfab8da27ae4fafb9aaa429246d9aaea492d9a13128496657c1016b9b6134a2d`；manifest 内绑定同一 result hash，result 状态为 `completed_exploratory`、source HEAD 为 `f8510e3c15dc82642b37dbb33eb58bcdb801ffaa`、四折存在。
- 本票没有重验 245 个历史试验文件，也没有重训或重算；这次归档审查以已验证的最终 digest-review handoff、两份外部封存摘要 hash 和原独立报告为边界。

## Touch set 与 dirty 保护

上游实际 touch set 是以下 16 个路径：

- `docs/acceptance/m1-m2-status-archive-20260913.md`
- `docs/architecture/system-code-map/LAYERED-ARCHITECTURE.md`
- `docs/architecture/system-code-map/MILESTONE-STATUS-20260913.md`
- `docs/architecture/system-code-map/README.md`
- `docs/architecture/system-code-map/REASSESSMENT.md`
- `docs/research/m2-historical-environment-ab-20260913-results.md`
- `frontend/e2e/architecture-knowledge.spec.ts`
- `frontend/e2e/architecture-mindmap.spec.ts`
- `frontend/scripts/test-architecture-knowledge.mjs`
- `frontend/scripts/test-architecture-mindmap.mjs`
- `frontend/src/workspaces/ArchitectureMapWorkspace.tsx`
- `frontend/src/workspaces/architecture/ArchitectureKnowledge.tsx`
- `frontend/src/workspaces/architecture/ArchitectureMindMap.tsx`
- `frontend/src/workspaces/architecture/catalog.json`
- `frontend/src/workspaces/architecture/knowledge.json`
- `frontend/src/workspaces/architecture/mindmap.ts`

另消费原 handoff，并仅新增／刷新：`frontend/public/frontend-identity.json`、本验收报告、`.agent/handoffs/INTEGRATE-M1-M2-STATUS-ARCHIVE-20260913/`。所有上游路径和原 handoff 目录在集成前逐路径 `safe_status=clean`；没有覆盖、清理或消费其他工作树的未提交文件。用于 TypeScript 的 `frontend/node_modules` 只是 ignored junction，目标为 registered-main 已安装依赖，不纳入提交。

## 回归结果

| 命令 | 结果 |
| --- | --- |
| `npm.cmd --prefix frontend run lint` | PASS；TypeScript `tsc --noEmit` 完成 |
| `node --test frontend/scripts/test-architecture-knowledge.mjs frontend/scripts/test-architecture-mindmap.mjs` | PASS；`10 passed / 0 failed` |
| `npm.cmd --prefix frontend run identity:refresh` | PASS；baseline `146d6d97d`，fingerprint `988fdf7e1aa34df04bdf37139617b454f4473e2a112c31a2806c1b816c53c5e2` |
| `npm.cmd --prefix frontend run identity:check` | PASS；`manifest_match=true`、`baseline_ancestor=true`、dirty paths empty at check time |
| `npm.cmd --prefix frontend run identity:test` | PASS；4 个 object target 校验通过 |
| `git diff --check`（批准范围） | PASS；只有 Windows LF/CRLF 提示，无 whitespace error |

未运行 build，也未在 worktree 启动页面或执行 E2E。固定节点文案没有 CSS／布局变化，静态测试的本地滚动与响应式断言通过；实际 viewport 容纳、current-main identity、canonical 3000 页面与两个 architecture Playwright spec 由主会话合入后验收。未启动后端、未训练模型、未读取 secret、未调用 private/order/live endpoint。

## 发布、阻塞与安全状态

本提交可以按精确顺序合入 registered main，但集成本身不完成发布。主会话仍需：只合入本票最终审定提交，按 `research_readonly` 使用 canonical launcher 重启 8765/3000，验证 source/main HEAD、`canonical=true`、`runtime_stale=false`、只读模式与正式页面。旧 BTC runtime/promotion artifact 不在本票重建范围；main HEAD 改变后必须保留其原计算 commit 并按 stale/blocked 展示，不能称 current-head promotion evidence。

真实账户三项生产接线缺口仍未验收；private-readonly receipt 仍缺失，本票没有运行观察器。`demo_control_enabled/promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 全部保持 `false`。

## 治理记录

已读 `AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role config、delivery risk policy、`research_readonly_release`，并使用 quant preflight / handoff skills；仓库不存在单独的 `integrator_pitfalls.md`。未全文读取原始事故日志。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。本票命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
