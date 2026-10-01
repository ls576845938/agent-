from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import settings
from quant_crypto.oms.account_risk_facts import (
    AccountRiskFactError,
    load_reviewed_account_facts_approval,
)
from quant_crypto.oms.okx_demo_paper_runtime import (
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
)


def _load_snapshot(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AccountRiskFactError("sealed_snapshot_invalid") from exc
    if not isinstance(value, Mapping):
        raise AccountRiskFactError("sealed_snapshot_invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Register one externally reviewed BTC Demo account drawdown baseline "
            "without starting Demo or opening a private client."
        )
    )
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--sealed-snapshot", type=Path, required=True)
    args = parser.parse_args()

    registry = str(settings.btc_demo_account_facts_approval_registry or "").strip()
    configured_id = str(settings.btc_demo_account_facts_approval_id or "").strip()
    runtime_identity = str(settings.btc_demo_runtime_identity or "").strip()
    if not registry or not configured_id or not runtime_identity:
        raise AccountRiskFactError("account_facts_server_config_incomplete")
    if args.approval_id != configured_id:
        raise AccountRiskFactError("approval_id_mismatch")

    def resolver(approval_id: str) -> Mapping[str, Any] | None:
        return load_reviewed_account_facts_approval(
            registry_path=registry,
            approval_id=approval_id,
            repo_root=settings.repo_root,
        )

    controller = OkxDemoPaperRuntimeController(
        config=OkxDemoPaperRuntimeConfig(
            repo_root=settings.repo_root,
            data_db_path=Path(settings.data_db_path),
            runtime_identity=runtime_identity,
            account_facts_approval_resolver=resolver,
            account_facts_approval_id=configured_id,
        ),
        credential_loader=lambda _service: (_ for _ in ()).throw(
            AccountRiskFactError("credential_access_forbidden_for_baseline_registration")
        ),
        start_worker=False,
    )
    result = controller.register_reviewed_account_drawdown_baseline(
        approval_id=args.approval_id,
        snapshot=_load_snapshot(args.sealed_snapshot.resolve()),
    )
    fact = result["account_drawdown_fact"]
    print(
        json.dumps(
            {
                "status": result["status"],
                "approval_id": configured_id,
                "fact_digest": fact.get("fact_digest"),
                "history_complete": fact.get("history_complete"),
                "risk_eligible": fact.get("risk_eligible"),
                "safety_flags_changed": result.get("safety_flags_changed"),
                "demo_started": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
