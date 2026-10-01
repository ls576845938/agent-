# BTC Funding Rate Patch Request 20260501-20260512

## Request

Capture the missing BTCUSDT USD-M perpetual funding-rate rows from the public Binance USD-M endpoint:

```text
GET /fapi/v1/fundingRate
```

Query parameters:

```text
symbol=BTCUSDT
startTime=1777593600000
endTime=1778544000000
limit=1000
```

Expected event count: `34`

Expected range:

```text
2026-05-01T00:00:00Z through 2026-05-12T00:00:00Z
```

No API key is required. Do not call private, account, order, listenKey, userData, leverage, margin, transfer, broker, income, or balance endpoints.

## Output Paths

CSV:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/funding_rate_patch_20260501_20260512.csv
```

Metadata:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/funding_rate_patch_20260501_20260512.metadata.json
```

Optional raw response:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/funding_rate_patch_20260501_20260512.raw.json
```

Raw JSON may be normalized to CSV only if it matches the public `fundingRate` response shape.

## CSV Contract

Required columns:

```text
timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id
```

Rules:

- `symbol` must be `BTCUSDT`.
- `fundingTime` must be a UTC millisecond timestamp.
- `fundingRate` must be finite numeric text.
- `markPrice` should be finite numeric text if present.
- `source_record_id` must be non-empty.
- Rows must be sorted by `fundingTime`.
- Rows must exactly match the 34 expected missing funding events.

## Metadata Contract

```json
{
  "schema_version": "btc_funding_rate_patch_metadata_v1",
  "patch_id": "funding_rate_patch_20260501_20260512",
  "csv_filename": "funding_rate_patch_20260501_20260512.csv",
  "csv_sha256": "<64 lowercase hex sha256>",
  "source_method": "manual_offline_public_rest_capture",
  "source_base_url": "https://fapi.binance.com",
  "source_endpoint": "/fapi/v1/fundingRate",
  "symbol": "BTCUSDT",
  "requested_start": "2026-05-01T00:00:00Z",
  "requested_end": "2026-05-12T00:00:00Z",
  "startTime": 1777593600000,
  "endTime": 1778544000000,
  "captured_at": "2026-05-19T00:00:00Z",
  "operator_note": "Manual public REST capture from an accessible environment. No API key.",
  "api_key_used": false,
  "private_endpoint_used": false,
  "auth_headers_present": false,
  "record_count": 34,
  "expected_row_count": 34,
  "expected_first_fundingTime": 1777593600000,
  "expected_last_fundingTime": 1778544000000,
  "funding_interval_hours": 8,
  "target_bundle_id": "btc_usdm_binance_btcusdt_20240101_20260512_v1",
  "target_file": "funding_rate.csv",
  "merge_key": "fundingTime",
  "merge_policy": "fail_on_duplicate_fundingTime",
  "operator": "manual",
  "created_at": "2026-05-19T00:00:00Z",
  "requests": [],
  "blockers": []
}
```

## Safe Example Commands

Standalone Python script for an external environment with access to Binance public REST:

```python
#!/usr/bin/env python3
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

PATCH_ID = "funding_rate_patch_20260501_20260512"
BUNDLE_ID = "btc_usdm_binance_btcusdt_20240101_20260512_v1"
SYMBOL = "BTCUSDT"
START_TIME = 1777593600000
END_TIME = 1778544000000
ENDPOINT = "/fapi/v1/fundingRate"
BASE_URL = "https://fapi.binance.com"
URL = f"{BASE_URL}{ENDPOINT}"

out_dir = Path(".")
raw_path = out_dir / f"{PATCH_ID}.raw.json"
csv_path = out_dir / f"{PATCH_ID}.csv"
metadata_path = out_dir / f"{PATCH_ID}.metadata.json"

params = {
    "symbol": SYMBOL,
    "startTime": START_TIME,
    "endTime": END_TIME,
    "limit": 1000,
}

captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
resp = requests.get(URL, params=params, timeout=30)
resp.raise_for_status()
rows = resp.json()

if not isinstance(rows, list):
    raise ValueError("Expected JSON list response")

raw_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

required = ["timestamp", "fundingTime", "symbol", "fundingRate", "markPrice", "source_record_id"]
with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=required)
    writer.writeheader()
    for row in sorted(rows, key=lambda item: int(item["fundingTime"])):
        funding_time = int(row["fundingTime"])
        timestamp = datetime.fromtimestamp(funding_time / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        writer.writerow({
            "timestamp": timestamp,
            "fundingTime": str(funding_time),
            "symbol": row.get("symbol") or SYMBOL,
            "fundingRate": row.get("fundingRate"),
            "markPrice": row.get("markPrice", ""),
            "source_record_id": f"funding_rate_manual_public_rest:{funding_time}",
        })

csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()

metadata = {
    "schema_version": "btc_funding_rate_patch_metadata_v1",
    "patch_id": PATCH_ID,
    "csv_filename": f"{PATCH_ID}.csv",
    "csv_sha256": csv_sha256,
    "source_method": "manual_offline_public_rest_capture",
    "source_base_url": BASE_URL,
    "source_endpoint": ENDPOINT,
    "symbol": SYMBOL,
    "requested_start": "2026-05-01T00:00:00Z",
    "requested_end": "2026-05-12T00:00:00Z",
    "startTime": START_TIME,
    "endTime": END_TIME,
    "captured_at": captured_at,
    "operator_note": "Captured from public Binance USD-M Futures fundingRate endpoint in an accessible network environment. No API key, no private/account/order endpoint.",
    "api_key_used": False,
    "private_endpoint_used": False,
    "auth_headers_present": False,
    "record_count": len(rows),
    "expected_row_count": 34,
    "expected_first_fundingTime": START_TIME,
    "expected_last_fundingTime": END_TIME,
    "funding_interval_hours": 8,
    "target_bundle_id": BUNDLE_ID,
    "target_file": "funding_rate.csv",
    "merge_key": "fundingTime",
    "merge_policy": "fail_on_duplicate_fundingTime",
    "operator": "manual",
    "created_at": captured_at,
    "requests": [{"url": URL, "params": params, "captured_at": captured_at, "http_status": resp.status_code, "row_count": len(rows)}],
    "blockers": [],
}

metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Wrote {csv_path}")
print(f"Wrote {metadata_path}")
print(f"record_count={len(rows)}")
print(f"csv_sha256={csv_sha256}")
```

Curl:

```bash
curl 'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime=1777593600000&endTime=1778544000000&limit=1000' \
  -o funding_rate_patch_20260501_20260512.raw.json
```

Python:

```python
import json
from urllib.parse import urlencode
from urllib.request import urlopen

params = {
    "symbol": "BTCUSDT",
    "startTime": 1777593600000,
    "endTime": 1778544000000,
    "limit": 1000,
}
url = "https://fapi.binance.com/fapi/v1/fundingRate?" + urlencode(params)
with urlopen(url, timeout=30) as response:
    payload = json.loads(response.read().decode("utf-8"))
print(json.dumps(payload, indent=2))
```

Checksum:

```bash
sha256sum funding_rate_patch_20260501_20260512.csv
```

## Validate Locally

After placing the CSV and metadata under the bundle `patches/` directory:

```bash
python3 scripts/validate_btc_funding_rate_patch.py
```

If validation passes, merge:

```bash
python3 scripts/merge_btc_funding_rate_patch.py
```

Successful funding coverage does not imply `perpetual_evidence_ready=true` while `exchange_info.json` is still missing. It also does not imply alpha pass, paper review, or live readiness.
