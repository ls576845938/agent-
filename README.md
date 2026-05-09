# QuantStation VNEXT

个人美股量化研究/回测/纸交易平台。

最小闭环说明见 [docs/VNEXT_MINIMAL_CLOSED_LOOP.md](docs/VNEXT_MINIMAL_CLOSED_LOOP.md)。
本轮 baseline 收口报告见 [docs/report/baseline/2026-05-09-vnext-minimal-closed-loop/](docs/report/baseline/2026-05-09-vnext-minimal-closed-loop/).

## 系统状态

| 指标 | 状态 |
|------|------|
| 测试 | 全量 pytest 需要 `PYTHONPATH=.`，具体覆盖与结果以本轮交付报告为准 |
| 回测引擎 | 事件驱动，全订单生命周期 |
| 数据 | YFinance → Parquet → Manifest → 质量评分 |
| 风控 | 投前 9 项检查 + 投后滑点 + 流动性 |
| 纸交易 | simulated paper 可用；真实 Alpaca paper adapter 尚未接入，`paper_broker=alpaca` fail-closed；fake adapter 仅用于 contract tests |
| 实盘 | 未启用（纸交易门禁阻塞中） |

## 快速开始

```bash
# 安装
python -m venv venv && source venv/bin/activate
pip install -e .

# 测试
PYTHONPATH=. pytest backend/tests/ -q

# 启动 API
uvicorn backend.app.api.app_factory:create_app --host 0.0.0.0 --port 8000 --factory

# 启动前端
cd frontend && npm install && npm run dev

# 数据 / 回测 / 门禁
python scripts/generate_data_manifest.py --source yfinance --symbol AAPL --interval 1d --start 2024-01-01 --end 2024-03-31 --validate
python -m quant_us.cli manifest list --kind all --limit 20
python -m quant_us.cli report backtest --run-id <run_id>
python -m quant_us.cli report daily --latest
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli research promotion-gate --candidate-id <candidate_id>

# 端到端研究闭环，止步于当前闭环边界，不会自动开始纸交易或实盘
python scripts/run_full_pipeline.py --symbol AAPL --mode full --start 2024-01-01 --end 2024-03-31
```

说明：

- 这里的快速开始只覆盖当前可用的研究、回测、报告和门禁检查入口。
- 真实 Alpaca paper 还未接入；`paper_broker=alpaca` 继续保持 fail-closed。
- paper startup sync artifact 只用于审计和门禁判断，不代表真实交易已经开通。
- 文档里出现的 paper/live 入口只代表边界和门禁，不代表自动提交订单。

## 目录结构

```
quant_us/          # 核心量化引擎
  backtest/        # 事件驱动回测（engine, broker, slippage, ledger, walk-forward）
  core/            # 基础类型、日历、枚举
  data/            # 数据摄取、清洗、存储、manifest、幸存者偏差
  execution/       # OMS、订单路由、券商适配器
  factors/         # 因子计算（动量、波动率、流动性、价值、质量）
  live/            # 纸交易循环、对账、状态协调
  monitoring/      # 告警、指标、日志
  portfolio/       # 仓位管理、配置、再平衡
  research/        # 实验、参数扫描、数据集构建
  risk/            # 风控（投前、投后、流动性、敞口、熔断）
  strategies/      # 策略实现
backend/           # FastAPI 后端
  app/api/         # API 路由、Schema
  app/services/    # 业务逻辑
  app/domain/      # 领域模型、策略注册
frontend/          # React 仪表盘
scripts/           # CLI 脚本
config/            # SQL Schema, Prometheus 配置
```

## 架构原则

1. 策略只发出 Signal，不直接调用券商
2. 所有订单必经 Risk Engine
3. 所有 PnL 从 Fills 和 Ledger 推导
4. 回测结果可从 Manifest 复现
5. 不做前视，不做幸存者偏差
6. 实盘代码需纸交易门禁通过后才能上线
