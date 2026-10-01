# BTC 真实候选离线验收一次性交付合同

本合同只服务 `BTC-REAL-CANDIDATE-OFFLINE-ACCEPTANCE-GOVERNANCE-20260930`。它不改通用 risk policy、hook、启动器、认证或交易权限，也不允许 Demo、paper、private、order 或 live。

## 当前状态

`source_sealed=true`。业务 producer 已从审定的 handoff 修复基线 `ee42a967663d7bc306b4ac8b0d3c7d178f5b79cd` 机械复封干净 review source `4f730f54b34e3d2c2af7cc62e796058bc2fc3048`，并交付经验证的 append-only source handoff；合同仍封存相同的 14 个源码、9 个实际变更测试、10 个 feature runtime 文件、依赖版本与组合指纹。不得用 placeholder、未提交文件、他人 worktree 路径或自由填写的 hash 替换该 R。

最终封存由本合同的单一 owner 完成，仅接受：

- 已提交的业务审查源 R 与 source base；合同不内嵌尚未产生的 S，避免 Git commit 自引用；
- 实际 R diff 的精确 path/blob/mode/SHA-256/classification；14 个源码+10 个测试是 allowlist 上限，不是必改数；新增范围仅为 `app_factory.py`、`candidate_delivery_bootstrap.py` 与 `test_qlib_pipeline.py` 的外部只读研究目录接线；
- 8 个运行 primitive 对应的固定实现文件 inventory/指纹，以及 Python 3.11.15、numpy 2.4.6、pandas 3.0.4、lightgbm 4.7.0、qlib 0.9.7 的精确依赖指纹；
- 经 `handoff.py` 验证且 `deliverable_commit=R` 的 append-only source handoff，并固定业务 ticket prefix、`btc_developer`、`btc`、`published` 身份；
- 明确 readiness class 与 blockers，其中 `promotion_eligible` 始终为 false。

## 两阶段边界

### `source_review`

合同先封 R 上的代码/测试、固定实现 inventory/指纹和 source handoff。集成形成生产基线 S 后，由 post-S 只读 source-review 提交 Q 记录 S、R→S 精确 preparation inventory 和真实 runtime 依赖回执。Q 必须是 S 的后代，但不进入 S，也不要求成为后续运行 F 的祖先。它明确允许：

- 尚未实际 fit；
- 尚未产生真实 candidate 或校准参数；
- 尚无 catalog/account/input 最终绑定；
- 尚未启动或恢复离线 run。

这些“未运行”不是源码不可交付。源码阶段不得要求真实 fit receipt 或业务 run 通过；只要 R、source handoff、S preparation inventory、真实依赖指纹、数据 manifest 和独审均为提交态即可通过 source review。

### `deployment_acceptance`

部署阶段允许 `S != F`，但必须证明：

- R 是 S 的审定祖先，S 是冻结运行基线 F 的审定祖先；
- R 的实际受审 inventory 在 S/F 上 blob/mode/SHA-256 不变；
- feature、dependency 和 combined 指纹不变；
- `consumer_commit=execution_commit=F`；
- candidate/catalog/account/input 的 version 和 SHA-256 在登记前冻结；
- source review Q 位于 S 之后；运行证据、campaign/ledger/page/deployment 报告位于 F 之后的独立只读验收提交 A，要求 `F ancestor A`，A 不合 main；
- S→F 只允许本票 source-review/identity 元数据与精确 handoff 命名空间；不得在 F 夹带任意源码、治理文件或数据准备文件。pre-run blocked 的 campaign 分支同样只允许证据增量；
- 只有合同精确列出的 governance/review/campaign evidence/identity/handoff 路径可作为 evidence delta，不得泛放 `.agent/` 或夹带业务代码。

F 不必须等于 S，也不得因登记索引、审查报告或 handoff 而重训候选。Q 不需要成为 F 的祖先；A 不得为了把事后证据塞回 F 而改写运行基线。

## 唯一 campaign 与 fit 预算

