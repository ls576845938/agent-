from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.gate_dashboard import build_btc_gate_dashboard, load_json_or_none


DEFAULT_OUTPUT = Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json")
DEFAULT_CURRENT_STATUS = Path("artifacts/btc_current_status/latest/btc_current_status_report.json")
DEFAULT_REGISTRY = Path("artifacts/global_research_registry/research_registry.json")
DEFAULT_PAPER_READINESS = Path("artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json")
DEFAULT_PROMOTION_GATE_CONTROL = Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json")
DEFAULT_ARTIFACTS = {
    "exchange_runtime_contract": Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_contract.json"),
    "daily_observation": Path("artifacts/btc_trend_v0/latest/btc_trend_raw_forward_observation_daily_run_report.json"),
    "cost_model": Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json"),
    "funding_ledger": Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json"),
    "perpetual_route_request": Path("artifacts/btc_perpetual_route_request/latest/btc_perpetual_route_request_report.json"),
    "perpetual_policy_status": Path("artifacts/btc_perpetual_policy/latest/btc_perpetual_policy_status_report.json"),
    "perpetual_execution_evidence": Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"),
    "paper_validation_start": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_start_report.json"),
    "paper_validation_runtime": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_runtime_report.json"),
    "paper_validation_evaluation": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_evaluation_report.json"),
    "api_key_permission_audit": Path("artifacts/btc_security/latest/btc_api_key_permission_audit.json"),
    "order_surface_audit": Path("artifacts/btc_security/latest/btc_order_surface_audit_report.json"),
    "account_attestation": Path("artifacts/btc_exchange_runtime/latest/btc_paper_account_runtime_attestation_report.json"),
    "live_readiness": Path("artifacts/btc_live_readiness/latest/btc_live_readiness_risk_constitution_report.json"),
    "micro_live_preflight": Path("artifacts/btc_micro_live_preflight/latest/btc_micro_live_preflight_report.json"),
    "trend_boundary": Path("artifacts/btc_trend_v0/latest/btc_trend_boundary_report.json"),
}


def build_btc_gate_dashboard_file(
    *,
    output: Path = DEFAULT_OUTPUT,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
    promotion_gate_control: dict | None = None,
    use_promotion_gate_control: bool = True,
) -> dict:
    generated = generated_at_utc or datetime.now(timezone.utc)
    promotion_source = (
        promotion_gate_control
        if promotion_gate_control is not None
        else (load_json_or_none(DEFAULT_PROMOTION_GATE_CONTROL) or {}) if use_promotion_gate_control else {}
    )
    payload = build_btc_gate_dashboard(
        generated_at_utc=generated,
        current_status=load_json_or_none(DEFAULT_CURRENT_STATUS) or {},
        registry=load_json_or_none(DEFAULT_REGISTRY) or {},
        paper_readiness=load_json_or_none(DEFAULT_PAPER_READINESS) or {},
        artifacts={name: load_json_or_none(path) for name, path in DEFAULT_ARTIFACTS.items()},
        aggregation_batch_id=aggregation_batch_id,
        promotion_gate_control=promotion_source,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--aggregation-batch-id", default="")
    args = parser.parse_args()
    payload = build_btc_gate_dashboard_file(output=args.output, aggregation_batch_id=args.aggregation_batch_id or None)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
