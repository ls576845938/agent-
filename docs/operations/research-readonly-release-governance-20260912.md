# 限定研究只读发布：治理修订交付

状态：生产者实现与最终 80 项回归通过，等待独立审查；本票据不发布 M1 业务代码、不启动或停止服务。

## 授权与版本

用户明确授权“限定的治理修订，经独立审查生效后继续发布 M1”。角色 super_developer；change_risk=`governance_control`。base/main=`c1d11987d28f06bb0fe89b2c289e88d07522790d`；planner sparse 分支 `agent/super_developer/research-readonly-release-governance-20260912`。初始限定路径全部 clean，无覆盖他人改动。磁盘约 48.7 GB，使用 sparse、跳过 LFS，不创建完整 checkout 或大型数据。

后继 M1 既有独立验收分支 final=`165a446729f8c114748e1b20bbfcf0c91e75066e`；计算来源仍为59f5eb861，不随治理提交改变。此票据不把已有历史 M1 证据改成当前版本的交易证据。

## 修改边界

- `delivery_risk_policy.json`：仅新增 `research_readonly_release`；七个既有类别逐项与 base 完全一致。独立 integrator=true、backend restart=true、fast-forward-main=false；只对这一新类别免除 BTC promotion/runtime artifact 重建，固定使用现有 research_readonly profile。
- `delivery_policy.py`：枚举、严格新合同字段校验、无副作用验收 receipt 校验器。未知类别仍拒绝，默认仍 unclassified；未修改自然语言分类顺序，不自动识别新类别，必须显式票据/CLI 选择。
- `context_packet.py`、`team_context.py`：共用枚举；仅新类别展示新增要求，截断尾部仍保留研究发布边界。既有类别 Markdown 保持不变，未修改 Hook 文件/trust/交易安全后缀，也未隐藏领域运行 blockers 或套用 Demo fastpath。
- `pitfall_catalog.json`：仅六条规则追加新类别适用范围：GOV-OBJECTIVE、GOV-ENGINEERING-CIRCUIT、GOV-PITFALL、DATA-FRESHNESS、DATA-BTC-FINAL、DATA-US-PIT。保留原 owner、sunset、角色/领域路由；旧类别适用性不变。QSYS-ARTIFACT 仍仅 promotion/live。
- `research_readonly_release.md`：明确适用范围、独立审查、激活/新上下文、当前主页面验收、真实证据/陈旧标记、回退与停止条件。
- `test_research_release_policy.py`：新增拒绝路径/能力/缺失/错误模式/非布尔安全态、合同删除、旧类别未弱化、CLI/截断与数据规则回归。
- 本报告与本票据 append-only handoff。

交易、业务、服务、数据集、BTC runtime root、启动脚本、密钥、private/order/live 均不修改或访问。治理任务与后继 M1 业务发布仍为分离的票据/执行上下文；不扩到 503、registry 冲突或 M2—M4。

## 回归证据

命令使用 `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider`。

- 失败优先：新增测试在实现前 **26 failed / 2 passed**；错误是 unknown_change_risk、缺校验函数和 CLI 不接受类别，确认旧合同无法表达目标。
- 首轮实现后 **40 passed / 1 failed**：测试未包含 gate scope，修正测试以遵循原有 global rule 的领域适用性，没有扩大或删除旧规则。
- 六组治理回归首次 **73 passed / 1 failed**：新增 Markdown 字段被显示到旧类别，造成 Hook 截断丢失 BTC-OMS ID；同一测试在 main baseline passed。修复为只对新类别渲染新增字段，保留旧输出。随后定向 Hook + 新类别 **32 passed**。
- 最终完整回归包含 `test_research_release_policy.py test_delivery_policy.py test_context_packet.py test_team_context.py test_hooks.py test_governance_contract.py test_context_scalability.py`：**80 passed / 80.00s**。
- 新类别 context JSON 可生成，严格边界和 required checks/false flags 可见；限定 `git diff --check` 无空白错误。

未运行 M1 重训、业务单元测试、浏览器、服务重启、promotion/runtime artifact builder。这些不属于治理票据，不能把治理回归通过说成 M1 发布通过。

## 生效与后继交付

生产者先提交 deliverable，再发布/验证 append-only handoff。独立 integrator 复核新类别不会影响既有合同、禁区、授权或交易安全，发布独立 integrated/rejected 事件。通过后后继任务从精确审定提交建立全新上下文与专属 sparse 工作树，显式加载该类别；旧任务不能靠修改环境变量假装规则已热更新。

研究发布随后单独完成：已批准 M1 提交集、只读 immutable manifest 数据发现、独立代码/数据验收、registered main 集成、现有 canonical launcher 的 research_readonly 启动、真实页面验收、回退点校验。不得为治理中间提交提前停服务或把待发布页面伪装成当前页面。

receipt 校验器只核对字段与保守路径边界；独立报告必须提供真实 Git diff、hash、命令与观察来源。它不会自动授权、推导 gate passed 或从全 true JSON 推断真实完成。最终研究发布 readiness 上限 `quality_checked`；研究结果是否有效与交易是否获准独立判断。

## 治理与安全交接

已读 preflight/handoff、AGENTS、knowledge README、non-negotiables、shared/super_developer playbook、cross-agent coordination、delivery policy。原 catalog hash=`127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`；修订后=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。

本轮命中 GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS-001、QSYS-GATE/SECURITY-001。只读 explorer 核对枚举/CLI/catalog/Hook 输出，未并行写入。

promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed 全部 false；现有 Demo 服务模式未在本票据改变，禁止将它误记为已经关闭。M1 主页面发布和最终验收仍 pending；M2—M4 未授权。
