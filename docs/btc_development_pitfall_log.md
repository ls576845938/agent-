# BTC 系统开发踩坑日志

## 2026-06-24 PowerShell 中文输出可能误显示为乱码

- 场景：检查 Python 源码或 Markdown 产物时，`Get-Content` 默认输出里中文路径和中文正文可能显示为乱码。
- 误判风险：把实际正常的 UTF-8 文件误认为源码损坏，进而做无意义修复。
- 处理方式：先用 `Get-Content -Encoding UTF8 <path>` 或读取实际产物确认；不要仅凭终端默认显示判断文件编码。
- 本次证据：`scripts/build_btc_intraday_trend_v1_report.py` 和 `学习资料/量化交易业务闭环/系统评估/BTC 小周期趋势 v1 回测报告.md` 实际 UTF-8 正常。

## 2026-06-25 PowerShell 不支持 Bash heredoc

- 场景：在 PowerShell 中执行 `python - <<'PY'` 校验 JSON/schema。
- 现象：PowerShell 报 `Missing file specification after redirection operator`，因为 `<<` heredoc 是 Bash 写法。
- 处理方式：Windows/PowerShell 下改用 `python -c "..."`，或把临时代码放入脚本文件后运行。
- 本次证据：schema JSON 校验命令改为 `python -c` 后通过。

## 2026-06-25 BTC 状态产物生成顺序会造成短暂冲突

- 场景：`btc_current_status` 开始读取 `btc_paper_readiness`、BTC registry、global registry 做状态一致性检查。
- 现象：如果按 `current_status -> btc_registry -> global_registry` 首次生成，`current_status` 会先读到旧 registry，并记录 `btc_current_status_btc_registry_queue_conflict` / `btc_current_status_global_registry_queue_conflict`。
- 处理方式：状态 schema 或生成链改动后，按 `current_status -> btc_registry -> global_registry -> current_status -> btc_registry -> global_registry` 收敛一次；日常稳定链路中应由编排器保证依赖顺序。
- 本次证据：第二轮收敛后 `current_status.paper_queue_status=approved`，`status_source_conflicts=[]`，BTC/global registry 均为 `approved`。

## 2026-06-25 PowerShell 复杂 rg 正则引号容易被拆

- 场景：在 PowerShell 中用包含大量 `"`、`[]`、`|` 的 `rg` 正则搜索测试断言。
- 现象：参数被 PowerShell 拆分，`rg` 把表达式片段当路径，报 `系统找不到指定的文件`。
- 处理方式：优先用简单关键词分步搜索，例如 `rg -n pending_review <file>`；复杂匹配放到脚本或使用更严格的引号转义。

## 2026-06-25 BTC bundle id 不宜在通用 preflight 测试中硬编码

- 场景：数据源配置和本地产物可能在 `history_365d`、`intraday_5m_31d`、`daily_roll_90d` 等 bundle 之间切换。
- 现象：`test_btc_perpetual_bundle_preflight_schema_valid` 硬编码旧 bundle id，当前 artifact 已指向另一个有效 BTC bundle 时测试失败。
- 处理方式：通用 schema/preflight 测试只断言 BTC bundle id 前缀、结构完整、`preflight_pass` 和 required files；具体 bundle id 应留给配置选择测试或 operator report。
- 本次证据：将断言从精确 `btc_okx_swap_btcusdt_history_365d_v1` 改为 `btc_okx_swap_btcusdt_` 前缀后，PIT/preflight 定向测试通过。

## 2026-06-26 resample lineage 不应写入 quality_summary

- 场景：P0-4 要求 BTC resample manifest 写入 source hash、transform version、参数和输出 hash。
- 现象：`DataManifest` 的 `quality_summary` 会被 `_normalize_quality_summary` 归一化为固定整数质量计数字段，额外的 lineage/hash 字段会在写入 manifest 时丢失。
- 处理方式：给 `DataManifest` 增加向后兼容的 `lineage` 字段；BTC resample 将 `source_hash`、`output_hash`、`transform_version`、`transform_params_hash` 写入 `lineage`，保留 `quality_summary` 只表达质量计数。
- 本次证据：`python -m pytest tests/data/test_crypto_resample.py backend/tests/test_data_manifest.py -q` 通过，manifest JSON 中可直接读取 `lineage`。

## 2026-06-26 market_klines 当前态表不是完整多版本存储

- 场景：P0-4 同时要求 raw immutable 和 derived versioned，但现有 `market_klines` 唯一键是 `exchange/symbol/interval/open_time_ms`，写入逻辑是 upsert 当前态。
- 现象：直接把底层表改为多版本存储会影响现有同步、预览、resample 和测试语义，也可能干扰美股主线 agent 的共享基础设施工作。
- 处理方式：本轮先将 BTC resample 派生版本落实到 manifest 层：`data_version` 绑定 `source_hash + output_hash`，源数据变化会生成新的 manifest 文件，旧 manifest 不被覆盖；底层 SQLite 仍作为当前态物化表。后续若要实现物理 raw immutable，需要单独设计 raw append-only 表或版本列迁移。
- 本次证据：新增测试覆盖源 1m 数据变化后生成不同 `data_version`、不同 manifest path，且旧 manifest 文件仍存在。

## 2026-06-26 evidence pack 测试不能假设 BTC 仍停在人工复核前

- 场景：P0-5 加固 `build_btc_paper_review_evidence_pack.py`，给 evidence pack 增加 promotion evidence contract。
- 现象：旧测试只预期 readiness 已批准带来的 blockers，但当前权威状态机已经显示 `status=paper_observing`、`paper_queue_status=approved`，再次生成“人工复核前 evidence pack”时还会合理出现 `btc_paper_review_current_status_not_ready`。
- 处理方式：测试改为反映当前状态机语义：report 可以因状态已推进而 blocked，但 `promotion_evidence_contract.status` 必须是 `complete`，且 `missing_fields` / `missing_minimum_metrics` 必须为空。
- 本次证据：`python -m pytest tests/contracts/test_btc_paper_review_evidence_pack.py -q` 通过，生成的 `artifacts/btc_paper_readiness/latest/btc_paper_review_evidence_pack_report.json` 中 contract complete。

## 2026-06-26 trial registry 不能只读显式 params_hash

- 场景：P0-6 要求每个 BTC 候选参数、失败 fold、被拒配置都保留 `run_id / params_hash / selected_by / rejection_reason`。
- 现象：部分旧 bounded retest artifact 没有在 outcome 顶层写 `params_hash`，但其 source artifact 指向的 canonical report 含 `config_hash`，run manifest 也可提供 source run lineage。若 registry 只读顶层字段，会误报缺 `params_hash`。
- 处理方式：trial registry 对 bounded retest 先读 outcome，再沿 `source_artifacts.run_manifest` 和 `source_artifacts.canonical_backtest_report` 补齐 `strategy_id` 与 `params_hash`；仍补不齐时才 fail closed。
- 本次证据：`python -m pytest tests/contracts/test_btc_trial_registry.py -q` 通过；生成的 `artifacts/btc_trial_registry/latest/btc_trial_registry.json` 含 26 条 trial，`status=complete`，`blockers=[]`。

## 2026-06-26 未来数据变异测试不等于截断一致性测试

- 场景：P0-7 要求全量数据与截断到决策时点的数据，历史信号必须一致。
- 现象：已有 BTC intraday 测试会把未来价格放大后比较早期信号，但这只能证明“远端未来变异不影响早期窗口”，不能证明生产中按 `decision_time` 截断重算时，resample context、rolling feature、diagnostics 和 repaired/drift-guarded filter 也完全一致。
- 处理方式：新增全量 frame 与 `frame.loc[:cutoff_ts]` 截断 frame 的直接一致性断言，分别覆盖基础 `pullback_reclaim_intraday_signal` 和 `DRIFT_GUARDED_ENTRY_FILTER` 后的信号/diagnostics。
- 本次证据：`python -m pytest tests/research/test_btc_intraday_short_cycle_event_ledger.py -q` 通过，另跑 `python -m pytest tests/backtest/test_crypto_event_backtest.py tests/research/test_btc_hypothesis_lab_no_lookahead.py -q` 通过。

## 2026-06-26 Forecast -> TargetPosition 不能只记录风险预算

- 场景：P1-8/P1-10 要求 BTC 先经过 Forecast/Alpha 层，再由 portfolio/risk budget 生成 TargetPosition，并且目标仓位必须记录 `target_weight`、`target_notional`、`expected_vol`、`cost estimate`、约束命中和 rebalance reason。
- 现象：初版 BTC Forecast 层已经阻断了 Signal 直接变仓位，也记录了 forecast horizon/unit/confidence/expiry/IC 证据和风险预算，但 target metadata 漏了 `cost_estimate`，后续若直接接 OrderIntent 会弱化“成本感知调仓”的 fail-closed 边界。
- 处理方式：在 BTC 专用 `BTCRiskBudget` 上增加 `estimated_round_trip_cost_bps`，TargetPosition metadata 输出 `cost_estimate.round_trip_cost_bps`、`estimated_cost_bps` 和计算依据；仍只生成 TargetPosition，不生成订单意图。
- 本次证据：`python -m pytest tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过。

## 2026-06-26 BTC 风险预算配置不能替代运行时风险状态

- 场景：P1-9 要求 BTC portfolio/risk budget 覆盖 `max BTC exposure`、cash floor、daily loss、drawdown stop、cooldown、turnover、funding risk、exchange outage、data anomaly。
- 现象：只在 `BTCRiskBudget` 上增加阈值字段还不够，因为 daily loss、当前回撤、cooldown 截止时间、funding rate、交易所可用性、数据异常都是运行时状态；如果 target 生成函数没有强制接收这些状态，就会把“有预算配置”误当成“已检查风险预算”。
- 处理方式：新增 BTC 专用 `BTCRiskState`，`btc_forecast_to_target_position` 缺少 risk state 时直接拒绝；cash floor/turnover 缩仓，daily loss/drawdown/funding/cooldown 触发 target 归零并禁止订单生成，exchange outage/data anomaly 保持当前仓位并禁止订单生成。
- 本次证据：`python -m pytest tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio` 通过。

## 2026-06-26 成本感知 OrderIntent 测试要同时设置阈值和状态

- 场景：P1-11 要求下单前比较 alpha 增量与 fee/spread/slippage/funding/impact，无法估成本或 alpha 不足时不得生成 order intent。
- 现象：新增 BTC 成本门后，测试“daily loss stop 应阻断 OrderIntent”时只把运行时 `daily_loss_pct` 设为 3.1%，但 `BTCRiskBudget.max_daily_loss_pct` 仍是默认 100%，导致风险层没有触发 `order_generation_allowed=False`，测试错误地进入成本通过路径。
- 处理方式：风险阻断 fixture 必须同时设置预算阈值和运行时状态；OrderIntent 成本门只读取 TargetPosition 的风险结论，不重新解释 daily loss 阈值。
- 本次证据：修正 fixture 后 `python -m pytest tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过。

## 2026-06-26 BTC Paper OMS 不应为了 reconciled 改共享 OrderStatus

- 场景：P1-12 要求 BTC paper OMS 覆盖 `created/risk_checked/submitted/accepted/partial/filled/canceled/rejected/expired/reconciled`，且全程幂等。
- 现象：共享 `quant_us.core.enums.OrderStatus` 已被美股执行链大量使用，但它没有 `reconciled`，取消请求也使用 `cancel_pending` 而不是架构清单里的 `cancel_requested`。直接改共享枚举会影响美股 agent 的主线和既有 paper/live 测试。
- 处理方式：新增 BTC 专用 `BTCPaperOrderStatus` 和 `BTCPaperOrderLifecycle`，状态值完整覆盖 BTC 架构要求；用 `client_order_id` 做本地幂等索引，记录 append-only event history，不提交 broker。
- 本次证据：`python -m pytest tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms` 通过。

## 2026-06-26 BTC venue precision 不能替代 tick/step 规则

- 场景：P1-13 要求 BTC venue rules 统一 tick size、lot size、min notional、precision、maker/taker fee、funding interval、24/7 交易日历，并同时服务回测和 paper。
- 现象：交易所 metadata 同时有 `pricePrecision/quantityPrecision` 和 `PRICE_FILTER.tickSize/LOT_SIZE.stepSize`。如果执行约束只按 precision 四舍五入，可能生成不满足 tick/step 的价格或数量；这和既有 `docs/btc_exchange_info_metadata_policy.md` 中“precision 仅作诊断，不能替代 tick/step”的规则冲突。
- 处理方式：新增 BTC 专用 `BTCVenueRules`，执行规范化只使用 `tick_size` 和 `step_size`；`price_precision/quantity_precision` 只写入 metadata 作诊断。venue gate 同时输出 min notional、maker/taker fee、funding interval、24/7 calendar 和 best-execution basis。
- 本次证据：`python -m pytest tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms` 通过。

## 2026-06-26 Execution quality 不能只看最终 reconciled 状态

- 场景：P1-14 要求 BTC 执行质量指标输出 implementation shortfall、fill rate、reject rate、cancel rate、latency、unfilled opportunity cost。
- 现象：BTC Paper OMS 的最终成功对账状态统一是 `reconciled`，如果 execution quality 只看最终状态，会把 filled/cancelled/rejected 全部混在一起，无法正确计算 fill/reject/cancel rate。
- 处理方式：新增 BTC 专用 `build_btc_execution_quality_report`，统计 filled/rejected/cancelled/expired 时读取订单生命周期 event history；报告同时聚合 fill 级 latency、implementation shortfall、fee/spread/impact/delay cost 和未成交机会成本。
- 本次证据：`python -m pytest tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms` 通过。

## 2026-06-26 Audit DAG 不能只检查 artifact_hash

- 场景：P2-15/P2-17 要求 BTC audit DAG 覆盖 `data snapshot -> feature -> signal -> forecast -> target -> risk -> order -> fill -> ledger -> PnL -> report`，每个节点有 artifact path/hash/code version，并统一结构化日志字段。
- 现象：如果只要求每个 artifact 有 hash，仍可能出现节点顺序缺失、依赖断裂、结构化日志缺 `risk_decision_id/fill_id/error_code` 等字段的问题；这种 DAG 看似可追踪，实际无法支持 replay 和 incident 定位。
- 处理方式：新增 BTC 专用 `BTCAuditDAG`，强制固定节点顺序、逐节点依赖、artifact path/hash/code version/input_hashes，并校验 `run_id/strategy_id/data_version/decision_time_utc/signal_id/forecast_id/target_id/risk_decision_id/order_id/fill_id/error_code`。
- 本次证据：`python -m pytest tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms quant_crypto/monitoring` 通过。

## 2026-06-26 Replay engine 不应自己读取实时或当前文件状态

- 场景：P2-16 要求 BTC replay engine 固定 clock/seed，不接 live data，能重放任一 BTC 决策并输出 signal/target/risk diff。
- 现象：如果 replay engine 内部按 artifact path 自行读取文件，测试环境和生产运行时都可能读到“当前 latest”而不是 audit DAG 绑定的历史输入；这会让 replay 看似成功，实际混入当前状态。
- 处理方式：新增 BTC 专用 `run_btc_replay` 纯函数契约，只消费调用方注入的 audit DAG payload、历史 data snapshot/params/risk/current position/orders/fills 和 replay 函数；`live_data_accessed=True` 或 audit DAG 非 complete 直接 blocked。
- 本次证据：`python -m pytest tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms quant_crypto/monitoring` 通过。

## 2026-06-26 Incident trigger 和模板空值校验不能依赖隐式 Python 行为

- 场景：P2-18 要求数据中断、OKX/Binance API 错误、funding 缺口、ledger mismatch、gate 状态冲突、重复订单、drawdown breach 都生成 incident artifact 和回归测试。
- 现象：初版 incident builder 对 `BTCIncidentTrigger` 枚举成员再次执行 `str(trigger)`，得到的是 `BTCIncidentTrigger.DATA_INTERRUPTION` 这类枚举显示名，不是 contract 需要的 value；模板空值判断还把 `[]` 放进 set，导致 `TypeError: unhashable type: 'list'`，所有 incident 校验先炸掉。
- 处理方式：新增 `_trigger_from_value`，枚举成员原样返回，字符串输入才按 value 转换；模板空值判断改成显式函数，分别处理 `None`、空字符串和空容器。
- 本次证据：`python -m pytest tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms quant_crypto/monitoring` 通过。

## 2026-06-26 Order surface audit 会扫描到自己的禁止端点正则

- 场景：P2-19 要求审计 BTC 直接 broker/order 调用面，除 OMS 外全部冻结或封装，避免研究/策略层绕过 Risk Engine。
- 现象：新增源码扫描规则后，真实 `quant_crypto` 扫描首先命中 `quant_crypto/monitoring/order_surface_audit.py` 自己的 `/order`、`/account`、`/position` 禁止端点正则定义；这是策略文本，不是业务调用面。
- 处理方式：只对审计策略文件自身加窄豁免；`quant_crypto/oms/` 仍作为唯一允许 paper order lifecycle 的边界，其他 BTC 源文件出现 broker SDK 导入、私有/订单端点字面量、直接下单/撤单函数或 live order true flag 都会 blocked。
- 本次证据：`python -m pytest tests/contracts/test_btc_order_surface_audit.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms quant_crypto/monitoring` 通过。

## 2026-06-26 统一 artifact schema 要落在生成层而不是只写测试断言

- 场景：P2-20 要求所有 BTC 报告必须有 `status`、`decision`、`blockers`、`warnings`、`generated_at`、`as_of_utc`、`artifact_hash`、`input_hashes`。
- 现象：P2 新增的 audit DAG、replay、incident、order surface audit 已经各自有 `status/blockers/artifact_hash/input_hashes`，但字段命名和完整性不统一；如果只在测试里检查某些报告，会让后续新报告继续漂移。
- 处理方式：新增 `apply_btc_artifact_schema` / `validate_btc_artifact_schema`，在 artifact 生成层统一补齐 schema version、decision、warnings、generated_at、as_of_utc 和 hash；当前 P2 monitoring 输出全部接入该 helper。
- 本次证据：`python -m pytest tests/contracts/test_btc_artifact_schema.py tests/contracts/test_btc_order_surface_audit.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_venue_rules.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_risk_budget_contract.py -q` 通过，`python -m compileall -q quant_crypto/portfolio quant_crypto/oms quant_crypto/monitoring` 通过。

## 2026-06-26 新增脚本不能假设调用者已经设置 PYTHONPATH

- 场景：P0 后续要求生成 `artifacts/btc_paper_validation/latest/` 三件套和 `btc_api_key_permission_audit` artifact。
- 现象：直接运行 `python scripts/build_btc_paper_validation_artifacts.py` 和 `python scripts/build_btc_api_key_permission_audit.py` 时，Windows 路径下脚本进程的 `sys.path` 没有仓库根目录，导致 `ModuleNotFoundError: No module named 'quant_crypto'`。
- 处理方式：两个新脚本都在导入项目模块前把 `Path(__file__).resolve().parents[1]` 加入 `sys.path`；这和仓库内其他独立脚本的运行方式保持一致。
- 本次证据：两个脚本均可直接运行；`python -m pytest tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_api_key_permission_audit.py -q` 通过。

## 2026-06-26 Trend boundary 不能把扫描报告伪装成 runner 已接入

- 场景：P0-5 要求当前 BTC trend runner 显式经过 `Signal -> Forecast -> Target -> Cost Gate -> OrderIntent -> Paper OMS`，并禁止策略绕过 broker/order 边界。
- 现象：当前 raw forward daily report 只有 public-only/simulated-only guardrails，没有真实的 `forecast_target_order_chain`；如果边界报告只检查“没有下单”，会掩盖 Forecast/Target/Cost/OMS 尚未接入主流程的问题。
- 处理方式：新增 `btc_trend_boundary_report`，完整链路缺任一 artifact 或 source_boundary 不匹配都 blocked；当前 latest 报告如实 blocked，后续 runner 真正写出 chain 后才允许变 complete。
- 本次证据：`python scripts/build_btc_trend_boundary_report.py` 生成 `artifacts/btc_trend_v0/latest/btc_trend_boundary_report.json`，状态为 `blocked` 且列出缺失链路；`python -m pytest tests/contracts/test_btc_trend_boundary_report.py -q` 通过。

## 2026-06-26 Daily 数据刷新失败不能抹掉 roll runner 边界证据

- 场景：继续 P0-5，把 BTC raw trend runner 真正接入 `Signal -> Forecast -> Target -> Cost Gate -> OrderIntent -> Paper OMS` 链路。
- 现象：执行 `python scripts/run_btc_trend_raw_forward_observation_daily.py --execute-network --json` 时 OKX public REST 刷新失败，daily latest 被正确写成 `BLOCKED`，但 roll runner 使用本地已有 bundle 可以生成完整 `forecast_target_order_chain`。如果 boundary 只读 daily report，会把“数据刷新失败”误判为“runner 没有边界链路”。
- 处理方式：roll runner 每轮写出 signal、forecast、target、cost_gate、order_intent、paper_oms_lifecycle 六类轻量 artifact；daily 成功时透出该 chain，boundary 脚本在 daily 缺 chain 时回退读取 latest roll chain，并保留 daily source status。数据刷新 blocker 仍留在 daily，不伪造刷新成功。
- 本次证据：`python scripts/run_btc_trend_raw_forward_observation_roll.py --json` 输出完整 `forecast_target_order_chain`；`python scripts/build_btc_trend_boundary_report.py` 输出 `status=complete`；`python -m pytest tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_trend_boundary_report.py -q` 通过。

## 2026-06-26 Source role 报告不能只复用 PIT contract

- 场景：P1-1 要求每个 BTC source role 输出 PIT、finalized、gapfill 状态。
- 现象：已有 `evaluate_pit_contract` 能检查 `event_time/available_time/ingested_at/processed_at`，但它不知道 K 线是否 finalized，也不知道时间序列 gap 是否被 gapfill 恢复；如果只引用 PIT contract，会把未 final K 线或未恢复缺口漏掉。
- 处理方式：新增 `build_btc_source_role_report`，在 PIT contract 外再检查 finalization 字段、非 final 行、按 role interval 识别 gaps，并要求 gapfill events 证明缺口已恢复。
- 本次证据：`python -m pytest tests/contracts/test_btc_source_role_report.py -q` 通过；综合回归 `python -m pytest tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_forecast_layer.py tests/contracts/test_btc_cost_aware_order_intent.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过。

## 2026-06-26 Paper OMS session 不能只看单笔 lifecycle

- 场景：P1-2 要求把 partial fill/reject/cancel/reconcile 和 execution quality 写入同一 session ledger。
- 现象：BTC Paper OMS lifecycle 能证明单笔订单状态机，execution quality 能统计订单和 fill，但如果没有 session-level reconciliation，仍可能出现 filled order 缺 fill row、fill 找不到订单、ledger hash 未绑定等跨文件不一致。
- 处理方式：新增 `build_btc_paper_oms_session_reconciliation`，把 orders、fills、ledger_hash、execution_quality 聚合为一个标准 artifact；未 reconciled、缺 ledger hash、filled order 缺 fill、unknown fill 都 blocked。
- 本次证据：`python -m pytest tests/contracts/test_btc_paper_oms_session_reconciliation.py -q` 通过；综合回归 `python -m pytest tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过。

