# 策略统一接入：V0—V3 当前架构与进度

核查日期：2026-09-20。核查主版本：`42673c9b323689168a5984651d7dc3127561003b`。
本记录是源码与已提交验收记录的综合评估，不是新一轮执行验收、实时账户快照或交易授权。
以下第 1—6 节保留当时的架构核查／候选快照；2026-09-21 的发布层级与自然历史阶段状态见第 7 节，不回写旧验收结论。

## 结论与下一步

**V3 未整体结项；核心离线实现已有独审，局部页面修复已正式发布。**
不能再把早期“保护归属未解决”“只读交付路径未建立”当作当前阻断；也不能把最近一次只读展示修复的验收，自动升级成原 V0—V3 全部交付完成。

下一步仅建议一次“最终交付收口”：把已有 Donchian 非零离线决策证据精确接到既有页面；固定版本汇总原验收清单，复用已经通过的源码、恢复、推理及页面证据，只补未覆盖的关联验证。通过则结项；未通过则说明断点、成本与路线，不自动追加工程。

不重训、不搜参、不扩市场、不新建控制台或 OMS，不修改默认策略、参数与环境特征用途，不启动 Demo／paper／live 或 M3—M4。**本次地图更新不实施上述下一步。**

## 1. 已实现的架构，统一什么

统一三个连接点：完整策略包的身份／版本；决策的时间、类型、单位与状态合同；决策到经济事实的证据关联。

```text
Alpha 工厂 / Qlib 研究 → 固定模型、特征、校准、候选政策（不在运行时训练）
                             ↓
Donchian 原方向信号          固定 Qlib 预测
原固定合约 / 退出            原校准 / 仓位 / 退出
          └─────────────┬─────────────┘
          单策略、单账户分别回放，不混合目标
                       ↓
现有 BTC T2/T3 → Guardian → OMS / 保护 → 权限校验 → 离线执行适配
                       ↓
             模拟成交 → BTC 持久账本
                       ↓
       版本化决策证据（不替代意图与账本的权威状态）
                       ↓
       既有研究台 / 组合 / 策略模块的只读关联
       Qlib 封存摘要已展示；Donchian 非零关联在本轮候选补齐
```

这不是美股决策服务接管 BTC，不是两个算法合并，也不是三市场执行语义已统一。美股、A 股仍保留领域边界；多策略账户预算、组合净额与归因不在本轮交付内。

核心入口：

- `quant_shared/strategy_runtime/decision_envelope.py`：版本化证据信封，精确绑定事件、输入、阶段及策略身份。
- `quant_crypto/application/donchian_offline_replay.py`：原注册信号与固定目标的限定离线场景、恢复和经济证据；不是无限历史回测器。
- `integrations/qlib_adapter/frozen_inference.py`、`candidate_policy.py`：固定推理及候选原政策。
- `quant_crypto/application/qlib_offline_replay.py`：固定预测进入原 BTC 权威链的离线回放、单写者、事件顺序、恢复和结果封存。
- `backend/app/services/offline_execution_views.py`、`frontend/src/workspaces/research/OfflineExecutionSummary.tsx`：提交态封存摘要的只读展示，不触发恢复或补算。

## 2. 分阶段验收事实

| 阶段 | 实现与已审证据 | 不能据此宣称 |
|---|---|---|
| V0 冻结与准入 | 原 Donchian 版本、0.01 合约目标、参数、Qlib 固定模型与合同均冻结；历史验收 219 passed | 候选有效或账户可交易 |
| V1 Donchian 纵向链 | 父订单关联缺口修复后，独审 V1 11 passed；归一化 15 passed、composition 19 passed；原策略与既有测试预期未改 | 所有交易所响应已验证、真实账户通过或 OS 强杀恢复已覆盖 |
| V2 固定 Qlib | 独审推理 28 passed，V0/V1 关联兼容 4 passed；13 特征、1,392 预测和固定校准核验，不训练 | Qlib 全局初始化适于并发长期进程，或当前候选值得交易 |
| V3 验收与发布 | 后续事件顺序／恢复源码已独审；正式 CLI 两次运行及同目录恢复已做；Qlib 离线摘要与缺证展示已限定发布 | 原定两个来源的最终页面与整体交付验收已经全部关闭 |

V3 最后集中回归真实结果为 **51 passed / 1 failed**；失败发生于测试期间 HEAD 移动。后续固定版本独审 **5 passed**，包含该失败用例及新增恢复断点。这是两份可关联证据，不改写为一次“52/52”，也不因汇总形式不同自动重跑整套实验。

