# STRATEGY-SOURCE-PROVENANCE-02 独立源码集成

## 决定与范围

- Role=`integrator`; change_risk=`unclassified`; gate_impact=`none`。
- Approved main base/current integration base：`71b104883d4d23db6790bbc6f4057e8e2c31aaaa`。
- Architect 已批准独立消费 `published-strategy-source-provenance-02-5f1b6a076`；deliverable=`5f1b6a076cd9560cf7004e93e67efc6b5d4fe0d3`，handoff commit=`a8d70dd239bf851abf583157d6ce4f430d249dd8`。
- Handoff 经 `handoff.py validate` 为 valid；6/6 committed object SHA-256 与 envelope 完全一致。producer base `bbc39bec1449c5ea6947c200be1541988d34db2c` 同时为 deliverable 和 current main 祖先；producer touch set 在 bbc→71b 的 main 增量中无重叠。
- 使用 planner 创建 `agent/integrator/strategy-source-provenance-02-integration` sparse worktree，并以 no-ff 合入批准的单一 handoff set。旧 `published-strategy-source-provenance-02-8bf83fa23` 是已验证祖先，保持 append-only 历史。

## Touch set 与职责

- Producer：`StrategyExplorer.tsx`、`strategy-history-provenance.ts`、strategy-workbench 局部 CSS、Node pure test、9项浏览器测试、producer 报告及 published handoff。
- Integrator：`frontend/public/frontend-identity.json`、本集成报告、append-only integrated handoff。
- Identity 以 source merge `404051064ba6f60ca5245bb69b3237189afeafd9` 为 baseline，fingerprint=`9c291222960e6ef9cea6625a4b55d99070f9750698fdf28ee2500de64983efdb`。
- 未修改 backend/API/runner/data/ledger/策略执行合同，未触碰 ResearchDashboard 或其依赖变更；未消费任何 producer worktree 未提交文件。

## Dirty、验证与未运行项

- 新 integrator worktree、注册主工作树在声明的 source/identity/handoff 范围初始均 clean；两处 sparse checkout 已验证。main 当时精确为 `71b104883d4d23db6790bbc6f4057e8e2c31aaaa`。
- `node frontend/scripts/test-strategy-history-provenance.mjs`：PASS。
- `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`：PASS，无诊断。
- `node node_modules/vite/bin/vite.js build`：PASS，5228 modules，14.53s；保留既有单 bundle >500kB warning。
- 首次 Node 调用因 integrator 将复用 junction 误建为 `frontend/frontend/node_modules` 而 `ERR_MODULE_NOT_FOUND: typescript`；确认该自建 junction 精确指向 main node_modules 后仅移除该错误 junction，改为正确的 `frontend/node_modules` junction，随后 Node/tsc/build 全部通过。未安装或升级共享依赖。
- 9项新 browser regression、3项既有 parameter heatmap 回归、真实 1131×975/宽屏 QA 未在 worktree 运行；由 root 在 main 接入和 canonical 重启后执行。未运行全前端 E2E 套件。

## 治理、artifact 与安全

- 已读：quant-agent-preflight、quant-agent-handoff、AGENTS、knowledge README、non-negotiables、shared pitfalls、integrator profile、delivery risk policy；未全文加载原始事故日志。
- Catalog hash=`127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。
- Active IDs：GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001。
- 本阶段无新 artifact/manifest/ledger/replay；既有历史报告仍 `historical_not_current_head`，连续 equity/drawdown/trades/fills/ledger 缺失，不作推断或补造。
- 保守 unclassified 政策的 promotion artifact/read model 未重建且不在本 gate_impact=none 票据授权内；promotion gate 继续 blocked。
- promotion、paper、live、private、order、real_order、transfer、withdraw 全部保持 false；没有 secret、private/broker/order/live endpoint、真实订单、依赖升级、外部 push 或服务重启。

## Canonical failure-first 与统一纠正续接

- Root 在首次 main `79a70d459bf30662da01c3c1ad16b11a317b75b3` 执行 12 项 E2E：10 passed / 2 failed（48.8s）。两项失败只是 KPI 文本的浏览器换行与 `textContent` 口径不同；producer 以 `useInnerText:true` 修正测试，目标 2 项在 canonical 3000 上 2 passed（6.6s）。
- 随后真实窄屏 QA 发现长 `source_ref` 将 filetab 状态挤成单字竖列；旧 CSS 下新增 cold-load 断言 failure-first 得到 134.234px，违反 `<120px`。统一 corrected event `published-strategy-source-provenance-02-0ef47f5f0` 将 2 行文本断言、真实长路径回归和 `max-width:1279px` 的局部换行 CSS 一次性交付；`>=1280px` 布局不变。
- Architect 明确批准同一 integrator 消费；event validate=valid，6 项 committed SHA 匹配。Integrator 从 main79a70 no-ff 合入 producer tip `7f47fb862b00733a648a0844eff9a25e311823b9`，保留被 supersede 的 `published-7bf4db75c` 审计记录。
- 纠正后 integrator 复核：Node pure PASS、tsc PASS、Vite build PASS（5228 modules，13.22s，仍只有既有大 bundle warning）。Identity 以 merge commit `bfcb21998d87616821d9ffb82bdfa29a155bfe6e` 为 baseline，fingerprint=`78e34550eb642f0d47b21e26ba7ddf5d3b2c29ca0864c60669945a970aae6e03`。
- 最终 12 项 canonical 浏览器回归及真实 narrow/wide QA 仍由 root 在 main 接入、服务重启后执行；业务 source/helper/backend/API/执行权限均未在此纠正中变化。
