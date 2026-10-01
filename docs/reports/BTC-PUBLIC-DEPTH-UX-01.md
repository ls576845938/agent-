# 公共盘口实时连接与中文展示修复

- Role: btc_developer; ticket BTC-PUBLIC-DEPTH-UX-01; change_risk=demo_transport_hotfix; gate_impact=none.
- Base: 04e60ea3cd7db9f1a07a6b5d06ea2d062796840a. Dedicated planner-created sparse producer, branch agent/btc_developer/btc-public-depth-ux-01.
- Touch set: backend/app/services/btc_public_market_stream.py; tests/contracts/test_btc_okx_public_display_stream.py; frontend/src/workspaces/crypto/{DemoTradingConsole.tsx,PublicDepthPanel.tsx,console-display.ts}; frontend/scripts/test-btc-public-depth-ux.mjs; frontend/public/frontend-identity.json; this report; ticket handoff.
- Initial scoped source dirty main/producer: clean. No unrelated files changed or other uncommitted work consumed. Existing unrelated artifacts/hooks preserved.

## 原因与修复

本地公共 SSE 返回 stale，ConnectionResetError / WebSocketAddressException，depth/trade 为空。Windows 系统有 HTTP 代理，进程没有 HTTP(S)_PROXY；websocket-client 未读取系统代理。失败优先测试证实 _new_connection 遗漏代理参数。

仅公共 display socket 使用 urllib 的系统/环境代理发现，并尊重 proxy_bypass；HTTP CONNECT 沿用已有配置，不改全局环境、不关闭 TLS、不接触私有连接或凭证。带认证或不支持的代理配置停止连接。沿该公共入口实测收到 trades/books5 订阅确认和多条真实盘口快照。

前端将运行版本、哈希、历史、时间戳等置于默认折叠的技术详情。风险提示保留中文说明与下一步，缺失记录不推断安全。原始诊断仍可展开，不改变任何操作授权判断。

盘口使用中文实时/断线轮询/过期标签及毫秒时间；只在流为 live 且有深度时展示实时。OKX books5 有变化时约 100ms 五档快照，并非每笔成交或 10ms 全量盘口。官方说明：https://app.okx.com/docs-v5/trick_en/#market-data 。未添加登录通道。

## 验证

- Failure-first: system proxy forwarding test failed before fix (1 failed / 1 passed); UI default-collapse AST assertion failed before fix.
- Python: main .venv/Scripts/python.exe -m pytest tests/contracts/test_btc_okx_public_display_stream.py -q: 16 passed (one existing Starlette deprecation warning).
- node frontend/scripts/test-btc-public-depth-ux.mjs: passed; verifies folded metadata, Chinese unknown/tripped guidance and real/fallback/stale labels.
- npm run lint: passed. npm run build: passed, 5221 modules, 1m36s; existing large-chunk warning.
- test-btc-demo-start-feedback.mjs, test-btc-operator-cleanup.mjs, test-btc-operator-attempt-state.mjs, test-btc-operator-v2-contract.mjs: passed. Harness uses mocks, no real private call.
- Local status before deployment: active=false, worker_alive=false, opening_allowed=false, cancel_only=true.
- Canonical-main restart, browser and deployed SSE verification pending at source commit; recorded separately in final acceptance, not inferred from unit tests.

## Safety attestation / governance

### 部署验收（2026-09-07）

主分支首轮部署 6529682cc，backend PID 8820 / frontend PID 21484；两个 identity 均 canonical=true、runtime_stale=false。公共 SSE 6 秒样本：37 events、32 个不同深度、sequence 338404191301 -> 338404197579、status=live、last_error_code 为空，private/order accessed=false。2625x1696 浏览器显示“实时推送”，技术详情 open=false、内部徽标不可见，风险提示为中文。HTTP 503 历史/只读观察投影缺失仍存在，不属于本票据修复范围。

浏览器发现仅指定 fractionalSecondDigits 会隐藏时分秒；追加显式 hour/minute/second 选项及回归断言。最终当前 HEAD 与窄屏检查在会话验收中给出，不将该首轮部署证据误标为新 HEAD。

No strategy, risk, order construction, private-WS reconciliation, ledger, security or live-permission modifications. No credentials read; no remote private/order endpoints or strategy start/stop actions called. Only public market sockets and local GET projections used. Frontend identity refreshed against committed sources. No schema, data manifest, ledger or promotion artifact rebuild.

Read: AGENTS, knowledge README/non-negotiables, shared_pitfalls, btc_developer_pitfalls, delivery_risk_policy, websocket_reconnect_gapfill, preflight/handoff skills. Browser verification uses Playwright skill.
Catalog: 127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c.
Active IDs: BACKTEST-COST-001, BTC-OMS-001, BTC-PERP-001, BTC-WS-001, DATA-BTC-FINAL-001, GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, REPLAY-ISOLATION-001, RESEARCH-HOLDOUT-001. Advisory GOV-PROMPT-001, GOV-WINDOWS-001.

Readiness quality_checked only. Fast-forward eligible under scoped demo_transport_hotfix policy; backend restart required. Promotion, paper_or_live, private, order, real_order, transfer, withdraw remain false. Existing startup/preflight and current-HEAD promotion blockers are not resolved by this display fix. Network availability remains external; fallback must remain visibly degraded.
