# Candidate Management 本机免口令独立集成验收（2026-09-26）

## 结论

`INTEGRATE-CANDIDATE-NO-PASSWORD-20260926` 在批准的 23 个 deliverable 范围内独立验收通过，未发现 P0/P1。候选仅达到 `quality_checked` 源码集成，可由主会话按普通非快进流程合入；不代表服务已启用、真实浏览器已验收、候选任务已执行，亦不解锁 promotion、paper、private、order 或 live。

## 身份、工作树与交付范围

- `change_risk=unclassified`；base/main：`568a8985eb4f9d9a614881e4cbac31eecdf048d3`。
- producer source：`7ad24d747f972c2ef97397f464f2283b1f7d7dbd`，tree `b19cb41abc0c1a2587a0fc31d0126c489597cfc5`。
- derived identity commit：`6df54dc491f75553c412602834bef42709b0a2c3`，tree `64bdb60634078845974eb66f2f158e4b8cebc963`。
- producer handoff HEAD / 独立测试 HEAD：`342af3886cac4d948af685b8ceab82758ab96893`，tree `4723c4985b209803cebcceecae0b0e40c0bf4ac5`。
- planner sparse worktree：`D:\vibe coding\Obsidian\量化系统\worktrees\integrator-integrate-candidate-no-password-20260926`；分支：`agent/integrator/integrate-candidate-no-password-20260926`；初始 scoped dirty 0，`core.sparseCheckout=true`。
- 使用 `git merge --ff-only 342af388...` 保留 producer 原始 source、derived 与 handoff 祖先；未 cherry-pick、未修改注册 main。
- `published-candidate-management-no-password-20260926-6df54dc49` 经官方 schema/Git/hash 校验为 `valid`；23 个 deliverable 均匹配，base→source→derived→handoff 祖先有效。
- 23 路径职责：backend 本机请求权威与两组候选路由/装配；部署 helper 与双击 wrapper；Vite pre-proxy guard；候选登记及离线结果 UI/API；对应 backend/Node/SSR/E2E 测试、操作文档与前端 identity。未触碰 `quant_crypto`、`quant_shared`、`quant_us`、`quant_cn`、`integrations`、readonly access policy、正式 backend launcher、治理或 Agent 配置。

## 安全与行为复审

- `local_no_password` 仅在精确 `candidate_management` profile 下成立；默认及未知模式不会免口令，旧 `key` 模式仍用恒时 key 比较。缺 operator、错误 profile、未知 auth mode 均 fail-closed。
- 双击 wrapper 显式传入 `--auth-mode local_no_password`，不生成、读取、记录或持久化口令；旧 key 模式仍可使用 Process 环境中的既有 key。外部配置文件仍只允许原 9 个非敏感字段。
- Vite guard 以 `enforce: pre` 在 `changeOrigin` 代理之前注册，直接检查原始 socket peer；非 loopback、伪造或重复 Host/Origin、`Forwarded`/`X-Forwarded-*`、编码/双斜杠/点段候选路径均在代理前拒绝。非候选公共 API 不受该 guard 影响。
- Backend 不信任 Host/Origin 或 forwarded headers 推断本机；再次检查 `request.client.host`、精确 Host、精确候选路由、原始路径、非简单 intent header、重复/控制字符 headers，以及浏览器 Fetch Metadata/Origin/Referer 组合。
- 正常同源浏览器 GET 可无 Origin，但必须是完整 `same-origin` metadata、允许的 mode、`dest=empty` 与可信 Referer；浏览器 POST 有 metadata 却缺 Origin 被拒绝。完全无 Origin/metadata 只允许真实 loopback CLI 且仍需 intent。
- `_LocalContext` 由模块私有 proof 构造，字符串或普通对象不能伪造；offline 写权限仍同时要求原 `candidate_management` profile 与显式 `QS_CANDIDATE_OFFLINE_ENABLED=true`。免口令不会绕过 catalog/account/job identity、注册或启动条件。
- 前端只根据服务端 capabilities 的明确 auth mode 展示免口令分支；unknown、失败或 readonly 不生成密码门或写请求。API 客户端发送公开 intent，但 intent 单独不构成认证；所有安全权限字段仍必须为 false。
- FastAPI 的 wildcard CORS 不是认证来源；独立回归确认跨站写请求在 service 调用前被本机请求权威拒绝。

## 独立测试与环境说明

1. `canonical .venv python -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider --basetemp <isolated> tests/contracts/test_candidate_local_auth.py`
   - `35 passed, 1 warning in 1.80s`；warning 为既有 Starlette/httpx 弃用提示。
2. `node --test frontend/scripts/test-candidate-local-auth.mjs frontend/scripts/test-candidate-delivery.mjs`
   - sparse worktree 无 `frontend/node_modules`，首次在加载 `typescript` 时退出，未进入产品断言。
   - 只读设置 canonical `NODE_PATH` 后 12 项通过，Vite ESM 包仍因 Node 不读取 `NODE_PATH` 而未加载。
   - 使用 `%TEMP%` 的临时只读 ESM loader，仅将 `vite` 与 `@vitejs/plugin-react` 映射到 canonical 已安装依赖后：`13 passed, 0 failed in 3.92s`；loader 随后删除，未在 main/worktree 建链接或安装依赖。
3. `node frontend/scripts/check-frontend-identity.mjs`
   - passed；`manifest_match=true`、`baseline_ancestor=true`、`canonical=false`（独立分支预期）；fingerprint `7208605f3c8fb93beceba7d492870982b5251eb6ef831497faad2266d111dc05`。
4. `git diff --check 568a8985...342af388...`
   - exit 0；受保护的执行/治理路径 diff 为空。

producer handoff 中记录但本 integrator 未重复运行：wrapper 31、launcher candidate 子集 21、legacy API/authorize 门禁 33、Node 13、TypeScript noEmit、SSR 定向 2。长离线执行/身份/账本组合矩阵按批准范围未运行，producer 的中断运行不计通过。

未运行：真实浏览器、真实配置或候选写入、服务启停、User/Machine 环境写入、真实账户/凭据、private/order/live endpoint、promotion artifact 重建、完整 214/执行/账本矩阵。未读取 secret，未生成候选运行证据。

## Gate 与后续动作

- `promotion_eligible=false`；promotion、paper、live、private、order、real_order、transfer、withdraw、execution permission 均保持 false。
- `unclassified` 的 promotion artifact 要求未执行；本报告只是源码 `quality_checked`，不能用作 promotion evidence。
- 本票未生成或改变 artifact、manifest、ledger、replay 或外部运行目录；现有证据 freshness 状态不变。
- 主会话合入后仍须在 canonical main 校验前后端身份、fingerprint、listener ownership/health，并用真实浏览器验证本机免口令路径及 LAN 拒绝；服务启用和任何候选作业仍是独立显式动作。

## 治理记录

- 读取：`AGENTS.md`、knowledge README、quant non-negotiables、shared pitfalls、integrator role，以及 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 冲突：无；本票路径未发现其他 agent dirty，未覆盖、清理或回滚任何改动。
