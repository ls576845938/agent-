# BTC Public Data Closure 01

## 范围与结论

本报告对应 `BTC-PUBLIC-DATA-CLOSURE-01`，绑定 current HEAD `b5ac9b45ff47136aaef8919bedd11ab030f4bffd`。只引用已存在的 external immutable shared-data；未下载、复制或改写 `data/market_data.sqlite`，未创建新的物理数据版本。最高 readiness 为 `quality_checked`，不是 research-ready、backtest-ready、paper-ready、live-ready 或 promotion evidence。

机器可读 attestation：`.agent/data_manifests/BTC-PUBLIC-DATA-CLOSURE-01/btc-public-data-closure-01.json`。

## Immutable 依赖

| 类别 | dataset version | Git manifest SHA-256 | physical manifest SHA-256 | aggregate SHA-256 | 覆盖/解析 |
| --- | --- | --- | --- | --- | --- |
| Binance 5m immutable | `btc-kline-binance-btcusdt-20260725T235959999Z-decimal18-v2-src11278c46327f-main97d6448b` | `7f09a7e171813cabf4f6cc9d7eab93db4903da6393f03d983b6be71324462666` | `8a9511e065f7d2e76d88eda02b9e277706d7cb0908971acc6be45336a7e3690c` | `e000f25f293c688a14f1cbe43d1eb0e4ef182f25c264e8dea8d90578cc9cd8a4` | 2024-01-01 至 2026-07-25；完整 hash resolve |
| OKX v3 public market | `btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7` | `adb63e38565d4f40e19f30eb196de7ee1807667d5511b83761e6bd513884e804` | `8ca8d695966553d08c22650739a7f252842c67e3bf3e7e97ea0354e65e250a68` | `1fcd9cc02adbaca7c77bf97a4af021deef231916bd7d650768af654756fe5d24` | 30 日 public REST；resolved |
| OKX public WS/L2/funding | `btc-okx-public-evidence-20260728T081955Z-main1c2d545c-corr1` | `ea87a31cfd15ab134803750c3c6e52035d3d1d8cc2594731afd6c0c75bb37694` | `dcfea81bf409f7474ea9393e38ccaf9585c7ab0389dbbfe12f434401971132b3` | `01279be2ff6fb86897660e2fc91dd32aee1ed82422a48d6cb81553a064e13003` | funding resolved；WS 在订阅 ack 前断开 |
| timestamp-aligned observer latest | `btc-okx-l2-observer-1d-00000002-20260729t035023327336z` | `2e174ffa320e05b445e0e585779029b3d59e29971b8518fbcfdf0e33980bf3b7` | 缺失 | `a0609e1aa2b55b0d00cedba9481e4465edff95bd352e06a6fd30a4683fe45856` | physical version 缺失，结构化 blocked；不伪造 fallback |
| timestamp-aligned blocked audit fallback | `btc-okx-l2-blocked-audit-20260726T154045300Z-main97d6448b` | `8ea79488adf391698622caab03fe1eec4cc8151f796c68b4313ecd94d4015de1` | `c85e53d4b7ba8890e460ea5e2ea7dca6af855c1755c26c9ae1f61ed4cf47e725` | `62b85f26153f21c42452a44d39bc469be305d0322c097a3f6a42be8b3d7e51f5` | 仅 blocked audit；resolved |
| OKX real L2 attestation | `btc-okx-real-l2-attestation-20260728T232947Z-e3471caf3-timestamp-precision07-quality1` | `43516667e0b38f99f49af48b5c157a9e0e45fb892f1f1e64f596da6dc37af888` | `5cb4043056dbad8e194892c22474ccb34cca488b87c5b9f3b6f450218da2b8d9` | `965bfbca8ae9de8f7f7558896ac001e6291221307c12038e7165620e5334119f` | 57 条 books message；resolved |
| OKX public swap research bundle | `btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-src6cea196b4-corr1` | `6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9` | `2cab16deb4c7bc18dca35de987e3405b749ca7a5e0ca0617ff7ccb00d953dd52` | `3a61fc915da66994294113cc7b2334a1da4c0e08bccf428a743564c863c8d680` | 2025-12-21 至 2026-07-30；resolved |

物理版本均位于 external root `D:\vibe coding\Obsidian\量化系统\shared-data`；没有覆盖既有 manifest 或 latest pointer。

