# Quant System Knowledge Rules

本目录不是普通读书笔记，而是从五个核心来源建立硬规则，并持续吸收本地 Obsidian 量化书库的系统开发规范库。

来源：
- Designing Data-Intensive Applications - 数据可靠性、可恢复性、可演化性。
- Architecture Patterns with Python / Cosmic Python - 分层架构、领域模型、Repository、Unit of Work、事件驱动。
- Active Portfolio Management - 信号、预测、风险预算、组合构建。
- Advances in Financial Machine Learning - 金融 ML 数据结构、标签、样本权重、purged CV、回测过拟合控制。
- Trading and Exchanges - 市场微观结构、订单、流动性、滑点、成交机制。
- Modern BTC / crypto sources - 永续合约、资金费率、交易所 API、WebSocket、清算、API key 安全、交易所 outage。
- Local quant book corpus - 28 本已转换 Markdown 的策略、统计、组合、执行和工程书籍；仅作为规则与假设来源，不作为 promotion evidence。

## 使用方式

开发前按任务读取对应文件：

- 数据、行情、特征、结果库：`01_data_layer/data_reliability_rules.md`
- Point-in-time、复权、幸存者偏差、schema、数据质量：`01_data_layer/`
- 策略研究、特征、标签、回测验证：`02_research_backtest/financial_ml_validation_rules.md`
- 回测报告和 promotion gate：`02_research_backtest/backtest_evidence_contract.md`
- No-lookahead、事件驱动回测、成本滑点、walk-forward、策略接口：`02_research_backtest/`
- 组合、风险预算、仓位：`03_portfolio_risk/forecast_to_portfolio_rules.md`
- 仓位、风险预算、回撤、暴露约束：`03_portfolio_risk/`
- OMS、成交、滑点、执行模拟：`04_execution_oms/market_microstructure_execution_rules.md`
- 订单生命周期、执行算法、拒单重试撤单、broker adapter：`04_execution_oms/`
- 模块边界、测试、服务层、事件：`05_architecture/domain_architecture_rules.md`
- 监控、审计、回放、事故复盘：`05_monitoring_replay/`
- 全局不可违反规则：`00_codex_rules/quant_system_non_negotiables.md`
- 书籍到规则的映射卡片：`06_book_cards/`
- 本地 28 本书籍清单与 Agent 阅读路由：`06_book_cards/README.md`
- 跨书籍 Agent 行动手册：`06_book_cards/agent_book_knowledge_playbook.md`
- 加密市场结构、BTC 永续、参考价格：`07_crypto_market_structure/`
- 交易所 API、WebSocket、断线补数、outage：`08_live_trading_sre/`
- API key 权限、安全、轮换、泄露响应：`09_exchange_api_security/`
- BTC 趋势研究门槛、永续成本/资金费率/清算、实盘晋级：`10_btc_trend_strategy_playbook/`

## 规范原则

1. 研究、回测、纸盘、实盘必须共享同一套策略接口。
2. 策略只能产生信号、目标仓位或订单意图，不能直接调用券商或交易所。
3. 所有收益必须可由成交、仓位账本和资金流水回放得到。
4. 所有数据必须有可追溯的数据版本、时间戳、时区、可见时间和处理链路。
5. 每个回测都必须记录成本、滑点、换手、容量、敞口、回撤和样本外验证。
6. 任何 promotion gate 只能基于证据包，不允许基于单一 Sharpe 或最终收益。
7. 回测通过不等于纸盘通过，纸盘通过不等于实盘通过。
8. Signal 必须先转成 forecast / alpha，再经组合层生成目标仓位。
9. 目标仓位必须经过交易成本和执行可行性检查后才可进入 OMS。
10. 任何执行结果必须通过订单、成交、仓位、现金四类账本对账。
11. BTC 永续必须显式建模 funding、mark/index price、liquidation buffer 和 exchange outage。
12. 交易所 API key 默认不能有 withdraw 权限，live/paper/data key 必须分离。

## 推荐任务入口

- 架构师 Agent：先读 `00_codex_rules/`、`05_architecture/`，再按任务读对应模块。
- 数据 Agent：读 `01_data_layer/` 和 `05_monitoring_replay/audit_trail.md`。
- 回测 Agent：读 `02_research_backtest/`、`03_portfolio_risk/risk_budget.md`、`04_execution_oms/market_microstructure_execution_rules.md`。
- 风控 Agent：读 `03_portfolio_risk/`、`02_research_backtest/backtest_evidence_contract.md`。
- 执行 Agent：读 `04_execution_oms/` 和 `05_monitoring_replay/`。
- BTC/Crypto Agent：读 `07_crypto_market_structure/`、`08_live_trading_sre/`、`09_exchange_api_security/`、`10_btc_trend_strategy_playbook/`。

## 本地书库使用边界

外层 Obsidian 书籍是只读知识源，当前路径为 `D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD`。Agent 默认先读本目录的项目规则和书籍提炼卡；只有需要核对概念、公式或来源时才打开原文。

书中策略、历史结果、参数和案例只能进入 `concept_only` 或 `research_only` 流程。任何当前状态、回测通过、paper readiness 或 live promotion 结论必须来自当前 HEAD 的数据、测试、artifact、ledger 和 gate。
