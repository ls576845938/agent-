# BTC 统一离线候选一次性只读交付治理 producer（2026-10-04）

本票治理候选已通过限定失败优先回归，readiness 为 `quality_checked`。producer 没有批准自己的 source_review、集成或正式部署，没有合入 main、push、启动服务、运行新研究或访问交易账户。后续需要新的独立治理审查上下文和新的独立 source integrator；这份 producer 报告没有独审批准 evidence marker。

## 责任与提交边界

- ticket：`BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004`。
- role：`super_developer`；producer actor：`btc_unified_readonly_governance_producer_20261004`。
- change_risk：本票 `governance_control`；被封存原源码仍为 `demo_execution_semantics`。
- base/main：`eaa88400f01e47e5c8da377606b6df52a9543382`。
- branch：`agent/super_developer/btc-unified-offline-readonly-delivery-20261004`。
- planner worktree：`D:\vibe coding\Obsidian\量化系统\worktrees\super_developer-btc-unified-offline-readonly-delivery-20261004`；sparse=true；LFS skip-smudge。
- deliverable 与最终 HEAD 由后续 append-only handoff 和 Git 提交身份精确给出，报告不自引用其尚未生成的 commit。
- 初始声明 touch set 与 main/本票工作树限定 dirty 均为 0；无重叠冲突、无覆盖/清理他人修改。其他代理未合并交付未被消费为未提交文件，也未在本票集成。

5 个 deliverable 文件：

1. `docs/agent_playbooks/btc_unified_offline_readonly_delivery_20261004.json`：一次性精确来源、33 文件 mode/blob/SHA、6 个已审 handoff 和依赖闭包、路径/阶段/旗标合同。
2. 同名 `.md`：调用、独审与发布 evidence 格式、限制、前端派生及避免提交自引用的操作说明。
3. `tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py`：只读 Git/evidence 校验；复用现有 `handoff.py` 与 `frontend-identity-lib.mjs`，不写收据、不访问网络或运行研究。
4. `tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py`：69 个失败优先与精确来源/派生正例。
5. 本 producer 报告。

append-only handoff 仅在本票精确目录发布：
`.agent/handoffs/BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004/`。

未修改：业务、通用 delivery_risk_policy、旧只读特例、launcher、auth、hooks、共享 schema/枚举、权限或服务。source 后允许的精确报告和 handoff 目录已按主会话审定规格冻结；没有任意 docs/.agent 白名单。

## 来源与证据复用

- assembly：`815a18fe8541ed0b4a61416bba23df480d8418eb`。
- 被独审 deliverable：`58b37ac726cfd0d5276356782e7868c873f1aab1`。
- 原 integrated envelope commit：`ba9f28bd6272bbcae62c6bb5c0e5f9ce55633a29`。
- 原独审报告：`docs/acceptance/btc-unified-entry-coordination-independent-review-20261004.md`；raw SHA-256 `b9a053dc62e851e732a646b7005a79563d4850fcb5a880b0d9d4a89f9fcc9a7e`。
- 原 integrated envelope raw SHA-256：`6e95c798e6381496560b92ffa731d8d66feb3ac7278e55aefbb281860b2bec91`。
- 33 个封存文件从提交态 Git 核验，6 个精确 envelope 的 `validate_handoff_against_git errors=[]`。58b → ba9 只增加该原 envelope；原 producer handoff 用确切 Git 对象验证，不搬入 main。
- 合同 canonical SHA-256：`15a23d317265f4f0bc3235983152a3a5f81755e09cd2565641f14235762ac695`；raw Git 文件 SHA 由本票 handoff 提供。

原独审记录的协调 22、默认 runtime/proof 2、registered Donchian 2、Qlib primary 1、前端静态与 tsc 均按原报告封存复用，本票没有重新跑这些无变业务用例，也没有把它们写为本票新增通过。source_review 通过不等于页面通过。

共同账户协调仅 application interface，没有共同账户页面或 HTTP 多策略流程。Qlib 测试成员身份/合成 fixture 不是真实有效模型；R2/R3 model/calibration、真实候选组合为零和未启动新研究等限制不变。未配置 catalog/管理目录应如实显示 not_configured；合法 missing/blocked 可保留。实际读取失败必须记录并阻断正式部署验收，不造产物或扩大代码范围修好页面。

## 测试

