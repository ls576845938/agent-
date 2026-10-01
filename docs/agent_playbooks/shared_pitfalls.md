# Shared Pitfall Rules

这些规则适用于所有代理。它们来自 BTC、美股、A 股和监控/回放踩坑日志，是项目级硬约束。

## 启动顺序

1. 先进入真实代码仓库 `D:\vibe coding\Obsidian\量化系统\agent-`，不要在 Obsidian 根目录里误判项目结构。
2. 先读 `AGENTS.md`、`docs/knowledge/README.md` 和本文件。
3. 按角色读取对应 playbook，并通过 `tools/agent_governance/context_packet.py` 读取匹配的 active pitfall IDs。
4. 先声明 touch set，再运行 `py -3 tools/agent_governance/safe_status.py --path <repo-relative-path>` 检查相关源码；非 sparse 工作树禁止无 pathspec 的全仓 `git status` 或 `git diff`，运行数据和 artifact 使用 manifest/hash 核验。不要覆盖、回滚、清理其他代理留下的文件。
5. 仅在命中 catalog source、调查历史事故或补 catalog 时定向读取原始踩坑日志；默认不全文加载。
6. 如果任务涉及 gate、artifact、readiness、paper/live，必须读取当前最新 artifact 或重建当前 HEAD 证据；不能引用旧结论替代当前事实。
7. 运行 `context_packet.py` 时显式传入 `--change-risk`。无法分类时使用 `unclassified`；不要用 severity 代替 applicability 判断。

## 变更风险选择

- `global_invariant` 是真正的全局硬线；只有 `shared` scope 可跨领域自动匹配。`governance` scope 不再让规则自动进入所有任务。
- `conditional_guardrail` 只有在 catalog 的 `applicability.change_risks` 命中时进入已分类任务；历史 incident guardrail 必须定期复审并满足 sunset criteria 后下线。
- `demo_transport_hotfix` 是交付快路径，不是交易安全快路径。它免除独立 integrator 与 promotion artifact/read-model 重建，但保留 sparse/dirty/单写者、回归测试、Demo safety attestation、提交态 handoff 校验和 backend restart。
- Demo transport 改动不得触碰 strategy、risk、order construction、private WS reconciliation、ledger、security 或 live 权限；一旦触碰，升级为 `demo_execution_semantics` 或更高风险。

## Windows / PowerShell 规则

- 读取中文 Markdown 或源码时使用 `Get-Content -Encoding UTF8`，不要因为终端默认乱码就修文件编码。
- PowerShell 不支持 Bash heredoc。需要临时 Python 校验时，用 `python -c`、`py -c` 或已有脚本。
- 复杂 `rg` 正则容易被 PowerShell 拆参。优先用简单关键词多次搜索，复杂匹配放入脚本。
- Windows 上 `python` 可能不可用或返回 9009；按踩坑日志确认是否需要 `py` 或 `.venv\Scripts\python.exe`。
- Windows 上 pytest 临时目录可能被锁，不要重复使用固定 `.tmp\pytest` 作为 basetemp。

## 多代理协作规则

- 修改前写明本次打算触碰的文件/目录；发现同一文件已有他人改动时，先读差异再决定是否继续。
- 数据师、BTC 程序员、美股/通用程序员和 A 股程序员使用独立 worktree；同一路径、SQLite 或 latest artifact 同时只能有一个写入者。
- 写代理不得启动并行写子代理；子代理默认只做读取、测试、日志分析和独立审查。
- 数据师负责数据源、数据快照、manifest、freshness 和 lineage；程序员不得把下载器塞进策略层。
- BTC 程序员负责 BTC 执行链和交易所规则；超级程序员不得随手改 BTC 专用 OMS/风险枚举。
- A 股程序员负责 `cn_equity` 领域实现；不得把 A 股市场规则塞进 `quant_us`，也不得直接修改 BTC/美股专用执行语义。
- 架构师默认只读和写文档/票据，不直接改业务代码。
- 研究员只能交付研究证据、策略接口和验证报告，不能绕过 risk/OMS 生成真实订单。
- 新 writer worktree 默认使用 sparse checkout，并设置 `GIT_LFS_SKIP_SMUDGE=1`；`data/`、`artifacts/` 和 `mlruns/` 不得进入默认 sparse 范围。
- 仓库盘可用空间低于 50 GB 时禁止创建完整 checkout；低于 20 GB 时数据采集和 artifact 重建必须写 blocked receipt 后停止。
- `data/market_data.sqlite` 属于仓库外单写者运行存储，不得重新 stage 或提交；可复现数据通过不可变 shared-data version、hash 和 Git-tracked manifest 交付。

