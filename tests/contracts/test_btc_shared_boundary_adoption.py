from __future__ import annotations

import ast
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_shared.core import canonical_payload_hash
from quant_shared.evidence import FreshnessAssessment
from quant_shared.replay import validate_replay_input

from quant_crypto.adapters.shared_platform import (
    BTC_SHARED_BOUNDARY_VERSION,
    build_btc_evidence_reference,
    build_btc_ledger_record,
    build_btc_read_model_snapshot,
    build_btc_replay_input,
    new_btc_id,
)
from quant_crypto.monitoring.artifact_schema import stable_payload_hash
from quant_crypto.monitoring.replay_engine import BTCReplayContext
from quant_crypto.oms.lifecycle import BTCPaperOrderStatus
from quant_crypto.risk.liquidation import BTCLiquidationPolicy
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)


ALLOWLIST_PATH = Path("quant_crypto/shared_boundary_allowlist.json")


def _direct_quant_us_imports() -> list[dict[str, object]]:
    imports: list[dict[str, object]] = []
    for path in sorted(Path("quant_crypto").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "quant_us" or node.module.startswith("quant_us.")
            ):
                imports.append(
                    {
                        "path": path.as_posix(),
                        "module": node.module,
                        "names": sorted(alias.name for alias in node.names),
                    }
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "quant_us" or alias.name.startswith("quant_us."):
                        imports.append(
                            {
                                "path": path.as_posix(),
                                "module": alias.name,
                                "names": [alias.name],
                            }
                        )
    return imports


def test_quant_crypto_quant_us_dependency_baseline_is_reduced_and_fully_allowlisted() -> None:
    allowlist = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    imports = _direct_quant_us_imports()
    expected = [
        {
            "path": item["path"],
            "module": item["module"],
            "names": sorted(item["names"]),
        }
        for item in allowlist["allowed_imports"]
    ]
    assert allowlist["baseline_direct_import_statements"] == 34
    assert allowlist["baseline_direct_import_files"] == 26
    assert allowlist["schema_version"] == "btc_quant_us_dependency_allowlist_v2"
    assert allowlist["maximum_allowed_direct_import_statements"] == 0
    assert imports == expected == []


def test_btc_trading_contracts_have_one_identity_and_legacy_shim_only_reexports() -> None:
    from quant_crypto.adapters import legacy_quant_us

    canonical_types = (
        OrderIntent,
        OrderSide,
        OrderType,
        RiskDecision,
        Signal,
        SignalDirection,
        TargetPosition,
        TimeInForce,
    )
    assert all(value.__module__ == "quant_crypto.trading_contracts" for value in canonical_types)
    assert legacy_quant_us.OrderIntent is OrderIntent
    assert legacy_quant_us.OrderSide is OrderSide
    assert legacy_quant_us.OrderType is OrderType
    assert legacy_quant_us.RiskDecision is RiskDecision
    assert legacy_quant_us.Signal is Signal
    assert legacy_quant_us.SignalDirection is SignalDirection
    assert legacy_quant_us.TargetPosition is TargetPosition
    assert legacy_quant_us.TimeInForce is TimeInForce


def test_btc_trading_contract_wire_values_fields_and_serialization_are_stable() -> None:
    shifted = datetime(2026, 7, 24, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    signal = Signal(
        timestamp_utc=shifted,
        strategy_id="btc-v1",
        symbol="btcusdt",
        direction=SignalDirection.LONG,
        strength=1.2,
        horizon="1h",
        signal_id="sig_fixture",
    )
    target = TargetPosition(
        timestamp_utc=shifted,
        strategy_id="btc-v1",
        symbol="btcusdt",
        target_weight=0.1,
        target_quantity=0.01,
        signal_id=signal.signal_id,
        target_position_id="tgt_fixture",
    )
    intent = OrderIntent(
        timestamp_utc=shifted,
        strategy_id="btc-v1",
        symbol="btcusdt",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=60_000.0,
        time_in_force=TimeInForce.IOC,
        signal_id=signal.signal_id,
        target_position_id=target.target_position_id,
        client_order_id="coid_fixture",
        order_intent_id="oint_fixture",
    )
    risk = RiskDecision(
        approved=False,
        reason="fixture_fail_closed",
        order_intent_id=intent.order_intent_id,
        checked_at=shifted,
        risk_check_id="risk_fixture",
    )

    assert signal.timestamp_utc.isoformat() == "2026-07-24T01:30:00+00:00"
    assert signal.symbol == target.symbol == intent.symbol == "BTCUSDT"
    assert signal.strength == 1.0
    assert intent.quantity == 1.0
    assert [value.value for value in SignalDirection] == ["long", "short", "flat"]
    assert [value.value for value in OrderSide] == ["buy", "sell"]
    assert [value.value for value in OrderType] == ["market", "limit", "stop"]
    assert [value.value for value in TimeInForce] == ["day", "gtc", "ioc", "fok"]
    payload = {
        "signal": asdict(signal),
        "target": asdict(target),
        "intent": asdict(intent),
        "risk": asdict(risk),
    }
    assert canonical_payload_hash(payload) == stable_payload_hash(payload)


def test_quant_crypto_uses_shared_utc_and_canonical_serialization() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("quant_crypto").rglob("*.py"))
    assert "quant_us.core.clock" not in source
    shifted = datetime(2026, 7, 24, 9, 30, tzinfo=timezone(timedelta(hours=8)))
    payload = {"at": shifted, "nested": {"b": 2, "a": 1}}
    assert stable_payload_hash(payload) == canonical_payload_hash(payload)


def test_btc_adapter_preserves_shared_identity_evidence_ledger_and_read_model_contracts() -> None:
    now = datetime(2026, 7, 24, 1, 30, tzinfo=timezone.utc)
    runtime_id = new_btc_id("run")
    assert runtime_id.startswith("run_")
    digest = canonical_payload_hash({"run_id": runtime_id})
    evidence = build_btc_evidence_reference(
        evidence_id="btc-evidence-01",
        path="immutable/btc/evidence.json",
        sha256=digest,
        schema_version="btc_evidence_v1",
        generated_at_utc=now,
        code_commit="07e32a043a3fd48e5b50f67dd90ed59679bf6af7",
    )
    ledger = build_btc_ledger_record(
        stream_id="btc-ledger-01",
        record_id="btc-fill-01",
        sequence=1,
        occurred_at_utc=now,
        record_type="btc_funding_cashflow",
        payload={"funding_rate": -0.0001, "venue": "fixture"},
    )
    freshness = FreshnessAssessment(
        status="pass",
        blockers=(),
        missing_count=0,
        stale_count=0,
        future_count=0,
        code_commit_mismatch_count=0,
        dependency_newer_count=0,
    )
    read_model = build_btc_read_model_snapshot(
        snapshot_id="btc-read-model-01",
        generated_at_utc=now,
        code_commit="07e32a043a3fd48e5b50f67dd90ed59679bf6af7",
        data_version="fixture-v1",
        status="pass",
        decision="quality_checked",
        freshness=freshness,
        evidence=(evidence,),
        metadata={"paper_allowed": False, "live_allowed": False},
    )
    assert evidence.contract_version == "shared_evidence_reference_v2"
    assert ledger.contract_version == "shared_ledger_record_v2"
    assert ledger.record_type == "btc_funding_cashflow"
    assert read_model.contract_version == "shared_read_model_snapshot_v2"
    assert read_model.metadata["btc_shared_boundary_version"] == BTC_SHARED_BOUNDARY_VERSION
    assert read_model.metadata["paper_allowed"] is False
    assert read_model.metadata["live_allowed"] is False


def test_btc_replay_adopts_injected_history_contract_without_live_access() -> None:
    fixed_clock = datetime(2026, 7, 24, 1, 30, tzinfo=timezone.utc)
    replay_input = build_btc_replay_input(
        fixed_clock_utc=fixed_clock,
        random_seed=7,
        strategy_version="btc-fixture-v1",
        params={"lookback": 20},
        data_snapshot={"data_version": "fixture-v1", "close": 100.0},
        risk_config={"max_leverage": 1.0},
        current_position={"quantity": 0.0},
        historical_orders=({"timestamp_utc": fixed_clock.isoformat(), "order_id": "order-1"},),
        historical_fills=({"timestamp_utc": fixed_clock.isoformat(), "fill_id": "fill-1"},),
    )
    assert replay_input.source_mode == "injected_history"
    assert validate_replay_input(replay_input) == ()
    assert [event.event_type for event in replay_input.events] == ["btc_fill", "btc_order"]

    context = BTCReplayContext(
        fixed_clock_utc=fixed_clock,
        random_seed=7,
        strategy_version="btc-fixture-v1",
        params={"lookback": 20},
        data_snapshot={"data_version": "fixture-v1", "close": 100.0},
        risk_config={"max_leverage": 1.0},
        current_position={"quantity": 0.0},
        historical_orders=[{"timestamp_utc": fixed_clock.isoformat(), "order_id": "order-1"}],
        historical_fills=[{"timestamp_utc": fixed_clock.isoformat(), "fill_id": "fill-1"}],
    )
    assert context.to_shared_replay_input() == replay_input


def test_btc_specific_lifecycle_and_liquidation_semantics_remain_in_quant_crypto() -> None:
    assert BTCPaperOrderStatus.__module__ == "quant_crypto.oms.lifecycle"
    assert BTCLiquidationPolicy.__module__ == "quant_crypto.risk.liquidation"
