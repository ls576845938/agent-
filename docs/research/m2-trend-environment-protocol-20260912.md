# M2 趋势环境增量验证：固定协议与准入停止点

协议版本：`m2_environment_ab_v1`；登记日期：2026-09-12；参考代码：`2eafaf5220a5527962874e02fc04c1674e379ce8`。

状态：**协议登记、输入准入检查已做；独立样本和精确切分未绑定，效果计算未启动。** 这是不可执行的预注册草案，不是已完成的有效性实验。M1 必须先独立结项；M3/M4 不启动。

## 唯一问题与两臂

问题：在完全相同的数据、预测标签、模型和计算预算下，M1 的历史因果趋势环境是否带来额外样本外预测信息？不声称这些分数是概率，不把预测质量称作可交易净收益。

- A：保持 `configs/qlib/okx_btc_trend_1h.yaml` 的 13 项 `causal_ohlcv_trend_v1` OHLCV 特征。
- B：A 加入 M1 的 24/72/168 根 K 线尺度，每尺度固定 direction、trend_fit、bar_volatility、shock_score、transition_score 共 15 个字段。direction 固定编码 down=-1、flat=0、up=1；unknown 不是 flat。
- 不改现有生产配置、Factory profile、M1 sidecar、默认 BTC 信号/目标/仓位/退出/风控/OMS/保护/账本。环境仅进入本票后续隔离离线实验的训练输入；不会回写现有训练配置。
- 首个市场固定 OKX `BTC-USDT-SWAP` / 1h / UTC_24x7；禁止用 Binance spot 或别的 5m 任务尾段替代。共享方法以后可注入 US/CN 的日历、可见时间、复权和成本合同，本轮不宣称这两个市场已验证。

## 固定计算合同

- 复用现有 Qlib/LightGBM `train_feature_trial`、`split_plan/purged_selection_folds`、`signal_metrics` 及 M1 `estimate`，不另建 Alpha 工厂。
- 标签固定 `open[t+14]/open[t+2]-1`：12bar horizon、2bar delay，purge/embargo 不小于 15bar。每折 test 必须时间不相交，训练/早停只能使用该折更早的 train/valid。
- 模型固定 LGBModel，loss=mse，num_leaves=15，learning_rate=0.035，min_data_in_leaf=80，lambda_l2=5，seed=17，num_threads=2；最多 120 boosting rounds，early_stopping_rounds=15，仅在 valid 上早停。配置来源 Git blob `9d496d5898b9857e0705b545e0049130a8eeb099`。
- 预算固定两臂 × 四折，**最多 8 次 fit（失败尝试也计入）**。零 GA、零参数网格、零额外 seed、零特征选择、零失败后调参重跑。不得先看 B 的表现再决定采用哪项环境字段或时段。
- A/B 使用相同时间/资产配对行。环境全部 15 字段非有限、缺失、warmup、迟到或未完成时排除该行并保留原因；两臂用同一掩码，同时报告相对原始可评估时钟的覆盖率，不将 unknown 填成 0/正常。
- 每个环境输入必须是 completed 且 close_time/available_time <= decision_time；输入 warmup 至少 170 根可见完成 bar。只能使用训练期统计量。行情原始到达语义缺失则只能输出历史重建研究，不输出在线可用性证明。

## 固定评价与成本边界

- 唯一主要统计量：同一时间块的 `RankIC(B)-RankIC(A)` 均值；次要统计量是配对 MSE 差、每折一致性、覆盖率和缺失原因。完整保留四折，不只报告最佳折。
- 使用固定 168bar 时间块作配对不确定性分析；不跨缺口或折边界拼块。块重采样固定 seed=17、2000 次、95% 区间。有效块不足 30 时只报告描述量并标记 `inconclusive`，不把小时行数当独立样本数。
- 只有覆盖率>=90%、至少3/4折增量为正且主要增量区间下界>0，才能建议进一步独立研究；仍不构成 Alpha 合格、paper 或 live gate。未达到就如实无支持/证据不足，不能追加搜索。
- Factory 的 24/36/48bps 仅为原有预测成本代理，保持标签，不称为逐笔实扣费用或净收益。本协议主要问题是预测信息，不用代理指标制作净值曲线。
- 若后续需要研究净收益，必须先绑定实际 fill/position/cash/funding 重放合同；现有参考配置为每边 fee=5bps、slippage=3bps、spread=2bps、impact=2bps，严格沿用其实现解释，不能另把它们相加冒充24bps。资金费时间覆盖不足时净收益部分必须 blocked；禁止为制造成交降低原门槛。

## 计算前必须绑定的真实证据（目前缺失）

下列字段必须由独立数据/研究审查从事实确认，并在读取新标签或表现**之前**提交精确版本，不能只填布尔 true：

1. 同市场同频率的不可变 manifest Git ref、dataset/version、aggregate 和文件 hash，以及实际内容/完整时钟/PIT 核验。
2. 独立用途登记、历史曝光/候选锁/其他任务使用核对；已有普通 Qlib、M1 和 Factory 使用过的时段排除出确认范围。hash 通过不能证明“未见”。
3. 精确的 train/valid/four-test 日历时间、labels 可见终点、purge/embargo、warmup 和成本覆盖，全部锁定；当前均未绑定。
4. 数据所有者明确保留该确认集，不能挪用另一任务的封存尾段；预注册与首次读取记录形成可审计顺序。
5. 薄离线 A/B 编排的合同与独立验收。现有 `run_m1_research_acceptance.py` 不是 A/B 有效性评价器，不能改名使用。

当前 Factory 的 `previously_observed_audit=True` 必须保留；本票不修改 registry、共享 schema 或一次性确认权限来绕过它。后续新增数据绑定或确认基础设施需沿既有数据/研究交付边界提出精确下一任务，不能由本次失败自动无限扩展。

## 本轮执行事实与停止条件

输入准入记录见 `m2-trend-environment-input-audit-20260912.json`。目前可直接绑定的 OKX 小时数据已用于 M1，未找到经核验可供本 M2 独立确认的足够新窗口；其他市场/候选锁不借用。

因此：`fit_count=0`、`performance_evaluated=false`、`confirmation_status=blocked`。本轮停止在数据准入，不在已看过样本上追加一轮探索来替代用户要求的未见样本验证，也不在缺数据时先建一套暂时不可验收的评价引擎。

后续准入通过后，8 次预算耗尽、任何版本/完整性/可见时间不一致、样本不足或原接口不能表达合同，均产生明确停止记录。不自动换市场、补值、降成本、改窗口、换赢家或启动 M3/M4。

所有 promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed 均为 false。研究完成不授予交易权限。
