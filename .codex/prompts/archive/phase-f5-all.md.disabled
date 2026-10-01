你是 QuantStation VNEXT 的总控 Codex Agent。

当前项目状态：
- Phase F 大部分模块已经完成
- live/execution/risk/monitoring/scripts/backtest/engine 均已有模块和测试覆盖
- 当前目标不是继续加策略，不是接 IBKR，不是开启真实实盘，而是完成 Phase F.5 Integration Closure
- 目标：把 LiveRuntime、PaperRuntime、ShadowLive、EventDrivenEngine、Broker、OMS、Risk、Reconciliation、CLI 串成一条真正可运行、可测试、可恢复、不会误下真实订单的链路

请一次性完成以下任务。可以 spawn subagents：
- quant_architect：先只读审查并给出集成边界
- runtime_integration：实现 runtime 统一抽象和生命周期
- engine_broker：实现 engine broker 注入、streaming/event 输入
- qa_risk：补齐故障测试和 live safety 测试
- cli_devops：补 CLI / report / script 集成

硬性安全规则：
1. 不允许开启真实 live order。
2. 不允许删除、绕过、弱化 live readiness gate。
3. 不允许修改策略 alpha 逻辑。
4. 不允许修改 frontend。
5. 不允许提交或读取 .env、API key、broker key、真实账户敏感日志。
6. live 模式必须默认禁止提交真实订单。
7. shadow_live 模式必须无论如何不能提交真实订单。
8. paper 模式只能提交 paper broker / simulated broker 订单。
9. 所有新增 live 相关命令必须默认 dry-run 或 shadow，不得默认真实下单。
10. 所有订单必须仍然经过 OMS、Risk、Reconciliation、KillSwitch。

需要解决的已知问题：

A. 代码质量问题：
1. shadow_live.py: PaperBroker 类型未显式导入，当前可能被 from __future__ import annotations 掩盖。
2. paper_runtime.py: 不能直接调用 kill_switch._trigger() 私有方法，需要提供公开 API，例如 trigger()/trip()/activate()，并改造调用方。

B. 8 个集成缺口：
1. EventDrivenBacktestEngine 硬编码 SimulatedBroker，无法注入真实 broker / paper broker / readonly broker。
2. Engine 只接受 list[Bar]，缺少 streaming/event market data 接口。
3. CLI 缺 quant-us live 子命令。
4. TradingMode.LIVE 枚举已定义但未真正接入运行链路。
5. LiveRunner / PaperRuntime / ShadowLiveRunner 存在重复实现，缺少统一运行时抽象。
6. Strategy ABC 只有 on_bar，缺少 tick/stream 适配层；不要强行改所有策略，可以做 adapter。
7. 回测/运行引擎缺少连接健康检查概念。
8. 缺统一 LiveRuntimeConfig。

请按以下目标实现：

目标 1：修复代码质量问题
- 显式处理 PaperBroker 类型导入，优先使用 TYPE_CHECKING 或直接安全导入。
- 给 KillSwitch 增加公开触发 API。
- paper_runtime 不再调用 _trigger() 私有方法。
- 增加测试覆盖。

目标 2：统一 LiveRuntime 抽象
建议新增或对齐以下概念，具体文件名可根据现有项目结构调整：
- quant_us/live/runtime.py
- quant_us/live/runtime_config.py
- quant_us/live/runtime_state.py
- quant_us/live/runtime_events.py
- quant_us/live/modes.py

LiveRuntime 生命周期至少包括：
- bootstrap()
- load_config()
- check_readiness()
- reconcile_on_start()
- start_market_data()
- run_cycle()
- submit_orders()
- poll_orders()
- sync_fills()
- update_ledger()
- emit_metrics()
- reconcile_on_close()
- shutdown()

模式要求：
- paper：paper account / paper broker / simulated broker，允许 paper submit
- shadow_live：真实行情或真实账户只读，但绝不允许真实订单
- live：保留接口，但必须 gate blocked，除非 readiness 全部 PASS + 显式 confirm flags + config allow_live_orders true

