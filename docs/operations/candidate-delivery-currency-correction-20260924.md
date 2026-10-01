# 候选管理币种与文案限定修复

日期：2026-09-24。角色：主会话 super_developer；change_risk=`unclassified`。仅修复独审指出的 P1 币种匹配与 P2 目录文案，不接入运行，不启用服务、不合 main、不发布。

## 对象、归属和回退

- 主版本/原票 base：`55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`。
- 修复前生产者提交/回退参考：`d18bfb9e0f39ab6f87a327f9ad0e0ca26c6634e9`，其中包含被拒绝的源码与独审记录；不可当作安全发布版本。
- 分支：`agent/super_developer/candidate-delivery-backend-20260924`；原专属 sparse worktree 内单写者修正，不复制第二套管理实现。
- 开始时声明的限定源码路径 clean，无他人重叠修改。不修改其他工作树或其未合并改动。原 source/rejected 交接和审查报告不覆写，新提交与 append-only 交接记录修正。
- 最终 deliverable commit 由本票新 handoff 精确绑定；本文随源码提交，不用未提交状态作为跨代理输入。

## 修改范围

| 文件 | 职责 |
| --- | --- |
| `quant_shared/strategy_delivery/models.py` | 包 v2/校验器 v2；必填规范结算币种与账户精确匹配 |
| `backend/app/services/candidate_delivery_sources.py` | 既有固定 Donchian 与兼容 Qlib 来源明确 USDT；未知来源不推断币种 |
| `tests/contracts/test_strategy_delivery.py` | 缺失/非法币种、USD 绑定、账户漂移、旧 v1 拒绝 |
| `tests/contracts/test_candidate_delivery_api.py` | 真实冻结来源字段；原 Donchian USD 拒绝/USDT 正向流程；Qlib blocker 保留 |
| `frontend/src/workspaces/research/CandidateDelivery.tsx` | 按钮、登记状态、回执仅说明候选管理目录，不暗示已接运行 |
| `frontend/scripts/test-candidate-delivery.mjs` | 对应文案回归 |
| `docs/architecture/candidate-runtime-handoff.md` | 目录边界与 v2 币种合同说明 |
| 本报告及本票新 handoff | 审查、验证与交接证据 |

## 行为合同

`settlement_currency` 是包必填身份字段：大写字母开头、2–16 位大写字母/数字；不从 instrument 后缀猜测，不 trim 或把 USD 转成 USDT。账户 `currency` 必须精确等于包结算币种；缺失/异常包返回 `settlement_currency_invalid`，误配账户拒绝为 `account_settlement_currency_mismatch`。

现有 bind/review/register/resolve 调用同一账户校验，不修改状态机或 SQLite 算法。币种纳入现有完整包摘要，绑定后的账户币种变更也重新验证，失败事务不增加登记记录。USDT 账户正向流程保留。

包 schema 升为 `strategy_delivery_package_v2`，validator 为 `strategy_delivery_validator_v2`。旧 v1 不补默认币种、不自动升级或继承审定；历史记录仍可只读查看，新绑定/审定/登记/解析须通过当前版本验证。旧记录不能凭旧通过状态绕过验证。

前端明确：“登记到候选管理目录”“已登记候选管理记录 · 未接入运行入口 · 未启动”。没有增加入口、布局、账户采集、运行控制或交易权限。

## 本轮验证

失败优先：修复前新增币种用例 **15 failed**；前端原 5 项通过、新文案断言 1 项失败。既有非空检查部分拒绝 malformed 账户，但未按结算合同拒绝 USD，新增用例完整复现该缺口。

在本票工作树，`QS_BACKEND_EVIDENCE_PROFILE=research_readonly`：

```text
<main>/.venv/Scripts/python.exe -m pytest -q tests/contracts/test_strategy_delivery.py tests/contracts/test_candidate_delivery_api.py tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_strategy_registry.py -p no:cacheprovider --tb=short --basetemp <TEMP>/qs-currency-after-20260924
72 passed, 1 existing Starlette/httpx deprecation warning, 19.80s

node --test frontend/scripts/test-candidate-delivery.mjs frontend/scripts/test-candidate-handoff.mjs
20 passed

frontend/node_modules/.bin/tsc.cmd --noEmit
passed

frontend/node_modules/.bin/vite.cmd build
passed; 5270 modules; 47.03s; existing large-chunk warning
```

类型检查与生产构建均通过；独立复核尚待提交后进行，结果另记。不启动开发服务器或工作树预览。不重复之前 37 项 V1/V3 离线执行测试（没有修改执行链），不把旧测试计为本轮新结果。正式服务/浏览器验收和运行消费未执行。

## 治理、证据与剩余限制

