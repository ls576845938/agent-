# 阅读续接与未验证发现

最新状态：固定基准2515文件／808857行全部EOF。下文早期断点为追加式历史记录，不是当前未读清单；以末尾“全量源码阅读收束”和catalog为准。整体重评见REASSESSMENT.md，运行／独立发布尚未验收。

基准：7403c5331057cbba21b9c013b8d6c0ee4c517d91。这里记录的是源码审阅，不是已复现事故；未执行修复、研究、gate 或交易。

## 已落盘完整阅读

逐文件范围与 blob 见 [catalog](../../../frontend/src/workspaces/architecture/catalog.json)，不要从本文件的叙述推算覆盖。
本快照：340 文件 / 113,588 行完整 EOF；含主代理和只读分工，不称主代理逐一亲读全部。
清单范围 2,515 文件 / 808,857 行。脚本获取文件元数据不计阅读。

批次涵盖：quant_shared；BTC portfolio/risk/application/runtime/adapters 及7个OMS基础文件；
US core/strategies/risk/backtest/regime/signals/portfolio；CN portfolio；前端90个TS/TSX；
Qlib适配器；后台Alpha Factory；research已读52文件；少量兼容入口。
其余文件状态以清单为准。

## 尚未 EOF 的明确续接点

- quant_crypto/oms/okx_demo_paper_runtime.py：连续实际读完 1–15,120，EOF=18,423；继续15,121。尚未把这15,120行计入完整文件覆盖。7个完整OMS文件见 btc-oms-03a。
- quant_us/research：已完成52/70，含 evidence_registry 和 automation 全部；余18个BTC/ETF研究文件刚开始新批，不计本快照。
- 前端 CSS、JS、构建/测试未全部通读；90 TS/TSX EOF不是整个前端已读完。
- backend多数服务、A股非portfolio代码、数据、测试、脚本、工具等仍未读完。
- 如果后续线程已推进，应先读取更新的 catalog / 附加审阅记录再从这里续接，不能把本快照计数当实时进度。

后续源码改变只对改变的 blob 重审；本 UI 票据新增文件以及 App / Workbench 接线不是基准中的已读代码。

## 研究与统计口径

| 来源 | 已观察到的代码事实 | 尚需核对的边界 |
| --- | --- | --- |
| quant_shared/alpha_factory/engine.py | trainer注入、有界搜索、冻结冠军后审计 | 不是自动promotion；训练器输出与执行账本分开 |
| integrations/qlib_adapter/research_pipeline.py:87 | 仅crypto生成七层trace | factory trial不自动生成同一trace |
| integrations/qlib_adapter/research_trace.py:328 | regime为diagnostic，volatility_target_applied=false | 不能显示为在线环境调仓模型 |
| quant_us/research/orchestration/research_execution_pipeline.py:145 | Qlib预测→PyPortfolioOpt→TargetPosition→事件回测链已存在；入口会重写导入/manifest | 与已sealed普通Qlib run的兼容性；WF是既有目标切窗，不是每窗重训 |
| quant_us/research/portfolio_sim_bridge.py:176 | 模拟桥固定合成增长/换手，能产出PORTFOLIO_PASS | 不得当真实回测或账本收益 |
| quant_us/research/portfolio_research/stress.py:209 | run_all使用固定seed随机收益 | 情景演示不等于真实组合压力证据 |
| quant_us/research/portfolio_research/correlation.py:192 | 使用scorecard相似度代理 | 不是实际收益相关矩阵 |
| quant_us/research/features/asof.py:20 | PIT校验主要未来日期与对齐约束 | 不等同逐决策available_time审计 |
| quant_us/research/features/snapshot.py:92 | snapshot ID不包含完整symbols/window/data version，125可覆写 | 版本化输入和覆盖风险待回归 |
| quant_us/research/orchestration/queue.py:223 | 调用ExperimentManager.inspect并引用其模块没有的BatchBacktestRunner | 定向复现；dry_run还会落completed，不能等同研究完成 |
| quant_us/research/validation.py:284 | DSR/PSR/PBO/多重检验实现存在 | 缺return时用成本情景收益、Sharpe后备252年化等口径待核 |
| quant_us/research/automation/factor_mining.py:143 | FactorEvaluator→去相关→单因子/篮子/共识→编译器 | 本文件不调用Qlib；负IC绝对分数与固定降序/正权重方向待核 |
| quant_us/research/automation/pipeline.py:397 | 日期切半回测；regime_filter是参数注入 | 不是本层重训/purge；是否实际过滤看消费者 |
| quant_us/research/automation/evidence_materializer.py:216 | 已有指标转completed摘要 | 不代表重新执行WF或成本实验 |
| quant_us/research/automation/promotion_gate.py:669 | 统计门槛及账本artifact hash/绑定/摘要检查 | 本文件不校验current HEAD，不重算原始fill/cash PnL；非CN通用gate |
| quant_us/research/automation/report_gen.py:140 | 生成报告会调用gate.evaluate，可能写入 | 不应视为纯只读页面查询 |
| quant_us/research/paper_review_bridge.py:237 | 人工approve记录paper-only审批，gate_snapshot仍paper_execution_authorized=false | 审核与执行权严格分开 |

## 策略、组合与运行

| 来源 | 已观察到的代码事实 | 尚需核对的边界 |
| --- | --- | --- |
| quant_us/strategies/decision_service.py:59 | 共享Context、CAS、身份和重复决策保护已消费 | 不同专用模拟器未必经过同一服务 |
| quant_us/strategies/donchian_breakout_strategy.py:37 | 通道含当前high/low，再要求close突破 | 合法OHLC下不可达入场，待隔离测试，不在此改信号 |
| quant_us/strategies/factory.py:85 | 参数白名单只取dataclass字段 | 三个非dataclass策略构造参数的配置路径待核 |
| quant_us/backtest/engine.py:291 | allocation combine未传account/prices | 不走账户换手缩放分支 |
| quant_us/backtest/engine.py:410 | 按date取feature；UnifiedRunner桥返回datetime键 | 独立runner路径不同，不能断言所有因子回测失效 |
| quant_us/portfolio/construction/allocator.py:89 | 缩放后归一化 | 可能抵消cap/整体波动降仓 |
| quant_us/portfolio/construction/backtest.py:116 | 简化净值/回撤与序列对齐 | 不是逐fill组合回放 |
| quant_us/backtest/crypto_event.py:955 | 全样本波动回填/中位数、间断净值regime切片 | 事后诊断，不是在线环境策略 |
| quant_us/backtest/us_etf_26_canonical.py:1224 | 年度切片称walk-forward | 不等同每窗重新训练 |
| quant_us/backtest/replay.py:129 | 比较指标和数量 | 不是完整事件内容一致验证 |
| quant_us/backtest/ledger_pnl.py:277 | 实现fill/调整重放；部分缺价用零/成本，空对账可passed | 不能以布尔字段代替充分账本验证 |
| quant_crypto/application/btc_demo_production_composition.py:1065 | 默认Demo装配T2/T3/Guardian | 本批未发现默认消费者使用共享forecast乘法公式；不改默认目标 |
| quant_crypto/application/btc_demo_production_composition.py:721 | short protection适配取tpTriggerPx | 待定向验证，不宣称运行事故 |
| quant_crypto/application/runtime_risk_guardian.py:921 | drawdown缺失未见同类unknown blocker | 与消费者/风控配置一起回归 |
| quant_crypto/oms/okx_demo_paper_runtime.py:9390 | 将snapshot容器包成runtime store UOW并核对同次snapshot hash | 不是此函数独立由fills/cash推导positions/PnL；文件尚未EOF |
| quant_crypto/oms/okx_demo_paper_runtime.py:13822 | 恢复先加入持久pending IDs，再调用严格intersection helper | 不能把helper注释当整个恢复owned集合定义；文件尚未EOF |

## 前端与清理

前端分工审阅确认：研究台、组合动作、人工复核分属不同action层；BTC Demo V2有后端合同、fence、幂等、人工确认；
美股页仍独立编排数据/回测/压力/WF/promotion/paper；A股页为只读投影。入口操作能力不等于权限已开放。

- USEquityWorkspace.tsx:2723、2615：缺overview/reconcile显示“开放”，缺paperStatus显示“正常”。这是UI条件事实，不代表服务端授权。
- OptimizationPanel.tsx:116：缺失图点使用整条序列最后有效值补位；不是真实观测。
- ExperimentList.tsx:114：独立执行/评分动作与父action guard关系待查后端，不推断当前绕过。
- QlibDecisionTrace的安全字段与Factory严格false校验不完全一致；没有证明实际收到不安全响应。
- StrategyModulesWorkspace：未引用的MARKET_STATE_CARDS/FLOW；ResearchPortfolioWorkspace：未用parseJsonObject/paperReadyCount/WorkbenchNotice；PreviousResearchDashboard：未用paperReadyCount/WorkbenchNotice。
- BTC composition的_position_contracts/_fresh_bool/_derive_protective_capabilities_legacy及gate rebuild的_integer_path：限定Python名称搜索只见定义，动态兼容待查。
- **未删除任何上述代码**。旧版研究路由、crypto_event、旧paper回放/恢复、on_bar兼容接口和ETF builder均有消费者，不当作无用代码清理。

这些发现用来支撑最终整体评估，不会自动启动局部修复、M1或M2—M4。所有交易权限保持false。

## 关机恢复快照：541 EOF / 223,245 行

审阅对象仍为 `7403c5331057cbba21b9c013b8d6c0ee4c517d91`。上文340文件是较早已提交快照；本节与更新的catalog接续它，不把旧断点当当前进度。

从关机前已经实际收到的连续EOF阅读与只读分工交付恢复201文件 / 109,657行。逐文件路径、blob、行数、reader、`read_ranges`已写入catalog，批次为`shutdown-recovered-eof-20260910`。仅有目录扫描或不完整断点的文件不补为EOF。范围仍是2,515文件 / 808,857行，**全仓审阅未完成**，分工阅读不冒称全部由主代理亲读。

恢复范围：

- 主代理：`backend/app`余43个Python文件全部EOF；`quant_us/data/connectors/{base,factory,yfinance_data}.py`3个EOF。
- BTC只读分工：OMS余9个；data16、backtest3、exchange2；monitoring21、security2、根`__init__`1个；research中`long_short_trend_following_lab`、`ga_factor_mining`、`regime_conditional_5m_alpha_search`、`weak_regime_short_lab`共4个。
- 通用只读分工：`quant_us/research`余18个（该目录70个Python文件全部EOF）；US application7、execution17、factors12；CN余43个（CN47个Python文件全部EOF）。

### 已确认的边界与静态发现（不等于复现／修复）