## 2026-06-26 Incident drill 要补 order_reject 触发类型

- 场景：P1-3 要求用 paper observation 生成 data outage、funding gap、order reject、ledger mismatch 的 incident 模板、回放和回归测试链接。
- 现象：既有 `BTCIncidentTrigger` 覆盖数据中断、API 错误、funding 缺口、ledger mismatch、gate 冲突、重复订单、drawdown breach，但没有显式 `order_reject`。如果用 duplicate order 代替，会让拒单 drill 的根因和回归测试指向不准。
- 处理方式：扩展 `BTCIncidentTrigger.ORDER_REJECT`，并新增 `build_btc_incident_replay_drill` 聚合四类核心 paper drill；每个 scenario 必须有 incident artifact、audit DAG hash、replay hash 和 regression test。
- 本次证据：`python -m pytest tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py -q` 通过；综合回归 `python -m pytest tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_artifact_schema.py -q` 通过。

## 2026-06-26 Gate dashboard 不能用单页汇总掩盖 blocker

- 场景：P2-1 要求把 current status、registry、paper readiness、live blockers 合成单页 BTC gate dashboard。
- 现象：当前 trend boundary 已 complete，但 paper validation runtime/evaluation 和 API key permission audit 仍 blocked。如果 dashboard 只显示顶层 paper_observing，会让人工 review 误以为 paper/live 证据闭合。
- 处理方式：新增 `build_btc_gate_dashboard`，逐个聚合 current status、global registry、paper readiness 和关键 artifact；任何 missing/blocked artifact 都提升为 dashboard blocker，live_state 始终显示 `live_order_allowed=false`。
- 本次证据：`python scripts/build_btc_gate_dashboard.py` 生成 `artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json`，状态为 `blocked`，blockers 指向 `paper_validation_runtime`、`paper_validation_evaluation`、`api_key_permission_audit`；综合回归 `python -m pytest tests/contracts/test_btc_gate_dashboard.py tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过。

## 2026-06-26 Paper validation runtime 不能只写占位 blocker

- 场景：P0-3 要求 `btc_paper_validation` 的 start/runtime/evaluation 三件套绑定 run_id、ledger hash、paper OMS lifecycle、audit DAG 和 replay hash。
- 现象：初版 builder 能生成三件套，但 runtime report 明确写着等待 paper OMS lifecycle、audit DAG、replay hashes，导致 evaluation 也被 runtime blocked 连带阻塞；这会让已有 roll runner 链路证据无法进入 promotion artifact。
- 处理方式：`build_btc_paper_validation_artifacts.py` 现在读取 latest roll 的 `forecast_target_order_chain`，从 signal/forecast/target/cost_gate/order_intent/paper_oms_lifecycle artifacts 生成 `btc_paper_validation_audit_dag.json` 和 `btc_paper_validation_replay_report.json`，再把 paper OMS/audit/replay hashes 注入 runtime。仍然保持 `real_order_submitted=false`、`private_endpoint_used=false`、`order_endpoint_used=false`。
- 本次证据：`python scripts/build_btc_paper_validation_artifacts.py` 输出 start/runtime/evaluation 全部 `complete`，`btc_paper_validation_audit_dag.json` 为 `complete`，`btc_paper_validation_replay_report.json` 为 `replay_pass`；综合回归 `python -m pytest tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_gate_dashboard.py tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过，结果 `87 passed`。

## 2026-06-26 Gate dashboard 的剩余 blocker 要反映最新 artifact 状态

- 场景：P0-3 闭环后重新生成 BTC gate dashboard。
- 现象：如果并行生成 dashboard 和读取 dashboard，可能读到上一版旧文件，误以为 paper validation runtime/evaluation 仍 blocked。
- 处理方式：先运行 `python scripts/build_btc_gate_dashboard.py`，再单独读取落盘后的 `artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json`。
- 本次证据：最终 dashboard 状态仍为 `blocked`，但 blockers 已收敛为 `btc_gate_dashboard_artifact_blocked:api_key_permission_audit`；这是真实剩余阻塞，因为当前没有用户提供的脱敏 data/paper/live API key 权限记录。

## 2026-06-26 API key 审计不能为了闭环而制造权限事实

- 场景：P0-4 要求 data/paper/live key 分离、withdraw=false、IP allowlist、mode 匹配，但不能读取或输出任何 secret。
- 现象：当前没有用户提供的脱敏权限记录；如果代码自行生成通过记录，就会把“模板/规范存在”伪装成“交易所权限已审计”。这会错误解除 live blocker。
- 处理方式：`build_btc_api_key_permission_audit.py` 增加 `--write-template`，只生成可填写的脱敏权限事实模板；loader 读取记录时会扫描不属于允许 schema 的 secret-like 字段，以及 `raw_metadata` 内的 secret/passphrase/token/signature/auth 字段，命中后输出 blocked artifact，不回显敏感值。
- 本次证据：`python scripts/build_btc_api_key_permission_audit.py --write-template artifacts/btc_security/latest/btc_api_key_permission_records.template.json` 可生成模板；未提供 `--records` 时 `btc_api_key_permission_audit.json` 仍保持 `blocked`，blockers 为缺少 data/paper/live 三类脱敏记录；`python -m pytest tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_gate_dashboard.py tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过，结果 `90 passed`。

## 2026-06-26 完成度审计不能用“有测试”替代“有 latest artifact”

- 场景：附件的 completion audit 要求逐项证明 P0/P1/P2 是否完成，不能只说相关 tests 通过。
- 现象：P0-1、P0-2、P1-1、P1-2、P1-3 已有模块和契约测试，但部分项没有落盘的 latest artifact；如果只看测试，会遗漏“验收证据是否可供 gate/dashboard/人工 review 使用”。
- 处理方式：新增 `build_btc_exchange_runtime_contract.py` 生成 simulated contract probe artifact；新增 `build_btc_completion_evidence.py` 生成 liquidation risk、source role、paper OMS session、incident drill 四类 contract proof artifacts；新增 `build_btc_completion_audit.py` 聚合 9 项 P0/P1/P2 要求并输出 `btc_completion_audit.json`。
- 本次证据：`python scripts/build_btc_completion_audit.py` 输出 `summary={total:9, complete:8, blocked:1, missing:0}`，唯一 blocker 为 `P0-4 api_key_permission_audit` 缺脱敏权限记录；`python -m pytest tests/contracts/test_btc_completion_audit.py tests/contracts/test_btc_paper_validation_artifacts.py tests/contracts/test_btc_gate_dashboard.py tests/contracts/test_btc_incident_replay_drill.py tests/contracts/test_btc_incident_artifact.py tests/contracts/test_btc_paper_oms_session_reconciliation.py tests/contracts/test_btc_source_role_report.py tests/contracts/test_btc_exchange_runtime_contract.py tests/contracts/test_btc_liquidation_risk.py tests/contracts/test_btc_api_key_permission_audit.py tests/contracts/test_btc_trend_boundary_report.py tests/contracts/test_btc_trend_raw_forward_observation_roll.py tests/contracts/test_btc_trend_raw_forward_observation_daily.py tests/contracts/test_btc_replay_engine.py tests/contracts/test_btc_audit_dag.py tests/contracts/test_btc_execution_quality.py tests/contracts/test_btc_paper_oms_lifecycle.py tests/contracts/test_btc_artifact_schema.py -q` 通过，结果 `94 passed`。

## 2026-06-29 OKX public REST 超时不等于交易所不可用

- 场景：运行 BTC raw trend daily observe-only pipeline 时，OKX public REST 数据刷新连续超时，capture report 写入 `status=rejected`，错误为 `URLError(TimeoutError(10060, ...))`。
- 现象：本机直连解析 `www.okx.com` 到 `awscn.okpool.top -> 169.254.0.2`，直连 443 失败；同时 Windows WinHTTP 为 direct、HKCU `ProxyEnable=0`，Python `urllib.request.getproxies()` 返回空，说明脚本进程没有自动继承本地代理。`127.0.0.1:12334` 代理端口可连，显式指定该代理访问 OKX public REST 返回 HTTP 200。
- 处理方式：遇到 OKX public REST 超时，先区分“交易所不可用”和“本机 DNS/代理未生效”。需要走本地代理时，在运行 public REST 采集前显式设置：
  ```powershell
  $env:HTTPS_PROXY='http://127.0.0.1:12334'
  $env:HTTP_PROXY='http://127.0.0.1:12334'
  ```
  或后续给 public collector 增加显式代理配置入口；不能为了绕过网络问题放松 `public_rest_only`、`private_endpoint_used=false`、`order_endpoint_used=false`、`real_order_submitted=false` 这些安全边界。
- 本次证据：使用上述临时代理环境重跑 `python scripts\run_btc_trend_raw_forward_observation_daily.py --repo-root . --execute-network --request-retry-count 2 --request-retry-backoff-seconds 2 --json` 后，daily report 变为 `status=PASS`，`generated_at=2026-06-29T03:13:39Z`，`daily_rows=1826`，`sample_end=2026-06-29T00:00:00Z`，`observation_days=5`，且 guardrails 仍为 `simulated_only=true`、`private_endpoint_used=false`、`order_endpoint_used=false`、`real_order_submitted=false`。

## 2026-06-29 Gate dashboard complete 不能等于关键门禁全覆盖

- 场景：P1 要求 BTC gate dashboard 汇总 current status、paper validation、daily observation、cost model、funding ledger、live readiness、API key audit、exchange runtime，作为单一事实源。
- 现象：旧 dashboard 只聚合了部分 artifact；即使 `status=complete`，也可能缺少 daily observation、cost model、funding ledger、live readiness 等关键门禁。另外，`btc_funding_ledger_report.json` 没有顶层 `status` 字段，直接摘要会让 dashboard 中 funding ledger 状态显示为空。
- 处理方式：dashboard 的 `complete` 只表示“单一事实源构建完整”，不能表示 live ready；新增 `coverage`、`sources`、统一 artifact 摘要、live readiness blocker 展示和 unsafe flag fail-closed。对没有顶层 status 的 funding ledger，用已对账字段保守显示为 `funding_ledger_reconciled`，不伪造成 `pass`。
- 本次证据：`python scripts\build_btc_gate_dashboard.py` 输出 `status=complete` 且 coverage 覆盖 `daily_observation/cost_model/funding_ledger/live_readiness/api_key_permission_audit/exchange_runtime`；`live_state.live_order_allowed=false`，`live_state.live_readiness_status=live_readiness_blocked`，仍显示前向观察 `5/30` 等 live blocker。

## 2026-06-29 TimesFM 运行超时不一定是代理问题

- 场景：运行 BTC 1H TimesFM 离线 smoke forecast 或 `compare_btc_timesfm_vs_trend_baseline.py` 做样本外诊断时，命令可能因为首次导入 `torch/timesfm`、加载 checkpoint 或多决策点逐次预测而超过交互式命令等待时间。
- 现象：这种超时要先和 OKX public REST 的代理/DNS 超时分开判断。OKX 超时是外部 public REST 访问问题；TimesFM 离线 smoke/对比主要读本地 `data/market_data.sqlite` 和模型 checkpoint。若 checkpoint 未缓存，下载阶段才可能受代理影响；若 artifact 已完整落盘，说明模型链路并未被代理问题阻断。
- 处理方式：不要因为一次终端等待超时就判定 TimesFM 不可用或代理坏了。先检查进程是否仍在运行、`artifacts/shared_forecasting/timesfm/` 下的 report 是否生成、report 的 `status` 和 safety flags 是否正常；必要时延长命令等待时间或减少 `--max-decisions` 做 smoke。TimesFM 仍只能写 research artifact，不能写 paper 队列、不能解锁 live、不能触达 OMS/broker。
- 本次证据：`artifacts/shared_forecasting/timesfm/btc_1h_smoke_latest/btc_timesfm_1h_smoke_forecast_report.json` 已生成 `status=PASS_RESEARCH_ONLY_SMOKE`，输入为 720 条 BTCUSDT 1H 记录；`artifacts/shared_forecasting/timesfm/btc_vs_trend_baseline_latest/btc_timesfm_vs_trend_baseline_oos_report.json` 已生成 `status=COMPLETE_RESEARCH_ONLY_DIAGNOSTIC`，`decision_count=24`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`oms_access_allowed=false`、`broker_access_allowed=false`。本次诊断只说明趋势基线 `btc_trend_baseline_momentum_24h_z24` 在小样本里暂时优于 TimesFM zero-shot，不能进入 paper/live。

## 2026-06-29 监控页不能只信旧 data status artifact

- 场景：做 BTC 只读监控页时，需要展示数据新鲜度和 latest closed bar。
- 现象：`artifacts/btc_data_status/latest/btc_data_status_report.json` 的 `coverage.sample_end` 仍停在 `2026-05-12T00:00:00+00:00`，但 `data/market_data.sqlite` 中 BTCUSDT 1H 最新 closed bar 已到 `2026-06-27T08:59:59.999000+00:00`。如果监控页只读旧 data status，会把真实 SQLite 新鲜度误报为过旧。
- 处理方式：`btc_data_status_report` 保留旧 fold/regime lineage 的 `coverage/intervals`，但新增 `current_sqlite_coverage` 直接从当前 `market_klines` 读取各周期最新 closed bar、event/available/ingested/processed 字段和 finalization 状态；监控快照优先读取该字段，只在它缺失或落后时输出 warning。
- 本次证据：刷新 `python scripts\build_btc_data_status_report.py --repo-root .` 后，`current_sqlite_coverage.status=pass`，`coverage.latest_close_time_by_interval.1h=2026-06-27T08:59:59.999000+00:00`，`latest_closed_bar` 同时记录 `event_time/available_time/ingested_at/processed_at`；再运行 `python scripts\build_btc_monitoring_snapshot.py --repo-root .` 后，`artifacts/btc_monitoring/latest/btc_monitoring_snapshot.json` 变为 `warnings=[]`，安全字段仍为 `live_order_allowed=false`、`private_endpoint_used=false`、`order_endpoint_used=false`、`real_order_submitted=false`。

## 2026-06-29 踩坑日志不能靠事后回忆维护

- 场景：BTC 侧连续推进数据状态、监控、TimesFM、gate/dashboard 等任务时，容易把注意力放在代码、artifact 和测试通过上，最后只在 commit message 或聊天里解释问题。
- 现象：虽然近期已有 `TimesFM 运行超时不一定是代理问题`、`监控页不能只信旧 data status artifact` 等条目，但维护节奏不够稳定；如果每次真实踩坑没有随代码和 artifact 同步入日志，后续 agent 或人工复核会从零排查同一个问题。
- 处理方式：以后 BTC 任务收尾固定检查三件事：是否发现了可复用的真实坑；如果是，是否已更新 `docs/btc_development_pitfall_log.md`；如果没有更新，final 回复必须明确说明“本轮没有新增可沉淀踩坑”。涉及 paper/live/gate/数据新鲜度/代理/TimesFM/跨策略归因的问题，默认优先写入该日志。
- 本次证据：`git log --oneline -- docs/btc_development_pitfall_log.md` 显示近期已有 `f333a5b4 Document BTC TimesFM timeout pitfall` 和 `ec87a6c2 Add BTC current SQLite coverage status` 更新该文件，但本轮将“踩坑日志维护本身”补成显式流程约束，避免后续遗漏。

## 2026-06-29 Windows 测试解释器不能默认信 `python`

- 场景：新增 BTC 多策略归因契约测试后，需要运行 `pytest` 验证 no-broker/no-order 边界。
- 现象：当前 PowerShell 中 `python` 指向 `C:\Program Files\LibreOffice\program\python.exe`，会报“指定的登录会话不存在”；Codex bundled Python 和 `.venv-timesfm` 可以编译源码，但没有安装 `pytest`；`py -m pytest` 又落到 Visual Studio 的 Python 3.9，同样没有 pytest。直接用 `uv run` 时默认缓存目录 `C:\Users\...\AppData\Local\uv\cache` 还可能因权限被拒绝。
- 处理方式：在本项目里跑测试时，优先明确解释器和缓存位置。编译可用 Codex bundled Python；需要 pytest/dev 依赖时，用 `uv --cache-dir .tmp\uv-cache run --extra dev ...`，把缓存写到工作区内。不要把 `python -m pytest` 失败直接误判为测试失败。
- 本次证据：`python -m pytest`、bundled Python、`.venv-timesfm`、`py -m pytest` 均无法直接运行 pytest；改用 `uv --cache-dir .tmp\uv-cache run --extra dev python -m pytest tests\contracts\test_btc_multi_strategy_attribution.py tests\contracts\test_no_broker_import_in_evidence_builders.py -q` 后通过，结果 `7 passed`。

## 2026-06-29 多策略归因不能把 internal gate pass 当成 paper 队列许可

- 场景：BTC 多策略归因要同时展示 trend、intraday、GA candidate/研究线，避免一条策略线的收益或 gate 结果污染另一条线。
- 现象：`btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1` 的 `canonical_backtest_report.json` 中 `gate_decision.status=candidate_passed_internal_gate`，但这只说明 intraday 研究线内部候选门槛通过；它不能自动继承趋势前向观察状态，也不能因为 GA/TimesFM 或趋势线证据而写入 paper 队列。
- 处理方式：多策略归因报告必须按 bucket 分开：`trend_forward_observation`、`intraday_event_ledger`、`ga_factor_research` 各自保留 source path、ledger scope、source gate status 和 promotion scope；报告顶层固定 `paper_queue_write_allowed=false`、`paper_candidate_created=false`、`live_unlock_allowed=false`，并显式输出 `cross_strategy_pnl_reuse_allowed=false`、`cross_strategy_gate_inheritance_allowed=false`。
- 本次证据：新增 `scripts\build_btc_multi_strategy_attribution.py` 生成 `artifacts/btc_multi_strategy_attribution/latest/btc_multi_strategy_attribution_report.json`，状态 `complete`，三条 bucket 分离，`contamination_controls.violations=[]`，安全字段仍为 `live_order_allowed=false`、`paper_queue_write_allowed=false`、`oms_access_allowed=false`、`broker_access_allowed=false`。

## 2026-06-29 永续禁用不能只埋在 target/replay 元数据里

- 场景：P0 要求 BTC 永续风险要么有 funding、mark/index、liquidation buffer 证据，要么在 gate 中明确当前策略不使用永续。
- 现象：latest target 和 paper replay 已经分别记录 `perpetual_allowed=false`、`liquidation_risk_required=false`、`perp_risk_decision_status=not_required_spot_or_unlevered_path`，live readiness constitution 也写了 `perpetual_allowed=false`；但这些字段分散在不同 artifact 里，dashboard/gate 使用者仍可能误以为 funding/mark 数据存在就代表永续路径可用。
- 处理方式：新增独立 `btc_perpetual_policy_status` artifact，聚合 latest target、paper replay、live readiness constitution、funding ledger、cost model 和 liquidation contract；只有 target/replay/live 三处一致禁用时，才输出 `perpetual_path_disabled_for_current_strategy`。如果任一策略线打开永续，则必须要求 funding、mark/index、liquidation contract 完整，否则 fail closed。
- 本次证据：`python scripts\build_btc_perpetual_policy_status.py --repo-root .` 生成 `artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_report.json`，状态 `complete`，`current_strategy_uses_perpetual=false`，`gate.perpetual_allowed=false`，`gate.live_unlock_allowed=false`；刷新 `python scripts\build_btc_gate_dashboard.py` 后，dashboard coverage 新增 `perpetual_policy_status=true`，`perpetual_state.current_route=spot_or_unlevered_path_perpetual_disabled`。

## 2026-06-29 真实下单能力不能替代稳定策略

- 场景：BTC 侧仍处于 `paper_observing / simulated paper only`，30 天真实行情前向观察继续累积，但当前还没有证明稳定盈利、成本后有效且样本外稳健的策略。
- 现象：如果把近期最高优先级继续放在打通真实下单、private/order endpoint 或 live adapter 上，会把工程连通性误当成交易能力。即使真实下单链路可用，也不能解决 alpha 不稳定、样本不足、成本后失效、不同策略线互相污染的问题。
- 处理方式：真实下单和 live 解锁继续冻结，只保留 no-broker/no-live/no-private endpoint 的安全边界和必要证据；30 天观察继续 observe-only 跑着。30 天窗口内 BTC 主线改为策略挖掘与研究收敛：扩展历史样本、维护 research registry、比较趋势基线/GA/TimesFM/intraday 候选、做 walk-forward/holdout/成本压力/行情分段，候选最多进入扩展研究短名单，不写 paper 队列。
- 本次证据：当前已有 `artifacts/btc_multi_strategy_attribution/latest/btc_multi_strategy_attribution_report.json` 用于分离 trend、intraday、GA、TimesFM 研究线，且安全字段保持 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`oms_access_allowed=false`、`broker_access_allowed=false`；同时 `artifacts/btc_research_registry/latest` 尚不存在，说明下一步更应该先补 research registry 单一事实源，而不是继续推进真实下单。

## 2026-06-29 BTC research registry 不能只停在老路径和老候选结构

- 场景：BTC 主线从执行链路优先改为策略挖掘优先后，需要一个单一事实源同时登记趋势观察、intraday、GA、TimesFM 等研究线。
- 现象：仓库已有 `artifacts/btc_research_registry/research_registry.json` 老路径，也有较早的 `build_btc_research_registry.py`，但没有 `latest/` 镜像和中文摘要；同时多策略归因报告没有进入 registry。这样人工复核容易只看老候选字段，漏掉 GA/TimesFM/intraday/trend 的当前研究边界。
- 处理方式：保留老路径兼容下游脚本，同时新增 `artifacts/btc_research_registry/latest/research_registry.json` 和 `btc_research_registry_summary_cn.md`；registry 读取 `btc_multi_strategy_attribution`，显式注册四条研究线，并在 schema/test 中固定 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`oms_access_allowed=false`、`broker_access_allowed=false`。
- 本次证据：`python scripts\build_btc_research_registry.py` 现在同时写老路径与 latest；latest 摘要显示 `strategy_mining_and_validation`，研究线包含 `trend_forward_observation`、`intraday_event_ledger`、`ga_factor_research`、`timesfm_auxiliary_forecast`；`python -m pytest tests\contracts\test_btc_research_registry.py tests\research\test_btc_research_registry.py tests\contracts\test_no_broker_import_in_evidence_builders.py -q` 通过，结果 `19 passed`。

## 2026-06-29 OHLCV 扩展不能掩盖 derivatives sentiment 覆盖不足

- 场景：BTC 侧要求把 BTCUSDT 1H OHLCV 扩到至少 90-180 天，并用扩展后的 OHLCV、derivatives sentiment、GA、趋势基线、intraday、TimesFM 生成 research-only 对比报告。
- 现象：`data/market_data.sqlite` 的 BTCUSDT 1H OHLCV 已经扩到 2026-06-29，覆盖约 910 天；但免费 derivatives sentiment 行仍只有 720 小时。尝试用免费公共源抓 4320 小时时，Binance USDM 返回 HTTP 451，OKX Rubik 返回 `50030:Illegal time range`。如果总报告只写“GA 使用 4320 小时 lookback”，会让人误以为 OI/funding/liquidation/long-short ratio 也完成了 180 天覆盖。
- 处理方式：扩展研究报告必须把 OHLCV 覆盖和 derivatives sentiment 覆盖分开写入 `data_context`，并把免费源 180 天抓取失败作为 warning，而不是静默吞掉。GA 可以用 4320 小时 OHLCV 运行，但必须同时披露 derivatives 可见行数、字段非空计数、`available_time <= decision_time` 可见性规则、确认性 holdout、成本压力和行情分段结果。只要 holdout 存活候选为 0，就不能硬挑 GA 候选进短名单。
- 本次证据：`scripts/research/run_btc_ga_factor_mining.py --lookback-hours 4320 --confirmatory-holdout-hours 168 --seed 20260627` 输出 `status=complete`、`candidate_count=10`、`trial_count=3728`，但 `confirmatory_holdout.surviving_candidate_count=0`。新报告 `artifacts/btc_strategy_mining/latest/btc_extended_strategy_mining_comparison_report.json` 输出 `status=complete_research_only`、`warnings=["btc_derivatives_sentiment_free_source_extended_fetch_blocked"]`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；扩展研究短名单只保留现有趋势基线 `btc_trend_baseline_momentum_24h_z24` 和 intraday 研究候选 `4h_it04_atr_channel_binary_78f046fffa`，TimesFM 仅保留为风险辅助诊断，GA 本批候选不入短名单。

## 2026-06-29 Binance/OKX/GitHub 网络失败要区分直连、香港代理和美国代理

- 场景：BTC 数据层接入 Binance Vision、Binance futures REST、OKX public REST、GitHub raw 等公开数据源时，同一个 URL 在不同网络路由下可能表现完全不同。
- 现象：如果只用当前默认代理或只用某一个代理节点测试，容易把“路由问题”误判成“交易所或网站不可用”。用户补充当前可用路由：可以先不用代理走本地国内网络直连；也可以走“飞鸟加速”的香港节点；HIDIIFY 是美国节点。Binance/部分网站在美国节点、香港节点、国内直连下的可达性和地区限制可能不同。
- 处理方式：以后遇到 Binance、OKX、GitHub 或其他公开数据源连接失败时，先做路由矩阵验证并写进 fetch report：`direct_local_cn`、`feiniaojiasu_hk_proxy`、`hidiify_us_proxy`。能直连就优先记录直连结果；需要代理时明确记录代理名称和节点地区。无论换哪条路由，都不能放松 `public_rest_only`、`private_endpoint_used=false`、`order_endpoint_used=false`、`real_order_submitted=false` 这些边界。
- 本次证据：用户明确说明“飞鸟加速”为香港代理节点，HIDIIFY 为美国节点；后续 BTC public data collector 和 derivatives sentiment 扩展任务应把路由选择作为诊断维度，而不是只记录 timeout、HTTP 451 或 403。

## 2026-06-29 Binance Vision derivatives 扩展要把 metrics、funding、liquidation 分开验收

- 场景：BTC derivatives sentiment 要接入 Binance Vision metrics，把 5 分钟数据聚合成 1H，同时用 Binance Vision funding 月文件和 OKX 720h 补尾；liquidation 暂时只能保留 OKX 720h。
- 现象：直连 `direct_local_cn` 能下载一部分 Binance Vision metrics 文件，但在 `BTCUSDT-metrics-2026-03-27.zip` 附近出现 HEAD 超时；改走 HIDIIFY 美国节点 `http://127.0.0.1:12334` 后同一 URL 返回 200。Binance Vision 当前月 `BTCUSDT-fundingRate-2026-06.zip` 返回 404，因此 funding 覆盖要明确披露 Binance 月文件缺口和 OKX tail 补尾，不要伪造成完整月度覆盖。
- 处理方式：fetch report 必须分别输出 metrics 覆盖、funding 覆盖、liquidation policy。metrics 的 5m->1H 聚合要用已完成小时窗口，1H 行的 `event_time` 放在下一小时决策点，`available_time=event_time+5min`，避免把小时内 00:55 的数据泄漏给 00:00 决策。GitHub 日频 liquidation fallback 只能保留为 diagnostic，不进 gate；不能声称完成 1H liquidation 历史覆盖。
- 本次证据：`scripts\fetch_btc_binance_vision_derivatives_sentiment.py --execute-network --lookback-days 180 --network-route-label hidiify_us_proxy` 生成 `row_count=4321`；`open_interest_usd/long_short_ratio/open_interest/top_trader_long_short_ratio/top_trader_long_short_position_ratio/taker_buy_sell_ratio` 均为 4321 条，`funding_rate=4280`，`long_liquidation_usd/short_liquidation_usd=720`。审计报告仍写明 `liquidation_policy.one_hour_history_complete=false`、`github_daily_fallback_diagnostic_only=true`、`gate_eligible=false`。

