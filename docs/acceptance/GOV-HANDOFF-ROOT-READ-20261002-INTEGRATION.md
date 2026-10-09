# GOV-HANDOFF-ROOT-READ-20261002 独立集成报告

## 结论

- `change_risk`: `governance_control`
- base commit: `3b4ad82d14ef441e6c5ad780edf2fb4acd80e5b1`
- implementation commit: `968cd12066cd42921631b20045b58b77585fdac5`
- producer deliverable commit: `ccce2aa8912d47f019dda76fa5222c841d8e3c26`
- producer final handoff HEAD: `fc4f544978d2ab17a65480cad8e8c5c679aa1cd1`
- integration branch: `agent/integrator/gov-handoff-root-read-20261002`
- readiness: `quality_checked`
- 独立审查与关键安全回归通过，可以交给主会话评估合入 `main`。
- 本报告不是 `main` 已部署证明，也不解锁 promotion、paper、private、order 或 live。

## 已验证交接

最终消费事件：

- `.agent/handoffs/GOV-HANDOFF-ROOT-READ-20261002/published-gov-handoff-root-read-20261002-ccce2aa89.json`
- `event_type=published`
- `deliverable_commit=ccce2aa8912d47f019dda76fa5222c841d8e3c26`
- full Git validation: `valid`

生产者最初发布的 `published-gov-handoff-root-read-20261002-d382d26bc` 已由
`superseded-gov-handoff-root-read-20261002-ccce2aa89` 终止。该
`superseded` 事件本身只改变旧 published 的状态，不会成为新的 active
deliverable。独立集成曾因此 fail-closed 停止；生产者随后只追加新的 active
`published` 事件，没有改写历史。Team Context 状态解析最终同时得到：

- 旧 `d382d26bc...` published：`state=superseded`；
- 新 `ccce2aa...` published：`state=published`，无 state error。

Git 实际祖先链为：

```text
3b4ad82d14ef441e6c5ad780edf2fb4acd80e5b1
  -> 968cd12066cd42921631b20045b58b77585fdac5
  -> d382d26bc252e0ad25be50a163b08653cce3a67a
  -> 9dd74824149c6a26abb6d931ebdcbe71d34a8c19
  -> ccce2aa8912d47f019dda76fa5222c841d8e3c26
  -> c9bbf808139ee988491b04876bf6cb3ab1511aba
  -> fc4f544978d2ab17a65480cad8e8c5c679aa1cd1
```

早先聊天中出现过错误的 implementation SHA；本报告只采用 Git 祖先和提交态
blob 核验出的 `968cd12066cd42921631b20045b58b77585fdac5`。

## 改动与独立审查

生产者源码 touch set：

- `tools/agent_governance/handoff.py`
- `tests/agent_governance/test_handoff.py`
- `docs/acceptance/GOV-HANDOFF-ROOT-READ-20261002.md`
- 本票三个 append-only producer handoff events

没有修改 `tests/agent_governance/test_team_context.py`。没有触碰业务前端、启动器、
策略、risk、OMS、ledger、security、权限或服务配置。

独立审查确认：

- handoff root 查询由短 branch DWIM 改为启动时捕获的完整 commit SHA；
- merged 查询固定到同一个 captured main SHA；
- root 读取后再次比对 agent/main refs，变化时 fail-closed；
- branch 名仍用于 provenance 和 `observed_refs`，没有用 SHA 取代来源身份；
- 仍为单次 root `cat-file --batch`；未采用已否决的 metadata/unique-root 两阶段方案；
- `GIT_COMMAND_TIMEOUT_SECONDS=4.0`、`HANDOFF_DISCOVERY_TIMEOUT_SECONDS=10.0` 未变；
- tree/blob/ref/depth/单 blob/总 materialized bytes caps 未放宽；
- malformed object id、负数/非法 size、missing root、错误 object type、ref movement
  均有 failure-first 回归；
- full validation、冲突 winner、invalid 顺序与 hash 语义未被改写。

提交态 Git blob：

```text
tools/agent_governance/handoff.py                 19405a9b9885c233de5848803440e2966504c7b8
tests/agent_governance/test_handoff.py            62f07ca05216ccce565f18a0aa76582da0fe0772
docs/acceptance/GOV-HANDOFF-ROOT-READ-20261002.md  59e561dd9b5da90477ab0ffbe27a5a24c1f22746
```

active published 中三项 deliverable SHA-256 均由 full Git validation 重新核验：

