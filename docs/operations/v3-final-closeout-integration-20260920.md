# V3 最终收口：独立候选审查（正式发布前）

票据 `V3-FINAL-CLOSEOUT-INTEGRATION-20260920`，`change_risk=research_readonly_release`。独立审查结论是 **源码候选通过、正式 main 发布与浏览器验收未完成**；本版不宣布 V3 整体结项，不是 promotion、paper 或 live 证据。

## 候选身份与边界

基线与回退候选为 `e024f42468f4d0a7c39b83fe28ed86c5688459aa`。已审 producer 修正 deliverable `e80fe7a79851a49e15eaaac4bea42c0ce39fbe20`，append-only handoff `v3-donchian-source-correction-e80fe7a79` 位于 `120a0dc4bd419f9539c278a7a94d4d4e3c618c64`，独立 CLI 校验 `valid`，旧 `be0bf76a7` 发布事件被 supersede 而未改写。专属 sparse 工作树为 `D:/vibe coding/Obsidian/量化系统/worktrees/integrator-v3-final-closeout-integration-20260920`；no-ff 集成 `47ef33e0f5716177c257c0ad682056a0a641a2ca`，机械前端身份提交后的候选为 `ce35a2bc378f020371a23718a2e02f78018457a2`，tree `257e815ec723674ee631a3bf1dca3f7d456715f5`。main 在审查时仍为基线；主会话才可按授权发布，随后核对 tree 完全相同。前端指纹 `3c96bb6fdaa3b50e1c9849300dd1d82228d24bb63b55dcb9df5df4b47beab5f9`，identity baseline 为独立 merge commit。

变更严格为同目录 JSON 所列 20 路径：17 个 producer 源码／文档／测试／封存／一次性离线封存脚本，2 个 append-only 上游 handoff，1 个机械身份清单。未修改 `quant_crypto`、`quant_shared`、`quant_us`、`quant_cn`、`integrations`、原 fixture、原执行链、启动器、治理规则或权限；无冲突，初始限定 dirty `[]`，已合入路径提交后 clean。脚本只在显式 CLI 生成离线封存，正式 GET 不调用它；不重训、搜参、采数或重建生产 artifact。

## 独立核验与保留限制

原封存的 5 阶段为 5 决策、4 模拟订单、4 模拟成交和 4 个精确账本引用；hold 无新经济事件。原 fixture 固定每次 0.01 张 OKX 合约、模拟成交价 60000 USDT、费用合计 -0.012、实际 funding 0、终值 4999.988、终仓位 0。合成 OHLCV 仅供信号，不是自然历史盈利或真实账户。本次先复现旧 validator 可接受重封数量／hold 仓位篡改；producer 在同票补了数量、目标、方向、费用与逐阶段仓位交叉约束，独审同样的七组负例现全部拒绝，原封存通过。任意重封 `event_hash` 或 `raw_payload_sha256` 在内部投影 validator 不是原始账本验真；正式读取入口以已审摘要 SHA 钉住唯一 run。发布独审还只读核验了外部精确目录中 41 条原始事件的 sequence/previous/hash 全链、checkpoint 和封存引用的 4 条原事件 raw payload SHA、五账本投影。正式 GET 只读提交态 seal/fixture，不读外部目录或执行恢复。

历史矩阵照实引用：V0 历史 219（24+195）；V1 归一化 15／装配 19／原链 11；V2 28+4；V3 事件顺序 51 passed、1 次 HEAD 变动失败，固定 HEAD 独审 5 覆盖该失败例，**不写作一次 52/52**；既有治理 144。旧 Qlib `m1-okx-qlib` 两次各 1,392 决策、22 拒绝批、0 批准／成交仍是历史来源，和本次 Donchian 模拟链分别展示，不自动升级为当前运行证据。冻结的 88 个源对象上轮为 87 同一、仅已审交付政策变化；本次从 `aca55c90...` 到基线的执行领域路径无 diff。本轮没有重跑历史模型／经济矩阵。

独立命令结果：`py -3 -B -X utf8 -m pytest -q -p no:cacheprovider backend/tests/test_donchian_offline_views.py backend/tests/test_offline_execution_views.py` 为 **33 passed**；`node --test frontend/scripts/test-donchian-offline-evidence.mjs frontend/scripts/test-strategy-delivery-map.mjs` 为 **6 passed**；`npm.cmd --prefix frontend run lint -- --typeRoots <main node_modules/@types> --baseUrl <main node_modules>` 类型检查通过；复用主树已有依赖的专属工作树联接后 `npm.cmd --prefix frontend run build` 通过，5,262 modules，仅既有大 chunk 提示。`git diff --check` 通过。首次无联接的 lint/build 只因 sparse 工作树缺依赖失败；没有安装依赖。自动 Playwright E2E、正式浏览器、当前 main API/服务身份尚未运行，不能拿组件测试替代。

发布前后端旧 listener 由主会话独立核实，但当前旧 profile 为 `demo_quasi_live`、`read_only=false`、`controls_disabled=false`；旧 health 中 broker/order 等 false 不等于真实账户证明。主会话将按既有启动器转为 `research_readonly`，并在正式 main 上核 `canonical=true`、`runtime_stale=false`、只读/禁控及真实页面；本报告当前不预填通过。生产 BTC artifact root 缺失／503、真实账户、OS 强杀、盈利、Demo/paper/live、M3–M4 均不纳入本离线软件结项，也不因本候选解锁。`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_worker_enabled`、`runtime_observed` 保持 false。

预检读取 `AGENTS.md`、知识 README/non-negotiables、shared pitfalls、integrator TOML、`research_readonly_release.md`、delivery policy；仓库无单独 integrator pitfalls 文件。使用 quant-agent-preflight、quant-gate-evidence-review、quant-agent-handoff。catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中 `GOV-CONCURRENCY-001,GOV-DIRTY-001,GOV-ENGINEERING-CIRCUIT-001,GOV-HANDOFF-001,GOV-OBJECTIVE-001,GOV-PITFALL-001,GOV-ROOT-001,GOV-STORAGE-001,GOV-WORKTREE-001,GOV-PROMPT-001,GOV-WINDOWS-001`。未全文读取历史踩坑日志，未访问 secret、private、broker、order 或 live endpoint。
