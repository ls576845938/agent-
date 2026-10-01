#!/usr/bin/env python3
"""Run one observe-only OKX public L2 depth accumulation pass and rebuild BTC evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.research.btc_depth_slippage import (
        DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
        DEFAULT_CONFIG_PATH as DEFAULT_DEPTH_CONFIG_PATH,
        DEFAULT_OUTPUT_ROOT as DEFAULT_DEPTH_OUTPUT_ROOT,
        MAX_HISTORY_GAP_HOURS,
        MIN_HISTORY_COVERAGE_DAYS,
        MIN_HISTORY_SNAPSHOT_COUNT,
        build_btc_depth_slippage_report,
        build_btc_depth_slippage_fill_mapping_report,
    )
    from quant_crypto.research.btc_perpetual_execution_evidence import (
        DEFAULT_ATTACK_OBSERVER_REPORT,
        DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT as DEFAULT_EVIDENCE_BINANCE_BOOK_DEPTH_REPORT,
        DEFAULT_CONFIG_PATH as DEFAULT_EVIDENCE_CONFIG_PATH,
        DEFAULT_COST_MODEL_REPORT,
        DEFAULT_EXCHANGE_RUNTIME_CONTRACT,
        DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT,
        DEFAULT_FUNDING_LEDGER_REPORT,
        DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
        DEFAULT_LIQUIDATION_RISK_CONTRACT,
        DEFAULT_LONG_SHORT_OBSERVER_REPORT,
        DEFAULT_OUTPUT_DIR as DEFAULT_EVIDENCE_OUTPUT_DIR,
        DEFAULT_PERPETUAL_POLICY_REPORT,
        DEFAULT_PROVIDER_REPORT,
        build_btc_perpetual_execution_evidence_pack,
    )
    from scripts.build_btc_cost_model_report import (
        DEFAULT_FEE_TIER_IMPORT_REPORT,
        DEFAULT_FEE_TIER_OVERLAY,
        DEFAULT_OUTPUT_ROOT as DEFAULT_COST_OUTPUT_ROOT,
        build_btc_cost_model_report,
        write_btc_cost_model_report,
    )
    from scripts.build_btc_true_scalping_l2_aligned_capture_quality_report import (
        DEFAULT_OUTPUT_ROOT as DEFAULT_L2_QUALITY_OUTPUT_ROOT,
        build_btc_true_scalping_l2_aligned_capture_quality_report,
    )
    from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import (
        DEFAULT_CAPTURE_REPORT,
        DEFAULT_CONFIG as DEFAULT_CAPTURE_CONFIG,
        capture_okx_timestamp_aligned_l2_public_data,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.research.btc_depth_slippage import (
        DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
        DEFAULT_CONFIG_PATH as DEFAULT_DEPTH_CONFIG_PATH,
        DEFAULT_OUTPUT_ROOT as DEFAULT_DEPTH_OUTPUT_ROOT,
        MAX_HISTORY_GAP_HOURS,
        MIN_HISTORY_COVERAGE_DAYS,
        MIN_HISTORY_SNAPSHOT_COUNT,
        build_btc_depth_slippage_report,
        build_btc_depth_slippage_fill_mapping_report,
    )
    from quant_crypto.research.btc_perpetual_execution_evidence import (
        DEFAULT_ATTACK_OBSERVER_REPORT,
        DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT as DEFAULT_EVIDENCE_BINANCE_BOOK_DEPTH_REPORT,
        DEFAULT_CONFIG_PATH as DEFAULT_EVIDENCE_CONFIG_PATH,
        DEFAULT_COST_MODEL_REPORT,
        DEFAULT_EXCHANGE_RUNTIME_CONTRACT,
        DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT,
        DEFAULT_FUNDING_LEDGER_REPORT,
        DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT,
        DEFAULT_LIQUIDATION_RISK_CONTRACT,
        DEFAULT_LONG_SHORT_OBSERVER_REPORT,
        DEFAULT_OUTPUT_DIR as DEFAULT_EVIDENCE_OUTPUT_DIR,
        DEFAULT_PERPETUAL_POLICY_REPORT,
        DEFAULT_PROVIDER_REPORT,
        build_btc_perpetual_execution_evidence_pack,
    )
    from scripts.build_btc_cost_model_report import (
        DEFAULT_FEE_TIER_IMPORT_REPORT,
        DEFAULT_FEE_TIER_OVERLAY,
        DEFAULT_OUTPUT_ROOT as DEFAULT_COST_OUTPUT_ROOT,
        build_btc_cost_model_report,
        write_btc_cost_model_report,
    )
    from scripts.build_btc_true_scalping_l2_aligned_capture_quality_report import (
        DEFAULT_OUTPUT_ROOT as DEFAULT_L2_QUALITY_OUTPUT_ROOT,
        build_btc_true_scalping_l2_aligned_capture_quality_report,
    )
    from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import (
        DEFAULT_CAPTURE_REPORT,
        DEFAULT_CONFIG as DEFAULT_CAPTURE_CONFIG,
        capture_okx_timestamp_aligned_l2_public_data,
    )


SCHEMA_VERSION = "btc_okx_l2_depth_observation_daily_run_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_l2_depth_observation/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_l2_depth_observation_daily_run_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_l2_depth_observation_daily_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_ROOT / "paper_live_safety_status.json"


def run_btc_okx_l2_depth_observation_daily(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    execute_network: bool = False,
    sample_count: int = 6,
    trade_limit: int = 100,
    book_size: int = 50,
    request_sleep_seconds: float = 0.25,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_now()
    generated_dt = _parse_utc(generated)
    output_dir = _resolve(root, output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    capture = capture_okx_timestamp_aligned_l2_public_data(
        repo_root=root,
        config_path=DEFAULT_CAPTURE_CONFIG,
        capture_report_path=DEFAULT_CAPTURE_REPORT,
        execute_network=execute_network,
        sample_count=sample_count,
        trade_limit=trade_limit,
        book_size=book_size,
        request_sleep_seconds=request_sleep_seconds,
        captured_at=generated,
        append_existing=True,
    )
    evidence_generated = _post_capture_generated_at(capture=capture, fallback=generated)
    evidence_generated_dt = _parse_utc(evidence_generated)

    step_statuses: list[dict[str, Any]] = [
        _step("okx_public_rest_l2_capture", capture.get("status"), capture.get("blockers", [])),
    ]
    l2_quality: dict[str, Any] = {}
    depth_slippage: dict[str, Any] = {}
    fill_mapping: dict[str, Any] = {}
    cost_model: dict[str, Any] = {}
    perpetual_evidence: dict[str, Any] = {}
    post_capture_reports_built = False

    if execute_network and capture.get("status") == "verified_preflight":
        l2_quality = build_btc_true_scalping_l2_aligned_capture_quality_report(
            repo_root=root,
            output_root=DEFAULT_L2_QUALITY_OUTPUT_ROOT,
            generated_at=evidence_generated,
        )
        step_statuses.append(_step("aligned_l2_capture_quality", l2_quality.get("status"), l2_quality.get("blockers", [])))

        fill_mapping = build_btc_depth_slippage_fill_mapping_report(
            repo_root=root,
            config_path=DEFAULT_DEPTH_CONFIG_PATH,
            output_root=DEFAULT_DEPTH_OUTPUT_ROOT,
            generated_at_utc=evidence_generated_dt,
        )
        depth_slippage = build_btc_depth_slippage_report(
            repo_root=root,
            config_path=DEFAULT_DEPTH_CONFIG_PATH,
            output_root=DEFAULT_DEPTH_OUTPUT_ROOT,
            binance_vision_book_depth_report_path=DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
            generated_at_utc=evidence_generated_dt,
        )
        step_statuses.append(_step("depth_fill_mapping", fill_mapping.get("status"), fill_mapping.get("blockers", [])))
        step_statuses.append(_step("depth_slippage", depth_slippage.get("status"), depth_slippage.get("blockers", [])))

        cost_model = build_btc_cost_model_report(
            repo_root=root,
            fee_tier_overlay_path=DEFAULT_FEE_TIER_OVERLAY,
            fee_tier_import_report_path=DEFAULT_FEE_TIER_IMPORT_REPORT,
            generated_at=evidence_generated,
        )
        write_btc_cost_model_report(cost_model, _resolve(root, DEFAULT_COST_OUTPUT_ROOT))
        step_statuses.append(_step("cost_model", cost_model.get("status"), cost_model.get("blockers", [])))

        perpetual_evidence = build_btc_perpetual_execution_evidence_pack(
            output_dir=_resolve(root, DEFAULT_EVIDENCE_OUTPUT_DIR),
            config_path=_resolve(root, DEFAULT_EVIDENCE_CONFIG_PATH),
            provider_report_path=_resolve(root, DEFAULT_PROVIDER_REPORT),
            cost_model_report_path=_resolve(root, DEFAULT_COST_MODEL_REPORT),
            funding_ledger_report_path=_resolve(root, DEFAULT_FUNDING_LEDGER_REPORT),
            perpetual_policy_report_path=_resolve(root, DEFAULT_PERPETUAL_POLICY_REPORT),
            exchange_runtime_contract_path=_resolve(root, DEFAULT_EXCHANGE_RUNTIME_CONTRACT),
            exchange_runtime_replay_gap_report_path=_resolve(root, DEFAULT_EXCHANGE_RUNTIME_REPLAY_GAP_REPORT),
            binance_vision_book_depth_report_path=_resolve(root, DEFAULT_EVIDENCE_BINANCE_BOOK_DEPTH_REPORT),
            liquidation_risk_contract_path=_resolve(root, DEFAULT_LIQUIDATION_RISK_CONTRACT),
            long_short_observer_report_path=_resolve(root, DEFAULT_LONG_SHORT_OBSERVER_REPORT),
            attack_observer_report_path=_resolve(root, DEFAULT_ATTACK_OBSERVER_REPORT),
            high_yield_followup_report_path=_resolve(root, DEFAULT_HIGH_YIELD_FOLLOWUP_REPORT),
            generated_at_utc=evidence_generated_dt,
        )
        step_statuses.append(
            _step("perpetual_execution_evidence", perpetual_evidence.get("status"), perpetual_evidence.get("blockers", []))
        )
        post_capture_reports_built = True

    blockers = _blockers(
        execute_network=execute_network,
        capture=capture,
        l2_quality=l2_quality,
        depth_slippage=depth_slippage,
        cost_model=cost_model,
        perpetual_evidence=perpetual_evidence,
        post_capture_reports_built=post_capture_reports_built,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": evidence_generated_dt.isoformat(),
        "capture_request_generated_at_utc": generated_dt.isoformat(),
        "post_capture_evidence_asof_utc": evidence_generated_dt.isoformat(),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_free_public_okx_l2_depth_observation_no_candidate_no_paper_no_live",
        "status": _status(execute_network=execute_network, capture=capture, post_capture_reports_built=post_capture_reports_built),
        "decision": "continue_accumulating_free_public_l2_depth_evidence_fail_closed_no_paper_no_live",
        "requested": {
            "execute_network": bool(execute_network),
            "sample_count": max(1, int(sample_count)),
            "trade_limit": min(100, max(1, int(trade_limit))),
            "book_size": min(400, max(1, int(book_size))),
            "request_sleep_seconds": max(0.0, float(request_sleep_seconds)),
            "append_existing": True,
            "free_data_sources_only": True,
        },
        "free_data_policy": {
            "allowed_sources": ["OKX public REST", "Binance Vision public files already attached to cost diagnostics"],
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "api_key_used": False,
            "paid_data_source_used": False,
            "cannot_clear_with_free_data_yet": _cannot_clear_with_free_data(blockers),
        },
        "step_statuses": step_statuses,
        "capture_snapshot": {
            "status": capture.get("status"),
            "network_called": bool(capture.get("network_called", False)),
            "completed_sample_count": capture.get("completed_sample_count"),
            "capture_summary": capture.get("capture_summary"),
            "current_capture_summary": capture.get("current_capture_summary"),
            "selected_bundle_dir": capture.get("selected_bundle_dir"),
        },
        "evidence_snapshot": {
            "aligned_l2_quality_status": l2_quality.get("status"),
            "aligned_l2_quality_blockers": l2_quality.get("blockers", []),
            "depth_slippage_status": depth_slippage.get("status"),
            "depth_aware_slippage_history_verified": depth_slippage.get("depth_aware_slippage_history_verified"),
            "depth_snapshot_coverage": depth_slippage.get("snapshot_coverage"),
            "depth_fill_mapping_status": fill_mapping.get("status"),
            "depth_fill_mapping_verified": fill_mapping.get("strategy_fill_mapping_verified"),
            "depth_fill_mapping_summary": fill_mapping.get("summary"),
            "cost_model_status": cost_model.get("status"),
            "cost_model_blockers": cost_model.get("blockers", []),
            "perpetual_execution_evidence_status": perpetual_evidence.get("status"),
            "perpetual_execution_evidence_decision": perpetual_evidence.get("decision"),
            "perpetual_execution_evidence_summary": perpetual_evidence.get("summary"),
            "perpetual_execution_evidence_blockers": perpetual_evidence.get("blockers", []),
        },
        "depth_gate_progress": _depth_gate_progress(depth_slippage=depth_slippage, fill_mapping=fill_mapping),
        "post_capture_reports_built": post_capture_reports_built,
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(output_dir / DEFAULT_REPORT_PATH.name, root),
            "summary_cn": _portable_path(output_dir / DEFAULT_SUMMARY_PATH.name, root),
            "paper_live_safety_status": _portable_path(output_dir / DEFAULT_SAFETY_PATH.name, root),
        },
    }
    _write_json(output_dir / DEFAULT_REPORT_PATH.name, report)
    _write_text(output_dir / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    _write_json(output_dir / DEFAULT_SAFETY_PATH.name, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    capture = _mapping(report.get("capture_snapshot"))
    evidence = _mapping(report.get("evidence_snapshot"))
    lines = [
        "# BTC OKX L2 深度观察日跑",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 本次完成采样：`{capture.get('completed_sample_count')}`",
        f"- 已重建后续证据：`{report.get('post_capture_reports_built')}`",
        f"- 深度历史已验证：`{evidence.get('depth_aware_slippage_history_verified')}`",
        f"- 永续执行证据状态：`{evidence.get('perpetual_execution_evidence_status')}`",
        f"- 写入 paper 队列：`{_mapping(report.get('gate')).get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{_mapping(report.get('gate')).get('live_unlock_allowed')}`",
        "",
        "本运行只使用免费公共数据源补充研究证据：OKX 公共 REST L2/成交采样，以及已有 Binance Vision 免费诊断。",
        "它不会写 paper 队列、不会接 broker/OMS、不会调用下单或私有接口。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 仍未补齐的数据"])
        for blocker in report.get("blockers", []):
            lines.append(f"- `{blocker}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BTC observe-only OKX public L2 depth accumulation.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--sample-count", type=int, default=6)
    parser.add_argument("--trade-limit", type=int, default=100)
    parser.add_argument("--book-size", type=int, default=50)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.25)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    report = run_btc_okx_l2_depth_observation_daily(
        repo_root=args.repo_root,
        output_root=args.output_root,
        execute_network=bool(args.execute_network),
        sample_count=args.sample_count,
        trade_limit=args.trade_limit,
        book_size=args.book_size,
        request_sleep_seconds=args.request_sleep_seconds,
        generated_at=args.generated_at or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "post_capture_reports_built": report["post_capture_reports_built"],
                "blocker_count": len(report["blockers"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _status(*, execute_network: bool, capture: Mapping[str, Any], post_capture_reports_built: bool) -> str:
    if not execute_network:
        return "dry_run_free_public_l2_depth_observation_planned"
    if capture.get("status") == "verified_preflight" and post_capture_reports_built:
        return "free_public_l2_depth_observation_completed_research_only"
    return "free_public_l2_depth_observation_failed_or_partial_research_only"


def _blockers(
    *,
    execute_network: bool,
    capture: Mapping[str, Any],
    l2_quality: Mapping[str, Any],
    depth_slippage: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    perpetual_evidence: Mapping[str, Any],
    post_capture_reports_built: bool,
) -> list[str]:
    blockers: list[str] = []
    if not execute_network:
        blockers.append("btc_okx_l2_depth_observation_dry_run_no_network_executed")
    blockers.extend(str(item) for item in capture.get("blockers", []) if str(item))
    if execute_network and capture.get("status") != "verified_preflight":
        blockers.append("btc_okx_l2_depth_capture_not_verified")
    if execute_network and not post_capture_reports_built:
        blockers.append("btc_okx_l2_depth_post_capture_evidence_not_rebuilt")
    blockers.extend(str(item) for item in l2_quality.get("blockers", []) if str(item))
    blockers.extend(str(item) for item in depth_slippage.get("blockers", []) if str(item))
    blockers.extend(str(item) for item in cost_model.get("blockers", []) if str(item))
    blockers.extend(str(item) for item in perpetual_evidence.get("blockers", []) if str(item))
    return _dedupe(blockers)


def _cannot_clear_with_free_data(blockers: list[str]) -> list[str]:
    hard_to_clear = {
        "btc_execution_latency_model_missing_rest_latency_is_not_execution_latency",
        "btc_queue_model_missing_visible_depth_is_proxy_only",
        "btc_perp_exec_liquidation_history_or_snapshots_available",
        "btc_perp_exec_exchange_runtime_real_or_paper_replay_ready",
        "btc_perp_exec_perpetual_policy_allows_current_strategy",
    }
    return [item for item in blockers if item in hard_to_clear]


def _depth_gate_progress(*, depth_slippage: Mapping[str, Any], fill_mapping: Mapping[str, Any]) -> dict[str, Any]:
    coverage = _mapping(depth_slippage.get("snapshot_coverage"))
    fill_summary = _mapping(fill_mapping.get("summary"))
    two_sided_snapshot_count = _float(coverage.get("two_sided_snapshot_count"))
    two_sided_coverage_days = _float(coverage.get("two_sided_coverage_days"))
    max_two_sided_gap_hours = coverage.get("max_two_sided_gap_hours")
    gate_fill_count = _float(fill_summary.get("gate_fill_count"))
    mapped_gate_fill_count = _float(fill_summary.get("mapped_gate_fill_count"))
    history_snapshots_ok = two_sided_snapshot_count >= float(MIN_HISTORY_SNAPSHOT_COUNT)
    history_days_ok = two_sided_coverage_days >= float(MIN_HISTORY_COVERAGE_DAYS)
    history_continuity_ok = coverage.get("two_sided_continuity_satisfied") is True
    history_coverage_ok = history_days_ok and history_continuity_ok
    fill_mapping_ok = fill_mapping.get("strategy_fill_mapping_verified") is True
    return {
        "selected_venue": "okx_swap",
        "same_venue_as_execution_gate": True,
        "required_two_sided_snapshot_count": MIN_HISTORY_SNAPSHOT_COUNT,
        "two_sided_snapshot_count": int(two_sided_snapshot_count),
        "remaining_two_sided_snapshot_count": max(0, int(MIN_HISTORY_SNAPSHOT_COUNT - two_sided_snapshot_count)),
        "required_two_sided_coverage_days": MIN_HISTORY_COVERAGE_DAYS,
        "two_sided_coverage_days": round(two_sided_coverage_days, 6),
        "remaining_two_sided_coverage_days": round(max(0.0, MIN_HISTORY_COVERAGE_DAYS - two_sided_coverage_days), 6),
        "max_allowed_two_sided_gap_hours": MAX_HISTORY_GAP_HOURS,
        "max_two_sided_gap_hours": max_two_sided_gap_hours,
        "history_continuity_requirement_satisfied": history_continuity_ok,
        "history_snapshot_requirement_satisfied": history_snapshots_ok,
        "history_coverage_days_requirement_satisfied": history_coverage_ok,
        "gate_fill_count": int(gate_fill_count),
        "mapped_gate_fill_count": int(mapped_gate_fill_count),
        "strategy_fill_mapping_verified": fill_mapping_ok,
        "depth_aware_slippage_history_verified": bool(depth_slippage.get("depth_aware_slippage_history_verified")),
        "gate_ready": bool(depth_slippage.get("depth_aware_slippage_history_verified")),
        "next_required_evidence": _depth_next_required_evidence(
            history_snapshots_ok=history_snapshots_ok,
            history_days_ok=history_days_ok,
            history_continuity_ok=history_continuity_ok,
            fill_mapping_ok=fill_mapping_ok,
            gate_fill_count=gate_fill_count,
        ),
    }


def _depth_next_required_evidence(
    *,
    history_snapshots_ok: bool,
    history_days_ok: bool,
    history_continuity_ok: bool,
    fill_mapping_ok: bool,
    gate_fill_count: float,
) -> list[str]:
    missing: list[str] = []
    if not history_snapshots_ok:
        missing.append("collect_more_okx_two_sided_depth_snapshots")
    if not history_days_ok:
        missing.append("accumulate_okx_two_sided_depth_history_until_14_days")
    if history_days_ok and not history_continuity_ok:
        missing.append("close_okx_two_sided_depth_history_gaps")
    if gate_fill_count <= 0:
        missing.append("wait_for_or_replay_gate_eligible_non_flat_strategy_fill")
    elif not fill_mapping_ok:
        missing.append("map_gate_eligible_strategy_fills_to_visible_okx_depth")
    return missing


def _step(name: str, status: object, blockers: object) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "blockers": [str(item) for item in blockers] if isinstance(blockers, list) else [],
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
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
        "paid_data_source_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_okx_l2_depth_observation_safety_status_v1",
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
        "paid_data_source_used": False,
        "blockers": list(report.get("blockers", [])),
    }


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _post_capture_generated_at(*, capture: Mapping[str, Any], fallback: str) -> str:
    manifest = _mapping(capture.get("alignment_manifest"))
    candidates = [
        fallback,
        str(manifest.get("latest_capture_end") or ""),
        str(manifest.get("capture_end") or ""),
    ]
    parsed = [_parse_utc(candidate) for candidate in candidates if candidate]
    if not parsed:
        return fallback
    return max(parsed).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
