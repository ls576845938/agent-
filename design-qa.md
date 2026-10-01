# Strategy Workbench PTrade Fidelity — Correction-04 Visual QA

## BTC-CRYPTO-STRATEGY-EDITOR-BACKTEST-FLOW-01 — Producer 设计 QA

### 参考输入与实现范围

- 参考图 1（研究草稿编辑器）：`C:\Users\李烁18353780778\AppData\Local\Temp\codex-clipboard-1d34cda9-08e2-4a9a-ad3d-b21379ef1005.png`。
- 参考图 2（配置并启动回测）：`C:\Users\李烁18353780778\AppData\Local\Temp\codex-clipboard-bdc4accc-a9ba-454a-9f6d-8473c37dd8f6.png`。
- 参考图 3（策略结果概览）：`C:\Users\李烁18353780778\AppData\Local\Temp\codex-clipboard-209d9326-f1f9-402e-9ccc-344a7f93eaa3.jpg`。
- 目标 viewport：`1440×900`；本阶段未启动前端服务，未访问任何真实 endpoint。
- 实现路径：`frontend/src/workspaces/crypto/CryptoStrategyEditor.tsx`、`crypto-strategy-editor.css`、`StrategyTesterReport.tsx`、`CryptoWorkspace.tsx`。

### 交互/安全核对

- 策略下拉来自 OKX Demo catalog；Demo 运行候选与研究回测候选保持独立。
- 编辑器只保存浏览器本地草稿；草稿与 canonical source 不一致时，开始与确认均 disabled/fail-closed，并明确提示先重置或未来建设受限 DSL/sandbox。
- canonical source 通过 immutable strategy version 后仅调用 `/api/research/btc/strategy-versions/{version}/backtests`；不 `eval/exec`，不调用 Demo/private/order/live/transfer/withdraw。
- 配置弹窗只启用现有受控接口支持的区间、初始资金与策略身份；方向、标的、周期、杠杆、仓位、费用、滑点、复利等不受当前接口控制的字段以 disabled + 真实说明呈现。
- 提交/计算/加载结果/完成（或失败）使用服务实际生命周期，不显示伪百分比；结果只投影服务返回的 summary/chart，缺失字段保持空缺。
- 底部策略测试器 tabs 改为普通流布局，不再以 sticky overlay 遮挡主图或控制台。

### Failure-first 与可复核证据

- `npm --prefix frontend run lint`：通过。
- `npm --prefix frontend run build`：通过（Vite 5214 modules）。
- `git diff --check`：通过。
- `npm exec -- playwright test e2e/btc-backtest-workbench.spec.ts --config=playwright.config.ts --list`：列出 4 项；完整 mocked Playwright 未运行。
- 3000 端口当前由 registered main 的旧前端持有；按治理禁止从 detached producer worktree 启动页面，也不能把旧页面当本变更证据。因此 mocked Playwright、1440×900 implementation screenshot 与最终浏览器 QA 明确 `deferred_to_integrated_current_main`。

### P0 / P1 / P2

- P0：无已知安全边界回归；paper/live/private/order/real-order/transfer/withdraw/demo-start 均保持 false。
- P1：受控回测路径必须由 canonical source/version 证明驱动；草稿不能执行；unsupported fields 不可编辑。
- P2：集成主工作树后复核字体、间距、弹窗裁切、编辑器滚动与小屏堆叠；补充截图和完整 mocked Playwright。

final result: blocked (deferred_to_integrated_current_main)

## 比较输入

- 参考图：`C:\Users\李烁18~1\AppData\Local\Temp\codex-clipboard-ddababbe-17da-4e6b-baa2-a025fa400aa4.png`
- 实现图：`C:\Users\李烁18353780778\AppData\Local\Temp\quantstation-ptrade-fidelity-c4-visual\strategy-workbench-1440x960.png`
- viewport：`1440x960`
- 数据边界：所有 `/api/**` 均由离线 mock fixture 提供；未访问真实交易或行情端点。

## 独立视觉结论

- P0：无。
- P1：无。
- P2：仅存在非阻塞的字体、间距和标签视觉差异，不影响信息层级、可读性或安全边界。
- 三栏比例：左侧目录约 `13%`，中间策略定义约 `41%`，右侧分析与真实 mock 图表约 `46%`；三栏在同一 viewport 内保持稳定。
- 主图：`168` 根 mock candles；Donchian 线可由足量 candles 生成并展示。
- 成交量：后端未发布时明确显示“成交量未发布”，没有伪造 volume 数据。
- 交易标记：已对齐并显示 `2/2`，包含 entry/exit（mock BUY/SELL）标记。
- 分析面板：权益、回撤、交易 PnL、成本分解均在右侧同屏可见。
- 底部 dock：回测记录/交易明细等只读 tabs 位于 workbench 底部，未被 viewport 裁切。
- 中心区：`no source body` 明确诚实降级；页面没有伪造 Python 源码、fills 或 PnL。