campaign 固定为 `btc-real-candidate-offline-acceptance-20260930`，不得 template/genetic、换模型、换 seed、换窗口或追加第六次 fit。

- 4 折筛选；通过后最多 1 次 final-audit fit；业务 outcome=`passed` 时 4 折与 final-audit 五个实际 fit 均必须成功；
- failed/crashed 的 fit 同样占用序号和预算；
- 总数最多 5，恢复不能清零；
- 筛选失败不得出现 final-audit fit；
- 校准失败可保留已消耗的 fit，但不得登记或运行候选。

`blocked_screening`、`blocked_calibration` 或输入完整性失败可交付结构化 blocked report。校验器会验证其真实性，然后仍返回 `business_acceptance_not_passed:<outcome>`；“报告可验证”不等于“业务验收通过”，也不要求重训来消除自然失败。

## 离线运行与时间语义

仅 `passed` 允许声称：

- 1 个正式 run ID；
- 固定 48 个决策小时；
- 6 个已核验资金费事件；
- 请求目标是第 24 个已提交事件，但回执记录“不早于 24 且早于 48”的首个真实安全内部 checkpoint；不得为凑 24 改账、重跑或按 PnL 挑点；
- 实际 checkpoint path/hash；
- 同 task 恢复至固定终点；
- 重复启动无第二 writer，恢复无重复经济记账。

本轮只是真实分钟数据的离散采样工程验收。receipt 必须明确 `minute_sampling_only=true`、`tick_path_verified=false`、`exact_exchange_settlement_verified=false`。不得把分钟 close/mark/index 观察写成逐笔路径或交易所精确结算。

## 临时能力与最终归位

业务验收过程分两个必须显式报告的 runtime stage：

1. `temporary_offline_acceptance`：仅 loopback，`candidate_management` + `local_no_password`，允许本次 management write/offline task/offline worker。
2. `restored_after_acceptance`：恢复 `research_readonly`，关闭 management write、offline task 和 offline worker；保留既有认证配置，不强制改成 `key`，也不新增密码步骤。

若在筛选、校准或输入完整性阶段已阻断，temporary stage 必须是 `not_started`，不得为“便于报告”假填启用。

deployment checks 使用 `passed|blocked|not_run`。只有业务 outcome=`passed` 时所有 deployment checks 才能为 `passed`；blocked report 必须保留真实 `blocked/not_run`，不得补写停止/恢复/ledger/页面已验证。

fit、candidate/package、catalog/account/input、run/checkpoint/ledger 不由 receipt 布尔值或任意 hash 自证；campaign manifest 中每一项必须给出既有 task-owned artifact 的 logical path、immutable revision、schema、content SHA-256 和 seal SHA-256，并与 receipt 逐字段交叉核对。fit 指向既有 `fit_budget.json`，四 binding 指向 `candidate_offline_job_identity_v1`，checkpoint/run/ledger 指向既有 state/seal/run-seal/ledger reconciliation 证据，不新增平行平台。source/integration/deployment review 同样使用结构化 decision/blockers/not_run，不接受任意文件 hash 代替审查结论。

temporary 的 `offline_worker_enabled=true` 只表示本次已封存输入的单写者离线任务，不等于交易权限。两个 stage 都必须独立证明 Demo、promotion、paper、private、order、live、broker/exchange access 等旗标为 literal false；缺字段不得推定为 false。

## 只读命令

```powershell
py -3 -B -X utf8 tools/agent_governance/btc_real_candidate_offline_acceptance_delivery_20260930.py --repo-root . inspect-contract
py -3 -B -X utf8 tools/agent_governance/btc_real_candidate_offline_acceptance_delivery_20260930.py --repo-root . validate-source
py -3 -B -X utf8 tools/agent_governance/btc_real_candidate_offline_acceptance_delivery_20260930.py --repo-root . validate-receipt --input <receipt.json>
```

命令不遍历全仓历史 handoff，只读取合同明确列出的 source handoff、review report 和本票 handoff prefix。
