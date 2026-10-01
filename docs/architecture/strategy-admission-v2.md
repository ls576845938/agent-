# V2：冻结 Qlib 候选离线推理一致性

2026-09-15 · STRATEGY-V2-FROZEN-QLIB-20260915

本阶段只验证一个已封存 Qlib 候选能否在研究任务之外，以相同的 13 个特征、相同的 Fillna 预处理、相同的 LightGBM 模型和相同的冻结校准规则重放研究预测。它不是训练任务、收益研究、组合接线或交易授权。

## 固定对象与边界

- 上游基线：V1 独立候选 `a315f1169d9b628e9a4acd70100f188076c32560`。
- 研究运行：`m1-okx-qlib`；候选 `qlib_manifest_0de835a36fc243c1`；模型 `lgbm_causal_trend`。
- 数据身份：来源符号 `BTCUSDT`、交易场所品种 `BTC-USDT-SWAP`、Qlib 品种 `BTC-USDT-SWAP` 分开绑定。
- 归档只能通过 40 位小写提交 SHA 锁定的 Git manifest 和 immutable shared-data resolver 解析；`HEAD`、分支、标签、`latest` 以及旧产物内的历史绝对路径都不可信。
- 校准 `clip_fraction=0.05` 由 V0 不可变 Git blob 及其 SHA-256 独立约束，不能仅因当前样本没有触及截断边界就接受漂移后的数值。
- 标签包含未来收益，只留作封存说明；推理入口不实例化 label 或 `DropnaLabel`。
- 输出是 `frozen_inference / research_only`，不是 `offline_execution`。仓位、退出和成本只记录冻结引用及内容摘要，不在 V2 执行。

## 冻结验收

1. 对整包 seal、模型、配置、数据、候选、市场、品种、时间和有序特征做严格绑定；任何缺失、损坏或不匹配都拒绝。
2. 直接从封存 float32 Qlib provider 按冻结表达式生成 13 个特征，只执行 `Fillna(feature)` 的 NaN→0；Infinity 不会被补成正常值。
3. 测试段 1,392 行原始分数逐行对照 `pred_score.parquet`，冻结 OLS＋5% clip 后结果逐行对照封存研究决策；容差固定为 `atol=1e-10, rtol=1e-8`，失败后不得放宽。
4. 批量与逐行预测一致；可见前缀通过固定历史起点和 Qlib `end_time` 限制，与同截止点的批量历史一致；另在 provider 副本中物理扰动未来数据，证明截止点以前的特征不变。这里没有为每个事件分别物理删尾。
5. V2 入口运行前后封存文件 hash 不变；入口及本次修正测试禁止网络、训练、搜索、MLflow 写入、归档写入、账户、Demo、private/order/live。

## 时间语义

Qlib 索引是完成小时 K 线的开盘时间 `event_time`。该根 K 线在 `event_time + 1h` 可用，决策时间也为 `event_time + 1h`。研究配置的 2-bar 延迟表示假设成交发生在 `event_time + 2h`，不是 `decision_time + 2h`；V2 不生成成交。

当前实现调用 `qlib.init(..., clear_mem_cache=True)`，会修改进程级 Qlib provider 状态。因此本入口只按隔离离线进程验收，不能据此宣称已经具备并发在线 predictor；后续若进入 V3，必须另行审定进程隔离或会话生命周期。

## 停止点

V2 通过只能说明该 BTC 候选的冻结特征与预测可以一致重放，不说明模型有效，更不说明美股/A 股已接入。候选已有负测试 IC、零研究成交和 `no_simulated_fills` 阻断继续保留。V3 是否启动由 V2 独立验收后的架构决策决定，不自动接入风控、OMS、保护单或账本。

## Producer 验证结果

执行环境与封存加载记录一致：pyqlib 0.9.7、LightGBM 4.7.0、pandas 3.0.4、NumPy 2.4.6；另有 PyYAML 6.0.3。封存包不是完整训练依赖锁，因此这里只证明该加载环境的确定性重放。

- 失败优先：实现入口不存在时，新增测试以 `ModuleNotFoundError: integrations.qlib_adapter.frozen_inference` 在 collection 阶段失败（1 error / 0.89s）。
- 初版 V2：`tests/integrations/test_qlib_frozen_inference.py` 为 18 passed / 63.50s，无 skip；预测变异负对照单独为 1 passed / 15.08s。
- 独立审查负例：固定环境中 `HEAD:` manifest 与 `clip_fraction=0.5` 均未被拒绝（2 failed / 38.14s），证明初版存在不可变引用和校准绑定缺口。
- 修正后定向负例：符号 manifest / 校准证据引用、clip 漂移及非有限或错误类型 clip 共 10 passed / 0.83s。
- 修正后完整 V2：首次为 27 passed、1 failed / 59.87s，唯一失败是新证据校验提前改变了既有特征错序的错误分类；保留原 fail-closed 原因后最终为 28 passed / 58.42s，无 skip。
- V1 冻结离线闭环：`tests/contracts/test_strategy_v1_donchian_offline.py` 为 11 passed / 205.40s。
- V0、M1 与既有 Qlib 混合兼容集：62 passed、1 failed / 114.16s。唯一失败是既有 `test_m1_history_stays_frozen_with_only_reviewed_post_m1_safety_fixes` 的 post-M1 静态文件白名单没有纳入已审 V1 文件；相同失败来自 V2 base，预期未修改，本票不扩大范围修它。

封存归档没有保存独立的 13 列历史特征矩阵。因此“特征通过”的精确含义是：从逐文件 hash 通过的同一 float32 provider，用逐字相同的冻结表达式、列顺序和 Fillna 处理重新生成；全量模型分数与封存 1,392 行原始预测零误差，且物理修改 provider 的未来部分不会改变截止点以前的特征。不能把它表述成与一个不存在的历史特征文件逐行比较。

V2 生产入口本身没有 fit、训练、搜索、MLflow 写入、归档写入或研究账本写入；固定 `m1-okx-qlib` 模型未重训，原封存归档和原账本 hash 未改变。需要准确保留的历史事实是：初版兼容回归曾执行 `test_real_qlib_60min_training_and_domain_replay_on_synthetic_fixture` 的两个参数例，在 pytest 临时目录中训练了两个合成 Qlib 模型，并写入临时 MLflow、模型、预测、研究决策和研究账本；独立审查后未再运行这些训练型兼容例。

本次修正未运行：上述训练型兼容例、V1、V0/M1 混合集、目标仓位/退出计算、风控、OMS、成交、持久账本、服务、页面、真实账户、OKX Demo、private/order/live、主版本发布。所有交易与晋级安全旗标保持 false。
