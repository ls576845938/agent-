# Donchian 历史评估入口与固定窗口基线

票据 `BTC-DONCHIAN-HISTORY-SPEC-20260920`。本轮已完成入口源码独审、一周兼容及一次冻结的20天探索性历史评估；独立集成另记，未正式发布。**十二个月数据目标尚未满足，不能宣布长达一年的业务基线完成，也不能据此判断策略有效。**

## 事前边界

- 用户批准原计划：入口规格化、固定历史评估、精确证据与架构状态修正；不调策略、参数、仓位、退出，不训练或搜索，不自动进入 M3/M4、Demo/paper/live。
- base/main：`e2e7496acaa16b9fd5eda37dd65ea328a18ab032`。
- 上游历史适配器：`fa41914d52c994b3faf0155e8e68ca98d3b757ff`，独立交付 `integrated-btc-donchian-history-correction-independent-review-20260916-6d607cff1` 本轮 validate=valid。
- role=btc_developer（用户主会话）；源码 change_risk=demo_execution_semantics，仅表示独立审查强度，不授权 Demo 部署。
- planner sparse worktree：`agent/btc_developer/donchian-history-spec-20260920`；初始限定 dirty=[]。
- touch set：历史 replay/venue/spec、原离线 replay 的注入与末期编排、既有历史 CLI、两个历史合同测试、本文及同名 JSON 规格、架构 STRATEGY-DELIVERY-STATUS/mindmap 和对应静态测试、本票 append-only handoff。不得改生产 Risk/OMS/ledger/保护/权限、治理或启动器。
- 现有数据先做来源与覆盖核验，收益不可用于选窗。目标连续十二个月另加足够预热；实际不足就报告缺口，不冒充十二个月。新数据只允许既有 OKX 公共入口，不读账户或凭证。
- 一份配置、一个实际历史运行；恢复是同一运行。不因无交易、负收益或资料缺失自动扩窗搜参。
- 先实现/测试，再冻结源码和精确数据规格，随后运行；独立复核后才判断是否具备限定交付条件。
- 末期非零经济变化必须从既有 BTC 权威账本确认。若正确输入仍需修改生产合同，停下报告并单独申请，不修改规则迁就模拟器。

## 起始证据

磁盘 D 28.65 GiB（超过 20 GiB 门槛，仍禁止 full checkout）；原历史测试先移入主版本候选后 collection 失败：历史 venue 尚不存在。随后按已审 Git 对象导入适配器，不整支覆盖旧分支。

数据、源码、测试与结果记录将在本轮完成时追加。所有交易、安全授权和 runtime_observed 均保持 false。本报告不是 promotion evidence。

## 数据准入与事前冻结（未查看新窗口收益）

2026-09-21 校验既有 manifest 与全部文件 hash：原 OKX 输入日内行情 5,280 根，范围 2025-12-22 00:00 至 2026-07-29 23:00 UTC；mark/premium 各 5,302 根且小时连续。资金费 276 个八小时结算记录，2026-04-29 16:00 至 2026-07-30 08:00 UTC。无重复时间戳。数据入口还须逐行验证品种、来源 ID、OHLC 边界、完整小时、确认位、可见时间及结算覆盖，不能只相信 manifest 的 readiness。

通过既有 `OkxSwapPublicCollector` 仅查询公共资金费：最新 3 条为 2026-09-20 的 00/08/16 UTC；以 2025-09-21 为边界的查询 code=0、0 条。只证明该查询没有返回一年以前的记录，不断言整个 OKX 历史库不存在；本票不另建历史归档采集器。补后续公共行情仍不能补上缺失的一年资金费。两次查询未创建数据版本、未访问账户或凭证。

本轮固定的可执行替代区间为 **2026-07-10 00:00 至 2026-07-30 00:00 UTC（右开，共 480 小时／20 天）**；预热 2025-12-22 至 2026-07-10，共 200 个完整 UTC 日、4,800 小时。这是既有不可变输入满足预热后的连续最大区间，未依据收益或成交选择。十二个月目标仍缺资料，不能把本次叫作一年评估。旧样本已有研究使用记录，结论仅为探索性历史证据。

