# Donchian 离线重复计算优化：一次小样本证明与全年运行准入

> 下文“第一阶段”记录的是 1.88x / 2.10x 的早期结果。用户明确认为不足并授权继续优化；该结果**不再作为启动全年的最终验收**。第二阶段冻结候选为 `dbac2d21cd5c90bcc636919fa375382cd4182be0`，小样本通过，同票停止性能改动，等待独立集成后的全年运行。未合入 main、未启动交易。

## 第二阶段：规模相关重复工作（当前）

追加 touch set 已逐项 safe_status 确认 clean：`quant_crypto/research/simple_trend_rule_lab.py`、`quant_crypto/research/multi_timeframe_rule_lab.py`、`quant_crypto/research/long_short_trend_following_lab.py`、`quant_crypto/application/btc_strategy_registry.py`、`quant_crypto/oms/runtime_store.py`。仍不改策略数学规则/参数、风险、下单、退出、保护、持久文件格式、checkpoint/fsync/落账或权限。

- finite、float64、连续 UTC 小时数据使用等价数组块聚合；缺行、非 UTC、非数值或其他形状仍走原实现。固定周/月边界 UTC 计算也向量化，其他时区与对象类型保留旧路径。
- Top5 已有四种信号分支不消费周/月线；不再计算这些未使用输入。新信号类型保留原通用计算路径。
- 原状态循环仅将已对齐且唯一索引的数值 Series 取值改为数组索引；所有入场、退出、ATR、冷却顺序保持原函数。未对齐等输入仍走原取值路径。
- `BTCRuntimeStore` 增加默认关闭的 `verified_prefix_cache`，仅离线子类在首次完整恢复后开启。每次仍读原文件，**逐字节比较整个已验证前缀**；变化/截断则完整重验，新尾部按原哈希链/幂等键验证，checkpoint 每次重验，异常即清除缓存。既不靠 mtime，也不信任路径、status 或声明。
- 已验证事件的复杂字段仅从本进程编码的私有快照按需展开，避免每次恢复完整复制所有历史账户 state_after。缓存绝不从磁盘/网络读取 pickle。每次恢复的 Mapping 视图和复合值互相隔离，外部修改一次读到的 payload 不会污染下次恢复。离线对外结果将选中的 ledger 物化为普通 dict；生产默认仍返回原 dict 事件。
- 不改变 shared schema 或落账内容；`BTCRuntimeRecovery.events` 的内部类型标注扩为 Mapping 以容纳离线读视图。不是第二套账本、不是省略历史验证。

第二阶段诊断与测试：

- `optimized64.prof`：64 根完整链 signal 106.73 s，其中小时聚合85.709 s；388次recover 31.726 s。仅用于定位热点，不与未加 profiler 的计时比较。
- Failure-first：数组聚合 1 failed/3 passed；原日志缓存接口 6 failed；未使用日历/重复索引检查2 failed。实现后数学及注册策略回归49 passed。
- 数组状态循环、原数学规则及全链第一次集中回归 **187 passed,1 skipped /121.65s**（在按需事件视图加入前）。
- 按需读视图加入后的缓存、篡改、非零成交/重复/恢复和原runtime hardening：**56 passed/73.57s**。被篡改内容即使恢复相同文件大小和mtime仍与原 verifier 一致拒绝；截断、坏尾部、错误checkpoint、重算哈希后的日志替换均对照原 verifier。
- `scale-history24` 和 `scale-continuous` 为第二阶段中间候选 628d9a649，**非最终性能结论**；当时计时明显受不同机器负载影响。
- 中间 `scale-history240` 在已暴露反复展开历史快照成本后停止本任务自有进程，保留全部文件和 writer.lock；不作240根完成证据，不重启或消费该中间状态。不是正式全年运行，也不是用户旧45根关机现场。
- 最终计时增加进程CPU时间与逐phase耗时；同一测试工具顺序执行、未并发跑测试或 profiler。不同时间的机器负载明显不同，因此不将早期46秒基线直接与此次候选相除。

### 最终小样本结果（第二阶段准入）

| 样本 | 旧源码906620792 | 新源码dbac2d21c | 结论 |
| --- | ---: | ---: | --- |
| 同机重测24根历史，原4800根预热 | 195.6100072 s，CPU181.1875 s | 21.2408868 s，CPU14.15625 s | 墙钟9.2091x，CPU12.7991x；完整经济投影相等 |
| 同一历史起点240根 | 不重复运行慢版240根 | 107.658092 s，CPU78.125 s | 240事件、0阻断；前24事件与24根对照严格相同；仍是0成交样本 |
| 原V1非零成交、重复及逐阶段重启 | 复用已冻结业务投影，不作跨负载速度比较 | 5.6124577 s，CPU4.0625 s | 4单/4成交、归零、权益4999.988、费用-0.012；经济投影与旧版相等 |

