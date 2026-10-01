# Data Quality Checks

## 运行顺序

数据质量检查必须先于研究、回测、paper 和 live。

## 检查项

- 缺失时间段。
- 重复 bar 或重复交易。
- 时间戳乱序。
- 价格为 0 或负数。
- OHLC 关系异常。
- 极端跳点。
- 成交量异常。
- 时区不一致。
- 数据源延迟。
- 最新日期不满足 freshness SLA。

## 输出要求

每次数据任务应输出：

- `status`
- `data_source`
- `data_version`
- `start_time`
- `end_time`
- `row_count`
- `missing_count`
- `duplicate_count`
- `stale_reason`
- `blocking_issues`

## Fail-Closed

以下情况不得继续进入交易路径：

- live 数据陈旧。
- 信号所需字段缺失。
- 时间戳无法解释。
- 数据质量报告不存在。
- 数据版本和策略 manifest 不匹配。