| 来源（行号均为7403） | 源码事实 | 对整体架构评估的约束 |
| --- | --- | --- |
| backend/app/api/app_factory.py:2788、5051 | 装配BTC/US/CN只读投影、研究服务、任务队列、Alpha工厂及专用运行路由 | 后端不是只有一个统一研究路径；旧研究API仍有真实消费者 |
| 同文件:1862、3569 | 旧注册表可在解析/schema检查后写PASS/STABLE；部分查询异常返回空数组 | 注册表可读、证据充分、当前HEAD一致必须分开 |
| 同文件:4757 | 旧robustness入口缺收益时用seed42生成序列，邻近参数分数也有随机生成；response无对应synthetic字段 | 不能把此类报告当观测到的稳健性证据；本轮不运行入口 |
| backend/app/services/data_management.py:1001、1196、1522 | 清理后可固定质量分100；部分同步返回completed；manifest指向mutable SQLite | 同步完成不等于完整/合格/PIT；不可变声明要核对实际字节来源 |
| 同文件:43、728、1571 | Coinbase的4h请求映射21600秒，再按4h标识解析 | 周期语义存在静态不一致，未运行采集或修复 |
| backend/app/services/research_gate.py:587、628、663 | portfolio分支只做优化、ledger_verified=false，仍可产生服务层候选；明确不授权paper | 服务候选不能替代执行门禁或统一样本外验收 |
| backend/app/services/backtests.py:1519、1539、1651 | 事后regime用全样本波动/分位及窗口特征，按状态取不连续价格再模拟 | 不是可用于当时决策的在线环境模型；M1应显式校验available_time |
| 同文件:1903、2597、2883 | 通用向量模拟独立于event/fill路径；WF先算全段信号再切窗；CPCV也存在切片模拟 | “事件驱动”“walk-forward”标签不能证明共享策略重训与完整账本闭环 |
| 同文件:1991、2026、2043 | breaker下限0.1；连续反向信号被min-hold拒绝时计数可能不递增；换手分母依赖整段长度 | 记录为待隔离回归的统计/行为问题，不改默认BTC |
| backend/app/domain/strategy_registry.py:391、539、564、588 | FundingSentiment为价格偏离；FactorRank为时序；EarningsDrift不消费财报；ETFRotation为单资产动量 | 模块名字或机制说明不代表真实输入/算法已经实现；22个策略均注册，不整批删除 |
| backend/app/services/btc_demo_runtime.py:892、908、913 | 实际装配production composition、dispatcher、controller及权威bundle | 默认BTC风险/OMS/保护/账本链保留；不把研究模拟当默认链 |
| 同文件:1167、1692、1829 | 部分status查询会协调/更新durable operation或operator状态 | HTTP GET／status命名不能一概声称完全只读 |
| 同文件:1705、1771、2206、2236 | payload整理移除expected_guardian字段，后续ack/recover又读取这些字段 | 控制台动作存在静态合同疑点，需失败优先fixture验证，未调用真实动作 |
| backend/app/services/btc_public_market_stream.py:143、162 | public SSE独立于策略/订单；全局新鲜度会被成交消息更新 | 显示行情不等于策略兼容输入；每通道/事件时效须独立 |
| backend/app/services/us_quant.py:244、295 | 本地reconcile将同一ledger映射给PaperBroker；unified入口仅传部分参数 | 内部一致性不等于独立券商对账，不能用UI参数数量判断底层已消费 |
| backend/app/services/us_ibkr_runtime.py:690 | 显示层safe_to_submit依赖provider摘要，顶层执行授权仍false | 只读展示与最终执行gate不同，继续查live消费者 |
| backend/app/services/market_data.py:280、492 | 固定质量机制说明；部分预期索引用工作日/连续时钟而非完整交易日历 | 不得把说明图与实际数据可用性合并为绿灯 |
| quant_crypto/data/dataready相关实现 | 消费者可核验不可变字节/PIT但只接纳quality_checked，拒绝research/backtest权限声明 | 数据层验收等级不自动成为研究或交易权限 |
| quant_crypto/research/ga_factor_mining.py:307、1128、1269 | cutoff/event_time合并不等于逐历史available_time；重叠4h标签可能按小时复利 | 共享工厂消费AST生成器，不等于旧miner结果已适合新工厂验收 |
| quant_crypto/monitoring/okx_demo_execution_watchdog.py:42、337 | 本地持久状态监督与保护单检查，只可写自己的报警，不续dead-man/下单 | 已有监督实现，但未证明当前后台常驻；remote supervisor另含私有GET，本轮禁运行 |
| quant_crypto/monitoring/replay_engine.py:113 | 即使前置blocker存在仍调用注入replay_fn | replay接口不是执行沙箱，固定seed不证明没有外部访问 |
| scripts/build_btc_paper_validation_artifacts.py:213（仅定位，未EOF） | replay_fn返回原outputs；hash计算后再补policy字段 | 原输出自比较不证明策略重算；最终hash一致性需独立验证 |
| quant_crypto/monitoring/artifact_schema.py:46、completion_audit.py:139 | schema/hash形状与status检查不重算内容，允许status可能压过内部blocker | 报告组装完整不等于运行或当前HEAD证据完整 |
| quant_crypto/monitoring/btc_dirty_worktree_boundary.py:427、632 | 可扫描dirty全文含敏感配置，Git失败返回空；仍有旧gate消费者 | 不作为本任务预检，不运行，不未经迁移就删 |
| quant_crypto/security/api_key_audit.py:69 | 脱敏事实合同，不是权限查询；部分布尔/venue/时间校验待核 | 绝不根据该报告擅自读取凭证或授予交易权限 |
| quant_us/application/us_equity_domain_read_model.py:44、us_equity_final_paper_readiness.py:301 | 只读投影与离线有锁证据发布各自独立；最终只是架构师审核候选 | 不将gate builder接到GET；paper/live仍false |
| quant_us/application/us_equity_forward_observation.py:692 | 部分外部四态证据检查SHA形状/元信息，未在此重算artifact字节 | 还需核对上游生产者与消费者，不把receipt数量当质量 |
| quant_us/execution/oms.py:184、order_polling.py:268 | OMS风控→submit→fills/events；通用polling吞fill错误后可能仍记终态 | ledger与恢复在外围；专用IBKR路径可能另有强制门禁，不能泛化所有执行链 |
| quant_us/execution/ledger.py:15 | Windows无fcntl时只剩进程内锁 | 多进程写入边界需实际单写者证据，不做无授权并发实验 |
| quant_us/factors/evaluation.py:189、244、271 | 部分turnover/correlation是占位；compute_decay为零stub；lookahead采5股票与IC最少10样本冲突 | 现有因子评价功能存在，但具体报告字段必须区分真实计算和占位 |
| quant_us/factors/pipeline.py:384、522 | 中性化函数已定义但主pipeline未调用；部分定义窗口与实现不同 | 注册因子、声明机制与实际计算必须建立可追溯关联 |
| quant_cn/backtest、ledger、execution | 离线engine有risk→OMS→simfill→ledger→replay；部分PIT价格带/结算/公司行动未装配默认engine | A股不是纯空目录，也不能宣称所有市场规则已经默认接通 |

### 关机时的部分断点：不计入541完整文件

- US live首批12文件目标10,123行。前读者6个EOF共996行（__init__、modes、runtime_config、runtime_events、runtime_state、paper_trading_loop），待新读者交付整个批次后入账；paper_runtime连续1–2940/4113，ibkr_runtime_supervisor连续1–120/982。剩余provider、recovery、reconciliation、orchestrator未读。
- 前端首批38文件目标7,848行。可精确恢复的EOF为frontend-identity-lib.mjs 1–740、start-current-main.mjs 1–131。其他已报告13个EOF但缺完整文件清单的11个不推测恢复，由续读者重新确认。
- 主代理继续US data。Alpaca connector与US ingestion关机恢复后新读203+252行，暂不混入本快照。

### 独立验收纠正与发布边界

当前已提交main是`f3a78afe0b59d432820dc8f50510038df6c00754`，其地图仍显示已提交340文件快照；541文件恢复记录目前在producer工作树，未发布到main，不宣称浏览器已经显示新数值。

独立集成分支的`6f204282e265c7408364976c2b59b3e162316bc7`（测试/报告）和`1d3b6ca98f6d2573b36c39a39e1fd557e71b15eb`（handoff）未合入main；此前最终FF被权限审查拒绝，未改用其他方式绕过。

**纠正旧推断：测试提交也会改变前端指纹。** 后续只读审阅在`frontend/scripts/frontend-identity-lib.mjs:20–25、186–219`确认，指纹覆盖所有tracked frontend文件，唯一排除public/frontend-identity.json。旧报告的identity/build通过对应f3，不能认证6f/1d；即使后续获准集成，也须先用正式生成器刷新身份并重验，不能直接沿用旧81a指纹。当前main地图不因此失效。

此前架构页6/6、研究导航9/9等是关机前的验收，不冒充关机后服务在线；公共壳10项既有失败、后端external artifact root缺失未解决。关机恢复初检3000/8765无监听，只说明进程不在；没有自动启动BTC运行、collector、private观察或研究。

本轮root唯一写者，原planner producer工作树恢复前上述docs/catalog/identity限定路径clean，touch set仅原票据的docs/architecture/system-code-map、frontend/src/workspaces/architecture/catalog.json及后续必要的身份文件。没有删除代码，没有覆盖其他工作树或重建任何交易artifact；M1保持暂停，M2—M4不自动启动，所有交易许可保持false。Team Context恢复调用返回unknown，无新跨writer交付可消费；固定Git源码阅读与自有文档恢复继续，集成仍阻塞。

## 恢复后续读快照：618 EOF / 253,048 行

新增77文件 / 29,803行已逐文件写入catalog，批次`post-shutdown-resume77-eof-20260910`：US live12 / 10,123行、BTC research12 / 8,055行、frontend38 / 7,848行、root US data15 / 3,777行。US live继承4,056行、新读6,067行；前端继承两个身份脚本871行，新读36文件6,977行。未读/部分断点不算EOF。

新增架构节点为BTC趋势研究与候选、quant_us通用因子引擎；US application/live与BTC monitoring/security按实际职责纳入运行域。图中引用关系不表示已部署/执行。

### 静态发现补充（均未运行复现或修复）

- US PaperRuntime、通用paper循环、旧production orchestrator、专用IBKR supervisor/recovery是不同接线。旧orchestrator的dry run仍有broker调用路径，不是离线模式；provider读取缓存不代表连接健康；闭环receipt明确不计入30天观察。
- `ibkr_runtime_supervisor.py:795–803`先记seen再写ledger；475–478缺guardian默认pass；292–300完整性默认值可能覆盖显式incomplete。`ibkr_recovery.py:458–486、1184–1194`注入弱Mapping时可能出现success与blocked并存。需要结合真实装配和失败优先fixture，不泛化成当前订单已绕过风控。
- `ibkr_paper_reconciliation.py:1356、1437–1440`分别有默认时钟取快照自身、全部exec序列缺失时提前返回。默认参数下的clean不能代替独立freshness/restart验收。
- BTC strategy ledger固定五线，stable Long/Short为champion，其余为challenger/历史/辅助。micro-live packet是独立high-yield诊断，不是默认champion执行装配。
- 总控成功状态与dry-run manifest允许集合矛盾；manifest要求的paper true又被总控视为危险。holdout锁缺边界、自检计数；paper packet独立blocker不回写ready；micro压力只扣清算袖本金、不扣其他浮亏，缺funding按0。这些报告不是风险/账本执行事实。
- US DataLake仅装配yfinance；另一个ingestion固定YFinanceConnector却按config.source标记来源，raw路径实际存清理后数据。后者版本hash按请求/行数，不是前者逐值hash。
- 旧FeatureStore checksum独立排序各列，不绑定symbol/value行关系；read_as_of仅按日期选最新，未校验历史available_time。CorporateActionAdjuster无as_of参数，股息/拆股共用factor并一起调整volume。M1输入不能仅靠方法名声称PIT。
- LocalCsvProvider重算文件hash，但adjustment_replay701–727只信输入replay_error；NaN比较和宏观时间字符串814–819待核。生产PIT consumer另有六表hash和逐行event≤available≤ingested检查；与旧manifest校验器分开看，全部promotion仍锁定。
- 前端terminal-workbench.css的全局!important字号与研究页inline-style文本选择器耦合；tsc不覆盖全部MJS/JSX/E2E。两组research spec使用synthetic API，navigation单独核验canonical，layout没有同等beforeEach；测试源码存在不等于执行通过。

### 验证与阻塞

本快照运行`node --test frontend/scripts/test-architecture-map.mjs`：8/8通过；`node frontend/scripts/architecture-review.mjs --ref=7403c5331057cbba21b9c013b8d6c0ee4c517d91`：618/2515、catalog_errors=[]、基准inventory未变、runtime_verified=false、trading_permission=false。

注册主工作树`start-frontend.cmd -Check`被Windows脚本策略拒绝（PSSecurityException / UnauthorizedAccess，running scripts is disabled）。没有修改ExecutionPolicy或换入口绕过。未运行恢复后的浏览器回归、业务测试、模型或gate重建。

当前main仍f3，已提交地图仍为340快照；618记录在producer内，未提交/集成/发布。后续在可批准的独立发布窗口统一刷新指纹并验收，不为每个阅读小批次反复构建。

## 后续快照：658 EOF / 282,456 行

批次 `resumed-eof40-20260910` 新增40文件 / 29,408行：US live16 / 8,065、BTC research10 / 8,104、root US data13 / 3,846、frontend/src/index.css 1 / 9,393。均固定7403源码、逐文件EOF；40条精确blob/范围/读者记录见catalog，不把当前main或运行证据更新为这个数字。

### 美股运行与证据边界

- LiveRunner协调行情、订单轮询、对账和metrics；其strategy cycle未构成已证实的Signal提交链。LiveRuntime是另一个外壳，LIVE末端始终拒绝/人工复核，production_loop_started=false。不能根据类名将两者拼成已经上线的装配。
- `readonly_live_broker.py:216–229、247–265`存在条件性凭证审计泄漏路径：脱敏分支从context读取api_key/api_secret，禁止操作日志却保存整个context。仅推演调用者放入凭证时的风险，未读取任何凭证/实际日志，没有证实泄漏事件。
- `ibkr_runtime_market_data.py:414–415、949–962`全局sequence与分标的连续序列检查冲突。`runner.py:391、543–547`普通过期没有error时可能不冻结，clean对账还可能覆盖其他原因的reduce_only；536以零初始现金对账。均需真实装配追踪，不在此次审阅修复。
- `paper_oms_reconciliation.py:1079–1085、1515–1520` NaN转换配合大小比较可污染fixture账本；1204–1207允许同为unknown/cancel_pending的订单一致，523–524则清除halt，且cancel_pending转reconciled可能不在状态表。不是默认BTC或真实broker故障证明。
- `paper_ledger_uow.py:79–81、245–260`恢复时信任journal中的目标和备份路径，未重验路径边界/内容SHA；锁是进程内，不是断电事务完整性保证。
- `ibkr_paper_observation.py:344–419`validator弱于builder，没有重算完整eligibility/input内容；空安全字典和自声明counts_toward的加载边界需独立检查。`live_state_store.py:119–134、169–186、271`坏文件视同缺失、尾部clean条目不核自然日、旧状态默认reconciliation=true。它们不是同一观察合同。
- MarketDataLoop按全体最大时间判freshness；MarketDataParity不实际比较价格/成交量；ReadOnlyLiveBroker仍可转发私有网络读取；本轮没有运行这些方法。最终LiveOrderSubmissionGate即使条件满足仍只到人工复核。

### BTC 研究回放与观察边界

- perpetual paper replay消费公开观测/历史OHLC、mark/index、funding、rules，经模拟风险/订单/fill/ledger与oms.paper_runtime_replay_session；不是默认Demo。每个样本从flat/10k起算。current/historical/fixture证据标签不同，后两者不能计真实paper证据。
- `btc_perpetual_paper_runtime_replay.py:1077、1262、1338–1341`short数量已经为负，nested position又取负；autocapture:191消费该字段。回放中的mapping文字不代表此文件真的调用了depth fill mapping；private WS/funding观测仍false。
- `btc_perpetual_paper_runtime_reconciliation.py`双空输入可出现passed=true而row-present检查失败；其禁止breaker+fill，与replay允许非safety blocker下fill的边界矛盾。historical drill未传reconciliation却可passed，需报告合同核对。
- `btc_demo_observation_accumulator.py:508–564、643`当前身份blocker未全部进入complete/window_ready；905–910 gap分支覆盖不合格小时起点。`btc_observe_only_health_report.py:266、418、502`缺锁不阻塞、未来时间/负age边界与无HEAD绑定需分开观察；promotion仍false。
- public dry probe默认execute_network=true而server-time preflight默认false；前者恢复成功仍保留早期错误作为blocker。没有运行任何网络入口。25小时Demo、30/60自然日观察、三策略observe-only不是同一验收窗口。