## 交互与安全证据

- `frontend/e2e/strategy-workbench.spec.ts`：3/3 passed。
- canonical frontend identity：`source_head/current_main_head=7f9ef42bbd1840d63ef1ebc3a9623ec5e59f2ac6`、`canonical=true`、`runtime_stale=false`、`dirty_paths=[]`。
- 浏览器控制/console：定向 smoke 无前端 error；mock 请求全部 GET-only。
- 真实 backend 当前对 identity 读取返回 HTTP `409`；页面保持 fail-closed，不伪造真实数据，不将 live 状态描述为可用。
- 所有 promotion、paper、live、private、order、real-order 旗标继续为 `false`。

final result: passed

## BTC-OKX-PUBLIC-CHART-ORDERBOOK-UX-02 — Producer 阶段设计 QA

### 参考与范围

- 官方参考：<https://www.okx.com/learn/what-is-an-order-book-crypto>（Order book example）。
- 目标 viewport：`1440×900`。
- 本次仅改 `/crypto` 的公开、内存态 OKX public `trades + books5` 可视层；不读取凭证，不访问 private/order/live/transfer/withdraw，也不改变策略、账本或执行语义。
- 实现意图：在 K 线右侧固定 `260–300px` 订单簿，以 `Price / Amount / Total` 三列展示五档 asks/bids；中间显示当前形成中 K 线的最新价、方向和 spread；行内累计深度与底部买卖力量仅来自 books5 snapshot。

### Producer 可复核证据

- 形成中 K 线继续复用 `TradingViewChart` 既有 `candleSeries.update` / `volumeSeries.update` 增量更新，不使用 tick 触发全量 `setData`；公共 visual candle 永不标为 confirmed，策略/Donchian 仍只消费 confirmed completed 1h。
- 新增 mocked E2E：同一分钟三笔不同 trade 断言 forming candle 的开高低收及累计 volume；books5 同时刷新右侧盘口、最优 bid/ask、spread 和力量比例。
- `npm.cmd run lint`、`npm.cmd run build`、限定 `git diff --check` 已通过。

### 延后验证与限制

- `frontend/e2e/btc-demo-console.spec.ts` 的完整 mocked Playwright、`1440×900` 完整页和局部截图，只能在 fast-forward 后的 registered-main canonical frontend 上执行。producer worktree 依规不得启动前端；现有 `127.0.0.1:3000` 是未集成本次 UI 的 canonical HEAD，不能作为本实现的截图或通过证据。
- failure-first 基线已在该 canonical 页面复现：同一分钟 trade 会更新开高低收，但没有 `量 0.09`；producer 实现补充这一实时 volume 投影。最终截图、P0/P1/P2 结论和完整 Playwright 由 integrated current-main correction 追加。

### P0 / P1 / P2

- P0：无已知安全边界回归；所有 public/private/order/live 安全旗标仍为 false。
- P1：订单簿原在图表下方，交易终端信息层级不足；本提交移到图表右侧并加入五档累计深度、最新价与力量比例。
- P2：小屏下订单簿下移并提供展开/收起；canonical 截图阶段复核行高、裁切、键盘焦点与可读性。

final result: blocked (deferred_to_integrated_current_main)

## STRATEGY-WORKBENCH-VISUAL-POLISH-06 — Correction-01 收口

- source visual truth：`D:\vibe coding\Obsidian\量化系统\agent-\artifacts\ui-audit\strategy-polish-before-single-20260814.jpg`
- correction：`d7858164fc0ccf6cb17f3843712879d5e531a1bd`，仅将 `.strategy-workbench-dock-body` 的高度从 `calc(100% - 38px)` 对齐为 `calc(100% - 40px)`；未改变布局比例、数据、行为或交易语义。
- implementation screenshot：`C:\tmp\strategy-workbench-visual-polish-06\strategy-workbench-visual-1440x960.png`
- viewport：`1440x960`；离线 GET-only fixture，截图包含三栏、真实 mock K 线/Donchian、权益/回撤、交易 PnL、成本与底部 dock。
- correction 前 P1：dock body 越过 dock 边界，两个布局断言得到 `dock=false`；Correction-01 后目标 spec `4/4 passed`，该 blocker 已关闭。
- identity：最终 tracked change 后刷新 frontend identity；fingerprint=`ff0a756486611cc4e97262a67cc44efb2396aee3aa0d3a4cac0ff1559f21a38e`，canonical frontend；identity check/test/launcher check 通过，`runtime_stale=false`。
- 视觉与交互：字体、间距、颜色 token、选中/hover/focus、三栏比例和 dock containment 均通过目标合同；console 无前端错误，mock 请求保持 GET-only。
- live 边界：backend 仍为旧 `114c232b...`，identity/status GET 返回 `409 backend_runtime_main_drift`；页面继续 fail-closed，未伪造 live 数据。backend 未重启，artifact/read-model 不适用。
- 安全旗标：promotion、paper、live、private、order、real_order、transfer、withdraw、demo_start 全部 `false`。

