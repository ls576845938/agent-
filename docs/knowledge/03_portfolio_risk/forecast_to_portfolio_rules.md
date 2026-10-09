# Forecast To Portfolio Rules

来源主线：Active Portfolio Management。

## 适用范围

多策略、多标的、BTC-only 仓位管理、ETF 轮动、US Equity 组合、风险预算。

本文区分两条合法路线：

- **预测路线**：模型输出 `Forecast`，适用 IC、校准、置信度、alpha 和 transfer coefficient 等预测质量要求。
- **规则路线**：经版本化、参数和数据身份冻结的规则可输出 `Signal` 或 `TargetPosition`，不得伪造 `Forecast`、IC 或模型校准。它仍必须经过 Portfolio/Risk、OMS/Execution、Fill/Ledger 和审计链。

下文的 IC、alpha、预测置信度与 Forecast 定标要求仅对预测路线强制；风险预算、成本、容量、时间语义、OMS、成交、账本和 fail-closed 对两条路线都强制。

## 核心规则

1. Signal 不等于可直接交易的订单；预测路线必须先转成 forecast，规则路线可按冻结的仓位规则转成 TargetPosition。
2. Forecast 必须说明预测对象、预测周期、单位、置信度和失效条件；纯规则输出必须明确标记为规则信号，不能借 Forecast 名义绕过冻结政策。
3. Portfolio construction 必须在 signal 和 order 之间。
4. 单策略回测收益不等于组合贡献；要看边际风险贡献和相关性。
5. 目标仓位必须同时受预测强度、波动率、相关性、容量、杠杆、回撤约束影响。
6. BTC-only 也要有组合层；至少要管理现金、BTC 暴露、风险预算和停机状态。
7. 预测策略必须记录 IC 或等价预测质量指标；规则策略必须记录冻结规则、触发、参数、风险与成本后表现，两者都不能只靠历史收益分配资金。
8. 换手是组合成本的一部分；高换手策略必须证明成本后仍有边际价值。
9. 风险预算要先于收益最大化；组合优化不能把估计误差当确定性。
10. 仓位缩放必须可解释，不能用后验收益曲线调仓。
11. 主动组合必须区分 benchmark return、active return、residual return。
12. 信息比率 IR 是主动管理的核心预算，不是单纯绩效展示指标。
13. 预测质量必须用 IC、t statistic、hit ratio 或类似指标记录，并说明样本长度。
14. 广度 breadth 必须是独立机会数，不能把同一个年度观点拆成 12 个月后冒充 12 次独立预测。
15. 组合优化必须记录约束导致的 forecast loss 或 transfer loss；长期只看未约束最优组合没有意义。
16. 组合构建和交易执行是两个问题：前者决定目标组合，后者决定如何从当前组合走到目标组合。
17. 当成本不为零时，最优行为通常不是每次 alpha 变化都立刻全量交易。
18. 高换手只有在新增 value added 超过交易成本和短期风险时才允许。
19. 仓位调整应优先执行单位成本价值最高的交易，而不是机械按目标权重一次性调完。
20. 多策略叠加必须看相关性、共同因子暴露和边际主动风险贡献。

## Active Management 指标

组合层至少要区分：

- `alpha`: 预测残差收益。
- `score`: 标准化信号分数。
- `ic`: 预测与未来实现的相关性或等价预测质量指标。
- `breadth`: 每年独立预测机会数。
- `information_ratio`: 主动收益相对主动风险。
- `active_risk`: 相对 benchmark 的主动波动。
- `residual_risk`: 剔除系统/benchmark 暴露后的剩余风险。
- `transfer_coefficient`: 约束组合对原始 alpha 的传递效率。

## Forecast 到 Alpha

本节只适用于预测路线，不要为了复用该流程而给规则信号伪造 forecast 或 IC。

规范流程：

1. 原始信号归一化为 score。
2. 用历史或样本外 IC 估计预测质量。
3. 用波动率和 IC 把 score 转成 alpha。
4. 对 alpha 做 winsorize、衰减、置信度缩放和容量约束。
5. 将 alpha 输入组合层，而不是直接输入 OMS。

禁止流程：

- `signal > 0` 不经冻结仓位规则、Portfolio/Risk 和成本阈值就直接满仓。
- 用全样本最优收益给 alpha 定标。
- 根据回测净值曲线手动放大仓位。
- 把不同周期、不同资产的 signal 当作同单位可加。

## 最低组合对象

组合层应输出：

- `target_weight`
- `target_notional`
- `risk_budget`
- `expected_volatility`
- `marginal_risk_contribution`
- `active_risk`
- `residual_risk`
- `expected_active_return`
- `information_ratio_estimate`
- `forecast_confidence`
- `capacity_estimate`
- `turnover`
- `transaction_cost_estimate`
- `transfer_coefficient`
- `constraint_violations`
- `rebalance_reason`

## 换手与交易成本

组合层必须回答：

- 本次调仓的预期 alpha 增量是多少？
- 本次调仓的预期成本是多少？
- 如果只执行 25%、50%、75%、100% 的目标换手，value added 如何变化？
- 哪些交易最值得先做？
- 哪些交易因为成本、流动性或最小下单量应被延后？

如果不能回答这些问题，不能把目标仓位直接送到 OMS。

## 风控约束

必须显式配置：

- 最大单标的权重。
- 最大净暴露。
- 最大杠杆。
- 最大日换手。
- 最大回撤停机线。
- 最大单日亏损停机线。
- 数据异常停机线。
- 流动性不足或交易所异常停机线。
- 最大主动风险。
- 最大残差风险。
- 最大因子暴露。
- 最大单次调仓换手。
- 最大 forecast decay 后持仓期限。

## Codex 开发检查

修改组合或风险模块时必须确认：

- 路线是否明确标记为预测或规则；预测路线的仓位是否来自 forecast，规则路线是否来自已冻结的 Signal→TargetPosition 规则。
- 预测路线的 forecast 是否有 IC 或等价置信度来源；规则路线是否避免伪造这些字段。
- 是否记录了风险预算和约束命中。
- 是否记录了主动风险、残差风险和边际风险贡献。
- 是否能解释为什么从旧仓位变成新仓位。
- 是否有最小下单量、最小调仓阈值，避免噪音交易。
- 是否估算了交易成本和换手损耗。
- 是否把订单切给 OMS，而不是直接交易。

## BTC-only 适配

BTC-only 没有横截面 breadth，但仍有时间序列 breadth。必须保守处理：

- 不得把高频 bar 数量等同于独立机会数。
- 日线、4H、1H 信号若高度相关，不能简单相加放大仓位。
- 多周期共振必须说明是提高置信度、降低噪音，还是增加独立信息。
- 仓位上限应来自目标波动、最大回撤、流动性和交易成本，而不是来自回测最优杠杆。
