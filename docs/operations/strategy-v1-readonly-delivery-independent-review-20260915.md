# STRATEGY V1 只读交付治理独立审查

- 基线：`b920d131e41ecbfe7f76f0709affbe22c8b35f5e`
- 前一审定 source：`6861a653bea3903670ad7b1b359d30d1e682cbfc`
- 本次 source：`202379a65d0956769a3c38df69db9658aa8f00e2`
- published handoff：`96cd540da4500983c60dda00f8a63da42e65d728`
- change risk：`governance_control`
- catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

## 结论

通过限定治理独审，可进入独立集成；未集成 main、未激活新规则、未启动服务。

精确增量仅为四个治理文件：策略只读交付 policy JSON、校验器、说明和测试。新增准入仅允许精确路径 `quant_crypto/portfolio/decision.py` 与能力 `reduce_only_signal_forecast_source_identity_binding`；同时禁止 `quantity_economics`。相邻 portfolio、risk、permissions 路径仍拒绝；旧 change-risk 类别、Hook、启动器和交易权限未放宽。所有 Demo、promotion、paper、live、private、order、real order、transfer、withdraw、execution、runtime worker/observed 旗标仍要求为 `false`。

## 验证

- handoff 工具：`valid`；base 与前一 source 均为本次 source 祖先；提交态 deliverable hash 由校验器验证。
- 独立环境：网络 socket 禁用、独立 TEMP/TMP、pytest cache 禁用、根 logger 使用 `NullHandler`。
- 完整限定矩阵：`141 passed in 65.42s`。
- 未运行：业务源码、后端／前端、浏览器、账户、凭据、broker／exchange、private／order／live。

初次尝试只 cherry-pick 末端增量时因其依赖前一审定 source 发生预期冲突；在本任务自有清洁工作树中中止该尝试后，改为 fast-forward 到已验证的提交态 source tip，再 fast-forward published handoff。未手工改写 producer 文件，未覆盖其他代理修改。

## 保持阻断

- main 集成与新上下文激活仍待独立执行。
- V1 Donchian 业务 source 仍须单独高风险审查；本报告不证明纵向闭环完成。
- 只读页面发布和正式页面验收尚未发生；本治理变更不授予 Demo、paper、live 或交易权限。

## REDUCE_ONLY 动作投影增量

- source：`3d64b5c433c2c05498aa6e1c94014e9e473552cb`
- published handoff：`b1cbc46b5b87854423af46449dc6d6a3ec973f86`，校验为 `valid`
- 精确治理增量：只新增能力 `reduce_only_runtime_action_projection` 及其文档／测试；未放开共享 `PermissionEvaluator`、真实 `CANCEL_ONLY`、账户、Risk、连接、ledger、启动器、Hook 或交易权限。
- 独立禁网、独立 TEMP/TMP、禁用 pytest cache、根 logger `NullHandler`：`149 passed in 65.66s`。
- 结论：该限定治理增量通过独审，但尚未集成 main、未激活，不能证明业务映射已修复或 V1 已完成。
