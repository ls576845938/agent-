---
tags:
  - BTC
  - 策略来源
  - 滚仓
  - Donchian
  - TQQQ迁移
aliases:
  - BTC 10x滚仓爆炸版来源
  - Donchian方向信号来源
  - frozen high-yield v3方向来源
---

# BTC 10x 滚仓爆炸版与 Donchian 方向来源说明

日期：2026-07-06

用途：保存本次对话中关于 `10x no_rollover / split_2_on_double` 原始爆炸版，以及其底层 BTC long/short Donchian 趋势方向来源的解释，方便后续迁移到 TQQQ 或交接给美股系统 agent。

保存位置：`agent-/docs/research/btc_10x_rollover_and_donchian_direction_origin.md`

## 一句话结论

`10x no_rollover / split_2_on_double` 原始爆炸版不是一个独立新 alpha。它是把已经筛选出的 BTC long/short Donchian 趋势方向信号，叠加 10x 杠杆、isolated sleeve、复利或翻倍拆仓资金管理后的研究样本。

复核结论显示，爆炸收益主要来自：

1. 已有 BTC 趋势方向信号。
2. 10x 杠杆。
3. 趋势段复利。

不是主要来自 `split_2_on_double` 拆仓本身。

## 对话 1：10x 原始爆炸版怎么来的

问题：

> `10x no_rollover / split_2_on_double` 原始爆炸版最原始的那个策略是怎么来的？

回答摘要：

最原始的爆炸版不是从知乎、GitHub 来的，也不是后来那份“10U 滚仓大法指南”来的。

它最早来自用户提出的币圈滚仓想法：

- 把资金拆成多个账户或 sleeve。
- 用高杠杆抓趋势。
- 某个 sleeve 翻倍后继续拆仓滚下去。

系统把这个想法工程化成 `btc_bankroll_rollover_lab` research-only 实验。

这个实验有两层：

### 1. 方向信号层

不是新策略，而是复用了已有 BTC long/short 趋势方向。

方向来源：

- frozen high-yield v3 / Donchian 趋势方向信号。
- 用已完成 1H K 线聚合出 4H K 线。
- 由 4H 决策周期产生方向。

### 2. 资金管理放大层

在这个方向信号上套：

- 初始资金拆成 10 个 isolated sleeve。
- 测试 `1x / 3x / 5x / 10x` 等杠杆。
- `no_rollover`：不拆仓，只让 10x 复利滚。
- `split_2_on_double`：单个 sleeve 翻倍后拆成 2 个继续滚。
- `extract_principal`：翻倍后提本金，利润继续滚。

后来复核发现，约 `1,510,327.76%` 总收益、约 `4648.31%` 年化的爆炸结果，主要不是因为 `split_2_on_double` 很强，而是因为：

> 已有趋势信号 + 10x 杠杆 + 长趋势段复利。

关键证据：

- `10x no_rollover` 和 `10x split_2_on_double` 最终收益几乎一样。
- `split_2_on_double` 相对 `10x no_rollover` 的增量是 `0`。
- 所以它不是“拆仓带来收益”，而是“10x 趋势复利本身带来收益”。

### 后来为什么被降级

它有几个硬伤：

- 所有 sleeve 基本同方向、同杠杆、同一根 K 线承担风险。
- 遇到合成 `-5% / -8% / -10%` 插针时，可能多个 sleeve 同时归零。
- `-10%` 插针后剩余本金最低可以到 `0%`。
- rolling start 起点敏感，最好起点和中位起点差距很大。
- 它是收益天花板样本，不是可直接 forward observation / paper 的候选。

最准确的定义：

> 这是“已有 BTC 趋势信号的 10x isolated sleeve 复利压力测试”，不是一个独立新 alpha。

### 迁移到 TQQQ 时的注意

美股 agent 不应该照搬 “10x BTC 永续强平模型”，而应该迁移结构：

- 趋势方向信号。
- 高 beta 标的。
- sleeve 隔离。
- 复利或提本金规则。
- 起点敏感性复核。
- 极端回撤复核。

## 对话 2：底层 Donchian 趋势方向怎么来的

问题：

> 我们已有的 BTC long/short 趋势方向，来源是 frozen high-yield v3 / Donchian 趋势方向信号，用已完成的 1H 聚合 4H K 线生成方向，这个是怎么来的？

回答摘要：

这条方向信号最早来自 `BTC Long/Short 趋势跟踪实验室`。

当时用户提出：

> 趋势跟踪不应该只做多，确认下跌趋势也应该做空。

于是系统新增了 `btc_long_short_trend_following_lab`。

它不是机器学习，也不是 GA 挖出来的，核心是简单规则：

