# ADR-003: 订单生命周期状态机

**状态**: ACCEPTED
**日期**: 2026-05-03
**决策者**: 个人开发者

## 背景

订单从策略信号到最终成交经过多个模块（Strategy → Portfolio → Risk → OMS → Broker → Ledger），每个模块可能修改订单状态。如果不明确状态转换规则，会出现重复执行、状态不一致、或静默丢单。

## 决策

### 核心管道

```
Signal ──► TargetPosition ──► OrderIntent ──► RiskDecision ──► Order ──► Fill
  |              |                |               |              |          |
  Strategy   PositionSizer   RebalancePlanner  RiskEngine     OMS      Broker
              AllocCombiner
```

### OrderStatus 状态机

```
                    CREATED
                       │
                       ▼
                  RISK_CHECKED
                       │
                    ┌──┴──┐
                    │     │
                拒绝 ▼     │ 通过
              REJECTED     ▼
                        SUBMITTED
                           │
                        ┌──┴──────┐
                        │         │
                    拒绝 ▼    接受 ▼
                  REJECTED   ACCEPTED
                                 │
                              ┌──┴──────────┐
                              │              │
                         部分成交 ▼       全部成交 ▼
                    PARTIALLY_FILLED     FILLED
                              │
                              ▼
                          FILLED
                         (补足后)


CANCEL_PENDING ──► CANCELLED    (主动撤单)
EXPIRED                         (过期)
ERROR                           (异常)
```

### 各阶段详细说明

#### 1. CREATED → RISK_CHECKED

**触发**: `Order.from_intent(intent, risk_decision)`
**位置**: `quant_us/execution/oms.py:60`
**逻辑**: 风控通过后，将 OrderIntent + RiskDecision 转换为 Order 对象。Status 直接设为 `RISK_CHECKED`。

#### 2. RISK_CHECKED → SUBMITTED（或 REJECTED）

**触发**: `OMS.handle_intent()`
**位置**: `quant_us/execution/oms.py:61-64`
**逻辑**:
- KillSwitch 触发 → 直接返回 `OMSResult`，不创建 Order（状态仍为 `OrderStatus` 枚举中定义，但 `OMSResult.order` 为 None）
- `client_order_id` 重复 → 返回 `OMSResult`，不提交
- RiskEngine 拒绝 → 返回 `OMSResult`，不创建 Order
- RiskEngine 批准 → `order.status = SUBMITTED`，调用 `broker.submit_order(order)`

#### 3. SUBMITTED → ACCEPTED / REJECTED / ERROR

**触发**: `SimulatedBroker.submit_order()` 或 `AlpacaBroker.submit_order()`
**位置**: `quant_us/backtest/broker_simulator.py:70-145`
**逻辑**:
- 回测引擎：检查 gap_overrides → 计算 fill_price → 创建 Fill → 返回 status=ACCEPTED 的 Order
- Alpaca Paper：通过 REST API 提交，返回券商响应中的 status
- `SimulatedBroker` 的 `fill_ratio` 控制部分成交概率（默认 1.0 = 全部成交）

#### 4. ACCEPTED → PARTIALLY_FILLED → FILLED

**触发**: Broker 的成交匹配逻辑
**逻辑**:
- `PARTIALLY_FILLED`: 部分数量成交，剩余数量挂单
- `FILLED`: 全部数量成交

#### 5. 撤单路径

**触发**: `broker.cancel_order(order_id)`
**位置**: `quant_us/execution/broker_base.py:28`
**逻辑**: `CANCEL_PENDING → CANCELLED`（券商确认后）

### OMS.handle_intent() 完整决策树

```
handle_intent(intent, account, market_price, timestamp)
    │
    ├─ KillSwitch 触发?
    │   └─ YES → RiskDecision(False, "kill_switch_*")
    │       └─ return OMSResult(order=None, events=[RiskEvent])
    │
    ├─ client_order_id 重复?
    │   └─ YES → RiskDecision(False, "duplicate_client_order_id")
    │       └─ return OMSResult(order=None, events=[RiskEvent])
    │
    ├─ RiskEngine.evaluate() → RiskDecision
    │   └─ NOT approved?
    │       └─ return OMSResult(order=None, events=[RiskEvent])
    │
    ├─ Order.from_intent(intent, decision)
    │   └─ status = SUBMITTED
    │
    ├─ broker.submit_order(order)
    │   ├─ 成功 → register client_order_id
    │   │         ├─ status = REJECTED/ERROR → kill_switch.record_order_failure()
    │   │         └─ status = 其他 → kill_switch.record_order_success()
    │   └─ 异常 → kill_switch.record_order_failure()
    │            └─ order.status = ERROR, raise
    │
    └─ broker.get_fills(order_id=submitted.order_id)
        └─ return OMSResult(order=submitted, fills=fills, events=[RiskEvent, BrokerOrderEvent, FillEvent...])
```

### 一 Bar 延迟规则

**Strategy 在 bar t 用 close 决策入场的 Signal，实际 Fill 发生在 bar t+1。**

原因：收盘价只有在 bar 结束后才知道。在 bar t 的 close 做决策 + 在 bar t 的 close 执行 = 前视偏差。

实现方式：
1. `EarningsDriftStrategy` 将入场 Signal 缓冲到 `_pending_entry`，在下一个 bar 发出
2. 事件驱动引擎按 bar 顺序处理，天然保证 signal_time < fill_time
3. 回测引擎禁止同一 bar 的 close 同时用于决策和成交价

## 后果

### 正面

- 状态转换明确，可测试（`test_oms.py` 覆盖所有路径）
- KillSwitch 和重复订单检查在风控之前执行，防止无效计算
- OMS 是唯一的订单提交路径，不存在绕过风控的代码路径
- 订单幂等性通过 `client_order_id` 保证

### 负面

- 状态机有 11 个状态，`PARTIALLY_FILLED` 路径在纸交易中较少触发
- 异常路径（`ERROR`）当前只是记录状态，没有自动重试机制
