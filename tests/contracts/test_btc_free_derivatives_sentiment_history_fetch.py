from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import scripts.fetch_btc_free_derivatives_sentiment_history as fetcher


TS = datetime(2026, 6, 27, 9, tzinfo=timezone.utc)


def test_free_derivatives_fetch_fails_closed_without_overwriting_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows_output = tmp_path / "derivatives_sentiment_1h.json"
    audit_output = tmp_path / "btc_free_derivatives_history_fetch_report.json"

    def _raise_binance(**_: object) -> dict[str, object]:
        raise RuntimeError("binance unavailable")

    def _raise_okx(**_: object) -> dict[str, object]:
        raise RuntimeError("okx illegal time range")

    monkeypatch.setattr(fetcher, "fetch_binance_free_derivatives_payloads", _raise_binance)
    monkeypatch.setattr(fetcher, "fetch_okx_free_derivatives_payloads", _raise_okx)

    payload = fetcher.fetch_btc_free_derivatives_sentiment_history(
        rows_output=rows_output,
        audit_output=audit_output,
        lookback_hours=2160,
        execute_network=True,
        generated_at_utc=TS,
    )

    assert payload["status"] == "blocked"
    assert payload["provider"] == "none"
    assert payload["row_count"] == 0
    assert "btc_free_derivatives_history_fetch_failed_all_public_sources" in payload["blockers"]
    assert payload["network_called"] is True
    assert payload["public_market_data_only"] is True
    assert payload["api_key_used"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["order_endpoint_used"] is False
    assert audit_output.exists()
    assert not rows_output.exists()
