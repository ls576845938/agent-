# BTC 共同账户组合入口验收

票据：`BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004`

## 必须通过

- 单策略 v1 identity/job/result/decision 精确兼容，既有 hash 算法不变。
- 组合作业 identity 由完整 canonical 两成员 authority、共同账户、各自输入、预算、event clock、执行 HEAD 和 catalog hash 生成。
- 只接受两个不同登记、Donchian + Qlib 精确 adapter 集合；两登记保留各自源账户，另由 proposal/review 显式审定第三个 v3 共同经济账户与精确 5000 USDT 初始权益。
- proposal、人工 review、start 是三个独立命令；approved binding 事件 append-only，start 只能引用 binding ID/digest/revision，不能覆盖成员、输入、预算或共同账户。
- 永久 reserve account/state 与两个 registration/member authority；重复 start 不产生另一作业。
- 每成员 input revision/digest/head/evidence kind、package/source/binding/adapter 均固定；共同 price/mark/index/funding 冲突拒绝。
- 当前精确 Donchian/Qlib pair 因原执行合同不兼容而 fail-closed：Donchian t+1 与 Qlib t+2 delayed-open 加方向成本不能压成一个共同订单，`cohort_member_execution_policy_incompatible` 必须在市场、资金、Risk、OMS 等经济副作用前返回。不得以统一延迟或统一填价伪装兼容。
- 当前原保护合同也不兼容：Donchian 100/200bps 与注册 Qlib 400/800bps 的 policy_id／参数／完整 hash 不同，必须保留 `multi_strategy_cohort_protection_policy_incompatible`，不得统一 hash 或改包退出参数。
- 若未来存在执行合同兼容的精确 pair，空仓仍只允许两个 long 成员同时开仓；非空仓只允许各自 hold/reduce。short、冲突、increase、reverse、保护不兼容或不完整证明在经济动作前阻断。
- 显式成员预算合计不超过共同 `50 USDT` 名义和 `10 USDT` 亏损上限；预算不足拒绝，不缩放 target，无默认 25/25。
- delta-zero 只提交 decision/member state/cursor，不签发执行 context。
- 所有非零经济动作复用同一 DonchianOfflineReplay controller、venue、原 Risk/OMS/Fill/Funding/Ledger UOW。
- committed-ledger-before-projection 的 sealed-authority 修复逻辑已实现并对 allocation plan、成员归属、order/fill 与时间证明 fail-closed；但由于当前真实 pair 在新决策前即被执行合同阻断，本票不得宣称完整真实双成员经济恢复已经验收。
- hosted protection 触发但缺成员归属回执时 fail-closed 并保留现场；本票不宣称该触发恢复用例已支持。
- GET list/status/result 保持只读，不构造 controller、不 reconcile、不创建目录。
- API、页面和 SSR 对混合 identity、未知 schema、成员归属不守恒均拒绝；页面显示真实能力、失败、共同状态和成员归属。

## 证据限制

- synthetic fixture 仅能证明合同与恢复工程，不是实际候选、研究通过、promotion、paper 或 live 证据。
- 当前真实 Qlib final 包缺失时，真实组合入口必须显示 blocked。
- 旧 R3 诊断模型不是 final model，不能登记。`2026-09-25T00:00:00Z` 是 R3 audit 的右开结束边界，不是新独立窗口起点。以后续未参与选择规则的数据、完整标签、新不可变 manifest 与原冻结有效样本算法（包括 12 小时标签重叠处理）核算；现有证据仅支持独立有效样本不足 30，没有确定达标日期，也不能宣称独立确认。
- 本票不启动工作树 Vite，不部署、不重启 main 服务、不做正式 browser/current-main 验收。
- promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed 全部保持 `false`。

## 计划验证

- 既有 candidate-offline 五个剩余生命周期节点，同次串行，原等待窗口不缩短。
- 新 cohort contract/integration/API：identity、账户、币种、版本、重复 start、stop/resume、ledger commit 后 crash、partial/protection 阻断、归属守恒、GET 无副作用。
- TypeScript `tsc` 与相关 frontend 静态/SSR 测试。
- `git diff --check`、scoped safe status、deliverable commit、append-only handoff validate。

## 明确不运行

- 真实 Qlib 训练/重训、数据采集或扩窗。
- private/order/live endpoint、真实订单或账户读取。
- 用户已授权限定 `research_readonly` 集成发布，但仍待独立审查且本票未执行；main merge、push、部署、backend restart、正式 browser acceptance 均为 `not_run`。该授权不开放 candidate-management write、offline tasks/accounts、Demo、private/order/live。
