# BTC-CURRENT-HEAD-AUTHORITATIVE-DATA-POINTER-01

## 目标

提供一个只能从已集成且 clean 的 `main` 运行的离线发布入口，将指定的 Git committed immutable 10s 数据版本解析、逐文件校验并绑定到 current-HEAD 外部 runtime artifact。该入口不采集数据、不读取凭证、不调用 private/order/live endpoint，也不改变策略、风险、OMS 或运行时执行语义。

## 冻结输入

- Git manifest spec：`f96473dda7e96df0adfa2a0a2f10cd936674cef1:.agent/data_manifests/btc-okx-10s-microstructure-immutable-feed/btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6.json`
- `dataset_id=btc-okx-10s-microstructure-immutable-feed`
- `data_version=btc-okx-10s-feed-00000001-20260827t111218925177z-src4e615032a6`
- `aggregate_sha256=2fa444de042e742e9763b6a4988205b7f05d5374d6cf66fa94d20c7efd26fd70`
- active research scope：`trade_imbalance_continuation + 10s`

禁止 SQLite、`HEAD:`、`latest`、glob、staging 或 repo-local artifact fallback。解析必须通过 `shared_data.py` 的完整 physical file hash verification。

## 发布协议

入口：

```powershell
py -3 scripts/publish_btc_current_head_authoritative_data_pointer.py --expected-head <current-main-full-sha>
```

前置条件：

1. 当前分支必须是 `main`，full HEAD 必须与 `--expected-head` 一致，worktree 必须 clean。
2. `QS_BTC_RUNTIME_ARTIFACT_ROOT` 必须是仓库外绝对路径，并已由 bootstrap 生成 repository-owner marker。
3. artifact 所在磁盘可用空间不少于 50 GiB。
4. 只能有一个 writer，必须取得 runtime artifact writer lock。

发布次序：

1. 在 run-owned staging 中写入 attestation、blocked depth-fill mapping、evidence、manifest。
2. 原子替换为 immutable run directory。
3. active criteria 已作为 immutable run member 写入；随后原子更新其 `latest` mirror。mirror 只是非权威缓存，不能脱离 authoritative pointer 形成 authority。
4. 最后原子替换 `artifacts/btc_okx_native_backtest_evidence/latest_manifest.json`。

pointer、manifest、evidence 仅引用 artifact-root 逻辑路径，不暴露 physical root；三者唯一包含同一份真实 data-steward attestation reference，reader 会重新读取并验证实际 SHA256 和 identity membership。该协议不伪造跨文件原子性：若 mirror 成功而 pointer 更新失败，旧 pointer 仍是 authority，mirror 与旧 pointer 的 run/hash lineage 不一致会让 gate fail-closed；使用新 run id 重跑可恢复一致状态。

cleanliness 检查只针对本入口声明的 Git-tracked source/contract path，并使用带 pathspec 的 `git diff` / `git ls-files`。注册 main 中与本发布无关的 data、artifact 或文档 dirty 不会误阻塞；任何相关路径相对 HEAD dirty 则必须停止。

## 当前数据结论

producer 阶段对冻结 shared-data version 做了只读 full-file verification：

- normalized trades 与 ordered L2 均存在；same-connection trade-book alignment 有测量；two-sided coverage 为 100%。
- coverage 为 55.997 秒；60 秒 reconnect/epoch embargo 后，10s/30s/60s 均为 `eligible_labeled_windows=0`、`autocorrelation_adjusted_ess=0`。
- UTC、weekday 与 volatility/liquidity regime coverage 均不完整。
- OI/liquidation 不适用于当前选定的 trade-imbalance family，不作为该 family 的数据阻塞。
- 现有 `depth_impact_bps` 不是自然成交、queue position 或 partial fill 证据；`historical_timestamp_aligned_depth_fill_mapping_missing` 保留。

因此发布结果必须是 `blocked_insufficient_information`，只能作为 current-HEAD 权威数据身份与质量证据，不能解锁 runtime、promotion、paper 或 live。

## 安全边界

`promotion/paper/live/private/order/real_order/transfer/withdraw=false`。本票据 producer 只提交代码、schema、测试和文档；外部 current-HEAD artifact 必须等独立 integrator 合入 main 后，由注册 main 上的单写者入口生成。
