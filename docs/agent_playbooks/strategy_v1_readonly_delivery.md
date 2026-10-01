# V1 Donchian 离线接线与只读发布合同

本合同只适用于票据 `STRATEGY-V1-DONCHIAN-OFFLINE`：在不改变原 Donchian 交易语义的前提下，验证“原信号与固定合约目标 → 现有 BTC 风控／OMS／保护 → 模拟成交 → 持久账本 → 精确决策证据”的离线纵向链，最终仅将密封的离线证据发布到现有研究只读页面。owner：quant_architect；复审：2026-10-30。

它不是新的 `change_risk`，也不改写旧类别。源码接线仍必须显式使用 `demo_execution_semantics`，保留原有高风险 conditional guardrails、独立 integrator 和后端重启要求；发布环境固定为 `research_readonly`。自由文本不会自动选择本合同。

## 两阶段验收

### 1. `source_review`

这一阶段审查已提交的高风险离线接线源码。通过只表示该源码有资格进入独立集成，不表示页面已发布，也不表示 Demo、paper 或 live 可用。本阶段不填写 `current_main_identity`、`canonical_browser_acceptance` 等发布事实。

必须证明：

- V0 冻结基线经独立核验，接线前后原 Donchian 信号、固定合约目标、反向先平仓、退出和冷却等经济语义一致。
- 复用现有 BTC Risk／OMS／protection／fill／ledger 权威链，不新建第二套 OMS 或账本。
- 运行 failure-first、恢复、重复事件、重复成交、账实回放一致和精确决策关联测试。
- 实际差异与独立审定的 touch set 完全相同；交付是已提交 commit 和经验证的 append-only handoff。
- 测试仅消费注入的历史／合成事实，网络被禁止，不读取 secret，不触达 private／order／live endpoint。

`demo_execution_semantics` 现有 requirements 必须以原名完整包含在 source checks 中，不得用语义相似的新名称替换掉。其中 `demo_safety_attestation` 在本票据中证明 Demo 仍为禁用，不是 Demo 启动授权。

source-review receipt 必须分别绑定 source commit、producer handoff commit／path／SHA-256、独立 review commit 与 review report path／SHA-256。独立 review commit 不能与 source commit 相同。它还必须引用由 architect 审定的 touch-set artifact commit／path／SHA-256；`approved_source_touch_set` 与实际差异列表必须一致，且路径仅能落在合同固定的 V1 源码／测试／证据边界。同一 receipt 里自报两个相同列表不构成授权；独立审查者必须从引用的提交态 artifact 和真实 Git diff 核对。

允许的源码能力只限于：Donchian 离线输入注入、确定性离线时钟注入、确定性决策证据关联、密封离线执行证据、离线运行状态投影、持久账本回放验证及其文档／测试。允许修改哪些执行文件，不由目录前缀自动授权，而是由后续 V1 票据的精确 touch set 和独立逐文件审查决定。共享层只额外允许精确文件 `quant_shared/strategy_runtime/decision_envelope.py`，用于版本化决策证据包；不放开 `quant_shared/strategy_runtime/` 或 `quant_shared/runtime/` 目录，相邻 models、permissions 与 runtime 路径继续拒绝。

本票据另外精确允许 `quant_crypto/portfolio/decision.py`，仅用于修复减仓请求的来源类型（`Signal` 或 `Forecast`）和来源 ID 绑定。窄能力名为 `reduce_only_signal_forecast_source_identity_binding`；它不允许改变风险判定、数量、目标仓位、退出、保护或任何权限语义。不放开 `quant_crypto/portfolio/` 目录；相邻 portfolio 文件、risk kernel 和 permissions 继续拒绝。

