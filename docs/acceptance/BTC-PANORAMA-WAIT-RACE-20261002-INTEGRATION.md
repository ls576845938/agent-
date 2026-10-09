# BTC Panorama wait-race 独立集成报告

## 结论

- 票据：`BTC-PANORAMA-WAIT-RACE-20261002`；`change_risk=research_readonly_release`。
- 独立集成基准：`28687b34497f1fe9a7438bc2774026acabba4672`；分支：`agent/integrator/btc-panorama-wait-race-20261002`。
- 最终生产者交付：`84d38b3a14f3bdb1e0fa7a8975b845c9c8b97d18`；提交态 handoff HEAD：`7e5de8d806a3cbf31445a462d5556470428283b3`。
- 当前 active published 事件为 `published-btc-panorama-wait-race-local-geometry-20261002-84d38b3a1`。旧 `d77e6d977` 与 `07ffba116` published 事件均由 append-only superseded 事件终止，未被当作活跃交付。
- 独立审查确认最终改动仅调整 Playwright 测试调度与证据：两轮只截获调用栈属于 `fitPanoramaAfterRender` 的 rAF；跨轮完成条件比较节点与分组自身的 inline transform 和 computed width/height，不依赖文档滚动或祖先 viewport；pending/ready 仍保留真实 hit-test 和 mouse drag。没有生产源码、业务 API、布局算法、等待预算或用例数量变化。
- 当前上限仍为 `quality_checked`；canonical main 构建、重启与四文件 29 项浏览器矩阵由 root 在合入 main 后执行。本报告不声称浏览器验收已通过，也不声称历史 30 秒超时根因已证实或修复。

## 集成范围与冲突

- 源码/测试：`frontend/e2e/btc-system-panorama.spec.ts`。
- 派生身份：`frontend/public/frontend-identity.json`，仅通过既有 `npm.cmd --prefix frontend run identity:refresh` 生成。
- 证据：`docs/acceptance/BTC-PANORAMA-WAIT-RACE-20261002.md`、本报告与本票 `.agent/handoffs/` append-only 历史。
- 从已批准 base 顺序 cherry-pick 生产者本票的七个提交；无冲突。没有合并生产者旧基线整支，因此保留 main 上既有治理修复。
- 初始限定 `safe_status=clean`，未发现重叠 writer；除 identity 与本报告外没有集成代理新增业务修改。

## 验证

| 命令/检查 | 结果 |
|---|---|
| 对最终 published 与 superseded 事件运行 `handoff.py validate`，并复核 base ancestry、deliverable ancestry、提交 touch set 与 Git blob hash | 通过；两事件均 `status=valid` |
| 对旧两版 published/superseded 历史运行完整 Git validate | 通过；解析后旧两版均非 active |
| 最终源码独立审查 | 通过；原先“任意 ReactFlow rAF”与“第一轮未 gate”两个阻断已闭合；绝对屏幕坐标风险已由局部 DOM 布局签名闭合 |
| `npm.cmd --prefix frontend run identity:refresh` 与 `node frontend/scripts/check-frontend-identity.mjs` | 通过；非 canonical 集成分支 `manifest_match=true`、`baseline_ancestor=true` |
| `node --test frontend/scripts/test-btc-system-panorama.mjs` | 首次因 sparse worktree 无本地 `node_modules` 导致 `ERR_MODULE_NOT_FOUND: elkjs`，未进入测试；临时只读复用主工作树依赖后重跑 `7 passed / 0 failed`，junction 已移除 |
| `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json` | 通过；无诊断，随后命令进入 build 阶段 |
| `npm.cmd --prefix frontend run build` | 未完成；为避免与 root 即将执行的 canonical build/浏览器矩阵争用，在 Vite build 开始时主动终止；正式 build 留给 root |
| `git diff --check`（本票源码、报告、identity） | 通过 |
| canonical current-main 四文件 29 项浏览器矩阵 | 未运行；明确留给 root 在 main 合入、identity 对齐和 canonical 服务启动后执行 |

## 治理证据

- 已读取根 `AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、integrator 角色配置、`delivery_risk_policy.json`、`research_readonly_release.md`，以及 `quant-agent-preflight`、`quant-agent-handoff` skills。
- context packet catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 未生成或修改 artifact、manifest、ledger、数据版本或 latest pointer；无 current-HEAD promotion artifact/read model 可由本票重建。

## 保持 fail-closed

- 正式 main build、identity canonical check、服务重启与 29 项矩阵仍待 root；历史 30 秒加载/导航根因仍未证实。
- `demo_control_enabled=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_observed=false`。
- 集成本身不解锁 promotion、Demo、paper、private、order 或 live，也未访问 secret、private/order/live endpoint 或提交真实订单。
