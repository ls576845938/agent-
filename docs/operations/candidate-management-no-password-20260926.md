# 本机候选管理免手输口令

票据 CANDIDATE-MANAGEMENT-NO-PASSWORD-20260926；role=super_developer；
change_risk=unclassified；base=568a8985eb4f9d9a614881e4cbac31eecdf048d3。
只交付源码候选，不合 main、不启停服务、不修改外部 deployment 配置或候选数据。

## 使用与威胁模型

合入并由主会话验收后，原双击入口将以 --auth-mode local_no_password 调用原部署 helper，
不再使用 getpass / --prompt-auth，不生成或保存替代密码。默认直接 helper / 环境配置仍是 key；
旧 key 模式继续校验原密钥。九键部署 JSON 不变，新模式仅作为子进程
QS_CANDIDATE_AUTH_MODE 传入；profile、owner/hash/revision、offline enabled 值均不改。
首次选文件/可选“记住路径”不属于密码环节，原取消和端口占用阻断仍保留。

local_no_password 只在 candidate_management 对精确候选管理/离线路由生效：
真实连接 peer 必须 loopback（含 IPv4 mapped），Host 必须是固定 loopback 名称与正式端口，
固定公开 X-QS-Candidate-Intent: candidate-management 表示显式请求意图，不是密钥。
拒绝远程 peer、转发头、异常/重复头、null/跨站 Origin 和不完整或冲突的 Fetch Metadata。
不信任 Host 自称本机，也不信任 X-Forwarded-For 被 Uvicorn 改写后的 peer。

Vite guard 在 changeOrigin 代理之前验证原始 socket peer/rawHeaders，
覆盖两个候选 namespace 的编码、重复/尾斜线、反斜线和点段变体。
无关市场 GET 不受影响；旧 key-only 请求不要求新增 intent/Fetch Metadata，
但候选代理边界仍拒绝远程/伪造 Host/跨站 Origin/转发头。
只提供可被本机程序调用的管理界面，不是个人身份强认证：
本机进程/可在本机执行 HTTP 的程序属于信任范围。机器多用户隔离/恶意本机程序不在保护范围。
不要部署为公网或 LAN 的免认证管理接口，也不要额外建立会抹除真实来源的可信代理。

浏览器写请求：可信精确 Origin；若含 Fetch Metadata 必须完整 same-origin /
mode=cors|same-origin / dest=empty。浏览器缺 Origin 的写请求拒绝。
同源 fetch GET 通常没有 Origin，因此只读 GET 可凭完整上述 metadata + 可信 Referer 通过；
不可信/缺失 Referer 或不完整 metadata 拒绝。禁用 Referer 的浏览器可能被阻断，不降级放行。
无 Origin、无浏览器 metadata、无 Referer 的 CLI 必须同时满足真实 loopback、合法 Host、intent；
这明确依赖“本机程序受信任”，不把公开 intent 伪装成秘密。
固定 Host：后端 127.0.0.1/localhost/[::1]:8765；前端同名 :3000。
浏览器 Origin 允许相应 http 来源，前端要求 Origin/Referer 与自身 Host 精确匹配。

后端请求验证产生进程内 context，offline service 只接受同一验证 context 或原 key 模式密钥，
不接受空密码、固定密码、布尔“已授权”或 HTTP 字符串绕过。
offline enabled=false 仍 423，profile/read-only 写禁令、幂等键、revision、账户/币种、
输入与证据身份、无自动启动原则全部保留。CLI Python 原 key 入口不新增绕过；
无密码 CLI 指经过同样请求边界校验的本机 HTTP。

前端只读 capability 发现 local 模式后不出现密码输入，也不以非空 key 禁用操作；
明确 key 模式（或合法旧 capabilities 协议）才显示旧密码框。
未知/423/网络失败显示“未开放/待读取”，不会把失败当作需要输入密码。
页面加载、展开管理区与读取精确证据仅 GET，不注册、不执行离线作业。

## 文件与验收