已准入的 `quant_crypto/runtime/control_plane.py` 只允许两项窄能力：`reduce_only_runtime_action_projection` 允许 dispatcher 将已获准的 `REDUCE_ONLY` 减仓意图投影为减仓运行动作，而不得误投影为 `CANCEL_ONLY`；`deterministic_offline_clock_injection` 只允许 dispatcher 通过构造依赖在显式离线回放中使用调用方注入的 UTC observation clock 计算快照 freshness，未注入时仍默认使用 `utc_now()`。时钟注入不得改变 30／120 秒新鲜度阈值，不得改变风险证据 authority 的签发、验签或有效期，不得形成 HTTP／热配置开关，也不得绕过或补造账户、风控、连接、private WS、Guardian、ledger 或其他权限事实。这两项能力都不改共享 `PermissionEvaluator`，不改真实 `CANCEL_ONLY` 的取消语义，不改变数量、目标仓位或退出语义，也不授权 Demo、paper、live 或真实订单。其他 runtime 权限语义仍不在准入范围内。

禁止：修改策略参数、信号／仓位／退出经济语义；弱化 Risk／OMS／protection／ledger；修改 broker transport、private WS、security 或交易权限；自动注册或启动运行 worker；开启 Demo、paper 或 live。启动器、Hook trust、agent 角色和权限文件属于源码保护路径。

### 2. `deployment_acceptance`

只能在治理合同经独立审查并集成后，由加载新规则的新上下文执行。旧任务不得声称规则热更新生效。

必须重新验证 source-review receipt，再核对 sealed `offline_execution` 证据的完整性、精确 source/data/code 版本与 stale 状态、只读发现、registered main 身份、canonical browser 实页面和精确回退点。deployment receipt 必须绑定已审 source commit、source review commit 和 touch-set artifact SHA-256，并附 deployment handoff commit／path／SHA-256 与独立 deployment review commit／report path／SHA-256。独立审查必须验证 deployment commit 包含已审 source commit，而且审后源文件未变。

`deployment_changed_paths` 专指“已审 source commit 到 deployment commit”之间新增的只读展示差异，不是从旧 main 开始的累计 diff。已经 source review 审过的 runtime 文件不在这个列表中重复判定为 protected，但也不得利用分阶段再次修改或漏审。最终只执行一次 `research_readonly` 发布：它同时包含已审且未改动的 source commit 和展示增量，不要求也不允许先以 Demo 部署源码。发布路径只能增加离线证据 read model 与研究前端关联；执行、共享 runtime／strategy runtime、治理、安全和启动路径都是发布阶段保护路径。

后端只能以现有 `research_readonly` profile 通过 canonical launcher 重启。`runtime_observed=false` 表示页面展示的是离线执行证据，不是实时账户、Demo 观测或真实成交。页面不得自动拼接“相似记录”，必须按精确 package/run/decision/evidence kind 关联；缺证或错版本应显示 blocked／unknown。

## 机器校验器

`delivery_policy.strategy_v1_readonly_delivery_blockers(receipt)` 是无副作用的验收记录校验器：它只读取已提交的静态策略配置，不读运行证据或 secret、不写文件、不开服务、不调 broker／exchange、不授权。receipt 中的 true 必须由独立报告的真实命令、Git hash、seal 和浏览器证据支撑，单纯填写 JSON 不是证明。

校验器会拒绝：缺失字段、未知票据／阶段／风险／profile，非规范路径，未经审定的 touch set，未知能力，以及任一安全旗标不是字面布尔 false 的 receipt。源码阶段通过不会产生页面已发布的结论。

## 保持关闭的权限与 gate

两个阶段都要求 `demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_worker_enabled`、`runtime_observed` 严格为 false。readiness 上限是 `quality_checked`，不是 `promotion_evidence_ready`。旧 BTC promotion/runtime artifact blocker 原样保留；本软件发布不重建 promotion artifact，不消费真实账户，不开启 Demo，不自动启动 V2 或 M3—M4。

## 有限回归

```powershell
py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/agent_governance/test_strategy_v1_readonly_delivery.py tests/agent_governance/test_research_release_policy.py tests/agent_governance/test_delivery_policy.py tests/agent_governance/test_context_packet.py tests/agent_governance/test_team_context.py tests/agent_governance/test_hooks.py tests/agent_governance/test_governance_contract.py
```

测试通过只能证明治理合同 fail-closed，不证明 V1 源码已实现、已集成、已发布或可交易。
