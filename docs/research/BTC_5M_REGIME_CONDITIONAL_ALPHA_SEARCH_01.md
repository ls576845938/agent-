# BTC 5m regime-conditional alpha search 01

## 结论

`BTC-5M-REGIME-CONDITIONAL-ALPHA-SEARCH-01` 已按预注册合同完成分层搜索，但没有保留任何研究候选。

- 终态：`complete_research_only`
- 决策：`reject_selection_batch_holdout_not_revealed`
- 保留候选：`0`
- 未见尾段：`preserved_unseen`
- 未见候选揭示：`0`
- Demo 策略注册：`false`
- promotion / paper / live / private / order / real order / transfer / withdraw：全部 `false`

这是一个选择阶段负结果，不是未见留出集的负结果。程序没有计算 30,658 根未见 K 线上的策略收益、成本、成交或账本指标。

## 本轮关闭的结构问题

新引擎不再把 Alpha、仓位和安全参数塞入同一基因组，而是固定为三层：

1. `AlphaGenome`：仅搜索经济假设、市场状态、入场事件与语义退出。
2. `FixedSizingPolicy`：固定 1x 上限、12 根调仓节拍、15% no-trade band 和 15% 最小仓位变化；不做每根 5m 波动率重置。
3. `FixedRiskConstitution`：固定仓位上限、bar-based 止损代理、结构突变暂停、日内亏损暂停和策略最大亏损；任何一项都不得由 GA 优化。

搜索的三个互斥假设家族是：

- 波动压缩后的趋势突破延续；
- 高层级趋势中的 5m 回撤再启动；
- 震荡状态中的失败突破反转。

市场状态使用因果的 completed-bar EMA/ATR 特征，冠军的快慢窗口为 12/48 根 5m K 线，对应 1h/4h 层级。退出包含语义失效、时间止损、结构突变和固定 bar-based 硬止损代理。后者只是研究回放证据，不是交易所托管保护单证据。

## 预注册、代码与数据身份

- base commit：`8e37b30844b6919333be804612982e91b9f0d0f6`
- engine commit：`9a42e6eb55956aa5c6aa7c7d48fc83542f20ad05`
- 唯一授权官方搜索 HEAD：`f7d7f95c9117d85896f5f9f6fd13212867e7c43b`
- 邻域补证修复 HEAD：`b7c34360cc0b42a885b5e90f016bf4c7c24c43e8`
- 预注册：`docs/research/BTC_5M_REGIME_CONDITIONAL_ALPHA_SEARCH_01_PREREG.json`
- dataset version：`btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1`
- selector SHA-256：`b934de48d233c1f813494825c82b89ed1cd128a0ccf2e48bb28908f6967b0590`
- Git manifest SHA-256：`ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56efa9ee`
- physical manifest SHA-256：`0ee09f51f53608c16c9306334c5e4fbe7ede86f948c625ba91bbd36d7f327068`
- aggregate SHA-256：`cfe0fe05e59e0fef4919a601926563750f94a27dfb08f84f093e6440270385f4`
- 5m file SHA-256：`76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08`
- source SHA-256：`40741d3929d3d337a784ff2a475148e68d6e3e7aaf944c34ed73d34eba6cfaea`
- 总行数：`278,928`
- public network：`false`
- mutable SQLite fallback：`false`

## 冻结选择集与未见留出集

选择只使用前 `248,270` 根 completed 5m K 线：

- start：`2024-01-01T00:00:00Z`
- end / prior research cutoff：`2026-05-12T01:05:00Z`
- validation：4 个 chronological expanding folds
- embargo：`192` 根，等于最大特征回看
- decision / execution：completed close / next open

未见尾段：

- start：`2026-05-12T01:10:00Z`
- end：`2026-08-26T11:55:00Z`
- rows：`30,658`
- 用于搜索：`false`
- 策略指标已读：`false`
- 揭示候选：`0`
- 调参复用：`false`

## 搜索方法与预注册门禁

- deterministic Pareto genetic search；seed `20260827`。
- population `32`，generations `8`，4-fold，本轮 `224` 个唯一基因组。
- 前两轮 5m 搜索唯一评估为 `499 + 858 = 1,357`；主搜索后累计 `1,581`。
- 邻域补证额外评估 `6` 个唯一基因组；最终累计 `1,587`。
- 选择不使用单一加权 fitness，而使用 Pareto 层、最差 stress fold、条件收益、effective bets、回撤、PF 与成本效率。
- 不使用 `trades/day` 硬门；使用独立 bets、lag-1 自相关修正的 effective sample 和累计多重检验 haircut。
- 非适用状态下可以空仓，不强制该 fold 盈利；但至少 3 个 folds 必须有足够状态和 bets 证据。
- base / conservative / stress 成本分别为每单位换手 `10 / 16.5 / 30 bps`，三者都参与选择门禁。
- 冠军必须通过 6 个局部参数邻域稳定性，才有资格触发单候选未见揭示。

## 锁定冠军与四折结果

冠军是 `btc_5m_regime_alpha_26a95432510a`，属于 `range_failed_breakout_reversal`：

