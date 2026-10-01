# BTC 账户事实入口操作说明

本入口只登记经外部人工审定的 BTC Demo 账户基线，并把完整资金流证据和回撤单位接入既有 Guardian。它不启动 Demo、不授予交易权限，也不把“摘要哈希”当作批准。

## 前置证据

1. 通过既有、另行授权的 private-readonly 流程封存同一时点的账户配置、USDT 权益和 BTC 运行快照。现有运行快照的仓位与挂单查询按 BTC instrument 过滤，**不能单独证明整个交易账户为空仓**；人工审定材料还必须覆盖 dedicated trading account 的全部仓位、普通挂单、算法单和未完成 intent。
2. 在仓库外建立服务端持有的批准注册表。批准记录必须绑定账户哈希、账户范围、币种、source HEAD、稳定 runtime identity、封存快照哈希、观察时间、权益、账户全范围空仓证据，以及明确的 `usdt` 或 `ratio` 回撤阈值。`approval_digest` 只校验记录未被改写，不代表批准。
3. 封存快照必须在观察后 30 秒内完成审定和登记；不得为了通过 freshness 修改观察时间。过期快照只能保留为历史材料，本入口会拒绝登记，不能成为实时 risk fact。

## 服务端配置与登记

仅在人工批准完成后，由服务端固定以下配置：

- `QS_BTC_DEMO_RUNTIME_IDENTITY`
- `QS_BTC_DEMO_ACCOUNT_FACTS_APPROVAL_REGISTRY`：仓库外 JSON 注册表的绝对路径
- `QS_BTC_DEMO_ACCOUNT_FACTS_APPROVAL_ID`

运行时必须已停止且没有另一 writer。登记命令只接收批准 ID 和封存快照，不接收自填 authority、complete 或审定回执：

```powershell
py -3 -B -X utf8 scripts/register_btc_account_facts_baseline.py `
  --approval-id <server-configured-approval-id> `
  --sealed-snapshot <sealed-snapshot.json>
```

成功后，既有 `BTCRuntimeStore` 以持锁、append-only UOW 写入 `account_drawdown_baseline_registered`，再写 checkpoint。重复同一批准与同一快照幂等；任何新基线重置均拒绝。登记不会启动 worker、清除 latch、允许 opening 或改变 private/order/live 旗标。

## 后续资金流覆盖

本票只把 account bills provider 接入 `OkxDemoPaperRuntimeController._collect_exchange_snapshot`。既有独立 private-readonly observer 未修改，不能产出本票要求的账户全范围审定材料，也不会向生产账本写入这些事实。只有未来另行授权并实际启动 production Demo runtime 的私有读取链，才会通过该 controller 快照入口调用 provider：

- `GET /api/v5/account/bills`；不按 instrument、type 或 currency 过滤；
- `begin/end/limit=100`，按 OKX newest-first 结果用 `after` 向更早 billId 翻页；
- 满 100 行必须继续请求，直到取得短页或空页；重复 ID、cursor 不前进、缺页、未知类型、币种不符、时间缺失、超过七天可证窗口均为 `unknown`；
- transfer `type=1/subType=11|12` 即使净额为零也阻断；当前白名单只接受普通 trade `type=2/subType=1..6` 与 funding `type=8/subType=173|174`，其他事件先保持未知；
- 完整证据仅表示“从已审定基线到本次观察没有外部资金流”，不表示历史全覆盖。

`evidence_digest` 仅把 validator 收到的字段做完整性绑定，调用方自行重算 digest 并不构成来源证明。完整分页事实的 provenance 边界是服务端固定注入的 collector/provider，以及它与当前 runtime snapshot、账户、覆盖起止时间的精确绑定；HTTP/body 不能选择或替换该 provider。

账本回放保留原始 snapshot/hash/UOW，不删除交易所返回的历史行；计算时只计入严格晚于基线且不晚于本次观察的 fill/funding，避免基线权益已包含的费用和资金费被重复计算。

依据：OKX 官方 [Get bills details (last 7 days)](https://www.okx.com/docs-v5/en/) 与 [Pagination](https://www.okx.com/docs-v5/trick_en/#pagination)。本票不访问这些私有端点；只实现 provider 接线和离线 fake 回归。

## 当前限制

- 当前没有真实账户批准注册表、封存快照或资金流页，未登记任何真实基线。
- 现有 private-readonly observer 的健康快照不是账户全范围经济对账证明。
- 本票没有启用 Demo、paper、private/order/live，也没有生成 promotion artifact。
- registry 未配置、批准不完整、快照过期、现金流证据不完整或回撤单位未知时继续 fail-closed。
