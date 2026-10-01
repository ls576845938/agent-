from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "btc_exchange_paper_runtime_replay_report_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_paper_runtime_replay_report.json"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_paper_runtime_replay_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_exchange_paper_runtime_replay_safety_status.json"

DEFAULT_ROUTE_REQUEST = Path("artifacts/btc_perpetual_route_request/latest/btc_perpetual_route_request_report.json")
DEFAULT_PAPER_START = Path("artifacts/btc_paper_validation/latest/btc_paper_validation_start_report.json")
DEFAULT_PAPER_RUNTIME = Path("artifacts/btc_paper_validation/latest/btc_paper_validation_runtime_report.json")
DEFAULT_PAPER_EVALUATION = Path("artifacts/btc_paper_validation/latest/btc_paper_validation_evaluation_report.json")
DEFAULT_PAPER_REPLAY = Path("artifacts/btc_paper_validation/latest/btc_paper_validation_replay_report.json")


def build_btc_exchange_paper_runtime_replay_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    route_request_path: Path = DEFAULT_ROUTE_REQUEST,
    paper_start_path: Path = DEFAULT_PAPER_START,
    paper_runtime_path: Path = DEFAULT_PAPER_RUNTIME,
    paper_evaluation_path: Path = DEFAULT_PAPER_EVALUATION,
    paper_replay_path: Path = DEFAULT_PAPER_REPLAY,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    route = _read_json(route_request_path)
    start = _read_json(paper_start_path)
    runtime = _read_json(paper_runtime_path)
    evaluation = _read_json(paper_evaluation_path)
    replay = _read_json(paper_replay_path)

    legacy_ready = _legacy_paper_runtime_ready(start=start, runtime=runtime, evaluation=evaluation, replay=replay)
    route_requires_perp = route.get("perpetual_route_requested") is True
    replay_policy = _mapping(replay.get("perpetual_risk_policy") or _mapping(replay.get("metadata")).get("perpetual_risk_policy"))
    replay_is_perp = replay_policy.get("perpetual_allowed") is True or replay_policy.get("liquidation_risk_required") is True
    current_ready = legacy_ready and (not route_requires_perp or replay_is_perp)
    blockers = _blockers(
        legacy_ready=legacy_ready,
        route_requires_perp=route_requires_perp,
        replay_is_perp=replay_is_perp,
        start=start,
        runtime=runtime,
        evaluation=evaluation,
        replay=replay,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "complete_research_only" if current_ready else "incomplete_research_only",
        "decision": (
            "paper_runtime_replay_ready_for_manual_review"
            if current_ready
            else "paper_runtime_replay_not_applicable_to_current_perpetual_route_no_paper_no_live"
        ),
        "scope": "btc_exchange_paper_runtime_replay_applicability_no_order_no_broker",
        "code_commit": _git(["rev-parse", "--short", "HEAD"]),
        "route_request": {
            "path": _portable_path(route_request_path),
            "present": bool(route),
            "status": route.get("status"),
            "perpetual_route_requested": route.get("perpetual_route_requested"),
            "eligible_strategy_line_count": route.get("eligible_strategy_line_count"),
            "paper_queue_write_allowed": _mapping(route.get("gate")).get("paper_queue_write_allowed"),
            "live_unlock_allowed": _mapping(route.get("gate")).get("live_unlock_allowed"),
        },
        "legacy_paper_runtime": {
            "ready": legacy_ready,
            "source_strategy_id": start.get("strategy_id") or _mapping(_mapping(replay.get("replayed_outputs")).get("signal")).get("strategy_id"),
            "start_status": start.get("status"),
            "runtime_status": runtime.get("status"),
            "runtime_decision": runtime.get("decision"),
            "evaluation_status": evaluation.get("status"),
            "evaluation_decision": evaluation.get("decision"),
            "replay_status": replay.get("status"),
            "replay_decision": replay.get("decision"),
            "days_completed": evaluation.get("days_completed"),
            "total_orders": evaluation.get("total_orders"),
            "total_fills": evaluation.get("total_fills"),
            "total_rejected": evaluation.get("total_rejected"),
            "profitability_conclusion": evaluation.get("profitability_conclusion"),
        },
        "current_route_applicability": {
            "current_route_requires_perpetual": route_requires_perp,
            "legacy_replay_perpetual_allowed": replay_policy.get("perpetual_allowed"),
            "legacy_replay_liquidation_risk_required": replay_policy.get("liquidation_risk_required"),
            "legacy_replay_perp_status": replay_policy.get("status"),
            "current_perpetual_paper_runtime_replay_ready": current_ready,
            "reason": (
                "legacy paper runtime is for spot/unlevered route; current BTC research route requires perpetual execution replay"
                if route_requires_perp and not replay_is_perp
                else "paper runtime replay matches current route boundary"
            ),
        },
        "source_reports": {
            "paper_start": _source_status(paper_start_path, start),
            "paper_runtime": _source_status(paper_runtime_path, runtime),
            "paper_evaluation": _source_status(paper_evaluation_path, evaluation),
            "paper_replay": _source_status(paper_replay_path, replay),
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
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
    legacy = _mapping(report.get("legacy_paper_runtime"))
    current = _mapping(report.get("current_route_applicability"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC paper runtime replay 适用性报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 旧 paper runtime 是否完整：`{legacy.get('ready')}`",
        f"- 旧 paper 策略：`{legacy.get('source_strategy_id')}`",
        f"- 当前路线需要永续：`{current.get('current_route_requires_perpetual')}`",
        f"- 当前永续 paper runtime replay 是否就绪：`{current.get('current_perpetual_paper_runtime_replay_ready')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "这个报告只判断现有 paper runtime replay 是否能用于当前 BTC 永续研究线。它不下单，不访问私有接口，不解锁 paper/live。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 阻断项"])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _legacy_paper_runtime_ready(
    *,
    start: Mapping[str, Any],
    runtime: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    replay: Mapping[str, Any],
) -> bool:
    if not all((start, runtime, evaluation, replay)):
        return False
    if start.get("status") != "complete" or runtime.get("status") != "complete" or evaluation.get("status") != "complete":
        return False
    if replay.get("status") != "replay_pass":
        return False
    if runtime.get("decision") != "paper_validation_runtime_complete":
        return False
    if evaluation.get("decision") != "paper_validation_evaluation_complete":
        return False
    if replay.get("decision") != "replay_pass":
        return False
    if any(payload.get("blockers") for payload in (start, runtime, evaluation, replay)):
        return False
    unsafe_keys = ("private_endpoint_used", "order_endpoint_used", "real_order_submitted")
    return not any(payload.get(key) is True for payload in (start, runtime, replay) for key in unsafe_keys)


def _blockers(
    *,
    legacy_ready: bool,
    route_requires_perp: bool,
    replay_is_perp: bool,
    start: Mapping[str, Any],
    runtime: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    replay: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not legacy_ready:
        blockers.append("btc_legacy_paper_runtime_replay_not_ready")
    if route_requires_perp and not replay_is_perp:
        blockers.append("btc_current_perpetual_paper_runtime_replay_missing")
    for source_name, payload in {
        "paper_start": start,
        "paper_runtime": runtime,
        "paper_evaluation": evaluation,
        "paper_replay": replay,
    }.items():
        if not payload:
            blockers.append(f"btc_{source_name}_missing")
        blockers.extend(f"btc_{source_name}:{item}" for item in payload.get("blockers", []) if item)
    return _dedupe(blockers)


def _source_status(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _portable_path(path),
        "exists": path.exists(),
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "artifact_hash": payload.get("artifact_hash"),
        "blockers": payload.get("blockers", []),
    }


def _gate() -> dict[str, Any]:
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
        "schema_version": "btc_exchange_paper_runtime_replay_safety_status_v1",
        "status": "research_only",
        "decision": report.get("decision"),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _portable_path(path: Path) -> str:
    return path.as_posix()


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
