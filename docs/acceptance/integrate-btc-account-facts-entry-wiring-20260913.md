# INTEGRATE-BTC-ACCOUNT-FACTS-ENTRY-WIRING-20260913 独立验收

## 身份与边界

- role：`integrator`
- change risk：`demo_execution_semantics`
- main base：`13fa72af3e3f7ee7912421118d9ca66b4160a51e`
- producer deliverable：`528f792b997252b21bfb7c28a026abc17df2ed2e`
- producer amendment：`79da72da750076f0b92196b233f3185b85d385e0`
- validated handoff：`published-btc-account-facts-entry-wiring-20260913-528f792b9`
- validated superseding handoff：`published-btc-account-facts-entry-wiring-20260913-provenance-amendment-79da72da7`
- readiness 上限：`quality_checked`。本报告与随后 integrated handoff 记录独立审定；不代表已合入注册主工作树，不授权服务启动、真实账户读取、Demo、paper、order、live 或 promotion。

## 审定 touch set

上游十项交付：

- `quant_crypto/oms/account_risk_facts.py`
- `quant_crypto/oms/okx_demo_paper_runtime.py`
- `backend/app/core/config.py`
- `backend/app/services/btc_demo_runtime.py`
- `scripts/register_btc_account_facts_baseline.py`
- `tests/contracts/test_btc_account_facts_entry_wiring.py`
- `tests/contracts/test_btc_account_facts_closeout.py`
- `backend/tests/test_btc_demo_runtime_service.py`
- `docs/operations/btc-account-facts-entry-wiring.md`
- `docs/acceptance/btc-account-facts-entry-wiring-20260913.md`

集成代理仅新增／更新：

- `tests/contracts/test_m1_btc_behavior_freeze.py`：在完整独立审查后更新已审定 post-M1 精确 blob 清单；默认 BTC candidate、参数哈希和 observer 不改变执行行为的断言原封不动。
- `docs/acceptance/integrate-btc-account-facts-entry-wiring-20260913.md`：本独立验收。
- `.agent/handoffs/BTC-ACCOUNT-FACTS-ENTRY-WIRING-20260913/*.json` 与 `.agent/handoffs/INTEGRATE-BTC-ACCOUNT-FACTS-ENTRY-WIRING-20260913/*.json`：已验证的上游发布事件和本次 append-only integrated 事件。

未触碰 frontend、策略默认参数、订单构造、保护单经济语义、权限合同、secret、runtime artifact、真实 ledger 或任何 private/order/live endpoint。

## 独立审查结论

1. 外部批准只从服务端配置的仓库外 registry resolver 读取；调用参数不能携带 `approved`、authority、receipt 或 complete 自授。批准记录绑定账户哈希、账户范围、USDT、source HEAD、runtime identity、封存 snapshot、观察／复核时间、权益、全账户空仓审定和显式 `usdt|ratio` 回撤阈值。
2. baseline 登记复用既有进程 writer lock、hash-chain event 和 checkpoint；要求 runtime 停止、账户空仓、无普通挂单／算法单／未完成 intent。相同批准及快照幂等，替换 baseline／重置高水位拒绝；登记不清 latch、不启动 worker、不改变交易权限。
3. account bills collector 不使用 instrument/type/currency 过滤，按 `begin/end/limit=100` 与 `after` 完整走到短页；重复 ID、cursor/窗口不符、缺 terminal page、未知类型、缺时间、非 USDT 与任何 transfer（包括净额抵消）均 fail-closed。digest 只做字段完整性，不被描述为来源授权；provenance 来自服务端固定 provider 和 runtime snapshot/账户/覆盖窗口绑定。
4. 经济回放按 `baseline_observed_at_utc < event_time <= final_observed_at_utc` 过滤 fill/funding，保留原始 snapshot、hash 和 UOW；基线前费用／资金费不重复计入。缺失或未来经济时间拒绝，重试和恢复继续使用同一 idempotency/hash-chain 语义。
5. backend 默认 registry/approval/runtime identity 为空，readonly import/status 不解析 registry。只有完整配置才注入审定 threshold/unit；默认 Guardian unit 保持 `unknown`。没有新增 HTTP body 审批、操作 API 或交易开关。
6. 独立审查退回并接收一次限定 amendment：操作说明现已明确 provider 只接 `OkxDemoPaperRuntimeController._collect_exchange_snapshot`，既有独立 private-readonly observer 未改、不能生成全账户审定材料或写生产账本；测试名不再夸大 unkeyed digest 的证明力。amendment 无业务代码变更。

