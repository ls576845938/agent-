from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_perpetual_gate_objective_status_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_perpetual_gate_objective_status/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_gate_objective_status_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_perpetual_gate_objective_status_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

DEFAULT_EVIDENCE_REPORT = Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json")
DEFAULT_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
DEFAULT_DEPTH_REPORT = Path("artifacts/btc_cost_model/latest/btc_depth_slippage_report.json")
DEFAULT_FILL_MAPPING_REPORT = Path("artifacts/btc_cost_model/latest/btc_depth_slippage_fill_mapping_report.json")
DEFAULT_L2_BATCH_REPORT = Path("artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_batch_report.json")
DEFAULT_REPLAY_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json")
DEFAULT_DRILL_REPORT = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_report.json")


def build_btc_perpetual_gate_objective_status(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    evidence_report_path: Path = DEFAULT_EVIDENCE_REPORT,
    cost_model_report_path: Path = DEFAULT_COST_MODEL_REPORT,
    depth_report_path: Path = DEFAULT_DEPTH_REPORT,
    fill_mapping_report_path: Path = DEFAULT_FILL_MAPPING_REPORT,
    l2_batch_report_path: Path = DEFAULT_L2_BATCH_REPORT,
    replay_report_path: Path = DEFAULT_REPLAY_REPORT,
    drill_report_path: Path = DEFAULT_DRILL_REPORT,
    generated_at_utc: datetime | None = None,
    current_code_commit: str | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    code_commit = current_code_commit or _git_commit()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    evidence, evidence_error = _read_json(evidence_report_path)
    cost_model, cost_model_error = _read_json(cost_model_report_path)
    depth, depth_error = _read_json(depth_report_path)
    fill_mapping, fill_error = _read_json(fill_mapping_report_path)
    l2_batch, l2_error = _read_json(l2_batch_report_path)
    replay, replay_error = _read_json(replay_report_path)
    drill, drill_error = _read_json(drill_report_path)

    evidence_checks = {
        str(row.get("check_id")): str(row.get("status"))
        for row in _list(_mapping(evidence).get("evidence_checklist"))
        if isinstance(row, Mapping)
    }
    mark = _mapping(_mapping(cost_model).get("mark_price_model"))
    replay_summary = _mapping(_mapping(replay).get("summary"))
    drill_summary = _mapping(_mapping(drill).get("summary"))
    replay_liquidation = _mapping(replay_summary.get("liquidation_buffer_evidence"))
    drill_liquidation = _mapping(drill_summary.get("liquidation_buffer_evidence"))
    depth_progress = _mapping(_mapping(l2_batch).get("depth_gate_progress_after"))
    depth_coverage = _mapping(_mapping(depth).get("snapshot_coverage"))
    fill_summary = _mapping(_mapping(fill_mapping).get("summary"))
    l2_diag = _mapping(_mapping(evidence).get("l2_depth_diagnostics"))
    replay_generated = _timestamp(_mapping(replay).get("generated_at_utc"))
    fill_mapping_generated = _timestamp(_mapping(fill_mapping).get("generated_at_utc"))
    depth_required_days = _positive_float(depth_progress.get("required_two_sided_coverage_days"), default=14.0)
    depth_required_snapshots = _positive_float(depth_progress.get("required_two_sided_snapshot_count"), default=48.0)

    checks = [
        _check(
            "evidence_json_parseable",
            evidence_error is None and bool(evidence),
            "btc_perpetual_execution_evidence_report.json can be parsed as JSON",
            {"path": _portable_path(evidence_report_path), "error": evidence_error},
        ),
        _check(
            "current_mark_price_available",
            evidence_checks.get("current_mark_price_available") == "pass"
            and mark.get("mark_price_current_available") is True,
            "current mark price is available",
            mark,
        ),
        _check(
            "mark_used_for_liquidation_risk",
            evidence_checks.get("mark_used_for_liquidation_risk") == "pass"
            and mark.get("mark_price_used_for_liquidation_risk") is True,
            "liquidation risk uses current mark price, not spot close proxy",
            mark,
        ),
        _check(
            "liquidation_buffer_visible_in_replay",
            (
                _liquidation_buffer_visible(replay_summary, replay_liquidation)
                and replay_liquidation.get("uses_mark_price_reference") is True
            )
            or (
                _liquidation_buffer_visible(drill_summary, drill_liquidation)
                and drill_liquidation.get("uses_mark_price_reference") is True
            ),
            "liquidation buffer and mark price reference are visible in replay evidence",
            {
                "current_replay_visible": _liquidation_buffer_visible(replay_summary, replay_liquidation),
                "current_replay_uses_mark_price_reference": replay_liquidation.get("uses_mark_price_reference"),
                "drill_replay_visible": _liquidation_buffer_visible(drill_summary, drill_liquidation),
                "drill_replay_uses_mark_price_reference": drill_liquidation.get("uses_mark_price_reference"),
                "drill_is_gate_evidence": drill_summary.get("paper_runtime_gate_evidence"),
            },
        ),
        _check(
            "okx_same_venue_depth_source",
            depth_progress.get("selected_venue") == "okx_swap"
            and depth_progress.get("same_venue_as_execution_gate") is True,
            "depth evidence source is OKX swap, same venue as selected execution gate",
            depth_progress,
        ),
        _check(
            "btc_depth_instrument_filter_verified",
            _depth_instrument_filter_verified(depth),
            "depth evidence is explicitly filtered to BTCUSDT / BTC-USDT-SWAP instruments",
            {
                "depth_report_symbol": _mapping(depth).get("symbol"),
                "depth_instrument_filter": _mapping(depth).get("depth_instrument_filter"),
                "depth_source_paths": _mapping(depth).get("depth_source_paths"),
            },
        ),
        _check(
            "binance_cross_venue_not_substituted",
            l2_diag.get("free_public_cross_venue_depth_gate_eligible_for_selected_venue") is False
            and l2_diag.get("free_public_cross_venue_depth_verified_for_selected_venue") is not True,
            "Binance cross-venue diagnostics are not counted as OKX gate evidence",
            l2_diag,
        ),
        _check(
            "depth_artifacts_match_current_code",
            _mapping(depth).get("code_commit") == code_commit
            and _mapping(fill_mapping).get("code_commit") == code_commit,
            "depth report and strategy fill mapping are built from the current code commit",
            {
                "current_code_commit": code_commit,
                "depth_report_code_commit": _mapping(depth).get("code_commit"),
                "fill_mapping_report_code_commit": _mapping(fill_mapping).get("code_commit"),
                "depth_report_path": _portable_path(depth_report_path),
                "fill_mapping_report_path": _portable_path(fill_mapping_report_path),
            },
        ),
        _check(
            "depth_fill_mapping_sources_consistent",
            _depth_fill_mapping_sources_consistent(depth=depth, fill_mapping=fill_mapping),
            "depth report and strategy fill mapping use the same OKX bundle and depth source files",
            {
                "depth_selected_bundle_dir": _mapping(depth).get("selected_bundle_dir"),
                "fill_mapping_selected_bundle_dir": _mapping(fill_mapping).get("selected_bundle_dir"),
                "depth_source_paths": _mapping(depth).get("depth_source_paths"),
                "fill_mapping_depth_source_paths": _mapping(fill_mapping).get("depth_source_paths"),
            },
        ),
        _check(
            "depth_history_coverage_window_satisfied",
            _depth_history_window_satisfied(
                depth_progress=depth_progress,
                depth_coverage=depth_coverage,
                required_days=depth_required_days,
                required_snapshots=depth_required_snapshots,
            ),
            "OKX two-sided depth history covers the required continuous window",
            {
                "required_two_sided_snapshot_count": depth_required_snapshots,
                "depth_report_two_sided_snapshot_count": depth_coverage.get("two_sided_snapshot_count"),
                "batch_progress_two_sided_snapshot_count": depth_progress.get("two_sided_snapshot_count"),
                "required_two_sided_coverage_days": depth_required_days,
                "depth_report_two_sided_coverage_days": depth_coverage.get("two_sided_coverage_days"),
                "batch_progress_two_sided_coverage_days": depth_progress.get("two_sided_coverage_days"),
                "remaining_two_sided_coverage_days": depth_progress.get("remaining_two_sided_coverage_days"),
                "max_allowed_two_sided_gap_hours": depth_coverage.get("max_allowed_two_sided_gap_hours")
                or depth_progress.get("max_allowed_two_sided_gap_hours"),
                "max_two_sided_gap_hours": depth_coverage.get("max_two_sided_gap_hours")
                or depth_progress.get("max_two_sided_gap_hours"),
                "depth_report_continuity_satisfied": depth_coverage.get("two_sided_continuity_satisfied"),
                "batch_progress_continuity_satisfied": depth_progress.get("history_continuity_requirement_satisfied"),
                "batch_progress_coverage_satisfied": depth_progress.get("history_coverage_days_requirement_satisfied"),
            },
        ),
        _check(
            "fill_mapping_not_older_than_runtime_replay",
            fill_mapping_generated is not None
            and replay_generated is not None
            and fill_mapping_generated >= replay_generated,
            "strategy fill mapping is rebuilt after the latest paper runtime replay ledger",
            {
                "paper_runtime_replay_generated_at_utc": _mapping(replay).get("generated_at_utc"),
                "fill_mapping_generated_at_utc": _mapping(fill_mapping).get("generated_at_utc"),
                "input_event_ledgers": _mapping(fill_mapping).get("input_event_ledgers"),
            },
        ),
        _check(
            "strategy_fill_mapping_verified",
            fill_summary.get("strategy_fill_mapping_verified") is True
            and _float(fill_summary.get("gate_fill_count")) > 0.0
            and _float(fill_summary.get("mapped_gate_fill_count")) > 0.0,
            "gate-eligible strategy fills are mapped to visible OKX depth",
            fill_summary,
        ),
        _check(
            "depth_aware_slippage_history_verified",
            evidence_checks.get("depth_aware_slippage_history_verified") == "pass"
            and depth_progress.get("depth_aware_slippage_history_verified") is True,
            "depth-aware slippage has been promoted from diagnostic to gate evidence",
            {
                "evidence_check_status": evidence_checks.get("depth_aware_slippage_history_verified"),
                "depth_gate_progress": depth_progress,
            },
        ),
    ]
    blockers = [f"btc_perpetual_gate_objective:{row['check_id']}" for row in checks if row["status"] != "pass"]
    status = "complete_research_only" if not blockers else "incomplete_research_only"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": status,
        "decision": (
            "btc_perpetual_gate_objective_complete_manual_review_only_no_paper_no_live"
            if not blockers
            else "btc_perpetual_gate_objective_incomplete_wait_for_depth_gate_evidence_no_paper_no_live"
        ),
        "scope": "btc_current_objective_json_mark_liquidation_depth_gate_status",
        "code_commit": code_commit,
        "inputs": {
            "evidence_report": _portable_path(evidence_report_path),
            "cost_model_report": _portable_path(cost_model_report_path),
            "depth_report": _portable_path(depth_report_path),
            "fill_mapping_report": _portable_path(fill_mapping_report_path),
            "l2_batch_report": _portable_path(l2_batch_report_path),
            "replay_report": _portable_path(replay_report_path),
            "drill_report": _portable_path(drill_report_path),
        },
        "parse_errors": {
            "evidence_report": evidence_error,
            "cost_model_report": cost_model_error,
            "depth_report": depth_error,
            "fill_mapping_report": fill_error,
            "l2_batch_report": l2_error,
            "replay_report": replay_error,
            "drill_report": drill_error,
        },
        "checks": checks,
        "summary": {
            "pass_count": sum(1 for row in checks if row["status"] == "pass"),
            "fail_count": sum(1 for row in checks if row["status"] != "pass"),
            "current_mark_price_age_hours": mark.get("current_mark_price_age_hours"),
            "two_sided_snapshot_count": depth_progress.get("two_sided_snapshot_count"),
            "two_sided_coverage_days": depth_progress.get("two_sided_coverage_days")
            or depth_coverage.get("two_sided_coverage_days"),
            "remaining_two_sided_coverage_days": depth_progress.get("remaining_two_sided_coverage_days"),
            "gate_fill_count": fill_summary.get("gate_fill_count"),
            "mapped_gate_fill_count": fill_summary.get("mapped_gate_fill_count"),
            "depth_aware_slippage_history_verified": depth_progress.get("depth_aware_slippage_history_verified"),
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(report_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_text(markdown_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    lines = [
        "# BTC 永续 gate 当前目标验收状态",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 通过项：`{summary.get('pass_count')}`",
        f"- 未完成项：`{summary.get('fail_count')}`",
        f"- 当前 mark 年龄小时：`{summary.get('current_mark_price_age_hours')}`",
        f"- OKX 双边 depth 覆盖天数：`{summary.get('two_sided_coverage_days')}`",
        f"- 距离 14 天还差：`{summary.get('remaining_two_sided_coverage_days')}`",
        f"- gate fill 数：`{summary.get('gate_fill_count')}`",
        f"- 已映射 gate fill 数：`{summary.get('mapped_gate_fill_count')}`",
        "",
        "## 检查项",
        "",
    ]
    for row in _list(report.get("checks")):
        if isinstance(row, Mapping):
            lines.append(f"- `{row.get('check_id')}`：`{row.get('status')}` - {row.get('evidence')}")
    lines.extend(
        [
            "",
            "本报告只做当前目标范围的验收状态，不写 paper 队列，不解锁 live，不连接 broker/OMS/order。",
        ]
    )
    return "\n".join(lines) + "\n"


def _check(check_id: str, passed: bool, evidence: str, details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "evidence": evidence,
        "details": details,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - persisted as objective status.
        return {}, f"{type(exc).__name__}: {exc}"
    return (payload if isinstance(payload, dict) else {}, None)


def _liquidation_buffer_visible(summary: Mapping[str, Any], evidence: Mapping[str, Any]) -> bool:
    return summary.get("liquidation_buffer_visible_in_replay") is True or evidence.get("visible_in_replay") is True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_float(value: Any, *, default: float) -> float:
    parsed = _float(value)
    return parsed if parsed > 0.0 else default


def _depth_history_window_satisfied(
    *,
    depth_progress: Mapping[str, Any],
    depth_coverage: Mapping[str, Any],
    required_days: float,
    required_snapshots: float,
) -> bool:
    progress_ok = depth_progress.get("history_coverage_days_requirement_satisfied") is True
    coverage_days_ok = _float(depth_coverage.get("two_sided_coverage_days")) >= required_days
    snapshot_count_ok = _float(depth_coverage.get("two_sided_snapshot_count")) >= required_snapshots
    continuity_ok = depth_coverage.get("two_sided_continuity_satisfied") is True
    return progress_ok and coverage_days_ok and snapshot_count_ok and continuity_ok


def _depth_instrument_filter_verified(depth: Mapping[str, Any]) -> bool:
    instrument_filter = _mapping(depth.get("depth_instrument_filter"))
    accepted = {str(item) for item in _list(instrument_filter.get("accepted_normalized_instruments"))}
    return (
        depth.get("symbol") == "BTCUSDT"
        and instrument_filter.get("requires_explicit_instrument_field") is True
        and {"BTCUSDT", "BTCUSDTSWAP"}.issubset(accepted)
    )


def _depth_fill_mapping_sources_consistent(*, depth: Mapping[str, Any], fill_mapping: Mapping[str, Any]) -> bool:
    depth_bundle = str(depth.get("selected_bundle_dir") or "").strip()
    fill_bundle = str(fill_mapping.get("selected_bundle_dir") or "").strip()
    depth_paths = _path_set(_list(depth.get("depth_source_paths")))
    fill_paths = _path_set(_list(fill_mapping.get("depth_source_paths")))
    return bool(depth_bundle and fill_bundle and depth_bundle == fill_bundle and depth_paths and depth_paths == fill_paths)


def _path_set(paths: list[Any]) -> set[str]:
    return {str(path).replace("\\", "/").strip() for path in paths if str(path).strip()}


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_perpetual_gate_objective_status_safety_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "blockers": list(report.get("blockers", [])),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
