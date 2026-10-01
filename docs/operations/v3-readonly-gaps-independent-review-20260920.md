# V3 只读展示缺口：独立源码审查

状态：`source_review_passed`；正式 `research_readonly` 服务和浏览器验收尚未进行。本报告只审定本票源码与封存摘要，不授予交易权限。

## 交付身份与范围

- 票据：`V3-READONLY-GAPS-INTEGRATION-20260920`；角色：independent integrator；风险类别：`research_readonly_release`；基线：`7d686dbd6b8d63fd6c0b317e95ef23565ec4b924`。
- 唯一生产者交付：`958828c56c0ab77ee35ffad41f56263abff5774b`；发布事件提交：`67bca9831298f82e00a650c400a9e51cefd41826`；新事件 supersedes `f3d668f5e4a718332d3ed0dfb934aed6c7fb1cbd` 的旧版封装。
- 集成工作树由 planner 从基线创建，`core.sparseCheckout=true`。初始 13 个交付源码路径与本报告、handoff 路径的限定 dirty 均为 clean；未覆盖其他代理文件。
- `handoff.py validate` 为 valid；13 个交付文件逐一使用提交态 Git blob 的 SHA-256 与 envelope 校验，全部相等；生产者提交是基线的后代，`git diff --check` 无错误；审定链在专属集成分支 `--ff-only` 合入，无冲突。
- 变更仅为已有 Qlib 详情响应的只读摘要、提交态 Git 读取器、前端账户展示与研究详情、封存脚本、对应测试、摘要及说明。未修改策略、仓位、退出、风控、OMS、保护、账本、权限、启动器、治理、broker/private transport 或运行存储。

## 独立事实核验

- `offline_execution_views.py` 只通过固定路径读取当前 HEAD 内 Git blob；请求不接收路径/ref 选择器，不打开运行目录，不写快照。缺少 blob、封印不符、身份或模型不符时仅阻断新摘要。Qlib 原研究记录仍按原有封印读取。
- 绑定同时核对 run、candidate、strategy、strategy version、data version、dataset manifest SHA-256 与 model SHA-256。报告的计算代码仍为历史 `7d686dbd6...`，发布页版本单独给出；`historical_source=true` 不会被抹成当前执行证据。
- 封存器只接受五个已审原始文件的固定 SHA-256，恢复事件哈希链、核对 checkpoint 尾端与全部 1392 条决策链接，并调用现有纯账本重算。本人从已授权原始离线目录运行只读封存，得到的 JSON 与提交态摘要完全相同：24 事件、22 拒绝批、1392 决策、0 获准、0 订单、0 成交。模拟账户观察时间早于决策覆盖末端，页面如实注明。
- 账户展示只有已对账且有有效快照时间时才把显式空数组展示为零/FLAT；快照缺失、数值空值/非有限值、资金费账单缺失与历史对账时间均不会伪装为当前账户事实。该 helper 不参与控制按钮、订单或权限判定。

## 回归与遗留项

- 独立执行 `python -B -m pytest -q -p no:cacheprovider backend/tests/test_offline_execution_views.py backend/tests/test_research_readonly_views.py backend/tests/test_backend_research_readonly.py`：`63 passed, 2 skipped`（Windows symlink），1 条已存在的 Starlette/httpx 弃用 warning。
- 独立执行 `node frontend/scripts/test-btc-account-facts-view.mjs` 与 `node frontend/scripts/test-offline-execution-summary.mjs`：均通过；前端 fingerprint/祖先检查通过。生产者已捕获 TypeScript `--noEmit` exit 0，Vite 构建通过；独立集成未启动 worktree 页面服务。
- `node frontend/scripts/test-research-portfolio-contract.mjs` 在**尚未合入交付的基线**已因 `frontend/src/lib/research-api.ts` 与旧 `13486a7...` 冻结断言不一致而失败。该测试及依赖文件均不在本票 diff；它是可复现遗留失败，不隐瞒也不修改旧基准。

## 发布门槛与限制

- 源码审查通过，readiness 上限 `quality_checked`。正式发布仍需：非覆盖回退 tag、注册主版本合入、既有 canonical 启动器以 `research_readonly` 重启、真实 listener/HEAD/identity 与 `/crypto` 和精确研究详情页的浏览器验收。
- BTC production artifact root 缺失、证据注册表冲突/延迟、真实账户及非零成交覆盖不足继续按原状态报告。源封存摘要不是 current-HEAD 交易或晋级证据。
- `demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 false。

## 预检

已读 `AGENTS.md`、知识 README/不可违反规则、shared playbook、integrator TOML、研究只读发布合同、架构边界规则及 preflight/handoff/gate-review 技能。无独立 integrator pitfall 文件；context packet 角色 integrator、scope shared/research/gate，catalog `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。命中 GOV-CONCURRENCY、DIRTY、ENGINEERING-CIRCUIT、HANDOFF、OBJECTIVE、PITFALL、ROOT、STORAGE、WORKTREE、PROMPT、WINDOWS，MONITOR-AUDIT-001、QSYS-GATE-001；未因本票读取任何 private/order/live 端点或密钥。