Qlib 正式入口在 `7d686dbd6b8d63fd6c0b317e95ef23565ec4b924` 执行两次：1,392 次逻辑决策、22 个拒绝批次、0 个批准、0 笔成交；两次政策记录 SHA256 同为 `13a43a9723547bd8f517850567e79497ced5523f234efc7c255a37b41faaf51b`。这证明该固定候选的阻断与幂等，不证明非零经济过程；非零测试是单独标注的场景。

## 3. 原核查时还差什么，以及不再追什么

### 原目标内剩余缺口

1. **Donchian 的非零离线证据缺少同等的页面关联。** 当前读模型只接受 `m1-okx-qlib` 的精确研究身份；研究详情只在 `qlibId` 分支挂载离线摘要。摘要保留首尾决策预览，但其来源是零成交候选。未找到消费 Donchian 离线证据信封的对应前端／后端入口。V1 已有经济及恢复测试，不能用 Qlib 的零成交页面代替它的关联验收。
2. **分散验收尚未形成原目标的最终结项记录。** 首轮部署的页面缺证误导与缺少摘要，后续分别修复；最新展示票据明确只验收其限定范围。最终应把这些有效证据组合起来，而不是要求每份历史报告都回写“完成”。

### 不作为离线 V3 结项前置

- 生产 BTC 运行证据 503、未采集真实账户、尚无 Demo／paper／live 授权。这些仍是实际运行限制，必须如实展示，但不强行纳入本离线工程。
- Qlib 当前候选不合格、零成交，不是应该修改策略或换数据“做出成交”的软件缺陷。
- 未开展更多模型、环境特征接交易、多市场迁移，不是原 V0—V3 交付遗漏。
- 历史测试之外的 OS 级强杀、交易所真实部分成交等不能冒称已验；未列入本冻结离线矩阵的目标，需另行决定，不自动扩票。

## 4. 证据索引及版本关系

旧地图 `catalog.json` 的阅读基准、25 个模块说明及核心文件卡片原样保留，不伪造重新通读。M1/M2 旧快照仍在 `MILESTONE-STATUS-20260913.md`，页面显式标为历史记录。

本次按 `docs/architecture/strategy-v3-readonly-source-20260920.json` 的 88 条 Git 对象做只读 SHA256 比较：87 条相同；唯一不同的是 `docs/agent_playbooks/delivery_risk_policy.json`，即后续独审的 V3 只读交付治理修订。业务源码／测试对象未因最近的页面修复改变；这支持复用已审业务证据，不表示全仓测试已在当前 HEAD 重跑。

| 证据 | 已提交来源 |
|---|---|
| V0 冻结 | `docs/architecture/strategy-admission-v0.md`、`tests/fixtures/strategy_v0/baseline.json` |
| V1 最后父订单关联独审 | `docs/operations/btc-protection-parent-join-independent-review-20260915.md` |
| V2 推理独审 | `docs/operations/strategy-v2-frozen-qlib-independent-review-20260915.md` |
| V3 事件顺序／恢复独审 | `docs/operations/strategy-v3-event-ordering-independent-review-20260920.md` |
| 高风险源码＋只读发布规则独审 | `docs/operations/strategy-v3-readonly-release-independent-review-20260920.md` |
| 首轮正式 CLI／页面验收（当时部分拒绝） | `541398905` 对应报告：`docs/operations/strategy-v3-readonly-deployment-acceptance-20260920.md`；提交态读取，不消费私有工作树修改 |
| 后续只读缺证及摘要修复 | 主版本 `ea5d62324caf28fb8087f915ef35e08a2d411a30`，提交态 `.agent/offline_evidence/v3-readonly-20260920.json` |
| 最近展示修复正式验收 | 独审提交 `0234b7fbfbbdb999206d3b1b3aa40c2632adb776`：`docs/operations/v3-remaining-display-integration-20260920.md` 及同名 JSON；实际发布版本 `42673c9b323689168a5984651d7dc3127561003b` |

上述集成分支验收报告不在当前主树时，按精确 Git 提交读取，不为让文档出现在主树而移动主版本、重算模型或重建运行证据。旧 `strategy-admission-v1.md` / `v3.md` 中的阻断段落是当时快照，必须结合后续独审判断。

## 5. 前一地图票据的更新边界

本次仅更新 `/architecture` 的进度说明、总图节点措辞、静态文档和对应回归。页面把“技术验证”“页面发布”“整体结项”分开；新增的研究链接精确指向既有 `m1-okx-qlib`，不根据相似策略找运行记录。

不更改策略、模型、数据、API、执行链、权限、治理规则、历史证据或账本，不创建 runtime root，不调用交易所。地图发布采用 `research_readonly_release` 的独立审查路径；地图通过本身不使 V3 完成。

