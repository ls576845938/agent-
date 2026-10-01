# QuantStation 当前开发进度（2026-09-29）

核查基线：`3fc39879d14ecab2288368afe588385cc44c08e1`。本文是版本化提交态快照，不是实时权限、账户或运行监控；没有重新通读全仓，也不把历史测试写成当前 HEAD 新跑结果。

| 主线 | 已实现 | 历史测试／证据 | 已合入或页面 | 当前限制 |
| --- | --- | --- | --- | --- |
| V0—V3 冻结离线工程 | Donchian 与固定 Qlib 分别进入同一 BTC 风控／OMS／保护／账本链 | Donchian 5 决策、4 模拟成交；固定 Qlib 1,392 决策、0 成交 | `e2e7496` 已完成 research_readonly 页面验收 | 仅离线软件与只读证据，不是 Demo／paper／live |
| Donchian 长历史 | 长窗口、历史时钟、保护时序与性能能力 | 316 passed / 1 skip；另有 800 事件、3 fills 工程验证；自然阶段 2960 / 8760、56 模拟成交、28 roundtrips、370 funding | `441e057e2` 已是当前 main 祖先；`donchian-stage-20260921` 已发布 | 年度暂停，不是全年或盈利确认 |
| 登记候选离线入口 | 策略包 v3 验证、审定、USDT 绑定、登记；CLI／HTTP／coordinator 进入原 BTC 离线链 | 错包、币种、账户、版本拒绝；重复／恢复不重单、不重账 | `8821b04e5`、`8ea90775b` 已是 main 祖先 | 仅 `factory_lgbm_ast_v1`，默认 `candidate_offline_enabled=false`；旧 M1 v2 不执行 |
| 市场状态 v2 | 2960 bars 历史诊断与 72h efficiency=0.20 的 entry-only 条件政策 | 28 roundtrips、170 segments；baseline 2960 / 2960，conditioned 1956 / 2960 后 fail-closed | 冻结源码 `f2455bf…` 已进入当前 main 历史 | 保留 -0.01 张空头；缺完整逐事件状态，M3—M4 未启动 |
| 研究只读读取 | 注册表扫描与 Qlib 并发完整校验优化 | 正式 11 / 11 场景、每场 12 读均小于 12 秒，最慢 8.293 秒；40 passed | `3fc39879` canonical research_readonly 已验收 | `CONFLICT`、BTC 503／runtime root 缺失、source-context 警告仍保留 |

## 执行关系

`Alpha／Qlib → 完整策略包 → 管理审定、币种绑定与登记 → 显式受支持的离线 worker → 原 BTC Risk／OMS／保护／账本 → offlineRun 只读证据`

这条关系只说明支持合同内的离线工程路径。登记不自动启动；离线诊断不自动成为研究通过；研究通过也不自动获得交易权限。

市场状态是独立条件分支：仅当冻结政策显式启用、当前空仓且原目标为新增风险时才参与开仓过滤；已有仓位的退出、减仓、反向先平和保护责任仍由原业务链处理。

## 证据入口

- `78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json`
- `docs/operations/donchian-stage-readonly-20260921.md`
- `docs/operations/donchian-history-main-integration-20260922.md`
- `docs/acceptance/btc-candidate-offline-entry-20260925.md`
- `docs/acceptance/integrate-candidate-market-policy-closeout-20260927.md`
- `D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/deployment-acceptance-report-3fc39879.md`（外部只读发布验收，不复制进仓库）

`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 `false`。