### 数据与前端边界

- `quant_us/data`31个Python文件全部EOF，共7,982行。HFETFResearchDataset本层只记录SHA，shared_hf_etf26 wrapper另有resolver和实际字节SHA检查；不能泛化成所有输入不验hash。RTH重采样不是完整early-close日历，缺分钟也能聚合。
- DataManifestStore按请求构造版本、非原子覆盖json；本层fingerprint==checksum不等于重算文件字节。UniverseBuilder仍消费当前is_active；SurvivorshipDetector对幸存者集合可能判clean；as_of命名不能证明PIT。
- minute_quality_gate严格检查已完成交易日XNYS网格，但不把当前freshness_lag纳入status；缺volume可能不失败，正Infinity价格未显式拒绝，也未在此按分区核symbol。PASS是局部质量状态，不是DataReady/交易许可。
- 前端index.css完整9,393行，随后还加载workbench/terminal CSS。小屏.strategy-toolbar前一单列规则会被后续双列覆盖，但最终须结合后续CSS/DOM；旧/新layout-report和两种dock DOM并存，不凭选择器删除旧代码。inline font与testid选择器耦合记录为维护风险。

本批只修改root自有docs/catalog；无删除、无业务修复、无私有调用、无模型或交易gate重建。当前main与启动/集成阻塞保持上一节状态；完整系统阅读及M1仍未完成。

## 后续快照：723 EOF / 313,246 行

批次`resumed-eof65-20260910`新增65文件 / 30,790行：前端最后25 / 7,911、BTC搜索6 / 8,153、美股simulation/shadow16 / 8,018、root监控18 / 6,708。reader、blob与完整范围均逐文件入catalog；无部分文件混入。

前端基准inventory为154文件，现已全部EOF；7403实际tracked frontend157，排除package-lock.json、public/favicon.svg、public/frontend-identity.json三项，不把排除项倒填已读。最后23个e2e目录文件实际为22 spec+1 fixtures。新地图/票据不属于7403基准。前端大量page.route、EventSource/fetch/clock注入只证明fixture行为；填入Git HEAD不证明真实API或artifact一致。

### 研究搜索不是默认执行链

- Intraday与high-yield的同组validation folds反复用于GA选参，train_end不产生逐折重训；尾部又参与候选retention。high-yield另有先锁单champion再揭盲的frozen-unseen模式，不能混淆普通尾部模式。新默认不可变JSONL loader与旧SQLite路径不同。
- `ga_rule_component_mining.py:493–543`vol_scaled诊断用当根close波动率调整当根收益exposure，二元主搜索不受这一具体路径影响；650/658按validation_score排名单，与evaluation-only声明冲突。691–715 baseline用全样本score却标same_validation_window。
- `simple_trend_rule_lab.py:713–715、1289–1291`所谓单exit优化还把ΔOI>0改为zscore(ΔOI)>0。其WF/按年regime是既有收益切片，无独立holdout。Intraday研究ledger的reconciled=true为固定值；high-yield主要检查数组长度/有限性，不是OMS独立对账。
- Trend-family与multiscale复用FixedSizingPolicy/FixedRiskConstitution及next-open模拟，typed genome不改风险/仓位；固定prefix仅selection，不宣称confirmatory。Multiscale核Git manifest blob却读取worktree manifest，元数据未与blob字节绑定。High-yield验证row visibility后丢弃available_time，不能逐决策校验真实可见延迟。
- 六搜索模块固定对象引用检索未见backend/quant_shared/BTC runtime直接导入，主要由scripts/research驱动。共享Factory→Qlib适配→quant_shared.alpha_factory是独立链，输出research_only、automatic_execution_handoff=false、not_trading_backtest。同名历史注册候选不是新GA genome已晋级。

### 美股 simulation / shadow 必须按实现区分

- ShadowLiveRunner实际有PreTradeRiskEngine→OMS→SimulatedBroker→JsonlLedger；ShadowLiveOrchestrator只有strength×100、自行模拟、原样通过risk，shadow_models:138–139定价恒零，且订单重建target/risk ID，不能作为前者的等价验收。
- 已确认此前安全风险的源码调用者：`shadow_live.py:620–624、1343–1354`把原始api_key/api_secret放入context并传给readonly proxy；1324–1330未初始化broker分支直接返回它；结合readonly_live_broker:216–229形成原样审计传递链。**未读凭证/日志，未确认泄露事件或外部展示消费者**。
- `paper_simulation_runner.py:181–194、221–269`旧持仓缺新目标价格按0估值；roll:259–268目标数量置0，307–308却跳过缺价成交，可能无卖出fill就清仓并通过局部对账。这是独立simulation路径，未改变/证明默认BTC账本行为。
- simulation preflight blocker判断前先执行恢复（runner:77–85），所以blocked start不等于无文件副作用。readiness/roll缺HEAD/hash/freshness绑定；evaluation在已有账本时不传播roll BLOCKED（61–65），用snapshot行数而非唯一自然日完成30日门槛（95–98）。
- shadow controller每调用一次record_day加一天且real_submit_count硬置0；Runner恢复/启动对账失败继续（673–728），先检一帧后另取缓存、成功前推进游标（841、1140、1178），保存新session/空日记录。全部默认OMS是SimulatedBroker，不夸大为真实订单绕过。
- ETF26 candidate envelope是固定4订单3fill与临时目录UoW演练，顶层status/decision固定成功文字不随scenario失败变化（339–340）；不是broker/promotion证据。IBKR no-submit在factory前校验committed/hash/lineage/freshness，真实PortfolioAllocator+PreTradeRisk后停止，不进OMS；injected_fake仅依赖counter接口，不能证明网络沙箱。
- Alpaca adapter类级capability与运行时network_submit_enabled不同；读取方法可懒创建真实Broker。IBKR通用adapter合同只返回readonly ready、submit_capable=false。PaperScheduler次数不是成功交易日；多周期aggregate fresh是任一周期新鲜，不是all_fresh。

### 监控域完整通读后的地图

`quant_us/monitoring`18文件/6,708行全部EOF；新增独立监控节点，以下是源码事实而非运行验收。

- RuntimeIncidentManager→JsonlIncidentStore→注入AlertSink：先append+flush+fsync再告警；结构化context/文本脱敏、损坏JSONL抛错是实质性实现。锁仅进程内，回放接受最新完整snapshot而不校验事件转换/时间或hash链；同一OPEN事件severity升级只coalesce不再次通知（runtime_incidents:750–754）。ACK不等于恢复交易权限。
- 两个AlertSink定义不是同一实现：alert.py抽象raise；alert_sinks.py支持callback/fanout/未来协议；telegram_alerts是独立真实外发实现，默认disabled，本轮未调用env loader或send。告警文案“已停止交易”不执行风控动作。
- USCommittedEvidenceRepository真正读取指定Git对象并重算artifact/manifest SHA、校验integration祖先；其freshness=current_head表示提交绑定，不检查生成时钟（read_sources忽略generated_at），不等价市场数据新鲜。
- DailyTradingReport从当前broker equity减旧snapshot算daily_pnl，缺snapshot用当前equity回退成0；total_fees/risk拒绝计数不按report_date过滤，对账取最新文件/mtime并信hash文字，缺失显示unknown但halt=false。不能把其摘要代替Fill/Ledger推导的当日PnL验收；本轮未调用broker。
- daily_monitoring builder实际写多份保留artifact，且默认markdown在repo外；源码“CLI只写”说明不准确。其replay_diff只是状态白名单比对，不执行策略回放；无HEAD/hash/time校验。任何open queue先加入blocker，因此正常builder流程下observing分支不可达。
- completion_dependency与completion_audit依据status/布尔，passed分支清空源blockers；同一portfolio报告前者接受promotion_evidence_ready+promotion_ready，后者要求portfolio_promotion_evidence_pass，状态合同矛盾（dependency:192、audit:171）。两者都不授予交易权限。
- next_action_queue缺completion源时得到空milestones并返回next_actions_complete（51–56、115–125、463–466）；operator_unblock_packet缺源也可返回complete（46–68、268–270）。缺资料不能在前端解释成真的无阻塞。
- strategy_production_line本层全是报告聚合；声明的architecture_layer_contract是目标约束，不是动态依赖检查。validation只认状态并允许缺安全字段（531–545），不消费其blockers；顶层observing还可能覆盖registry阻塞（127–133）；chain_complete仅看manual+validation，不要求其他node无blocker（825–834）。paper/live阶段永久blocked，safe_blocked只是“不需额外告警”，不是ready。标准化回测硬编码tiingo_eod及最少20标的，不是资产中性工厂合同。

### 前端测试的有效范围

`btc-demo-console.spec.ts:1371`两处boundingBox读取left/right，而返回形状是x/y/width/height，默认0/Infinity使对应几何断言退化；邻近宽度断言仍有效。策略来源fixture有重复字符假摘要与真实计算合成源码SHA两种强度。view-model.js假设部分输入类型完整；未证实当前消费者违约。全部仅阅读，未运行此批E2E。

658与723快照地图合同测试均8/8通过；723固定7403对象检查exit0、catalog_errors=[]、source_inventory_unchanged=true。持续仅root写原producer的docs/catalog，无新业务修复/清理/执行。main仍为旧340地图快照，未称浏览器已经显示新增覆盖；启动策略和集成批准阻塞仍在。M1暂停，M2—M4不自动启动，全部交易许可false。

## 2026-09-11 续接批次：830文件／351,969行已EOF

在723快照后新增107文件／38,723行：root的US reports/内嵌tests等13／3,820，adapter/backend tests22／6,261，US live第四批41／14,293，BTC research第四批8／8,357，backend tests增量23／5,992。每文件blob、reader、批次与完整范围已入catalog；总范围仍2515文件／808,857行。目录枚举不当通读；当前为并行只读者与root的联合审阅，不称root亲自看完全部源码。

### 研究工具适配器的真实职责

- OpenBB只组装supplementary research manifest，不是采集器或Forecast。Vectorbt筛选实际用pandas计算，import vectorbt是依赖探针；不是fill-ledger回测。其125附近排序价格而exposure仍沿原索引shift，非单调输入下时间对齐待验证。
- PyPortfolioOpt链为scores→预期收益→协方差→优化权重→parquet/json导入；上层研究编排才构造TargetPosition并送事件回测/risk/sim broker，适配器本身不授予交易权限。
- build_covariance:47按symbol缓存第一次加载的历史，不随后续rebalance扩展；build_expected_returns:165按行datetime筛选forward label，未显式约束label成熟时间。import_target_weights检查列/类型，缺完整run/source hash关联，不能作为独立lineage证明。

### Reports通读与CLI阅读断点

- quant_us/reports六文件2492行全部EOF。quantstats_ledger_profile把调用方ledger_reconciled（默认True）当断言，无独立fills/cash重算；可选quantstats仅计算，不比较数值，外部指标未传内部periods_per_year，异常可跳过。
- paper_validation:809行，读取持久session/recovery/reconciliation状态和parquet存在性；天数信任state计数，days_required可配置且无最低值；未核自然日完整性、artifact哈希/HEAD、跨run关联。记录hash文字不等于重算hash；非有限cash差值的比较仍待复现。
- live_readiness:1197行，check_all不是纯本地：583账户查询、774下载SPY、832 Telegram真实外发、1117/1140固定.write_test文件探针。Telegram返回False仍可记passed；多项检查只验字段/方法存在。报告review_only=True、submission_ready=False；本轮未调用任何检查函数、env读取器或外部账户。
- live_readiness的paper检查虽调用inspect_paper_validation_evidence，却只消费recovery_summary、没有完整消费gaps；parity异常可降为warning。portfolio_observability也多按文件存在/计数推断展示状态，不是运行归因验收。
- quant_us/tests六文件1323行全部EOF：broker sync/fill identity conflict/unknown order→reduce-only确有内存模拟断言；不是生产broker证明。factor测试部分只断言类型或条件成立才比较，lookahead检测仅验证返回形状，不能据此证明无未来函数。
- root正在读quant_us/cli.py（9378行）；当前连续已读1–2500，尚不计EOF。初步发现regime report:1305–1309把收益指标写0、trade_count设为regime行数，属于占位报告；shadow-live start:2203忽略readiness返回，2231一次cycle调用record_day。这里只保存断点，完整入口结论待余下源码。

### US live目录85文件／40,499行完成

- OneShot和LivePilot最终提交函数硬冻结；LivePilot execute在最终门禁前仍可能做private account查询，即dry-run不保证无网络。没有运行或解锁。
- G6 reduce-only接受Any broker，显式关闭dry-run并满足本地门禁后有真实方法调用；209–225在任意AttributeError后再调用另一submit方法，可能重复且丢失reduce-only/limit语义，未检查拒绝结果。不能把它泛化成当前BTC路径或已发生真实交易。
- OneShot坏锁文件→未锁，read-check-write非原子；EmergencyStop坏JSON→ARMED允许新增风险，resolve不要求先ACK。FirstLive确认部分ticket缺失/status问题不纳入reasons。
- G6 final dossier:317把cumulative_notional当亏损阈值，172跨episode读G5；progression累计风险恒True。Risk monitor把unrealized PnL按调用累加、daily count无日期复位。G8未消费G7完整TTL/证据合同，采用简化promotions；缺/坏daily cap允许。Bridge不更新提交计数且异常可能先返回不freeze。最终仍受冻结OneShot阻挡，不能称可交易。
- execution_drill_evidence:144–238是七个固定通过场景；order_reconciliation_drill复用并以列表非空代表可重算。LivePilotDryRun:191只用前两步errors判断overall_passed，后续失败可不影响整体；dossier安全证明文字为常量。与真正故障注入/当前运行审计分开。
- G9 restore:184–224未先验checksum而extractall，源码无显式成员路径约束/filter，实际行为另受Python版本影响；本轮未提取或运行。备份包含历史自身产物且仅文件名排敏；readiness只查record存在，latest排序与config-check相反，不证明归档当前HEAD完整性。
- credential metadata/人工review有schema、布尔及路径格式约束，但自由文本原样保留，secret scan主要检查key，contains_secret_values常量false不是内容去敏证明。本轮未读实际credential或artifact，未确认泄漏事件。

