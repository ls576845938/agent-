# BTC 测试包系统接入正式验收（2026-10-02）

## 结论

本轮里程碑通过：一份明确标注为 `synthetic_fixture` 的固定测试包，已在正式 `main` 页面和正式 backend 上完成：

`真实页面选择 → 服务端包验证 → USDT 模拟账户绑定 → 人工审定 → 管理登记 → 显式启动 → 同请求幂等核对 → 安全停止 → 同作业恢复 → 页面结果读取 → 闭合账本核对`。

这证明的是候选接入、运行编排、恢复和账本闭环的软件能力，不证明测试模型有研究价值，不构成真实候选、48 小时业务验收、promotion、paper、Demo 或 live 证据。

## 身份与版本

- 正式运行／页面版本 `G2`：`ec1f098a6d827be6d45a903eb5bfc81aad079aab`。
- 研究包、模型和输入的历史计算来源：`4157ac389104cfaf50f8a2f48551dbb63f291067`。
- 页面明确分别显示 source/input `4157ac…` 与 execution/deployment `ec1f098a…`，没有把历史包篡改成当前版本训练结果。
- 外置验收根：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a`。
- repository owner：`8a790ee7bb21695904864e1f1d452fe9ea51e9f2a02a8664046e2d815881b6f2`。
- offline catalog：`fixture-v1`，SHA-256 `38c99e98a5601fc5b2d2b27801906acb648cd020dbe91f03e56a03ecb5befa9e`。
- package digest：`d23e917f1c3311b393bdcc14f08bb97e76fd43a6c3b718c2e4d9bba2531cd2af`。
- input digest：`6b2cf3c31096e6d28ed5748032bff8835df92d62101945cf514eb61637b9c435`。
- model SHA-256：`860406b530d4f7ab27e977fe9e5f944dce3d1e601498c514d73ba4d2a1e161bc`。
- bars SHA-256：`b2db1c52a444dc0cd5c5e3ec53d3d41ecb4dc9b4cae8f613a2f50ec82a9bc15c`。
- observations SHA-256：`0f9828a478704f84524cd808d79248e1332ac095a1cdd9e17af4262254efcdc3`。
- frozen evidence SHA-256：`c9d7505ba9dfbad2e74c86d1cb4acec1cc17b2be64031ecfdf313a301285c03a`。
- manifest SHA-256：`8ba61a550f6ac6c972629f806b650fc4fc7f91307f13db3e0173eaf3342608b5`。

新命名空间在开始前为 `0` 个 SQLite 文件，且 `economic-state` 不存在；没有复制旧管理数据库、旧经济状态或旧失败作业。模型、策略、参数、成本、窗口和输入字节没有重训或改写。

## 正式读取链

在进入候选管理窗口前，正式 G2 页面真实读取一次通过：

- Alpha overview GET：`6571 ms`，HTTP 200。
- selected detail GET：`4080 ms`，HTTP 200。
- 本次同页组合约 `10651 ms`，未出现 20 秒超时或错误告警。
- 这一步读取的是研究运行 `m1-okx-factory`：页面如实显示 `计算完成 · 已核验`、候选 `0`、淘汰结果 `no_model_passed_selection_gate`、`audit_not_opened_no_eligible_model`、历史来源版本、研究限制和交易未授权。证据截图为 `D:/quantstation-runtime/alpha-read-chain-formal-20261002-576096f6/alpha-real-selected-g2-trace.png`，SHA-256 `A178EC7C4A62AEA3A7617A604D27A7BF0AE23EFD07AB1B89D37EF306A66C6EFA`。后续候选管理窗口使用的 `synthetic-candidate-1` 是独立测试包，不属于这次 Alpha 正式读取烟测。

仍保留限制：此前冷路径 direct overview 实测 `17.971 s`，随后 detail `3.476 s`。本轮不能据一次通过宣布冷路径性能已被全面根治。

## 服务端发布、审定与登记

- 首次 immutable publication：`2363a3c387a5f5ddac03eadc41f4889a4396f4d93f7593d4420a46aa4542364c`。
- publication artifact digest：`5c478259e901fecd5f3649f5cd9bcd4255d52e63c5700c033a42ec512c18c037`。
- 正式页面管理记录：`delivery_807c67f46c584c699c5476532a624193`。
- 最终记录：revision `4`，status `registered`，account `fixture-account`，review `approve`。
- account 环境 `offline`、币种 `USDT`，与策略包 `BTC-USDT-SWAP / USDT` 匹配。
- 页面明确写明“已登记候选管理记录 · 运行另查”，未把登记包装成已经启动或获准交易。

publication API 的工具调用经历一次 30 秒 yield，随后约 7.5 秒返回；因为没有单独的请求开始／结束 trace，本报告不把它写成精确 35 秒或视为页面预算通过。

## 唯一作业、停止与恢复

- job：`coff_03a9756e8210947a92ee131a2ccb2354`。
- job identity digest：`18be425f79cacd6510b8224d54f63963977c5fc795084fb1abc572c1232adb0b`。
- 输入：`synthetic-input-v1 / synthetic_fixture`。
- 计算版本：`ec1f098a…`；输入／来源版本：`4157ac…`。
- 首次 GUI start 返回 HTTP 202、revision `1`。
- 捕获同一 `Idempotency-Key` 和同一 body 的补充 API 重放返回同一个 job、同一 revision `1`、HTTP 202，没有第二作业。此证据只补充幂等性，不替代 GUI 启动。
- GUI stop 返回 `stop_requested`、revision `5`；后端在提交边界落为 `stopped`、revision `7`、cursor `1/2`、blocker `null`。
- 从 stop 提交到停止更新时间约 `207 s`。这是真实提交边界延迟，不是扩大页面 HTTP 超时；没有手工改状态或缩短输入。
- GUI resume 返回 HTTP 202、`queued`、revision `8`，恢复同一 job；终态 `complete`、revision `13`、cursor `2/2`、blocker `null`。
- 两条决策 cursor 精确为 `1` 和 `2`；receipt SHA-256 分别为 `855b7307545e5bdef2d0730da5cf968d3c62e57e07f4ddfa6e1115b1698b0fcc`、`9e2d40241abbfe85b723b41e4ac13da02110bdd550bcf11c993c576a89e942bf`，都绑定同一 job identity。

本 worker 是正式 backend 进程内线程，不是另一个 coordinator 进程。job 进入 `complete` 后，candidate-management backend PID `24040` 已停止；随后使用官方 current-main 启动器恢复新的 research-readonly backend，因此不存在继续运行的候选 worker 或候选写服务。

## 经济结果与核账

- result SHA-256：`377593e520a009a94482db0054813cbc0b15e6f7a2afab7e4c4aced8b8c9e45d`。
- 固定窗口：`2/2` 个 synthetic 事件。
- 模拟订单：`2`；模拟成交：`2`；最终持仓：`0` 张 / `0 BTC`。
- 唯一成交：
  - `tradeId=qlib-offline-fill-1`，buy `0.01` 张，价格 `101.48666434504989043`，fee `-0.0000050743332172524945215 USDT`。
  - `tradeId=qlib-offline-fill-2`，sell `0.01` 张，价格 `101.8353846164790018`，fee `-0.00000509176923082395009 USDT`。
- 初始权益：`43.95247225902749 USDT`。
- 价格盈亏：`+0.000034872027142911137 USDT`。
- 手续费：`-0.0000101661024480764446115 USDT`。
- 资金费：`-0.0001 USDT`，`1` 笔资金费事件。
- 未实现盈亏：`0`；其他现金流：`0`；最终仓位为零。
- 桥接：`43.95247225902749 + 0.000034872027142911137 - 0.0000101661024480764446115 - 0.0001 = 43.9523969649521848346923885 USDT`。
- 原账本投影：`status=reconciled`、`reconciled=true`、blockers `[]`，final observed equity 与 final equity 完全一致。

保护成交在页面仍明确标为未支持；本测试未触及保护歧义，不能把它宣传为保护路径业务验收。

## 正式页面证据

- 登记页：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a/gui-registered.png`，SHA-256 `f94305c53ca558d5e7d3023b0eb7949744d7a02c1316dd01053f96580df4d982`。
- stop_requested 页面：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a/gui-lifecycle-final.png`，SHA-256 `90b22a4db9536bfaa0b30e88ac9156509e2c2f38f4503594d1957ada9dbb47c7`。
- 最终结果页：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a/gui-result-final.png`，SHA-256 `04f4ef6dc871a1e4aef0992895d10bd87e8509aacf50722964532f2df3044d4d`。
- 最终结果网络／DOM trace：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a/gui-result-trace.json`，SHA-256 `44c7c4d97674627ae3c38d7453e0628e1f8a13444cc6c62fa38211e532a11ece`。
- 管理记录只读 trace：`D:/quantstation-runtime/btc-system-intake-formal-20261002-ec1f098a/gui-approve-register-trace.json`，SHA-256 `7ce1008fc3af9c5253b66d89c36053b29d9e32e9e2ffb7095fb3bce40747f232`。

QA 口径修正：第一次管理脚本在写最终 trace 之前退出，随后脚本仍按旧的 `validated` 标题等待而超时；实际 DOM 和服务端只读记录已显示 revision 4 / registered。首次 lifecycle 脚本用 `JSON.stringify` 比较键顺序不同的等价幂等响应，误报 mismatch；同 job、revision 和 HTTP 状态一致。恢复轮询脚本后按要求人工中止以避免每 3 秒 GET 争用，因此没有该脚本的 finally trace；真实 resume 回执、低频终态 GET 和最终正式页面结果保留为权威证据。上述 QA 假失败没有被包装成业务缺陷。

## 恢复只读与安全边界

验收后已停止 candidate-management backend，并通过官方 current-main 启动器恢复：

- backend source/main：`ec1f098a…`，`research_readonly`，canonical `true`，runtime stale `false`。
- frontend source/main：`ec1f098a…`，fingerprint `b7f5aa813eb44c45a3c96b61fc5f6c8c2381fa7382e115a7fda2c8cbf913164c`，manifest match `true`。
- `read_only=true`、`controls_disabled=true`。
- `demo_control_enabled=false`、`execution_permission=false`、`runtime_observed=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`。
- 未读取密钥、私有账户或交易所接口；未发真实订单；未访问 private/order/live endpoint。

管理记录、作业和结果的动态读取是在限定的 candidate-management 窗口完成；恢复 `research_readonly` 后候选离线管理能力与命令重新关闭，不能继续从该 profile 动态读取这份管理结果。封存截图、trace、不可变 publication、result SHA 和 closed-ledger 核账回执承担本轮验收证据；本票没有为方便展示而扩大只读部署的认证或 GET 合同。

## 测试、继承证据与未运行项

本票没有修改业务代码，也没有重跑无变化全仓测试。继承并明确区分：

- registered catalog guard 修复的 producer / independent integrator 证据已进入 G2；正式本轮 GUI worker 是额外正例。
- Alpha read chain：Node contract `17/17`、正式页面 e2e `9/9`、build/lint/identity 检查在上游集成票通过。
- 本轮正式页面与业务验收使用正式 `main:ec1f098a…` 的 `3000/8765`，没有启动 worktree preview。
- 未运行真实候选研究、48 小时观察、Demo、paper、live 或交易所账户验证。

## 治理、dirty 与职责

- `change_risk=research_readonly_release`（此前 guard 修复按 `unclassified` 独立集成；本票不新增生产变更）。
- readiness 仅 `quality_checked`；gate impact `none`。
- 本票专属 sparse worktree 基线：`ec1f098a6d827be6d45a903eb5bfc81aad079aab`。
- 本票 touch set：本报告与 append-only handoff；临时 GUI harness 不提交。
- 本票初始 scoped dirty：空。
- 注册主工作树已有两份用户知识文档 dirty 由 root 核对并保持哈希不变，本票未读取差异、覆盖、清理或提交。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 读取 playbook：shared pitfalls、integrator pitfalls、preflight、gate evidence review、handoff、Playwright。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

## 未完成项与停止条件

以下均保持未完成／fail-closed：

- 真实 v3 候选尚未产生，真实候选研究和 48 小时业务验收未开始。
- 本测试包只有 2 个 synthetic 事件，不能替代真实行情、真实候选有效性或年度评估。
- Alpha 冷读取接近 20 秒的性能余量仍是限制；不自动派生新工程票。
- protection 路径未在本轮证明。
- promotion、Demo、paper、live、private、order、real order、transfer、withdraw 继续关闭。

因此当前“测试包系统接入正式验收”可结项；真实候选研究继续单独保留为未完成项，不重复 R2，不自动启动 R3 或真实数据采集。
