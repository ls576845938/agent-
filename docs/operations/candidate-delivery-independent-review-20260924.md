# 候选交付后端独立审查：拒绝当前候选

日期：2026-09-24。本记录由主会话整理独立 `quant_architect` 子任务 `candidate_delivery_independent_review` 的结论；不是原作者自审通过，也不是集成/发布回执。

## 精确对象与结论

- Base / 未变更 main：`55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`。
- 审查源码：`ac74ba23c46110e42d21227418e9b7f5a0c1ea28`。
- 交接提交：`ef742adc6736e8f3fde093eb987451523a7d08e1`。
- 来源事件：`candidate-delivery-source-20260924-01`；本轮主会话与独审均验证 `valid`，三个交付物 SHA-256 与提交对象一致。
- 本轮注入的 Team Context 已成功发现该事件，之前的发现超时不再作为本轮独审阻断；其他历史无关 invalid handoff 不纳入本票修复。
- **独审拒绝集成当前候选：1 项 P1、1 项 P2，无 P0。** 测试通过不覆盖下述缺口。
- 仅审查及记录；不改业务代码、不合 main、不启用管理能力、不发布。原交接/报告保留，以下新结论不改写历史证据。

## P1：账户结算币种未匹配

`quant_shared/strategy_delivery/models.py:64` 的包身份没有结算/保证金币种；`:98` 的账户验证只要求 `currency` 非空。
`backend/app/services/candidate_delivery_sources.py:98` 和 `:125` 的冻结 BTC-USDT-SWAP Qlib/Donchian 包均未提供结算币种合同，尽管费用、限额及初始权益采用 USDT。

独审以真实冻结 Donchian 来源和临时 SQLite 复现（不修改仓库/真实账户）：

```text
账户 currency=USD，instrument=BTC-USDT-SWAP
bind → approve → register → resolve 全部成功
status=registered, account_currency=USD
max_notional_usdt=50, settlement_currency=None
```

这是账户兼容验证缺陷；当前未接运行，不会立即下单，但不能以“未启用”掩盖错误的登记结论。

必要修正限定为本票包/账户合同与测试：

1. 包增加必填、规范化结算币种；当前两个固定来源明确为 USDT。
2. 包验证拒绝缺失/非法币种，账户验证精确匹配。
3. USD 绑定拒绝、USDT 原流程通过；审定后账户漂移为 USD 时登记/消费均拒绝。
4. 真实 Donchian 与固定 Qlib 包均验证币种字段，Qlib 原研究阻断仍保留。

不改变仓位/成本值、不补 Demo 适配、不重跑全年。

## P2：前端目录名称容易误导

`frontend/src/workspaces/research/CandidateDelivery.tsx:99` 为“登记到目标环境目录”。实际上只写独立 `candidate-delivery.sqlite`，`resolve_btc_registered_candidate` 只有测试调用；现有离线 CLI 和 Demo 入口不消费该目录。

原源码报告已说明这一限制；问题是前端文案和“可运行目录”完成标准容易混淆。必要修正为“登记到候选管理目录”“已登记管理记录 · 未接入运行入口 · 未启动”，同步架构文档并加对应文本断言。**不能为修正文案顺带增加运行接线。**

## 已认可边界与复核范围

独审确认：默认关闭的候选管理白名单没有放开 research_readonly 写入或构造 Demo；操作员来自服务端配置；固定模型/规格/校准/参数精确绑定；Qlib 原 blocker 保留；HEAD、账户 hash/revision/expiry、审定有效期和撤销消费前重验；SQLite 事务/CAS/幂等及未知提交回执机制存在；没有改 Risk、OMS、经济账本、原策略或 Demo 启动链。

### 独立验证

独审从 `tests/contracts/test_strategy_delivery.py` 抽取：
`test_idempotency_and_concurrent_registration`、`test_drift_cannot_register`（参数化）、`test_revision_and_revoke_and_wrong_consumption`、`test_running_service_rejects_head_change`、`test_receipt_recovery_and_tampering_fail_closed`；从 `test_candidate_delivery_api.py` 抽取 `test_auth_origin_fields_and_actor_are_server_owned`、`test_http_lifecycle_receipt_catalog_and_revoke`。

结果 **10 passed / 1 既有弃用警告，1.97s**；另执行上述真实冻结 Donchian 币种误配的临时复现。独审未写源码/报告/Git，不运行服务器/浏览器/真实账户/交易所，不重复原 16 分钟离线套件。

### 主会话复核（不是独立证据）

在交接提交 `ef742adc...` 的干净限定源码范围：

```text
QS_BACKEND_EVIDENCE_PROFILE=research_readonly
python -m pytest -q tests/contracts/test_strategy_delivery.py tests/contracts/test_candidate_delivery_api.py tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_strategy_registry.py -p no:cacheprovider --tb=short --basetemp <TEMP>/qs-admin-review-20260924-b
57 passed / 1 既有 Starlette/httpx 弃用警告，17.91s

frontend: node --test scripts/test-candidate-delivery.mjs scripts/test-candidate-handoff.mjs
19 passed
```

上轮类型检查、构建和 37 项旧离线测试本轮未重复，不当作新增独立证据。未运行正式发布或浏览器交互验收。

## 治理与后续

本轮业务 touch set 为空；文档 touch set 仅本报告及本票 append-only rejected handoff。开始时 scoped clean；不覆盖他人改动，不改旧事件。独审角色 architect，主会话只记录结果；`change_risk=unclassified`。

已读 preflight/handoff skills、shared/architect playbooks、knowledge README/non-negotiables/source-map/domain architecture、交付风险政策。Catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
适用规则包括 ARCH-READONLY-001、GOV-CONCURRENCY/DIRTY/HANDOFF/ROOT/WORKTREE/STORAGE/ENGINEERING-CIRCUIT/OBJECTIVE/PITFALL/PROMPT/WINDOWS-001、QSYS-GATE-001、QSYS-SECURITY-001；未扩查原始事故日志。

下一步只需修正上述两项及必要测试，以新提交/交接重新限定独审；通过后仍须独立 integrator。不得以本报告授权部署或运行接线。

管理服务未启用；没有生产管理 DB、manifest 或经济账本变更。`demo_control_enabled/execution_permission/runtime_observed/promotion/paper/live/private/order/real_order/transfer/withdraw` 均 false。当前 verdict：**implementation integration blocked / paper blocked / live blocked**。
