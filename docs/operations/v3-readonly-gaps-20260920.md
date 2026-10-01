# V3 只读展示缺口修复

状态：源码候选，待独立集成与 canonical 页面验收；不宣称正式发布完成。

## 边界

- ticket V3-READONLY-GAPS-20260920；role super_developer；change_risk research_readonly_release。
- base 7d686dbd6b8d63fd6c0b317e95ef23565ec4b924；专属 planner sparse 工作树 super_developer-v3-readonly-gaps-20260920。初始限定 dirty clean，无覆盖其他任务。
- touch set：DemoTradingConsole 与纯展示 account-facts-view；ResearchRunDetails 与 OfflineExecutionSummary；两个同名前端回归；app_factory 的既有 Qlib 详情响应；offline_execution_views 与测试；seal_v3_offline_summary；.agent/offline_evidence/v3-readonly-20260920.json；前端派生 identity manifest；本报告及本票 handoff。
- 不改策略、仓位、退出、风控、OMS、保护、账本、启动器、权限、治理或运行存储。无 broker/private/order/账户调用；无训练、搜索、策略重跑。

## 修复事实

账户快照缺失、读取失败、对账未完成、无时间戳、仓位格式错误时不再显示 FLAT；挂单、保护单、成交、资金费条数缺失显示未知。显式已对账空数组才显示零。多头空头并存时全部展示，不只显示首个仓位。操作授权仍完全来自原后端合同。
独立审查同票补齐：资金费条数漏项；数值 null/空白/布尔值不转换成零；账户更新时间不借用运行时历史对账时间。失败优先断言后回归通过，TypeScript 单独捕获 exit=0。

V3 摘要通过既有 Qlib 详情接口附加，与旧研究账本、七层研究记录及实际账户分开。消费者只读取当前提交里的固定 Git blob，不读取工作树脏文件或离线运行目录；无请求路径/ref 选择器、无 latest 或替代样本。run/candidate/strategy/version/data/dataset digest/model digest 必须精确匹配，缺失或不符仅阻断新摘要区块，不改原研究证据。

封存器仅接受已审的五个原始文件固定 SHA256；完整验证事件/semantic/decision hash 链、checkpoint tip、1392 条精确关联、权限 false，并复用现有纯账本函数重算经济事实。只输出 JSON，不写原产物。摘要是 Git 提交态封存报告，不是新的 runtime artifact，也不是实时账本。

原始 capture：offline-runs/v3-readonly-20260920-7d686dbd6（仓库外本票已知产物）。计算 HEAD 保持 7d686dbd6，不替换成页面发布 HEAD。24 事件、22 拒绝批、1392 决策、0 获准、0 订单、0 成交；模拟权益 100000 USDT，仓位/手续费/资金费零。

必须分开：行情决策覆盖 2026-06-01 至 2026-07-28，模拟账户观察仍在 2026-06-01T00:59:59+00:00。此为全部拒绝后未变化的初始账本，不证明全周期真实账户或非零成交能力。首尾两条仅为预览；全量精确关联在封存时校验，不按相似时间拼接。

## 回归

- failure-first：前端账户 helper、离线组件及后端读取器各因未实现而失败；随后针对性测试通过。
- `node frontend/scripts/test-btc-account-facts-view.mjs`：缺失/显式零/非法数值/多仓位/展示接线通过。
- `node frontend/scripts/test-offline-execution-summary.mjs`：SSR 身份错配、权限、缺失、零成交、双时间边界通过；不替代真实页面验收。
- canonical Python `-B -m pytest -q -p no:cacheprovider backend/tests/test_offline_execution_views.py backend/tests/test_research_readonly_views.py backend/tests/test_backend_research_readonly.py`：63 passed, 2 skipped（Windows symlink 不可用）, 1 已有依赖弃用 warning。首次 broad collection 因 sparse 缺 quant_cn 失败；只补读取 cone 后重跑得到上述结果。
- frontend TypeScript `--noEmit -p frontend/tsconfig.json`：独立捕获 exit=0；Vite 构建 5261 modules、1m15s 通过，仅既有大 chunk warning，审查修订后由独立集成复验。
- test-btc-demo-start-feedback、test-research-read-request（5项）、test-research-rollback：通过。
- test-research-portfolio-contract：失败于冻结依赖 research-api.ts 与旧 13486a7 基准差异。该测试与 research-api.ts 均与本票 base 完全一致；不是本次改动，不改预期来做绿，列为遗留限制。
- 封存脚本针对明确 capture 运行成功，源码证据与原始文件未改。新增读取器覆盖错误身份/模型/摘要篡改/危险权限/无 Git 不能回退/提交态优先/拒绝其他源。

## 发布与停止条件

仅独立 integrator 审查提交态 diff、hash、测试和 append-only handoff 后集成。注册 main 回退点为本票 base；使用既有 canonical launchers，research_readonly、fixture fallback false、demo control false。正式页面验收：/crypto 缺失账户不显示零；精确 m1-okx-qlib 详情显示独立离线摘要、真实来源版本、零成交与缺证边界；不存在运行仍明确报错；写操作仍被拒绝。

注册表冲突/读取延迟与 BTC production root 缺失503保持真实，不重建假证据，不作为本轮自动扩展任务。通过此限定展示验收即结束；失败只报告本次直接断点，不自动追加模型、控制台、M3—M4或交易任务。

## 预检与安全

读取 preflight/gate-evidence-review/handoff、knowledge README/non-negotiables、shared/super_developer playbook、domain_architecture_rules、research_readonly_release。catalog 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
活动 IDs：GOV-CONCURRENCY/DIRTY/ENGINEERING-CIRCUIT/HANDOFF/OBJECTIVE/PITFALL/ROOT/STORAGE/WORKTREE/PROMPT/WINDOWS；MONITOR-AUDIT-001、QSYS-GATE-001、RESEARCH-HOLDOUT-001。
readiness 上限 quality_checked；promotion、paper、live、private、order、real_order、transfer、withdraw、execution_permission、runtime_observed、demo_control_enabled 全 false。没有 current-HEAD 运行或晋级证据；源 capture 属于历史代码版本。未运行真实账户、交易所或非零成交试验。
