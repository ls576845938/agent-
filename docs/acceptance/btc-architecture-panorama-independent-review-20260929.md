# BTC 系统全景可编辑子页独立集成审查（2026-09-29）

## 结论

- 票据：`BTC-ARCHITECTURE-PANORAMA-20260929`。
- `change_risk=research_readonly_release`，独立 integrator 路径；本报告只给出 `quality_checked` 的主分支合入候选，不是 promotion、Demo、paper 或 live 证据。
- 架构师批准基线：`5542a542459f2b56eaf11035fca409422142471d`。
- 最终 producer deliverable：`8bffc2de1f0b9250d6e74870e1c8b8d05e857581`；最终 published handoff commit：`6ce9a85b94b656510964e39336039ab462b70d48`；事件：`published-btc-architecture-panorama-20260929-8bffc2de1`，明确 supersede 旧事件 `published-btc-architecture-panorama-20260929-cbbd183a5`。
- 提交链从批准基线线性到最终 handoff；`handoff.py validate` 返回 `valid`，9 个 deliverable 的提交态 SHA-256 全部与 envelope 相同。集成前本票全部限定路径为 clean。
- 最终范围仅为 `/architecture?view=btc-panorama` 前端子页、必要 `@xyflow/react` 锁定依赖、文档、测试、前端身份与 append-only handoff；未改 backend、策略、组合/风控、OMS/Execution、Fill/Ledger、账户、权限或运行服务。

## 独立审查与最小修正

producer 的 A-I 固定快照保持 9 个分区、37 个业务节点、49 条关系；`frontend/src/workspaces/architecture/btcPanoramaData.ts` 在 integrator 修正中未改动，37 个节点原文与关系没有被重写。新视图使用黑底、深蓝灰分层节点、React Flow 初始 `fitView`、缩放/适应/100% 控件、节点拖动、文本编辑、节点/边增删、撤销/重做、本机显式保存与 JSON 下载。

独立审查在批准 touch set 内做了以下最小修正：

1. `ArchitectureMapWorkspace` 仅在 BTC 新视图把通用“只读文档”标签改为“原始快照只读 · 个人草稿可编辑且未经代码核验”；旧视图标签不变。
2. 新增可执行的纯数据草稿解析器。读取时固定验证 `schemaVersion`、`sourceHead=5542a542...`、`verification=personal_unverified_draft`、保存时间、数量/字节上限、节点类型、A-I 分区完整性、有限且有界的坐标/尺寸、普通节点的合法分区引用，以及边 ID 唯一、两端均为不同普通节点、引用存在。返回值重新构造为白名单字段，丢弃草稿携带的任意视觉/行为字段。
3. HTML/脚本文本继续由 React 作为纯文本渲染；没有 `dangerouslySetInnerHTML`、`fetch`、POST 或外部草稿资源加载。测试同时覆盖恶意标记文本与未批准字段净化。
4. “恢复原始版本”保持全页统一的显式保存语义：恢复先写入可撤销画布状态，不偷偷改写 `localStorage`；状态明确提示“点击保存本机草稿后刷新才生效”。验收用例覆盖未保存恢复后刷新仍读旧草稿、恢复可撤销、再次恢复并显式保存后刷新保持基线。
5. 浏览器验收规格新增坏草稿/重复边、真实拖动位移、文本注入、`localStorage.setItem` 失败、CRUD/下载及 390/1131/1440 布局；拖动前显式滚入视口，新增边通过其真实 interaction path 选中，不使用 `force` 掩盖不可操作状态。
6. 按用户最终明确要求，删除顶部固定快照/localStorage 长说明、标题旁来源免责声明及手柄操作说明，不以其他长说明替代；日期、`sourceHead=5542a542...`、个人草稿 verification 与恢复合同仍保留在数据、导出 JSON 和校验器中，37 个图内节点原文未删。

## 依赖审查

- 新直接依赖为 `@xyflow/react@12.12.0` 与 `elkjs@0.12.0`；后者由锁文件固定、无 CDN，许可证为 `EPL-2.0 OR GPL-3.0-or-later`。`@xyflow/system@0.0.83`、`zustand@4.5.7`、`d3-*` 等传递依赖继续锁定。
- `npm ls` 对上述关键包返回正常依赖树；构建未使用 CDN 或运行期远程脚本。
- `npm audit --registry=https://registry.npmjs.org/ --omit=dev --audit-level=high` 返回非零，唯一命中为 `react-router/react-router-dom@7.15.0` 的存量 1 high + 1 low。批准基线与候选锁文件均为 `7.15.0`，不是本票或 `@xyflow` 新增；本票没有越界升级共享路由依赖。该存量风险必须单独治理，不能被本报告描述为已修复。
- 默认 `npmmirror` audit endpoint 不实现 advisory API；因此依赖审查改用 npm 官方 registry 取得上述结果，并保留非零结论。

## 验证结果

