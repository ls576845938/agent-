"""US equity portfolio promotion-evidence gate.

This module is deliberately read-only. It separates fixture plumbing,
candidate research evidence, and promotion-grade portfolio evidence so a
fixture ledger or a research-only validation report cannot unlock paper/live.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REQUIRED_LAYER_IDS = [
    "fixture_isolation",
    "candidate_strategy_validation",
    "portfolio_event_ledger",
    "event_driven_backtest",
    "ledger_pnl",
    "portfolio_construction",
    "portfolio_cost_stress",
    "portfolio_walk_forward",
    "exposure_constraints",
    "promotion_gate",
]


def build_portfolio_promotion_evidence_report(
    *,
    repo_root: Path,
    generated_at: str | None,
    portfolio_canonical: Mapping[str, Any],
    fixture_ledger: Mapping[str, Any],
    strategy_validation_gate: Mapping[str, Any],
    walk_forward_report: Mapping[str, Any],
    cost_stress_report: Mapping[str, Any],
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    layers = {
        "fixture_isolation": _fixture_isolation_layer(fixture_ledger),
        "candidate_strategy_validation": _candidate_strategy_validation_layer(strategy_validation_gate),
        "portfolio_event_ledger": _portfolio_event_ledger_layer(portfolio_canonical),
        "event_driven_backtest": _event_driven_backtest_layer(portfolio_canonical),
        "ledger_pnl": _ledger_pnl_layer(portfolio_canonical),
        "portfolio_construction": _portfolio_construction_layer(portfolio_canonical),
        "portfolio_cost_stress": _portfolio_cost_stress_layer(portfolio_canonical, cost_stress_report),
        "portfolio_walk_forward": _portfolio_walk_forward_layer(walk_forward_report),
        "exposure_constraints": _exposure_constraints_layer(portfolio_canonical),
    }
    promotion_gate_blockers = []
    for layer_id in REQUIRED_LAYER_IDS:
        if layer_id == "promotion_gate":
            continue
        layer = layers[layer_id]
        if layer["passed"] is not True:
            promotion_gate_blockers.append(f"portfolio_promotion_layer_failed:{layer_id}")
    layers["promotion_gate"] = {
        "layer_id": "promotion_gate",
        "status": "blocked" if promotion_gate_blockers else "pass",
        "passed": not promotion_gate_blockers,
        "promotion_eligible": not promotion_gate_blockers,
        "blockers": promotion_gate_blockers,
        "source_report": "derived:portfolio_promotion_evidence_layers",
        "summary": "all required portfolio promotion evidence layers must pass before paper/live gates can consider this candidate",
    }
    blockers = _dedupe(
        [
            blocker
            for layer in layers.values()
            for blocker in _list_of_str(layer.get("blockers"))
        ]
    )
    promotion_ready = not blockers and all(layers[layer_id]["passed"] is True for layer_id in REQUIRED_LAYER_IDS)
    evidence_gap_summary = _evidence_gap_summary(layers, promotion_ready=promotion_ready)
    evidence_tiers = _evidence_tiers(layers, evidence_gap_summary, promotion_ready=promotion_ready)
    evidence_source_matrix = _evidence_source_matrix(layers, evidence_gap_summary)
    summary = _summary(
        evidence_gap_summary=evidence_gap_summary,
        blockers=blockers,
        promotion_ready=promotion_ready,
    )
    return {
        "schema_version": "us_equity_portfolio_promotion_evidence_report_v1",
        "generated_at": generated,
        "asset": "us_equity",
        "status": "promotion_evidence_ready" if promotion_ready else "promotion_evidence_blocked",
        "summary": summary,
        "portfolio_run_id": str(portfolio_canonical.get("portfolio_run_id") or ""),
        "strategy_id": str(strategy_validation_gate.get("strategy_id") or ""),
        "candidate_variant": str(strategy_validation_gate.get("candidate_variant") or ""),
        "evidence_classification": {
            "fixture_evidence_present": bool(fixture_ledger),
            "candidate_evidence_present": bool(strategy_validation_gate),
            "promotion_evidence_present": promotion_ready,
            "fixture_can_promote": False,
            "candidate_can_promote_without_portfolio_ledger": False,
        },
        "source_reports": {
            "portfolio_canonical_report": _source_ref(repo_root, portfolio_canonical, "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json"),
            "portfolio_fixture_event_ledger_report": _source_ref(repo_root, fixture_ledger, "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json"),
            "strategy_validation_gate_report": _source_ref(repo_root, strategy_validation_gate, "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
            "walk_forward_report": _source_ref(repo_root, walk_forward_report, "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json"),
            "cost_stress_report": _source_ref(repo_root, cost_stress_report, "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json"),
        },
        "evidence_tiers": evidence_tiers,
        "evidence_source_matrix": evidence_source_matrix,
        "evidence_gap_summary": evidence_gap_summary,
        "required_layers": REQUIRED_LAYER_IDS,
        "evidence_layers": layers,
        "blockers": blockers,
        "promotion_ready": promotion_ready,
        "paper_queue_status": "locked",
        "paper_simulation_allowed": False,
        "live_status": "frozen",
        "live_order_allowed": False,
        "guardrails": {
            "read_only": True,
            "strategy_parameters_mutated": False,
            "broker_calls_used": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "fixture_or_candidate_report_cannot_unlock_live": True,
        },
    }


def _summary(
    *,
    evidence_gap_summary: Mapping[str, Any],
    blockers: list[str],
    promotion_ready: bool,
) -> dict[str, Any]:
    fixture = _mapping(evidence_gap_summary.get("fixture_evidence"))
    candidate = _mapping(evidence_gap_summary.get("candidate_evidence"))
    promotion = _mapping(evidence_gap_summary.get("promotion_evidence"))
    return {
        "promotion_ready": bool(promotion_ready),
        "fixture_evidence_present": bool(fixture.get("present")),
        "candidate_evidence_present": bool(candidate.get("present")),
        "promotion_evidence_present": bool(promotion.get("ready")),
        "required_layer_count": int(promotion.get("required_layer_count") or len(REQUIRED_LAYER_IDS)),
        "passed_layer_count": int(promotion.get("passed_layer_count") or 0),
        "blocked_layer_count": int(promotion.get("blocked_layer_count") or 0),
        "blocked_layer_ids": _list_of_str(promotion.get("blocked_layer_ids")),
        "first_blocker": blockers[0] if blockers else "",
        "next_required_evidence": _list_of_str(promotion.get("next_required_evidence")),
        "paper_queue_status": "locked",
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }


def _evidence_tiers(
    layers: Mapping[str, Mapping[str, Any]],
    evidence_gap_summary: Mapping[str, Any],
    *,
    promotion_ready: bool,
) -> list[dict[str, Any]]:
    fixture = _mapping(evidence_gap_summary.get("fixture_evidence"))
    candidate = _mapping(evidence_gap_summary.get("candidate_evidence"))
    promotion = _mapping(evidence_gap_summary.get("promotion_evidence"))
    promotion_next = _list_of_str(promotion.get("next_required_evidence"))
    return [
        {
            "tier_id": "fixture",
            "classification": "fixture_plumbing_only",
            "present": bool(fixture.get("present")),
            "status": str(fixture.get("status") or "missing"),
            "can_promote": False,
            "can_unlock_paper_or_live": False,
            "required_layers": ["fixture_isolation"],
            "passed_layers": _passed_layers(layers, ["fixture_isolation"]),
            "blocked_layers": _blocked_layers(layers, ["fixture_isolation"]),
            "blockers": _list_of_str(fixture.get("blockers")),
            "next_required_evidence": [
                "keep fixture ledger isolated from candidate and promotion evidence",
            ],
            "reason": str(fixture.get("reason") or "fixture evidence cannot be used for promotion"),
        },
        {
            "tier_id": "candidate",
            "classification": "strategy_candidate_research",
            "present": bool(candidate.get("present")),
            "status": str(candidate.get("status") or "missing"),
            "can_promote": False,
            "can_unlock_paper_or_live": False,
            "required_layers": ["candidate_strategy_validation"],
            "passed_layers": _passed_layers(layers, ["candidate_strategy_validation"]),
            "blocked_layers": _blocked_layers(layers, ["candidate_strategy_validation"]),
            "blockers": _list_of_str(candidate.get("blockers")),
            "next_required_evidence": [
                "attach independent portfolio ledger, cost stress, walk-forward, construction and exposure evidence",
            ],
            "reason": str(candidate.get("reason") or "candidate evidence cannot promote without portfolio evidence"),
        },
        {
            "tier_id": "promotion",
            "classification": "portfolio_promotion_evidence",
            "present": bool(promotion_ready),
            "status": "ready" if promotion_ready else "blocked",
            "can_promote": bool(promotion_ready),
            "can_unlock_paper_or_live": False,
            "required_layers": [
                "portfolio_event_ledger",
                "event_driven_backtest",
                "ledger_pnl",
                "portfolio_construction",
                "portfolio_cost_stress",
                "portfolio_walk_forward",
                "exposure_constraints",
                "promotion_gate",
            ],
            "passed_layers": _passed_layers(
                layers,
                [
                    "portfolio_event_ledger",
                    "event_driven_backtest",
                    "ledger_pnl",
                    "portfolio_construction",
                    "portfolio_cost_stress",
                    "portfolio_walk_forward",
                    "exposure_constraints",
                    "promotion_gate",
                ],
            ),
            "blocked_layers": _list_of_str(promotion.get("blocked_layer_ids")),
            "blockers": [
                blocker
                for blockers in _mapping(promotion.get("blockers_by_layer")).values()
                for blocker in _list_of_str(blockers)
            ],
            "next_required_evidence": promotion_next
            or ["manual review still required before any paper/live path"],
            "reason": "portfolio promotion evidence may become ready, but paper/live stays locked for separate manual gates",
        },
    ]


def _evidence_source_matrix(
    layers: Mapping[str, Mapping[str, Any]],
    evidence_gap_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fixture = _mapping(evidence_gap_summary.get("fixture_evidence"))
    candidate = _mapping(evidence_gap_summary.get("candidate_evidence"))
    promotion = _mapping(evidence_gap_summary.get("promotion_evidence"))
    promotion_next = _list_of_str(promotion.get("next_required_evidence"))
    rows = [
        _evidence_source_row(
            source_id="portfolio_fixture_event_ledger",
            evidence_tier="fixture",
            classification="fixture_plumbing_only",
            layer=_mapping(layers.get("fixture_isolation")),
            present=bool(fixture.get("present")),
            required_for_promotion=False,
            next_required_evidence=["keep fixture ledger isolated from promotion evidence"],
        ),
        _evidence_source_row(
            source_id="strategy_validation_gate",
            evidence_tier="candidate",
            classification="strategy_candidate_research",
            layer=_mapping(layers.get("candidate_strategy_validation")),
            present=bool(candidate.get("present")),
            required_for_promotion=True,
            next_required_evidence=["candidate validation must pass before portfolio evidence can be considered"],
        ),
    ]
    for layer_id in (
        "portfolio_event_ledger",
        "event_driven_backtest",
        "ledger_pnl",
        "portfolio_construction",
        "portfolio_cost_stress",
        "portfolio_walk_forward",
        "exposure_constraints",
        "promotion_gate",
    ):
        layer = _mapping(layers.get(layer_id))
        rows.append(
            _evidence_source_row(
                source_id=layer_id,
                evidence_tier="promotion",
                classification="portfolio_promotion_evidence",
                layer=layer,
                present=layer.get("passed") is True,
                required_for_promotion=True,
                next_required_evidence=promotion_next
                if layer.get("passed") is not True
                else ["manual review still required before any paper/live path"],
            )
        )
    return rows


def _evidence_source_row(
    *,
    source_id: str,
    evidence_tier: str,
    classification: str,
    layer: Mapping[str, Any],
    present: bool,
    required_for_promotion: bool,
    next_required_evidence: list[str],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "evidence_tier": evidence_tier,
        "classification": classification,
        "layer_id": str(layer.get("layer_id") or ""),
        "source_report": str(layer.get("source_report") or ""),
        "status": str(layer.get("status") or "missing"),
        "passed": layer.get("passed") is True,
        "present": bool(present),
        "required_for_promotion": bool(required_for_promotion),
        "promotion_eligible": layer.get("promotion_eligible") is True and evidence_tier == "promotion",
        "can_unlock_paper_or_live": False,
        "blockers": _list_of_str(layer.get("blockers")),
        "next_required_evidence": next_required_evidence,
    }


def _passed_layers(layers: Mapping[str, Mapping[str, Any]], layer_ids: list[str]) -> list[str]:
    return [layer_id for layer_id in layer_ids if _mapping(layers.get(layer_id)).get("passed") is True]


def _blocked_layers(layers: Mapping[str, Mapping[str, Any]], layer_ids: list[str]) -> list[str]:
    return [layer_id for layer_id in layer_ids if _mapping(layers.get(layer_id)).get("passed") is not True]


def _evidence_gap_summary(layers: Mapping[str, Mapping[str, Any]], *, promotion_ready: bool) -> dict[str, Any]:
    fixture_layer = _mapping(layers.get("fixture_isolation"))
    candidate_layer = _mapping(layers.get("candidate_strategy_validation"))
    promotion_layers = [
        layer_id
        for layer_id in REQUIRED_LAYER_IDS
        if layer_id not in {"fixture_isolation", "candidate_strategy_validation", "promotion_gate"}
    ]
    blocked_layer_ids = [
        layer_id
        for layer_id in REQUIRED_LAYER_IDS
        if _mapping(layers.get(layer_id)).get("passed") is not True
    ]
    blocker_by_layer = {
        layer_id: _list_of_str(_mapping(layers.get(layer_id)).get("blockers"))
        for layer_id in blocked_layer_ids
    }
    missing_promotion_layers = [
        layer_id
        for layer_id in promotion_layers
        if _mapping(layers.get(layer_id)).get("passed") is not True
    ]
    return {
        "fixture_evidence": {
            "present": bool(fixture_layer.get("source_type") and fixture_layer.get("source_type") != "none"),
            "status": str(fixture_layer.get("status") or "missing"),
            "can_promote": False,
            "blockers": _list_of_str(fixture_layer.get("blockers")),
            "reason": "fixture evidence proves plumbing only and is never promotion evidence",
        },
        "candidate_evidence": {
            "present": str(candidate_layer.get("gate_status") or "missing") != "missing",
            "status": str(candidate_layer.get("status") or "missing"),
            "can_promote_without_portfolio_ledger": False,
            "blockers": _list_of_str(candidate_layer.get("blockers")),
            "reason": "strategy validation is candidate evidence; portfolio promotion requires independent portfolio evidence",
        },
        "promotion_evidence": {
            "ready": bool(promotion_ready),
            "required_layer_count": len(REQUIRED_LAYER_IDS),
            "passed_layer_count": sum(1 for layer_id in REQUIRED_LAYER_IDS if _mapping(layers.get(layer_id)).get("passed") is True),
            "blocked_layer_count": len(blocked_layer_ids),
            "blocked_layer_ids": blocked_layer_ids,
            "missing_promotion_layer_ids": missing_promotion_layers,
            "blockers_by_layer": blocker_by_layer,
            "next_required_evidence": _next_required_evidence(missing_promotion_layers),
        },
    }


def _next_required_evidence(missing_promotion_layers: list[str]) -> list[str]:
    actions_by_layer = {
        "portfolio_event_ledger": "produce a production event ledger candidate, not a fixture ledger",
        "event_driven_backtest": "prove the data -> signal -> portfolio -> risk -> order_intent -> simulated_fill -> ledger -> report flow",
        "ledger_pnl": "provide fills, ledger PnL, cost model, cash conservation, and position conservation evidence",
        "portfolio_construction": "prove forecast-to-target portfolio construction with volatility, turnover and liquidity evidence",
        "portfolio_cost_stress": "attach portfolio-layer cost stress and 50bps strategy cost-stress survival evidence",
        "portfolio_walk_forward": "attach walk-forward evidence with nonzero folds and stable-enough status",
        "exposure_constraints": "attach sector/style exposure checks for the target portfolio",
    }
    return [actions_by_layer[layer_id] for layer_id in missing_promotion_layers if layer_id in actions_by_layer]


def _fixture_isolation_layer(fixture_ledger: Mapping[str, Any]) -> dict[str, Any]:
    source_type = str(fixture_ledger.get("source_type") or "none")
    promotion_evidence = bool(fixture_ledger.get("promotion_evidence", False))
    blockers = []
    if not fixture_ledger:
        blockers.append("portfolio_fixture_ledger_missing")
    if promotion_evidence:
        blockers.append("portfolio_fixture_ledger_wrongly_marked_promotion_evidence")
    return {
        "layer_id": "fixture_isolation",
        "status": "pass" if fixture_ledger and source_type == "fixture" and not promotion_evidence else "blocked",
        "passed": bool(fixture_ledger and source_type == "fixture" and not promotion_evidence),
        "promotion_eligible": False,
        "source_type": source_type,
        "exclusion_reason": "source_type_fixture_not_promotion_evidence" if source_type == "fixture" else "",
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio_fixture_ledger/latest/portfolio_fixture_event_ledger_report.json",
        "summary": "fixture ledger may prove plumbing only; it is explicitly excluded from promotion evidence",
    }


def _candidate_strategy_validation_layer(strategy_validation_gate: Mapping[str, Any]) -> dict[str, Any]:
    status = str(strategy_validation_gate.get("status") or "missing")
    checks = _mapping(strategy_validation_gate.get("checks"))
    allowed = status == "validation_passed_for_forward_observation"
    blockers = [] if allowed else [f"strategy_validation_gate_not_passed:{status}"]
    if bool(strategy_validation_gate.get("paper_ready", False)) or bool(strategy_validation_gate.get("live_ready", False)):
        blockers.append("strategy_validation_gate_must_not_directly_unlock_paper_or_live")
    return {
        "layer_id": "candidate_strategy_validation",
        "status": "pass" if allowed else "blocked",
        "passed": allowed,
        "promotion_eligible": False,
        "gate_status": status,
        "strategy_id": str(strategy_validation_gate.get("strategy_id") or ""),
        "checks_summary": {
            "cost_stress_passed": _check_passed(checks, "cost_stress"),
            "walk_forward_passed": _check_passed(checks, "walk_forward"),
            "parameter_stability_passed": _check_passed(checks, "parameter_stability"),
            "data_coverage_and_quality_passed": _check_passed(checks, "data_coverage_and_quality"),
        },
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        "summary": "strategy validation is candidate evidence only; portfolio promotion still requires ledger, PnL, cost stress, exposure and walk-forward evidence",
    }


def _portfolio_event_ledger_layer(portfolio_canonical: Mapping[str, Any]) -> dict[str, Any]:
    status = str(_mapping(portfolio_canonical.get("event_ledger_status")).get("status") or "missing")
    ledger_validation = _mapping(portfolio_canonical.get("ledger_validation"))
    source_type = str(ledger_validation.get("source_type") or "none")
    candidate = bool(ledger_validation.get("event_ledger_candidate", False))
    passed = status == "pass" and candidate and source_type == "production"
    blockers = []
    if status != "pass":
        blockers.append(f"portfolio_event_ledger_not_passed:{status}")
    if not candidate:
        blockers.append("portfolio_event_ledger_candidate_required")
    if source_type != "production":
        blockers.append(f"portfolio_event_ledger_source_type_not_production:{source_type}")
    return {
        "layer_id": "portfolio_event_ledger",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "event_ledger_status": status,
        "source_type": source_type,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        "summary": "portfolio promotion requires a production event ledger, not embedded fixture plumbing",
    }


def _event_driven_backtest_layer(portfolio_canonical: Mapping[str, Any]) -> dict[str, Any]:
    backtest_flow = _mapping(portfolio_canonical.get("backtest_flow"))
    status = str(backtest_flow.get("status") or "missing")
    source_type = str(backtest_flow.get("source_type") or "none")
    all_steps_present = backtest_flow.get("all_steps_present") is True
    pnl_source = str(backtest_flow.get("pnl_source") or "")
    blockers = _list_of_str(backtest_flow.get("blockers"))
    if not backtest_flow:
        blockers.append("event_driven_backtest_flow_missing")
    if status != "pass":
        blockers.append(f"event_driven_backtest_flow_not_passed:{status}")
    if source_type != "production":
        blockers.append(f"event_driven_backtest_source_type_not_production:{source_type}")
    if all_steps_present is not True:
        blockers.append("event_driven_backtest_all_steps_required")
    if pnl_source != "ledger_fills":
        blockers.append(f"event_driven_backtest_pnl_source_not_ledger_fills:{pnl_source or 'missing'}")
    passed = not blockers
    return {
        "layer_id": "event_driven_backtest",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "flow_status": status,
        "source_type": source_type,
        "all_steps_present": all_steps_present,
        "required_sequence": list(backtest_flow.get("required_sequence", [])) if isinstance(backtest_flow.get("required_sequence"), list) else [],
        "pnl_source": pnl_source,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        "summary": "portfolio promotion requires an event-driven backtest flow from data through fills, ledger and report",
    }


def _ledger_pnl_layer(portfolio_canonical: Mapping[str, Any]) -> dict[str, Any]:
    ledger_validation = _mapping(portfolio_canonical.get("ledger_validation"))
    source_type = str(ledger_validation.get("source_type") or "none")
    required_flags = {
        "fills_available": bool(ledger_validation.get("fills_available", False)),
        "ledger_pnl_available": bool(ledger_validation.get("ledger_pnl_available", False)),
        "cost_model_available": bool(ledger_validation.get("cost_model_available", False)),
        "cash_conservation_pass": bool(ledger_validation.get("cash_conservation_pass", False)),
        "position_conservation_pass": bool(ledger_validation.get("position_conservation_pass", False)),
    }
    blockers = [f"ledger_validation_missing:{key}" for key, passed in required_flags.items() if not passed]
    if source_type != "production":
        blockers.append(f"ledger_pnl_source_type_not_production:{source_type}")
    passed = not blockers
    return {
        "layer_id": "ledger_pnl",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "source_type": source_type,
        "required_flags": required_flags,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        "summary": "fills, ledger PnL, cost model and conservation checks must be recomputable from non-fixture evidence",
    }


def _portfolio_construction_layer(portfolio_canonical: Mapping[str, Any]) -> dict[str, Any]:
    construction = _mapping(portfolio_canonical.get("portfolio_construction"))
    maturity = _mapping(portfolio_canonical.get("portfolio_evidence_maturity"))
    source_type = str(construction.get("source_type") or maturity.get("portfolio_construction_source_type") or "none")
    status = str(construction.get("status") or "missing")
    required_flags = {
        "forecast_to_target_position_available": bool(
            construction.get("forecast_to_target_position_available", maturity.get("forecast_to_target_position_available", False))
        ),
        "volatility_model_available": bool(
            construction.get("volatility_model_available", maturity.get("volatility_model_available", False))
        ),
        "turnover_report_available": bool(
            construction.get("turnover_report_available", maturity.get("turnover_report_available", False))
        ),
        "liquidity_report_available": bool(
            construction.get("liquidity_report_available", maturity.get("liquidity_report_available", False))
        ),
    }
    blockers = [f"portfolio_construction_missing:{key}" for key, passed in required_flags.items() if not passed]
    if not construction:
        blockers.append("portfolio_construction_report_missing")
    if status not in {"pass", "ready"}:
        blockers.append(f"portfolio_construction_status_not_pass:{status}")
    if source_type != "production":
        blockers.append(f"portfolio_construction_source_type_not_production:{source_type}")
    passed = not blockers
    return {
        "layer_id": "portfolio_construction",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "source_type": source_type,
        "construction_status": status,
        "required_flags": required_flags,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        "summary": "portfolio promotion requires forecast-to-target construction evidence with volatility, turnover and liquidity controls",
    }


def _portfolio_cost_stress_layer(
    portfolio_canonical: Mapping[str, Any],
    cost_stress_report: Mapping[str, Any],
) -> dict[str, Any]:
    maturity = _mapping(portfolio_canonical.get("portfolio_evidence_maturity"))
    canonical_available = bool(maturity.get("cost_stress_available", False))
    external_status = str(cost_stress_report.get("status") or "missing")
    survives_50bps = bool(_mapping(cost_stress_report.get("best_50bps")).get("survives_50bps", False))
    stress_levels = [str(item) for item in cost_stress_report.get("stress_cost_bps", [])] if isinstance(cost_stress_report.get("stress_cost_bps"), list) else []
    blockers = []
    if not canonical_available:
        blockers.append("portfolio_cost_stress_missing_from_portfolio_layer")
    if external_status == "missing":
        blockers.append("strategy_cost_stress_report_missing")
    if "50" not in stress_levels and "50bps" not in stress_levels:
        blockers.append("cost_stress_50bps_required")
    if not survives_50bps:
        blockers.append("cost_stress_50bps_not_survived_or_unproven")
    passed = not blockers
    return {
        "layer_id": "portfolio_cost_stress",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "portfolio_layer_available": canonical_available,
        "strategy_cost_stress_status": external_status,
        "stress_levels": stress_levels,
        "survives_50bps": survives_50bps,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_cost_stress_report.json",
        "summary": "strategy cost stress is not enough unless portfolio layer cost stress is also available",
    }


def _portfolio_walk_forward_layer(walk_forward_report: Mapping[str, Any]) -> dict[str, Any]:
    status = str(walk_forward_report.get("status") or "missing")
    walk_forward = _mapping(walk_forward_report.get("walk_forward"))
    stable = bool(walk_forward.get("stable_enough_for_next_research_stage", False)) or bool(
        _mapping(walk_forward_report.get("stability")).get("stable_enough_for_next_research_stage", False)
    )
    fold_count = int(walk_forward.get("fold_count") or 0)
    blockers = []
    if status == "missing":
        blockers.append("portfolio_walk_forward_report_missing")
    if fold_count <= 0:
        blockers.append("portfolio_walk_forward_fold_count_missing")
    if not stable:
        blockers.append("portfolio_walk_forward_not_stable_enough")
    passed = not blockers
    return {
        "layer_id": "portfolio_walk_forward",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "report_status": status,
        "fold_count": fold_count,
        "stable_enough": stable,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_walk_forward_stability_report.json",
        "summary": "promotion requires out-of-sample walk-forward evidence, not a single full-sample backtest",
    }


def _exposure_constraints_layer(portfolio_canonical: Mapping[str, Any]) -> dict[str, Any]:
    blockers = [str(item) for item in portfolio_canonical.get("blockers", []) if "exposure" in str(item) or "sector" in str(item) or "style" in str(item)]
    maturity = _mapping(portfolio_canonical.get("portfolio_evidence_maturity"))
    exposure_available = bool(maturity.get("exposure_report_available", False))
    if not exposure_available:
        blockers.append("portfolio_exposure_report_missing")
    passed = not blockers and exposure_available
    return {
        "layer_id": "exposure_constraints",
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "promotion_eligible": passed,
        "exposure_report_available": exposure_available,
        "blockers": _dedupe(blockers),
        "source_report": "artifacts/us_equity_portfolio/latest/portfolio_canonical_report.json",
        "summary": "portfolio promotion requires sector/style exposure checks in addition to target weights",
    }


def _source_ref(repo_root: Path, payload: Mapping[str, Any], default: str) -> str | None:
    if not payload:
        return None
    return default


def _check_passed(checks: Mapping[str, Any], key: str) -> bool:
    return bool(_mapping(checks.get(key)).get("passed", False))


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_str(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
