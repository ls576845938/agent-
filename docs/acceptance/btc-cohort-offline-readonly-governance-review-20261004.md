# BTC cohort 限定只读治理独立审查

本记录由独立 integrator 根据 root 的实际审查结论封存。当前 root 治理审查身份为 `/root`，上下文为
`/root/cohort-governance-review-20261004-780f8c23c`；本文件不构成 integrator 自批。初版治理审查历史由
Git 父提交保留，当前 marker 绑定包含只读 UI overlay 封印的最终治理对象。

## 审查结论

- 精确最终治理 deliverable：`780f8c23c9565d766defe2f100269eaacdc2ec62`。
- root 已完整读取初版到最终治理 JSON、validator、全部回归源码、说明和 producer 报告的实质差异。
- 最终 published handoff `ba564fb8a519a0cdbae39d6e49839aeeb169408b` 已验证有效；Git raw SHA256 为
  `267d2c853ef4763a840bb67911fce28022830ef526aaa19682d6818083915912`。
- base 到治理 deliverable 仅新增合同固定的五个治理路径；`git diff --check` 通过；未修改业务、
  launcher、风险、OMS、ledger、安全或权限合同。
- 批准范围仅为已审 source 的 `research_readonly` 源码集成与只读展示；不是实际共同经济执行、模型有效性、
  promotion、Demo、paper、live、private、order 或账户权限批准。
- 本次后继记录位于 frontend identity 刷新提交 `fad8eb1db41c3fafb40e9213d12a0fd435530699`
  之后，仅修正证据提交顺序绑定；root 对治理对象的审查结论和全部阻断保持不变。

## 独立复验

- 最终治理 producer 的 source CLI 为 `valid`、`errors=[]`、`readiness_ceiling=quality_checked`、
  `gate_impact=blocks_gate`、`permissions_granted=false`；71 节完整治理回归为 `71 passed in 245.64s`。
- `py -3 -m pytest -q -p no:cacheprovider tests/agent_governance/test_btc_cohort_offline_readonly_delivery_20261004.py`：
  初版治理独立复验为 `71 passed in 102.89s`；最终 overlay 未重复整套无变化矩阵，另做提交态 source/overlay
  seal、精确 delta 与证据引用核验。
- 已审业务冻结长测沿用 source 独审的提交态证据：5 passed / 3 warnings / 1208.16s；本治理阶段没有重跑，
  也没有把 seam fixture 或原单策略生命周期测试称为真实共同成交恢复通过。

## 保持阻断

真实 Donchian 与 Qlib 的执行时钟/方向成本及完整保护策略 hash 仍不兼容；真实共同非零订单、成交、
保护归属与经济恢复仍未运行；合格真实 Qlib final/positive calibration 缺失且独立有效样本不足 30。
所有管理、离线 worker、账户、Demo、promotion、paper、live、private、order 与执行权限继续关闭。

<!-- btc-cohort-offline-readonly-evidence
{
  "schema_version": "btc_cohort_offline_readonly_evidence_v1",
  "kind": "governance_review",
  "ticket_id": "BTC-COHORT-OFFLINE-READONLY-DELIVERY-20261004",
  "outcome": "approved_limited_readonly",
  "source_commit": "af7d1ba3222bc60fa44032ee70f63b8615248d45",
  "deployment_profile": "research_readonly",
  "readiness_ceiling": "quality_checked",
  "gate_impact": "blocks_gate",
  "limitations": [
    "current_Donchian_t_plus_1_and_Qlib_t_plus_2_directional_cost_execution_incompatible",
    "original_Donchian_100_200bps_and_Qlib_400_800bps_protection_policy_hashes_incompatible",
    "real_common_nonzero_orders_fills_protection_attribution_and_economic_recovery_not_run_blocked",
    "eligible_real_Qlib_final_positive_calibration_missing_independent_effective_sample_below_30",
    "seam_mock_compatible_tests_are_engineering_only_not_real_candidates_or_promotion_evidence",
    "ordinary_closed_missing_artifact_and_not_configured_are_truthful_readonly_states",
    "Demo_promotion_paper_live_private_order_and_execution_gates_remain_blocked"
  ],
  "safety_flags": {
    "candidate_management": false,
    "management_write": false,
    "offline_worker": false,
    "offline_enabled": false,
    "account": false,
    "demo": false,
    "demo_control_enabled": false,
    "promotion": false,
    "paper": false,
    "live": false,
    "private": false,
    "order": false,
    "real_order": false,
    "transfer": false,
    "withdraw": false,
    "execution_permission": false,
    "runtime_observed": false,
    "runtime_worker_enabled": false,
    "offline_commands_enabled": false,
    "offline_start_allowed": false,
    "start_allowed": false
  },
  "actor_id": "/root",
  "context_id": "/root/cohort-governance-review-20261004-780f8c23c",
  "actor_role": "root_reviewer",
  "reviewed_commit": "780f8c23c9565d766defe2f100269eaacdc2ec62",
  "identity_refresh_commit": "fad8eb1db41c3fafb40e9213d12a0fd435530699"
}
-->

