# BTC 系统入口生命周期独立验收（2026-10-01）

## 结论

- 票据：`INTEGRATE-BTC-SYSTEM-INTAKE-ACCEPTANCE-20261001`；`change_risk=unclassified`，沿用最严格独立集成路径。
- 批准基线：`c5a9570bd40a5ce5243c4d61320a2fd5860dd8c5`；producer deliverable：`8511500b59d0447cade5717c76aeef503843a900`；published handoff：`d73dd76ff91c5c7916ac5e0ef731fd9a7d560a70`，事件 `published-btc-system-intake-v1-fixture-fix-20261001-8511500b5`。
- 独立集成提交：`a6d05bfdbc77332410b74f9d119dec8ccb35312d`，双亲为批准基线与 producer deliverable；只包含生命周期测试 fixture 和说明文档，没有生产源码变化。
- 独立执行完整 `tests/integrations/test_candidate_offline_lifecycle.py`，未使用 `-k` 或 deselect：`6 passed, 3 warnings in 1033.96s`。四个原生命周期场景与两个新增 schema 边界场景均通过。
- 本次修复只让 synthetic v1 fixture 按真实 v1 wire schema 省略**确实为空**的 `funding_settlements`。非空资金费事实明确拒绝，v1 额外字段仍被生产加载器拒绝，v2 缺失 required references 仍被拒绝。生产 v1/v2 加载合同一字未改。
- 结论仅为 synthetic 离线入口生命周期软件验收通过，不是新的真实候选、历史业务结果、正式页面或交易授权证据。

## 根因与变更边界

原完整五文件矩阵在批准基线得到 `146 passed / 4 failed`。四个失败都停在 cursor 0：测试用 `dataclasses.asdict` 把 v2 才存在的空 `funding_settlements=[]` 写进 v1 observation；生产加载器按精确字段合同正确返回 `offline_observation_facts_missing_or_extra`。这不是生产加载器缺陷。

本票仅变更：

1. `tests/integrations/test_candidate_offline_lifecycle.py`：增加仅供 synthetic fixture 使用的 v1 序列化 helper；精确白名单输出 10 个 v1 字段，非空资金费事实禁止降级；原业务断言及 600 秒等待预算保持不变。
2. `docs/acceptance/btc-system-intake-fixture-schema-20261001.md`：记录 v1/v2 fixture 边界和失败历史。

`c5a957...` 到独立集成提交的生产目录差分（`backend/`、`quant_crypto/`、`quant_shared/`、`integrations/`、`frontend/`、`scripts/`、`tools/`）为空。其他四个矩阵测试文件 blob 与批准基线相同：

- `tests/contracts/test_strategy_delivery.py`：`3fb7538eedf1a514470c70ab3592c74d2784ebf1`
- `tests/contracts/test_candidate_offline_access.py`：`90b0f4b6b61c614ac363cc3ec413a5bc55bc48f8`
- `tests/contracts/test_candidate_offline_entry.py`：`7ad7962a3187a75570d4ba3f0e174fff7b0c1769`
- `tests/integrations/test_candidate_package_inference.py`：`35ede9964ec39aaae74609e9dac234407aa61b9b`

## 独立执行证据

专属 planner sparse worktree：

`D:/vibe coding/Obsidian/量化系统/worktrees/integrator-integrate-btc-system-intake-acceptance-20261001`

`core.sparseCheckout=true`；集成前及测试后限定 touch set 均为 clean。没有读取或消费 producer 未提交文件，也没有覆盖其他代理改动。

唯一完整生命周期命令：

```powershell
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B -m pytest tests/integrations/test_candidate_offline_lifecycle.py -q -p no:cacheprovider --basetemp 'D:/codex-test-tmp/btc-system-intake-lifecycle-independent-20261001-6d7f3a/basetemp' --junitxml 'D:/codex-test-tmp/btc-system-intake-lifecycle-independent-20261001-6d7f3a/junit.xml'
```

- unified exec session：`30875`，final chunk：`8268ac`，exit `0`。
- launcher PID：`24708`；实际 Python PID：`22768`；创建时间：`2026-10-01 14:26:45`（Asia/Shanghai）。
- 结果：`6 passed, 3 warnings in 1033.96s (0:17:13)`。
- JUnit：`D:/codex-test-tmp/btc-system-intake-lifecycle-independent-20261001-6d7f3a/junit.xml`；SHA-256 `26db90a301a401b72c4030aa21d9d8c5f4c140c550a001e3b9f45b7195d10114`。
- 三条 warning 均为 Starlette/httpx 与 websockets 的既有依赖弃用提示，不改变断言结果。

逐项结果：

| 用例 | 秒 | 结果 |
|---|---:|---|
| v1 fixture 精确 wire 且拒绝非空 funding 降级 | 0.003 | passed |
| 生产加载器保持 v1/v2 拒绝边界 | 10.239 | passed |
| 默认 bootstrap 发布、HTTP 启动、结果与幂等 `[0]` | 265.951 | passed |
| 默认 bootstrap 发布、HTTP 启动、结果与幂等 `[1]` | 280.754 | passed |
| 已提交边界停止、服务重启后同 job 恢复 | 239.926 | passed |
| 权威经济提交后投影崩溃，恢复时不重复订单或记账 | 233.864 | passed |

## 组合矩阵口径

原失败现场保持不变：

- `D:/quantstation-runtime/btc-system-intake-tests-20261001-8ef569e7955f43959c8d4b2a49f2d51e/junit.xml`
- SHA-256：`5d8546ca2d4823523aa9faf7da86b3feb056d2b135311d815734dd7c090ab7d3`
- 结果：`146 passed / 4 failed`；四个失败均为旧 v1 fixture schema 错误。

本轮没有机械重跑其余四文件的 146 个已通过用例。由于这些测试 blob 与全部生产源码 blob 未变，继承原 146 项证据，并与本轮完整生命周期 6 项结果组成当前提交态覆盖。**这不是一次新的“全矩阵 150/152 passed”单次运行**；producer 的 `2 passed` 也只属于序列化快速检查，不替代本次独立完整生命周期执行。

## 治理、回退与未运行项

- 已读取根 `AGENTS.md`、知识入口、量化不可妥协规则、共享 pitfalls、`.codex/agents/integrator.toml`，以及 `quant-agent-preflight`、`quant-agent-handoff` 技能。
- context packet：role `integrator`，scope `BTC-SYSTEM-INTAKE-ACCEPTANCE-20261001`；catalog hash `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 命中 pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- producer handoff 已用 canonical `handoff.py validate` 验证为 `valid`；deliverable sole parent 为批准基线，touch set 与 envelope 一致。
- 回退点为批准基线 `c5a9570bd40a5ce5243c4d61320a2fd5860dd8c5`；本分支未合 main，未删除或重写原失败 JUnit。
- 未运行：其余四文件 146 项重复回归、真实 R2 候选、真实历史业务运行、正式浏览器/UI48、后端或前端服务、账户、Demo、paper、live、private/order/transfer/withdraw。

保持 fail-closed：`promotion_ready=false`、`demo_control_enabled=false`、`paper_enabled=false`、`live_enabled=false`、`private_endpoint_allowed=false`、`order_endpoint_allowed=false`、`real_order_submitted=false`、`transfer_allowed=false`、`withdraw_allowed=false`、`execution_permission=false`。真实 R2 候选仍为 rejected；本票不改变该事实。
