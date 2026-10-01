# V1 单策略离线闭环集成与验收基线

## 结论与状态

本票据已将 V0 冻结基准、V1 Donchian 业务切片、已审的 Signal/Forecast 减仓来源合同、`REDUCE_ONLY` 动作投影、限定只读交付规则及两份独立审查证据集中到一个独立候选树。

当前仅为 **技术候选基线**：完整 V1 业务验收尚未通过，页面验收和正式发布未开始。不得将已通过的 97 项业务切片或 149 项治理回归描述为 V1 整体通过。

| 阶段 | 状态 | 说明 |
|---|---|---|
| 技术候选集中 | 已完成 | 上游提交、handoff、独审 ack 及精确源树已固定 |
| 完整离线业务验收 | 待实现与独审 | 反向重新开仓、最终退出、身份/输入绑定与关键恢复点未闭环 |
| 只读页面关联验收 | 未开始 | 离线 V1 不得冒充历史 Qlib/factory run |
| 正式发布 | 未开始 | 未改 `main`，未重启服务，未生成 promotion evidence |

## 票据和候选身份

- parent V1 ticket：`STRATEGY-V1-DONCHIAN-OFFLINE`。既有治理合同中的 source receipt 仍使用该身份。
- closeout child ticket：`STRATEGY-V1-CLOSEOUT-INTEGRATION-20260915`，仅用于集中候选、冻结验收与最终独立判定，不修改准入合同。
- change risk：`demo_execution_semantics`。
- approved main base：`b920d131e41ecbfe7f76f0709affbe22c8b35f5e`。
- assembled source candidate commit：`2fe7bf8729e306f1c89b8728976f1b005eb54892`。
- assembled source candidate tree：`7dc090069b09e988e509135a0c5501eb23968df9`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

### 已校验上游

| 职责 | source / report | handoff / ack | 候选使用方式 |
|---|---|---|---|
| V0 行为冻结 | `e0b7a08f88fcc20bbe56bb93de655469927cd902` | `2b4cada2ce62bdaba434f28099fffac0b6d0e03f` | 已在 V1 业务 ancestry 中 |
| V0 独立审查 | `4813854858118c7b9155cb5247272a46b273521c` | `61f4e31429755046c3f8d7bab9dad96f3ca843ab` | 历史独立证据，不代替当前候选回归 |
| V1 业务切片 | `7ec632f9341dcc4b2fdfef7f3e4792eb2aac383f` | `6edb1e5961bab4f3ecaf6e222bd60bbcf373c7c2` | 已合入候选 |
| V1 业务独审 | `df9689529c902fe012831950188300252b10ec9f` | `528049d06cdf82276115dca5ec4c79a896bbbe8d` | 报告与 ack 已合入候选 |
| 限定只读交付治理 | `3d64b5c433c2c05498aa6e1c94014e9e473552cb` | `b1cbc46b5b87854423af46449dc6d6a3ec973f86` | 已合入候选，尚未激活 |
| 治理独审 | `4d46619831450009922d215050a2d2c02029d9a7` | `12d0962eca5eb3fd262fe9545a4add9020cb0587` | 报告与 ack 已合入候选 |

三份 published handoff 和两份 acknowledged handoff 均已对 Git 对象运行 `validate_handoff_against_git`，结果均为空错误列表。生产者 base ancestry、V0 -> V1 ancestry 及 deliverable SHA-256 均有效。

## 冻结的策略、账户和输入

| 项目 | 固定值 |
|---|---|
| strategy | `long_short_donchian_top5_okx_native` |
| candidate | `okx_native_btc_ls_tf_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_78f5f0a0e4` |
| version | `btc_long_short_donchian_top5_okx_native@1.0.0` |
| params hash | `5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355` |
| 标的/周期 | `BTC-USDT-SWAP` / 最新已完成 1h 产生原多周期决策 |
| 仓位规则 | `sign(raw_signal) * 0.01 contracts`；不是 `0.01 BTC` |
| 合约面值/上限 | `ctVal=0.01 BTC`，`max_net=0.01 contracts`，`max_notional=10 USDT` |
| 成本 | fee `5 bps`，funding `1 bp`，slippage budget `5 bps`，impact `0` |
| 初始离线账户 | equity `5000 USDT`，空仓，无订单/成交/保护单，不是真实账户事实 |
| 固定输入 | 单一连续 OHLCV 时间线前缀，依次驱动 open long -> hold -> reverse close -> same-bar open short -> exit flat |
| 固定时钟 | 显式 UTC event/available/decision clock，禁止用墙上时钟改变回放结果 |
| 证据等级 | `offline_execution`，`runtime_observed=false`，非市场有效性和 promotion 证据 |

