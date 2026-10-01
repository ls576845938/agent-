# Super Developer Pitfall Rules

适用代理：超级程序员、quant-developer、主要维护美股和通用工程代码的程序员。

## 职责边界

- 按架构票据实现代码、测试、报告和本地工具。
- 默认不接管 BTC 专用交易所/OMS 风控逻辑，除非任务明确指定。
- 不直接改外部用户策略项目；需要 refactor 前先确认已有 file-hash backup。
- 不把数据下载、调度、broker 登录放进策略层。

## 必读文件

- `docs/agent_playbooks/shared_pitfalls.md`
- 本文件
- 美股任务读取 catalog 中匹配 `super_developer` / `us_equity` 的 active rules；只在命中 source 时定向读取原始日志
- 数据相关读 `docs/knowledge/01_data_layer/`
- 回测/策略相关读 `docs/knowledge/02_research_backtest/`
- 风控相关读 `docs/knowledge/03_portfolio_risk/`
- 执行相关读 `docs/knowledge/04_execution_oms/`

## 美股开发重点

- 数据层要服务多策略，不要把 Tiingo、IBKR、vendor drop 命名成 ETF-only 基础设施。
- 外部 ETF rotation 只能在数据完整、PIT、复权和宏观数据通过前保持 research-only。
- 月末调仓必须使用最后一个实际交易日，并按 T+1 执行语义移动权重。
- strategy math 只消费 Data Layer 输出，不拥有 AkShare/FRED/IBKR 下载器。
- schema 变更后必须重建 concrete latest artifacts，再跑 schema/contract tests。
- blocker taxonomy 要能区分 source-level PIT file blockers、external_data、operator action。

## Windows 开发规则

- 没有 GNU make 时使用 `make.cmd` 或 `scripts/win_make.py`。
- npm 被 PowerShell policy 阻断时使用 `npm.cmd`。
- Playwright spec 路径使用 forward slash。
- pytest basetemp 避免复用固定目录。
- 本机 Python 启动器异常时，按踩坑日志使用 `py` 或 `.venv\Scripts\python.exe`。

## 执行/OMS 开发规则

- 不能为了通过 BTC paper OMS 改共享 `quant_us.core.enums.OrderStatus`。
- 美股 broker credential review 只能记录审查事实，不接触 secret。
- live_order_allowed、paper_order_allowed 等安全 flag 必须默认 false，除非 gate 证据链完整。
- 拒单、撤单、部分成交、重复提交、market closed、broker outage、对账差异都要有演练证据。

## 交付要求

- 列出改动文件、测试命令、重建 artifact 路径。
- 说明是否改变 schema、是否需要数据师刷新数据、是否影响 BTC 边界。
- 如果测试失败，保留 exact failure 和下一步，不要把失败包装成通过。
