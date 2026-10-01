# ADR-001: 系统边界定义

**状态**: ACCEPTED
**日期**: 2026-05-03
**决策者**: 个人开发者

## 背景

QuantStation 是一个量化交易平台。为了避免范围蔓延，必须在 V1 明确系统边界。

## 决策

### V1 资产范围

**仅支持美股正股和 ETF。** 不包含：

- 加密货币（现有 crypto 代码保留但不在 V1 路径中）
- 期权、期货、外汇
- 粉单、OTC、SPAC

### V1 交易方向

**仅做多。** `PreTradeRiskConfig.long_only = True` 是默认且唯一支持的配置。`SignalDirection.SHORT` 枚举存在但风控层会拒绝。

### V1 券商接入

**仅 Alpaca Markets Paper Trading。** 不接入：

- Alpaca Live（纸交易门禁通过前）
- Interactive Brokers（stub 存在但 `submit_order` 抛出 `NotImplementedError`）
- 任何其他券商

### V1 数据源

**仅 YFinance。** 通过 `yfinance_data.py` 适配器获取日线 OHLCV。

### V1 回测范围

- 日线 bars（`1d`）
- 单一策略信号
- 不做投资组合优化（等权分配）
- 不做 ML 模型集成

### 明确排除

| 项目 | 状态 | 启用条件 |
|------|------|---------|
| 做空 | 代码存在，风控拒绝 | ADR 修订 |
| 加密货币 | 代码存在，未接入 V1 管线 | ADR 修订 |
| IBKR 实盘 | Stub 存在 | 纸交易 30 天通过 |
| Alpaca Live | 适配器已实现 | 纸交易 30 天通过 |
| ML 模型 | 脚本存在，未接入 | 因子管线验证通过 |
| 分钟级回测 | Schema 存在，引擎未适配 | 日线验证通过 |

## 后果

### 正面

- 减少测试矩阵（只需测美股/做多/Alpaca Paper）
- 减少操作风险（无实盘资金风险）
- 减少监管复杂度（美股证券，非衍生品）

### 负面

- V1 收益来源单一（只做多美股）
- 当前代码库包含 V2/V3 功能的 stub（crypto, IBKR, ML），需要维护但不激活

## 合规

- `PreTradeRiskConfig.long_only` 默认 `True`
- `PreTradeRiskEngine.evaluate()` 拒绝 `projected_quantity < 0` 的 OrderIntent
- `SignalDirection.SHORT` 在风控层被拦截