final result: passed

## STRATEGY-WORKBENCH-PTRADE-FIDELITY-04 — Stage C 收口

### 比较输入与证据

- 参考图：`C:\Users\李烁18~1\AppData\Local\Temp\codex-clipboard-ddababbe-17da-4e6b-baa2-a025fa400aa4.png`
- 参考图补充：`C:\Users\李烁18353780778\AppData\Local\Temp\codex-clipboard-209d9326-f1f9-402e-9ccc-344a7f93eaa3.jpg`
- Stage B 实现图（1440×960）：`C:\tmp\strategy-workbench-ptrade-fidelity-04\strategy-workbench-1440x960.png`
- Stage B 实现图（1180×900）：`C:\tmp\strategy-workbench-ptrade-fidelity-04\strategy-workbench-1180x900.png`
- 机器证据：`C:\tmp\strategy-workbench-ptrade-fidelity-04\capture-evidence.json`
- 所有 `/api/**` 均为离线 mock GET；没有真实行情、交易、private、order 或 live 请求。

### 第一次独立 reviewer FAIL 的三项根因

1. 左侧树容器同时继承通用 `strategy-discovery-grid`，四个系统分类被错误排成多列，策略名和“历史回测”入口出现截断。
2. 中间 identity/evidence 表在首屏占据主体，真实 SourceDraftEditor 被挤到下方；代码行号出现双编号，编辑/保存/重置动作不在稳定首屏。
3. 1180 宽度右侧 performance body 使用 `overflow:hidden` 和过高固定行高，K 线/副图或底部 dock 被裁切。

### Stage B 修正

- 隔离树模式的通用多列 class，分类改为单列纵向布局，并允许选中策略名、说明及历史入口换行完整显示。
- 将 source editor 排到定义主体首屏，代码 viewport 固定 `sourceHeight=300`，使用单一手工行号列表，保存/重置按钮保持可见；identity/evidence/params 后置。
- 调整中等宽度 performance grid，取消外层裁切并保留 KPI、主 K 线、权益/回撤副图、成本/交易 PnL 与 dock 表头/记录行。
- 仅调整离线 mock fixture 的 marker/trade 时间索引至可见区间；生产 marker 对齐与真实数据缺失降级规则未改变。

### 第二次独立 reviewer 结论

- 独立视觉 reviewer：PASS；P0/P1 均无，剩余仅非阻塞 P2 视觉差异。
- 1440×960：`sourceHeight=300`；KPI、K 线、权益图、dock 与 dock row 均 `within=true`；canonical markers `2/2`，BUY/SELL 同屏。
- 1180×900：`sourceHeight=300`；KPI、K 线、权益图、dock 与 dock row 均 `within=true`；canonical markers `2/2`，BUY/SELL 同屏。
- 中心源码、历史回测与图表均遵守诚实降级；source/history unavailable 时显示 unavailable，不伪造 Python、fills、volume、PnL 或 benchmark。
- `frontend/e2e/strategy-workbench.spec.ts`：3/3 passed；TypeScript、Vite build、diff-check 通过。
- backend/artifact：沿用 immutable read-only history artifact，状态 `stale` / `research_only`；本票 `artifact rebuild not_applicable`，不得描述为 promotion ready。
- promotion、paper、live、private、order、real-order：全部 `false`。

final result: passed

## BTC-OKX-PUBLIC-CHART-ORDERBOOK-UX-02 — Canonical QA Closeout

### Reference, implementation, and viewport

- Official visual reference: <https://www.okx.com/learn/what-is-an-order-book-crypto> (`OKX_order_book_example.png`).
- Canonical implementation: `main@891fb27762a3805b9053b3be389d71bc3b96e73b`; frontend fingerprint `e33a16fed4a95ebc61b81f84bf2e341d9f315ea9967aac88502a8fc0c8d96759`.
- Implementation paths: `frontend/src/workspaces/CryptoWorkspace.tsx`, `frontend/src/workspaces/crypto/TradingViewChart.tsx`, `frontend/src/workspaces/crypto/PublicDepthPanel.tsx`, and `frontend/src/index.css`.
- QA viewport: `1440×900`. Full-page and focused evidence: `C:/Users/李烁18353780778/AppData/Local/Temp/btc-okx-public-chart-orderbook-ux-02-final-focus.png`.
- Canonical backend identity: HTTP `200`, `canonical=true`, `runtime_stale=false`, profile `demo_quasi_live`.

