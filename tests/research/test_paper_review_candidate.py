from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_us.research.evidence_pack import EvidencePackGenerator
from quant_us.research.evidence_contracts import (
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
    PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
)
from quant_us.research.paper_review_bridge import PaperReviewManager
from quant_us.research.strategy_manifest import StrategyManifestManager
from quant_us.research.paper_review_candidate import (
    inspect_paper_review_candidate_evidence,
)


def _write_candidate(tmp_path: Path, candidate_id: str = "cand_001") -> None:
    candidate_path = tmp_path / "research" / "candidates" / candidate_id / "candidate.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "experiment_id": "exp_001",
                "strategy_id": "portfolio",
                "created_at": "2026-05-10T00:00:00+00:00",
                "metrics": {},
            }
        ),
        encoding="utf-8",
    )


def _write_strategy_attribution(
    tmp_path: Path,
    *,
    fills: float,
    notional: float,
) -> None:
    path = tmp_path / "paper_ledger" / "daily_reports" / "strategy_attribution_2026-05-10.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "by_strategy": {
                    "trend": {
                        "fills": fills,
                        "filled_notional": notional,
                    }
                },
                "totals": {
                    "orders": 1,
                    "fills": fills,
                    "strategies": 1,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_portfolio_observability(tmp_path: Path, *, pnl_status: str = "PASS") -> None:
    path = tmp_path / "reports" / "portfolio_observability.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "multi_strategy": {
                    "status": "PASS",
                    "strategies": ["trend", "reversion"],
                },
                "multi_timeframe": {
                    "status": "PASS",
                    "timeframes": ["1m", "5m"],
                },
                "pnl_attribution": {
                    "status": pnl_status,
                    "rows": [{"strategy_id": "trend", "pnl": 12.5}],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_validation_state(tmp_path: Path) -> None:
    path = tmp_path / "paper_ledger" / "validation_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "days_required": 30,
                "days_completed": 30,
                "consecutive_clean_days": 30,
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(tmp_path: Path, manifest_id: str, candidate_id: str) -> None:
    path = tmp_path / "research" / "manifests" / manifest_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "strategy_candidate_id": manifest_id,
                "source_candidate_id": candidate_id,
                "source_experiment_id": f"exp_{candidate_id}",
                "symbols": ["SPY", "QQQ"],
                "promotion_status": "READY_FOR_PORTFOLIO_SIM",
                "created_at": "2026-05-10T00:00:00+00:00",
                "params_frozen": True,
                "data_version": "qs-yfinance-SPY-1d-test",
                "sample_window": {"start": "2024-01-01", "end": "2024-12-31"},
                "purge_embargo": {"purge_bars": 3, "embargo_bars": 1},
                "trial_id": candidate_id,
                "trial_count": 4,
                "pbo": 0.07,
                "dsr": 0.88,
                "cpcv": {
                    "method": "cpcv",
                    "purged": True,
                    "embargoed": True,
                    "embargo_steps": 1,
                    "fold_count": 4,
                    "path_count": 6,
                    "pass_rate": 0.75,
                },
                "cost_model": {"name": "default", "commission_rate": 0.0001},
                "slippage_model": {"name": "default", "slippage_bps": 1.0},
                "cost_stress": {
                    "stress_survival_rate": 0.83,
                    "cost_sensitivity": 0.18,
                    "level_count": 3,
                },
                "style_exposure": {
                    "observations": 252,
                    "betas": {"MKT": 1.1, "SMB": -0.2},
                    "benchmark_columns": ["MKT", "SMB"],
                    "r_squared": 0.79,
                },
                "capacity": {"estimated_capacity_usd": 1_000_000.0},
                "turnover": {"turnover": 0.2, "annual_turnover_pct": 120.0},
                "holding_period": {"expected": "5d", "avg_holding_period": 5.0},
                "exposure_limits": {"max_gross_exposure_pct": 95.0},
                "failure_conditions": ["drawdown_limit_breach"],
                "delisting_conditions": {"policy": "manual_review_required"},
                "contract_missing_reasons": {},
            }
        ),
        encoding="utf-8",
    )


