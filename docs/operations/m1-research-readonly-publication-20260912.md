# M1 research_readonly 发布准备：producer 交付报告

状态：**producer 已完成，等待独立发布 integrator**。本票据把已审定的 M1 封印研究证据接入 canonical 现有四个只读 GET；没有部署、启动或停止服务，也没有运行正式浏览器验收。readiness 上限为 `quality_checked`，不是 promotion、paper 或 live 证据。

## 身份、治理与工作树

- role=`super_developer`；change risk=`research_readonly_release`。
- 审定 base=`7700450bbc41465ec44c223fbec42f315dcdf30d`；registered main 在 producer 期间保持 `c1d11987d28f06bb0fe89b2c289e88d07522790d`。
- planner：`py -3 tools/agent_governance/worktree_plan.py --role super_developer --task-id m1-readonly-publication-20260912 --base-ref 7700450bbc41465ec44c223fbec42f315dcdf30d --apply`；branch=`agent/super_developer/m1-readonly-publication-20260912`；`core.sparseCheckout=true`。
- 已批准 M1 final=`165a446729f8c114748e1b20bbfcf0c91e75066e` 从 Git 对象验证后无冲突合入本分支；治理票据与 M1 票据保持分离。producer source commit=`4c7e48a9e003088c99e500ffd7f32adfb323d752`。
- fresh preflight：`--change-risk research_readonly_release --scope shared --scope research --scope gate`；catalog=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`RESEARCH-HOLDOUT-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未全文读取原始事故日志。
- 已读 `AGENTS.md`、knowledge README、non-negotiables、shared/super_developer playbook、delivery risk policy、research readonly release contract、治理独立审定报告、`quant-agent-preflight`、`quant-agent-handoff` 与三份 M1 报告。
- fresh Team Context 已生成，仍如实显示 CN/US domain read model missing 与 BTC runtime artifact root unavailable；命令因这些 fail-closed blocker 返回 1。本票据没有把它们扩成新工程范围。

治理 published/integrated 两个事件及 M1 code/data/review 三个事件均经 `handoff.py validate` 返回 `status=valid`。初始限定 `safe_status.py` 的 8 个 producer 路径全部 clean；没有重叠 dirty 文件，未覆盖、回滚或清理其他工作树。为运行既有 app imports，只读扩展 sparse 到 `quant_crypto`、`quant_cn`，未修改其中任何文件。

## Touch set 与职责边界

本 producer 新增/修改：

- `backend/app/services/research_archive_discovery.py`：通用只读 archive catalog 的首个 M1 固定条目；固定 Git manifest、数据身份、6 个 Qlib ID 和 1 个 Factory ID，每次读取使用 `load_manifest_from_git` 与 `resolve_manifest_payload(..., verify_files=True)`。
- `backend/app/api/app_factory.py`：Qlib list/detail 在 `research_readonly` profile 自动合并只读 archive；保持原 `artifacts_root` server-owned 拒绝，并拒绝用户传入 manifest/root/ref/path selector；archive 错误 503、同 ID 冲突 409、unknown 404。
- `backend/app/services/alpha_factory.py`：Factory list/detail 可从同一只读数据集读取，并用该版本的 Qlib root 验证 input 与 trial seals；submit/queue/lock/resume 和本地写 roots 保持原样，archive ID 不可写或 resume。
- `backend/app/api/alpha_factory.py`：对两个 Factory GET 增加 selector 拒绝及 archive 409/503 显式响应。
- `tests/api/test_m1_research_readonly_archive.py`：失败优先与四 GET、完整性、冲突、逃逸、无写入、兼容合同。
- `frontend/public/frontend-identity.json`：在 source commit 后由官方脚本刷新；baseline=`4c7e48a9e003088c99e500ffd7f32adfb323d752`，fingerprint=`421d1b955739d9438240dccd86ee44293a36d7eaf6c7fb86b2554ff7ff1d4d6e`。
- 本报告与 `.agent/handoffs/M1-READONLY-PUBLICATION-20260912/` 的 append-only published event。

从审定 base 到最终 producer 的实际 diff 还包含已批准 M1 final 的 22 个提交态路径；下游必须审查完整真实 diff。三份既有 M1 报告未被重写。治理文件已经存在于审定 base，不把 `c1d11987 -> 7700450b` 的治理保护路径伪装成本 research 类别变更。

没有修改 schema/enum、策略信号、仓位、退出、risk、OMS、保护、账本、broker/private transport、权限、BTC runtime artifact store、launcher、治理政策或 M2—M4。

## 固定证据与读取语义

- Git manifest selector=`165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json`；客户端不能覆盖 selector。
- manifest Git blob SHA-256=`2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a`；aggregate=`593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`；160 files / 56,134,415 bytes。
- producer/computation commit 保留 `59f5eb86132fd0e386d1d4e733c9fbc53ff80d7e`；`historical_reconstructed_availability` 与 `source_stale=true` 如实保留。Factory 仍为 `rejected`、0 candidate、`audit_not_run_selection_failed`；没有把 seal 改写成 current HEAD 证据。
- archive 响应只给 `shared-data://...` 逻辑 provenance，不泄漏 physical root。本地响应继续给 repo-local 逻辑路径。
- local 与 archive 同 ID 明确 fail closed；manifest/file/root 解析失败不退化为空成功；archive seal 不完整不返回成功详情。旧 local run 缺失仍为 404，不补算、不 export、不 mkdir、不 repair。
- Factory archive 读取时 input 与四折 trial 都解析到同一 immutable Qlib version；写服务的 `root`、`qlib_root`、queue、locks 与 resume 仍是原本本地路径。

