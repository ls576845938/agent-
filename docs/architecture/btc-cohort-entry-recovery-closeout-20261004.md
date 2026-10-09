# BTC 共同账户组合离线入口与恢复闭环

票据：`BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004`
变更风险：`demo_execution_semantics`
边界：离线模拟、候选管理；不授予 promotion、paper、live、private、order 或 real-order 权限。

## 决策

共同账户组合不是两个单策略作业的并排展示。它是一个显式版本化、exact-2 的作业：一个已登记 Donchian 规则成员和一个已登记 Qlib 成员保留各自原审定源账户；另由三阶段 cohort proposal/review/start 封印第三个共同模拟账户，并在同一 controller、同一 venue、同一 Risk/OMS/Fill/Funding/Ledger UOW 上串行推进。

单策略 `candidate_offline_job_identity_v1`、`candidate_offline_job_v2` 及其摘要算法保持原样。组合另用：

- `candidate_offline_cohort_job_identity_v1`
- `candidate_offline_cohort_job_v1`
- `candidate_offline_cohort_decision_v1`
- `candidate_offline_cohort_result_v1`
- `btc_registered_cohort_member_state_v1`

组合作业 ID 由完整 canonical cohort authority 推导，不复用任一成员的单策略 job ID。成员按 registration ID canonical 排序；重复、混合或未知 identity 均拒绝。

## 管理审定与账户绑定

共同 runtime 为 `delivery_offline_runtime_v3`，必须由外部账户目录显式提供，固定包含：

- 共同 `account_ref`、account identity hash、state directory hash 与 run ID；
- 精确 adapter 列表：`btc_donchian_history_offline_v1`、`factory_lgbm_ast_v1`；
- 初始权益精确为 `5000 USDT`；
- 单一 venue adapter：Donchian offline controller 驱动、Qlib verified observation 提供共同 mark/index/funding；
- runtime contract digest。

两个包必须先在各自原账户完成 bind、review、register。由于原管理 store 对 `(environment, account_hash)` 保持唯一租约，组合不得绕过它把两个登记改绑到同一账户。现有 `POST /candidate-offline/jobs` 使用 strict discriminated union 完成三阶段：proposal 显式列出两登记、两输入、第三共同账户与预算；review 记录人工 reason、actor、expiry 和 append-only 事件；start 只接收已审 `cohort_binding_id/digest/revision`。start 请求不能覆盖成员、账户、预算或输入。store 在 review approve 时 reserve 共同 account/state 与两个 registration/member authority；成员不能同时进入单策略或另一组合作业。

## 不可变输入与共同观察时钟

每个成员分别绑定 registration/package/binding/source/adapter、input revision/digest/head/evidence kind。Qlib `registered_offline_market_v2` 是共同 price/mark/index/funding 观察源；与 Donchian 历史输入重叠的 event time 必须 close/mark 完全一致，不一致直接 `cohort_common_price_source_conflict`，不得择一。

共同 event clock、成员列表、预算、allocation plan、共同 market facts 和前后成员状态摘要进入 decision binding。真实 Qlib final 包或合格 verified input 不存在时，页面如实 blocked；synthetic fixture 只能验证工程合同，不能成为真实候选、promotion 或 paper 证据。

## 决策与经济边界

每个事件：

1. 使用 Qlib verified observation 原样推进共同 mark/index/funding，并先由原 ledger UOW 对账。
2. Donchian 调原策略 signal preview；Qlib 调固定 inference 与原 candidate policy，生成不可变 Forecast/Signal/TargetPosition。
3. 两成员策略看到各自 allocation 份额与独立 exit/member state；Risk/OMS 看到共同账户总仓位、权益、订单、成交、资金费和账本。
4. `build_two_member_cohort_plan` 只做精确单位换算与 fail-closed 协调，不缩放策略 target。
5. delta 非零时才签发 `OfflineMultiStrategyContext`，依次走原 prepare/execute；delta 为零只持久化决策和 cursor，不调用拒绝 delta-zero 的 context。

