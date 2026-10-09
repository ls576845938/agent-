# BTC 共同账户组合入口与恢复最终独立验收

票据：`BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004`

角色：`integrator`

变更风险：`demo_execution_semantics`

## 审定结论

**限定批准 source integration 与 `research_readonly` 页面展示；共同经济执行、真实恢复、Demo、paper、live 与 promotion 继续 `blocked`。**

最终修正 source `af7d1ba3222bc60fa44032ee70f63b8615248d45` 已闭合此前四项确定代码缺陷：初始与恢复共享 adapter-keyed data version；累计 ledger 以首次新增 fill/allocation 的精确 transition 定位原 UOW；当前真实不兼容 pair 的 proposal/review/start 在任何 transaction、持久化或 dispatch 前同步拒绝；已有 binding 的 review/start UI 同步检查 execution/protection compatibility。

这不等于真实共同交易通过。当前注册 Donchian 与 Qlib 的 t+1 / t+2 delayed-open 成交时钟和方向成本合同不兼容，100/200bps 与 400/800bps 的原保护 policy/hash 也不兼容；后端按 `cohort_member_execution_policy_incompatible` 在经济动作前拒绝。没有合格真实 Qlib final/positive-calibration 包，独立有效样本仍小于 30。因此 seam/mock-compatible tests 只证明合同与恢复算法，不证明两个真实成员已发生共同订单、成交、保护归属或经济恢复。

## 身份与交付校验

- approved base 与注册 main：`a78e5e112f564c1ceaf47c57fc3035542cd12562`；本独审结束时 main 未变化。
- producer source：`af7d1ba3222bc60fa44032ee70f63b8615248d45`；handoff commit：`5b0ecf9050ca0d99364f7271dd5eb25916878b9c`。
- producer handoff：`.agent/handoffs/BTC-COHORT-ENTRY-RECOVERY-CLOSEOUT-20261004/published-btc-cohort-entry-recovery-seam-correction-20261004-af7d1ba32.json`；Git blob raw SHA-256 `92bfb38117802d9e6c7b35e906aa30189979e9710ef0b7f125bbdf58da7b3796`；`handoff.py validate=valid`；7 个 deliverable Git blob SHA-256 全匹配。
- 固定长测 integration HEAD：`6d1fd20eedfa609c594199d3518cd4defd8aa8c8`。Git 证明 source 是该 HEAD 祖先；长测前后声明业务、测试与 handoff 路径均 clean，测试期间没有 commit、merge 或 source 变动。
- 初始相关路径 clean。首次消费原交付时独立测试文件出现 add/add 冲突，仅保留 producer 已消费的四项检查并追加 integrator 累计 ledger 正例；最终 af7 合入无冲突，未覆盖他人 dirty 文件。

## 四项独立源码核验

1. `quant_crypto/application/btc_registered_cohort.py:56,330` 与 `backend/app/services/candidate_offline_service.py:538` 使用同一 `cohort_data_version(donchian_input_digest=..., qlib_input_digest=...)`，不再以无键 members list 重算恢复身份。
2. `quant_crypto/application/btc_registered_cohort.py:685-851` 对相邻 ledger UOW 的 order/fill/allocation 做增量比较，只接受目标 fill 与相同 allocation plan 首次共同出现的 transition，并继续核验 member before/after、delta、order/fill identity 与时间；后续累计纯核账快照不再制造第二候选。
3. `backend/app/services/candidate_offline_service.py:175-181` 的当前 pair compatibility guard 在 proposal/review/start 的 authorize 与 identifier 校验后、transaction 和持久化前恒定拒绝；零 binding/job/cache/reservation 写入且零 dispatch。mock-compatible 管理生命周期测试显式 monkeypatch guard，只是管理 seam。
4. `frontend/src/workspaces/research/RegisteredCandidateRunControls.tsx:178-179` 的 existing proposed/approved binding review/start 按钮同时要求 execution/protection compatibility；不再只禁新 proposal。

## 独立验证

