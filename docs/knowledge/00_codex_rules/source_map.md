# Source Map

## DDIA

用于约束数据层：
- 可恢复写入、日志、重放、快照。
- 数据模型演化、schema 兼容、读写路径分离。
- 批处理和流处理的边界。
- 数据质量、复制、一致性和故障恢复。

## Cosmic Python

用于约束架构层：
- 领域模型承载业务规则。
- Repository 隔离存储细节。
- Unit of Work 管理事务边界。
- Service Layer 编排用例。
- Message Bus / Events 解耦副作用。

## Active Portfolio Management

用于约束组合层：
- 信号必须变成预测，预测再进入组合。
- 组合评价重点是风险调整后的主动收益。
- 风险预算、约束、相关性和容量必须显式。
- 单策略收益不等于组合贡献。
- IR、IC、breadth、active risk、residual risk 是组合层核心语言。
- 交易成本和换手会侵蚀 value added，组合构建必须和交易执行分离。

## Advances in Financial Machine Learning

用于约束研究和回测：
- 金融数据非 IID、标签重叠、样本泄漏。
- Purged CV、embargo、walk-forward、CPCV。
- triple barrier、meta-labeling、sample weights。
- PBO、deflated Sharpe、试验次数记录。

## Trading and Exchanges

用于约束执行层：
- 市价单、限价单、价差、冲击成本、成交延迟。
- 订单簿、流动性、部分成交、撤单、拒单。
- 回测成交假设必须和交易市场结构一致。
- liquidity 至少区分 tightness、depth、resiliency。
- 执行绩效应使用 implementation shortfall、effective spread、fill rate 等指标。
- Broker / exchange adapter 是代理层，必须记录路由、确认、清算和对账。

## Modern BTC / Crypto Market Sources

用于约束 BTC 和加密交易扩展层：
- 永续合约不是现货加杠杆，必须显式处理 funding、basis、mark/index price、liquidation。
- 加密交易所 API 是实盘风险源，必须处理限频、精度、过滤器、WebSocket 断连、REST/WS 乱序。
- BTC 参考价格不能默认使用单一交易所 last trade，必须定义 reference price、stale/outlier/gap policy。
- 交易所 outage、cancel-only、data stale、private stream down 都必须进入交易状态机。
- API key 必须最小权限；live/paper/data key 分离；bot key 禁止 withdraw 权限。
- 预印本和交易所报告只能作为候选规则来源，进入规范前必须交叉验证。

主要映射文件：
- `07_crypto_market_structure/crypto_market_structure_source_map.md`
- `07_crypto_market_structure/btc_perp_funding_and_basis.md`
- `07_crypto_market_structure/crypto_reference_price_rules.md`
- `08_live_trading_sre/exchange_api_runtime_contract.md`
- `08_live_trading_sre/websocket_reconnect_gapfill.md`
- `08_live_trading_sre/exchange_outage_playbook.md`
- `09_exchange_api_security/api_key_permission_policy.md`
- `10_btc_trend_strategy_playbook/btc_trend_research_gate.md`
- `10_btc_trend_strategy_playbook/perp_cost_funding_liquidation_model.md`
- `10_btc_trend_strategy_playbook/live_promotion_checklist.md`

## Local Obsidian Quant Book Corpus

当前本地来源根目录：

`D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD`

截至 `2026-07-11`，目录中有 28 本独立 Markdown 书籍，另有转换索引、重复 OCR 版本和 OCR 质量报告。完整清单与来源质量见：

- `06_book_cards/local_quant_book_inventory.md`
- `06_book_cards/agent_book_knowledge_playbook.md`

扩展映射：

- 系统化策略、趋势、动量、因子：转化为候选登记、forecast、风险归一、参数稳定和研究上限规则。
- 时间序列、蒙特卡洛、随机微积分：转化为模型假设、残差诊断、置信区间、收敛、场景和模型风险规则。
- 市场微观结构与高频执行：转化为 LOB、队列、库存、冲击、延迟、adverse selection 和执行证据规则。
- 软件设计、数据库内部和遗留代码：转化为深模块、信息隐藏、Repository/UoW、WAL/recovery、characterization tests 和安全改动规则。
- 风险溢价与策略生态：转化为 edge explanation、对手盘、流动性、融资、拥挤和失效条件。

权威边界：书籍提供概念、假设和设计约束，不提供当前数据事实、当前实现正确性或 promotion 结论。遇到冲突时，以 `AGENTS.md`、`00_codex_rules/`、当前模块契约和当前 HEAD 证据为准。
