# Database Schema Rules

## 核心原则

数据库 schema 要服务于可追溯、可恢复、可迁移，而不是只满足当前查询方便。

## 规则

1. 原始表、清洗表、特征表、结果表分层。
2. 所有派生表必须能追到原始 source 和 transform version。
3. 核心表必须有唯一键，防止重复写入。
4. schema 变化必须有版本和迁移说明。
5. 数值单位必须写入字段名或 metadata。
6. 时间字段必须有时区约定。
7. 账本表只能追加或用显式 reversal 纠错，不能静默覆盖历史。
8. 回测结果表不能只存 summary，必须能追到 ledger 和 manifest。

## 最低表族

- `raw_market_data`
- `clean_market_data`
- `features`
- `signals`
- `target_positions`
- `orders`
- `fills`
- `position_ledger`
- `cash_ledger`
- `artifacts`
- `run_manifest`

