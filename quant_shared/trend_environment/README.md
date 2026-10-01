# 共享趋势环境（M1）

职责：按资产 × 历史趋势窗口输出描述性观测。`model.py` 是纯函数，没有 pandas、文件、网络、broker、风险或交易依赖。

- 输入：明确资产、已完成 bar 的 event/close/available time、决策时间、注入的预期收盘日历、冻结窗口/年化周期/最大年龄。
- 输出：方向、路径效率比（趋势适配度）、单 bar/年化收益波动、最后一根收益相对先前窗口波动的冲击比、窗口方向/效率变化；不是学习模型或校准概率。
- warmup 需要窗口 + 2 根价格，供前后两个收益窗口比较。缺失、不完整、不可见、过期、重复、无效价格明确 unknown。零方差下冲击不识别，不造零。
- 不同资产各自计算；未来行与未来日历不影响历史值或滚动输入 hash。session calendar 由数据合同拥有，不能使用 BTC 的连续小时历代替股票市场。

接入：`integrations/qlib_adapter/trend_environment.py` 在普通 pipeline 与 Factory trial 封印之前运行同一生产者，保存单独 JSON/JSONL。Context 只承载不可变 evidence_refs，不新增 schema、不传给实际 BTC 决策。

读取：既有 seal reader/详情 API 验证文件 hash 以及 run/data/code/config/source-input-seal/context 关联；旧 run 返回 missing，GET 不补算。前端复用 QlibRunSummary（研究台、组合页、策略模块）和工厂的子试验链接，默认折叠。

修改禁区：默认特征、工厂选优目标、风险输入、目标仓位、退出、OMS/保护单与账本。此目录不拥有交易权限。后续任何决策接入另需 M2—M4 授权和有效性证据。

对应测试：`test_trend_environment.py`（纯函数）、`test_trend_environment_sidecar.py`（版本与 API）、`test_m1_btc_behavior_freeze.py`（不变区与三态对照）、`test-trend-environment.mjs`（真实组件静态渲染）。当前交付状态见 `docs/operations/m1-trend-environment-20260911.md`，不以此说明代替运行事实。

## 描述状态 v2 与条件政策研究

`state_v2.py` 是资产中性的因果滚动状态生产者，输出方向、归一化趋势强度、72 小时路径效率、多尺度一致性、波动及历史相对位置、波动扩缩、冲击、持续时间和切换频率。它的标签是描述区间，不是状态概率；funding、OI、深度没有带可见时间的输入时必须保持 missing。重复、乱序、未来或不可用 bar 不得改变已接受状态，缺口之后必须重新预热。

`entry_policy.py` 只定义一条默认关闭的研究政策：当前空仓且原目标非零时，72 小时路径效率未知或低于 0.20 才可把本次新增目标改为零。已有持仓、减仓、退出、反向先平和保护义务必须保持原路径。`market_policy_attachment.py` 只负责把状态定义、政策、完整基础策略身份、数据、成本、时间及证据绑定为可验证附件，不注册策略、不启动运行。

当前提交态诊断位于 `.agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json`。它使用 2960 根历史小时 bar，将 28 次开平仓按精确决策时间分组为低效率 18、混合 9、方向性 1，并识别 170 个连续状态片段。这三类数量是不同样本单位，不能据此推导概率、胜率或独立样本量；逐笔资金费不可分配，Donchian 没有预测序列，因此 IC/Rank IC 不适用。

条件政策 A/B 仍为 `not_started`，18 次“可能被拒绝”只是事后计数，不是新的成交或收益。正式试验必须使用冻结的两个回放臂、相同数据/成本/账户，同时报告敞口与持仓时长；不能因为交易变少就声称状态识别改善。BTC 实际消费、Demo、paper、live 和交易授权不属于此共享模块。
