# BTC current-head read-model 前端合同兼容验收

## 结论

- 票据：`BTC-READMODEL-UI-CONTRACT-20260913`
- 角色：`super_developer`
- `change_risk`：`promotion_evidence`
- 基线：`827a4d1d8bc547cb048c7e2f6d44d0ff8011860f`
- 交付上限：`quality_checked`
- 变更仅为前端只读证据消费的第三套精确 allowlist；没有改变 gate、builder、后端、策略、风控、OMS、账本、布局、CSS、启动器或权限。

当前 committed rebuild 代码按检查顺序生成 10 项 required blockers；当前只读 API 返回同一顺序、数量 `10` 和 SHA-256 `cc0d8cbd8ff93afeab933d1b87bed493f667177aa1c9b1fdbe38a42a07ec65fa`。前端新增该精确合同，同时保留两套既有 17 项合同。

## Touch set 与职责

- `frontend/src/workspaces/CryptoWorkspace.tsx`：仅登记 current-head rebuild 的精确 10 项 required blockers 及固定 hash；既有 matcher 和全部 fail-closed predicate 原样保留。
- `frontend/e2e/btc-trading-fixtures.ts`：增加 current-head rebuild 精确 fixture；不改变 legacy/quality fixture。
- `frontend/e2e/btc-current-head-reader-ui-binding.spec.ts`：增加精确正例以及 missing/extra/reordered/hash/count/preserved/payload drift 反例。
- `frontend/scripts/test-btc-current-head-readmodel-contract.mjs`：读取真实 workspace 源码，核对三套 source/fixture 顺序与 hash 映射，并检查实际 fail-closed predicate 未被削弱。
- 本报告及 `.agent/handoffs/BTC-READMODEL-UI-CONTRACT-20260913/**`：提交态验收和跨代理交付。

`frontend/public/frontend-identity.json` 明确保留给独立 integrator，本票据未修改。

## 权威来源核验

- 使用 `git show HEAD:quant_crypto/application/btc_current_head_gate_rebuild.py` 读取基线提交中的官方 rebuild 实现；没有读取或依赖其他 worktree 的未提交文件。
- 使用本地 GET-only `/api/research/btc/domain-read-model` 交叉核对当前发布 payload：source HEAD 为基线、required count 为 `10`、required hash 为 `cc0d...`、顺序与 committed rebuild 检查顺序一致。
- 新合同不绑定 run id、日期或 artifact 物理路径。

## Failure-first 与验证

1. 初始直接调用 `npm.cmd exec -- playwright ...` 因 sparse worktree 没有本地 `node_modules`，命令尝试解析错误版本的 CLI 后以 `ERR_MODULE_NOT_FOUND @playwright/test` 退出；未修改 package 或 lock 文件。随后仅把该工作树的 ignored `node_modules` 建为指向注册主工作树已安装依赖的 junction。
2. 在实现 source allowlist 前，针对既有 canonical `main:3000` 运行：

   ```powershell
   .\node_modules\.bin\playwright.cmd test e2e/btc-current-head-reader-ui-binding.spec.ts --reporter=line
   ```

   结果：`21 passed, 1 failed`。唯一失败是精确 10 项 current-head rebuild 正例仍显示 `CONTRACT UNAVAILABLE OR UNSAFE`；旧两套合同和所有新旧 drift 反例均通过，精准复现缺陷。

3. 实现后静态合同守卫：

   ```powershell
   node scripts/test-btc-current-head-readmodel-contract.mjs
   ```

   结果：`PASS`。

4. TypeScript：

   ```powershell
   npm.cmd run lint -- --pretty false
   ```

   结果：exit `0`。

5. 生产构建：

   ```powershell
   npm.cmd run build
   ```

   结果：exit `0`，`5258 modules transformed`。保留既有大 chunk 警告，没有为此扩大范围。

实现后的 Playwright 正例需要 canonical 页面加载本提交的 bundle；治理规则禁止从 writer worktree 启动 Vite/preview。因此该项由独立 integrator 合入、更新 identity 后在 `main:3000` 完成，不在 producer 阶段伪造通过。

## Fail-closed 保证与剩余项

- required blockers 仍要求精确 hash、精确数量、精确顺序和精确逐项内容；没有接受任意 count、后端自报 hash、别名、并集或子集。
- structured blocker payload 必须覆盖每个 required blocker，`blocker_count` 必须与 rows 数量一致。
- safety 必须是现有 49 个真实键且全部为 `false`；伪造 49 键仍拒绝。
- source HEAD、status、stage、freshness、decision、gate decision、readiness 和三个 readiness flags 的既有检查均未改变。
- 读取仍为 GET-only；未增加写请求。
- promotion、paper、live、private、order、real_order、transfer、withdraw、execution permission 全部保持 `false`。
- 未重建或发布任何 runtime artifact；当前 gate 仍为 `blocked_fail_closed_no_paper_no_live`。独立 integration、current-main identity 和真实 canonical 页面验收仍待下游完成。

## 治理记录

- worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-readmodel-ui-contract-20260913`
- branch：`agent/super_developer/btc-readmodel-ui-contract-20260913`
- 初始授权路径全部 clean，无重叠修改，无冲突处理；未覆盖或清理其他代理改动。
- 已读：`AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/super_developer_pitfalls.md`、`docs/agent_playbooks/delivery_risk_policy.json`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 未读取原始踩坑日志；未命中需要事故原文的实施细节。