### BTC第四批：观察、搜索和默认策略分界

- atr_baseline_narrow_ga训练fitness与最终selection不同：379–412/729–748最终候选排名使用holdout、全样本年度/成本/近期指标，与holdout未参与选择说明冲突。atr_regime_failure是全样本选基准后的当根标签归因，非事前可交易regime filter。
- ladder v1退出后同迭代可重新进入，净exposure.diff漏双边turnover；v2新增cooldown避免此分支，却是任一梯级触及即满leverage，周线参数未实际控制决策。两版event价格与close-to-close PnL不是同一fill-ledger；formal网格全样本排名、无独立OOS，清算仅诊断计数。
- multi_timeframe_rule_lab所谓WF是既有PnL切片；vote高周期只限制EMA一票，use_derivatives_vote未控制衍生品票，缺失序列可形成正票；部分状态机exit后可被entry覆盖。其聚合/指标工具被long_short趋势研究间接复用，不代表八类候选进入默认BTC。
- high_yield confirmation明确clean_pre_selection_holdout=False；60行forward CSV是计划。Followup:64–114读观察锁后仍运行全市场48组loss-v3搜索（291–356），锁未约束搜索；观察JSONL:209–220/638–642可改写既有行、整文件重写，缺原子替换/锁。
- comparison读取异源旧报告，不重跑同窗口；覆盖取首尾跨度，缺WF字段可默认True。Followup对mark/index等联合证明用任意字段为真合并，未统一校验source blocker/hash/freshness。
- 本批8模块未见backend/shared/runtime直接导入；research/scripts及报告消费者存在，不能“没运行”就删除。BTC registry的高收益v2是identity-only、不可由single-position runner执行；默认仍OKX native条件选择或stable Donchian。Factory是另外一条受研究权限约束的链。

### Backend tests首批33／200文件的覆盖边界

已读33／10,534行。automation/gate_deep确有显式审批不能绕过not-ready、通过研究门槛仍paper_runtime_approved=false的断言；负向missing/stale/conflict测试有效。但许多成功研究运行由固定metrics替代，合成manifest/hash不能作当前收益证据。registry readonly handler测试比较文件字节且禁止rebuild，但不是完整startup无副作用证明。candidate registry部分测试直接改JSON而未过审批CLI；strategy isolation仅顶层glob及单bar调用；anti-lookahead与regime测试若只检查源码字符串，不能替代未来扰动/前缀不变数值实验。测试未执行，本批只记录覆盖范围。

830快照的地图合同测试已通过8/8；未新建修复票据、未删除代码、未合并main，未启动研究、服务或交易。其后的EOF增量见下节；M1维持暂停。

## 2026-09-11：断电恢复后的1043文件快照

固定源码仍为7403c5331057cbba21b9c013b8d6c0ee4c517d91。新增213文件／72,649行，联合完整EOF累计1043／2515文件、424,618／808,857行。分工阅读不是主代理逐行亲读全部；catalog逐文件保留reader、blob与完整区间。主代理此次新增CLI1、根入口5、旧ETF8、内嵌Alpha Radar19、配置29；只读协作者新增backend测试69、BTC研究33、美股脚本49。未提交快照不等于main或浏览器已更新。

### quant_us全部源码EOF；CLI9378行读完

上节CLI 1–2500是历史断点，现已连续读至9378并计EOF。CLI把数据、回测、研究、组合、报告、G3–G9审批及live入口集中到一个模块；不是只有声明或无法调用的废文件。

- 6538–6559候选组合评分、6618–6629组合回测、6665–6714评分／分配使用随机演示数据；后者还忽略传入策略ID而生成strategy_i。8769–8828缺足够trades/daily returns时按Sharpe合成收益，负Sharpe被收益均值下限截断；robustness将结果落盘而未标识合成来源。8908–8920与9089–9103参数稳定性是随机邻域评分，不是参数重跑。不能泛化为前端全部合成：backend/app_factory有不同实现的同名loader。
- walk-forward:7863–7950切既有指标，缺fold退为单份汇总并补零，不实施逐折训练；auto-cycle:7487以非空结果dict打印promotion PASS，详细decision仍可能全blocked。research scorecard:7797消费其parser未定义的args.robust；portfolio-build:9113未落盘而analyze:9207要求该文件。均为静态入口风险，未运行复现。
- next-step/readiness/overview/micro入口会间接调用LiveReadinessGate的账户、行情、告警、写探针；force_rerun/no_cache只是打印。live-start:3428和_start_live_production_loop:3850始终阻塞。_run_simulated_paper_loop:3547–3847仅找到定义、无静态调用，标记清理候选而非直接删除；其999阈值、skip_session、全局warmup、state天数等不能代表现行默认。
- G6 CLI默认dry-run=True且execute入口不注入broker，不能因generic组件有submit分支就称当前CLI真实下单。部分G4/G5/G8入口只按--execute计算dry-run而忽略同传--dry-run；最终OneShot冻结仍独立。G7 --conditions未消费；G8简化审批不等于完整上游验证。

### 仓库内两个历史子系统，不等同平台交易链

- legacy_strategies/us_etf_rotation_original 8文件622行全EOF：可独立抓AkShare/FRED、拼接Parquet、生成月度权重和CSV；收益为shift(1)权重乘价格变化，不是fills/cash ledger。ME月末若非交易日则跳过；相关性过滤后的补足候选可重新加入相关资产。宏观只简单延迟两行、缺失回满风险，不是vintage PIT；年均收益被标CAGR。所谓实盘指令是CSV展示，未接OMS或权限。保留原参考实现，未删除。
- alpha-radar 19文件3514行全EOF：仓库内的旧stdlib HTTP研究可信度评分器，非另一个工作区的完整Alpha Radar。四维文本／关键词／字段存在性评分，source_name不同即独立，publish_time非空即可追溯；RESEARCH_READY/HIGH_CONVICTION不是QuantStation promotion。main监听0.0.0.0:8100、CORS全开、无认证/body上限；GET id直接拼持久路径，静态存在越界路径风险，未探测真实文件。runner会原地把EvidenceItem转dict；直接runner保存report_json而HTTP保存result形状，target检索合同不同。测试是fixture/FakeSocket，未覆盖完整成功POST持久闭环、路径边界或原子写。
- config旧SQL包含orders/fills与positions/cash快照表，但corporate_actions无available_at、日历无market主键；schema本身不证明当前存储使用。docker-compose的8000/3001与官方8765/3000不是同一启动合同。根cmd均无ExecutionPolicy绕过，重启仍按官方入口和已有阻塞处理。BTC holdout/config研究专用与模板审批不解锁交易。

### BTC剩余研究33文件25091行的差异化判断

- small-account/near-miss/high-octane多处分配使用当前close/波动乘当前收益，near-miss:649–655还以固定BEST signal代替若干variant；bankroll rollover先用当根高低点退出后再计算同根收益，换向成本常按固定side而非杠杆、flat分支可能漏exit成本。不是默认BTC运行链的结论。
- risk_stress:851行存在严格pos→pos+1收益分支；10U v1/v2 ActiveUnit先mark旧仓再开新仓，不能与上述同根研究一概而论。但终局强制平仓后的费用／权益未重新写回收益曲线。spike survival只扣liquidated sleeve损失、忽略其余受冲击仓位；top-confirmation blocked仍可forward_observation_allowed，observer未完整检查其状态。
- bar-replay的completed=True为常量，feature available_at另做backward asof而非逐特征真实谱系；0violations不能自动证明无未来函数。10s contract则确实消费精确Git manifest+全hash resolver，无SQLite/latest回退；source ready与promotion blockers分开。
- depth JSONL路径不复用CSV instrument过滤；integrity未查crossed book，capture sequence不能代替实际交易时序。legacy fill mapping可由两个调用方attested布尔进入promotion_evidence_ready同时immutable_inputs_verified=false；native criteria的schema/head错误进validation_errors未直接进promotion_blockers。
- Nautilus是字段字符串审计，Freqtrade是既有报告聚合，并非实际运行第三方引擎。liquidation formula verified由静态source ID与公开档位验证组合，不是数值清算回放验收。本节仅研究消费者审计，不碰风险、OMS、保护单、账本或默认信号。

### Backend测试新增69文件17915行：测试名不等于覆盖结论

- 因子IC／分组收益／报告测试部分只运行测试自带helper；no-lookahead多为字符串／路径扫描，time-split可在空结果不做比较。walk_forward_multisymbol确实验证unique timestamp切分；quant_us_data_lake实际连临时Parquet→FeaturePipeline→event backtest→JSONL，但本轮仅阅读、未执行。
- capital allocator测试先clip0.2再归一使3标的各1/3；construction两标的0.5即使cap0.25；portfolio scorecard线性加权CAGR与最差单策略DD不是组合权益曲线。这些是现行测试保护的语义，未来不能靠改名修复。
- OMS/恢复测试实际覆盖超时查单、同ID不同qty/price/fee冲突、未知订单减险、重复fill只入账一次；启动同步有零submit及恶意poll尝试submit拦截。另一方面runtime_reconciliation_gate只做局部赋值/hasattr，不能替代这些生产对象断言。
- PG双写有exists() or True、直接手工_pg_write及允许>=0成交；FakeConnection的三次commit不是跨表事务。数据缺失/过期有强负向用例，但market_data_parity部分无断言或条件断言。ledger empty consistent+No data不是完整性通过；手工id_traceability字段也不证明端到端关联。
- 测试夹具可能固定目录、允许零成交；因此只列覆盖边界，不并行实际运行，更不拿这些测试替代当前HEAD或30天观察验收。

### 美股根脚本49文件14980行：入口的实际副作用

- run_alpaca_paper:181–256历史90天bars直接进入strategy→sizing→Risk/OMS→paper broker，没有warmup/current-day提交隔离；恢复缺完整日期去重与初始对账，FILLED-only取fills可能漏partial/cancelled成交，最终对账异常只warn仍completed。仅静态风险，未连接broker或实际订单。
- IBKR历史脚本readonly连接在TypeError后去掉readonly重试；network_called仅统计行情chunk、不统计connect/qualify。credentials初始化脚本导入包装模块未提供的DEFAULT_TEMPLATE。manual-stop/reset演练用固定事件和True，kill-switch/replay报告主要校验结构，不是实际故障注入。
- forward rotation走独立模拟JSONL/state而非Risk/OMS，equity只扣滑点/融资无MTM；仅末日去重、多文件无锁/事务。evaluation零份daily gate亦可pass，连续性信息不阻日历缺口；daily pipeline先写临时PASS再eval，异常可遗留旧PASS。
- daily production:273未因incoming blocked短路便调用local importer；程序接口promotion_clean_allowed默认True，而CLI默认False。非空license占位文本及合法表头零rows可被导入并贴production_bundle_imported；不能据此声称后续PIT/gate通过。忽略规则回退字符串搜索也不证明实际目标受保护。
- FRED freshness仅最后非空时间字符串、Parquet仅存在性；Kline质量pass就promotion_clean，先drop坏行、未来年龄夹0；artifact_health仅比自报hash，不重算引用文件且非法时间当不stale。总编排用1,000,000小时阈值。独立FRED/PIT消费者仍继续读，禁止把局部缺陷泛化成全部门禁绕过。

本1043快照仅阅读索引和静态发现，非最终架构评估、验收或promotion证据；当前main与浏览器仍未更新。继续未读配置、工具、schema、脚本和测试；不新开修复任务，不启动M1/M2–M4。

## 关机续读快照：1364文件 / 487901行（固定7403，联合阅读）

本次新增321文件63283行；精确path/blob/1–EOF/reader在catalog。1043快照的Node地图测试8/8、固定源审阅检查catalog_errors=[]，不是业务运行验收。root新读配置31、治理工具14、治理元数据16、一般schema36；代理补后端测试84、BTC研究7、US脚本34、研究/HTML脚本99。BTC研究目录80文件70042行已全EOF；后端测试仍未全部。无业务文件改动或删除，main/浏览器尚未更新；M1继续等全仓评估，所有交易权限不变。

### 配置：声明与生效参数分开

- US Qlib YAML的model/lineage声明5日标签，但实际DatasetH/Alpha158 kwargs没有显式传label；须核SDK及消费者生效值，不能拿配置标题证明。validation_scheme写walk_forward，而task只有单次train/valid/test切分。固定13标的的survivorship clean声明不是PIT成分证明。
- BTC Qlib为因果OHLCV特征、延后开盘入场和分段隔离；默认无衍生品风险过滤；研究风险预算不是交易授权。Qlib内部region=us本身不代表BTC用了美股交易日历。OKX数据绑定与旧SQLite入口要分开画。
- PyPortfolioOpt top_k=5、max_weight=.15、cash=.02时总权重上限只有.75；仅记录可行性与fallback约束待核，不声称实际求解失败。共享合同配置保留市场专属策略/执行类；wire兼容不等于类身份统一。
- 冻结ETF/QQQ 3x、252交易日/30自然日及forward观察合同各有范围；历史工程open和自然时间不足不是本任务自动修复授权。安全配置只空标识/false，未读取实际凭证。

