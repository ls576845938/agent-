# DDIA Rule Cards

> 状态：旧版主题摘要，不计入章节覆盖。标准章节卡见 `cards/ENG-03_designing_data_intensive_applications.md`。

## 用途

约束行情、因子、账本、报告、任务日志的数据系统设计。

## 转化规则

- 原始数据不可覆盖。
- 派生数据必须有 lineage。
- 批处理和流处理输出契约应一致。
- 写入必须幂等。
- schema 变化必须可迁移。
- 故障恢复必须依赖日志、快照和重放。

## 对应文件

- `01_data_layer/data_reliability_rules.md`
- `01_data_layer/database_schema_rules.md`
- `05_monitoring_replay/replay_engine.md`
