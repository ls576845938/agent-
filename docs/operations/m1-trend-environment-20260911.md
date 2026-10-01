# M1 共享趋势环境旁路：开发与验收记录

状态：生产者实现、冻结数据研究实跑和 API 读取通过；已封印并发布不可变研究证据。尚未独立验收、合入 canonical main 或完成正式浏览器验收。M2—M4 不启动。

实现 commit：`59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`。证据发布 deliverable：`ce9fa46858e257b4eac4381e2044bf5696983d87`，发布 handoff commit：`04f54523bf2d14d765599b0338a92cd044d74e6e`。后续文档/manifest/handoff 提交不改变计算源码，但不能冒充在这些新 HEAD 上重新产生的 promotion/runtime 证据。

## 冻结基准（先于实现）

- base：`c1d11987d28f06bb0fe89b2c289e88d07522790d`。
- worktree：planner 创建 `agent/super_developer/m1-trend-environment-20260911`；初始声明路径 clean。
- 默认 BTC：`long_short_donchian_top5_okx_native`，`baseline_1x`；候选 `okx_native_btc_ls_tf_formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone_78f5f0a0e4`。
- 参数 hash：`5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355`。
- 固定输入 Git manifest：`.agent/data_manifests/btc-okx-public-swap-research-bundle/btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-src6cea196b4-corr1.json`。
- manifest SHA256：`6c5dd8036da320062002b839792852c1aa53971fecdd20b1ba7ae3ec6c2260c9`；aggregate：`3a61fc915da66994294113cc7b2334a1da4c0e08bccf428a743564c863c8d680`。
- 普通 Qlib 配置、时间切分、特征、成本保持现有 `configs/qlib/okx_btc_trend_1h.yaml`；研究窗口 2025-12-22 至 2026-07-29。历史可见时间由 bar close 重建，并非原始到达记录；OI/清算未具备。
- 不变区：`quant_crypto/`、`quant_shared/strategy_runtime/`、`quant_shared/runtime/`、`quant_shared/alpha_factory/`、`quant_us/backtest/`、`backend/app/services/btc_demo_runtime.py`。禁止借旁路改信号、退出、仓位、T2/T3、OMS、保护单、账本、权限或排名。

实现前已有合同基线：Context/CAS/restart、production composition、risk kernel、portfolio exit、guardian latch、OMS delegation、runtime hardening 共 **169 passed / 6.73s**。使用 canonical `.venv/Scripts/python.exe`（Qlib 0.9.7 / LightGBM 4.7.0）；系统 `py -3` 无 Qlib，不安装重复环境。

## 唯一生产票据与停止条件

touch set：新 `quant_shared/trend_environment/`、新 `integrations/qlib_adapter/trend_environment.py`；现有 `research_pipeline.py`、`factory_trainer.py`、`factory_data.py` 的旁路写入/封印/读取；现有研究组件 `QlibDecisionTrace.tsx`、`AlphaFactoryConsole.tsx` 与新共享观察卡片；相应新增测试、有限前端回归、此报告和 M1 handoff。不另建后台服务/API/控制台，不修改 Context schema。

纯函数只消费资产身份、已完成且可见的数据、明确日历/周期/冻结配置；输出连续描述分数，不声称概率或有效 alpha。研究入口在原训练、筛选后追加独立旁路，不向特征/风险/目标/OMS 注入分数。普通与 Factory 使用同一函数；Factory 缺七层 trace 如实保留缺证。

验收限于因果/日历隔离、旧 run 兼容、精确版本与 hash、失败隔离、BTC 行为保护、真实 Qlib/Factory 生产者持久化/API 连接以及定向前端。完成后独立 integrator 复核；未发布到 canonical main 前不声称浏览器验收通过。

## 实现与职责

| 文件/组 | 责任与边界 |
| --- | --- |
| `quant_shared/trend_environment/{model.py,__init__.py,README.md}` | 无 I/O 的资产中性估计：方向、趋势适配度、波动、冲击、切换强度；明确时间、日历与未知原因。不是概率、择时开关或风险授权。 |
| `integrations/qlib_adapter/trend_environment.py` | 统一追加旁路、版本/输入/hash/context 关联、封印后只读投影；拒绝错 run、损坏、未封印/跨版本来源。 |
| `research_pipeline.py`、`factory_trainer.py` | 原研究任务产物之后追加观察；共用一个适配器，不给特征、筛选、排序、仓位或交易注入分数。 |
| `factory_data.py` | 通用 panel 导出增量保留原始时间与日历证据；缺合同的旧输入显示 blocked，不猜测补齐。 |
| `TrendEnvironmentEvidence.tsx`、`QlibDecisionTrace.tsx`、`AlphaFactoryConsole.tsx` | 现有研究/组合/策略引用同一只读折叠卡片；工厂通过原 fold 链接显示同 run 状态。没有新控制台或导航。 |
| 新增纯函数、sidecar、BTC freeze/parity 测试和 `frontend/scripts/test-trend-environment.mjs` | 因果性、隔离、hash、缺失/异常/安全标记、旧版本兼容及实际 React SSR 渲染。 |
| `scripts/run_m1_research_acceptance.py` | 有界、断网络、仅新外部输出目录的真实 Qlib/Factory 验收，不改 latest、不连接交易。 |

