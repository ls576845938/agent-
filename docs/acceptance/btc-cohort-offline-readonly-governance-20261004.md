# BTC cohort 限定只读 once 治理 producer 报告

票据 BTC-COHORT-OFFLINE-READONLY-DELIVERY-20261004；角色 super_developer；change_risk=governance_control。
producer actor：btc_unified_readonly_governance_producer_20261004。
base：a78e5e112f564c1ceaf47c57fc3035542cd12562。
planner 树：D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-btc-cohort-offline-readonly-delivery-20261004-c01；
分支 agent/super_developer/btc-cohort-offline-readonly-delivery-20261004-c01。
本报告不自批治理或发布；实际 deliverable commit 由随后 append-only handoff 引用，避免自身未来 commit 循环。

本次是原票一次最小补充，不是新票。旧 deliverable ef5271fdd06639a170bf5e7c0c28c5e265ca5475、
handoff f6506af39fa9c4cdf5fd5b9891b0612f92ea02ab 及原分支原样保留；新树只消费旧 deliverable
的提交态五文件，不带入旧 envelope。注册 main 已为 8707bc48f5614571a3874cbdf0caaba46986c8b8；
root 在真实只读页面发现 capabilities GET 403，本治理票不修业务或绕过 auth。

## 文件与边界

仅新增五个文件：
1. docs/agent_playbooks/btc_cohort_offline_readonly_delivery_20261004.json：精确 once，18 源码/8 已审 metadata mode/blob/Git raw SHA，固定 source/review 引用和限制。
2. 同名 .md：真实 CLI/exports、receipt/report 字段、root 审查和部署不自引用流程。
3. tools/agent_governance/btc_cohort_offline_readonly_delivery_20261004.py：只读来源、receipt、身份/能力/browser/rollback validator。
4. tests/agent_governance/test_btc_cohort_offline_readonly_delivery_20261004.py：限定 failure-first 回归；真实冻结 Git 对象，隔离临时 metadata fixtures。
5. 本 producer 报告。交付后另新增本票精确 handoff 目录内单个 published envelope。

不修改旧 58b/427 sidecar、通用 risk 政策、launcher、auth、安全、hooks、业务、运行 artifact。
只复用旧 427 的 ticket-neutral readonly helper 和既有 frontend identity library；固定 support blob
ea531318717ecb9a649cbf61831c84d6acf08a72，不调用旧 contract/source/delta，不复用旧源码批准。
base 固定 a78；本补充 producer 未改注册 main、merge/push/开服务/浏览器/研究/交易。
初始声明路径 dirty=[]；准备后四个自有 draft，最终仅本票五文件。未读业务工作树 dirty；
他人修改、历史分支与旧 once 原样保留；未加入额外 QA source/published 或扩展历史路径。

## 提交态 source 与独审

- source af7d1ba3222bc60fa44032ee70f63b8615248d45；
  published 5b0ecf9050ca0d99364f7271dd5eb25916878b9c，Git raw SHA
  92bfb38117802d9e6c7b35e906aa30189979e9710ef0b7f125bbdf58da7b3796。
- 最终独审报告 aa9905ee37f42c5434d7b783fbe7fba2664fdbe1，
  docs/acceptance/btc-cohort-entry-recovery-independent-final-review-20261004.md，SHA
  1f5729f8e6bdc93344bd1ccd2640f705888e1b1838e9bf646894bb8555cd8571。
- integrated handoff 87d3fbf9a16c8f7a3cbe82e45ff9263681c13817，Git raw SHA
  ca0aa7fb2fc844d9c9d0cad27d2c888151c2aa1f6ae87c8bfa718a7b8e300e05。
- source/review ancestry、18 源码对象、8 已审 metadata 对象、相应 handoff validate errors=[] 已实际核验。
  历史 rejected e19 与 clock/middleware 8c32 仅固定 diagnostic，不作 pass；
  rejected 使用 Git raw SHA 317c5772...，不使用旧 CRLF 工作副本 34df hash。
- 独审已批准的固定 6d1fd20eedfa609c594199d3518cd4defd8aa8c8 原五长测：
  5 passed / 3 deprecation warnings / 1208.16s；
  JUnit SHA 13638dcdfa06a4ca173895c45c6fb9ceb122c2056623778edf1b528a21464cd2，
  tests=5/failures=0/errors=0/skipped=0。复用已审证据，不由治理 producer 重跑。
  旧漂移 3pass2fail 是 deployment_changed，不计最终冻结回归；原 base 5pass/1813.78s 保留历史地位。
