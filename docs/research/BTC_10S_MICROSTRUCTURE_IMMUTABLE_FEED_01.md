# BTC-10S-MICROSTRUCTURE-IMMUTABLE-FEED-01

## 边界

本票据新增一个与 legacy L2 history 平行的公共数据族：
`btc-okx-10s-microstructure-immutable-feed`。它仅用于 10/30/60 秒研究准入，
不修改 legacy 30 natural days promotion gate，不运行模型或 GA，也不解锁
paper/live/private/order。

数据流固定为：

`同一 OKX public WS connection 的 trades+books raw frames`
→ `既有 ordered-L2 sequence/checksum/reconnect validator`
→ `unique trades normalization`
→ `available_time/capture_sequence backward-only book join`
→ `immutable shared-data publication`
→ `exact committed Git manifest consumer`。

首个执行基线仍为 taker-only。`side` 被记录为 OKX public trades 的 aggressor
side；显式保守 research taker fee、spread 和可见深度 impact 分开保留。可见深度
不代表 queue position，maker/queue family 仍为 `not_applicable`。

## Failure-first baseline

精确 base `4432c18251e827487070f598161ef9cacbfc068c`：

- `git cat-file -e <base>:quant_crypto/data/immutable_okx_10s_microstructure_export.py`
  返回 `128`；新 exporter 不存在。
- `git cat-file -e <base>:scripts/run_btc_okx_10s_microstructure_immutable_feed.py`
  返回 `128`；新 runner 不存在。
- base evaluator 对未知 immutable dataset 只返回
  `verified_immutable_unparsed`，并固定
  `eligible_labeled_windows=0`、`trade_ordered_l2_joined=false`。

这是新增能力的基线，不伪造为已有函数的失败测试。

## 数据与时间语义

每条 trade 保存 `event_time`、`available_time`、`ingested_at`、
`capture_sequence`、`connection_sequence`、`monotonic_ns`、`trade_id`、价格、
数量、aggressor side 和原消息 hash。Book 由既有 exporter 重放；任何 sequence
gap、duplicate/out-of-order sequence、checksum mismatch、reconnect 后非 snapshot
均 fail-closed。

Trade 只能连接到同时满足以下条件的最近有效双边 book：

- `book.capture_sequence <= trade.capture_sequence`；
- `book.available_time <= trade.available_time`。

负 alignment 被视为 future-book join 并阻断 export。

## 外部单写者与恢复

正式运行必须使用 worktree 外专属 runtime root 和 shared-data root。Runner 在
clock、network 和 ticket payload 写入前先取得 `writer.lock`，随后验证不可变
`owner.json`。状态使用：

- `inflight.json`：publication 失败后复用同一 slice；
- `events/`、`health/`：append-only；
- `latest_pointer.json`：引用 event hash，并最后原子更新；
- `manifests/`：每个 immutable dataset version 的发布 manifest。

低于 20 GiB、owner/lock 冲突、clock、public network、export 或 publication
异常均 fail-closed。Publisher 失败不会重新捕获已完成 slice。

## 持续观察入口

独立集成到 current main 后，runner 可以用 `--continuous` 顺序捕获多个
60–600 秒 immutable slice。连续观察推荐使用 600 秒 slice，以摊销每个新
connection epoch 固定的前 60 秒 gap/resync embargo，并让 60 秒 horizon 留有
合法完整窗口。每个成功 slice 都使用新 dataset version，然后由
evaluator 对多个精确 committed manifest 聚合 windows、ESS、UTC 时段和
volatility/liquidity regime 覆盖。Runner 不会自动启动 GA，也不会因
累积数据而改变 research/promotion gate；600 秒只是采集切片边界，不是
readiness 证明，也不改变任何冻结信息量门禁。

- 成功 slice 后继续；`--max-slices N` 用于有界验收，`STOP` sentinel 或
  Ctrl-C 用于人工停止。
- clock 和已启用 public-network 的短暂错误使用有界指数退避；publication
  失败必须重用原 inflight/capture/export，不重采。
- writer/owner/storage/export/config 以及不可恢复的持久状态错误立即终止。
- `continuous_attempts.jsonl` 保留每次尝试的完整 result；每 slice 仍保留
  pointer-last events/health/state 证据。

### 容量与已发布 runtime payload 剪枝

首版 55.997 秒 slice 的 runtime 重载荷为 11,703,883 bytes，若 runtime 和
shared-data 长期双份保留，线性外推约 34 GiB/day，无法在当时 D 盘
52.95 GiB 可用空间下可靠跨越 20 GiB 存储熔断线并达到 UTC 覆盖门禁。

`--continuous` 因此默认启用 `--prune-published-runtime-payload`，也可显式用
`--no-prune-published-runtime-payload` 保留调试载荷。剪枝只能在以下证据全部
成立后执行：

