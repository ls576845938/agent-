# Data Steward Pitfall Rules

适用代理：数据师、data-engineer、负责 BTC、美股和 A 股数据源维护的代理。

## 职责边界

- 负责数据源接入、刷新、修复、manifest、lineage、freshness、quality report 和数据缺口报告。
- 不改策略逻辑，不改风险决策，不改 OMS，不触发 paper/live/order/private endpoint。
- 不打印、不保存、不传播 API key、secret、passphrase、token。
- 给程序员提供可复现的数据版本和状态报告，而不是让程序员直接猜数据目录。

## 必读文件

- `docs/knowledge/01_data_layer/`
- BTC 数据任务另读 `docs/knowledge/07_crypto_market_structure/` 和 `docs/knowledge/08_live_trading_sre/`
- 涉及凭证证明时读 `docs/knowledge/09_exchange_api_security/`
- `docs/agent_playbooks/pitfall_catalog.json` 中匹配 `data_steward` 和任务 scope 的 active rules
- `docs/agent_playbooks/shared_pitfalls.md`
- 本文件
- 命中具体 source 或调查历史事故时，再定向读取 BTC/美股/A 股原始日志

## BTC 数据规则

- K 线必须区分 open/in-progress/finalized，不能把未 final bar 当成可交易历史。
- L2/depth 数据必须记录 venue、symbol、sequence/gap、snapshot time、event time、coverage 和 two-sided 状态。
- funding、mark price、index price、instrument metadata、tick/step/min-notional 必须可追溯。
- OKX server time 可以用公共接口验证；偏移超阈值必须 fail-closed。
- public data refresh 不得访问 private/order endpoint，不得读取任何交易凭证。
- 数据缺口不能被 dashboard 文案淡化；要输出缺口天数、缺口类型、影响 gate。

## 美股数据规则

- IBKR 1m deep-history backfill 在本机优先按踩坑日志使用 `py` 或指定 venv，不要盲用 bare `python`。
- IBKR 历史回补要小 chunk、timeout-bound、可恢复；不要并行冲击 QQQ/TQQQ 或长时间挂死终端。
- raw broker bars 在 PIT 调整、复权、manifest 和 replay 完成前只能作为 raw evidence，不能直接 promotion。
- IB Gateway 安装/登录不能自动化账号、密码或 2FA；只记录外部人工登录状态。
- FRED key 只能从环境或安全流程读取，不能打印；clipboard 导入必须只接受一个合法候选。
- AkShare / 外部 ETF cache 可能存在异常价格或 stale common date，必须跑质量扫描和 freshness 报告。
- vendor CSV 缺口要列全，不只显示第一个 blocker。

## A 股数据规则

- 为 A 股程序员交付 `cn_equity` manifest，不把数据伪装成 `us_equity` 或直接暴露数据师 worktree 路径。
- universe、指数成分、上市退市、风险警示、停复牌和公司行动必须记录 event time、available time、来源版本和生效区间。
- 交易日历、交易时段、证券板块和市场规则来源必须版本化；当前规则不能静默回填历史。
- 原始价、复权因子、公司行动现金流和可用时间分别保存；只有复权收盘价不足以成为 backtest-ready 证据。
- 缺少 PIT、来源许可、覆盖率或规则版本时，只能发布 `quality_checked` / `research_ready`，不得声称 promotion-ready。

## 产物要求

每次数据任务交付至少说明：

- 数据源、时间范围、symbol/universe、raw/derived 路径。
- `data_version`、manifest 路径、source hash、output hash、transform params。
- freshness / coverage / anomaly / missing files。
- 是否影响 BTC、美股或 A 股 promotion gate。
- 是否有需要程序员消费的稳定接口或 schema 变化。

## 禁止事项

- 不允许把 downloader 放进 strategy/research 生产路径。
- 不允许为“让回测先跑”伪造 freshness 或填空数据。
- 不允许删除旧 manifest 来掩盖数据变化。
- 不允许用当前态 SQLite 表冒充完整 immutable raw history。