### 治理与证据基础设施：机械保护不等于业务或权限证明

- context_packet→planner/safe_status→committed handoff→Team Context构成协作入口；shared_data负责不可变发布与列举文件hash。ready发现使用verify_git=False或verify_files=False的地方，只能表示待验证交付发现，不能升级为内容质量或当前HEAD promotion。
- handoff验证commit/hash，但测试结果字段自报不验证测试产物内容，未强制所有变更属于scope；Team Context未解析depends_on依赖图，last-created转换也不是完整状态机校验。append写入存在先exists后replace，单写者仍是独立约束。
- shared_data发布拒绝symlink并校验副本；resolver校验manifest列举文件，不验证未列文件或重新检查全部symlink越界；verify_files=False只做轻量元数据。调用者必须钉完整commit并选择强校验，不能只信quality标签。
- private_readonly工具以签名、session、HEAD、runner hash、TTL、独占claim/launch/start绑定单次只读。此处只读源代码，未读取实际receipt/keyring，未创建能力或触及private。runner hash不等于整个传递导入图指纹。Hook只检查特定tool_input字段，不能被视为全部宿主命令解析或OS隔离；不据此绕过。
- .codex角色/CI配置是仓库声明，非当前宿主权限。CI跑部分后端/研究测试和前端构建，不等于全tests或Playwright。main当前f3与固定审阅源7403区分保留。

### Schema：格式通过与事实成立分开

- 一般36schema共3806行EOF；大global registry含2281行，将众多历史BTC研究阶段直接展开在单read-model，并只允许US/BTC资产键。它不宜承接未来A股所有新状态；重整需消费者兼容，不在本审阅中改schema。
- registry有paper_queue状态与BTC候选数的条件约束、live frozen及大量false常量；仍无当前HEAD/hash真实性或所有flag跨字段一致性的自动证明。global approved是研究队列描述，不等于真实下单授权。
- IBKR/Yahoo/Tiingo覆盖报告多处仅定义guardrails子字段却未required，空对象可格式合格；provider/PIT布尔自报不证明发布时间、退市覆盖。shared manifest形状校验与Python聚合校验是两层；重复兼容schema先保留，不能仅因相似删除。

### 后端测试新增84文件：断言强弱与当前运行分开

- 人工复核、G6错方向/数量、OMS durable client ID、registry并发锁/hash冲突/原子替换有真实生产对象负向断言；但approval输入省略symbol/version的匹配边界、空expiry、默认SafetyEvidence和G7空dict/G8不存在ticket等测试不足不能被“gate通过”掩盖。五个同名测试定义只最后一个被Python保留。
- 多个30天/观察测试是即时record_day或parse/hasattr/manual dict，不证明自然时间；部分replay恢复只是计数而非订单去重。旧shadow零价权益变化是其受测语义，非真实fill账本收益。
- BTC API测试替换verify_api_key并用fake控制计数，验证路由合同但不是真实认证/交易。runtime外置root缺失、相对路径、owner错配拒绝且US/health独立；只读树不变/hash篡改拒绝测试较强，currentHEAD正例仍是fixture。
- history拒绝跨版本run兜底/改标旧HEAD，OKX同公式不算native；edit只是draft。CN读面验证schema/hash/HEAD/不可变generation并维持blocked；这些是测试覆盖边界，全部业务测试本次未执行。

### BTC研究及研究/报告入口

- BTC研究尾部7文件中部分leakage/risk drill使用固定安全字符串、常量blocked或自身policy检查，而非实际Risk故障注入。全80研究文件已EOF，不能据目录完整读完声称全系统健全。
- scripts/research89及reports10已全EOF：假说/事件账本实际消费quant_us.research；GA小账户消费quant_crypto.research；新GA入口使用显式immutable manifest、holdout/cutoff，与早期SQLite/latest默认不同。
- spot_source_comparison会清理指定临时manifest目录、同步公开行情并调用quant_us.backtest.crypto_event；7策略×2源的分段是诊断，不是walk-forward，更不是默认Demo OMS。只读源，未执行、联网或删除。
- TimesFM smoke未传now/cutoff再用最后row作decision_time，hour gap只记录；interval可变但预测时间按小时，固定PASS_RESEARCH_ONLY_SMOKE不能证明已完成bar。US共享预测默认Drift，显式开关才使用TimesFM。
- HTML生成器无current-HEAD/hash验证，部分判词/全局registry/旧canonical写死；eventPF双缺失None相等也可通过局部比较。地图标为表现层，不视为gate权威。

### 美股脚本新增34文件：数据接入和PIT

- FRED preflight多为行数/最后时间；macro release policy检查字段与来源字样不逐行验证available_at。production预检记录actual hash但不总比较expected，record_count键存在可为0；独立provider/PIT消费者另有严格校验，不能笼统说全部放行。
- run_pit_bundle_acceptance会在readiness失败时短路；vendor_drop_pipeline先import再调用会再次import的acceptance，结合不可变目标存在即拒绝，默认组合有自阻断静态风险。未运行。
- Tiingo EOD/IEX在execute_network分支前读.env.local；IEX隐藏single-chunk可直接走凭证/网络路径，URL参数中的token到异常str/报告无脱敏是静态传播风险，非已发生泄漏。本次未读取.env或执行脚本。dry-run报告writes_performed=false与实际写报告含义不一致。
- 数据先写后quality、skip-existing不刷新stale、network_called按成功数量而非请求；finite/NaN、逐日coverage、ratio不可用的阻断并不一致。IEX顶层research_ready与单标的raw blocker聚合不同，质量PASS应按实际消费者解释。
- PIT replay把发布时间人工指定为ex-date 09:30不是供应商历史available_at，顶层状态未总聚合子blocker；只能研究草稿，不能当PIT已验证。activation入口消费旧报告未重验hash/HEAD/TTL等风险暂入审阅记录，不开新工程票。

本快照仍in_progress；目录扫描、schema阅读、历史测试源码均不等于当前运行通过。后续按未读差集继续，避免重复阅读；没有启动M1、M2–M4、promotion或任何交易能力。

## 关机续读快照：1469文件 / 516032行（固定7403）

新增105文件28131行：CN schema4、BTC schema32、后端测试最后14、US脚本55。地图增加“协作治理与证据发现”“证据格式与版本合同”两个模块，共25模块；不是新业务模块。1364快照Node地图测试8/8、固定源检查无差异/无catalog错误。仍仅3份本任务地图/说明dirty，没有业务改动、删除或新修复票，主页面未同步。

### Schema阅读方式与边界

- Schema均完整读取所有字段/枚举/条件/引用；为减少重复缩进输出，BTC批次去掉行间空白、不删除属性或字符串、不筛选字段，覆盖仍按固定Git blob的原始1–EOF记录。CN前2份原样，后2份完整JSON标准化输出。此记录不是schema执行结果。
- CN合同锁定七阶段顺序与current_head、安全全false，paper closure固定blocked、至少4个blocker及两个offline drill；format/date/hash字样需要实际validator与consumer重算，不由schema文字证明。source_events min6也不自动保证六层各一次，stage ordinal与ID对应依赖生产校验。
- BTC历史bounded retest合同直接固定quant_us.research.btc_eventpf_wf.run_stabilization_sprint、旧run manifest路径和5m/15m/family；不是通用Alpha工厂接口。部分current-status允许paper_observing但仍research_only/simulated_broker_only，必须查看运行receipt才能称实际观察。
- 10s数据准入合同按5家族×3horizon列15项，但长度本身不保证每组合唯一；研究信息量准入与自然天/执行证据分开。authoritative pointer receipt固定旧data_version/manifest/hash、eligible windows=0、blocked，是一次证据合同，不是全数据通用schema。
- 新Demo operation V2明确请求digest、revision、terminal result、ack时间及start-attempt；未在schema跨字段验证parentID、sourceHEAD相等或current/historical互斥，生产对象是另层保护。读面与真实权限边界不变。
- exchange overlay已兼容Binance与OKX instrument形状；顶层规范symbol仍BTCUSDT，OKX venue BTC-USDT-SWAP由raw字段表达。fee overlay接受OKX公开费率但旧market_type命名仍usds_m_perpetual，不能单凭名称推断执行用了Binance规则。
- 早期fold/regime、funding账本、成本报告多为形状与布尔字段，不校核日期顺序、实际净收益相加、序列因果。研究PASS/复核allowed不自动授予交易，重复旧合同先保留消费者兼容。

### 后端测试全部EOF：200文件 / 60832行

- catalog与Git tree逐path/行数/blob核对无遗漏/重复；本次只阅读，未实际运行200文件。r2_hardening、r6_r7_r8前段是测试内手写算法，不是生产研究计算器；后者另段真实调用PromotionGate，保护坏证据/manifest/hash/PnL篡改拒绝，正例仍只是手工证据包READY_FOR_PAPER_REVIEW。
- crypto_closure调用真实编排但研究/data/gate替身；live_modules无recon或require=false的readiness可ready，真正start仍另有gate。secret_masking部分只直写audit，不触HTTP endpoint；对象raw与序列化脱敏不同。
- 日历测试覆盖若干节假日/DST/早收盘预期，但YAML加载与holiday来源分开、部分条件assert可不执行；Telegram和交易DB均fake。不能据此证明真实数据或告警送达。
- launcher测试保护main/root/HEAD/端口/profile/锁；Demo无旧promotion仍canonical且权限false，strict模式需要current。锁存guard每请求只读HEAD，测试未证明同HEAD后续dirty/artifact持续监测。CLI报告fixture bytes和手写日期/hash可格式PASS，不等于真实Parquet/30交易日/账本生成。

### US脚本CP3/4：启动、旧修复和设计报告

- 官方backend launcher DIRTY_SCOPES不包含全部quant_us/quant_shared/configs，canonical只表其明示检查，不证明全仓干净。仅读代码，服务仍未启动，未绕ExecutionPolicy或hook信任。
- repair_external_etf_kline_quality把短时大跳变视为复权并追溯全部历史OHLC/volume，缺公司行为PIT佐证；可能抹掉真实跳变。其K线质量PASS与promotion_clean标签不是全PIT证明。未执行修复。
- audit_research_evidence缺canonical manifest直接continue、只遍历已扫描versions，空根可无blocker；不能替代完整gate。run_full_pipeline ingestion没传data_root、合并全部raw日期、gate未绑定Stage2 run/manifest；closed_loop ingestion失败仍回测，run_backtest缺日期可隐式synthetic。只登记调用风险。
- Yahoo intraday聚合没要求4h桶完整，available_at取已有末bar；可能发布未封闭4h。CN materializer验证committed handoff，但schema来自工作树、全流程未持writer锁，异常报告artifact_written=false可能掩盖先前局部写入；未实际materialize。
- 六design-spec是固定研究假设/参数/计划生成器，不是回测。registry正式source只查key/path.exists（空值可落根），research-start的全局blocked与子行allowed可能不一致，下游必须遵全局gate。
- taxonomy只汇顶层blockers，缺报告可no_blockers，关键词分类可能遮住unsafe；development/taxonomy相互消费latest未绑HEAD。remediation closure主要按missing/open_count，空报告或unsafe blocker可伴随tickets_closed，不能当交易晋级。
- schema-audit仅部分字段存在和格式，未跨报告核strategy/hash/HEAD；missing/null live_allowed可视safe_false。external-adoption看依赖/文件/测试路径存在，不是测试通过。上述均是报告级静态风险，不宣称实际执行放行。

地图仍in_progress，下一步按未读差集继续BTC根脚本、仓库tests与余下schema；已读内容不重头扫描，M1仍待完整重新评估。

## 关机续读快照：1720文件 / 570111行（固定7403）

新增251文件54079行：BTC schema余48、US脚本23、BTC根脚本57、非contracts测试123。BTC schema全部EOF；后端测试保持全部EOF。精确原始行数/blob/reader记在catalog；root为唯一地图写入者，三个代理均仅阅读。1469快照Node地图测试8/8，本快照尚待检查。没有业务改动、删除、运行研究/交易入口或读取实际凭证；main页面尚未同步。

### 共享研究来源选择：不能用全局“最新”代替市场与run

- US脚本CP5：global registry的Qlib收集遍历全部manifest，未在该层按asset过滤；组合和因子报告部分按全局目录mtime择最新。factor pack还把选中的全局挖掘结果贴上当前US数据版本，不能保证原run谱系。本结论来自固定源码，不等于已观察到当前前端串数据；重新评估应先追踪market/instrument/data_version/run_id的完整消费者键。
- US factor pack只用前100行，cost-adjusted/WF部分硬编码false/null；run_us_equity_factor_evidence固定Yahoo 2020–2025，不绑定选定production bundle；5日标签收益与日换手成本口径需区分，“WF”拆三段未重新训练择参。两个旧producer共写latest pack，不能视为已具备单写者/原子发布。
- US V3 G06→canonical→hash-bound portfolio是另一条较强证据链，但构建器会删除output_root下canonical/portfolio/build_inputs；只检查root包含关系而非任务所有权。此处只读代码，未运行、未删除任何目录。
- global registry还存在未聚合manual/operator/GA/TimesFM子blocker、信任旧approved状态/候选非空来推荐start/resume的路径。这是建议读面，不是真实执行授权；必须与新权限链分开画。

### BTC旧研究脚本：历史样本报告、收益模型、真实执行不可混同

