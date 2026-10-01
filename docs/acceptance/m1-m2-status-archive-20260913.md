# M1 / M2 状态归档 Producer 验收

- 票据：`M1-M2-STATUS-ARCHIVE-20260913`
- 角色：`super_developer`
- change risk：`research_readonly_release`
- base / rollback point：`b02836ce1415693471c0bc263a164160b27736d9`
- readiness ceiling：`quality_checked`
- gate impact：`evidence_only`

## 结论与边界

本票只归档已有 M1/M2 证据并修正 `/architecture` 中的过期阶段文案：M1 已完成限定工程结项；M2 已完成 8/8 历史探索对照，本版增量不稳定且不晋级；M3—M4 未启动。页面与文档显式区分已实现、已测试、已运行验证和可交易。

历史源码阅读 catalog 仍绑定原 `source_commit`；仅用 4 处“历史快照／当时”提示防止将旧判断当成当前里程碑，未重建 catalog，未改写逐文件 EOF 覆盖。M2 报告保留实际计算 HEAD、后续 review commit、原 manifest/result hash 和历史 as-of，不冒充当前 HEAD 运行证据。

本票没有重训、重算或搜索模型，没有修改信号、仓位、退出、风险、OMS、保护单、账本、broker/private transport、运行产物或任何权限；未启停服务。

## 证据消费

- M1：主分支 `docs/operations/m1-closeout-m2-validation-integration-20260912.md`，历史独立验收为 Python `205/205`、前端定向 `27/27`。本票未重跑这些 M1 业务矩阵。
- M2：先验证 final corrected/superseding handoff `superseded-result-digest-review-9263c4bc9`，结果 `status=valid`。原 report commit `9263c4bc9f8d22c66620d2f8906500c63f19e966`，实际计算 HEAD `f8510e3c15dc82642b37dbb33eb58bcdb801ffaa`，handoff 容器 commit `c885f3e0515e967b50afc193754ead2fd47a5c10`。
- M2 外部 manifest 当前 SHA-256：`5270f155ef4871bd619f00fadb1079dee1ca12f347df661dd3e377d796c5f37e`；result SHA-256：`cfab8da27ae4fafb9aaa429246d9aaea492d9a13128496657c1016b9b6134a2d`，与原封存报告一致。本票未改写外部 evidence root。
- 账户门槛：主会话在 base `b02836ce` 跑定向离线矩阵 `50 passed in 6.01s`，没有网络或真实账户调用。这只证明工程合同，不是真实账户运行验收。
- current-main 只读身份：主会话核验 `/__backend_identity` 为 `canonical=true`、`runtime_stale=false`、`controls_disabled=true`；BTC domain read model 为 `current_head`、`blocked`、49 个 safety flag 全为 false。当前 private-readonly receipt 缺失，未运行 runner。

## 真实账户门槛仍未闭合

账户事实模块、持久 UOW 和经济重放已有离线保护，但生产入口尚有三类明确缺口，本票只记录、不修复：

1. `quant_crypto/oms/account_risk_facts.py:164` 的显式基线 builder 尚无正式 CLI/API 调用，测试中的直接注入不能伪装成生产操作。
2. `quant_crypto/oms/okx_demo_paper_runtime.py:9548` 消费 `account_cashflow_evidence`，但同文件 `7065–7156` 的快照采集不生成该字段；private observer 只取最近 100 条 fills/bills，不证明完整账户现金流覆盖。
3. `backend/app/services/btc_demo_runtime.py:878–883` 实例化 `GuardianConfig` 时未传 `max_drawdown_unit`，默认保持 unknown。private observer 的 `snapshot_reconciled` 仅投影 health，没有接入新的 account fact / commit UOW / replay 生产链。

因此 receipt 齐备仍不等于真实账户只读验收完成。这些属于另一个需要明确授权和独立集成的生产接线范围。

## Producer 回归

| 命令 | 结果 |
| --- | --- |
| 修改前 `node --test frontend/scripts/test-architecture-knowledge.mjs frontend/scripts/test-architecture-mindmap.mjs` | failure-first：`7 passed / 3 failed`，三处失败均精确命中旧 M1 planned/paused 状态 |
| 修改后同命令 | `10 passed / 0 failed` |
| `npm.cmd --prefix frontend run lint` | 未完成：专属 sparse worktree 没有本地 `tsc` executable |
| 使用 registered-main 的 `tsc.cmd --noEmit -p frontend/tsconfig.json` | 未完成：worktree 没有对应 `@types/node`，`TS2688` |
| `git diff --check -- <declared paths>` | PASS；只有 Windows LF/CRLF 提示，无 whitespace error |

未运行 E2E：producer 工作树不得启动前端，当前 3000 仍是旧 main 对象。主会话已在正式页面复现旧文案；新断言必须由独立 integrator 合入 main、按 `research_readonly` 重启后运行 canonical browser acceptance。

## Touch set 与治理

实际修改限于 16 个文档／前端只读文案／架构测试文件，另有交付后的 append-only handoff。所有路径初始 `safe_status=clean`；未覆盖或消费他人未提交变更。

已读：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、super developer pitfalls、delivery risk policy、`research_readonly_release`、quant preflight / handoff skills。未全文读取原始事故日志。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`RESEARCH-HOLDOUT-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`、`US-SERVICE-BOUNDARY-001`。

## 待独立集成

生产者不自批。待 integrator 验证提交 ancestry、逐文件 hash、完整 diff、历史 M2 封存证据、交易语义不变和只读能力；然后才能合入 registered main、重启 8765/3000 并完成正式页面验收。回退点为 base `b02836ce1415693471c0bc263a164160b27736d9`，不使用 hard reset。

`demo_control_enabled/promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 全部保持 `false`。