| 验证 | 结果 |
|---|---|
| `node --test frontend/scripts/test-architecture-map.mjs frontend/scripts/test-architecture-mindmap.mjs frontend/scripts/test-architecture-knowledge.mjs frontend/scripts/test-btc-system-panorama.mjs` | `27 passed`，含布局/避障、默认新增节点、草稿解析器可执行校验 |
| `npm.cmd --prefix frontend run lint` | 通过，`tsc --noEmit` exit 0 |
| `npm.cmd --prefix frontend run build` | 通过，Vite 6.4.2，5403 modules；只保留既有 large-chunk warning |
| `npm.cmd --prefix frontend ls @xyflow/react @xyflow/system zustand d3-drag d3-selection d3-zoom` | 通过，依赖树完整 |
| `npx.cmd playwright test e2e/btc-system-panorama.spec.ts --list`（在 `frontend/`） | 发现 11 条；未启动 web server、未在 integrator worktree 运行浏览器 |
| `py -3 -m pytest tests/agent_governance/test_handoff.py tests/agent_governance/test_context_packet.py -q` | `32 passed` |
| `npm.cmd --prefix frontend run identity:refresh` | 最终 fingerprint `628b151d0431c5ea95925abd205b45edf1cb6344c80973bf1b300fb70c0b494e`，baseline commit `fb195a8724e60d384b797e3205a9349a91d0d182` |
| `npm.cmd --prefix frontend run identity:check` | 通过；manifest match、baseline ancestor、identity dirty paths 空 |

## 治理证据与边界

- 已读取：根 `AGENTS.md`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`.codex/agents/integrator.toml`、`docs/agent_playbooks/delivery_risk_policy.json`、`docs/agent_playbooks/research_readonly_release.md`，以及 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff` skills。
- context packet：role `integrator`；scope `shared/research/gate`；catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 命中 pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 专属 planner sparse worktree：`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-btc-architecture-panorama-20260929`；`core.sparseCheckout=true`。没有覆盖或回滚其他代理文件，cherry-pick 无冲突。
- 本票没有生成 runtime artifact、研究 manifest、promotion evidence 或 ledger；唯一版本身份为 `frontend/public/frontend-identity.json`，它只证明提交态前端对象指纹，不证明正式 3000 页面或运行服务。
- integration 从未启动 Vite、backend、账户、Demo、paper 或 live；未访问 secret、private/order/live endpoint，也未提交真实订单。

## 主分支发布后必须完成的正式验收

本候选合入 `refs/heads/main` 后，只允许从注册主工作树使用官方入口重启 `research_readonly` backend/frontend，并核对真实 listener PID、命令路径、`/api/health`、`/__frontend_identity` 与 canonical identity。随后在正式 `3000` 运行：

```powershell
npm.cmd --prefix frontend run identity:check -- --canonical
Push-Location frontend
npx.cmd playwright test e2e/architecture-map.spec.ts e2e/architecture-mindmap.spec.ts e2e/architecture-knowledge.spec.ts e2e/btc-system-panorama.spec.ts
Pop-Location
```

还需由真实无 mock 浏览器检查：旧 `/architecture` 默认页保留；`?view=btc-panorama` 深链刷新/返回；9/37/49 完整结构；黑底分层布局、正交线路、fit/zoom；真实拖动；纯文本编辑；节点/边 CRUD；显式重排不自动保存且可撤销；显式保存/刷新；恢复/撤销/再次保存；JSON 下载；坏草稿与存储失败 fail-closed；390/1131/1440 页面不横向溢出；无 backend/business side effect。

正式页面回执保存到 main ignored 的本票 output/playwright 目录，不再为运行回执修改源码或追新 HEAD。完成前 `runtime_observed=false`，本报告不声称页面已发布。

## 正式 main 首轮验收反馈与同票修复

首版候选已由主会话合入 main `df0e358f1ff3f28b7531871f68ad31c8ab58165e`。正式启动证据显示 backend/frontend 均来自该 main HEAD，`research_readonly`、`canonical=true`、`runtime_stale=false`；frontend listener PID `1860`、backend listener PID `18632`，没有开放业务执行权限。

正式 28-spec Playwright 首轮结果为 `21 passed / 7 failed`（约 3.3 分钟），原始失败上下文保留在 main ignored 路径 `frontend/output/playwright/btc-panorama-20260929/test-results/`，没有删除或改写。七项失败归并为四个确定问题：

1. 浏览器 history 返回后 URL 已恢复 `?view=btc-panorama`，但本地 `view` state 仍显示 overview；损坏草稿 reload 看到 overview 与此同源。
2. 无副作用断言把 Vite 源码 GET `review-actions.ts`、`demo-start-feedback.ts` 的文件名误判为业务动作。
3. 五处全页 `getByRole('status')` 同时命中全局审计提示、缩放 `<output>` 和画布状态，触发严格模式失败。
4. 新增节点后，React Flow 的空 selection change 覆盖手工 `selectedNodeId`，导致删除按钮保持 disabled。

同票提交 `5d0bc45980ee205d9cc0abfb80284de7a946cc44` 做了限定修复；producer 随后以 `git show` 对该提交做只读独审并通过：

- BTC panorama 是否显示由 URL query 直接决定，本地 state 只保存非 panorama 视图；不再用 effect 追认 query，因此首次深链、刷新和前进/后退使用同一权威。
- 节点、边、画布空白改用明确的 click/pane 事件维护 inspector selection；拖动起点同步选中节点；新增节点写入受控 `selected=true` 并清空旧选择。
- 无副作用断言仅把匹配动作词的 `/api/` GET 识别为业务调用；任意非 GET 仍无条件记录并使测试失败。
- 状态断言精确定位当前 BTC panorama 内的 `p.btc-panorama-status[role="status"]`，文本和失败条件不变。

用户随后明确要求 BTC 子页使用黑底且各元素不必同色。视觉提交 `cb11050779cba686243802996a50445f52395d29` 仍在原授权 touch set：画布为 `#090f18`，职责分区与节点采用不同深蓝灰，文字改为浅色，默认连线/箭头为 `#91a9c2`、选中关系为 `#f0b35a`，minimap 与边标签同步使用暗色表面。没有改 A-I、37 节点、49 关系、坐标/尺寸布局、编辑功能，也没有新增主题切换或设置模块。producer 对该提交的三文件 diff 做了第二次只读独审，确认 create/hydrate/new-edge 三条路径颜色一致且范围未扩大。

