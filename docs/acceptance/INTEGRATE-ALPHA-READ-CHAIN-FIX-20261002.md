# Alpha 只读读取链独立集成报告（2026-10-02）

## 结论

`ALPHA-READ-CHAIN-FIX-20261002` 的最终提交态交付已完成独立源码审查、限定集成、
项目级静态验证，并已在 registered main `576096f625368029c36bfedb68d5c85bc380059f`
完成正式重启、身份核验和一次真实 Alpha 页面读取验收。

本结论只覆盖 Alpha 工厂 overview/detail 的只读读取生命周期：同键在途合流、取消、
错误代际隔离，以及 overview 等待与 detail 共享同一个 20 秒页面预算。正式页面的一次
真实读取已经通过，但冷直连 overview 仍接近 20 秒预算，所以不能据此宣称读取性能已经
全面根治，也不解锁候选管理、离线任务、Demo、paper、private、order 或 live。

## 固定身份与交付来源

- approved base：`23aab6e5a948dc611e762c3193d3f692b896a314`
- producer deliverable：`23afadd3da0b2e812c2f34b0c74afe4db7d4be3c`
- producer handoff commit：`6ea8c61a0b4092ecaad48a100ec7d678fbcb0dd9`
- canonical producer event：
  `.agent/handoffs/ALPHA-READ-CHAIN-FIX-20261002/published-alpha-read-chain-fix-final-20261002-23afadd3d.json`
- canonical event SHA-256：
  `d86f5c0d5d63a630ce046bb8f89ddb109aa5f7dfac3d58b344cfb424d79d617e`
- independent merge commit：`a8de8cdb4f377bad728d8a19bd2bc0529df2a407`
- initial integration report commit：`052258acc712644211564901dbc0edad8ba97820`
- registered main runtime HEAD：`576096f625368029c36bfedb68d5c85bc380059f`
- change risk：`research_readonly_release`
- readiness ceiling：`quality_checked`
- gate impact：`none`

`handoff.py validate` 对最终 canonical event 返回 `valid`；base 是 deliverable 祖先，
deliverable 是 handoff commit 祖先。交付中的五个 Git 对象 SHA-256 已逐项从
`23afadd3d...` 的 blob 独立重算，与 handoff 完全一致。前三条被拒绝的 handoff 事件
仅保留 append-only 审计历史，没有作为集成依据。

## 独立审查结论

初始 producer 版本没有直接放行。独审发现首次详情读取会先等待一个 20 秒 overview
租约，再新建一个 20 秒 detail 租约，最坏把固定页面预算扩大为近 40 秒；同时旧
overview effect 仅依赖跨 effect 的 `alive` 引用，存在 cleanup 后旧错误污染新代际的
风险。

最终提交态实现已修正：

1. selected 读取开始时记录 `performance.now()`，overview 的等待计入同一 20 秒预算；
   detail 的 HTTP timeout 与读取租约只取得剩余预算，系统时钟回拨也不能扩大预算。
2. 等待 overview 期间离开页面或切换来源，会释放租约且不再发送 detail GET。
3. overview effect 使用本 effect 的 active/sequence；旧 promise 的成功或失败不能写入
   新 read-only/StrictMode 代际。
4. overview、detail 和 action 错误分别保存；某一路成功不会掩盖另一条仍有效的错误。
5. 只复用已有 `research-read-request` 在途租约，不增加结果缓存，不改变通用 12 秒默认
   截止，不修改 backend 封印、catalog、认证或启动器。

最终生产代码变更只有：

- `frontend/src/lib/alpha-factory-api.ts`：Alpha 20 秒租约和 detail 剩余预算。
- `frontend/src/workspaces/research/AlphaFactoryConsole.tsx`：串行读取、取消及错误代际。

其余 producer 变更是既有 Node/Playwright 回归与验收说明。本集成另刷新
`frontend/public/frontend-identity.json`，仅绑定已审前端对象指纹；没有 backend、
策略、风险、OMS、账本、认证、启动器或权限合同变更。

## 独立验证

