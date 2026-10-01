# Trading And Exchanges Rule Cards

> 状态：旧版主题摘要，不计入 `L1/L2`。`EXE-01` 标准章节卡已完成 `29/29` 章 `L2`，原子项仍待 `L3`，以 `coverage_manifest.md` 为准。

## 用途

约束订单、成交、流动性、滑点、OMS、broker adapter。

## 转化规则

- 订单不等于成交。
- 市价单和限价单交换的是成交确定性和价格确定性。
- Liquidity 至少拆为 tightness、depth、resiliency。
- 成交绩效用 implementation shortfall 评估。
- Broker/交易所适配器是代理层，必须可审计和可对账。

## 对应文件

- `04_execution_oms/market_microstructure_execution_rules.md`
- `04_execution_oms/order_lifecycle.md`
- `04_execution_oms/broker_adapter_contract.md`
