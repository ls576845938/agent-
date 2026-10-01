# BTC 研究只读工作台：423 与控制契约误报修复

- 票据：`BTC-READONLY-WORKSPACE-FIX-20260922`（9 月 22 日开始，9 月 23 日继续）。
- base：`a2bbae85077bc4a580e5d3915648669308e31996`；角色：主会话按 super_developer 写职责实施。
- 工作树：planner 创建的专属 sparse 工作树；未在 registered main 修改业务代码。
- 风险分类：`research_readonly_release`，须独立审查及 integrator 验收；上限 `quality_checked`。
- 用户明确授权：公共行情 GET（K 线、盘口、报价）独立审查、只读模式修复、仅发布审定改动；不开放 Demo 控制、账户读取、下单或交易权限。

## 根因与边界

正式后端健康检查确认 `research_readonly / read_only=true / controls_disabled=true`。
原 BTC 页面忽略此模式，启动 Demo catalog/status/operator/klines/public market 轮询及 SSE。
旧请求确定返回 `423 / route_not_reviewed_for_readonly`；Demo 路由在此模式根本未挂载。
因此这不是通过重试或放行整个 Demo 命名空间能解决的网络故障。

本票只新增两个公共展示 GET：

- `/api/research/btc/public-market/view`：固定 BTC-USDT-SWAP、白名单周期、2–300 根 K 线、五档盘口。
- `/api/research/btc/public-market/ticker`：同一标的公共报价。

复用既有 credential-free `OkxDemoPublicMarketClient`，不改该客户端或 Demo 装配。
上游限定 unsigned GET `/api/v5/market/ticker`、`/candles`、`/books`，没有私有客户端、密钥、WS/后台订阅或持久写入。
访问策略仅追加上述两个完整 GET 路径；原方法拦截、认证、Demo/private/operator/订单边界均不变。
这属于经明确授权的公共研究读取面增补，不修改鉴权算法、运行能力、交易权限或治理规则。

读取使用最多 32 项内存缓存及单飞锁。失败时无缓存为 503，有缓存明确 `stale`；不会回填模拟行情。
缺失盘口不会补造；报价或盘口时间过旧不会声明为实时。
公共行情始终 `strategy_signal_compatible=false`，不得成为运行信号、成交或账户事实。

## Touch set 与职责

- `backend/app/api/{app_factory,btc_public_market}.py`：挂载独立只读路由，不构造 Demo 服务。
- `backend/app/core/backend_access_policy.py`：仅新增两个精确公共 GET；未经审查路由仍 423。
- `backend/app/services/btc_public_market_view.py`：公共展示、缓存与缺证/过期状态。
- `frontend/src/App.tsx`、`workspaces/CryptoWorkspace.tsx`、`workspaces/crypto/{workspace-access.ts,demo-operator-v2.ts,DemoTradingConsole.tsx}`：读取模式、禁止无效轮询、只读边界文案、研究证据入口；模式未知仍停止请求，旧 Demo V2 授权算法不变。
- `frontend/scripts/test-btc-readonly-workspace.mjs`、`tests/api/test_btc_public_market_readonly.py`：失败优先与隔离/兼容回归。
- `frontend/public/frontend-identity.json`：仅按既有 `identity:refresh` 派生版本指纹。
- 本说明及本票 `.agent/handoffs/`：提交态交接。

main 上述路径初始全部 clean；工作树无他人 dirty。其他任务修改及 17 条既有无效历史 handoff 不覆盖、不修复，不据此宣布全仓治理通过。
`node_modules` 仅以 junction 复用本机现有依赖；构建在本工作树，不启动任何工作树预览服务。
暂停中的 `2960/8760` 年度运行、账本、恢复点、manifest 和历史证据均未修改。

## 验证记录

1. 失败优先前端：原 hook 忽略 `enabled=false`，实际发出 11 次 Demo GET；新增测试明确失败后修复。
2. 失败优先后端：两个新公共路径原策略均拒绝，2 个断言失败后仅增补明确路径。
3. `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_okx_public_display_stream.py tests/agent_governance/test_research_release_policy.py`：57 passed。测试环境固定 research_readonly、Demo 控制 false、fixture fallback false。
4. 八组 Node 回归：readonly workspace、operator-v2-contract、operator-cleanup、operator-attempt-state、account-facts-view、missing-evidence、public-depth-ux、chart-navigation 均 passed。包含真实 hook handler、只读 SSR、未知账户不得渲染空仓/零成交。
5. `tsc --noEmit`：passed。初次发现本仓 JSX shim 要求显式 key 类型；仅补本组件可选 key 后复跑通过。
6. `vite build`：passed（46 秒，既有大 chunk 警告保留）；只构建，不启动服务。
7. 用户授权后的公共网络读：真实 OKX 返回 300 根 1m K 线和买卖各 5 档；`stale=false`，private/order endpoint used 均 false。仅网络读取，不保存市场数据。

尚未在本说明阶段执行：main 合入、正式前后端重启和浏览器验收。不能把源码测试通过称为页面已经修好。
独审必须覆盖全部 diff、两个读取入口、无 Demo 构造、无密钥/账户/订单、未知模式及旧控制合同兼容。
正式发布须保留 main 回退点，指纹匹配，以 research_readonly 通过 canonical 8765/3000 验收；页面须显示真实图表与盘口，以及“当前为研究只读模式／运行控制未开放”。

## 规则与未放行项

已读：quant-agent-preflight、quant-agent-handoff、quant-gate-evidence-review、knowledge README/non-negotiables、shared/super_developer/architect playbook、research_readonly_release、delivery_risk_policy、Playwright skill。
catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
命中：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、GOV-PROMPT-001、GOV-WINDOWS-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001。
原始事故日志未额外全文读取；本票不消费未提交上游。

Demo control、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 均保持 false。
缺失的生产 BTC 运行证据仍可返回 503；账户、保护单、私有观察仍未接入，不能伪装健康。
不重训、不跑年度评估、不改策略/仓位/风险/OMS/保护/账本，不启动 M3/M4。
