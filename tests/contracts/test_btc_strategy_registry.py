from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_crypto.application.btc_backtest_identity import (
    load_latest_btc_backtest_manifest,
    write_btc_backtest_run_manifest,
)
from quant_crypto.application.btc_strategy_registry import (
    BTCStrategyIdentityError,
    BTCStrategyNotCanonicalError,
    HIGH_OCTANE_STRATEGY_LINE,
    HIGH_YIELD_STRATEGY_LINE,
    OKX_NATIVE_STRATEGY_LINE,
    STABLE_STRATEGY_LINE,
    btc_strategy_registry,
)


def test_registry_freezes_top5_and_keeps_overlay_lines_identity_only() -> None:
    top5 = [spec for spec in btc_strategy_registry.list_specs() if spec.strategy_id == STABLE_STRATEGY_LINE]

    assert len(top5) == 5
    assert all(spec.promotion_credit_eligible for spec in top5)
    assert all(spec.signal_callable is not None for spec in top5)

    for strategy_id in (HIGH_YIELD_STRATEGY_LINE, HIGH_OCTANE_STRATEGY_LINE):
        overlays = [spec for spec in btc_strategy_registry.list_specs() if spec.strategy_id == strategy_id]
        assert overlays
        assert all(not spec.promotion_credit_eligible for spec in overlays)
        assert all(spec.signal_callable is None for spec in overlays)


def test_registry_exposes_okx_native_identity_without_unlocking_paper_or_live() -> None:
    native = [
        spec for spec in btc_strategy_registry.list_specs() if spec.strategy_id == OKX_NATIVE_STRATEGY_LINE
    ]

    assert len(native) == 5
    assert all(spec.venue == "OKX" for spec in native)
    assert all(spec.instrument == "BTC-USDT-SWAP" for spec in native)
    assert all(spec.canonical_signal_available for spec in native)
    assert all("requires_okx_native_evidence" in spec.promotion_eligibility for spec in native)


def test_stable_and_okx_native_top5_expose_the_same_backtest_execution_capability() -> None:
    stable = btc_strategy_registry.get(STABLE_STRATEGY_LINE)
    native = btc_strategy_registry.get(
        OKX_NATIVE_STRATEGY_LINE,
        f"okx_native_{stable.candidate_id}",
    )

    assert stable.candidate_id.startswith("btc_ls_tf_")
    assert not native.candidate_id.startswith("btc_ls_tf_")
    assert stable.params_hash == native.params_hash
    assert stable.backtest_execution == native.backtest_execution
    assert stable.backtest_execution.supported is True
    assert stable.backtest_execution.position_capability == "long_short"
    assert stable.backtest_execution.target_weight == 0.98
    assert stable.backtest_execution.execution_timing == "bar_close_signal_next_completed_1h_open"


def test_registry_rejects_identity_impersonation_and_frozen_param_drift() -> None:
    top1 = btc_strategy_registry.get(STABLE_STRATEGY_LINE)

    with pytest.raises(BTCStrategyIdentityError, match="cannot impersonate"):
        btc_strategy_registry.resolve_request(strategy_id="trend_macd", candidate_id=top1.candidate_id)

    with pytest.raises(BTCStrategyIdentityError, match="frozen params mismatch"):
        btc_strategy_registry.resolve_request(
            strategy_id=STABLE_STRATEGY_LINE,
            candidate_id=top1.candidate_id,
            params={"donchian_window": 1},
        )

    with pytest.raises(BTCStrategyNotCanonicalError, match="completed BTC 1h"):
        assert top1.signal_callable is not None
        top1.signal_callable(None, "4h")  # type: ignore[arg-type]


def test_backtest_identity_manifest_binds_ledger_and_never_unlocks(tmp_path) -> None:
    top1 = btc_strategy_registry.get(STABLE_STRATEGY_LINE)
    result = _canonical_result(tmp_path, top1)

    manifest = write_btc_backtest_run_manifest(
        repo_root=tmp_path,
        spec=top1,
        result=result,
        request=_canonical_request(top1),
    )

    assert manifest["promotion_credit_allowed"] is True
    assert manifest["strategy_identity"]["candidate_id"] == top1.candidate_id
    assert manifest["ledger_binding"]["pnl_source"] == "ledger_fills"
    assert manifest["request_data_contract"]["observed"] == {
        "source": "sqlite",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "leverage": 1.0,
        "candidate_id": top1.candidate_id,
        "strategy_version": top1.strategy_version,
    }
    assert all(manifest["request_data_contract"]["checks"].values())
    assert manifest["gate"]["paper_queue_write_allowed"] is False
    assert manifest["gate"]["live_unlock_allowed"] is False
    assert load_latest_btc_backtest_manifest(tmp_path)["run_id"] == "run-1"

    run_manifest = tmp_path / manifest["outputs"]["manifest"]
    run_manifest.write_text("{}\n", encoding="utf-8")
    assert load_latest_btc_backtest_manifest(tmp_path) == {}


