# Donchian 历史能力：单次只读发布治理候选

票据 `DONCHIAN-HISTORY-READONLY-GOVERNANCE-20260922`；角色
`super_developer`；本票风险 `governance_control`。用户单独授权这一项
“高风险源码独审＋research_readonly 发布”规则。生产者只交治理候选，
不合 main、不启动服务、不运行历史回放、不授予交易权限。

## 固定来源与范围

- base/source 分别为 `31e3e882e69e983aa88c01ccdf517236e0172e75`、
  `7fef4db378aef350a45c9ee716338103ecc5031e`。source 是已独立
  集成候选；原业务提交 `441e057e2cdc84dd9dba32bf827fd150e614e0e2`。
- 上游提交态事件
  `.agent/handoffs/DONCHIAN-HISTORY-MAIN-INTEGRATION-20260922/integrated-donchian-history-main-9527ded08.json`
  已由 `handoff.py validate` 检查通过。Team Context 的 discovery-only
  旧 blocker 未当作该最终事件的新审批。
- `docs/architecture/donchian-history-readonly-touch-set-20260922.json`
  固定 base→source 的 35 个净差异路径及每个 source Git blob 的
  SHA-256；规范 JSON 哈希
  `ae95a6ae216b7297f37994ab5f5e062f7188c151eeecfd3313073cce2582d9b2`。
  其中 33 项业务代码、规格、manifest、测试，2 项集成报告与 handoff。
- 本票只增加独立说明、逐文件清单、只读校验器、拒绝测试、报告、
  append-only handoff，并在 `delivery_risk_policy.json` 顶层新增
  `donchian_history_readonly_delivery` 固定合同。旧风险类别和 V1/V3
  合同值不变。未编辑任何 BTC 策略、风控、OMS、账本、数据或前端。
- planner 由精确 source 建立独立 sparse 工作树，`core.sparseCheckout=true`；
  初始限定路径 `safe_status=clean`、dirty_count=0。为了运行既有
  `team_context` 导入测试，只扩展本工作树 sparse 读取 `quant_crypto`
  目录；未对其写入。

## 规则判断

源码风险仍归 `demo_execution_semantics`，不借普通
`research_readonly_release` 类别合入执行路径。本固定合同要求：

1. source_review 阶段核验冻结来源、原集成报告、上游交接、旧 800 小时
   恢复/账本/对照、316 项兼容测试及独立治理审查；治理提交和独审提交
   必须不同，独审报告需提交态原始哈希。
2. deployment_acceptance 阶段要求独审后 source 文件完全未变、
   main 精确等于验收提交、回退标签指向 base、research_readonly
   正式入口的版本/监听/健康/页面与权限实测。部署验收报告在独立分支
   提交，不移动已验收的 main。
3. 校验器仅返回 blocker 列表，逐项检查来源 35 个 Git blob、
   source 后允许的精确 delta、旧 policy 不变、提交祖先、报告哈希、
   checks 为字面 true 且安全旗标为字面 false。缺失、未知、错类型、
   错来源、错哈希、额外业务路径、旧合同修改均拒绝。receipt
   的字面 true 不能替代审查报告和页面实测。

本票没有填写 source_review/deployment_acceptance 通过 receipt。
独立审查与正式页面验收由不同后续任务完成。

## 实际验证

- 失败优先：新测试最初因目标校验模块尚未存在而 `20 failed`；
  实现后新合同测试通过。
- 首次兼容矩阵先在缺少 `quant_crypto` sparse 读取范围时报导入错误；
  补该只读目录后再次运行时，外部 pytest `--basetemp` 父目录
  尚未创建，结果为 `156 passed, 27 fixture errors`。新建本票自有
  外部临时父目录后用相同源码与用例重跑，得到
  **183 passed in 58.48s**。这些都是测试环境准备问题，未改测试断言
  或生产代码。
- 命令：
  `py -3 -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider
  --basetemp D:/vibe coding/Obsidian/量化系统/offline-runs/donchian-history-readonly-governance-20260922/pytest-matrix3
  tests/agent_governance/test_donchian_history_readonly_delivery.py
  tests/agent_governance/test_strategy_v1_readonly_delivery.py
  tests/agent_governance/test_strategy_v3_readonly_delivery.py
  tests/agent_governance/test_research_release_policy.py
  tests/agent_governance/test_delivery_policy.py
  tests/agent_governance/test_context_packet.py
  tests/agent_governance/test_team_context.py
  tests/agent_governance/test_governance_contract.py`。
  独立集成候选的 316 passed/1 skip 与 400＋400 工程回放来自
  source `7fef…` 上游报告，本票未重复执行。

## 独立审查与发布待办

独审需按本合同对冻结清单、政策增量、校验器误放风险和测试结果形成
`docs/operations/donchian-history-readonly-independent-review-20260922.md`，
并提交独立事件。独审通过后主会话才可按用户授权保留回退点、合入
审定提交、在 `research_readonly` 以注册启动器重启并正式验收。
当前架构地图在 base 已有少量旧静态文字；架构页本轮仅验收可打开、
精确链接和正式版本身份，不能以旧静态说明代替阶段只读 API 的真实来源。
当前阶段摘要仍来自 `897d5e99…` 的暂停运行，本票新源码和页面不能
把它改写成新 HEAD 的运行结果。页面验收尚未发生。

原年度 2960/8760 暂停未动；年度完整表现、生产 BTC 证据、真实账户、
交易所对账及 promotion gate 未完成。Demo、paper、live、promotion、
private、order、real_order、transfer、withdraw、execution_permission、
runtime_worker_enabled、runtime_observed 均为 false。此交付仅
`quality_checked`，不启动 M3/M4。

预检读取 `quant-agent-preflight`、`quant-agent-handoff`、
`AGENTS.md`、知识 README/非协商规则、shared/super-developer
playbook、研究只读发布说明、领域架构规则、旧 V3 合同及当前风险政策。
catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；
适用的主要 ID：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、
`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、
`GOV-WORKTREE-001`、`GOV-OBJECTIVE-001`、
`QSYS-GATE-001`、`GOV-WINDOWS-001`。无原始事故全文、
secret 或交易端点访问。