## 目标选择与工程循环熔断

- active user objective / current milestone 决定本轮选择什么工作；blocker inventory 是风险清单，不是自动 backlog。已有可运行路径时，环境、数据、自然时间和人工审批 blocker 不授权新代码、测试、handoff、集成或 gate 重建。
- 运行/观察链路已有 current-HEAD 持久入口、单写者、fail-closed 和可恢复状态后，clock/W32/NTP/offset/RTT/latency、DNS/TLS/network/proxy/connection reset、公开 WS 运行故障和观察覆盖不足只进入恢复环境、继续既有重试或等待的路径，代码范围保持冻结。
- 只有可在 current HEAD 确定复现的代码缺陷、现有入口无法表达 active objective，或用户明确扩大工程范围时，才创建最小工程票据；每个显式修复请求默认最多一个 producer ticket 与一个 integration ticket。
- milestone 缩短或变更时必须重算当前验收条件，不能把旧 artifact 写成满足新目标；旧长期 blocker 转 backlog。security、risk、OMS、ledger、private/order/live 和 fail-closed 硬线不受快路径影响。

## 交易安全边界

- 策略层只能输出 `Signal`、`Forecast`、`OrderIntent` 或 `TargetPosition`，不得直接调用 broker/exchange。
- 所有订单路径必须经过 Risk Engine、OMS、Ledger 和审计链。
- 不允许访问真实 private/order/live endpoint；不允许读取、打印或写入 API key、secret、passphrase、token。
- API key 证明只能记录 broker/venue、账户哈希、reviewer、review time、approval ticket、权限结论和外部证明代号。
- 任何 paper/live/order/private/broker/OMS 安全旗标异常时，必须 fail-closed。

## Artifact / Gate 规则

- wrapper 命令成功不等于 gate 成功；最终结论来自报告字段、blockers、decision、安全旗标和 artifact hash。
- `research_only`、`blocked`、`fail_closed`、`paper_observing` 不能被描述成 live-ready。
- schema 或报告字段变更后，必须重建对应 latest artifact，再跑 schema/contract tests。
- 上条只在 artifact、promotion 或 live 变更风险命中时驱动交付；纯 Demo transport hotfix 不得被 legacy promotion artifact 阻塞，但 promotion endpoint 本身仍独立 fail-closed。
- 当前 HEAD 与 artifact 记录 commit 不一致时，gate 证据默认不新鲜，必须重建或明确标注 stale。
- dashboard、micro-live、readiness 报告互相引用时，要过滤自引用摘要 blocker，不能让 blocker 数无限膨胀。

## 数据与回测规则

- 数据必须区分 raw、derived、manifest、lineage、freshness 和 PIT 语义。
- 缓存存在不等于数据新鲜；报告必须输出最新 common date、缺口和来源状态。
- 部分 universe 或缺关键文件时，只能标记 research-only / blocked，不能做 promotion。
- 回测结论必须扣除手续费、税费、滑点、适用时的资金费率和冲击成本，并经过 walk-forward / holdout / no-lookahead 检查。
- 单一 Sharpe、单次样本或诊断图不能作为上线依据。

## 日志 / 审计 / 回放规则

所有核心链路日志至少要能追踪：

- `run_id`
- `strategy_id`
- `data_version`
- `decision_time`
- `signal`
- `forecast`
- `target_position`
- `risk_decision`
- `order_id`
- `fill_id`
- `error_code`

Replay engine 只能消费注入的历史 audit DAG、snapshot、params、risk state、orders、fills；不能自己读取 live/current/latest 状态。

## 交付检查清单

交付前确认：

- 已说明读取了哪些 playbook、catalog hash 和命中的 pitfall IDs。
- 已说明是否定向读取原始日志及对应条目。
- 已说明是否触碰数据、策略、回测、风控、执行、监控边界。
- 已说明测试命令和结果；无法运行时说明原因。
- 已说明 gate 是否仍 blocked/fail-closed。