- `py -3 -m pytest tests/integrations/test_btc_cohort_entry_independent_acceptance.py tests/integrations/test_registered_cohort_recovery.py -q --tb=short`：`11 passed in 33.66s`。
- 定向运行 `tests/contracts/test_candidate_offline_access.py` 的真实 readonly allowlist/app factory、SSR/source flags、cohort identity/strict union、三段零写拒绝与 mock-compatible management seam 7 节点：`7 passed in 64.54s`。首次组合运行仅有 Windows GBK reader warning；以 `PYTHONUTF8=1` 单独重跑 SSR 节点：`1 passed in 6.12s`，无 warning。
- `node frontend/scripts/test-unified-candidate-offline.mjs`：exit 0，`unified candidate offline static contracts: ok`。
- service=None 公共 capability 实取 HTTP 200：`cohort_source_supported=true`；`deployed_configured/capability_enabled/offline_commands_enabled/offline_start_allowed=false`；blocker 为 `candidate_offline_not_configured`；未返回 compatibility true，UI 按 false 保持禁用。
- 原五个生命周期精确节点使用注册 main `.venv`、固定 integration HEAD 单次运行：`5 passed, 3 warnings in 1208.16s`。JUnit：`D:/codex-test-tmp/btc-cohort-final-long-6d1fd20e/junit.xml`，SHA-256 `13638dcdfa06a4ca173895c45c6fb9ceb122c2056623778edf1b528a21464cd2`，tests=5/failures=0/errors=0/skipped=0。三项 warning 均为 FastAPI/httpx 与 websockets deprecation。
- producer 提交态另有全量 candidate-offline 合同 `59 passed in 457.02s`、TypeScript Compiler API 117 source files/no diagnostics、`py_compile` exit 0、af7 scoped `git diff --check` exit 0；这些已由有效 handoff 固定，但不是本 integrator 重跑的 tsc。
- 旧 a1f 漂移长测 `3 passed, 2 failed` 只证明 `deployment_changed_restart_required`，不计本次最终结果。

## 只读页面与未运行项

- 本独立 worktree 未启动服务或 worktree 前端。正式浏览器验收必须在批准 source 合入 main、按现有唯一启动器重启后，从 `/research?view=run-details&qlibRun=m1-okx-qlib` 展开“准备部署交接”，验证“共同账户组合离线只读入口”。
- 该页面只允许公开 `GET /api/health` 与 `GET /api/candidate-offline/capabilities`；不得因卡片加载请求 `/api/strategy-delivery/*`、`/api/candidate-offline/catalog`、`/api/candidate-offline/jobs`，POST 必须为零，启动按钮永久 disabled。旧 main 的真实路径已由 root 只读预查可达，但旧页没有新卡片，不能算最终浏览器通过。
- 实际两真实成员非零共同订单、成交、保护归属和 post-ledger 恢复：`not_run`，因原执行/保护合同结构性不兼容而在经济动作前 fail-closed。
- 真实 LightGBM final/positive calibration：缺失；fixture/seam 不是真实候选或 promotion evidence。

## 修改、产物与职责边界

- integrator 自有改动：`tests/integrations/test_btc_cohort_entry_independent_acceptance.py` 的累计 UOW 正例；阶段拒绝报告、本最终报告及 append-only handoff。未修改 producer 生产算法、risk、OMS、ledger 或策略。
- producer source 只在本独立分支顺序消费；未合 main、未 push、未部署、未启动 backend/frontend。
- 无新 data/model/runtime artifact、manifest 或经济 ledger。JUnit 为固定 HEAD 测试证据，不是运行时账本或 promotion artifact。
- 未访问 network、secret、private/broker/order/live endpoint，未提交真实订单。

## 治理与安全状态

- playbooks：`AGENTS.md`、知识 README/硬规则、shared pitfalls、integrator playbook、delivery risk policy，以及 preflight/evidence/handoff skills。
- active pitfalls：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`；catalog SHA-256 `6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- gate 仍为 `blocks_gate`，`promotion_eligible=false`。限定只读 source/page approval 不改变该 gate。
- 保持 false：`candidate_management`、`offline_commands_enabled`、`offline_start_allowed`、`demo_control_enabled`、`execution_permission`、`runtime_observed`、`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、`withdraw`、`promotion_unlock_allowed`、`paper_or_live_unlock_allowed`、`real_order_submitted`。

下一步仅是 root 按既有授权审定限定 main 合入、rollback 准备、启动器重启与正式 `research_readonly` 浏览器验收；不得顺带启用管理、offline、账户、Demo、paper/live 或创建新的经济执行范围。
