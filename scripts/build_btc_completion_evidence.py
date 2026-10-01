from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.data.source_role_report import build_btc_source_role_report
from quant_crypto.monitoring.artifact_schema import apply_btc_artifact_schema, stable_payload_hash
from quant_crypto.monitoring.incident import BTCIncidentTrigger
from quant_crypto.monitoring.incident_replay_drill import BTCIncidentReplayDrillScenario, build_btc_incident_replay_drill
from quant_crypto.oms.execution_quality import BTCExecutionFill
from quant_crypto.oms.lifecycle import BTCPaperOrderLifecycle
from quant_crypto.oms.session_reconciliation import build_btc_paper_oms_session_reconciliation
from quant_crypto.risk.liquidation import (
    BTCPerpPositionState,
    BTCReferencePriceState,
    BTCLiquidationPolicy,
    evaluate_btc_perp_liquidation_risk,
)
from quant_crypto.trading_contracts import OrderIntent, OrderSide


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_completion_evidence/latest")
HASH = "a" * 64


def build_btc_completion_evidence_files(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    generated_at_utc: datetime | None = None,
) -> dict[str, str]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    output_root.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "liquidation_risk_contract": _liquidation_contract(generated_at),
        "source_role_contract": _source_role_contract(generated_at),
        "paper_oms_session_contract": _paper_oms_session_contract(generated_at),
        "incident_replay_drill_contract": _incident_replay_drill_contract(generated_at),
    }
    outputs: dict[str, str] = {}
    for name, payload in artifacts.items():
        path = output_root / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        outputs[name] = str(path)
    return outputs


