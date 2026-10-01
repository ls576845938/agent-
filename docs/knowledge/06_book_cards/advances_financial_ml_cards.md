# Advances In Financial ML Rule Cards

> 状态：旧版主题摘要，不计入覆盖率。`RES-01` 标准章节卡已完成 `22/22` 章 `L2` 与原EPUB概念级 `L3`，共650项均为 `verified_concept_only`，以 `coverage_manifest.md` 为准。

## 用途

约束金融 ML、标签、交叉验证、回测过拟合控制。

## 转化规则

- 金融样本非 IID。
- 标签重叠时必须 purge 和 embargo。
- Triple barrier 要记录三类 barrier。
- Meta-labeling 不替代 primary signal 的经济逻辑。
- 每次参数搜索必须记录 trial count。
- 回测报告必须记录 false discovery 风险。

## 对应文件

- `02_research_backtest/financial_ml_validation_rules.md`
- `02_research_backtest/no_lookahead_rules.md`
- `02_research_backtest/walk_forward_validation.md`
