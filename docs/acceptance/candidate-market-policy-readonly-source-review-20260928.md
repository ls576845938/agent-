# Candidate market policy readonly source review

- 票据：`CANDIDATE-MARKET-POLICY-READONLY-DELIVERY-20260928`
- 角色：独立 integrator
- change_risk：`unclassified`（沿用冻结 SOURCE 的最严格交付路径）
- main 基线：`770392bacab55596da3238b1815af4476866f0de`
- 冻结业务 SOURCE：`4deb1e57ef3b98d08a3ae7b70e171d65f364ebcc`
- 审定治理累计提交：`7f3788f8c80da74c9d256120ebc0c99c702805e6`
- 被更正、不单独消费的初版 deliverable：`10d1e716b052062a69bb8ccd6836306a879cd65e`
- 最终治理 deliverable：`0fae8a39cd43993edcd362724b148e1eab58c73f`
- 最终治理 handoff：`33201a0ee5ceb78bba60cba2d66be99f2ddbe7e2`

## 独立结论

SOURCE 与一次性 `research_readonly` 治理边界通过源码审查，可进入后续集成回执、identity 派生与正式发布验收。这个结论只是 `quality_checked` 的源码结论，不是页面验收、策略有效性、promotion、Demo、paper 或 live 放行。

审查使用了已有高风险 closeout 和本轮 UI/性能 handoff，没有声称重新通读全仓。合同只允许 86 个冻结业务路径、5 个本票治理文件、3 个精确报告路径、2 个本票 handoff 前缀和既有 identity 派生文件，不放宽通用发布规则。

## 关键证据

1. `validate-source` 在累计集成树上返回 `status=valid` 且 `blockers=[]`，完整核对 base→SOURCE 的路径、blob、mode、SHA-256 和 3 份指定 handoff。
2. 独立使用 canonical Python 运行限定治理回归：`22 passed in 65.75s`。
3. 实际 SOURCE `4deb…` 到累计集成 `a7a8…` 仅包含合同已验证 `post_source_integration.delivery_chain_paths` 的两个精确文件；同旧票目录中未登记事件继续被拒绝。
4. 两份性能交付事件在 `a7a8…` 与当前治理累计提交之间 Git blob 完全一致：
   - performance correction blob `2c28d9a3bbc5f3b7d5155fea92ae074225e59f14`
   - integrated performance blob `0862538586c2f6bce36998bb64b5445569aab432`
5. 更正后文档保留精确 gate impact：旧高风险 closeout=`blocks_gate`，UI/性能=`none`；三者均 `promotion_eligible=false`。
6. 注册表 summary 仍执行原完整性与冲突检查；Qlib manifest hash 只复用当次请求内已验证结果，没有引入跨请求 Windows ctime 信任缓存。形式页面预算仍是 12 秒，未延长超时来制造通过。

## 保留的 blocker 和安全边界

- 真实 A/B 仍是 baseline `2960/2960` 完成、conditioned `1956/2960` 因单根 K 线内保护价双触发顺序模糊而 fail-closed；末端空头 `-0.01` 张保留且已核账，不声称有完整政策效果结论。
- 候选目录当前仍为空；旧 M1 v2 可进行限定诊断管理，但不等于通用 factory worker 可运行。
- `candidate_management_enabled`、`management_write_enabled`、`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_worker_enabled`、`runtime_observed` 都必须保持 `false`。
- 正式 main、8765/3000 双 identity、真实 12 路同页刷新和页面按钮验收尚未执行，不在本源码报告中提前写为通过。

## 审查范围与冲突

初始限定 dirty 为 0。第一次直接 cherry-pick 更正提交时，因其依赖初版治理文件而出现预期的 modify/delete 冲突；已在本专属集成工作树内 abort，然后按已审定的完整提交链顺序合入，没有覆盖他人文件。初版 handoff 仅作为被 correction supersede 的 append-only 历史保留，不作为最终审定授权依据。

