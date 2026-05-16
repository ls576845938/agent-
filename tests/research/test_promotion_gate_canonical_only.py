import json

import pytest

from quant_us.research.btc_canonical import load_single_canonical_report


def test_promotion_gate_rejects_non_canonical_evidence(tmp_path) -> None:
    legacy = tmp_path / "legacy_report.json"
    legacy.write_text(json.dumps({"schema_version": "legacy", "evidence_source": "signal_equity"}), encoding="utf-8")

    with pytest.raises(ValueError, match="not a single BTC canonical report"):
        load_single_canonical_report(legacy)


def test_promotion_gate_rejects_wrong_evidence_source(tmp_path) -> None:
    report = tmp_path / "wrong_source.json"
    report.write_text(
        json.dumps({"schema_version": "btc_canonical_backtest_report_v1", "evidence_source": "strict_evidence"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rejects non-canonical evidence"):
        load_single_canonical_report(report)
