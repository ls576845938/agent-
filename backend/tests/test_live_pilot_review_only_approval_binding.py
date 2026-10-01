from __future__ import annotations

import json
from pathlib import Path

from quant_us.live.live_pilot_approval import HumanApprovalGate
from quant_us.live.live_pilot_dossier import DesignFreeze, LivePilotReadinessDossier


def _write_dossier(path: Path, dossier: LivePilotReadinessDossier) -> None:
    path.write_text(json.dumps(dossier.to_dict(), indent=2), encoding="utf-8")


def test_approval_record_binds_design_freeze_and_stays_review_only(tmp_path: Path) -> None:
    dossier_path = tmp_path / "dossier.json"
    dossier = LivePilotReadinessDossier()
    _write_dossier(dossier_path, dossier)

    gate = HumanApprovalGate(store_path=str(tmp_path / "approvals"))
    draft = gate.create(
        approval_id="approval_001",
        strategy_id="etf_rotation",
        strategy_version="1.0.0",
        symbols=["SPY", "QQQ"],
        requested_by="risk_reviewer",
        readiness_dossier_path=str(dossier_path),
    )
    approved = gate.approve("approval_001", approver="risk_committee")

    assert draft.design_freeze_version == dossier.design_freeze.version
    assert draft.design_freeze_hash == dossier.design_freeze.hash
    assert draft.design_freeze_scope == dossier.design_freeze.scope
    assert approved.review_only is True
    assert approved.execution_authorized is False
    assert approved.status == "APPROVED"


def test_approval_becomes_invalid_when_dossier_design_freeze_binding_mismatches(
    tmp_path: Path,
) -> None:
    dossier_path = tmp_path / "dossier.json"
    dossier = LivePilotReadinessDossier()
    _write_dossier(dossier_path, dossier)

    gate = HumanApprovalGate(store_path=str(tmp_path / "approvals"))
    gate.create(
        approval_id="approval_002",
        strategy_id="etf_rotation",
        strategy_version="1.0.0",
        symbols=["SPY"],
        requested_by="risk_reviewer",
        readiness_dossier_path=str(dossier_path),
    )
    gate.approve("approval_002", approver="risk_committee")

    mismatched = LivePilotReadinessDossier(
        dossier_id=dossier.dossier_id,
        design_freeze=DesignFreeze(
            version="micro-live-review-only-v2",
            hash="mismatch-freeze-hash",
            scope="review_only",
            frozen=True,
            no_continuous_loop=True,
            manual_approval_required=True,
            max_symbols=1,
            max_notional=50.0,
            max_orders=1,
        ),
    )
    _write_dossier(dossier_path, mismatched)

    result = gate.check(
        approval_id="approval_002",
        strategy_version="1.0.0",
        symbols=["SPY"],
    )
    reloaded = gate.inspect("approval_002")

    assert result.passed is False
    assert result.status == "INVALID"
    assert result.checks["design_freeze_binding_match"] is False
    assert reloaded is not None
    assert reloaded.status == "INVALID"
    assert reloaded.execution_authorized is False
