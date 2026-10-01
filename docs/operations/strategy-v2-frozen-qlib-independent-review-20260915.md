# V2 冻结 Qlib 推理独立验收

## 结论

- 票据：`STRATEGY-V2-FROZEN-QLIB-INTEGRATION-20260915`
- 审定基线：`a315f1169d9b628e9a4acd70100f188076c32560`
- 变更风险：`demo_execution_semantics`
- 最终上游 source：`c8a8c8d7d063d53ba81cf210f17a32ed43de633f`
- 最终上游 handoff HEAD：`2e5128751f626c672bea4b1264bcab1a702fbd13`
- 独立审查：`source_contract=passed`，`readiness_class=quality_checked`。

最终候选在独立 sparse 集成工作树中通过：它能从固定 Git manifest 和不可变 shared-data 归档重建封存 `m1-okx-qlib` 的 13 列 Qlib float32 特征，复现 1,392 条原始预测和固定校准。这只证明“特征→预测→冻结校准”的离线源码合同一致，不证明 Alpha 有效、仓位/退出一致、Demo 或交易权限就绪。

## 变更边界

最终 source 仅涉及四个审定路径：

- `integrations/qlib_adapter/frozen_inference.py`：封存包解析、Qlib 特征加载、固定模型推理、校准和证据绑定。
- `tests/integrations/test_qlib_frozen_inference.py`：真实封存归档、特征/预测对照、prefix/未来扰动和 fail-closed 负例。
- `tests/fixtures/strategy_v2/contract.json`：精确 run、数据、模型、特征顺序、校准、时间和权限合同。
- `docs/architecture/strategy-admission-v2.md`：V2 范围、验收证据和局限。

未修改 V0/V1、训练入口、策略、Portfolio/Risk、OMS、成交/账本、共享合同、治理、启动器、API 或 UI。上游两个 append-only handoff 均保留，修正 event 显式 supersede 初版 event。初始限定 source 路径 clean；集成无冲突，未覆盖其他代理修改。

## 独立核验

1. 上游 handoff 以 `tools/agent_governance/handoff.py validate` 对提交对象校验为 `valid`；base ancestry、交付 hash、精确 touch set 和 `git diff --check` 通过。
2. 初版独审复现两个缺口：`HEAD:` manifest 被接受；`clip_fraction=0.5` 仍返回 1,392 行，最大绝对校准值仅 `0.0011495290234579962`，未碰到 clip 而掩盖配置漂移。
3. 最终修正要求 manifest 使用 40 位小写提交 SHA；`HEAD/main/分支/标签` 均拒绝。`clip_fraction=0.05` 由 V0 不可变 Git blob 和 blob SHA-256 独立绑定。
4. 源码入口无 `fit`、搜参、MLflow 写入、归档写入、研究账本写入或执行对象构造。标签和 `DropnaLabel` 只用于验证封存配置，不进入推理。
5. Qlib datetime 是 bar open；可用/决策时间为 `event+1h`，研究 2-bar 事件时间为 `event+2h`。`Fillna(feature)` 仅处理 NaN，Inf 在处理后 fail-closed。

### 独立测试

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:MLFLOW_DISABLE_AGENT_HINT='1'
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v2-integrator-final-v2-20260915" tests/integrations/test_qlib_frozen_inference.py
```

结果：`28 passed in 45.30s`，无 skip。包含真实封存 provider、1,392 条特征/原始预测/校准预测、batch/逐行、prefix、未来 provider 扰动、列顺序、身份、不可变 Git 引用、clip 和非有限值负例。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:QS_V0_VERIFY_ARCHIVE='1'; $env:MLFLOW_DISABLE_AGENT_HINT='1'
& 'D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider --tb=short --basetemp "$env:LOCALAPPDATA\Temp\v2-integrator-final-compat-20260915" tests/contracts/test_strategy_v0_freeze.py::test_exact_qlib_archive_and_model_are_frozen tests/contracts/test_strategy_v1_donchian_offline.py::test_continuous_open_hold_reverse_reopen_exit_is_economically_replayable tests/contracts/test_strategy_v1_donchian_offline.py::test_identity_input_and_time_mismatches_fail_before_new_order tests/contracts/test_strategy_v1_donchian_offline.py::test_evidence_v2_binds_input_and_v1_remains_readable_but_not_v1_qualified
```

结果：`4 passed in 89.45s`。覆盖 V0 精确归档/模型身份，以及 V1 主线经济回放、错身份/时间拒绝、证据版本可读边界。

在未合入 V2 的纯基线 `a315f116...` 运行旧 M1 静态白名单测试，结果为 `1 failed in 4.99s`；首个差异是已审 V1 `quant_crypto/application/donchian_offline_replay.py` 未被旧名单登记。这是 V2 之前的继承失败，本轮未修改白名单/金标；因此结论是“V2 未新增该回归”，不是“全套全绿”。

## 限制和未运行项

- 归档没有独立的 13 列历史特征矩阵。特征通过的含义是：从同一已逐文件 hash 验证的 float32 provider，用逐字冻结表达式/列序/Fillna 重建，并与 1,392 条封存原始预测零误差。
- prefix 通过 Qlib `end_time` 限制可见截止，并物理改写未来 provider 证明过去不变；没有对 1,392 个时点各自删除全部未来文件再重跑。
- `qlib.init` 会改变进程内 Qlib 全局状态；当前合格形态是隔离离线进程，不是可并发嵌入长驻服务的 predictor。
- 上游初版兼容命令曾运行两个 synthetic Qlib fit，并在 pytest 临时目录写入合成 MLflow/模型/预测/研究决策/研究账本。它们没有重训 `m1-okx-qlib`、没修改封存归档或原账本；修正后和本独审都未重跑这两个训练例。
- 未运行：模型训练/搜参、仓位/退出一致性、Portfolio/Risk、OMS、成交/持久账本、服务/API/UI、实际账户、OKX Demo、private/order/live、主版本发布和 V3。
- 未生成新 artifact/manifest/ledger；消费的是既有 shared-data `m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911`，aggregate `593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde`。
- 注册主分支仍为 `b920d131e41ecbfe7f76f0709affbe22c8b35f5e`；本轮仅隔离集成，尚未合入 main。

## 治理证据和安全状态

- 已读：`quant-agent-preflight`、`quant-agent-handoff`、`quant-gate-evidence-review`，integrator playbook、共享踩坑、金融机器学习验证、领域架构和审计链规则。
- active pitfall IDs：`GOV-CONCURRENCY-001`、`GOV-DIRTY-001`、`GOV-HANDOFF-001`、`GOV-ROOT-001`、`GOV-STORAGE-001`、`GOV-WORKTREE-001`、`GOV-PROMPT-001`、`GOV-WINDOWS-001`。
- catalog hash：`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。
- `promotion_eligible=false`；`promotion/paper/live/private/order/real_order/transfer/withdraw/execution_permission/runtime_observed` 全部保持 `false`。
- 本次集成不授予 Demo/paper/live，不构成 promotion evidence，不自动启动 V3。
