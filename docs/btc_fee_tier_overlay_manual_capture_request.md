# BTC 手续费等级人工证据说明

生成位置：`artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json`

配套导入报告：`artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json`

用途：给 BTC USD-M 永续成本模型提供 maker/taker 手续费等级证据。没有 overlay 文件时，成本模型必须继续保留 `btc_maker_taker_fee_tier_missing`；有 overlay 但没有匹配的写入型 import report/hash 时，成本模型也必须拒绝 `fee_tier_verified`。

## 允许来源

- 人工查看 Binance USD-M futures 公开费率表后的离线记录。
- 人工确认的研究假设费率，但必须写清楚来源和时间。
- 不允许用私有接口、API key、账户权限或订单接口自动抓取。

## JSON 模板

优先使用下面的 Make 目标生成 overlay，不要手写生产文件。`maker/taker` 数值必须来自人工确认的公开费率来源；示例值只表示字段格式。

```json
{
  "schema_version": "btc_fee_tier_overlay_v1",
  "symbol": "BTCUSDT",
  "market_type": "usds_m_perpetual",
  "maker_fee_bps": 2.0,
  "taker_fee_bps": 4.0,
  "source": "manual_public_binance_usdm_fee_schedule",
  "source_url_or_doc": "https://www.binance.com/en/fee/futureFee",
  "captured_at": "2026-05-23T00:00:00Z",
  "api_key_used": false,
  "private_endpoint_used": false,
  "auth_headers_used": false
}
```

## 导入命令

先 dry-run，确认 `status=verified` 且 `writes_performed=false`：

```bash
BTC_FEE_TIER_MAKER_BPS=<captured_maker_fee_bps> \
BTC_FEE_TIER_TAKER_BPS=<captured_taker_fee_bps> \
BTC_FEE_TIER_CAPTURED_AT=2026-05-23T00:00:00Z \
make dry-run-btc-fee-tier-overlay-import
```

再 apply 写入 `artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json` 和 `artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json`，并重建 BTC data/cost/candidate/registry/paper-readiness/paper-start 证据链。机器可读 operator packet 里的 `fee_tier_overlay_request.post_import_rebuild_command` 也固定为 `make rebuild-btc-paper-readiness-chain`：

```bash
BTC_FEE_TIER_MAKER_BPS=<captured_maker_fee_bps> \
BTC_FEE_TIER_TAKER_BPS=<captured_taker_fee_bps> \
BTC_FEE_TIER_CAPTURED_AT=2026-05-23T00:00:00Z \
make apply-btc-fee-tier-overlay-import
```

默认来源字段：

- `BTC_FEE_TIER_SOURCE=manual_public_binance_usdm_fee_schedule`
- `BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.binance.com/en/fee/futureFee`

成本模型会校验 import report 的 `status=verified`、`dry_run=false`、`writes_performed=true`、overlay 输出路径、maker/taker/source/captured_at 字段，以及 `overlay_payload_sha256` 与实际 overlay 内容一致。不要手写或直接覆盖生产 overlay。

## 验证命令

```bash
PYTHONPATH=. venv/bin/python scripts/build_btc_cost_model_report.py --repo-root .
PYTHONPATH=. venv/bin/python -m pytest tests/contracts/test_btc_cost_model_contract.py -q
```

即使手续费等级通过，只要交易所规则、资金费率说明或数据包预检查仍失败，`candidate_pass_allowed` 和 `promotion_ready` 仍必须保持 `false`。
