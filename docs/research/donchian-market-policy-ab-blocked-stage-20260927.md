# Donchian 市场状态入场政策阶段回执（blocked）

## 身份与范围

- truth kind: `sealed_blocked_stage_read_model`
- schema: `market_policy_trial_blocked_report_v1`
- trial: `donchian-market-policy-ab-20260927`
- compute source: `f2455bfbcafd15404bb4ff98dd6bb925728d0339`
- integrated consumer event commit: `ad036fb1de882587e781114085214f5c1693c372`
- baseline run: `donchian-market-entry-baseline-20260927`
- conditioned run: `donchian-market-entry-conditioned-20260927`
- intended window: `[2025-09-01T00:00:00Z, 2026-01-02T08:00:00Z)`，2960 小时事件，4800 小时预热。
- Python / pandas: `3.11.15 / 3.0.4`。
- 运行根（仓库外、create-only）：`D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-market-policy-ab-20260927`。

本回执只封存一次冻结的阶段实验事实。它不恢复旧年度运行，不构成完整 A/B 效果估计，不是 promotion evidence，也不授予 Demo、paper、live、private 或 order 权限。

## 不可变文件与校验

| 文件 | schema / 用途 | 文件 SHA-256 | 内部内容哈希 |
|---|---|---|---|
| `donchian-market-policy-ab-blocked-stage-summary.json` | `market_policy_trial_blocked_report_v1` | `5251cb9e11d3ff3160001a07a1e9d93ef1648334e09006bdbed66cc137a60084` | `report_hash=9361be7e2bac7b58b940f4f02594a2a14d5f0d8d63722bf1508620acee1d9b79` |
| `donchian-market-entry-baseline-20260927-ledger-reconciliation-receipt.json` | baseline 只读 ledger recover / reconcile | `3913b1706617d96e030b1e468699205bc8642a3518bbaecfdad071013b0d2d9c` | `receipt_sha256=bc1f3041f517689f818d1b0f3a47f6c296567cd78e929f8303465b51892321d4` |
| `donchian-market-entry-conditioned-20260927-ledger-reconciliation-receipt.json` | conditioned 只读 ledger recover / reconcile | `f1d98c214648595891f4d44bd9a90051c971eee73e62ea234f373df54e2f8fc3` | `receipt_sha256=79423c9c6a3c9fe56b299ef92ff2c5316b715344effb2d70278a115385e94fcd` |

三份文件的内部 canonical JSON 哈希均已独立重算并与声明一致；封存后未再次运行研究或 recover。

## 顶层读模型

`donchian-market-policy-ab-blocked-stage-summary.json` 顶层键固定为：

`arms`、`comparison`、`consumer_binding`、`generated_at_utc`、`limitations`、`protocol`、`rejected_entry_phase_index`、`report_hash`、`runtime_budget`、`safety`、`schema_version`、`source`、`status`、`trial_id`、`truth_kind`、`usage`、`window`。

- top-level `status`: `blocked_fail_closed`
- `usage`: `blocked_stage_diagnostic_only_not_effect_estimation_not_promotion`
- arm keys:
  - `original_donchian`
  - `original_donchian_plus_frozen_entry_policy`
- `comparison.status`: `unavailable_incomplete_conditioned_arm`
- `comparison.effect_verified=false`
- `comparison.improvement_claim_supported=false`
- `comparison.promotion_supported=false`
- 不存在 completed-trial 的 `decision_effects` 或完整经济差字段；reader 不得推导或补造。

## 两臂事实

### Baseline

- status: `completed`
- processed / expected: `2960 / 2960`
- fills / orders / roundtrips: `56 / 56 / 28`
- nonzero funding bills: `24`
- terminal position: `0`（flat）
- cash / equity: `4999.756705676961504352009`
- price PnL: `0.0346310615`
- fees: `0.26552203961525`
- funding: `-0.012403344923245647991`
- ledger sequence / last hash: `14874 / ce5d234628d03ca22edc9e0db36f32b06bd18a9631363b4bb438f78f6bfa2bab`
- 与此前封存的 2960 阶段业务数字精确一致。
- arm elapsed: `7259.479s`，比 120 分钟预算多 `59.479s`；不得描述为 within budget。
- policy decisions 为 `2959`，最后一个事件没有下一根 bar 的政策决策，不补造第 2960 个决策。

