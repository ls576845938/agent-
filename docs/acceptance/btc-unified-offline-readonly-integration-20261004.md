# BTC 统一离线候选只读发布独立源码集成 CORRECTION-01（2026-10-04）

## 结论

本票 CORRECTION-01 的 `source_review` 结论为 `approved`，readiness 上限为 `quality_checked`。批准范围仅是：在已部署候选 `837246619a6e79c0d4481da61950cae2fa6bab2c` 上合入已独审的治理兼容修正 `4278777dd06ce8f1bffe570887c8d4abb6654d75` 及复审 `91b725a8bbdf7d813aa707964ff7bf128b869d7f`。修正只让 deployment validator 接受生产 backend canonical identity 的真实无 physical-root 字段形状，同时仍以独立 listener 证据绑定注册主树；frontend worktree、HEAD/profile/权限/freshness/browser/rollback 要求均未放宽。

本结论不是 deployment acceptance，不代表 CORRECTION-01 候选已合入 main、已按新 HEAD 重启 8765/3000 或已完成 canonical browser 验收。registered main 当前仍为上一轮已部署候选 `837246619...`，且固定 rollback ref 已存在并指向 `eaa88400...`；本报告不把这些上一轮事实冒充新候选部署证据，也不授权管理写入、离线 worker、Demo、promotion、paper、live、private、order 或真实交易。原源码 `source_change_risk` 保持 `demo_execution_semantics`；发布 profile 固定为 `research_readonly`；治理候选自身为 `governance_control`，没有把执行语义重新分类为普通研究改动。

## 独立性与 Git 链

- ticket：`INTEGRATE-BTC-UNIFIED-OFFLINE-READONLY-20261004`。
- role：短生命周期 `integrator`。
- actor：`btc_unified_readonly_release_integrator_20261004`。
- context：`agent-integrator-integrate-btc-unified-offline-readonly-20261004`。
- producer actor：`btc_unified_readonly_governance_producer_20261004`。
- CORRECTION-01 governance reviewer actor/context：`root_btc_unified_readonly_compatibility_review_20261004` / `agent-integrator-btc-unified-ro-gov-compat-review-c01`。原 reviewer `btc_unified_readonly_independent_integrator_20261004` / `agent-integrator-btc-unified-ro-gov-review-20261004` 仅属于首次治理独审历史。
- approved base：`eaa88400f01e47e5c8da377606b6df52a9543382`。
- 原封存源码独审提交：`58b37ac726cfd0d5276356782e7868c873f1aab1`。
- 原源码 integrated envelope commit：`ba9f28bd6272bbcae62c6bb5c0e5f9ce55633a29`。
- 原治理 producer/reviewer 链 `2920ca0... -> 420171d...` 继续作为历史祖先保留。
- CORRECTION-01 治理 producer：`4278777dd06ce8f1bffe570887c8d4abb6654d75`；producer handoff commit：`6a8e422421d9e5c35df322df04b865caca9f68a2`。
- CORRECTION-01 独审报告 commit：`91b725a8bbdf7d813aa707964ff7bf128b869d7f`；有效独审 handoff commit：`5d3310aba7dd69c42aab1534bc02cb5ad6b8f42c`。
- 隔离的无效 handoff 分支 `5b47f13e246a9990d8d5fd93720aea82eb6916b4` 不是 `5d3310a...` 或本候选祖先，未消费。
- 合成 merge：`60abafcf936cb3ab3804fbe524917da506449f45`，parents 为 `ba9f28b...` 与 `0f70f52...`；`ba9f28b...`、`2920ca0...`、`420171d...` 和 `0f70f52...` 均为祖先。
- identity 派生提交：`93318ef013463805e0b7818f0f1cb0d7d437528d`；CORRECTION-01 不触碰 frontend，继续复用同一 manifest/fingerprint。
- CORRECTION-01 合成 merge：`5d025e00fa0c469b6be4d7942f541347a63b650e`，parents 为已部署候选 `8372466...` 与有效复审 handoff `5d3310a...`。

CORRECTION-01 工作树由 `worktree_plan.py` 从实际 main `8372466...` 创建：`agent/integrator/btc-unified-ro-compat-integrate-c01`，sparse checkout 为 true。43 个已知 source/governance/review/integration/identity 路径在合并前 `safe_status` 均为 clean；没有读取、覆盖、清理或回滚其他 worktree 的 dirty 文件。`--no-ff` 合并出现五个预期 add/add 冲突，仅限 producer/reviewer 报告、sidecar MD、validator 与治理测试；逐文件选择有效复审链 `5d3310a...` 的 blob，并核对 index blob 与 approved blob 全部相同。没有业务冲突。

## 封存对象与 hash

