# QuantStation 系统架构

## 管道拓扑

```
Data Pipeline                  Trading Pipeline
-------------                  ----------------
YFinance API                     Strategy.on_bar()
     |                                |
     v                                v
  Raw Parquet                      Signal[]
     |                                |
     v                                v
  BarCleaner                   PositionSizer.size()
  CorporateActionAdjuster           |
  BarDataValidator                  v
     |                        TargetPosition[]
     |                                |
     v                                v
  DataManifest               AllocationCombiner.combine()
  (quality score,                   |
   fingerprint,                     v
   coverage_pct)              RebalancePlanner.plan()
     |                                |
     v                                v
  ParquetBarStore              OrderIntent[]
  (hive-style)                      |
     |                                v
     v                         OMS.handle_intent()
  DataLakeService                    |
     |                           +----+----+
     v                           v         v
  EventDrivenEngine <------- RiskEngine  BrokerBase
     |                           |         |
     |                      RiskDecision  Order
     |                           |         |
     v                           v         v
  LedgerEquityCurve            OMSResult  Fill[]
     |
     v
  UnifiedBacktestResult
  (event_driven + ledger + turnover + determinism)
```

## 模块边界

Strategy 只读 MarketEvent + StrategyContext, 返回 Signal[], 不访问券商/账户。

Portfolio + Risk 将 Signal 转换为 OrderIntent, 所有订单必经 RiskEngine。

OMS 封装 RiskEngine + KillSwitch + Broker, 是唯一的订单提交路径。

Broker 接收 Order, 返回 Fill[]。SimulatedBroker 用于回测, PaperBroker/AlpacaBroker 用于纸交易/实盘。

Ledger 从 Fill[] 推导 PnL, 与 Broker 快照交叉验证。

## 数据契约

| 对象 | 可变性 | 来源 | 消费者 |
|------|--------|------|--------|
| Bar | frozen | DataPipeline | Strategy.on_bar() |
| Signal | frozen | Strategy | PositionSizer |
| TargetPosition | frozen | AllocationCombiner | RebalancePlanner |
| OrderIntent | frozen | RebalancePlanner | OMS |
| RiskDecision | frozen | RiskEngine | OMS |
| Order | mutable | OMS | Broker |
| Fill | frozen | Broker | Ledger |
| PortfolioSnapshot | frozen | Broker | Ledger, API |

所有时间戳 UTC, symbol 大写, 构造时自动标准化。

## 关键设计决策

1. 策略不调用券商 — Strategy 只能读 MarketEvent + StrategyContext, 返回 Signal[]
2. PnL 从 Fills 推导 — 不存在直接从 Signal 计算 PnL 的路径
3. 事件驱动回测是唯一规范路径 — UnifiedBacktestRunner 包含完整订单生命周期
4. Manifest 是不可变契约 — 每个回测记录 data_version, strategy_version, commit_hash
5. 纸交易是实盘门禁 — 必须连续 30 天无状态错误才能上线
