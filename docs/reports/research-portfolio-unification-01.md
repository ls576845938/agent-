# RESEARCH-PORTFOLIO-UNIFICATION-01 — 页面职责整合
日期：2026-09-09。角色：super_developer。change_risk=unclassified，gate_impact=none。
Base / 回退基线：13486a7802628e93dd624213ba6c317c5deb4ddf。
Producer branch：agent/super_developer/research-portfolio-unification-01。
专属 sparse worktree：由 worktree_plan.py 产生，注册主工作树同级。没有在 producer 启动前端服务。

## 交付目标与范围

保留研究台和投资组合两个页面，去除重复的 canonical 操作入口。
研究台仅拥有实验、因子、Qlib 与单策略证据；第四阶段改为“研究结论与交接”。
投资组合独占 PyPortfolioOpt、目标权重/目标持仓、组合模拟和研究风险验证。
已有人工复核操作集中到 /live?view=research-review；原 /live 组件没有修改。
页面跳转只带引用并进行 GET 核验，不自动计算、不自动创建/批准复核、不解锁执行。

Touch set：
- frontend/src/App.tsx：路由包装和导航说明。
- frontend/src/workspaces/{ResearchDashboard,PortfolioMonitor,ExecutionSafetyRoute,ResearchPortfolioWorkspace}.tsx：入口、只读加载/展示和按页面装配。
- frontend/src/workspaces/{research,portfolio,review}-actions.ts：各域独立操作控制器、按钮以外的提交拦截与同步重复提交锁；不互相导入。
- frontend/src/workspaces/research/{ResearchWorkbench.tsx,ResearchDashboard.css,workspace-links.ts,workspace-evidence.ts}：四阶段、范围化样式、显式引用 codec、ID/root/version/config 原件校验。
- frontend/src/workspaces/research/{PreviousResearchDashboard,PreviousResearchWorkbench}.tsx 与 portfolio/LegacyPortfolioMonitor.tsx：冻结上一个版本。
- frontend/e2e/{research-portfolio-workflow,research-workbench,research}.spec.ts、frontend/scripts/test-research-portfolio-contract.mjs：新职责链与旧版回归。
- 本报告及 .agent/handoffs/RESEARCH-PORTFOLIO-UNIFICATION-01/ 自有 append-only 交接事件。

后端仅收紧 GET /research/evidence-registry 的只读语义（见下文）。研究计算/风险/OMS 接口、策略配置、依赖、账本、真实账户组件、共享 API client、其他页面均未修改。
旧 PortfolioOverview/Allocation/Risk、旧研究子组件及最初 LegacyResearchDashboard 保持不变；新增 CSS 全部在 workspace-unified 范围内。
真实依赖安装已由前一票完成，本票不安装或修改 Python/Node 依赖。

## 来源与失败处理

- dataRoot、qlibRoot、portfolioRoot、candidate、experiment、Qlib run、portfolio run、simulation、manifest IDs、dataVersion、featureVersion 都有固定 codec。
- 不用“最新一条”替代显式 ID；列表中不存在、详情编号/路径不符、版本没有原件证明、异步旧读取代次均阻塞关联动作。
- 已有权重版本不可覆盖；显式新建草稿后才能重算。未完成草稿可继续 expected returns → covariance → optimize。
- Portfolio 默认配置不能代表自定义根目录；这些来源只读。导入/风险验证要求原件配置匹配已知配置合同，静态回归核对 YAML，防止合同漂移。
- 当前 portfolio-sim GET 报告没有 manifest ID 绑定，跨页不能靠策略名称推断；带此绑定的复核保持 blocked。
- 旧 data/portfolio/targets 目标快照单独标注，不能当作 artifacts/portfolio_runs 的当前结果或真实持仓。
- 不再生成 volatility×2.5 的“最大回撤”或 volatility×1.645 的“VaR”。简化模拟的估计指标不能作为真实成交回测/准入证据。
- 没有受控再平衡实现的按钮禁用并说明原因。人工批准要求当前待审 ID、复核人、理由及默认目录；仅保留既有接口，不改变权限。

