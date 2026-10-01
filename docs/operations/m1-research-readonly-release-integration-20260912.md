# M1 research_readonly 发布：独立集成验收

状态：**独立 sparse 集成与有限矩阵通过，形成可发布 integration head；registered main、服务切换、canonical 浏览器与最终 release receipt 仍 pending。** 本报告只达到 `quality_checked`，不是 promotion、paper、live 或运行时证据。

## 身份、治理与有序交付

- role=`integrator`；change risk 明确选择 `research_readonly_release`，scopes=`shared,research,gate`。
- registered main / 实际发布前回退点=`c1d11987d28f06bb0fe89b2c289e88d07522790d`。本票据没有推进 main、没有裸改 ref、没有启停服务。
- planner worktree=`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-m1-readonly-release-20260912`；branch=`agent/integrator/m1-readonly-release-20260912`；`core.sparseCheckout=true`。
- 治理集合先从 c1d fast-forward 到独立审定 `7700450bbc41465ec44c223fbec42f315dcdf30d`；随后才合入 M1 producer final=`fdfd716fdcfb4f3b1e78a7c6590fcec071394dc3`。两集合保持分离，没有把治理 protected paths 混入 research receipt。
- M1 deliverable=`7211bef9fed42d42d4e07df94f1b5a1db4233d26`；source=`4c7e48a9e003088c99e500ffd7f32adfb323d752`；本 integrator 边界修复=`88ebba053bc412c4cc1e359dd685fa9f2394f80c`；frontend identity refresh=`5af0ef5e44ee753ee14ad9a86ca8ff98297fec40`。
- ancestry `c1d -> 770 -> 4c7e -> 7211 -> fdfd -> 88eb -> 5af0` 全部成立。治理 published、治理 integrated、M1 published 三个 envelope 均经 `handoff.py validate` 返回 `status=valid`；M1 7 个 deliverable Git blob SHA-256 mismatch=0。
- 初始限定 `safe_status.py` 覆盖治理 11 个路径和 M1 30 个实际 changed paths，结果 clean；没有重叠 dirty 文件、冲突、回滚或清理其他工作树。

治理合入后重新运行 fresh context：catalog=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；固定 `independent_integrator_required=true`、`promotion_artifact_rebuild_required=false`、`backend_restart_required=true`、`fast_forward_main_allowed=false`、profile=`research_readonly`、readiness ceiling=`quality_checked`。Team Context 仍显示 14 个历史 invalid handoff、CN/US read model missing 与 BTC runtime artifact root unavailable；这些 blocker 未被隐藏，也不扩成新工程范围。

命中并保持适用：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。已读 `AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、cross-agent coordination、integrator role、delivery risk policy、research readonly release playbook、治理独立审定和 producer/M1 报告，以及 `quant-agent-preflight`、`quant-agent-handoff`；未全文读取原始事故日志。

## 完整 diff 与语义审查

research receipt 的 `changed_paths` 精确取 `7700450... -> 5af0ef5...`，共 30 个路径：immutable manifest / 既有 M1 handoff、4 个 backend 文件、M1 报告、frontend identity / SSR 脚本 / 3 个研究组件、Qlib adapter / trend environment 旁路、验收脚本和测试。未命中 `research_readonly_release.protected_path_prefixes`。

独立审查确认：

1. 四个既有 GET 只在 `research_readonly` profile 合并 server-fixed archive；manifest、ref、root、path 等客户端 selector 被拒绝。local write root、submit、queue、lock 与 resume 语义未改变，archive ID 不可提交或恢复。
2. fixed Git manifest 每次经 immutable resolver 和全文件 hash 校验；缺失/损坏为 503，同 ID 冲突为 409，未知 run 为 404，不读取时补算、建目录或改写来源；正常响应只暴露 `shared-data://` 逻辑 provenance。
3. M1 趋势环境是资产隔离、因果时间、显式 calendar 的纯研究旁路；Factory 筛选不读取该分数，BTC signal/position/exit/risk/OMS/protection/ledger 与配置保持冻结。前端只显示精确 run 的封印证据，missing/mismatch/unsafe 不借其他 run 补齐。
4. 历史计算 commit=`59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`、真实 data version、as-of、`historical_reconstructed_availability` 与 `source_stale=true` 保留。Factory 仍 `rejected`、0 candidate、`audit_not_run_selection_failed`；不得写成 current-HEAD promotion/runtime evidence。

## 独立发现的两处边界缺陷与修复

root 复读 producer 提交后指出两个同票据风险，本 integrator 用临时 fixture 做失败优先验证：

- archive 模式下 `AlphaFactoryService.get` 未先调用既有 `_run_path`，导致 `..`、绝对 run id 和真实 NTFS junction 逃逸没有维持旧 `FactoryError` containment 合同。
- archive resolver / Factory seal 的底层异常文本可能把 physical shared-data 路径直接放入 503 detail。

