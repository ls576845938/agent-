from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_crypto.research import btc_okx_liquidation_snapshot_observer as observer


def test_liquidation_snapshot_observer_dry_run_keeps_boundaries_closed(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["dry_run"] is True
            assert kwargs["allow_network"] is False

        def request_by_name(self, name: str, params: dict[str, str]) -> dict[str, Any]:
            assert name == "liquidation_orders"
            assert params["instType"] == "SWAP"
            return {"url": "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP"}

    monkeypatch.setattr(observer, "OkxSwapPublicCollector", FakeCollector)

    report = observer.run_btc_okx_liquidation_snapshot_observer(
        repo_root=tmp_path,
        output_dir=Path("out"),
        data_path=Path("data/liquidations.csv"),
        execute_network=False,
        generated_at_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    safety = json.loads((tmp_path / "out/paper_live_safety_status.json").read_text(encoding="utf-8"))
    assert report["status"] == "dry_run_research_only"
    assert "btc_okx_liquidation_snapshot_observer_dry_run_no_network_executed" in report["blockers"]
    assert report["gate_interpretation"]["liquidation_snapshot_gate_eligible"] is False
    assert report["gate_interpretation"]["complete_liquidation_history_available"] is False
    assert report["gate"]["paper_queue_write_allowed"] is False
    assert report["gate"]["live_unlock_allowed"] is False
    assert safety["order_endpoint_used"] is False
    assert safety["broker_access_allowed"] is False


def test_liquidation_snapshot_observer_appends_public_rows_with_capture_time_visibility(tmp_path: Path, monkeypatch) -> None:
    class FakeCollector:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["dry_run"] is False
            assert kwargs["allow_network"] is True

        def request_by_name(self, name: str, params: dict[str, str]) -> dict[str, Any]:
            assert name == "liquidation_orders"
            return {
                "payload": {
                    "code": "0",
                    "msg": "",
                    "data": [
                        {
                            "instId": "BTC-USDT-SWAP",
                            "uly": "BTC-USDT",
                            "state": "filled",
                            "details": [
                                {"ts": "1782864000000", "side": "sell", "posSide": "long", "bkPx": "60000", "sz": "0.2"},
                                {"ts": "1782867600000", "side": "buy", "posSide": "short", "bkPx": "60100", "sz": "0.1"},
                            ],
                        }
                    ],
                }
            }

    monkeypatch.setattr(observer, "OkxSwapPublicCollector", FakeCollector)

    report = observer.run_btc_okx_liquidation_snapshot_observer(
        repo_root=tmp_path,
        output_dir=Path("out"),
        data_path=Path("data/liquidations.csv"),
        execute_network=True,
        generated_at_utc=datetime(2026, 7, 1, 1, tzinfo=timezone.utc),
    )

    rows = (tmp_path / "data/liquidations.csv").read_text(encoding="utf-8")
    assert report["status"] == "complete_research_only"
    assert report["data"]["new_row_count"] == 2
    assert report["data"]["merged_row_count"] == 2
    assert report["gate_interpretation"]["liquidation_snapshot_available"] is True
    assert report["gate_interpretation"]["liquidation_snapshot_gate_eligible"] is False
    assert report["gate_interpretation"]["complete_liquidation_history_available"] is False
    assert "max_public_rest_response_time_and_event_time" in rows
    assert "btc_okx_liquidation_snapshot_observe_only_not_complete_1h_history" in report["blockers"]
    assert report["gate"]["paper_queue_write_allowed"] is False
