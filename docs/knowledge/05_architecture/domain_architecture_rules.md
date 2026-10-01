# Domain Architecture Rules

来源主线：Architecture Patterns with Python / Cosmic Python。

## 适用范围

Python 模块边界、策略接口、数据访问、回测服务、paper/live 编排、测试。

## 分层规则

推荐依赖方向：

1. Domain: 纯业务对象和规则。
2. Service Layer: 编排用例。
3. Repository / Unit of Work: 数据访问和事务边界。
4. Adapters: DB、文件、API、交易所、消息队列。
5. Entrypoints: CLI、任务调度、HTTP、notebook。

依赖只能向内。Domain 不应依赖数据库、HTTP、交易所 SDK、pandas 文件路径或环境变量。

## 量化系统对象边界

Domain 层适合放：

- `Signal`
- `Forecast`
- `TargetPosition`
- `OrderIntent`
- `RiskDecision`
- `Fill`
- `Position`
- `LedgerEntry`
- `PromotionDecision`

Service Layer 适合放：

- 运行一次回测。
- 生成一次 paper roll。
- 执行一次 promotion gate。
- 从 signal 编排到 target position。
- 从 order intent 编排到 OMS。

Repository 适合隔离：

- 行情读取。
- 特征读取。
- 实验结果写入。
- ledger 读写。
- 报告 artifact 写入。

## Unit of Work 规则

以下操作必须在明确事务边界内：

- 写入订单和成交。
- 写入仓位和现金变动。
- 写入 paper/live 状态。
- promotion gate 状态变更。
- 数据版本切换。

失败时必须 rollback 或写入明确失败状态，不能半写入。

## 测试规则

1. Domain 层优先单元测试。
2. Service Layer 用 fake repository / fake unit of work 测试。
3. Adapter 用集成测试。
4. End-to-end 测试只覆盖关键路径，不替代单元测试。
5. 每个 bug 修复要有一个失败优先的回归测试。

## Codex 开发检查

修改架构时必须确认：

- 是否把业务规则塞进了 CLI、API、notebook 或脚本。
- 是否让策略直接读写数据库。
- 是否把外部 SDK 泄漏进 domain 层。
- 是否能用 fake repository 测试核心逻辑。
- 是否把副作用集中在 service/adapters，而不是散落在模型函数里。