修复后在 integrator worktree 验证：architecture 静态与可执行草稿单测 `26 passed`；`tsc --noEmit` 通过；Vite build 5398 modules 通过并仅保留既有 large-chunk warning；BTC Playwright 文件仍发现 10 条规格。暗色提交的 identity fingerprint 为 `8813453603fde781a680a2dd111efc07f70b727e895be0e67fc65d1f00ac8fc0`。按照 worktree 禁止启动前端的规则，没有在该工作树重跑正式浏览器；修复合入 main 后必须顺序重启并复跑原正式验收，不能把上述提交态验证描述为 7 项正式失败已通过。

## 最终分层布局与编辑互斥收口

用户对正式截图指出固定九横排、Bezier 长斜线与原 TB 语义不一致，随后明确批准同票恢复 A-I/TB 层次、黑底可编辑、正交避节点线路。最终实现以原 Mermaid 拓扑为语义基线，不宣称逐像素复刻：A 位于顶部，B/C/D 分栏，E 居中，F→G 为右侧执行链，H 在底部，I 为左侧证据汇聚；主链、市场旁路、证据 bus 与 UOW→账户事实外围反馈分开。`btcPanoramaData.ts` 仍保持 9/37/49 与 43 实线/6 虚线。

- `elkjs` 只负责组内 TB 初始布局；限定于本图的正交路由器使用 A* 最小堆，严格检查 49 条线段与非端点节点、分区标题相交，标签也不得压住节点/标题。提交态预览为 `3771×3602`，检测结果 `collisions=[]`；预览是 ignored 审查产物，不作为运行验收。
- 基准实测：37/49 `arrange=452ms`、全量单次 route `64ms`、dataset 相邻 6 边 route `12ms`。拖动、加边与改标签只重算受影响边；详细路由不可达时保留内容并回退为简化正交路径，提示用户可显式重新整理，不抛 UI、不静默丢边。
- 默认数据组新增节点的旧位置可确定覆盖 dataset 并导致路由异常；最终改为按当前 children bounds 放入右侧空位并扩展 parent。可执行单测在布局 ready 后加入该节点，确认 49 条原边仍可路由。
- 初始/显式重排期间，顶部控制、React Flow 拖连与整个 inspector fieldset 都被 `layoutBusy` 禁用；初始 fit 无动画。drag start 会立即作废旧异步请求，防止旧 layout 在拖动中回写。旧草稿默认保持位置，只有用户确认“重新整理布局”才变化；变化进入 undo 且不会自动写 localStorage。
- producer 对 `5545be9e7951bbb63dbe5f1e54dedd9cfba4c9c9`、`8e0a6f56017399db2fa18c565b52b4ad315a2d69` 与 `fb195a8724e60d384b797e3205a9349a91d0d182` 逐次做提交态只读复审；最终结论无剩余 P0/P1。
- 最终代码/身份候选为 `d288d1bb46d6bcbb269a9771e255f375c018b6a0`；fingerprint `628b151d0431c5ea95925abd205b45edf1cb6344c80973bf1b300fb70c0b494e`。正式 main 仍停留在旧首轮发布 `df0e358f...`，所以旧 `21 passed / 7 failed` 必须保留，最终 11 条 BTC spec 与完整 29-spec architecture 套件均待 root 合入、canonical 重启后正式执行。

## 保持 fail-closed

`demo_control_enabled=false`、`promotion_ready=false`、`paper_enabled=false`、`live_enabled=false`、`private_endpoint_allowed=false`、`order_endpoint_allowed=false`、`real_order_submitted=false`、`transfer_allowed=false`、`withdraw_allowed=false`、`execution_permission=false`、`runtime_observed=false`。本票达标不会自动解锁其中任何一项。
