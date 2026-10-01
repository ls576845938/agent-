#!/usr/bin/env python3
"""Run repeated observe-only OKX public L2 depth accumulation cycles."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_btc_okx_l2_depth_observation_daily import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as DEFAULT_DAILY_OUTPUT_ROOT,
    run_btc_okx_l2_depth_observation_daily,
)


SCHEMA_VERSION = "btc_okx_l2_depth_observation_batch_v2"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_l2_depth_observation/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_l2_depth_observation_batch_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_l2_depth_observation_batch_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_l2_depth_observation_batch_safety_status.json"


def run_btc_okx_l2_depth_observation_batch(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    daily_output_root: Path = DEFAULT_DAILY_OUTPUT_ROOT,
    execute_network: bool = False,
    cycles: int = 3,
    cycle_sleep_seconds: float = 300.0,
    sample_count: int = 6,
    trade_limit: int = 100,
    book_size: int = 50,
    request_sleep_seconds: float = 0.25,
    stop_when_depth_gate_ready: bool = True,
    generated_at: str | None = None,
    data_version: str = "unpublished",
    run_id: str | None = None,
    source_head: str | None = None,
    immutable_manifest_verified: bool = False,
    data_steward_attested: bool = False,
    sleep_fn: Any = time.sleep,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    output = _resolve(root, output_root)
    output.mkdir(parents=True, exist_ok=True)
    started = _parse_utc(generated_at or _utc_now())
    resolved_head = source_head or _git_head(root)
    resolved_run_id = run_id or f"btc-l2-observation-{started.strftime('%Y%m%dT%H%M%SZ')}"
    cycle_count = max(1, int(cycles))
    sleep_seconds = max(0.0, float(cycle_sleep_seconds))

    cycle_reports: list[dict[str, Any]] = []
    stopped_reason = "completed_requested_cycles"
    for index in range(cycle_count):
        report = run_btc_okx_l2_depth_observation_daily(
            repo_root=root,
            output_root=daily_output_root,
            execute_network=bool(execute_network),
            sample_count=sample_count,
            trade_limit=trade_limit,
            book_size=book_size,
            request_sleep_seconds=request_sleep_seconds,
            generated_at=None if generated_at is None else _cycle_generated_at(started, index),
        )
        cycle_reports.append(_cycle_summary(index=index + 1, report=report))
        progress = _mapping(report.get("depth_gate_progress"))
        if stop_when_depth_gate_ready and progress.get("gate_ready") is True:
            stopped_reason = "depth_gate_ready"
            break
        if index < cycle_count - 1 and sleep_seconds > 0.0:
            sleep_fn(sleep_seconds)

    progress_before = _mapping(cycle_reports[0].get("depth_gate_progress")) if cycle_reports else {}
    progress_after = _mapping(cycle_reports[-1].get("depth_gate_progress")) if cycle_reports else {}
    requested = {
        "execute_network": bool(execute_network),
        "cycles": cycle_count,
        "cycle_sleep_seconds": sleep_seconds,
        "sample_count": max(1, int(sample_count)),
        "trade_limit": min(100, max(1, int(trade_limit))),
        "book_size": min(400, max(1, int(book_size))),
        "request_sleep_seconds": max(0.0, float(request_sleep_seconds)),
        "stop_when_depth_gate_ready": bool(stop_when_depth_gate_ready),
        "free_data_sources_only": True,
    }
    evidence_blockers = _blockers(cycle_reports)
    if not immutable_manifest_verified:
        evidence_blockers.append("immutable_snapshot_not_published")
    if not data_steward_attested:
        evidence_blockers.append("data_steward_attestation_required")
    if data_version in {"", "unpublished", "fixture"}:
        evidence_blockers.append("okx_timestamp_aligned_l2_manifest_not_published")
    promotion_evidence_ready = bool(progress_after.get("gate_ready")) and not evidence_blockers
    cycle_hashes = {
        f"cycle_{index + 1}": _stable_hash(cycle)
        for index, cycle in enumerate(cycle_reports)
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_generated_at_utc": started.isoformat(),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "data_version": data_version,
        "run_id": resolved_run_id,
        "source_head": resolved_head,
        "params": requested,
        "params_hash": _stable_hash(requested),
        "input_hashes": cycle_hashes,
        "evidence_class": "promotion_evidence" if promotion_evidence_ready else "fixture_or_diagnostic_only",
        "quality_checked": bool(cycle_reports),
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": promotion_evidence_ready,
        "scope": "research_only_repeated_free_public_okx_l2_depth_accumulation_no_order_no_broker",
        "status": _status(execute_network=execute_network, cycle_reports=cycle_reports),
        "decision": "continue_accumulating_free_public_okx_l2_depth_history_fail_closed_no_paper_no_live",
        "requested": requested,
        "completed_cycles": len(cycle_reports),
        "stopped_reason": stopped_reason,
        "depth_gate_progress_before": progress_before,
        "depth_gate_progress_after": progress_after,
        "depth_gate_progress_delta": _progress_delta(before=progress_before, after=progress_after),
        "cycle_reports": cycle_reports,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": _dedupe(evidence_blockers),
        "outputs": {
            "json": _portable_path(output / DEFAULT_REPORT_PATH.name, root),
            "summary_cn": _portable_path(output / DEFAULT_SUMMARY_PATH.name, root),
            "paper_live_safety_status": _portable_path(output / DEFAULT_SAFETY_PATH.name, root),
        },
    }
    report["output_hash"] = _stable_hash(report)
    _write_json(output / DEFAULT_REPORT_PATH.name, report)
    _write_text(output / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    _write_json(output / DEFAULT_SAFETY_PATH.name, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    after = _mapping(report.get("depth_gate_progress_after"))
    delta = _mapping(report.get("depth_gate_progress_delta"))
    lines = [
        "# BTC OKX L2 depth batch observation",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 完成轮数：`{report.get('completed_cycles')}`",
        f"- 双边覆盖天数：`{after.get('two_sided_coverage_days')}` / `{after.get('required_two_sided_coverage_days')}`",
        f"- 本批增加双边覆盖天数：`{delta.get('two_sided_coverage_days_delta')}`",
        f"- 剩余双边覆盖天数：`{after.get('remaining_two_sided_coverage_days')}`",
        f"- gate fill 映射：`{after.get('mapped_gate_fill_count')}` / `{after.get('gate_fill_count')}`",
        f"- 写入 paper 队列：`{_mapping(report.get('gate')).get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{_mapping(report.get('gate')).get('live_unlock_allowed')}`",
        "",
        "该批处理只重复调用免费 OKX public L2 observe-only 采集；不使用 API key、不访问 private/order endpoint、不连接 broker/OMS、不生成策略骨架。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 仍未满足"])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _cycle_summary(*, index: int, report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cycle": index,
        "status": report.get("status"),
        "decision": report.get("decision"),
        "post_capture_reports_built": bool(report.get("post_capture_reports_built")),
        "depth_gate_progress": report.get("depth_gate_progress"),
        "blockers": list(report.get("blockers", [])),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _progress_delta(*, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "two_sided_snapshot_count_delta": int(_float(after.get("two_sided_snapshot_count")) - _float(before.get("two_sided_snapshot_count"))),
        "two_sided_coverage_days_delta": round(
            _float(after.get("two_sided_coverage_days")) - _float(before.get("two_sided_coverage_days")),
            6,
        ),
        "remaining_two_sided_coverage_days_delta": round(
            _float(after.get("remaining_two_sided_coverage_days")) - _float(before.get("remaining_two_sided_coverage_days")),
            6,
        ),
        "gate_fill_count_delta": int(_float(after.get("gate_fill_count")) - _float(before.get("gate_fill_count"))),
        "mapped_gate_fill_count_delta": int(
            _float(after.get("mapped_gate_fill_count")) - _float(before.get("mapped_gate_fill_count"))
        ),
    }


def _blockers(cycle_reports: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not cycle_reports:
        blockers.append("btc_okx_l2_depth_batch_no_cycles_completed")
    for report in cycle_reports:
        blockers.extend(str(item) for item in report.get("blockers", []) if str(item))
    return _dedupe(blockers)


def _status(*, execute_network: bool, cycle_reports: list[Mapping[str, Any]]) -> str:
    if not execute_network:
        return "dry_run_free_public_l2_depth_batch_planned"
    if not cycle_reports:
        return "free_public_l2_depth_batch_no_cycles_completed"
    if all(report.get("post_capture_reports_built") is True for report in cycle_reports):
        return "free_public_l2_depth_batch_completed_research_only"
    return "free_public_l2_depth_batch_partial_research_only"


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
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "withdraw_allowed": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "withdraw_allowed": False,
        "real_order_submitted": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "paid_data_source_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_okx_l2_depth_observation_batch_safety_status_v1",
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
        "withdraw_allowed": False,
        "paid_data_source_used": False,
        "blockers": list(report.get("blockers", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated BTC observe-only OKX public L2 depth accumulation cycles.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--daily-output-root", type=Path, default=DEFAULT_DAILY_OUTPUT_ROOT)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--cycle-sleep-seconds", type=float, default=300.0)
    parser.add_argument("--sample-count", type=int, default=6)
    parser.add_argument("--trade-limit", type=int, default=100)
    parser.add_argument("--book-size", type=int, default=50)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.25)
    parser.add_argument("--no-stop-when-depth-gate-ready", action="store_true")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--data-version", default="unpublished")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--source-head", default="")
    args = parser.parse_args()
    report = run_btc_okx_l2_depth_observation_batch(
        repo_root=args.repo_root,
        output_root=args.output_root,
        daily_output_root=args.daily_output_root,
        execute_network=bool(args.execute_network),
        cycles=args.cycles,
        cycle_sleep_seconds=args.cycle_sleep_seconds,
        sample_count=args.sample_count,
        trade_limit=args.trade_limit,
        book_size=args.book_size,
        request_sleep_seconds=args.request_sleep_seconds,
        stop_when_depth_gate_ready=not bool(args.no_stop_when_depth_gate_ready),
        generated_at=args.generated_at or None,
        data_version=args.data_version,
        run_id=args.run_id or None,
        source_head=args.source_head or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "completed_cycles": report["completed_cycles"],
                "depth_gate_progress_after": report["depth_gate_progress_after"],
                "blocker_count": len(report["blockers"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _cycle_generated_at(started: datetime, index: int) -> str:
    return started.isoformat().replace("+00:00", "Z") if index == 0 else ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
