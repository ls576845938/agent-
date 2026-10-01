# V3 冻结源码的限定只读发布

owner：quant_architect；复审：2026-10-30。此合同仅适用于 V3-READONLY-DELIVERY-20260920，完成一次限定发布后停止，不自动适用于下一版本。不是新的 change_risk，不改变既有类别或 V1 合同。

## 精确边界

原主版 b920d131e41ecbfe7f76f0709affbe22c8b35f5e；已审源码 aca55c90d82b327800e473774e22dbbeac69bd90。前者至后者共 88 个净差异路径，逐文件原始 Git 对象 SHA-256 固定在 docs/architecture/strategy-v3-readonly-source-20260920.json。不是仅合并最后一次事件排序修复。独立 integrator 必须检查该完整清单与上游交接；已有局部审查复用，不把本治理票当成执行语义的新授权。

源码风险仍为 demo_execution_semantics；本次新增规则/校验器/文档/测试风险为 governance_control。独立审查、提交态交接和独立集成必须保留。部署唯一 profile 为 research_readonly。没有新增执行语义权限，不改启动器、hooks、角色、安全权限，不开启 Demo、paper、live。没有专用 V3 前端或 read model 不构成添加新页面的授权。

已审业务源码到部署提交之间，仅允许本次交付规则、独立校验器、测试、冻结清单、报告和两个指定票据的 append-only 交接。完整精确列表由 tools/agent_governance/strategy_v3_readonly_delivery.py 固定。不得修改已有业务源码、现有页面、启动器、旧 policy 类别或 V1 合同。

## 两阶段及证据

1. source_review：producer 提交治理候选和有效交接。新建独立 integrator 上下文读取该提交并审查规则与冻结清单，使用已有上游审查且核验交接。报告必须提交于 docs/operations/strategy-v3-readonly-release-independent-review-20260920.md。receipt 绑定不同的 governance_commit、review.commit/report path/raw SHA-256，且 governance 是 review 的祖先。不得填写发布检查已通过。
2. deployment_acceptance：独立审查通过后才能执行用户已授权的限定发布。确认主版仍在预期基线且相关路径无他人 dirty；创建非覆盖回退标签 refs/tags/codex/v3-before-readonly-20260920 指向 b920d131e41ecbfe7f76f0709affbe22c8b35f5e；只快进包含审定源码及治理/独审的提交。保留上述旧 HEAD，不自动回滚他人变更。
3. 按原正式入口以 research_readonly 重启前后端；检查当前 main HEAD、提交态指纹、canonical=true、runtime_stale=false、监听进程、健康、profile 和必需页面。禁止启动受控交易 worker，禁止访问账户/密钥/private/order。
4. 在固定发布 HEAD 用既有离线 CLI、明确模拟输入和独立外部输出目录运行并恢复同一批次；验证重复恢复不重单/不重账、报告引用与版本。此时不得提交移动 HEAD。零批准/零成交照实保留，不换模型、参数或区间制造交易。
5. 真实浏览器验收架构、研究运行详情及必要组合/策略关联页面。已有源码未实现某种关联就记录缺项，不能凭 HTTP 200 宣称关联完成；旧 BTC runtime 证据 stale/blocked 不改标为当前运行。离线执行与研究预测、真实运行必须区分。
6. 验收后在隔离 integration 分支提交 docs/operations/strategy-v3-readonly-deployment-acceptance-20260920.md 和 receipt/handoff；该验收报告提交不再合入正在验收的 main，从而不改变已验证的 HEAD。部署 receipt 分别绑定 deployment_commit、acceptance.commit/path/SHA-256，校验 main 和回退标签。

校验器只读验证合同、Git 对象、祖先、清单和报告引用；它不会执行合并、启动服务、写交易权限，也不能从报告 hash 自动判定报告内容为真实。checks 的字面 true 必须由独立人工/agent 审查的实测报告支撑。测试中的 mock 仅证明拒绝和结构校验，绝非真实独审或页面验收。

## 停止和交付

- 达标后结项，分别报告源码、治理独审、正式启动、CLI、页面验收状态。
- 发现超出本合同的缺口就报告具体阻断和负责边界，不派生新工程、不修改机器规则来凑通过。
- 不重建 promotion artifact；历史运行证据失效照实阻断。readiness 上限 quality_checked。
- demo_control_enabled、promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_worker_enabled、runtime_observed 全为 false。
- 不启动 M3—M4、多市场推广或模型训练。

有限回归：新 V3 校验测试、原 V1 合同、research release、delivery policy、context packet、governance contract。业务回归复用最终审定报告的真实结果；51 passed/1 HEAD污染失败加固定HEAD五项复验，不得写成一轮52/52。

