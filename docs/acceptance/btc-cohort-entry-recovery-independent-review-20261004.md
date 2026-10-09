# BTC 共同账户组合入口与恢复独立验收（拒绝）

票据：`BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004`

变更风险：`demo_execution_semantics`

## 结论

最终 source `3d4d8841385c80cec12e9ae793232b4fad597528` 未通过共同账户组合入口与恢复验收。限定的 `research_readonly` 能力披露、只读说明和 fail-closed 文案可以作为后续治理交付的输入，但不证明 proposal／review／start 管理流、共同经济执行或 post-ledger projection recovery 可用。本结论不自动创建后续票据，也不解锁 main 合入、部署、Demo、paper、private/order/live 或 promotion。

当前真实 Donchian 与注册 Qlib pair 仍结构性不兼容：执行分别是 Donchian t+1 与冻结 Qlib t+2 delayed-open 加方向成本；保护分别是 `btc_demo_p0_exchange_guard` 100/200bps 与 `registered-1bc91cabc0aed1edf2d75ee3` 400/800bps，完整 policy hash 不同。因此真实共同成交和真实共同恢复均为 `not_run`，seam fixture 不得替代。

## 固定身份与交付校验

- approved base 与注册 main：`a78e5e112f564c1ceaf47c57fc3035542cd12562`；验收期间 main 未变化。
- producer source：`3d4d8841385c80cec12e9ae793232b4fad597528`；最终 handoff commit：`2c9955a157611c1f5b7b598f9c3ef1bec66f43e2`。
- handoff：`.agent/handoffs/BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004/published-btc-cohort-entry-recovery-final-doc-correction-20261004-3d4d88413.json`；`handoff.py validate` 为 `valid`；raw SHA-256 为 `e8286b91aa4ee1c5737ba345d6d6d580fe713df2353b3c1504607ee6b81173e8`；18 个声明 deliverable blob SHA-256 全部匹配。
- base 是 source 祖先，source 是 handoff commit 祖先；最终时间 `2026-10-04T12:34:42.1517466Z` 合法。依赖的独立测试 handoff `published-btc-cohort-independent-clock-middleware-20261004-6ff5aec49` 已存在并已验证。
- 独立 sparse worktree：`agent/integrator/btc-cohort-entry-recovery-closeout-20261004`；初始相关路径 clean。合入 source 时仅 `tests/integrations/test_btc_cohort_entry_independent_acceptance.py` 出现 add/add 冲突，保留 producer 的四项独立检查并追加本次累计快照正例；未覆盖生产文件或他人未提交改动。

## 阻断项

1. **恢复 data version 与原运行身份不一致。** `quant_crypto/application/btc_registered_cohort.py:320` 的初始 runtime 使用 `digest({"donchian": don_digest, "qlib": qlib_digest})`，而 `backend/app/services/candidate_offline_service.py:523-527` 的 projection recovery 使用 `digest({"members": [input_digest, ...]})`。同一输入示例的两个摘要分别为 `f1dcc345...` 与 `53dd6b55...`，明确不相等；真实已有 `offline_replay_identity.json` 会以 `offline_replay_identity_mismatch:data_version` 拒绝恢复。
2. **累计账本快照被误判为多笔经济权威。** `quant_crypto/application/btc_registered_cohort.py:675-693` 只要累计 `order_ledger.orders` 含相同 client order ID 就收集事件并要求候选数为 1；`repair_committed` 在 `:808-812` 再次做相同判断。后续纯核账 UOW 会保留旧 order/fill，导致唯一真实成交转移被判 ambiguous。独立正例稳定复现 `cohort_committed_ledger_authority_missing_or_ambiguous`。
3. **不兼容准入未在管理入口同步阻断。** 真实 pair 的执行政策在 `quant_crypto/application/btc_registered_cohort.py:175-181` 已知不兼容，但只在 runtime 构造 `:279` 校验。`backend/app/services/candidate_offline_service.py:300-323` 的 `_start_cohort` 仍先持久化 queued job，随后 dispatch；proposal/review 也可由直接 API caller 写入不可能执行的 binding。能力虽然公开 false，后端管理合同仍不满足“proposal/start 禁用且不创建作业”的 fail-closed 口径。
4. **已有 binding 可绕过前端不兼容禁用。** `frontend/src/workspaces/research/RegisteredCandidateRunControls.tsx:113-118,174` 只把 execution/protection compatibility 纳入新 proposal 的 `eligible`；已有 proposed binding 的 review 按钮 `:177-178` 和 approved binding 的 start 按钮 `:179` 没有这些条件。页面文字说 proposal/start 禁用，但管理 UI 仍可触发 review/start。