- regime fast / slow：`12 / 48` 根（`1h / 4h`）
- state strength：`1.0 ATR`
- entry / exit：`12 / 6` 根
- ATR：`48` 根
- invalidation：`2.0 ATR`
- max holding：`48` 根
- cooldown：`12` 根
- compression ratio：`1.0`
- Pareto rank：`0`
- 适用 folds：`4 / 4`
- 通过 folds：`0 / 4`
- 正收益 folds：`0 / 4`

| Fold | Base return | Base PF | Base max DD | Independent bets | Stress return | Passed |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | -15.316704% | 0.62885129 | -15.343520% | 89 | -15.391878% | false |
| 2 | -15.096311% | 0.52553033 | -15.103775% | 104 | -15.441498% | false |
| 3 | -15.517530% | 0.71069109 | -15.657660% | 113 | -15.326581% | false |
| 4 | -15.176035% | 0.67728986 | -15.176035% | 114 | -15.226937% | false |

四折都有足够状态和独立 bets，因此不存在“策略只是少交易被 `trades/day` 误杀”的解释。四折的 base PF 全部显著低于 1，conservative 和 stress 收益也全部为负。

多重检验补证后：

- pooled effective bets：`373.89692888`
- median mean bet return：`-0.052955%`
- expected-maximum haircut：`0.053389%`
- deflated mean bet return：`-0.106344%`

因此负结果不是由多重检验修正单独造成；修正前的平均 bet 本身已为负。

## 参数邻域补证与缺陷修正

官方搜索终态复核时发现，最终冠军保留了 `not_yet_evaluated` 占位对象，根因是代码仅检查字段是否存在，没有检查其 `status`。这个缺陷是 fail-closed：占位对象的 `passed=false` 额外阻止了留出集揭示，没有伪造通过。

修复后没有覆盖原 artifact，也没有重跑 GA。新的 selection-only correction：

- 精确绑定原 report 文件 SHA、artifact hash、原 candidate lock 文件/语义 SHA 和冠军 genome hash；
- 重新解析相同 qcv2r1 数据身份；
- 仅在前 248,270 根选择样本上计算 6 个局部邻居；
- 无论补证结果如何，correction lock 都固定 `reveal_authorized=false`；
- 未见策略指标读取为 `false`。

6 个邻居的 eligible-fold 中位 base return 分别为：

`-15.148204%`, `-15.116335%`, `-15.246370%`, `-15.175948%`, `-15.150162%`, `-15.246370%`。

- 稳定邻居：`0 / 6`
- 要求：至少 `3 / 6`
- 邻域结论：`fail`

这进一步排除了“只是冠军单点参数偏差”的解释。

## 不可变 artifact

初始官方搜索（其邻域字段不完整，不得单独作为完整门禁证据）：

`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-5m-regime-conditional-alpha-search-01/official-f7d7f95c9117`

- report semantic artifact hash：`607f9278eef21ceeee1ed1dfec598d8e6a3c95a47f133c3eeb056b008fd85b22`
- report file SHA-256：`caa7ffaf73ca026daf1c23656359ba1735e38ba2ff7a2c5066fef080415cd9bb`
- candidate lock semantic SHA-256：`c42568704f03c7afb82328d1700334731ada73ffb0c7e62f078b5bf1c2377eaf`
- candidate lock file SHA-256：`b37a7a1fbf56541a58aed41ad4b8797e51f32cf858a0bca84c63bafa7ab23dd7`
- candidate definitions SHA-256：`79e8a73f3561b06691252796b30f35d614aa933290021e2eaf8b78ac01483c41`
- summary SHA-256：`3fe26e1fc5ba06ea86381c47933f4ab33c31dbcdbe75e9e5fa083a0bdfe8aeba`

选择邻域补证（与上述 source artifact 组合后才是完整选择证据）：

`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-5m-regime-conditional-alpha-search-01/correction-b7c34360cc0b`

- correction semantic artifact hash：`e6c444196d7b8b5d2319b07f6df294d93ce13834923227c454443b0d0fa4094b`
- correction report file SHA-256：`1be950ccfd6123c67e1f20c6c58ebb7557089a0bc1c5577cd759feadc37f9435`
- correction lock semantic SHA-256：`2d73d92c8bc8c393a702382e7188e39da102e52aa00608fc0f579a78c9e6ae16`
- correction lock file SHA-256：`9afb94531a5a10f5cf5556534ac89481e3de91b813bd8ae6728335d497f3778f`

## 验收与边界

- 合同回归：`17 passed`
- 公式搜索与补证均为本地离线执行。
- 没有启动或修改 frontend/backend、runtime、OMS、策略注册、paper queue 或 live adapter。
- 没有读取密钥，没有访问 private/order/live endpoint，没有创建 Demo 或真实订单。
- 固定 bps 成本不证明 L2 queue、latency、unfilled orders、mark/index、funding、liquidation 或 hosted protective stop。
- 质量通过、搜索完成和未见集尚未揭示都不等于 promotion；所有执行与晋级 gate 保持 fail-closed。

当前证据支持的动作是：拒绝这一搜索批次，保留未见尾段，不降低门禁，不将“最不差”候选接入 Demo 或 paper。
