# V1 减仓来源合同独立审查

- producer base：`2b4cada2ce62bdaba434f28099fffac0b6d0e03f`
- 本次复核基线：`5a23994f0c655be814d5335246f41c04cd13665c`
- source：`99a2d5c72feed7aec09f56a4b4eba0491653b305`
- published handoff：`1a936c41f6175d8151b13f65336c677888c6491c`
- change risk：`demo_execution_semantics`
- catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

## 结论

减仓来源 slice 通过独立高风险审查，可作为后续 V1 集成的一个已审子集；V1 整体仍为 blocked。

生产差异限于三个文件：运行目标显式声明规则 `Signal` 来源；Portfolio 以互斥的 Signal/Forecast 身份构造版本化减仓计划；OMS 将 plan、target、signal/forecast 与 bundle 精确绑定。未修改策略信号、数量、仓位、风险阈值、退出、保护、账本、`control_plane` 或 `permissions`。

三项兼容性已核实：`forecast_id` 与 `source_forecast_id` 同时非空且不一致时 T3/T5 均 fail-closed；旧 `RiskReductionPlan` 全位置参数顺序保持；旧 Forecast 默认继续输出 v1 wire，Signal 显式使用 v2，缺 Forecast 的普通 target 不会自动降级成 Signal。

## 验证

- handoff 工具：`valid`；source 是复核基线后继，提交态 hash 校验通过。
- 独立环境：网络 socket 审计事件禁用、独立 TEMP/TMP、pytest cache 禁用、根 logger 使用 `NullHandler`。
- 四个合同测试文件：`82 passed in 12.53s`。
- 六个变更 Python 文件／测试文件 `py_compile`：通过；精确 source diff `git diff --check`：通过。
- 初始与最终限定 dirty：clean；无冲突、无覆盖其他代理修改。

## 保持阻断

- Donchian 反向链仍在既有 dispatcher 模式投影处以 `trading_mode_does_not_support_reduction` fail-closed；本票据未获准修改该映射。
- runner 的 package identity、frame digest、post-ledger 证据修复及 close-restart-open 恢复仍未完成。
- M1 历史 blob、只读前端关联、服务发布和页面验收未执行。
- 未合 main、未启动服务、未访问账户／凭据／网络／交易端点；Demo、paper、private、order、live 与 promotion 仍为 false。

## REDUCE_ONLY 动作投影与反向平仓增量审查

- final source：`7ec632f9341dcc4b2fdfef7f3e4792eb2aac383f`
- published handoff：`6edb1e5961bab4f3ecaf6e222bd60bbcf373c7c2`
- source base：`1a936c41f6175d8151b13f65336c677888c6491c`
- change risk：`demo_execution_semantics`

结论：动作投影与反向平仓 slice 通过独立高风险审查；V1 整体仍为 blocked。生产增量仅修改 `control_plane.py`、两个限定合同测试和准入说明；未修改共享 `PermissionEvaluator`、策略信号、仓位／减仓数量、风险阈值、Guardian、OMS、账本、启动器、Hook、前端或任何交易权限。

代码先让既有账户、private WS、ledger、公共行情、REST 时效、动作 capability 和 canonical projection 全部通过，再把该动作的 `NORMAL` 快照收紧为 `TradingMode.REDUCE_ONLY + block_new_orders=true`。真实 `cancel_only`、`FROZEN_UNKNOWN`、`STARTUP_RECONCILING`、缺失权威事实、withdraw 权限、121 秒过期或 capability 缺失均在 callback 前阻断。特别核实：`STARTUP_RECONCILING + opening_allowed=true` 的矛盾输入在通用健康回退之前投影为 `unknown`，不会落入 `NORMAL`。

原 Donchian 反向平仓已真实经过 T2/T3、Guardian、OMS、dispatcher、第二笔离线 fill 和持久 ledger，最终仓位归零；证据为 `reversal_close`，精确绑定 fill 与 ledger UOW。随后同 bar 重新开 short 仍由 Guardian fail-closed：`drawdown_fact_unknown`、`drawdown_unknown`、`protective_order_owner_missing`、`protective_order_reduce_only_unknown`。这是离线事实／保护所有权尚未重新一致，不据此宣称 Guardian 算法缺陷，也不扩本票范围。

### 独立验证

- handoff：`valid`；source/handoff 祖先链与四个 deliverable SHA-256 全部匹配。
- 命令：禁用 pytest 自动插件、socket connect/bind/getaddrinfo、pytest cache，并使用独立 TEMP/TMP 后，运行本票 20 项加既有 Portfolio 来源、OMS 绑定、production composition 兼容矩阵；结果 `97 passed in 15.48s`。
- 命令：`python -B -m py_compile quant_crypto/runtime/control_plane.py tests/contracts/test_btc_okx_demo_paper_runtime.py tests/contracts/test_strategy_v1_donchian_offline.py`；结果通过。
- 阅读：`docs/knowledge/README.md`、`quant_system_non_negotiables.md`、`shared_pitfalls.md`、integrator playbook；context packet 命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`；catalog hash 仍为 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 初始与最终限定 dirty：clean；cherry-pick 无冲突，未覆盖其他代理修改。注册 `main` 仍为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`；本审查未合 main、未发布、未启动服务、未访问账户／凭据／网络／交易端点。

### 继续保持阻断

- 同 bar 反向重新开仓及离线 venue／runtime-owned protection、drawdown observation 一致性未验收。
- runner 的 package identity、canonical visible-frame digest、post-ledger evidence repair、close-restart-open phase recovery 仍 pending。
- M1 精确历史 runtime blob、只读前端关联、服务发布和页面验收仍 pending。
- `quality_checked` 不等于 promotion evidence；Demo、paper、private、order、live、promotion 旗标全部保持 false。
