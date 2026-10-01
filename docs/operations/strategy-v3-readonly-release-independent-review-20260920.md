# V3 离线只读发布：独立交付审查

日期：2026-09-20。票据：`V3-READONLY-DELIVERY-INTEGRATION-20260920`。结论：**限定源码及治理候选通过独立审查，准许进入本次已授权的正式只读发布验收；正式发布尚未验收。** 证据强度上限 `quality_checked`，不授予 Demo、paper、live、private、order 或 promotion 权限。

## 审查对象与边界

- 注册主版基线：`b920d131e41ecbfe7f76f0709affbe22c8b35f5e`；冻结业务源码：`aca55c90d82b327800e473774e22dbbeac69bd90`；治理提交：`0fbefe044369878deb82cd42c553abc9dc25bfba`；append-only 发布交接后的候选：`966582cc446172307e54f32cbad2a930e94fbdd0`。四者依次满足 Git 祖先关系。
- 本独审工作树由 `worktree_plan.py` 从基线建立，为 `agent/integrator/v3-readonly-delivery-integration-20260920` 的 sparse checkout；`core.sparseCheckout=true`。合入候选前，对本票 6 个治理文件、交接和独审报告的限定 `safe_status` 为 `clean`；`git merge --ff-only` 只推进本集成树到 `966582cc4`，无冲突、无他人 dirty 被覆盖，注册主版未动。
- 生产交接 `published-v3-readonly-delivery-20260920-0fbefe044` 与其依赖的上游 `acknowledged-btc-v3-event-ordering-independent-review-20260920-645e1ce04` 均经 `handoff.py validate` 返回 `valid`；提交存在，祖先、报告对象 SHA-256、schema、`quality_checked`、blockers 与安全旗标已核对。
- 冻结清单 `strategy-v3-readonly-source-20260920.json` 覆盖基线至业务源码的全部 **88 个**净差异路径；逐项读取该提交的 Git 原始 blob，**88 个 SHA-256 全部匹配**，路径集合一致。清单原始 SHA-256 为 `94052bc92c9dbaa2895b4baa82f1ead3059f280a1bfaf7320e475298ccfb45ac`，规范化摘要为 `f87bd74bf0a992601d7d45f0affcb7d67aff578702d1ec656dc38c3aaad6bbb1`，与交接和校验器一致。
- 业务源码之后仅新增限定 V3 规则、校验器、对应测试/文档/清单及本票交接。未出现新的执行语义变更；旧 `change_risks` 与 V1 只读合同保持相同 JSON。V3 新合同固定源码、主版基线、`research_readonly`、`offline_execution` 和失效即阻断的权限旗标；没有改现有策略、Risk、OMS、账本、页面、启动器、hooks 或权限。

## 独立验证与证据局限

使用注册主版 `.venv/Scripts/python.exe`、本独审树源码及独立 pytest 临时目录，运行 `python -B -m pytest -q -p no:cacheprovider --tb=short` 的六个治理测试文件：`test_strategy_v3_readonly_delivery.py`、`test_strategy_v1_readonly_delivery.py`、`test_research_release_policy.py`、`test_delivery_policy.py`、`test_context_packet.py`、`test_governance_contract.py`，结果 **144 passed / 22.48s**。覆盖 V3 票据身份、冻结清单、提交引用、literal bool、缺证拒绝、发布与源码阶段分离，及旧 V1/通用规则兼容。生产方 failure-first 14 failed、新实现 142 passed 加后续 2 项单独通过，可作过程证据；本独审的 144 项是同一次运行。

上游 V3 事件顺序独审已记录：业务 52 项生产方末轮 **51 passed / 1 failed**，失败时 HEAD 在运行中被 handoff-only 提交移动；固定 HEAD 的独立五项复验 **5 passed / 370.60s**，覆盖该失败用例和新时槽恢复/过期 ACK/破损批次。不能宣称一次固定 HEAD 的 52/52；本治理票也没有重跑业务 52 项或离线 CLI。上游封存候选原 CLI 两次均为 1392 次逻辑决策、22 个物理拒绝批次、0 批准、0 成交，这不是策略盈利、真实执行或交易准入证据。

校验器能核对冻结对象、提交链和报告摘要，不能单凭 receipt 的 `true` 保证页面或运行事实。本独审已核对上述源码、旧规则和测试；其余只读启动、固定 HEAD 离线运行及恢复、浏览器和回退点须在后续部署验收中真实执行，再填写部署 receipt。现有 V3 页面关联若缺失，须如实报告，不补造新控制台或运行观察。

## 后续限定步骤与安全状态

只允许在主版仍为上述基线、无相关 dirty 和非覆盖回退点已建立时，快进本次审定提交；然后固定发布 HEAD，以 `research_readonly` 运行正式前后端入口、一次原候选 CLI 加同目录恢复，检查必要页面与身份。任何一步失败，保留阻断并停止此发布路径，不扩大业务代码和交易权限。

预检读取 `AGENTS.md`、knowledge README、non-negotiables、shared pitfalls、integrator role config，使用 `quant-agent-preflight`、`quant-gate-evidence-review`、`quant-agent-handoff`。catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`；命中 `GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-ENGINEERING-CIRCUIT-001`、`GOV-HANDOFF-001`、`GOV-OBJECTIVE-001`、`GOV-PITFALL-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`MONITOR-AUDIT-001`、`QSYS-GATE-001`、`QSYS-SECURITY-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`；未全文读取旧事故日志。

本票未发布新的市场 artifact、真实账本或 promotion evidence。`demo_control_enabled=false`、`runtime_observed=false`、`execution_permission=false`、`promotion=false`、`paper=false`、`live=false`、`private=false`、`order=false`、`real_order=false`、`transfer=false`、`withdraw=false`、`runtime_worker_enabled=false`。未读 secrets，未访问账户、交易所、private/order/live endpoint。
