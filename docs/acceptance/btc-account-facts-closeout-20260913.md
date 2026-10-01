# BTC 账户事实与持久闭环收口验收

- 票据：`BTC-ACCOUNT-FACTS-CLOSEOUT-20260913`
- 基线：`0c9efaf51a95ed69bfb7f1180b4a6fbf22d85743`
- 变更风险：`demo_execution_semantics`
- 发布路径：专属 sparse producer，提交态 handoff，随后由独立 integrator 集成
- 当前结论：工程合同与离线闭环可验收；真实 Demo 账户回撤仍为 unknown，所有交易权限保持关闭

## 合同与职责边界

新增 `btc_account_drawdown_fact_v1`，同时记录 USDT 金额回撤和比例回撤，绑定账户身份、账户范围、币种、快照、观测时间、覆盖起点、基线权限和事实摘要。首次快照不会自动成为高水位基线；只有显式审定的 `explicit_reviewed_account_baseline_v1` 可作为工程起点。外部充值或划转的覆盖不完整、非零或未知时，事实保持 unknown。

Guardian 新增显式 `max_drawdown_unit`（`usdt`、`ratio`、`unknown`）。默认是 `unknown`；历史裸 `max_drawdown` 数值不被解释成金额或比例，且原始 `drawdown`/`drawdown_pct` 不能绕过版本化事实。旧 T2 risk kernel 的无单位参数没有在本票据中改义。

实际 `_commit_ledger_reconciliation` 现在把账户事实同时写入 ledger UOW payload 与 `state_after`，由现有 `BTCRuntimeStore` 的事件哈希、幂等键和 checkpoint 恢复。两处必须同时为空走 legacy，或同时存在且精确相等；state-only 和 payload-only 都在 append 前拒绝。经济重放从基线后的 committed UOW 去重 fills/bills，以 `contracts × contract_value_btc` 重算仓位、交易现金流、手续费、funding 和最终权益，再与独立传入的最终 exchange snapshot 比较。错权益或错仓位会使 reconciliation mismatch、进入 cancel-only，并把当前回撤事实降为 unknown；最后一个有效高水位事实不会被错误快照覆盖。

独立审查后补齐观测时间绑定：Guardian 除账户和经济快照 hash 外，还要求版本化 fact 的 `observed_at_utc` 与实际 snapshot 观测时间精确对应。经济内容相同但时间更晚的正常 poll 会生成新的时间绑定事实和新的 UOW identity；同一观察重试保持幂等，fills/funding 仍按自身 ID 去重。旧 fact 不能借同一经济 hash 附着到新鲜观察。

本票据未改默认 BTC candidate、参数 hash、信号、仓位公式、退出阈值、T2 risk kernel、OMS 生命周期、保护单或账本经济语义；仅为既有执行链补齐账户事实、版本单位、持久恢复和独立经济核对。

## 固定反例

覆盖：`100→90`、`100→110`、重启后 `110→99`；账户/范围/币种变化；NaN、Inf、非正权益；倒序、未来、过期和同时间异 hash；外部现金流未知或非零；同一观察幂等、同 hash 异经济冲突、同 hash 新时间正常观察；事件已 fsync 但 checkpoint 落后、损坏/截尾；UOW state-only/payload-only；旧 fact 加同 hash 新时间；自洽容器 hash/count 下的错权益和错仓位。错权益和错仓位通过真实 `_commit_ledger_reconciliation → commit_ledger_uow` 路径触发 cancel-only，并非只调用测试 helper。

## 验证

- failure-first：新增合同测试在模块实现前因 `ModuleNotFoundError: quant_crypto.oms.account_risk_facts` collection 失败；这是缺失实现证据，不描述为经济缺陷复现。
- 独立审查 failure-first：修订前 state-only fact 被接受且恢复无 blocker；旧 fact 加同 hash 新时间被 Guardian 误判为 PASS。修订后两项固定负例 `2 passed`。
- 新增限定合同：`23 passed`，包含连续相同经济 poll 的时间区分、同一观察重试幂等及 fills/funding 去重正例。
- Producer sparse 可运行矩阵：原 8 文件 153 项加新增限定合同 23 项，共 `176 passed in 7.83s`。
- M1 精确 blob、默认 candidate/hash 与 observer-invariant 行为包含在上述矩阵，`3 passed`。
- 原有后端 read-only/current-main 52 项在 producer sparse 中因只读依赖 `quant_cn` 未被 planner 检出而 collection 阻断（`ModuleNotFoundError: quant_cn`）；不是业务断言失败。按治理边界不扩 producer sparse，由独立 integrator 在其完整依赖工作树统一执行 205+23 共 228 项。
- `git diff --cached --check`：通过。

## 未执行与阻塞

- 未访问网络、secret、private/order/live endpoint；未启动服务；未创建或发布 BTC runtime artifact。
- 未执行真实 Demo 账户历史、充值/划转完整性或交易所只读对账；因此生产回撤事实仍是 unknown。
- 当前运行配置仍未给历史 `max_drawdown` 指定受审定单位；默认 Guardian 会同时报告 `max_drawdown_unit_unknown` 与 `drawdown_unknown`，不会解除新增风险阻断。
- 持久账本和经济重放在工程注入的显式基线、完整零外部现金流条件下通过；这不是生产账户对账证明。
- `promotion_evidence_ready=false`；paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、demo_control 均保持 false。

## 治理证据

- 阅读：`docs/knowledge/README.md`、系统不可妥协规则、共享与 BTC developer pitfalls、delivery risk policy，以及研究/组合风险/OMS/架构监控/BTC 市场结构与策略 playbook。
- Active pitfall IDs：`BACKTEST-COST-001,BTC-NONFLAT-001,BTC-OMS-001,BTC-PERP-001,BTC-WS-001,DATA-BTC-FINAL-001,GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-HANDOFF-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,MONITOR-AUDIT-001,QSYS-BOUNDARY-001,QSYS-GATE-001,QSYS-LEDGER-001,QSYS-SECURITY-001,REPLAY-ISOLATION-001,RESEARCH-HOLDOUT-001,GOV-PROMPT-001,GOV-WINDOWS-001`。
- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 初始声明路径全部 clean；未覆盖其他代理 dirty，未消费其他 worktree 未提交文件。