最终执行：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py --basetemp "$env:TEMP/btc-unified-offline-readonly-governance-20261004-second"
```

结果：`69 passed in 168.86s`。正例使用原封存真实 Git 对象与 OS TEMP 独立 bare Git metadata fixture；不是页面、研究或部署 evidence。失败分支定向隔离原源码核验，完整真实来源已单独复验，没有跳过正式来源校验。

覆盖：未知 source/ticket/profile、缺错 report/handoff、精确 commit/报告 SHA 绑定、自批与不同独立上下文、源码/sidecar 漂移、额外 business/protected/宽泛元数据路径、任意非 literal false 或缺失安全字段、listener/current main identity/browser/freshness、mock 部署、实际读取失败、非法 identity 派生；现有派生算法允许正确祖先 baseline 加 metadata 后继。

初次回归 `43 passed / 8 failed in 90.93s`：fixture 的 integrated envelope 缺少现有平台必需 transition_for，已按原 validator 修正 fixture，未修改 validator 平台或预期。中途一次定向来源正例与合同增补交叠而返回 fixed_contract_changed，未作为最终证据；最终冻结态 69 项通过。

真实 CLI：

```powershell
py -3 tools/agent_governance/btc_unified_offline_readonly_delivery_20261004.py --verify-source
```

封存源校验已运行，`status=valid/errors=[]/permissions_granted=false`。交付前对 staged touch set 执行 `git diff --cached --check -- <五个精确路径>`，结果由提交前验证确认。

未运行：无变业务完整矩阵、研究/训练、真实离线 worker 或交易产物生成、backend lifecycle、main 浏览器/HTTP 流程、promotion artifact 重建、正式 source_review/deployment_acceptance 审批收据。最后两项由独立治理 reviewer/source integrator 和主会话正式发布验收负责。

## 治理和 freshness

已读取：quant-agent-preflight、quant-agent-handoff、AGENTS、knowledge README/non-negotiables、shared/super_developer playbooks 与 TOML、delivery risk policy；已读 Hook Team Context。依赖只消费已提交并验签 Git 对象，未读取其他 worktree dirty。未全文加载原始事故日志。

context_packet：`--role super_developer --scope shared --scope btc --change-risk governance_control --format markdown`。

命中 IDs：`BACKTEST-COST-001`、`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`REPLAY-ISOLATION-001`、`RESEARCH-HOLDOUT-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

本票没有 artifact publication、data manifest、真实 ledger 或新的 gate/read-model。测试仅使用 OS TEMP fixture。治理提交是 base eaa 上的独立候选，不是 current-main 部署 evidence。source_review/deployment_acceptance 分阶段校验；部署 records 必须绑定实际 main HEAD、8765/3000 real listener/identity、900 秒内真实 browser 和 rollback ref，不能复用旧 eaa 页面为新版本验收。

独审 report.reviewed_commit 绑定实际治理 deliverable，独审 report 在后继 commit，由其 handoff 精确绑定路径/SHA；source integrator 必须新上下文和不同 actor/context。部署报告在独立证据提交中绑定实际部署 HEAD，验收报告 commit 不改变已部署 main。若 main 后续推进，旧 runtime/receipt 必须拒绝并重启复验；不要求 frontend manifest.baseline_commit 等于 metadata 后继 HEAD。

## 仍阻断与下一步

独立治理 reviewer 负责审核本票 committed deliverable 并发布精确 review 报告及 validated handoff；新的 source integrator 之后组合原 ba9 package 与本票治理提交并发布 integration 报告/handoff。主会话最后验证正式 readonly 发布和 rollback；producer 不执行这些步骤。

以下始终显式 false：candidate_management、management_write、offline_worker、demo、demo_control_enabled、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、runtime_worker_enabled。既有 production/promotion/模型/研究 gate 仍 blocked/fail-closed。没有控制写入、新运行、private/order/live、真实订单、转账、withdraw 或 secret 访问权限。


## CORRECTION-01：兼容既有 backend 身份返回形状

本节为原 2920 producer 记录的追加修正；上文原测试与阶段结论属于原交付，不冒充此次修正验收。原批准 commit/report/handoff 历史不改写。此修正仍是原票 `BTC-UNIFIED-OFFLINE-READONLY-DELIVERY-20261004`，producer actor 不变，风险仍 `governance_control`。

正式 readonly 发布时，主会话确定复现了本 sidecar 的兼容缺陷：既有 `backend_current_main_identity_v1` 正常返回 canonical、HEAD、branch/port、profile/read_only/controls_disabled 及 false 权限字段，刻意不返回 physical worktree/repo_root。原 `_deployment_records` 却把 path 当作 backend 必需字段，拒绝正常 canonical backend。生产 identity 的形状从封存 source 58b 的 `scripts/start_backend_current_main.py` 逐项核对；本修正没有修改该生产文件或增加路径暴露。

修正行为：

- backend 保留原始 schema/canonical/nonstale、source_head/main_head、canonical branch/port、research_readonly/read_only/controls_disabled 和 false 权限检查，使用独立 listener 的注册 main 归属证明；原始 identity 无 path 合法，校验器不补造字段。
- backend 若提供 worktree 或 repo_root，每个实际提供的路径必须是非空绝对路径且匹配注册 main；一项正确不能掩盖另一项错误。空路径不再被当作当前目录。
- frontend identity 仍须显式精确 worktree，不能用 repo_root 或 listener 证明替代。
- mock/fixture、listener、current HEAD、browser、freshness、rollback、source/report/handoff 和所有 false 旗标约束均保留。

本次专属工作树由 planner 从固定 eaa 创建：
`D:\vibe coding\Obsidian\量化系统\worktrees\super_developer-btc-unified-offline-readonly-backend-shape-c01`，
branch `agent/super_developer/btc-unified-offline-readonly-backend-shape-c01`，sparse=true。
只消费已提交 `2920ca044772f561d21b9550cfb9afbeaffbd672` 的五文件 deliverable，并先验证其原 published envelope `errors=[]`；未把旧 `85fb02c3fe8232180222961ef7e3f59cd6dca95b` envelope 引入治理 deliverable。
初始相关 dirty=0、无冲突；eaa → 修正治理 deliverable 仍只能是原五个路径。此次相对 2920 只修改 validator、对应测试、README 最小说明和本报告追加节，JSON 合同逐字不变，source 58b、33 对象、6 个依赖、producer actor、readiness 和 flags 全部不变。

原 mock 部署测试曾把注册 main 永久假设为 eaa。本次测试只把“无副作用”断言改为运行前后实际 refs/heads/main 相同；没有修改生产 base/source 身份规则。治理 fixture 仍在 OS TEMP 的独立 bare repository，不运行实际服务或交易。

失败优先：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py -k existing_backend_identity_without_paths_is_accepted --basetemp "$env:TEMP/btc-unified-offline-readonly-backend-shape-c01-failure-first"
```

