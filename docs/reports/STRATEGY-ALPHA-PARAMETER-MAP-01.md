# 策略浏览：历史报告恢复、Alpha 来源与参数稳定性

## 任务与边界

- Ticket: STRATEGY-ALPHA-PARAMETER-MAP-01
- Producer: root / super_developer
- Base: 4096453b344e777e99f4272b43582d60cf1251f9
- Worktree: planner 创建的 `super_developer-strategy-alpha-parameter-map-01`
- change_risk: unclassified（现有政策没有普通研究 UI/只读报告类别）。独立 integrator 必需。
- gate_impact: none；不是 promotion evidence 工作。架构审查批准一个 producer + 一个独立 integrator；不重建不相关交易 gate。
- 安全：promotion、paper、live、private、order、real_order、transfer、withdraw=false。无交易网络、secret、订单、SQLite 写入。
- 初始声明路径 dirty_count=0；只写专属工作树，未消费其他 worktree 未提交交付，未回滚其他改动。

## 根因与实现

历史接口收到的 runtime artifact reader 为 None。当前进程未继承外部 root；现有 User-level promotion root 本身也没有 history。旧 UI 将配置/发布缺失错误统称“服务正在恢复”，不准确。

增加显式 `QS_BTC_STRATEGY_HISTORY_ARTIFACT_ROOT`，只影响历史报告和参数网格读取。启动脚本只从 User scope 补读这个非秘密路径；不补读凭证或改变 promotion root。路径仍使用原 owner/reparse/worktree 边界校验；显式配置错误不 fallback。保留既有历史 snapshot pointer/index/report SHA 校验、候选及 native baseline 语义。

策略目录增加独立 Alpha 筛选（可与完成度相交）、按 Alpha 分组，以及同策略所有变体共享的本浏览器多标签标注。统计套利、趋势、宏观、时序、截面为主要来源，另提供事件、微观结构与待归类。默认映射只用已知 strategy ID，不从名称猜测未知 Alpha；标签不改变系统完成度或执行权限。

根据独立架构审查核对实际 generate：macro_trend 是价格均线趋势，factor_rank 是单序列动量/波动率，etf_rotation/earnings_drift 目前都是价格动量。分别按趋势/时序标注，不伪称宏观、截面或财报事件来源。宏观、统计套利、截面分类即使暂时为空也保留；用户可另行保存本机研究标签。

右侧分析新增“历史回测 / 参数稳定性”标签。热力图支持 Sharpe、CAGR、最大回撤、Sortino，指标颜色与数字一致；hover/focus/click 展示同组合全部指标。数值轴排序；所有其他参数固定；同坐标多结果标记重复，未发布组合留空，NaN/缺失不补零；drawdown 越接近 0 越好。只有所有行逐行满足唐奇安公式 `exit_window=floor(entry_window/2)` 时才允许该明确显示的联动，其他条件继续固定。

二维图不会改变参数或执行策略。公式/优化阶段分组，完整窄网格与其他阶段不混算。提示已参与选参的历史样本、相对色阶、来源哈希、成本/窗口、研究近似及所需样本外验证。

## 声明 touch set

- `backend/app/api/btc_strategy_history.py`：独立 history reader、只读参数接口。
- `backend/app/services/strategy_parameter_evidence.py`：有界校验、历史投影、hash-bound reader。
- `backend/tests/test_strategy_parameter_evidence.py`：源数据、错误配置与哈希负向测试。
- `backend/tests/test_btc_strategy_history_api.py`：旧报告合同测试显式注入 fixture reader，不依赖生产 fallback。
- `scripts/start_backend_current_main.ps1`：补读显式历史 root。
- `scripts/publish_strategy_parameter_evidence.py`：仅手工作业调用的一次性单写者发布；新增路径属于同一报告数据接入范围。
- `frontend/src/lib/strategy-alpha.ts`：身份映射与来源标签。
- `frontend/src/workspaces/StrategyExplorer.tsx`：分析页签、真实错误文案。
- `frontend/src/workspaces/crypto/StrategyDiscoveryCatalog.tsx`：分类和分组。
- `frontend/src/workspaces/crypto/StrategyParameterHeatmap.tsx`：图、筛选、检查器和证据说明。
- `frontend/src/workspaces/crypto/strategy-parameter-map.ts`：可验证的纯数据切片规则。
- `frontend/src/workspaces/strategy-workbench.css`：该页面范围样式。
- `frontend/scripts/test-strategy-parameter-map.mjs`、`frontend/e2e/strategy-alpha-heatmap.spec.ts`：纯函数和浏览器验收。
- 本报告、`.agent/handoffs/STRATEGY-ALPHA-PARAMETER-MAP-01/` append-only 交付。
- 集成时需更新 `frontend/public/frontend-identity.json`（独立 integrator 自有），再重启 canonical 服务。

