# M1 有限结项与 M2 样本准入：独立集成审查

日期：2026-09-12；票据：`M1-CLOSEOUT-M2-VALIDATION-INTEGRATION-20260912`；角色：`integrator`；change_risk：`research_readonly_release`。

## 审查结论

生产者交付已从 base `2eafaf5220a5527962874e02fc04c1674e379ce8` 在 planner 创建的独立 sparse worktree 中验证并顺序集成。交付提交为 `c3a1f0b7779d175327d961aa6cd4555c2cb8d116`，最终生产者提交为 `d9fc499dc5d38cb9c49d96194935796503f734f4`；published handoff 的 ancestry、路径、SHA-256 和 schema 均经独立校验有效。

M1 可以按原始目标做**有限工程结项**：资产中性的历史因果环境旁路、版本化证据关联、默认 BTC 行为冻结以及研究只读页面兼容均已形成提交态保护。本结论不等于 Alpha 有效、全仓无债、运行环境完整或具备交易权限。

M2 仅接受为不可执行的预注册协议和输入准入审查。独立只读研究复核没有找到经核验、适用于本轮 OKX `BTC-USDT-SWAP` 1h 的独立确认样本；因此 `fit_count=0`、`performance_evaluated=false`，不运行 A/B、不采集数据、不启动 M3/M4。

## 集成范围与独立审查

生产者 touch set 限于：

1. `frontend/e2e/research-layout.spec.ts`
2. `frontend/scripts/test-research-portfolio-contract.mjs`
3. `docs/operations/m1-closeout-m2-validation-20260912.md`
4. `docs/research/m2-trend-environment-protocol-20260912.md`
5. `docs/research/m2-trend-environment-input-audit-20260912.json`
6. `.agent/handoffs/M1-CLOSEOUT-M2-VALIDATION-20260912/published-m1-closeout-m2-validation-20260912-c3a1f0b77.json`

上述路径初始 `safe_status=clean`，cherry-pick 无冲突；没有覆盖或撤销其他工作树的修改。审查确认：

- 页面测试改用确切标题定位两个独立 details，并同步已发布折次标题；没有删除 guard，也没有重置整份 baseline。
- 冻结合同仍锚定旧 rollback base `13486a7802628e93dd624213ba6c317c5deb4ddf`，只放行已存在的一个 Qlib pipeline helper，并用负对照拒绝 endpoint 漂移、旧方法改名和额外 submit。
- CSS 校验按 media、selector 和 declaration 比较，只允许三处已审 sticky padding 变量替换，并保留标题样式突变负对照。
- M2 固定为同一 OKX 1h 数据合同下的 13 个 OHLCV 特征对照与增加 15 个 M1 环境字段实验，最多 2 臂 × 4 折 = 8 次 fit；但所有拟合必须等独立输入、用途可见性和精确切分先行封存。
- `frontend/src`、后端、量化域、配置及 `frontend/public/frontend-identity.json` 相对 base 均无差异，因此未凭空刷新 identity。

## 独立验证

| 检查 | 结果 |
| --- | --- |
| `npx.cmd --no-install playwright test e2e/research-layout.spec.ts e2e/alpha-factory.spec.ts e2e/m1-archive-compat.spec.ts --workers=1 --reporter=line --output=output/playwright/m1-closeout-integration` | **27 passed / 1.7m**；全部 `/api/**` 使用既有 mock，未启动 worktree 前端 |
| `node frontend/scripts/test-research-portfolio-contract.mjs` | PASS |
| `node frontend/scripts/test-trend-environment.mjs` | PASS |
| `node frontend/scripts/test-m1-archive-compat.mjs` | PASS |
| `node frontend/scripts/test-research-rollback.mjs` | PASS |
| `npm.cmd --prefix frontend run lint` | PASS（`tsc --noEmit`） |
| `pytest ... test_trend_environment.py test_trend_environment_sidecar.py test_m1_btc_behavior_freeze.py` | **25 passed**；1 条既有 Starlette/httpx2 弃用警告 |
| `pytest ... test_strategy_decision_context_v1.py ... test_btc_okx_demo_runtime_hardening.py` | **169 passed** |
| `pytest ... tests/api/test_m1_research_readonly_archive.py` | **11 passed**；1 条既有 Starlette/httpx2 弃用警告 |
| `git diff --exit-code 2eafaf52..HEAD -- frontend/src backend quant_crypto quant_shared integrations configs frontend/public/frontend-identity.json` | PASS，无业务源码、配置或 identity 变化 |
| `git diff --check 2eafaf52..HEAD` | PASS |

定向 Python 保护矩阵合计 **205/205**。浏览器矩阵为本票约定的 27 项，不表述为全仓所有前端测试均已执行。

## M1 有限结项与遗留边界

原四组验收现可形成闭环：

- 因果/资产中性：25 项环境估计、sidecar 与默认行为冻结通过；未声称 US/CN 已有真实市场验证。
- 兼容/行为保护：169 项 Context、composition、risk、portfolio/exit、Guardian、OMS 和 runtime hardening 合同通过；不把组件合同冒充交易所 fill E2E。
- 生产者/证据/API：11 项 M1 research-readonly archive API 加上既有封印、manifest 与 provenance 证据保持 fail-closed。
- 安全/前端：旧 5 项 UI 断言债务已关闭，三组 canonical mock 页面矩阵 27/27；先前正式页面对普通 M1、Factory 四折、missing、旧 local run 与恢复场景的验收继续作为增量证据。

以下事项不阻止 M1 按既定范围结项，但仍必须明确保留：历史重建/`source_stale` 语义；Factory rejected、0 candidate；BTC runtime artifact root 503；已登记的四类执行安全疑点；无真实成交；全仓未做无限制全量回归。它们没有被本票修复，也不会自动转成新工程循环。

## M2 准入阻断与安全状态

当前可直接绑定的 OKX 1h 时段已经用于普通 Qlib、M1 与 Factory；hash 正确不等于未见。其他 Binance spot 或 5m 候选锁不能替代同市场确认集。计算前仍缺：

- 同市场不可变 manifest、aggregate、文件 hash 与 PIT/时钟核验；
- 独立用途/历史曝光记录和精确 train、valid、4 个 test、purge/embargo、warmup 切分；
- 数据所有者与研究复核者对确认集的先行封存；
- 通过审查的最小离线 A/B 绑定。

因此协议停在 `independent_okx_1h_confirmation_window_not_verified`，没有效果结论。`promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 全部为 false；M2 研究完成也不授予交易权限，M3/M4 未启动。

## 治理与交付状态

- 读取并遵循：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role、`research_readonly_release`、quant preflight/handoff skills。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。未全文读取原事故日志。
- 本票无新 dataset、artifact、manifest、ledger、latest、schema 或服务变更。readiness 上限为 `quality_checked`，gate impact=`evidence_only`。
- registered main 的发布、`research_readonly` 重启与发布后身份核验由主会话在用户限定授权下单独执行；本集成工作树不修改 main、不启停服务。