不可变规格为同目录 `donchian-history-spec-20260920.json`；运行只接受精确 Git 提交引用，身份绑定规格 hash、文件 hash、源码 HEAD 和全部原策略参数。初始 5,000 USDT、固定 0.01 合约＝0.0001 BTC、手续费 5 bps、半价差 0.5 bps、无盘口时一张合约深度假设保持显式。运行预算一份规格、一段区间、最多一次实验；中断恢复不换窗口，歧义／账本不符即停。

## 集中实现与保护验证

- 复用现有 Qlib 输入校验器（只校验数据，不加载模型、不训练）；新增历史规格，不修改通用决策合同。
- 原历史适配器仅接受 `limit`，而当前原 OMS 发出 `fok` 开仓／`ioc` 减仓，真实原信号测试明确复现拒单。只修历史适配器承接这两种可立即成交的限价指令；数量超过固定模拟深度仍拒绝，不改生产下单或风险逻辑。
- 末期没有下一根行情仍不生成订单；已经发生的保护成交、资金费、持仓估值由原 controller 的 ledger reconciliation 确认。非零持仓、保护成交、提交账本后缺证恢复均独立测试，未改生产 ledger。
- 历史事件输入指纹补齐指数、资金费和可见时间；重复同一事件的不同输入拒绝。Blocked 运行不自动重试；必须报告断点。
- 已完成：原历史 13 项；规格／末期第一批 27 项；保留原 V1 11 项（合并初次 45 passed，后续新增测试另报）。地图 3 项静态渲染测试通过。测试数量是覆盖索引，不作为历史策略有效性的证据。

## 交付边界与已知限制

本轮未修改策略、参数、原目标仓位、风险、OMS、生产保护、账本、权限、治理或启动器。V3 结项状态修正在候选地图中，正式验收结论引用 `78aaa489214c24f00e076eae0e11ec9089f2f544` 的最终报告，而非旧的发布前快照。

本票源码已通过下述限定独审；尚未合入 main 或发布页面。现有 V1/V3 只读交付条款绑定各自票据，不能借用其专属收据，也不为本票切换 Demo 部署或自动修改治理规则。回退基线为 main `e2e7496acaa16b9fd5eda37dd65ea328a18ab032`，本票所有源码在独立 sparse 分支；未移动 main，当前可用系统不受影响。

Playbook：shared_pitfalls、btc_developer_pitfalls、data_steward_pitfalls；补读研究、执行、资金费、回放及安全知识规则。catalog hash=`6ea783731473604875c962acc6338fd868f95b13e2230d62254ef79c0a67f3af`。active IDs：GOV-CONCURRENCY/DIRTY/HANDOFF/ROOT/STORAGE/WORKTREE/OBJECTIVE/ENGINEERING-CIRCUIT/PROMPT/WINDOWS，BACKTEST-COST-001、BTC-NONFLAT-001、BTC-OMS-001、BTC-PERP-001、BTC-WS-001、DATA-BTC-FINAL-001、MONITOR-AUDIT-001、QSYS-GATE-001、QSYS-SECURITY-001、REPLAY-ISOLATION-001、RESEARCH-HOLDOUT-001。

初始 dirty=[]；未覆盖他人文件。`promotion/demo/paper/live/private/order/real_order/transfer/withdraw/runtime_observed=false`。公开数据核验发生过网络请求；离线执行本身禁止网络，不能把二者的 network 标记混为一谈。

## 冻结提交与独立审查

