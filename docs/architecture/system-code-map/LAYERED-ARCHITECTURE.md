# QuantStation 分层架构说明

本说明对应 `/architecture` 的“分层架构说明”视图。它解决的是后续开发者如何从模块职责定位到源码，不是运行监控、测试收据或交易权限证明。

## 三层阅读入口

1. **25 个模块边界**：每个现有 catalog 模块登记输入、输出、上下游、职责边界和关键入口。模块关系表示职责归属，不证明同一次 runtime 已跑通。
2. **28 张核心文件卡**：覆盖共享合同、Alpha/Qlib、BTC/US/CN、后端启动与前端工作台。每张卡记录用途、入口、消费者、副作用、修改禁区、测试，并绑定确切 Git commit/blob；blob 改变即标记为需复核。
3. **10 个普通文件分组**：按领域合同测试、研究测试、前端、后端服务、数据适配、监控报告、兼容、schema 和治理启动等 pattern 缩小阅读范围。分组说明不是逐文件职责摘要。

机器可读单一来源是 [knowledge.json](../../../frontend/src/workspaces/architecture/knowledge.json)。原 [catalog.json](../../../frontend/src/workspaces/architecture/catalog.json) 继续独立记录历史逐文件阅读和调用证据；不能用职责卡回填或替代 catalog 的 EOF 审阅事实。

## 修改时怎么使用

- 先从模块卡确认输入、输出、上游、下游和边界。
- 再核对目标核心文件的当前 blob；若已 stale，重新阅读该文件和对应消费者，不能沿用旧摘要。
- 普通文件按分组 pattern 定位。无论是否有卡，修改后都要核对目标文件、受影响调用方和相关测试。
- 静态说明只证明来源绑定；浏览器、后端、current-main 身份和业务流程必须用各自验收证据验证。

## research_readonly 后端边界

`research_readonly` 是显式 opt-in 的只读证据 profile；默认仍为 `promotion_strict`。允许的 GET/HEAD 路径仅包括 identity、health、strategies、单个/列表 task、Qlib run、Alpha Factory run、evidence registry 和 BTC domain read model。其他 GET 以及全部业务写请求在进入 handler 前返回 `423`；`OPTIONS` 仅服务 CORS。

只读 profile 不构造 Demo runtime、US IBKR service/provider 或 private projection。可选 artifact 缺失仍返回真实错误，不伪造 ready；未知 profile 冷启动 fail-closed。新增 health 字段由仓内 app factory 显式提供，仓外旧代码若直接构造 schema 尚未验证。

## 2026-09-29 状态边界

- 历史 `catalog.json`／`knowledge.json` 基准继续分别绑定 `7403c…` 与 `ecde…`，没有因本次状态同步宣称重新通读全仓。
- 市场状态 v2 与历史诊断已实现；entry-only 条件政策默认关闭。最新 conditioned 臂在 `1956 / 2960` 阻断，完整增量未成立，M3—M4 未启动。
- 策略包 v3 的验证、审定、USDT 绑定与登记已接通；候选离线 worker 仅支持 `factory_lgbm_ast_v1`、默认关闭，旧 M1 v2 仍只可管理诊断。
- Donchian 长历史执行改动已合入 main；`2960 / 8760` 阶段快照已核账并发布，但年度暂停。
- 研究读取链已在 `3fc39879` 完成 `11 / 11` 正式页面场景验收；`CONFLICT`、BTC `503` 和 source-context 限制继续保留。
- 真实账户只读验收未完成，候选离线能力没有转换为 Demo、paper 或 live 权限。
- Alpha/Qlib 研究完成不会自动晋级。
- `runtime_verified=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`。
- 本说明不改变 BTC 信号、仓位、退出、风险、OMS、保护单或账本语义。

静态校验：

```powershell
node --test frontend/scripts/test-architecture-knowledge.mjs
node frontend/scripts/architecture-review.mjs --ref=HEAD
```

第二条命令同时报告旧 catalog 的源码漂移；非零退出可能是预期漂移，必须分别查看 `catalog_errors`、`knowledge_errors` 与 changed/added/deleted，不能把它解释为交易 gate 结论。