冻结配置：BTC 1h 为 24/72/168 bars、UTC 24×7；日线为 20/60/120 bars，日历与年化由明确 profile 注入。只使用已完成且当时可见的数据；预热不足、延迟、未完成、缺日历时点、非有限/非正价格、过期等返回 unknown。模型/配置 hash、run/data/code/候选/工厂来源与 `StrategyDecisionContext.evidence_refs` 绑定，不修改 Context schema，也不传给 BTC runtime。

## 回归结果与限制

下列 Python 命令均使用注册主仓 `.venv/Scripts/python.exe`，在此专属工作树执行；`-B -m pytest -q -p no:cacheprovider`。临时 runtime 测试目录位于 Git 工作树外。

1. 实现前后相同命令各 **169 passed**（6.73s / 18.80s）：
   `tests/contracts/test_strategy_decision_context_v1.py tests/contracts/test_btc_demo_production_composition.py tests/contracts/test_btc_shared_platform_v3_risk_kernel.py tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py tests/contracts/test_btc_shared_platform_v3_guardian_latch.py tests/contracts/test_btc_shared_platform_v3_oms_delegation.py tests/contracts/test_btc_okx_demo_runtime_hardening.py`。
2. 新增最终定向回归 **25 passed / 76.16s**：
   `tests/research/test_trend_environment.py tests/integrations/test_trend_environment_sidecar.py tests/contracts/test_m1_btc_behavior_freeze.py`。
3. 现有集成/工厂回归：
   `tests/integrations/test_qlib_time_series.py tests/integrations/test_qlib_alpha_factory.py tests/api/test_qlib_pipeline.py tests/api/test_alpha_factory.py tests/research/test_alpha_factory.py` 首次 **96 passed / 10 failed**；10 项均为 sparse 未包含 `quant_cn` 导致 import 失败。扩展只读 sparse 后，两份 API 测试及新增 sidecar 测试重跑 **22 passed / 65.40s**（其中 API 10 项）。未修改业务代码掩盖此失败。
4. 前置定向保护 **5 passed**：初始 freeze 两项及 runtime 三个既有测试（stable signal/empty native tail、exact run/order recovery、atomic funding/reconciliation）；438 deselected。测试准备曾出现 registry 导入用法错误与 Git 内临时 artifact root 被安全规则拒绝；修正测试导入和外部临时路径后通过，未放宽安全规则。
5. 纯函数测试采用 failure-first：模块尚未实现时先确认缺模块失败，再实现并通过。三态 BTC 对照单独 **3 passed**；关闭/启用/观察器异常时，固定输入下真实注册信号、实际控制器决策、开仓/持有/反向退出/保护计划及成交账本、费用、资金费、去重、对账结果相同。负对照能发现费用变化。
6. `node frontend/scripts/test-trend-environment.mjs`、`node frontend/scripts/test-research-rollback.mjs`、`node frontend/scripts/test-strategy-history-provenance.mjs` 均通过；`npm.cmd run lint`（tsc）通过；`npm.cmd run build` 通过（5258 modules，既有 >500KB chunk 告警保留）；限定 `git diff --check` 通过。

三态测试不是一次实际运行的 signal→T2/T3→dispatcher→exchange fill 全链路：它比较实际信号/计划/账本组件，并由独立的既有 composition/risk/OMS/Guardian 合同覆盖装配边界。没有真实/Demo/private/order 网络验收，也没有新 runtime 产物。美股/A 股仅覆盖已有 fixture 与日历合同，未宣称真实市场数据接入已验收。

前端验证是类型/构建和实际组件 SSR，不是 Playwright/浏览器交互验收。旧 `test-research-portfolio-contract.mjs` 已知基准任务 API 断言失败不在本次修复范围；本轮没有改该文件或 `task-api.ts`。依赖复用 canonical node_modules，没有安装新依赖。测试准备误建的 ignored `frontend/frontend/node_modules` junction 未入提交；清理被策略拒绝后未绕过，保留于本票据工作树，不影响主仓或发布代码。

## 冻结 OKX 数据实跑

