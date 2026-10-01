# Quant System Agent Contract

本仓库同时服务 BTC/加密资产、美股与 A 股量化研究、回测、paper 和受控实盘准备。默认使用中文沟通。

规则版本：`agent-governance-v2`

## 授权边界

- 回答、解释、审查、诊断、规划类请求：读取本地证据并报告，不修改业务代码。
- 修改、实现、修复类请求：仅修改明确范围内的本地文件，并运行非破坏性验证。
- 外部写入、真实 broker/exchange 调用、private/order/live endpoint、破坏性文件或 Git 操作必须取得明确授权。
- 架构师和研究员 profile 默认只读；不得借子代理绕过其 sandbox。

## 写代理执行授权

- 对程序员、数据师和集成代理，当前用户提示或 active Goal objective 即为已批准任务；在已声明 touch set 和专属 worktree 内，无需为读取、编辑、格式化、测试、重建本任务自有 artifact 或按交付合同提交本分支逐步重复请示。
- 写代理应在授权范围内自主推进到任务完成或出现真实阻塞；缺少上游数据或 handoff 时，发布明确 blocker，并继续完成不依赖该 blocker 的工作，不得用“是否继续”代替执行。
- 仅在扩大 touch set、修改当前任务未授权的共享 schema/枚举/执行合同、覆盖其他代理 dirty 文件、外部 push/merge/写入、破坏性文件或 Git 操作、读取 secret，或触及 private/order/live endpoint 时再次请求明确授权。
- Full Access 或 Goal mode 只消除工作区内的机械确认，不改变量化 promotion gate；paper/live、真实下单、密钥和 fail-closed 安全边界始终独立生效。

## 目标边界与工程循环熔断

- 当前用户目标和 active milestone 是工作选择边界；完整 blocker inventory 只用于暴露风险，不会自动转成 backlog、工程票据、测试、handoff、集成或 gate 重建授权。
- 运行/观察任务已有 current-HEAD 持久入口、单写者、fail-closed 和可恢复状态后，间歇性 clock、network、TLS、DNS、latency、观察覆盖不足、自然时间、数据或人工审批 blocker 只能驱动既有运行、重试或环境阻塞报告，代码范围保持冻结。
- 只有 current-HEAD 可确定复现的代码缺陷、现有入口无法表达当前用户目标，或用户明确授权新的工程范围时，才创建最小工程票据。每个显式修复请求默认最多一个 producer ticket 和一个 integration ticket；需要额外扩展时回到用户重新授权。
- active milestone 变更只改变当前验收窗口；旧 artifact 不得被描述为满足新目标，旧长期 blocker 转入 backlog 且不再驱动当前任务。任何快路径都不得放宽 security、risk、OMS、ledger、private/order/live 授权或 fail-closed 旗标。

## 变更风险与交付路径

- 每个任务必须显式声明 `change_risk`，以 `docs/agent_playbooks/delivery_risk_policy.json` 为机器可读合同；无法可靠分类时使用 `unclassified` 并保留旧的最严格交付路径。
- `demo_transport_hotfix` 仅适用于 Demo parser、transport、candle 或公共 REST tail merge 等不改变执行语义的小修复。它要求专属 sparse producer、限定 dirty、失败优先回归、Demo safety attestation、提交态 deliverable；跨代理消费时必须有 append-only handoff。主代理校验 commit、touch set、测试和 handoff 后可 fast-forward main，无需独立 integrator，也不要求 promotion artifact/read-model 重建，但必须重启 backend。
- `demo_transport_hotfix` 严禁改变 strategy、risk、order construction、private-WS reconciliation、ledger、security 或 live 权限。`demo_execution_semantics` 及以上继续由独立 integrator 集成；`promotion_evidence` 与 `live_execution` 必须使用 current-HEAD artifact/read model，live 还必须有人工作业授权。
- `severity` 只表示规则命中后的后果。catalog 中 `global_invariant` 在其角色/领域适用范围内始终生效；`conditional_guardrail` 必须由 `applicability.change_risks` 命中，并记录 owner、复审日期和 sunset criteria；历史事故不得仅因 P0 就永久注入所有任务。

## 量化硬规则