## 验证结果

- failure-first：新增测试在旧代码上 `1 failed in 0.37s`，精确失败 `ModuleNotFoundError: backend.app.services.research_archive_discovery`。
- 首版扩展测试暴露 Qlib 两 GET 的局部 `Request` postponed-annotation 被识别为必填 query，产生 422；改成显式 selector 拒绝参数合同后修复。最终：
  `python -B -m pytest -q -p no:cacheprovider tests/api/test_m1_research_readonly_archive.py tests/api/test_qlib_pipeline.py tests/api/test_alpha_factory.py tests/research/test_alpha_factory.py` → **72 passed, 1 warning in 27.08s**。
- `python -B -m pytest -q -p no:cacheprovider tests/research/test_trend_environment.py tests/integrations/test_trend_environment_sidecar.py tests/contracts/test_m1_btc_behavior_freeze.py` → **25 passed, 1 warning in 18.06s**。
- `python -B -m pytest -q -p no:cacheprovider tests/contracts/test_strategy_decision_context_v1.py tests/contracts/test_btc_demo_production_composition.py tests/contracts/test_btc_shared_platform_v3_risk_kernel.py tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py tests/contracts/test_btc_shared_platform_v3_guardian_latch.py tests/contracts/test_btc_shared_platform_v3_oms_delegation.py tests/contracts/test_btc_okx_demo_runtime_hardening.py` → **169 passed in 6.10s**。
- `node frontend/scripts/test-trend-environment.mjs`（仓库根）→ **PASS**；覆盖 SSR 的 evidence/missing/stale/mismatch/unsafe 与三页复用，不替代浏览器验收。首次从 `frontend/` CWD 误写重复路径而 `MODULE_NOT_FOUND`，改用正确相对路径后通过。
- `npm.cmd run lint`（`frontend/`）→ **passed**；`npm.cmd run build` → **passed**，5258 modules / 47.41s；既有 >500KB chunk 告警保留。依赖为经绝对路径核验的 ignored canonical `frontend/node_modules` junction，没有安装新依赖。
- `py -3 tools/agent_governance/shared_data.py ... resolve --manifest-git-spec <fixed-selector>` → `status=resolved`、`consumer_read_only=true`，执行全文件哈希验证。
- `git diff --check` 与 Python compile 检查通过。

未运行且仍 pending：registered-main 集成、backend restart、8765/3000 listener/identity 复核、canonical `research_readonly` 启动、正式浏览器展开/时间切换/Factory fold 链接/unknown 交互、rollback 实施、promotion/runtime artifact 或 gate rebuild。没有重训 6 分钟 sealed run，没有访问 network、secret、private/order/live endpoint。

## Gate、回退与下一入口

结论仅为 producer `quality_checked`。独立 integrator 必须从 registered main 按“治理审定提交 → 本 M1 producer”顺序集成，验证 base-to-final 完整 diff、逐文件 hash、执行语义不变、当前 main identity、固定 `research_readonly` profile、正式浏览器与回退点。候选 rollback point 是治理审定 base `7700450bbc41465ec44c223fbec42f315dcdf30d`；它尚未在 registered main 发布，不能由 producer 标记 `rollback_point_verified=true`。

保持：`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。`current_main_identity`、`canonical_browser_acceptance`、`rollback_point_verified` 仍 pending；handoff/manifest 不解锁任何 gate。