## 回退

Git 备份分支 codex/research-portfolio-before-20260909 精确指向 base。
即时页面回退：
- /research?layout=previous：本次修改前的研究台。
- /portfolio?layout=legacy：本次修改前的投资组合。
- /research?layout=legacy：更早的原版研究台（4096453b 基线仍保留）。

两个改版前页面提供返回新版入口。脚本对照 Git 对象逐字核验组件及未变的依赖。
如需永久回退，由隔离票据只反向应用本次已集成页面提交并重建前端身份；不执行 reset、不回退数据/依赖/后端、不撤销其他任务提交。集成提交号由 integration 报告记录。

## 验证（producer）

已执行：
- node scripts/test-research-portfolio-contract.mjs --baseline：在 base 上预期失败，原因 canonical research 未使用隔离 surface；failure-first。
- node scripts/test-research-portfolio-contract.mjs：通过；冻结依赖、职责、codec、ID/root/version/config、提交拦截、payload、重复点击锁；全程内存 API stub，无网络调用。
- node scripts/test-research-rollback.mjs：通过；4096453b 原版逐字保持。
- node node_modules/typescript/bin/tsc --noEmit：通过。
- node node_modules/vite/bin/vite.js build：通过，5238 modules，1m36s；已有大 bundle 警告保留。最终集成仍须重建。
- node node_modules/@playwright/test/cli.js test e2e/research-portfolio-workflow.spec.ts --list：只枚举用例，不启动前端、不算浏览器通过。

尚须 independent integrator：
- current-main 3000 对三个 spec 执行真正的 Playwright（所有 API POST 必须 route mock，真实系统零 POST）。
- 当前主版本前后端身份、健康、规范启动和重启；独立浏览器视觉/窄屏检查。
- 失败时返回本 producer 最小纠正，不让 integrator 修改业务源码。
这些是交付中的待验收项，不能提前描述为完成。

### 提交态审查后的同票纠正

独立架构审查核验初版 1440e8b69 的 20/20 blob hash 和 handoff 后，要求 7 项 P1 最小纠正；未把初版交给集成。
同票纠正覆盖：拒绝 drive/rooted/UNC/scheme/dot-segment 来源且阻止引用相关 GET；candidate/manifest 关联缺失阻塞；组合 action 白名单；仅首次目标持仓导入（已存在/未知均禁用）；草稿配置 UI 冻结及 handler 的 run_id/configKey 绑定；按 eligible_candidate_ids / eligible_manifest_ids 精确判断选中来源；旧目标快照完整性与 ID/date。
无来源研究页折叠空来源卡，保持四阶段导航靠前。旧版依赖完全未改。
回归新增非法来源无 GET/POST、首次导入后禁用、草稿配置冻结、资格错配、错误快照及真实 API 列表格式的预览断言。最终新增 spec 共 28 项，加原有 10 项共 38 项 canonical 待验收；--list 不是执行成功。
生产构建已复验通过 5238 modules / 49.49s；最终纠正提交仍要求 typecheck/static 和集成重建。初版失败审查与后续纠正均保留，不 amend/rewrite 历史交付。

## 并发与规则证据

### 页面读取期间发现并修复的后端缺陷