- Strategy 不得直接调用 broker/exchange，只能输出 `Signal`、`Forecast`、`TargetPosition` 或 `OrderIntent`。
- 所有订单路径必须依次经过 Portfolio/Risk、OMS/Execution、Fill/Ledger 和审计链。
- PnL 必须由 fills、positions、cash ledger 推导。
- Backtest、paper、live 必须共享核心策略接口，但执行适配器和权限必须隔离。
- 实验必须记录 data、strategy、params、cost/slippage、run 和 code version。
- 禁止未来函数、全样本归一化、未来成分股、未来复权因子和回填财报。
- Promotion gate 必须基于当前 HEAD 的证据包；`research_only`、`blocked`、`fail_closed` 不得被描述为 ready。
- 任何数据、风控、账本、连接、对账或凭证异常默认 fail-closed。
- 不读取、打印、提交或传播 API key、secret、passphrase、token；默认禁止 withdraw 权限。

## 启动前置

1. 确认 CWD 是本仓库根目录，而不是外层 Obsidian 目录。
2. 前端唯一启动入口是仓库根目录 `start-frontend.cmd`（或其调用的 `scripts/start_frontend_current_main.ps1`）。所有 Vite serve/preview 与 Playwright web server 都必须绑定 `refs/heads/main` 对应的注册主工作树、当前 main HEAD、提交态前端对象指纹和端口 `3000`；代理、历史或 detached worktree 在任何端口启动页面都必须 fail-closed，不再提供 worktree 前端预览入口。
3. 若项目 hooks 显示未信任，先审查 `.codex/hooks.json` 与 `.codex/hooks/`，再通过客户端 `/hooks` 信任当前 hash；禁止绕过 hook trust。
4. 读取 `docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`。
5. 读取 `docs/agent_playbooks/shared_pitfalls.md` 和当前角色 playbook。
6. 运行 `py -3 tools/agent_governance/context_packet.py --role <role> --scope <scope>`，读取命中的 active pitfall IDs。
7. 仅当命中具体 ID、调查历史事故或 catalog 缺项时，读取原始 BTC/美股/A 股踩坑日志的对应条目；默认不全文加载原始日志。
8. 先声明本次 touch set，再用 `py -3 tools/agent_governance/safe_status.py --path <repo-relative-path>` 检查相关源码路径；禁止在非 sparse 工作树执行无 pathspec 的全仓 `git status` 或 `git diff`。`data/`、`artifacts/`、`mlruns/` 通过 manifest、hash 和任务自有路径核验，不进入 dirty 扫描；发现他人修改时先读限定路径 diff，禁止覆盖或回滚。

## 角色任务与工作树拓扑

- 常驻角色任务必须从本仓库项目以 Local 环境启动，CWD 指向注册主工作树；不得把外层 Obsidian 目录或 `$CODEX_HOME/worktrees` 下的 Codex-managed worktree 作为角色常驻任务。
- Local 常驻任务只承担调度、审查和票据入口。架构师与研究员保持只读；程序员、数据师和集成代理不得直接修改或提交注册主工作树。
- 收到具体写票据后，写代理必须从票据指定的 base commit 运行 `tools/agent_governance/worktree_plan.py`，在注册主工作树同级的 `worktrees/` 下创建独立 sparse worktree，并只在该票据工作树内写入。
- 票据 worktree 的真实路径以 planner 输出为准；禁止硬编码或消费其他代理的 Codex-managed worktree、私有 worktree 路径或未提交文件。
- 项目级 `approval_policy = "never"` 与 `sandbox_mode = "danger-full-access"` 只消除授权范围内的机械审批；角色 TOML、touch set、单写者、secret/private/order/live 禁令和 promotion gate 继续独立生效。
- 任务保存创建时的 workspace、sandbox 和角色指令，不会热更新；治理配置变更后必须结束旧任务并从本仓库项目重建常驻角色任务。

## 规则路由

- 数据、schema、PIT、lineage、freshness：`docs/knowledge/01_data_layer/`
- 研究、标签、回测、walk-forward、promotion evidence：`docs/knowledge/02_research_backtest/`
- Forecast、仓位、组合和风险预算：`docs/knowledge/03_portfolio_risk/`
- OMS、成交、滑点、paper/live：`docs/knowledge/04_execution_oms/`
- 架构边界：`docs/knowledge/05_architecture/domain_architecture_rules.md`
- 监控、审计、回放、incident：`docs/knowledge/05_monitoring_replay/`
- BTC 市场结构、交易所 SRE、安全和趋势门槛：`docs/knowledge/07_crypto_market_structure/` 至 `10_btc_trend_strategy_playbook/`

## 多代理协作

