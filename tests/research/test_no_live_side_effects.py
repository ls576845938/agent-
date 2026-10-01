from pathlib import Path

from quant_us.research.btc_alpha_hardening import decide_paper_review_queue


def test_btc_hardening_research_code_has_no_live_runtime_imports() -> None:
    source_paths = [
        Path("quant_us/research/btc_alpha_hardening.py"),
        Path("scripts/run_btc_alpha_hardening.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    assert "quant_us.live" not in combined
    assert "run_live" not in combined
    assert "run_paper" not in combined
    assert "submit_order" not in combined


def test_gate_decision_keeps_live_frozen() -> None:
    decision = decide_paper_review_queue(
        [{"strategy_id": "candidate", "status": "candidate_passed_internal_gate", "passed": True}]
    )

    assert decision["live_frozen"] is True
    assert decision["paper_auto_start"] is False
