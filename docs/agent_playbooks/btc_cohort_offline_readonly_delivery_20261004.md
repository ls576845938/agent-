# BTC cohort 一次性限定只读交付

票据：BTC-COHORT-OFFLINE-READONLY-DELIVERY-20261004；治理风险 governance_control。
基线固定 a78e5e112f564c1ceaf47c57fc3035542cd12562；不修改通用风险类别或旧 58b/427 once。
本合同不是执行权限；所有输出仍 gate_impact=blocks_gate、permissions_granted=false。

## 精确已审来源

source af7d1ba3222bc60fa44032ee70f63b8615248d45、published handoff 5b0ecf9050ca0d99364f7271dd5eb25916878b9c、
最终独审报告 aa9905ee37f42c5434d7b783fbe7fba2664fdbe1、integrated handoff 87d3fbf9a16c8f7a3cbe82e45ff9263681c13817。
JSON 固定各引用的路径/Git raw SHA、18 源码对象及 8 个已审 metadata 对象。
历史拒绝/clock-middleware refs 仅 diagnostic；不作 pass，不复写 CRLF 工作副本 hash。
原五长测固定 6d1fd20eedfa609c594199d3518cd4defd8aa8c8，5 passed/3 deprecation warnings/1208.16s；
旧漂移 3pass2fail 不算最终证据，不消费额外 QA source/published。

批准范围只有修复的共同账户入口、恢复读取与 fail-closed 只读展示。当前真实 Donchian t+1
与 Qlib t+2 delayed-open/方向成本不兼容，100/200bps 与 400/800bps 原保护 hash 不兼容；
真实共同非零订单/成交/保护归属/经济恢复 not_run；合格真实 Qlib final/positive calibration
缺失，独立有效样本不足 30。fixture/seam 只证明工程合同，不是真实候选或 promotion。
不启用管理/账户/offline/Demo/paper/live/private/order，不造 artifact、不运行研究。

## 同票只读 UI 最小补充

旧 ef5271fdd/f6506af39 与原分支保留；本修订仍从 a78 planner sparse 树仅交付原五文件。
原 af7/5b/aa990/87d3、18 源码与 8 metadata 封印不变；6d1 原五长测未覆盖本次 UI 补充。
readonly_ui_overlay 另绑定原 published 5b 基线的精确两对象 CandidateDelivery.tsx 与
test_candidate_offline_access.py、发布 envelope 的 exact Git ref/path/raw SHA，以及 root 最小独审。
只读修正仅复用既有 offlineRequest 的 intent header，不允许改变 guard/auth/timeout/执行语义。
新 target 必须保留 overlay 审查历史，只替换这两对象，余 16 对象和旧 8 metadata 原封不动。
source→published 仅精确一个 envelope；不得泛化 BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT 目录。
已绑定 UI source 2eb5e975f69a200bd200cf200a75dcc35f01a36f、published e814e3102dedcaec57e2a032015f31f4504f0a93，
root UI report b1f1d6ba256173258adc59964fe6859c6da62c08；精确路径与 raw SHA 以 JSON 为准。
此前 main 8707 页面 capabilities 403 是未通过发布观察，不是此新版本部署验收。

root 最小 UI 审查使用既有 governance-review 报告中的唯一独立 marker：

    <!-- btc-cohort-offline-readonly-ui-review
    {实际 root UI 审查 JSON}
    -->

记录 schema_version 取 evidence_schema_version、kind=readonly_ui_fix_review、ticket_id 为本治理票，
actor_id=/root、actor_role=root_reviewer、非空真实 context_id、reviewed_commit=UI deliverable，
source_commit=af7、outcome=approved_limited_readonly；profile/readiness/gate/limitations/21 false 同合同。
报告保留 published 与原 87d3 的祖先历史，相对自己的单一 parent 仅报告 delta，不自引；
此 UI 审查不替代随后对新治理 deliverable 的 root 独审。
后续 governance-review 报告替换旧治理 evidence marker，不能追加成两个同名 marker；
UI 审查的历史 raw SHA 另行核验，不把未来报告改写冒充旧审查。

## 入口与最小复用

新模块提供 contract()、verify_source(repo_root=...)、blockers(receipt,repo_root=...)、
allowed_delta(path,contract)、validate_false_flags 和 validate_publication_records。
复用未修改旧 427 模块中参数化只读 Git/handoff、listener/browser 和 identity 派生 helper，
固定 baseline support blob；不调用旧 contract/source/delta 或接受其旧源绑定。启动器无旧 once caller。

真实只读 CLI：

    py -3 tools/agent_governance/btc_cohort_offline_readonly_delivery_20261004.py --verify-source
    py -3 tools/agent_governance/btc_cohort_offline_readonly_delivery_20261004.py --repo-root . --receipt "<已存在收据路径>"
    py -3 -m pytest -q -p no:cacheprovider tests/agent_governance/test_btc_cohort_offline_readonly_delivery_20261004.py