240根样本的前24次phase均值0.588287s、末24次0.469436s；只能说明此样本没有重现原有严重增长，不能保证8760根线性耗时。仍逐次读取并比对完整日志字节，随着账本增长存在剩余成本，不以此自动扩成存储重构。

最终证据根仍为下文 external offline-runs 根，以下 SHA256 固定文件内容（不是未提交源码交付）：

- `frozen-fast24/benchmark.json`: `990ee7c97a801c5af3e6f7d13a2463818e39c599c57244139f57ab827b2e88a1`
- `frozen-control24/benchmark.json`: `f3601be92839e40f1a1dfbef349d5ee190a72f8ba1806b9a6bf40661649b4d8e`
- `frozen-fast240/benchmark.json`: `c9688ef0af4447311f06fd994be0fe5f6d6cc1e3fbeb2d6b393cd003fd5aa746`
- `frozen-fast-continuous/benchmark.json`: `fa6828d2b8fd4b9c47bf839204ad5d6d5ef3e19e03a6aca95f61935f63e4c12c`

最终源码56项专项回归已通过；完整限定矩阵由独立 integrator 在集成候选上复跑，避免把按需视图之前的187项结果冒充最新完整回归。独审应重点核对 Mapping 消费、序列化与缓存篡改边界。只读发布、页面验收、主分支合入不在本票授权内。

## 第一阶段记录（保留，不代表当前完成）

## 边界与身份

- 用户明确旧运行是关机中断；本票不修后台保活、不清旧锁、不改关机恢复合同。
- role: btc_developer；change_risk: demo_execution_semantics（保守审查类别，不授予 Demo）。
- producer base: `9066207923dd29e8ef7afc997579570473959d53`。
- 小样本被测源码: `16a20adddf04c9f6dc0e8109261de45cc75aceff`。
- 主工作树仍 `e2e7496acaa16b9fd5eda37dd65ea328a18ab032`，未合入或重启服务。
- 新票独立 sparse worktree `btc_developer-donchian-replay-perf-20260921`，初始限定 safe_status clean，无覆盖其他 worktree dirty。
- 实际 touch set：`quant_crypto/application/donchian_offline_replay.py`、`tests/contracts/test_donchian_replay_performance.py`、`scripts/benchmark_donchian_replay.py`、本报告及本票 append-only handoff。
- 未修改原 signal_callable、策略注册表、参数、风险、OMS、保护、账本、权限、生产 controller、历史数据规格与编排。

## 只做两处性能修改

1. 离线专属 controller 子类仅缓存原 `_signal_decision` 的纯信号读取。预览和 run_cycle 在相同策略身份、callable、完整 DataFrame 上复用；不是缓存风控、账户事实、订单或账本。未来输入交回原校验。正常生产 controller 不变。离线 provider 存在时原方法不消费 client，因此 preview 无 client 和 cycle 的模拟 venue 可以共享结果。
2. 保持 `canonical_completed_ohlcv_v1` 原指纹格式。将行编码改为 itertuples；每次仍校验时间结构并精确比较已验证前缀，只有完全相同的前缀才复用其编码，追加行仍作原 Decimal/high/low 校验。每次仍计算全量 SHA256。修改旧行、缩短前缀、恢复进程均不能沿用错误缓存；返回对象与私有缓存分离。

不预计算未来信号、不截短原策略预热、不省略账本恢复/哈希链校验，不将状态不明补成正常。

## 性能与业务证据

证据根：`D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-perf-20260921`。

完整链 cProfile：4 根回放 14.233 秒（不含入口和数据加载）；8 次信号读取 10.226 秒，canonical_frame 2.859 秒；recover 28 次 0.278 秒。诊断文件 `baseline.prof`。Profiler 时长不与普通计时作提速比较。

以下为同机、顺序执行、同配置、无 profiler 的工程对照，不增加研究搜索次数：

| 样本 | 冻结旧源码 | 优化源码 | 比率 | 业务结果 |
| --- | ---: | ---: | ---: | --- |
| 真实历史起点 24 根 + 原 4800 根预热 | 46.1749125 s | 24.6100064 s | 1.8763x | 24 个事件的信号、阶段、仓位、现金、权益、费用、资金费、计数与安全旗标逐项相同；无成交 |
| 冻结 V1 连续业务场景，包含重复事件和每阶段重启 | 37.3183856 s | 17.7563210 s | 2.1017x | 4 单/4 成交，最终仓位0，权益4999.988，费用现金流-0.012；现金、仓位、资金费 ledger 相同 |