- 一个文件、SQLite 数据库或 `artifacts/**/latest` 路径同一时间只能有一个写入者。
- 数据师、BTC 程序员、美股/通用程序员、A 股程序员应为每个写票据使用 planner 创建的独立 Git worktree；架构师和研究员保持只读。
- 写代理不得再启动并行写子代理。子代理默认只做代码探索、测试读取、日志分析或独立审查。
- Hooks 仅提供上下文和机械 guardrail，不是完整安全边界；sandbox、worktree、合同测试和 promotion gate 仍必须独立生效。
- 每个任务记录 base commit、touch set、已有 dirty paths、测试命令、产物路径和 gate 影响。
- gate_impact=none 的 Demo transport handoff 在 deliverable commit 已是 main 祖先时，可由 Team Context 派生 `integrated_fastpath`；不得改写历史 handoff，也不得据此解锁 promotion、paper、private、order 或 live。
- 共享 schema、枚举或执行语义必须由独立集成票据协调，不得由单一领域代理顺手修改。
- 未提交文件只属于当前 worktree；跨代理交付必须使用 `.agent/handoffs/` 中的 append-only 事件引用已提交 deliverable commit。
- 大型数据必须由数据师发布到 worktree 之外的不可变 shared data version；消费者只能通过 Git-tracked manifest 和 resolver 只读访问。
- BTC runtime artifact 必须分为 source integration、显式 external-root bootstrap、独立 artifact publication 三阶段；`QS_BTC_RUNTIME_ARTIFACT_ROOT` 必须是 worktree 外绝对路径并带精确 repository-owner marker。仅一个 writer 可持锁写入，latest pointer 最后原子替换；backend、Team Context 和其他 reader 禁止 mkdir、复制 repo-local artifact、回退到 worktree `artifacts/` 或泄漏 physical root。
- `quality_checked`、`research_ready`、`backtest_ready` 和 `promotion_evidence_ready` 必须明确区分；handoff 或 manifest 本身不得解锁 promotion、paper 或 live。
- 每次启动或接收新任务时读取 Hook 注入的 Team Context；若其不可用，依赖其他代理交付的任务必须 fail-closed。
- 架构师只审批边界和交接；已批准的集成由短生命周期、干净的 `agent/integrator/<ticket>` worktree 顺序执行。

## 用户主会话与可选 Agent 协作

- 在 `agent-` 项目的用户主会话中，主会话可在当前用户授权、角色边界和已声明 touch set 内直接进行诊断、实现、测试、提交与验收；不再以先调用某个命名 Agent 作为具体执行的前置条件。
- 是否调用 Agent 由任务的独立性、可并行性、角色专业性和验收隔离需求决定，属于可选协作手段；不绑定 `agent1`–`agent9`、固定模型或成本档位，也不得为简单回答或可直接完成的局部修复机械派发。
- 当交付政策明确要求独立 integrator、独立审查或单写者隔离时，仍必须按该政策使用职责匹配且相互独立的短生命周期任务；这是验收与权限边界，不是主会话日常执行的强制路由。
- 主会话或任何 Agent 都不得绕过角色边界、专属 sparse worktree、touch set、dirty 保护、提交态 deliverable、append-only validated handoff、security/private/order/live/promotion gate 或 fail-closed 规则。
- 治理任务必须声明 touch set，并运行 failure-first 或仓库已有的最小静态治理回归；跨代理交付必须提交 deliverable 和经验证的 append-only handoff。路由与治理票据不得修改业务代码或服务，不得访问交易端点、密钥或真实订单。

## 角色入口

- 架构师：`.codex/agents/quant-architect.toml`，读取 `architect_pitfalls.md`。
- 数据师：`.codex/agents/data-steward.toml`，读取 `data_steward_pitfalls.md`。
- 超级程序员：`.codex/agents/super-developer.toml`，读取 `super_developer_pitfalls.md`。
- BTC 程序员：`.codex/agents/btc-developer.toml`，读取 `btc_developer_pitfalls.md`。
- A 股程序员：`.codex/agents/a-share-developer.toml`，读取 `a_share_developer_pitfalls.md`。
- 研究员：`.codex/agents/researcher.toml`，读取 `researcher_pitfalls.md`。
- 集成任务：`.codex/agents/integrator.toml`，仅在架构师已批准的 handoff 上短期启用。

## 交付合同

最终交付必须包含：

- 修改文件与职责边界。
- 测试命令、结果和未运行项。
- 读取的 playbook、命中的 pitfall IDs、catalog hash。
- 初始 dirty paths、冲突处理和仍未合并的其他代理改动。
- artifact/manifest/ledger 路径及其 current-HEAD freshness。
- 仍然 blocked/fail-closed 的 gate 和所有保持为 false 的安全旗标。

缺少上述证据的交付不得作为 promotion evidence。
