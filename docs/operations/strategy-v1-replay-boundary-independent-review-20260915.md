# V1 回放边界修正独立终验

## 结论

**partial / blocked，技术验收未通过，本轮在约定停止点结束。**

本次限定修正确实关闭了上一轮的两个直接安全反例：固定历史 observation clock 已贯通 dispatcher 的快照 freshness；持久的 `FROZEN_UNKNOWN`、不可信写路径、private WS 断开与已 trip Guardian 在重启后不再被改写成健康状态。可是固定五阶段主序列仍不能完成：`open long -> hold -> reversal close` 后 Guardian 因保护单证据缺失而持久 trip，重启后的 `reversal open short` 在第三笔提交前被拒绝。

现有证据只能精确证明 OCO ownership，不能证明 sanitized OCO 是 `reduce_only` 或 `close_position`。把 `market_exit=true` 解释成减仓事实需要改变 Guardian 语义，超出本票据；而且 Guardian 还要求 non-flat 仓位和完整生命周期关系，不能断言“只补字段”即可解决。因此不生成 passed source receipt，不修改 M1 精确冻结，不进入页面、发布、Demo、paper 或 live，也不自动开启第二轮修复。

## 提交与边界

- parent ticket：`STRATEGY-V1-DONCHIAN-OFFLINE`
- integration ticket：`STRATEGY-V1-REPLAY-BOUNDARY-INTEGRATION-20260915`
- change risk：`demo_execution_semantics`
- integration base：`c2f9646e6a23dfc5d74a9a30b160ec60fa59f080`
- 限定说明提交：`3bb2338a1c3123cc5c4834d6ed5aaeb598ae4146`
- producer source：`7c0f9692a216f019c4f1546bb00811662827e61e`
- producer handoff HEAD：`f1990dd926a7ee30989d471bad31f80d8bdbdfaa`
- producer handoff：`.agent/handoffs/STRATEGY-V1-REPLAY-BOUNDARY-20260915/published-strategy-v1-replay-boundary-20260915-7c0f9692a.json`
- 独立集成 merge：`25302af74c59685ef805d715ae0036be06f8300b`
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

producer handoff 对 Git 提交态对象校验为 `[]`；source 是 base 后继。独立工作树合并无冲突，初始限定路径 `safe_status=clean`。source 精确变更为：

- `quant_crypto/application/donchian_offline_replay.py`
- `quant_crypto/runtime/control_plane.py`
- `tests/contracts/test_strategy_v1_donchian_offline.py`
- `tests/contracts/test_btc_okx_demo_paper_runtime.py`
- `tests/fixtures/strategy_v1/offline_contract.json`
- `docs/architecture/strategy-admission-v1.md`

V0 golden、Donchian 参数、`0.01 contracts`、成本和初始账户文件未修改；fixture 只增加封存的 observation time。

## 已通过的独立证据

### 1. Observation clock 与授权时钟分离

`BTCDemoExecutionDispatcher` 新增构造依赖 `clock`，未注入时仍为 `utc_now()`。注入值只参与 exchange snapshot freshness 与 runtime projection 的 observation time；`RuntimeRiskEvidenceAuthority` 的 `issued_at` 仍直接使用 `utc_now()`，现有风险凭证签发、验签、有效期和 30／120 秒快照阈值未改变。

```text
pytest dispatcher 两个限定合同
2 passed in 3.83s
```

同一测试证明：封存为 `2020-01-01T00:00:00Z` 的 snapshot 可由同一封存时钟验证；推进到 31 秒后仍以 `btc_demo_dispatch_projection_blocked` 拒绝且 callback 未调用。旧风险凭证没有被历史回放时钟“复活”。

### 2. 持久阻断不会在恢复时被补成健康

完整 V1 测试中的以下四个保护分支通过：

- `FROZEN_UNKNOWN` 重启后仍冻结，零提交、零仓位；
- `write_path_trusted=false` 重启后仍不可信，零提交、零仓位；
- private WS disconnected / listener dead 重启后仍断开，零提交、零仓位；
- 持久 Guardian trip 重启后仍 trip，零提交、零仓位。

这说明上一轮“恢复后改写成 RUNNING／connected 并开新风险”的直接反例已关闭。

## 未通过的主序列与首次 trip