- 脚本两项：双击 PS1 和 deployment helper 的显式模式。
- 后端：config、candidate_local_auth、两个候选 API、app_factory 两行接线、
  bootstrap 和 offline service 认证入口；不改 offline 经济计算。
- 前端：两个候选 API 客户端、CandidateDelivery、RegisteredCandidateOfflineEvidence、
  Vite 配置与独立局部 guard；不改其他页面布局。
- 回归：新 local-auth Python/Node、既有候选前端脚本和两份启动器测试；
  另经主会话批准精确增加 frontend/e2e/candidate-offline.spec.ts，更新一处初始 SSR 密码旧断言。
- frontend-identity.json 仅提交态派生；本文件与本票 append-only handoff。
- 无数据 manifest、ledger、replay 或 promotion artifact 产出。

失败优先：新 local-auth 测试在实现前明确报 ModuleNotFoundError（1 error / 2.56s）。
初轮后端边界 29 passed；补齐同范围浏览器/CORS/旧 key/合法 POST 后 35 passed / 2.16s。
Node 前端与代理 13 passed / 5.08s；tsc --noEmit exit0。
Node 初轮实际 Vite 配置加载曾因中文/空格 URL 未解码失败，改 fileURLToPath 后通过；
未改变运行守卫。旧前端测试中已有过时登记文案断言和 TSX 子组件加载缺口已同范围同步。
旧 SSR 初始密码断言先失败（其余四项子测通过），修改为待读取/无密码/disabled 后，
与无密码部署配置定向一起 2 passed / 10.64s。
旧完整组合运行包含旧离线身份/执行矩阵，期间出现上述 SSR 旧断言失败；
在主会话收敛验收预算后以 Ctrl+C 正常中断本票 pytest（exit1，无最终汇总），
不将点状进度/部分完成计为整套通过，不宣称未完成的身份/重放/封存/账本矩阵已验收。
随后必要矩阵通过：
- backend/tests/test_candidate_management_interactive_launcher.py：31 passed / 21.61s。
- backend/tests/test_backend_current_main_launcher.py -k 'candidate_management or candidate_local_mode'：
  21 passed / 12.46s，29 deselected，未声称全 50 通过。
- tests/contracts/test_candidate_delivery_api.py 加 test_candidate_offline_access.py 的
  test_independent_capability_blocks_all_writes_even_with_key、test_local_auth_opaque_fields_no_get_side_effects、
  test_precise_route_allowlist_readonly_never_writes：33 passed / 62.83s。
- 一项现有 Starlette/httpx 弃用警告；没有因此修改依赖。
- 最终 staged diff --check；初次只发现两个新文件末尾空行，删除后通过。

所有命令都在票据 worktree，
使用 canonical .venv Python -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider，
Node --test 与 frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json。

初始精确 touch set clean，未覆盖他人改动，主工作树不写。
只读依赖 sparse 增加 quant_crypto/quant_cn；frontend node_modules 使用现有依赖 junction。
已读 AGENTS、super-developer role、知识 README/non-negotiables、
shared_pitfalls/super_developer_pitfalls 和 quant-agent-preflight/quant-agent-handoff；
上游 oneclick handoff validate=valid。
catalog hash=6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
IDs：GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-ENGINEERING-CIRCUIT-001、
GOV-HANDOFF-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-ROOT-001、
GOV-STORAGE-001、GOV-WORKTREE-001、QSYS-GATE-001、QSYS-SECURITY-001、
GOV-PROMPT-001、GOV-WINDOWS-001。不加载无关历史原始日志。

仍需独立 integrator 审查、主会话合入/部署与真实 main identity/浏览器验收。
本票仅 quality_checked，源码/派生证据绑定提交，不声称当前运行服务已免口令。
未读取真实凭证、启服务、写外部配置/候选数据、跑真实回测或采集账户。
promotion、paper/live、private、order、real_order、transfer、withdraw 全 false；
无晋级/交易产物重建，无权限提升。