已读 quant-agent-preflight / quant-agent-handoff、shared/super_developer playbooks、knowledge README/non-negotiables/source-map/domain architecture、delivery risk policy；context packet role=super_developer，scopes=shared,research,btc。

Catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。适用 IDs：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-HANDOFF-001、GOV-ROOT-001、GOV-WORKTREE-001、GOV-STORAGE-001、GOV-ENGINEERING-CIRCUIT-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-PROMPT-001、GOV-WINDOWS-001、QSYS-GATE-001、QSYS-SECURITY-001、REPLAY-ISOLATION-001、BACKTEST-COST-001、RESEARCH-HOLDOUT-001。未扩大历史事故排查。

只有测试临时 SQLite；未创建或修改生产管理目录、manifest、研究封存、账户或经济账本。证据仅对应本票修复提交，不是当前 main 的运行/晋级证据。

下一步由独立 reviewer 仅复核这两项与相关拒绝边界；未来若要合入，仍须独立 integrator 和另行发布验收。本轮不消费旧被拒绝候选的 ready 状态。管理能力仍默认关闭，既有运行入口不消费候选管理目录；Qlib 原研究有效性阻断保留。

`demo_control_enabled/execution_permission/runtime_observed/promotion/paper/live/private/order/real_order/transfer/withdraw=false`。`research_readonly` 未改变；未访问交易所/密钥，未启用 Demo/paper/live。源码修复不授予任何交易或晋级权限。

## 提交后独立复核结论（最终）

主会话记录只读 `quant_architect` 子任务 `candidate_delivery_independent_review` 的独立返回；不是原作者自审。被审源码：`891d79f316d3850a80578ae132a670a476d4e02b`；交接提交：`6109fdde17c7604e2e53d7fae2574bb7f5a9d6da`；事件：`candidate-delivery-currency-fixed-20260924-03`。

独审校验提交亲缘、handoff valid、三项交付 SHA-256 MATCH，canonical/producer 限定路径均 clean；main 仍是 `55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`。

**结论：原 P1/P2 均关闭，本范围内无新阻断，源码限定修复通过。** v1 包在 `_fresh` 中因来源升级触发 `package_changed`，或在仍返回同一 v1 时触发 `package_admission_blocked`；管理文案不再暗示可启动。可以交给独立 integrator，但本轮没有集成或发布授权，不继续自动合入。

### 独立命令与结果

`PYTHONDONTWRITEBYTECODE=1`，`QS_BACKEND_EVIDENCE_PROFILE=research_readonly`，使用 main `.venv/Scripts/python.exe`，临时 `--basetemp <TEMP>/candidate-currency-rereview-<uuid>`：

```text
python -m pytest -q
 tests/contracts/test_strategy_delivery.py::test_package_currency_must_be_explicit_and_canonical
 tests/contracts/test_strategy_delivery.py::test_account_currency_mismatch_rejected_before_bind
 tests/contracts/test_strategy_delivery.py::test_account_currency_drift_rejected_at_each_boundary
 tests/contracts/test_strategy_delivery.py::test_legacy_package_without_currency_is_not_silently_upgraded
 tests/contracts/test_candidate_delivery_api.py::test_committed_donchian_spec_compiles_without_inference_or_network
 tests/contracts/test_candidate_delivery_api.py::test_real_frozen_qlib_stays_blocked_without_training
 tests/contracts/test_candidate_delivery_api.py::test_real_rule_registers_and_resolves_to_existing_history_spec
 -p no:cacheprovider --tb=short --basetemp <TEMP>/candidate-currency-rereview-<uuid>
18 passed, 1 existing Starlette/httpx warning, 3.60s

node --test frontend/scripts/test-candidate-delivery.mjs
6 passed, 0 failed
```

上述是原测试子集的独立复核，不与生产者 72/20 相加为不同测试总数。独审没有重跑生产者全套、类型检查、构建、长离线测试或浏览器。

额外的历史已登记 v1 临时 SQLite 探针输出 `legacy_v1_resolve=blocked, error=package_admission_blocked`，但因 Windows 临时文件清理阶段 `WinError 32` 非零退出，**不计为通过的测试**。残留目录：`C:/Users/李烁18353780778/AppData/Local/Temp/candidate-v1-rereview-31h75ubf`；删除尝试被平台拦截，未再清理，不在仓库、生产管理根或经济账本内。不能把业务拒绝输出当作整个探针成功。

独审 role=architect，读取 shared/architect playbooks、preflight/handoff、AGENTS、knowledge README/non-negotiables/source map/domain architecture/delivery policy，同一 catalog；未修改源码/报告/Git/服务，未接触交易所、账户或密钥。

最终限定交付：本票源码修复通过独审；主版本未变，候选管理仍未启用，运行目录消费仍未实现。所有上述安全旗标继续为 false。以后合入由独立 integrator 负责，发布/启用另行审定；本轮至此结束。
