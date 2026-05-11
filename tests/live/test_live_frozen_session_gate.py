from __future__ import annotations

from pathlib import Path

from quant_us.live.g8_session_gate import SessionGate
from quant_us.live.g8_session_state import SessionStatus


def test_g8_frozen_session_reports_session_frozen_before_not_armed(tmp_path: Path) -> None:
    gate = SessionGate(data_root=str(tmp_path))
    promotion_id = "promo_frozen_reason"
    session = gate.state_mgr.create(promotion_id=promotion_id, session_id="session_frozen_reason")
    gate.create_promotion(promotion_id)
    gate.approve_promotion(promotion_id)
    gate.state_mgr.arm(session.session_id)
    gate.state_mgr.activate(session.session_id)
    frozen = gate.state_mgr.freeze(session.session_id, reason="ORDER_SUBMITTED")

    assert frozen.status == SessionStatus.FROZEN
    decision = gate.check(
        session_id=session.session_id,
        promotion_id=promotion_id,
        ticket_id="ticket_after_freeze",
        proposed_notional=100.0,
        manual_confirm=True,
        dry_run=False,
    )

    assert decision.decision == "BLOCKED"
    assert decision.block_reasons == ["session_frozen"]
