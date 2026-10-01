from __future__ import annotations

import copy
import hashlib
import json
import pytest

from backend.app.services.strategy_parameter_evidence import project_parameter_evidence, ParameterEvidenceError


def source():
    params = {"entry_window": 180, "exit_window": 90, "cooldown_bars": 6, "signal_type": "symmetric_donchian"}
    return {
        "schema_version": "btc_long_short_trend_following_lab_v1",
        "status": "complete_research_only", "code_commit": "a" * 40,
        "generated_at_utc": "2026-06-30T00:00:00Z",
        "input": {"exchange": "binance_spot", "symbol": "BTCUSDT", "source_interval": "1h", "base_decision_interval": "4h", "bar_4h_start": "2024-01-01", "bar_4h_end": "2026-06-29"},
        "guardrails": {key: False for key in ("broker_access_allowed", "live_order_allowed", "live_unlock_allowed", "oms_access_allowed", "order_endpoint_used", "paper_candidate_created", "paper_queue_write_allowed", "private_endpoint_used", "real_order_submitted")},
        "validation_design": {"candidate_count": 1, "long_short_candidate_count": 1, "cost_model": {"base_cost_bps": 10, "includes_taker_fee_and_slippage": True}, "execution_rule": "next bar", "funding_model": {"research_approximation": True}},
        "long_short_research_rows": [{"candidate_id": "candidate-1", "family_id": "donchian", "params": params, "sharpe_ratio": 1.2, "annual_return_pct": 14, "max_drawdown_pct": -8, "cost_stress": {"scenarios": [{"cost_bps": 10, "metrics": {"sharpe_ratio": 1.2, "annual_return_pct": 14, "max_drawdown_pct": -8, "sortino_ratio": 1.6}}]}}],
    }


def test_projection_preserves_metrics_and_source_without_inventing_pnl():
    result = project_parameter_evidence(source(), source_sha256="b" * 64)
    assert result["rows"][0]["metrics"]["sortino_ratio"] == 1.6
    assert result["rows"][0]["metrics"]["max_drawdown_pct"] == -8
    assert result["source"]["report_sha256"] == "b" * 64
    assert result["coverage"]["published_count"] == 1
    assert result["safety"] and not any(result["safety"].values())
    assert "pnl" not in result["rows"][0]


@pytest.mark.parametrize("mutation", ["unsafe", "duplicates", "count", "cost", "nonfinite", "params", "metric_mismatch", "params_hash", "duplicate_params"])
def test_invalid_source_fails_closed(mutation):
    report = copy.deepcopy(source())
    if mutation == "unsafe": report["guardrails"]["order_endpoint_used"] = True
    if mutation == "duplicates": report["long_short_research_rows"] *= 2
    if mutation == "count": report["validation_design"]["long_short_candidate_count"] = 4
    if mutation == "cost": report["long_short_research_rows"][0]["cost_stress"]["scenarios"][0]["cost_bps"] = 20
    if mutation == "nonfinite": report["long_short_research_rows"][0]["params"]["entry_window"] = float("nan")
    if mutation == "params": report["long_short_research_rows"][0]["params"] = {}
    if mutation == "metric_mismatch": report["long_short_research_rows"][0]["sharpe_ratio"] = 9
    if mutation == "params_hash": report["long_short_research_rows"][0]["params_hash"] = "bad"
    if mutation == "duplicate_params":
        second = copy.deepcopy(report["long_short_research_rows"][0])
        second["candidate_id"] = "different-id-same-params"
        report["long_short_research_rows"].append(second)
        report["validation_design"]["long_short_candidate_count"] = 2
    with pytest.raises(ParameterEvidenceError):
        project_parameter_evidence(report, source_sha256="b" * 64)


def test_hash_bound_reader_rejects_tampering_path_escape_and_unsafe_payload():
    from backend.app.services.strategy_parameter_evidence import load_parameter_evidence, SCHEMA
    class Reader:
        raw = json.dumps(project_parameter_evidence(source(), source_sha256="b" * 64)).encode()
        pointer = {}
        def read_json(self, path): return self.pointer
        def read_bytes(self, path): return self.raw
    reader = Reader()
    digest = hashlib.sha256(reader.raw).hexdigest()
    reader.pointer = {"schema_version": SCHEMA, "sha256": digest, "path": f"artifacts/strategy_parameter_map/runs/{digest}/evidence.json"}
    result = load_parameter_evidence(reader, strategy_id="long_short_donchian_top5_okx_native")
    assert "非 OKX-native" in result["relationship"]
    assert result["evidence_sha256"] == digest
    reader.raw += b" "
    with pytest.raises(ParameterEvidenceError, match="hash"):
        load_parameter_evidence(reader, strategy_id="long_short_donchian_top5")
    reader.pointer["path"] = "../../arbitrary.json"
    with pytest.raises(ParameterEvidenceError, match="pointer"):
        load_parameter_evidence(reader, strategy_id="long_short_donchian_top5")
    with pytest.raises(LookupError):
        load_parameter_evidence(reader, strategy_id="not-registered")


def test_explicit_history_root_does_not_change_promotion_reader(monkeypatch):
    import backend.app.services.strategy_parameter_evidence as service
    sentinel = object()
    monkeypatch.delenv(service.HISTORY_ROOT_ENV, raising=False)
    assert service.configured_history_reader(sentinel) is None
    monkeypatch.setenv(service.HISTORY_ROOT_ENV, "relative-not-allowed")
    with pytest.raises(RuntimeError):
        service.configured_history_reader(sentinel)


def test_promotion_reader_with_published_history_is_never_an_implicit_fallback(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api.btc_strategy_history import build_btc_strategy_history_router
    from backend.app.services.strategy_parameter_evidence import HISTORY_ROOT_ENV
    from backend.tests.test_btc_strategy_history_api import _published_writer
    from quant_crypto.application.btc_strategy_history import load_btc_strategy_history_catalog
    writer = _published_writer(tmp_path)
    assert load_btc_strategy_history_catalog(writer)
    monkeypatch.delenv(HISTORY_ROOT_ENV, raising=False)
    monkeypatch.setenv("QS_BTC_RUNTIME_ARTIFACT_ROOT", str(writer.artifact_root))
    app = FastAPI()
    app.include_router(build_btc_strategy_history_router(writer, write_dependency=lambda: False))
    client = TestClient(app)
    for url in ("/research/btc/strategy-history/catalog", "/research/btc/strategy-history/long_short_donchian_top5/candidate", "/research/btc/strategy-parameter-map/long_short_donchian_top5"):
        assert client.get(url).status_code == 503


def test_history_configuration_error_is_503_without_physical_path_leak(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api.btc_strategy_history import build_btc_strategy_history_router
    from backend.app.services.strategy_parameter_evidence import HISTORY_ROOT_ENV
    monkeypatch.setenv(HISTORY_ROOT_ENV, "untrusted-local-path")
    app = FastAPI()
    app.include_router(build_btc_strategy_history_router(None, write_dependency=lambda: False))
    client = TestClient(app)
    for url in ("/research/btc/strategy-history/catalog", "/research/btc/strategy-parameter-map/long_short_donchian_top5"):
        result = client.get(url)
        assert result.status_code == 503
        assert "untrusted-local-path" not in result.text