策略参数、目标数量、成本和预期行为以 `tests/fixtures/strategy_v0/baseline.json` 为权威基准。后续不得为了通过测试更改该预期。

## 精确源树指纹

以 assembled source candidate `2fe7bf8729e306f1c89b8728976f1b005eb54892` 为准；下表是 Git blob OID。任一项变化都必须进入最终精确 diff，不能继承旧测试数量作为新身份证明。

| 路径 | blob OID |
|---|---|
| `docs/architecture/strategy-admission-v0.md` | `af4bbf8d3d9847df73fd63a59f47dc0cf94f3eed` |
| `docs/architecture/strategy-admission-v1.md` | `e326302c28ae03b2b31601f90b73d1ea234d32ec` |
| `quant_crypto/application/donchian_offline_replay.py` | `eb2aa17c862297f039c2091a396e607f19236aeb` |
| `quant_crypto/oms/okx_demo_paper_runtime.py` | `135a4d3d0f8ca39d5fa8806cf53cf4218b12b692` |
| `quant_crypto/oms/shared_platform_v3.py` | `beac3a14d01953fd1d8625a8ef0334ce404b816c` |
| `quant_crypto/portfolio/decision.py` | `aa72cceb8a5a701862e0ed7d6b71d3a836b9d1d5` |
| `quant_crypto/runtime/control_plane.py` | `a7a490e3228e87c1ad355c6639fb3ac2d3bb6c2c` |
| `quant_shared/strategy_runtime/decision_envelope.py` | `473b7ff1915a588f2cca4c0aebffdec4f1e163c7` |
| `tests/contracts/test_btc_okx_demo_paper_runtime.py` | `085df7c2746b2adf7dbca3522c126754c843dbcd` |
| `tests/contracts/test_btc_shared_platform_v3_oms_delegation.py` | `13aab9f59ff8d9fa2df4687084d6e4c46aa81ea0` |
| `tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py` | `3526a79e9461cba9e58c5ffd85722e40f04ed329` |
| `tests/contracts/test_strategy_v0_freeze.py` | `d61508bd40a8cff99552e3208554e5e9a38a4cf7` |
| `tests/contracts/test_strategy_v1_donchian_offline.py` | `73ab44a8ba9b4a0b2ac4b1b83f86b974879f03f9` |
| `tests/fixtures/strategy_v0/baseline.json` | `ce7edb5df2e6512447dd10def3deb37336bce898` |
| `tests/fixtures/strategy_v1/offline_contract.json` | `ae6788b67a08dbf9c5c143f5b35077780b8c776c` |
| `docs/agent_playbooks/delivery_risk_policy.json` | `5b95beae4d51068c4c3b1c3a2f293156492dc83f` |
| `docs/agent_playbooks/strategy_v1_readonly_delivery.md` | `a5b0d016ecadc8be5f65a187782ab086ae0eeeb1` |
| `tests/agent_governance/test_strategy_v1_readonly_delivery.py` | `d9da9a284fe58f8fbc65754bbf47438291082bd8` |
| `tools/agent_governance/delivery_policy.py` | `094fd3683264d0b3a945f763a3dbc51d66327f8c` |

## 冻结的完整技术验收清单

下列条件必须在同一个最终提交态候选上全部成立。测试总数不是代替品。

### A. 身份、时间与可见输入

- 每个阶段进入原 controller 之前，持久绑定 `strategy_id/version/params_hash/code_version/package_digest/run_id/data_version` 与 canonical frame digest。
- event id 绑定 canonical visible-frame digest 和 completed-bar UTC 边界；只换数据内容也不能误命中已完成事件。
- 增加决策时点之后的数据不改变过去决策；未完成、过期、时区不明或错身份输入均 fail-closed。
- 重用 state directory 时，错 `run/package/code/data/frame` 不得返回旧证据。

### B. 单策略纵向业务结果

1. 空仓 -> long：产生 `0.01 contracts` 的非零模拟 fill，经 T2/T3、Guardian、OMS、dispatcher、保护与 ledger。
2. long -> hold：目标未变时不重复加仓、不增加 fill 或 ledger UOW。
3. long -> short：必须先产生 `reversal_close`，平多后 ledger 仓位精确为零。
4. 同一可见 bar 继续 -> short：在不伪造健康事实的前提下完成 `reversal_open`，目标 `-0.01 contracts`。
5. short -> flat：按原退出/目标规则平空，最终 orders、fills、positions、cash 与决策证据一致。

上述每一步都使用原注册 Donchian `signal_callable`、原固定合约目标和既有 BTC 风控/OMS/保护/账本链；不允许复制策略算法或新建第二套 OMS。

### C. 幂等、关键重启与提交后恢复

