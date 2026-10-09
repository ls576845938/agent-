# BTC 统一离线只读交付治理独立复审：CORRECTION-01

## 结论与独立性

批准治理修正 `4278777dd06ce8f1bffe570887c8d4abb6654d75` 进入独立的限定集成，readiness 上限为 `quality_checked`。这不是正式部署通过、研究成功或交易授权。原治理独审 `420171d76b9f475c9ad15ba3865a50d4e11e2ed2` 及其历史交接保留；本报告仅是针对新修正提交的后继复审。

原校验器要求 backend 身份提供其生产接口刻意不暴露的目录字段。修正接受正常的无目录字段形状，同时严格保留真实主版本、只读部署与独立 listener 归属证明。没有补造生产身份字段、修改生产接口或放开权限。

本次复审由主会话执行，actor 为 `root_btc_unified_readonly_compatibility_review_20261004`，上下文 `agent-integrator-btc-unified-ro-gov-compat-review-c01`。主会话未编写 producer 的校验器、测试或说明修正。尝试派发新的独审代理和继续旧独审代理均被产品代理数量上限拒绝，因此由独立于 producer 的主会话核对已提交对象并运行独立回归；后续 source integration 仍由另一名 release integrator 执行。不得把报告 actor 当成密码学签名，也不得让下一 integrator 自批本治理修正。

## 已提交对象与限定范围

- 固定业务 base：`eaa88400f01e47e5c8da377606b6df52a9543382`。
- 原业务独审来源：`58b37ac726cfd0d5276356782e7868c873f1aab1`，原业务交接 HEAD：`ba9f28bd6272bbcae62c6bb5c0e5f9ce55633a29`。
- 本次治理 deliverable：`4278777dd06ce8f1bffe570887c8d4abb6654d75`；其交接 HEAD：`6a8e422421d9e5c35df322df04b865caca9f68a2`。
- published 交接路径：`.agent/handoffs/BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004/published-btc-unified-offline-readonly-governance-20261004-correction-01-4278777dd.json`。
- 交接 SHA-256：`7c4a7060baf3d7a6b8f5ee47119a5bf24f68af21da9fa2d7d9bc8bbc42bfce6c`，现有 validator 返回 `valid`。
- producer 报告 SHA-256：`56f38daf326d5110f87d33219a3418ea471a6195f61a54d2d0b757b57bb6cd8a`。
- validator SHA-256：`77a207c22bbcb1e01328e98d163981b2de76af4172aef0b1bab1db33341d05cc`。
- JSON 合同未改变：raw SHA-256 `4d577b7351a0644a82f3deb7c323f6e00422468563c565033068ec63f938d03a`，canonical SHA-256 `15a23d317265f4f0bc3235983152a3a5f81755e09cd2565641f14235762ac695`。

base 到新治理提交仍是原四个 sidecar 加 producer 报告五路径。相对原 `2920ca044772f561d21b9550cfb9afbeaffbd672`，只有 validator、测试、最小说明和 producer 报告改变；旧 `85fb02c...` envelope 不在新治理 deliverable。未触及通用 risk policy、启动器、认证、hook、业务源码或交易权限。冻结的 33 个源码对象及六个依赖交接从 Git 对象核验通过。

## 静态审查与回归结论

1. backend 必须具有原 schema、canonical/nonstale、正确 source/main HEAD、main branch/port，并显式保持 `research_readonly`、`read_only=true`、`controls_disabled=true` 和原四个交易相关权限 false。
2. backend 不提供路径合法，但不能替代独立 listener 的实际 PID、端口、已核对进程、注册主树与源码 HEAD 绑定。提供的每一项路径都必须非空、绝对且精确匹配；正确 worktree 不能遮住错误 repo_root。
3. frontend 仍必须显式提供 worktree，不能以 repo_root 或 listener 代替。manifest、当前 HEAD、dirty、freshness、真实浏览器与回退要求保留。
4. 空字符串不再经 `Path('')` 解析为当前目录。治理测试对“main 没被改变”的断言改为执行前后同一真实 main HEAD，不把注册 main 永久假定为旧 eaa；生产 base/source 规则未改变。
5. 校验只读，不启动服务、写 receipt、运行研究或授予权限。缺失字段不默认为 false；mock/fixture、实际读取失败和业务漂移仍拒绝。

