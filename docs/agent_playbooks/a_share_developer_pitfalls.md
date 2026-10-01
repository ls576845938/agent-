# A-Share Developer Pitfall Rules

适用代理：A 股程序员，canonical role 为 `a_share_developer`，scope/domain 为 `cn_equity`。

## 职责边界

- 按架构票据实现 A 股研究、回测、组合风控、执行模拟、监控和证据链。
- 新领域代码进入明确的 `cn_equity` 命名空间；不得把 A 股规则塞进 `quant_us` 或 BTC 专用模块。
- 数据师拥有数据源、raw/derived 版本、manifest、lineage、freshness 和质量结论；A 股程序员只消费已提交 handoff。
- 共享 schema、枚举、组合接口和执行合同必须走独立集成票据，不得单方面修改。

## 必读文件

- `AGENTS.md`
- `docs/knowledge/README.md`
- `docs/agent_playbooks/shared_pitfalls.md`
- 本文件
- 数据任务读取 `docs/knowledge/01_data_layer/`
- 回测任务读取 `docs/knowledge/02_research_backtest/`
- 组合风控任务读取 `docs/knowledge/03_portfolio_risk/`
- 执行模拟任务读取 `docs/knowledge/04_execution_oms/`
- 监控与回放任务读取 `docs/knowledge/05_monitoring_replay/`

## A 股数据与 PIT 硬线

- universe、指数成分、上市/退市、ST/风险警示、停复牌和公司行动必须带可见时间，不能使用未来状态回填历史。
- 交易日历、交易时段、板块和证券规则必须版本化，并记录来源与生效日期。
- 复权价格不能替代公司行动现金流与可用时间；原始价、复权因子和账本处理必须可追溯。
- 数据缺失、状态未知、规则来源未验证或 source splice 未证明等价时，只能 research-only / blocked。

## A 股回测与执行硬线

- 回测和执行模拟不得默认复用美股连续交易、卖出可用性、涨跌停、整手、费用或结算语义。
- 撮合必须显式处理交易时段、集合竞价、停牌、价格限制、可卖数量、最小交易单位和拒单原因。
- 成本模型必须使用按生效日期版本化的佣金、税费和其他交易成本；缺规则时 fail-closed。
- Strategy 只能输出 `Signal`、`Forecast`、`TargetPosition` 或 `OrderIntent`，风险与 OMS 必须位于下单之前。
- 未经独立 paper gate、人工审批和 broker 安全审查，不得接入真实下单。

## 多代理交接

- 启动时运行 `context_packet.py --role a_share_developer --scope cn_equity` 并读取 Team Context。
- 只通过 committed manifest、append-only handoff 和 shared-data resolver 消费数据师交付。
- 完成代码后先提交 deliverable，再发布单独的 handoff event；不得把 worktree 私有路径交给其他代理。
- 发现 schema、共享接口或其他领域文件冲突时停止修改，交给架构师创建 integration ticket。

## 交付要求

- 列出 base commit、touch set、初始 dirty paths、测试命令和产物路径。
- 说明使用的市场规则版本、数据版本、PIT 状态、成本模型和仍未验证项。
- 所有 promotion、paper、live、private、order 权限默认保持 false。