| 验证 | 结果 |
| --- | --- |
| producer canonical handoff validate、ancestry、五个 blob SHA-256 | 通过 |
| `node frontend/scripts/test-research-read-request.mjs` | `17/17` 通过 |
| `npm.cmd --prefix frontend run lint` | 通过；项目 `tsc --noEmit` exit 0 |
| `npm.cmd --prefix frontend run build` | 通过；`5403 modules transformed`，`built in 59.11s` |
| `npm.cmd --prefix frontend run identity:refresh` | 更新为 fingerprint `0f756c00ac17dd13563d8362836507d31c4d50526647274a00a6c086ac610e77` |
| `npm.cmd --prefix frontend run identity:check` | 通过；manifest match、baseline ancestor、dirty paths 为空 |
| `npm.cmd --prefix frontend run identity:test` | 正常本机权限通过；`object_targets=4` |
| scoped `git diff --check` | 通过 |

环境性失败也保留：第一次 build 已完成 5403 个模块转换，但 sandbox 无权在外置工作树
创建 `frontend/dist`，返回 `EPERM`；同一命令在正常权限下通过。`identity:test` 第一次
被系统脚本执行策略阻断，第二次被 sandbox 用户对主仓库的 `dubious ownership` 阻断；
没有修改系统 ExecutionPolicy、全局 `safe.directory`、hook trust 或身份校验器，第三次
以正常本机权限运行同一测试通过。

以下尚未运行，因此系统接入正式验收仍未完成：

- 测试包 GUI 的校验、模拟账户绑定、审定、登记、显式启动、重复启动、停止、同 job
  恢复、结果关联和 closed-ledger 核账；
- 最终恢复 `research_readonly` 后的安全归位。

上面两项必须在测试包系统接入完整生命周期完成后另行形成最终验收结论。

## Registered main 正式读取与浏览器证据

Root 正常合并后冻结 main 为
`576096f625368029c36bfedb68d5c85bc380059f`，并通过正式入口重启 canonical
`3000/8765`。前后端 identity 均显示 source/current main 为该 HEAD、
`canonical=true`、`runtime_stale=false`；前端 fingerprint 为
`0f756c00ac17dd13563d8362836507d31c4d50526647274a00a6c086ac610e77` 且
manifest match。后端仍是 `research_readonly`，`read_only=true`、
`controls_disabled=true`，paper/live/broker 均为 `false`。Root 另行独立复核了相同
身份与安全边界。

正式启动后，直连 backend 的一次冷路径测量为：

- Alpha overview：HTTP 200，`17,971 ms`，`8,048 bytes`；
- `m1-okx-factory` detail：HTTP 200，`3,476 ms`，`364,064 bytes`。

这组串行直连累计会超过 20 秒；它是必须保留的冷启动残余风险，不以延长页面等待、
反复刷新或暖缓存宣称解决。

随后只执行一次真实浏览器读取
`/research?view=alpha-factory&factoryRun=m1-okx-factory`，抓到一条 overview 请求
`4,204 ms`、一条 detail 请求 `2,803 ms`，合计约 `7,007 ms`，没有 alert。页面如实
显示 completed／完整性已核验、候选 0、淘汰状态、
`no_model_passed_selection_gate`、`audit_not_opened_no_eligible_model`、source stale 和
研究只读边界。截图：
`D:/quantstation-runtime/alpha-read-chain-formal-20261002-576096f6/alpha-real-selected.png`，
SHA-256
`9A81105FC2F2C6A41EBA45F84AE57EFA0B6604E7DF81FB9292E4CB35D58A5774`。
Root 已独立视觉核验该末帧。本证据只证明这一次正式读取在固定预算内完成，不替代冷路径
性能结论。

## Test-only 浏览器合同收口

第一次在正式 main 页面上运行既有 Alpha Playwright 集合得到 `4 passed / 5 failed`：

1. 三条既有受控研究动作测试没有 mock `/api/health`，因此继承正式
   `research_readonly` 后按钮被正确禁用；这不是生产权限缺陷。
2. StrictMode 用例把“在途同键合流”误写为“终态结果缓存”，期望 overview 永远只有
   一次。
3. 离页用例用整页 `page.goto` 模拟 SPA 离开，不能稳定表达组件 cleanup 的业务语义。

限定修正只触及 `frontend/e2e/alpha-factory.spec.ts`：fixture 明确模拟受控研究动作能力，
所有交易安全旗标保持 false；StrictMode 断言改为不允许重叠的 overview 请求，而不是
要求终态缓存；离页通过现有“架构地图”SPA 链接触发 cleanup。生产 API、Console、
20 秒预算、认证和权限源码均未再修改。