- 复用最终报告中的独审短验收 11pass/33.66s、7pass/64.54s、UTF8 SSR 1pass/6.12s 与 Node exit0；
  producer 59pass/tsc 是原报告限定来源，未冒充本代理重跑。

## 精确两对象只读补充

原 business producer 只修 CandidateDelivery.tsx 与 test_candidate_offline_access.py，
复用既有 offlineRequest 的 intent header；guard/auth/超时/执行实现不变。
合同 readonly_ui_overlay 已封存实际两对象 mode/blob/raw SHA、published exact ref/path/SHA，
以及 root 已实际读取提交后的最小独审报告：

- UI source 2eb5e975f69a200bd200cf200a75dcc35f01a36f，parent=5b，Git delta 严格两路径。
- published e814e3102dedcaec57e2a032015f31f4504f0a93，
  .agent/handoffs/BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004/published-btc-cohort-readonly-public-capability-intent-20261004-2eb5e975f.json，
  Git raw SHA e4bf632c3b7d2f00ba5d10b929a3f9f11dfbbb08e5c7cd924873075acea72bba；
  role=btc_developer，原票 base_commit=a78，已按现有 Git handoff validator 核验 valid。
- root UI report b1f1d6ba256173258adc59964fe6859c6da62c08，现有 governance-review 报告路径，
  Git raw SHA e9a0fc183772693fead45f483834bb3263351e9031b826f4d052223e7a84ba5e；
  新 marker 单份、actor=/root、真实 context、reviewed_commit=2eb、21 false/7limitations。
  相对单一 parent 仅报告变化，87/e814 均为祖先。最初缺 review ref 的草案实际被拒绝，不造占位通过。
postsource 目标仅这两对象替换原 seal，余 16 原对象与 8 原 metadata 不变。
原 6d1 五长测仅旧冻结源码证据，未宣称测试过新 UI。新 UI 不会解除真实 pair 不兼容、
final/calibration 缺失或经济执行 not_run。未来 root 对新治理 deliverable 的独审仍必需。

## 治理回归

实际命令：

    py -3 tools/agent_governance/btc_cohort_offline_readonly_delivery_20261004.py --verify-source
    py -3 -m pytest -q -p no:cacheprovider tests/agent_governance/test_btc_cohort_offline_readonly_delivery_20261004.py

CLI：valid、errors=[]、readiness_ceiling=quality_checked、gate_impact=blocks_gate、permissions_granted=false。
准备版 40 passed/2.22s；最终 JSON 原静态范围 43 passed/2.47s；
完整来源/receipt/report/handoff/delta 70 passed/91.93s；旧交付全部 71 passed/103.85s。
本补充已运行不依赖新 refs 的子集：53 passed/18 deselected/4.25s；真实 refs 绑定后 source CLI
实际 valid/errors=[]（9.96s）；最终完整 71 passed/245.64s（session 6066 已完成）。
首轮完整 70 passed/1 failed/234.56s：错误 reviewed_commit 的新隔离负例从 e814 构造报告，
先被缺 87 祖先拒绝，未到预期 binding reason；只将 fixture parent 修正为实际 b1 后继，
预期仍是错误 reviewed_commit 必须拒绝，未放宽校验。随后重跑原完整 71 范围。
补充 negatives 并入原矩阵，不增加业务范围：overlay 多路径/未知 source envelope/错误 root SHA、
错误 reviewed_commit 与目标对象漂移均拒绝；source stage 正例依真实旧 18+8 和实际新 2 对象/审查 refs。
最后新增仅本票前端 identity 派生祖先 baseline 正例与非法 fingerprint/safety 拒绝，不运行业务矩阵。

