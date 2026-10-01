# BTC 保护单父订单关联独立终验

## 结论

**source contract passed。** 已知的 raw parent 依赖缺口在本次源码候选中关闭，且没有改变原 V1 行为。

raw parent 缺失时，归一化器只从唯一且同时匹配 `algoId + algoClOrdId` 的 owned 登记取得父订单，再与 parent intent、active receipt、当前 account／run／source／epoch／strategy／snapshot binding 逐项交叉验证。raw parent 非空但冲突、只匹配单个 ID、重复／外来／未绑定证明仍被拒绝；父订单不是从 `A` 后缀推导，后缀关系只作为取得本地父订单后的额外一致性校验。

原始 exchange snapshot 与 canonical ledger hash 未修改；helper 输出的是 detached projection，同一 normalized rows 继续进入 composition 预分类和未修改的 Guardian。原 10 个 V1 测试函数 AST 完全不变，只新增一个 parentless readback E2E，并复用完整五阶段经济、重复、重启、账本和证据断言。

本结论只证明源码合同及冻结离线场所适配。它不表示实际 OKX Demo 账户已调用，也不表示 Demo、paper、private、order 或 live 已开放。

## 提交与范围

- integration ticket：`BTC-PROTECTION-PARENT-JOIN-INTEGRATION-20260915`
- source ticket：`BTC-PROTECTION-PARENT-JOIN-20260915`
- change risk：`demo_execution_semantics`
- base：`bcc63648fcb39e23b690bc860318b226fd106546`
- source：`cd211003fe574bc3a643d32060a17bb245d6e8d0`
- source handoff HEAD：`1563f9ce758d016662f97272ae5dcfc8a2e95619`
- source handoff：`.agent/handoffs/BTC-PROTECTION-PARENT-JOIN-20260915/published-btc-protection-parent-join-20260915-cd211003f.json`
- isolated integration merge：`16ac7184dd2b30d2de1972a2d66dc2fd53974957`
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

producer handoff 的 schema 与 committed Git objects 均校验为 `[]`；base／source／handoff ancestry 正确，隔离合并无冲突。source 精确修改四个批准路径：

- `quant_crypto/application/hosted_protection_facts.py`
- `tests/contracts/test_btc_hosted_protection_facts.py`
- `tests/contracts/test_strategy_v1_donchian_offline.py`
- `docs/architecture/btc-hosted-protection-facts.md`

Guardian、runtime、composition、OMS、risk kernel、shared permissions、control plane、策略、goldens、M1、治理、launcher、UI／API 均未修改。Guardian 在 base 与候选的 Git blob 都是 `c8e2f74751803a3a466bf6881681011a1adf6d4a`。

## 独立验收

```text
$env:PYTHONDONTWRITEBYTECODE='1'; <venv-python> -B -m pytest -q -p no:cacheprovider --tb=short --basetemp <isolated-temp> tests/contracts/test_btc_hosted_protection_facts.py
15 passed in 0.69s

$env:PYTHONDONTWRITEBYTECODE='1'; <venv-python> -B -m pytest -q -p no:cacheprovider --tb=short --basetemp <isolated-temp> tests/contracts/test_btc_demo_production_composition.py
19 passed in 2.81s

$env:PYTHONDONTWRITEBYTECODE='1'; <venv-python> -B -m pytest -q -p no:cacheprovider --tb=short --basetemp <isolated-temp> tests/contracts/test_strategy_v1_donchian_offline.py
11 passed in 153.97s
```

额外静态核验：base 与 source 的 V1 测试 AST 对比为 `changed_existing=[]`、`removed=[]`，仅新增 `test_continuous_closeout_accepts_parentless_exchange_algo_readback_only_via_local_join`。新增用例从 pending-algo 与 order-algo 回读剥离 `parentClOrdId/clOrdId`；取消后的 algo-history 终态核验不消费 parent，只核对 exact algo id、algo client、instrument、order type 与 terminal state。因此当前五阶段覆盖成立，但不能扩写成所有实际 OKX API 响应形状均已实测。

producer handoff 中 failure-first 的斜杠表达式只是历史红测摘要，不是本独审执行的 pytest 命令；本报告只把上面三条完整命令作为独立结果。

## 未运行项与 Gate

- `source_contract=passed`
- `offline_v1=passed`
- `actual_okx_demo_runtime=not_run`
- `os_level_hard_crash=not_run`
- `page=not_started`
- `release=not_started`

未访问网络、secret、账户、broker/exchange、private/order/live endpoint；未提交或撤销真实订单。未运行 UI、API、服务启动、Qlib、M1、M3—M4、promotion 或 main 发布。本候选 readiness 上限为 `quality_checked`；promotion、Demo、paper、live、private、order、real order、transfer、withdraw、execution permission、runtime worker 与 runtime observed 均保持 `false`。

## 预检

工作树由 planner 从指定 base 创建，`core.sparseCheckout=true`，初始 source 路径 clean；唯一初始 dirty 是本 integrator 自有 pending 报告。已读取 integrator profile、知识总则、non-negotiables、shared pitfalls、执行／架构／审计规则，以及 `quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review` 技能。

active IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
