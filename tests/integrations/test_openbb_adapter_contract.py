from __future__ import annotations

from pathlib import Path

from integrations.openbb_adapter.research_manifest import (
    OpenBBAdapterError,
    OpenBBResearchRequest,
    build_openbb_research_manifest,
)


def test_openbb_manifest_is_supplemental_research_only(tmp_path: Path) -> None:
    output = tmp_path / "openbb_manifest.json"

    manifest = build_openbb_research_manifest(
        OpenBBResearchRequest(
            request_id="openbb_etf_macro",
            topic="ETF macro context",
            symbols=["spy", "QQQ", "SPY"],
            requested_datasets=["etf_profile", "macro_series"],
        ),
        output_path=output,
    )

    payload = manifest.to_dict()
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["symbols"] == ["SPY", "QQQ"]
    assert payload["production_pit_clean"] is False
    assert payload["promotion_status"] == "supplemental_research_only"
    assert payload["allow_paper"] is False
    assert payload["allow_live"] is False
    assert "provider_neutral_ingest" in payload["required_normalization_before_promotion"]
    assert output.exists()


def test_openbb_request_refuses_trading_or_promotion_enablement() -> None:
    try:
        OpenBBResearchRequest(
            request_id="bad",
            topic="bad",
            symbols=["SPY"],
            requested_datasets=["news"],
            allow_promotion_clean=True,
            allow_live=True,
        )
    except OpenBBAdapterError as exc:
        message = str(exc)
        assert "allow_promotion_clean" in message
        assert "allow_live" in message
    else:
        raise AssertionError("expected OpenBBAdapterError")
