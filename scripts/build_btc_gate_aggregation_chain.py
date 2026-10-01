from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_crypto.research.btc_micro_live_preflight import build_btc_micro_live_preflight  # noqa: E402
from quant_crypto.research.btc_manual_paper_review_approval import (  # noqa: E402
    build_btc_manual_paper_review_approval,
)
from quant_crypto.research.btc_exchange_runtime_replay_gap import (  # noqa: E402
    build_btc_exchange_runtime_replay_gap_report,
)
from quant_crypto.research.btc_exchange_public_runtime_dry_probe import (  # noqa: E402
    build_btc_exchange_public_runtime_dry_probe,
)
from quant_crypto.research.btc_depth_slippage import (  # noqa: E402
    build_btc_depth_slippage_fill_mapping_report,
    build_btc_depth_slippage_report,
)
from quant_crypto.research.btc_perpetual_gate_objective_status import (  # noqa: E402
    build_btc_perpetual_gate_objective_status,
)
from quant_crypto.research.btc_perpetual_execution_evidence import (  # noqa: E402
    build_btc_perpetual_execution_evidence_pack,
)
from quant_crypto.research.btc_perpetual_paper_runtime_reconciliation import (  # noqa: E402
    build_btc_perpetual_paper_runtime_reconciliation_report,
)
from quant_crypto.research.btc_perpetual_paper_runtime_replay import (  # noqa: E402
    build_btc_perpetual_paper_runtime_replay_drill_report,
    build_btc_perpetual_paper_runtime_replay_fixture_drill_report,
    build_btc_perpetual_paper_runtime_replay_report,
)
from quant_crypto.research.btc_paper_exchange_rule_preflight import (  # noqa: E402
    build_btc_paper_exchange_rule_preflight,
)
from quant_crypto.research.btc_paper_live_kill_switch_status import (  # noqa: E402
    build_btc_paper_live_kill_switch_status,
)
from quant_crypto.research.btc_promotion_gate_control import (  # noqa: E402
    DEFAULT_SOURCE_PATHS as PROMOTION_SOURCE_PATHS,
    build_btc_promotion_gate_control,
)
from quant_crypto.research.btc_paper_candidate_packet import (  # noqa: E402
    build_btc_paper_candidate_packet,
)
from quant_crypto.research.btc_strategy_promotion_readiness_review import (  # noqa: E402
    build_btc_strategy_promotion_readiness_review,
)
from quant_crypto.monitoring.btc_dirty_worktree_boundary import (  # noqa: E402
    build_btc_dirty_worktree_boundary_report,
)
from quant_crypto.monitoring.btc_gate_report_consistency import (  # noqa: E402
    build_btc_gate_report_consistency,
)
from quant_crypto.application.btc_gate_snapshot import (  # noqa: E402
    BTC_CONTROL_CENTER_ARTIFACTS,
    capture_gate_build_state,
    gate_build_lock,
    publish_gate_run_snapshot,
)
from scripts.build_btc_paper_readiness_report import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as PAPER_READINESS_OUTPUT_ROOT,
    build_btc_paper_readiness_report,
    write_btc_paper_readiness_report,
)
from scripts.build_btc_cost_model_report import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as COST_MODEL_OUTPUT_ROOT,
    build_btc_cost_model_report,
    write_btc_cost_model_report,
)
from scripts.build_btc_order_surface_audit import build_btc_order_surface_audit_report  # noqa: E402
from scripts.build_btc_gate_dashboard import build_btc_gate_dashboard_file  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("artifacts/btc_gate_aggregation_chain/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_gate_aggregation_chain_report.json"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild the read-only BTC gate aggregation chain.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--aggregation-batch-id", default="")
    return parser.parse_args()


def build_btc_gate_aggregation_chain(
    *,
    repo_root: Path = REPO_ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
    publish_snapshot: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))
    batch_id = aggregation_batch_id or "btc_gate_aggregation_" + generated.strftime("%Y%m%dT%H%M%S%fZ")
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)

    lock = gate_build_lock(root) if publish_snapshot else nullcontext()
    with lock:
        start_state = capture_gate_build_state(root) if publish_snapshot else None
        with _pushd(root):
            steps = [
            _step(
                "manual_paper_review_approval",
                lambda: build_btc_manual_paper_review_approval(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_readiness",
                lambda: _build_btc_paper_readiness_file(root=root, generated=generated, aggregation_batch_id=batch_id),
            ),
            _step(
                "paper_runtime_replay_current",
                lambda: build_btc_perpetual_paper_runtime_replay_report(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_runtime_replay_historical_drill",
                lambda: build_btc_perpetual_paper_runtime_replay_drill_report(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_runtime_replay_fixture_drill",
                lambda: build_btc_perpetual_paper_runtime_replay_fixture_drill_report(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_runtime_reconciliation",
                lambda: build_btc_perpetual_paper_runtime_reconciliation_report(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "depth_slippage_fill_mapping_after_runtime_replay",
                lambda: _tag_batch(
                    build_btc_depth_slippage_fill_mapping_report(
                        repo_root=root,
                        generated_at_utc=generated,
                    ),
                    batch_id,
                ),
            ),
            _step(
                "depth_slippage_after_runtime_replay",
                lambda: _tag_batch(
                    build_btc_depth_slippage_report(
                        repo_root=root,
                        generated_at_utc=generated,
                    ),
                    batch_id,
                ),
            ),
            _step(
                "cost_model_after_depth_slippage",
                lambda: _build_btc_cost_model_file(root=root, generated=generated, aggregation_batch_id=batch_id),
            ),
            _step(
                "order_surface_audit",
                lambda: build_btc_order_surface_audit_report(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_exchange_rule_preflight_initial",
                lambda: build_btc_paper_exchange_rule_preflight(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "public_runtime_dry_probe",
                lambda: build_btc_exchange_public_runtime_dry_probe(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "exchange_runtime_gap",
                lambda: build_btc_exchange_runtime_replay_gap_report(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "perpetual_execution_evidence_after_runtime_gap",
                lambda: _tag_batch(
                    build_btc_perpetual_execution_evidence_pack(
                        generated_at_utc=generated,
                    ),
                    batch_id,
                ),
            ),
            _step(
                "perpetual_gate_objective_after_execution_evidence",
                lambda: _tag_batch(
                    build_btc_perpetual_gate_objective_status(
                        generated_at_utc=generated,
                    ),
                    batch_id,
                ),
            ),
            _step(
                "gate_dashboard_initial",
                lambda: build_btc_gate_dashboard_file(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                    use_promotion_gate_control=False,
                ),
            ),
            _step(
                "strategy_promotion_readiness_initial",
                lambda: build_btc_strategy_promotion_readiness_review(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "kill_switch_status_initial",
                lambda: build_btc_paper_live_kill_switch_status(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_exchange_rule_preflight_final",
                lambda: build_btc_paper_exchange_rule_preflight(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "kill_switch_status_final",
                lambda: build_btc_paper_live_kill_switch_status(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "micro_live_preflight_initial",
                lambda: build_btc_micro_live_preflight(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "gate_dashboard_final",
                lambda: build_btc_gate_dashboard_file(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                    use_promotion_gate_control=False,
                ),
            ),
            _step(
                "strategy_promotion_readiness_final",
                lambda: build_btc_strategy_promotion_readiness_review(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "kill_switch_status_after_strategy_readiness",
                lambda: build_btc_paper_live_kill_switch_status(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "micro_live_preflight_final",
                lambda: build_btc_micro_live_preflight(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "gate_dashboard_after_micro_live_final",
                lambda: build_btc_gate_dashboard_file(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                    use_promotion_gate_control=False,
                ),
            ),
            _step(
                "gate_report_consistency",
                lambda: build_btc_gate_report_consistency(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "dirty_worktree_boundary",
                lambda: build_btc_dirty_worktree_boundary_report(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "promotion_gate_control_initial",
                lambda: build_btc_promotion_gate_control(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "gate_dashboard_after_promotion_control",
                lambda: build_btc_gate_dashboard_file(
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "gate_report_consistency_after_promotion_control",
                lambda: build_btc_gate_report_consistency(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "promotion_gate_control",
                lambda: build_btc_promotion_gate_control(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            _step(
                "paper_candidate_packet_current",
                lambda: build_btc_paper_candidate_packet(
                    repo_root=root,
                    generated_at_utc=generated,
                    aggregation_batch_id=batch_id,
                ),
            ),
            ]

        final_promotion = _payload_for_step(steps, "promotion_gate_control")
        final_packet = _payload_for_step(steps, "paper_candidate_packet_current")
        final_consistency = _payload_for_step(steps, "gate_report_consistency_after_promotion_control")
        final_freshness = final_promotion.get("artifact_freshness", {})
        report_path = output / DEFAULT_REPORT_PATH.name
        safety_path = output / DEFAULT_SAFETY_PATH.name
        report = {
            "schema_version": "btc_gate_aggregation_chain_v2",
            "generated_at_utc": generated.isoformat(),
            "aggregation_batch_id": batch_id,
            "status": _chain_status(steps),
            "decision": "btc_gate_aggregation_chain_rebuilt_read_only_no_paper_no_live",
            "scope": "read_only_gate_dashboard_micro_live_promotion_control_rebuild",
            "step_order": [step["step_id"] for step in steps],
            "steps": steps,
            "final_promotion_status": final_promotion.get("status"),
            "final_promotion_decision": final_promotion.get("decision"),
            "paper_candidate_packet_status": final_packet.get("paper_candidate_packet", {}).get("packet_status", ""),
            "paper_candidate_packet_decision": final_packet.get("decision", ""),
            "artifact_freshness": final_freshness,
            "source_timeline_consistent": final_freshness.get("source_timeline_consistent"),
            "stale_source_count": final_freshness.get("stale_source_count"),
            "dependency_newer_than_consumer_count": final_freshness.get("dependency_newer_than_consumer_count"),
            "required_rebuild_reports": final_promotion.get("required_rebuild_reports", []),
            "root_cause_summary": final_promotion.get("root_cause_summary", {}),
            "snapshot_publication": {
                "status": "pending" if publish_snapshot else "disabled_for_test",
                "published": False,
            },
            "gate": _gate(),
            "guardrails": _guardrails(),
            "outputs": {
                "json": _portable_path(report_path),
                "paper_live_safety_status": _portable_path(safety_path),
            },
        }
        _write_json(report_path, report)
        _write_json(safety_path, _safety_status(report))

        if publish_snapshot and start_state is not None:
            end_state = capture_gate_build_state(root)
            validation_checks = _snapshot_validation_checks(
                steps=steps,
                final_promotion=final_promotion,
                final_packet=final_packet,
                final_consistency=final_consistency,
                batch_id=batch_id,
            )
            try:
                publication = publish_gate_run_snapshot(
                    repo_root=root,
                    aggregation_batch_id=batch_id,
                    generated_at_utc=generated,
                    start_state=start_state,
                    end_state=end_state,
                    step_order=report["step_order"],
                    source_paths=_snapshot_source_paths(root=root, report_path=report_path, safety_path=safety_path),
                    required_paths=_snapshot_required_paths(root=root, report_path=report_path),
                    validation_checks=validation_checks,
                )
            except Exception as exc:  # noqa: BLE001 - fail-closed publication boundary.
                publication = {
                    "status": "publication_exception_fail_closed",
                    "published": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "paper_queue_write_allowed": False,
                    "live_unlock_allowed": False,
                    "broker_or_order_allowed": False,
                }
            report["snapshot_publication"] = publication
            if publication.get("published") is not True:
                report["status"] = "incomplete_fail_closed_research_only"
                report["decision"] = "btc_gate_snapshot_not_published_previous_pointer_preserved_no_paper_no_live"
            _write_json(report_path, report)
            _write_json(safety_path, _safety_status(report))
        return report


def main() -> int:
    args = parse_args()
    report = build_btc_gate_aggregation_chain(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        aggregation_batch_id=args.aggregation_batch_id or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "aggregation_batch_id": report["aggregation_batch_id"],
                "step_order": report["step_order"],
                "final_promotion_status": report["final_promotion_status"],
                "paper_candidate_packet_status": report.get("paper_candidate_packet_status"),
                "source_timeline_consistent": report.get("source_timeline_consistent"),
                "stale_source_count": report.get("stale_source_count"),
                "dependency_newer_than_consumer_count": report.get("dependency_newer_than_consumer_count"),
                "required_rebuild_reports": report.get("required_rebuild_reports", []),
                "artifact_freshness": report.get("artifact_freshness", {}),
                "snapshot_publication": report.get("snapshot_publication", {}),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    publication = report.get("snapshot_publication", {})
    return 0 if publication.get("published") is True else 1


def _step(step_id: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        payload = fn()
        return {
            "step_id": step_id,
            "status": str(payload.get("status", "")),
            "decision": str(payload.get("decision", "")),
            "generated_at_utc": str(payload.get("generated_at_utc") or payload.get("generated_at") or ""),
            "aggregation_batch_id": str(payload.get("aggregation_batch_id") or ""),
            "blocker_count": len(payload.get("blockers", [])) if isinstance(payload.get("blockers"), list) else 0,
            "safety": {
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
                "broker_or_order_allowed": False,
            },
            "payload": payload,
        }
    except Exception as exc:  # pragma: no cover - defensive artifact boundary
        return {
            "step_id": step_id,
            "status": "failed_exception",
            "decision": "btc_gate_aggregation_chain_step_failed_fail_closed",
            "generated_at_utc": "",
            "aggregation_batch_id": "",
            "blocker_count": 1,
            "error": f"{type(exc).__name__}: {exc}",
            "safety": {
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
                "broker_or_order_allowed": False,
            },
            "payload": {},
        }


def _payload_for_step(steps: list[dict[str, Any]], step_id: str) -> dict[str, Any]:
    for step in steps:
        if step.get("step_id") == step_id and isinstance(step.get("payload"), dict):
            return step["payload"]
    return {}


def _build_btc_paper_readiness_file(*, root: Path, generated: datetime, aggregation_batch_id: str) -> dict[str, Any]:
    payload = build_btc_paper_readiness_report(repo_root=root, generated_at=_z_timestamp(generated))
    payload["aggregation_batch_id"] = aggregation_batch_id
    write_btc_paper_readiness_report(payload, _resolve(root, PAPER_READINESS_OUTPUT_ROOT))
    return payload


def _build_btc_cost_model_file(*, root: Path, generated: datetime, aggregation_batch_id: str) -> dict[str, Any]:
    payload = build_btc_cost_model_report(repo_root=root, generated_at=_z_timestamp(generated))
    payload["aggregation_batch_id"] = aggregation_batch_id
    write_btc_cost_model_report(payload, _resolve(root, COST_MODEL_OUTPUT_ROOT))
    return payload


def _tag_batch(payload: dict[str, Any], aggregation_batch_id: str) -> dict[str, Any]:
    payload["aggregation_batch_id"] = aggregation_batch_id
    outputs = payload.get("outputs")
    output_path = outputs.get("json") if isinstance(outputs, dict) else None
    if output_path:
        _write_json(Path(str(output_path)), payload)
    return payload


def _snapshot_source_paths(*, root: Path, report_path: Path, safety_path: Path) -> list[Path]:
    paths = {Path(path) for path in PROMOTION_SOURCE_PATHS.values()}
    paths.update(Path(path) for path in BTC_CONTROL_CENTER_ARTIFACTS.values())
    paths.update(
        {
            _repo_relative(root, report_path),
            _repo_relative(root, safety_path),
            Path("artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"),
            Path("artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json"),
            Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"),
        }
    )
    return sorted(paths, key=_portable_path)


def _snapshot_required_paths(*, root: Path, report_path: Path) -> list[Path]:
    return [
        _repo_relative(root, report_path),
        Path("artifacts/btc_promotion_gate_control/latest/btc_promotion_gate_control_report.json"),
        Path("artifacts/btc_gate_dashboard/latest/btc_gate_dashboard.json"),
        Path("artifacts/btc_gate_report_consistency/latest/btc_gate_report_consistency_report.json"),
        Path("artifacts/btc_perpetual_execution_evidence/latest/btc_perpetual_execution_evidence_report.json"),
        Path("artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"),
    ]


def _snapshot_validation_checks(
    *,
    steps: list[dict[str, Any]],
    final_promotion: dict[str, Any],
    final_packet: dict[str, Any],
    final_consistency: dict[str, Any],
    batch_id: str,
) -> dict[str, bool]:
    freshness = final_promotion.get("artifact_freshness", {})
    required_rebuilds = final_promotion.get("required_rebuild_reports", [])
    step_batch_ids = [str(step.get("aggregation_batch_id") or "") for step in steps]
    return {
        "chain_steps_completed_without_exception": all(step.get("status") != "failed_exception" for step in steps),
        "all_step_batch_ids_match": bool(step_batch_ids) and all(value == batch_id for value in step_batch_ids),
        "gate_report_consistency_passed": final_consistency.get("status") == "pass",
        "promotion_artifact_freshness_evaluated": freshness.get("status") in {"pass", "fail"},
        "promotion_source_timeline_consistent": freshness.get("source_timeline_consistent") is True,
        "promotion_rebuild_plan_explicit": isinstance(required_rebuilds, list),
        "promotion_batch_matches": final_promotion.get("aggregation_batch_id") == batch_id,
        "paper_candidate_packet_batch_matches": final_packet.get("aggregation_batch_id") == batch_id,
        "all_safety_flags_fail_closed": all(_step_safety_fail_closed(step) for step in steps),
    }


def _step_safety_fail_closed(step: dict[str, Any]) -> bool:
    payload = step.get("payload", {})
    if not isinstance(payload, dict):
        return False
    for container_name in ("gate", "guardrails", "safety"):
        container = payload.get(container_name, {})
        if not isinstance(container, dict):
            continue
        for field in (
            "paper_queue_write_allowed",
            "paper_allowed",
            "live_unlock_allowed",
            "live_order_allowed",
            "broker_or_order_allowed",
            "broker_access_allowed",
            "oms_access_allowed",
            "order_endpoint_used",
            "private_endpoint_used",
            "real_order_submitted",
        ):
            if container.get(field) is True:
                return False
    return True


def _repo_relative(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"gate aggregation output is outside repo root: {path}") from exc


def _z_timestamp(value: datetime) -> str:
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chain_status(steps: list[dict[str, Any]]) -> str:
    if any(step.get("status") == "failed_exception" for step in steps):
        return "incomplete_fail_closed_research_only"
    return "complete_read_only_research_only"


def _gate() -> dict[str, bool]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "read_only_aggregation_only": True,
        "network_collection_used": True,
        "public_network_probe_used": True,
        "strategy_rerun_used": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _safety_status(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_gate_aggregation_chain_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "paper_candidate_created": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_or_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
        "real_order_submitted": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@contextmanager
def _pushd(path: Path):
    old_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


if __name__ == "__main__":
    raise SystemExit(main())