独立执行的定向回归：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py -k 'existing_backend_identity_without_paths or backend_optional_identity_path or backend_mismatching_second_path or pathless_backend_identity or frontend_requires_worktree' --basetemp "$env:TEMP/btc-unified-ro-gov-compat-review-c01-20261004-c68a7"
```

结果：`15 passed, 69 deselected in 0.74s`。正例使用生产身份形状、不补路径；错误 HEAD、profile、权限、listener、路径及缺 frontend worktree 均拒绝。

独立执行 `py -3 tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py --verify-source`，结果 `valid/errors=[]/permissions_granted=false`。`git diff --exit-code 2920ca0... 4278777... -- docs/agent_playbooks/btc_unified_offline_readonly_delivery_20261004.json` 返回 0。

复用 producer 的冻结全套结果 `84 passed in 161.57s` 和失败优先结果：旧校验器正常 backend 正例失败；首次修正又暴露空路径问题，随后拒绝条件收紧。未重跑无变化的业务矩阵、全年、训练、模型研究、worker、服务或页面。主会话在另一部署阶段的页面观察不作为本治理独审的正式部署证据。

## 执行记录、风险与未完成项

review tree 由 planner 从精确 `6a8e422...` 创建，路径 `worktrees/integrator-btc-unified-ro-gov-compat-review-c01`，branch `agent/integrator/btc-unified-ro-gov-compat-review-c01`，sparse=true。本 reviewer 只写此报告和既有治理独审 namespace 的新 append-only envelope。初始限定 dirty=0；没有消费 producer dirty、覆盖其他文件或改写旧交接。

change_risk=`governance_control`。已读取 quant-agent-preflight/handoff、AGENTS、knowledge/non-negotiables、shared pitfalls、integrator TOML；仓库无独立 integrator_pitfalls.md，按 integrator TOML 与 shared playbook 执行。context packet 命中 GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS，对应 `-001`。catalog hash 为 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。Team Context 是 discovery_only，显示 17 blocked 和 20 历史 invalid；仅消费本票已明确验证的交接，不放行或修复无关交付。

后续由不同 actor/context 的 release integrator 消费本 report commit、精确 SHA 与新交接，完成 metadata-only 集成；随后主会话才重启正式 main，采集新 HEAD 的 listener/identity/health/browser 证据并验收。旧 main `8372466...` 的服务观察不得包装成新版本的验收。

本阶段不生成数据 manifest、交易产物或经济账本。真实 Qlib R2/R3 的模型与校准缺项、零个真实可比较候选对、共同账户页面/HTTP 尚未提供等限制继续保留。以下全部 false：candidate_management、management_write、offline_worker、demo、demo_control_enabled、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、runtime_worker_enabled。

<!-- btc-unified-offline-readonly-evidence
{"schema_version":"btc_unified_offline_readonly_evidence_v1","kind":"governance_review","ticket_id":"BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004","outcome":"approved","deployment_profile":"research_readonly","readiness_ceiling":"quality_checked","limitations":["coordination_application_interface_only_no_common_account_page_or_http_flow","qlib_member_identity_and_fixture_not_real_valid_model","R2_R3_model_and_calibration_limits_retained","no_real_comparable_candidate_pairs_or_new_research","original_promotion_demo_paper_live_and_execution_gates_remain_blocked"],"actor_role":"integrator","actor_id":"root_btc_unified_readonly_compatibility_review_20261004","context_id":"agent-integrator-btc-unified-ro-gov-compat-review-c01","reviewed_commit":"4278777dd06ce8f1bffe570887c8d4abb6654d75"}
-->
