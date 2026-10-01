# V3 限定只读交付治理候选（2026-09-20）

状态：治理源码候选，等待独立 integrator；尚未合入 main、启动服务或验收页面。用户授权仅补齐 V3 离线只读交付，独审通过后发布审定提交，保留回退点；不新增交易语义、修改启动器或权限。

## 边界与基线

- role super_developer；change_risk governance_control。
- base/source aca55c90d82b327800e473774e22dbbeac69bd90；注册 main b920d131e41ecbfe7f76f0709affbe22c8b35f5e。
- planner 专属 sparse 工作树 super_developer-v3-readonly-delivery-20260920；初始 scoped dirty clean；无他人文件覆盖。
- touch set：delivery_risk_policy.json 的独立 strategy_v3_readonly_delivery 键；独立 strategy_v3_readonly_delivery.py 校验器及测试；同名规则文档；本报告；strategy-v3-readonly-source-20260920.json；本票 .agent/handoffs/V3-READONLY-DELIVERY-20260920/**。
- 不修改旧 change_risks、V1 合同、业务代码、页面或启动器。88 个上游净差异的 committed blob hash 被固定，独审必须检查完整累计差异。
- 既有 V3 最终独审 report SHA-256 202f6940f6472b1fdcea6bd631abcebcd4df852948f75b1bd8ff25b829a502c7；既有 acknowledged handoff 已 validate=valid。源码独审不等于本治理或正式发布完成。

## 实现和测试

新规则保留执行接线的 demo_execution_semantics 高风险审查，部署限定 research_readonly；固定 source/baseline/profile/ticket；检查 literal bool、原始 Git blob hash、完整 touch set、祖先、审后源/治理不变、当前 main 与精确回退标签。校验器只读且不授予权限。独立报告必须为提交态并核验摘要；checks 必须有实测报告支持，不能用 JSON 声明替代独立审查。

使用 canonical .venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --tb=short：

- failure-first 新测试 14 failed / 1.04s，原因未实现模块。
- 初始新测试 17 passed / 13.97s。
- 首轮六文件兼容矩阵 141 passed / 1 failed / 26.56s，失败为 sparse 未包含 quant_crypto，team_context 导入失败；补齐只读源码 cone 后该用例 1 passed / 3.64s。
- 六文件兼容矩阵重跑 142 passed / 15.52s：test_strategy_v3_readonly_delivery.py、test_strategy_v1_readonly_delivery.py、test_research_release_policy.py、test_delivery_policy.py、test_context_packet.py、test_governance_contract.py。
- 随后新增审后治理文件漂移/报告摘要错误两项负向回归 2 passed / 0.08s。未声称这些分段运行是一轮144项。
- 本票未重跑旧52项业务矩阵、CLI、服务、页面、真实交易所或账户。既有真实结果维持51通过/1 HEAD污染失败与独立固定HEAD五项复验，不写成52/52。

## 后续独审/交付

独立 integration 票据 V3-READONLY-DELIVERY-INTEGRATION-20260920，新上下文从已提交治理交接启动，验证全部 source hashes、上游交接和不变的旧规则，运行有限回归。通过后，仅将已审源码及治理/独审提交快进主版；创建非覆盖标签 codex/v3-before-readonly-20260920。正式入口与页面只能在 canonical main。离线CLI首跑/恢复保持HEAD固定，不在运行中提交；现有候选零成交如实报告。

治理/源审查报告、正式页面/CLI验收报告和部署receipt分别记录。验收报告留在 integration 分支，避免再次移动已验收的main。若旧BTC证据因HEAD变动失效仍显示blocked；本票不生成假新证据，不增加专用页面。

## 预检与安全

读取 preflight/gate-evidence-review/handoff skills、knowledge README/non-negotiables、shared/super_developer pitfalls、角色和既有 V1/V3 规则。
catalog hash 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
active IDs：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-HANDOFF-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、GOV-PITFALL-001、GOV-PROMPT-001、GOV-WINDOWS-001、GOV-ENGINEERING-CIRCUIT-001、GOV-OBJECTIVE-001、QSYS-GATE-001、QSYS-SECURITY-001；按 context_packet 实际适用范围执行，未加载无关旧事故全文。

本票无新市场artifact或运行ledger；上游离线产物不变成 current-main promotion evidence。readiness ceiling=quality_checked；demo_control_enabled、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_worker_enabled、runtime_observed 全 false。未读secret/真实账户，未访问交易所/private/order。M3—M4及Demo不启动。