### Functional and safety evidence

- Mocked `frontend/e2e/btc-demo-console.spec.ts`: `20/20 passed`.
- `market-view` is `public_only=true`, `private=false`, `order=false`; no private, order, paper, live, transfer, or withdraw capability was enabled.
- The primary chart shows `Order Book LIVE` to its right: `Price / Amount / Total`, red asks, green bids, midpoint, spread, cumulative row depth, and buy/sell ratio are all visible without moving the book below the chart.
- Public tick display remains visual-only: forming bars do not become confirmed strategy input and do not alter strategy, risk, ledger, or execution state.

### Live visual sampling

- Sample A: summary `63,571.9`; forming OHLCV volume `3390.96`.
- Sample B, 3.5 seconds later: timestamp advanced; forming OHLCV volume `3479.73`; order-book cumulative quantities, buy/sell ratio, and sequence all changed.
- This confirms the visible forming candle and depth panel receive advancing public-stream updates rather than presenting the completed-bar baseline as real-time.

### P0 / P1 / P2 closeout history

- P0: none. Public-only boundaries remained intact; all trading-related permissions remain false.
- P1: corrected the non-terminal layout by placing the five-level book beside the chart, with a stable chart-to-book hierarchy and readable market midpoint/spread.
- P2: corrected the pre-merge detail issues in the closeout chain: book persistence during stream status changes, chart canvas containment, 1440px chart width, terminal-formatted depth prices, explicit chart-mode user intent, public tick versus REST ordering, subscriber lifecycle, new-bucket forming bars, epoch update timestamps, and replayed-trade deduplication.

final result: passed

## QS-STRATEGY-MODULES-MARKET-MAP-01-CORRECTION-01 — Final Design QA Closure

### Reference, implementation, and evidence

- Reference target: `C:\Users\李烁18353780778\.codex\generated_images\019facb5-9817-7b10-a3ac-e08bdea521e8\exec-49e95103-31ac-4ff5-af7f-23a4bb0f2a69.png`
- Canonical implementation: `C:\Users\李烁18353780778\.codex\visualizations\2026\07\29\019facb5-9817-7b10-a3ac-e08bdea521e8\strategy-modules-final-1488x1058.png`
- Side-by-side composite: `C:\Users\李烁18353780778\.codex\visualizations\2026\07\29\019facb5-9817-7b10-a3ac-e08bdea521e8\strategy-modules-design-qa-composite.png`
- Current main under review: `e39ade587c4fdf3d92597bfe46d31be7336589cc`
- Viewport: `1488x1058`
- Canonical evidence: Playwright `e2e/strategy-modules.spec.ts` `6/6` passed; left panel `477.265625px`, right panel `778.734375px`, measured ratio `0.37998855`; US/CN switching passed; all seven modules passed; POST count `0`; console errors `0`.

### Fidelity

- Existing global shell is intentionally preserved per the user requirement.
- Strategy-module information architecture, market/family controls, seven-module map, and right-hand detail composition match the reference target.
- Desktop composition is the measured `38/62` split; the four state cards, four process nodes, results section, and evidence-gap section remain present and aligned.
- Existing dark tokens, icon language, borders, and focus treatment are retained; no new image or hand-drawn SVG asset was introduced.

### Interaction and state

- `/strategy-modules` is the canonical route.
- Crypto, US, and CN market switching and strategy-family switching are functional and local.
- All seven module cards update the detail state and passed the canonical interaction contract.
- The surface is read-only with `POST 0`; no trade, private, live, transfer, withdraw, or broker action is exposed.

### Responsive

- The `760x900` responsive contract stacks the panels and passed in Playwright.
- No overlap or loss of the primary interaction was reported in the canonical run.

### Accessibility

- Interactive controls use native button semantics and tab-list/tab roles.
- `aria-selected`/`aria-pressed` state contracts are retained for selected controls.
- Existing keyboard `:focus-visible` treatment remains in place.
- This closure records tested semantics and does not overclaim accessibility beyond the supplied evidence.

### Known non-issues

- This is a static research map and does not fabricate real-time, backtest, fill, PnL, or promotion metrics.
- It is not a trading page; backend and Demo runtime were not modified.

### Actionable findings

- P0: none.
- P1: none.
- P2: none.

final result: passed