- `publication_result` 和 runtime manifest 身份一致；
- shared-data resolver 对不可变物理版本执行逐文件 full-hash 验证；
- `published_quality_checked` event 已持久化，latest pointer 状态不早于该
  event，且 inflight 已移入 `completed_inflight`。

删除目标固定且逐路径验证为
`runtime_root/slices/<exact-slice>/capture` 和 `immutable_export`；禁止 glob、宽目录
删除和 shared-data target 删除。Clock、capture report、metadata、publication
result、manifest、completed inflight、event/health 全部保留，并生成包含
dataset/version/aggregate/target/hash/removed bytes 的 append-only prune receipt。如在
finalize 前崩溃则不剪枝；finalize 后剪枝失败则记录
`blocked_runtime_prune` 并终止 continuous，但不否认已发布事实。重启时会从精确
`completed_inflight` 幂等补做已终态但未完成的剪枝，不重采数据。

## 研究准入计算

Evaluator 只能接受 repeatable 的
`<40-hex-commit>:.agent/data_manifests/...json`，通过 shared-data resolver 完整
验证物理 manifest、文件大小和 SHA-256。禁止 `HEAD/latest/glob/staging/SQLite`
fallback。

Evaluator 从同一 resolved immutable version 的 normalized trades 计算：

- 10/30/60 秒 non-overlap cost-adjusted labeled windows；标签使用同一不可变
  version 的 `left.mid -> right.mid` 收益并扣除两端 taker 可成交成本，trade price
  不作为基准收益，避免 bid/ask bounce 与 spread 重复计量；
- 每个 connection epoch 起始 60 秒以及实际重连点前后 60 秒 embargo，禁止跨
  connection label；future-label availability 的分母仅包含 embargo 后候选锚点；
- 按 connection/slice segment 分别计算 lag-1 autocorrelation-adjusted ESS 后保守求和；
- 六个 UTC 4 小时桶、weekday、3×3 volatility/liquidity regime；regime 波动率只取
  decision-time 向后 60 秒 mid，liquidity 只取 start row；多 slice 在全局 pooled
  decision-time observations 上重新划分 tercile，不累加局部 tercile；
- joined coverage、future-label availability、cost completeness；
- receive lag、trade/book alignment、duplicate、out-of-order、gap、crossed、
  one-sided 状态。

所有阈值继续来自既有冻结 prereg。OI/liquidation 缺失只阻塞 liquidation family；
maker/queue 仍 `not_applicable`。

## Public smoke 与不可变发布

首次 60 秒 public-only smoke 成功捕获 1,110 帧，但两条收集器合法记录的
文本 `pong` 心跳暴露了 exporter 兼容缺陷，因此 fail-closed 为
`blocked_export`。Correction `4e615032a6ca223531235aadf7b1da32b8f235a7`
保留原始帧不变，只为旧 L2 replay validator 生成可丢弃的心跳兼容视图。

第二次 60 秒 public-only smoke 发布：

- dataset version:
  `btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6`；
- coverage: `2026-08-27T11:12:39.209Z`–`2026-08-27T11:13:35.206Z`；
- raw frames: 859，其中 books 571、trades 284，单连接、零 collector error；
- normalized unique trades: 284，PIT joined coverage 100%；
- aggregate SHA-256:
  `2fa444de042e742e9763b6a4988205b7f05d5374d6cf66fa94d20c7efd26fd70`；
- readiness class: `quality_checked`，尚非 `research_ready/backtest_ready`。

正式 evaluator 仅从上述 committed manifest 解析物理版本，结论为
`blocked_insufficient_information`：10/30/60 秒 eligible windows 分别为
`0/0/0`，ESS 为 `0/0/0`。55.997 秒首片完全落在每个 connection epoch
起始 60 秒 embargo 内，因此没有合法候选锚点，距离每 horizon 固定的
`1000 windows / 500 ESS` 门禁还很远。实测 two-sided book coverage 100%，
duplicate/out-of-order/unrecovered gap/crossed/one-sided 均为 0，receive lag p99
290 ms，trade/book alignment p99 109 ms。Correction-02 的 exact-manifest report
以本次 committed source head 离线发布，精确 artifact hash 记录在 append-only
handoff，不覆盖旧 report。

Trade-imbalance、micro-breakout 和 sweep/absorption 三个 family 只因信息量、
时段/状态覆盖及成本分层稳定性不足而 blocked。Liquidation family 另缺
time-aligned OI/liquidation events；maker/queue 保持 `not_applicable`。

## 安全声明

本票据只允许 OKX official public endpoint；不读取 secret，不访问 private、
account、order 或 live endpoint，不写 paper queue，不发送订单或转账/提现。
`promotion/paper/live/private/order/real_order/transfer/withdraw` 全部保持 false。
