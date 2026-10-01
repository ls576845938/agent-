from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT = (
    REPO_ROOT
    / "docs"
    / "handoffs"
    / "DATA-BTC-REAL-L2-ATTESTATION-04"
    / "blocked-receipt.json"
)


def test_blocked_receipt_preserves_real_l2_and_trading_fail_closed() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert payload["status"] == "blocked"
    assert payload["scope"] == {
        "venue": "okx",
        "instrument_id": "BTC-USDT-SWAP",
        "channel": "books",
        "public_market_data_only": True,
        "credentials_used": False,
    }
    assert len(payload["public_ws_attempts"]) == 2
    assert all(
        attempt["message_count"] == 0
        for attempt in payload["public_ws_attempts"]
    )
    assert payload["sequence"]["sequence_continuity_verified"] is False
    assert payload["controlled_recovery"]["gapfill_pass"] is False
    assert payload["server_clock"]["valid_sample_count"] == 9
    assert payload["server_clock"]["offset_verified"] is False
    assert (
        payload["server_clock"]["abs_offset_max_ms"]
        > payload["server_clock"]["max_allowed_abs_offset_ms"]
    )
    assert payload["readiness"] == {
        "quality_checked": False,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
        "paper_ready": False,
        "live_ready": False,
    }
    assert not any(payload["safety"].values())
