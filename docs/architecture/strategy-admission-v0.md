# V0：策略冻结与准入记录

2026-09-15 · STRATEGY-V0-FREEZE-20260915

结论：已固定比较对象、预期业务结果、决策合同设计和发布缺项，并增加保护测试。**这不是 V1 接入实现；后续发布准入仍 blocked，独立审查/合入尚未完成。**

基准 main：`b920d131e41ecbfe7f76f0709affbe22c8b35f5e`。生产分支：`agent/btc_developer/strategy-v0-freeze-20260915`。只新增本文、`tests/fixtures/strategy_v0/baseline.json`、`tests/contracts/test_strategy_v0_freeze.py`，另附 append-only 交付事件。不改运行源码、共享 schema、治理、UI、模型或历史证据。

## 1. 固定比较对象

### Donchian

- 策略 `long_short_donchian_top5_okx_native`；候选 `okx_native_btc_ls_tf_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_78f5f0a0e4`。
- 版本 `btc_long_short_donchian_top5_okx_native@1.0.0`；参数 hash `5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355`。
- `baseline_1x`；方向归一后乘 0.01 合约，每张 0.01 BTC，不是持有 0.01 BTC。
- 原参数：4h Donchian 入场 240、退出 120、日线 50/200、ATR 20×2、冷却 12；失败突破退出/衍生品过滤保持关闭。完整参数固定在 JSON。
- 三组 5,200 根合成小时序列，结束于 `2026-07-30T12:00:00Z`，时钟 `12:05Z`。多/空/平的输入公式、初态、目标与订单预期已固定。账户未采集、无 worker；测试不是历史市场收益证据。
- 测试成本：手续费 5bps、资金费绝对值 1bps、限价预算 5bps、测试深度冲击 0；不声明真实市场成本。
- 旧回测的 0.98 权重及 next-completed-open 约定单独记录，不能与运行固定合约/完成 bar 后决策混同。V1 保护原运行行为，不改写旧回测收益。

保护测试直接调用原注册函数、控制器 `_signal_decision`/`_build_order_plan` 及原 ATR/冷却状态函数，没有重写策略。历史源码 Git blob 用于找回旧实现，不作为永久禁止 V1 改动整个文件的门槛。

### 一个固定 Qlib 模型

选择平台既有普通研究运行 `m1-okx-qlib`，不是重新按收益选模，也不冒称工厂冠军。

- 候选 `qlib_manifest_0de835a36fc243c1`，策略 `qlib_time_series_trend_v1`。
- 源计算版本 `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`，不冒充当前 V0 计算产物。
- 既有 resolver 固定 Git manifest：`165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`。
- 整包 160 个文件校验通过，aggregate `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`。
- 模型 SHA256 `8b44ef4bc97be069c21240cbf70a78b7e2f29fc182b057925328503196e16b74`；预测、校准、配置、seal 等关键文件 hash 固定在 JSON。
- 实际加载为 1 棵树、13 个特征，内部名称 Column_0—Column_12；必须遵守封存配置的特征顺序。
- 固定训练/验证/测试日期、Fillna、验证集 OLS 系数、12h 期限、2-bar 延迟及候选成本/仓位/退出。配置声明波动目标与实际未应用分别记录。
- 校准质量字段为 true，但测试 IC 约 -0.08289，1,392 次研究决策、0 次模拟成交，blocker=`no_simulated_fills`。校准通过不等于有效性或执行通过。
- 实际加载环境：Qlib 0.9.7、LightGBM 4.7.0、pandas 3.0.4、numpy 2.4.6。这不是完整训练依赖锁恢复证明。

只做归档校验与模型加载；没有 fit/predict、校准重拟合、MLflow 恢复、下载或归档修改。模型加载后逐行预测/特征一致性留 V2。

## 2. 决策合同设计冻结

这是设计合同，不是运行 schema 已实现的声明。

| 项目 | 决定 |
|---|---|
| 接入 | 复用 Context，外围组合版本化信封，不替换 BTC/US/CN 领域类 |
| 身份 | package digest、策略/参数/代码/模型引用、domain/instrument、账户绑定、事件/decision ID |
| 时间 | event/available/decision/expiry；新入口严格校验与具体 TTL enforcement 留 V1，不改旧默认 |
| 输出 | Donchian 方向＋固定合约；Qlib 校准收益＋候选政策；禁止补造 Forecast 质量 |
| 单位 | contracts/BTC/weight 显式区分，面值/精度校验，不猜 quantity 含义 |
| 策略状态 | 前后态、schema、处理阶段；保留虚拟持仓与 close-based ATR |
| 经济状态 | BTC pending intent/clOrdId/order/fill/ledger UOW 权威，shared CAS 不单独宣告经济完成 |
| 反向 | 先平仓不等于整根 bar 完成；恢复需分阶段，不能换 ID 盲重发 |
| 账户范围 | 单策略、单账户、单 instrument；两策略分离回放，不做账户优化 |
| 对比 | 身份/方向/理由/单位/Decimal 业务结果 exact；V2 预测 atol=1e-10、rtol=1e-8，禁止失败后自动放宽 |
| 权限 | 包完整性、模型质量、一致性、执行覆盖、交易授权分开判断 |

## 3. 测试与覆盖

新增保护：身份/参数、历史源码可找回、真实多空平信号/固定目标、重复决策不增订单序号、充分预热前缀因果性、短预热空仓、八种订单计划、数量拒绝、缺失/过期 loader 错误传播、长短 ATR/退出/12-bar 冷却、候选不授权、精确归档/模型/特征/校准核验。

