from __future__ import annotations

import json
from pathlib import Path

from quant_us.live.manual_decision_record import evaluate_manual_decision_local_init
from scripts.init_us_equity_manual_decision_record_local import (
    init_us_equity_manual_decision_record_local,
)


def test_manual_decision_local_init_copies_safe_template_without_unlocking(tmp_path: Path) -> None:
    _write_template(tmp_path)

    payload = init_us_equity_manual_decision_record_local(
        repo_root=tmp_path,
        generated_at="2026-06-27T00:00:00Z",
    )

    local = tmp_path / "configs/reviews/us_equity_manual_decision_record.local.json"
    report = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_local_init_report.json"
    assert payload["status"] == "manual_decision_local_initialized"
    assert payload["local_record_exists_after"] is True
    assert payload["actions"] == ["manual_decision_template_copied"]
    assert payload["guardrails"]["manual_approval_recorded_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert local.exists()
    assert report.exists()
    copied = json.loads(local.read_text(encoding="utf-8"))
    assert copied["schema_version"] == "us_equity_manual_decision_record_v1"
    assert copied["paper_simulation_allowed"] is False
    assert copied["live_order_allowed"] is False


def test_manual_decision_local_init_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    _write_template(tmp_path)
    local = tmp_path / "configs/reviews/us_equity_manual_decision_record.local.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps({"existing": True}), encoding="utf-8")

    payload = init_us_equity_manual_decision_record_local(
        repo_root=tmp_path,
        generated_at="2026-06-27T00:00:00Z",
    )

    assert payload["status"] == "manual_decision_local_init_blocked"
    assert "manual_decision_local_record_already_exists" in payload["blockers"]
    assert json.loads(local.read_text(encoding="utf-8")) == {"existing": True}


def test_manual_decision_local_init_blocks_unsafe_template_defaults(tmp_path: Path) -> None:
    _write_template(tmp_path, extra={"live_order_allowed": True})

    payload = init_us_equity_manual_decision_record_local(
        repo_root=tmp_path,
        generated_at="2026-06-27T00:00:00Z",
    )

    assert payload["status"] == "manual_decision_local_init_blocked"
    assert "manual_decision_template_forbidden_true_default:live_order_allowed" in payload["blockers"]
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_manual_decision_local_init_service_blocks_unsafe_defaults_without_filesystem() -> None:
    payload = _template_payload({"paper_simulation_allowed": True})

    evaluation = evaluate_manual_decision_local_init(
        template=payload,
        template_exists=True,
        local_record_exists=False,
        force=False,
    )

    assert evaluation.status == "manual_decision_local_init_blocked"
    assert "manual_decision_template_forbidden_true_default:paper_simulation_allowed" in evaluation.blockers
    assert evaluation.actions == []
    assert evaluation.guardrails["manual_approval_recorded_by_this_report"] is False
    assert evaluation.guardrails["live_order_allowed"] is False


def _write_template(tmp_path: Path, extra: dict[str, object] | None = None) -> None:
    payload = _template_payload(extra)
    path = tmp_path / "configs/reviews/us_equity_manual_decision_record.template.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _template_payload(extra: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "us_equity_manual_decision_record_v1",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "review_id": "",
        "reviewed_at": "",
        "reviewer": "",
        "decision": "",
        "reason": "",
        "evidence_paths": [],
        "follow_up_ticket_ids": [],
        "parameter_or_strategy_id_change_required": False,
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }
    if extra:
        payload.update(extra)
    return payload
