# Research Readonly Registry / Qlib 性能 Superseding 独立验收

日期：2026-09-14（Asia/Shanghai）
集成票据：`INTEGRATE-RESEARCH-READONLY-REGISTRY-QLIB-PERF-20260914`
角色：`integrator`
风险：`research_readonly_release`
批准基线：`1925362a76a5c48476642373c1f26ee7196aafce`
首版 deliverable：`93ca2536e49da5c8277b27a0d7592957e90b0d02`
Amendment deliverable：`0b39a752098f63f05b70aa343a8623472ef70838`
Superseding handoff：`bcc8d987981603277b3f006be0e1eba795967683`

## 结论

`ACCEPTED / QUALITY_CHECKED`。此前 rejection 中的确定性 blocker 已由最小 amendment 修复：`run_seal.json.files` 非对象、非法 name、非法 digest 和目录逃逸均无异常泄漏，显式返回 `integrity_status=blocked`，执行与交易安全旗标全部保持 false。

Evidence Registry 的验证索引状态矩阵、Qlib limit 前移、完整 seal/hash/identity、详情单次校验、损坏可见性及并发读取均通过独立验证。变更可作为独立 integrator 分支上的提交态研究只读交付；尚未发布 registered main，不能替代 backend restart、canonical-main HTTP 或浏览器验收，也不解锁 research/promotion/paper/live。

## 工作树、历史与边界

- Planner worktree：`D:\vibe coding\Obsidian\量化系统\worktrees\integrator-integrate-readonly-registry-qlib-perf-20260914`
- Branch：`agent/integrator/integrate-readonly-registry-qlib-perf-20260914`
- `core.sparseCheckout=true`
- 初始及 amendment 前 scoped dirty：限定路径全部 clean，无重叠写入或冲突。
- 原 rejection 报告与 rejected event 均保留，未修改或删除。
- Amendment cherry-pick：`c5fb8286c82c223ca57ab31205fa8414276b2bf8`
- Superseding handoff cherry-pick：`4773af8a1715fb3e182d2265d6f3751f21aa3698`
- Registered main 在集成前后均为 `1925362a76a5c48476642373c1f26ee7196aafce`。

Superseding envelope、Git ancestry 和 6 个 deliverable SHA-256 全部匹配。Amendment 仅修改：

- `integrations/qlib_adapter/research_pipeline.py`
- `tests/api/test_qlib_pipeline.py`
- `docs/acceptance/research-readonly-registry-qlib-performance-20260914.md`
- append-only superseding handoff

完整累计 producer touch set 仍限于研究只读路由、Evidence Registry/Qlib reader、聚焦测试和验收文档。未触碰 strategy/signal/position/exit/Risk/OMS/protection/ledger/security/trading permissions/governance/data source/training/runtime artifact store。

## 独立正确性验证

### Handoff 与测试

- `handoff.py validate` 对 superseding event 返回 `valid`。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/research/test_evidence_registry.py tests/api/test_qlib_pipeline.py`
  -> `23 passed in 14.88s`。
- `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/api/test_m1_research_readonly_archive.py`
  -> `11 passed in 12.58s`。

### Qlib 损坏与边界矩阵

以下形状均未泄漏异常，返回 `blocked`，且 `execution_permission/runtime_observed/promotion/paper/live/private/order=false`：

- `files` 为 string、list、null、empty object；
- 空文件名；
- digest 为整数、63 位短串、大写十六进制、非十六进制；
- `../outside.bin` 目录逃逸，即使外部文件和摘要真实存在也返回 `run_file_hash_mismatch`；
- 原始 truthy-string reproduction 现返回 `seal_files_invalid`。

首次并发夹具曾把 JSONL 分隔符误写为字面量 `\\n`，顺序及并发读取均一致返回 `Extra data` blocked；该结果不是并发缺陷。修正为真实换行后，同一 sealed run 顺序和 4 并发均为 `passed`。

### Evidence Registry 状态矩阵

- stable：`present / PASS/STABLE`
- 内容修改：`changed / STALE/CHANGED`，显式 `content_changed`
- 文件缺失：`stale / STALE/CHANGED`，显式 path-set changed
- validation index digest 损坏：`conflict / CONFLICT`
- validation index 错版本：`stale / STALE/CHANGED`
- data root 错配：`conflict / CONFLICT`
- 越界路径：聚焦测试返回 conflict

## 有界性能与读取量

所有测量只使用系统临时目录，没有读取或改写 registered main 的真实 runtime data/artifacts。

### Evidence Registry 合成压力夹具

500 个 candidate 文件：

| 场景 | 墙钟耗时 | SHA256 calls | SHA256 bytes | 结果 |
| --- | ---: | ---: | ---: | --- |
| 首次 saved inspection | 2.261s | 0 | 0 | present |
| 同进程第二次 inspection | 2.241s | 0 | 0 | present |
| 4 个并发 inspection | 5.046s | 0 | 0 | 4/4 present |

显式 rebuild 为 9.406s；rebuild 是写入口，不在 GET 等待预算内。Saved inspection 只做候选路径发现与已登记文件 metadata 检查，未重新 SHA256。

### Qlib 合成只读路由夹具

12 个 sealed runs，请求 `limit=3`，每个选中 run 含一个 pipeline JSON 和 128 行 decisions JSONL：

| 场景 | 墙钟耗时 | 返回 runs | 普通 hash | decision 校验 | 读取 bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首次 TestClient GET | 0.242s | 3 | 3 | 3 | 14,034 |
| 同进程第二次 GET | 0.097s | 3 | 3 | 3 | 14,034 |
| 同一 run 4 并发 summary | 0.030s | 4/4 passed | 完整校验 | 完整校验 | 有界夹具 |

返回顺序为最新的 `run-11/run-10/run-09`，证明 limit 在 seal 验证前生效；未读取其余 9 个 run。

这些是独立合成夹具的首读/同进程复读数字，不等同于 OS page-cache flush 后的真实冷读，也不等同于 canonical browser 等待。两条读取均低于既有页面单项约 12 秒、底层请求 20 秒的预算，但真实发布等待仍必须在 canonical main 发布后重新测量。

## 治理证据与未运行项

- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- 读取：`AGENTS.md`、`.codex/agents/integrator.toml`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/research_readonly_release.md`、`docs/agent_playbooks/delivery_risk_policy.json`、`quant-agent-preflight`、`quant-agent-handoff`。
- 仓库不存在 `docs/agent_playbooks/integrator_pitfalls.md`；角色约束由 TOML、共享 playbook、风险合同和 context packet 提供。
- Active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

未运行：producer 声明的 4 个平台/可选依赖基线失败、全仓回归、真实 Qlib 训练、前端 build/Playwright、registered-main backend restart、canonical identity/HTTP/browser 验收。没有启动 worktree 前端或正式服务。

未重建/改写真实 Evidence Registry、BTC artifact/manifest/read-model、ledger、replay 或 latest pointer。旧真实 Registry 在未来发布后仍需 operator 通过显式 rebuild 获取 `validation_index_v1`；GET 不会隐式写入。当前 artifact/browser freshness 尚未建立。

Readiness 仅为 `quality_checked`。安全旗标保持 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。
