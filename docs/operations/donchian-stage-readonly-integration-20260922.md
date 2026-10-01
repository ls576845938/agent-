# Donchian 暂停阶段只读证据：独立源码集成

票据 `DONCHIAN-STAGE-READONLY-INTEGRATION-20260922`，风险类别 `research_readonly_release`。本记录只裁定源码集成，正式 `research_readonly` 服务与浏览器验收另行记录。注册主版本及精确回退点：`e2e7496acaa16b9fd5eda37dd65ea328a18ab032`。

## 已审来源与变更边界

- 唯一消费的生产者交接：`DONCHIAN-STAGE-READONLY-20260921/published-donchian-stage-reviewfix-989ab5e3d`，已提交封套版本 `2d245e8fc80b216393126d880bc68217aa4b3946`，最终业务交付提交 `989ab5e3d0feb903435183b100e52d1bf26d08a5`；旧的 `published-donchian-stage-b4f855638` 仍作为 append-only 历史记录保留，已由最终封套 supersede。`handoff.py validate` 返回 `valid`，封套工作树文件的 Git blob 与已提交 blob 均为 `0b4ff323906408b6af409cfc38375ab3367f7aeb`，生产者 base 为当前主版本祖先。
- 生产者范围为 16 个路径：提交态小封存与两份 append-only 封套、后端固定只读读取器及单一 GET 选择器、对应后端测试、研究详情页及链接、架构地图状态与链接、前端组件／测试、交付说明。完整差异和受保护路径核查通过；`quant_crypto/`、策略、风控、OMS、保护、账本、运行产物存储／发布、治理、启动器、权限和交易适配器均无修改。独立集成只新增本报告及同名 JSON 记录。
- 计算来源仍为 `897d5e99ebe4c898f71ac66cf33fb2d2420855d5`。原小回执 `stage-baseline-verification-v2.json` 的 SHA-256 为 `cc4158866b38c25c4d4d2314671642169bd87304844e1557d7df1dbcc823f647`；原报告 `STAGE_BASELINE.md` 为 `643ec8de296ba254efb67dee77750fe1c7313991cfc434410eaa6903090b936f`，两者此次只读核对未改变。提交态小封存规范 JSON 摘要为 `ff5d5ad93538a4b74a2b3da1c7f76cad963e4a25195ff56373ad83c7806cce01`，与计算来源、页面发布提交分开显示。
- 独立比对小封存与原回执：30 条主决策、28 次开平仓、月度数组、未验证项逐项一致；运行 ID、来源、参数、数据、2960 已处理事件、56 订单／成交、价格盈亏、手续费、资金费、净额与现金均一致。年度总计划为 8760 小时，剩余 5800 小时，状态暂停。没有打开约 3 GB 原始日志、恢复回放或重新核账。

## 集成验证

专属 planner sparse 工作树初始限定路径 `dirty_count=0`，未覆盖其他代理工作树。producer 交接 schema、祖先关系、逐文件 SHA、候选完整差异、`git diff --check` 和研究只读边界通过；无合并冲突。

- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_donchian_stage_views.py backend/tests/test_donchian_offline_views.py backend/tests/test_offline_execution_views.py`：**52 passed**。
- `node scripts/test-donchian-stage-evidence.mjs`、`node scripts/test-donchian-offline-evidence.mjs`、`node scripts/test-strategy-delivery-map.mjs`、`node scripts/test-architecture-mindmap.mjs`：分别 **3、3、3、5 passed，共 14 passed**。
- `npm run lint`：退出码 0；`npm run build`：退出码 0，仅有既有大 chunk 提示。
- `npx playwright test e2e/research-run-details.spec.ts --list`：5 例收集成功，尚未在此工作树运行浏览器用例。该仓库只允许注册主工作树的 3000 端口前端接受正式页面验收。
- 独立工作树初次前端命令缺本地 `node_modules`，因此找不到 TypeScript；核对本工作树与注册主树 `package-lock.json` SHA-256 同为 `7ac5765247d5f9202e1b4bfd1458e5b70dae1c283297c5c7856d7b12a5799e07` 后，只在此工作树配置被 Git 忽略的本地依赖 junction，重跑上述测试均通过。未编辑共享依赖或源码。

## 发布边界

本分支可交付的结论是 `source_integrated_quality_checked`。不能把本记录的通过项填入最终发布合同的 `current_main_identity` 或 `canonical_browser_acceptance`：截至此源码集成步骤，两项尚未执行。由主会话核对集成提交后，按研究只读合同单独发布至注册主版本；正式服务身份、精确运行选择、历史来源／暂停标识、缺证安全态和浏览器交互必须使用该发布版本重新验收。本报告及 JSON 是集成分支回执，不要求为补写浏览器结果移动已验收主版本。

原年度运行仍暂停 2960 / 8760；M3／M4 未启动。`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。研究阶段结果和源码集成均不授予交易权限。生产 BTC 证据 503、真实账户与交易所对账限制维持原状态。

## 2026-09-22 限定派生身份刷新

主会话发布上述审定集成源码到注册主版本 `6e64168f28658f8482a4a14ecde179bbdb522fc6` 后，前端 canonical `--Check` 正确阻断旧指纹。经单文件限定授权，在本票集成工作树用现有 `npm run identity:refresh` 刷新 `frontend/public/frontend-identity.json`；该脚本从已提交 `6e64168f…` 重算提交态对象。唯一新增源码路径即此文件；`baseline_commit` 改为 `6e64168f…`，前端 inventory 和 `frontend/src` 树对象 ID 更新，指纹为 `f431bda4b1ad944b695d95fd4f0814fc304a637aea31667dc1532823c87db05e`。schema、release ID、canonical branch/port、routes、launcher 对象 ID、全部 false 安全标记不变。身份文件自身被 inventory 排除，不造成自引用指纹循环。

本工作树 `npm run identity:check` 退出码 0，`manifest_match=true`、`baseline_ancestor=true`；因它不是注册主工作树，`canonical=false` 是预期结果。`npm run identity:runtime-test` 退出码 0。`npm run identity:test` **在发布前退出码 1**：其 Windows 最后一项测试强制调用注册主工作树的 `start_frontend_current_main.ps1 -Check` 并期待成功，而注册主版本此时尚未包含本派生身份文件，正确返回 `fingerprint_or_object_ids_mismatch`。此前身份对象核验没有报错。此项记录为 **待正式发布后复验**，不能填成通过或修改测试预期。主会话合入审定的单文件补丁后须在注册主工作树重跑原 `npm run identity:test`、前后端 `--Check`；任何失败继续阻断服务启动。

预检读取 `AGENTS.md`、`docs/knowledge/README.md`、全局不可违反规则、`shared_pitfalls.md`、`research_readonly_release.md`、集成角色配置及 `quant-agent-preflight`／`quant-agent-handoff` 技能。catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；本任务命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。没有读取原始踩坑全文、账户密钥或任何 private/order/live 端点。