### Conditioned

- status: `blocked_fail_closed`
- processed / expected: `1956 / 2960`
- blocker: `ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous`
- blocked bar: `2025-11-21T12:00:00Z`（报告展示的 `2025-11-21T20:00:00+08:00` 为同一时点）
- rejected new-entry proposals: `48`
- fills / orders: `17 / 17`
- nonzero funding bills: `14`
- terminal position: `-0.01` contract short，average price `82667.566415`；状态为 `nonflat_blocked_preserved`，不得写成空仓。
- cash: `5000.437975996854100955919`
- equity: `5000.476042638354100955919`
- realized / unrealized: `0.539018739 / 0.0380666415`
- fees: `0.08911722294525`
- funding: `-0.011925519200649044081`
- ledger sequence / last hash: `9807 / e799b5f8163473649e1df22a740e1486b60d2048259a3627b25ca954c2396b2c`

两个 ledger 回执均显示完整 event-chain recover、无 truncated tail、checkpoint 与 recovered state 相符、ledger reconciled、exchange snapshot match、funding reconciled。该核账不把未完成 conditioned arm 变成完整效果证据。

## 48 个政策拒绝 phase 的字段

实际字段位于顶层数组 `rejected_entry_phase_index`，长度严格为 `48`。每项键为：

- `phase_index`
- `event_time_utc`
- `decision_time_utc`
- `action`
- `market_entry_policy`
- `projection`
- `evidence_links`

`market_entry_policy` 包含 `policy_id/version/hash`、`attachment_hash`、`applied`、`reason`、`original_target_contracts`、`effective_target_contracts`、`existing_position_contracts`、`state_binding_status`、`state_version`、`state_definition_hash`、`state_source_binding_hash`、`state_content_hash`、`state_input_hash`、`state_status`、`state_reasons`、`state_cutoff_utc` 和 `usage`。48 项的 `state_binding_status` 均为 `verified`。

`projection` 明确为 `projection_source=consumer_phase`、`projection_status=partial`。由于计算环境与早期诊断环境不同，不能使用 nearest / last observation 或跨解释器 helper 冒充 exact join。未持久化的 24/72/168 path efficiency、方向、波动、冲击、持久性和切换指标均保持 `null`，且每项 `missing_fields` 已排序列出。`evidence_links` 中不存在的订单、成交或账本身份保持 `null` / 空数组，不能因为拒绝计数推导为成交效果。

## 安全与结论

以下旗标全部保持 `false`：

- `demo_enabled`
- `paper_enabled`
- `live_enabled`
- `promotion_enabled`
- `private_endpoint_accessed`
- `real_order_submitted`
- `network_accessed`
- `runtime_observed`

结论只能是：baseline 完整通过并可核账；conditioned 在第 1956 个事件因同一小时 K 线内保护单双触发顺序不明而 fail-closed，留下已核账的 `-0.01` 合约空头。因此本轮不能形成完整 A/B 改善或失效结论，不能为了完成比较而选择有利的止盈/止损顺序、补造细粒度行情或自动重跑。

## 验证与边界

- 已验证：三份文件的 SHA-256、内部 canonical JSON hash、48 phase 数量、全部 partial/null/sorted missing fields、`state_binding_status=verified`、conditioned terminal short 和全部安全旗标为 false。
- 未验证／不声称：逐 tick 最大回撤、连续 intrabar 路径、完整 conditioned arm、完整 A/B effect、paper/live readiness。
- 原始运行根保持原样；本清单是小型提交态索引，不复制大日志、SQLite 或 runtime payload。
- touch set 仅为本文件和对应 append-only handoff；未修改策略、市场状态算法、Risk、Guardian、OMS、ledger、启动器、权限或页面。

## 治理记录

- role: `btc_developer`
- change risk: `unclassified`
- catalog hash: `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- active pitfall IDs: `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- playbooks: `docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/btc_developer_pitfalls.md`。