旧校验器结果 `1 failed, 79 deselected in 1.64s`，精确错误 `backend_identity_main_binding_invalid`。
首次修正定向回归另有 `13 passed / 1 failed in 1.17s`，发现显式空路径通过 cwd 解析，被本 sidecar 的绝对路径规则关闭；没有放宽预期。

最终定向回归：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py -k 'existing_backend_identity_without_paths or backend_optional_identity_path or backend_mismatching_second_path or pathless_backend_identity or frontend_requires_worktree' --basetemp "$env:TEMP/btc-unified-offline-readonly-backend-shape-c01-targeted-final"
```

`15 passed, 69 deselected in 0.67s`：既有无路径形状正例、提供正确路径正例及不补造字段断言；错误/空/相对/混合路径、错误 HEAD/profile/read_only/controls/权限、错误 listener 归属、缺 frontend worktree 均拒绝。

最终治理全套：

```powershell
py -3 -m pytest -q tests/agent_governance/test_btc_unified_offline_readonly_delivery_20261004.py --basetemp "$env:TEMP/btc-unified-offline-readonly-backend-shape-c01-final"
```

`84 passed in 161.57s`。完整封存实际 Git source/33 文件/6 envelope 及 source_review fixture 正例仍通过；既有 unsafe flags、source/business 漂移、report/handoff、自批、browser、mock 部署、读取失败和派生 identity 回归均保持通过。该记录解析正例不是正式部署批准。

未运行：无变业务矩阵、服务启动/重启、正式 endpoint/browser 再验收、研究/worker/模型训练、promotion artifact。主会话在 preflight 已把正式 main 推进到 `837246619a6e79c0d4481da61950cae2fa6bab2c`；本 producer 只读核验该 Git 身份，未操作其服务或主工作树，不把主会话的 listener 记录包装成本票正式部署 evidence。

playbooks/pitfall IDs 与 catalog hash 同上，当前 context_packet 为 super_developer/btc/shared/governance_control，治理要求独立 integrator、promotion rebuild=false、backend restart=false。旧 Team Context 的 20 个 invalid handoff 保持可见，本票只接受已精确验证的自身 upstream，不修复或放行无关交付。

新 deliverable 与新的 append-only corrected published handoff 由实际 Git commit 给出，supersedes 原 published-2920 事件但不改写旧文件。后续必须针对新治理 commit/reportSHA 再独立审查，重新 source integration 并由主会话验证实际 current-main readonly 部署。全部 16 个 false 旗标以及模型/研究/交易 blocked/fail-closed 状态保持原值，没有授权控制写入、新运行、private/order/live、订单、转账、withdraw 或 secret 访问。