- 源码 deliverable：`e6643e67b2f4dccfe2b092a6e199571869669a3c`；handoff commit：`08344692956ef9646763287711a94ea95a49534f`；handoff `history-spec-candidate-e6643e67b` validate=valid。两者源码对象完全相同，后者仅增加交接事件。
- 实验使用 `08344692956ef9646763287711a94ea95a49534f` 的独立工作树；规格精确引用 `e6643e67b2f4dccfe2b092a6e199571869669a3c:docs/research/donchian-history-spec-20260920.json`，规格内容摘要 `500d15334f0f06a8e9ea61240f5a80c63cf9e179d4a76c48cc525e03d06aa886`。
- 独立只读审查 `/root/history_spec_independent_review`：有限源码审查通过，无直接阻断这次冻结实验的 P1/P2。审查方从 Git 对象导出限定源码，独立历史合同测试 **45 passed in 9.79s**；导出 archive SHA256=`81ab4264750214d47bbe72ba7a98e8f81ef8bde012936bc66d09bee77cc25545`。
- 独审上限仅 `quality_checked/research_only`；未运行实际历史实验、未独立重跑真实数据 check-data、原 V1、地图或浏览器；未访问网络/账户/交易。独立集成与正式发布不是这次只读审查已经做完的事。
- 主会话冻结前数据准入：**480 评估小时 + 4,800 预热小时 + 60 资金费结算，通过**。新增合同与历史合同合计 45 passed；原 V1 11 passed；V0 23 passed / 1 skipped，跳过项为显式 opt-in 的 Qlib 归档核验，本 Donchian 任务不启用。地图静态渲染 3 passed。
- 原策略 registry/研究、portfolio/risk/OMS/runtime/quant_shared、V1 测试和 fixture、Qlib 校验器、治理和启动器与 main 基线对象相同，限定 diff 核查 exit=0。

## 固定入口与停止／恢复

以下命令只在本票据独立工作树、上述固定执行 HEAD 使用；先检查 HEAD 和相关源码无 dirty。不会启动前后端或任何交易 worker。

```powershell
# 只校验数据，不计算策略收益，不创建运行状态。
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B scripts/run_btc_donchian_history.py check-data --spec-git e6643e67b2f4dccfe2b092a6e199571869669a3c:docs/research/donchian-history-spec-20260920.json
# 新实验；最多处理240个事件后干净停止，形成同一次实验的断点。
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B scripts/run_btc_donchian_history.py run --output-root 'D:/vibe coding/Obsidian/量化系统/offline-runs/history-spec-acceptance-20260921' --run-id donchian-fixed-history-20260921 --spec-git e6643e67b2f4dccfe2b092a6e199571869669a3c:docs/research/donchian-history-spec-20260920.json --max-events 240
# 只在前一进程已退出、单写锁释放后恢复；不得改配置或源码HEAD。
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B scripts/run_btc_donchian_history.py resume --output-root 'D:/vibe coding/Obsidian/量化系统/offline-runs/history-spec-acceptance-20260921' --run-id donchian-fixed-history-20260921 --spec-git e6643e67b2f4dccfe2b092a6e199571869669a3c:docs/research/donchian-history-spec-20260920.json
# 状态读取不下单、不恢复、不重算；Windows下建议在写进程退出后读取。
& 'D:/vibe coding/Obsidian/量化系统/agent-/.venv/Scripts/python.exe' -B scripts/run_btc_donchian_history.py status --output-root 'D:/vibe coding/Obsidian/量化系统/offline-runs/history-spec-acceptance-20260921' --run-id donchian-fixed-history-20260921
```

`--max-events` 是干净停止边界；若 OS 强杀留下 writer.lock，不盲目删锁/自动重试，应先确认进程归属和持久状态。`blocked` 结果不自动继续。运行中不要用不允许共享删除的 Windows 文件读取方式抢读正被原子替换的结果文件。

一周兼容验证沿用旧默认规格，独立 run_id=`history-week-compat-20260921`，不是新增研究实验。并发读取结果文件期间发生一次原子替换 WinError 5，与 Windows 共享冲突一致，但未做 OS 句柄级根因复现；已停止该读法，用同 run 恢复至84事件。不因瞬时环境问题修改生产代码。必要的进度读取改用允许 ReadWrite/Delete 共享的短生命周期只读句柄，不阻挡原子替换。后续完整结果、重复/恢复及账本复核另记于下。

## 原一周兼容与恢复结果