覆盖：缺 seal、未知 ticket/source/profile/phase/gate；21 false 旗标缺失/true/0/null；
源码 blob/mode/SHA 与 review digest 错误；缺/错报告或 handoff；producer 自批/错误 reviewed_commit；
额外 business/protected delta；backend pathless 正例和 optional path/HEAD/listener 拒绝；
frontend worktree/HEAD/stale 与非法派生指纹；mock、过期、实际读失败、管理 API/POST 拒绝；
普通 closed、missing artifact、public not_configured、promotion artifact unavailable、
backend listener_status=not_checked + 独立 listener proof 合法。
source fixture 使用真实 Git 对象，审批 metadata 只在隔离 bare TEMP 测试库；fixture 不是真实 root 审查或部署。
注册 main 在测试前后未改变。一次 apply_patch 同文件 delete+add 被机械拒绝，改用 update 后完成，无部分落地。
本补充注册 main 仍 8707，真实旧页面 403 尚未被描述为新版本通过。提交前 scoped/staged 仅原五文件，
git diff --cached --check 实际通过；临时 Git fixture 无正式批准效力。一次误用未提供的 handoff CLI
--from-commit 参数被拒绝，随后改用已有 _handoff/validate_handoff_against_git 对真实 Git ref 成功核验，
未写任何上游文件或更改 validator 预期。
未运行：业务/研究/计算、artifact publication、服务启动、正式 browser/部署、经济执行、真实账户/交易访问。

## 独立审查、集成与运行身份

root 实际读本提交源码/测试/contract，integrator 记录真实 root 审查，report.reviewed_commit 精确绑定
写入前 governance deliverable；report commit 是后继，不自引。执行集成人与 root/producer 不同。
集成保留 87d3、root 精确 UI 审查后继与 governance 精确历史，仅 allow 四 sidecar、四精确报告、
三精确治理 handoff 目录、单个精确 UI envelope 与既有 identity:refresh 派生文件。
原 18+8 在历史来源处仍完整核验；目标只有两对象 overlay，余 16 source/8 metadata 不漂移，
不任意 allow docs/.agent 或整个业务 handoff 目录。
若候选已经继承旧 main 的 manifest，源更新使其不匹配，必须用既有 identity:refresh 精确派生再验，
不能把旧 fingerprint 视为新 UI 版本。治理 fixture 仅在隔离 TEMP Git 库按既有 library 派生，
不改 registered main；正式运行身份仍由 root 后续实际监听者/浏览器验证。

正式部署另核实际 main HEAD、8765/3000 OS listener ownership、canonical/non-stale raw identity、
research_readonly health、派生 fingerprint 和 rollback tag→a78。backend 没 path 不伪加，
如有必须精确匹配；frontend 必须显式 worktree。manifest baseline 可为 metadata HEAD 祖先，
objects/fingerprint 必须一致，不修改算法。部署报告绑定实际运行 HEAD并保留为独立报告后继；
若 main 后来推进，旧 receipt 失效，需要相应 restart/identity/browser 复验。

## 固定限制与权限

最高 quality_checked；source/read-only approval 不等于页面、模型或共同经济执行通过。
真实 Donchian t+1 与 Qlib t+2/方向成本不兼容；原 100/200bps 与 400/800bps 完整保护 hash 不兼容。
真实共同非零订单、成交、保护归属和经济恢复 not_run/blocked；合格真实 final/positive calibration 缺失，
独立有效样本不足30，无确定通过日期。mock-compatible seam 只证明工程合同，禁止包装真实候选或 promotion。

全部保持 literal false：candidate_management、management_write、offline_worker、offline_enabled、account、
demo、demo_control_enabled、promotion、paper、live、private、order、real_order、transfer、withdraw、
execution_permission、runtime_observed、runtime_worker_enabled、offline_commands_enabled、offline_start_allowed、start_allowed。
未改风险/OMS/ledger/执行权限；gate 始终 blocks_gate、promotion_eligible=false。
公共卡片只允许 GET health/capabilities，POST=0，不因验收登记账户、启动研究、造模型/交易 artifact。

下一步 owner=root：独立治理审查；随后独立 integrator 精确合入，再 root 按已有授权正式只读发布和页面验收。
这些仍 pending；本 producer 不自审自批、不合 main，不自动新增工程票据。

## 规则上下文

已读 AGENTS、knowledge README/non-negotiables、shared/super_developer playbook、角色 TOML、
delivery_risk_policy、quant-agent-preflight/handoff skills。catalog hash
6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
active IDs：BACKTEST-COST-001、GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、
GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、
GOV-WORKTREE-001、REPLAY-ISOLATION-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001。
未全文读原事故日志。Team Context 是 discovery-only，历史 invalid/read-model 缺失不授权扩改；
本源引用均另跑提交态 handoff validator，不消费其他工作树未提交文件。
