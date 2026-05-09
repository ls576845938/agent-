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
| 纸交易 | simulated paper 可用但默认不提交订单；真实 Alpaca paper adapter 未进入自动提交路径，`paper_broker=alpaca` 默认 fail-closed；fake adapter 仅用于 contract tests |
| 实盘 / micro live | `LiveRuntime` 是 safety shell，live mode 不执行订单；真实 live 需独立 executor、人工审批、submission gate、readiness、endpoint guard |
| Ledger | fill idempotent append 使用同 ledger root 的文件锁；直接 `append_fill()` 不提供幂等保护 |

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
python -m quant_us.cli report evidence-registry --data-root data
python -m quant_us.cli report daily --latest
python -m quant_us.cli readiness --profile paper --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile shadow_live --validation-state data/reports/paper_production/validation_state.json
python -m quant_us.cli readiness --profile live --validation-state data/reports/paper_production/validation_state.json --check-credentials
python -m quant_us.cli research promotion-gate --candidate-id <candidate_id>

# 端到端研究闭环，止步于当前闭环边界，不会自动开始纸交易或实盘
python scripts/run_full_pipeline.py --symbol AAPL --mode full --start 2024-01-01 --end 2024-03-31
```

说明：

- 这里的快速开始只覆盖当前可用的研究、回测、报告和门禁检查入口。
- CLI report/readiness/evidence registry 输出统一使用 `PASS` / `STALE` / `MISSING` / `CONFLICT`，并标明 `report only, no execution`。
- CLI 会展示 Data Manifest v2 lineage、Evidence Registry subject index、paper session manifest、startup sync artifact、ledger reconciliation artifact 等 persisted evidence；这些只是只读证据。
- `report backtest` 会展示 ledger artifact hash、ledger/fills/orders/snapshot hash、`generated_at`、`as_of_utc`、artifact consistency/completeness 状态；缺字段显示 `(missing)`。
- paper daily/report 输出会在存在时展示 `paper_session_history_artifact_path`，指向 `paper_ledger/audit/paper_session_manifests/<session_id>.json`。
- Canonical path 是 `manifest -> ledger-backed backtest -> promotion handoff -> paper/runtime readiness report`。
- readiness / report / paper runtime gate 默认只消费已保存的 Evidence Registry，不会隐式 rebuild；`MISSING`、`STALE`、`CONFLICT` 都是 fail-closed。
- Evidence Registry 显式 rebuild 使用 atomic write 和 lock；report/readiness/paper runtime gate 只读 saved registry。
- `paper_review_index` 只是 legacy view，不是 paper/runtime gate 的权威来源。
- 只有 `review.json` 不足以启动 paper runtime；必须先显式 rebuild registry，再由 readiness / report / paper runtime gate 读取保存结果。
- 真实 Alpaca paper 还未进入自动提交路径；`paper_broker=alpaca` 继续保持默认 fail-closed。
- paper order 默认不提交，必须走显式 paper path 和显式配置才能开启。
- readiness/evidence/report 都是 report/review only，不执行 paper/live order。
- `LiveRuntime` 是 safety shell；即使 readiness evidence pass，live mode 也不会提交订单。
- live production / micro live 仍需要独立 executor、人工审批、submission gate、readiness、endpoint guard，不属于本轮自动化。
- ledger 幂等写入通过 `append_fill_idempotent()` 使用文件锁；直接 `append_fill()` 仅用于非幂等追加场景。
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