## 只读 public capability 接线补充审查

root 以 `/root/cohort-ui-public-read-review-20261004-2eb5e975f` 实际审查提交
`2eb5e975f69a200bd200cf200a75dcc35f01a36f` 的完整两文件差异、published handoff、Git raw SHA 与
diff-check。补丁只让只读卡片复用现有 `offlineRequest` 发出带非秘密 intent 的 public capability GET；
health 路径、20 秒截止、caller abort、body 解析期限、proxy guard、auth、权限和业务算法均未改变。

独立 integrator 的最小回归为 SSR/static 1 passed in 2.09s，以及真实 candidate local guard/harness
7 passed / 0 failed / 3267.6241ms。批准仍只限 `research_readonly` 展示；真实 pair 兼容性、final 模型、
共同非零经济动作和恢复保持 blocked/not_run。

<!-- btc-cohort-offline-readonly-ui-review
{
  "schema_version": "btc_cohort_offline_readonly_evidence_v1",
  "kind": "readonly_ui_fix_review",
  "ticket_id": "BTC-COHORT-OFFLINE-READONLY-DELIVERY-20261004",
  "actor_id": "/root",
  "actor_role": "root_reviewer",
  "context_id": "/root/cohort-ui-public-read-review-20261004-2eb5e975f",
  "reviewed_commit": "2eb5e975f69a200bd200cf200a75dcc35f01a36f",
  "source_commit": "af7d1ba3222bc60fa44032ee70f63b8615248d45",
  "outcome": "approved_limited_readonly",
  "deployment_profile": "research_readonly",
  "readiness_ceiling": "quality_checked",
  "gate_impact": "blocks_gate",
  "limitations": [
    "current_Donchian_t_plus_1_and_Qlib_t_plus_2_directional_cost_execution_incompatible",
    "original_Donchian_100_200bps_and_Qlib_400_800bps_protection_policy_hashes_incompatible",
    "real_common_nonzero_orders_fills_protection_attribution_and_economic_recovery_not_run_blocked",
    "eligible_real_Qlib_final_positive_calibration_missing_independent_effective_sample_below_30",
    "seam_mock_compatible_tests_are_engineering_only_not_real_candidates_or_promotion_evidence",
    "ordinary_closed_missing_artifact_and_not_configured_are_truthful_readonly_states",
    "Demo_promotion_paper_live_private_order_and_execution_gates_remain_blocked"
  ],
  "safety_flags": {
    "candidate_management": false,
    "management_write": false,
    "offline_worker": false,
    "offline_enabled": false,
    "account": false,
    "demo": false,
    "demo_control_enabled": false,
    "promotion": false,
    "paper": false,
    "live": false,
    "private": false,
    "order": false,
    "real_order": false,
    "transfer": false,
    "withdraw": false,
    "execution_permission": false,
    "runtime_observed": false,
    "runtime_worker_enabled": false,
    "offline_commands_enabled": false,
    "offline_start_allowed": false,
    "start_allowed": false
  }
}
-->