## 2026-06-29 TimesFM 专用环境不能依赖手工 PYTHONPATH

- 场景：用 `.venv-timesfm` 运行 `scripts\research\compare_btc_timesfm_vs_trend_baseline.py`，做 BTC TimesFM vs 趋势基线 research-only 对比。
- 现象：主 `.venv` 没有 TimesFM 包，`.venv-timesfm` 有 TimesFM 包，但脚本原来没有自动把项目根目录加入 `sys.path`，直接运行会报 `ModuleNotFoundError: No module named 'quant_shared'`。临时设置 `$env:PYTHONPATH=(Get-Location).Path` 可以跑通，但这会让命令依赖人工记忆。
- 处理方式：研究脚本自身应注入 repo root，专用 venv 只负责模型依赖，不负责项目 import 路径。验证 TimesFM 脚本时可先用 `runpy.run_path(..., run_name='__not_main__')` 做导入 smoke，再跑真实对比；真实产物仍只允许 research-only artifact，不写 paper 队列、不解锁 live。
- 本次证据：补 root 注入后，`.venv-timesfm\Scripts\python.exe scripts\research\compare_btc_timesfm_vs_trend_baseline.py --lookback-hours 720 --horizon-hours 24 --holdout-days 180 --stride-hours 24 --max-decisions 24` 成功生成 `COMPLETE_RESEARCH_ONLY_DIAGNOSTIC` 报告。

## 2026-06-29 简单规则优化不能只看一次性打包版

- 场景：BTC 侧要研究 6 类简单趋势规则，并给出原始版、优化版和最终保留结果。
- 现象：如果只把多个优化方法一次性组合成一个“优化版”回测，就无法判断到底是哪个优化组件带来改善，也可能把过拟合、年份集中或局部行情适配隐藏在最终组合里。
- 处理方式：简单规则研究实验必须按家族输出 `original`、单项优化和预声明组合优化，分别记录 `optimization_stage`、`optimization_components`、逐项收益/回撤/PF/walk-forward/成本压力，并生成 `family_stepwise_comparison`。最终只能进入“扩展研究短名单”，不能写 paper 队列、不能解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_simple_trend_rule_lab.py` 生成 `artifacts/btc_simple_trend_rule_lab/latest/btc_simple_trend_rule_lab_report.json`，状态 `complete_research_only`，共 6 个策略家族、25 个候选；仅 `btc_4h_ma_ribbon_vol_filter_b09cd48fa9` 保留为 `retain_extended_research_only`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-29 多周期研究不能直接信旧 4H/1D 物化表

- 场景：BTC 多周期简单规则实验室需要用 1D 判断方向、4H 找入场、1H 做退出或降噪。
- 现象：当前 `market_klines` 里 BTCUSDT 1H 已更新到 2026-06-29，但 4H/1D 物化表仍停在 2026-05-11/12 附近。如果多周期策略直接混读这些周期表，会让不同周期样本窗口不一致，既影响结果，也容易制造隐性前后错位。
- 处理方式：多周期研究默认只读完成的 1H bar，然后在研究脚本内派生 4H/1D；报告必须写明 `derived_timeframes_from_1h=["4h","1d"]`、4H/1D 派生行数、`available_time <= decision_time` 的 derivatives 对齐规则。严格门槛下短名单为 0 时不能硬挑候选，必须保留 `research_only_no_paper_no_live`。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_multi_timeframe_rule_lab.py` 生成 `artifacts/btc_multi_timeframe_rule_lab/latest/btc_multi_timeframe_rule_lab_report.json`，状态 `complete_research_only`，39 个候选、8 个策略家族；普通扩展研究短名单和做空观察名单均为 0，`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-29 GA 规则组件挖掘不能只看训练适应度

- 场景：把 6 类简单规则、8 类多周期规则和做空研究分支拆成 primitive 后，让 GA 只负责组合、筛选和找阈值。
- 现象：GA 在训练段可以组合出看起来有逻辑的 rule genome，但验证段可能收益为负、PF 过薄，且不一定超过手写规则基线。如果只展示 GA top fitness，会把“组件组合成功”误读成“策略发现成功”。
- 处理方式：GA 规则组件挖掘必须固定 primitive 白名单，不允许任意代码执行；训练段只用于进化，验证段、walk-forward、成本压力和手写规则基线比较只做评估。候选只能写 research artifact，不能写 paper 队列，不能解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_ga_rule_component_mining.py` 生成 `artifacts/btc_ga_rule_component_mining/latest/ga_rule_component_mining_report.json`，33 个 primitive 覆盖全部已提规则家族，GA 试验 1152 次、选出 12 个候选；当前候选验证段多为 `reject_non_positive_validation_return` 或 `defer_validation_profit_factor_too_thin`，手写规则基线仍显著更强，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-29 GA 规则组件 v2 不能把候选级完整复核塞进每个 trial

- 场景：GA 规则组件 v2 增加手写规则初始种群、EMA/Donchian/ATR 参数网格、regime router 语法、失败突破退出、冷却期、年度稳定、最近分段和成本压力。
- 现象：如果在训练阶段每个 genome 都完整重跑 2x/5x 成本压力和候选级复核，默认 smoke 档 `64*20=1280` 也会跑到数分钟以上；formal `128*60=7680` 和 extended `256*100=25600` 会进一步放大数据挖掘风险和运行成本。
- 处理方式：默认 CLI 只跑 `--run-profile smoke`；训练 fitness 使用已算收益/费用派生的成本压力代理，并加入年度稳定和最近分段，完整成本压力、walk-forward、手写基线同窗比较只在预筛后的候选复核阶段执行。报告必须记录 `run_profile`、`trial_count`、`rejected_count`、`seeded_genome_count`，仓位缩放只作为诊断输出，不进入主短名单。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_ga_rule_component_mining.py` 输出 `status=complete_research_only`、`primitive_count=70`、`run_profile=smoke`、`trial_count=1280`、`rejected_count=84`、`seeded_genome_count=11`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；当前 GA 第一名验证收益约 `2.05%`，但因年度收益集中被 `defer_year_concentration_review`，手写 ATR 基线仍显著更强，不能写 paper 队列。

## 2026-06-29 ATR 手写基线强不等于最近仍有效

- 场景：进一步复核手写 ATR channel 为什么在简单规则比较中最强，并只围绕 ATR/EMA/退出/冷却期做窄范围 formal GA，而不是扩大到全 primitive 搜索。
- 现象：最强手写 ATR 原始版全样本收益高，但收益高度集中：2024 年收益约 `136.50%`，2025 年约 `-18.64%`，2026 年约 `3.51%`；最大正收益年份占比约 `0.9749`，Top 3 正收益交易占比约 `0.7646`。锁定 holdout 为 2026-02-12 到 2026-06-28 后，手写 ATR 原始版 holdout 收益约 `-0.34%`，validation 收益约 `-18.76%`。这说明它强在历史大趋势段，不代表最近仍稳定。
- 处理方式：ATR 窄 GA 必须先锁定 holdout，再只在 train/validation 上进化和排序；formal 档 `128*60=7680` 只能作为 research-only 证据。若 validation 非正、holdout 非正、年度集中或成本压力不过关，候选不得进入扩展研究短名单，更不能写 paper 队列。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_atr_baseline_narrow_ga.py --run-profile formal` 输出 `status=complete_research_only`、`trial_count=7680`、`rejected_count=20`、`seeded_genome_count=9`、`strongest_atr_baseline=btc_4h_atr_channel_original_02f3dbcde7`；top GA 候选 `btc_atr_narrow_ga_0e169c62efaf` validation 收益约 `-0.88%`、holdout 收益约 `-12.62%`，结论为 `reject_non_positive_validation_return`，短名单数量为 0，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-29 ATR 需要 regime 空仓条件，不能全时段裸跑

- 场景：对最强手写 ATR channel 做行情分段失效分析，把 2024 趋势段、2025 回撤段、2026 最近段拆开，并按 `bull_trend`、`bear_or_drawdown`、`high_volatility_risk`、`sideways_chop` 归因。
- 现象：ATR 原始版全样本仍是 `99.16%` 收益、PF `1.10`，但 2025 回撤段为 `-18.64%`，PF `0.94`，应空仓；按 regime 看，`bear_or_drawdown` 收益约 `-36.38%`、PF `0.59`，`high_volatility_risk` 虽小幅正收益但最大回撤约 `35.32%`，也应空仓。`bull_trend` 收益高但回撤约 `20.51%`，只适合降仓或附加过滤；当前定义下 `sideways_chop` 收益约 `36.96%`、PF `1.46`、回撤约 `6.49%`，反而是最稳的 ATR 触发环境，说明它捕捉的是横盘后上破，而不是任何趋势都追。
- 处理方式：后续不能把 ATR 当全时段 long/flat 策略直接推进。若要继续研究，应做 regime filter 版本：`bear_or_drawdown` 默认空仓，`high_volatility_risk` 默认空仓或极低仓，`bull_trend` 降仓/附加失败突破退出，`sideways_chop` 可作为候选允许区。任何 filter 版本都必须重新做 walk-forward、holdout、成本压力和人工复核，不得继承原 ATR 的历史收益结论。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_atr_regime_failure_analysis.py` 输出 `status=complete_research_only`，`should_be_flat_calendar_segments=["2025_drawdown_segment"]`，`should_be_flat_regimes=["bear_or_drawdown","high_volatility_risk"]`，`effective_regimes=["sideways_chop"]`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-29 BTC 多周期趋势不能只停在 4H/1D

- 场景：用户指出 BTC 的主要趋势更可能体现在日线、周线、月线，当前多周期规则过度集中在 1H/4H/1D，容易把短周期噪声当成主趋势。
- 现象：`btc_multi_timeframe_rule_lab` 旧版只从完成 1H 派生 4H/1D，并在报告里记录 `derived_timeframes_from_1h=["4h","1d"]`；这足以做中短周期规则比较，但不足以回答“周线/月线大趋势是否支持入场”。
- 处理方式：多周期规则实验室必须把 1W/1M 也从完成 1H bar 派生，丢弃未完成的当前周/月；新增高周期确认变体时保留旧原始版并排比较，避免把原基线改没。周线/月线只能作为 research-only 过滤和诊断，不能直接写 paper 队列或解锁 live。
- 本次证据：`multi_timeframe_rule_lab.py` 新增 `aggregate_ohlcv_calendar(..., timeframe="1w"/"1mo")`、`higher_timeframe_context` 和高周期确认候选；合约测试要求 `derived_timeframes_from_1h=["4h","1d","1w","1mo"]`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false` 边界保持不变。

## 2026-06-29 高周期不能简单硬共振，分层控制更适合研究

- 场景：三周期硬确认要求日线、周线、月线全部看多才交易，实测会过度变慢；用户要求改成日线决定是否允许交易、周线决定仓位大小、月线只做大风险开关。
- 现象：硬确认版本多数收益下降，说明 BTC 趋势早期和横盘突破容易被周/月线滞后过滤掉。分层版本改善了 `mtf_trend_original`：收益从约 `40.68%` 提高到 `50.39%`，PF 从 `1.08` 提高到 `1.10`，平均暴露略降；但最近分段仍失败、年度集中问题仍在。海龟和投票分层版主要降低暴露或回撤，没有形成稳定短名单；regime router 分层版仍为负收益。
- 处理方式：高周期研究应避免把周线/月线直接当开仓硬条件。更合理的默认实验形态是：日线作为交易许可；周线作为 `1.0 / 0.5 / 0.25` 仓位缩放；月线明显转熊时切到 `0`。即便某个分层变体收益改善，也只能进入 research-only 对比，不得直接进入 paper candidate。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_multi_timeframe_rule_lab.py` 输出 `candidate_count=47`、普通扩展短名单 `0`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；`tests/contracts/test_btc_multi_timeframe_rule_lab.py` 覆盖 tiered 候选存在、周/月线自动派生和 no-broker 边界。

## 2026-06-29 Trend tiered 窄参数复核不能解决最近分段失败

- 场景：围绕上轮最有改善的 `mtf_trend_tiered_htf_control` 做下一轮窄搜索，只试周线仓位比例和月线风险开关快慢，不扩大到全策略/全 primitive 空间。
- 现象：新增 6 个 trend tiered 变体后，最好的是 `mtf_trend_tiered_monthly_fast_switch`，收益约 `50.41%`、PF `1.099`、回撤约 `-26.67%`，仅比默认 tiered 的 `50.39%` 略高；周线 `1.0/0.6/0.2` 和更宽松 `1.0/0.75/0.5` 都弱于默认，说明当前改善主要不是来自周线比例微调。所有 trend tiered 仍然 `latest_segment_passed=false`、`defer_year_concentration_review`。
- 处理方式：不要继续在同一窗口上细磨周线比例或月线均线参数；下一步若继续，应转向最近分段失败归因、失败突破退出、冷却期或 regime 空仓，而不是把窄参数调参当成可推进 paper 的证据。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_multi_timeframe_rule_lab.py` 输出 `candidate_count=53`、普通扩展短名单 `0`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；合约测试仍为 `10 passed`。

## 2026-06-30 BTC 弱势行情需要单独做空研究，不能混入现货 long/flat

- 场景：用户指出近期 BTC 行情偏弱，现有策略多数是现货 long/flat，行情不好时天然失效；需要研究做空或至少更强的空仓防守。
- 现象：新增 `btc_weak_regime_short_lab` 后，真实数据里最强候选是 `donchian_breakdown_short_flat_original`，总收益约 `36.45%`、最大回撤约 `-15.86%`、PF `1.12`、最近 180 天通过；但收益几乎集中在 2026 最近弱势段，2024/2025 分段不稳定，walk-forward pass rate 只有 `0.25`。这说明它是当前弱势适配线索，不是稳定做空策略。
- 处理方式：做空/long-short 必须独立留在 `short_research` 分桶，默认假设 USDT 永续模拟研究，并显式计入 taker+slippage、funding 近似、做空挤压和强平缓冲诊断。任何候选不得写 paper 队列，不得解锁 live；后续若继续，应优先复核 Donchian breakdown 的早期年份失效和 walk-forward 不稳定。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_weak_regime_short_lab.py` 输出 `candidate_count=7`、做空观察名单 `0`、防守观察名单 `0`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；`tests/contracts/test_btc_weak_regime_short_lab.py` 和 no-broker 合约测试通过。

## 2026-06-30 BTC long/short 趋势跟踪不能等同于“行情差就做空”

- 场景：用户要求新增独立 `btc_long_short_trend_following_lab`，用同一套趋势规则对称处理多空：Donchian 上破做多、下破做空，EMA ribbon 多头排列做多、空头排列做空，ATR trailing stop 双向退出，震荡区间空仓。
- 现象：如果把 long/short 直接并入现货 long/flat 或弱势 short/flat 研究线，容易把“最近跌所以做空”的行情适配误读成趋势跟踪能力；也会让 funding、OI、多空比从风险过滤器滑成事实上的开仓信号。
- 处理方式：long/short 必须作为独立 research-only 实验室输出，和同窗口 long/flat、short/flat 参考基线比较；只有日线趋势确认下跌且 4H 价格趋势确认时才允许做空，没有趋势默认空仓。funding/OI/long-short ratio 只做风险过滤和诊断，不能独立生成方向信号；所有候选不得写 paper 队列、不得解锁 live。
- 本次证据：新增 `quant_crypto/research/long_short_trend_following_lab.py`、`scripts/research/run_btc_long_short_trend_following_lab.py` 和 `tests/contracts/test_btc_long_short_trend_following_lab.py`；报告需要输出 JSON、CSV、中文摘要、同窗口参考对比、成本压力、walk-forward、年度/最近分段、行情分段和 adverse move 诊断。

## 2026-06-30 Long/short formal 扩展要记录搜索空间，避免把窄网格误读成自由挖参

- 场景：在 `btc_long_short_trend_following_lab` 中按用户指定做窄范围 formal 扩展：Donchian 窗口 `72/96/120/180/240`，日线趋势 `EMA20/80、34/144、50/200`，ATR 倍数 `2.0/2.5/3.0/3.5`，冷却期 `0/6/12` 根 4H，失败突破退出开/关，风险过滤为无、funding、funding+OI、funding+OI+多空比。
- 现象：该组合会生成 `5*3*4*3*2*4=1440` 个 formal Donchian 候选，加上原有 12 个 smoke/参考候选后总计 1452 个；如果不在报告里写清 `run_profile` 和 `formal_grid`，后续复核者会不知道这是预声明窄网格，还是随意参数挖掘。
- 处理方式：CLI 默认 `--run-profile formal_narrow`，合约测试使用 `smoke` 以保持快速；报告必须写入 `run_profile`、完整 `formal_grid`、候选数、同窗口 reference 对比和 research-only gate。formal 真实数据运行约数分钟，不能在每个候选中重复重算信号；成本压力应复用已算好的 exposure/funding/cost。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_long_short_trend_following_lab.py` 输出 `candidate_count=1452`、`long_short_candidate_count=1448`、`same_window_reference_count=4`、`long_short_watchlist_count=5`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；当前最强观察候选集中在 `Donchian 180/240 + EMA50/200 + ATR2.0 + 无风险过滤`，说明下一轮必须做 holdout/分段复核，不能直接进 paper。

## 2026-06-30 Top5 holdout 通过不等于可以进 paper，收益集中度仍是 blocker