经济负对照只在测试进程把合约数从 0.01 改为 0.02，确认旧预期会失败，monkeypatch 随后恢复。退出用例注入 channel-exit 条件，验证原状态函数，不冒称覆盖全部价格驱动通道检测。

复用回归覆盖 Context、US 类型、A 股边界、BTC composition/risk/portfolio/Guardian/OMS、M1 保护、未完成意图重启、超时按 clOrdId 查询、资金费原子落账、历史行情 stale 限制。它们不是一条新生产 cycle 的端到端证明。

最终命令（在本专属工作树运行）：

```powershell
$v0Temp = Join-Path ([System.IO.Path]::GetTempPath()) ('qs-v0-final-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $v0Temp) { throw 'temporary path already exists' }
$env:QS_V0_VERIFY_ARCHIVE='1'
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B -c "import socket,sys,pytest,logging; logging.getLogger('quantstation').addHandler(logging.NullHandler()); deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('V0 network prohibited')); socket.socket.connect=deny; socket.socket.connect_ex=deny; socket.create_connection=deny; sys.exit(pytest.main(sys.argv[1:]))" -q -p no:cacheprovider --tb=short --maxfail=2 --basetemp $v0Temp tests/contracts/test_strategy_v0_freeze.py tests/contracts/test_btc_strategy_registry.py tests/contracts/test_strategy_decision_context_v1.py tests/contracts/test_us_shared_platform_adoption.py tests/cn_equity/test_boundaries.py tests/contracts/test_btc_demo_production_composition.py tests/contracts/test_btc_shared_platform_v3_risk_kernel.py tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py tests/contracts/test_btc_shared_platform_v3_guardian_latch.py tests/contracts/test_btc_shared_platform_v3_oms_delegation.py tests/contracts/test_m1_btc_behavior_freeze.py tests/contracts/test_btc_okx_demo_paper_runtime.py::test_restart_recovers_every_nonterminal_exchange_intent_fail_closed tests/contracts/test_btc_okx_demo_paper_runtime.py::test_submit_timeout_queries_by_durable_clordid_and_never_reposts tests/contracts/test_btc_okx_demo_paper_runtime.py::test_runtime_commits_atomic_funding_ledger_uow_and_exchange_reconciliation tests/contracts/test_btc_okx_demo_paper_runtime.py::test_stale_okx_native_baseline_is_loadable_only_as_explicit_public_tail_seed
```

过程证据：

- 先写测试、未建清单：1 个预期 FileNotFoundError，证明没有隐式 baseline fallback；不是旧业务缺陷复现。
- 首次新增测试：8 passed/15 setup errors，原因是既有 pytest 全局临时目录权限；任务独立目录重跑 23 passed/14.52s。
- 首次扩大回归：backend import 默认日志目录不可写导致 collection error；测试进程 NullHandler 后 218 passed/47.97s，没有更改正式日志配置。
- 补充合约数量漂移负对照并恢复执行后的最终结果：**219 passed / 46.99s**（24 项新增 V0 参数化测试，195 项既有回归）；无 skip。
- 中断前一次最终测试进程结果无法取回，未推断通过；恢复后重跑。

本轮显式设置 archive 验证标志，没有借 skip 宣布模型核验。普通环境未设置该变量时会明确 skip 本地归档检查，不下载、不找 latest。

未运行：完整生产 cycle、真实账户/交易所对账、V1 适配比较、全部崩溃点、Qlib 预测 parity、正式页面、服务重启。原恢复测试通过不等于未来 shared 状态接线已经安全。

## 4. 发布准入与停止点

- Donchian/Qlib 比较对象和工程预期已经固定；V1/V2 必须消费提交态清单，不重新选参/选模。
- V0 仅 tests/fixture/document，保守 unclassified；独立审查/集成待完成，不直接合入 main。
- **后续发布仍 blocked**：research_readonly_release 禁止执行语义修改，demo_execution_semantics 映射 demo_quasi_live。需独立审定“高风险代码＋只读展示”发布路径；如需治理改动，另行限定授权，不混入 V0、不启用 Demo。
- V0 不启动 V1/V2、M3—M4，不授予账户/交易权限。加载通过不证明 Qlib 候选有效。
- 回退点为上述 base，main 未改变。合入前可以不消费本分支；合入后按审定提交回退代码，不能 reset 或删除模型、历史研究与经济账本。

## 5. 交付审计

- 主会话承担已授权 V0 测试/文档生产职责，role=btc_developer，change_risk=unclassified；没有修改业务语义。planner 建立 sparse 工作树，quant_us/quant_cn 仅补入只读测试依赖。
- 初始限定路径 clean；仅本票据新增，无覆盖/回滚其他工作树。未合入账户采集交付不在本票据消费链中。
- 使用 quant-agent-preflight/handoff；已读 AGENTS、知识索引、non-negotiables、shared/btc_developer/architect playbook、domain_architecture_rules、delivery_risk_policy。
- catalog `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- pitfall：BACKTEST-COST-001、BTC-NONFLAT/OMS/PERP/WS-001、DATA-BTC-FINAL-001、GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS-001、QSYS-GATE/SECURITY-001、REPLAY-ISOLATION-001、RESEARCH-HOLDOUT-001。
- 运行 context_packet（btc_developer，btc/shared，unclassified）、限定 safe_status、planner、Git/源码读取、既有归档 resolver 及上列测试。
- 模型/数据只读，无新 promotion/runtime artifact；冻结 JSON 是工程 fixture/reference，不是交易账本。历史计算版本与 V0 版本明确区分。
- promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 全部保持 false。