失败优先：`tests/api/test_m1_research_readonly_archive.py -k "preserves_local_run_id or redact_physical_paths"` 在 producer final 上为 **4 failed**（parent / absolute / junction / physical-root redaction）。最小修复只做：`get` 前置复用 `_run_path`；resolver 与 archived Factory seal 对外只返回稳定错误码、原异常仅保留在 exception chain；补 4 个回归。修复后本地为 **4 passed, 7 deselected in 3.05s**。

root 对 commit `88ebba053bc412c4cc1e359dd685fa9f2394f80c` 做了独立只读 diff 复核，并用全新临时 basetemp 重跑同组：**4 passed, 7 deselected, 1 warning in 4.86s**，无 skip；root 未修改代码、文档或服务。该修复未改变 archive 的固定数据、四 GET 正常语义或任何交易语义。

## 数据、seal 与测试证据

- manifest=`.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`；Git selector=`165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`。
- manifest Git blob SHA-256=`2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`；160 files / 56,134,415 bytes；aggregate=`593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`。
- 非 `--fast` 的 `shared_data.py resolve` 返回 `status=resolved`、`consumer_read_only=true`，完成全文件 hash 验证。6 个 Qlib run 与 1 个 Factory run 的既有 seal 结论保持；没有重训、修补 seal 或改写 stale。
- archive + 旧 API：`python -B -m pytest -q -p no:cacheprovider --basetemp <external-new-dir> tests/api/test_m1_research_readonly_archive.py tests/api/test_qlib_pipeline.py tests/api/test_alpha_factory.py tests/research/test_alpha_factory.py` -> **76 passed in 32.77s**。
- M1：同解释器/独立 basetemp 跑 trend environment、sidecar、BTC freeze -> **25 passed in 20.72s**。
- BTC 既有冻结合同七组 -> **169 passed in 5.68s**。
- `node frontend/scripts/test-trend-environment.mjs` -> **PASS**；这是 SSR contract，不替代浏览器。
- `frontend/` 下 `npm.cmd run lint` -> **passed**；`npm.cmd run build` -> **passed**，5258 modules / 15.51s，保留既有 >500KB chunk warning。
- `npm.cmd run identity:check` -> **passed**，fingerprint=`421d1b955739d9438240dccd86ee44293a36d7eaf6c7fb86b2554ff7ff1d4d6e`、manifest match=true、baseline ancestor=true。先提交 source 修复，再由既有 `identity:refresh` 把 baseline 更新到 `88ebba053...` 并单独提交。
- `git diff --check` 对治理集合、M1 producer 集合及本修复均通过。

新 sparse worktree 首次运行 frontend 三项时因没有 `frontend/node_modules`，分别得到缺 `typescript`、`tsc`、`vite`；这不是代码回归。核验 canonical `frontend/node_modules` 的绝对路径后，仅在本 worktree 建立 ignored junction，不安装或修改依赖，随后按上列命令全部通过。

## 当前运行事实、receipt 与阻塞

本票据没有启停服务。当前 registered main 仍为 c1d；root 最近只读观测现有 8765/3000 仍绑定 c1d，backend profile=`demo_quasi_live`、`read_only=false`、`controls_disabled=false`。因此不能声称当前运行的 `demo_control_enabled=false`，也不能把 `current_main_identity` 或 `canonical_browser_acceptance` 填为已完成。当前可观测 `paper_allowed=false`、`live_allowed=false`、`broker_or_order_allowed=false` 保持。

用真实 `770 -> 5af0` changed paths 运行 `delivery_policy.research_release_blockers` 的预发布记录，保留：

- `research_release_checks_invalid:current_main_identity`
- `research_release_checks_invalid:canonical_browser_acceptance`
- `research_release_safety_flags_invalid:demo_control_enabled`
- `research_release_unsafe_extra_flag`

这四项只能在 registered main 受控推进、以 `QS_ALLOW_FIXTURE_FALLBACK=false`、`QS_BACKEND_EVIDENCE_PROFILE=research_readonly`、`QS_BTC_DEMO_CONTROL_ENABLED=false` 通过既有 canonical launcher 重启，并完成 listener / identity / health / 正式浏览器后复核；不得用填写 JSON 代替事实。启动前回退点是 c1d，不是治理 base 770。

未运行且仍 pending：registered-main 受控发布、backend/frontend restart、canonical `identity:check -- --canonical`、8765/3000 listener/PID/identity 复核、正式浏览器的 M1 页面与交互验收、最终 release receipt。也未运行 M1 重训、M2—M4、BTC root bootstrap、promotion/runtime artifact builder、private/order/live endpoint、网络数据采集或 secret 读取。

最终边界：本票据未授予 Demo 或交易能力；现有未重启 Demo 进程事实也未被改写。`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`；`demo_control_enabled` 的发布后 false 仍待真实 canonical 验收。M1 readiness 仅 `quality_checked`，M2—M4 未授权。
