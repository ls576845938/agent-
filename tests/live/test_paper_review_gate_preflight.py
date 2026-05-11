from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
from quant_us.research.evidence_contracts import (
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
)
from quant_us.research.evidence_registry import rebuild_evidence_registry
from quant_us.research.evidence_pack import EvidencePackGenerator
from quant_us.research.paper_review_bridge import PaperReviewManager
from quant_us.research.strategy_manifest import StrategyManifestManager
from quant_us.live.micro_live_design_freeze import design_freeze_metadata


def _write_approved_review(
    data_root: Path,
    *,
    review_id: str,
    symbols: list[str],
    capital: float = 100_000.0,
    bar_sizes: list[str] | None = None,
    strategy_manifest_id: str = "candidate_for_paper",
) -> Path:
    review_path = data_root / "research" / "paper_reviews" / review_id / "review.json"
    evidence_pack_path = data_root / "research" / "evidence_packs" / review_id / "evidence_pack.json"
    evidence_pack_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_pack_path.write_text(json.dumps({"paper_review_id": review_id}), encoding="utf-8")
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(
            {
                "paper_review_id": review_id,
                "strategy_manifest_id": strategy_manifest_id,
                "status": "APPROVED_FOR_PAPER_ONLY",
                "reviewer": "human-risk-reviewer",
                "evidence_pack_path": str(evidence_pack_path),
                "proposed_symbols": symbols,
                "proposed_capital": capital,
                "proposed_risk_envelope": {"bar_sizes": bar_sizes or ["1m", "5m", "15m"]},
            }
        ),
        encoding="utf-8",
    )
    rebuild_evidence_registry(data_root)
    return review_path


