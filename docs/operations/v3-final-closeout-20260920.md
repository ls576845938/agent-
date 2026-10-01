# V0—V3 最终收口矩阵：独审与正式页面验收前的源码候选

票据：`V3-DONCHIAN-READONLY-CLOSEOUT-20260920`。执行源码基线：`e024f42468f4d0a7c39b83fe28ed86c5688459aa`。本报告只记录本轮实现和已提交历史证据的覆盖；独立集成及正式入口验收尚未发生，最终结论为 **待独审／待正式页面验收**。适用范围为固定 BTC 策略的离线软件正确性，不是候选收益或交易准入。

## 固定比较对象与新封存事实

- Donchian：`long_short_donchian_top5_okx_native`，版本 `btc_long_short_donchian_top5_okx_native@1.0.0`，参数哈希 `5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355`，单一离线账户，目标 0.01 张合约。原 `tests/fixtures/strategy_v1/offline_contract.json` 未改。
- 提交候选：`.agent/offline_evidence/donchian-v3-closeout-20260920.json`；封印摘要 `a83e6745d485c0ce2e90259f284128722c4ae744d0bd8212d6114b7d8ce89a9a`。读取器只能从当前提交对象取这一个固定文件及固定 fixture，无工作树／运行目录回退。
- 原五阶段：开多 → 持有 → 反向先平 → 反向开空 → 退出；5 条 `strategy_decision_evidence_v2`，4 笔模拟订单、4 笔模拟成交、4 个精确关联的持久账本提交。重复事件及重启按原测试顺序核对，不手填持仓或成交。持有阶段无新订单、成交及账本提交。
- 独审发现旧只读验证器可接受重封后的 `0.02` 合约成交或持有阶段仓位篡改。本票只收紧封存读取：按原 fixture 的 `0.01` 合约单位核对目标、订单计划、订单及成交数量，逐阶段核对仓位延续、方向、费用与资金费总和；固定 selector 还必须匹配上述已审摘要 SHA。**旧封存值及业务运行输出未重建、未改写。**
- 收益边界：合成 OHLCV 仅用于信号；模拟器执行价固定 60000 USDT，资金费率输入 0.0001，实际资金费现金流 0。初始模拟权益 5000 USDT，最终 4999.988 USDT，费用 -0.012 USDT，最终仓位 0。不得据此判断自然历史表现、部分成交或真实账户。

## 冻结验收矩阵

| 项 | 来源与已审覆盖 | 本轮实际工作 | 判定边界 |
|---|---|---|---|
| A 原策略与执行链不变 | `docs/architecture/strategy-v3-readonly-source-20260920.json` 的 88 个源对象先前比对 87 同一，仅已审只读交付政策不同；`aca55c90...` 至 `e024f424...` 的策略、执行、原 fixture 和原合同测试 diff 为空 | 本票不修改 `quant_crypto`、`quant_shared`、`integrations`、原 fixture／测试 | 独立集成需复核最终提交的文件集；不重新训练或回测策略 |
| V0 冻结 | `docs/architecture/strategy-admission-v0.md`：历史 219 passed，24 新增及 195 兼容 | 未复跑；基准只引用冻结版本 | 0.01 是合约张数，不是 BTC 数量；不是收益有效证据 |
| V1 Donchian 原链 | `docs/operations/btc-protection-parent-join-independent-review-20260915.md`：归属归一化 15、装配 19、原链 11 passed，含重复与恢复；独审 handoff 已验证 | 原 runner 在全网络 deny 下生成一次五阶段封存；逐次核对 decision、input、risk、intent、client/order、fill、ledger hash／投影／现金仓位 | 新封存证明确定性软件场景；OS 强杀及真实交易所未验 |
| V2 固定 Qlib | `docs/operations/strategy-v2-frozen-qlib-independent-review-20260915.md`：推理 28＋V0/V1 兼容 4 passed；独审 handoff 已验证 | 未重训、未搜参；旧 `m1-okx-qlib` 读取路径保留 | 当前候选不合格时正确阻断，不宣称值得交易 |
| V3 事件顺序、恢复和首轮发布 | `docs/operations/strategy-v3-event-ordering-independent-review-20260920.md`：51 passed / 1 HEAD 变动失败，固定 HEAD 独审 5 passed 包含该例；只读交付治理 144；首轮正式 CLI 两次每次 1392 决策、22 拒绝批、0 批准／成交 | 保留这些各自结果，未写成“一次 52/52”；新 Donchian 封存与旧 Qlib 零成交摘要独立显示 | 两次运行是历史 `7d686...` 来源，不自动升级为当前 runtime 证据 |
| D 错来源与安全关闭 | 原页面及 backend read model 各有源身份限制 | 固定 selector、提交态已审 seal SHA、Git 对象大小、fixture hash、策略/参数/包/决策 ID、0.01 合约及逐阶段仓位、订单成交账本投影关联、所有权限 false 的回归；重复、混合、latest、路径输入拒绝 | 缺证显示 blocked/not_bound，读取 API 不启动回放或恢复 |
| E/F 页面与发布 | 上轮地图发布与最近缺证展示各有独立验收；Qlib 零成交已有详情 | 在既有 `run-details` 增加 `offlineRun`，保留 Qlib 和工厂选择；持有阶段写明没有新经济事件；新增架构地图精确链接 | 工作树不得启动前端服务；正式 `research_readonly` 浏览器验收由独立集成完成 |

## 本轮测试与剩余判定

本轮 `py -3 -m pytest backend/tests/test_donchian_offline_views.py backend/tests/test_offline_execution_views.py -q` 为 **33 passed**；数量与持有仓位 5 个负例曾按 failure-first 先失败，修正后连同订单已成交数量、仓位计划、费用、资金费和重封引用负例通过。前端 SSR／链接 3 passed、地图 3 passed、TypeScript 检查和生产构建通过。新增页面 E2E 用例在候选工作树编写，但因前端只能从注册主工作树当前 main 启动，留给独立集成在正式入口执行。旧地图扩大回归已有 **21/22**，其中未改动的 `ArchitectureKnowledge.tsx` 文案断言失败照实保留，不纳入本票修复。

独审已从本票生成时的仓库外状态目录 `D:/vibe coding/Obsidian/量化系统/offline-runs/v3-donchian-closeout-20260920-e024f424-r3` **只读**核对 41 条原始持久事件的 hash 链、checkpoint／链尾，及封存所引 4 个事件的原文身份、raw payload SHA 与五账本投影。该目录不提交、不作为正式 API 读取源；正式 GET 每次只核验固定已审提交态 seal、当前提交态 fixture 和上述经济语义，不重新读取或重算外部运行账本。独审正式结论仍由独立集成报告落款。

发布验收停点：独立集成核对提交态证据、原业务对象未改、只读 API、Qlib 兼容、安全旗标与页面；通过后写一份最终通过／未通过结论和回退点，即结束本离线工程。生产 BTC `503`、真实账户、Demo／paper／live、OS 强杀及策略盈利不属于这次离线软件结项。`promotion`、`demo_control_enabled`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed` 均保持 `false`。

磁盘余量核查时 D 盘约 16.4 GB，本轮只生成上述小型封存 JSON；不扩展数据采集或大型 artifact 重建。临时模拟状态位于仓库外，不提交、也不作为 API 读取源。