- CP1 completion_evidence使用固定价格/数量/hash、手工fills和测试名称，completion audit默认样例；cost model会由字段齐全及旁侧current标记宣称mark已使用，没有完整身份绑定。current_status可因ready/approved/start_allowed直接写paper_observing，不能证明发生实际start或持续观察。
- CP2 alpha_probe/refinement把15m开盘时间映射该15m最终close给区间内5m信号，前两根5m可能提前消费高周期收盘；lookahead_used_for_signal却为固定false。refinement以同样本选择8变体×3horizon并分6段，不构成独立holdout；费用标签收益也不是fills/现金账本。记录待复现，不动默认BTC链。
- CP3 paper_candidate_gate只接受research_definition_ready_paper_locked/paper_candidate_ready_for_manual_review，与已读current_status输出的状态枚举不相容；该固定源直接衔接存在静态自阻断。manual packet核approval内容hash/strategy/gate_snapshot，但下一层preflight依赖上游布尔；definition manifest排除部分人工check，timestamp仅格式检查不是日期真实性。
- intraday_trend_v1是独立long-flat exposure×return−turnover成本模型，默认shift1/HTF另shift1；CLI仍允许0/负delay。无终局平仓费用、真实fill ledger、独立WF/holdout，SQL未逐bar核final/asof/hash。4hATR报告消费此模型，而非默认OMS实绩。
- 根聚合器有public dry-probe网络调用入口；不抛异常就complete_read_only、缺失安全字段未必阻断。runtime contract/故障回放也有固定CONNECTED/OK/序列样例。funding ledger从已闭合trades重建fills，不是原始成交账本。所有入口本轮均未执行。
- 新DataReady/bootstrap/immutable export则要求committed HEAD、owner、manifest/hash/time，拒绝歧义与SQLite/latest兜底；必须保留“新强约束链”和“历史报告链”两种事实，不能据旧脚本概括全部BTC执行能力。

### 美股收益与筛选脚本：组合权重、成本、时间口径

- macro optimization先缩减risky权重、按缩减后的总和计算defensive残余，再额外加capped_excess，有重复计权静态风险；防御上限回补风险后未再次应用risky cap。固定目标权重逐日乘收益只按目标变化记换手，维持权重的漂移再平衡成本未计；多个stress/WF/book脚本复用此函数。
- 年度WF确实历史择参，但拼接各方案独立全历史收益流，fold切换没有统一仓位迁移与换仓成本；训练只需有行而非完整五年。leverage用前日exposure记收益、当日exposure记融资，融资时点错位；没有真实杠杆调整成交/保证金/破产账本。
- macro loader只读日期和指标值，不消费release/vintage available_at。独立WF gate读汇总计数与stability布尔，不核OOS/source blockers/HEAD/hash，且固定strategy ID与默认输入邻域不一致。仍研究专用，不宣称执行放行。
- CN current-head gate对committed handoff/7阶段继承/HEAD/hash/24h有严格校验，但publish先于最终validate；失败时artifact_written=false可能遗漏已落盘状态。多文件rollback只捕获部分异常不是事务，closure依然有offline/runtime/manual/not-authorized四类blocker。仅读取，无发布。

### BTC schema余48：格式合格不是因果、自然时间或权限证明

- 全部属性/条件/枚举已完整读到EOF，仅去行间缩进降低输出；source_time允许derived_from_close_time，与真实vendor available_at不同。L2接收延迟/可见深度代理明确不是订单执行延迟/交易所队列位置，checksum策略字段也只是源码声明，未核当前交易所文档。
- paper run的PASS要求consecutive_clean_days≥30，不校calendar连续性或与days_required一致；paper readiness的若干ready分支未在schema层强制packet hash匹配；paper start的文本步骤及checks不证明实际执行。生产校验另层评估，schema缺约束不等于实际绕过。
- trial registry即使blocked也要求至少一个selected，不能自然表达全失败/零候选；旧roadmap固定funding-carry及天数/事件数，不是自动工厂学习。部分orchestrator/工程schema固定15/17项历史blocker，这是历史证据协议，不应自动变成今日全部工程backlog。
- WS quality/coverage/replay/resync按格式、序列、政策文档、实际演练、执行延迟分别标状态，所有promotion/paper/live仍false。状态字符串及多个boolean未普遍跨字段绑定，必须由实际consumer和来源hash校验；计划、报告、观察事实三者继续分开。

### tests非contracts CP1/2：123文件12756行仅源码覆盖审阅

- AlphaFactory AST/PIT/purge/immutable panels有真实函数测试；champion训练/部分指标用mock。研究测试大量消费固定202605–202606 JSON/CSV和pass标记，no-live字符串/AST禁词不能证明整个传递调用图；test_hypothesis_lab_v2_no_lookahead只断言报告pass。
- compression/liquidation/lowvol/regime/range/intraday有真实未来变异或prefix一致性断言，但若只变动低周期数据不能扩成全多周期因果证明。历史测试文件数量不能代替有效收集、断言质量和当前执行结果。
- Qlib AlphaFactory有可因缺依赖skip的真实三市场训练/seal防篡改测试；time_series训练后覆写scores/calibration制造成交、另patch风险强制减仓，成交只证明research_simulated链。Qlib→组合→ResearchExecutionPipeline的合成数据/预置分数/假checksum不是真实市场验收；PyPortfolioOpt换手测试允许超阈值或fallback，不是硬约束通过。
- StrategyRegistry测试覆盖合成信号/退出/冷却而非订单成交；PaperReview采用真实manager加stub桥接，READY只到人工pending。IBKR runtime权限分流用真实对象但OMS/kill/submit stub，坏状态验证零OMS call，不证明实际交易恢复。
- experiment真实Parquet→回测→ledger/gate对象存在，但允许零fills/nonPASS；exposure缺数据回退1、手写计数999的PASS只属诊断约定。本轮未执行这些测试，未生成业务证据。

继续未读合同测试、US schema及BTC脚本。覆盖数字不代表最终评价，不扩大修复范围、不启动M1/M2–M4；服务启动与main发布阻塞仍独立保留。

## 关机续读快照：1862文件 / 598846行（固定7403）

新增142文件28735行：一般合同测试21、BTC合同测试前24、US脚本最后5、BTC根脚本21、非contracts测试25、US schema46。1720快照Node地图8/8、固定源检查catalog_errors=[]且2515清单未变。US根脚本现166文件55214行全部EOF；全部schemas/US尚未读完。仅地图记录更新，无业务测试运行或交易语义变更。

### 通用合同与策略上下文：可复用保护和测试缺口

- 一般合同21/3515中，no_lookahead_portfolio_rebalance全部测试内列表/字典/算术；walk_forward仅一项调用真实window builder，其余手写均值/常量purge；factor pipeline有真实label构建，但时点/拒绝用例也有常量。不能把文件名当生产因果保护。
- global registry schema879行多数断言历史候选、固定数值/路径/approved状态，不检最新run计算；几个负例确实保护缺schema/raw path/command与pending无候选拒绝。no-broker测试只扫描字符串并跳过不存在文件；artifact健康hash mismatch用自报a/b，不是源文件篡改测试。
- StrategyDecisionContext779行覆盖深层不可变快照、版本隔离、revision冲突、损坏文件拒绝、重启后重复事件抑制、Composite子状态一次提交；10类策略信号restart parity调用真实策略与服务。是M1行为保护可复用基础，但数据为合成短序列、不是BTC默认运行全链验收。
- OKX live preflight400行实际测试offline fake issuer的对象身份/nonce/TTL/digest/namespace/复制伪造拒绝；从设计上不注册POST、不产生order能力。测试里的live字样不代表联网、真实账户或已获实盘权限，本轮仅读代码。
- BTC合同前24覆盖10s真实窗口/ESS/epoch embargo/未来变异以及缺物理版本拒绝，输入仍fixture。10u/rollover/attack组实际运行研究模拟器的测试使用合成SQLite和固定/替换方向，主要断言格点、事件/资金保护与权限false，不是市场绩效确认。4hATR正例采用手写单行ledger；architecture gate测试runner返回固定0，collect-only也ci_passed，不等于155项实际通过。FileClosureUoW测试同run不同payload仍保留旧文件，属于现有幂等约定而非冲突拒绝；另有第二次replace失败全回滚负例。

### BTC根脚本CP4：状态文本与执行事实

- only_trend_v0的vol_scalar含当日return并乘当日PnL，即使均线延后一天，仓位尺度仍有同日信息；research_ready仅365行，而365期momentum再shift尚无有效敞口。独立向量研究链，不修改默认BTC。
- paper_readiness当前packet缺失/坏JSON会回退legacy审批；legacy只匹配symbol和APPROVED_FOR_PAPER_ONLY，未核candidate/commit。可输出paper_execution_authorized=true只是报告级静态风险，真实执行还需独立链；current packet分支仍review-only。
- paper review pack把非空dict（含全None）视为present，参数稳定性靠params_hash/fold_count非空推定；模板只要candidate_id就READY_FOR_REVIEW且不继承builder blockers。不能当WF/风险/真实账本已验证。
- metadata readiness缺provider时可能status=metadata_verified但exchange/funding_verified=false；objective_completion较严格核raw/output哈希及funding合计，但不核current HEAD/TTL。owned_id_restore_archive实际是keyring→Demo private只读入口，非离线聚合；本轮仅读源，没有执行或触凭证。

### US脚本收尾与schema46：数据/PIT和收益证据分层

- strategy_validation_gate决定status漏original_semantics/benchmark失败，blocked_data_quality也可能forward_allowed=true；evidence audit未完整继承gate status/blockers或核源HEAD/hash。专项20pct_15x的ADV未shift、空有效参与率算pass，missing volume只展示；静态风险未运行。
- 同专项DGS2 ffill后bfill使用未来值补开头；约束重算默认slippage0可能丢原成本；全样本择约束方案再混用原方案cost/WF与新capacity，固定strategy ID不能证明同版本一致。ETF26 wrapper verify_files=false、checkpoint未绑manifest/result hash，no-lookahead为常量；明确selection_sample_reused/clean_holdout=false保留。
- TQQQ-BTC命名脚本是US合成模拟，不调用BTC默认策略；源quality全失败仍返回最后非空数据；全样本择方向后rolling-start不独立OOS，ledger把下一open收益标在bar开始，不含恒杠杆再平衡成本。其danger_reference且forward/paper/live全部false，不可晋级。
- US schema CP1完整46/5552：旧CSV合同无真实available/ingested_time，adjustment无availability，与新DataReady三时间合同是版本差异；manifest path/hash仅string/record_count可0，须实际consumer校验。DataReady accepted只收紧数量/accepted、未普遍约束六表唯一和blockers为空；incoming ready未跨约束子row issues。schema限制不足不自动等于运行绕过。所有stage ready与promotion_clean/交易权限分别表达。

### 非contracts CP3：真实回测保护但仍非真实市场验收

- EventDrivenBacktest有target→pending intent→下一bar Risk/OMS/fill、同timestamp多symbol隔离、无下一bar零fill，以及现金/持仓/equity/幂等冲突断言。共享权限对象有proof身份/epoch/TTL/快照篡改负例，是应保留的资产。
- UnifiedRunner正例却使用五分钟bars_override、manifest标1d/yfinance、abc123 hash和不存在raw路径；证明字段绑定完整，不证明原始字节/PIT。数据manifest正例也有手写quality/hash，HF ETF两分钟合成一天只可research-only。
- CryptoClosure多数Stub研究/门禁/数据与手填统计；optimizer部分mock simulate/WF/ranking；RiskGuardian使用手填事实和FakeKillSwitch。强生产断言与汇总样例要逐测试区分，不能合并成“全系统运行通过”。

下一步继续未读差集与图上关键来源引用整理；上述风险不自动生成修复票。M1前置完整审阅、独立验收与页面发布阻塞仍保留，全部交易授权false。

## 关机续读快照：2062文件 / 657667行（固定7403）

新增200文件58821行：root BTC合同24（dataready_consumer 2600行已分段EOF）、BTC根脚本CP5–7共30、非contracts CP4–6共60、US schema CP2–4共86。US schema现132/22836全部EOF。只登记阅读证据，无业务测试执行、无真实运行/账户/凭证访问，main未发布。清单仍2515/808857，未将额外fixture混进代码分母。

### BTC合同：强内容校验与报告预设要分开

- dataready_consumer的测试不止schema：真实临时JSONL/manifest/resolver验证K线OHLC/PIT/步长/行数和L2两侧深度/CRC/序列/重连/端点/单调时长，包含重新哈希后内容异常、极端Decimal、NaN、虚报行数和额外payload拒绝。manifest discovery的Git树/commit_exists仍stub，正例只有两组3行K线和3条L2；quality_checked不等于真实数据集已通过，也不升research/backtest/promotion。
- canonical observe launcher使用临时Git、main/worktree、owner marker/pin/固定exe/hash/env清洗，负例保护不覆盖和失败关闭；内部job/consumer仍fake脚本、receipt/hash手写，不是实际连续观察。control center测试用真实外部artifact store和API reader，状态依然手填，错误root/权限旗标/路径泄漏负例有实际价值。
- current-head rebuild真实验证原子pointer/hash/DAG/schema/锁/缓存不匹配和失败保留，但正例promotion/nonflat/funding/privateWS/25小时用手工数据，current HEAD也fake。数据/自然时间验收仍必须另做。cost-aware order intent使用真实Signal→Forecast→Target→Intent，覆盖缺成本、收益不足、风险停止及最小差额；不提交OMS。
- bounded_retest的正例runner_command甚至是不可执行的Python导入/参数文本，只证明报告字段存在；full-ledger正例是手工JSON计数/PnL，不从fills/cash得出。current_status测试明确把ready_for_paper_start与start下一步显示为paper_observing，正是需要登记的状态语义混淆。current_packet审批测试接受预设review hash，无本轮人工审批事实。
- 公共collector及跨venue诊断测试保持private/orderfalse；data_status测试依赖202606静态latest与手填ready，available_time=close_time即使ingested晚5秒，不能据此证明供应商PIT。fee模型fixture允许capture日期晚于报告generated日期，实际attestation时序验收仍未证明。

