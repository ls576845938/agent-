# 候选交付后端：源码候选与限定验收

## 任务与停止边界

日期：2026-09-24。角色：主会话按 `super_developer` 写票执行。
Base：`55f039ae5fbcd48730cc55cb0ade2c0d92eb3066`。
分支：`agent/super_developer/candidate-delivery-backend-20260924`，由 planner 创建专属 sparse worktree。
`change_risk=unclassified`，沿用严格独立审查/集成路径；不是普通前端发布票。

用户授权：实现包验证、审定、账户绑定、登记和撤销；管理写入默认关闭；不启用、不发布。本票不修改启动器/治理机器规则，不训练/搜参，不改策略、Risk、Guardian、OMS、保护单、账本或原 Demo 启动合同。

源码实现与测试不能被描述为独立审查通过或正式交付上线。当前跨代理 Team Context 出现 `handoff_discovery_timeout`，故独立审查尚未进行；没有绕过发现工具。发布/集成、正式页面、真实账户绑定均未验收。

## 实现边界与调用关系

```text
既有研究交接面板（明确点击/管理认证）
  → 默认关闭的管理 API（不是 Demo API）
  → 服务端解析精确 run/candidate、重新验证封印及固定策略合同
  → validate → bind → review → register；可 reject/revoke
  → 独立管理 SQLite：原子事务、版本 CAS、幂等回执、追加审计事件
  → 管理目录/精确 BTC 离线加载合同
  × 不创建回放器或 Demo 控制器，不推理、不下单、不写经济账本
```

核心模块：

| 路径 | 职责 |
|---|---|
| `quant_shared/strategy_delivery/models.py`、`service.py` | 资产中性交付合同、精确摘要、状态转换、审定绑定、版本/过期拒绝 |
| `backend/app/services/candidate_delivery_sources.py` | 仅从服务端已登记来源编译包；校验封印、最终审计引用、固定执行绑定 |
| `candidate_delivery_accounts.py` | 服务端非秘密账户引用；离线模拟命名空间，或既有审定账户事实回执；不调用 private |
| `candidate_delivery_store.py` | 外部管理库事务、单写序列化、CAS、幂等、账户独占登记、哈希核验；不是交易账本 |
| `candidate_delivery_bootstrap.py` | 延迟组装、不初始化目录；只有显式命令创建管理存储 |
| `backend/app/api/candidate_delivery.py` | 管理认证、精确白名单、拒绝客户端权限/账户哈希、干净错误码 |
| `backend/app/core/{backend_access_policy,config,deps}.py`、`api/app_factory.py` | 单独管理配置；继承研究读取边界，只增加管理 API；禁止构造 Demo |
| `quant_crypto/application/btc_registered_candidate.py` | exact registration + digest + account hash + adapter 校验，返回已有离线入口绑定；不启动 |
| `frontend/src/workspaces/research/{CandidateDelivery.tsx,candidate-delivery-api.ts}` | 认证、验证、绑定、人工审定、登记/撤销、未知提交查询及原幂等键重试 |
| `CandidateHandoff.tsx`、`CandidateHandoffInbox.tsx`、`candidate-handoff.css` | 只接入现有交接区域；原草稿、控制台及布局保持 |

完整策略包包含来源/代码/参数/数据身份、产物 SHA-256、特征、预处理、输出类型/单位/期限、校准、仓位、退出、成本、时间和状态版本，以及精确既有执行绑定。管理层校验不伪造统计指标、不覆盖研究阻断，也不改变已封存模型。

## 当前支持与明确缺项