诊断 trace 记录：第一次 overview 于 `1790876936458 ms` 发起、
`1790876936565 ms` 完成；第二次于 `1790876936712 ms` 发起，即在第一次完成 `147 ms`
后才开始。它证明第二次是已结束后的新读取，不是并发重复请求。修正后的完整 Alpha
Playwright 集合为 `9 passed (39.1s)`；测试 runner 连接现有 committed main 3000，
没有启动 worktree preview/server，也没有向页面注入未提交生产源码。

本 test-only 收口合并后会产生新的最终 main HEAD。该 HEAD 仍须用正式入口重启并重新
核验 identity 和一次真实 GET/页面 smoke；本节的 F576 运行证据不得包装成新 HEAD 的
运行证据。

### Test-only 合并后的必要身份派生

Root 将 test-only 收口正常合并为
`a3da539094547842908d19652ef52fc4f809ddcd` 后，canonical frontend guard 正确拒绝旧
fingerprint：计算值为
`b7f5aa813eb44c45a3c96b61fc5f6c8c2381fa7382e115a7fda2c8cbf913164c`，配置值仍为
`0f756c00...`，`manifest_match=false`。因此该 HEAD 的服务尚未启动，不能把 F576 的
运行证据称为该 HEAD 的运行证据。

本票通过现有 `identity:refresh` 只更新
`frontend/public/frontend-identity.json`，将 baseline 绑定到 `a3da539...`，并记录
`frontend_runtime_inventory=d76376a187d50c7e354cf9de23f672c705bb2813`、
`frontend_src_tree=4e4bedfcfc1dbb37bb06ae99b87bc1ea0120a6b9`、
`powershell_launcher_blob=7b842ba9f58466c94b37607d004402a00ba9e429`、
`cmd_launcher_blob=98aa80ce4b6363c6c7bdd80a3b6fe8bc9c18d920`。随后 `identity:check`
通过，`manifest_match=true`、dirty paths 为空；`identity:test` exit 0。第一次在 sandbox
写外置工作树时 `identity:refresh` 返回 `EPERM`，没有产生 dirty；同一现有命令以正常
本机权限执行后通过，没有改 ExecutionPolicy、safe.directory、hook 或身份校验规则。

这是 test-only 合并所需的版本身份派生，不是业务逻辑修复。派生提交合入后仍须冻结新
main HEAD，用正式入口重新核验双 identity 和一次真实页面 smoke，之后才能继续测试包
GUI 生命周期。

## 尚未完成的系统接入验收

- 测试包 GUI 的校验、模拟账户绑定、审定、登记、显式启动、重复启动、停止、同 job
  恢复、结果关联和 closed-ledger 核账；
- 最终恢复 `research_readonly` 后的安全归位。

这些必须在 root 合并本 test-only 收口并冻结新的 main HEAD 后进行；禁止从本工作树
启动前端或把 mock Playwright 结果替代正式 public GET。

## 治理、dirty 与冲突保护

集成工作树由 planner 从 approved base 创建，`core.sparseCheckout=true`。开始集成前，
全部授权路径通过 `safe_status.py` 核验为 clean；producer 工作树的交付和 handoff 路径
也在提交后独立核验为 clean。合并无源码冲突，没有读取或覆盖其他代理的未提交文件。
主工作树原有两份用户知识文档 dirty 始终保留，本票没有读取、修改、暂存或回滚它们。

已读规则与 playbook：

- `docs/knowledge/README.md`
- `docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`
- `docs/agent_playbooks/shared_pitfalls.md`
- `.codex/agents/integrator.toml`
- `docs/agent_playbooks/delivery_risk_policy.json`
- `docs/agent_playbooks/delivery_paths/research_readonly_release.md`
- `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`
- Playwright skill（正式浏览器阶段使用 CLI-first）

catalog hash：
`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`

active pitfall IDs：

`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、
`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、
`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、
`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

## 仍保持 fail-closed

- 本报告不是 promotion evidence；未构建或刷新任何 promotion artifact/read model。
- `promotion_eligible=false`，`promotion/paper/live/private/order/real_order/transfer/withdraw`
  和执行授权均保持 `false`。
- F576 正式服务在真实读取阶段始终为 `research_readonly`；本工作树没有启动前端服务。
- 真实 v3 候选研究与 48 小时业务验收仍是单独未完成项；本票没有训练、重新拟合、
  调参、采集真实行情或修改策略成本/窗口。
- 旧失败命名空间和旧 blocked job 保持原样，不续跑、不删除、不改写。
