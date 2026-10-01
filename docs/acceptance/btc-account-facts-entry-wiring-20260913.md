# BTC-ACCOUNT-FACTS-ENTRY-WIRING-20260913 验收

## 范围

- `change_risk=demo_execution_semantics`
- base `13fa72af3e3f7ee7912421118d9ca66b4160a51e`
- 三项入口：外部审定基线登记、完整 account bills 资金流覆盖、审定回撤阈值单位。
- 必要账本修订：按审定基线与本次观察时窗回放经济项，原始 snapshot/hash/UOW 与 PnL 公式不变。

## 离线证据

- 新入口合同与原账户/observer 基线合跑：`67 passed`。
- backend runtime service：`49 passed`，其中新增 2 项证明默认配置不读取 registry 且单位保持 `unknown`；完整批准才把 threshold/unit 注入 runtime 与 Guardian。
- backend artifact wiring/API：`23 passed`。
- 合并限定矩阵：`139 passed`。
- `py_compile` 与 CLI `--help` 通过；环境未安装 `ruff`，未运行该可选检查。
- 未调用网络、private/order/live endpoint；未读取 secret、真实 runtime state；未启动服务或 Demo。

覆盖的关键反例包括：body 自批准、账户范围未证明、长短对冲净零、挂单/algo/旧 intent、错误账户/HEAD/runtime/snapshot/time、过期快照、二次高水位重置、抵消 transfer、未知账单类型、分页缺失/重复、伪造 complete、缺失/未来经济时间。正例覆盖 append-only 登记、幂等、恢复，以及基线前手续费/资金费在首次、重试、重启后均不重复计入（权益 `100 -> 100`）。

## 工程状态与外部依赖

工程入口已接通并有离线合同证据，但真实账户尚未读取或审定。正式使用仍依赖：另行授权的只读账户全范围封存、独立人工批准、仓库外 registry、30 秒 freshness 内登记，以及随后完整分页资金流证据。任何一项缺失均保持 `unknown`/fail-closed。

本提交不是 Demo、paper 或 live readiness，不授予交易权限，不重建 promotion evidence。M1 exact-blob 冻结清单由独立 integrator 在审定最终 diff 后精确更新；producer 不自行批准自己的变更。

已知基线矩阵结果为 `60 passed / 5 failed`：其中 1 项是本票源码变更触发的 M1 exact-blob 审定清单，按交付政策留给独立 integrator；另 4 项是 base 已登记的旧 Guardian recovery fixture 缺少审定单位/账户事实，未在本票放宽或修复。