- 场景：对 long/short formal Top 5 做确认性 holdout、行情分段归因、收益集中度和失败场景复核。
- 现象：Top 5 的 post-selection holdout 全部为正：窗口 240 的候选 holdout 收益约 `39.71%`、回撤约 `-10.04%`、PF 约 `1.89`；窗口 180 的候选 holdout 收益约 `32.45%`、回撤约 `-12.80%`、PF 约 `1.66`。年度和 regime 归因没有出现负收益 regime，但 Top3 正收益交易贡献占比约 `0.66-0.68`，说明收益仍偏集中。
- 处理方式：复核报告必须明确 `clean_pre_selection_holdout=false`，因为 Top 5 已经来自完整历史 formal 报告；当前 holdout 只能作为 post-selection 压力确认。只要收益集中度仍高，结论应为 `defer_concentration_review`，不能写 paper 队列，不能解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_long_short_top5_review.py` 输出 `top_n_reviewed=5`、`holdout_pass_count=5`、`high_concentration_count=5`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；产物为 `artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json`。

## 2026-06-30 趋势跟踪不能把收益集中度当成单独硬 blocker

- 场景：用户指出趋势跟踪本来就是低胜率、高盈亏比，收益集中在少数大趋势交易是正常特征；需要给 Top5 复核包补一个趋势跟踪专用评价口径。
- 现象：同一批 Top5 的 Top3 正收益交易贡献占比仍约 `0.66-0.68`，但第一名最大盈利交易持续 `111` 根 4H bar，单根最大正收益只占该笔正收益约 `0.0903`，趋势 regime 占比约 `0.6306`；最差亏损约 `-3.88%`，平均亏损约 `-1.92%`；`sideways_chop` 阶段收益约 `0.19%`，平均暴露约 `0.0015`，更符合“无趋势少亏或空仓”而不是异常单点拉动。
- 处理方式：收益集中度对趋势策略不再单独判死刑，但必须同时检查：大盈利是否来自多根 K 线趋势突破、亏损交易是否小亏可控、趋势缺失阶段是否少亏或空仓、不同年份是否都有趋势机会、未来 30/60 天是否继续符合“少亏、等待大趋势”的形态。结论应改为 `trend_following_concentration_expected_requires_forward_confirmation`，仍然不能写 paper 队列，不能解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_long_short_top5_review.py` 输出 `top_n_reviewed=5`、`trend_profile_pass_count=5`、`large_winner_trend_pass_count=5`、`loss_control_pass_count=5`、`trendless_phase_pass_count=5`、`yearly_opportunity_pass_count=5`、`forward_observation_pending_count=5`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`；产物为 `artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json` 和中文摘要。

## 2026-06-30 BTC 短周期刷新不能只依赖 Binance REST，也不能误读 Vision 时间戳

- 场景：小资金高收益研究线需要把 `market_klines` 中 `binance_spot/BTCUSDT` 的 `1m` 补到与最新完成 `1h` 同期，并由完整 `1m` 重采样生成 `5m/15m`。
- 现象：`https://api.binance.com/api/v3/klines` 在当前环境返回 `HTTP 451`；改走 Binance Vision daily ZIP 后，CSV 时间戳是微秒级，例如 `1778544000000000`，如果按毫秒解析会触发 `OSError: [Errno 22] Invalid argument` 或时间越界。
- 处理方式：短周期刷新器应先尝试 REST，失败后自动 fallback 到 `data.binance.vision` daily ZIP；解析 Binance Vision 时必须把微秒/纳秒时间戳归一到毫秒；`5m/15m` 只允许由完整 `1m` 聚合，且网络补齐后只增量重采样受影响窗口，避免全量重写 5m/15m 导致长时间卡住。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_short_interval_data_refresh.py --execute-network --sleep-seconds 0.02` 输出 `status=complete_research_only`，`rows_written=69107`，`row_sources=["binance_vision_spot_daily_zip"]`；覆盖到 `2026-06-29T00:59:59.999000+00:00`，`1m/5m/15m/1h` 均为 `gap_count=0`、`duplicate_open_time_count=0`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-30 小资金高收益不是放宽 paper/live 门槛的理由

- 场景：在 long/short Donchian Top5 基础上研究小资金高收益版本，测试 `1x/1.5x/2x/3x`、波动目标仓位、回撤控制、强平缓冲、连亏降仓、趋势缺失空仓和 15m intraday 候选。
- 现象：真实数据 smoke 生成 41 个候选，最佳为 `hy_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_vol_target_120`，年化约 `57.188766%`、最大回撤约 `25.208402%`、PF 约 `1.353536`、无模拟强平；但预声明高收益研究短名单门槛是年化 `>=60%`，所以不能因为“接近 60%”就人工放宽。
- 处理方式：高收益线只能输出 `high_yield_research_watchlist`，且最低线必须照报告执行：年化、最大回撤、PF、2x 成本压力、模拟强平、30/60 天观察状态同时看；没有达到预声明门槛就不进入短名单，更不能写 paper 队列或解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_small_account_high_yield_lab.py` 输出 `status=complete_research_only`、`candidate_count=41`、`watchlist_count=0`、`best_annual_return_pct=57.188766`，安全文件 `artifacts/btc_small_account_high_yield_lab/latest/paper_live_safety_status.json` 记录 `paper_queue_write_allowed=false`、`paper_candidate_created=false`、`live_unlock_allowed=false`、`oms_access_allowed=false`、`broker_access_allowed=false`。

## 2026-06-30 Near-miss v2 通过研究门槛不等于 paper/live 许可

- 场景：围绕当前最佳高收益候选 `hy_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_vol_target_120` 做 Top10 near-miss 复核，并只在 Donchian 240 + EMA50/200 + cooldown 12 + volatility target 邻域里跑 270 个 v2 窄网格候选。
- 现象：v2 最佳候选 `hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff` 的研究指标达到年化约 `66.42%`、最大回撤约 `22.07%`、PF 约 `1.44`，并产生 30 个 `high_yield_near_miss_research_watchlist` 候选；但这是 post-selection 窄网格研究结果，不是 clean pre-selection holdout，也不是实盘证据。Top1 near-miss 到 60% 的差距只有约 `2.81%`，成本和连亏降仓的反事实拖累都大于这个差距，说明归因字段只能解释敏感点，不能作为关闭成本或风控的理由。
- 处理方式：near-miss 报告必须固定 `paper_queue_write_allowed=false`、`paper_candidate_created=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`、`oms_access_allowed=false`。v2 候选即使超过年化 60%，也只能进入 `high_yield_near_miss_research_watchlist`，不能写 paper 队列；`15m intraday` 诊断若继续明显弱于 4H Donchian overlay，也不能混入 v2 网格或被解释成新增收益来源。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_small_account_high_yield_near_miss_review.py` 输出 `status=complete_research_only`、`top10_review_count=10`、`v2_candidate_count=270`、`v2_watchlist_count=30`、`best_v2_annual_return_pct=66.422834`，安全文件 `artifacts/btc_small_account_high_yield_near_miss/latest/paper_live_safety_status.json` 记录 paper/live/broker/OMS/order 全部禁止。

## 2026-06-30 高收益 v2 确认包不是晋级包，亏损控制和永续证据仍是 blocker

- 场景：冻结当前 v2 最佳候选 `hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff`，按 5 步做确认包：确认性 holdout、30/60 天观察计划、稳健 Top5 对比、杠杆/强平/资金费率复核。
- 现象：真实确认包显示全样本年化约 `66.42%`、最大回撤约 `22.07%`、PF 约 `1.44`，post-selection holdout 收益约 `92.65%` 且通过；但趋势跟踪专用口径没有全过，原因是平均亏损约 `-4.31%`，超过“小亏可控”口径的 `-3%` 阈值。5x 固定成本压力虽然仍为正，但年化被压到约 `4.86%`，说明高收益特征对成本假设敏感。
- 处理方式：确认包只能输出 `research_only_forward_observation_required_no_paper_no_live`。30/60 天观察计划只是未来数据到来后的记录模板，不是当前证据；spot OHLCV proxy 下的强平缓冲通过也不能替代永续 mark/index price、真实 funding settlement、深度/滑点和交易所 outage 证据。亏损控制未过或永续证据缺失时，不得写 paper 队列、不得生成策略骨架、不得解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_high_yield_v2_confirmation.py` 输出 `status=complete_research_only`、`holdout_passed=true`、`costs_2x_survives=true`、`costs_5x_survives=true`、`forward_observation_rows=60`，安全文件 `artifacts/btc_high_yield_v2_confirmation/latest/paper_live_safety_status.json` 记录 `forward_observation_required=true`、`perpetual_execution_evidence_required=true`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-30 v3 亏损改善不能覆盖永续执行证据缺口

- 场景：按用户要求同时执行三步：把高收益 v2 冻结候选做成日度观察器，围绕退出/降仓做 v3 亏损控制小修，并补永续执行证据包。
- 现象：v3 窄网格只改 `fast_stop`、冷却期、连亏降仓和失败突破退出，不改 Donchian 240 + EMA50/200 入场结构；真实数据里最佳 v3 候选 `hy_v3_lossctl_fs6p0_scd12_lt3_db12_fail1` 年化约 `68.34%`、最大回撤约 `21.67%`、PF 约 `1.51`，平均亏损改善到约 `-2.82%`，通过“小亏可控”口径。但永续证据包仍缺 `mark/index price path`、深度/滑点、交易所 outage 模型和精确强平公式；当前最新观察记录还是空仓，不能说明未来 30/60 天已经验证。
- 处理方式：v3 保留候选只能进入 `loss_control_v3_research_watchlist`，不能替代未来观察；日度观察器只允许幂等写 `data/forward_observation/btc_high_yield_v2_frozen/observations.jsonl`，不能写 paper 队列。永续证据缺口未补齐前，即便 v3 指标优于冻结 v2，也不得生成策略骨架、不得 paper、不得 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_high_yield_v2_followup.py` 输出 `status=complete_research_only`、`new_observation_written=true`、`loss_v3_candidate_count=48`、`loss_v3_retained_count=5`、`perp_evidence_decision=perp_execution_evidence_incomplete_no_paper_no_live`，安全字段继续保持 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-06-30 分仓滚仓高收益结果不能当成策略稳定性证据

- 场景：用户提到币圈“分 10 个账户隔离资金、每个账户开高杠杆抓趋势、翻倍后继续拆仓滚仓”的做法；本轮新增 `btc_bankroll_rollover_lab`，用 10 个隔离 sleeve、`3x/5x/10x/20x/50x/100x` 杠杆和 `no_rollover/extract_principal/split_2/split_5` 滚仓规则做 research-only 压力实验。
- 现象：真实数据 smoke 中最佳场景为 `br_split_2_on_double_lev10p0`，最终权益约 `377,606,940.06`、总收益约 `1,510,327.76%`、最大回撤约 `49.50%`、模拟强平次数为 `0`；但所有 `100x` 场景均触发 `10` 个初始 sleeve 全部强平归零，强平阈值只有约 `20 bps`。这说明滚仓是资金管理凸性和历史路径依赖的放大器，不是新的 alpha 证据。
- 处理方式：滚仓实验室必须固定为 `research_only`，只能输出报告、CSV、事件样本、中文摘要和 safety status；不得写 paper 队列、不得生成策略骨架、不得解锁 live。`100x` 只能作为极端压力场景；即使 `10x` 历史路径表现极高，也必须先补齐真实永续 `mark/index price`、交易所强平公式、资金费结算、深度/滑点、断连/outage 和前向观察证据。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_bankroll_rollover_lab.py` 输出 `status=complete_research_only`、`candidate_count=24`、`best_scenario_id=br_split_2_on_double_lev10p0`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；`artifacts/btc_bankroll_rollover_lab/latest/paper_live_safety_status.json` 记录 `broker_access_allowed=false`、`oms_access_allowed=false`、`paper_candidate_created=false`、`strategy_skeleton_generated=false`。

## 2026-06-30 分仓滚仓复核要先证明不是起点路径依赖

- 场景：在 `10x split_2_on_double` 历史收益极高后，新增 `btc_bankroll_rollover_review` 复核包，拆解收益来源，并测试更严强平、funding/fee/slippage 压力、年度分段和 30 天 rolling start。
- 现象：真实复核显示 `10x split_2_on_double` 相对 `10x no_rollover` 的最终权益增量为 `0.0`，说明收益主要来自 `10x` 杠杆复利，而不是拆仓本身；`1x no_rollover` 总收益约 `202.49%`，`10x no_rollover/split_2` 总收益约 `1,510,327.76%`。强平敏感性 540 行中，`split_2` 在插针压力下有 134 行出现强平/全灭；rolling start 共 29 个起点，最大最终权益约 `377,606,940.06`，中位最终权益约 `6,641,357.09`，最大/中位比约 `56.86`。
- 处理方式：只要 rolling start 路径依赖显著，结论必须降级为 `path_dependent_not_forward_observation_ready`；不能因为全样本收益炸裂就进入 30/60 天观察，更不能 paper/live。下一步若继续，应默认转向 `3x/5x + 提本金滚仓` 的保守复核，而不是继续扩大杠杆。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_bankroll_rollover_review.py` 输出 `status=complete_research_only`、`decision=path_dependent_not_forward_observation_ready`、`liquidation_sensitivity_row_count=540`、`cost_stress_row_count=54`、`rolling_start_count=29`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；产物为 `artifacts/btc_bankroll_rollover_review/latest/`。

## 2026-06-30 分仓防插针不能只看最终收益

- 场景：用户指出拆仓的主要目的不是提高收益，而是防止插针；本轮新增 `btc_bankroll_spike_defense_review`，逐个 sleeve 模拟 10 个账户、错峰入场、`3x/5x/10x` 混合杠杆、翻倍提本金、最大同时暴露限制，并用一次性 `-3%/-5%/-8%/-10%` 插针后的最差剩余资金比例做主评价。
- 现象：基线 `all_10x + all_at_once + max10 + none` 在 `-10%` 插针下最差剩余资金为 `0.0%`，说明 10x 同时满仓会被一次插针打穿。全局最佳是 `all_5x + all_at_once + max10 + none`，`-10%` 插针最差剩余资金为 `100.0%`，说明防插针第一层来自降杠杆；如果坚持 10x，最佳是 `all_10x + stagger_3bar + max2 + extract_principal_on_double`，`-10%` 插针最差剩余资金约 `69.95%`，总收益约 `576.41%`，明显牺牲收益换存活。
- 处理方式：后续讨论分仓滚仓必须把“收益增强”和“插针存活”分开。防插针线的主指标是 `min_remaining_capital_pct_after_10pct_spike`、最大单次插针损失 sleeve 数、已提取 reserve cash、最大同时暴露，而不是最终权益。任何结果仍然只保留 research-only，不得写 paper 队列、不得解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_bankroll_spike_defense_review.py` 输出 `status=complete_research_only`、`scenario_count=128`、`baseline_min_remaining_capital_pct_after_10pct_spike=0.0`、`best_min_remaining_capital_pct_after_10pct_spike=100.0`、`research_watchlist_count=90`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；产物为 `artifacts/btc_bankroll_spike_defense_review/latest/`。

## 2026-06-30 分层 sleeve 调度器会牺牲收益换存活

- 场景：为解决所有 sleeve 同方向、同杠杆、同 K 线同时承担风险的问题，新增 `btc_bankroll_layered_sleeve_scheduler`，把 10 个 sleeve 拆成 `core/reserve/attack` 三层：core 先入场，reserve 只在趋势持续且上一根已完成 4H 出现回撤或不利波动后入场，10x attack 最后入场并受最大同时暴露限制。
- 现象：真实复核 146 个场景中，`10x` 同时满仓基线在 `-10%` 插针下仍为 `0.0%` 剩余资金，总收益约 `1,510,327.76%`；`5x` 同时满仓基线 `-10%` 插针剩余 `100.0%`，总收益约 `19,064.85%`。最佳保命分层方案 `layer_core3x4_reserve3x4_attack10x2_max3_extract` 的 `-10%` 插针剩余 `100.0%`，但总收益只有约 `153.26%`；真正发生过 10x attack 暴露的最佳方案 `layer_core5x6_reserve5x2_attack10x2_max7_extract` 的 `-10%` 插针剩余约 `88.21%`，总收益约 `689.90%`。
- 处理方式：分层调度器证明了同步风险可以通过角色分层、延迟入场、限制 10x 暴露和提本金缓解，但收益会明显下降。后续若继续，应围绕“实际使用 attack 的分层方案”细化，而不是用没有实际 attack 暴露的保守方案冒充 10x 进攻模型；所有结果仍然 research-only。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_bankroll_layered_sleeve_scheduler_review.py` 输出 `status=complete_research_only`、`scenario_count=146`、`best_layered_scenario_id=layer_core3x4_reserve3x4_attack10x2_max3_extract`、`best_layered_total_return_pct=153.264319`、`research_watchlist_count=118`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；产物为 `artifacts/btc_bankroll_layered_sleeve_scheduler/latest/`。

## 2026-06-30 10x attack 小资金线要同时区分“真实暴露”和“插针后剩余本金”

- 场景：用户明确希望围绕“实际使用过 10x attack、但 -10% 插针后还能剩 80%+”的分仓方案继续细化，并说明这是小资金研究线，即使全部亏完也可以接受。
- 现象：上一轮分层调度器里最保命的方案虽然 -10% 插针后剩余 100%，但实际 `max_attack_exposed_sleeves_observed=0`，不能冒充“10x attack 进攻模型”；真正有过 10x attack 暴露的上一轮最佳是 `layer_core5x6_reserve5x2_attack10x2_max7_extract`，-10% 插针后剩余约 `88.21%`，总收益约 `689.90%`。
- 处理方式：新增 `btc_bankroll_attack_refinement` 复核包，只围绕 5x core、3x/5x reserve、10x attack、不同 attack 错峰、`max_total_exposed=7/8/10`、`max_attack_exposed=1/2/3` 和是否提本金做窄网格；watchlist 必须同时满足真实 10x attack 暴露、-10% 插针后剩余本金 `>=80%`、总收益为正、无普通强平。用户的小资金高风险偏好只改变排序，不改变 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_bankroll_attack_refinement_review.py` 输出 `status=complete_research_only`、`scenario_count=432`、`actual_attack_scenario_count=432`、`watchlist_count=156`。按收益排序最佳观察为 `attack_ref_core5x6_reserve5x2_attack10x2_max8_atkcap1_delaylate_noextract`，总收益约 `9286.14%`、年化约 `518.45%`、最大回撤约 `26.77%`、-10% 插针后最差剩余本金约 `84.80%`，但仍然只能进入 research-only 观察，不进 paper/live。

## 2026-06-30 10x attack Top 方案通过观察门槛不等于能承受极端插针

- 场景：围绕 `attack_ref_core5x6_reserve5x2_attack10x2_max8_atkcap1_delaylate_noextract` 做 Top 方案确认复核，重点检查真实强平假设、mark/index price 不利偏移、额外插针、funding/成本压力和 rolling start 起点敏感性，再决定是否进入 30/60 天 research-only forward observation。
- 现象：基准口径仍显示总收益约 `9286.14%`、年化约 `518.45%`、最大回撤约 `26.77%`、-10% 插针后最差剩余本金约 `84.80%`，无普通强平；216 行强平/mark/index 插针压力中有 205 行仍满足 80%+ 剩余本金，标准 10% 压力 12/12 通过，funding 5x + 成本压力下最差总收益仍约 `8016.46%`。rolling start 共有 28 个起点，全部正收益、全部 80%+ 存活，最大/中位正收益比约 `8.54`，路径依赖低于本轮观察门槛。
- 处理方式：允许结论降到且仅降到 `eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live`，也就是可以进入 30/60 天观察模板；不能写 paper 队列，不能生成策略骨架，不能解锁 live。极端组合压力仍必须单独提示：当维护保证金、强平费、mark 不利偏移和额外插针全部取最严时，最差剩余本金只有约 `1.08%`，说明该方案不是“永远防插针”，只是通过了预声明的观察门槛。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_bankroll_attack_top_confirmation_review.py` 输出 `status=complete_research_only`、`decision=eligible_for_30_60_day_forward_observation_research_only_no_paper_no_live`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`，产物位于 `artifacts/btc_bankroll_attack_top_confirmation/latest/`。

## 2026-06-30 10x attack forward observation 只能记录理论状态，不能变成纸盘

- 场景：Top 方案通过确认复核后，需要一个 30/60 天 observe-only 观察器，每天记录信号、理论 sleeve 暴露、插针后剩余本金、funding/cost 压力和是否触发降级。
- 现象：如果观察器沿用 paper/OMS 语义，容易把“观察记录”误读为“纸盘运行”或“订单意图”。这会绕过 BTC paper gate，也会让 mark/index、funding 近似和极端插针风险被过早实盘化。
- 处理方式：新增 `btc_bankroll_attack_forward_observer`，默认只追加 `data/forward_observation/btc_bankroll_attack_top/observations.jsonl`；同一个最新完成 4H 决策点幂等不重复写。观察行只包含 `daily_signal`、`theoretical_sleeve_exposure`、`spike_remaining_capital`、`funding_cost_pressure`、`downgrade_triggered/downgrade_reasons`，并固定 `paper_queue_write_allowed=false`、`paper_candidate_created=false`、`live_unlock_allowed=false`、`strategy_skeleton_generated=false`。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_bankroll_attack_forward_observer.py` 输出 `status=complete_research_only`、`decision=attack_forward_observer_active_under_30d_no_paper_no_live`、最新决策时间 `2026-06-28T23:59:59.999000+00:00`、当前信号 `flat`、理论暴露 sleeve 数 `0`、-10% 插针后剩余本金 `100.0%`、`downgrade_triggered=false`，产物位于 `artifacts/btc_bankroll_attack_forward_observer/latest/`。
## 2026-06-30 滚仓检索遗漏来自把资金管理误当成非策略

- 场景：复盘 BTC 策略时，用户指出“分仓滚仓/防插针”这类币圈资金管理做法在上一次外部检索中没有被检索到。
- 现象：如果只按 `alpha / signal / trend following / ML / GA` 关键词检索，会漏掉币圈常见的 `滚仓`、`浮盈加仓`、`金字塔加仓`、`分账户隔离`、`逐仓防插针`。这些不一定是新方向信号，但会显著改变小资金高收益线的收益分布、强平风险和路径依赖。
- 处理方式：把滚仓从“拆仓复利收益增强”重新定义为“资金管理叠加层”，新增 `BTC Pyramiding Sleeve Lab v1`：底层方向仍来自已有 Donchian 线，只研究 ATR 浮盈阶梯加仓、分 sleeve、错峰、提本金、10x attack 子榜和插针后剩余本金。报告必须同时输出综合榜和“实际使用 10x attack”的子榜，避免低杠杆保守方案掩盖激进线。
- 本次证据：新增 `quant_crypto/research/pyramiding_sleeve_lab.py` 和 `scripts/research/run_btc_pyramiding_sleeve_lab.py`；真实 smoke 输出 `status=complete_research_only`、`scenario_count=649`、`watchlist_count=553`、综合最佳 `pyr_step0p75_core5x6_reserve5x4_attack10x0_max7_noextract`，实际 10x attack 最佳 `pyr_step0p75_core5x6_reserve5x2_attack10x2_max7_extract`，年化约 `130.51%`，最大回撤约 `6.09%`，-10% 插针后剩余本金约 `89.63%`。安全边界仍为 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`、`oms_access_allowed=false`。

