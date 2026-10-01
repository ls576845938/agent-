# Candidate market policy readonly governance producer record

- 日期：2026-09-28
- 票据：`CANDIDATE-MARKET-POLICY-READONLY-DELIVERY-20260928`
- 角色：`super_developer`
- change_risk：`governance_control`
- base：`770392bacab55596da3238b1815af4476866f0de`
- readiness：`quality_checked` 上限；SOURCE 已封存，治理独审与正式部署仍 blocked

## 范围与结论

仅新增本票 JSON/Markdown 合同、只读 CLI 校验器、合成 Git fixture 测试和本记录；未修改业务源码、通用风险策略、枚举、hooks、启动器、认证、安全、权限或执行语义。

规则将旧源、UI 独立集成、性能独立集成和最终累计 SOURCE 约束为有序 ancestry，并对 base→SOURCE 的完整路径、Git blob/mode、SHA-256 及指定 handoff 做精确校验。4 个 `quant_crypto/application/` 离线接线文件必须精确出现，不使用目录白名单放行后续业务变化。

源码独审与正式发布验收是两个 receipt phase。正式 phase 强制 current main、8765/3000、双 identity、`research_readonly`、真实 canonical 页面回执和安全旗标；`candidate_management` 或 mock 回执必定失败。治理/报告/本票 handoff/现有 identity 派生以外的 post-source delta 必定失败。

## 当前精确 blocker

SOURCE 已精确封存为 `4deb1e57ef3b98d08a3ae7b70e171d65f364ebcc`。合同完整列出 base→SOURCE 的路径、blob、SHA-256、mode、分类，并强制验证三条提交态依赖：旧高风险 closeout `deace3f2b`、UI 集成 `833dec6f1`、性能集成 `9ad0277b3`。closeout 中 A/B blocked、conditioned `-0.01` 持仓及其他 blocker 原样保留。

当前 blocker 是：本治理 deliverable 尚待独立 integrator 审查和集成；正式 current-main 切换、research_readonly 重启、8765/3000 identity/health 与 canonical 页面验收均未执行。

## 验证结果

- `py -3 -B -X utf8 tools/agent_governance/candidate_market_policy_readonly_delivery_20260928.py --repo-root . validate-source`：exit 0，`status=valid`、`source_sealed=true`、`blockers=[]`。真实读取精确 86 文件 inventory 及 3 个指定 handoff；未扫描或修复其他历史 handoff。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider --basetemp <unique-temp> tests/agent_governance/test_candidate_market_policy_readonly_delivery_20260928.py`：`20 passed in 73.27s`。
- failure-first 覆盖：未封存、祖先链漂移、增删路径、blob/mode、SHA-256、handoff readiness/blockers、receipt 多余字段、非 literal boolean、`candidate_management`/mock 冒充正式验收、宽泛业务 delta、通用风险策略漂移。

独审更正：receipt 的 SOURCE→governance 阶段现在只额外接受已封存 `post_source_integration.delivery_chain_paths` 中的两个精确路径，即性能 correction 与 integrated event；不放开其旧票目录。真实 `4deb…→a7a…` Git 拓扑正例与同目录未登记事件负例已加入，最终回归为 `22 passed in 80.11s`；真实 `validate-source` 再次为 `valid`、`blockers=[]`。

封存后的独立 integrator 仍需审查治理提交和完整 source diff；主会话随后才可按正式只读发布流程切换、重启并采集真实页面验收。当前工作树不合 main、不启动服务、不创建回退 tag。

## 明确保留的 fail-closed 状态

`candidate_management_enabled=false`、`management_write_enabled=false`、`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_worker_enabled=false`、`runtime_observed=false`。

这些值是合同要求，不是缺失证据时的推定。deployment receipt 必须由正式报告支持；缺证据不得写成通过。本票不生成 promotion artifact，不改变 A/B blocker、现存 conditioned 持仓、ledger 或任何运行状态。