命令：`.venv/Scripts/python.exe -B scripts/run_m1_research_acceptance.py --output <全新 worktree 外目录>`（实际解释器用注册主仓绝对路径）。运行期间禁用 socket connect，复用既有真实 Qlib/LightGBM 与 AlphaFactoryService；没有另造训练引擎。

| 运行 | 实际结果 |
| --- | --- |
| `m1-okx-qlib` | 既有六项研究阶段完成；5280 个 finalized hourly bars；15840 条环境记录，其中 observed 15573、warmup unknown 267；as-of 2026-07-30T00:00Z。 |
| `m1-okx-factory-input` | 同一冻结来源的封印输入；普通研究与工厂时钟按各自已有合同解释，未改变训练标签。 |
| `m1-okx-factory` | population=4、generations=1、max features=3、model trials=1、seed=17；4 个真实 Qlib fold，最终 **rejected**。不调参、不追加搜索，不把候选失败说成 Alpha 合格。 |
| 四个 fold | 分别 10836 / 11418 / 12000 / 12582 条环境记录；每折 267 条预热未知，观察截止不超过各自 test_end；没有七层交易 trace 的折明确缺证。 |

现有 FastAPI TestClient GET `/api/integrations/qlib/runs/<id>`：普通研究 + 四个真实 fold 共 **5/5 HTTP 200**；原封印完整性、环境状态 completed、精确 run、order=false 均验证。仅进程内指定验收 root；没有修改 canonical 8765 服务或配置。在实现 commit 上 source_stale=false；以后 HEAD 变化时必须如实显示版本差异。

## 可复用证据与回退

- 使用 Git manifest：`.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`；dataset `m1-trend-environment-acceptance`，version `m1-okx-59f5eb861-20260911`。
- manifest Git 对象 SHA256：`2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`；aggregate `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`。
- 只读 resolver 验证 160 files / 56,134,415 bytes。原始验收摘要 SHA256 `d7b1278480adae33ff48b8f08c1aa5a2393275a65ab78663e4a81775d12af78b`；原 source inventory SHA256 `65433604d9566b7f03d638aba696c8d549e2a94293b9c6f56a6a46a7ac89f63d`。
- 已顺序消费数据师提交态 handoff `published-m1-observation-evidence-20260911-ce9fa4685`；详见 `docs/operations/m1-observation-evidence-20260911.md`。源计算代码 59f5eb861 与此报告/handoff 提交区分记录。
- 共享数据治理正确拒绝可变 MLflow SQLite；发布的是明确声明的封印证据投影：保留六个 Qlib seal、Factory seal 及所有封印文件，排除 21 个未封印辅助文件/数据库并记录原因。它可复核预测与证据，**不能恢复/续跑 MLflow 数据库**。源目录未删除或更改；不以改名绕过限制。
- main 仍在冻结基准，当前用户页面尚未改变。将来若部署后回退，应在专属回退票据 revert 实现 commit 59f5eb861，并按同样发布合同集成；研究归档保留，不 reset、不覆盖其他改动。

## 独立验收与下一步边界

交付分类仅 `quality_checked` / research observation evidence。独立 integrator 应验证提交 ancestry/hash、封印 manifest、旁路失败隔离、因果时间、BTC 冻结与前端不误标交易状态，再给出独立 integrated/rejected 事件。禁止直接以生产者通过代替验收。

尚未运行：canonical main 发布/当前 HEAD backend 重启、正式页面端到端与滚动交互、当前 HEAD promotion/runtime artifact/gate 重建。`change_risk=unclassified` 保留严格发布路径；现有 BTC runtime root 503 不得用伪造 artifact 或降级绕过。若严格发布需要本轮未授权的 runtime bootstrap/交易相关运行，应停在提交态交付并明确报告，不扩成新工程循环。

M2—M4 仅在 M1 独立验收完成后再向用户汇报建议；即使 M1 工程通过，也不证明环境分数有投资效果，不授予交易权限。下游需要新的独立样本外效果证据与单独授权。

## 已知非本轮阻塞

- 研究证据注册表解析已恢复，但仍有 57 个 ID 多路径完整性冲突；不重建/去重。
- BTC runtime root 未配置导致 503；不伪造/回退本地 artifact。
- 小批前端死代码清理已在别的专属分支完成，未并入本基准。
- 没有 promotion/current-runtime 验收证据，promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission 均不解锁。

## 治理

role=super_developer，change_risk=unclassified；独立 integrator、提交态 handoff 与发布门槛保留。已读 preflight/handoff、shared/super_developer playbook、非协商规则、架构/数据可靠性/金融ML规则及 REASSESSMENT。catalog `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`；active IDs：GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS-001、QSYS-GATE/SECURITY-001、RESEARCH-HOLDOUT-001。两个只读探索，无并行写代理，无未提交跨工作树消费。
