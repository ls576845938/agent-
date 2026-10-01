# STRATEGY-ALPHA-PARAMETER-MAP-01 独立源码集成

## 集成决定

- Role: `integrator`; change_risk: `unclassified`; gate_impact: `none`。
- Base/main: `4096453b344e777e99f4272b43582d60cf1251f9`。
- 架构师批准消费 `published-strategy-alpha-parameter-map-01-b5aef3559`；producer deliverable `b5aef35597c2e75010eba65372a979c650372d90`，handoff commit `224f8e0cd129162c3647debeba7ffd081a2ac40d`。
- `handoff.py validate` 返回 `valid`；base→deliverable→handoff 祖先链成立，交付路径哈希、schema、测试证据、blocker 与安全 guardrail 通过校验。
- 使用 `--no-ff` 将批准的单一 handoff set 合入短生命周期 planner sparse worktree；无冲突、无共享合同扩项、未消费其他 worktree 未提交文件。

## Touch set 与职责

- Producer 已批准路径：历史报告只读 API/校验服务、参数快照发布脚本、显式 history root 启动绑定、Alpha 来源分类、参数稳定性热力图、局部样式、测试、producer 报告及 append-only published handoff。
- Integrator 自有路径：`frontend/public/frontend-identity.json`、本报告、后续 append-only integrated handoff。
- 前端 identity 以 no-ff merge commit `91325acaee06cebc70cea81e2b03093268b27fe9` 刷新，fingerprint `c1c7945797394e40438ee77857e5d2ca6143f943f3414cea9d44fc323fac8209`。
- 未触碰并仍未合并的其他任务：ResearchDashboard 及其本地组件/样式/测试/报告。未覆盖、回滚或清理其他代理文件。

## Dirty、规则与测试

- 集成 worktree 与注册主工作树在声明的 17 个源码范围内初始 `dirty_count=0`；两处 `core.sparseCheckout=true`，main 当时仍精确位于 base。
- 已读：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator profile、delivery risk policy、quant-agent-preflight、quant-agent-handoff。Integrator 专用 pitfalls 文件不存在；未全文加载历史事故日志。
- Catalog hash: `127da8cce21efec826410506f35dd59e219ba9e15661d757a5937a47860fab3c`。
- Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001。
- `node frontend/scripts/test-strategy-parameter-map.mjs`: PASS。
- `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`: PASS。
- `python -m pytest backend/tests/test_strategy_parameter_evidence.py backend/tests/test_btc_strategy_history_api.py -q`: 33 passed，1 个既有 Starlette/httpx deprecation warning。
- Producer 已报告 `vite build` PASS；integrator 未重复构建。Canonical 浏览器/API 及 runtime snapshot 验收尚未运行，由 root 在源码接入 main 后完成。

## Artifact、freshness 与 fail-closed

- 本阶段只集成源码，没有 bootstrap、发布 artifact、配置环境或重启服务；没有 artifact/manifest/ledger/replay 产物。
- 待 root 独立执行的顺序：外部 owner-marked root bootstrap → hash-bound 参数快照 publication → history env 绑定 → canonical backend/frontend restart → API/浏览器验收。
- 历史研究源 SHA-256 `406cfb9f2bf0facb0c1445c65aca601cc5c930c992c35dcc0f810aa8f1a9fd22`，但 `source_data_hashes_unavailable`，且样本已参与选择；只可称 historical research evidence，不是 current-HEAD replay/promotion evidence。
- 保守政策要求的 promotion artifact/read model 未重建，promotion gate 继续 blocked；此 gate_impact=none 票据不扩展为无关 gate 工程。
- promotion、paper、live、private、order、real_order、transfer、withdraw 均保持 `false`；没有 private/broker/order/live endpoint、secret、真实订单或外部 push。