def _liquidation_contract(generated_at: datetime) -> dict:
    decision = evaluate_btc_perp_liquidation_risk(
        reference_prices=BTCReferencePriceState(
            observed_at_utc=generated_at,
            signal_price=100_000.0,
            execution_price=100_000.0,
            mark_price=100_010.0,
            index_price=99_990.0,
            current_mark_price=100_005.0,
            primary_mid=100_002.0,
            secondary_reference_mid=100_000.0,
            spread_bps=1.0,
            cross_venue_deviation_bps=2.0,
            data_age_ms=500,
            order_book_depth_usd=1_000_000.0,
            source="contract_fixture",
        ),
        position=BTCPerpPositionState(current_quantity=0.0, proposed_quantity=0.01, account_equity=10_000.0),
        policy=BTCLiquidationPolicy(
            max_leverage=2.0,
            maintenance_margin_rate=0.005,
            min_liquidation_buffer_bps=1_000.0,
            max_reference_price_age_ms=5_000,
            max_cross_venue_deviation_bps=50.0,
            max_spread_bps=10.0,
            min_order_book_depth_usd=100_000.0,
        ),
    )
    payload = {
        "status": "complete" if decision.approved else "blocked",
        "risk_model": "btc_perp_liquidation_risk_v1",
        "decision_metadata": decision.to_metadata(),
        "mark_index_current_mark_required": True,
        "liquidation_buffer_required": True,
        "target_risk_action": decision.action,
        "blockers": list(decision.blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="liquidation_risk_contract_complete" if decision.approved else "liquidation_risk_contract_blocked",
        generated_at_utc=generated_at,
        as_of_utc=generated_at,
        blockers=list(decision.blockers),
        warnings=list(decision.warnings),
        input_hashes={"decision": stable_payload_hash(decision.to_metadata())},
    )


def _source_role_contract(generated_at: datetime) -> dict:
    rows = [
        _source_row(generated_at - timedelta(minutes=2), generated_at - timedelta(minutes=1, seconds=55)),
        _source_row(generated_at - timedelta(minutes=1), generated_at - timedelta(seconds=55)),
        _source_row(generated_at, generated_at + timedelta(seconds=5)),
    ]
    return build_btc_source_role_report(
        role="klines_1m",
        source_path=Path("contract_fixture/btc_klines_1m.json"),
        generated_at_utc=generated_at,
        decision_time_utc=generated_at,
        rows=rows,
        gapfill_events=[],
    )


def _paper_oms_session_contract(generated_at: datetime) -> dict:
    intent = OrderIntent(
        timestamp_utc=generated_at,
        strategy_id="btc_completion_contract",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.01,
        target_position_id="tgt_contract",
        metadata={"arrival_price": 100_000.0, "reference_price": 100_000.0},
        client_order_id="coid_contract_001",
        order_intent_id="oint_contract_001",
    )
    lifecycle = BTCPaperOrderLifecycle(order_intent=intent)
    lifecycle.mark_risk_checked(approved=True)
    lifecycle.mark_submitted(broker_order_id="paper_broker_order_001")
    lifecycle.mark_accepted(broker_order_id="paper_broker_order_001")
    lifecycle.apply_fill(fill_quantity=0.01, timestamp_utc=generated_at + timedelta(seconds=1), fill_id="fill_contract_001", price=100_001.0)
    lifecycle.reconcile(metadata={"ledger_hash": HASH})
    fill = BTCExecutionFill(
        client_order_id="coid_contract_001",
        fill_id="fill_contract_001",
        filled_quantity=0.01,
        arrival_price=100_000.0,
        fill_price=100_001.0,
        benchmark_price=100_000.5,
        submitted_at_utc=generated_at,
        filled_at_utc=generated_at + timedelta(seconds=1),
        fee=0.01,
    )
    return build_btc_paper_oms_session_reconciliation(
        session_id="btc_completion_contract_session",
        orders=[lifecycle],
        fills=[fill],
        ledger_hash=HASH,
        generated_at_utc=generated_at,
        opportunity_benchmark_price=100_002.0,
    )


def _incident_replay_drill_contract(generated_at: datetime) -> dict:
    scenarios = [
        BTCIncidentReplayDrillScenario(
            name="data_outage",
            trigger=BTCIncidentTrigger.DATA_INTERRUPTION,
            regression_test="tests/contracts/test_btc_incident_replay_drill.py::test_btc_incident_replay_drill_requires_core_scenarios_and_artifacts",
            replay_artifact_hash=HASH,
            audit_dag_hash=HASH,
            source_refs={"contract": "btc_completion_evidence"},
            detected_at_utc=generated_at,
            run_id="btc_completion_contract",
            strategy_id="btc_completion_contract",
        ),
        BTCIncidentReplayDrillScenario(
            name="funding_gap",
            trigger=BTCIncidentTrigger.FUNDING_GAP,
            regression_test="tests/contracts/test_btc_incident_replay_drill.py::test_btc_incident_replay_drill_requires_core_scenarios_and_artifacts",
            replay_artifact_hash=HASH,
            audit_dag_hash=HASH,
            source_refs={"contract": "btc_completion_evidence", "funding_gap_report": "contract_fixture/funding_gap_report.json"},
            detected_at_utc=generated_at,
            run_id="btc_completion_contract",
            strategy_id="btc_completion_contract",
        ),
        BTCIncidentReplayDrillScenario(
            name="order_reject",
            trigger=BTCIncidentTrigger.ORDER_REJECT,
            regression_test="tests/contracts/test_btc_incident_replay_drill.py::test_btc_incident_replay_drill_requires_core_scenarios_and_artifacts",
            replay_artifact_hash=HASH,
            audit_dag_hash=HASH,
            source_refs={"contract": "btc_completion_evidence"},
            detected_at_utc=generated_at,
            run_id="btc_completion_contract",
            strategy_id="btc_completion_contract",
        ),
        BTCIncidentReplayDrillScenario(
            name="ledger_mismatch",
            trigger=BTCIncidentTrigger.LEDGER_MISMATCH,
            regression_test="tests/contracts/test_btc_incident_replay_drill.py::test_btc_incident_replay_drill_requires_core_scenarios_and_artifacts",
            replay_artifact_hash=HASH,
            audit_dag_hash=HASH,
            source_refs={"contract": "btc_completion_evidence"},
            detected_at_utc=generated_at,
            run_id="btc_completion_contract",
            strategy_id="btc_completion_contract",
        ),
    ]
    return build_btc_incident_replay_drill(scenarios=scenarios, generated_at_utc=generated_at)


def _source_row(event_time: datetime, available_time: datetime) -> dict:
    return {
        "event_time": event_time.isoformat(),
        "available_time": available_time.isoformat(),
        "ingested_at": (available_time + timedelta(seconds=1)).isoformat(),
        "processed_at": (available_time + timedelta(seconds=2)).isoformat(),
        "is_final": True,
        "close": 100_000.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_btc_completion_evidence_files(output_root=args.output_root)
    print(json.dumps({"outputs": outputs}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
