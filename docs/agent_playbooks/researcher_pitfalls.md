# Researcher Pitfall Rules

适用代理：研究员、策略研究、假设生成、回测验证和 promotion evidence 准备。

## 职责边界

- 研究员不写真实下单代码，不调用 broker/exchange，不接触 secret。
- 策略研究产物只能进入 Signal / Forecast / TargetPosition 接口，不能绕过 portfolio/risk/OMS。
- 研究结果必须标注数据版本、样本窗口、holdout 状态、cost model、slippage model、funding/fees、commit hash。

## 必读文件

- `docs/agent_playbooks/shared_pitfalls.md`
- 本文件
- 读取 catalog 中匹配 `researcher` 和任务 scope 的 active rules
- `docs/knowledge/02_research_backtest/`
- `docs/knowledge/02_research_backtest/backtest_evidence_contract.md`
- `docs/knowledge/03_portfolio_risk/`
- BTC 研究另读 `docs/knowledge/10_btc_trend_strategy_playbook/`
- 命中具体 source 或调查历史事故时，再定向读取 BTC/美股原始日志

## 研究硬线

- 不允许用单一 Sharpe、单一窗口、单一榜单或样本内收益作为上线依据。
- 不允许用未建模费用、滑点、funding、冲击成本的回测指导 paper/live。
- 不允许在 holdout、confirmatory window 或 future observe-only 窗口继续选参。
- 不允许把 partial universe、stale cache、缺 FRED/ETF 覆盖的数据结果写成候选。
- 不允许把 diagnostic report、research_only artifact 或 flat heartbeat 当成 promotion evidence。

## BTC 研究规则

- bar replay 必须证明可见字段在 `decision_time` 前可用。
- Long/Short、High-Octane、High-yield 等观察线必须区分 research-only、observe-only、paper gate evidence。
- observe-only 30/60 天按唯一决策日和连续性计算，不能按首尾跨度冒充。
- 非空信号出现后，要触发 paper runtime evidence 链；研究员不得手工跳过 risk/OMS/fill/ledger。

## 美股研究规则

- 外部 ETF rotation 必须先验证 required universe、latest common price date、宏观数据 freshness。
- 月末/调仓研究必须使用实际交易日和 T+1 执行语义。
- partial yfinance / stale AkShare / 缺 PIT 文件时只能输出 research-only blocker。
- hypothesis registry 需要 design spec evidence，策略卡片本身不够。

## 交付要求

研究报告必须输出：

- 数据版本、样本窗口、训练/验证/holdout 切分。
- 参数来源、是否有 selection bias 风险。
- 成本、滑点、funding、冲击成本假设。
- walk-forward / stress / no-lookahead / ledger evidence。
- 明确 gate 结论：research-only、candidate、blocked 或可提交架构审查。
