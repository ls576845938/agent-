# Candidate market policy readonly integration review

- 票据：`CANDIDATE-MARKET-POLICY-READONLY-DELIVERY-20260928`
- 角色：独立 integrator
- 治理累计提交：`7f3788f8c80da74c9d256120ebc0c99c702805e6`
- 源码审查提交：`f2f8c77b3778bab29fada79612b78df633a8900d`
- 冻结业务 SOURCE：`4deb1e57ef3b98d08a3ae7b70e171d65f364ebcc`
- identity 派生基线：`f2f8c77b3778bab29fada79612b78df633a8900d`
- identity fingerprint：`77abe7330f4ddd89c6c25d1f13a2e46a8b4225bfa6eea50421b4045000373aec`

## 集成结论

已将更正后的一次性治理提交按已审定提交链集成到累计候选，未修改 86 个冻结业务文件、通用风险规则、hooks、启动器、认证、交易权限或 A/B 封存事实。

`frontend/public/frontend-identity.json` 由现有 `npm.cmd --prefix frontend run identity:refresh` 生成，它是唯一派生文件；不手工编辑指纹或启动器。本提交仅证明源码与派生链可发布，不代表服务已切换或页面已验收。

## 验证摘要

- corrected governance handoff 通过 Git 对象校验，且工作树限定路径 clean。
- `validate-source`：`status=valid`、`blockers=[]`。
- 限定治理回归：`22 passed in 65.75s`。
- `a7a8…` 到当前候选的两份已封存性能交接 blob 保持一致。
- identity 生成命令只修改 `frontend/public/frontend-identity.json`，baseline 绑定源码审查提交。
- 初始限定 dirty 为 0；未覆盖他人改动。

## 发布前后的明确边界

发布前仍需要：最终 source-review receipt 校验、精确回退 tag、main 只读快进、官方入口重启、8765/3000 双 identity 与真实页面 12 秒同页验收。正式页面冲突、BTC 503、A/B blocked 和空候选目录必须如实显示，不能用 fixture 或放宽超时替代。

以下安全旗标保持 `false`：`candidate_management_enabled`、`management_write_enabled`、`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_worker_enabled`、`runtime_observed`。

