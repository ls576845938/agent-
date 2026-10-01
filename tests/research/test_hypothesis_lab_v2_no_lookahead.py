import json
from pathlib import Path


RUN = Path("artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle")
SOURCE = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/feature_profile.json")


def test_hypothesis_lab_v2_lifecycle_no_lookahead_contract() -> None:
    report = json.loads((RUN / "lifecycle_aware_distribution_report.json").read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))

    assert report["no_lookahead_status"] == "pass"
    assert source["no_lookahead"]["status"] == "pass"
    assert source["feature_definitions"]["future_return_usage"] == "labels_only"
    assert "full_lifecycle_distribution" in report
