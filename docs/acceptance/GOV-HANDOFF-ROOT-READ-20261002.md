# GOV-HANDOFF-ROOT-READ-20261002 验收记录

## 结论

- `change_risk`: `governance_control`
- base commit: `3b4ad82d14ef441e6c5ad780edf2fb4acd80e5b1`
- implementation commit: `968cd12066cd42921631b20045b58b77585fdac5`
- producer branch: `agent/super_developer/gov-handoff-root-read-20261002`
- readiness: `quality_checked`
- 集成状态：producer 已提交，仍需独立 integrator；未合入 main。
- 结论只覆盖 handoff root 读取恢复，不是 promotion、paper、private、order 或 live 证据。

## 职责与边界

改动只涉及：

- `tools/agent_governance/handoff.py`：把 handoff root 查询从短 branch DWIM 改为启动时捕获的 immutable commit SHA；merged 查询绑定同一个 captured main SHA；root 读取后再次核对 main/agent refs，变化时 fail-closed。
- `tests/agent_governance/test_handoff.py`：增加 failure-first、captured SHA、malformed/missing/type/size、materialized-byte cap、ref-changed 回归。
- 本验收记录与票据自己的 append-only handoff。

未改变：

- `GIT_COMMAND_TIMEOUT_SECONDS=4.0`
- `HANDOFF_DISCOVERY_TIMEOUT_SECONDS=10.0`
- ref/tree/blob/depth/byte caps
- handoff schema、validation 规则、merged coverage 语义、conflict winner 语义
- policy、threshold、deadline、hooks、hook trust、backend/frontend、策略、risk、OMS、ledger 或任何交易权限

最终方案仍为单次 `cat-file --batch`。曾验证 metadata `--batch-check` 后再 unique-root materialize 的两阶段候选，但真实仓库 868/927 unique roots 仅约 4.8% 去重收益，并有一轮触发既有 10 秒总预算，因此最终实现删除该额外 subprocess，保留原 tree-object cache 与 caps。

## Failure-first

先新增 `test_tree_root_lookup_uses_captured_commit_specs_with_bounded_batch` 的原型回归；旧实现执行结果：

```text
TypeError: _git_tree_handoff_index() got an unexpected keyword argument 'captured_heads'
1 failed in 4.18s
```

最终对应安全组：

```text
py -3 -m pytest -q tests\agent_governance\test_handoff.py -k "captured_root or captured_ref" --basetemp .pytest-tmp-gov-handoff-4
7 passed, 32 deselected in 4.21s
```

## 真实仓库测量

测量对象均为同一 producer worktree 指向的已提交对象库；测量时实现尚未进入 main。

### Root lookup 对照

命令逻辑：用 `git for-each-ref --format=%(refname:short)%09%(objectname) refs/heads/agent/` 捕获 branch/head，再分别把 928 个 `<branch>:.agent/handoffs` 与 `<captured-sha>:.agent/handoffs` 送入同体积 `git cat-file`。

| 查询 | 项数 | 时间 | stdout bytes |
|---|---:|---:|---:|
| short branch `--batch-check` | 928 | 0.879687s | 47,880 |
| short branch `--batch` | 928 | 1.021890s | 14,694,273 |
| captured SHA `--batch-check` | 928 | 0.212478s | 47,880 |
| captured SHA `--batch` | 928 | 0.396388s | 14,694,273 |

### Discovery before/after

命令逻辑：`scan_handoffs(Path('.').resolve(), verify_git=False)`，以 canonical JSON（`sort_keys=True,separators=(',',':')`）计算 `invalid` SHA-256。

Before（base implementation）：

- 6.435359s：1283 events / 927 refs / 20 invalid
- 2.822448s：1283 events / 927 refs / 20 invalid
- invalid canonical SHA-256：`67c5252e7d683ee9be351cba0d32e3c9681fa1dd65239ead019687fb4b043660`

After（最终单批 captured-SHA implementation）：

- 2.389643s：1283 events / 927 refs / 20 invalid
- 4.745967s：1283 events / 927 refs / 20 invalid
- 4.846129s：1283 events / 927 refs / 20 invalid
- 三轮 invalid canonical SHA-256 均为 `67c5252e7d683ee9be351cba0d32e3c9681fa1dd65239ead019687fb4b043660`

计数是测量窗口快照；之后其他 producer 新增合法 branch/handoff 时允许自然增长，验收约束是相同 ref snapshot 上 invalid 集合不被过滤或伪造成 valid。

### Team Context

```text
py -3 tools/agent_governance/team_context.py --repo-root . --role super_developer --change-risk governance_control --format json
elapsed=9.511666s, stdout_chars=245986, process_exit=2
```

输出已恢复当前 branch/head，不再是 timeout 后的 `unknown`。`exit=2` 是 20 条历史 invalid 继续被 fail-closed 暴露，不是读取超时。

## 20 条历史 invalid 保持可见

