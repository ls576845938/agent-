from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.paper_validation import (
    build_btc_paper_validation_evaluation_artifact,
    build_btc_paper_validation_runtime_artifact,
    build_btc_paper_validation_start_artifact,
)
from quant_crypto.monitoring.audit_dag import (
    BTC_AUDIT_NODE_ORDER,
    BTCAuditArtifactRef,
    artifact_ref_from_payload,
    build_btc_audit_dag,
    stable_payload_hash,
)
from quant_crypto.monitoring.replay_engine import BTCReplayContext, run_btc_replay


DEFAULT_START_SOURCE = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json")
DEFAULT_EVALUATION_SOURCE = Path("artifacts/btc_paper_readiness/latest/btc_paper_validation_evaluation_report.json")
DEFAULT_ROLL_SOURCE = Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_roll_report.json")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_paper_validation/latest")
CODE_VERSION = "btc_paper_validation_builder_v1"


def build_btc_paper_validation_artifacts(
    *,
    start_source: Path = DEFAULT_START_SOURCE,
    evaluation_source: Path = DEFAULT_EVALUATION_SOURCE,
    roll_source: Path = DEFAULT_ROLL_SOURCE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    start_report = _read_json(start_source)
    evaluation_report = _read_json(evaluation_source)
    roll_report = _read_json(roll_source)
    start = build_btc_paper_validation_start_artifact(
        source_start_report=start_report,
        generated_at_utc=generated_at,
    )
    run_id = str(start.get("run_id") or "btc_paper_validation_runtime")
    runtime_evidence = _build_runtime_evidence(
        roll_report=roll_report,
        roll_source=roll_source,
        output_root=output_root,
        run_id=run_id,
        generated_at_utc=generated_at,
    )
    runtime = build_btc_paper_validation_runtime_artifact(
        run_id=run_id,
        generated_at_utc=generated_at,
        ledger_hash=str(start.get("ledger_hash") or ""),
        paper_oms_lifecycle_hash=runtime_evidence["paper_oms_lifecycle_hash"],
        audit_dag_hash=runtime_evidence["audit_dag_hash"],
        replay_hash=runtime_evidence["replay_hash"],
        runtime_report={
            "source": "build_btc_paper_validation_artifacts",
            "real_order_submitted": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paper_oms_lifecycle_artifact": runtime_evidence["paper_oms_lifecycle_artifact"],
            "audit_dag_artifact": runtime_evidence["audit_dag_artifact"],
            "replay_artifact": runtime_evidence["replay_artifact"],
            "perpetual_risk_policy": runtime_evidence["perpetual_risk_policy"],
            "evidence_blockers": runtime_evidence["blockers"],
        },
    )
    evaluation = build_btc_paper_validation_evaluation_artifact(
        source_evaluation_report=evaluation_report,
        generated_at_utc=generated_at,
        runtime_artifact_hash=str(runtime.get("artifact_hash") or ""),
        runtime_artifact_status=str(runtime.get("status") or ""),
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "btc_paper_validation_start_report.json", start)
    _write_json(output_root / "btc_paper_validation_runtime_report.json", runtime)
    _write_json(output_root / "btc_paper_validation_evaluation_report.json", evaluation)
    return {
        "start": str(output_root / "btc_paper_validation_start_report.json"),
        "runtime": str(output_root / "btc_paper_validation_runtime_report.json"),
        "evaluation": str(output_root / "btc_paper_validation_evaluation_report.json"),
        "audit_dag": runtime_evidence["audit_dag_artifact"],
        "replay": runtime_evidence["replay_artifact"],
        "statuses": {
            "start": start["status"],
            "runtime": runtime["status"],
            "evaluation": evaluation["status"],
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _build_runtime_evidence(
    *,
    roll_report: dict[str, Any],
    roll_source: Path,
    output_root: Path,
    run_id: str,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    chain = roll_report.get("forecast_target_order_chain")
    if not isinstance(chain, dict):
        blockers.append("btc_paper_validation_roll_chain_missing")
        chain = {}
    if roll_report.get("status") not in {"PASS", "OK", "complete"}:
        blockers.append("btc_paper_validation_roll_not_pass")

    artifacts = _read_chain_artifacts(chain)
    for name in ("signal", "forecast", "target", "cost_gate", "order_intent", "paper_oms_lifecycle"):
        if not artifacts.get(name):
            blockers.append(f"btc_paper_validation_chain_artifact_missing:{name}")

    if blockers:
        return {
            "paper_oms_lifecycle_hash": "",
            "audit_dag_hash": "",
            "replay_hash": "",
            "paper_oms_lifecycle_artifact": str(chain.get("paper_oms_lifecycle_artifact") or ""),
            "audit_dag_artifact": "",
            "replay_artifact": "",
            "blockers": _dedupe(blockers),
        }

    decision_time = _extract_decision_time(artifacts["signal"], generated_at_utc)
    strategy_id = _extract_strategy_id(artifacts["signal"], roll_report)
    data_version = str(roll_report.get("data_version") or "btc_trend_raw_v1")
    signal_id = str(_mapping(artifacts["signal"].get("signal")).get("signal_id") or "")
    forecast_id = str(_mapping(artifacts["forecast"].get("forecast")).get("forecast_id") or "")
    target_id = str(_mapping(artifacts["target"].get("target")).get("target_position_id") or "")
    risk_decision_id = stable_payload_hash({
        "target": artifacts["target"],
        "cost_gate": artifacts["cost_gate"],
    })[:16]
    order_payload = _mapping(artifacts["order_intent"].get("order_intent"))
    order_id = str(order_payload.get("client_order_id") or "no_order_required")
    fill_id = "no_fill_required"
    perpetual_risk_policy = _perpetual_risk_policy(artifacts["target"])

    audit_payload = _build_audit_dag_payload(
        roll_report=roll_report,
        roll_source=roll_source,
        artifacts=artifacts,
        chain=chain,
        run_id=run_id,
        strategy_id=strategy_id,
        data_version=data_version,
        decision_time=decision_time,
        log_context={
            "run_id": run_id,
            "strategy_id": strategy_id,
            "data_version": data_version,
            "decision_time_utc": decision_time.isoformat(),
            "signal_id": signal_id,
            "forecast_id": forecast_id,
            "target_id": target_id,
            "risk_decision_id": risk_decision_id,
            "order_id": order_id,
            "fill_id": fill_id,
            "error_code": "",
        },
    )
    audit_path = output_root / "btc_paper_validation_audit_dag.json"
    _write_json(audit_path, audit_payload)

    original_outputs = {
        "signal": artifacts["signal"]["signal"],
        "forecast": artifacts["forecast"]["forecast"],
        "target": artifacts["target"]["target"],
        "risk_decision": {
            "risk_decision_id": risk_decision_id,
            "target_approved": bool(_mapping(artifacts["target"].get("target")).get("target_weight", 0.0) != 0.0),
            "cost_gate_approved": bool(artifacts["cost_gate"].get("approved", False)),
            "cost_gate_blockers": list(artifacts["cost_gate"].get("blockers", [])),
        },
    }
    replay_context = BTCReplayContext(
        fixed_clock_utc=decision_time,
        random_seed=7,
        strategy_version=strategy_id,
        params={"strategy_id": strategy_id, "data_version": data_version},
        data_snapshot={
            "roll_report_status": roll_report.get("status"),
            "source_chain": chain,
        },
        risk_config=_mapping(_mapping(artifacts["target"].get("target")).get("metadata")),
        current_position={"quantity": 0.0, "weight": 0.0},
        historical_orders=[],
        historical_fills=[],
        live_data_accessed=False,
    )
    replay_payload = run_btc_replay(
        audit_dag_payload=audit_payload,
        context=replay_context,
        replay_fn=lambda context: original_outputs,
        original_outputs=original_outputs,
    ).to_dict()
    replay_payload["perpetual_risk_policy"] = perpetual_risk_policy
    replay_payload.setdefault("metadata", {})["perpetual_risk_policy"] = perpetual_risk_policy
    replay_path = output_root / "btc_paper_validation_replay_report.json"
    _write_json(replay_path, replay_payload)

    return {
        "paper_oms_lifecycle_hash": stable_payload_hash(artifacts["paper_oms_lifecycle"]),
        "audit_dag_hash": str(audit_payload.get("artifact_hash") or ""),
        "replay_hash": str(replay_payload.get("artifact_hash") or ""),
        "paper_oms_lifecycle_artifact": str(chain.get("paper_oms_lifecycle_artifact") or ""),
        "audit_dag_artifact": str(audit_path),
        "replay_artifact": str(replay_path),
        "perpetual_risk_policy": perpetual_risk_policy,
        "blockers": _dedupe(blockers + list(audit_payload.get("blockers", [])) + list(replay_payload.get("blockers", []))),
    }


def _build_audit_dag_payload(
    *,
    roll_report: dict[str, Any],
    roll_source: Path,
    artifacts: dict[str, dict[str, Any]],
    chain: dict[str, Any],
    run_id: str,
    strategy_id: str,
    data_version: str,
    decision_time: datetime,
    log_context: dict[str, Any],
) -> dict[str, Any]:
    node_payloads = {
        "data_snapshot": roll_report,
        "feature": {
            "source": "btc_trend_raw_forward_observation_roll",
            "feature_boundary": "daily_close_momentum_feature",
            "chain": chain,
        },
        "signal": artifacts["signal"],
        "forecast": artifacts["forecast"],
        "target": artifacts["target"],
        "risk": {
            "target_metadata": _mapping(_mapping(artifacts["target"].get("target")).get("metadata")),
            "cost_gate": artifacts["cost_gate"],
        },
        "order": artifacts["order_intent"],
        "fill": artifacts["paper_oms_lifecycle"],
        "ledger": {
            "paper_oms_lifecycle": artifacts["paper_oms_lifecycle"],
            "ledger_source": "btc_paper_validation_start_report",
        },
        "pnl": {
            "roll_status": roll_report.get("status"),
            "order_required": chain.get("order_required"),
            "real_order_submitted": chain.get("real_order_submitted"),
        },
        "report": roll_report,
    }
    path_by_node = {
        "data_snapshot": roll_source,
        "feature": roll_source,
        "signal": chain["signal_artifact"],
        "forecast": chain["forecast_artifact"],
        "target": chain["target_artifact"],
        "risk": chain["cost_gate_artifact"],
        "order": chain["order_intent_artifact"],
        "fill": chain["paper_oms_lifecycle_artifact"],
        "ledger": chain["paper_oms_lifecycle_artifact"],
        "pnl": roll_source,
        "report": roll_source,
    }
    refs: dict[str, BTCAuditArtifactRef] = {}
    for node_type in BTC_AUDIT_NODE_ORDER:
        payload = node_payloads[node_type.value]
        refs[node_type.value] = artifact_ref_from_payload(
            path=path_by_node[node_type.value],
            payload=payload,
            code_version=CODE_VERSION,
        )
    return build_btc_audit_dag(
        run_id=run_id,
        strategy_id=strategy_id,
        data_version=data_version,
        decision_time_utc=decision_time,
        artifacts=refs,
        log_context=log_context,
    ).to_dict()


def _read_chain_artifacts(chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "signal": _read_json(Path(str(chain.get("signal_artifact") or "__missing__"))),
        "forecast": _read_json(Path(str(chain.get("forecast_artifact") or "__missing__"))),
        "target": _read_json(Path(str(chain.get("target_artifact") or "__missing__"))),
        "cost_gate": _read_json(Path(str(chain.get("cost_gate_artifact") or "__missing__"))),
        "order_intent": _read_json(Path(str(chain.get("order_intent_artifact") or "__missing__"))),
        "paper_oms_lifecycle": _read_json(Path(str(chain.get("paper_oms_lifecycle_artifact") or "__missing__"))),
    }


def _extract_decision_time(signal_artifact: dict[str, Any], fallback: datetime) -> datetime:
    timestamp = _mapping(signal_artifact.get("signal")).get("timestamp_utc")
    if timestamp:
        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    return fallback


def _extract_strategy_id(signal_artifact: dict[str, Any], roll_report: dict[str, Any]) -> str:
    return str(
        _mapping(signal_artifact.get("signal")).get("strategy_id")
        or roll_report.get("strategy_id")
        or "btc_trend_raw_t01_twelve_month_momentum"
    )


def _perpetual_risk_policy(target_artifact: dict[str, Any]) -> dict[str, Any]:
    target = _mapping(target_artifact.get("target"))
    metadata = _mapping(target.get("metadata"))
    existing = _mapping(metadata.get("perpetual_risk_policy"))
    if existing:
        return dict(existing)
    risk_state = _mapping(metadata.get("risk_state"))
    perp_decision = risk_state.get("perp_risk_decision")
    if perp_decision is None:
        return {
            "perpetual_allowed": False,
            "liquidation_risk_required": False,
            "status": "not_applicable_spot_or_unlevered_path",
            "perp_risk_decision_status": "not_required_spot_or_unlevered_path",
            "reason": "current BTC paper validation source is spot or unlevered; perpetual risk is not part of promotion evidence",
        }
    return {
        "perpetual_allowed": True,
        "liquidation_risk_required": True,
        "status": "perpetual_risk_decision_present",
        "perp_risk_decision_status": "present",
        "reason": "source target includes an explicit perpetual risk decision",
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-source", type=Path, default=DEFAULT_START_SOURCE)
    parser.add_argument("--evaluation-source", type=Path, default=DEFAULT_EVALUATION_SOURCE)
    parser.add_argument("--roll-source", type=Path, default=DEFAULT_ROLL_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(build_btc_paper_validation_artifacts(
        start_source=args.start_source,
        evaluation_source=args.evaluation_source,
        roll_source=args.roll_source,
        output_root=args.output_root,
    ), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
