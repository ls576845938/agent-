# BTC 真实候选固定窗口数据规格（2026-09-30）

## 边界

- 仅 OKX 官方 public REST；不读凭证，不访问 account/private/order/live。
- 不修改原 collector、通用 schema、策略、风控、OMS 或账本。
- 结果只能标记 `quality_checked`；manifest/handoff 不解锁 promotion、paper 或 live。

## 冻结时间语义

- 决策起点 `T0=2026-06-16T01:00:00Z`，48 个决策小时为 `[T0, 2026-06-18T01:00:00Z)`。
- 分钟 open-time 区间固定为 `[2026-06-15T23:59:00Z, 2026-06-18T03:00:00Z)`，trade/mark/index 各 3061 条。
- 只接受 `confirm=1`；`available_time=open_time+60s`；三类序列必须逐分钟完整配对。
- 任一缺失、重复冲突、错币种、错时间或边界/相邻间隔大于 90 秒都阻断；不插值、不前填、不换窗。
- 末尾只为延迟执行/核账，不是新决策。
- 历史 `available_time` 为 bar-close 重建假设，不是当时网络到达回执。

## 稳定文件合同

- `trade_1m.csv`：`BTC-USDT-SWAP` 成交 K 线，包含 `volume`。
- `mark_1m.csv`：`BTC-USDT-SWAP` mark K 线。
- `index_1m.csv`：`BTC-USDT` index K 线。
- `funding_events.csv`：六个决策窗内结算事件，只含 rate/time/source/id，不含 amount/cash/settlement mark。`2026-06-16T00:00:00Z` 是 T0 前界，不收费。
- `dataset_contract.json`：冻结窗口、可见性假设、资金费估值政策和已绑定 OKX public instruments 合约快照。交易所限制字段命名为 `maximum_market_size_contracts`，不使用容易被误解为策略权限的 `maximum_absolute_contracts`。shared manifest v1 不允许未知顶层键，因此快照作为 manifest `files[]` 中的哈希文件交付。
- `quality_report.json` 和 `raw/**/page-*.json`：保留实际抓取时间、请求参数、原始响应 payload 及 canonical payload SHA-256。

## 已绑定来源

- 小时数据 manifest SHA-256：`6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9`。
- 15 文件 aggregate SHA-256：`3a61fc915da66994294113cc7b2334a1da4c0e08bccf428a743564c863c8d680`。
- funding CSV SHA-256：`ba745f622ff9753ecd6b0a7a828ba308cebcc151c22c5b9424ed9c12de324d19`。
- instruments snapshot SHA-256：`1a3be93ab5be07d8d0625ff37c077a461cba075876e44e8517266c9a28e336e8`；2026-07-30T11:45:48Z 实际抓取，`ctVal=0.01 BTC`、`settleCcy=USDT`、`lotSz=minSz=0.01 contracts`、`maxMktSz=35000 contracts`。该 7 月快照不是 6 月 PIT 生效证据，只能标为“冻结工程合约假设”；交易所最大市价单数量也不是业务风控许可。

## 资金费

六个事件为 2026-06-16 08:00/16:00，2026-06-17 00:00/08:00/16:00，2026-06-18 00:00 UTC。数据层不预填 cash。没有交易所实际结算 mark，因此估值规则固定为 `minute_close_sampled_valuation_not_exchange_actual_settlement`。
