# BTC 统一离线候选一次性只读交付（2026-10-04）

本 sidecar 只绑定 `BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004`。不修改通用交付政策或旧只读特例；原源码保持 `demo_execution_semantics`，本治理 producer 为 `governance_control`。只读发布 profile 为 `research_readonly`，readiness 上限 `quality_checked`，独立治理审查和新的独立 integrator 均必需。无需为本 sidecar 重建无关 promotion artifact；原 promotion 与交易 gate 保持阻断。

## 固定 Git 来源

- base/main：`eaa88400f01e47e5c8da377606b6df52a9543382`。
- assembly：`815a18fe8541ed0b4a61416bba23df480d8418eb`。
- 原独审 deliverable：`58b37ac726cfd0d5276356782e7868c873f1aab1`。
- 原独审 handoff commit：`ba9f28bd6272bbcae62c6bb5c0e5f9ce55633a29`。
- 精确 33 个非 handoff 文件的 mode/blob/SHA、5 个业务依赖和原独审 envelope 见同名 JSON。校验从 Git 对象读取，不读取其他 worktree 的 dirty 文件。
- 58b → ba9 只增加原 integrated envelope。旧 producer envelopes 从确切 Git commit 验证，无须搬入 main。

复用原独审报告所记录的协调 22、默认 runtime/proof 2、Donchian 2、Qlib 1、前端静态及 tsc 结果。它们不是本治理票新跑的业务矩阵。共同账户协调只覆盖 application 接口；没有共同账户页面/HTTP 用户流程。Qlib 成员身份和合成 fixture 不是有效真实模型。R2/R3 的 model/calibration 限制、真实可比较候选组合为零和未启动研究等限制不变。

## 两个校验阶段

`source_review` 验证原封存源码、治理 producer 提交、独立治理 review 提交及 handoff、新 integrator 报告及 handoff。通过仅表示这次受限源码交付完整，不表示页面、实际模型、研究或运行 gate 通过。

`deployment_acceptance` 还验证实际 main HEAD、注册 main worktree、8765/3000 listener 的真实 PID/进程归属、canonical 且 nonstale 的当前 HEAD 身份、research_readonly health、真实浏览器记录和回滚 ref。`mocked` 与 `fixture` 必须显式为 false。证据时间必须带时区，且不得未来或超过 900 秒。

部署验收报告允许位于独立证据提交中：`report.reviewed_commit` 绑定真实部署 HEAD，报告 commit 是该 HEAD 的后继。报告自身 commit 不应加入已部署 main 后冒充相同 runtime。若 main 之后推进，旧收据将拒绝，必须重启并重新验收。

前端 manifest 的 `baseline_commit` 可以是部署 HEAD 的祖先，因为现有 `identity:refresh` 先从当时 HEAD 计算对象，之后精确报告/handoff 元数据提交可以推进 HEAD。派生校验复用 `frontend-identity-lib.mjs`，要求 baseline 与目标的 frontend 对象和 fingerprint 相同；release、routes、safety 等旧受保护字段保持原值。

## 精确冻结边界

source 冻结后仅允许同名 4 个 sidecar 文件及以下路径：

- `docs/acceptance/btc-unified-offline-readonly-governance-20261004.md`（producer）。
- `docs/acceptance/btc-unified-offline-readonly-governance-review-20261004.md`（独立治理 review）。
- `docs/acceptance/btc-unified-offline-readonly-integration-20261004.md`。
- `docs/acceptance/btc-unified-offline-readonly-deployment-20261004.md`。
- `.agent/handoffs/INTEGRATE-BTC-UNIFIED-ENTRY-COORDINATION-20261004/`。
- `.agent/handoffs/BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004/`。
- `.agent/handoffs/INTEGRATE-BTC-UNIFIED-OFFLINE-READONLY-GOVERNANCE-20261004/`。
- `.agent/handoffs/INTEGRATE-BTC-UNIFIED-OFFLINE-READONLY-20261004/`。
- 现有 `identity:refresh` 派生的 `frontend/public/frontend-identity.json`。

以上 handoff 目录只接受直接子级、正常命名 JSON envelope，且须用现有 handoff validator 验证。没有任意 `docs/` 或 `.agent/` 白名单。任何新增业务路径、旧治理规则、launcher、auth、hook、账户/执行权限或已封存源码改动均拒绝。source 后的 4 个 sidecar 必须与精确 governance producer commit 对象相同。

## 收据与独立报告

导出接口为 `contract()`、`allowed_delta(path)`、`verify_source(repo_root=...)`、`blockers(receipt, repo_root=...)`。校验只读，返回失败原因，不 merge、写收据、启动服务、调用网络或运行研究。

