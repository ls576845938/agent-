# Donchian 历史评估：50 USDT 名义金额 / 10 USDT 亏损门槛

## 授权与边界

用户最后确认：交易金额上限 50 USDT；原有亏损门槛保持 10 USDT。
此前“都调整到 50”不再适用。50 是允许的上限，不是目标仓位或保证每笔交易 50 USDT。
只调整隔离的离线历史评估。原固定目标 0.01 张合约（面值 0.01 BTC，实际 0.0001 BTC）、
策略、参数、退出、手续费和成交规则不变。默认生产/Demo 入口仍为原 10 USDT 配置。
每日亏损、回撤及综合亏损均保持 10 USDT，Guardian、T2 订单与保护减仓映射口径一致。

## 冻结配置

- 配置：`docs/research/donchian-long-50usdt-20260921.json`，版本 `btc_donchian_history_spec_v2`。
- 对照配置：`a8eeab1da3f65d1d0fd6a800ceaf6671513b8e74:docs/research/donchian-long-evaluation-20260921.json`。
- 相比对照仅新增明确的 50/10 额度及规格版本；data、window、strategy、budget、原 execution 字段不变。
- 数据：`donchian-long-input-20260921-v2`，manifest SHA256 `349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d`。
- 预热：2025-02-13 至 2025-09-01 UTC；评估：2025-09-01 至 2026-09-01 UTC，右端不含，共 8760 小时。
- 新运行 ID：`donchian-long-50usdt-20250901-20260901`。
- 新输出根：`D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-long-50usdt-20260921`。
- 旧 10 USDT 运行完整保留，不能用新策略规格或新代码恢复它。
- 初始权益仍为 5000 USDT。历史深度、排队和冲击未建模，资金费使用冻结的历史可见价格近似；只形成探索性历史证据。

## 最小实现及兼容性

`donchian_history_spec.py` 仅允许旧 v1 或本次明确的 v2 50/10 组合，拒绝任意扩额。
`donchian_historical_replay.py` 把冻结额度交给原离线编排。
`donchian_offline_replay.py` 同步运行限制、Guardian 和现有 composition；非默认额度进入恢复身份。
`btc_demo_production_composition.py` 增加可选亏损上限；未传值仍保持旧“亏损上限等于名义上限”的行为，
本次离线显式传入 10。两个保护减仓投影同样读取显式值，缺省仍保留旧行为。
不修改风险算法、Guardian 判断、OMS、保护单或账本规则，不修改任何启动器、权限或治理合同。

## 验证、交接与运行

角色 btc_developer，change_risk=demo_execution_semantics（审查强度，不是 Demo 授权）。
base `5a0d6f604f1795a5affa6cd59e37ec54a79a7685`；专属 sparse worktree，初始 touch set 无 dirty，未覆盖其他代理改动。
已先运行失败优先测试：15 failed / 3 passed（新接口未实现），实现后专项 18 passed。
最终 producer 回归：117 passed / 1 skipped，524.74 秒。运行命令：
`py -3 -m pytest -q -p no:cacheprovider tests/contracts/test_donchian_offline_notional.py tests/contracts/test_btc_demo_production_composition.py tests/contracts/test_btc_donchian_history.py tests/contracts/test_btc_donchian_history_spec.py tests/contracts/test_strategy_v1_donchian_offline.py tests/contracts/test_strategy_v0_freeze.py --basetemp D:/vibe coding/Obsidian/量化系统/offline-runs/offline-50-regression-20260921`
跳过项为需显式启用的 Qlib 模型归档全量哈希验收（QS_V0_VERIFY_ARCHIVE=1），不是 Donchian/额度验收。
包含实际开仓 T2 风险合同的 50/10 断言、V1 非零成交/重复/重启恢复、旧历史入口和 V0 原策略保护。
独立审查与历史运行结果仍待提交态 handoff/集成报告，不以测试通过代替全年运行结果。

仅从独立审查后的冻结源码运行既有 `scripts/run_btc_donchian_history.py`：
先 `check-data --spec-git <spec_commit>:docs/research/donchian-long-50usdt-20260921.json`，
再 `run` 使用上述新根、新 run ID 和 `--max-events 240`；合格后以相同源码/规格/根/ID `resume`。
暂停恢复属于同一次评估，不是追加试验。运行中不提交或变更 HEAD。
若出现新的事实/风险/双触发/账本阻断，则保存并报告，不改参数、不换时间段、不自动续开工程。
末期不制造下一根行情或强制平仓；已发生的成交与资金费仍按原权威账本核验。

## 交付限制与回退

本票据只产生独立源码候选、测试和离线结果，不合入 main、不部署页面、不重启生产服务、不重建生产证据。
完整回退基准为上述 base；旧规格、旧运行根和 main 均保留。回退不是把新运行伪装成旧运行继续。
网络/真实账户/交易所私有端点禁止；demo_enabled、paper_enabled、live_enabled、promotion_eligible、
private_endpoint_allowed、order_endpoint_allowed、real_order_submitted 均为 false。
未验收实盘、Demo 或生产账户恢复；历史结果不构成推广权限。

## 治理记录

已读 preflight/handoff/gate-evidence 技能、shared_pitfalls、btc_developer_pitfalls、知识入口/不可违背规则、
risk_budget、execution_microstructure、backtest_evidence、audit_trail。
catalog SHA256 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
active IDs: BTC-NONFLAT-001, BTC-OMS-001, BTC-PERP-001, BTC-WS-001,
GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-HANDOFF-001, GOV-ROOT-001, GOV-STORAGE-001,
GOV-WORKTREE-001, MONITOR-AUDIT-001, QSYS-BOUNDARY-001, QSYS-GATE-001,
QSYS-LEDGER-001, QSYS-SECURITY-001, REPLAY-ISOLATION-001, GOV-PROMPT-001, GOV-WINDOWS-001。
