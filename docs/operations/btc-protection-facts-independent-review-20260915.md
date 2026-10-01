# BTC 保护单事实归一化独立终验

## 结论

**partial / blocked，本轮在约定停止点结束。**

限定的离线映射候选通过：原始快照与账本 hash 未被 enrichment 改写；sanitizer 只保留白名单字段；本地 parent intent、owned-algo 与 active receipt 必须绑定同一 account／run／source／epoch／strategy／snapshot；同一份 normalized rows 同时进入 composition 预分类和未修改的 Guardian。冻结 V1 五阶段序列及其重复、恢复和错误身份保护共 10 项全部通过。

但真实 OKX 回执兼容没有闭合。当前 helper 要求交易所行自带 `parent_client_order_id`，且要求 `algo_client_order_id == parent_client_order_id + "A"`。OKX 官方合同只保证用户提交的 `attachAlgoClOrdId` 在主订单完全成交后成为附属单的 `algoClOrdId`，并明确普通订单 `clOrdId` 不会自动转发给附属 TP／SL。因此冻结模拟器提供的 `parentClOrdId` 不是已经证明的场所权威字段。[OKX API Guide](https://www.okx.com/docs-v5/en/)

独立反例进一步确认：移除 raw parent 后，即使本地 exact algo id／algo client、owner、parent intent、active receipt 与当前 binding 均保持一致，helper 仍返回 parent／owner／receipt 五类 blocker，且不生成 `owned_by_runtime` 或 `close_position`。这是安全的 fail-closed，但不能描述成“真实 OKX 归属映射已完整实现”。本轮不修改 helper、不召回 producer、不启动下一轮修复。

## 提交与变更边界

- integration ticket：`BTC-PROTECTION-FACTS-INTEGRATION-20260915`
- source ticket：`BTC-PROTECTION-FACTS-20260915`
- change risk：`demo_execution_semantics`
- base：`3c5a040a21109e8f4b7c25c29473049d3e53ab6d`
- source：`f019609ac2b3c2acea6dc7e96a5d4b0bb53c8fa9`
- source handoff HEAD：`bb95c24ac2830cd31682f529338568e62e09c26a`
- source handoff：`.agent/handoffs/BTC-PROTECTION-FACTS-20260915/published-btc-protection-facts-20260915-f019609ac.json`
- isolated integration merge：`4b2afd02daac11622d1e68a7927458ad6599c415`
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

producer handoff against committed Git objects 校验为 valid；source 是指定 base 的后继，隔离合并无冲突。精确 source touch set 为：

- `quant_crypto/application/hosted_protection_facts.py`
- `quant_crypto/application/btc_demo_production_composition.py`
- `quant_crypto/oms/okx_demo_paper_runtime.py`
- `quant_crypto/application/donchian_offline_replay.py`
- `tests/contracts/test_btc_hosted_protection_facts.py`
- `tests/contracts/test_btc_demo_production_composition.py`
- `tests/contracts/test_btc_okx_demo_paper_runtime.py`
- `docs/architecture/btc-hosted-protection-facts.md`

Guardian、risk kernel、OMS 核心、shared permissions、control plane、策略、V0 goldens、M1、治理、launcher、UI／API 均未修改。`quant_crypto/application/runtime_risk_guardian.py` 在 base 与候选的 Git blob 都是 `c8e2f74751803a3a466bf6881681011a1adf6d4a`。

## 独立验收证据

```text
focused normalization / sanitizer / immutable projection / shared rows
15 passed in 3.80s

frozen V1 Donchian offline matrix
10 passed in 71.53s

BTC demo production composition compatibility
19 passed in 2.08s
```

额外纯函数反例：

```text
raw parent removed; exact local owner/parent/receipt retained
blockers = parent_identity_mismatch, owner_lifecycle_mismatch,
           parent_binding_mismatch, parent_intent_mismatch,
           receipt_identity_mismatch
owned = null; close = null
```

伪造的 `owned_by`、`owner_id`、`runtime_identity`、`closePosition` 在 raw sanitizer 后全部消失，没有进入 helper 或 Guardian。通过用例中的 `reduceOnly` 缺失保持 `unknown`，`long_short_mode` 的关闭方向只来自明确的 `sell+long` 或 `buy+short` 及完整本地生命周期交集，没有被补造为 `true`。旧订单的 `uTime` 较早本身没有新增 TTL；未来时间、身份／snapshot／状态不匹配继续阻断。

上一轮首次 Guardian trip 的精确时点是 reversal-close 提交前、仍为 non-flat 的观察；flat／2 fills／1 cancel 是事后检查点。本候选只证明冻结模拟回执下该序列已通过，不把旧离线复现外推成已验证的生产故障，也不承诺“补一个字段即可解决真实场所兼容”。

## 未运行项与 Gate

- 未运行真实 OKX／Demo/private/order/live 接口或账户读取；未提交、撤销任何真实订单。
- 未运行独立子进程 OS-level hard-crash；V1 fault hook 仍是同进程注入并在重构 runner 前显式 `close()`，不能外推为所有硬崩溃点已覆盖。
- 未运行 UI、API、服务启动、M1、Qlib、M3—M4、promotion 或正式发布。
- 未改 main；本报告与源码均只在隔离候选分支。

状态分别为：`offline_mapping=passed`、`real_okx_receipt_compatibility=blocked`、`technical=partial`、`page=not_started`、`release=not_started`。readiness 上限为 `quality_checked/partial`；promotion、Demo、paper、live、private、order、real order、transfer、withdraw、execution permission、runtime worker、runtime observed 均保持 `false`。

## 预检

工作树由 planner 从指定 base 创建，`core.sparseCheckout=true`，初始限定路径 `safe_status=clean`。已读取 integrator profile、知识总则、non-negotiables、shared pitfalls、架构／执行／审计规则，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review` 技能。

active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