CLI 只读 Git 和既有收据，不写/merge/push/开服务/研究；status=valid 的 source 核验不是页面验收。
坏来源、缺/错报告或 handoff、未知字段、缺失/非 literal false 旗标、额外业务/protected delta 拒绝。

## 收据与 root 独审记录

receipt 必须精确包含合同固定字段：
schema_version(取 receipt_schema_version)、ticket_id、baseline_commit、source_commit、
source_handoff_commit、reviewed_release_commit、source_change_risk、deployment_profile、
readiness_ceiling、gate_impact、limitations；另有 phase、checks、safety_flags、
governance_commit、governance_handoff、governance_review、governance_review_handoff、
integration、integration_handoff。deployment_acceptance 再加 deployment_commit、deployment。
每个 Git 引用只含 commit/path/sha256；checks 精确采用对应 required_source_checks，
部署时加 required_deployment_checks，全 literal true；safety_flags 精确采用 required_false_flags，全 literal false。
checks 不能把 not_run 共同经济执行改写成通过；相应固定 limitations 始终保留。

source_review 须先提交 governance 五文件 deliverable（base→gov 仅五路径）和 published handoff；
root 实际读该提交源码/测试/合同独审，integrator 写 root 的真实审查记录；执行集成人不同于 root 和 producer。
不新增审查线程，不靠 bool 或 producer 自批。集成保留 87d3 与 governance 精确历史，main 漂移先报告。

三个精确后续报告/三个 handoff 目录以 JSON 为准，禁止任意 docs 或 .agent 扩展。
每个报告含唯一 HTML marker：

    <!-- btc-cohort-offline-readonly-evidence
    {实际报告 JSON}
    -->

JSON 公共字段：schema_version=btc_cohort_offline_readonly_evidence_v1、kind（governance_review/integration/deployment）、
ticket_id、本次 source_commit、outcome=approved_limited_readonly、deployment_profile=research_readonly、
readiness_ceiling=quality_checked、gate_impact=blocks_gate、limitations（原样）、safety_flags（全部）、
actor_id/context_id（非 producer 的真实身份和上下文）、actor_role。
governance_review 的 actor_id=/root、actor_role=root_reviewer、reviewed_commit=实际 governance deliverable；
integration 的 actor_role=integrator，actor/context 与 root 不同，reviewed_commit 同 gov，
governance_review_commit=实际 root 审查报告 commit。
两 integrated handoff 均 producer_role=integrator、transition_for=本治理 published event_id、
deliverable_commit=对应报告 commit，deliverables 精确绑定报告 path/SHA，gate 仍 blocks_gate。

## 部署证据（不可由源码/fixture 替代）

最终 registered-main/current HEAD、8765/3000 真实 positive PID、独立 listener worktree/head proof、
canonical/non-stale raw identities、readonly health、精确 rollback ref→a78 均必须核验。
backend 原 identity 没 path 时不伪加；如有 optional path 必须全部匹配。frontend 必须显式 worktree。
promotion_artifact_status=unavailable、listener_status=not_checked 合法，后者由独立 OS listener proof 核验。
closed/missing/not_configured 如实显示，无需造无关 promotion artifact；真实读取错误不能装成全健康。

frontend manifest 使用现有 identity:refresh；baseline 可为 metadata HEAD 祖先，但 objects/fingerprint 必须一致，
不改算法。只允许派生 frontend/public/frontend-identity.json，不允许 source/business 变化。
deployment 报告 reviewed_commit=实际已部署 main HEAD；保存于该 HEAD 的独立报告后继且仅报告 delta，
不把报告自身未来 commit 冒充运行 HEAD。若 main 后来推进，旧 receipt 失效，需要对应 identity/restart/复验。

deployment 报告还含既有 backend/frontend（raw identity + listener）、health、browser、checks、safety_flags，
evidence_origin=canonical_main_live、mocked/fixture=false、observed_at_utc（900 秒内）。
browser.url 仅允许 JSON 两个精确 research URL；query 仅在只读解析副本规范化 path，原回执不改写。
browser 记录真实 screenshot_sha256、visible_states、actual_read_failures=[]、required_browser_checks、
cohort_card_api_requests（仅 GET /api/health 与 GET /api/candidate-offline/capabilities，两者都有）、
cohort_card_post_count=0。不得以卡片请求 strategy-delivery/*、catalog/jobs 或 POST。
capabilities={url,http_status:200,source_head,observed_at_utc,body:真实原返回}：
body.source_implemented/cohort_source_supported=true，JSON 指定配置/命令/start 字段严格 false；
permissions 为原完整 11 false 字段，blockers=[candidate_offline_not_configured]。
compatibility 字段缺失代表未知/禁用；不得补伪 false，也不得返回 true。公共只读未配置是合法受限发布。