## 验证结果与证据边界

- 独立固定 source 验收：`py -3 -m pytest tests/integrations/test_btc_cohort_entry_independent_acceptance.py -q --tb=short` -> **1 failed, 4 passed in 25.54s**。失败仅为本次新增的累计 ledger 正例；通过项覆盖确定性成员对象、allocation plan 拒绝、完整共同 clock、真实 `create_app` research-readonly middleware。
- data-version failure-first 计算：初始 adapter-keyed digest `f1dcc345f24c2a110a7683471e5b9ca2830785f522d6ec50a22dd9a191d8787e`，恢复 members-list digest `53dd6b55a5d4e4fa605e1469c60639113dd474c2f258e3d3270ec53ddd6d0573`，`equal=False`。
- 最终 source scoped `git diff --check` -> **失败**：`docs/architecture/btc-cohort-entry-recovery-closeout-20261004.md:3-4` 两处 Markdown 硬换行 trailing whitespace；这是格式缺陷，不是执行缺陷，也不能继续声称最终全 diff-check 通过。
- producer handoff 的提交态边界证据：cohort recovery/independent 9 节点 `9 passed, 1 warning in 30.24s`；proposal/review/start 3 节点 `3 passed, 1 warning in 38.21s`；SSR `5 passed`；TypeScript compiler API `no diagnostics`。这些证明所列 seam、合同和静态渲染，不覆盖上述四项缺口，不是正式浏览器或真实经济恢复证据。
- 旧五个生命周期节点曾在同一验收工作树发生 HEAD 漂移，结果 `3 passed, 2 failed in 1191.33s`，两项失败均为 `deployment_changed_restart_required`。该轮只作身份漂移诊断，不计最终版本 pass 或业务 fail。
- 最终固定版本的五个长生命周期节点未运行：四项确定性验收缺口已足以拒绝，且真实 pair 在经济动作前结构性阻断；不再消耗 600 秒等待预算伪造完成度。
- 正式 main 页面、真实浏览器、backend restart、部署、真实 LightGBM fit/candidate 均未运行。R2/R3 没有 final/positive calibration，独立有效样本仍小于 30 且无确定达到日期；fixture 不是真实候选。

## 修改与产物边界

- 独立测试：`tests/integrations/test_btc_cohort_entry_independent_acceptance.py`，新增累计 ledger UOW 正例；未修改 OMS、ledger、strategy、risk、执行政策或 producer 生产实现。
- 独立报告：本文件。
- 无新 runtime artifact、manifest、经济 ledger、replay、数据或模型产物；所有 producer 路径仅作为已提交 source 审查。
- 未访问 network、secret、private/broker/order/live endpoint，未提交真实订单，未启动服务，未 push、未合 main、未发布。

## 后续最小路线（需新授权，不自动续票）

若用户另行授权同一缺陷修复，最小范围是：恢复端复用原 adapter-keyed data version；按 ledger 的真实 transition/delta/allocation/order/fill 识别原 UOW 而非扫描累计快照；在 proposal/start 后端准入和既有 binding 的 UI review/start 同步阻断当前不兼容 pair；补这两项 failure-first 回归后才重跑固定 HEAD 的五个长生命周期节点。不得改原 Donchian/Qlib 时钟、成本、保护参数/hash，不得新造 matcher、OMS 或账本。

## 治理与安全状态

- playbooks：`AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`.codex/agents/integrator.toml`、`docs/agent_playbooks/delivery_risk_policy.json`，以及 preflight/evidence/handoff skills。
- active pitfalls：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`；catalog SHA-256：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- gate：`blocks_gate`；`promotion_eligible=false`。
- 保持 false：`offline_commands_enabled`（research_readonly）、`candidate_management`、`Demo`、`formal_paper_runtime_started`、`private_endpoint_allowed`、`order_endpoint_allowed`、`live_order_allowed`、`real_money_order_allowed`、`transfer_allowed`、`withdraw_allowed`、`permission_upgrade_allowed`、`promotion_unlock_allowed`、`paper_or_live_unlock_allowed`、`real_order_submitted`。
