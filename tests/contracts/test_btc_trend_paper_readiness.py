from __future__ import annotations

import json
from pathlib import Path

from scripts.check_btc_trend_paper_readiness import check_btc_trend_paper_readiness


def test_btc_trend_paper_readiness_requires_promotion_gate_ready(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    gate.write_text(
        json.dumps(
            {
                "status": "research_only",
                "paper_candidate_ready": False,
                "selected_candidate": {"strategy_id": "twelve_month_momentum_intended"},
                "ledger_audit": {"complete": True, "lookahead_pass": True},
                "guardrails": {
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "broker_calls_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_frozen(freeze)

    payload = check_btc_trend_paper_readiness(
        repo_root=tmp_path,
        promotion_gate=gate,
        freeze_report=freeze,
        ledger_root=tmp_path / "data/paper_ledger/btc_trend_v0",
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert payload["readiness_type"] == "paper_operational_readiness_only"
    assert "btc_trend_promotion_gate_not_ready" in payload["blockers"]
    assert "btc_trend_paper_candidate_not_ready" in payload["blockers"]
    assert payload["guardrails"]["paper_readiness_is_not_strategy_validation"] is True
    assert payload["guardrails"]["order_endpoint_used"] is False


def test_btc_trend_paper_readiness_rejects_btc_5m_ledger_root(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    _write_ready_gate(gate)
    _write_frozen(freeze)

    payload = check_btc_trend_paper_readiness(
        repo_root=tmp_path,
        promotion_gate=gate,
        freeze_report=freeze,
        ledger_root=Path("data/paper_ledger/btc_5m"),
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_ledger_root_must_not_be_btc_5m" in payload["blockers"]


def test_btc_trend_paper_readiness_blocks_private_or_order_endpoint_flags(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    _write_ready_gate(gate, private_endpoint_used=True, order_endpoint_used=True)
    _write_frozen(freeze)

    payload = check_btc_trend_paper_readiness(
        repo_root=tmp_path,
        promotion_gate=gate,
        freeze_report=freeze,
        ledger_root=tmp_path / "data/paper_ledger/btc_trend_v0",
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_trend_private_endpoint_used" in payload["blockers"]
    assert "btc_trend_order_endpoint_used" in payload["blockers"]


def test_btc_trend_paper_readiness_blocks_gate_claiming_strategy_validation(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    freeze = tmp_path / "freeze.json"
    _write_ready_gate(gate)
    payload = json.loads(gate.read_text(encoding="utf-8"))
    payload["paper_candidate_ready_is_strategy_validation"] = True
    gate.write_text(json.dumps(payload), encoding="utf-8")
    _write_frozen(freeze)

    result = check_btc_trend_paper_readiness(
        repo_root=tmp_path,
        promotion_gate=gate,
        freeze_report=freeze,
        ledger_root=tmp_path / "data/paper_ledger/btc_trend_v0",
        output=tmp_path / "readiness.json",
        generated_at="2026-06-23T00:00:00Z",
    )

    assert result["status"] == "BLOCKED"
    assert "btc_trend_paper_gate_misstates_strategy_validation" in result["blockers"]


def _write_ready_gate(path: Path, *, private_endpoint_used: bool = False, order_endpoint_used: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "paper_candidate_ready",
                "paper_candidate_ready": True,
                "selected_candidate": {"strategy_id": "twelve_month_momentum_intended"},
                "ledger_audit": {"complete": True, "lookahead_pass": True},
                "guardrails": {
                    "private_endpoint_used": private_endpoint_used,
                    "order_endpoint_used": order_endpoint_used,
                    "broker_calls_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_frozen(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "frozen_rejected_as_high_frequency",
                "guardrails": {"parameter_tuning_allowed": False},
            }
        ),
        encoding="utf-8",
    )
