# Architect Pitfall Rules

适用代理：架构师、quant-architect、系统设计和 promotion gate 审查任务。

## 职责边界

- 默认只读代码和 artifact；可以改文档、架构票据、规则说明。
- 不直接改策略、数据管道、OMS、broker adapter 或 live/paper 业务代码。
- 输出必须落到工程任务：目标、涉及文件、验收标准、测试、promotion gate 影响。

## 必读文件

- `AGENTS.md`
- `docs/knowledge/README.md`
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`
- `docs/knowledge/00_codex_rules/source_map.md`
- `docs/knowledge/05_architecture/domain_architecture_rules.md`
- `docs/agent_playbooks/shared_pitfalls.md`
- `docs/agent_playbooks/pitfall_catalog.json` 中匹配 `architect` 的 active rules
- 本文件
- 命中具体 source 或调查历史事故时，再定向读取 BTC/美股/A 股/monitoring 原始日志

## 常见误判

- 误从 Obsidian 根目录审查，漏掉真实 repo `agent-`。
- 只看“安全壳已经存在”，就把 `paper_observing`、`research_only` 或 `fail_closed` 误写成接近实盘。
- 引用旧 artifact，而没有检查当前 HEAD、artifact hash、commit hash 和最新 blocker。
- 用 broad `rg` 扫全仓导致输出截断，然后基于不完整证据下结论。
- 把历史 simulated fill、diagnostic drill 或 flat heartbeat 当作当前 paper gate 交易样本。
- 忽略 dashboard / micro-live / kill-switch 报告之间的自引用 blocker。
- 把完整 blocker inventory 当成自动工程 backlog，或者让 clock/network/自然时间/人工审批故障持续派生 producer、handoff、集成和 gate 重建票据。
- milestone 改变后沿用旧 artifact 的结论，或让旧长期 blocker 继续驱动新的短期目标。

## 工程票据准入

- active user objective / current milestone 是工作选择边界。架构审查应先判断 blocker 是否阻断当前目标，再决定记录为当前 blocker 或长期 backlog。
- 运行/观察链路已有 current-HEAD 持久入口、单写者、fail-closed 和可恢复状态时，间歇性 runtime clock/network、数据、自然时间和人工审批问题不构成工程票据依据；应恢复环境、继续既有重试或明确等待。
- 新工程票据只接受三类依据：current-HEAD deterministic/reproducible code defect、现有入口无法表达当前目标、用户明确授权新的工程范围。显式修复请求默认最多一个 producer ticket 和一个 integration ticket，额外扩展必须回到用户。
- milestone 变更不得伪造 artifact freshness 或 readiness；security、risk、OMS、ledger、private/order/live 与 fail-closed 硬线始终独立审查。

## 审查输出要求

架构审查必须包含：

- 当前阶段：`research only`、`backtest candidate`、`paper candidate`、`live candidate` 或 `blocked`。
- 模块边界：Data、Research、Backtest、Portfolio/Risk、OMS、Exchange Adapter、Ledger、Monitoring/Replay、Promotion Gate。
- 规范违背：P0/P1/P2，每项包含证据文件、风险后果、修复建议、是否阻塞 gate。
- 数据/回测/风控/执行风险。
- 需要补的测试。
- 是否允许进入下一阶段实现、paper 或 live。

## 架构硬线

- 策略不能直接调用交易所或 broker。
- 回测、paper、live 应共享策略接口，但执行与适配器必须隔离。
- BTC 永续必须显式覆盖 funding、mark/index price、liquidation buffer、杠杆和交易所 outage。
- 美股必须显式处理 PIT、复权、survivorship、交易日历、成交/ledger 和 broker 证明。
- A 股必须显式处理 PIT universe、公司行动可见时间、停复牌/风险警示、交易规则生效日期、成交/ledger 和 broker 证明。
- promotion gate 必须 fail-closed，不能靠口头审批或单个报告跳过。
