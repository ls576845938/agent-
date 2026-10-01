# M1 共享趋势环境旁路：独立验收与集成报告

状态：获批 handoff set 的代码、提交态证据与离线研究/组件验收通过，已 fast-forward 到独立 integrator 分支。**整体 M1 尚未最终验收**：canonical main 尚未发布该提交，canonical 研究页面尚未证明可发现该不可变证据，正式浏览器交互验收未运行。M2—M4 不启动。

## 身份、边界与交付链

- role：`integrator`；change risk：`unclassified`；catalog：`127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。
- base/main：`c1d11987d28f06bb0fe89b2c289e88d07522790d`。生产者 final：`d6074ff5ff3213b43bd6747bfd0f9e0c780e25fd`；生产者 deliverable：`009540a025d4f5f0f509463a3d50245a713a9cb9`；实现/计算 commit：`59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`。
- 数据 deliverable：`ce9fa46858e257b4eac4381e2044bf5696983d87`；数据 handoff commit：`04f54523bf2d14d765599b0338a92cd044d74e6e`。
- 工作树由 `worktree_plan.py --role integrator --task-id m1-trend-environment-review-20260911 --base-ref c1d11987... --apply` 创建，分支 `agent/integrator/m1-trend-environment-review-20260911`，`core.sparseCheckout=true`。
- 独立 touch set 仅包含获批 final 的 20 个提交态路径、本报告和本票据 append-only handoff。未修改 BTC signal/position/exit/risk/OMS/protection/ledger/permissions，未触及 M2—M4、503/registry/治理政策。
- 合并前对上述每个路径逐一运行 `safe_status.py --path`，全部 `clean`；无重叠 dirty，无冲突，未清理、回滚或覆盖其他工作树。

## handoff、Git 与不可变数据校验

- `published-m1-trend-environment-20260911-009540a02` 与 `published-m1-observation-evidence-20260911-ce9fa4685` 均通过 `handoff.py validate`；schema、producer branch、base ancestry 和逐 deliverable SHA-256 无误。
- ancestry 为 `c1d11987 -> 59f5eb861 -> ce9fa4685 -> 04f54523b -> 009540a02 -> d6074ff5`；生产者 branch HEAD 精确为 `d6074ff5...`。
- 合并前限定 touch set 的 `git diff --check` 通过；从 base 到 producer final 只有获批的 20 个路径。
- 使用 `shared_data.py resolve --manifest-git-spec d6074ff5...:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json` 执行非 `--fast` 的全文件哈希校验，`status=resolved`、`consumer_read_only=true`。
- manifest：`shared_dataset_manifest_v1`，dataset/version 为 `m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911`，160 files，56,134,415 bytes，aggregate `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`，Git object SHA-256 `2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`。
- 清单只有 `quality_checked / pass_with_research_only_warnings`；`historical_reconstructed_availability`、`factory_candidate_rejected`、`canonical_publication_and_browser_acceptance_pending`、`not_execution_evidence` 保留。投影不包含可变 MLflow SQLite，不能恢复或续跑训练数据库。

## 独立代码审查

1. **资产中性与因果时间**：`quant_shared/trend_environment/model.py` 为无 I/O 纯函数，按精确 `asset` 隔离；只使用 `completed=true`、`available_time <= decision_time`且 `close_time <= decision_time` 的样本。未来行、其他资产和未来日历不进入窗口或 input hash。
2. **calendar 与 unknown**：日历、horizon、年化周期和最大年龄均由上游显式注入；BTC 1h 使用 UTC 24x7，股票日线合同保留 XNYS/XSHG。预热不足、延迟/缺条、未完成、过期、重复/乱序、无时区、无效价格显式返回 unknown/blocked，不压缩日历缺口。
3. **旧 run 兼容与失败隔离**：旧 seal 没有 sidecar 时只返回 `missing/old_run_has_no_environment_evidence`，GET 路径不补算。旁路被关闭或抛错时原研究文件哈希不变，错误只写入 sidecar blocked receipt，不修改原研究结果。
4. **精确绑定**：读取器核对 run/data/code/research-config/dataset-manifest/metadata/candidate/factory/source-input-seal 身份；`StrategyDecisionContext` 只保存指向已封印 JSONL 的 `evidence_refs`，未改 Context schema，也未传入 BTC runtime。
5. **Factory 筛选不读分数**：全提交搜索中 `trend_environment/environment_observation` 只出现于 sidecar 生产、封印引用和只读 UI；`quant_shared/alpha_factory` 及其筛选源码与 base 完全一致。训练器将 prediction 与 sidecar reference 分开返回，候选排名和 gate 不消费环境分数。
6. **前端 fail-closed 表达**：只在 run identity、seal integrity、schema、`usage=observation_only` 和安全旗标满足时展示数值；missing/mismatch/blocked/unsafe 不显示观测分数，stale 显式标注不作 current-HEAD 证据。界面始终标注“非实时市场状态/不授予交易权限”，不把环境分数标为执行事实。
7. **BTC 保护边界**：受保护路径 `quant_crypto/`、`quant_shared/strategy_runtime/`、`quant_shared/runtime/`、`quant_shared/alpha_factory/`、`quant_us/backtest/`、`btc_demo_runtime.py` 和 BTC Qlib/universe 配置与 base 无差异。三态对照比较真实注册 signal、计划/保护和 ledger 组件，并由原有 composition/risk/OMS/Guardian 合同覆盖装配；它不是新的 private dispatcher/exchange fill 全链路运行。

## 封印证据重读

- 对共享数据根下 6 个 Qlib seal 重跑 `read_sealed_evidence`，全部 `integrity_status=passed`。dataset-only `m1-okx-factory-input` 按合同为旧 run `trend_environment=missing`，不补算；普通 run 与 4 个 fold 的 sidecar 均 `completed`。
- `m1-okx-qlib`：15,840 条，15,573 observed / 267 unknown，as-of `2026-07-30T00:00:00Z`。四折依次 10,836 / 11,418 / 12,000 / 12,582 条，每折 267 条 warmup unknown；as-of 均不超过自身 test end。
- 普通 run 与四折的代码版本均为 `59f5eb861...`，data version 均为 `btc-okx-public-swap-btcusdt-demo25h-tail-20260730T1145Z-src6cea196b4-corr1`；四折均绑定 source-input seal `d5c446445c8d36787c685080a49d06440e071afb10a089c8043576eec24e6c2e`，Context reference 与封印 observation reference 逐字段一致。
- 由于后续只有 manifest/报告/handoff，在 integrator HEAD `d6074ff5...` 重读时上述计算证据正确显示 `source_stale=true`。这是如实的历史封印证据，不是 current-HEAD promotion/runtime artifact。
- Factory seal 重读 `integrity_status=passed`、`status=completed`、`decision=rejected`、0 candidate、1 model trial、4 次 Qlib fit，`audit_status=not_run_selection_failed`。未调参，不做 Alpha 有效性声称。

## 独立测试

1. `...\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp <external-new-dir> tests/research/test_trend_environment.py tests/integrations/test_trend_environment_sidecar.py tests/contracts/test_m1_btc_behavior_freeze.py`：**25 passed** / 21.99s，1 个 Starlette TestClient 弃用警告。
2. 同解释器运行 Context/CAS/restart、production composition、risk kernel、portfolio exit、guardian latch、OMS delegation、runtime hardening 七组既有合同：**169 passed** / 6.57s。
3. `node frontend/scripts/test-trend-environment.mjs`：**PASS**，覆盖真实 SSR 组件、missing/stale/mismatch/unsafe 与现有三页复用；它不替代浏览器验收。
4. `frontend/` 下 `npm.cmd run lint`（`tsc --noEmit`）：**passed**。为不安装依赖，先核对绝对路径后仅在本工作树创建 ignored `frontend/node_modules` junction，指向注册主工作树既有依赖。
5. 一次 `npm.cmd run lint` 从仓库根误调用，因根目录无 `package.json` 而 `ENOENT`；在正确 `frontend/` CWD 重跑通过。这是命令 CWD 错误，不是代码回归失败。

未运行：6 分钟真实重训（按票据不重跑）、生产者的 5/5 external-root TestClient 封印 API 组合复跑、frontend build、Playwright/正式浏览器、canonical backend restart、current-HEAD runtime/promotion artifact 与 gate rebuild、private/order/live 任何路径。本轮通过 seal reader、Factory service reader、fixture TestClient 和定向合同完成独立验收，不把未复跑项标记为已运行。

## canonical 发布的精确阻塞

root 在本验收期间只读观察到：8765 `/api/health=ok`，`evidence_profile=demo_quasi_live`、`read_only=false`、`controls_disabled=false`，但 `paper_allowed/live_allowed/broker_or_order_allowed=false`；`/__backend_identity` 为 `canonical=true`、`runtime_stale=false`、main HEAD `c1d11987...`。`QLIB_ARTIFACTS_ROOT` 和 Factory root 仍是 canonical repo-local `artifacts/qlib_runs` / `artifacts/alpha_factory_runs`。因此，生产者 5/5 API 是 TestClient 进程内注入本票据 external root 的结果，**不等于 canonical 页面已能发现归档 manifest 数据**。

`unclassified` 保留严格 legacy 发布路径：独立 integrator 之外，仍要求 current-HEAD artifact/read model、promotion gate rebuild 和 backend restart；当前严格启动又会因缺少合法 BTC runtime artifact root 而 fail closed。本票据不得伪造 root、改政策或触达交易端点。

已有 launcher 还提供独立 `research_readonly` profile（`scripts/start_backend_current_main.ps1` 的参数路由与 Python 验收），其前提是 `QS_BTC_DEMO_CONTROL_ENABLED=false`。它可作为下一步向用户请求“限定研究发布”明确授权的选项，但不能在本轮擅自把现有 Demo backend 降级，也不能把它写成满足 `unclassified` strict 发布政策。若后续获授权，仍需先把提交集成到 canonical main，并为只读数据发现、current-main identity 和正式浏览器流程建立新鲜证据。

## Gate 结论与安全旗标

- 本次 `integrated` 只表示获批 Git handoff set 在独立 integrator 分支通过验收；不是 canonical main 发布，不是 M1 最终用户验收，不是 promotion evidence。
- readiness 仍为 `quality_checked`。Factory 已 rejected；历史 available time 是重建语义；平台级实际 private dispatcher 端到端链路未新增验收。
- `promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。
- 下一可执行动作的 owner 是 root/用户：先选择并明确授权 canonical strict 发布，或明确授权 `research_readonly` 限定发布；随后再做 current-main identity、只读证据发现、浏览器滚动/交互和安全旗标验收。在此前 M1 整体保持 blocked，M2—M4 不得启动。

## 治理读取

已完整读取 `AGENTS.md`、`quant-agent-preflight`、`quant-agent-handoff`、`docs/knowledge/README.md`、非协商规则、shared pitfalls、integrator TOML、cross-agent coordination、delivery risk policy、数据可靠性/PIT、金融 ML 验证、领域架构与 BTC 趋势研究 gate。仓库无独立 `integrator_pitfalls.md`，故以 integrator TOML 与 `cross_agent_coordination.md` 作为角色交付合同，未全文读取原始事故日志。

active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