def test_paper_review_candidate_blocks_without_fill_backed_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_candidate(tmp_path)
    _write_portfolio_observability(tmp_path)
    _write_strategy_attribution(tmp_path, fills=0.0, notional=0.0)
    _write_validation_state(tmp_path)

    monkeypatch.setattr(
        "quant_us.research.paper_review_candidate.inspect_paper_validation_evidence",
        lambda *args, **kwargs: type(
            "PaperValidationStub",
            (),
            {
                "to_dict": lambda self: {
                    "readiness_state": "PASS",
                    "audit_blocker_status": "PASS",
                    "days_completed": 30,
                    "days_required": 30,
                    "gaps": [],
                    "ledger_reconciliation_summary": {
                        "status": "clean",
                        "halt_new_orders": False,
                        "artifact_hash": "artifact_123",
                    },
                    "broker_local_diff_summary": {
                        "cash_diff": 0.0,
                        "position_diff_count": 0,
                        "order_diff_count": 0,
                        "fill_diff_count": 0,
                        "total_diff_count": 0,
                    },
                }
            },
        )(),
    )

    evidence = inspect_paper_review_candidate_evidence("cand_001", tmp_path).to_dict()

    assert evidence["overall_status"] == "BLOCKED"
    assert evidence["review_candidate_status"] == "BLOCKED"
    assert "strategy_attribution_missing_fills" in evidence["blocking_reasons"]
    assert evidence["sections"]["strategy_attribution"]["status"] == "BLOCKED"


def test_evidence_pack_includes_paper_review_candidate_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_candidate(tmp_path)
    expected = {
        "schema_version": "paper_review_candidate_evidence_v1",
        "candidate_id": "cand_001",
        "review_candidate_status": "READY_FOR_REVIEW",
        "overall_status": "PASS",
        "blocking_reasons": [],
        "sections": {},
        "portfolio_observability": {"multi_strategy": {"status": "PASS"}},
        "paper_validation": {"readiness_state": "PASS"},
    }
    monkeypatch.setattr(
        EvidencePackGenerator,
        "_get_paper_review_candidate",
        lambda self, candidate_id: expected,
    )

    evidence = EvidencePackGenerator(data_root=str(tmp_path)).generate("cand_001")
    sections = evidence["sections"]

    assert sections["paper_review_candidate"]["review_candidate_status"] == "READY_FOR_REVIEW"
    assert sections["portfolio_observability"] == expected["portfolio_observability"]
    assert sections["paper_validation"] == expected["paper_validation"]