`promotion=false`、`demo_control_enabled=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`、`runtime_worker_enabled=false`、`runtime_observed=false`。

## 6. 本轮 Donchian 只读关联候选（源码基线 `e024f42468f4d0a7c39b83fe28ed86c5688459aa`）

上述第 3 节的第一个缺口已有提交候选：复用原 `DonchianOfflineReplay` 和原冻结 fixture，在仓库外状态目录经原信号、风控、OMS、模拟成交和持久账本连续运行。小型封存对象为 `.agent/offline_evidence/donchian-v3-closeout-20260920.json`，摘要 SHA-256 为 `a83e6745d485c0ce2e90259f284128722c4ae744d0bd8212d6114b7d8ce89a9a`。其五阶段精确关联为 5 条决策、4 笔模拟订单、4 笔模拟成交及 4 个对应账本事件；持有阶段无新经济事件。末期模拟账户权益 4999.988 USDT、仓位 0、手续费现金流 -0.012 USDT、实际资金费现金流 0。合成行情只用于信号，模拟器执行价固定 60000 USDT；这些数字不代表历史收益或真实账户。

只读服务从当前提交对象读取固定封存与 fixture，核对策略、参数、输入摘要、五阶段订单／成交／账本精确链接和 false 权限；坏封印、混合选择、错来源时显示阻断。原 `/api/research/btc/strategy-registry` 无参数响应保留；显式 `offline_run=donchian-v3-closeout-20260920` 返回该只读投影。现有 `/research?view=run-details` 用独立 `offlineRun` 显示 Donchian，仍用 `qlibRun` 显示原 Qlib 摘要；架构地图只增加该精确链接。

统一来源、验收覆盖与未运行项见 `docs/operations/v3-final-closeout-20260920.md`。**本节记录源码候选，不提前宣布 V3 整体通过。** 独立代码审查、正式 `research_readonly` 页面与发布验收结束后，由独立报告作最终通过／未通过判定；本地图继续把交易权限保持关闭。

## 7. 2026-09-21 增量：已发布源码与暂停历史阶段分开

注册主版本 `e2e7496acaa16b9fd5eda37dd65ea328a18ab032` 已包含上述五阶段 Donchian 只读源码；第 6 节的“候选”是历史措辞。后续独立集成回执 `78aaa489214c24f00e076eae0e11ec9089f2f544:docs/operations/v3-final-closeout-integration-20260920.json`（Git blob SHA-256 `e7475030f22e2159df1e4b7e887df631509de7a3f40f7dbfb6ef38a68e30a52d`）记载 `limited_offline_v3_pass`、`overall_v3_complete=true`，canonical `research_readonly` 页面已由主会话实测 Qlib／五阶段 Donchian 精确切换。自动 Playwright 未运行；独立验收限定于冻结离线工程，不代表全年历史、盈利性或任何交易权限。回执为避免移动当时已验收主版本，仅保存在集成分支 Git 对象中；不能因当前主树没有该文档就推断 V3 尚未结项。

另一个来源是原 Donchian 自然历史年度运行：计算源码 `897d5e99ebe4c898f71ac66cf33fb2d2420855d5`，run `donchian-effective-time-20250901-20260901`。其阶段只读核账回执 SHA-256 `cc4158866b38c25c4d4d2314671642169bd87304844e1557d7df1dbcc823f647`、报告 SHA-256 `643ec8de296ba254efb67dee77750fe1c7313991cfc434410eaa6903090b936f`；回执状态为 `stage_baseline_reconciled_research_only`。原运行暂停在 2960 / 8760 小时，30 条主决策关联与 26 条保护退出、共 56 笔模拟成交、28 次完整开平仓、370 条资金费已在原持久账本只读复核。价格盈亏 +0.0346310615、手续费 -0.26552203961525、资金费 -0.012403344923245647991，净额 -0.243294323038495647991 USDT，暂停时空仓、现金 4999.756705676961504352009 USDT。

本票只把该历史来源的小型提交态快照接入现有研究详情与地图链接：计算源码与页面发布源码分别展示；30 条主决策的 signal/target/risk/intent/order/fill/ledger 引用与 26 条保护退出分开，不补造信号值或真实成交。**这项阶段展示是 V3 结项后的独立只读候选**，仍待独立审查、限定发布及正式浏览器验收；当前主版本没有这份阶段快照。年度剩余 5800 小时、独立确认、真实账户和交易所对账未完成。M1 环境模型仍为研究旁路；M2 历史探索已结项且无稳定增量；M3—M4 未启动。`research_only`、`promotion=false`、Demo／paper／live／private／order／real_order／transfer／withdraw／execution_permission 均维持关闭。
