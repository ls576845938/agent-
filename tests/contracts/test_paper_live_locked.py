from __future__ import annotations

from pathlib import Path

import yaml


EVIDENCE_POLICY = Path("configs/evidence/evidence_policy.yaml")
RUNTIME_CONFIG = Path("quant_us/live/runtime_config.py")
SUBMISSION_GATE = Path("quant_us/live/live_order_submission_gate.py")


def test_evidence_policy_keeps_paper_and_live_locked_by_default() -> None:
    policy = yaml.safe_load(EVIDENCE_POLICY.read_text(encoding="utf-8"))

    assert policy["promotion"]["paper_queue_locked_by_default"] is True
    assert policy["promotion"]["live_frozen_by_default"] is True
    assert policy["promotion"]["candidate_passed_internal_gate_required"] is True


def test_live_runtime_static_boundary_remains_fail_closed() -> None:
    runtime_config = RUNTIME_CONFIG.read_text(encoding="utf-8")
    submission_gate = SUBMISSION_GATE.read_text(encoding="utf-8")

    assert "def real_order_submission_enabled" in runtime_config
    assert "return False" in runtime_config
    assert "live_runtime_frozen" in runtime_config
    assert "REQUIRES_MANUAL_REVIEW" in submission_gate
    assert "review_only_surface_no_automatic_submission" in submission_gate
