# Donchian 长历史能力：主版本候选的限定源码集成

票据 `DONCHIAN-HISTORY-MAIN-INTEGRATION-20260922`，角色 `integrator`，风险 `demo_execution_semantics`。本票目标只是在当前已发布主版 `31e3e882e69e983aa88c01ccdf517236e0172e75` 之上，集成已审长窗口回放、冻结成本/数据规格、时钟、附带保护单有效时序与离线性能能力。源码候选提交为 `441e057e2cdc84dd9dba32bf827fd150e614e0e2`，已完成一次**另建身份、最多 800 事件**的工程运行与恢复核验；**没有合入 main、重启服务、运行全年或授权交易**。最终只读部署规则由架构师另行审定；普通 `research_readonly_release` 不允许将本票执行路径伪装成纯页面改动。

## 准入、来源与冲突边界

- planner 从精确 `31e3e882…` 创建独立 `agent/integrator/donchian-history-main-integration-20260922` sparse 工作树；`core.sparseCheckout=true`，初始限定路径 `safe_status=clean/dirty_count=0`。没有消费其他工作树未提交文件或覆盖其他代理修改。
- 批准的最终来源为 `897d5e99ebe4c898f71ac66cf33fb2d2420855d5`，producer deliverable `ccd2015d53218a5734b898883674f7f004d81c19`，共同祖先 `e2e7496acaa16b9fd5eda37dd65ea328a18ab032`。最终 producer handoff `published-effective-time-envelope-ccd2015d5`、独立审查 handoff `integrated-effective-time-588366c9e` 均按提交态 schema、祖先与 Git blob SHA 验证无错误。性能独审 `3af51a9b…` 记录 `1030ded2/09edb9b2` 在 1,760 小时工程样本同路径运行和独立账本复算通过；它不证明全年固定耗时。e2e→897 链包含全部冻结规格、50 名义/10 亏损分离、回放优化、日志会话/恢复及保护时序必要提交，并非只消费最后修复。
- 来源链新增的 17 个历史 handoff 中 15 个当前 schema/Git 验证有效，另两个是已被最终/v2 事件 supersede 的旧格式封套，不作为本票交付或晋级证据。外部不可变 `donchian-long-input-20260921-v2` manifest Git SHA `349bd130…` 与冻结规格一致；resolver 逐一校验 7/7 文件哈希，状态仅 `quality_checked`，保留来源警告与无深度/历史 mark 近似限制。
- 最终来源相对共同基线有 33 个必要代码、测试、冻结规格和数据 manifest 路径；当前 main 在这些路径相对共同基线没有变更。候选只取这 33 个精确最终 blob，index 与 `897d5e99…` 对应路径逐项相同。保留当前 main 的 backend 只读证据、frontend 研究页面、身份派生文件和架构地图；旧来源三处地图差异以及旧 handoff/运维说明没有覆盖主版。无合并冲突、无策略参数搜索或成本口径变更。

## 源码候选的集中验证

- 独立 15 文件矩阵：Donchian V0/V1、实际注册信号、50 名义/10 亏损、成本和保护时序、OMS 默认行为、日志会话/恢复、历史输入与阶段只读后端兼容，`308 passed, 1 skipped in 66.49s`。唯一 skip 是旧 `test_strategy_v0_freeze.py:206` 本地 Qlib 不可变归档 opt-in，无下载/fallback。
- 新数据准备合同 `tests/test_donchian_long_input.py`：`8 passed in 3.56s`。正式 CLI `check-data` 只读输出 `evaluation_rows=8760`、`warmup_rows=4800`、`funding_settlements=1095`、`evaluation_not_run=true`、`permissions_granted=false`，冻结规格 digest `7a87dba25a55991f86af58c69c29772026ad3fe9f87a90cf4a5c063b0d98a38b`。
- 矩阵参数为 `py -3 -m pytest -q -ra --tb=short -p no:cacheprovider --basetemp 'D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-history-main-integration-20260922/pytest-matrix-20260922b'`，其后逐一传入 14 份 `tests/contracts/`：`test_donchian_history_scaling.py`、`test_donchian_offline_liveness.py`、`test_strategy_v1_donchian_offline.py`、`test_donchian_replay_performance.py`、`test_btc_simple_trend_rule_lab.py`、`test_btc_long_short_trend_following_lab.py`、`test_btc_strategy_registry.py`、`test_btc_okx_demo_runtime_hardening.py`、`test_donchian_offline_notional.py`、`test_btc_demo_production_composition.py`、`test_btc_donchian_history.py`、`test_btc_donchian_history_spec.py`、`test_strategy_v0_freeze.py`、`test_donchian_effective_time.py`，再传 `backend/tests/test_donchian_stage_views.py`。数据测试同参数，改用独立 `pytest-data-20260922a` 和 `tests/test_donchian_long_input.py`。运行前设置 `PYTHONDONTWRITEBYTECODE=1`，不下载数据。
- 首次矩阵调用因新外部 pytest `--basetemp` 父目录尚未创建，102 passed/1 skipped/206 fixture setup `FileNotFoundError`；建好本票自有外部父目录后，**同一业务矩阵全部通过**，未修改源码或测试预期。该环境错误保留，不计为策略或安全断言通过。
- `git diff --check` 通过；当前主版只读/backend/frontend/地图路径在候选里零变更。生产默认 `BTCRuntimeStore` 未启用离线 cache/session；离线新会话的限制由既有独审和本次合同测试约束，不能外推为恶意进程安全边界。

