# ADR-002: 数据契约规范

**状态**: ACCEPTED
**日期**: 2026-05-03
**决策者**: 个人开发者

## 背景

系统中多个模块之间通过数据对象传递信息。如果各模块对字段的理解不一致，会导致静默 bug（特别是前视偏差和单位错误）。需要为所有跨模块边界的数据对象定义明确的字段契约。

## 决策

### Bar — 市场数据原子单元

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `timestamp_utc` | `datetime` | UTC, 不可为 None | Bar 的结束时间 |
| `symbol` | `str` | 自动大写 | 股票代码 |
| `open` | `float` | > 0 | 开盘价 |
| `high` | `float` | >= low | 最高价 |
| `low` | `float` | <= high, > 0 | 最低价 |
| `close` | `float` | > 0 | 收盘价 |
| `volume` | `float` | >= 0 | 成交量 |
| `vwap` | `float \| None` | >= 0 或 None | 成交量加权均价 |
| `source` | `str` | 非空 | 数据来源标识 |
| `session` | `str` | REGULAR/AFTER_HOURS 等 | 交易时段 |
| `adjusted` | `bool` | 默认 False | 是否已复权 |

**规则**: 策略做入场决策时必须用 `bar.close`。如果策略在 bar t 用 close 决策入场，实际执行必须在 bar t+1（参见 ADR-003 一 bar 延迟规则）。

### Signal — 策略输出

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `timestamp_utc` | `datetime` | UTC | 信号产生时间 |
| `strategy_id` | `str` | 非空 | 策略标识 |
| `symbol` | `str` | 自动大写 | |
| `direction` | `SignalDirection` | LONG/FLAT（V1 不做 SHORT） | 方向 |
| `strength` | `float` | [0.0, 1.0], 自动截断 | 信号强度 |
| `horizon` | `str` | 非空 | 持仓周期，如 "20d" |
| `reason` | `str` | | 信号原因，可审计 |
| `metadata` | `dict` | | 扩展字段，不参与决策 |

### TargetPosition — 组合管理器输出

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `timestamp_utc` | `datetime` | UTC | |
| `strategy_id` | `str` | | |
| `symbol` | `str` | 自动大写 | |
| `target_weight` | `float` | | 目标权重（占权益比） |
| `target_quantity` | `float \| None` | | 可选目标数量 |

### OrderIntent — 再平衡器输出

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `timestamp_utc` | `datetime` | UTC | |
| `strategy_id` | `str` | | |
| `symbol` | `str` | 自动大写 | |
| `side` | `OrderSide` | BUY 或 SELL | |
| `quantity` | `float` | > 0, 自动转 float | 订单数量 |
| `order_type` | `OrderType` | 默认 MARKET | |
| `limit_price` | `float \| None` | | 限价单价格 |
| `time_in_force` | `TimeInForce` | 默认 DAY | |
| `client_order_id` | `str` | 唯一, 自动生成 | 客户端幂等键 |

### Order — OMS 输出, Broker 输入

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `order_id` | `str` | 唯一, 自动生成 | 系统订单 ID |
| `client_order_id` | `str` | 来源 OrderIntent | 幂等键 |
| `broker_order_id` | `str` | 券商返回后填充 | |
| `status` | `OrderStatus` | 状态机参见 ADR-003 | |
| `quantity` | `float` | 可能被风控调整 | |
| 其他字段 | | 继承自 OrderIntent | |

### Fill — Broker 输出, Ledger 输入

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `fill_id` | `str` | 唯一, 自动生成 | |
| `order_id` | `str` | 关联 Order | |
| `symbol` | `str` | 自动大写 | |
| `side` | `OrderSide` | BUY 或 SELL | |
| `quantity` | `float` | > 0 | 成交数量 |
| `price` | `float` | > 0 | 成交价格 |
| `commission` | `float` | >= 0 | 佣金 |
| `filled_at` | `datetime` | UTC | 成交时间 |
| `broker` | `str` | | 券商标识 |

### DataManifest — 数据版本契约

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `data_version` | `str` | 非空, 哈希前缀 | 数据版本 ID |
| `source` | `str` | | yfinance 等 |
| `symbol` | `str` | 自动大写 | |
| `interval` | `str` | 1d | bar 周期 |
| `coverage_pct` | `float` | >= 90.0 为可用 | 数据覆盖率 |
| `quality_score` | `float` | >= 80.0 为可用 | 数据质量分 |
| `fingerprint` | `str` | SHA256 | 内容指纹 |
| `row_count` | `int` | | 实际行数 |
| `start` / `end` | `str` | ISO 日期 | 数据时间范围 |
| `cleaning` | `dict` | | 清洗统计（去重、无效 OHLC 等） |
| `git_commit` | `str` | | 生成时的 commit hash |

## 通用规则

1. **所有时间戳均为 UTC。** `datetime` 构造时自动调用 `ensure_utc()`。
2. **所有 symbol 均为大写。** 构造时自动 `.upper()`。
3. **Signal/Bar/TargetPosition/OrderIntent/Fill 均为 frozen dataclass。** 不可变，保证线程安全。
4. **Order 为 mutable。** 状态字段随生命周期更新。
5. **metadata 字段不参与交易决策。** 仅用于审计和调试。
6. **strength 自动截断到 [0.0, 1.0]。** 策略不需要自己做归一化。
7. **quantity 在 OrderIntent 构造时自动转 float。**

## 因子数据（Feature）

因子存储在 `ParquetFeatureStore` 中，以 `(date, symbol, factor_name, factor_value, universe, version)` 结构存储：

| 因子名 | 类型 | 范围 |
|--------|------|------|
| `momentum_score` | float | [-1, 1] |
| `realized_vol_20` | float | > 0 |
| `average_dollar_volume_20` | float | > 0 |

## 后果

- 所有跨模块接口有明确的类型契约
- 构造函数自动标准化减少静默 bug
- metadata 扩展不破坏核心决策逻辑