```text
handoff.py      ce69f9abaceb4440b632ac5c68435a4793f9f79be2b7a9ca2a5b0548be97a4f3
test_handoff.py 26bfdb931ebc1b1fab58a880469e42a075ce060bd690dcec6098fa402aa4722c
producer report 47c18b1de642069f4a599fd752159442a739a5fca6e6a6a2db9fdecd7c2ba9db
```

## 验证结果

生产者完整回归证据经报告和 handoff 复核：

```text
py -3 -m pytest -q tests\agent_governance\test_handoff.py tests\agent_governance\test_team_context.py --basetemp .pytest-tmp-gov-suite-final
55 passed in 272.21s
```

集成代理没有在源码不变时机械重复该 4.5 分钟完整套件；独立重跑关键安全组：

```text
py -3 -m pytest -q tests\agent_governance\test_handoff.py -k "captured_root or captured_ref or git_timeout or discovery_remaining_timeout" --basetemp <unique-system-temp>
11 passed, 28 deselected in 11.72s
```

其他验证：

```text
py -3 tools/agent_governance/handoff.py --repo-root . validate --input .agent/handoffs/GOV-HANDOFF-ROOT-READ-20261002/published-gov-handoff-root-read-20261002-ccce2aa89.json
status=valid

git diff --check 3b4ad82d14ef441e6c5ad780edf2fb4acd80e5b1..HEAD -- <ticket touch set>
exit 0
```

在 producer final Git snapshot 的已提交 reader 上，独立进程实际恢复索引：

```text
events=1286
refs=928
invalid=20
verification_mode=discovery_only
invalid canonical SHA-256=67c5252e7d683ee9be351cba0d32e3c9681fa1dd65239ead019687fb4b043660
current ticket event discovered=true
current ticket full Git validation errors=[]
```

events/refs 会随 append-only handoff 和 agent refs 自然增长；验收重点是历史 20 条
invalid 没有被过滤或伪造成 valid，canonical hash 与 producer before/after 一致。

集成分支上的 Team Context 实测：

```text
exit=2
elapsed=13.676231s
current_branch=agent/integrator/gov-handoff-root-read-20261002
current_head=fc4f544978d2ab17a65480cad8e8c5c679aa1cd1
branches=928
invalid_handoffs=20
new active event state=published
new active event blocker=independent_integration_pending
old event state=superseded
```

`exit=2` 是历史 20 invalid 的 fail-closed 结果，不是本票 event invalid。主会话另有一次
同源码 reader 运行返回 `exit=1` 且 current branch/head 为 unknown、stdout 没有明确 timeout
码；之后 hook 又成功读取 main、928 refs、20 invalid 并发现新 published。该现象说明 Windows
环境读取仍可能波动，不能宣称此改动让读取永不超时。本票不扩大 4 秒/10 秒预算，也不据此
新增代码范围。

## Preflight、dirty 与冲突

- worktree 由 `worktree_plan.py --role integrator --task-id GOV-HANDOFF-ROOT-READ-20261002`
  从指定 base 创建，branch 为 `agent/integrator/gov-handoff-root-read-20261002`。
- `core.sparseCheckout=true`。
- 初始限定 dirty：`handoff.py`、`test_handoff.py`、`test_team_context.py`、本票
  acceptance 和 handoff 路径全部 clean。
- 没有覆盖、清理或回滚其他 worktree；没有消费生产者未提交文件。
- 线性提交链使用 `git merge --ff-only fc4f544...` 进入本集成分支，无冲突。
- 读取：`AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、
  `integrator.toml`、delivery risk policy、preflight/handoff skills。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、
  `GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、
  `GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、
  `QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 仓库没有单独的 `integrator_pitfalls.md`；角色约束来自 `.codex/agents/integrator.toml`。

## Artifact、gate 与下一步

- 本票没有 data、runtime artifact、manifest、ledger、replay 或 promotion evidence。
- `promotion_artifact_rebuild_required=false`；`backend_restart_required=false`。
- 未运行服务、浏览器或 private/broker/order/live endpoint；未读取 secret。
- 未执行 `main` merge、外部 push 或部署。
- 保持 fail-closed：`promotion=false`、`paper=false`、`live=false`、
  `private=false`、`order=false`、`real_order=false`、`transfer=false`、
  `withdraw=false`、`execution_permission=false`。
- 主会话只有在复核本集成提交和 append-only integrated event 后，才能决定合入
  `main`。合入后必须刷新 current-main Team Context；治理票正式进入 main 前不得启动后续
  UI 独立集成。