## 2026-06-30 30/60 天观察不能只靠“计划 CSV”

- 场景：稳健线 `Long/Short Donchian Top5` 和高收益线 `Donchian v2 vol target max2.5x` 都要求继续 30/60 天 observe-only。
- 现象：如果只有确认包里的 forward observation plan 或人工复核结论，而没有每日追加 ledger，后续无法证明“真实未来行情已经被观察了多少天”，也无法区分同一决策时间重复运行和新增市场数据。
- 处理方式：新增稳健线 `btc_long_short_top5_forward_observer`，每日只追加 `data/forward_observation/btc_long_short_top5/observations.jsonl`，记录 Top5 的最新完成 4H 决策信号、已 shift 的理论仓位、30/60 天窗口表现和降级原因；高收益线复用既有 `btc_high_yield_v2_followup`。二者均加入 Codex app 每日自动任务，且命令提示中固定禁止 broker/private/order/live、paper 队列和策略骨架。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_long_short_top5_forward_observer.py` 输出 `status=complete_research_only`、新增 `5` 条 Top5 观察、`observation_days=1`、`downgrade_triggered=false`；`.\.venv\Scripts\python.exe scripts\research\run_btc_high_yield_v2_followup.py` 输出 `status=complete_research_only`、`loss_v3_retained_count=5`，但永续证据仍缺 `mark/index price path`、深度滑点、outage 模型和精确强平公式。两个观察任务分别创建为 `btc-long-short-top5-observe-only-daily` 和 `btc-high-yield-v2-observe-only-daily`。

## 2026-07-01 激进滚仓预选不能只按年化收益

- 场景：用户要求单独开 `BTC High-Octane Attack Sleeve Lab v2`，把防守版的 `-10%` 插针后剩余本金门槛从 80% 放宽到 40/50/60 三档，允许 50%-70% 回撤，追求小资金更高收益。
- 现象：第一版 v2 先按纯年化收益取 Top60 做 rolling start，结果 Top60 全是极端 attack 暴露场景，年化可到约 `5300%`，但 `-10%` 插针后剩余本金不到 `1%`，导致最终 40/50/60 三档 watchlist 全部为 0。基础网格里其实有大量满足 `survive_40pct` 的候选，问题出在预选口径。
- 处理方式：v2 预选必须先满足最低生存层：真实用过 10x attack、总收益为正、`-10%` 插针后剩余本金 `>=40%`、最大回撤 `<=70%`，再按年化/总收益/rolling 中位收益/全灭率排序。低于 40% 的超高收益场景只能留在 grid 诊断，不进入 rolling watchlist。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_high_octane_attack_sleeve_lab.py` 输出 `status=complete_research_only`、`scenario_count=1944`、`rolling_start_row_count=1680`、`watchlist_count=60`、`survive_40pct=60`、`survive_50pct=12`、`survive_60pct=0`。最佳观察候选为 `ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none`，年化约 `969.07%`、总收益约 `36627.90%`、`-10%` 插针后剩余本金约 `40.01%`、rolling 中位总收益约 `1435.83%`、rolling 全灭率 `0.0`。仍然 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、不接 broker/OMS。

## 2026-07-01 审计包要把“未发现未来函数”和“可实盘”分开

- 场景：用户要求对 `Long/Short Donchian Top5` 和 `High-Octane Attack Sleeve v2` 做未来函数/过拟合审计，重点检查 v2 最佳候选 `-10%` 插针后剩余本金 `40.01%` 是否是参数挖出来的。
- 现象：Long/Short Top5 静态检查未发现直接未来函数证据：Donchian 线使用 `high/low.shift(1)`，收益计算使用 `raw.shift(1)`，报告声明 completed bar 和 `available_time <= decision_time`。但 Top5 全部存在趋势策略常见的正收益交易集中问题，仍需要 forward confirmation。High-Octane v2 没有 paper/live 解锁，但最佳候选距离 40% 生存门槛只有 `0.011869` 个百分点，且 `survive_60pct=0`，这是明显阈值边界风险。
- 处理方式：新增 `btc_strategy_leakage_overfit_audit`，结论不再写成“通过/可实盘”，而是拆成三层：`no_direct_leakage_detected_from_static_checks`、`model_boundary_risk_same_bar_proxy_requires_execution_replay`、`high_overfit_and_threshold_boundary_risk_research_only`。同根 4H high/low 强平和 close-to-close 收益更新只能算研究近似，不等于真实 mark/index execution replay。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_leakage_overfit_audit.py` 输出 `status=complete_research_only`、`decision=research_only_overfit_risk_high_no_paper_no_live`、`check_fail_count=0`、`check_warn_count=3`。Long/Short 结论为 `no_direct_leakage_detected_but_concentration_requires_forward_confirmation`；High-Octane 结论为 `high_overfit_and_threshold_boundary_risk_research_only`；安全状态继续 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`。

## 2026-07-01 静态未来函数审计不能替代逐 bar replay

- 场景：用户要求先审 `Long/Short Donchian Top5` 和 `High-Octane Attack Sleeve v2`，尤其确认 v2 最佳候选 `-10%` 插针后剩余本金 `40.01%` 是否是参数挖出来的。
- 现象：静态审计能检查源码里是否有 `shift(1)`、是否声明 `available_time <= decision_time`，但它不能证明实际每一根 bar 的 raw signal、exposure、return 和 derivatives 行都按可见性规则绑定；如果只停留在静态检查，容易把“未发现明显未来函数”误读为“可进入 paper/live”。
- 处理方式：新增 `btc_strategy_bar_replay_visibility`，按当前真实代码路径重算 Top5 的逐 bar 信号与仓位，要求 `current exposure == previous raw signal` 且 `current raw signal` 只能影响下一根 bar；derivatives sentiment 逐 bar 保留 `available_time/event_time` 可见性；High-Octane v2 单独标记同根 `high/low` 强平/插针与 close-to-close return 近似，要求后续真实 mark/index execution replay。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_bar_replay_visibility.py` 输出 `status=complete_research_only`、`decision=research_only_bar_replay_passed_for_long_short_high_octane_requires_execution_replay_no_paper_no_live`、`long_short_row_count=27300`、`long_short_shift_violation_count=0`、`long_short_derivatives_visibility_violation_count=0`；High-Octane v2 最佳仍为 `ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none`，距 40% 门槛仅 `0.011869` 个百分点，`high_octane_model_boundary_row_count=5460`。安全状态继续为 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`。

## 2026-07-01 看过的 holdout 不能继续当干净样本

- 场景：完成逐 bar replay 后，下一关口是锁定确认性 holdout，防止后续继续围绕 Long/Short Top5 或 High-Octane v2 调参数时，把已经看过的验证段又拿来做选择。
- 现象：Long/Short Top5 的 `2025-12-29T03:59:59.999Z` 到 `2026-06-28T23:59:59.999Z` 已经作为 post-selection confirmation stress 被报告看过；High-Octane v2 的 `2024-01-01T03:59:59.999Z` 到 `2026-06-28T23:59:59.999Z` 更是已经参与网格排序。它们可以用于审计回放和固定参数回归，但不能再被包装成“干净确认性 holdout”。
- 处理方式：新增 `btc_confirmatory_holdout_lock`，同时写 artifact 报告和 tracked 配置 `configs/btc/research_holdout/btc_confirmatory_holdout_locks.json`。配置中把历史已看过窗口和 `2026-06-28T23:59:59.999Z` 之后的 30/60 天 observe-only 窗口都列为 forbidden for `parameter_search/candidate_ranking/ga_fitness/threshold_tuning/watchlist_replacement`，并提供 `selection_window_violations(...)` 供后续实验接入。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_confirmatory_holdout_lock.py` 输出 `status=complete_research_only`、`decision=btc_confirmatory_holdout_locked_research_only_no_paper_no_live`、`lock_count=3`、`historical_seen_lock_count=2`、`future_observe_only_lock_count=1`、`latest_common_history_end=2026-06-28T23:59:59.999000+00:00`、`self_check_violation_count=7`；安全状态继续为 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`。

## 2026-07-01 observe-only 观察器也要接 holdout lock

- 场景：Long/Short Donchian Top5 和 10x attack/High-Octane 线进入 30/60 天 observe-only 后，如果观察器只追加每日信号 ledger，却不读取 `btc_confirmatory_holdout_locks.json`，后续很容易把观察期数据反向用于调参、候选排序或 watchlist 替换。
- 现象：观察器本身没有下单风险，但它产生的新数据最容易被误用成“新验证集”。如果不在报告中同时证明 `observe_only_signal_recording` 允许、`parameter_search/candidate_ranking/ga_fitness/threshold_tuning/watchlist_replacement` 禁止，就会在研究流程里留下过拟合绕行口。
- 处理方式：新增共用 `btc_observe_only_lock`，两个观察器写入 ledger 前必须读取 holdout lock；锁缺失或 observe-only 用途违规时 fail-closed，不写观察 ledger。报告和安全文件新增 `holdout_lock_enforced`、`observe_only_violation_count`、`selection_use_blocked_by_lock`，每条新观察行也写入锁状态。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_long_short_top5_forward_observer.py` 和 `.\.venv\Scripts\python.exe scripts\research\run_btc_bankroll_attack_forward_observer.py` 均输出 `status=complete_research_only`、`observe_only_violation_count=0`、`selection_use_blocked_by_lock=true`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。当前本地数据最新时间仍为 `2026-06-28T23:59:59.999000+00:00`，等于锁定锚点，所以本次只是锚点复跑，尚不算真正新增的 30/60 天 forward observation。

## 2026-07-01 完整网格有保守方案不代表高收益第一名稳健

- 场景：复核 `High-Octane Attack Sleeve v2` 的最佳候选 `ho_step0p35_core5x6_reserve5x2_attack10x2_cap2_max10_delaylate_none`，它在 `-10%` 插针压力下剩余本金为 `40.011869%`，只比 40% 生存线高 `0.011869` 个百分点。
- 现象：完整 1944 个场景里确实存在不少更保守的高生存候选，不能简单说“全网格没有稳健方案”。但高收益 watchlist 的结构暴露了另一层风险：按年化收益排序的 Top60 全部低于 40% 生存线，最终 watchlist 虽然有 60 个 survive_40pct，但只有 12 个 survive_50pct、0 个 survive_60pct；最佳候选还落在 `atr_step` 最小、`max_total_exposed` 最大、`late` 延迟和 `extract_policy=none` 主导的网格边界上。
- 处理方式：未来判断高收益候选是否挖参，必须同时看完整网格和高收益 watchlist：完整网格回答“有没有保守替代”，watchlist 回答“当前第一名是不是为了收益贴着风险阈值筛出来”。40.01% 这种压线候选只能标记为 `strong_parameter_mining_symptoms_threshold_boundary_research_only`，不能进 paper/live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_leakage_overfit_audit.py` 输出 `status=complete_research_only`、`check_fail_count=0`、`check_warn_count=4`、`high_octane_parameter_mining_verdict=strong_parameter_mining_symptoms_threshold_boundary_research_only`、`high_octane_likely_parameter_mined_boundary_candidate=true`。报告同时显示 Long/Short Top5 bar replay shift/available-time 违规数为 0，但仍需 forward confirmation；安全状态继续为 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 provider/cost 证据通过不等于永续可执行

- 场景：目标进入永续真实执行证据关口，需要同时核对 mark price、index/premium、资金费率结算、手续费、深度滑点、强平公式和断线/outage，而不是只看单个 provider 或 cost artifact 是否为 pass。
- 现象：当前 `btc_perpetual_provider_verification_report.json` 选择的是 `btc_okx_swap_btcusdt_intraday_5m_31d_v1`，但当前配置 `configs/data/btc_perpetual_sources.yaml` 选择的是 `btc_okx_swap_btcusdt_daily_roll_90d_v1`，二者不一致；配置 bundle 的样本结束时间为 `2026-06-23T00:00:00Z`，落后最新策略观察时间 `2026-06-28T23:59:59.999Z` 约 144 小时。成本模型里历史 mark/premium 可用，但 current mark 不可用、mark 未用于强平风险、滑点仍为 `0.0 bps`、深度滑点未验证、精确强平公式/维护保证金档位/outage replay 证据不完整。
- 处理方式：新增 `btc_perpetual_execution_evidence` 统一证据包，把 Long/Short Top5、High-Octane v2 和 high-yield v2 都挂到同一套永续证据门禁上。只要任何关键证据缺失，就输出 `perpetual_execution_evidence_incomplete_fail_closed_no_paper_no_live`，不写 paper 队列、不生成策略骨架、不接 broker/OMS、不解锁 live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_perpetual_execution_evidence.py` 输出 `status=incomplete_research_only`、`pass_count=11`、`fail_count=10`、`blocker_count=10`，阻断项包括 provider/config bundle 不一致、永续数据未覆盖最新策略观察、current mark 缺失、mark 未用于强平风险、0 滑点/深度滑点未验证、精确强平公式未验证、liquidation history/snapshot 缺失、runtime replay 未就绪、当前策略永续 policy 未允许。安全状态继续为 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。
## 2026-07-01 raw capture cache mismatch 不能直接否定已验证 bundle 输出

- 场景：重建 `btc_perpetual_provider_verification_report` 时，当前配置与 provider 选择已统一为 `okx_swap / btc_okx_swap_btcusdt_daily_roll_90d_v1`，但 `btc_manual_metadata_import_report.json` 记录的 `funding_info_raw.json` 原始抓取文件后来被新的 public metadata 抓取覆盖，触发 `btc_funding_info_raw_import_current_file_mismatch`。
- 现象：如果把 raw cache 当前文件 hash mismatch 一律当作硬 blocker，会导致已经写入 bundle 的 `funding_info.json` 输出 hash 明明仍与导入报告匹配，却让 provider 和 cost evidence 误判失败；这会混淆“原始抓取缓存被覆盖”和“候选 bundle 输出证据失效”两类问题。
- 处理方式：只在输出文件 hash 已验证、输出路径仍指向当前 selected bundle、HTTP status/provenance 仍有效时，把 `btc_exchange_info_raw_import_current_file_mismatch` / `btc_funding_info_raw_import_current_file_mismatch` 从硬 blocker 降级为 `diagnostic_warnings`。若 raw provenance 缺失、HTTP status 非 200、输出 hash mismatch 或输出路径不属于 selected bundle，仍必须 fail-closed。
- 本次证据：修正后 `btc_perpetual_provider_verification_report.json` 显示 `perpetual_evidence_ready=true`、`blockers=[]`，并在 `diagnostic_warnings` 保留 `btc_funding_info_raw_import_current_file_mismatch`；`btc_cost_model_report.json` 重新为 `status=pass`。但 `btc_perpetual_execution_evidence_report.json` 仍为 `status=incomplete_research_only`，剩余 blocker 包括永续数据未覆盖最新策略决策、current mark 缺失、mark 未用于强平风险、深度滑点/精确强平公式/清算快照/runtime replay/policy 未完备，仍不得写 paper 队列或解锁 live。

## 2026-07-01 OKX 90 天全量分页不稳时应走 tail merge，不应降低验证口径

- 场景：为消除 `btc_perp_exec_perp_data_covers_latest_strategy_decision`，尝试用 `fetch_btc_okx_swap_public_data.py --history-days 90 --execute-network` 刷新 `btc_okx_swap_btcusdt_daily_roll_90d_v1`。
- 现象：OKX public REST 在长分页的 5m candles 阶段多次远端断开，先后出现 `RemoteDisconnected` 和 `[WinError 10054] 远程主机强迫关闭了一个现有的连接`。这不是私有权限或下单问题，而是 public REST 长分页网络稳定性问题。
- 处理方式：给 OKX public request 增加有限重试；同时新增 `merge_btc_okx_swap_tail_bundle.py`，先抓短尾部 bundle，再合并进主 90 天 bundle，保留历史主体。合并时必须按主键保留盘口多档深度，不能只按 timestamp 去重，否则 100 档 order book 会被压成 1-2 行。
- PIT 要点：新写入的 OKX CSV 必须带 `event_time/available_time/ingested_at/processed_at`；K 线 `available_time` 应为开盘时间加周期长度，不能把未完成 bar 当成可见。
- 证据口径：永续执行证据的数据覆盖不能只看 manifest 总 `sample_end`，因为元数据或盘口时间可能把总 sample_end 推到当前；应看核心执行序列的最小 sample_end：`klines_1h`、`mark_price_klines_1h`、`premium_index_klines_1h`、`funding_rate`。
- 本次证据：10 天 tail bundle `btc_okx_swap_btcusdt_tail_10d_v1` 抓取成功，`sample_end=2026-07-01T00:00:00Z`，public only 且 `api_key_used=false/private_endpoint_used=false/order_endpoint_used=false`；合并后主 bundle 核心角色 sample_end 均为 `2026-07-01T00:00:00Z`，覆盖最新策略观测 `2026-06-28T23:59:59.999Z`。`btc_perpetual_execution_evidence_report.json` blocker 从 9 个降为 8 个，但仍 fail-closed，不得写 paper 队列或解锁 live。

## 2026-07-01 current mark 证据不能硬编码为缺失，也不能偷看未来行

- 场景：`btc_perpetual_execution_evidence_report.json` 里剩余 blocker 包含 `current_mark_price_available` 和 `mark_used_for_liquidation_risk`，但 selected OKX bundle 已经有 `mark_price_klines_1h.csv` 与 `premium_index_klines_1h.csv`，并覆盖到最新策略观察之后。
- 现象：问题不是“没有 mark/index 数据”，而是 `build_btc_cost_model_report.py` 把 `mark_price_current_available` 和 `mark_price_used_for_liquidation_risk` 硬编码为 `false`。如果简单改成 `true` 也不对，因为 report 生成时间早于 `available_time` 的 mark 行不能被当成当前价，否则会引入未来函数。
- 处理方式：cost report 只读取 selected perpetual bundle 中 `available_time <= generated_at` 的已完成 mark/premium 行，并要求 current mark 年龄不超过 6 小时；强平风险只在 `liquidation_risk_contract.json` 完整、要求 mark/current_mark/index 且当前 mark 可用时标记为已使用 mark。测试新增临时 fixture，覆盖“未来 mark 行不可见”和“近期完成 mark 行可用”两种情况。
- 本次证据：重建 `btc_cost_model_report.json` 后，`mark_price_current_available=true`、`mark_price_used_for_liquidation_risk=true`，当前 mark 来自 `btc_okx_swap_btcusdt_daily_roll_90d_v1/mark_price_klines_1h.csv`，可用时间 `2026-07-01T01:00:00+00:00`。重建 `btc_perpetual_execution_evidence_report.json` 后 blocker 从 8 个降到 6 个，剩余为滑点/深度、精确强平公式、清算快照、runtime replay 和 perpetual policy；仍然 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 免费 L2 样本能修正 0 bps 滑点，但不能替代历史深度滑点验证

- 场景：永续执行证据还剩 `btc_perp_exec_slippage_positive_or_depth_aware` 和 `btc_perp_exec_depth_aware_slippage_history_verified` 两个滑点相关 blocker。用户要求数据不够时先想办法用免费数据源补，不能补的数据最后说明。
- 现象：selected OKX bundle 里原本只有一个主要 50 档盘口快照和一个历史残留盘口行；这不足以证明“历史深度滑点模型已验证”。同时 cost model 里 `slippage_bps=0.0` 也不合格，因为 0 bps 明显低估真实永续执行成本。
- 处理方式：先复用现有免费 OKX public REST L2 对齐采样器，不使用 API key，不访问 private/order endpoint。60 样本采集因公共 REST 长等待被中止，改跑 3 样本短采集成功，生成 `order_book_depth_aligned.csv` 和 `agg_trades_aligned.csv`。新增 `btc_depth_slippage_report`，读取 `order_book_depth.csv`、`order_book_depth_aligned.csv`、`order_book_depth_samples.csv`，只使用 `available_time/local_receive_ts <= generated_at` 的可见行，计算当前盘口 spread/depth 和正滑点下限；但历史深度验证要求至少 48 个两边盘口快照和 14 天覆盖，不满足则继续 fail-closed。
- 本次证据：`btc_depth_slippage_report.json` 显示 `positive_slippage_floor_bps=1.0`、`snapshot_count=5`、`two_sided_snapshot_count=4`、`coverage_days=7.944373`、`depth_aware_slippage_history_verified=false`。重建 `btc_cost_model_report.json` 后，原 `configured_slippage_bps=0.0` 被免费 L2 样本给出的 `depth_snapshot_positive_floor_diagnostic_partial` 口径替代为 `slippage_bps=1.0`。重建 `btc_perpetual_execution_evidence_report.json` 后 blocker 从 6 个降到 5 个；`btc_perp_exec_depth_aware_slippage_history_verified` 仍保留，不得写 paper 队列或解锁 live。

## 2026-07-01 OKX 强平公式可以用免费公共源补，但不等于清算历史已覆盖

- 场景：永续执行证据还剩 `btc_perp_exec_exact_exchange_liquidation_formula_verified`。用户要求数据不够时先找免费数据源补，不能补的最后说明。
- 现象：OKX 私有 `account/position-tiers` 需要 API key，不适合当前 research-only 公共证据；但 OKX 公共 `public/position-tiers` 可以匿名返回 `BTC-USDT` swap 的 `tier/minSz/maxSz/mmr/imr/maxLever`。因此保证金档位可以补，账户专属组合保证金状态、真实强平成交、历史清算快照不能由这个接口补。
- 处理方式：新增 `btc_okx_liquidation_formula_report`，只访问 OKX public REST，不使用 API key，不访问 private/order endpoint；同时把官方公式来源、强平触发条件、mark price 口径和公共保证金档位分开记录。provider verification 只读取该 artifact 的布尔字段，不把它误当成完整 provider bundle blocker；perpetual execution evidence 要求 `liquidation_formula_verified` 和 `maintenance_margin_tiers_verified` 同时为真才通过该项。
- 本次证据：`.\.venv\Scripts\python.exe scripts\build_btc_okx_liquidation_formula_report.py --execute-network` 输出 `status=verified_research_only`、`liquidation_formula_verified=true`、`maintenance_margin_tiers_verified=true`、`exact_exchange_liquidation_formula_verified=true`、`blockers=[]`；重建 `btc_perpetual_provider_verification_report.json` 后 `maintenance_margin_tier_count=198`、`maintenance_margin_td_modes_verified=["cross","isolated"]`。重建 `btc_perpetual_execution_evidence_report.json` 后 blocker 从 5 个降到 4 个，强平公式 blocker 已解除，但 `liquidation_history_or_snapshots_available` 仍保留，不得写 paper 队列或解锁 live。

## 2026-07-01 免费清算历史不能被 Binance Vision 空目录误判为可用

- 场景：继续尝试补 `btc_perp_exec_liquidation_history_or_snapshots_available`，优先检查免费公共源。
- 现象：检索到 Binance Vision 页面存在 `data/futures/um/daily/liquidationSnapshot/BTCUSDT/` 前端目录，但直接访问底层 S3 `list-type=2&prefix=data/futures/um/daily/liquidationSnapshot/BTCUSDT/` 返回 `KeyCount=0`，没有可下载文件。Binance 官方 forceOrder websocket 是实时推送，并且单合约每秒只推最大一笔强平快照；OKX liquidation-orders 也是公共近实时/短窗口记录，不能直接补成 90/180 天完整 1H 清算历史。
- 处理方式：不把空目录、实时流或第三方付费 API 包装成 gate 证据。当前只能保留既有 OKX 720h tail 和 GitHub 日频 fallback 的 diagnostic 角色；它们可以用于研究诊断，不能解除 execution evidence 的清算历史/快照 blocker。
- 本次证据：Binance Vision S3 列表返回 `KeyCount=0`；`btc_perpetual_execution_evidence_report.json` 仍保留 `btc_perp_exec_liquidation_history_or_snapshots_available`。这项短期内无法用当前已确认的免费公共源一次性补齐。

## 2026-07-01 锚点复跑不能算 30/60 天样本外验证

- 场景：审计 `Long/Short Donchian Top5` 和 `High-Octane Attack Sleeve v2` 是否存在未来函数或过拟合，尤其是 `-10%` 插针后只剩 `40.011869%` 本金的 High-Octane 压线候选。
- 现象：逐根 bar replay 没有发现 Long/Short 当前仓位/下一根执行 shift 违规，也没有发现 derivatives `available_time > decision_time` 的可见性违规；但两个 observe-only 观察器的最新决策时间仍是 `2026-06-28T23:59:59.999000+00:00`，属于 holdout 锁定锚点复跑，不是新增样本外数据。High-Octane v2 还使用 close-to-close return 与同根 4H high/low 做强平/插针近似，不能替代真实 mark/index execution replay。
- 处理方式：把 `btc_confirmatory_holdout_lock`、Long/Short observer 和 Attack observer 纳入 `btc_strategy_leakage_overfit_audit`。审计必须同时报告：历史窗口已被选择过程消耗、未来数据只能 observe-only、选择用途被锁阻断、30/60 天观察是否完成。40.01% 压线候选标记为 `strong_parameter_mining_symptoms_threshold_boundary_research_only`，不允许进 paper/live。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_bar_replay_visibility.py` 输出 Long/Short shift/available-time 违规数为 0，High-Octane 模型边界行数 `5460`；`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_leakage_overfit_audit.py` 输出 `status=complete_research_only`、`check_fail_count=0`、`check_warn_count=5`、`forward_observe_clean_confirmation_ready=false`、`forward_observe_only_anchor_rows_so_far=true`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 公共 WS/L2 replay 不能替代 paper runtime replay