- 同一事件重放不增加订单、fill、ledger UOW 或 decision evidence。
- 在订单意图持久化后、fill/ledger 提交后但证据写入前、`reversal_close` 后但 `reversal_open` 前及最终 flat 后重启，都不重单、不重复记账。
- ledger 已提交但证据缺失时，只能从 exact input anchor 之后的权威 order lifecycle 与 ledger UOW 重建证据关联，不得再次提交订单。
- 反向分阶段恢复必须区分 close 已完成和整根 bar 已完成，不得吞掉 reopen。

### D. 账本经济一致性

- PnL/equity 只从 fills、position ledger、cash ledger、fee 和 funding 重算。
- 订单数、fill 数、签名仓位、现金变动、手续费/资金费和证据引用在每个阶段相互对应。
- 模拟 venue 必须保留真实的 OCO 生命周期，并通过既有 cleanup/cancel/readback 入口终结 runtime-owned registry；不得直接清除状态或强制标记健康。

### E. fail-closed 与旧语义保护

- 缺 account/drawdown/protection/ledger/public/private-WS 事实，事实过期，来源 ID 缺失/冲突/篡改，错单位或越界数量均必须拒绝。
- 真实 `CANCEL_ONLY`、`FROZEN_UNKNOWN`、`STARTUP_RECONCILING`、风险未知和新增风险禁止保持原拦截。
- 旧 Forecast 减仓 wire 兼容保留；Signal 来源不允许伪造 forecast id，普通无来源 target 不得自动降级为 Signal。
- Demo、paper、private、order、real order、live、promotion、transfer、withdraw、runtime worker/observed 仍全部为 `false`。

### F. 回归与版本审定

- V0 goldens 保持，原 Donchian 信号、目标、退出、冷却及成本预期不变。
- 已审 Portfolio/OMS/dispatcher 切片和治理矩阵必须在最终候选上重跑。
- `tests/contracts/test_m1_btc_behavior_freeze.py` 的历史 base 不得挪动，不得 skip/xpass。只有在最终独审确认实际批准源差异后，才能将对应的精确新 blob 身份登记为合法变更；不得复制算法、改预期或降低保护强度来消除失败。

## 实现边界与工程循环燔断

1. 下一个唯一 BTC producer 优先只修复新离线回放适配层及其固定测试/输入。
2. 只有在正确的离线事实下能在生产权威链确定复现的缺陷，才允许根据已审 touch set 做最小修复；不得改 Guardian/风控阈值迁就 fixture。
3. 本验收清单冻结后，新发现先分类为「本闭环直接阻断」或「backlog」，不自动扩因子、模型、多市场、前端或交易权限。
4. producer 只交付一次最终 committed handoff；随后由本独立 integrator 在完整候选上做一次整体审查。通过则进入「技术通过」；未通过则给出剩余阻断、成本与路线选择，不自动开新修复轮次。
5. 技术通过后才能锁定最小只读页面关联；页面必须显示 `offline_execution` 与未绑定运行，不得将其塞入 Qlib/factory run。发布仍是后续独立状态。

## 当前集成校验证据

- 工作树由 planner 从指定 main base 创建，`sparseCheckout=true`；所有声明路径初始 `safe_status=clean`。
- 业务与治理两组交接按顺序合入。两份独审报告因上游历史树将同名路径删除而出现 `modify/delete`；本集成只保留 handoff SHA-256 已验证的审定报告，无业务冲突。
- `git diff --check b920d131e41ecbfe7f76f0709affbe22c8b35f5e 2fe7bf8729e306f1c89b8728976f1b005eb54892`：通过。
- 本阶段未重跑业务或治理 pytest；原 97/149 通过仅作为上游切片证据。完整回归留给 producer 最终交付后的一次集中验收。

## 当前已知直接阻断

- 平仓后 drawdown observation 存在时间戳冲突，venue protection 与 runtime-owned protection registry 尚未收敛，因此同 bar `reversal_open` 正确 fail-closed。
- 离线 runner 的 package identity、canonical visible-frame digest、post-ledger evidence repair 和 close-restart-open phase recovery 尚未完成。
- 完整退出归零和上述关键重启点尚无同一候选上的纵向证据。

这些阻断是本次集中实现的固定输入，不会自动派生额外模型、页面、交易所或权限任务。

## 预检与安全边界

- 已读：`AGENTS.md`、`docs/knowledge/README.md`、`quant_system_non_negotiables.md`、`shared_pitfalls.md`、`domain_architecture_rules.md`、integrator profile，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review` 技能。
- 命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未全文读取原始踩坑日志。
- 未读凭据或账户，未访问网络、broker/exchange、private/order/live endpoint，未提交真实订单。
- promotion、paper、live、private、order、real order、transfer 和 withdraw 均保持 `false`。
