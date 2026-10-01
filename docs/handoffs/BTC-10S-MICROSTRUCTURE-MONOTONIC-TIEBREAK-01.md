# BTC-10S-MICROSTRUCTURE-MONOTONIC-TIEBREAK-01

## 目标与边界

- base commit：`30bc24a82fa407432697adf08432711dd7783349`
- change risk：`promotion_evidence`
- producer：`data_steward`
- 仅修复 OKX public trades/books 原始采集在 Windows 上遇到相同 `time.monotonic_ns()` 值时无法满足 immutable exporter 严格递增合同的问题。
- 不修改 exporter、策略、风险、OMS、ledger、private WS 或执行权限；不读取凭证，不调用 private/order/live endpoint。

## Failure-first 证据

current-HEAD 90 秒公开采集得到 1,031 帧，其中 152 组相邻帧的 `monotonic_ns` 相同；首组为 capture sequence `1 -> 2`。导出按合同 fail-closed：

`feed_export_exception:MicrostructureExportBlocked:microstructure_monotonic_ns_not_strict`

新增回归在修复前失败为 `KeyError: raw_monotonic_ns`，证明旧采集器既未保留原始时钟，也未提供严格排序字段。

## 修复语义

- 每帧保留真实 `raw_monotonic_ns`。
- 规范化 `monotonic_ns=max(raw_monotonic_ns, previous_monotonic_ns + 1)`，只用 1ns 级逻辑 tie-break 表达已由 `capture_sequence` 确定的接收顺序。
- 每帧记录 `monotonic_tiebreak_ns`；manifest 记录排序策略、调整次数和最大调整量。
- 原始时钟真正回退（当前 raw 值小于前一 raw 值）仍写入 `btc_okx_public_ws_l2_monotonic_clock_rollback` 并使采集结果 fail-closed；不得用 tie-break 隐藏回退。
- immutable exporter 的严格递增、sequence、checksum、gap、two-sided 和时间对齐门禁全部保持不变。

## Touch set

- `scripts/fetch_btc_okx_public_ws_l2_raw_capture.py`
- `tests/contracts/test_btc_okx_public_collector_boundaries.py`
- `docs/handoffs/BTC-10S-MICROSTRUCTURE-MONOTONIC-TIEBREAK-01.md`

## 验证

```powershell
D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py::test_okx_public_ws_l2_raw_capture_tiebreaks_equal_windows_monotonic_ticks -q
D:\vibe coding\Obsidian\量化系统\agent-\.venv\Scripts\python.exe -m pytest tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_okx_l2_immutable_export.py tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py -q
```

- 定向 failure-first 回归：`1 passed`（修复前失败）。
- 联合合同：`102 passed`。

## Gate 影响

本提交仅令后续新采集可产生可验证的严格排序 raw/immutable 版本。失败的旧 slice 不得重新标记为成功，也不得作为 current-HEAD data pointer。独立 integrator 合入后必须从注册 `main` 重新采集并发布新的 immutable version，再重建 current-HEAD pointer/read model。

`promotion/paper/live/private/order/real_order/transfer/withdraw=false`。
