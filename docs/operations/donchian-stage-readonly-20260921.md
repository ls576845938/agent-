# Donchian 暂停历史阶段：只读接入源码候选

票据 `DONCHIAN-STAGE-READONLY-20260921`，`change_risk=research_readonly_release`。生产者基线／回退点为注册主版本 `e2e7496acaa16b9fd5eda37dd65ea328a18ab032`。本票仅交付提交态小封存、读取接口、既有研究详情和架构地图的阶段入口；独立审查、集成、正式发布和浏览器验收另行记录，不能因本报告把候选说成已发布。

## 证据身份与界限

- 唯一历史运行：`donchian-effective-time-20250901-20260901`；计算源码 `897d5e99ebe4c898f71ac66cf33fb2d2420855d5`，不是页面发布源码。原机器核账回执 `stage-baseline-verification-v2.json` SHA-256 `cc4158866b38c25c4d4d2314671642169bd87304844e1557d7df1dbcc823f647`；原阶段报告 `STAGE_BASELINE.md` SHA-256 `643ec8de296ba254efb67dee77750fe1c7313991cfc434410eaa6903090b936f`。仅读这两个小文件核对来源；未打开、复制或重放约 3 GB 的原始运行日志，未改原年度目录。
- 小封存 `.agent/offline_evidence/donchian-stage-20260921.json` 是固定来源的约 42 KB 投影，规范 JSON SHA-256 `ff5d5ad93538a4b74a2b3da1c7f76cad963e4a25195ff56373ad83c7806cce01`。去掉原回执的 `input_fingerprints`／运行物理路径；保留来源哈希、数据／策略／参数／费用／撮合／保护政策身份及原 Git 规格引用、主决策引用、开平仓摘要、账本金额、成本假设和未验证项。GET 先解析当前提交 SHA，再从**同一个已解析提交**取固定封存，避免两个 Git 调用间 HEAD 移动时把新封存标成旧发布版本；不能从磁盘工作树、latest、外部运行根、相似 run 或训练／回测入口回退。固定摘要、身份、计数、金额、链接和 false 权限任一不符都阻断。
- 阶段业务核账通过，不等于年度完成：`2960/8760` 小时、`paused_at_checkpoint`，原时区偏移保留。30 条主决策成交引用与 26 条保护退出分开展示；共 56 个模拟订单／成交、28 次完整开平仓、370 条资金费。价格盈亏 `+0.0346310615`、手续费 `-0.26552203961525`、资金费 `-0.012403344923245647991`，净额 `-0.243294323038495647991` USDT；初始 5000，暂停时现金／权益 `4999.756705676961504352009` USDT、空仓。主决策引用含 signal／target／risk／intent／client／exchange／fill／ledger ID 和哈希，但不含信号数值；保护退出不补造主决策 ID、真实回执或小时内精确成交时刻。
- 这是历史模拟的探索性阶段基线，不是独立确认、全年收益、真实账户、实际成交或交易晋级证据。原运行还余 5800 小时；本票不恢复、不重跑、不改策略、参数、成本、上限、风控、OMS、保护或账本。
- 历史成本／撮合口径沿用原报告：taker 手续费 5 bps、half-spread 0.5 bps（已经体现在成交价）、资金费使用先前可见小时 mark 收盘近似；假定买卖两侧各一张合约深度，未建模队列或市场冲击。小时内精确成交时刻未知，双触顺序无法证明时保持阻断。页面显示这些限制，不将其解释为交易所实测质量。

## 版本化地图

冻结范围 V0—V3 离线工程在主版本 `e2e7496` 已限定结项，不能沿用旧地图的“未结项”说法。独立集成的最终 canonical 回执为 `78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json`，Git blob SHA-256 `e7475030f22e2159df1e4b7e887df631509de7a3f40f7dbfb6ef38a68e30a52d`：`decision=limited_offline_v3_pass`、`overall_v3_complete=true`，正式 research_readonly 浏览器由主会话验收；自动 Playwright 未跑。它只覆盖当时的五阶段／固定 Qlib 范围，不覆盖本次自然历史阶段。M1 环境研究旁路不接默认交易，M2 探索已结项但没有稳定增量；M3—M4 未启动。

## 本票验证与未运行项

Failure-first：新增后端测试先因缺少 `donchian_stage_views` 在收集阶段失败；实现后以下命令通过：

- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_donchian_stage_views.py backend/tests/test_donchian_offline_views.py backend/tests/test_offline_execution_views.py`：52 passed（初稿 47，独审三项修订补 5）。涵盖精确选择、缺少已提交对象、脏工作树内容不生效、篡改／缺字段／错金额／错计数／权限为 true／暂停被写成 complete 的拒绝、HEAD 移动时固定已解析 Git 对象、旧五阶段兼容和 API 权限。
- `node frontend/scripts/test-donchian-stage-evidence.mjs`：3 passed；旧 Donchian 组件：3 passed；`node frontend/scripts/test-strategy-delivery-map.mjs`：3 passed；总图脚本：5 passed。覆盖研究类型切换清旧选择、来源与发布版本区分、保护退出不补造主决策及失配阻断。
- `npm run lint`（TypeScript）exit 0；`npm run build` exit 0，只有既有大 chunk 警告。`npx playwright test e2e/research-run-details.spec.ts --list`：5 例成功收集。按项目规则，工作树不得启动 Vite／preview；本票新增两例浏览器场景**未执行**，待独立发布后的 canonical 页面跑与核查。未运行全仓回归、年度回放或交易／账户接口。

本票初始列明的路径均 clean；新增单一 `ArchitectureMapWorkspace.tsx` 入口和 `frontend/e2e/research-run-details.spec.ts` 用例经主会话确认后才加入 touch set，并再次 safe_status 为 clean。为测试导入只读扩展 sparse checkout 的 `quant_cn`／`quant_us`，未编辑或提交其源码。未发现或覆盖其他代理 dirty 文件。预检读 `AGENTS.md`、quant-agent-preflight／handoff 技能、`research_readonly_release.md`、知识规则、共享与 BTC 开发 playbook；catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`，命中 GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、GOV-STORAGE-001、GOV-WORKTREE-001、MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001、GOV-PROMPT-001、GOV-WINDOWS-001；未加载原始踩坑全文。Team Context 只作发现，未消费其他代理未提交内容。

交付上限 `quality_checked`；独立 integrator 必须核对本票提交、完整 diff、哈希与只读执行不变边界，再按授权决定是否发布。没有重新生成 BTC 生产 artifact，旧 503／真实账户缺口不因本票修复。`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。研究完成不授予交易权限。
