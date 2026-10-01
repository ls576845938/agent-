# Research Registry Request Chain 独立集成验收

- Ticket: `RESEARCH-REGISTRY-REQUEST-CHAIN-20260928`
- `change_risk`: `research_readonly_release`
- Base: `870ca75f5a2fad57fba1a73571020308b302328b`
- Approved producer deliverable: `2fb17f64bb16512f39e400861b4a84ccd08a60c6`
- Validated producer envelope: `385d6ddd7ef95e824274de98edf0b8a1f7824381`
- Integrated source HEAD before this report: `62f9957cfec4cf718fdd70a93ce55256d22faa1b`
- Source tree: `16396d28949ebaa5b6dc3fa6b546e049c3636de5`

## 审查结论

通过源码独立集成审查，可以交给主会话按 `research_readonly_release` 做普通 merge、官方只读重启与正式页面验收。提交态 handoff 全 Git 校验有效，五个 deliverable blob 的 SHA-256 均与 envelope 一致。

实现只涉及 evidence registry 的请求内目录元信息复用、Qlib 详情读取移入 FastAPI 同步线程池，以及对应测试。完整发现、文件 hash、冲突、root/reparse、别名和取消 fail-closed 语义保留；无跨请求缓存、无超时放宽、无权限或执行语义变化。

## 独立验证

- Focused/API: `47 passed, 1 skipped`；skip 为既有 Windows symlink 权限条件。
- Research-readonly compatibility: `20 passed`。
- 定向治理回归: `74 passed`；本次未复现 producer 的 Team Context discovery timeout。
- `py_compile` 与 `git diff --check`: 通过。
- Canonical 数据一次性 TestClient 13 路并发：`13/13 HTTP 200`、全部 `<12s`、wall `9.395s`；registry `4.598s`、`10731 bytes`、HTTP SHA-256 `81f7ce04b3bf1874255b814cd9376821b3fe04ce8bd3462a2b46df4276c242a0`，与 producer 证据一致；Qlib list `9.374s`，M1 detail `7.996s`。
- 机器回执：`D:/vibe coding/Obsidian/量化系统/offline-runs/research-request-chain-20260928/integration/independent-after-integration-testclient-13way.json`，SHA-256 `355a98bc2446246d790bfd605ec88f1837a8532bf11ca51a2bd518d425c1c569`。

## 范围与状态

集成 worktree 由 planner 从批准 base 创建，`core.sparseCheckout=true`，初始及验证后限定 `safe_status=clean`。首次仅 cherry-pick 子提交出现预期依赖冲突，已在无本地变更时安全 abort；随后按批准提交链顺序集成，无人工冲突覆盖。未消费其他代理未提交文件。

读取了仓库根规则、non-negotiables、shared pitfalls、integrator 角色入口、`research_readonly_release` 和 delivery policy。命中 pitfall：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。Catalog SHA-256: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

本票未修改前端，因此不刷新 frontend identity。未创建 artifact/manifest/ledger，也未访问 private/order/live/secret。registry 原有 `CONFLICT` 结论保持，不是 promotion evidence。正式 current-main merge、8765/3000 重启、固定浏览器矩阵仍待主会话发布后完成；在此之前不声明页面验收通过。`promotion/paper/live/private/order/real_order/transfer/withdraw` 全部保持 `false`。

## Qlib overlap delta

在 `b03f505376f2c906a1a4abaecf526b72c58e6beb` 的正式矩阵出现单次双页重叠 Qlib list 超时后，同票独审了 `cc9fee02d5cb6679cab0348ad29ae1a7cf58c033`。变更仅涉及 `app_factory.py` 与既有 Qlib 测试：鉴权、selector 和 server-owned root 仍在 join 前校验；每个 app 只共享尚未完成、且 key 相同的完整读取；成功或 `BaseException` 后立即移除，不提供完成缓存，新请求必须重新核验。原 archive/hash/seal/summary 路径未删减。

独立回归为 `36 passed`；`py_compile` 与 diff check 通过。Canonical 数据双请求只读核验 wall `2.201s`，两响应均为 HTTP 200、`23838 bytes`、SHA-256 `673e58586b70d626fcb48005cabc68c24af8a178ee9e025fe1f2af0662fbe9bd`，仅执行一次 archive 验证和 17 次 run seal 校验。回执：`D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/integration-qlib-delta/independent-qlib-list-overlap.json`，SHA-256 `d328dbecf68ac50e4ed9d26acd58faf84eea95adf160bbf8916564bf7150c305`。正式 11 项页面矩阵仍须在该 delta 合入并重启 current main 后完整重跑，不能只重跑失败场景。

## Qlib cold-first 有界并行 delta

在 `d7cb976b6158a5e9608de32d715bc3a47d91813d` 的正式矩阵首次 bare overview 仍出现一次 Qlib list 超时后，同票独审了 `9aa5a44fbbd837324c9c2e55104c10193448eef0`。变更仍只涉及 `app_factory.py` 与原 Qlib 测试：research-readonly app 使用共享、最多 4 个 worker 的 summary executor；完整 archive 发现和已验证文件绑定不变；返回顺序、逐 run blocker/error、异常 fail-closed 和无 settled cache 语义保留；app shutdown 等待既有任务并释放 executor。

独立回归为 `40 passed`（另有 1 条既有 Starlette deprecation warning）；`py_compile` 与 diff check 通过。一次新进程 canonical-data 13 路只读核验为 `13/13 HTTP 200`、全部 `<12s`、wall `5.418s`；Qlib list `4.875s`、`23838 bytes`、SHA-256 `673e58586b70d626fcb48005cabc68c24af8a178ee9e025fe1f2af0662fbe9bd`，M1 detail `5.409s`，并保留 18 次 seal 校验。回执：`D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/integration-qlib-cold-delta/independent-cold-13way-42fdbef17.json`。这只是提交态源码与真实数据预验证；正式 8765/3000 固定 11 项矩阵仍须在 current-main 合入、官方重启后完整执行，历史失败不得被本结果覆盖。