- 场景：永续执行证据仍有 `btc_perp_exec_exchange_runtime_real_or_paper_replay_ready` blocker。当前已有 OKX 公共 WS/L2 分段捕获、order book replay、reconnect/resync policy 报告，但 exchange runtime contract 仍是 `simulated_contract_probe`。
- 现象：公共 WS/L2 replay 只能证明市场数据序列、断线重连和 order book 重放的一部分；它不能证明真实订单延迟、撮合队列位置、paper fill 行为，也不能证明 private order/fill stream reconcile。当前 coverage 虽然有 `verified_public_session_count=8`、`total_capture_duration_seconds=3792.63477036`、replay/resync ready session 都为 8，但事件历史只有 `0.043896235768055555` 天，日历跨度只有 `0.49421296296296297` 天，距离 30 天级别证据还很远。
- 处理方式：新增 `btc_exchange_runtime_replay_gap_report`，把 runtime contract、public WS/L2 coverage 和 paper runtime replay 分开审计。总 `btc_perpetual_execution_evidence` 只把 gap report 作为 details 接入，不因为公共行情 replay 存在就放行 runtime gate。
- 本次证据：`.\.venv\Scripts\python.exe scripts\build_btc_exchange_runtime_replay_gap_report.py` 输出 `status=incomplete_research_only`、`blocker_count=11`，关键 blockers 包括 `btc_runtime_contract_still_simulated_contract_probe`、`btc_public_ws_l2_event_history_days_insufficient`、`btc_execution_latency_model_missing_public_ws_is_not_order_latency`、`btc_queue_model_missing_public_l2_is_not_exchange_queue_position`、`btc_paper_runtime_replay_missing`。重建 `btc_perpetual_execution_evidence_report.json` 后总 blocker 仍为 4 个，继续 fail-closed，不得写 paper 队列或解锁 live。

## 2026-07-01 Binance Vision bookDepth 能补免费跨交易所深度诊断，但不能替代 OKX 深度滑点门禁

- 场景：用户要求数据不够时优先用免费数据源补，补不了的最后明确说明。当前永续执行证据仍有 `btc_perp_exec_depth_aware_slippage_history_verified` blocker，OKX 自身 L2 快照只有少量样本，不足以验证历史深度滑点模型。
- 现象：Binance Vision 免费公开 `data/futures/um/daily/bookDepth/BTCUSDT/` 确实有可下载日文件，并可补到 14 个自然日、483,840 行、40,320 个两边盘口时间点；但该文件字段是 `timestamp,percentage,depth,notional`，属于 Binance USD-M 按价格百分比聚合后的深度，不是 OKX 逐档盘口，也不是 paper fill replay。
- 处理方式：新增 `btc_binance_vision_book_depth_diagnostic` 作为 research-only 诊断，只记录跨交易所深度环境、覆盖窗口和百分比深度分布；接入 `btc_depth_slippage_report` 与 `btc_perpetual_execution_evidence_report` 的 details，但 `gate_eligible_for_selected_venue=false`，不得把它用于解除 OKX 深度滑点、paper 或 live 门禁。
- 本次证据：`.\.venv\Scripts\python.exe scripts\build_btc_binance_vision_book_depth_diagnostic.py --execute-network --lookback-days 14 --network-route-label direct_local_cn` 成功下载最新可用窗口 `2026-06-16` 到 `2026-06-29`；重建 `btc_depth_slippage_report.json` 后 `free_public_cross_venue_depth_diagnostic.present=true`、`row_count=483840`，但 `depth_aware_slippage_history_verified=false`；重建 `btc_perpetual_execution_evidence_report.json` 后仍保留 `btc_perp_exec_depth_aware_slippage_history_verified`，继续 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 OKX L2 对齐采样必须累积历史，REST 对齐不能冒充撮合级执行证据

- 场景：继续推进 `btc_perp_exec_depth_aware_slippage_history_verified` blocker，需要用免费 OKX public L2 样本积累历史深度；同时不能把 REST trades/books 的时间差误认为真实撮合队列或订单延迟。
- 现象：原 `fetch_btc_okx_timestamp_aligned_l2_public_capture.py` 每次都会覆盖 `agg_trades_aligned.csv` 和 `order_book_depth_aligned.csv`，导致 30/60 天观察无法累积。实际跑 50 组 public REST 采样时还可能长时间卡在网络等待；改跑 5 组后成功，但 REST trades 与 books 的 `local_receive_ts` 差距约 2-3 秒，超过 250ms 同窗口对齐阈值。
- 处理方式：对齐采样脚本改为默认 `append_existing=true`，读取已有 aligned CSV 后偏移 `capture_sequence`、追加并去重，同时在 `l2_alignment_manifest.json` 记录 `existing_*`、`new_*`、`cumulative_*` 行数和累计捕获跨度。真实执行证据仍要求区分 REST latency、execution latency、queue model 和 paper fill replay，不允许用 REST 样本替代。
- 本次证据：小批量 public REST 采样成功，累计 `capture_sequences=8`、`trade_row_count=800`、`book_level_row_count=800`，`private_endpoint_used=false`、`order_endpoint_used=false`。重建 aligned quality 后格式文件齐全、public 边界通过，但 `same_window_trade_book_alignment_satisfied=false`、`event_ledger_history_days=0.0437847`；重建 `btc_depth_slippage_report.json` 后 `snapshot_count=10`、`two_sided_snapshot_count=9`、`two_sided_coverage_days=0.059302`，仍保留 `btc_depth_aware_slippage_history_insufficient`，不写 paper 队列、不解锁 live。
## 2026-07-01 OKX L2 深度观察应做成日跑累积，不能把一次 smoke 当成执行证据

- 场景：用户要求数据不够时优先用免费数据源补，补不了的最后明确说明；当前永续执行证据仍有 `btc_perp_exec_depth_aware_slippage_history_verified` blocker。
- 现象：新增 `run_btc_okx_l2_depth_observation_daily.py` 后，用 OKX public REST 小样本日跑串联“L2 采集 -> aligned quality -> depth slippage -> cost model -> perpetual execution evidence”。真实 smoke `--execute-network --sample-count 3` 成功，但累计也只有 `same_capture_sequence_count=11`、`trade_row_count=1100`、`book_level_row_count=1100`；深度报告里 `two_sided_snapshot_count=9`、`two_sided_coverage_days=0.059302`，距离 48 个两边盘口快照和 14 天覆盖仍很远。
- 处理方式：runner 必须固定 research-only，默认不联网，显式 `--execute-network` 才访问 OKX 公共 REST；默认 `append_existing=true` 累积历史；每次日跑都重建证据包但继续 fail-closed。不能因为 cost model 已有 1 bps 正滑点下限就认为 depth-aware slippage history 已验证。
- 不能靠当前免费 L2 一次性补齐的缺口：`btc_execution_latency_model_missing_rest_latency_is_not_execution_latency`、`btc_queue_model_missing_visible_depth_is_proxy_only`、`btc_perp_exec_liquidation_history_or_snapshots_available`、`btc_perp_exec_exchange_runtime_real_or_paper_replay_ready`、`btc_perp_exec_perpetual_policy_allows_current_strategy`。这些要么需要长期观察/真实 paper runtime，要么当前未找到可用免费完整历史源。
- 本次证据：`.\.venv\Scripts\python.exe scripts\run_btc_okx_l2_depth_observation_daily.py --execute-network --sample-count 3 --book-size 50 --trade-limit 100 --request-sleep-seconds 0.1` 输出 `status=free_public_l2_depth_observation_completed_research_only`、`post_capture_reports_built=true`、`blocker_count=9`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。产物位于 `artifacts/btc_l2_depth_observation/latest/`。
## 2026-07-01 永续 policy 不能继续引用旧 spot 路径来判断 long/short 策略

- 场景：当前有 Long/Short Donchian、High-Octane attack、High-yield v2 等研究线，它们都需要做空、杠杆、mark/index、funding 和强平证据；但 `btc_perpetual_policy_status_report.json` 仍来自旧的 `btc_trend_raw` spot/unlevered daily target，导致永续证据包出现 `btc_perp_exec_perpetual_policy_allows_current_strategy` blocker。
- 现象：这不是策略证据缺口，而是路由声明缺口。旧 policy 显示 `current_strategy_uses_perpetual=false`、`gate.perpetual_allowed=false`，会把需要永续证据的研究线误判成“当前策略不走永续”。
- 处理方式：新增 `btc_perpetual_route_request`，只声明哪些 BTC 研究线需要永续执行证据；它不写 paper 队列、不生成策略骨架、不解锁 live。`build_btc_perpetual_policy_status.py` 读取该声明后，允许 policy 表达 `current_strategy_uses_perpetual=true` 和 `gate.perpetual_allowed=true`，但 `paper_queue_write_allowed=false`、`live_unlock_allowed=false` 必须保持不变。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_perpetual_route_request.py` 输出 `eligible_strategy_line_count=3`；重建 `build_btc_perpetual_policy_status.py` 后 policy 为 `current_route=perpetual_requires_full_risk_evidence`、`current_strategy_uses_perpetual=true`；重建 `build_btc_perpetual_execution_evidence.py` 后 blocker 从 4 个降为 3 个，剩余为 `btc_perp_exec_depth_aware_slippage_history_verified`、`btc_perp_exec_liquidation_history_or_snapshots_available`、`btc_perp_exec_exchange_runtime_real_or_paper_replay_ready`，paper/live 仍然关闭。
## 2026-07-01 Gate dashboard 不能忽略永续执行证据 blocker

- 场景：重建 `btc_gate_dashboard.json` 后曾显示 `status=complete`、`blockers=[]`，但 `btc_perpetual_execution_evidence_report.json` 实际仍有 3 个硬 blocker。
- 现象：旧 dashboard 只检查缺失 artifact、`status=blocked` 和 unsafe flag；没有把 `incomplete_research_only` 的永续执行证据 blocker 传导到总 gate。这样会让总看板看起来“完成”，但实际上永续 paper/live 仍不能走。
- 处理方式：把 `perpetual_route_request` 和 `perpetual_execution_evidence` 加入 dashboard 输入；对 `perpetual_execution_evidence` 设为硬门禁 artifact，只要其 `blockers` 非空，就转成 dashboard blocker。`live_readiness` 的 blocker 仍保留为 live 状态信息，不因此改变既有 paper observing 语义。
- 本次证据：刷新 `.\.venv\Scripts\python.exe scripts\build_btc_gate_dashboard.py` 后，dashboard 为 `status=blocked`，阻断项明确为 `btc_perp_exec_depth_aware_slippage_history_verified`、`btc_perp_exec_liquidation_history_or_snapshots_available`、`btc_perp_exec_exchange_runtime_real_or_paper_replay_ready` 三项，继续不允许 paper/live。
## 2026-07-01 旧 paper runtime replay 完整不等于当前永续研究线 runtime 就绪

- 场景：`btc_exchange_runtime_replay_gap_report.json` 缺少 `btc_exchange_paper_runtime_replay_report.json`，但现有 `artifacts/btc_paper_validation/latest/` 里已有 30 天 paper validation runtime/evaluation/replay 产物。
- 现象：现有 paper validation runtime 本身完整，`days_completed=30`、`total_orders=4`、`total_fills=4`、`runtime_status=complete`、`replay_status=replay_pass`；但它绑定的是旧 `btc_trend_raw_t01_twelve_month_momentum` spot/unlevered 路线，`perpetual_allowed=false`、`liquidation_risk_required=false`。当前 Long/Short、High-Octane、High-yield v2 研究线已经声明需要永续执行证据，不能拿旧 spot paper replay 清掉永续 runtime gate。
- 处理方式：新增 `btc_exchange_paper_runtime_replay_report`，专门判断“已有 paper runtime replay 是否适用于当前永续路线”。旧 paper replay 可以标记 `legacy_ready=true`，但当前永续路线仍为 `current_perpetual_paper_runtime_replay_ready=false`，并输出 blocker `btc_current_perpetual_paper_runtime_replay_missing`。
- 本次证据：`.\.venv\Scripts\python.exe scripts\build_btc_exchange_paper_runtime_replay_report.py` 输出 `legacy_ready=true`、`current_perpetual_ready=false`；重建 `btc_exchange_runtime_replay_gap_report.json` 后不再是简单 missing，而是明确为 `btc_paper_runtime_replay_not_ready` + `btc_current_perpetual_paper_runtime_replay_missing`。上层 `btc_perpetual_execution_evidence_report.json` 仍保留 `btc_perp_exec_exchange_runtime_real_or_paper_replay_ready`，总 dashboard 仍 blocked。

## 2026-07-01 未来函数/过拟合审计必须同时披露免费数据补齐和剩余缺口

- 场景：用户要求审 `Long/Short Donchian Top5` 和 `High-Octane Attack Sleeve v2` 是否有未来函数、是否过拟合，且数据不够时先用免费源补，补不了的最后说明。
- 现象：旧审计包已经能发现 `High-Octane v2` 的 40.011869% 插针剩余本金候选是阈值边界风险，但默认 derivatives sentiment 只有约 180 天覆盖；如果只写“无 available_time 违规”，会漏掉数据覆盖责任。另一方面，免费 Binance Vision 能补 OI/OI USD/多空比/顶级交易员/主动买卖量比，但 1H liquidation 完整历史依然没有免费公共归档可用。
- 处理方式：用 `scripts\fetch_btc_binance_vision_derivatives_sentiment.py --execute-network --lookback-days 912` 写入单独 extended attempt 文件，避免破坏默认数据；再用扩展 derivatives 文件重跑 `btc_strategy_bar_replay_visibility`、holdout lock 和两个 observe-only 观察器。`btc_strategy_leakage_overfit_audit` 新增 `data_coverage_audit`，明确写出免费源、字段非空数、bar replay 缺失数、funding 当前月归档滞后和 liquidation 未补齐。
- 本次证据：扩展免费数据输出 `row_count=21832`，`open_interest_usd=21832`、`long_short_ratio=21829`、`funding_rate=21767`、`long_liquidation_usd/short_liquidation_usd=720`；bar replay 使用扩展文件后 `bar_replay_derivatives_missing_count=0`、`available_time_violation_count=0`。最终 `btc_strategy_leakage_overfit_audit_report.json` 为 `complete_research_only`，`check_fail_count=0`、`check_warn_count=5`，但结论仍是 `research_only_overfit_risk_high_no_paper_no_live`；`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。不能补齐的免费数据缺口：`binance_vision_current_month_funding_archive_lag_or_missing_rows`、`free_source_full_1h_liquidation_history_not_available`。

## 2026-07-01 永续执行证据需要中文逐项状态，不能只给英文 blocker

- 场景：继续推进“永续真实执行证据”关口，用户要求数据不够时先用免费源补，补不了的数据最后说明。
- 现象：追加 OKX public REST L2 日跑后，证据确实有进展，但 `btc_perpetual_execution_evidence_report.json` 仍只用英文 blocker 表达，不利于人工复核。另一方面，Binance Vision `bookDepth` 已经能提供跨交易所深度诊断，但不能替代 OKX 的时间对齐深度滑点门禁。
- 处理方式：执行 `scripts\run_btc_okx_l2_depth_observation_daily.py --execute-network --sample-count 12 --trade-limit 100 --book-size 50 --request-sleep-seconds 0.2`，只使用 OKX 免费公开 REST，不用 API key、不访问 private/order endpoint；随后重建 depth slippage、cost model 和 perpetual execution evidence。再给 `btc_perpetual_execution_evidence_report.json` 增加 `requirement_status_cn`，按“标记价/指数价、资金费率、手续费、深度滑点、强平公式、强平历史/快照、断线/outage/runtime replay”逐项输出中文状态，并同步到中文摘要。
- 本次证据：L2 日跑输出 `status=free_public_l2_depth_observation_completed_research_only`、`completed_sample_count=12`、累计 `same_capture_sequence_count=23`；depth 报告显示 `coverage_days=7.998237`、`two_sided_snapshot_count=12`、`two_sided_coverage_days=0.069493`，仍不足以通过 14 天/48 快照门槛。重建后的 `btc_perpetual_execution_evidence_report.json` 为 `incomplete_research_only`，`pass_count=19`、`fail_count=3`，中文状态表显示：mark/index、funding、手续费、强平公式通过；深度滑点、强平历史/快照、永续 runtime replay 阻断；`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。
- 当前免费源仍补不了的缺口：OKX gate 级别的长窗口 depth-aware slippage 历史、完整 1H 清算历史或可审计快照、当前永续路线的 paper runtime replay/真实成交回放/队列延迟/断线恢复证据。

## 2026-07-01 当前信号为空仓时，paper runtime replay 只能记 heartbeat，不能算成交回放通过

- 场景：永续执行证据仍有 `btc_perp_exec_exchange_runtime_real_or_paper_replay_ready`，已有旧 `btc_paper_validation` 30 天回放但它是 spot/unlevered 路线，不适用于当前 long/short 和杠杆永续研究线。
- 现象：只检查旧 paper replay 会误以为 paper runtime 已完整；但当前永续路线需要把 observe-only 理论信号转成永续规则下的模拟订单、模拟成交、funding、手续费、强平缓冲和熔断检查。当前最新观察时间 `2026-06-28T23:59:59.999000+00:00`，Long/Short Top5 和 High-Octane 的理论信号都是 `flat`，没有理论订单，也没有模拟成交。
- 处理方式：新增 `btc_perpetual_paper_runtime_replay_report`，默认读取 Long/Short Top5 与 High-Octane observe-only CSV、selected OKX 永续 bundle 的 1H mark/index/funding、cost model 和上层永续执行证据；只做本地模拟，不访问 private/order endpoint，不接 broker/OMS。若当前信号为空仓，只记录 heartbeat；若上层永续证据还有 blocker，则触发 `execution_evidence_incomplete_blocks_new_paper_orders` 熔断；若没有模拟成交，不能输出 ready。
- 本次证据：`.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_report.py` 输出 `status=incomplete_research_only`、`theoretical_order_count=0`、`simulated_fill_count=0`、`blockers=[btc_perpetual_paper_runtime_replay_execution_evidence_blocked, btc_perpetual_paper_runtime_replay_no_theoretical_orders_current_flat, btc_perpetual_paper_runtime_replay_no_simulated_fills]`。`btc_exchange_runtime_replay_gap_report.json` 现在能读取该新报告，`paper_runtime_replay.present=true` 但 `ready=false`，不会再把“文件缺失”和“当前永续回放不合格”混在一起。上层 `btc_perpetual_execution_evidence_report.json` 和 `btc_gate_dashboard.json` 仍保留三大 blocker，不写 paper 队列、不解锁 live。

## 2026-07-01 OKX 强平快照可以免费累积，但 available_time 必须按抓取后可见处理

- 场景：永续执行证据仍有 `btc_perp_exec_liquidation_history_or_snapshots_available`。当前找不到免费完整 1H 强平历史归档，但 OKX public REST `liquidation-orders` 可以拿到近期强平明细。
- 现象：第一次把本地函数开始时间当成 `available_time` 时，OKX 返回的最新 `event_time` 可能比本地开始时间晚几秒，导致 `available_time < event_time` 的可见性风险。强平快照来自“现在去公共接口查询”，不能被当成事件发生当时系统已经可见。
- 处理方式：新增 `btc_okx_liquidation_snapshot_observer` 和 `run_btc_okx_liquidation_snapshot_observation_daily.py`，只访问 OKX public REST，不使用 API key/private/order endpoint；每行 `event_time` 用 OKX `ts/time`，`available_time` 用 `max(public REST 响应完成时间, event_time)`，并追加去重写入 `data/external/btc_perpetual/okx_swap/liquidation_snapshots/okx_liquidation_orders_observe_only.csv`。成本模型读取该观察报告，只把 `liquidation_snapshot_available=true` 记为诊断，仍保持 `liquidation_snapshot_gate_eligible=false`、`complete_liquidation_history_available=false`。
- 本次证据：`.\.venv\Scripts\python.exe scripts\run_btc_okx_liquidation_snapshot_observation_daily.py --execute-network --limit 100` 返回 `new_row_count=1600`、`merged_row_count=1643`、事件时间范围 `2026-06-30T14:01:51.518000+00:00` 到 `2026-07-01T06:37:06.655000+00:00`；本地检查 `available_time_violation_count=0`。重建 `btc_cost_model_report.json` 后 `liquidation_snapshot_available=true`、`liquidation_snapshot_status=diagnostic_snapshot_observe_only_not_complete_history`；重建 `btc_perpetual_execution_evidence_report.json` 后该项仍为 `status=fail`，因为仍缺 gate 级别完整历史或可审计长窗口快照。总 dashboard 仍 blocked，不写 paper 队列、不解锁 live。
## 2026-07-01 L2 采样后重建证据不能继续用采样前 as-of
- 场景：继续推进 `btc_perp_exec_depth_aware_slippage_history_verified` blocker 时，发现 `run_btc_okx_l2_depth_observation_daily.py` 在抓取 OKX public REST L2 前生成 `generated_at`，但抓取完成后重建 `btc_depth_slippage_report.json` 仍使用这个旧 as-of。
- 现象：刚抓到的 aligned 盘口里，后半段 `local_receive_ts/exchange_ts` 晚于旧 as-of，会被 depth 报告过滤掉；本次修正前报告只看到 `two_sided_snapshot_count=12`，而实际 aligned CSV 已累计 23 组以上。
- 处理方式：runner 现在从 capture manifest 读取 `latest_capture_end/capture_end`，用采样结束后的 `post_capture_evidence_asof_utc` 重建 aligned quality、depth slippage、cost model 和 perpetual execution evidence；同时 `btc_depth_slippage.py` 对盘口行可见时间采用 `max(available_time, local_receive_ts, event_time/timestamp/exchange_ts)`，防止本地时钟慢于交易所时间时提前可见。
- 本次证据：补采后 `btc_depth_slippage_report.json` 显示 `snapshot_count=49`、`two_sided_snapshot_count=48`、`two_sided_coverage_days=0.135425`，样本数已达到最低线，但仍远低于 gate 要求的 `14` 天双边覆盖，因此继续保留 `btc_depth_aware_slippage_history_insufficient`；`btc_perpetual_execution_evidence_report.json` 仍为 `incomplete_research_only`，三项 blocker 不变，`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 永续执行证据日跑要有单独汇总入口，不能散落在多个手工命令里
- 场景：当前 BTC 侧离 paper/live 仍卡在深度滑点历史、强平历史/快照和当前永续 runtime replay 三个 gate。单独手工跑 L2、强平快照、成本模型、runtime gap、perpetual evidence 和 dashboard 容易漏步骤，也不利于 14 天/30 天这类时间覆盖累计。
- 现象：已有策略观察自动任务只负责 Long/Short Top5、高收益 v2 和 attack observe-only，不负责每天补 OKX public L2、OKX liquidation snapshot，也不负责刷新当前永续 runtime replay/gate 汇总。
- 处理方式：新增 `scripts/run_btc_perpetual_evidence_observe_only_daily.py`，串联 `OKX L2 observe-only -> OKX 强平快照 -> cost model -> 当前永续 paper runtime replay -> runtime gap -> perpetual execution evidence -> gate dashboard`，统一输出 `artifacts/btc_perpetual_evidence_observe_only_daily/latest/`。该入口固定 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`broker_access_allowed=false`、`order_endpoint_used=false`，只使用免费公开数据和本地回放证据。
- 本次证据：真实小样本命令 `.\.venv\Scripts\python.exe scripts\run_btc_perpetual_evidence_observe_only_daily.py --execute-network --l2-sample-count 2 --l2-trade-limit 100 --l2-book-size 50 --l2-request-sleep-seconds 0.2 --liquidation-limit 100` 输出 `status=complete_research_only`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。汇总报告显示 L2 双边快照 `51`、双边覆盖天数 `0.140389`、强平快照累计 `1651` 行、当前永续 runtime 理论订单 `0`、模拟成交 `0`，上层 `btc_perpetual_execution_evidence_report.json` 仍为 `incomplete_research_only` 且三项 blocker 不变。已创建自动任务 `btc-perpetual-evidence-observe-only-daily`，每天 9:40 运行该汇总入口。
## 2026-07-01 观察器不能只跑策略信号，必须先保证行情和永续情绪尾部同步

