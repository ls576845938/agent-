# 候选市场策略离线接线的一次性只读交付合同

本合同仅适用于 `CANDIDATE-MARKET-POLICY-READONLY-DELIVERY-20260928`。它补足旧候选管理特例未覆盖 4 个 `quant_crypto/application/` 离线执行接线文件的问题；不修改通用 `delivery_risk_policy.json`、风险枚举、hooks、启动器、认证、安全或执行代码，也不成为后续发布的通用豁免。

## 当前状态：源码已封存，治理独审与部署待完成

JSON 已冻结基线 `770392bacab55596da3238b1815af4476866f0de`、旧高风险源 `8ea90775bc250ad4cfcab7592fbdc720b3df4edc`、UI 独立集成 `8e120f7d4de92bcbde97edb9c5d34b34cce0a911` 与最终累计业务 SOURCE `4deb1e57ef3b98d08a3ae7b70e171d65f364ebcc`。同时绑定旧高风险 closeout、UI 集成和性能集成三个有效 handoff；blockers 原样保存，不因治理封存被消除。

本合同只接受该累计 SOURCE，并从上述 main 基线冻结：

- 严格有序的 Git 祖先链；
- 完整且完全相等的变更路径集合；
- 每个文件的 Git blob、mode 和原始字节 SHA-256；
- 恰好 4 个 `quant_crypto/application/` 文件，均标为 `offline_execution_wiring`；
- 本次指定的提交态 handoff，其 envelope、deliverable hash、schema、readiness、blockers 和 gate impact 均按合同精确冻结：旧高风险 closeout 为 `blocks_gate`，UI/性能集成为 `none`；三者均须 `promotion_eligible=false` 并通过仓库 handoff 校验器。

历史无效 handoff 不遍历、不修复，也不自动阻塞本票；只校验最终合同显式列出的审定依赖。

## 两阶段，不能互相替代

### `source_review`

高风险源码审查与正式部署分开。源码阶段要求治理提交、独立源码审查报告、独立 integrator 报告均为不同提交，并验证报告原始字节 hash、Git 亲缘、冻结源码未变。源码之后只允许：本票 5 个治理文件、精确的 3 个报告路径、本票两个 handoff 目录，以及通过现有 `identity:refresh` 命令产生的 `frontend/public/frontend-identity.json`。不允许再修改任何业务源码。

`source_review` 的上限是 `quality_checked`；它不是当前 main 发布、页面验收、promotion evidence 或任何交易权限。

### `deployment_acceptance`

正式验收额外要求：

- 注册 `refs/heads/main` 精确等于 receipt 的 target commit，回退 ref 精确指向基线；
- 官方入口重启后的真实 8765/3000 注册 listener；
- backend/frontend identity 都绑定同一个 current-main target；
- `/api/health` 真实为 `research_readonly`、`status=ok`、`read_only=true`、`controls_disabled=true`；
- canonical、非 stale、非 mock 的真实页面回执；
- 管理写入不启用、不创建管理存储，所有合同列出的安全旗标有证据地保持 false。

现存 `candidate_management` profile 的 8765 健康回执不能复用为本票验收；mock、fixture 或源码阶段报告也不能替代 8765/3000 正式回执。缺字段就是 blocker，不补造 `false`。

## CLI

```powershell
py -3 tools/agent_governance/candidate_market_policy_readonly_delivery_20260928.py --repo-root . inspect-contract
py -3 tools/agent_governance/candidate_market_policy_readonly_delivery_20260928.py --repo-root . validate-source
py -3 tools/agent_governance/candidate_market_policy_readonly_delivery_20260928.py --repo-root . validate-receipt --input <receipt.json>
```

CLI 只读 Git 和提交态 JSON/报告，不合并、不创建 tag、不刷新 identity、不启动服务、不访问 private/order/live endpoint，也不生成训练、恢复、管理写入或交易证据。退出码 `0` 仅表示所选检查无 blocker；`1` 会输出精确 blocker 数组。

## 保持不变的边界

- 不训练、不恢复、不执行候选管理写入，不开放 Demo/paper/live/private/order/promotion/transfer/withdraw。
- 不要求重建旧交易或 promotion artifact；本票 `promotion_artifact_rebuild_required=false`。
- BTC 生产 503/未配置可以在真实只读页如实显示，不得伪造 ready。
- 现有 A/B `blocked` 与 conditioned 1956/2960 的 `-0.01` 持仓事实原样保留，不属于本治理票的修复或晋级条件。
- `frontend/public/frontend-identity.json` 只允许既有 `identity:refresh` 的派生增量，不修改算法。

owner=`quant_architect`；一次性有效。源码、路径、hash、handoff 或部署目标任何漂移都必须另开审定，不能修改 receipt 绕过。
