# 架构地图当前开发进度同步验收

日期：2026-09-29

票据：`ARCHITECTURE-MAP-STATUS-20260929`

核查基线：`3fc39879d14ecab2288368afe588385cc44c08e1`
变更风险：`research_readonly_release`

## 交付结论

本票仅更新 `/architecture` 的版本化开发进度快照、总图说明、分层说明和对应回归。既有五个视图、六分支总图、缩放／筛选／证据钻取交互及历史源码审阅基线均保留。新快照明确区分：已实现、历史测试、已合入或已完成页面验收、运行限制。

本票不把架构地图解释为实时账户、权限或交易监控，不声称在 `3fc39879` 重新通读全仓或重跑全部历史测试。它不修改后端、执行链、权限、交易语义、历史 `catalog.json` 或核心文件卡 `knowledge.json`。

## 当前状态事实

- V0—V3 是已冻结的限定离线工程结项：Donchian 五次决策、四笔模拟成交；旧固定 Qlib 运行 1392 次决策、零成交。该事实引用历史提交 `78aaa489214c24f00e076eae0e11ec9089f2f544` 中的结项报告，不改写为当前 HEAD 新跑结果。
- Donchian 自然历史阶段基线为 `2960 / 8760` 小时、已暂停、56 笔模拟成交、28 次 roundtrip、370 次 funding；计算来源仍为 `897d5e99…`。阶段只读页面已发布，历史执行 33 个 blob 已随 `441e057e2cdc84dd9dba32bf827fd150e614e0e2` 合入 main。
- 支持的登记候选离线 worker 目前限定 `factory_lgbm_ast_v1`，默认 `candidate_offline_enabled=false`。管理登记、离线诊断准入和可交易准入保持分离；研究只读模式不允许写入或启动。
- 市场状态 v2 已有 2960 bars、28 roundtrips、170 segments 的历史诊断；entry-only 条件默认关闭，只影响空仓新增风险。最新条件组在 `1956 / 2960` 因保护双触碰歧义阻断，不能称为完整增量证据；旧 M2 没有稳定增量，M3—M4 未启动。
- 证据注册表／Qlib 正式只读验收在 `3fc39879` 为 11 / 11 场景通过，每场景 12 次读取均在 12 秒预算内，最慢 8.293 秒，40 项聚焦回归通过。`CONFLICT`、BTC `503` 和 source-context 限制仍按原规则保留。

注册表验收外部不可变证据：

- `D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/deployment-acceptance-report-3fc39879.md`，SHA-256 `F57B014BDE1E963CCF71A4C110781021CC342B271F22E0238378C2825CA6C429`；
- `D:/vibe coding/Obsidian/量化系统/offline-runs/research-registry-request-chain-20260928/research-readonly-release-receipt-3fc39879.json`，SHA-256 `A5004F082F251D7403214F13761B58C2A9593E3FC7290A8080722369397612C9`。

这里只引用既有只读验收，不复制大产物、不重新计算。

## Producer 验证

| 验证 | 结果 |
|---|---|
| `node frontend/scripts/test-architecture-map.mjs` | 9 / 9 通过 |
| `node frontend/scripts/test-architecture-mindmap.mjs` | 6 / 6 通过 |
| `node frontend/scripts/test-architecture-knowledge.mjs` | 5 / 5 通过 |
| 主工作树 `tsc.cmd --noEmit`，只读复用其 `node_modules` | exit 0 |

Playwright E2E 本 producer 工作树不运行。正式合入后应由主会话在 canonical `3000` 端口以 `research_readonly` 验收五个视图、总图节点与缩放、状态筛选、三条历史证据链接，以及 390／1131／1440 三种宽度。正式验收前不得将本 producer 结果描述为已发布。

## 安全边界

- 不启动训练、回放、恢复或交易进程；读取页面不得触发上述动作。
- 不启用候选离线 worker、账户读取、Demo、paper、promotion、private、order、real order、transfer、withdraw 或 live。
- 历史实现与当前启用能力分开显示；缺失、冲突、阻断与未启动状态不得补造成通过。
