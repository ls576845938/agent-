# BTC 公共行情研究只读发布独立集成审查

- 集成票据：`BTC-READONLY-WORKSPACE-INTEGRATION-20260923`
- 角色：短生命周期 `integrator`
- 风险分类：`research_readonly_release`
- main/base：`a2bbae85077bc4a580e5d3915648669308e31996`
- producer source：`055309cf8da345aa1581c268c0e38fb16ebd47e0`
- producer deliverable：`54fe43e36327d28851b8555de94acea627723b1d`
- producer handoff：`7f5e10037b89cab5d32e7b0a8e6892a0ecc017b1`
- producer event：`published-btc-readonly-workspace-54fe43e36`
- rollback point：`a2bbae85077bc4a580e5d3915648669308e31996`
- readiness ceiling：`quality_checked`

## 审批范围与分类结论

用户已明确授权开放 `research_readonly` 下两个公共行情 GET，修正 BTC 页面模式识别，并在独立审查通过后发布到 registered main。授权不包含 Demo 状态或控制、私有账户、下单、paper/live、密钥、生产账本或年度评估。

本变更符合 `research_readonly_release`：它只增加研究展示读模型、研究前端和测试；不改变策略信号、仓位、退出、风险、OMS、保护、账本、broker/private transport、权限、runtime artifact、promotion 或治理。无需 BTC promotion artifact 重建，必须由独立 integrator 审查，并在 current main 以 `research_readonly` 重启和做 canonical 页面验收。

## 独立源码与权限审查

对 `a2bbae850..54fe43e36` 的完整 diff 逐文件审查，实际 13 个 producer 路径与 handoff 完全一致：

- 后端只新增 `/api/research/btc/public-market/view` 与 `/api/research/btc/public-market/ticker` 两个 exact GET；其他方法、额外 path 与未知 query 继续 fail-closed。
- `research_readonly` 仅挂载新的公共行情 router；既有 Demo router、Demo runtime service、private-readonly observation 与 IBKR runtime 均不挂载/不构造。
- 新服务仅复用既有 `OkxDemoPublicMarketClient`。该客户端固定 `www.okx.com` allowlist、BTC-USDT-SWAP、unsigned GET、ticker/candles/books 三个公共 path；无签名、keyring、私有 client 或 order surface。
- 服务只维护最多 32 项进程内缓存与锁，无后台线程、订阅、持久写入、账本、模型、运行恢复或 fallback。无缓存失败返回 503；有缓存失败明确 stale；盘口缺失不伪造，时间过旧不标实时。
- 页面仅在 health 精确为 `research_readonly + read_only=true + controls_disabled=true` 时使用两个公共 GET；未知 health 不发公共或 Demo 请求。只读模式不启动 Demo polling/SSE/operator action，不渲染账户为零或健康。
- 原 runtime 模式继续使用既有 Demo paths 和 V2 operator contract；新增 `enabled` 开关只撤销读取/定时器/POST，不放宽任何授权算法。
- 公共行情固定 `strategy_signal_compatible=false`、`private_endpoint_used=false`、`order_endpoint_used=false`、`persisted_market_rows=false`。

Git 与 handoff 验证：

- `base -> source -> deliverable -> handoff` 祖先链全部成立；producer branch 精确指向 handoff commit。
- `handoff.py validate` 直接对 deliverable Git blob 校验 13 项 SHA-256，结果 `valid`。
- `git diff --check a2bbae850..54fe43e36` 通过；工作树和声明 touch set 初始全部 clean，无冲突、无他人 dirty 被覆盖。
- frontend identity manifest fingerprint `41b95bbd0a7215803db83510f47dcfc1c678d332a6850f7c27ae8c33a958a8dc` 与提交态前端对象匹配；baseline `055309cf8...` 是当前集成链祖先。

## 独立测试

环境固定：`QS_BACKEND_EVIDENCE_PROFILE=research_readonly`、`QS_BTC_DEMO_CONTROL_ENABLED=false`、`QS_ALLOW_FIXTURE_FALLBACK=false`。

1. `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_okx_public_display_stream.py tests/agent_governance/test_research_release_policy.py`：`57 passed in 8.91s`。
2. Node：`test-btc-readonly-workspace`、`operator-v2-contract`、`operator-cleanup`、`operator-attempt-state`、`account-facts-view`、`missing-evidence`、`public-depth-ux`、`chart-navigation`：8/8 passed。
3. `frontend/node_modules/.bin/tsc.cmd --noEmit`：passed。
4. `npm.cmd run identity:check`：passed，manifest match，dirty paths 为空。
5. `npm.cmd run build`：passed，5264 modules，18.44s；仅保留既有 chunk size warning。

测试覆盖公共 GET 正常/缓存/上游失败/过期/盘口缺失/非法输入、read-only 下 Demo GET/POST 全拒绝、keyring/private client 毒丸、未知 health fail-closed，以及原 operator runtime 兼容。

## Touch set、产物与未放行项

producer 13 个路径保持逐字不改；integrator 只新增：

- `docs/operations/btc-readonly-workspace-integration-20260923.md`：本独立审查报告。
- `.agent/handoffs/BTC-READONLY-WORKSPACE-INTEGRATION-20260923/integrated-btc-readonly-workspace-integration-20260923.json`：append-only 集成事件。

没有生成或改写 data、artifact、manifest、ledger、replay、runtime latest 或年度评估。生产 BTC runtime root 缺失/503、17 个历史无效 handoff 与暂停中的 2960/8760 年度产物均保持原状，不属于本票阻断，也不据此宣布全仓通过。

正式发布仍需在 registered main 做非 fast-forward 集成，确认 rollback tag 指向 base，只通过现有 canonical 8765/3000 launcher 以 `research_readonly` 启动，并由主会话完成 `/crypto` 浏览器验收。浏览器验收前，本票只达到提交态 `quality_checked`，不是 promotion evidence。

所有安全旗标保持 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。

## 治理证据

- 已读：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator profile、`research_readonly_release.md`、delivery risk policy、quant-agent-preflight、quant-agent-handoff。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 原始事故日志未读取；未访问 secret、private、broker、order 或 live endpoint。
