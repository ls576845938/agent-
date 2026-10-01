# Data Reliability Rules

来源主线：DDIA。

## 适用范围

行情库、K 线库、因子库、财报库、宏观库、回测结果库、paper/live ledger、任务日志。

## 核心规则

1. 每条可交易数据必须区分 `event_time`、`available_time`、`ingested_at`、`processed_at`。
2. 策略只能使用 `available_time <= decision_time` 的数据。
3. 原始数据不可覆盖；修正、清洗、复权、聚合必须生成新版本。
4. 任何派生表都必须能追溯到原始数据、转换代码、参数和运行时间。
5. 写入 ledger 必须幂等；重复运行同一 `run_id` 不应制造重复成交或重复仓位。
6. 数据 schema 变化必须向后兼容，或者提供明确迁移脚本和版本边界。
7. 数据质量检查要先于策略运行；缺失、重复、乱序、异常跳点必须显式报告。
8. 批处理和实时/准实时处理要统一输出契约，不能让策略关心数据来自批任务还是流任务。
9. 任何缓存都必须记录生成条件；缓存不能隐藏数据版本变化。
10. 任何外部数据源异常都必须 fail-closed，而不是用陈旧数据静默运行。

## 数据表最低字段

行情或特征表至少需要：

- `symbol`
- `venue` 或 `source`
- `event_time`
- `available_time`
- `ingested_at`
- `data_version`
- `adjustment_policy`
- `quality_flags`

回测和研究结果至少需要：

- `run_id`
- `strategy_id`
- `data_version`
- `params_hash`
- `cost_model`
- `slippage_model`
- `created_at`
- `code_version`

## Codex 开发检查

修改数据模块时必须确认：

- 新增字段是否会破坏旧报告和旧测试。
- 是否保留原始数据而不是覆盖。
- 是否有唯一键或去重逻辑。
- 是否可以重跑同一天任务并得到同一结果。
- 是否把缺失和异常记录到质量报告。

## 反例

错误：用最新复权价格重算历史信号，但没有记录复权版本和可见时间。

正确：保存原始价格、复权因子版本、复权生成时间，并在回测中只使用当时可见版本。

