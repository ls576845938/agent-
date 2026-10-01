"""Import-safe constants shared by OKX public L2 capture and export."""

from __future__ import annotations


OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION = (
    "btc_okx_public_ws_l2_raw_capture_manifest_v1"
)
OKX_L2_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_L2_PUBLIC_WS_URLS = (
    OKX_L2_PUBLIC_WS_URL,
    "wss://wsaws.okx.com:8443/ws/v5/public",
)
OKX_L2_VENUE = "okx"
OKX_L2_INSTRUMENT_ID = "BTC-USDT-SWAP"
OKX_L2_SYMBOL = "BTCUSDT"
OKX_L2_BOOKS_CHANNEL = "books"
OKX_L2_RAW_MESSAGES_FILE = "okx_public_ws_l2_raw_messages.jsonl"
OKX_L2_RAW_MANIFEST_FILE = "okx_public_ws_l2_raw_capture_manifest.json"