目标 3：Engine 支持 broker 注入与 streaming/event 输入
- 移除硬编码 SimulatedBroker。
- 支持 broker 注入，例如 constructor injection 或 set_broker()。
- 保留 run_batch/list[Bar] 的确定性回测能力。
- 新增 run_streaming()/on_market_event() 风格接口，能够接 MarketEvent 或 MarketDataSource。
- 不破坏现有回测测试。
- PnL 仍然必须由 fills/ledger 推导。
- 增加连接健康检查或 runtime health status 概念，但不要让回测依赖真实网络。

目标 4：Strategy streaming adapter
- 不要大规模重写所有策略。
- 保留 on_bar。
- 增加 adapter，让 streaming market event 可以转成 on_bar 调用。
- 若需要 tick 级接口，只添加可选 on_tick，默认 fallback 到 on_bar，不要破坏现有策略。

目标 5：CLI 增加 quant-us live
根据现有 CLI 框架实现，不确定项目入口时先搜索。
至少提供：
- quant-us live readiness
- quant-us live shadow
- quant-us live dry-run

真实 live start 命令可以存在，但必须强保护：
- 默认禁止
- 必须 --confirm-live
- 必须 allow_live_orders true
- 必须 live_readiness_gate PASS
- 必须 paper runtime / shadow live 证明文件存在或 gate 通过
- 没有这些条件时直接拒绝，并给出原因

目标 6：端到端集成测试
新增或补齐以下测试：
1. test_runtime_quality_imports_and_killswitch_public_api
2. test_engine_broker_injection
3. test_engine_streaming_market_events
4. test_paper_runtime_full_day_with_simulated_broker
5. test_runtime_restart_no_duplicate_order
6. test_shadow_live_cannot_submit_real_order
7. test_reconciliation_fail_blocks_new_orders
8. test_live_command_default_is_safe
9. test_trading_mode_live_is_gate_blocked
10. test_strategy_stream_adapter_falls_back_to_on_bar

目标 7：文档和报告
新增或更新：
- docs/PHASE_F5_INTEGRATION_CLOSURE.md 或 PHASE_F5_INTEGRATION_CLOSURE.md
- 说明完成了哪些集成点
- 说明仍然不允许真实 live order
- 说明如何运行 paper / shadow / readiness
- 说明下一步进入 Paper Production Loop / Shadow Live 验收前的条件

工作方式：
1. 先让 quant_architect 只读审查实际目录结构，确认文件范围。
2. 再让 runtime_integration、engine_broker、qa_risk、cli_devops 分工实现。
3. 各 agent 不要互相改同一文件；如果必须改同一文件，由主 agent 整合。
4. 每完成一组改动就运行相关测试。
5. 最后运行全量测试，优先使用项目现有测试命令；如果不确定，先检查 pyproject.toml / package.json / Makefile / README。
6. 如果全量测试太久，至少运行 live/execution/risk/backtest/cli/integration 相关测试，并说明未运行的原因。

最终交付：
1. 修改代码并通过测试。
2. 输出变更摘要。
3. 输出新增/修改文件列表。
4. 输出测试命令和结果。
5. 输出仍未完成的事项，但不要把“真实 live order”作为本阶段完成目标。
6. 明确说明：当前系统完成 Phase F.5 后，下一步是 Paper Production Loop 连续运行，不是直接实盘。

验收标准：
- 当前已知 2 个代码质量问题被修复。
- 8 个集成缺口至少完成 1-5 项核心闭环，6-8 项有代码或 adapter 支撑。
- paper / shadow / live 三种模式有统一配置入口。
- shadow_live 不存在真实下单路径。
- live 默认 gate blocked。
- EventDrivenEngine 能注入 broker。
- Engine 支持 batch 和 streaming/event 输入。
- CLI 有 live readiness / shadow / dry-run。
- 端到端 simulated paper day 可跑。
- 重启不重复下单有测试。
- reconciliation fail 禁止开新仓有测试。
- 全部相关测试通过。
