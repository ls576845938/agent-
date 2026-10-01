# Research Readonly UI Loading 独立集成验收

- 票据：`INTEGRATE-RESEARCH-READONLY-UI-LOADING-20260914`
- 角色 / 风险：`integrator` / `research_readonly_release`
- 基线 / 回退点：`9735b6e46e21c6818c99699bddccdb26bc383e3e`
- 上游：`published-research-readonly-ui-loading-20260914-f9f513dfc`，deliverable `f9f513dfcb860ff87cd436c8385880cce8f66b80`
- 集成：no-ff merge `3bbc31d504f9dda5ce46c2deba6d843f2972373f`；identity commit `ad97d1d87660c56be6b4029d94d500d1dd49600a`
- 结论：独立源码审查与工作树验证通过；就绪上限仍为 `quality_checked`。

## 范围与审查

仅接收批准的 8 个源码/测试/报告文件、published 事件，并刷新 `frontend/public/frontend-identity.json`。未修改后端、索引、数据、schema、策略、风控、OMS、账本、治理或交易权限。

上游 handoff 在注册仓对象库验证为 `valid`；事件工作树文件 blob 与 `de57aa09fa466435da39179746635843efd0a18c` 一致，`9735b6e -> f9f513df -> de57aa09` 祖先链和逐文件 SHA-256 通过，实际 diff 恰为批准 touch set。初始 scoped dirty 为 0，无冲突、无其他代理改动被覆盖。

独立审查确认：数字型 `apiGet` 超时参数保持兼容；只读 GET 新增 signal，不改变 POST/执行语义；相同来源只共享在途请求，settled 后立即移除；来源 key 与 sequence 隔离迟到结果；12 秒 deadline 覆盖正文解析并取消读取；`CONFLICT` 显示为可读但阻塞，不被表述为合格或可晋级。

## 验证

- `handoff.py validate`：passed。
- `node frontend/scripts/test-research-read-request.mjs`（`NODE_PATH` 指向 registered-main 只读依赖）：`5/5 passed`。
- registered-main `esbuild` 编译 `ResearchPortfolioWorkspace.tsx`：passed；首次写 `C:\tmp` 被沙箱拒绝，改用系统临时目录后通过。
- `node frontend/scripts/check-frontend-identity.mjs`：passed，`manifest_match=true`、`baseline_ancestor=true`、fingerprint `905f28e5...`。
- `git diff --check`：passed。
- 未运行：canonical-main build、focused E2E、原 42 项 Playwright、真实页面、后端 `read_only`/423 与官方重启；必须由 registered main 合入后执行，本工作树不启动非 canonical 页面。

## 治理与剩余阻塞

读取 `AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator profile、`research_readonly_release.md`。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中：`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,MONITOR-AUDIT-001,QSYS-GATE-001,GOV-PROMPT-001,GOV-WINDOWS-001`。未读取原始事故日志。

未生成 artifact/manifest/ledger；current-HEAD freshness 不适用。本票不是 BTC 账户事实、账本恢复或只读对账的全局前置。owner `root` 仍需在 registered main 合入后刷新最终 identity、执行 canonical build/E2E/真实页面及官方重启。`demo_control_enabled,promotion,paper,live,private,order,real_order,transfer,withdraw,execution_permission,runtime_observed` 全部保持 `false`。
