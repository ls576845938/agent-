# Candidate Management One-click 独立集成验收（2026-09-26）

## 结论

`INTEGRATE-CANDIDATE-MANAGEMENT-ONECLICK-20260926` 在限定源码范围内独立验收通过，未发现 P0/P1。结论仅为 `quality_checked` 的源码候选，可由主会话按普通 `--no-ff` 流程合入；它不等于管理服务已启用、已运行任务、已取得账户能力或已解锁 promotion/paper/live。

## 身份与范围

- `change_risk=unclassified`，沿用严格独立 integrator 路径。
- base/main（验收期间）：`3631aa09dbbc0f3208d439c8539cbba718a08f51`；base tree：`12ec92147ab553e3ba6ce74343b4fddf7848cc94`。
- producer source/deliverable：`d83de5f003c1123c01ba0188de359578e193b9c6`；source tree：`31e699fc15a712be586ae8a6632c7a0a936ebbca`。
- producer handoff HEAD / 独立测试 HEAD：`3f70c4796aaa37dc1d309db2fc7b09fc8fb061eb`；tree：`d2e484c1a2b51b8b64a55d2f69e8591d60de473d`。
- 独立分支：`agent/integrator/integrate-candidate-management-oneclick-20260926`；planner sparse worktree：`D:\vibe coding\Obsidian\量化系统\worktrees\integrator-integrate-candidate-management-oneclick-20260926`。
- 初始 scoped dirty：0；`core.sparseCheckout=true`。使用 `git merge --ff-only 3f70c479...` 保留 producer 的 `2b0db9cb9 -> d83de5f00 -> 3f70c479` 原始祖先关系，未触碰注册 main。
- 官方 handoff 校验：`published-candidate-management-oneclick-20260926-d83de5f00` 为 `valid`；4 个 deliverable 的 schema、Git 对象与 SHA-256 均匹配；base、deliverable、handoff 祖先关系有效。
- 净业务 touch set 仅 4 个新增文件：根目录 CMD、交互 PowerShell、对应测试、操作文档；handoff HEAD 另新增 producer append-only event。无前端、业务 API、权限、策略、OMS、账本或治理改动。

## 独立检查结果

- `start-candidate-management.cmd` 为固定零参数双击入口，不展开或转发用户参数；以 `-STA -ExecutionPolicy Bypass` 调用受审 PowerShell 并精确保留退出码。
- PowerShell 在任何配置选择或口令提示前校验 sparse 注册主工作树、`HEAD == refs/heads/main`、当前端口状态与 canonical Python；8765 已占用时返回 `existing_backend_kept`，不停止或替换现有 listener。
- 配置路径只接受本机绝对盘符 JSON，拒绝 UNC、控制字符和 shell 元字符；优先级为显式参数、Process 配置变量、同名 User 非敏感路径、文件选择器。只有用户明确输入小写 `y` 才持久化非敏感配置路径。
- wrapper 不读取或保存 User auth，不含 `QS_WEB_API_KEY`，最终仍调用既有受审 helper 的 `start --config ... --prompt-auth`；未引入绕过认证、自动任务、交易或服务 kill 的路径。
- 真实 Windows PowerShell 5 非敏感 TTY 探针按源码同型 `& python ... | Out-Host` 调用，输出 `stdin=True stdout=False stderr=True len=18`，固定 dummy 输入未回显、退出 0。由此确认 `stdin`/`stderr` 仍为 TTY，`getpass` 未回退；`stdout=False` 是预期管道结果。此前两次探针仅因外层引号构造触发 Python `SyntaxError`，未执行源码且不构成产品失败。
- 文档准确声明：一键入口不免认证、不自动终止监听器、不创建或启动候选任务；取消选择安全退出 0。

## 独立测试

1. `canonical .venv python -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider --basetemp <isolated> backend/tests/test_candidate_management_interactive_launcher.py`
   - `31 passed in 61.46s`。
2. `canonical .venv python -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider --basetemp <isolated> backend/tests/test_backend_current_main_launcher.py -k candidate_management`
   - `20 passed, 29 deselected, 1 warning in 36.30s`；warning 为既有 Starlette/httpx 弃用提示。
3. `git diff --check 3631aa09...3f70c479...`
   - exit 0。

未运行：214 项业务矩阵、长 lifecycle、真实 GUI 文件选择、真实凭据输入、User 环境变量写入、实际服务启停、浏览器、候选作业、private/order/live endpoint。它们均不属于本次 wrapper 独立源码验收；本次未读取 secret、未访问真实账户、未造测试目录数据。

## 保持关闭与后续

- `promotion_eligible=false`；promotion、paper、live、private endpoint、order endpoint、真实订单均保持禁止。
- 管理服务未由本票启动或启用；实际 8765 listener 未被本票触碰。
- 主会话若合入，仍需在 canonical main 上验证 source-only merge、current-main 身份，并按既定计划对现有 readonly listener 做“拒绝且原进程不变”的真实 wrapper 检查；缺本机认证时必须 fail-closed，不得声称 candidate management 已启动。
- 无 artifact/manifest/ledger 由本票生成；既有候选数据质量与运行证据状态不变。

## 治理证据

- 读取：`AGENTS.md`、`docs/knowledge/README.md`、`quant_system_non_negotiables.md`、`shared_pitfalls.md`、integrator playbook，以及 quant-agent-preflight、quant-gate-evidence-review、quant-agent-handoff 指令。
- context catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- 冲突：无；未合并的其他代理 dirty：无（仅按本票 pathspec 检查）。
