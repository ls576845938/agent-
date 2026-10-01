# BTC-OKX-10S-L2-SNAPSHOT-RESYNC-RECOVERY-01

## 目标与边界

- base commit：`dc95a75ce2afe5205fa20bc1c06246c8e6c2c50b`
- change risk：`unclassified`，保留独立 integrator、current-HEAD artifact 和 backend restart 的严格交付路径。
- producer：`btc_developer`
- 仅修复 public-only continuous feed 对精确 L2 snapshot-resync export 失败的分类和恢复语义。
- 不修改 exporter 门槛、策略、风控、OMS、ledger、private WS、凭证或执行权限；producer 不运行网络采集、不发布数据、不重建 artifact、不重启服务。

## Failure-first 证据

current-HEAD 失败 slice 的 raw capture 保持单一连接、无 sequence gap，export blocker 精确为：

`l2_clock_lag_exceeds_limit;l2_update_requires_new_snapshot`

新增回归在修复前得到 `continuous_terminal_blocked`，预期为退避后以新 slice、新 capture、新连接等待 snapshot，并最终发布后续健康 slice。该回归证明旧 runner 将可恢复的 public snapshot-resync 场景错误归类为终态 `blocked_export`。

## 修复语义

- 仅当 `MicrostructureExportBlocked.blockers` 集合精确等于：
  - `l2_clock_lag_exceeds_limit`
  - `l2_update_requires_new_snapshot`
- runner 才将坏 slice 终结为可重试 `blocked_public_network`，保留 raw capture 审计，明确标记该 slice 不可发布，并在退避后创建新 slice、新 capture 和新连接等待 snapshot。
- 不复用坏 capture，不发布坏 slice，不删除其 raw 审计。
- 任意额外 blocker 都不匹配该恢复集合。sequence gap、checksum mismatch、未知 exporter blocker，以及包含上述任一项的混合失败，继续保持 `blocked_export` terminal。
- max clock lag、sequence、checksum、snapshot 和 exporter 的任何门槛均未改变。

## Touch set

- `scripts/run_btc_okx_10s_microstructure_immutable_feed.py`
- `tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py`
- `docs/handoffs/BTC-OKX-10S-L2-SNAPSHOT-RESYNC-RECOVERY-01.md`
- `.agent/handoffs/BTC-OKX-10S-L2-SNAPSHOT-RESYNC-RECOVERY-01/**`

## 验证

```powershell
py -3 -m pytest -q tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py
py -3 -m pytest -q tests/contracts/test_btc_okx_public_collector_boundaries.py tests/contracts/test_btc_okx_l2_immutable_export.py tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py
py -3 -m py_compile scripts/run_btc_okx_10s_microstructure_immutable_feed.py tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py
git diff --check -- scripts/run_btc_okx_10s_microstructure_immutable_feed.py tests/contracts/test_btc_okx_10s_microstructure_immutable_feed.py docs/handoffs/BTC-OKX-10S-L2-SNAPSHOT-RESYNC-RECOVERY-01.md
```

- failure-first：修复前 `1 failed`，实际状态为 `continuous_terminal_blocked`。
- 精确恢复与终态反例：`5 passed`。
- runner 合同文件：`26 passed`。
- collector + L2 exporter + runner 联合合同：`107 passed`。
- `py_compile` 与 `git diff --check`：通过。

## Gate 影响

本提交只恢复后续 public-only current-HEAD 采集的重连机会，不提供新的数据、ESS、depth-fill、funding、Private WS、25h 或人工批准证据。独立 integrator 合入后，才可从注册 `main` 以新 HEAD、新 runtime root 重新启动公共采集；随后仍需发布不可变 manifest 并重建 current-HEAD artifact/read model。

`promotion/paper/live/private/order/real_order/transfer/withdraw=false`。