以下路径在 before/after 中均保留为 invalid；未过滤、未改写、未计入 valid：

1. `BTC-OKX-DEMO-HELD-RECOVERY-CROSS-HEAD-OWNER-MARKER-20/published-btc-okx-demo-held-recovery-cross-head-owner-marker-20-f050fb026.json`
2. `BTC-OKX-DEMO-WORKER-PARENT-EMERGENCY-RECOVERY-BINDING-37-CORRECTION-02/published-btc-okx-demo-worker-parent-emergency-recovery-binding-37-correction-02-e07311e69.json`
3. `BTC-OKX-PUBLIC-CHART-ORDERBOOK-UX-02/published-btc-okx-public-chart-orderbook-ux-02-corr1-5e125ee50.json`
4. `DATA-US-PUBLIC-FORWARD-SNAPSHOT-REAL-06/delivery-evidence.json`
5. `INTEGRATE-ALPHA-READ-CHAIN-FIX-20261002/integrated-alpha-read-chain-browser-closure-20261002-9a936e619.json`
6. `STRATEGY-WORKBENCH-PTRADE-FIDELITY-04/published-strategy-workbench-ptrade-fidelity-04-2b3af50bd.json`
7. `ALPHA-READ-CHAIN-FIX-20261002/corrected-alpha-read-chain-fix-20261002-23afadd3d.json`
8. `ALPHA-READ-CHAIN-FIX-20261002/published-alpha-read-chain-fix-canonical-20261002-23afadd3d.json`
9. `BTC-DEMO-CLOCK-OFFSET-CAPTURE-01/published-btc-demo-clock-offset-capture-01-02cb0b215.json`
10. `BTC-DEMO-CUMULATIVE-OBSERVATION-01/published-btc-demo-cumulative-observation-01-0a91d0da1.json`
11. `BTC-DONCHIAN-HISTORY-INTEGRATION-20260916/rejected-btc-donchian-history-independent-review-20260916-a90637520.json`
12. `BTC-OKX-DEMO-PRIVATE-WS-PROBE-FAILURE-MONITORING-GUARD-17/published-btc-okx-demo-private-ws-probe-failure-monitoring-guard-17-85dec5c17.json`
13. `DATA-US-PUBLIC-FORWARD-SNAPSHOT-REAL-02/data-us-public-forward-snapshot-real-02-network-blocker-report.json`
14. `DATA-US-PUBLIC-FORWARD-SNAPSHOT-REAL-03/data-us-public-forward-snapshot-real-03-network-blocker-report.json`
15. `DATA-US-PUBLIC-FORWARD-SNAPSHOT-REAL-04/data-us-public-forward-snapshot-real-04-network-blocker-report.json`
16. `DATA-US-PUBLIC-FORWARD-SNAPSHOT-REAL-05/blocker-report.json`
17. `DONCHIAN-LONG-EVALUATION-20260921/published-long-binding-a8eeab1da.json`
18. `DONCHIAN-OFFLINE-LIVENESS-20260921/published-offline-clock-2f3d71d01.json`
19. `STRATEGY-ALPHA-PARAMETER-MAP-01/published-98a3be571.json`
20. `STRATEGY-WORKBENCH-PTRADE-FIDELITY-03-CORRECTION-04/published-strategy-workbench-ptrade-fidelity-03-correction-04-72c0ac1cd.json`

主要错误类别仍包括 test result、missing/unknown fields、schema/event type、transition、deliverable commit/type/hash；完整 errors 数组由 scan 原样返回，并由上述 canonical hash 锁定集合与顺序。

## 回归结果

```text
py -3 -m pytest -q tests\agent_governance\test_handoff.py tests\agent_governance\test_team_context.py --basetemp .pytest-tmp-gov-suite-final
55 passed in 272.21s (0:04:32)

git diff --check -- tools/agent_governance/handoff.py tests/agent_governance/test_handoff.py
exit 0
```

首次组合收集因 planner 的 super-developer sparse 默认未包含只读依赖 `quant_crypto` 而报 `ModuleNotFoundError`；仅执行 `git sparse-checkout add quant_crypto` 以读取测试依赖，没有修改或提交任何 `quant_crypto` 文件。

## Preflight 与交付状态

- 读取：`AGENTS.md`、`docs/knowledge/README.md`、`quant_system_non_negotiables.md`、`shared_pitfalls.md`、`super_developer_pitfalls.md`、`.codex/agents/super-developer.toml`、`delivery_risk_policy.json`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 初始 owned paths：全部 clean；未发现重叠 dirty 或其他代理未提交改动。
- artifact / manifest / ledger：无；本票只产出 Git-tracked acceptance report 和 handoff。
- schema/dependency order：无变化。
- backend restart / promotion artifact rebuild：均不需要。
- 保持 false / fail-closed：`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`execution_permission=false`。
- 下一步：独立 integrator 校验提交、touch set、测试与 handoff，之后才能决定是否集成 main。