- Donchian：唯一已冻结 `donchian-long-50usdt-20260921` 历史规格；注册候选版本/参数须吻合。固定 0.01 合约、50 USDT 名义限额和 10 USDT 损失阈值不变。此处不重新核验全部历史数据文件，真正运行前仍须现有历史入口的数据准入；管理包明确标记此限制。
- Qlib：仅已审固定 `m1-okx-qlib` 执行绑定，核验完整封印、模型和校准/政策绑定。真实封存的 `no_simulated_fills` 等阻断保留，因此该候选仍不能审批登记通过；更不能通过更换标题变成 Demo。
- Alpha 工厂：必须精确候选及最终审计 Qlib 引用、封印一致；没有受支持的完整执行绑定时记录 `runtime_adapter_binding_missing`，不回退折内模型或 Donchian。
- 当前接受的执行环境绑定只有 `offline`。`okx_demo` 可作为验证请求目标，但现有两个适配器均无此兼容声明，必须受阻。通用 Demo Qlib 适配不是本票能力。
- 目录不是原 `btc_strategy_registry` 的可变全局注入。新增管理目录返回已登记记录；BTC 解析器只返回现有离线入口合同。既有离线 CLI/Demo 启动器不会自动消费登记，启动接线仍须独立授权/验收。
- 单一服务端配置操作员，不是多用户 RBAC/双人签字系统。审定身份来自认证配置，不信任浏览器 `approved` 或 reviewer 名称。此项局限如实保留。

## 权限和账户配置（说明，不是启用作业）

默认不选择 `candidate_management`。只有另行批准启用后才可由运维设置该 profile、`QS_CANDIDATE_DELIVERY_ROOT`、`QS_CANDIDATE_DELIVERY_OPERATOR` 和既有本机 Web 管理认证。生产密钥不是管理口令；代理未读取任何实际口令。

管理根必须在仓库之外且不是磁盘根。GET/应用构造不得 mkdir 或创建 SQLite。所有管理数据保存在独立的 `candidate-delivery.sqlite`；管理口令不落库、不进请求体、不进入浏览器存储。

账户目录为管理根 `accounts.json`，服务端配置，不接受浏览器任意 hash/verified/currency 覆盖。离线记录必须明确 `environment=offline` 和 `simulation_namespace`，不是冒充真实账户。Demo 账户若未来使用必须引用现有独立审定账户事实 approval，不能靠手填账户生成准入。此次仅测试临时模拟目录，没有创建实际运维账户目录。

审定回执绑定包摘要、目标、账户证据摘要、consumer HEAD、validator 和 adapter；有效期 24 小时。重绑使旧审定失效。包、账户、部署 HEAD 或有效期变化时登记/消费拒绝。撤销释放登记占用，但**不表示已撤单/平仓或停止某个将来运行**。

POST 用 `Idempotency-Key`，每个动作带 `expected_revision`。结果未知时锁住后续变更，先查 `/requests/{key}` 或重试同一幂等请求。普通读取只返回保存的管理快照，不重新编译模型包；目录标记 snapshot-only/start_allowed=false，消费前另行重新验证。

管理库使用 SHA-256 检测损坏，不声称能抵御具有本机数据库写权限、能同时重写摘要的恶意管理员。密钥保护和文件权限仍是部署责任。

## 验收命令与结果

工作目录为票据 worktree，Python 使用 canonical main 的 `.venv/Scripts/python.exe`。pytest 设 `QS_BACKEND_EVIDENCE_PROFILE=research_readonly`，使用自有临时目录，不动现存账户/账本/暂停历史运行。

1. Failure-first：新共享模块不存在时 `test_strategy_delivery.py` collection 失败；实现后首批 12 passed。
2. 最终候选域/API/原公共行情/BTC 目录：
   `python -m pytest -q tests/contracts/test_strategy_delivery.py tests/contracts/test_candidate_delivery_api.py tests/api/test_btc_public_market_readonly.py tests/contracts/test_btc_strategy_registry.py -p no:cacheprovider --tb=short --basetemp <TEMP>/qs-admin-http-final-20260924`
   **57 passed，1 项既有 Starlette/httpx 弃用警告，50.51s**（在 56 项基础上补充拒绝其他注册 worktree 内的管理根）。
   覆盖事务中断回滚、并发幂等、CAS、审定失效/过期、账户冲突、撤销、来源漂移、损坏记录、HTTP 回执恢复、来源真实封印、固定规则登记/解析、默认关闭、认证/origin、拒绝训练/private/控制，以及独立 Python 进程不构造 Demo/不联网。