### BTC根脚本CP5–7：研究、报告和启动入口并非同一条链

- paper_validation_artifacts replay_fn返回原outputs，DAG ledger复用PnL状态而非重算fills；missing/roll非PASS分支缺perpetual_risk_policy，调用者直接索引有静态KeyError风险。缺文件返回非空dict还可绕过truthiness。start报告实际调用readiness子进程和ledger锁，不是纯JSON读取；本轮均未执行。
- evaluation实际走quant_us默认pullback_reclaim，已加载15m却传None；不是恢复批准candidate参数。trade重建BUY覆盖、SELL后全清，不支持partial/short/funding。provider完整性重点1h/4h/1d/mark/premium/funding/metadata；5m15m诊断不在同一强hash/grid校验，PASS不代表paper短周期输入可用。
- registry把legacy/current的passed计数取max、候选取并集，识别的current queue优先但没有统一HEAD/hash/TTL绑定，GA/TimesFM子blocker也不完全上提。all_strategy/volatility/top族排序有全样本选择；Donchian未用vol_target造成重复变体，ATR40实际是ATR20的40期均值，退出可能同bar重入。不得把向量研究PnL视为默认运行账本。
- priority/top脚本确有1095/180滚动选参，但策略族先按全样本选，最终赢家/部分统计又用全样本；旧v0 gate计算train_best却验收默认参数，positive fold只展示。only_trend同日vol风险在robustness/volatility的整体shift口径中不同，未来统一须先冻结各版本，不能一改全改。
- trend paper/raw forward把snapshot行数当30天，空targets/缺state可不阻断；raw forward有365momentum重算，但并未验证唯一连续日历/fills账本。tail依赖旧20260516 artifact且零PnL事件也可合格，未绑定当前candidate。trial registry即使paper gate失败仍selected，accepted只据fail_reasons为空，strategy_id缺失仅warning；complete是登记完整性，不是晋级。

### 非contracts CP4–6：保留真实安全基础，限定测试证明力

- CN真实PIT/交易日历/T+1/公司行为/零股/时间边界及Signal→Risk→offline OMS→Fill→Ledger有测试；license/quality/document ID仍手填，immutable研究正例手工hash也可backtest_validated但promotionfalse。QMT recorded/synthetic都是fixture，真实归一化/对账测试不构成交易商连接。
- IBKR controller/recovery、幂等fill ledger和权限护栏是真实对象；多个故障矩阵只是同一transport_lost(reason)，不是真实崩溃。closedloop为合成数据、假HEAD、即时离线client并跳过session/扩大freshness；不代表下一bar或30天连续观察。JSONL多线程/重启有覆盖，fork/fcntl项在Windows跳过，平台保障需单独验收。
- 名称live_canary/shadow仍FakeTransport/FakeClient+真实authority边界，forge/TTL/revoke/timeout保护有价值，不能称live。ETF26 shadow真frozen target→风险裁剪且OMS无handle，lineage错误拒绝；CLI报告路径mock不证明真实观察。
- PaperRuntime多周期watermark/asof/归因和JSONL有实对象，但MarketDataLoop/Freshness/starter reconciliation常被stub；scheduler整体fresh与某子周期stale可同时存在，展示需按粒度解释。worker启动同步覆盖隐藏submit/cancel、缺计数器、wrapper恢复与失败kill/reduce-only，正例FakeAdapter且提交止于Mock OMS。
- paper review测试明确APPROVED_FOR_PAPER_ONLY/entry_evidence=true同时execution_authorized=false；应保留这一区分。validation resume正例手写days_completed=30、伪Parquet或daily_results=[]，证明恢复/报告合同，不是自然30天。另读6个CSV fixture18行在固定代码清单之外，仅作理解辅助，不增加分母。

### US schema收尾：版本别名与晋级条件不是自证

- 全部132合同已EOF；operator_read_model称canonical alias却非$ref，缺canonical部分必填/层枚举；通用artifact_path_reference更严格，具体read-model有较弱路径字段。这里是schema约束差异，不已证明resolver可逃逸。
- portfolio/production阶段顺序和固定旧ETF26候选、历史计数、20260713–20270712计划仅是格式/历史合同；缺跨字段绑定不能代替真实结果和current HEAD。manual record→packet→readiness→显式run审批各层仍独立；paper_runner及交易旗标保持false。
- IBKR reconcile clean/allow_neworder判断不是交易授权；scenario enum/mincount不保证唯一样本覆盖，constant passed不等于运行。final ready约束review/root blockers但未普遍强制全部先决checks，需consumer测试继续确认。
- current_head_gate_rebuild成功固定consume_blocked_artifact；daily_monitoring的replay_diff仅缺source/unexpected_status，不是策略/风控/账本数值重放。部分safety允许任意false字段而非每个命名字段，不能以最弱schema作为授权根。
- ETF26 no-submit schema固定injected_fake/OMS未调用/零写；Yahoo→IBKR runtime语义合同禁Yahoo warmup fallback、要求IBKR completed bars，但session/freshness等子对象宽，执行约束须到实际consumer与测试核验。

剩余453文件继续按已分工差集EOF；不删除历史入口、不启动M1、不以此重建promotion证据。地图/服务发布阻塞独立保留，研究完成不产生交易权限。

## 关机续读快照：2223文件 / 694878行（固定7403）

新增161文件37211行：root BTC合同32、BTC根脚本CP8–9共24、非contracts最后23、US合同CP1–2共82。固定清单非contracts测试231/41390全部EOF；额外6CSV18行不计分母。2062地图静态8/8、catalog_errors=[]；main f3a78afe0b59差异仅前端3 changed/7 added/0 deleted，旧3文件阅读失效须补main版本，业务核心与固定基准无变更。剩292文件继续，不将源码差分当业务回归通过。

### BTC合同32：观察、计算和执行授权的真实边界

- Guardian实对象验证sticky trip、首次非空仓/未知订单、OCO owner/quantity、ack不清除且须更新健康观察；operator退出动作按running/frozen/flat/unknown互斥。production composition实际构造Signal/Target/Intent与组合风控、notional/成本/OCO，拒绝trusted guardian bool、快照hash/数量/资金费/PnL/新鲜度变异；输入账户/WS/ledger手工构建，proof仍pending_dispatcher_authority，不是实下单。
- observation accumulator实算连续小时、版本/进程断点、累计与当前segment、哈希链、重复/回填冲突和fixture不计；所谓real25h正例由循环造25条authorized_runtime_observed=true、natural_sample_count=0，不能作自然时间实证。private_readonly runner真实单写lease/恢复/事件去重/错权限/失败脱敏/授权先于keyring护栏，但provider/WS/clock/CLI授权皆fake或patch；本轮未执行入口或读取凭证。
- depth_slippage真实可见时间、BTC过滤、稀疏间隔、序列、单侧、薄深度、最小量/成本与确定性；legacy history正例48个8小时快照再配手填mapping。official正例resolver的full_hash_verified/manifest_blob手填、单depth+人工simulated_fill可promotion_evidence_ready=true（交易gate仍false），不证明自然成交证据或订单级queue模型。
- exchange/runtime gap与perp replay测试用手填31天/filled/reconciled/json决定ready，公共probe的FakeCollector对大多endpoint仅返回{ok:true}亦显示mark/index/funding/depth可用；它们是报告投影测试。execution_quality实际从OMS生命周期算部分成交/撤单/拒单/延迟/费用、拒绝orphan/unreconciled，但fill与risk/reconcile事实人工指定。
- Forecast真实IC/hit-rate→confidence、强度→bps、上限/换手/现金/冷却/停损/异常hold函数，质量证据hash是sha256:test且IC手填；不是训练校准模型。衍生品gate正例32合成行并降低min_rows=30，enabled_for_alpha_claims只代表特征合同；OKX liquidation测试把sz直接乘price锁定成BTC口径，未测合约面值换算。基准策略不受本轮改动。
- 外部框架采纳/泄漏CLI主要检查空源码文件/关键词/伪Git ref/手写报告，implemented不代表真实第三方集成。fee importer拒未来capture、NaN、无来源、dry/apply分离有测试，但旧fee cost-report接受时间口径不同；funding overlay允许空adjustment响应加历史spacing推定，验证并非历史规则沿革。funding payments有真实long/short/持仓时点算术，merge正例从手工trade ledger出发。manual patch严格固定34时间格、hash/冲突/重复拒绝属于历史补丁合同。
- external observe job比launcher stub更深：真实临时Git/manifest publication/resolver/external owner/overlap/no-write/hash，网络替换为抛错且输入不变；样本只是public:true及blocked L2 receipt，结果all_files_verified且blocked，不能冒充真实市场输入质量或执行观察。

### BTC脚本CP8–9：微观结构研究不能替代交易所执行证据

- true_scalping prototype/redesign/proxy是Binance spot 1m、下一open/固定2–15bar/1BTC模拟；OKX单点spread/REST latency跨历史作成本，queue仅字符串、无真实regime注入。六等分没有训练/purge/holdout，按同段排名，pass_rate只以≥20trade有效段作分母；数据版本词典序不绑SQLite/asof，short无borrow/funding。
- execution_queue外部合同虽核文件SHA，但sample/clock/IDs/queue labels取manifest声明，重复文件可累计；long_horizon按min/max日历跨度，无连续覆盖。aligned quality一个共同sequence+接收差≤250ms即可format_ready，未全面检查exchange_ts/monotonic/gap/checksum/50层，NaN可算observed；event/paper恒false。
- WS replay记prevSeq gap后仍更新book/metrics，未按connection/instrument隔离，坏JSONL静默跳过；resync quarantine/drop是政策文字，exercised仅看计数。coverage累计声明duration不去重，format/coverage部分成功条件未纳入public/channel/resync或已计算的monotonic失败。latency queue代理未在gap重置，notional直接price*size无合约面值，不能叫订单延迟或真实排队。
- architecture gate collect-only可ci_passed，64+91数量固定；runtime_local_ci默认builder链可包含public probe与产物写，名称read-only不足以保证无副作用，本轮没运行。rootcause CI只status/blocker/count，freshness仅展示。
- paper_validation preflight确实校包SHA、metadata raw/HTTP、cycle唯一与recon hash/锁；仍没把approve candidate/HEAD绑当前候选，也不读review正文，5m15m仅非零行。raw/daily readiness只拒绝ledger路径完全相等，不证明父子目录隔离；raw367行不证明当前freshness。

### US合同CP1–2：质量标签与业务充分性

- FRED freshness/preflight明确允许失败导入后本地DGS10+DGS2各一行PASS/WARN；kline三日两标的干净OHLC也可promotion_clean，仅为局部质量标签。IBKR minute coverage按文件chunk覆盖三天，fixture实际三行都元旦首日；backfill成功min_coverage_ratio=0，不是XNYS分钟验收。
- incoming drop严格六文件/重复ID/日期UTC，readiness失败不调用import/activation、apply显式confirm及备份有保护。DataReady accepted fixture每表只record/event/available/ingested/splice、调整表另available，不含完整证券/价格/行动业务字段；hash/PIT顺序负例不能自动证明业务充分。
- local_csv string_false测试把未加引号false写YAML变布尔，未覆盖字符串真值问题。Yahoo坏价格测试删行后PASS、Tiingo同类partial是语义不一致；IEX只测split相对RTH开盘，未测发布/入库/修订时间。Yahoo–IBKR真实收益比例而非绝对价校验，缺CA entitlement/adjusted数据负例补足部分schema约束。
- ETF26 canonical有真实部分成交取消、零量拒单、截断一致、fill/position/cash篡改及exposure不改变ledgerPnL保护；缺available_time仍可truncation通过，不是PIT认证。多份macro/WF/parity测试只断言历史mutable latest赢家/收益，不重算；evidence audit用布尔checks+不存在路径可ready，未证明identity/实际来源。
- 合法data handoff仍因immutable manifest未resolve/acceptance未run而blocked的测试，应保留。模板、branch、fixture与可消费production交付是四种状态，不能合并为ready。

### 非contracts收尾：统一工厂、Qlib与治理的测试边界

- AlphaFactory真实service/queue/seal/resume/并发锁/失败持久化，但训练与campaign是fixture；Qlib API每stage失败仅统一run函数抛指定字符串，不代表每层实际失败路径。closure/review/CLI多patch PASS，BTC forward API手写202606历史JSON/CSV，不是current观察。
- research-only AST/regex只覆盖命名import/call/字面API，不是动态调用图证明；global registry不等于live的部分集合断言本身恒真。治理有真实临时Git/crossbranch/hash/append-only/sparse/timeout测试，workflow forbidden_capabilities仅非空检查，不是OS能力隔离。
- private-readonly权限原子claim/线程进程单赢家/arm-bind/replay-revoke/TTL/turn/session是真实状态机测试，但autouse签名verify恒True/identity stub，负签名靠子进程返回码stub；无真实签名、private网络或宿主隔离验收。TeamContext external root正例替换正式published reader，必须与publication自身校验分开。

新发现只进入架构审阅，不自动开工程票；M1仍待完整审阅后重评，M2–M4未启动。

## 关机续读快照：2446文件 / 778343行（固定7403）