run=`history-week-compat-20260921`，执行 HEAD=`08344692956ef9646763287711a94ea95a49534f`。结果 complete、blockers=[]：168 小时、168 阶段（167 hold + 1 末期观察）、方向决策/订单/成交均为 0；现金及权益均 5,000 USDT，持仓、价格盈亏、手续费、资金费现金流均为 0。与原报告 `9653bf7e0540c661514ba375c34c3486225b80b3:docs/research/donchian-historical-baseline-20260920.json` 的业务结果一致，不把空仓兼容当作非零链路验收。

原 `BTCRuntimeStore.recover()` 验证 840 个哈希链事件、168 个 ledger UOW，无恢复 blocker、无重复幂等键；最终 `account_ledger_replay` 为 reconciled，21 个资金费观察全部入账（旧结果只有20个，缺少最后零现金流账单）。末期证据精确关联最后账本事件 hash。完成后再执行只读 status 和相同身份的 resume，以下五个文件逐字节 hash 不变：

| 文件（相对本 run 根目录） | SHA-256 |
|---|---|
| historical_replay.json | `557c16ae41d9035fb534d801cf8779049ed27d7d5b9aca411cd67c836d7bdfa9` |
| historical_identity.json | `86f1d9867a353805c0e6f5c8e21418794805284b1bab190be6ea48908d5db1ed` |
| state/offline_venue.json | `d519102c4da1c08a5d16fe5c15adce365d37181b8058ff2205aa320cd0cfd19e` |
| state/runtime/events.jsonl | `9ee7d1056d7af22f0b95595a519d86fc14ac500791aeaa1562c44e5138d63bff` |
| state/runtime/state.json | `0beb292c547f7459a634acfd5e2223c7e10bcb3b6b800c586e57afde36e3b52b` |

上述产物位于 `D:/vibe coding/Obsidian/量化系统/offline-runs/history-spec-acceptance-20260921/history-week-compat-20260921`，不是 main 当前版本的生产证据。

## 固定20天历史结果与逐账复核

- run=`donchian-fixed-history-20260921`；执行 HEAD=`08344692956ef9646763287711a94ea95a49534f`。480小时完整完成，blockers=[]。第240小时正常停止并退出，随后在相同 HEAD/规格/数据下恢复到480；这仍是同一次实验。
- 原信号输出480次 flat，479个正常 hold 阶段，最后1个 no_next_bar 观察。方向信号、多头/空头交易、订单、成交均为0；不是已有方向信号被交易权限或风控拒绝。
- 初始与末期现金/权益均为5,000 USDT，持仓为0。价格盈亏（已实现及未实现）、手续费、资金费现金流均为0；账户收益率0%，逐小时账本权益最大回撤0%。**全程空仓不是盈利或低风险能力的证明。**
- UTC固定自然周分段：2026-W28为72小时，W29为168小时，W30为168小时，W31为72小时；四段方向信号和净盈亏均为0。不能据此声称跨阶段稳健。
- 没有成交样本，胜率、盈亏比、单笔/单位名义敞口收益、盈利贡献集中度及 Sharpe 均不估计，标记为不适用。0.01合约=0.0001 BTC 的原目标没有放大。
- 原 `BTCRuntimeStore.recover()` 验证2,399个哈希链事件、480个 ledger UOW，无截断或恢复 blocker，幂等键唯一。最终权威 `account_ledger_replay` 核对全部60笔资金费观察、0笔成交、0持仓与5,000权益，状态 reconciled。账单有观察、现金流为0，不能写成“没有资金费记录”。
- 每个小时按其决策时间对应账本观察，480条权益和持仓均一致；末期证据以账本事件ID及hash精确关联。无成交阶段的订单/成交引用保持空，不补造关联。
- 完成后再执行原CLI的 `status` 与同身份 `resume`：全部9个运行文件的内容及文件集合不变。文件索引摘要算法为相对路径→文件SHA256映射按key排序的紧凑JSON，再做SHA256；摘要及关键文件hash见下。
- 原一周实际恢复与本次240小时断点均已验证；完整20天未额外运行第二次无中断实验，不能把此项写成已做完整双跑对照。连续/断点行为等价继续引用冻结的V1/历史合同测试；本次实际运行补证断点恢复和完成后幂等。
- 未发生保护路径歧义；由于0成交，真实区间本身没有覆盖非零订单/保护/成本过程。这些工程行为依赖已保留的V1及新增明确标注的测试场景，不混作真实历史成交。

