from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.monitoring.completion_audit import build_btc_completion_audit, load_completion_artifacts


DEFAULT_OUTPUT = Path("artifacts/btc_completion_audit/latest/btc_completion_audit.json")
DEFAULT_ARTIFACTS = {
    "exchange_runtime_contract": Path("artifacts/btc_exchange_runtime/latest/btc_exchange_runtime_contract.json"),
    "liquidation_risk_contract": Path("artifacts/btc_completion_evidence/latest/liquidation_risk_contract.json"),
    "paper_validation_start": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_start_report.json"),
    "paper_validation_runtime": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_runtime_report.json"),
    "paper_validation_evaluation": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_evaluation_report.json"),
    "paper_validation_audit_dag": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_audit_dag.json"),
    "paper_validation_replay": Path("artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json"),
    "api_key_permission_audit": Path("artifacts/btc_security/latest/btc_api_key_permission_audit.json"),
    "trend_boundary": Path("artifacts/btc_trend_v0/latest/btc_trend_boundary_report.json"),
    "source_role_contract": Path("artifacts/btc_completion_evidence/latest/source_role_contract.json"),
    "paper_oms_session_contract": Path("artifacts/btc_completion_evidence/latest/paper_oms_session_contract.json"),
    "incident_replay_drill_contract": Path("artifacts/btc_completion_evidence/latest/incident_replay_drill_contract.json"),
    "gate_dashboard": Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"),
}


def build_btc_completion_audit_file(*, output: Path = DEFAULT_OUTPUT) -> dict:
    payload = build_btc_completion_audit(
        generated_at_utc=datetime.now(timezone.utc),
        artifacts=load_completion_artifacts(DEFAULT_ARTIFACTS),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_btc_completion_audit_file(output=args.output)
    print(json.dumps({
        "output": str(args.output),
        "status": payload["status"],
        "summary": payload["summary"],
        "blockers": payload["blockers"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