def test_paper_review_evidence_must_match_runtime_symbols_and_timeframes(tmp_path: Path) -> None:
    review_path = _write_approved_review(
        tmp_path,
        review_id="paper_review_symbol_mismatch",
        symbols=["AAPL"],
        bar_sizes=["1m", "5m", "15m"],
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            bar_sizes=["1m", "5m", "15m"],
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok, reason = runtime._has_paper_entry_evidence()

    assert ok is False
    assert reason.startswith("paper_review_symbols_mismatch")


def test_paper_review_evidence_must_not_exceed_approved_capital(tmp_path: Path) -> None:
    review_path = _write_approved_review(
        tmp_path,
        review_id="paper_review_capital_mismatch",
        symbols=["SPY"],
        capital=25_000.0,
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            capital=50_000.0,
            bar_sizes=["1m", "5m", "15m"],
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok, reason = runtime._has_paper_entry_evidence()

    assert ok is False
    assert reason.startswith("paper_review_capital_exceeds_approved")


def test_paper_review_evidence_must_match_runtime_strategy_id(tmp_path: Path) -> None:
    review_path = _write_approved_review(
        tmp_path,
        review_id="paper_review_strategy_mismatch",
        symbols=["SPY"],
        strategy_manifest_id="approved_strategy",
    )
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY"],
            strategy_id="different_runtime_strategy",
            ledger_root=str(tmp_path / "ledger"),
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
            reconcile_on_start=False,
        )
    )

    with patch.dict(
        "os.environ",
        {
            "APCA_API_KEY_ID": "paper_key",
            "APCA_API_SECRET_KEY": "paper_secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "QUANT_ENABLE_ALPACA_PAPER_ADAPTER": "true",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="paper_review_strategy_mismatch"):
            runtime.bootstrap()

    gate_event = runtime.audit_events[-1]
    assert gate_event["event"] == "paper_runtime_entry_gate"
    assert gate_event["details"]["checks"]["paper_review_or_promotion_evidence"] is False
    assert (
        "paper_review_strategy_mismatch:approved=approved_strategy:"
        "runtime=different_runtime_strategy"
    ) in gate_event["details"]["reasons"]


def test_candidate_review_preparation_has_no_live_runtime_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_path = tmp_path / "research" / "candidates" / "cand_001" / "candidate.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(
            {
                "candidate_id": "cand_001",
                "experiment_id": "exp_001",
                "metrics": {"max_drawdown_pct": 0.08},
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "research" / "manifests" / "sm_001" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "strategy_candidate_id": "sm_001",
                "source_candidate_id": "cand_001",
                "source_experiment_id": "exp_001",
                "symbols": ["SPY"],
                "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                "data_version": "dv_001",
                "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
                "purge_embargo": {"purge_bars": 2, "embargo_bars": 1},
                "trial_id": "trial_001",
                "trial_count": 3,
                "pbo": 0.05,
                "dsr": 0.9,
                "cost_model": {"name": "default"},
                "slippage_model": {"name": "default"},
                "capacity": {"estimated_capacity_usd": 1000000.0},
                "turnover": {"turnover": 0.2},
                "holding_period": {"expected": "5d"},
                "exposure_limits": {"max_gross_exposure_pct": 80.0},
                "failure_conditions": ["dd_limit"],
                "delisting_conditions": {"policy": "manual_review_required"},
            }
        ),
        encoding="utf-8",
    )

    def _write_portfolio_pack(
        self,
        portfolio_evidence_pack_id: str,
        **_: object,
    ) -> str:
        path = (
            Path(self.data_root)
            / "research"
            / "evidence_packs"
            / portfolio_evidence_pack_id
            / "evidence_pack.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "evidence_pack_v2",
                    "paper_review_scope": "portfolio_sim",
                    "portfolio_sim_id": portfolio_evidence_pack_id,
                    "strategy_manifest_ids": ["sm_001"],
                    "evidence_contract": {
                        "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                        "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                        "portfolio_sim_id": portfolio_evidence_pack_id,
                        "strategy_manifest_ids": ["sm_001"],
                        "candidate_count": 1,
                        "all_strategy_manifest_contracts_complete": True,
                        "all_strategy_manifest_contracts_documented": True,
                        "paper_review_gate": "portfolio_evidence_pack_required",
                    },
                    "candidate_id": "cand_001",
                    "proposed_symbols": ["SPY"],
                    "proposed_capital": 100000.0,
                    "proposed_risk_envelope": {"max_drawdown_pct": 0.08},
                    "sections": {
                        "portfolio_sim": {
                            "status": "manifest_created",
                            "decision": "READY_FOR_PAPER_REVIEW",
                            "portfolio_sim_id": portfolio_evidence_pack_id,
                            "final_equity": 100000.0,
                        },
                        "candidate_data": {
                            "candidate_id": "cand_001",
                            "symbols": ["SPY"],
                            "metrics": {"max_drawdown_pct": 0.08},
                        },
                        "portfolio_candidates": [
                            {
                                "candidate_id": "cand_001",
                                "strategy_manifest_id": "sm_001",
                                "strategy_manifest_path": str(manifest_path),
                                "evidence_pack_path": str(
                                    tmp_path / "research" / "evidence_packs" / "cand_001" / "evidence_pack.json"
                                ),
                                "strategy_manifest_contract": {
                                    "contract_complete": True,
                                    "missing_fields": [],
                                },
                                "strategy_manifest_contract_complete": True,
                            }
                        ],
                        "promotion_gate": {"decision": "READY_FOR_PAPER_REVIEW"},
                        "paper_review_candidate": {
                            "review_candidate_status": "READY_FOR_REVIEW",
                            "blocking_reasons": [],
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return str(path)

    monkeypatch.setattr(
        EvidencePackGenerator,
        "save_portfolio_review_pack",
        _write_portfolio_pack,
    )

    review = PaperReviewManager(data_root=str(tmp_path)).create_from_candidate_evidence(
        strategy_manifest_id="sm_001"
    )

    assert review.status == "PENDING_HUMAN_REVIEW"
    assert (tmp_path / "paper_ledger").exists() is False
    assert (tmp_path / "ledger").exists() is False
    assert (tmp_path / "research" / "paper_reviews" / review.paper_review_id / "review.json").exists()


def test_ready_paper_candidate_enters_queue_but_runtime_waits_for_human_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = "cand_ready_for_paper"
    manifest_id = "sm_ready_for_paper"
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "experiment_id": "exp_ready_for_paper",
                "strategy_id": "paper_candidate_strategy",
                "symbols": ["SPY", "QQQ"],
                "metrics": {
                    "max_drawdown_pct": 0.07,
                    "proposed_capital": 75_000.0,
                },
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "research" / "manifests" / manifest_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "strategy_candidate_id": manifest_id,
                "source_candidate_id": candidate_id,
                "source_experiment_id": "exp_ready_for_paper",
                "strategy_template": "paper_candidate_strategy",
                "symbols": ["SPY", "QQQ"],
                "timeframe": "1d",
                "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                "created_at": "2026-05-11T00:00:00+00:00",
                "params_frozen": True,
                "data_version": "test-data-v1",
                "sample_window": {"start": "2024-01-01", "end": "2025-12-31"},
                "purge_embargo": {"method": "cpcv", "purged": True, "embargoed": True},
                "trial_id": "trial_ready_for_paper",
                "trial_count": 8,
                "pbo": 0.04,
                "dsr": 1.15,
                "cpcv": {"method": "cpcv", "fold_count": 6, "path_count": 10},
                "cost_model": {"name": "bps_commission", "commission_rate": 0.0001},
                "slippage_model": {"name": "fixed_bps", "slippage_bps": 2.0},
                "cost_stress": {"stress_survival_rate": 0.88, "level_count": 4},
                "style_exposure": {
                    "betas": {"MKT": 0.93},
                    "benchmark_columns": ["MKT"],
                },
                "capacity": {"estimated_capacity_usd": 500_000.0},
                "turnover": {"turnover": 0.18},
                "holding_period": {"expected": "5d"},
                "exposure_limits": {"max_gross_exposure_pct": 90.0},
                "failure_conditions": ["drawdown_limit_breach"],
                "delisting_conditions": {"policy": "manual_review_required"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        EvidencePackGenerator,
        "_get_promotion_gate",
        lambda self, candidate_id: {
            "decision": "READY_FOR_PAPER_REVIEW",
            "reasons": [],
            "warnings": [],
            "evidence": {},
        },
    )
    monkeypatch.setattr(
        EvidencePackGenerator,
        "_get_paper_review_candidate",
        lambda self, candidate_id: {
            "schema_version": "paper_review_candidate_evidence_v1",
            "candidate_id": candidate_id,
            "review_candidate_status": "READY_FOR_REVIEW",
            "overall_status": "PASS",
            "blocking_reasons": [],
            "portfolio_observability": {
                "live_state": "FROZEN",
                "multi_strategy": {"status": "PASS", "strategy_count": 2},
                "multi_timeframe": {"status": "PASS", "timeframe_count": 2},
                "pnl_attribution": {"status": "PASS", "row_count": 2},
            },
            "paper_validation": {
                "readiness_state": "PASS",
                "audit_blocker_status": "PASS",
                "gaps": [],
                "ledger_reconciliation_summary": {
                    "status": "clean",
                    "halt_new_orders": False,
                    "artifact_hash": "recon_hash",
                },
                "broker_local_diff_summary": {"total_diff_count": 0},
            },
        },
    )

    manager = PaperReviewManager(data_root=str(tmp_path))
    review = manager.create_from_candidate_evidence(strategy_manifest_id=manifest_id)
    review_path = (
        tmp_path / "research" / "paper_reviews" / review.paper_review_id / "review.json"
    )
    evidence_path = Path(review.evidence_pack_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    manifest = StrategyManifestManager(data_root=str(tmp_path)).load(manifest_id)

    assert review.status == "PENDING_HUMAN_REVIEW"
    assert review.approval is None
    assert review.strategy_manifest_id == manifest_id
    assert evidence["paper_review_scope"] == "portfolio_sim"
    assert evidence["sections"]["promotion_gate"]["decision"] == "READY_FOR_PAPER_REVIEW"
    assert evidence["sections"]["paper_review_candidate"]["overall_status"] == "PASS"
    assert evidence["sections"]["portfolio_candidates"][0]["strategy_manifest_id"] == manifest_id
    assert manifest is not None
    assert manifest.promotion_status == "PAPER_REVIEW_CANDIDATE"
    assert manifest.paper_review_id == review.paper_review_id
    assert manifest.paper_review_evidence_pack_path == str(evidence_path)

    rebuild_evidence_registry(tmp_path)
    runtime = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY", "QQQ"],
            capital=75_000.0,
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok, reason = runtime._has_paper_entry_evidence()

    assert ok is False
    assert reason == "paper_review_not_approved:PENDING_HUMAN_REVIEW"
    assert design_freeze_metadata()["frozen"] is True
    assert design_freeze_metadata()["scope"] == "review_only"

    approved = manager.approve(
        review.paper_review_id,
        reviewer="human-risk-reviewer",
        reason="manual paper review approved",
    )
    rebuild_evidence_registry(tmp_path)
    runtime_after_approval = PaperRuntime(
        PaperRuntimeConfig(
            symbols=["SPY", "QQQ"],
            capital=75_000.0,
            paper_broker="alpaca",
            paper_review_path=str(review_path),
            promotion_data_root=str(tmp_path),
        )
    )

    ok_after_approval, reason_after_approval = runtime_after_approval._has_paper_entry_evidence()

    assert approved.status == "APPROVED_FOR_PAPER_ONLY"
    assert approved.approval is not None
    assert approved.approval.gate_snapshot["paper_execution_authorized"] is False
    assert ok_after_approval is True
    assert reason_after_approval == "ok"
    assert not (tmp_path / "ledger").exists()
