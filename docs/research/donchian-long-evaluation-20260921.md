# 原 Donchian 固定一年历史评估：运行前冻结

本票据只绑定数据、执行一次既定历史评估并交付可复核结果。不是策略研究迭代或运行授权。当前文件是运行前规格，结果须由后续同身份产物另行记录，不提前宣称一年评估完成。

## 比较对象、版本与范围

- 已审回放源码基线：`3c0312f75a3eba0c89ec5281a3a2036a1b6ad90f`。注册 main 保持 `e2e7496acaa16b9fd5eda37dd65ea328a18ab032`。
- 已审数据交付：`4fc809deb5aac311ea33ec3608bdd8bb0dc6e03e`；实际源 manifest 固定 `03989606cebe675559b5cdcc9929baae96e8daec:.agent/data_manifests/okx-btc-long-history/okx-btc-1h-20250213-20260901-v2.json`。两份独立集成 handoff 本轮均通过 `handoff.py validate`。
- 新数据准备代码：`2d1ca3d67884073eaa7682cd23ac792a8352d54c`。仅复用共享 Qlib 的身份绑定与归一化函数导出 Parquet，不训练，不改 Qlib 特征或执行算法。
- 派生版本：`donchian-long-input / donchian-long-input-20260921-v1`，manifest 在 `56d6bd340116591d74f1bdb61614a0d4f2e9a014`；aggregate SHA-256=`7abce85b54259ca24ee699649dbc5ebd89dc1f7954443e31e2a04540dad6eeb9`。7 文件 / 3,684,492 字节。通过原 shared-data publisher 发布，不消费 staging。
- 派生数据包含原价格与资金费归一化结果，以及独立公开 REST 回执：新增 **2026-09-01 00:00 UTC** 实际资金费一条（原数据右开窗口不含它）；99 条重叠费率一致。原版本不改写。末期结算含终点，不能误把右开行情范围当作资金费结算范围。
- 本次冻结 JSON：`docs/research/donchian-long-evaluation-20260921.json`。相对旧规格仅更换 data/window；strategy、execution、budget、evidence_class 不变。
- 预热：`2025-02-13 00:00 UTC → 2025-09-01 00:00 UTC`，200 完整日 / 4,800 小时。
- 评估：`2025-09-01 00:00 UTC → 2026-09-01 00:00 UTC`，右开、365 日 / 8,760 小时；起点之后至终点有 1,095 次结算。
- 日期在查看本次收益之前固定，不换区间；原 `long_short_donchian_top5_okx_native`、params SHA `5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355` 不变。
- 初始权益 5,000 USDT；固定 0.01 张合约 × 0.01 BTC/张 = 0.0001 BTC；taker 5bps、半价差 0.5bps，成本、退出、保护均沿用冻结合同。不得为了成交或收益放大仓位。

## 执行与停止

只在独立复核后的提交态候选运行既有 `scripts/run_btc_donchian_history.py`，指定精确 `<spec-commit>:docs/research/donchian-long-evaluation-20260921.json`。

固定外部输出根：`D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-long-evaluation-20260921`；唯一 run ID：`donchian-long-20250901-20260901`。

先 `check-data`，再 `run --max-events 240` 建立首个正常检查点，然后同 HEAD / spec / run ID 执行 `resume` 至完成或既定阻断。重复 resume 不是新实验。禁止运行中提交源代码或更换运行身份。

停止条件：小时保护路径歧义、账本不一致、数据/身份错误，或安全存储阈值。发生则保留现场并报告，不自动改交易语义、不另挑区间或续开工程。末期不虚构下一根行情、不强制平仓，已发生的成交/资金费由原权威账本核验。

报告必须区分：数据合格、实际处理范围、完整或部分评估；不能将 0 成交或部分窗口描述为全年策略有效。分析成交、费用、资金费、权益、仓位、恢复与去重；固定日历分段、多空、集中度如可算则给出，样本不足则明确标注。成本压力/搜参/训练/独立确认不在本轮内。

## 风险与不变项

历史可见时间为事后按事件时间重建，非原始接收时间；资金费结算 mark 缺失，沿用前一小时可见 mark 近似；basis 是 mark/index 派生值，非官方 premium 指数。没有历史盘口、冲击、排队或历史合约规则 lineage。旧新 index 的 24 个重叠差异保留来源说明，不混用版本来追求旧结果。

不更改原策略、风控、OMS、保护单、账本、执行合同、治理或启动器；不重启服务、更新页面/架构图或合入 main。`change_risk=unclassified` 保留独立集成要求，但本轮只是独立源码/数据候选及历史运行，不是部署或 promotion 交付，不触发无关服务重建。

`promotion, demo, paper, live, private, order, real_order, transfer, withdraw, execution_permission, runtime_observed` 均保持 false。唯一联网动作是既有白名单公开资金费入口；未读取密钥或账户。

## 预检与验收记录

角色 data_steward；planner 专属 sparse 工作区、初始限定 dirty=[]，其他工作区/main 与旧数据未改。touch set：新增数据准备脚本、该脚本测试、冻结 JSON、本文、对应 data manifest 与本票据 append-only handoff。执行代码与已审基线无差异。

读取 preflight / handoff / gate-evidence-review 技能，shared / data_steward / btc_developer playbook，以及数据可靠性、回测证据、执行微观结构、审计、资金费与基差、参考价格、API/密钥安全、成本/强平与风险预算规则。catalog=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

命中：BTC-PERP-001, BTC-WS-001, CN-DATA-PIT-001, DATA-BTC-FINAL-001, DATA-FRESHNESS-001, DATA-US-PIT-001, DATA-VERSION-001, GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-ARTIFACT-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001。未触发 WS/美股/A股业务，未全文重读事故日志。

失败优先：脚本不存在时 1 个 collection error；实现后边界检查 7 passed。首次与历史合同合跑时 51 passed / 1 failed，失败为运行期间并行提交 manifest 导致 `btc_demo_dispatch_source_head_mismatch`，这是本次操作顺序错误，非放宽版本门槛的理由。固定 HEAD 后必须重跑，不隐藏第一次失败。

固定 HEAD `32a2831e4628011f8c784512687c17b92acccb8b` 后，原合跑 **52 passed in 49.42s**，版本门槛未改。

实际 check-data 发现 v1 的全空 markPrice 经 Arrow null 转成 Python None，无法被原消费者解析为 Decimal。仅在派生转换中统一为数值型 NaN，仍然缺失，不填零；增补 Parquet 往返测试后 **8 passed in 8.75s**。不改回放消费者。失败版保留，不用于评估。

**最终数据选择替代上文初版**：`donchian-long-input-20260921-v2`；数据转换源码 `0dd7af8834984d2a29d3fc2fedc431629df2c3bf`；manifest 提交 `02e85c7e035cf9fdd8becc8ea110c1bffef57964`；manifest SHA `349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d`；aggregate `62bed3a6efa945d8fa4f52917667dc44a276add7ed280bb45085ef52950d10af`；7 文件 / 3,684,810 字节。三个价格 Parquet 哈希与 v1 完全相同；资金费 mark 列类型改为 numeric missing。终点回执从 v1 提交态 manifest resolver 核验后复用，未再次联网。

独立复核、check-data 与正式运行结果由最终结果报告补充。回退：停止本次离线任务并继续使用旧 Git/manifest 引用即可；不删除旧数据、不复写旧结果。
