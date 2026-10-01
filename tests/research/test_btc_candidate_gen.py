from __future__ import annotations

import json
from pathlib import Path

from quant_us.backtest.crypto_event import qualify_crypto_candidates
from quant_us.research.automation.candidate_gen import (
    CandidateGenerator,
    conservative_btc_strategy_family_sweep_config,
)
from quant_us.research.automation.promotion_gate import ResearchPromotionGate


def _strong_validation() -> dict[str, float | int]:
    return {
        "total_return_pct": 12.0,
        "sharpe_ratio": 1.4,
        "profit_factor": 1.7,
        "max_drawdown_pct": -6.0,
        "trade_count": 22,
    }


def _event_ok() -> dict[str, object]:
    return {
        "diagnostics": {
            "engine": "event_driven",
            "pnl_source": "ledger_fills",
            "ledger_equity_consistent": True,
        }
    }


def _cost_ok() -> dict[str, object]:
    return {
        "engine": "event_driven",
        "survival_rate_pct": 100.0,
        "ledger_consistency_pct": 100.0,
    }


def _candidate_key(candidate: dict[str, object]) -> str:
    strategy_id = str(candidate["strategy_id"])
    params = dict(candidate.get("parameters") or candidate.get("params") or {})
    if not params:
        return strategy_id
    parts = ",".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{strategy_id}|{parts}"


def test_conservative_btc_family_sweep_generates_metadata_rich_candidates(tmp_path: Path) -> None:
    generator = CandidateGenerator(data_root=str(tmp_path))
    config = conservative_btc_strategy_family_sweep_config(
        data_version="qs-sqlite-BTCUSDT-1h-2026q1",
        max_candidates=24,
    )

    first = generator.generate_family_sweep(config)
    second = generator.generate_family_sweep(config)

    assert first == second
    assert 12 <= len(first) <= 24
    assert len({candidate["candidate_id"] for candidate in first}) == len(first)
    assert {candidate["strategy_family_variant"] for candidate in first} >= {
        "btc_trend_macd",
        "btc_macro_trend",
        "btc_donchian_breakout",
        "btc_reversion_rsi",
        "btc_volatility_squeeze",
    }

    sample = first[0]
    assert sample["strategy_family"] == "btc_conservative_family_sweep"
    assert sample["asset_class"] == "crypto"
    assert sample["data_source"] == "sqlite"
    assert sample["timeframe"] == "1h"
    assert sample["gate_requirements"] == {
        "requires_walk_forward": True,
        "requires_cost_stress": True,
        "requires_regime_evidence": True,
        "requires_event_driven_ledger": True,
        "requires_promotion_gate": True,
        "requires_sqlite_data_source": True,
    }
    assert sample["research_metadata"]["candidate_origin"] == "btc_strategy_family_sweep"
    assert sample["research_metadata"]["market"] == "btc"
    assert "regime" in sample["research_metadata"]
    assert "filters" in sample["research_metadata"]
    assert "turnover_aware" in sample["research_metadata"]
    assert sample["research_metadata"]["runtime_hints"]["cost_aware_filter"] is True

    generator.save_candidates("exp_btc_family", first[:2])
    manifest = json.loads(
        (tmp_path / "research" / "experiments" / "exp_btc_family" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    saved = json.loads(
        (
            tmp_path
            / "research"
            / "candidates"
            / first[0]["candidate_id"]
            / "candidate.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["strategy_families"] == ["btc_conservative_family_sweep"]
    assert set(manifest["strategy_ids"]) <= {
        "trend_macd",
        "macro_trend",
        "donchian_breakout",
        "reversion_rsi",
        "volatility_squeeze",
    }
    assert saved["research_metadata"]["family_id"] == saved["strategy_family_variant"]
    assert saved["research_metadata"]["runtime_hints"]["max_annual_turnover_pct"] > 0


def test_btc_family_candidates_still_require_cost_stress_and_walk_forward() -> None:
    candidate = CandidateGenerator().generate_family_sweep(
        conservative_btc_strategy_family_sweep_config(max_candidates=1)
    )[0]
    candidate = {
        **candidate,
        "score": 3.0,
        "validation": _strong_validation(),
    }
    key = _candidate_key(candidate)

    result = qualify_crypto_candidates(
        [candidate],
        event_backtest_by_candidate={key: _event_ok()},
        max_selected=1,
    )

    row = result["candidates"][0]
    assert row["qualified"] is False
    assert row["selected"] is False
    assert result["selected_count"] == 0
    assert "missing cost stress result" in row["qualification_blockers"]
    assert "missing walk-forward result" in row["qualification_blockers"]


def test_btc_family_candidates_still_require_regime_evidence() -> None:
    candidate = CandidateGenerator().generate_family_sweep(
        conservative_btc_strategy_family_sweep_config(max_candidates=1)
    )[0]
    candidate = {
        **candidate,
        "score": 3.0,
        "validation": _strong_validation(),
    }
    key = _candidate_key(candidate)
    walk_forward = {
        "stability": {
            "fold_pass_rate_pct": 100.0,
            "ledger_consistency_pct": 100.0,
            "regime_pass_rate_pct": 50.0,
        }
    }

    result = qualify_crypto_candidates(
        [candidate],
        cost_stress_by_candidate={key: _cost_ok()},
        walk_forward_by_candidate={key: walk_forward},
        event_backtest_by_candidate={key: _event_ok()},
        max_selected=1,
    )

    row = result["candidates"][0]
    assert row["qualified"] is False
    assert row["selected"] is False
    assert any(blocker.startswith("regime pass_rate < ") for blocker in row["qualification_blockers"])


def test_btc_family_candidates_remain_blocked_by_promotion_gate_without_artifacts(
    tmp_path: Path,
) -> None:
    generator = CandidateGenerator(data_root=str(tmp_path))
    candidate = generator.generate_family_sweep(
        conservative_btc_strategy_family_sweep_config(max_candidates=1)
    )[0]
    generator.save_candidates("exp_btc_gate", [candidate])

    candidate_path = (
        tmp_path / "research" / "candidates" / candidate["candidate_id"] / "candidate.json"
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["metrics"] = _strong_validation()
    candidate_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = ResearchPromotionGate(data_root=str(tmp_path)).evaluate(candidate["candidate_id"])

    assert result.decision == "BLOCKED"
    assert any(reason.startswith("missing_walk_forward_artifact:") for reason in result.reasons)
    assert any(reason.startswith("missing_cost_stress_artifact:") for reason in result.reasons)
    assert any(reason.startswith("missing_walk_forward_result:") for reason in result.reasons)
    assert any(reason.startswith("missing_scorecard:") for reason in result.reasons)
