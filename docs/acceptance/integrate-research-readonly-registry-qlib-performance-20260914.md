# Research Readonly Registry / Qlib 性能独立集成审查

日期：2026-09-14（Asia/Shanghai）
集成票据：`INTEGRATE-RESEARCH-READONLY-REGISTRY-QLIB-PERF-20260914`
角色：`integrator`
风险：`research_readonly_release`
批准基线：`1925362a76a5c48476642373c1f26ee7196aafce`
Producer deliverable：`93ca2536e49da5c8277b27a0d7592957e90b0d02`
Producer handoff：`42ed00ec2eaf21688169f83efec133bbfc89acf7`

## 结论

`REJECTED / BLOCKED`。提交链、handoff、逐文件哈希、限定 touch set 和聚焦回归均通过，但 Qlib seal 损坏可见性存在可确定复现的 fail-closed 缺陷：当 `run_seal.json` 的 `files` 字段为 truthy 非对象值时，`read_sealed_evidence()` 在 `.items()` 处抛出未捕获 `AttributeError`，没有返回 `integrity_status=blocked`。该缺陷直接违反本票要求的 seal 损坏显式阻断，当前交付不得进入 registered main。

Integrator 未修改 producer 业务代码，没有发布 main、没有启动服务或前端、没有访问 secret/private/order/live、没有训练或改写真实 data/artifact。

## 预检与边界

- Planner worktree：`D:\vibe coding\Obsidian\量化系统\worktrees\integrator-integrate-readonly-registry-qlib-perf-20260914`
- Branch：`agent/integrator/integrate-readonly-registry-qlib-perf-20260914`
- `core.sparseCheckout=true`
- 初始 scoped dirty：8 个限定路径全部 clean，无重叠写入或冲突。
- Catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- 读取：`AGENTS.md`、`.codex/agents/integrator.toml`、`docs/knowledge/README.md`、`docs/knowledge/00_codex_rules/quant_system_non_negotiables.md`、`docs/agent_playbooks/shared_pitfalls.md`、`docs/agent_playbooks/research_readonly_release.md`、`docs/agent_playbooks/delivery_risk_policy.json`、`quant-agent-preflight`、`quant-agent-handoff`。
- 仓库不存在 `docs/agent_playbooks/integrator_pitfalls.md`；Integrator 角色约束来自 TOML、共享 playbook、风险合同和 context packet。
- Active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。

Producer touch set 限于：

- `backend/app/api/app_factory.py`
- `integrations/qlib_adapter/research_pipeline.py`
- `quant_us/research/evidence_registry.py`
- `tests/api/test_qlib_pipeline.py`
- `tests/research/test_evidence_registry.py`
- `docs/acceptance/research-readonly-registry-qlib-performance-20260914.md`
- `.agent/handoffs/RESEARCH-READONLY-REGISTRY-QLIB-PERF-20260914/published-research-readonly-registry-qlib-perf-20260914-93ca2536e.json`

完整 diff 未触碰 strategy/signal/position/exit/Risk/OMS/protection/ledger/security/trading permissions/governance/data source/training/runtime artifact store。`app_factory.py` 变更仅为研究只读路由接线。`research_readonly_release` readiness 上限仍为 `quality_checked`。

## 已通过验证

1. `refs/heads/main` 在 cherry-pick 前仍精确为批准基线。
2. Git ancestry 为 `1925362a... -> 93ca2536... -> 42ed00ec...`；handoff 尚非 main 祖先。
3. 提交态 envelope 通过 `validate_handoff()` 与 `validate_handoff_against_git()`；cherry-pick 后官方 `handoff.py validate` 也返回 `valid`。
4. Envelope 中 6 个 deliverable SHA-256 全部与 `93ca2536...` 对象逐文件匹配。
5. 独立聚焦回归：
   `py -3 -B -X utf8 -m pytest -q -p no:cacheprovider tests/research/test_evidence_registry.py tests/api/test_qlib_pipeline.py`
   -> `22 passed in 16.79s`。
6. `git diff --check` 仅报告 producer acceptance Markdown 四处双空格行尾；这些是 Markdown 强制换行，不是业务语义冲突，但尚未改写 producer 提交。

## 拒绝复现

在临时目录创建最小 `run_seal.json`：

```json
{
  "schema_version": "qlib_run_seal_v1",
  "run_id": "bad-seal",
  "files": "not-an-object"
}
```

调用 `read_sealed_evidence(run_root)` 的实际结果：

```text
AttributeError:'str' object has no attribute 'items'
```

预期结果是无异常返回、`integrity_status=blocked` 且 blocker 明确指出 seal files schema/type 损坏。当前实现只捕获 `OSError/UnicodeError/ValueError/KeyError/TypeError/QlibAdapterError`，未在使用 `.items()` 前验证 `files` 为非空对象，也未捕获此 `AttributeError`。

## 未运行与 blocker

- 发现上述确定性缺陷后，按 fail-closed 合同停止冷热性能测量、扩展测试、全仓回归和发布验收；没有用性能数字掩盖正确性 blocker。
- 未复跑 producer 声明的 4 个平台/可选依赖基线失败；它们不是本次 rejection 的依据。
- 未运行 canonical main HTTP/浏览器验收、backend restart、前端 build/Playwright；registered main 未发布，worktree 禁止启动前端。
- 未重建 Evidence Registry 或任何真实 data/artifact/manifest/ledger/replay/latest pointer。

Blocker owner：`super_developer`。最小下一步是在 producer ticket 内验证 `seal["files"]` 为非空 mapping（并验证每个 name/digest 类型），将结构损坏显式映射为 blocked，补失败优先回归；重新提交 deliverable 与 append-only superseding handoff 后，再由独立 integrator 复审。

安全旗标保持 false：`demo_control_enabled`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`execution_permission`、`runtime_observed`。本 rejection 不解锁任何 gate。
