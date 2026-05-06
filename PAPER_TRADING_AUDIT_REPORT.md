# Paper Trading Audit Report

**日期**: 2026-05-03
**范围**: 全量只读代码审查 — 不修改代码
**目标**: 确认系统是否具备 30 交易日 Paper Trading 验证资格

---

## 一、整体判断

**当前阶段: Pre-Production — 未通过 30 天 Paper Trading 门禁**

系统具备基本的纸交易链路（ingest → signal → risk → OMS → broker → fill → ledger → reconcile），但存在 **3 个 CRITICAL blocker** 和 **4 个 HIGH blocker** 阻塞实盘准入。

---

## 二、逐项审计

### 1. 是否存在重复下单

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `client_order_id` 幂等检查 | ✅ | `oms.py:51-53` — `_client_order_ids` set 拒绝重复 ID |
| 重启后幂等 | ❌ **CRITICAL** | `_client_order_ids` 是内存结构，重启清空。`save_state()` 存了 `_pending_order_ids` 但 **未回传给 OMS** |
| `AlpacaPaperRunner._poll_order()` | ⚠️ | 轮询有超时但没有失败后查询 broker 状态再决定是否重试的逻辑 |

**结论**: 正常运行时不会重复下单。**重启后一定会重复下单。**

### 2. 是否存在订单状态丢失

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `SimulatedBroker` 状态持久化 | ❌ **CRITICAL** | 纯内存。`save_state()`/`load_state()` 存在但不恢复 broker 状态 |
| Ledger 可恢复性 | ✅ | `JsonlLedgerStore` 追加写，文件持久化 |
| `OrderLifecycleManager` | ✅ | 可检测过期订单并撤单 |
| 缺少 `UNKNOWN` 状态 | ⚠️ | `OrderStatus` 枚举缺 `UNKNOWN`，无法标记 broker 找不到的订单 |

**结论**: 进程崩溃后 broker 状态丢失，需从 ledger 重建。**`UNKNOWN` 状态缺失**导致异常订单无归属。

### 3. 是否存在本地持仓与 broker 持仓不一致

| 检查项 | 状态 | 详情 |
|--------|------|------|
| Reconciliation 四维检查 | ✅ | `ReconciliationService.reconcile_all()` 检查 cash/positions/orders/fills |
| 不一致时停新仓 | ✅ | `_halt_reconciliation` 标志 → `is_healthy()` 检查 → `run_day()` 拒绝 |
| 告警 | ✅ | CRITICAL 级别 Telegram 告警 |
| 差异报告 | ✅ | JSON 报告写入 `reconciliation/recon_*.json` |
| 不阻止减仓/平仓 | ⚠️ | 当前实现阻止所有交易（`is_healthy()` 返回 False 时 `run_day()` 直接返回），没有区分开仓和平仓 |

**结论**: 基本机制存在。但 **halt 过于粗暴**（应允许减仓平仓，只禁止开新仓）。

### 4. 是否存在 fill 无法追溯到 signal/order/risk

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `Order.signal_id` | ✅ | `Order.from_intent()` 从 `OrderIntent` 继承 |
| `Order.risk_check_id` | ✅ | 同上 |
| `Order.client_order_id` | ✅ | 唯一，自动生成 |
| `Order.broker_order_id` | ✅ | 券商返回后填充 |
| `Fill.order_id` → `Order.order_id` | ✅ | 直接关联 |
| `RiskDecision.risk_version` | ✅ | T-058 新增 |
| `RiskDecision.rule_name` | ✅ | 每次拒绝填充具体规则名 |
| `RiskDecision.threshold` | ✅ | 填充阈值 |

**结论**: **完整链可追溯**。Fill → Order → Signal/OrderIntent/RiskDecision 全链路闭合。

