# Point-In-Time Data

## 核心原则

策略在任意 `decision_time` 只能看到当时已经可见的数据。

## 必需字段

- `event_time`: 市场事件发生时间。
- `available_time`: 数据对策略可见时间。
- `ingested_at`: 系统接收时间。
- `processed_at`: 派生数据生成时间。
- `source`: 数据来源。
- `data_version`: 数据版本。

## 规则

1. 回测过滤条件必须是 `available_time <= decision_time`。
2. 财报、宏观、链上、资金费率、成分股、复权因子都必须有可见时间。
3. 任何回填、修正、重新发布的数据必须保留旧版本。
4. 训练集统计量不能使用测试期数据。
5. 每个 backtest manifest 必须记录数据快照版本。

## 反例

错误：用今天下载的复权数据回测五年前的信号。

正确：用五年前可见的价格和复权规则生成当时可交易信号。