身份、审定、预算、成员份额与恢复合同的目标支持范围严格为 exactly two、保护政策摘要完全兼容、long-only 的共同开仓，以及非空仓时各成员 hold 或 reduce。但当前精确登记对有两个结构性阻断：Donchian 原策略在 t+1 决策观察执行，冻结 Qlib 包在 t+2 delayed-open 并使用方向相关 `1.0006/0.9994` 成本；现有 exact-2 合同只有一个共同订单，不能同时保持两套执行时钟与填价。并且 Donchian 原保护 policy `btc_demo_p0_exchange_guard`（100/200bps，hash `28e04b92827f23d0c06579056094b3d48db5fb905d38eaa6ec67aa727e550465`）与注册 Qlib policy `registered-1bc91cabc0aed1edf2d75ee3`（400/800bps，hash `58f48060d29aeed9f72189352089060ee1f62c1c4645b33f7044d9d41a54f6c3`）的完整摘要不同。因此当前 pair 在任何市场／资金／Risk／OMS 经济副作用前以 `cohort_member_execution_policy_incompatible` 拒绝，并同时公开 `multi_strategy_cohort_protection_policy_incompatible`；本票不改原包契约、不统一 hash，也不新增 matcher。即使未来出现执行与保护合同均兼容的精确 pair，short、方向冲突、新成员加仓、任一成员增加、反转、预算不足、共同 market/funding 证明不完整仍须提前拒绝。V1 cohort seam 尚无可信的 hosted-protection fill 成员归属回执；一旦显式采样 mark 触发保护，必须以 `cohort_unattributed_hosted_protection_fill` 冻结现场，不把共同仓位抹平为成员份额，也不伪造策略 signal。

预算必须显式提供：共同名义上限 `<= 50 USDT`、共同亏损上限 `<= 10 USDT`，成员预算之和不得超过共同上限。不提供默认 25/25；原 target 超过成员预算时拒绝，不改公式、不自动缩仓。

## 恢复顺序

OfflineStore 先持久化 prepared decision（不推进 cursor、不宣布成员状态完成），再调用经济 authority：

1. 原 OMS/venue/ledger UOW 是经济事实权威；
2. 成功后同一 SQLite 事务持久化 result/decision、成员 next state 与 cursor；
3. 若在 ledger commit 后 projection 前崩溃，resume 使用 persisted pending decision 的 client order ID 查找唯一 ledger UOW，重构并校验同一次 decision，再修复 projection/cursor；
4. 若尚无 ledger UOW，只允许用相同 pending binding 继续；身份或摘要变化 fail-closed；
5. 重复 start、resume、事件、fill、funding 都不得重复下单或重复入账；GET list/status/result 不构造 controller、不 reconcile、不 mkdir。

## 研究冻结规程（本票不训练）

本轮工程不采集数据、不扩窗、不启动 fit。若后续收到单独研究实现授权，唯一冻结方案为：R3 六因子、标签、成本、4-fold、purge、正斜率 OLS、clip 0.05 全部不变，仅 `num_leaves: 3 -> 7`；保留 `min_data_in_leaf=240`、`lambda_l2=20`、`learning_rate=.035`、`num_boost_round=100`、`early_stopping_rounds=12`、seed 17、threads 2。最多四次 selection 加一次 final，每次单 OLS；首项失败即停止，零 retry、fallback 或 sign flip。

R3 Git 规格以 `2026-09-25T00:00:00Z` 为 audit 的右开结束边界，不是新独立窗口的起点。后续独立有效样本必须使用未参与选择规则的数据、完整标签，并严格沿用原冻结的有效样本算法和新的不可变 manifest 核算；不得用逐行计数替代 12 小时标签重叠等原规则。现有证据只能确认独立有效样本不足 30，不能给出确定达标日期，更不能保证未来研究会通过。即使之后按冻结规程运行，当前阶段结论上限仍为 `exploratory`，不得标记为有效独立确认。旧 R2/R3 的弱负相关结论和停止规则不得复活；旧 R3 诊断模型不是 final model，不能注册。