def test_create_from_portfolio_evidence_requires_ready_paper_review_candidate(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "sm_001", "cand_001")
    evidence_dir = tmp_path / "research" / "evidence_packs" / "cand_001"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "evidence_pack.json").write_text(
        json.dumps(
            {
                "schema_version": "evidence_pack_v2",
                "paper_review_scope": "portfolio_sim",
                "portfolio_sim_id": "psim_001",
                "strategy_manifest_ids": ["sm_001"],
                "evidence_contract": {
                    "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                    "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                    "portfolio_sim_id": "psim_001",
                    "strategy_manifest_ids": ["sm_001"],
                    "candidate_count": 1,
                    "all_strategy_manifest_contracts_complete": True,
                    "paper_review_gate": "portfolio_evidence_pack_required",
                },
                "sections": {
                    "portfolio_sim": {
                        "status": "manifest_created",
                        "portfolio_sim_id": "psim_001",
                        "final_equity": 101000.0,
                        "decision": "PORTFOLIO_PASS",
                    },
                    "candidate_data": {
                        "candidate_id": "cand_001",
                        "symbols": ["SPY", "QQQ"],
                        "metrics": {"max_drawdown_pct": -0.12},
                    },
                    "portfolio_candidates": [
                        {
                            "candidate_id": "cand_001",
                            "strategy_manifest_id": "sm_001",
                            "strategy_manifest_path": str(
                                tmp_path / "research" / "manifests" / "sm_001" / "manifest.json"
                            ),
                            "evidence_pack_path": str(
                                tmp_path
                                / "research"
                                / "evidence_packs"
                                / "cand_001"
                                / "evidence_pack.json"
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
                        "review_candidate_status": "BLOCKED",
                        "blocking_reasons": ["strategy_attribution_missing_fills"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="strategy_attribution_missing_fills"):
        PaperReviewManager(data_root=str(tmp_path)).create_from_portfolio_evidence("cand_001")


def test_create_review_from_portfolio_sim_requires_saved_evidence_gate_and_updates_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path, "sm_001", "cand_001")
    _write_manifest(tmp_path, "sm_002", "cand_002")

    class StubBridge:
        def __init__(self, data_root: str) -> None:
            self.data_root = data_root

        def _load_result(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(decision="PORTFOLIO_PASS", equity_curve=[101_500.0])

        def _load_request(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                strategy_manifest_ids=["sm_001", "sm_002"],
                capital=100_000.0,
                max_drawdown=0.12,
                max_correlation=0.35,
                risk_budget=1.0,
            )

    def _write_portfolio_pack(
        self,
        portfolio_evidence_pack_id: str,
        *,
        portfolio_sim_id: str,
        strategy_manifest_ids: list[str],
        proposed_symbols: list[str],
        proposed_capital: float,
        proposed_risk_envelope: dict[str, object],
        portfolio_decision: str,
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
                    "proposed_symbols": proposed_symbols,
                    "proposed_capital": proposed_capital,
                    "proposed_risk_envelope": proposed_risk_envelope,
                    "paper_review_scope": "portfolio_sim",
                    "portfolio_sim_id": portfolio_sim_id,
                    "strategy_manifest_ids": strategy_manifest_ids,
                    "evidence_contract": {
                        "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                        "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                        "portfolio_sim_id": portfolio_sim_id,
                        "strategy_manifest_ids": strategy_manifest_ids,
                        "candidate_count": len(strategy_manifest_ids),
                        "all_strategy_manifest_contracts_complete": True,
                        "paper_review_gate": "portfolio_evidence_pack_required",
                    },
                    "sections": {
                        "candidate_data": {
                            "candidate_id": "cand_001",
                            "symbols": proposed_symbols,
                            "metrics": {"max_drawdown_pct": -0.12},
                        },
                        "portfolio_candidates": [
                            {
                                "candidate_id": "cand_001",
                                "strategy_manifest_id": strategy_manifest_ids[0],
                                "strategy_manifest_path": str(
                                    tmp_path / "research" / "manifests" / strategy_manifest_ids[0] / "manifest.json"
                                ),
                                "evidence_pack_path": str(
                                    tmp_path / "research" / "evidence_packs" / "cand_001" / "evidence_pack.json"
                                ),
                                "strategy_manifest_contract": {
                                    "contract_complete": True,
                                    "missing_fields": [],
                                },
                                "strategy_manifest_contract_complete": True,
                            },
                            {
                                "candidate_id": "cand_002",
                                "strategy_manifest_id": strategy_manifest_ids[1],
                                "strategy_manifest_path": str(
                                    tmp_path / "research" / "manifests" / strategy_manifest_ids[1] / "manifest.json"
                                ),
                                "evidence_pack_path": str(
                                    tmp_path / "research" / "evidence_packs" / "cand_002" / "evidence_pack.json"
                                ),
                                "strategy_manifest_contract": {
                                    "contract_complete": True,
                                    "missing_fields": [],
                                },
                                "strategy_manifest_contract_complete": True,
                            },
                        ],
                        "portfolio_sim": {
                            "status": "manifest_created",
                            "portfolio_sim_id": portfolio_sim_id,
                            "strategy_manifest_ids": strategy_manifest_ids,
                            "proposed_symbols": proposed_symbols,
                            "final_equity": proposed_capital,
                            "decision": portfolio_decision,
                        },
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
        "quant_us.research.portfolio_sim_bridge.PortfolioSimBridge",
        StubBridge,
    )
    monkeypatch.setattr(
        EvidencePackGenerator,
        "save_portfolio_review_pack",
        _write_portfolio_pack,
    )

    review = PaperReviewManager(data_root=str(tmp_path)).create_review("psim_001")

    manifest_mgr = StrategyManifestManager(data_root=str(tmp_path))
    manifest_a = manifest_mgr.load("sm_001")
    manifest_b = manifest_mgr.load("sm_002")

    assert review.status == "PENDING_HUMAN_REVIEW"
    assert review.source_candidate_ids == ["cand_001", "cand_002"]
    assert review.evidence_gate_status == "READY_FOR_REVIEW"
    assert review.approval is None
    assert review.evidence_pack_path.endswith("/psim_001/evidence_pack.json")
    assert manifest_a is not None and manifest_a.promotion_status == "PAPER_REVIEW_CANDIDATE"
    assert manifest_b is not None and manifest_b.promotion_status == "PAPER_REVIEW_CANDIDATE"
    assert manifest_a.paper_review_id == review.paper_review_id
    assert manifest_a.paper_review_evidence_pack_path == review.evidence_pack_path
    assert manifest_a.paper_review_candidate_status == "READY_FOR_REVIEW"


def test_create_review_from_portfolio_sim_no_longer_bypasses_blocked_candidate_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_manifest(tmp_path, "sm_001", "cand_001")

    class StubBridge:
        def __init__(self, data_root: str) -> None:
            self.data_root = data_root

        def _load_result(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(decision="PORTFOLIO_PASS", equity_curve=[100_100.0])

        def _load_request(self, sim_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                strategy_manifest_ids=["sm_001"],
                capital=100_000.0,
                max_drawdown=0.10,
                max_correlation=0.25,
                risk_budget=1.0,
            )

    def _write_blocked_pack(self, portfolio_evidence_pack_id: str, **kwargs: object) -> str:
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
                    "portfolio_sim_id": "psim_blocked",
                    "strategy_manifest_ids": ["sm_001"],
                    "evidence_contract": {
                        "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                        "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                        "portfolio_sim_id": "psim_blocked",
                        "strategy_manifest_ids": ["sm_001"],
                        "candidate_count": 1,
                        "all_strategy_manifest_contracts_complete": True,
                        "paper_review_gate": "portfolio_evidence_pack_required",
                    },
                    "sections": {
                        "candidate_data": {"candidate_id": "cand_001", "symbols": ["SPY"]},
                        "portfolio_candidates": [
                            {
                                "candidate_id": "cand_001",
                                "strategy_manifest_id": "sm_001",
                                "strategy_manifest_path": str(
                                    tmp_path / "research" / "manifests" / "sm_001" / "manifest.json"
                                ),
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
                        "portfolio_sim": {
                            "status": "manifest_created",
                            "portfolio_sim_id": "psim_blocked",
                            "final_equity": 100_100.0,
                            "decision": "PORTFOLIO_PASS",
                        },
                        "promotion_gate": {"decision": "READY_FOR_PAPER_REVIEW"},
                        "paper_review_candidate": {
                            "review_candidate_status": "BLOCKED",
                            "blocking_reasons": ["strategy_attribution_missing_fills"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        return str(path)

    monkeypatch.setattr(
        "quant_us.research.portfolio_sim_bridge.PortfolioSimBridge",
        StubBridge,
    )
    monkeypatch.setattr(
        EvidencePackGenerator,
        "save_portfolio_review_pack",
        _write_blocked_pack,
    )

    with pytest.raises(ValueError, match="strategy_attribution_missing_fills"):
        PaperReviewManager(data_root=str(tmp_path)).create_review("psim_blocked")


def test_create_from_portfolio_evidence_blocks_incomplete_strategy_manifest_contract(
    tmp_path: Path,
) -> None:
    _write_manifest(tmp_path, "sm_001", "cand_001")
    evidence_dir = tmp_path / "research" / "evidence_packs" / "pack_incomplete"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "evidence_pack.json").write_text(
        json.dumps(
            {
                "schema_version": "evidence_pack_v2",
                "paper_review_scope": "portfolio_sim",
                "portfolio_sim_id": "psim_002",
                "strategy_manifest_ids": ["sm_001"],
                "evidence_contract": {
                    "schema_version": PORTFOLIO_PAPER_REVIEW_EVIDENCE_SCHEMA_VERSION,
                    "origin": PORTFOLIO_PAPER_REVIEW_EVIDENCE_ORIGIN,
                    "portfolio_sim_id": "psim_002",
                    "strategy_manifest_ids": ["sm_001"],
                    "candidate_count": 1,
                    "all_strategy_manifest_contracts_complete": False,
                    "paper_review_gate": "portfolio_evidence_pack_required",
                },
                "sections": {
                    "candidate_data": {
                        "candidate_id": "cand_001",
                        "symbols": ["SPY"],
                        "metrics": {"max_drawdown_pct": -0.12},
                    },
                    "portfolio_candidates": [
                        {
                            "candidate_id": "cand_001",
                            "strategy_manifest_id": "sm_001",
                            "strategy_manifest_path": str(
                                tmp_path / "research" / "manifests" / "sm_001" / "manifest.json"
                            ),
                            "evidence_pack_path": str(
                                tmp_path / "research" / "evidence_packs" / "cand_001" / "evidence_pack.json"
                            ),
                            "strategy_manifest_contract": {
                                "contract_complete": False,
                                "missing_fields": ["pbo", "dsr"],
                            },
                            "strategy_manifest_contract_complete": False,
                        }
                    ],
                    "portfolio_sim": {
                        "status": "manifest_created",
                        "portfolio_sim_id": "psim_002",
                        "final_equity": 101500.0,
                        "decision": "PORTFOLIO_PASS",
                    },
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

    with pytest.raises(ValueError, match="strategy_manifest_contract_incomplete:sm_001"):
        PaperReviewManager(data_root=str(tmp_path)).create_from_portfolio_evidence(
            "pack_incomplete"
        )


def test_create_from_candidate_evidence_builds_deterministic_pending_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_candidate(tmp_path, "cand_001")
    _write_manifest(tmp_path, "sm_001", "cand_001")

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
                        "paper_review_gate": "portfolio_evidence_pack_required",
                    },
                    "candidate_id": "cand_001",
                    "proposed_symbols": ["SPY", "QQQ"],
                    "proposed_capital": 100000.0,
                    "proposed_risk_envelope": {"max_drawdown_pct": 0.12},
                    "sections": {
                        "portfolio_sim": {
                            "status": "manifest_created",
                            "decision": "READY_FOR_PAPER_REVIEW",
                            "portfolio_sim_id": portfolio_evidence_pack_id,
                            "final_equity": 100000.0,
                            "proposed_symbols": ["SPY", "QQQ"],
                        },
                        "candidate_data": {
                            "candidate_id": "cand_001",
                            "symbols": ["SPY", "QQQ"],
                            "metrics": {"max_drawdown_pct": 0.12},
                        },
                        "portfolio_candidates": [
                            {
                                "candidate_id": "cand_001",
                                "strategy_manifest_id": "sm_001",
                                "strategy_manifest_path": str(
                                    tmp_path / "research" / "manifests" / "sm_001" / "manifest.json"
                                ),
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

    manager = PaperReviewManager(data_root=str(tmp_path))
    review = manager.create_from_candidate_evidence(strategy_manifest_id="sm_001")
    manifest = StrategyManifestManager(data_root=str(tmp_path)).load("sm_001")

    assert review.status == "PENDING_HUMAN_REVIEW"
    assert review.strategy_manifest_id == "sm_001"
    assert review.source_candidate_ids == ["cand_001"]
    assert review.evidence_pack_path.endswith(
        "/research/evidence_packs/pending_review_sm_001/evidence_pack.json"
    )
    assert manifest is not None
    assert manifest.paper_review_id == review.paper_review_id
    assert manifest.paper_review_candidate_status == "READY_FOR_REVIEW"

    same_review = manager.create_from_candidate_evidence(strategy_manifest_id="sm_001")
    assert same_review.paper_review_id == review.paper_review_id
