# BTC 15m/30m/1h 趋势家族搜索 01

## 冻结研究设计

本票据只在已提交的 `qcv2r1` selection-prefix 上比较三个相互独立的经济假设与三个固定决策周期。`timeframe × family` 是外层固定 stratum，周期不是 GA 基因。遗传只在同一 family 内交叉和变异，先做可行性约束支配，再做 Pareto 比较。

三个家族分别是动态 momentum-cycle/turning-point continuation、波动条件 channel breakout、以及高周期趋势中的 pullback/reacceleration。固定 12/48 MA 仅作为负面对照，不参与冠军选择。仓位固定 1x；慢速调仓、no-trade band、最大亏损、暂停和 completed-bar hard-stop proxy 全部由固定外部风险合同提供，不是收益优化旋钮。

## 数据和可见性

消费者只接受仓库固定 manifest、精确 dataset version、current-HEAD Git blob 和 payload SHA。打开 full qcv2r1、latest、SQLite、staging 或 glob 都不在代码路径中。5m 数据按 UTC epoch 左闭右开聚合，15m/30m/1h 必须分别由 3/6/12 根连续、唯一且 finalized 的 5m bar 构成；目标 bar 的 `available_time` 是最后一根源 bar 的真实 close/available time。信号在 completed target close 作出，成交代理在下一 target open，即下一根 5m open。

预期完整聚合行数为 82,756 / 41,378 / 20,689，三者最后可见时间均为 `2026-05-12T00:59:59.999Z`。每个 derived frame 的 semantic hash、聚合版本和边界进入 artifact provenance。

历史 qcv2r1 尾段已经失去干净留出资格，但没有策略指标被计算或展示；其状态固定记录为 `legacy_qcv2r1_holdout_retired_without_metric_reveal`。本票据不会读取它，也不会宣称 OOS 或 confirmatory test；四折只是带等价 5,760 根 5m bar embargo 的 purged chronological selection folds。即便锁定 selection candidate，也必须等待新的未来未见数据。

## 预注册门禁

正式预算为 9 个 strata × 12 population × 4 generations，新增唯一试验不超过 450，累计试验从 1,840 起算。基础/保守/压力成本固定为 10/16.5/30 bps。候选必须有足够独立 bets、适用 folds、有效样本、成本后保守收益、stress 容忍、multiple-testing haircut 和参数邻域稳定性；不设置通用 trades/day 门槛，不会为产生结果事后放宽。

## 证据边界

该研究不证明交易所托管保护单、mark/index/funding、清算、L2/排队/部分成交/冲击、运行时账本或 current-HEAD promotion artifact。`promotion/paper/live/private/order/real_order/transfer/withdraw` 始终为 `false`。

## 首次正式运行的不可消费补正记录

首次运行路径 `official-68b70551-seed20260827` 保持不可变，但其 semantic hash `666c9ebb130f9910c2cc119379d213c6c9c6fa8b3ea3b690f30e7a2a68b92620` 已明确作废，禁止消费。复核发现 neighborhood-only 诊断候选被重新放回可锁定排名，使 top candidate 与接受邻域检验的 candidate identity 不一致；同时复用 5m simulator 后，annualized 字段仍采用 5m periods-per-year。总收益、PF、回撤和 ledger 没有因此改变，但候选身份和周期度量证据不自洽。

补正仅剔除 neighborhood-only 候选的锁定资格，并按 15m/30m/1h 修正 annualization。基因空间、seed、432 slots、unique 上限 450、门禁、三档成本、fold 和 5,760×5m embargo 均未改变；确定性重跑不作为第二轮 multiple-testing 试验。

## 补正后正式结果

补正后的唯一可消费运行是：

- code commit：`ca3793f9166c535185e1ee475db3c92823014986`
- artifact：`D:/vibe coding/Obsidian/量化系统/research_artifacts/btc-15m-1h-trend-family-search-01/official-ca3793f9-corrected-seed20260827`
- decision：`reject_selection_batch`
- semantic hash：`10a58258ffbde30ce9aef44ba4db8a45ee3fe7865480750fed8e4f2f365f1e5c`
- 本票据唯一试验：379；累计 multiple-testing ledger：2,219（prior 1,840）
- old holdout：bytes read 0、rows decoded 0、strategy metrics read false

