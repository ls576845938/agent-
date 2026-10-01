# 候选管理双击入口（2026-09-26）

## 使用

独立审查并合入后，在注册 main 工作树中双击根目录 start-candidate-management.cmd。
CMD 是无参数入口，不展开、不转发任何附带参数；显式路径参数仅由 PS1 的
ConfigurationPath 接收。不要从票据 worktree 启动。

入口先验证 registered main、sparse 与当前 HEAD，再只读检查端口 8765。
端口已占用时提示 existing_backend_kept / Switch required，退出码 2：
现有后台保持不动，需要由操作者协调切换。未知监听状态也阻断。
不查账户、不访问交易端点、不停止进程、不换端口。最终监听与身份守卫仍由原入口执行，
前置检查不消除竞争窗口，更不替代正式守卫。

配置优先级：PS1 ConfigurationPath 参数、进程环境中的 QS_CANDIDATE_DEPLOYMENT_CONFIG、
User 环境中同名非敏感变量、文件选择器。选择器默认文件名 deployment-enabled.json。
取消选择安全退出（0），不保存路径、不询问口令、不启动。
路径必须是存在的绝对盘符 JSON 文件；支持中文、空格、单引号。
双引号、控制字符、反引号、&、括号等复杂路径稳定拒绝，不解释执行；UNC 路径暂不支持。
已保存路径失效时，设置新的非敏感路径变量或使用 PS1 显式路径参数；不会静默采用其他配置。

只有文件存在、大小不超过 2 MB、JSON 为原 helper 的精确九个字符串键后，才询问
Remember this configuration PATH for next time? [y/N]。仅输入小写 y 才保存 User 路径，
其他输入跳过；已有同一路径不重复询问。保存失败仍可继续本次启动。
此处只验证配置形状，owner/hash/revision/profile/权限等校验完全留给现有 helper，
形状通过不代表配置可用或权限就绪。不要将凭证放进该 JSON 或路径变量。

一键不等于免认证：原 helper 仍通过隐藏输入询问本地 Web 管理口令；包装层不读取、
记录、保存或转发口令，不读取 User 范围认证变量。网页仍须原有管理解锁。
helper 仅收到 start --config <路径> --prompt-auth，原正式后台入口不变。
启动在当前窗口前台运行，Ctrl+C 终止前台运行；CMD 结束后保留窗口提示，
错误码原样返回。helper_exit=0 仅是进程退出码，不宣称后台正在运行。

## 责任与边界

- start-candidate-management.cmd：ASCII 双击入口、进程级执行策略、保留错误窗口。
- scripts/start_candidate_management_interactive.ps1：ASCII / Windows PowerShell 5 兼容；
  本地只读 main/端口检查、配置定位与显式路径记忆、原 helper 前台委托。
- backend/tests/test_candidate_management_interactive_launcher.py：PS5 回归；
  选择器、记忆和启动副作用由 mock 替代，不访问真实认证信息。
- 本文：使用说明及验收记录。未修改原 helper、启动守卫、认证、业务代码或共享合同。

票据 CANDIDATE-MANAGEMENT-ONECLICK-20260926；
role=super_developer；change_risk=unclassified；
base=3631aa09dbbc0f3208d439c8539cbba718a08f51。
独立 sparse worktree，初始精确 touch set clean，无冲突或他人改动被覆盖。
另仅允许本票 .agent/handoffs/ 中 append-only 交接。

## 验收记录

使用 canonical main 的 .venv/Scripts/python.exe，在票据 worktree 运行：
-B -X utf8 -m pytest -q --tb=short -p no:cacheprovider 后接测试文件。

- 失败优先：新测试先运行，24 failed / 4.20s；因两个入口尚不存在，未触发服务。
- 首轮实现：wrapper 24 passed / 54.66s。
- 既有 backend/tests/test_backend_current_main_launcher.py：49 passed / 55.13s，
  一项现有 Starlette/httpx 弃用警告。
- 最终 backend/tests/test_candidate_management_interactive_launcher.py：31 passed / 58.24s，
  含字面参数委托、前台子输出、非零返回码、main/HEAD/sparse 和可跳过路径记忆。
- 所有运行/路径记忆操作为 mock；中文空格单引号文件使用临时目录。
- 未运行真实文件选择器/隐藏口令/持久化、实际后台启停或端口切换、浏览器、
  214 项业务矩阵或年度回放；不以模拟通过宣称部署验收通过。
- 未重建 promotion artifact/read-model 或重启后台：这是 producer 包装层交付，
  非 promotion 交付。严格 unclassified 后续要求由独立 integrator / 主会话处理，
  不因本次测试放宽。main 未由 producer 修改或合并。

已读 quant-agent-preflight / quant-agent-handoff、AGENTS、super-developer role、
知识 README / non-negotiables、shared_pitfalls / super_developer_pitfalls。
catalog hash=6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
active IDs：
GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、
GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、
GOV-STORAGE-001、GOV-WORKTREE-001、QSYS-GATE-001、QSYS-SECURITY-001、
GOV-PROMPT-001、GOV-WINDOWS-001。

上游 published-candidate-management-deploy-20260926-9dc28c7f5 已运行 handoff.py validate：valid。
上游历史 blocker 不由包装层解除。交付仅 quality_checked；
promotion、paper/live、private、order、real_order、transfer、withdraw 权限全部 false。
本票不产数据 manifest、ledger、replay 或可用性声明；源码证据绑定 deliverable commit，
合入后 current-main listener、HEAD/identity 及真实界面验收由主会话独立确认。
