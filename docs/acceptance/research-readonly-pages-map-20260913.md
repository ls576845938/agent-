# RESEARCH-READONLY-PAGES-MAP-20260913 producer acceptance

- role：`super_developer`
- base：`9ce39a517f6d4cb825a3b4aeb9993db5c2c0162d`
- change risk：`unclassified`
- readiness ceiling：`quality_checked`
- scope：修复 `research_readonly` 页面所需的精确只读 GET 423，并更新 `/architecture` 的版本化里程碑状态；不修改交易执行语义。

## 职责边界与实现

1. `backend_access_policy.py` 只增加经逐项审查的 exact GET 和一个 bounded portfolio run id GET；没有开放 `/api/*` 通配符，所有 mutation、训练、审批、private/order/live 路由仍在 middleware 前置返回 423。
2. `research_readonly_views.py` 仅从服务器固定的 `data/` 与 `artifacts/portfolio_runs/` 读取 JSON/parquet 证据。caller 不能选择绝对路径、父目录或其他 root；run id 必须为 bounded opaque id。缺目录返回空只读状态且不创建目录，损坏 JSON/parquet 返回 409，不伪装成空成功。
3. `app_factory.py` 在 `research_readonly` 分支对 experiments、candidates、strategy manifests、pending reviews、system overview、paper-review entry state、portfolio status/runs 使用纯读取投影；不会构造会 `mkdir` 的既有 manager，也不会调用 `_system_overview_payload` 的凭证审计路径。features/factors 固定到服务器 data root；evidence registry 的 caller root 同样被拒绝。
4. system overview 将 health/data quality/registry 未检查状态显式标为 `unknown`，broker credentials 为 `checked=false`，execution permission 与全部 paper/private/order/live 权限为 false；没有把“未检查”写成健康。
5. `/architecture` 使用 `architecture_milestone_status_v2` 独立状态数据，在默认折叠区分“实现 / 测试 / 运行 / 交易就绪”。账户 baseline、完整 bills/cashflow provenance、Guardian unit 入口标为已发布；测试如实记录 `270 passed / 4 个既有旧 fixture failure`；真实账户只读验收未做，M1 仅旁路结项、M2 不晋级、M3—M4 未启动。
6. 历史 `catalog.json` / `knowledge.json` 源码审阅快照未修改，页面没有冒充重新通读 current HEAD 全仓。证据入口显示准确文件路径，不生成浏览器会 404 的伪 `/docs` 链接。

## 验证

- failure-first：`py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_backend_research_readonly.py -k "opens_reviewed_page_gets"`：实现前 `13 failed / 2 passed / 20 deselected`；13 项均因 423，原已开放 evidence-registry 与 Qlib 两项通过。
- Python syntax：`py -3 -B -X utf8 -m py_compile backend/app/core/backend_access_policy.py backend/app/api/app_factory.py backend/app/services/research_readonly_views.py backend/tests/test_backend_research_readonly.py backend/tests/test_research_readonly_views.py`：通过。
- 最终 backend：`$env:PYTHONUTF8='1'; py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_research_readonly_views.py backend/tests/test_backend_research_readonly.py`：`47 passed in 98.41s`。
- 聚焦副作用/selector/损坏证据：同一 backend 集合内覆盖旧 manager 拒绝构造、`Path.mkdir/write_*`、socket/urlopen/sqlite 拒绝、外部 root/非法 id、损坏 JSON 409 与 missing-no-create。
- 前端类型检查：在票据 worktree 执行 `npm.cmd --prefix frontend run lint`，仅通过 junction 复用注册主工作树已安装且未修改的 `node_modules`；实际项目与源码为本票 worktree，退出码 0。
- 前端生产构建：在票据 worktree 执行 `npm.cmd --prefix frontend run build`：5258 modules transformed，build 成功；只产生 ignored `frontend/dist`，未启动 serve/preview。
- 未运行：worktree 前端 serve、Playwright 浏览器 E2E、backend listener、current-main canonical 浏览器验收。项目合同禁止从 writer worktree 启动页面；这些由独立 integrator 合入与 registered-main 发布后执行。

## 治理、dirty 与依赖

- planner worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/super_developer-research-readonly-pages-map-20260913`，sparse checkout；测试冷导入另将 `quant_crypto/`、`quant_cn/` 加入只读 sparse 范围，但未修改其中任何文件。
- 初始 declared touch set 全部 `safe_status=clean`；未发现重叠 writer，未覆盖或回滚其他代理改动。
- 读取：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、super developer pitfalls、research readonly release、domain architecture、delivery risk policy，以及 `quant-agent-preflight` / `quant-agent-handoff` skill。
- active pitfall IDs：`GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,QSYS-GATE-001,QSYS-SECURITY-001,GOV-PROMPT-001,GOV-WINDOWS-001`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 未消费其他 worktree 未提交文件或 handoff；未修改 schema、枚举、策略、风险、OMS、ledger、BTC runtime store/publication 或 live permissions。

## Artifact / gate

- 本 producer 不生成或刷新 BTC runtime artifact、data manifest、ledger、replay 或 promotion evidence。旧 HEAD 导致的 BTC domain read-model 503 仍由独立 current-main offline publisher 按正式 builder 处理，本票不复制、不改写 runtime store。
- `unclassified` 交付要求独立 integrator、backend restart、适用的 current-HEAD artifact rebuild 与 registered-main canonical browser acceptance；producer 不自批、不合并 main。
- 仍保持：`demo_control_enabled=false`、`promotion=false`、`paper=false`、`paper_or_live=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。
- 真实账户 registry、人工批准、封存 snapshot、完整 bills 页与 baseline 登记未验收；M2 不晋级，M3/M4 未启动。
