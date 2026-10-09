# BTC cohort 限定只读独立集成报告

票据 `INTEGRATE-BTC-COHORT-OFFLINE-READONLY-20261004`；change_risk=`governance_control`。
集成分支 `agent/integrator/btc-cohort-offline-readonly-delivery-20261004` 从已审 source release
`87d3fbf9a16c8f7a3cbe82e45ff9263681c13817` 创建。初次只读发布在 main
`8707bc48f5614571a3874cbdf0caaba46986c8b8` 的真实浏览器验收发现 public capability GET 被本地 proxy
guard 拒绝；失败网络/截图已保留。当前候选精确合入只读 UI overlay `2eb5e975f69a200bd200cf200a75dcc35f01a36f`
及最终治理 `780f8c23c9565d766defe2f100269eaacdc2ec62`，尚未再次合 main 或重启服务。

## 集成边界与验证

- 最终治理 handoff `ba564fb8a519a0cdbae39d6e49839aeeb169408b` raw SHA256：
  `267d2c853ef4763a840bb67911fce28022830ef526aaa19682d6818083915912`；
  envelope 有效，五个 deliverable Git raw SHA 全部匹配。
- base→治理 deliverable 仍只有合同声明的五个治理路径；补充业务 delta 严格为已审 UI/合同测试两对象，
  其余原 16 个 source 对象及旧 8 个 metadata seal 不变。
- root 最终治理审查后继绑定提交：`cb8af7bc2bd5c1d8aee646b30eed1899afd1b419`；对应 integrated handoff
  提交：`8f2b52dabb7c80243fdd66c91dd9047030d4fba0`。旧审查提交与 handoff 继续由 Git 历史保留。
- `py -3 tools/agent_governance/btc_cohort_offline_readonly_delivery_20261004.py --verify-source`：
  `valid`、`errors=[]`、`blocks_gate`、`permissions_granted=false`。
- 最终治理 producer 完整回归 `71 passed in 245.64s`；独立 integrator 没有重复无变化全套，另核 source/overlay
  seal、精确 delta，并运行 UI SSR/static `1 passed in 2.09s` 与真实 proxy guard/harness `7 passed`。
- 原五生命周期长测没有重跑；使用已审冻结证据 5 passed / 3 warnings / 1208.16s。没有把 seam fixture、
  单策略生命周期或治理回归描述为真实共同经济执行/恢复通过。

## 结论

允许形成限定 `research_readonly` 发布候选；frontend identity 已在 `fad8eb1db41c3fafb40e9213d12a0fd435530699`
派生，source-review receipt 尚待对本后继绑定复验；
正式 registered-main 合入、服务重启和真实页面验收仍由 root 后续明确执行。真实共同账户非零经济动作与恢复、
真实 pair 兼容性、合格 Qlib final/positive calibration 均保持 blocked/not_run。所有管理、worker、账户、
Demo、promotion、paper、live、private、order 和 execution 权限保持 literal false。

<!-- btc-cohort-offline-readonly-evidence
{
  "schema_version": "btc_cohort_offline_readonly_evidence_v1",
  "kind": "integration",
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
  "actor_id": "/root/btc_cohort_independent_integration",
  "context_id": "/root/btc_cohort_independent_integration/INTEGRATE-BTC-COHORT-OFFLINE-READONLY-20261004",
  "actor_role": "integrator",
  "reviewed_commit": "780f8c23c9565d766defe2f100269eaacdc2ec62",
  "governance_review_commit": "cb8af7bc2bd5c1d8aee646b30eed1899afd1b419"
}
-->
