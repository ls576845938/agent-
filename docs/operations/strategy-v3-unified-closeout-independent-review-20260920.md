# BTC V3 统一离线收口：独立源码审查与拒绝交接

审查日期：2026-09-20。结论：`partial_blocked`，不接受为 V3 完成、可用版或交易晋级证据。本轮按约定停止在一次提交态独审；未修改业务源码、合同测试或生产权威链。

## 审查对象与边界

- 风险类别：`demo_execution_semantics`；票据开发基线 `95b0ab4c406f6d85e83d1bcb21b618d129015fd5`。它不是当前主版。
- 原生产者源码 `16dd8b94512aa724afddc24a03a52c9c52076390`，生产者 handoff-only 提交 `ed7675ff81f21bec6e4d1e822fb2c78a6c250e99`；本独立 sparse worktree 顺序 cherry-pick 后，**实际测试的源码提交** `703d5d030`，交接就位 HEAD `1de267beab7afc96874c9b1fa3a23cb3ab4ce9bd`。
- 当前注册主版仍为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`。没有合入 main、发布、重启服务或做页面验收。
- 生产者交接 `.agent/handoffs/BTC-V3-UNIFIED-CLOSEOUT-20260916/published-btc-v3-unified-closeout-blocked-20260916-16dd8b945.json` 在生产者提交态和本独立 worktree 均经 `handoff.py validate` 返回 `valid`。六项 deliverable 的 SHA-256 按 `git show 16dd8b945:<path>` 原始 Git 对象字节逐一相符，提交祖先与六个改动路径相符。Windows checkout 的 CRLF 工作树字节与 Git 对象不同，不属于业务或交付阻断。
- Python 来自注册主版 `.venv/Scripts/python.exe`；导入的 `quant_crypto.application.qlib_offline_replay` 指向本独立集成 worktree。所有运行是隔离模拟 venue；原 V3 测试含断网和训练禁用 fixture。本轮未主动调用训练、账户、交易所、private/order/live 端点或读取秘密。

本轮 touch set 仅为本报告及一条 append-only `rejected` 交接事件。集成前源码、测试、合同、文档及上述两个输出路径的限定 `safe_status` 均 clean。生产者的其他未提交文件没有被消费或覆盖。

## 独立结果

| 证据 | 提交态结果 | 含义 |
| --- | --- | --- |
| `test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart` | `1 failed in 82.08s`；第二次构建后反向先平，在 `execute → _advance_offline_time → _renew_verified_offline_liveness` 抛出 `qlib_offline_maintenance_expired` | V3 连续离线执行与重启未通过；安全拒绝，没有假装交易健康 |
| 新收口合同 `tests/contracts/test_strategy_v3_unified_closeout.py` | `3 passed, 2 failed in 158.60s` | 封存 1,392 条调用共同 `execute`、22 个物理拒绝批次、零批准/零成交；过期 ACK 不能刷绿；已提交 ledger 到政策投影中断后的 exact fill 恢复，分别通过其自身断言 |
| 新合同中批次写前失败恢复、截断尾阻断两项 | 两项均在第二次构建 replay 时抛 `GuardianConcurrentWriterError: latch_concurrent_writer` | 测试没有到达预期恢复/截断断言，因此这两项安全性质**未验收**；不能写成“截断绕过成功”或“已验证失败关闭” |

本独审选择器合计 **3 passed、3 failed**，分别来自上面两个命令；不可与生产者早期源码的 `20 passed, 1 failed` 拼成最终通过率。完整 V3 矩阵、旧 V1/V2 兼容、OS 硬崩溃、真实账户/交易所、CLI 完整流程、服务/API/UI、Demo/paper/live 均未运行。

### 失败时的持久事实与静态定位

第一项失败保留的隔离状态显示：dead-man `last_ack_utc` 和 runtime `last_heartbeat_utc` 都为 `2026-07-01T08:59:59+08:00`；模拟 venue `last_observed_at_utc` 已为 `2026-07-01T10:00:00.001+08:00`。模拟 venue 已记 239 条维护 ACK、1 次 submit、1 笔 fill、0 笔 funding bill。失败后 runtime 为 `frozen_unknown`、`cancel_only=true`、`opening_allowed=false`，risk mode 为 `FROZEN_UNKNOWN`。因此这是跨重启的离线时钟/维护事实断点，不能解释为策略无信号或正常完成。

源码静态路径与上述状态相符：构造函数把 `self._now` 设为固定首次决策时间前 1 秒，venue 则恢复已观察的较晚时间；恢复入口以 `self._now` 写 dead-man ACK，推进器从 venue 的较晚时钟检查原 30 秒门槛。未增加逐调用探针，因此这段是**基于源码和持久事实的原因推断**，动态实证只到 `qlib_offline_maintenance_expired` 与失败关闭状态。不能为过关直接改写 ACK、拉长 TTL 或改 Guardian。

两项批次异常测试的独立堆栈均停在 `RuntimeRiskGuardianSupervisor` 重新获取文件 latch；源码 `evaluate_frozen_candidate` 在正常完成后才调用 `replay.close()`，异常路径没有同一层的 `finally` 清理。它是资源生命周期的明确审查疑点；独立测试实证仅证明重新获取 latch 失败，未证明文件尾截断判定本身错误。

## 固定测试命令

测试工作目录为本报告所在独立集成 worktree，`PYTHONDONTWRITEBYTECODE` 由 `-B` 保证，`MLFLOW_DISABLE_AGENT_HINT=1`；两个临时目录相互独立。

```powershell
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-unified-integrator-20260920-target" tests/contracts/test_strategy_v3_qlib_offline.py::test_explicit_nonzero_fixture_uses_existing_oms_ledger_and_survives_restart
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v3-unified-integrator-20260920-safety" tests/contracts/test_strategy_v3_unified_closeout.py
```

本轮没有重训、搜索参数、调整策略、成本或 lot，也没有重跑历史研究收益。封存候选的零批准/零成交和负 IC 仍是原研究事实；fixture 成交不构成候选有效性。

## 交付决定

本票据只发布 `rejected` 独审交接，不发布 `integrated` 事件。V3 主阻断为跨重启维护事实过期；批次异常后的 latch 生命周期还阻断其恢复合同的独立验收。按本轮熔断规则停止，不在集成分支修业务或追加生产者回合。是否开新的限定修复，交由主会话另行决策；本报告本身不授权任何代码扩围或交易。

报告、测试和隔离持久状态只对源码提交 `703d5d030` 有效。没有 current-main 的 V3 artifact 或运行证据；V3 仍为 `research_only` / `blocked` / `fail_closed`。`runtime_observed`、`execution_permission`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw` 均为 `false`。

预检读取：`quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`，`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role contract、delivery risk policy；项目未设置单独 `integrator_pitfalls.md`。活动规则 ID：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-BOUNDARY-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。catalog SHA-256：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。未定向读取原始事故日志；无 artifact/manifest/ledger 发布和 schema 或依赖顺序变更。
