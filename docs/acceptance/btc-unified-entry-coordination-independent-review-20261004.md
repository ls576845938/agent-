# BTC 统一离线入口与协调独立审查（2026-10-04）

## 结论

`INTEGRATE-BTC-UNIFIED-ENTRY-COORDINATION-20261004` 的提交态源码候选在限定范围内通过独立审查，可保留在集成分支供主会话审定；本结论不等于合入 `main`、正式浏览器验收、Demo/paper/live 放行或研究有效性验收。

- `change_risk`: `demo_execution_semantics`
- base / 当前 `main`: `eaa88400f01e47e5c8da377606b6df52a9543382`
- integration branch: `agent/integrator/integrate-btc-unified-entry-coordination-20261004`
- integration worktree: `D:\vibe coding\Obsidian\量化系统\worktrees\integrator-integrate-btc-unified-entry-coordination-20261004`
- 初始限定 dirty: `0`；冲突: `0`；未覆盖其他代理修改。

## 已消费的提交态交付

| 层次 | source commit | integration commit | validated handoff / raw SHA-256 |
|---|---|---|---|
| 规则/预测路线文档纠正 | `057f44d53dca0ac050192836356f74a8154b63eb` | 同 commit | `published-rule-forecast-doc-correction-20261004-057f44d53.json` / `a86b8654e33991aa741f84f594fad7a2aa61dbb1b2f69a994b13d38792f93bfd` |
| stage 1 corrected | `18823663e90a37cced4eccb2512fac418a263413` | `b892c6b84c19bdd3d1fc21ceac849f6a06327a21` | `published-btc-unified-entry-coordination-20261004-stage1-corrected-18823663e.json` / `646a1bc30f241b57f16bbd09da3fdc9be45a5f596877c9ccc276fa745a57646c` |
| stage 2 | `47b93c9a1ec4b7608b0fa55157bd60f78d3fa173` | `5fb03d5312d8cc1a5aecc4c99e5886856bf269b5` | `published-btc-unified-entry-coordination-20261004-stage2-47b93c9a1.json` / `d4501a53d44633c7f3d9342dc342415b79593738b7306340414cd4c2f379b9b6` |
| stage 2 correction | `d733e0b00e6e790ea70d5cf60d40b82b351d5370` | `689f406cd25af5dcff768aa3f3d853ae4b62b842` | `published-btc-unified-entry-coordination-20261004-stage2-correction-d733e0b00.json` / `a975f88c785b1b109b3d677219d6e836c96f4d199a2c0493088f45b3a71124c0` |
| allocation seal correction | `f54d242da326f1accb68a8c362379abb72634e7e` | `815a18fe8541ed0b4a61416bba23df480d8418eb` | `published-btc-unified-entry-coordination-20261004-stage2-allocation-seal-dependency-corrected-f54d242da.json` / `8f8833d760c98a727bc51d848aa00e3568ad4a5b8f03889b9e5be276751e80b1` |

各 envelope 均从对应 Git blob 校验，`validate_handoff_against_git errors=[]`；提交 ancestry、依赖链、逐文件 blob 与批准 touch set 相符。最终源码差异是上述交付的依赖并集：两份规则文档、统一生命周期的 backend/frontend/Donchian 接点、离线协调 application/portfolio/OMS/ledger 接点、对应测试及两份设计/验收说明；没有修改生产权限、策略参数、成本模型、事件时点、原账本算法或启动器。

## 独立失败优先审查

审查过程中先复现并阻断了以下真实缺口，最终提交态均已复验关闭：

1. 公开 registered Donchian driver 曾允许正确登记合同配错误实际 `output_root/run_id`；现直接校验运行位置与登记摘要，错误 root/run 在构造前拒绝。
2. 历史 replay 曾在未启用统一协调时也每根写完整 projection，并存在 artifact 已写而 projection 缺失的边界；现 projection 明确 opt-in，registered 路径启用，旧独立入口不承担新增全量写入。恢复声明只覆盖已测试的 UOW/projection 边界，不外推到任意 I/O 中断。
3. 相同成员对象/hash/ID 下曾可把 `MemberDecision` 数量由 `0.01` 改为 `0.02`，或直接篡改公开 `CohortAllocationPlan` 把总目标放大到 `0.03`；现校验目标数量、单位、方向、标的、来源对象与 canonical plan 数学等价，协调层不能重标策略目标。
4. `prior_allocation_state` 曾可在签发后改写，或由调用者自造/陈旧状态继续执行；现完整 prior-state 摘要进入签发 binding，执行前与 controller 的持久账本全量等价校验，首轮只接受精确空状态。
5. 普通运行路径曾无条件增加空 `offline_residual_protection_revision` 字段，改变默认 payload；现仅非空且启用离线协调时写入，普通 order/proof 输出保持旧合同。
6. 共同做空曾先产生第二笔经济动作，随后才因 residual protection 只支持 long 而失败；现 v1 short 在 prepare/OMS/UOW 前拒绝，零订单、零成交、零经济副作用。
7. 延迟到达的 funding bill 曾按“观察时当前持仓”错分给退出后的剩余成员；现以原始 fill 时间历史确定归属，bill 缺失时间、等时歧义或早于可证归属均 fail-closed，份额绑定 raw fill digest 与实际成交量。
8. 初始恢复测试只重建 Donchian replay 并直接调用纯分配函数；最终测试会关闭并重建 controller/context，从原 journal 恢复后把重复 fill/bill 重新送入原执行/UOW seam，订单、成交、费用、资金费、UOW/hash/equity 均不重复。