文件分别为 `baseline-history/benchmark.json`、`final-history/benchmark.json`、`baseline-continuous-valid/benchmark.json`、`final-continuous/benchmark.json`；完整历史报告和 runtime ledger 留在对应子目录。连续样本跨运行仅排除 `decisions[].signal.signal_id` 生成 UUID，其他投影字段全量精确比较；单次运行内的精确关联由原 V1 测试检验，不要求两个独立运行的随机 ID 相同。

早期诊断保留：`optimized-history` 是首次未复用 cycle 的中间实现（36.5935 s），不作为最终提速证据；`baseline-continuous` 首次测试工具在已完成业务断言后误读模拟 venue 不存在的 cash 字段报错，未产生 benchmark 报告，不算通过。改为读取权威 ledger 后使用新目录重跑，未覆盖旧产物。

小样本不能保证全年耗时线性；更长日志仍有全链恢复验证成本，本轮不因此自动扩成账本存储重构。

## 测试与停止条件

- Failure-first：新增前 3 failed（缺少缓存实现）；首次实现后 3 passed。
- 新增精确前缀/返回对象防污染/时钟与身份/cache callable 检查，以及从冻结 Git blob 提取原 canonical 编码对照 float64/float32/int64/object：7 passed。
- 完整限定回归：**124 passed, 1 skipped in 59.92s**；skip 为原有 Qlib 归档模型需显式 opt-in 的测试，本次未接入 Qlib。命令：

```powershell
py -3 -m pytest -q -p no:cacheprovider tests/contracts/test_donchian_replay_performance.py tests/contracts/test_donchian_offline_notional.py tests/contracts/test_btc_demo_production_composition.py tests/contracts/test_btc_donchian_history.py tests/contracts/test_btc_donchian_history_spec.py tests/contracts/test_strategy_v1_donchian_offline.py tests/contracts/test_strategy_v0_freeze.py --basetemp 'D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-perf-20260921/regression'
```

小样本工程通过 + 独立集成通过后只启动冻结全年；不继续追求更高倍数、不添加模型/市场/页面。独审发现直接阻断仅在本票集中处理，不派生工程链。

## 全年身份和限制

- 规格仍 `25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json`。
- spec digest `7a87dba25a55991f86af58c69c29772026ad3fe9f87a90cf4a5c063b0d98a38b`。
- 数据版本 `donchian-long-input-20260921-v2`；manifest SHA `349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d`；aggregate SHA `62bed3a6efa945d8fa4f52917667dc44a276add7ed280bb45085ef52950d10af`。
- 预热 2025-02-13 至 2025-09-01 UTC（4800小时）；评估 2025-09-01 至 2026-09-01 UTC（右开，8760小时）。金额上限50 USDT；亏损门槛10 USDT；固定目标仍0.01张（0.0001 BTC），不是50 USDT仓位。
- 旧 `71e5749fd9cbfd26516de058cafca50c1771816e` 的45根关机中断现场保持不动。优化源版本与旧运行身份不同，必须新技术 run ID；不改经济实验配置或挑历史窗口。
- 使用既有 CLI `run/resume/status/check-data`；单写者、版本校验、缺证阻断不变。全年结果未完成，不许把工程小样本当全年或盈利证据。
- 独立集成与全年运行待后续交接记录；无页面/主分支发布、无生产账户、无网络。生产503及真实账户验收不在此票。
- 数据原有限制（无历史深度/排队/冲击、资金费结算标记近似、保护双触碰阻断、末期不虚构成交）全部保留。
- readiness ceiling `quality_checked`；promotion/paper/live/private/order/real_order/transfer/withdraw/runtime_observed 均 false。

## 治理证据

已读 quant-agent-preflight、quant-agent-handoff、quant-gate-evidence-review；AGENTS、knowledge README/non-negotiables、shared_pitfalls、btc_developer_pitfalls、backtest_evidence_contract、no_lookahead_rules、audit_trail。

catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
命中 BACKTEST-COST-001、BTC-NONFLAT-001、BTC-OMS-001、BTC-PERP-001、BTC-WS-001、GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-HANDOFF-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、MONITOR-AUDIT-001、QSYS-BOUNDARY-001、QSYS-GATE-001、QSYS-LEDGER-001、QSYS-SECURITY-001、REPLAY-ISOLATION-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001。

其他任务改动未消费未合并；主分支不动。最终交接引用提交态代码/报告哈希；独立集成复核，不授予任何 gate。