用户明确授权主会话统一负责必要的前后端修改后，当前 main 的只读诊断复现 evidence-registry HTTP 500：已有 backtest manifest 解析时 JSONDecodeError。原 GET handler 还会在快照缺失时通过 rebuild_if_missing=True 写入注册表。
同票新增限定 touch set：backend/app/api/app_factory.py 中仅 get_research_evidence_registry；backend/tests/test_research_registry_readonly_api.py。扩展前两路径 clean。没有改写/删除/跳过损坏证据，也没有修改研究 gate 或 POST 重建接口。
GET 改用既有 inspect_saved_evidence_registry，不再回退到 legacy index 或自动重建；rebuild=true 在任何读写前返回405，指向原有显式 POST。坏来源文件返回结构化409/CONFLICT，read_only=true、promotion_eligible=false；不泄露物理路径。坏快照由既有 reader 返回 conflict，缺失返回 missing。
新增真实 handler HTTP 回归（AST提取生产函数，隔离服务启动）：缺失、有效快照、非法重建参数、坏JSON、坏编码、坏快照、legacy-only，共7项。failure-first为6 failed / 1 passed（23.47s），缺失/坏快照会尝试write=True，坏来源直接抛解析异常。修正后的结果记录在最新 handoff；所有测试只使用独占临时目录，无真实paper/private/order/live调用。
修正后新增7项全部通过；与 tests/api/test_research_only_boundaries.py 一并运行得到12 passed / 3 failed（11.50s），3项现有测试因producer sparse不含quant_crypto而在import阶段失败，未执行断言，需在integrator的完整领域sparse环境复跑，不修改这3项测试或补丁绕过依赖。
独立集成必须验证当前真实API由500转为明确409/CONFLICT，而不是把数据问题说成修复成功；其底层证据仍需单独核查。

初始 producer/source touch set clean；后续 dirty 均为本票列出的 19 个实现/测试路径及本报告。
本票未消费他人未提交文件，未覆盖/回滚其他任务改动。
先前按并发提醒做过只读协调；用户随后明确当前没有其他任务，并授权主会话作为整项目架构师及程序员统一推进。并发协调不再作为等待条件。仍在集成前核对 main 与限定源码 dirty，保护既有成果与回退能力。

已读取：AGENTS、quant-agent-preflight、quant-agent-handoff、playwright、knowledge README / non-negotiables、shared_pitfalls、super_developer_pitfalls、delivery_risk_policy、super-developer role TOML。
Active IDs：GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,RESEARCH-HOLDOUT-001,GOV-PROMPT-001,GOV-WINDOWS-001。
Catalog hash：127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c。

## Gate 与未完成的真实研究

### Canonical 首轮浏览器验收纠正

独立 integrator 在 main 7fd07dde2（no-ff integration merge 7ce3c5722 后更新 identity）跑38项：32 passed / 6 failed / 5.8m。原始失败证据保留在当轮 canonical frontend/test-results 并由 integration report 记录。
逐项检查失败快照：3项使用 exact getByLabel 查找包含选项文本的 select 标签，但浏览器AX已有正确命名/状态的 combobox；1项只断言权重表的标题div（收到“target_weights 预览1 行”），实际AAPL在表格中；2项整页旧版导航在5s断言时尚未找到目标，而失败快照已出现对应旧版标题/模块。
同票仅改2个测试文件：select 使用 role/name 的语义定位、AAPL 精确定位目标权重section的cell；2个跨文档回退用例提供15s明确加载等待与60s整用例预算。保留全部身份/来源/禁用/回退/零POST断言，不改fixture数据，不修改任何业务源码或安全逻辑。修正提交仍需 independent integrator 重跑失败用例和全部38项，未以静态枚举冒充通过。

本票只证明 UI/职责/来源防护，不证明 Qlib、组合风险或完整真实研究流程全部成功。
前一票留存的真实流程失败不在本次页面票中修复或重跑：常量预测/RankIC NaN、原生 Qlib portfolio 日历越界、optimizer fallback、pending intents、walk-forward 无窗口、因子时区键合并为空及注册表错误等。
这些历史结果不得作为 current-HEAD 成功证据；真实端到端验收仍 not_run / blocked，owner 为后续明确授权的研究/后端任务。

未写 data/artifacts/mlruns/ledger/latest。无新的市场/回测/promotion artifact 或 manifest。
unclassified 的独立 integrator / backend restart 要求保留；promotion artifact rebuild 本票未执行，UI-only 不申请 promotion，任何需要 current-HEAD promotion artifact 的 gate 继续 blocked。
所有安全旗标保持 false：promotion、paper_or_live、private、order、real_order、transfer、withdraw。