3. 扩展原 V1/V3 兼容首跑 **13 failed / 78 passed**：测试临时路径 `qs-delivery-final-20260924` 包含 `live` 子串，触发现有 `execution_state_directory_mode_crossed`。不修改安全规则或业务预期，仅换目录复跑：
   `python -m pytest -q tests/contracts/test_strategy_v1_donchian_offline.py tests/contracts/test_strategy_v3_qlib_offline.py tests/contracts/test_strategy_v3_unified_closeout.py -p no:cacheprovider --tb=short --basetemp <TEMP>/qs-candidate-admin-20260924`
   **37 passed，1016.49s**。此次为既有软件合同测试，不是新年度回测或真实运行验收。
4. 前端：`node --test frontend/scripts/test-candidate-delivery.mjs frontend/scripts/test-candidate-handoff.mjs`，**19 passed**。这是协议/SSR 测试，不是浏览器点击验收。
5. `frontend/node_modules/.bin/tsc.cmd --noEmit` 通过；`vite.cmd build` 通过（5270 modules）。初次新增代码类型检查的事件参数/组件 key 错误已修复；构建仍有现有大 chunk 警告，不扩大性能重构。
6. 未运行：管理 profile 实际部署、正式浏览器交互、真实账户/交易所、任何策略推理/历史评估/新训练、全仓回归。独立审查尚未通过，不能称发布完成。

## 治理、冲突与交接

- 初始限定 touch set 为 clean。本任务单写者，在专属 sparse worktree 编辑；未覆盖他人 dirty，无消费未提交上游。`quant_crypto`/`quant_cn` 为测试导入补充只读 checkout，除新增 BTC 解析文件不改其余源码。`frontend/node_modules` 是指向现有依赖的忽略 Junction，未安装依赖。
- touch set 为上表源码、两份 `tests/contracts/test_{strategy_delivery,candidate_delivery_api}.py`、两份前端 `scripts/test-candidate-*.mjs`、本报告和既有 `docs/architecture/candidate-runtime-handoff.md`，以及本票 `.agent/handoffs/` 事件。
- 已读 preflight/handoff skills、knowledge README/non-negotiables、domain architecture、shared/super-developer playbooks、角色规则与交付政策。
- Catalog：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- 采用 GOV-CONCURRENCY-001、GOV-DIRTY-001、GOV-HANDOFF-001、GOV-ROOT-001、GOV-WORKTREE-001、GOV-STORAGE-001、GOV-ENGINEERING-CIRCUIT-001、GOV-OBJECTIVE-001、GOV-PITFALL-001、GOV-PROMPT-001、GOV-WINDOWS-001、QSYS-GATE-001、QSYS-SECURITY-001、REPLAY-ISOLATION-001、BACKTEST-COST-001、RESEARCH-HOLDOUT-001。
- 交接等级仅 `quality_checked` 源码候选，不是 promotion evidence。最终提交及哈希以本票后续 append-only handoff 为准；报告不伪造自引用提交。
- `unclassified` 的独立 integrator、current-HEAD promotion artifact 和重启要求未履行，因为本轮禁止启用/发布；不能由此 fast-forward main。源码可留存，但不能跨越审查/发布门禁。
- 当前 blocker：Team Context 的 bounded discovery 连续超时；责任为本地交接发现环境，恢复后先验证提交态 handoff，再由独立审查者审查本票差异。不借本票改治理工具，不为解除阻断新增工程循环。
- `demo_control_enabled/execution_permission/runtime_observed/promotion/paper/live/private/order/real_order/transfer/withdraw` 均 false；未合 main、未部署，旧主版本保持原状。回退无需破坏性操作：不采用此候选即可。
