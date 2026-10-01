# Test Policy

## 目标

测试优先覆盖会导致资金损失、错误晋级、未来函数、账本不一致的风险。

## 测试层级

1. Domain unit tests: 纯规则、无 I/O、无外部依赖。
2. Service tests: 使用 fake repository / fake unit of work 验证流程。
3. Contract tests: 验证 artifact schema、promotion gate、ledger 字段。
4. Integration tests: 验证真实 adapter、数据库、文件、外部 API 的边界。
5. Regression tests: 每个已修复 bug 必须保留复现用例。

## 必测场景

- No look-ahead。
- 数据缺失、重复、乱序。
- 成本、滑点、换手变化。
- ledger PnL 可复原。
- 风控拒绝。
- paper/live fail-closed。
- 重跑幂等。
- 部分成交、拒单、撤单、超时。

## 禁止模式

- 只测 happy path。
- 用真实当前日期导致测试每天变化。
- 用网络请求作为单元测试依赖。
- 修改核心逻辑但只更新快照。
- 因测试难写而把逻辑留在 CLI 或脚本中。