产物根目录：`D:/vibe coding/Obsidian/量化系统/offline-runs/history-spec-acceptance-20260921/donchian-fixed-history-20260921`。运行输入通过固定manifest读取，状态与账本在仓库外专属目录。归档报告提交与实际执行提交必须区分：以下是 **083446929 的冻结研究产物**，不得重标为后来 HEAD 或生产 BTC 运行证据。

```json
{
  "status": "passed",
  "execution_head": "08344692956ef9646763287711a94ea95a49534f",
  "spec_digest": "500d15334f0f06a8e9ea61240f5a80c63cf9e179d4a76c48cc525e03d06aa886",
  "counts": {
    "blockers": 0,
    "decision_phases": 480,
    "directional_signal_decisions": 0,
    "fills": 0,
    "funding_bill_observations": 60,
    "hold_decisions": 479,
    "nonzero_funding_cashflow_bills": 0,
    "order_terminal_decisions": 0,
    "orders": 0,
    "processed_events": 480
  },
  "marked_state": {
    "average_price": "0",
    "cash_usdt": "5000",
    "equity_usdt": "5000",
    "fees_usdt": "0",
    "funding_usdt": "0",
    "position_contracts": "0",
    "realized_pnl_usdt": "0",
    "terminal_liquidation": false,
    "unrealized_pnl_usdt": "0"
  },
  "ledger_event_count": 2399,
  "ledger_uows": 480,
  "final_ledger_replay": {
    "baseline_observed_at_utc": "2026-07-10T00:59:58Z",
    "blockers": [],
    "contract_value_btc": "0.01",
    "currency": "USDT",
    "fee_cashflow_usdt": "0",
    "fill_count": 0,
    "final_equity_usdt": "5000",
    "final_observed_at_utc": "2026-07-30T00:00:01.479000Z",
    "funding_bill_count": 60,
    "funding_cashflow_usdt": "0",
    "observed_equity_usdt": "5000",
    "position_btc": "0",
    "position_contracts": "0",
    "price_pnl_usdt": "0",
    "reconciled": true,
    "schema_version": "btc_account_ledger_replay_v1",
    "source": "committed_ledger_uow_payloads_plus_independent_final_snapshot",
    "status": "reconciled"
  },
  "exact_ledger_links": 1,
  "terminal_exact_ledger_link": true,
  "all_480_hourly_equities_and_positions_match_ledger": true,
  "idempotency_unique": true,
  "status_and_completed_resume_all_files_unchanged": true,
  "hashed_file_count": 9,
  "all_files_index_digest": "2adcc3d283306507da9f619c38a1e4974aa22acb65f658a4d8297e4e51852295",
  "phase_counts": {
    "hold": 479,
    "no_next_bar": 1
  },
  "signal_directions": {
    "flat": 480
  },
  "account_return": "0",
  "hourly_account_max_drawdown_ratio": "0",
  "fixed_calendar_segments": [
    {
      "utc_iso_week": "2026-W28",
      "hours": 72,
      "net_pnl_usdt": "0",
      "directional_phases": 0
    },
    {
      "utc_iso_week": "2026-W29",
      "hours": 168,
      "net_pnl_usdt": "0",
      "directional_phases": 0
    },
    {
      "utc_iso_week": "2026-W30",
      "hours": 168,
      "net_pnl_usdt": "0",
      "directional_phases": 0
    },
    {
      "utc_iso_week": "2026-W31",
      "hours": 72,
      "net_pnl_usdt": "0",
      "directional_phases": 0
    }
  ],
  "zero_trades_metrics": "not_applicable",
  "artifact_hashes": {
    "historical_replay.json": "eb06486c370872e92d043a38f0c10400b697a87436d192d17af274bbe23186d9",
    "historical_identity.json": "d25d6380583e00996feedceaf480b4597f90663772c11babf8db3998aceda693",
    "state/offline_venue.json": "5f767467a29933491cdc6a77f30885a5764939f81fc6bbf997c4deee428ea1d5",
    "state/runtime/events.jsonl": "8b82f740faec4f4ebe6b8b07f3f3804866689fad9b23ef77a69f813c013d3243",
    "state/runtime/state.json": "d7fca179fdedcc0f1806f08a7023d1095696863ae9bfc66699ddc352cf7e8c13"
  },
  "safety": {
    "demo_enabled": false,
    "live_enabled": false,
    "network_accessed": false,
    "paper_enabled": false,
    "private_endpoint_accessed": false,
    "promotion_enabled": false,
    "real_order_submitted": false,
    "runtime_observed": false
  }
}
```