## 历史数据 / 发布合同

当前主工作树持久研究源：`artifacts/btc_long_short_trend_following_lab/latest/btc_long_short_trend_following_lab_report.json`。

- SHA-256: `406cfb9f2bf0facb0c1445c65aca601cc5c930c992c35dcc0f810aa8f1a9fd22`
- source code: `1b3bc6ed`（publisher 解析为完整 Git commit）。生成时间 2026-06-29T23:37:05.456709+00:00。
- Binance spot BTCUSDT completed 1h → 4h，2024-01-01 至 2026-06-28 UTC；成本 10 bps，含 taker/slippage，funding 为研究近似。
- 全量 long_short 1448 行，参数唯一 1448，原 params_hash 全部匹配。1440 formal_narrow_grid，8 其他公式/阶段。
- 每行取唯一基础成本 scenario 的全部四项指标，并核对同名顶层指标。无指标缺失，无重跑/插值/生成收益。
- CAGR 语义由 `multi_timeframe_rule_lab.performance_metrics` 的 `(1+total_return) ** (365/elapsed_days) - 1` 核实。
- 该 ignored 大文件只是经批准的一次性 bootstrap 输入，不是跨代理源码交付，干净 checkout 不声称能重建它。Backend 绝不直接读取该文件；后续只消费外部 hash-addressed 快照。
- 源数据没有物理数据文件哈希：明确 `source_data_hashes_unavailable`，只能称哈希冻结的历史参数结果；不能证明可重放。UI 同步说明。发布前另对 Top5 的每个 candidate、params、四指标与网格精确核对，两份 source SHA 分开保留，Top5 pointer v1 字节不改。

历史候选报告读取已发布 owner-marked `btc-strategy-history-current-head-0df67017-20260817T225023Z` 快照，原 report SHA `e0fed490008cf885c44e378369ffd0336d3bf9eabcae7b98b123c86725ca8026`，复制保持原字节与历史 provenance。

部署顺序：source integration → 独立显式 bootstrap 新任务 root → publisher（expected SHA 必填、空发布目录、原 writer exclusive lock、内容先写/pointer 最后）→ read-only hash 验收 → 配置独立 history root → canonical backend/frontend restart。不得更改已有 shared root 或历史报告，不得把新发布等同新的回测。所有报告仍 historical_not_current_head。

## 验证

- failure-first：新 Python test 在模块未实现时 ModuleNotFoundError；新 Node test 在实现未存在时 ENOENT。原 HTTP 请求直接返回 503 reader unavailable。
- `python -m pytest backend/tests/test_strategy_parameter_evidence.py -q`：14 passed。独立复核要求禁止缺省回退 promotion reader；新增失败优先回归先出现 2 failed / 12 passed（历史目录错误返回 200），修正后全部通过。
- `python -m pytest backend/tests/test_btc_strategy_history_api.py -q`：19 passed（FastAPI/httpx 既有 deprecation warning）。
- `node frontend/scripts/test-strategy-parameter-map.mjs`：passed。覆盖固定其他参数、缺失、重复、非有限值、轴、耦合、颜色方向、0 值、精确 Alpha 映射。
- `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`：passed；首次发现 React shim key 类型缺项，局部修复后通过。
- `vite build`：passed；现有单 bundle >500kB 提醒。
- 真实源只读 projection smoke：1448 行，四指标缺失计数全部 0。
- canonical 部署、浏览器新测试、真实页面检查在独立集成后执行，producer 阶段未运行。没有启动 worktree Vite。
- 曾尝试 `--no-cov`（该环境插件未安装，不识别）；移除无关选项后按仓库 pytest 执行。

## 治理与未解锁项

已读 quant-agent-preflight / quant-agent-handoff、knowledge README、non-negotiables、shared_pitfalls、super_developer_pitfalls、delivery_risk_policy、backtest_evidence_contract。

Catalog hash: `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。

Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, RESEARCH-HOLDOUT-001, GOV-PROMPT-001, GOV-WINDOWS-001。

未全文加载历史踩坑日志。未消费 discovery-only 队列中的其他 handoff。上游已有 invalid_handoffs=13，不由本任务修订。无 promotion、paper/live 或自然观察验收声明。