外层九个 strata 的保守成本后结果如下。收益为四个 selection folds 的 total-return 求和，只用于横向审计，不能当作连续复利曲线：

| timeframe | family | unique trials | feasible | independent bets | conservative return sum | median PF | worst DD | worst fold | blocker |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 15m | dynamic momentum-cycle | 41 | 41 | 182 | -60.41% | 0.630 | -15.85% | -15.16% | fold / haircut / neighborhood |
| 15m | volatility channel | 42 | 42 | 212 | -59.12% | 0.844 | -17.28% | -15.20% | fold / haircut / neighborhood |
| 15m | pullback reacceleration | 40 | 40 | 175 | -60.54% | 0.694 | -15.96% | -15.18% | fold / haircut / neighborhood |
| 30m | dynamic momentum-cycle | 42 | 42 | 171 | -60.45% | 0.710 | -15.87% | -15.28% | fold / haircut / neighborhood |
| 30m | volatility channel | 40 | 40 | 98 | -28.36% | 0.768 | -12.26% | -12.21% | fold / haircut / neighborhood |
| 30m | pullback reacceleration | 38 | 38 | 175 | -57.97% | 0.782 | -23.22% | -15.16% | fold / haircut / neighborhood |
| 1h | dynamic momentum-cycle | 39 | 39 | 231 | -40.17% | 0.764 | -16.74% | -15.17% | fold / haircut / neighborhood |
| 1h | volatility channel | 56（含 16 个 neighborhood-only） | 40 | 88 | +10.97% | 1.022 | -13.13% | -1.72% | 仅 1/4 fold pass；haircut；0/16 stable neighbors |
| 1h | pullback reacceleration | 41 | 41 | 125 | -38.53% | 0.929 | -27.04% | -15.17% | fold / haircut / neighborhood |

被评估但未锁定的 selection candidate 是 `btc_60m_volatility_conditioned_channel_breakout_13455207fc77`。其四折保守收益依次为 `-0.16% / -1.72% / +3.78% / +9.06%`，压力收益为 `-5.67% / -7.65% / -3.79% / +4.44%`；只有 1/4 folds 通过，multiple-testing deflated mean bet return 为 `-0.7048%`，16 个参数邻居中 0 个稳定。正的合计收益集中在后两折，不能掩盖前两折和邻域失败，因此门禁正确拒绝、candidate lock 为空。

正式 artifact 文件哈希：

- `btc_multiscale_trend_search_report.json`：`e8a933b6d573bc4369ae3793be676e3c8df799c127c7443209c72c7a2af7d1fe`
- `btc_multiscale_trend_candidate_lock.json`：`4c6f8e6fb59004525a9ad7e159352bf9bee055d7d018071b8b3bf8fb1d8a4670`
- `artifact_manifest.json`：`b1520ccbd59cb6a0ba5d83523c7c05fbc955ffc5a9d76da8516321ea2fa4d063`

15m/30m/1h derived-frame hashes 分别为 `97f80172839540dcd428e39b61b45e4256efb6fc87fa8986d51724d4225a4798`、`b1921a3075f263e25e22bc43566f9dc3bf64cd25b0d270c65d86be9aaeab2dca`、`7cd09e4ece9cb1c7038d7f87863478ded1ff92516ece5dca2dfc879ee525d7db`。

## 最终阶段

本票据完成的是 `research_only / selection batch rejected / no candidate locked`。旧 qcv2r1 尾段不再是干净 holdout，后续若重新提出经济假设，必须新开预注册票据；任何候选进入确认阶段都要等待新的未来未见数据。托管保护单、funding/mark/index、清算、L2/queue/partial fill、运行时账本和 current-HEAD promotion artifact 仍未证明。

## 假设来源边界

本票据只把既有趋势、动量、波动与 walk-forward 文献作为假设来源，不把文献结论当成本数据上的现成 alpha。最终报告只陈述本次不可变 selection-prefix 的可复核结果。