- 日线判断大方向。
- 4H Donchian 突破决定入场。
- ATR trailing stop / Donchian exit 决定退出。
- 没趋势就空仓。
- funding / OI / 多空比只做风险过滤，不单独决定方向。

### 预声明 formal narrow 网格

后来按用户要求做了一轮预声明窄网格：

- Donchian 窗口：`72 / 96 / 120 / 180 / 240`
- 日线趋势：`EMA20/80`、`EMA34/144`、`EMA50/200`
- ATR 倍数：`2.0 / 2.5 / 3.0 / 3.5`
- 冷却期：`0 / 6 / 12`
- 失败突破退出：开 / 关
- 风险过滤：无 / funding / funding+OI / funding+OI+多空比

总共 `1440` 个 formal Donchian 候选。

最后 Top5 里最强的是：

`formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone`

含义：

- 4H Donchian 窗口：`240`
- 日线趋势：`EMA50/200`
- ATR：`20`
- ATR 倍数：`2.0`
- 冷却：`12` 根 4H
- 失败突破退出：关
- 衍生品风险过滤：无

当时报告中该候选大概表现：

- 年化：约 `36.26%`
- 总收益：约 `116.23%`
- 最大回撤：约 `11.47%`
- PF：约 `1.44`

它进入 Long/Short research watchlist。

### 具体信号规则

基础 Donchian 方向大概是：

- 日线多头：日线 `EMA50 > EMA200` 且价格在 EMA200 上方。
- 日线空头：日线 `EMA50 < EMA200` 且价格在 EMA200 下方。
- 做多入场：日线多头 + 4H 收盘价突破过去 `240` 根 4H 的最高价。
- 做空入场：日线空头 + 4H 收盘价跌破过去 `240` 根 4H 的最低价。
- 做多退出：日线多头失效，或跌破 Donchian 退出线，或触发 ATR trailing stop。
- 做空退出：日线空头失效，或突破 Donchian 退出线，或触发 ATR trailing stop。

可见性边界：

- Donchian 入场线使用 `high.shift(1)` / `low.shift(1)`，也就是只看上一根及更早的已完成 4H K 线。
- 最终持仓使用 `raw_signal.shift(1)`。
- 当前完成 K 线算信号，下一根才持仓。

### 变成 high-yield v2 / v3

之后系统把这个 Donchian Top5 里的最强基础信号拿去做“小资金高收益线”。

v2 冻结候选：

`hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff`

含义：

- 底层方向还是 Donchian 240 + 日线 EMA50/200。
- 加波动目标仓位：`vol target 120%`
- 最大杠杆：`2.5x`
- 回撤闸门：`25%`
- 最低强平缓冲：`1200 bps`
- trendless filter 关闭。

v3 不是换入场逻辑，而是只改亏损控制：

- 快速止损。
- 冷却。
- 连亏降仓。
- 失败突破退出。

### 最后滚仓实验如何使用它

`10x no_rollover / split_2_on_double` 爆炸版没有重新生成方向。

它调用 `_frozen_v3_direction()`，把 high-yield v3 的 exposure 转成简单方向：

- exposure > 0：方向 `+1`
- exposure < 0：方向 `-1`
- exposure = 0：空仓

然后滚仓实验再自己叠加：

- 10x 杠杆。
- 10 个 sleeve。
- 翻倍拆仓。
- 提本金或不提本金。

最终一句话：

> 这条方向信号最早来自“多空 Donchian 趋势跟踪 formal 窄网格”，不是 GA、不是 TimesFM、也不是滚仓自己发明的。滚仓爆炸收益是把这条已筛选出来的 Donchian 趋势方向，再叠加 10x 杠杆复利资金管理。

## 代码和报告引用

- `quant_crypto/research/long_short_trend_following_lab.py`
- `quant_crypto/research/small_account_high_yield_lab.py`
- `quant_crypto/research/small_account_high_yield_near_miss_review.py`
- `quant_crypto/research/high_yield_v2_confirmation.py`
- `quant_crypto/research/bankroll_rollover_lab.py`
- `artifacts/btc_long_short_trend_following_lab/latest/btc_long_short_trend_following_lab_report.json`
- `artifacts/btc_bankroll_rollover_review/latest/btc_bankroll_rollover_review_report.json`
- `artifacts/btc_attack_strategy_continuation_shortlist/latest/btc_attack_strategy_continuation_shortlist_summary_cn.md`

## 当前边界

这篇笔记只做策略来源说明，不构成 paper/live 许可。

当前相关策略仍应保持：

- 不写 paper 队列。
- 不解锁 live。
- 不接 broker / OMS 下单面。
- 先做 forward observation、强平、mark/index、funding、滑点、起点敏感性和过拟合复核。