- 场景：继续审计 `Long/Short Donchian Top5` 和 `High-Octane Attack Sleeve v2` 是否存在未来函数、过拟合和数据覆盖缺口；用户要求数据不够时先用免费数据源补，补不了再说明。
- 现象：`market_klines` 曾经只到 `2026-06-29T00:59:59.999Z`，导致 30/60 天 observe-only 观察器卡在旧 anchor，不能算真正向前观察。补齐后，`binance_spot/BTCUSDT` 的 `1m/5m/15m/1h` 已覆盖到 `2026-07-01T06:59:59.999Z`；Long/Short 观察器写入 5 条新 forward observe-only 记录，最新策略决策推进到 `2026-07-01T03:59:59.999Z`。
- 免费源补数边界：Binance spot 主 REST 在当前网络返回 `HTTP 451`，但 `data-api.binance.vision/api/v3/klines` 可用于补当日 spot 1H；Binance futures 主 REST 的 `premiumIndex/openInterest/openInterestHist/long-short/taker` 当前均返回 `HTTP 451`，`data-api.binance.vision` 不代理 futures 指标接口，Binance Vision 当日/昨日 futures metrics zip 也未发布。因此扩展 derivatives sentiment 当前为 `21855` 行，覆盖 `2024-01-01T01:00:00Z` 到 `2026-06-30T01:00:00Z`，但仍落后最新策略决策，且 1H liquidation 完整历史仍只有最近 `720` 小时尾部。
- 审计结论：bar replay 未发现 Long/Short 的 shift 或 derivatives available-time 违规，`long_short_shift_violation_count=0`、`long_short_derivatives_visibility_violation_count=0`；但 overfit 审计仍给出 `research_only_overfit_risk_high_no_paper_no_live`。High-Octane v2 的最佳候选只高出 `40%` 插针剩余本金门槛 `0.011869` 个百分点，属于阈值压线和参数挖掘高风险，不能进入 paper/live。
- 永续执行 gate：重建 `btc_perpetual_execution_evidence_report.json` 后状态仍为 `incomplete_research_only`，当前 blocker 为 `btc_perp_exec_perp_data_covers_latest_strategy_decision`、`btc_perp_exec_depth_aware_slippage_history_verified`、`btc_perp_exec_liquidation_history_or_snapshots_available`、`btc_perp_exec_exchange_runtime_real_or_paper_replay_ready`；总 dashboard 为 `blocked`。
- 处理方式：新增/使用 1H 行情刷新和短周期刷新后再跑 observe-only、bar replay、overfit audit、runtime replay、perpetual evidence 和 dashboard；所有产物继续固定 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`，不得写 paper 队列、不得生成策略骨架、不得接 broker/OMS/order。
- 本次证据：`.\.venv\Scripts\python.exe scripts\research\run_btc_market_1h_data_refresh.py --execute-network --sleep-seconds 0.05 --fetch-limit 1000` 输出 `status=complete_research_only`、`rows_written=7`；`run_btc_short_interval_data_refresh.py` 输出 `rows_written=3240`；`build_btc_strategy_bar_replay_visibility.py` 输出 `check_fail_count=0`；`build_btc_strategy_leakage_overfit_audit.py` 输出 `data_coverage_derivatives_row_count=21855`、`data_coverage_liquidation_one_hour_history_complete=false`；相关合约测试 `15 passed`。
## 2026-07-01 High-yield v2 observe-only 也必须写入 holdout lock stamp

- 场景：用户决定本轮先不集中攻克数据源问题，改为完成非数据类关口，包括确认性 holdout、30/60 天 observe-only、paper/live 安全边界和 runtime replay 审计。
- 现象：`Long/Short Top5` 和 `Attack` 观察器已经在每条观察记录中写入 `holdout_lock`，但 `btc_high_yield_v2_frozen/observations.jsonl` 的新观察行只有理论方向、理论仓位、paper/live=false，没有逐行记录该决策属于 `future_observe_only_0_30d`，也没有显式记录 `selection_use_forbidden=true`。这会让后续复核者难以确认该行不能用于调参、排名、GA fitness、paper candidate 或 live unlock。
- 处理方式：`high_yield_v2_followup` 复用 `btc_observe_only_lock`，默认读取 `configs/btc/research_holdout/btc_confirmatory_holdout_locks.json`；报告和 JSONL 行都写入 `holdout_lock` 状态、`observe_only_violation_count`、`selection_use_blocked_by_lock`，并对旧格式的同一决策行做原地升级，不新增重复观察记录。
- 当前证据：重跑 `.\.venv\Scripts\python.exe scripts\research\run_btc_high_yield_v2_followup.py --derivatives-rows data\external\btc_derivatives_sentiment\free_sources\binance_vision_btcusdt\derivatives_sentiment_1h_extended_attempt.json` 后，输出 `holdout_lock_enforced=true`、`observe_only_violation_count=0`、`selection_use_blocked_by_lock=true`、`new_observation_written=false`、`observation_count=2`、`loss_v3_retained_count=0`，且 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。
- paper runtime 现状：`build_btc_perpetual_paper_runtime_replay_report.py` 仍为 `incomplete_research_only`，因为当前永续路线执行证据未完成、当前信号为空仓、理论订单数为 `0`、模拟成交数为 `0`；这不是失败下单，而是正确的 fail-closed heartbeat。
- 数据问题边界：本轮不继续攻克 OKX/Binance 尾部数据。已确认 `btc_gate_dashboard.json` 仍为 `blocked`，其中 `btc_perp_exec_perp_data_covers_latest_strategy_decision` 等数据/执行证据 blocker 保留到后续集中处理，不得为了消除 blocker 放宽 paper/live。
- 本次验证：`.\.venv\Scripts\python.exe -m pytest tests\contracts\test_btc_perpetual_execution_evidence.py tests\contracts\test_btc_perpetual_data_bundle_manifest.py tests\contracts\test_btc_high_yield_v2_followup.py tests\contracts\test_no_broker_import_in_evidence_builders.py -q` 输出 `15 passed`。
## 2026-07-01 非数据门禁也要有一张总表，不能分散在多个 artifact 里

- 场景：用户决定本轮先不集中攻克数据源尾部、liquidation、mark/index 和 L2 深度覆盖问题，而是先完成其他非数据类关口。
- 现象：未来函数审计、overfit 审计、holdout lock、30/60 天 observe-only、永续执行证据、paper runtime replay 和 dashboard 分散在不同目录；如果只看单个报告，容易把“某一项没有硬失败”误读为“策略可以进 paper/live”。
- 处理方式：新增 `btc_strategy_promotion_readiness_review`，只读现有 artifact，输出三条策略线的晋级准备度矩阵：`long_short_donchian_top5`、`high_octane_attack_sleeve_v2`、`high_yield_donchian_v2`。报告固定 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`paper_candidate_created=false`、`strategy_skeleton_generated=false`，并把数据类 blocker 标记为本轮 deferred，不为了消除 blocker 放宽门禁。
- 当前证据：`.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_promotion_readiness_review.py` 输出 `status=blocked_research_only`、`ready_for_paper_count=0`、`blocked_line_count=3`、`perp_execution_blocker_count=4`、`paper_runtime_blocker_count=3`。矩阵显示 Long/Short Top5 观察 `2` 天、High-Octane v2 观察 `3` 天、High-yield v2 观察 `2` 天，均未满足 30/60 天观察期；High-Octane v2 仍有 `40%` 生存门槛压线和参数挖掘风险；High-yield v2 仍需要单独 bar replay 审计且 loss-control v3 未保留候选。
- 本次验证：`.\.venv\Scripts\python.exe -m pytest tests\contracts\test_btc_strategy_promotion_readiness_review.py tests\contracts\test_no_broker_import_in_evidence_builders.py -q` 输出 `5 passed`。
## 2026-07-01 High-yield v2 纳入 bar replay 后不能被解读为通过，只能暴露执行代理边界

- 场景：非数据门禁总表显示 `high_yield_donchian_v2` 仍缺少当前逐 bar replay / 字段可见性审计覆盖。
- 现象：High-yield v2 的 frozen simulation 不是简单 `raw_signal.shift(1)` 模型，而是状态化资金管理叠加层：波动目标、回撤闸门、强平缓冲、快速止损、funding/cost 近似和同根 high/low 风控都会在同一根 4H bar 内影响理论仓位或收益。如果只套用 Long/Short Top5 的 shift 断言，会把真实风险边界掩盖掉。
- 处理方式：`btc_strategy_bar_replay_visibility` 新增 `high_yield_v2_bar_replay`，逐 bar 记录 frozen High-yield v2 的理论仓位、收益、derivatives `available_time <= decision_time` 可见性、同根 target/return 代理、同根 high/low 风控代理和 `execution_replay_required_before_paper=true`。readiness 总表不再把它标成“缺少审计覆盖”，而是标成“已覆盖但仍有模型边界，必须先做 mark/index + paper runtime replay”。
- 当前证据：真实重跑 `.\.venv\Scripts\python.exe scripts\research\build_btc_strategy_bar_replay_visibility.py --derivatives-rows data\external\btc_derivatives_sentiment\free_sources\binance_vision_btcusdt\derivatives_sentiment_1h_extended_attempt.json` 输出 `status=complete_research_only`、`check_fail_count=0`、`check_warn_count=4`、`high_yield_row_count=5473`、`high_yield_model_boundary_row_count=5473`、`high_yield_prior_exposure_return_violation_count=223`。随后 `btc_strategy_promotion_readiness_report.json` 显示 High-yield v2 的 blocker 从 `high_yield_v2_not_in_current_bar_replay_visibility_audit` 变为 `high_yield_v2_bar_replay_model_boundary_requires_execution_replay`，仍然 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。

## 2026-07-01 High-yield v2 不能只进 bar replay，还必须进 paper runtime replay

- 场景：当前 BTC 非数据门禁已经同时审 `Long/Short Donchian Top5`、`High-Octane Attack Sleeve v2` 和 `High-yield Donchian v2`。如果 paper runtime replay 只读取前两条 observe-only CSV，High-yield v2 即使在 bar replay 中暴露了模型边界，也会在执行层回放中被漏审。
- 现象：bar replay 是字段可见性和逐 bar 信号审计；paper runtime replay 是把 observe-only 理论仓位转换为永续规则下的本地模拟订单、模拟成交、资金费率、手续费和强平缓冲检查。两者不能互相替代。漏掉 High-yield v2 会让 readiness 总表误以为执行层只剩当前空仓/无成交问题，而没有记录 High-yield 本身也需要执行层 replay。
- 处理方式：`btc_perpetual_paper_runtime_replay` 新增 `DEFAULT_HIGH_YIELD_OBSERVATIONS`，读取 `artifacts/btc_high_yield_v2_followup/latest/btc_high_yield_v2_daily_observation_latest.csv`，把 `variant_id`、`decision_time`、`theoretical_side`、`theoretical_exposure` 统一映射为 `high_yield_donchian_v2` 的 observe-only replay row。三条当前策略线都列入 `REQUIRED_OBSERVATION_LINES`，缺任意一条观察记录都必须 fail-closed。
- 当前证据：重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_report.py` 后，报告仍为 `incomplete_research_only`，但 `observation_line_counts` 已包含 `long_short_donchian_top5=10`、`high_octane_attack_sleeve_v2=2`、`high_yield_donchian_v2=2`。当前 14 条观察全是空仓 heartbeat，所以 `theoretical_order_count=0`、`simulated_fill_count=0`，并继续因 `btc_perpetual_paper_runtime_replay_execution_evidence_blocked`、`btc_perpetual_paper_runtime_replay_no_theoretical_orders_current_flat`、`btc_perpetual_paper_runtime_replay_no_simulated_fills` 阻断 paper/live。

## 2026-07-01 历史执行重放演练有模拟成交，也不能替代当前 paper runtime 通过

- 场景：当前 observe-only 最新信号全部为空仓，`btc_perpetual_paper_runtime_replay_report.json` 只能记录 heartbeat，无法产生模拟成交。但这并不等于本地 paper runtime 的成交、手续费、资金费率和强平字段链路已经被真实非空仓样本验证过。
- 现象：如果只看当前 paper runtime，结论会停在“无理论订单/无模拟成交”；如果为了证明模拟成交链路而直接放宽当前执行证据 blocker，又会把诊断演练误升格为 paper gate 证据。
- 处理方式：新增独立 `btc_perpetual_paper_runtime_replay_drill`，从已有 `btc_strategy_bar_replay_visibility_rows.csv` 中抽取本地 selected perpetual bundle 窗口内的历史非空仓样本，按同一套 mark/index/funding/cost/liquidation 函数做模拟成交演练。该演练会显式记录 `ignored_current_execution_evidence_blockers` 和 `paper_runtime_gate_evidence=false`，只证明字段链路可跑通，不证明当前 paper 已可用。
- 当前证据：重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_drill_report.py` 输出 `status=complete_research_only`、`theoretical_order_count=24`、`simulated_fill_count=24`、`risk_approved_count=24`，三条线各 `8` 条历史样本；但 `paper_runtime_gate_evidence=false`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。随后重建 `btc_exchange_runtime_replay_gap_report.json` 后仍为 `incomplete_research_only`，只是新增显示 `paper_runtime_drill_simulated_fill_count=24`，当前 paper runtime blocker 不变。

## 2026-07-01 paper runtime 不能只输出汇总行，必须有事件账本

- 场景：`btc_perpetual_paper_runtime_replay` 和历史 drill 已经能输出 replay row，但 replay row 更像“每个理论信号的一行摘要”。按执行规范，paper execution 不能只记录目标仓位或汇总行，至少要能拆成订单意图、风控检查、熔断、模拟成交、手续费现金流和资金费率现金流。
- 现象：如果没有事件账本，后续很难做 reconcile，也很难判断“无成交”是空仓 heartbeat、被执行证据熔断、被强平缓冲风控拒绝，还是本地模拟器没有填充成交字段。这样会把 paper runtime 的 ready/not ready 解释留在人工口径里。
- 处理方式：`btc_perpetual_paper_runtime_replay` 新增事件账本 CSV 输出。当前 observe-only replay 写 `btc_perpetual_paper_runtime_replay_event_ledger.csv`，历史 drill 写 `btc_perpetual_paper_runtime_replay_drill_event_ledger.csv`。事件类型包括 `flat_heartbeat`、`order_intent_created`、`risk_checked`、`circuit_breaker_triggered`、`simulated_fill`、`fee_cashflow`、`funding_cashflow`；所有事件固定 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。
- 当前证据：重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_report.py` 后，当前 replay 仍为 `incomplete_research_only`，但新增 `event_ledger_row_count=14`，对应当前 14 条空仓 heartbeat。重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_drill_report.py` 后，历史 drill 仍为 `complete_research_only` 且 `paper_runtime_gate_evidence=false`，新增 `event_ledger_row_count=120`，其中 `order_intent_created=24`、`risk_checked=24`、`simulated_fill=24`、`fee_cashflow=24`、`funding_cashflow=24`。重建 runtime gap 后显示 `paper_runtime_drill_event_ledger_row_count=120`，但 readiness 仍为 `blocked_research_only`。

## 2026-07-01 事件账本还要独立对账，不能只看账本文件存在

- 场景：paper runtime 已经能写事件账本，但文件存在不等于可对账。必须检查每个 `candidate_id + decision_time` 事件组里，订单意图、风控检查、模拟成交、手续费现金流和资金费率现金流是否自洽。
- 现象：如果没有独立 reconciliation，可能出现 `fee_cashflow` 没有对应 fill、fill 没有 approved risk、circuit breaker 和 fill 同组并存、事件时间不可解析、paper/live flag 被意外写成 true 等问题，但上层只看汇总行会漏掉。
- 处理方式：新增 `btc_perpetual_paper_runtime_reconciliation`，读取当前 replay 和历史 drill 的事件账本，按事件组检查：flat heartbeat 不能混入 order/fill，fill 必须有 order intent 和 approved risk，fee/funding cashflow 必须有 fill，circuit breaker 不能和 fill 同组，所有事件必须保持 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。runtime gap 新增 reconciliation 摘要；如果未来 paper runtime 本身 ready 但 reconciliation 没过，则新增 `btc_paper_runtime_reconciliation_not_passed` blocker。
- 当前证据：重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_reconciliation_report.py` 输出 `status=complete_research_only`、`event_row_count=134`、`event_group_count=38`、`violation_count=0`、`fill_event_count=24`、`funding_cashflow_event_count=24`，但仍 `paper_queue_write_allowed=false`、`live_unlock_allowed=false`。重建 `btc_exchange_runtime_replay_gap_report.json` 后显示 `paper_runtime_reconciliation_passed=true`、`paper_runtime_reconciliation_violation_count=0`，但 runtime gap 和 readiness 仍因当前 paper replay/执行证据/L2 覆盖等问题保持 fail-closed。

## 2026-07-01 paper/live 熔断状态必须独立汇总，不能靠人工拼多个报告

- 场景：本轮先不继续攻克数据源问题，改做非数据门禁收口。此前 readiness、runtime gap、perpetual execution evidence、paper runtime reconciliation、gate dashboard 都各自有安全字段，但没有一张表直接回答“现在 paper 能不能接单、能不能加仓、能不能 micro-live”。
- 现象：如果只看单个 artifact，容易把“事件账本已对账通过”或“某个研究线没有静态未来函数硬失败”误读成可以进入 paper/live；实际上只要任一上游证据包仍 blocked/incomplete，或者没有人工审批记录，就必须 fail-closed。
- 处理方式：新增 `btc_paper_live_kill_switch_status`，只读取现有 artifact，不拉数据、不接 broker/OMS、不写 paper 队列。它递归检查 paper/live/order/private/broker/OMS 等安全旗标是否被误置为 true，并把所有上游 blocker 汇总成统一策略：`kill_switch_engaged=true`、`cancel_only_mode=true`、`paper_order_intake_allowed=false`、`position_increase_allowed=false`、`micro_live_allowed=false`、`live_unlock_allowed=false`。
- 当前证据：`.\.venv\Scripts\python.exe scripts\build_btc_paper_live_kill_switch_status.py` 输出 `status=fail_closed_research_only`、`decision=btc_paper_live_kill_switch_engaged_fail_closed_no_paper_no_live`、`blocker_count=86`、`true_safety_flag_blocker_count=0`；输出路径为 `artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json`。这说明当前不是“准备实盘但还差一步”，而是所有 paper/live 入口都应保持熔断，直到上游 blocker 和人工门禁全部清除。

## 2026-07-01 paper runtime 模拟成交也必须先过交易所过滤器