## Binance 5m 质量与增量窗口

immutable 5m 文件 97,280,364 bytes，SHA-256 `d1c6b3da7c051d39906090189f09cbbf1d22fefa55d2c9dc01c15a33c69dd261`。只读 streaming 审计：269,856 行、全部 finalized、in-progress=0、重复 event time=0、非法 OHLCV=0、非法 UTC=0、5m continuity gap=0。首行 `2024-01-01T00:04:59.999000Z`，manifest coverage start 为 `2024-01-01T00:00:59.999000Z`，两者差异保留为 manifest/first-row 事实；末行 `2026-07-25T23:59:59.999000Z`。

以 `2026-05-12T23:59:59.999000Z` 为 exclusive cutoff，已有后续增量 21,312 行，起点 `2026-05-13T00:04:59.999000Z`，终点 `2026-07-25T23:59:59.999000Z`，原始 JSONL slice SHA-256 为 `518859075e988982c95a8712c1516aa97863ccb262ab250b7abff0f3ada02cbe`。这只是数据可用性结果，不运行 GA、不调参、不产生 promotion 结论。

## OKX public 合同矩阵

- venue/instrument 由 public snapshot 证明为 OKX `BTC-USDT-SWAP`；metadata 显示 linear SWAP、USDT settlement、tickSz 0.1、lot/min 0.01，但不构成账户或权限证明。
- v3 与 swap bundle 存在 public mark/index 与 funding 观测；funding 覆盖不均匀，swap bundle 明确从 `2026-04-29T16:00:00Z` 起可用。
- v3 REST L2 alignment 有 20 个 capture sequence、2,000 book rows、2,000 trade rows、capture gap=0；没有证明 exchange sequence/checksum 或 queue position。
- WS/funding 批次有 91 条、8 小时间隔的 funding rows，但 public WS 在 subscription acknowledgement 前 connection reset，book message=0；server-time offset 4,641.123ms，高于 1,000ms threshold。
- real L2 attestation 有 57 messages（3 snapshots、54 updates），sequence gap=0，2 次 reconnect/2 次 resync，unrecovered gap=0，two-sided coverage=41.651865427%；observed history 仅 4.866247 秒（0.000056322 天），不满足 30 natural days。
- latest observer manifest 的 external physical version 缺失；resolved blocked-audit 仍明确 blocked，不被当作数据。
- public receive latency 与 depth snapshot 不是 order-to-fill latency、queue position、未成交订单、private WS 或 paper ledger 证据；liquidation history 未验证，open interest 仅 current snapshot/diagnostic。

## 关闭项与仍阻塞项

本次 closure 可确认：5m immutable version 已 resolve 且全文件 hash 验证；2026-05-12 之后尾部可用；5m finalized/continuity/duplicate/OHLCV 质量通过；public BTC-USDT-SWAP instrument、mark/index、funding samples 存在；已解析 public datasets 均保留 public-only、read-only、no-order/no-private guardrails。real L2 短样本仅证明 bounded sequence/reconnect recovery。

仍阻塞：latest observer physical version 缺失；sequence-valid L2 远少于 30 natural days 且 two-sided 不完整；execution-latency/queue/order-to-fill 模型缺失；private WS/fill/ledger 证据缺失；open-interest/liquidation history 不完整；一批 server-time offset 超 threshold；manual paper/live approval 缺失；本 closure 不是 promotion evidence。任何 public dataset 都不推断 paper fill 或 live permission。

## 验证与安全

resolver 使用 `py -3 tools/agent_governance/shared_data.py --repo-root <worktree> resolve --manifest <manifest> --shared-root D:\vibe coding\Obsidian\量化系统\shared-data`。六个 manifest 返回 `resolved`，latest observer 返回结构化 `blocked/shared_data_physical_version_missing`。定向 shared-data/kline/public collector/L2 合同使用 `-p no:cacheprovider` 和外部 basetemp：152 passed；`py -3 -m py_compile tools/agent_governance/shared_data.py` passed。

未读取或输出 API key、secret、token，未访问 private/order/live/transfer/withdraw，未调用 broker，未启动服务，未重建 artifact，未写 paper queue 或真实订单。`promotion_eligible=false`、`paper_or_live_unlock_allowed=false`、`private_endpoint_allowed=false`、`order_endpoint_allowed=false`、`real_order_submitted=false` 持续有效。