收据固定字段：
`schema_version`、`ticket_id`、`baseline_commit`、`source_commit`、`source_assembly_commit`、`source_handoff_commit`、`source_change_risk`、`deployment_profile`、`readiness_ceiling`、`limitations` 与 JSON 合同逐字匹配。

两个阶段都有 `phase`、`checks`、`safety_flags`、`governance_commit`、`governance_handoff`、`governance_review`、`governance_review_handoff`、`integration`、`integration_handoff`。部署阶段还需要 `deployment_commit`、`deployment`。所有 reference 只能有 `commit/path/sha256` 三字段，引用 Git 中的确切普通文件；未知字段或缺失字段拒绝。checks 精确匹配合同相应阶段列表且都是 literal true。

独立报告中恰好一段以下标记，内部是 JSON，不使用报告自己的 commit 作为被审 commit：

```text
<!-- btc-unified-offline-readonly-evidence
{ ... JSON evidence ... }
-->
```

共同 evidence 字段：
`schema_version=btc_unified_offline_readonly_evidence_v1`、`kind`、`ticket_id`、`outcome=approved`、`deployment_profile=research_readonly`、`readiness_ceiling=quality_checked`、`limitations`（合同原值）、`actor_role`、`actor_id`、`context_id`、`reviewed_commit`。

- governance review：kind 为 `governance_review`，role 为 architect/integrator，actor/context 不得等于 producer；reviewed_commit 精确等于治理 deliverable。独立报告在 producer 的后继提交，且只能增加精确 review 报告/producer handoff 元数据；其新 integrated handoff 必须将该报告路径及 SHA 列为 deliverable。
- source integration：kind 为 `independent_integration`，role 必须 integrator，actor/context 均与 producer 和治理 reviewer 不同；reviewed_commit 等于治理 deliverable，`governance_review_commit` 等于确切独审报告 commit。新 integrated release handoff 绑定实际 integration 报告路径/SHA。
- deployment：kind 为 `deployment_acceptance`，reviewed_commit 等于实际 main 部署 HEAD；还包含 `evidence_origin=canonical_main_live`、`mocked=false`、`fixture=false`、`observed_at_utc`、`backend`、`frontend`、`health`、`browser`、部署 `checks` 和完整 `safety_flags`。

backend/frontend 记录含 identity GET 的 `url`、`http_status=200`、`observed_at_utc`、原始 `identity`、`listener`。listener 必须有 `port`、正整数 `pid`、`process_verified=true`、注册 main 的 `worktree`、实际 `source_head`。health 有 `http_status=200`、当前 `source_head/observed_at_utc`、`profile=research_readonly`、`read_only=true`、`controls_disabled=true`，`paper_allowed/live_allowed/broker_or_order_allowed` 全 false。browser 有 `origin=canonical_browser`、research URL、`source_head`、`mocked/fixture=false`、`observed_at_utc` 和真实截图 SHA-256；`checks` 精确匹配合同的浏览器检查且 literal true，`visible_states` 非空如实记载实际状态，`actual_read_failures` 必须为空，否则正式部署阶段阻断。合法 missing/blocked 或未配置 catalog/管理目录的 `not_configured` 可原样显示；实际读取超时/失败必须具体报告，不能伪造全页面健康。验收只覆盖旧研究/阶段导航、精确/未知运行状态、写按钮 disabled/能力 false、身份及布局兼容，不登记、启动新运行或生成交易产物。

回滚 ref 固定为 `refs/tags/codex/btc-unified-offline-before-readonly-20261004`，必须指向 base。校验器仅检查，不创建或覆盖该 ref。

既有 `backend_current_main_identity_v1` 刻意不暴露 `worktree/repo_root`。backend 使用原始 canonical/nonstale、source_head/main_head、branch/port、research_readonly/read_only/controls_disabled 和 false 权限字段，配合独立真实 listener 的注册 main 归属证明；缺路径合法且不得伪加字段。若 backend 原始 identity 确实包含任一 physical path，则每个提供的值都必须匹配注册 main，否则拒绝。frontend identity 仍必须显式提供精确 `worktree`，不能用 listener 或仅 repo_root 替代。此兼容修正只作用于本 sidecar，不改变生产身份接口、路径保密、运行权限或来源封存。

所有 `candidate_management/management_write/offline_worker/demo/demo_control_enabled/promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed/runtime_worker_enabled` 均须显式 literal false。缺字段不默认 false；quality_checked 或报告不得解锁这些能力。

## 实际调用

仅验证原封存 Git 来源（不构成 source_review 批准）：

```powershell
py -3 tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py --verify-source
```

完整验收读取审查者已保存的收据；下面路径是需替换的输入占位，不是本 producer 已生成的批准收据：

```powershell
py -3 tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py --repo-root . --receipt "<已存在的收据绝对路径>"
```

失败优先治理回归：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py --basetemp "<本票独立OS-TEMP目录>"
```