- 原独审报告 raw SHA-256：`b9a053dc62e851e732a646b7005a79563d4850fcb5a880b0d9d4a89f9fcc9a7e`。
- 原 integrated envelope raw SHA-256：`6e95c798e6381496560b92ffa731d8d66feb3ac7278e55aefbb281860b2bec91`；现有 handoff validator 返回 valid。
- 治理 producer handoff raw SHA-256：`74ca8205c70afe9179a4eba3d6907fd5d9bbf9178f8ba3310d2ac26a5737e996`；现有 handoff validator 返回 valid。
- 治理独审报告 raw SHA-256：`08f2ee45a7160bbd7569dc19f6bcfc4a93f044a3d77fc220a82af423c2ef4b1d`。
- 治理独审 handoff raw SHA-256：`772d52bd11141d3e3b7240a8ba0e08a2f192baf4f4f165f357215a4353697218`；现有 handoff validator 返回 valid。
- contract JSON 保持 raw SHA-256 `4d577b7351a0644a82f3deb7c323f6e00422468563c565033068ec63f938d03a` / canonical SHA-256 `15a23d317265f4f0bc3235983152a3a5f81755e09cd2565641f14235762ac695`。CORRECTION-01 的说明 MD、validator、治理测试 raw SHA-256 分别为 `b9afa9f18d129ab23e28bbd23d46c740959bd266f300d0962b47b050b62ff412`、`77a207c22bbcb1e01328e98d163981b2de76af4172aef0b1bab1db33341d05cc`、`ae364799e480d0b209ff6c91c613f8f564a074c16f1caa17e4df0eea0011e378`；当前树与 `4278777...` 对象一致。
- CORRECTION-01 producer handoff raw SHA-256：`7c4a7060baf3d7a6b8f5ee47119a5bf24f68af21da9fa2d7d9bc8bbc42bfce6c`；复审报告：`c0649803ec74fb6d4ee76a867f6617344390ac30bd975491be1d8e74d67f90a9`；有效复审 handoff：`3443728d60e3d4ecdbd10aca971c1c988c93a946018350b0458040368ec6c4b5`。
- 派生 identity raw SHA-256：`30ea990c08dc01111d26bdf17460d7923e7dcdba43c7c3b081610fcb8498fe49`；`baseline_commit=60abafcf936cb3ab3804fbe524917da506449f45`，fingerprint=`7260b2c8405dc3f6403a845dd45eac54f2e909266dd8ba7796a376c8198ebaa5`。

原 `93318ef...` identity 阶段从 `58b37ac...` 起的 delta 只有原 integrated envelope、首次治理四 sidecar/报告/handoff 与派生 identity；在那个历史阶段四 sidecar 与 `2920ca0...` 一致。CORRECTION-01 当前 source tree 中四 sidecar 精确与 `4278777...` 一致（其中 contract JSON 未变，MD/validator/test 为已审修正对象）。33 个封存业务/文档/测试对象未改；没有业务、launcher、auth、hook、通用治理、权限或服务改动。

## 验证

本 integrator 实际运行：

1. `py -3 tools/agent_governance/handoff.py --repo-root . validate --input <原 ba9 envelope>`：valid。
2. `py -3 tools/agent_governance/handoff.py --repo-root . validate --input <85fb governance envelope>`：valid。
3. `py -3 tools/agent_governance/handoff.py --repo-root . validate --input <0f70 governance review envelope>`：valid。
4. `py -3 tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py --verify-source`：`status=valid`、`errors=[]`、`permissions_granted=false`。
5. `py -3 -m pytest -q -p no:cacheprovider tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py -k "existing_backend_identity_without_paths or backend_optional_identity_path or backend_mismatching_second_path or pathless_backend_identity or frontend_requires_worktree" --basetemp <独立 OS TEMP>`：`15 passed, 69 deselected in 1.18s`。
6. source-review receipt 在本报告与新 integrated handoff 提交后由同名只读 validator 读取外置 JSON 复验；receipt 不进入仓库以避免自引用循环。

未重跑：原独审已封存的协调 22、默认 runtime/proof 2、registered Donchian 2、Qlib primary 1、前端静态/tsc；也未运行完整业务矩阵、研究/训练、offline worker、backend/frontend service、浏览器/HTTP、promotion artifact 或 deployment acceptance。元数据后继没有改变封存对象，不能把“未重跑”改写成新增通过。

## 治理、artifact 与 gate

读取：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator TOML、research readonly release、delivery risk policy，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review`。context packet 使用 role=`integrator`、scopes=`shared,btc,research,gate`、`change_risk=demo_execution_semantics`；catalog hash=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未全文读取原始事故日志。

本票没有发布 data/artifact/manifest/ledger/replay，也没有 current-main freshness 或 runtime/browser evidence。原真实模型、calibration、可比较候选对、新研究及 promotion gate 继续 blocked/fail-closed；共同账户协调仍只有 application interface，没有共同账户页面/HTTP 用户流程；Qlib fixture 不是真实有效模型，R2/R3 限制不变。

## 后续与保持为 false 的安全旗标

下一步仅由主会话把当前位于 `837246619...` 的 registered main fast-forward 到本 CORRECTION-01 候选，核验既有固定 rollback ref 仍精确指向 `eaa88400...`，再通过 canonical launcher 按新 HEAD 重启并产生 900 秒内真实 listener/identity/health/browser evidence。若实际页面读取失败，应发布 failed deployment report，不得伪造 approved marker；deployment report 可在实际 deployed HEAD 的独立证据分支保存而不回写 main，避免 runtime identity stale 循环。

以下全部保持 literal false：`candidate_management`、`management_write`、`offline_worker`、`demo`、`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`、`runtime_worker_enabled`。

<!-- btc-unified-offline-readonly-evidence
{"schema_version":"btc_unified_offline_readonly_evidence_v1","kind":"independent_integration","ticket_id":"BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004","outcome":"approved","deployment_profile":"research_readonly","readiness_ceiling":"quality_checked","limitations":["coordination_application_interface_only_no_common_account_page_or_http_flow","qlib_member_identity_and_fixture_not_real_valid_model","R2_R3_model_and_calibration_limits_retained","no_real_comparable_candidate_pairs_or_new_research","original_promotion_demo_paper_live_and_execution_gates_remain_blocked"],"actor_role":"integrator","actor_id":"btc_unified_readonly_release_integrator_20261004","context_id":"agent-integrator-btc-unified-ro-compat-integrate-c01","reviewed_commit":"4278777dd06ce8f1bffe570887c8d4abb6654d75","governance_review_commit":"91b725a8bbdf7d813aa707964ff7bf128b869d7f"}
-->
