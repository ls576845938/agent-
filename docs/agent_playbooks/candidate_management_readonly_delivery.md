# 本票候选管理代码的只读交付合同

仅适用于 `candidate-management-delivery-governance-20260924`。本合同经用户单独授权、独立审查生效后，允许已经审定但默认关闭的候选管理源码部署为 `research_readonly`。不是管理写入/账户/交易授权。

## 精确例外，不修改通用类别

通用 `delivery_risk_policy.json`、risk 枚举、启动器、Hook、角色保持逐字不变。源码仍按 `unclassified` 高风险独立审查；唯一本票部署依据本独立合同与 `candidate_management_readonly_delivery.blockers` 校验，不套普通 `research_readonly_release`，不切 `promotion_strict` 或 `candidate_management`。

JSON 冻结 base `55f039ae...`、业务审定 `891d79f3...`、交接完结源码 `1fc70fec...` 及完整 30 文件 SHA-256。独审已经关闭 USD/USDT 误配和前端误导问题。所有冻结源码文件不得变更；其余仅允许本治理文件、精确报告/本票交接，以及按既有 `identity:refresh` 生成的前端派生指纹。指纹内容由独立集成和正式 launcher 校验，不得改刷新算法或绕过指纹。

## 顺序

1. 治理 producer 只提交合同、校验器、测试和报告；独立 integrator 审查与集成后先行生效。
2. 新 integrator 上下文读取已生效治理合同，验证冻结业务源码、审查/handoff、完整 diff，合成独立集成候选；不修改业务。
3. 在独立工作树提交集成报告与 source_review receipt；校验源码、治理/独审 Git 亲缘和报告哈希。主会话不得以未验证 handoff 消费。
4. 核验 main 未漂移和限定 dirty，保留 `codex/candidate-management-before-release-20260924` 指向原 base。仅合入审定集成提交，使用官方启动器重启 8765/3000。
5. 固定 `research_readonly`，管理 root/operator/auth 不配置、管理命令关闭、不创建管理 SQLite；`QS_BTC_DEMO_CONTROL_ENABLED=false`、`QS_ALLOW_FIXTURE_FALLBACK=false`。不读取密钥，可只检查相关配置是否存在而不打印内容。
6. 核验 current-main 双身份、listener/health、前端运行页的管理边界，管理 API/未经授权写入被阻断。注册文案分支在测试中验证，不为截图启用写入或伪造正式已登记状态。
7. 正式浏览器验收报告单独提交到集成分支，不为了保存验收报告再次改变已验收 main。部署 receipt 精确绑定 main target 与报告提交/哈希；缺项不写 true。通过则本票结束。

校验器只读 Git 和合同文件，没有合并、启动、训练、采集、下单、建库等副作用。true/false 声明只是必要条件，不能替代独立审查、真实命令与报告。source_review 不代表正式部署验收。promotion artifact 重建在本票只读部署不适用，原 promotion/账户/BTC 证据缺失或 stale 保持阻断，不能伪装新鲜。候选管理目录仍未接运行入口。

## 严禁

不可更换被冻结源码，不可修改原策略、参数、成本、Risk/OMS/保护/账本、运行接线、权限实现、启动器、Hook 信任或旧风险类别。不可设置管理写入 profile/root/operator/auth；不可启用 Demo/paper/live/promotion/private/order/real_order/transfer/withdraw/runtime worker。治理、独立集成与发布分别记录，任何真实阻断停止并报告，不自动扩票。

回退通过既有受控集成恢复精确版本，不 reset/覆盖 dirty 或自动恢复交易权限。owner=quant_architect；仅本票一次发布有效；后续源码变化须另行审定，不成为一般安全合同豁免。
