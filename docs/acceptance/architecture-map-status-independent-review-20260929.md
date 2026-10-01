# 架构地图当前状态独立集成审查

日期：2026-09-29

票据：`INTEGRATE-ARCHITECTURE-MAP-STATUS-20260929`

角色：`integrator`

变更风险：`research_readonly_release`

## 结论

批准的 `ARCHITECTURE-MAP-STATUS-20260929` 三提交已在独立 sparse worktree 中按顺序集成并通过限定独审。当前交付上限为 `quality_checked`，`gate_impact=none`，`promotion_eligible=false`。本审查没有修改 backend、策略、风控、OMS、账本、权限或服务配置，没有启动 Vite、backend、账户、Demo、paper 或 live，也没有写入注册主工作树。

当前仍不是正式发布：注册主工作树合入、`research_readonly` 正式重启、canonical `3000` 的 `/architecture` 三组 Playwright 及无 mock 浏览器验收由主会话在 main 合入后执行。

## 身份、来源与提交链

- planner worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-architecture-map-status-20260929`
- 分支：`agent/integrator/integrate-architecture-map-status-20260929`
- 批准基线／rollback：`3fc39879d14ecab2288368afe588385cc44c08e1`
- producer 业务提交：`2f82db2ba29dfe27add039066009b41e7919f0d7`，集成分支对应提交 `72c255347`
- producer identity 提交：`ffc49aa329660aa8f6418fcf2f9c134689595404`，集成分支对应提交 `914d40964`
- producer envelope 提交：`de421340d8b6a5fd6217f51a6288bd80aca0dc70`，集成分支对应提交 `cc992500a`
- 独审修订提交：`8fdb53b2eb939d6576d04fca11be044268210e18`
- 集成前端身份提交：`7793a8829ad22e974e62da28240fe12bb4813cad`

三笔 producer 提交父链严格为 `3fc39879 → 2f82db2 → ffc49aa → de42134`；批准基线在集成开始和独审结束时仍是 `refs/heads/main`。cherry-pick 无冲突。未消费 producer worktree 的未提交文件。

## Handoff、哈希与证据完整性

`published-architecture-map-status-20260929-ffc49aa32` 经 `handoff.py --repo-root . validate` 为 `valid`。五个 deliverable 的原始 Git blob SHA-256 与 envelope 精确一致：

| 路径 | SHA-256 |
| --- | --- |
| `frontend/src/workspaces/ArchitectureMapWorkspace.tsx` | `6820b93a84ccdc0252ebb85946b565b6e6159689ba5e567f220906dc180e0065` |
| `frontend/src/workspaces/architecture/mindmap.ts` | `89cf52818a2ef539ade3da01198dd6de0869edea820de829088aa0915fa75df2` |
| `docs/architecture/system-code-map/DEVELOPMENT-STATUS-20260929.md` | `c63a294f0359751d0ff66bf6722ffd0124ac7eee8e5e926632838a340cc4c4c5` |
| `docs/acceptance/architecture-map-status-20260929.md` | `b4e086dad2cff6d20e9871d350d744a28cfe974f1ee26e97d9f4267dfd37f672` |
| `frontend/public/frontend-identity.json` | `720fd885c250b75226408faa823c1ece15a277922e3d5c267b8593a070bde1dc` |

Windows checkout 的 CRLF 文件字节哈希与 Git blob 不同；交付合同以 `git cat-file blob <commit>:<path>` 的提交态原始字节为准，上表与 envelope 无差异。

外部只读验收证据也精确匹配 producer 引用：

- `D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/deployment-acceptance-report-3fc39879.md`：`f57b014bde1e963ccf71a4c110781021cc342b271f22e0238378c2825ca6c429`
- `D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/research-readonly-release-receipt-3fc39879.json`：`a5004f082f251d7403214f13761b58c2a9593e3fc7290a8080722369397612c9`

它们绑定 `3fc39879` 的历史正式只读验收；本票没有重跑 11/11 性能矩阵，也不把旧报告升级为新 HEAD 的 promotion artifact。

## 事实审查

逐项核对 `docs/operations/donchian-history-main-integration-20260922.md`、`docs/acceptance/integrate-candidate-market-policy-closeout-20260927.md`、`docs/acceptance/btc-candidate-offline-entry-20260925.md`、`docs/operations/donchian-stage-readonly-20260921.md`，以及 `78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json` 后，页面与说明保持以下边界：

- `factory_lgbm_ast_v1` 是登记候选离线 worker 当前唯一支持类型，默认 `candidate_offline_enabled=false`；旧 M1 v2 不是该通用 worker 的执行能力。
- V0—V3 只是历史冻结离线范围的限定结项，不是当前交易部署。
- 自然历史阶段为 `2960 / 8760` 暂停快照，计算来源仍为 `897d5e99…`；该提交不是当前 main 祖先，页面正确区分计算源码与发布源码。
- 历史执行提交 `441e057e2cdc84dd9dba32bf827fd150e614e0e2` 已是 main 祖先。
- 市场政策 baseline 为 `2960 / 2960`；conditioned 在 `1956 / 2960` 因 `historical_protection_double_touch_ambiguous` fail-closed，并保留 `-0.01` 张空头，没有伪平仓。
- 冻结计算源 `f2455bfbcafd15404bb4ff98dd6bb925728d0339` 已是 main 祖先；旧 M2 没有稳定增量，M3—M4 未启动。
- 当前 `research_readonly` 页面状态不代表账户、Demo、paper、private、order 或 live 部署能力。

## 独审修订

在 producer 原授权 map/docs/tests 范围内完成四项最小修订：

1. `ArchitectureMapWorkspace.tsx`：把 `changedBaseline` 提示改为“历史审阅索引与当前页面代码不同，不代表重新通读当前全仓”，不再把浏览器验收误写成源码差异核验。
2. `mindmap.ts`：V3 状态不再把自然历史阶段写成“只读证据候选”，明确 selector 已另行核账并发布。
3. `architecture-mindmap.spec.ts`：先断言 delivery 区域恰有三条证据链接，再逐一精确核验 Qlib、Donchian 五阶段和 Donchian 自然阶段的 href，消除 strict-mode 多元素定位失败且不弱化校验。
4. producer 验收文档移除三处 trailing whitespace；最终 `git diff --check` 通过。

前端源码修订后使用既有 `identity:refresh` 生成提交态身份：`baseline_commit=8fdb53b2eb939d6576d04fca11be044268210e18`，`fingerprint=5bdc9b0fb258a0c178a73f7c389e2c45d331d1abdcf3317b8b2d6e938e0372ba`。`identity:check` 在 `7793a8829` 返回 `manifest_match=true`、`baseline_ancestor=true`。

没有修改 `architecture-map.css`、`catalog.json`、`knowledge.json`、backend、`quant_crypto`、`quant_shared`、`quant_us` 或 `quant_cn`。

## 初始 dirty、touch set 与冲突

合入前对 producer 全部路径、独审报告路径和本票 handoff 目录逐项执行 `safe_status.py --repo-root . --path <path>`，均为 `clean`、`dirty_count=0`。本票只写 producer 已提交范围、上述四项独审修订、集成身份、本报告和 append-only 集成 handoff。

无 cherry-pick 冲突，无其他代理 dirty 文件被覆盖、清理、重置或消费。Team Context 的 17 项历史 invalid handoff 与其他 blocked dependency 未纳入本票，未合并其他代理改动。

## 独立验证

| 命令 | 结果 |
| --- | --- |
| `node frontend/scripts/test-architecture-map.mjs` | `9/9 passed` |
| `node frontend/scripts/test-architecture-mindmap.mjs` | `6/6 passed` |
| `node frontend/scripts/test-architecture-knowledge.mjs` | `5/5 passed` |
| 主工作树 TypeScript `tsc.cmd --noEmit -p frontend/tsconfig.json`，只读复用 `node_modules` | exit 0 |
| `npm.cmd --prefix frontend run identity:check` | passed；`manifest_match=true`、`baseline_ancestor=true` |
| `py -3 -B -m pytest -q -p no:cacheprovider ... tests/agent_governance/test_handoff.py tests/agent_governance/test_context_packet.py` | `32 passed in 41.80s` |
| `handoff.py --repo-root . validate` producer envelope | valid |
| 最终限定 `git diff --check` | exit 0 |
| 排除路径差异核验 | CSS、catalog、knowledge、backend、各交易域均无差异 |

未运行项：工作树不启动 Vite 或 backend，因此没有运行三个 Playwright architecture spec；没有做 390／1131／1440 canonical 浏览器验收、无 mock 页面验收或正式服务重启；历史性能 `11/11` 不重跑；不运行回测、训练、账户、Demo、paper、private/order/live 测试。

## Playbook 与治理证据

已读：`AGENTS.md`、知识 README、non-negotiables、`shared_pitfalls.md`、`.codex/agents/integrator.toml`、`delivery_risk_policy.json`，以及 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff` 技能。没有全文读取原始事故日志。

catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

本次 context packet 命中：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

## 剩余正式发布步骤与安全边界

主会话后续仅需：

1. 复核 main 仍为 rollback 点 `3fc39879…` 且批准 touch set clean，再合入本集成交付。
2. 使用仓库正式入口重启 `research_readonly` backend/frontend，确认 canonical identity 与当前 main 精确匹配。
3. 在 canonical `3000` 运行 `frontend/e2e/architecture-map.spec.ts`、`architecture-mindmap.spec.ts`、`architecture-knowledge.spec.ts`，覆盖五视图、总图节点／缩放、状态筛选、三条历史证据链接以及 390／1131／1440 宽度，并执行无 mock 浏览器验收。
4. 验收失败则保持 main rollback 点与只读 gate，不以工作树页面或历史报告替代正式验收。

本票不产生新的 artifact、manifest、ledger 或 replay；唯一刷新的是提交态 `frontend/public/frontend-identity.json`。`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 `false`。集成 handoff 本身不解锁 promotion、paper 或 live。