- 场景：paper runtime 已能把理论信号转成模拟订单/模拟成交/手续费/资金费率事件，但这还不等于“真实交易所规则下可接单”。OKX SWAP 至少还要检查 instrument 状态、`tickSz`、`lotSz`、`minSz`、`maxMktSz`、最小名义金额、杠杆、强平缓冲、账户/仓位/保证金模式、限频预算和 server time offset。
- 现象：历史 drill 的 24 条非空模拟订单能生成成交字段，但最初它们的 `quantity_btc` 是连续 BTC 数量。按 OKX `ctVal=0.01 BTC/contract` 换算成合约张数后，并没有全部对齐 `lotSz=0.01` 合约；真实交易所过滤器会拒绝这类数量。也就是说，模拟器“能算出成交价和 PnL”不代表订单尺寸符合交易所规则。
- 处理方式：新增 `btc_paper_exchange_rule_preflight`，读取当前 observe-only replay rows、历史 drill rows 和 selected bundle 的 `exchange_info.json`，逐行检查 tick/lot/min/max/leverage/liquidation buffer，并显式把当前 `kill_switch/cancel_only` 下的加仓订单标成拒绝。随后修正 `btc_perpetual_paper_runtime_replay`：保留策略 `target_exposure`，新增 `actual_exposure`、`requested_contracts`、`rounded_contracts`、`sizing_remainder_notional_usdt`，按 OKX 合约 `lotSz` 向下取整后再重算 BTC 数量、名义金额、手续费、funding 和强平缓冲。
- 当前证据：修复后重跑 `.\.venv\Scripts\python.exe scripts\build_btc_perpetual_paper_runtime_replay_drill_report.py`，历史 drill 仍为 `simulated_fill_count=24`、`event_ledger_row_count=120`、`paper_runtime_gate_evidence=false`；重跑 `scripts\build_btc_paper_exchange_rule_preflight.py` 输出 `status=incomplete_research_only`、`current_order_count=0`、`drill_order_count=24`、`order_filter_violation_count=0`、`quantity_lot_violation_count=0`、`kill_switch_reject_count=24`、`blocker_count=10`。随后重跑 `build_btc_paper_live_kill_switch_status.py`，总熔断表仍为 `blocker_count=98`，且 `paper_order_intake_allowed=false`、`position_increase_allowed=false`、`micro_live_allowed=false`。这说明合约尺寸问题已修复，但当前 observe-only 空仓、执行证据、账户/仓位/保证金模式、限频/server time 和人工门禁仍然阻断 paper/live。

## 2026-07-01 风控熔断不能只看状态布尔值，还要做故障注入演练

- 场景：本轮按用户要求先不集中攻克数据问题，继续补非数据类 paper/live 门禁。已有 `btc_paper_live_kill_switch_status` 能回答当前是否 fail-closed，但它主要是汇总上游状态；还缺少“如果理论订单出现，在各种风险故障下是否必然被拦截”的演练证据。
- 现象：只看 `kill_switch_engaged=true`、`cancel_only_mode=true` 这类布尔值，不能证明订单样本在参考价缺失、强平缓冲不足、杠杆超限、限频预算不足、server time 偏移、账户/仓位/保证金模式未验证、人工审批缺失等故障下都会禁止加仓。后续如果某个路径意外把 `position_increase_allowed` 置真，单纯汇总表可能发现得太晚。
- 处理方式：新增 `btc_paper_risk_circuit_breaker_drill`，读取 `btc_paper_exchange_rule_preflight_rows.csv` 的理论订单样本，对 11 类故障逐条注入并要求返回 `block_position_increase`。报告固定 `paper_order_intake_allowed=false`、`position_increase_allowed=false`、`live_unlock_allowed=false`，并接入 `btc_paper_live_kill_switch_status` 作为第 7 个输入源。当前 observe-only 没有理论订单时，历史 drill 样本只能用于诊断本地拦截逻辑，不能替代当前 paper gate 证据。
- 当前证据：`.\.venv\Scripts\python.exe scripts\build_btc_paper_risk_circuit_breaker_drill.py` 输出 `status=complete_research_only`、`scenario_count=11`、`order_sample_count=24`、`scenario_order_check_count=264`、`unexpected_allow_count=0`、`diagnostic_drill_only=true`。随后重跑 `.\.venv\Scripts\python.exe scripts\build_btc_paper_live_kill_switch_status.py`，总表 `source_count=7`、`missing_source_count=0`、`paper_risk_circuit_breaker_drill.status=complete_research_only`，但总体仍为 `fail_closed_research_only`、`blocker_count=98`、`paper_order_intake_allowed=false`、`position_increase_allowed=false`、`micro_live_allowed=false`。

## 2026-07-01 observe-only 30/60 天不能按首尾跨度冒充连续观察日

- 场景：本轮继续推进非数据门禁，目标是让 30/60 天 observe-only 只记录理论信号、不下单，并能被 readiness 和 kill-switch 总表统一审计。
- 现象：三条观察线各自产出 CSV/JSON，但没有横向健康总表时，很容易只看某个 observer 的 `observation_days` 汇总而忽略明细断档。实际检查发现，`btc_bankroll_attack_forward_observer` 曾按首尾时间跨度计算观察天数：`2026-06-28T23:59:59.999000+00:00` 到 `2026-07-01T03:59:59.999000+00:00` 被算成 3 天，但 CSV 明细只有 2 个唯一决策日期。这会在断档时高估 30/60 天观察进度。
- 处理方式：新增 `btc_observe_only_health_report`，统一读取 Long/Short Top5、High-Octane attack、High-yield v2 三条线的报告和观察 CSV，按“唯一决策日期”计算观察日，检查最大日历断档、重复 observation key、report 进度与 CSV 明细是否一致、holdout lock 是否阻止选参用途、paper/live/order/broker/OMS 安全旗标是否保持 false。随后修正 `btc_bankroll_attack_forward_observer._observation_progress`：`observation_days` 改为唯一观察日，另保留 `calendar_span_days` 作为诊断字段。
- 当前证据：修复后重跑 `.\.venv\Scripts\python.exe scripts\research\run_btc_bankroll_attack_forward_observer.py` 输出 `observation_count=2`、`observation_days=2`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`；重跑 `.\.venv\Scripts\python.exe scripts\research\build_btc_observe_only_health_report.py` 输出 `status=blocked_research_only`、`line_count=3`、`minimum_30d_complete_count=0`、`target_60d_complete_count=0`、`continuity_passed_count=0`、`safety_violation_count=0`、`blocker_count=9`。三条线当前都只有 2 个唯一观察日，最大断档 3 天，因此 readiness 继续 `ready_for_paper_count=0`，kill-switch 继续 `paper_order_intake_allowed=false`、`position_increase_allowed=false`、`micro_live_allowed=false`。
## 2026-07-01 micro-live 预检不能靠人工拼多个报告

- 场景：BTC 侧已经有 observe-only health、strategy promotion readiness、paper runtime replay/reconciliation、exchange rule preflight、risk circuit breaker drill、perpetual execution evidence、gate dashboard 和 kill-switch 等多个证据包。只看单个报告时，很容易把“某一项通过”误读为“差不多能小实盘”。
- 现象：当前 `btc_paper_risk_circuit_breaker_drill` 和 `btc_perpetual_paper_runtime_reconciliation` 可以通过，但 observe-only 仍不足 30/60 天，当前 paper runtime 没有模拟成交，kill-switch 仍拉闸，交易所规则/执行证据仍有 blocker，且没有人工批准和本金/订单/杠杆包络。
- 处理方式：新增独立 `btc_micro_live_preflight`，只读现有 artifact，不拉数据、不写 paper 队列、不生成策略骨架、不接 broker/OMS、不访问 private/order endpoint。它把所有上游证据、人工门禁和 micro-live 包络统一成一个 fail-closed 结论；即使未来上游证据全干净，也必须另有人工批准和明确额度，不能自动解锁 live。
- 当前证据：`.\.venv\Scripts\python.exe scripts\build_btc_micro_live_preflight.py` 输出 `status=blocked_fail_closed_research_only`、`decision=btc_micro_live_preflight_blocked_fail_closed_no_live`、`source_count=10`、`missing_source_count=0`、`failed_source_check_count=8`、`upstream_blocker_count=216`、`blocker_count=245`、`observe_only_60d_complete=false`、`paper_runtime_current_simulated_fill_count=0`、`kill_switch_engaged=true`、`manual_approval_recorded=false`、`micro_live_allowed=false`、`live_unlock_allowed=false`。输出路径为 `artifacts/btc_micro_live_preflight/latest/`。
## 2026-07-01 顶层 dashboard 不能漏掉 micro-live 预检

- 场景：`btc_micro_live_preflight` 已经能回答“小额实盘能不能开”，但旧的 `btc_gate_dashboard` 仍只覆盖旧 live readiness、paper validation 和 perpetual execution evidence。如果顶层 dashboard 不读取 micro-live 预检，后续复核时仍可能从旧视图误判状态。
- 现象：真实 dashboard 原来只显示 4 个 perpetual execution evidence blocker，没有显示 `micro_live_preflight_status`、`micro_live_allowed` 或 micro-live 预检 blocker 数。这样虽然 dashboard 仍是 blocked，但用户看不到“新小额实盘预检也明确 blocked”。
- 处理方式：`build_btc_gate_dashboard.py` 新增 `micro_live_preflight` 输入；`gate_dashboard` 新增 coverage、`live_state.micro_live_preflight_status`、`micro_live_preflight_blocker_count` 和固定 `micro_live_allowed=false`。若 micro-live 预检 blocked/fail_closed，只向 dashboard 传播一个摘要 blocker `btc_gate_dashboard_micro_live_preflight_blocked`，不展开全部 blocker，避免与 micro-live 预检互相引用导致日志膨胀。任何 artifact 写出 `micro_live_allowed=true` 也会被 unsafe flag 拦截。
- 当前证据：重跑 `scripts\build_btc_micro_live_preflight.py` 与 `scripts\build_btc_gate_dashboard.py` 后，`btc_gate_dashboard.json` 显示 `coverage.micro_live_preflight=true`、`live_state.micro_live_allowed=false`、`live_state.micro_live_preflight_status=blocked_fail_closed_research_only`、`live_state.micro_live_preflight_blocker_count=246`，顶层 blocker 包含 `btc_gate_dashboard_micro_live_preflight_blocked`。同时 `paper/live/order/private/broker/OMS` 仍全部未开启。
## 2026-07-01 micro-live 与 dashboard 互读时必须过滤自引用 blocker

- 场景：为了让顶层 dashboard 显示 micro-live 预检，`btc_gate_dashboard` 读取 `btc_micro_live_preflight`；而 micro-live 预检为了聚合最终状态也读取 dashboard。如果不处理自引用，`btc_gate_dashboard_micro_live_preflight_blocked` 会被 micro-live 反向当作自身 blocker。
- 现象：接入后重复运行时，micro-live blocker 从 245 增到 246，其中包含 `gate_dashboard:source_blocker:btc_gate_dashboard_micro_live_preflight_blocked`。这不是新的交易风险，而是报告间互相引用导致的噪音；如果继续让 kill-switch/dashboard/micro-live 多层互读，后续 blocker 会越来越难人工复核。
- 处理方式：`btc_micro_live_preflight` 新增 `SELF_REFERENCE_BLOCKER_TOKENS`，当前过滤 `btc_gate_dashboard_micro_live_preflight_blocked`。过滤只针对自引用摘要 blocker，不过滤 dashboard 里来自 perpetual execution evidence 等真实 blocker；同时在 source matrix 里记录 `ignored_self_reference_blocker_count`，防止静默吞掉信息。
- 当前证据：连续运行 `scripts\build_btc_micro_live_preflight.py` 与 `scripts\build_btc_gate_dashboard.py` 两轮后，micro-live `blocker_count` 稳定为 `245`，不再增长；`gate_dashboard` 行显示 `blocker_count=4`、`ignored_self_reference_blocker_count=1`。dashboard 仍保留顶层 `btc_gate_dashboard_micro_live_preflight_blocked`，且 `micro_live_allowed=false`、`live_order_allowed=false`。
## 2026-07-01 当前空仓 heartbeat 不能被误判成 runtime 坏，也不能被当作 paper gate 通过

- 场景：当前 observe-only paper runtime replay 里，三条 BTC 观察线最新信号全部为空仓，因此没有理论订单，也没有当前模拟成交；但事件账本能稳定写出 `flat_heartbeat`。
- 现象：旧报告把 `no_theoretical_orders_current_flat` 和 `no_simulated_fills` 都作为硬 blocker 往上传，容易让人误解为 runtime replay 坏了。实际上这是一种健康的空仓心跳状态，只是还没有“当前真实信号触发后的 paper 成交样本”。
- 处理方式：`btc_perpetual_paper_runtime_replay` 新增 `current_flat_heartbeat_healthy`、`trade_execution_evidence_available`、`trade_execution_evidence_pending_reason`、`paper_runtime_health_status` 和 `non_blocking_pending_conditions`。当前空仓不再输出 `btc_perpetual_paper_runtime_replay_no_theoretical_orders_current_flat` 硬 blocker，但 `btc_perpetual_paper_runtime_replay_no_simulated_fills` 仍保留为 paper gate 交易样本缺失 blocker。
- 上层联动：`btc_exchange_runtime_replay_gap`、`btc_strategy_promotion_readiness` 和 `btc_micro_live_preflight` 同步透传该状态，并新增 warning `paper_runtime_currently_flat_heartbeat_healthy_but_trade_sample_missing`。这样 readiness/micro-live 能看到“运行心跳健康、交易样本未出现”，但仍然 fail-closed。
- 当前证据：重建后 `btc_perpetual_paper_runtime_replay_report.json` 为 `status=incomplete_research_only`，blocker 只剩 `btc_perpetual_paper_runtime_replay_execution_evidence_blocked` 和 `btc_perpetual_paper_runtime_replay_no_simulated_fills`，`current_flat_heartbeat_healthy=true`，`paper_runtime_health_status=current_flat_heartbeat_healthy_waiting_for_trade_sample`。重跑 34 个相关合约测试通过；paper/live/order/broker/OMS 仍全部不允许。

## 2026-07-01 交易所规则预检也要区分当前空仓无订单样本和过滤器失败

- 场景：`btc_paper_exchange_rule_preflight` 会读取当前 observe-only replay rows 和历史 drill rows，检查 OKX tick/lot/min size/强平缓冲/kill-switch 等规则。当前信号全空仓时，当前 rows 存在，但没有当前理论订单。
- 现象：行级 preflight 已经把空仓行标成 `no_order_flat_or_heartbeat`，但报告级只输出 `btc_paper_exchange_rule_no_current_theoretical_orders_to_validate`，上层 micro-live 容易把它看成“交易所过滤器未通过”，而不是“当前空仓，所以还没有当前订单样本可检查”。
- 处理方式：`btc_paper_exchange_rule_preflight` 新增 `current_flat_no_order_healthy`、`current_order_sample_available`、`current_order_sample_status` 和 `current_order_sample_pending_reason`。当前空仓仍保留 no-current-order blocker，不能进入 paper；但报告会说明这是 `current_flat_heartbeat_waiting_for_order_sample`。`btc_micro_live_preflight` 同步改用 `paper_exchange_rule_preflight:current_flat_waiting_for_order_filter_sample`，不再把当前 flat 误写成普通 `no_current_theoretical_orders`。
- 当前证据：重建后 `btc_paper_exchange_rule_preflight_report.json` 显示 `current_order_count=0`、`current_flat_no_order_healthy=true`、`current_order_sample_status=current_flat_heartbeat_waiting_for_order_sample`、`current_order_sample_pending_reason=current_observe_only_signal_flat_waiting_for_exchange_filter_sample`。`btc_micro_live_preflight_report.json` 中新 blocker 已出现，旧的 specific `paper_exchange_rule_preflight:no_current_theoretical_orders` 已不再出现；`paper_order_intake_allowed=false`、`micro_live_allowed=false`、`live_unlock_allowed=false` 不变。

## 2026-07-01 OKX server time offset 可以用公共接口验证，但偏移超阈值必须继续 fail-closed

- 场景：`btc_paper_exchange_rule_preflight` 的账户/运行时证据里有 `btc_paper_exchange_rule_server_time_offset_not_verified`。这项不需要私钥，可以用 OKX 公共 `/api/v5/public/time` 验证本机时间与交易所 server time 的偏移。
- 现象：单次请求可能受网络路径延迟影响，不能直接用一条样本放行；但如果偏移持续超过阈值，也不能为了推进 paper 盘而放宽。真实下单路径里时间偏移过大会影响鉴权时间戳、延迟诊断和事件对账。
- 处理方式：新增 `btc_okx_server_time_preflight`，默认 dry-run，只有 `--execute-network` 才访问 OKX public REST；固定 `api_key_used=false`、`private_endpoint_used=false`、`order_endpoint_used=false`。真实运行时采 5 个样本，选择最小 RTT 样本并记录 median/max offset；`btc_paper_exchange_rule_preflight` 读取该 artifact，只有 `server_time_offset_verified=true` 且无 blocker 时才解除 server time blocker。
- 当前证据：`.\.venv\Scripts\python.exe scripts\build_btc_okx_server_time_preflight.py --execute-network --sample-count 5` 成功访问公共接口，但输出 `status=incomplete_research_only`、`server_time_offset_verified=false`、最优样本 `offset_ms=4192.357`、`round_trip_ms=1635.367`、`valid_sample_count=5`、blocker 为 `btc_okx_server_time_offset_exceeds_threshold`。重建 `btc_paper_exchange_rule_preflight_report.json` 后 `server_time_preflight.present=true`，但 `btc_paper_exchange_rule_server_time_offset_not_verified` 仍保留；`paper_order_intake_allowed=false`、`live_unlock_allowed=false` 不变。

## 2026-07-01 paper 账户运行环境不能靠默认配置猜测，必须有人工证明

- 场景：`btc_paper_exchange_rule_preflight` 除了 tick/lot/min size、强平缓冲和 kill-switch 外，还需要确认 OKX paper 账户运行环境，包括账户模式、仓位模式、保证金模式、限频预算、人工批准和 server time 偏移。这里不能因为本地代码能生成理论订单，就默认交易所侧环境已经合格。
- 现象：账户模式、仓位模式、保证金模式和限频预算不是 public market data 能证明的事实；如果缺少人工证明文件，系统必须 fail-closed。当前 OKX public server time 预检也未通过，最佳样本 offset 约 `4192ms`，因此 server time blocker 也必须保留。
- 处理方式：新增 `btc_paper_account_runtime_attestation` 研究证明包，只读取 `configs/btc/paper_runtime/account_runtime_attestation.json` 这类人工证明文件，不访问 private/order endpoint，不接受 `api_key`、`secret`、`passphrase`、`token`、`withdraw` 等疑似密钥字段。`btc_paper_exchange_rule_preflight` 改为读取该证明包，而不是硬编码账户运行环境 blocker。
- 当前证据：缺少证明文件时，`scripts/build_btc_paper_account_runtime_attestation.py` 输出 `status=blocked_fail_closed_research_only`，blocker 包括账户模式、仓位模式、保证金模式、限频预算、人工批准和证明时效；`scripts/build_btc_paper_exchange_rule_preflight.py` 仍为 `status=incomplete_research_only`，`current_flat_no_order_healthy=true`，但 `paper_queue_write_allowed=false`、`live_unlock_allowed=false` 不变。相关合约测试 `20 passed`，编译通过。

## 2026-07-01 paper 凭证权限也必须证明，模板不能默认通过

- 场景：用户目标里包含 paper 盘和 micro-live gate，交易所 API key 策略要求 data、paper、live 分离，且不能有提现类权限。即使暂时不写入真实密钥，paper 账户运行环境证明也必须记录 paper 交易凭证权限是否被人工核对。
- 现象：只验证账户模式、仓位模式、保证金模式和限频预算还不够；如果没有证明 paper 凭证是 `paper_trade`、读/交易权限符合预期、资金转出类权限关闭、IP 白名单已配置、live 凭证未加载，paper gate 仍然证据不足。模板如果填了 schema 和 OKX/BTC-USDT-SWAP 但默认全是 false，也不能被误判为通过。
- 处理方式：`btc_paper_account_runtime_attestation` 新增 `credential_permissions_verified`，并要求 `credential_permissions` 中的 `paper_trade`、read/trade、cashout disabled、IP allowlist、live credential not loaded 全部人工确认为 true 才能通过。新增 `configs/btc/paper_runtime/account_runtime_attestation.template.json` 和 README，模板只允许填人工确认结果和证据代号，不允许写入任何 API key、secret、passphrase、token 或截图敏感内容。
- 当前证据：模板默认运行仍为 `blocked_fail_closed_research_only`，`sensitive_fields_detected=[]`，blocker 包含 `btc_paper_account_runtime_credential_permissions_not_verified`；重建 `btc_paper_exchange_rule_preflight_report.json` 后 `paper_credential_permissions_verified=false`，blocker 包含 `btc_paper_exchange_rule_credential_permissions_not_verified`。相关合约测试更新为 `21 passed`，`paper_queue_write_allowed=false`、`live_unlock_allowed=false`、`micro_live_allowed=false` 不变。

## 2026-07-01 新目标收窄后，先确认未来函数审计和 holdout 锁，而不是继续扩执行证据

- 场景：目标被收窄为两项：代码级未来函数审计，包括逐 bar replay 和字段可见性报告；确认性 holdout 锁定，禁止该数据继续参与选参数。原先正在推进的永续执行证据、paper/micro-live 证据不再是当前目标的工作重点。
- 现象：`btc_strategy_bar_replay_visibility` 重跑后，Long/Short Donchian Top5 的 `current_exposure_is_previous_raw_signal`、`current_raw_signal_binds_next_bar_exposure` 和 derivatives `available_time <= decision_time` 检查全部通过，硬失败为 0。High-Octane v2 和 High-yield v2 未发现 derivatives 可见性硬违规，但报告明确保留同根执行近似、同根 high/low 风控代理、40% 阈值压线和 prior-exposure return 边界 warning，因此不能被解释为 paper/live 证据。
- 处理方式：重跑 `scripts/research/build_btc_strategy_bar_replay_visibility.py`、`scripts/research/build_btc_confirmatory_holdout_lock.py` 和 `scripts/research/build_btc_strategy_leakage_overfit_audit.py`。holdout 锁写入 `configs/btc/research_holdout/btc_confirmatory_holdout_locks.json`，包含 3 个锁定窗口：Long/Short 已看过确认窗口、High-Octane 已被选择过程消耗的历史窗口、2026-06-28 之后的 future observe-only 窗口。`selection_window_violations` 对 2026-06-29 之后参数搜索返回 future observe-only lock 违规。
- 当前证据：bar replay 报告 `status=complete_research_only`、`check_fail_count=0`、`long_short_row_count=27365`、`long_short_shift_violations=0`、`long_short_derivatives_available_violations=0`；holdout lock 报告 `status=complete_research_only`、`lock_count=3`、`latest_common_history_end=2026-06-28T23:59:59.999000+00:00`、`self_check_violation_count=7`；综合审计 `selection_use_blocked_by_lock=true`、`paper_queue_write_allowed=false`、`live_unlock_allowed=false`。相关合约测试 `20 passed`，编译通过。