新增223文件83465行，逐文件/blob/reader/EOF范围在catalog：root最后48个BTC合同8718行；US合同CP3–5共62个及其BTC合同CP1共30个；BTC根脚本CP10–12共36个；前端审阅代理BTC合同CP1/3–6共47个。US合同144/29178全部EOF。剩余69文件30514行：BTC根脚本9、US代理BTC合同36、前端代理BTC合同24。所有下列发现是源码审阅，均未运行对应业务入口。

### US合同收尾：声明消费与内容复算不能混淆

- credentials review有真实嵌套脱敏/hash/缺失拒绝，但operator handoff的local=true不是实际凭证可用性；execution drill五类报告输入不等于真实broker故障。manual decision只是可追踪审批文档，paper final complete仍不能自动执行。
- paper UOW七文件回滚、simulation fills/positions/cash重算及篡改否例应保留。IBKR30天fixture反复使用同一data.as_of和freshness=fresh、forward252用自然日含周末，不能用通过数证明自然时间或交易日覆盖。
- artifact_schema_coverage只遍历已存在latest，无存在/最小数量条件，可空集合通过；framework adoption以空文件/伪ref/布尔记录表示adoption。current_head_rebuild测试关闭旧schema校验并mock全部builders，daily58步也都是fake，回归证明力须分层。
- old forward daily在evaluation前先写PASS/evaluation_not_run；健康stale可WARN，remediation空tickets可closed但上游仍blocked，局部完成不是全系统ready。v3successor明确允许dirty worktree来源，不能误说所有历史consumer都只读提交对象。
- v3paperOMS真测UOW、重复、坏状态、reconcile halt；部分hash测试只比code_binding字段，不等于重算hash。大量Top1/杠杆/TQQQ测试依赖mutable latest固定结果，不是本次训练或市场事实。

### BTC采集/运行脚本CP10–12：入口名称不等于权限与副作用

- archive importer共享raw_dir并仅取URL basename作缓存；klines/markPriceKlines/premiumIndexKlines同名，存在错误复用风险。历史month枚举无条件去掉结束月、funding无daily补足。OKX/archive funding以fundingTime匹配1h mark open_time却使用该小时close，存在结算估值前视风险；OKX ingested/processed回填为历史available不能代表实际入库时间。应在后续独立数据修复票复现，不改变M1目标。
- 公共采集可能改provider YAML、bundle manifest及marker；REST trade/books顺序请求并把接收时间截成秒，不能证明250ms对齐。tail merge逐文件覆盖后验manifest，无bundle事务锁；旧repair只看首尾覆盖且success忽略errors。public/dry-run绝不等于本地无写入。
- 10s immutable feed有真实clock→capture→export→shared quality_checked、OS writer锁、owner/sourceHEAD和空间护栏；continuous默认prune，会在严格核验路径/hash后删除capture/export。旧L2 observer已有complete直接返回、不重新绑定新HEAD/duration，累计时长与首尾跨度不等于连续24h；cached clock/attestation/publication的exists复用须与当前来源区别。
- canonical outer绑定main/工作树/HEAD、7个保护文件blob+dirty、Git程序SHA和receipt，writer锁内原子发布；inner强制blocked，outer退出0仅表示基础设施执行完成。直接调用inner不能替代outer的真实HEAD校验。零参数private-readonly runner先消费一次授权再keyring/WS；remote supervisor另入口直接keyring/private-readonly。Demo fault runner显式授权后有真实订单/保护/取消能力；这些入口均未执行。
- 旧alpha hardening的regime trade PnL未扣fee、零交易regime算pass；PBO train_sharpe取全样本summary，no_lookahead/ledger一致性字段硬编码。daily paper wrapper只计5m/15m行数，SKIPPED周期可能跳过新检查。L2 batch readiness消费调用者manifest_verified/attested布尔、post_capture_reports_built只代表函数返回；都不是M1可复用的权威证据。

### BTC运行/执行合同：保留强测试，也明确fixture边界

- 16169行Demo runtime大文件并非全无价值：实对象覆盖policyhash、单写者、intent-before-POST、authority TOCTOU、timeout先查不重提、未知仓位非flat、owned-ID/hash绑定、Windows路径、跨进程锁及funding账本。其provider/审批/HEAD仍fixture，大量recovery/worker/snapshot/ledger被patch，自填synthetic=false不能改变来源；25h来自即时循环造时钟，非自然观察。
- 部分assert不检查被测实例：Demo runtime 3548–3621与owned_id_restore_archive 538–541；部分durable-before-submit只看内存或事后文件存在（runtime 7443–7479、live_canary451）。这些是静态弱断言，不声称运行缺陷已发生。owned-ID恢复测试还硬依赖仓库外历史archive，本轮没有打开它。
- privateWS真线程Event隔离迟到worker，但socket是fake；public collector真parse/write/export和UI hub race，但SSE用手写event可skip。immutable observer/24h和liquidation公式验证多fake；L2 exporter/dataready有更深hash/序列/单调时间/空洞负例，不能与只消费布尔的报告测试合并评级。
- paper runtime真串readiness→event backtest→JSONL ledger、两线程同周期/跨周期互斥、os.replace故障与半写恢复拒绝。正例审批commit=fixture、metadata HTTP200手写；flock在Windows可能skip，部分lock helper无fcntl恒false。start_report所谓compatible runtime是标记常量假runner加打印PASS的假preflight，不是服务验收。
- bundle/PIT/provider确实有hash与时间次序测试；raw cache漂移在output hash一致时可warning，另有Binance数据消费手写OKX formula正例，不证明同venue。perpetual replay真实风险/lot sizing/模拟fills/OMS，但flat pending、research模拟与execution promotion仍分开。promotion_control真聚合26源/freshness/DAG，96h有效期fixture不是刚生成证据。

### BTC合同后段与root收尾：M1应该复用什么

- GA中future-row/selection-tail扰动不变、族内交叉、风险参数不得进入genome、先落候选锁后单次holdout reveal、拒绝时不读holdout，属于可复用行为保护设计。gate_snapshot的immutable batch/HEAD漂移/锁/指针损坏无fallback同样重要。
- gate aggregation大量mock；fold_regime单行passed=false仍fold_status=pass、manual definition-only全source_reports=None仍可批准，只是结构/研究定义。strategy ledger固定五线，不是统一Alpha注册表；backtest identity正例ledger hash是占位字符串，不能宣称账本重新验证。
- raw/trend daily有真实t+1、幂等、模拟fill、target/snapshot及ledger篡改否例；30天通过是即时循环历史as_of，ready依赖手写计划/冻结报告。trend boundary只给不存在的artifact路径字符串也可complete，不是内容贯通证明。泄漏/holdout审阅输入中self_check_violation_count=7仍可得到局部pass，需看具体检查含义。
- scalping外部队列正例CSV只有表头，manifest宣称120/140样本即可contract_satisfied；long_horizon实际各1行，manifest宣称31天也可满足。microstructure readiness表头文件+model status=pass可ready；这些是声明合同，不能当已读并验证全部payload。对应的深层dataready内容检查不能由这些薄报告替代。
- WS coverage把不连续两段15天声明累计为30天，resync exercised来自手填计数；旧replay可缺独立checksum但记录deprecation政策。独立public adapter合同仍实测checksum/sequence/time-gap→cancel_only，funding合同实算fills/position/cash=9.599；offline closure明确quality_checked并保留external blockers，不是真实WS、paper或live观察。

### 当前main增量已另读，避免基准覆盖冒充current

main `f3a78afe0b59d432820dc8f50510038df6c00754` 相对固定基准3 changed、7 added、0 deleted，仅架构前端及接线。以下逻辑全文EOF由root补读，不增加2515固定分母：App.tsx165行/blob1a093e94bfdd81febada7895bf9e2ea41facf9f9；Workbench.tsx889/5b28af6729aba50f1330469d58eab03b8c197132；ArchitectureMapWorkspace.tsx133/efb2f5b67dc6547d4c1c15ee5aab709687badafe；architecture/model.ts33/46e5ea7babbf9dd0dac62f4fc8f00b79212ba284；architecture-map.css76/1db4905e8c18025f0cf03418e62f4a7c8158d84a；e2e/architecture-map.spec.ts69/f05445bbebc0c585fe2b87f2bda5f0baf7dfc43e；scripts/architecture-review.mjs130/7c5659c7edebf3fe6a84fa27ff5e51a85a17efe1；scripts/test-architecture-map.mjs64/0c7c754abe398dba2d713f9f2e53d23523bc884b；e2e/system-workbench.spec.ts605/33ca9adb3d21a30950c462c0eb486cd76f92db88。另读generated frontend-identity.json33行/blob72c1ece49f175f337fa016ddba06fae7a36984f1，不属代码分母。

main catalog blob07b074230b02b28c684d5202239b0eb9b7d2773a的手写模块/边/发现前缀已全文读；其生成文件数组仅解析校验元数据（旧340EOF），不声称逐行人工EOF。页面lazy route、本地筛选和30条分页不新增交易/API写入。E2E mock GET health/strategy、其他503，是前端隔离测试；shell静态LIVE FALSE不是授权快照。此轮最新账本在producer未发布，不将主页面旧计数说成已更新。

剩余69继续读；源码覆盖、静态测试、前端运行和业务验收四种状态保持分开。

## 全量源码阅读收束：2515 / 2515，808857 / 808857行

最后69文件30514行全部入账，missing=[]，无重复path，所有固定对象blob/bytes/lines与7403一致。此前2446+本批69=2515。BTC根脚本177/69169、US合同144/29178、非contracts231/41390以及所有既定目录均已收尾。整体采用主代理与三名只读分工，不称全部由主代理亲读；不含第三方依赖、真实数据payload／凭证或生成产物全文。

最后fault_drill合同5135行/blob32cb293c4090f121165c26282264b30aebe6a1cb分读：frontend_source_audit_resume连续1–2500，root连续2501–5135；catalog.reader保留双方范围，read_ranges合并为完整1–5135，不把任一半段冒充单人全文。

### 最后BTC脚本与合同的实质补充

- paper validation按唯一cycle_key递增days/consecutive_clean_days，无自然日／间隔／重叠校验；backfill调用同一runner/default ledger且边界包含，0窗口或全SKIPPED亦PASS。该runner消费quant_us crypto_event和其ledger，不是默认BTC Demo OMS；部分15m输入为None、flatten行为按分支不同，报告却统一标enabled。
- raw-trend链的IC=.01/sample_size=1是固定值，Forecast上限借本周期实现收益；风险后target又覆写为原0/1。伴随OMS只create/mark_risk_checked，模拟fill／权益不消费cost gate或OMS成交结果，不能称权威订单驱动PnL。周期末close成交却记整周期收益；重算同公式不是独立对账，倒序／OS锁未保护。SKIPPED仍可改写同周期chain证据。
- perpetual daily先旧cost/evidence→replay→mapping→新cost/evidence，不重跑replay，可能混合依赖版本；complete只代表无抛异常，CLI0不能表示研究或gate全部通过。没有为了本审阅重跑这些入口。
- 后段kline exporter有deterministic/finalized/hash/gap/freshness→shared consumer保护；micro-live candidate构造就绪仍live=false。manual metadata直接函数省sidecar与受控Make顺序是不同入口，不能由测试推断默认治理被绕过；manual approval文件hash不匹配可warning仍recorded，仅review-only。monitoring complete与当前数据freshness也非同义。
- operator V2真durable store/并发/fence，portfolio_exit真纯转换，regime search真未来扰动和先落锁回调；主要正例仍fixture。research/runtime parity仅同函数换source不代表两适配器集成；source_role把recovered=true/backfilled=4手填即可complete，不等于物理补洞。保留这些合同，同时明确其证明上限。
- nonflat autocapture测试手写simulated_fill_created/gateeligible/privateWS/funding observed可promotion_evidence_ready，反映来源／布尔消费边界；objective audit确实核hash与CSV数值，但成功fixture中metadata raw与overlay可空文本；current_head orchestrator多数builder mock，离线closure仍保留真实funding/privateWS/nonflat/25h/manual blockers。
- Demo adapter有GET有界重试／POST一次／只读client无提交方法，watchdog只写自身去重alert、不续约或改runtime。fault drill后半真binding loader／runtime store／当前Git祖先链／篡改拒绝／writer锁；真实场景结果仍FakeRuntime或手填exchange truth。部分用例硬依赖仓库外历史receipt与当前Git历史，本轮未打开该receipt，更未执行其private调用。
- fault drill缺失fill order_id只有唯一归属时兼容，歧义阻断；terminal receipt另写不可变文件且保留原失败receipt，unknown POST不重试。worker kill用fake process验证nonce/PID/create time，不是真杀进程；parent failure的post_calls列表从未连接被测对象，是弱零调用断言。expiry deadline凭手填server time和相同hash证明报告消费，不是自然时间观察。

### 本次地图自身回归

- 2446时静态8/8通过；2515全部EOF后旧测试失败2/8：要求真实catalog必须有unread、从空unread集合取path。先记录真实失败，再将否例改为显式构造unread fixture，新增全读不授予权限回归；最终9/9通过，不修改业务validator或权限合同。
- 基准检查器：2515/2515，catalog_errors=[]，source_inventory_unchanged=true，runtime_verified=false，trading_permission=false。TypeScript --noEmit无诊断；精确退出码在验收补充记录。
- main差异仍是已另读的架构前端接线，不将旧发布340EOF或历史浏览器通过数作为本次页面验收。当前producer未集成／服务启动执行策略阻塞单独保留。

阅读前置至此完成，停止全仓漫游。重评与下一步M1固定边界见REASSESSMENT；本轮不启动M1实现、不启动M2–M4、不删业务代码，不解锁任何交易权限。