## 有界运行、恢复与独立核账

架构师限定批准同一冻结规格 `25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json`、新外部根 `D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-history-main-integration-20260922`、唯一新 run ID `donchian-main-integration-smoke-20260922`，总计最多 800 事件。启动前新 run 子目录不存在、无同名 writer、D 盘余 `36.50 GiB`（高于 20 GiB 安全线）。源码固定为 `441e057e…`，spec/data/策略参数、50 USDT 名义上限与 10 USDT 亏损阈值不变。

正式已有入口按顺序执行 `py -3 scripts/run_btc_donchian_history.py run --output-root <上述新外部根> --run-id donchian-main-integration-smoke-20260922 --max-events 400 --spec-git <上述冻结规格>`，正常 exit 0/checkpoint `400/8760`、0 blocker、0 自然成交；随后同参数改 `resume --max-events 400`，正常 exit 0/checkpoint `800/8760`、0 blocker。批间只在首批退出后恢复；未重启旧运行、未扩大至第 801 事件。最终只读 `status` 同值：3 订单／成交、54 次方向信号决策、100 条资金费观察（6 条非零），现金 `5000.219577376904565258956`、权益 `5000.224686301404565258956`、持仓 `0.01` 张、已实现 `0.243506415`、未实现 `0.0051089245`、手续费总额 `0.01810510733025`、资金费净额 `-0.005823930765184741044` USDT。所有安全标记保持 false。关闭后 2026-09-22 11:54:18 +08 用精确 run ID 核对匹配 Python/PowerShell writer `0`；不把遗留锁文件当作活动 writer。

writer 全部退出后，以默认未启用离线缓存/排他会话的 `BTCRuntimeStore(<新运行>/state/runtime).recover()` **两次只读完整恢复**：每次 4,006 事件、链尾 `885b32eb06f01d0b7b4c653eef5287324b5294250bcbab1b9cff24ede9b89f06`、无 blocker、无截尾，序号与哈希相同。独立从 802 个已提交 `ledger_uow_committed` 的 payload 和关闭的模拟 venue 最终价、权益、仓位调用原 `replay_account_ledger_uows()`，不消费离线压缩缓存的计算替代：`reconciled=true`，3 成交、100 资金费账单、价格 PnL `+0.2486153395`、手续费 `-0.01810510733025`、资金费 `-0.005823930765184741044`、权益计算/观察同为 `5000.224686301404565258956`、仓位 `0.01` 张；与最后已提交 UOW 的账本回放字段一致。没有写新账本或重放订单。

旧冻结源码 `897d5e99…` 的原年度运行，coordinator 已记录首批 `0→800` 的 `batch_exited`，故只读比较关闭的 `cli-after-0000.json`；**不是** `cli-after-0800.json`（后者是 800→1040）。同一冻结数据/规格下，旧回执与本票新 800 在事件数、订单、成交、资金费观察/非零数、现金、持仓、权益、已实现/未实现、手续费、资金费均逐项相同；运行 identity digest 不同，这是源码 `897d` 与 `441e` 的正确区分。原 `2960/8760` 阶段继续由 `897d` 生成，不能转写为本候选的 2960 事件结果。该精确 800 事件对照说明迁移后的已覆盖业务行为一致，不证明余下 7960 小时、年度表现或恒定吞吐。

新运行关闭文件仅保存在任务自有外部根，不提交 Git：`historical_identity.json` SHA256 `b5e884c43b44f3c862ff9ff7d4228efcce356e04189232c111392ea765a1e3a0`，`historical_replay.json` `70289a06ff38289f3af8ddc57f110be28a05a0f5c1728118ce2fc0d4fb106886`，`state/offline_venue.json` `190583be40c321460c313053bf1e31fc87204729c4f8f2a636180cad485ea5a9`，`state/runtime/events.jsonl` `3bb47dac05046ff0349f4eb6a540ef57870470932b3e2359c65ac6c1345e62c4`，`state/runtime/state.json` `f796fce8c9485f28bf21664325787ba039675e636f293bdc737ce4c46d068b66`。最终身份记录 code version `441e057e…`，冻结策略及 spec digest `7a87…`。本次未设新的加速目标、不做长期吞吐承诺。

## 交付限制

当前 `main` 仍为 `31e3e882…`；阶段只读页面验收仍绑定该版本，不能把新候选认作正式部署。年度 2960/8760 暂停原样，生产 BTC 运行证据仍不可用，真实账户/交易所对账与 promotion gate 未完成。Demo、paper、live、promotion、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 均保持 false。当前只交源码候选 `quality_checked`；若需只读正式发布，必须另有本票适配的限定交付规则、独立审查和注册主版本验收。

预检读取 `quant-agent-preflight`、`quant-agent-handoff`、`AGENTS.md`、知识 README/非协商规则、shared pitfalls、integrator TOML 和交付风险政策。catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未读取原始事故全文、secret、账户或 private/order/live 端点。