### 5. 是否存在 broker 断连后继续下单

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `AlpacaBroker` 超时配置 | ✅ | `timeout_seconds=20.0` |
| 断连检测 | ❌ **HIGH** | `_poll_order()` 异常被静默捕获（`except Exception: pass`），无断连告警 |
| `KillSwitch` broker 断连熔断 | ❌ **HIGH** | KillSwitch 只有 daily_loss/drawdown/order_failure 三个触发条件，没有 broker 断连触发 |
| 断连后保护模式 | ❌ **HIGH** | 无。异常被吞没，系统继续尝试下一笔订单 |

**结论**: **broker 断连后无保护**。当前代码会继续尝试提交订单，每次失败被计入 `order_failure`，需累积到 `max_consecutive_order_failures=3` 才触发熔断。

### 6. 是否存在 live_runner 重启后重复下单

| 检查项 | 状态 | 详情 |
|--------|------|------|
| `save_state()` | ✅ | 保存 `last_run_date`, `daily_reports`, `pending_order_ids` |
| `load_state()` | ✅ | 恢复 `_pending_order_ids` |
| OMS `_client_order_ids` 恢复 | ❌ **CRITICAL** | `load_state()` 恢复 `_pending_order_ids` 但 **OMS 的 `_client_order_ids` 不会被填充** |
| 重启后 broker 状态恢复 | ❌ | `AlpacaPaperRunner` 不调用 `_poll_order()` 处理恢复的 `_pending_order_ids` |

**结论**: **重启一定重复下单**。`_client_order_ids` 不持久化且不恢复。

---

## 三、Kill Switch 覆盖分析

| 触发条件 | 状态 | 覆盖范围 |
|----------|------|---------|
| `daily_loss_limit` | ✅ | 日内亏损 > 3% |
| `drawdown_limit` | ✅ | 累计回撤 > 12% |
| `order_failure_limit` | ✅ | 连续下单失败 >= 3 次 |
| broker 断连 | ❌ | 未覆盖 |
| 数据延迟 | ❌ | `DataFreshnessGuard` 统计但不熔断 |
| reconciliation 失败 | ⚠️ | `_halt_reconciliation` 但不是 KillSwitch 机制 |
| 进程崩溃/重启 | ❌ | 未覆盖 |

---

## 四、30 交易日验收标准对照

| 标准 | 状态 | 备注 |
|------|------|------|
| 无重复下单 | ⚠️ | 运行时 OK，重启后 FAIL |
| 无状态丢失 | ❌ | broker 状态纯内存 |
| 本地 vs broker 每日一致 | ✅ | 四维 reconciliation 机制存在 |
| fill 可追溯 | ✅ | 全链路 ID 闭合 |
| 重启不重复提交 | ❌ | `_client_order_ids` 不恢复 |
| broker 失败后保护模式 | ❌ | 无断连熔断 |

---

## 五、Blocker 清单

### CRITICAL（阻塞 Paper Trading 30 天运行）

| # | Blocker | 位置 | 修复方向 |
|---|---------|------|---------|
| C1 | OMS `_client_order_ids` 不持久化，重启后重复下单 | `oms.py:37`, `run_alpaca_paper.py:save_state()` | 持久化 `_client_order_ids` 到 JSONL 或在 `load_state()` 时从 ledger 重建 |
| C2 | Broker 状态（positions, cash）不持久化，重启后丢失 | `broker_simulator.py`, `run_alpaca_paper.py` | 从 `JsonlLedgerStore` 重建 broker 状态（replay fills → positions + cash） |
| C3 | `OrderStatus` 缺少 `UNKNOWN` | `enums.py:51-62` | 添加 `UNKNOWN = "unknown"`，OMS 状态恢复逻辑处理 |

### HIGH（阻塞实盘准入）