@pytest.mark.parametrize(
    ("missing_field", "failed_check"),
    [
        ("source", "canonical_request_source_is_sqlite"),
        ("symbol", "canonical_request_symbol_is_btcusdt"),
        ("interval", "canonical_request_interval_is_completed_1h"),
        ("leverage", "canonical_request_leverage_is_1x"),
        ("candidate_id", "canonical_request_candidate_explicit_and_matches"),
        ("strategy_version", "canonical_request_version_explicit_and_matches"),
    ],
)
def test_backtest_identity_manifest_fails_closed_when_request_field_missing(
    tmp_path,
    missing_field: str,
    failed_check: str,
) -> None:
    top1 = btc_strategy_registry.get(STABLE_STRATEGY_LINE)
    request = _canonical_request(top1)
    request.pop(missing_field)

    manifest = write_btc_backtest_run_manifest(
        repo_root=tmp_path,
        spec=top1,
        result=_canonical_result(tmp_path, top1),
        request=request,
    )

    _assert_request_failure_is_fail_closed(manifest, failed_check)


@pytest.mark.parametrize(
    ("field", "invalid_value", "failed_check"),
    [
        ("source", "parquet", "canonical_request_source_is_sqlite"),
        ("symbol", "ETHUSDT", "canonical_request_symbol_is_btcusdt"),
        ("interval", "4h", "canonical_request_interval_is_completed_1h"),
        ("leverage", 2.0, "canonical_request_leverage_is_1x"),
        ("candidate_id", "candidate-drift", "canonical_request_candidate_explicit_and_matches"),
        ("strategy_version", "version-drift", "canonical_request_version_explicit_and_matches"),
    ],
)
def test_backtest_identity_manifest_fails_closed_on_six_request_value_errors(
    tmp_path,
    field: str,
    invalid_value: object,
    failed_check: str,
) -> None:
    top1 = btc_strategy_registry.get(STABLE_STRATEGY_LINE)
    request = _canonical_request(top1)
    request[field] = invalid_value

    manifest = write_btc_backtest_run_manifest(
        repo_root=tmp_path,
        spec=top1,
        result=_canonical_result(tmp_path, top1),
        request=request,
    )

    _assert_request_failure_is_fail_closed(manifest, failed_check)


def _canonical_request(spec) -> dict[str, object]:
    return {
        "source": "sqlite",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "leverage": 1.0,
        "strategy_id": spec.strategy_id,
        "candidate_id": spec.candidate_id,
        "strategy_version": spec.strategy_version,
    }


def _canonical_result(tmp_path, spec) -> SimpleNamespace:
    canonical_manifest = tmp_path / "canonical" / "manifest.json"
    canonical_manifest.parent.mkdir(parents=True)
    canonical_manifest.write_text(
        '{"manifest_schema_version":"v1","run_id":"run-1"}\n',
        encoding="utf-8",
    )
    return SimpleNamespace(
        diagnostics={
            "run_id": "run-1",
            "manifest_path": str(canonical_manifest),
            "strategy_id": spec.strategy_id,
            "strategy_version": spec.strategy_version,
            "pnl_source": "ledger_fills",
            "ledger_equity_consistent": True,
            "ledger_artifact_path": "ledger.json",
            "ledger_hash": "ledger-hash",
            "fills_hash": "fills-hash",
        },
        unified=SimpleNamespace(evidence={"pnl": {"source": "ledger_fills"}}),
    )


def _assert_request_failure_is_fail_closed(manifest: dict[str, object], failed_check: str) -> None:
    assert manifest["status"] == "blocked_research_only"
    assert manifest["decision"] == "btc_strategy_identity_backtest_blocked_fail_closed_no_paper_no_live"
    assert manifest["promotion_credit_allowed"] is False
    assert f"btc_strategy_backtest:{failed_check}" in manifest["blockers"]
    gate = manifest["gate"]
    assert gate["paper_queue_write_allowed"] is False
    assert gate["paper_allowed"] is False
    assert gate["live_unlock_allowed"] is False
    assert gate["live_order_allowed"] is False
    assert gate["broker_or_order_allowed"] is False
    assert gate["order_endpoint_used"] is False
    assert gate["private_endpoint_used"] is False
    assert gate["real_order_submitted"] is False
