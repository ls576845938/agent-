# BTC current-head read-model 前端合同独立集成验收

- 票据：`INTEGRATE-BTC-READMODEL-UI-CONTRACT-20260913`
- 角色：`integrator`
- 变更风险：`promotion_evidence`
- 基线：`827a4d1d8bc547cb048c7e2f6d44d0ff8011860f`
- Producer deliverable：`e0a651ad729843cecbf1d4f52d3caf27f23f447e`
- Producer handoff：`9c84216cc20a834a1f6d29860bf6e8dbc17d8ab2`
- 集成分支：`agent/integrator/integrate-btc-readmodel-ui-contract-20260913`
- 工作树：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-readmodel-ui-contract-20260913`
- 结论：源码兼容合同可供主会话限定合入；只增加第三套 current-head 精确阻塞合同，不改 gate、权限或已有 fail-closed predicate。

## 变更与职责边界

- `frontend/src/workspaces/CryptoWorkspace.tsx`：仅增加 10 项 current-head rebuild blocker allowlist 和其精确 SHA-256 合同，实际源码差异 17 行。
- `frontend/e2e/btc-current-head-reader-ui-binding.spec.ts`：补充第三套合同正例和 missing/extra/reordered/hash/count/preserved/payload 漂移负例。
- `frontend/e2e/btc-trading-fixtures.ts`：补充与真实合同完全对齐的 mock 数据；安全键仍是原 49 项。
- `frontend/scripts/test-btc-current-head-readmodel-contract.mjs`：静态验证三套合同与 fixture 对齐，独立重算新 10 项 hash，并固定原 fail-closed predicate。
- `docs/acceptance/btc-readmodel-ui-contract-20260913.md`：producer 验收记录。
- `.agent/handoffs/BTC-READMODEL-UI-CONTRACT-20260913/**`：原 append-only published event。
- `frontend/public/frontend-identity.json`：集成者使用现有脚本机械刷新前端对象身份；未改 launcher、guard、package、lock、CSS 或布局。

本票据未修改 backend、`quant_crypto`、artifact builder、gate 策略、交易语义或权限。

## 交接、祖先和提交映射

- `handoff.py validate`：`published-btc-readmodel-ui-contract-20260913-e0a651ad7` 为 `valid`。
- 祖先：`e0a651ad7^ = 827a4d1d8`，`9c84216cc^ = e0a651ad7`，基线正确。
- 哈希：envelope 列出的 5 个 deliverable 均从 Git object 独立重算，`5/5 match`。
- 范围：producer deliverable 仅 5 个审定路径，handoff commit 仅新增原 published event，`git diff --check` 通过。
- 集成方式：在新 dedicated sparse 分支中普通 cherry-pick，因此原 producer commit 不是最终集成 HEAD 的 Git 祖先。精确映射为 `e0a651ad7 -> 8193fb96f`、`9c84216cc -> d4e37e73c`；已通过原对象 SHA-256、完整 diff 和限定 touch set 证明等价，不应因“原 commit 非 main 祖先”重复创建工程票据。

## 合同审查

- 原 legacy 17 项和 quality-L2 17 项 allowlist/hash 块相对基线零 diff。
- 新 current-head rebuild allowlist 恰好 10 项，独立重算 SHA-256 为 `cc0d8cbd8ff93afeab933d1b87bed493f667177aa1c9b1fdbe38a42a07ec65fa`。
- read-model 仍只通过 `apiGet('/api/research/btc/domain-read-model')` 读取，未新增 POST 或操作调用。
- 接收条件仍要求：exact blocker hash/count/order/payload；`blocker_count` 与实际数组一致；`required_blockers_preserved=true`；49 个既定安全键全部 false；`status=blocked`、`current_stage=pending_next_stage_gate`、`freshness=current_head`、固定 blocked gate decision；promotion/paper/live false；source HEAD 与 canonical frontend identity 一致。
- 上述 predicate 都是原实现，本票据只让第三套 exact contract 可被同一判定链识别。

## 独立验证

- Failure-first：集成前 `node frontend/scripts/test-frontend-identity.mjs` 在第 241 行因 `manifest_match=false` 失败，与前端对象库存改变一致。
- 机械刷新后 `node frontend/scripts/check-frontend-identity.mjs` 通过：`manifest_match=true`、`baseline_ancestor=true`，sparse 分支 `canonical=false` 为预期，所有 identity 安全旗标 false。
- `node scripts/test-btc-current-head-readmodel-contract.mjs`：`BTC current-head read-model exact contracts: PASS`。
- `npm.cmd run lint -- --pretty false`：首次因 sparse worktree 未安装 `node_modules` 而报 `tsc is not recognized`；随后仅在本 worktree 创建 ignored junction 指向 registered-main 已安装依赖，同一命令通过。junction 的类型和解析目标已校验后删除，main 依赖目标仍存在；未修改 package/lock 或 TypeScript 配置。
- 未重复 build；producer 已报告 sourceguard、TypeScript 与 build 通过，本次独立审查优先验证精确合同和静态类型。

## 未执行与发布前置

- 未在 sparse/历史 worktree 启动 Vite 或任何服务，未运行 Playwright E2E。
- 未读写 BTC runtime artifact，未访问 network、secret、private/order/live endpoint。
- 主会话必须先将审定 HEAD 限定合入 registered main，再完成 frontend canonical identity、70 项 artifact/read-model 回归、current-HEAD blocked artifact publication、`research_readonly` 重启、22 项 E2E 和真实页面验收。任一硬前置失败都不能把本集成写成发布成功。

## Dirty、artifact、gate 与治理

- Planner 创建时所有声明路径 clean，`core.sparseCheckout=true`；cherry-pick 无冲突，未覆盖他人 dirty。
- 未产出 artifact/manifest/ledger/replay；既有 external root 由主会话及单写者管理，本集成者未操作。
- 已读：`AGENTS.md`、`docs/knowledge/README.md`、不可妥协规则、`shared_pitfalls.md`、`integrator.toml`、`cross_agent_coordination.md`、`delivery_risk_policy.json`、架构边界与三个量化 skill。
- Active pitfall IDs：`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,MONITOR-AUDIT-001,QSYS-GATE-001,GOV-PROMPT-001,GOV-WINDOWS-001`。
- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- Gate 仍是 `blocked_fail_closed_no_paper_no_live`；`promotion_evidence_ready=false`。promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、demo_control 全部保持 false。

本集成只证明前端可安全识别一个新的、仍然阻塞的 current-head 证据合同，不授予任何交易或晋级权限。