| # | Blocker | 位置 | 修复方向 |
|---|---------|------|---------|
| H1 | KillSwitch 缺少 broker 断连熔断 | `kill_switch.py` | 添加 `broker_disconnect` 触发条件 + `max_broker_disconnect_seconds` 配置 |
| H2 | Broker 断连后静默吞异常 | `run_alpaca_paper.py:_poll_order()` | 异常时告警 + 记录到 risk_event_log |
| H3 | Reconciliation halt 阻止平仓 | `paper_trading_loop.py:is_healthy()` | 区分开仓 vs 平仓：halt 只禁止开新仓，允许减仓平仓 |
| H4 | KillSwitch 缺少数据延迟熔断 | `kill_switch.py` | 添加 `max_data_staleness_seconds` 配置 |

### MEDIUM

| # | Issue | 位置 |
|---|-------|------|
| M1 | `AlpacaPaperRunner._poll_order()` 轮询失败后不查询 broker 状态 | `run_alpaca_paper.py:134-146` |
| M2 | `data_freshness` 统计但不熔断 | `paper_trading_loop.py:169-171` |
| M3 | KillSwitch 缺少 reconciliation 失败累积熔断 | `kill_switch.py` |

---

## 六、下一阶段推荐 Ticket（12 个）

| 优先级 | ID | 标题 | 文件范围 | 验收标准 |
|--------|----|------|---------|---------|
| **P0** | T-064 | OMS 幂等性持久化 | `oms.py`, `execution/ledger.py`, `run_alpaca_paper.py` | 重启后不重复下单 |
| **P0** | T-065 | Broker 状态从 Ledger 恢复 | `broker_simulator.py`, `run_alpaca_paper.py` | 重启后 positions/cash 恢复 |
| **P0** | T-066 | OrderStatus 添加 UNKNOWN + 状态恢复 | `enums.py`, `oms.py`, `order_lifecycle.py` | 异常订单可标记 UNKNOWN |
| **P0** | T-067 | Reconciliation Hard Gate（只禁开仓） | `paper_trading_loop.py`, `reconciliation_service.py` | halt 时允许平仓禁止开仓 |
| **P0** | T-068 | KillSwitch V2（broker/data/recon 熔断） | `kill_switch.py`, `risk/` | 4 类熔断全触发 |
| **P1** | T-069 | Broker 断连保护 + 告警 | `run_alpaca_paper.py`, `telegram_alerts.py` | 断连 → 告警 → 停止新单 |
| **P1** | T-070 | 故障模拟测试（10 场景） | `tests/test_chaos_*.py` | 10 场景全部覆盖 |
| **P1** | T-071 | Risk Event Log | `risk/risk_event_log.py` | 所有拒绝和熔断留痕 |
| **P1** | T-072 | 每日交易日报自动生成 | `monitoring/daily_report.py` | JSON + 可读摘要 |
| **P2** | T-073 | 监控指标暴露 | `monitoring/metrics.py` | Prometheus metrics |
| **P2** | T-074 | PostgreSQL 状态库迁移 | `data/storage/postgres_store.py` | 双写 SQLite + PG |
| **P2** | T-075 | Live Readiness Gate | `reports/live_readiness.py` | 自动检查 + 文档 |

---

## 七、推荐 4 周排期

| 周 | Sprint | 工单 | 目标 |
|----|--------|------|------|
| W1 | Sprint 1 | T-064, T-065, T-066 | 幂等性 + 状态恢复 |
| W2 | Sprint 2 | T-067, T-068, T-069 | Hard Gate + KillSwitch V2 |
| W3 | Sprint 3 | T-070, T-071 | 故障演练 + Event Log |
| W4 | Sprint 4 | T-072, T-073 | 日报 + 监控 |

---

## 八、不可进入实盘的硬条件

在以下条件全部满足前，**不得开启 Alpaca Live 订单**：

1. OMS `_client_order_ids` 持久化或从 ledger 重建 ✓
2. Broker 状态可从 ledger 恢复 ✓
3. KillSwitch 覆盖 broker 断连 + 数据延迟 + reconciliation 失败 ✓
4. Reconciliation halt 允许平仓 ✓
5. 10 个故障场景全部通过 ✓
6. 30 个连续交易日 paper trading 无状态错误 ✓
7. 本地 vs broker 仓位每日一致 ✓
