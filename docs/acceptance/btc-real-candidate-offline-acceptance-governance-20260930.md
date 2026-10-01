# BTC 真实候选离线验收治理 producer 报告

## 结论

已建立一次性、两阶段、fail-closed 的交付合同与只读 validator。当前只是治理 source delivery，不是真实候选、离线 run 或业务验收通过证据。

业务 producer 已从审定的 handoff 修复基线 `ee42a967663d7bc306b4ac8b0d3c7d178f5b79cd` 机械复封干净 R `4f730f54b34e3d2c2af7cc62e796058bc2fc3048` 与经验证的 source handoff；合同继续封存相同的精确 inventory、feature/dependency/combined fingerprints。`validate-source` 现在必须通过，但这只解除 source freeze 阻断，不代表真实 fit、候选质量、离线业务验收或交易权限通过。

## 职责边界

本票只新增：

- 一次性 JSON 合同；
- 合同说明；
- 只读 validator/CLI；
- failure-first 治理测试；
- 本验收报告；
- 待交付提交产生后的 append-only handoff。

未修改任何 BTC 工厂、策略、风控、OMS、ledger、资金费、数据、运行服务、认证、权限、启动器、hook 或通用 risk policy。未启动服务、未训练、未采集、未登记候选、未读取账户或交易端点。

## 验收内容

- `source_review` 只审代码/测试/独审/提交态 handoff，不依赖 fit、candidate 或 run。
- 业务审查源 R、生产基线 S 和冻结运行基线 F 可不同；合同先封 R，post-S 的 Q 记录 S/preparation/runtime review，运行后 post-F 的 A 记录验收证据。要求 R→S→Q 与 S→F→A 均可构造，不要求 Q 进入 main 或成为 F 祖先；`consumer_commit=execution_commit=F` 且 current main 仍为 F。
- F 及 pre-run blocked campaign 只能增加合同列出的审查/身份/证据文件和本票精确 handoff；任意未指纹源码或治理/数据准备文件增量均 fail-closed。
- 独立集成修正后的真实 Git fixture 已通过完整 `blockers()` 路径分别构造 source-review receipt 与 deployment-acceptance receipt；同时证明 Q 无须成为 F 祖先、S→F 或 pre-run campaign 夹带源码会被拒绝、业务通过时五次实际 fit 均必须成功。
- 唯一 campaign 最多 5 次实际 fit，failed/crashed 也占预算，筛选失败禁止 final-audit fit。
- `passed` 必须是 48 小时、6 结算事件、1 个正式 run；请求目标为 24，但记录首个真实安全内部 checkpoint 并同 task 恢复，禁止按 PnL 选点。
- 真实分钟采样必须标为非 tick 路径，非交易所精确资金费结算。
- 筛选/校准失败可交付 blocked report，但 validator 仍返回 business acceptance blocker，不会把报告写成 pass。
- 临时 `candidate_management` + `local_no_password` + offline worker 与最终 `research_readonly` 归位分开记录；offline worker 不推导交易权限。
- 归位不强制把现有 auth mode 改成 `key`，只要求不为归位改 auth、不新增密码步骤。
- source handoff 限定真实业务 ticket/`btc_developer`/`btc`/`published`；固定实现 inventory 覆盖实际 primitive/package/runtime 路径；fit、四 binding、checkpoint/run/ledger 必须以既有 artifact 的 logical path/revision/schema/content hash/seal hash 由单一结构化 campaign evidence manifest 交叉核对，review report 必须含 phase/commit/decision/blockers/not_run。
- 经限定授权，source/test allowlist 从 12/9 扩为 14/10，只增加外部只读研究目录的 `app_factory.py`、`candidate_delivery_bootstrap.py` 与 `test_qlib_pipeline.py`；不改变运行、账户、订单或权限合同。
- 所有安全旗标必须齐全且为 literal false；缺字段、字符串 `false`、0 或 null 均拒绝。

## 验证结果

- failure-first：测试先因 validator 模块不存在而失败，不是先有实现再补断言。
- 初版 focused governance regression：`19 passed in 72.17s`。
- 旧提交 `660691d` 的 “28 passed” 仅是编辑过程证据，不能作为提交态验收结论；本轮会在五文件冻结并提交后重新给出 exact-commit canonical contract hash 与完整回归结果。
- 当前真实合同：`inspect-contract`/`validate-source` 必须验证干净 R、source handoff、23 个实际变更路径及固定指纹；source 封存成功不改变业务 gate。
- 独立集成修正后的完整治理回归：`34 passed in 237.19s`；该结果只证明治理合同可构造，不代表 source 已封存或业务验收通过。

封存提交须运行真实 `validate-source`、source handoff validation、限定 safe status 与对应 sealed-contract 回归；既有 API、48 决策和治理全量回归按不变 blob 继承，不重复长测。

## 保持 fail-closed

`demo_control_enabled=false`、`promotion=false`、`paper=false`、`paper_order_allowed=false`、`live=false`、`live_order_allowed=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`broker_endpoint_access=false`、`exchange_account_access=false`。

这些旗标的 false 必须来自显式验收 receipt，不是缺证时的推定。本治理交付的 readiness ceiling 为 `quality_checked`，不是 promotion evidence。