保护 revision 由原 Guardian 读回并接受，未伪造 parent；共同开仓 `0.02`、成员退出 `0.01`、残余 `0.01` 使用原 Risk/OMS/venue/UOW，原 FOK/IOC 订单与 fills 不改写。预算不足仍拒绝，不缩减原策略数量；`50 USDT` 账户金额、`10 USDT` 损失阈值、T5 flat-only 及生产默认权限均未放宽。

## 独立验证

所有 pytest `--basetemp` 均指向 Git worktree 外的 OS TEMP；未安装依赖、未启动服务或 Vite。

```powershell
$reviewTemp = Join-Path ([System.IO.Path]::GetTempPath()) 'btc-unified-entry-coordination-review'
python -m pytest -q tests/contracts/test_btc_multi_strategy_coordination.py tests/contracts/test_btc_strategy_allocations.py tests/integrations/test_btc_multi_strategy_offline.py --basetemp $reviewTemp
```

- 最终协调、分配、纵向经济链、资金费 UOW 与新 controller 恢复：`22 passed in 4.87s`（外层 `7.6s`）。

```powershell
python -m pytest -q tests/contracts/test_btc_okx_demo_paper_runtime.py -k "hosted_protection_projection_is_redacted_and_does_not_mutate_snapshot or submit_delegates_explicit_authoritative_t2_t3_bundle_to_oms" --basetemp $reviewTemp
```

- 普通默认 runtime/proof 兼容：`2 passed, 453 deselected in 3.55s`（外层 `5.0s`）。

```powershell
python -m pytest -q tests/integrations/test_registered_donchian_lifecycle.py --basetemp $reviewTemp
```

- registered Donchian 启动/停止/恢复与 root/run 绑定：最终相关版本 `2 passed in 166.04s`（外层 `174.5s`）。

```powershell
python -m pytest -q tests/integrations/test_candidate_offline_lifecycle.py::test_default_bootstrap_publish_http_start_result_and_idempotency[0] --basetemp $reviewTemp
```

- 真实安装的 LightGBM `4.7.0` primary Qlib 兼容用例：`1 passed`，pytest `562.85s`、外层 `570.1s`，保持原 `600s` 预算；worker 从 `05:50:58.221477Z` 到 `05:57:04.669877Z`，约 `366.45s`，2 decisions / 2 fills / position 0 / ledger reconciled。该用例仍是合成 fixture，不是研究候选。

```powershell
node frontend/scripts/test-unified-candidate-offline.mjs
frontend\node_modules\.bin\tsc.cmd --noEmit -p frontend\tsconfig.json
```

- 前端静态断言通过；TypeScript `--noEmit` 通过（`234.1s`）。依赖来自 canonical main 的既有 `node_modules` 临时 junction，验证后已移除；未安装依赖或启动页面。

```powershell
python -m py_compile quant_crypto/application/btc_multi_strategy_offline.py quant_crypto/application/btc_registered_donchian.py quant_crypto/application/donchian_historical_replay.py quant_crypto/application/donchian_offline_replay.py quant_crypto/application/hosted_protection_facts.py quant_crypto/oms/okx_demo_paper_runtime.py quant_crypto/oms/runtime_store.py quant_crypto/oms/strategy_allocations.py quant_crypto/portfolio/multi_strategy.py
```

- 最终 9 个相关 Python 模块编译通过（`0.5s`）。历史/spec/scaling 影响子集另有 `82 passed in 29.55s`；保护/default 影响子集 `71 passed in 5.47s`；协调相关较早版本 `54 passed in 13.83s`，最终修正由上面的 22/22 覆盖。

未运行：其余 5 个旧 Qlib LightGBM 生命周期用例、旧 Qlib stop/crash、全仓/全年矩阵、backend 生命周期、正式 main 浏览器/UI/HTTP 多策略流程、训练与新研究。最终修正未改变旧 Qlib 执行分支，不把历史或生产者结果写成当前新增通过。

## 范围与 gate

- 统一生命周期完成的是 service + 前端组件接线、静态/类型检查及局部真实经济链测试；本轮没有正式 main 浏览器验收。
- 共同账户协调是 application interface，不是新增统一页面或 HTTP 多策略用户流程。
- `qlib-learning` 只是测试成员身份，没有加载真实 Qlib 模型或经校准 Forecast。
- Donchian 两根 fixture 注入了 `OfflineInputs.load` 与 research source rule；其 `verified_historical_observations` 标签不能解释为真实 Git spec→四表数据验收。下层历史 loader 的加载次数是每次 start/resume 的常数，不随 bar 数增长；完整校验未被跳过。
- 真实可比较候选组合仍为 `0` 对，研究未启动；R2/R3 rejected、无最终模型有效校准、48h/年窗未完成等旧限制未被本票改变。
- 未生成 current-HEAD promotion artifact、manifest 或正式 ledger 包；测试 ledger 仅位于 OS TEMP 且不构成交付。

最终 gate 仍为 fail-closed：`demo=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。

## 治理证据

- playbooks: `quant-agent-preflight`、`quant-agent-handoff`、`AGENTS.md`、`docs/agent_playbooks/shared_pitfalls.md`、integrator playbook/TOML、delivery risk policy、知识库架构/风险/OMS/审计与 BTC 策略边界。
- active pitfall IDs: `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- catalog SHA-256: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 无外部 artifact publication；无 secret、账户、网络、private/order/live endpoint 访问；无 merge/push/deploy/服务启动。
