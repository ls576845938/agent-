# 研究只读发布合同

`change_risk=research_readonly_release` 仅是软件发布类别，不是策略晋级或交易授权。默认 `unclassified` 和所有既有类别保持不变。owner：quant_architect；复审：2026-10-30。

## 何时可以选择

用户明确授权发布研究功能/证据/只读页面，且独立审查确认变更不会影响交易执行语义时，票据才可以显式选择本类别。自由文本中的“研究”“只读”“M1”不自动改变分类；预检必须显式传 `--change-risk research_readonly_release --scope shared --scope research --scope gate`。混合交易/治理变更应拆分，不能套本类别。

允许：共享研究生产者的独立观察旁路、研究结果读取、已有研究页面展示、研究证据发现、对应文档/测试。不允许改变任何默认交易信号、仓位、退出、风险、OMS、保护、账本、broker/private transport、权限、运行产物存储/发布、晋级判定或治理规则。历史研究证据可以展示，但必须保留真实计算 commit、数据版本、as-of 和 stale，不得改写为当前运行证据。

## 发布必须满足

1. 专属 sparse 工作树、限定且清洁的 touch set、失败优先/兼容回归、提交态 deliverable 与经验证的 append-only handoff。
2. 独立 integrator 在独立分支验证 Git ancestry、逐文件 hash、完整 diff、执行不变边界与研究结果读取；生产者不能自批。不得走 Demo `integrated_fastpath` 或主代理直接 fast-forward main。
3. 治理规则先经独立审查生效；随后由加载新规则的新执行上下文执行研究发布，旧角色/上下文不得宣称热更新生效。治理票据不混入业务代码或服务操作。
4. 提交到 registered main 后，只通过现有 canonical launchers 启动 8765/3000。发布模式固定 `research_readonly`，`QS_BTC_DEMO_CONTROL_ENABLED=false`，`QS_ALLOW_FIXTURE_FALLBACK=false`；核验真实 listener、source/main HEAD、`canonical=true`、`runtime_stale=false`、read_only/controls_disabled=true。
5. 只读研究数据通过提交态 manifest 与 immutable resolver 发现；全量 hash、seal、run/data/code/context 绑定通过。错版本、缺失、损坏必须显式 blocked/unknown；禁止复制到工作树来伪装成正常发现，禁止读取时补算、补建或改写来源。
6. 当前主页面真实打开对应 run，完成浏览器展示/缺失陈旧安全态/切换交互验收。TestClient 注入路径、SSR、构建成功都不能单独替代正式页面验收。
7. 记录精确回退 commit、实际发布 commit、启动模式与证据引用。回退经专属变更与集成流程，不 reset、不覆盖其他任务，不自动恢复任何交易权限。

本类别只免除与纯研究发布无关的 BTC promotion/runtime artifact 重建依赖。BTC root 缺失、503、晋级 gate 失败仍原样暴露；不得创建假 root、伪造 marker、重写 blocked 为 ready，不能因为免除重建就认为 BTC 已能运行。只读发布不等于允许训练任务：服务端已有只读写入保护继续生效。

## 机器校验与证据

`delivery_policy.research_release_blockers(receipt)` 为无副作用的**验收记录校验器**，不读取 secret、不开服务、不调用 broker、不授予任何权限。receipt 的 `checks` 必须由独立报告中的真实命令、Git/manifest hash、当前主版本身份和浏览器证据支撑；`changed_paths` 来自实际 Git diff；`changed_capabilities` 由独立代码审查判定。填 true 的 JSON 不是证明，路径黑名单也不是完整静态安全分析。

所有 `required_checks` 必须严格为布尔 true；`required_false_flags`（含 Demo 控制、promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed）严格为布尔 false。缺字段、未知能力、保护路径、非规范路径、错误模式或任一未完成检查都会阻断最终发布验收。这个类别的 readiness 上限为 `quality_checked`，不用于声明 `promotion_evidence_ready`。

Team Context 继续如实显示领域运行证据缺口，不隐藏 BTC 不健康状态。那些领域 gate blocker 不再自动驱动本类别的工程扩展；研究发布验收按本合同独立记录。M1 完成不自动授权 M2—M4。

## 回归

`py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/agent_governance/test_research_release_policy.py tests/agent_governance/test_delivery_policy.py tests/agent_governance/test_context_packet.py tests/agent_governance/test_team_context.py tests/agent_governance/test_hooks.py tests/agent_governance/test_governance_contract.py`

旧类别完整性、默认保守分类、拒绝混合/未知能力、交易标记、CLI 枚举与截断上下文、全局/适用数据规则均需回归。不得为本类别修改交易安全测试预期或 hook trust。
