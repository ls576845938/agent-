# 一次性全账户只读收据：限定治理修订

Ticket: PRIVATE-READONLY-PURPOSE-20260914. Change risk: governance_control.
Base: a89d3dadc59b63e69d541508b941e6103ace7890. Producer: super_developer.

## 边界与状态

本票据只扩充签名收据的用途与入口绑定，不实现或运行账户采集，不改策略、参数、风控、OMS、保护单、账本、服务或页面。
全账户采集入口尚须由独立业务票据交付；本票据不是账户验收，也不启动受控 Demo 或 M3—M4。

| 收据 | 用途 | 唯一零参数入口 |
| --- | --- | --- |
| v1（默认、兼容） | btc_demo_observation | scripts/run_btc_demo_private_readonly_observation.py |
| v2（显式选择） | okx_demo_account_facts_once | scripts/run_btc_account_facts_readonly.py |

v1 字段、旧命令与旧防重放声明格式保留。v2 要求显式 purpose，不能借 v1 字段或修改路径迁移用途。
用途和脚本路径进入签名正文；验证当前 main HEAD、提交 blob、工作树文件 SHA-256、会话、60—900 秒 TTL、撤销状态和权限。
arm / lease 内嵌完整签名收据。新用途的 binding / launch / start 声明携带用途和路径；启动摘要由对应固定命令推导。
跨用途命令与进程自授权均拒绝；一次 launch / process-start 仍原子排他。后续进程不可重用已消费收据。

未实现、未提交、被修改的新入口不能生成有效收据；不回退到旧 observer。未来新入口必须在凭证或网络操作之前，以固定 ACCOUNT_FACTS_RUNNER_PATH 调用 authorize_runner_process，拒绝用户附加参数；不得从环境变量选择用途。

## 生效与操作顺序

1. 独立 integrator 验证提交、touch set、回归与 handoff 后，按本次授权集成治理修订。
2. Hook 源码发生变化；客户端若提示未信任，人工审查并通过 `/hooks` 信任新 hash。不得绕过，也不得声称旧任务已热更新权限。
3. 在新鲜上下文中完成已授权的独立全账户只读业务入口与审查。治理票据不夹带该业务实现。
4. 最终主分支版本固定后，外部人工终端使用既有 prepare / sign / install 流程；新用途的 prepare 增加 `--purpose okx_demo_account_facts_once`，TTL、签名命名空间及已登记操作员公钥不变。人工确认文本同时包含会话与用途。
5. 不在 Codex 内生成签名密钥、签名、准备或安装真实收据。安装后下一条根用户消息使该会话 arm；只能执行其精确零参数入口一次，失败后不得重用。

新入口仍须独立证明：只读 endpoint 白名单、全账户覆盖、分页及时间边界、账户事实脱敏、缺失即阻断。收据仅许可一次指定程序读取，不证明数据完整、回撤基准获批、账本对齐或交易可用。

## 验证与交付记录

主工作树与 producer touch set 初始均 clean，其他未关联改动不触碰。producer 为 planner sparse worktree；为 Hook 导入补出同提交 quant_crypto 只读源码，未修改它。

读取：quant-agent-preflight、quant-agent-handoff；knowledge README / non-negotiables；shared_pitfalls / super_developer_pitfalls；delivery_risk_policy。
Catalog: 6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af。
Active IDs: GOV-CONCURRENCY-001, GOV-DIRTY-001, GOV-ENGINEERING-CIRCUIT-001, GOV-HANDOFF-001, GOV-OBJECTIVE-001, GOV-PITFALL-001, GOV-ROOT-001, GOV-STORAGE-001, GOV-WORKTREE-001, QSYS-GATE-001, QSYS-SECURITY-001, GOV-PROMPT-001, GOV-WINDOWS-001。

新增离线用途测试首轮 12 passed；默认 py -3 无 pytest，改用现有主仓 .venv。最初完整回归 57 passed / 5 failed，失败为 sparse 缺 quant_crypto 的 Hook 导入；补齐只读依赖后重跑。无安装依赖、无业务修复。
正式测试命令：主仓 `.venv/Scripts/python.exe -m pytest tests/agent_governance/test_private_readonly_permission.py tests/agent_governance/test_private_readonly_purposes.py tests/agent_governance/test_hooks.py -q --tb=short --basetemp <独立系统临时目录>`，进程 PYTHONUTF8=1。
最终分两次完成：收据与用途测试 66 passed（29.73s）；Hook 测试 8 passed（38.64s），合计 74 项，非一次单命令结果。git diff --check 通过。
中间回归曾出现 72 passed / 2 failed：新增未激活用途提示占用 Hook 4000 字符预算，截断角色规则；同两项在原主分支 2 passed。已将用途提示限定在 armed/active 状态，最终 8 项 Hook 回归通过。没有修改规则 catalog 或原测试断言。

未运行：真实签名准备/安装、真实账户采集、交易所调用、策略运行、前端回归、账本写入与恢复验收。测试只使用临时收据与 inert Git fixture，不能作为 promotion evidence。
不重建 BTC artifact/read model，不重启后端；旧 evidence 仍绑定原 HEAD，不能冒称新 HEAD 证据。
私有采集依然 blocked；promotion、paper、live、private、order、real_order、transfer、withdraw 均未授权生效、保持 false。签名收据中 private=true 仅为未来指定一次只读程序的条件能力，不是平台全局开关。