## 验收矩阵、未运行项与停止结论

| 验收项 | 本轮结果 |
|---|---|
| 冻结规格、不可变数据/源码、参数和成本身份 | 通过；JSON规格及其Git引用未在查看收益后修改 |
| 原一周业务兼容与恢复 | 168小时通过；末期账单从旧20笔补齐为21笔，经济结果一致 |
| 原策略非零行为、重复和恢复保护 | 原V1 11项通过；原fixture/预期未改 |
| 历史规格、因果时间、FOK/IOC模拟映射、末期非零归账 | 历史及规格45项通过；独立审查另从Git对象运行45项通过 |
| V0兼容 | 23 passed / 1 skipped；跳过显式opt-in的Qlib归档核验 |
| 地图静态/渲染 | 3 passed；未进行新一轮浏览器验收或发布 |
| 固定20天实际回放与权威账本 | 480小时通过、0成交、60笔资金费观察、逐小时账实一致 |
| 十二个月历史业务基线 | **未完成：当前可核验输入不足** |
| 策略盈利能力、独立确认、全年吞吐 | **未验证：无成交样本、仅20天；未运行独立确认或全年规模测试** |
| main / 正式页面 / 真实账户 / Demo / paper / live | **本票未实施、不授权** |

命令索引（均在专属 sparse worktree，使用主仓既有Python与Node依赖）：

- `python -B -m pytest -q tests/contracts/test_btc_donchian_history.py tests/contracts/test_btc_donchian_history_spec.py`：最终45 passed；独审独立执行45 passed in 9.79s。
- `python -B -m pytest -q tests/contracts/test_strategy_v1_donchian_offline.py` 的11项已与此前历史/规格测试合并执行通过；新增规格测试后未再次重复全部V1。两份证据明确分开，不合并成一次虚构的大测试计数。
- `python -B -m pytest -q tests/contracts/test_strategy_v0_freeze.py`：23 passed / 1 skipped。
- `node --test frontend/scripts/test-strategy-delivery-map.mjs`：3 passed。
- 数据准入、240小时停止、同一run恢复和status命令见上方入口说明。最后完整核账使用既有 `BTCRuntimeStore.recover()`，未改写产物。

最终限定源码仍在独立生产者分支，初始dirty=[]；本轮结束时只有本任务报告追加，没有他人重叠修改，其他代理分支未合并。执行期间HEAD始终冻结在083446929，运行及完成后恢复结束后才提交报告；后来报告/交接提交不意味着重新运行过历史。若需恢复既有run，必须在planner创建的独立工作树使用原执行HEAD，不能从报告新HEAD强行恢复旧身份。

本轮在此停止实验：入口与20天替代评估具备限定交付证据；一年业务结论仍缺数据，盈利能力仍缺成交样本。下一项若获用户确认，应由数据任务一次核验并封存更长的连续OKX行情、实际资金费及完整预热，而不是修改策略参数、扩大仓位或反复挑选有交易区间。独立集成只验证已审提交组合、报告与hash，不重跑研究；源码若要合入正式版本/发布页面，另核准本票的只读交付路径，不借用旧票据、不自动改治理。

保留：`promotion/demo/paper/live/private/order/real_order/transfer/withdraw/runtime_observed=false`。V3不重新打开，M3/M4不启动；未删除或覆盖任何历史研究证据。
