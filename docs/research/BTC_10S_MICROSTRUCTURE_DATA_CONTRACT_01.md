# BTC-10S-MICROSTRUCTURE-DATA-CONTRACT-01

## 结论

本票据建立的是 **10s/30s/60s 微观结构研究准入合同**，不是 legacy promotion gate 的替代品。固定 30 natural days 不再属于本合同，但现有短片段仍因信息量、时间覆盖、对齐、成本和字段缺失而判定：

> `blocked_insufficient_information / no family-horizon research ticket authorized`

没有运行模型、GA、回测、paper 或交易。`promotion/paper/live/private/order/real_order/transfer/withdraw=false`。

## 冻结预测目标与阈值

统一预测目标为 `future_10_30_60s_cost_adjusted_return_distribution`，首个执行基线固定为 `taker_only`。每个 horizon 均要求：

- non-overlap eligible labeled windows `>=1000`；
- autocorrelation-adjusted ESS `>=500`；
- joined coverage 和 future-label availability 均 `>=99%`；
- 六个 UTC 4h 桶各有 `>=100` 个独立 60s window；
- 3×3 volatility/liquidity regime 每适用格 ESS `>=50`；
- receive lag p99 `<=500ms`，trade/book alignment p99 `<=250ms`；
- duplicate、out-of-order、unrecovered sequence gap、crossed、one-sided 均为 `0`；
- reconnect 后必须 snapshot reset，gap/resync 周围 embargo `>=60s`；
- spread、fee、depth/impact 和分层稳定性样本完整率 `>=99%`。

这些阈值预注册于 `BTC_10S_MICROSTRUCTURE_DATA_CONTRACT_01_PREREG.json`，不得为当前数据事后放宽。

## Immutable source 评估

所有输入仅通过 `4f3139431bb801f71f0bca9bbb0f69e4febdb8a4:<Git manifest>` 和 `shared_data.py` resolver 读取，并对 physical manifest 与所有文件执行严格 SHA 校验。没有使用 SQLite、latest、glob、staging 或 repo-local artifact fallback。

| Dataset/version | Resolver | 主要证据 | 研究限制 |
|---|---|---|---|
| `btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7` | `resolved_verified` | 2,000 trade rows、1,073 unique IDs、927 duplicate-ID rows；20 个 REST BBO/depth snapshots；87s | 重复 history snapshots，不是 ordered L2；2,580 行负 receive lag；有效 p99 12,963ms |
| `btc-okx-public-evidence-20260728T081955Z-main1c2d545c-corr1` | `resolved_verified` | raw WS file bytes=0、message count=0 | 没有 WS L2 观察 |
| `btc-okx-l2-observer-1d-00000002-20260729t035023327336z` | `physical_version_missing` | Git manifest aggregate `a0609e1a…e45856` | 无原始字节，禁止用其他短段或重采样冒充 |
| `btc-okx-real-l2-attestation-20260728T232947Z-e3471caf3-timestamp-precision07-quality1` | `resolved_verified` | 57 records、3 snapshots、54 updates、11.6845514s；sequence gap=0；reconnect/resync=2/2 | two-sided coverage 41.6519%；receive lag p99 776ms；无 trades |

对缺失版本的恢复核验仅使用其 Git manifest 精确 file SHA、已提交 evidence 和同 dataset 的 immutable versions。未找到任何可证明字节相同的副本，因此没有恢复、没有发布新 manifest，也没有网络重采。

## 字段语义与 family 隔离

- `trade imbalance`：需要 unique tick trade IDs、exchange timestamps、aggressor side 及同版本 BBO。
- `order-flow imbalance (OFI)`：除上述条件外，还需要价档/队列变化和 ordered L2 updates。trade imbalance 与 OFI 不得混称。
- `micro breakout`：需要 trades、two-sided BBO/L2 及 volume/depth shock。
- `sweep/absorption reversal`：需要 trades 与 ordered L2 snapshot/update/recovery 在同一可对齐版本内。
- `liquidation cascade/recovery`：只在该 family 额外要求 time-aligned OI 与 liquidation events；该缺口不传导到前三类。
- `maker/queue`：本轮 `not_applicable`。visible depth 不是 queue position，不能用于 maker fill claim。

不能把 REST trade/BBO 与另一短段 WS L2 在时间不重合时跨数据集拼成“已对齐”。当前 `trade_ordered_l2_joined=false`。

## 正式 family × horizon 结论

| Family | 10s | 30s | 60s | 关键阻塞 |
|---|---|---|---|---|
| trade-imbalance continuation | blocked | blocked | blocked | eligible labels/ESS=0、重复交易、coverage/latency/cost 不足 |
| micro-breakout | blocked | blocked | blocked | 同上；缺持续、可成交的 aligned depth shock 样本 |
| sweep/absorption reversal | blocked | blocked | blocked | trades 与 ordered L2 未同版本对齐 |
| liquidation cascade/recovery | blocked | blocked | blocked | 上述阻塞，另缺 time-aligned OI 和 liquidation events |
| maker/queue | not_applicable | not_applicable | not_applicable | out of scope；taker-only baseline |

87s 最大 verified span 对应的原始 potential non-overlap windows 仅为 10s=`7`、30s=`1`、60s=`0`；由于缺少完整 cost-adjusted future label 链，eligible labeled windows 与 ESS 三个 horizon 均为 `0`。六个 UTC 桶、weekday、3×3 regime 均未形成有效覆盖。

## Immutable artifact

版本：`official-81024c156dd6`

稳定相对位置：`research_artifacts/btc-10s-microstructure-data-contract-01/official-81024c156dd6/`

- report semantic SHA: `8b05a33fbb0fcf03f2642dcb2316ad0b9e7c3e2b67bc056a007e19a43960d534`
- report file SHA: `dd92225a9cbe142c6aa907b7b873302d125cc957277440c58b8aa47f2fdc06bb`
- contract-lock semantic SHA: `a59082dbb07007c14360e923ba295da8c01d1e3071546479c14ddfd2f0a6e83b`
- contract-lock file SHA: `9bc45ca33b5904da8855a4ab90c764ef335792818445689f318fc7f3314a4ad6`
- artifact-manifest file SHA: `f98deca3b5d6bd78293196d3ea3aff737ff1836a5ad8c07ae3871a0964cbd54b`
- aggregate SHA: `4fb37192e9e6cace9d78a7399e26e76f9a7489fdd28e981489afaa26eab5c515`

artifact 路径不可覆盖，也没有 `latest` pointer。

## 与 execution/promotion 的独立阻塞

研究数据准入不能解决以下 execution evidence：

- venue-hosted protective stop；
- mark/index/funding runtime parity；
- queue/partial-fill 模型与证据；
- fill-position-cash ledger；
- adverse selection；
- current-HEAD promotion artifact。

即使未来某个 family+horizon 数据行成为 `ready`，也只允许开启相应的离线模型/GA 研究票据，不自动允许 paper、promotion 或 live。