独立运行：

```text
py -3 -B -m pytest tests/contracts/test_strategy_v1_donchian_offline.py -p no:cacheprovider --basetemp <isolated-temp> -q
1 failed, 9 passed in 65.57s
```

失败测试：`test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable`。

在失败前，`open long -> hold -> reversal close` 已完成；平仓后状态为：

- position：`0.00 contracts`
- submit：`2`
- fills：`2`
- OCO cancel：`1`
- Guardian 首次持久 trip 时间：`2026-09-15T00:00:02Z`
- reason codes：`protective_order_owner_missing`、`protective_order_reduce_only_unknown`

重启后处理同一 `reverse_to_short` 前缀时，runner 以 `okx_demo_paper_runtime_not_active` 拒绝，未产生第三笔提交。因此 fail-closed 是正确的，但冻结验收要求的 `reversal open short -> exit flat` 没有完成。

提交态静态边界也与该结果一致：Guardian 候选要求真实 ownership、`reduce_only/close_position`、non-flat 仓位与完整保护单关系；`_sanitize_algo_order` 没有保留 `reduce_only/close_position`。本报告只确认离线回放边界可复现，不把它描述成生产环境已验证故障，也不声称任何单一字段修改必然足够。

## 恢复证据限制

ledger-before-evidence 和 intent-before-post 用例本版都在“重启”前显式调用 `runner.close()`，因此通过结果不能外推为所有硬进程崩溃点已覆盖：

- ledger-before-evidence 场景在健康状态下会写入 `offline_replay_clean_stopped`，属于显式干净关闭后的恢复；
- intent-before-post 因 unresolved pending 不满足 clean-stop 条件，不写 clean-stop，但仍显式释放 Guardian lease；它证明 unknown intent 保持 fail-closed/no blind retry，不证明无清理进程死亡后的完整恢复。

这不新增修复任务，只作为本次证据强度限制保留。

## 治理说明同步

用户限定授权后，`3bb2338a1c3123cc5c4834d6ed5aaeb598ae4146` 只修改 `docs/agent_playbooks/strategy_v1_readonly_delivery.md` 一个段落：允许 dispatcher 构造依赖注入 observation clock，同时明确默认 `utc_now()`、快照阈值、风险证据 authority、HTTP／热配置、权限与交易旗标不变。

主会话作为非作者核验：单文件 `1+ / 1-`、Git blob SHA-256 `d1e0168ed1c5bed8ab159dc54db87bc0e08fc88ab1670277652eba9a4c924e`、`diff --check` 通过。独立集成侧回归：

```text
test_strategy_v1_readonly_delivery.py: 75 passed
限定治理矩阵: 149 passed in 72.12s
```

首次治理矩阵因 sandbox 无权创建 `C:\tmp` 得到 `122 passed, 27 errors`；改用获准的隔离系统临时目录后全绿。这是测试环境错误，不是合同失败。该说明目前只存在于候选集成分支，未在 main 生效，也未构成发布。

## 未运行项与停止状态

- 未独立重跑 V0/BTC 219 项兼容矩阵：主序列已触发约定的实质停止条件。
- 未运行 M1 exact-blob 测试，未修改其 base、golden 或批准登记。
- 未运行硬进程死亡恢复补充场景、部分成交、拒单、一般 cancel-response-loss 或 conflicting-fill。
- 未运行 UI、API、服务启动、只读页面、Qlib、M3—M4、Demo、paper、private/order/live 或 promotion acceptance。
- 未修改 Guardian、OMS、ledger、策略参数、仓位、退出、权限、机器治理规则或启动器。
- 未访问网络、secret、账户、broker/exchange、private/order/live endpoint；未提交真实订单。

技术、页面、发布三态分别为：`technical=blocked`、`page=not_started`、`release=not_started`。readiness 不高于 `quality_checked/partial`；promotion、Demo、paper、live、private、order、real order、transfer、withdraw、execution permission、runtime worker 与 runtime observed 均保持 `false`。

## 预检记录

- 工作树由 planner 从指定 base 创建，`core.sparseCheckout=true`。
- 已读 `AGENTS.md`、知识总则、non-negotiables、shared pitfalls、integrator profile、V1 只读交付合同，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review` 技能。
- active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