未发现需要扩大本票或放宽 fail-closed 的确定性缺陷。

## 验证结果

环境均设置 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`。

- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/contracts/test_btc_account_facts_entry_wiring.py tests/contracts/test_btc_account_facts_closeout.py tests/contracts/test_btc_demo_private_readonly_observation.py backend/tests/test_btc_demo_runtime_service.py backend/tests/test_btc_runtime_artifact_wiring.py backend/tests/test_btc_demo_runtime_api.py`：`139 passed`。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/contracts/test_m1_btc_behavior_freeze.py tests/contracts/test_btc_okx_demo_runtime_hardening.py tests/contracts/test_btc_shared_platform_v3_guardian_latch.py tests/contracts/test_btc_demo_guardian_operator_recovery.py`：`61 passed / 4 failed`。M1 exact-blob 项已通过；四项失败均位于既有 `test_btc_demo_guardian_operator_recovery.py` fixture，fixture 未提供审定 drawdown unit/account fact，当前 Guardian 正确返回 `max_drawdown_unit_unknown` / `drawdown_unknown`。它们在 base 已存在，本票未放宽 Guardian 使其变绿。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_btc_demo_runtime_service.py backend/tests/test_btc_private_readonly_observation_projection.py backend/tests/test_backend_research_readonly.py tests/agent_governance/test_private_readonly_permission.py`：`118 passed / 1 failed`。唯一失败 `test_cold_readonly_app_creation_avoids_runtime_and_external_side_effects` 在 planner sparse worktree 中把 `Path.open` 全局禁用后，Git worktree 的 `.git` 指针文件无法读取；这是该旧测试对注册主工作树 `.git` 目录的环境假设，不是本票新增 registry/private 副作用。未修改测试绕过。
- `py -3 -B -X utf8 -m py_compile ...`（九个本票 Python 路径及 M1 freeze test）：通过。
- `py -3 -B -X utf8 scripts/register_btc_account_facts_baseline.py --help`：通过；仅解析参数，未登记数据。
- `git diff --check 13fa72af... --`：通过。
- `ruff` 未安装，未运行；未以其他工具伪装替代。

未运行真实账户登记正例、private/network/order/live 调用、服务启动、当前 main 页面验收、runtime/promotion artifact 构建。这些均超出本轮“离线工程验收”授权。

## 治理与状态

- 读取：`AGENTS.md`、知识库 README、non-negotiables、shared pitfalls、integrator TOML、cross-agent coordination、risk budget、order lifecycle、audit trail，以及 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff` skills。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 未读取原始历史踩坑日志。
- 初始限定 dirty：全部 clean；无文件所有权冲突、无冲突解决、无其他代理未合并文件被消费。结束限定 dirty 以提交后 `safe_status` 为准。
- 未生成 artifact/manifest/replay 包，未读写真实账户 ledger。现有 current-main BTC read model/promotion artifact freshness 不因本集成改变，也未被本报告宣称为 fresh。

## Gate 裁决

本票可作为 `quality_checked` 的已审定、待发布源码交付。真实 registry、人工批准、全账户封存 snapshot、完整 account bills 页和 baseline 登记均不存在；真实账户闭环仍未验收。`promotion=false`、`paper_or_live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`，并保持 `promotion_unlock_allowed=false`、`paper_or_live_unlock_allowed=false`、`private_endpoint_allowed=false`、`order_endpoint_allowed=false`、`real_order_submitted=false`。M3/M4 不启动。
