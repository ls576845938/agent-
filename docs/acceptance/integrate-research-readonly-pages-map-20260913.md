# INTEGRATE-RESEARCH-READONLY-PAGES-MAP-20260913 独立集成验收

## 结论

- 集成角色：`integrator`
- `change_risk`：`unclassified`，保留独立 integrator、current-HEAD artifact、backend restart 和禁止 fast-forward main 的最严格路径。
- 注册主工作树基线与当前 `main`：`9ce39a517f6d4cb825a3b4aeb9993db5c2c0162d`。
- 独立 sparse worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-research-readonly-pages-map-20260913`。
- Producer 最终 deliverable：`e594d3bb2d4cb07ee2c3651b4ca55f879fe65e49`；superseding handoff commit：`c4f1ce6ca2125f14901fa1c766af6047e7b891bd`。
- Producer 提交、旧 published event、amendment 与 superseding event 已按线性父链集成，无冲突；业务改动通过独立限定回归，readiness 上限为 `quality_checked`。
- 本报告不代表 registered-main 发布、BTC promotion evidence、paper 或 live readiness。未 merge main、未启动 backend/frontend、未访问 runtime artifact root、未读取凭证、未调用 private/order/live endpoint。

## 修改与职责边界

- Producer 12 个业务 deliverable：受审 research-readonly GET policy、无副作用只读投影、app 路由分流、两组 backend 回归、策略地图及其两项前端测试、里程碑与 producer 验收文档。
- Producer append-only 事件：旧 `published-research-readonly-pages-map-20260913-58be4a7d6` 原样保留；新 `superseded-research-readonly-pages-map-20260913-e594d3bb2` 明确 supersede 旧事件。
- Integrator 自有输出：本报告、`frontend/public/frontend-identity.json` 与 `.agent/handoffs/INTEGRATE-RESEARCH-READONLY-PAGES-MAP-20260913/**`。
- 前端 identity 使用仓库正式 `identity:refresh` 工具生成，baseline `fb9363f5049e8f5ba3c9f407c270115d14da55c2`，fingerprint `3f9f2281e7c06bd342bb292da18b243b5f68aad543dcb02586e2663d87e63b06`，文件 SHA-256 `7071b1628b61720a55919f2e880d863377f7dc990afab8f769c76ea8511969e6`。
- `9ce39a5..95a732f` 对 `quant_crypto/`、`quant_shared/runtime/`、`quant_shared/strategy_runtime/`、`quant_us/live/`、`quant_us/oms/`、`quant_us/risk/`、`backend/app/services/btc_demo_runtime.py` 与正式 backend/frontend launcher 的 diff 为空。未改变策略信号、仓位、退出、Risk、OMS、ledger、broker transport、runtime artifact store/publication、治理规则或交易权限。

## Handoff、祖先与逐文件完整性

- 父链严格为 `9ce39a5 -> 58be4a7 -> ad9c2d64 -> e594d3bb -> c4f1ce6c`。
- 新 superseding event 直接从 Git object 运行 `validate_handoff_against_git`：`valid`；event SHA-256 为 `20337b79e2ef1c4a1c1fd1cd62d2043495be618d3e436801c88b5de5a308f956`。
- Envelope 声明的 12 个业务文件均存在于 `e594d3bb`，逐 blob SHA-256 全部匹配。`base..e594d3bb` 唯一未列为业务 deliverable 的路径是旧 published handoff；这是必须保留的 append-only 交付元数据，不是隐藏业务变更。
- 独立完整 diff 审查确认：GET 白名单是精确路径/受限 ID；POST 与未审路径继续 423；caller selector 不能指定物理 root；server-owned root 和 record child 在读取前做 resolve 边界检查；损坏 JSON/parquet 返回冲突而不静默成功；overview/entry-state 不调用 credential audit；非 readonly profile 保持原 handler 分支。
- 独立审查曾拒绝首版 `58be4a7d`：根 symlink 逃逸、features 损坏 manifest 静默跳过、portfolio 摘要伪造 0/None 且坏 parquet 未拒绝。`e594d3bb` 已在原 touch set 内收口这三项，不通过新增票据或放宽测试绕过。

## 测试与结果

- Producer failure-first：页面 GET `13 failed / 2 passed`，13 项均复现 423。
- Producer amendment failure-first：`3 failed / 2 skipped`，分别复现 features 损坏证据返回 200、portfolio 行数/权重和被伪成 0/None、坏 parquet 未拒绝；2 skip 为当前 Windows 无目录 symlink 权限。
- Producer 最终：`py -3 -m pytest backend/tests/test_backend_research_readonly.py backend/tests/test_research_readonly_views.py -q` -> `52 passed / 2 skipped`。
- Integrator 独立最终：同两文件，`PYTHONUTF8=1`、独立 `--basetemp`、`-p no:cacheprovider` -> `52 passed / 2 skipped in 99.93s`。两项真实 symlink 用例因 OS 权限 skip；权限无关的 mocked root/child resolve escape 均通过，未提升权限。
- Integrator producer 前 BTC 严格基线：`backend/tests/test_backend_research_readonly.py`、`tests/api/test_m1_research_readonly_archive.py`、`tests/contracts/test_btc_domain_read_model.py`、`tests/contracts/test_btc_current_head_gate_rebuild.py`、`tests/contracts/test_btc_current_head_authoritative_data_pointer.py` -> `85 passed / 2 failed`；两项失败均位于旧 cold-start test，分别为强制 UTF-8 解码 Windows stderr 与 sparse `.git` 指针被 `Path.open` 全禁。去掉强制 UTF-8 后为 `1 passed / 1 failed`，唯一失败精确落在读取 sparse `.git` metadata。Producer 最终用例只禁止写模式并保留 Git metadata 读取，最终 52 项通过；BTC builder/domain/pointer/M1 archive 在该基线中均通过。
- Integrator 前端首次 `npm.cmd --prefix frontend run lint`：未运行源码检查，因 sparse worktree 无自有 `node_modules`，报 `tsc is not recognized`。未安装或复制依赖；建立到 registered-main `frontend/node_modules` 的本地 junction 后复用 canonical dependencies。
- Integrator canonical dependencies：`npm.cmd --prefix frontend run lint` -> passed；`npm.cmd --prefix frontend run build` -> passed，`5258 modules transformed`，仅有既存 large-chunk warning。
- `npm.cmd --prefix frontend run identity:check` -> passed，`manifest_match=true`、`baseline_ancestor=true`；集成分支按设计 `canonical=false`。
- `npm.cmd --prefix frontend run identity:test` -> passed，`object_targets=4`。
- 未运行：worktree serve（治理禁止）、registered-main listener/restart、正式 HTTP 12 GET/POST、Playwright canonical browser、真实账户只读验收、真实 external-root BTC artifact rebuild/publication。

## 治理证据与初始 dirty

- 已读：`AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/delivery_risk_policy.json`、`docs/agent_playbooks/research_readonly_release.md`、`.codex/agents/integrator.toml`、`quant-agent-preflight` 与 `quant-agent-handoff` skills。仓库没有单独的 `integrator_pitfalls.md`；integrator TOML 为角色合同。未读取原始历史踩坑日志。
- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- Active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- Integrator 自有三项路径与 producer 最终 12 个业务路径在集成前逐路径 `safe_status=clean`。未发现重叠 writer 或 dirty 文件；cherry-pick 无冲突，未清理、覆盖或回滚其他工作树。

## Artifact、freshness 与剩余发布步骤

- 本集成未创建或修改真实 BTC artifact、manifest、ledger、replay 或 latest pointer；未读取 physical runtime root。
- 现有离线入口 `scripts/build_btc_current_head_gate_rebuild.py` 已通过 strict temp-root 合同：缺旧输入时仍可为最终发布 HEAD 原子发布 blocked snapshot，保留 blocker，last pointer 最后替换，read model 严格绑定 source HEAD，49 个安全字段保持 false。
- 当前 503 尚未在 registered main 修复，因为 artifact 仍未对最终发布 HEAD 重建/发布；不得把集成分支测试或旧 artifact 描述为 current-main freshness。
- 获得 main 发布授权后，唯一剩余顺序：集成审定 tip 到 registered main；记录实际发布 commit 与 rollback commit；在既有 external root、owner marker 和 single-writer lock 下仅运行一次 current-HEAD builder；记录新 snapshot batch/manifest hash 与替换前 pointer batch/manifest hash；验证 49 个安全字段全 false；使用正式 launcher 重启 8765/3000；核验 identity/health/canonical/runtime_stale；逐项验证 12 个 GET 非 423、BTC domain read model 为 HTTP 200 但 gate 仍 blocked、POST 仍 423、非法 root/ID 与损坏证据 fail-closed；最后运行 canonical Playwright 页面验收。
- 回退点必须同时记录 Git commit 与 artifact pointer 的旧 batch/manifest；Git 回退不会让旧证据自动匹配回退后的 source HEAD。

## Gate 与安全状态

- Gate：`blocked_fail_closed_no_paper_no_live`；本交付只达到 `quality_checked`，不构成 `research_ready`、`backtest_ready` 或 `promotion_evidence_ready`。
- 明确保留 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。
- Producer handoff 中的 `real_account_readonly_acceptance_not_run`、4 个既有 Guardian fixture failure、registered-main publication、backend restart、current-main BTC artifact publication 与 canonical browser acceptance 继续如实 blocked；本票未触碰 4 个既有 fixture。
