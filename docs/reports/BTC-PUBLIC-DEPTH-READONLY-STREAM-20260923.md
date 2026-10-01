# BTC 只读公共盘口实时流修复

- Role: `super_developer`; ticket: `BTC-PUBLIC-DEPTH-REALTIME-REPAIR-20260923`.
- Change risk: `demo_transport_hotfix`; gate impact: `none`.
- Base commit: `05d37042f4ea2f5b25708ceb77b8bc6acd52ee17`.
- Producer branch: `agent/super_developer/btc-public-depth-realtime-repair-20260923`.

## 根因与修复

当前 `research_readonly` 页面只允许公共 REST 读路由，前端又把 `publicStream` 限定为 runtime；硬编码的 Demo SSE 路由在只读模式会被 423 拦截，因此盘口只能诚实地显示“推送断开 · 2 秒轮询”。

本次新增独立的 `/api/research/btc/public-market/stream` 公共 SSE 路由，复用已有内存、无凭证的 `BtcPublicMarketStreamHub`，并将只读前端切换到该 path。运行模式仍使用原 Demo SSE 路由；模式未确认时不启动任何行情请求或流。

## Touch set

- `backend/app/api/btc_public_market.py`
- `backend/app/api/app_factory.py`
- `backend/app/core/backend_access_policy.py`
- `frontend/src/workspaces/crypto/workspace-access.ts`
- `frontend/src/workspaces/CryptoWorkspace.tsx`
- `frontend/public/frontend-identity.json`
- `tests/api/test_btc_public_market_readonly.py`
- `frontend/scripts/test-btc-readonly-workspace.mjs`
- 本报告

## 验证

- Failure-first：新增只读 stream allowlist/route/UI 断言在修复前失败；修复后通过。
- `PYTHONPATH=<registered-main>; py -3 -m pytest tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_okx_public_display_stream.py backend/tests/test_btc_demo_runtime_service.py -q`：`76 passed`。
- `PYTHONPATH=<registered-main>; py -3 -m pytest backend/tests/test_backend_research_readonly.py backend/tests/test_research_readonly_views.py -q`：`52 passed, 2 skipped`。
- `node frontend/scripts/test-btc-readonly-workspace.mjs`：通过。
- `node frontend/scripts/test-btc-public-depth-ux.mjs`：通过。
- `npm.cmd run lint -- --pretty false`：通过。
- `npm.cmd run build`：通过；保留既有大 chunk warning。
- `node frontend/scripts/update-frontend-identity.mjs` 后运行 `node frontend/scripts/check-frontend-identity.mjs`：manifest match，fingerprint `4ffdfe35e739997a61676ab6b87ed9a7ffd8dba3f7e5db21cb653de64ec75ad1`。
- `git diff --check`：通过。

## Demo safety attestation

只读 SSE 仅订阅 OKX public `trades`/`books5` 展示数据；不读取凭证，不访问 private/order/live endpoint，不创建 Demo runtime，不写策略、风控、OMS、ledger、数据库或持久 artifact。`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw` 仍为 `false`。公共网络不可用时继续显示 stale/reconnecting/REST fallback，不伪造实时状态。

## Canonical acceptance

- 注册 `main` 当前 HEAD：`99e353b570c5c1366e0b319759eff047c515adcf`。
- `GET /__backend_identity` 与 `GET /__frontend_identity` 均返回 `canonical=true`、`runtime_stale=false`，且 source/main HEAD 一致；前端 fingerprint 为 `4ffdfe35e739997a61676ab6b87ed9a7ffd8dba3f7e5db21cb653de64ec75ad1`。
- backend `GET /api/research/btc/public-market/stream` 以 `200 text/event-stream` 持续返回 `status=live` 公共事件；6 秒样本 `82` 个事件、`55` 个不同 sequence，`public_only=true`，private/order endpoint 均为 `false`。样本命令因 `--max-time` 到期返回 curl 28，属于预期停止。
- Playwright `/crypto` 页面显示 `实时推送` / `实时五档`；盘口序号在约 5 秒内由 `341405811570` 变为 `341405913363`，确认 UI 正在接收变化中的公共 SSE，而非静态缓存或仅 2 秒 REST 轮询。
- 浏览器仍显示研究只读、账户未接入、策略/订单/实盘控制关闭；网络或上游不可用时保留 stale/reconnecting/REST fallback，不伪造实时状态。
