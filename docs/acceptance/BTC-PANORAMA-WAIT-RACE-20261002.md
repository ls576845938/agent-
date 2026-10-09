# BTC Panorama pending/ready 竞态修复验收说明

## 结论

- 票据：`BTC-PANORAMA-WAIT-RACE-20261002`；角色：`super_developer`；`change_risk=research_readonly_release`。
- 基准：`3b4ad82d14ef441e6c5ad780edf2fb4acd80e5b1`；分支：`agent/super_developer/btc-panorama-wait-race-20261002`。
- 修复只改变 `frontend/e2e/btc-system-panorama.spec.ts` 的测试调度，不改变生产组件、布局、节点/连线内容、业务语义或权限。
- 既有 5 秒 expect 截止、30 秒单用例预算、11 条 BTC panorama spec 与四文件 29 项正式矩阵均未增加、延长、拆分或删减。
- 当前交付上限为 `quality_checked`；仍需独立 integrator 做提交态审查、合入后刷新 frontend identity、正式 main 重启与 canonical 29 项浏览器验收。本说明不是 promotion、Demo、paper 或 live 证据。

## 失败证据与测量

只读输入为正式 main 报告 `frontend/output/playwright/btc-goal-closeout-20261002-3b4ad82d-a1/editor-matrix.json`，SHA-256 为 `dfdf041ab242b425aff54945e4b23ad32ce23d10b578a27fb5e7c119f78a6043`。该 29 项矩阵耗时 `716226.911ms`，结果 `20 passed / 9 failed`。其中目标用例在第二次重排后等待 `toBeDisabled()` 超时，但错误快照已经显示状态“已重新整理画布”且“在当前分区新增节点”为 enabled，证明旧测试在 scroll/boundingBox/hit-test/mouse 往返后才复查 pending，已经错过真实 pending 窗口。

正式 3000 的一次临时无持久化 context 只读采集没有保存、恢复或重排草稿：DOMContentLoaded `1592ms`；37 节点与初始 status `2228ms`；effect/status commit 并 enabled `2454.6ms`；49 边 `2559.5ms`。Node 定向测量：baseline apply + 49 路由 mean `60.7ms`、median `56.8ms`；两组 baseline structured clone 合计约 `0.74ms/render`；显式 9 组 ELK warm `414.5ms`，现有 Node 合同 cold arrange/routes `1492.6ms`。这些结果不足以把上一轮 6.85 秒无 mock 冷加载或 30 秒导航超时归因于 clone/路由，因此本票不修改生产初始化，也不声称解决整体冷加载或历史 30 秒超时。

在修复前，正式 main 旧 spec 的目标单项按 `workers=1`、`retries=0`、原 30 秒预算与临时 browser context 重跑，当前环境结果为 `1 passed (19.1s)`。这说明竞态对机器时序敏感；它不推翻上述正式失败快照，也不作为候选 patch 的浏览器通过证据。候选 worktree 未启动 Vite/preview，未运行浏览器。

## 最小修复

两次显式重排都在页面 context 内安装同一个 test-only gate。gate 包装 `requestAnimationFrame` 与 `cancelAnimationFrame`，但只暂存调用栈明确包含 `fitPanoramaAfterRender` 的回调，并断言每条已捕获 stack 都包含该函数名；普通 React Flow rAF 不会被当作 ELK 完成证据。真实 Playwright click 触发重排；捕获该专用 fit frame 证明 ELK 已返回且 `setNodes`/`setEdges` 已发出后，测试执行以下确定性断言：

1. 第一轮新增节点按钮必须在专用 gate 内保持 disabled；释放并 ready 后，一次采样 history node 与 data group 的 ReactFlow 自身 inline transform 和 computed width/height，再撤销。
2. 第二轮同输入重排再次捕获专用 fit frame，并在原 5 秒 expect 截止内确认节点和分组的局部布局签名与第一轮相同，证明 arranged nodes 已提交。该签名不包含祖先 ReactFlow viewport 或文档滚动坐标，不以任意 rAF 或 sleep 代替完成条件。
3. pending 状态下按钮 disabled、status 为“正在重新整理分层布局”、React Flow 节点没有 `draggable` class；稳定 box 上的真实 mouse down/move/up 后位移仍小于 2px。
4. 两轮均由 `finally` 无条件恢复原始 rAF/cancelAnimationFrame 并释放队列；ready 后按钮 enabled、节点恢复 `draggable`，真实 mouse drag 位移大于 20px，原有 1.6 秒稳定性检查继续保留。

## 提交前验证

| 命令 | 结果 |
|---|---|
| 旧 main：`npx.cmd playwright test e2e/btc-system-panorama.spec.ts --grep "a loaded personal draft keeps its positions until explicit reversible rearrangement" --workers=1 --retries=0 --reporter=line` | `1 passed (19.1s)`；failure-first 环境复查，候选 patch 未被正式浏览器执行 |
| `node --test frontend/scripts/test-btc-system-panorama.mjs` | `7 passed / 0 failed`，总耗时 `1074.4464ms` |
| `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json` | exit 0，无诊断 |
| 测试内静态调度合同检查 | exit 0；确认无新增 `waitForFunction`/ready wait，真实 click/drag、busy gate、finally release、pending 不移动、ready 可拖动均存在 |
| `git diff --check -- frontend/e2e/btc-system-panorama.spec.ts` | exit 0；仅有 Windows 后续 CRLF 提示 |

未运行候选浏览器、正式四文件 29 项矩阵、frontend build、identity refresh/check、backend/业务回归、训练、回测、Demo、paper、live 或任何 private/order endpoint。候选浏览器与正式矩阵必须等独立集成并恢复 canonical main 服务后由 root 执行。

## 治理与边界

- 已读取根 `AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/super_developer_pitfalls.md`，以及 `quant-agent-preflight`、`quant-agent-handoff` skills。
- context packet catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 初始限定 safe status 为 clean；未发现重叠 writer，也未消费其他 worktree 的未提交文件。依赖安装只生成 ignored `frontend/node_modules`，不属于交付。
- 本票不改变 schema、依赖、数据、策略、风险、OMS、ledger、runtime artifact、manifest 或 latest pointer；没有生成 artifact/manifest/ledger。

## 保持 fail-closed

`demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。独立集成、frontend identity 刷新、canonical 重启与正式浏览器矩阵完成前，本票不得进入 main ready 或 promotion evidence。
