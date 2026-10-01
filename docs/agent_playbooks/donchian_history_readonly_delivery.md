# Donchian 长历史源码的单次只读发布

owner：quant_architect；复审：2026-10-30。合同只绑定
`DONCHIAN-HISTORY-READONLY-GOVERNANCE-20260922`。执行语义风险仍是
`demo_execution_semantics`，本次规则改动风险是 `governance_control`；
部署模式固定为 `research_readonly`。它不改变旧风险类别、V1/V3
合同、启动器、权限或晋级规则，也不授权下一份源码。

## 冻结对象

原主版 `31e3e882e69e983aa88c01ccdf517236e0172e75`，独立集成来源
`7fef4db378aef350a45c9ee716338103ecc5031e`。原主版至来源共有
35 个净差异路径，逐文件 Git 原始 blob 的 SHA-256 固定在
`docs/architecture/donchian-history-readonly-touch-set-20260922.json`。
其中 33 个是已审代码、规格、manifest 与测试，另两个是集成报告和
提交态交接。集成的业务源码提交为 `441e057e2cdc84dd9dba32bf827fd150e614e0e2`；
这与旧年度阶段运行的计算来源 `897d5e99…` 是两个不同版本。

已审集成报告位于 `docs/operations/donchian-history-main-integration-20260922.md`。
其集中矩阵为 308 passed、1 个既有 opt-in skip；另有数据合同 8 passed，
合计 316 passed、1 skip。正式历史 CLI 在新运行身份下完成
400＋400＝800 事件，3 笔模拟成交、0 blocker，经原账本独立重放和
旧 800 小时回执逐项比较。这些结果绑定原集成源码，不是本次部署 HEAD
重新运行的结果。旧年度运行仍是 `897d5e99…` 的 2960/8760 暂停阶段。

## 两阶段证据

1. `source_review`：治理 producer 提交本固定合同、逐文件清单、只读
   校验器、拒绝优先测试、报告与有效 append-only handoff。独立 integrator
   用新的上下文核对上游源码审查及 316＋800 的真实回执、全部 35 个
   Git blob、旧规则不变和新增治理代码。独审报告提交在
   `docs/operations/donchian-history-readonly-independent-review-20260922.md`。
   receipt 必须绑定不同的治理提交、独审提交，以及报告在独审提交中的
   原始 SHA-256；治理提交必须是独审提交的祖先。
2. `deployment_acceptance`：独审通过后，由主会话确认注册 main 仍可从
   上述原主版快进、限定路径无他人 dirty，并创建不覆盖已有标签的
   `refs/tags/codex/donchian-history-before-readonly-20260922` 指向原主版。
   仅合入审定来源和治理/独审提交。之后通过现成启动器以
   `research_readonly` 重启 8765/3000，核验实际监听 PID、健康、
   current-main HEAD、提交态前端指纹、`canonical=true`、
   `runtime_stale=false`、只读与交易控件禁用。
3. 正式入口仅运行 `check-data`、`status` 或 `--help` 等无经济副作用
   检查；不能据此声称在部署 HEAD 又完成了 800 小时，更不能恢复旧年度
   运行。架构页验收只核正式页面可打开及现有精确链接；它在原主版已有
   部分静态旧说明，不能当实时运行事实。研究台已发布阶段 run 的来源、
   2960/8760 暂停、模拟账本与交易禁用须以只读 API 和页面实际内容核验。
   已有生产 BTC 证据缺失照实显示。
4. 发布验收报告提交于独立验收分支
   `docs/operations/donchian-history-readonly-deployment-20260922.md`，其
   append-only handoff 前缀仅为
   `.agent/handoffs/DONCHIAN-HISTORY-READONLY-INTEGRATION-20260922/`。
   报告提交不能再移动已验收 main；部署 receipt 分别引用正式 main
   `deployment_commit` 和报告 `acceptance.commit/path/sha256`。

校验器 `tools/agent_governance/donchian_history_readonly_delivery.py`
只读取合同、Git 对象和提交态报告。来源之后只允许本票治理文件、两个指定
报告和两个指定 handoff 前缀；独审提交之后仅允许报告与 handoff。
未知路径、缺字段、错误哈希、错误祖先、旧 policy 改动、非字面布尔值或
任一安全旗标为 true 都阻断。即使校验返回空 blocker，checks 的真实
含义仍须由独立审查与正式页面实测支撑；校验器不会合并、启动服务或授予权限。

## 停止边界

只读发布的 readiness 上限为 `quality_checked`。不重训、搜参、
恢复旧年度、修改策略/成本/风控/OMS/账本、重建生产 BTC 或晋级证据，
不启动 M3/M4、Demo、paper、live。交易权限、private/order、
real_order、transfer、withdraw、promotion 以及 Demo 控制全部保持 false。
若源码、规则或正式页面证据不满足本合同，报告精确阻断并保留现场，不用
新实验或扩展页面来补齐本次验收。
