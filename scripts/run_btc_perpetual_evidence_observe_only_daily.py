#!/usr/bin/env python3
"""Run one BTC perpetual execution-evidence observe-only daily pass."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.research.btc_exchange_runtime_replay_gap import (  # noqa: E402
    DEFAULT_OUTPUT_DIR as DEFAULT_RUNTIME_GAP_OUTPUT_DIR,
    DEFAULT_PAPER_RUNTIME_REPLAY_PATH,
    DEFAULT_PUBLIC_WS_COVERAGE_PATH,
    DEFAULT_RUNTIME_CONTRACT_PATH,
    build_btc_exchange_runtime_replay_gap_report,
)
from quant_crypto.research.btc_depth_slippage import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as DEFAULT_DEPTH_SLIPPAGE_OUTPUT_ROOT,
    build_btc_depth_slippage_fill_mapping_report,
    build_btc_depth_slippage_report,
)
from quant_crypto.research.btc_okx_liquidation_snapshot_observer import (  # noqa: E402
    DEFAULT_DATA_PATH as DEFAULT_LIQUIDATION_DATA_PATH,
    DEFAULT_OUTPUT_DIR as DEFAULT_LIQUIDATION_OUTPUT_DIR,
    run_btc_okx_liquidation_snapshot_observer,
)
from quant_crypto.research.btc_perpetual_execution_evidence import (  # noqa: E402
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
    DEFAULT_OUTPUT_DIR as DEFAULT_PERPETUAL_EVIDENCE_OUTPUT_DIR,
    DEFAULT_PERPETUAL_POLICY_REPORT,
    DEFAULT_PROVIDER_REPORT,
    build_btc_perpetual_execution_evidence_pack,
)
from quant_crypto.research.btc_perpetual_paper_runtime_replay import (  # noqa: E402
    DEFAULT_ATTACK_OBSERVATIONS,
    DEFAULT_CONFIG_PATH as DEFAULT_PAPER_RUNTIME_CONFIG_PATH,
    DEFAULT_COST_MODEL_REPORT as DEFAULT_PAPER_RUNTIME_COST_MODEL_REPORT,
    DEFAULT_LONG_SHORT_OBSERVATIONS,
    DEFAULT_OUTPUT_DIR as DEFAULT_PAPER_RUNTIME_OUTPUT_DIR,
    DEFAULT_PERPETUAL_EVIDENCE_REPORT as DEFAULT_PAPER_RUNTIME_PERPETUAL_EVIDENCE_REPORT,
    build_btc_perpetual_paper_runtime_replay_report,
)
from scripts.build_btc_cost_model_report import (  # noqa: E402
    DEFAULT_FEE_TIER_IMPORT_REPORT,
    DEFAULT_FEE_TIER_OVERLAY,
    DEFAULT_OUTPUT_ROOT as DEFAULT_COST_OUTPUT_ROOT,
    build_btc_cost_model_report,
    write_btc_cost_model_report,
)
from scripts.build_btc_gate_dashboard import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_GATE_DASHBOARD_OUTPUT,
    build_btc_gate_dashboard_file,
)
from scripts.run_btc_okx_l2_depth_observation_daily import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT as DEFAULT_L2_OUTPUT_ROOT,
    run_btc_okx_l2_depth_observation_daily,
)


SCHEMA_VERSION = "btc_perpetual_evidence_observe_only_daily_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_perpetual_evidence_observe_only_daily/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "btc_perpetual_evidence_observe_only_daily_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_ROOT / "btc_perpetual_evidence_observe_only_daily_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_ROOT / "paper_live_safety_status.json"


def run_btc_perpetual_evidence_observe_only_daily(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    execute_network: bool = False,
    l2_sample_count: int = 6,
    l2_trade_limit: int = 100,
    l2_book_size: int = 50,
    l2_request_sleep_seconds: float = 0.2,
    liquidation_limit: int = 100,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = _parse_utc(generated_at) if generated_at else datetime.now(timezone.utc)
    output_dir = _resolve(root, output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []

    l2_payload = _safe_step(
        steps,
        "okx_l2_depth_observation",
        lambda: run_btc_okx_l2_depth_observation_daily(
            repo_root=root,
            output_root=DEFAULT_L2_OUTPUT_ROOT,
            execute_network=execute_network,
            sample_count=l2_sample_count,
            trade_limit=l2_trade_limit,
            book_size=l2_book_size,
            request_sleep_seconds=l2_request_sleep_seconds,
            generated_at=generated.isoformat().replace("+00:00", "Z"),
        ),
    )
    liquidation_payload = _safe_step(
        steps,
        "okx_liquidation_snapshot_observation",
        lambda: run_btc_okx_liquidation_snapshot_observer(
            repo_root=root,
            output_dir=DEFAULT_LIQUIDATION_OUTPUT_DIR,
            data_path=DEFAULT_LIQUIDATION_DATA_PATH,
            execute_network=execute_network,
            limit=liquidation_limit,
        ),
    )
    cost_model_payload = _safe_step(
        steps,
        "cost_model_rebuild",
        lambda: _build_and_write_cost_model(root=root, generated=generated),
    )
    paper_runtime_payload = _safe_step(
        steps,
        "perpetual_paper_runtime_replay",
        lambda: build_btc_perpetual_paper_runtime_replay_report(
            repo_root=root,
            output_dir=DEFAULT_PAPER_RUNTIME_OUTPUT_DIR,
            config_path=DEFAULT_PAPER_RUNTIME_CONFIG_PATH,
            long_short_observations_path=DEFAULT_LONG_SHORT_OBSERVATIONS,
            attack_observations_path=DEFAULT_ATTACK_OBSERVATIONS,
            cost_model_report_path=DEFAULT_PAPER_RUNTIME_COST_MODEL_REPORT,
            perpetual_evidence_report_path=DEFAULT_PAPER_RUNTIME_PERPETUAL_EVIDENCE_REPORT,
            generated_at_utc=generated,
        ),
    )
    fill_mapping_payload = _safe_step(
        steps,
        "depth_fill_mapping_rebuild",
        lambda: build_btc_depth_slippage_fill_mapping_report(
            repo_root=root,
            output_root=DEFAULT_DEPTH_SLIPPAGE_OUTPUT_ROOT,
            generated_at_utc=generated,
        ),
    )
    depth_slippage_payload = _safe_step(
        steps,
        "depth_slippage_rebuild",
        lambda: build_btc_depth_slippage_report(
            repo_root=root,
            output_root=DEFAULT_DEPTH_SLIPPAGE_OUTPUT_ROOT,
            generated_at_utc=generated,
        ),
    )
    refreshed_cost_model_payload = _safe_step(
        steps,
        "cost_model_refresh_after_fill_mapping",
        lambda: _build_and_write_cost_model(root=root, generated=generated),
    )
    effective_cost_model_payload = refreshed_cost_model_payload or cost_model_payload
    runtime_gap_payload = _safe_step(
        steps,
        "exchange_runtime_replay_gap",
        lambda: build_btc_exchange_runtime_replay_gap_report(
            output_dir=_resolve(root, DEFAULT_RUNTIME_GAP_OUTPUT_DIR),
            runtime_contract_path=_resolve(root, DEFAULT_RUNTIME_CONTRACT_PATH),
            public_ws_coverage_path=_resolve(root, DEFAULT_PUBLIC_WS_COVERAGE_PATH),
            paper_runtime_replay_path=_resolve(root, DEFAULT_PAPER_RUNTIME_REPLAY_PATH),
            generated_at_utc=generated,
        ),
    )
    perpetual_evidence_payload = _safe_step(
        steps,
        "perpetual_execution_evidence",
        lambda: build_btc_perpetual_execution_evidence_pack(
            output_dir=_resolve(root, DEFAULT_PERPETUAL_EVIDENCE_OUTPUT_DIR),
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
            generated_at_utc=generated,
        ),
    )
    gate_dashboard_payload = _safe_step(
        steps,
        "gate_dashboard_rebuild",
        lambda: build_btc_gate_dashboard_file(output=_resolve(root, DEFAULT_GATE_DASHBOARD_OUTPUT)),
    )

    blockers = _dedupe(
        [
            *[blocker for step in steps for blocker in step.get("blockers", [])],
            *[str(item) for item in _mapping(perpetual_evidence_payload).get("blockers", []) if str(item)],
            *[str(item) for item in _mapping(gate_dashboard_payload).get("blockers", []) if str(item)],
        ]
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "partial_research_only" if any(step["status"] == "error" for step in steps) else "complete_research_only",
        "decision": "continue_accumulating_btc_perpetual_execution_evidence_fail_closed_no_paper_no_live",
        "scope": "btc_perpetual_execution_evidence_observe_only_daily_no_order_no_broker",
        "requested": {
            "execute_network": bool(execute_network),
            "free_public_sources_only": True,
            "l2_sample_count": max(1, int(l2_sample_count)),
            "l2_trade_limit": min(100, max(1, int(l2_trade_limit))),
            "l2_book_size": min(400, max(1, int(l2_book_size))),
            "l2_request_sleep_seconds": max(0.0, float(l2_request_sleep_seconds)),
            "liquidation_limit": min(100, max(1, int(liquidation_limit))),
        },
        "steps": steps,
        "evidence_snapshot": _evidence_snapshot(
            l2_payload=l2_payload,
            liquidation_payload=liquidation_payload,
            cost_model_payload=effective_cost_model_payload,
            initial_cost_model_payload=cost_model_payload,
            fill_mapping_payload=fill_mapping_payload,
            depth_slippage_payload=depth_slippage_payload,
            paper_runtime_payload=paper_runtime_payload,
            runtime_gap_payload=runtime_gap_payload,
            perpetual_evidence_payload=perpetual_evidence_payload,
            gate_dashboard_payload=gate_dashboard_payload,
        ),
        "free_data_policy": {
            "allowed_sources": ["OKX public REST", "existing local/free Binance Vision diagnostics"],
            "api_key_used": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "paid_data_source_used": False,
            "cannot_clear_with_free_data_yet": _cannot_clear_with_free_data(blockers),
        },
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
    evidence = _mapping(report.get("evidence_snapshot"))
    depth = _mapping(evidence.get("depth_snapshot_coverage"))
    liquidation = _mapping(evidence.get("liquidation_snapshot"))
    runtime = _mapping(evidence.get("paper_runtime_replay"))
    perpetual = _mapping(evidence.get("perpetual_execution_evidence"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC 永续执行证据 observe-only 日跑",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- L2 双边盘口快照：`{depth.get('two_sided_snapshot_count')}`",
        f"- L2 双边覆盖天数：`{depth.get('two_sided_coverage_days')}`",
        f"- 强平快照累计行数：`{liquidation.get('merged_row_count')}`",
        f"- 当前永续 runtime 理论订单数：`{runtime.get('theoretical_order_count')}`",
        f"- 当前永续 runtime 模拟成交数：`{runtime.get('simulated_fill_count')}`",
        f"- 永续执行证据状态：`{perpetual.get('status')}`",
        f"- 永续执行证据 blocker 数：`{perpetual.get('blocker_count')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "本日跑只累计免费公开数据和本地 observe-only 回放证据，不调用 private/order/live 接口，不提交订单，不写 paper 队列。",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(["", "## 仍未通过的关口"])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    return "\n".join(lines) + "\n"


def _build_and_write_cost_model(*, root: Path, generated: datetime) -> dict[str, Any]:
    payload = build_btc_cost_model_report(
        repo_root=root,
        fee_tier_overlay_path=DEFAULT_FEE_TIER_OVERLAY,
        fee_tier_import_report_path=DEFAULT_FEE_TIER_IMPORT_REPORT,
        generated_at=generated.isoformat(),
    )
    write_btc_cost_model_report(payload, _resolve(root, DEFAULT_COST_OUTPUT_ROOT))
    return payload


def _safe_step(
    steps: list[dict[str, Any]],
    name: str,
    fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        payload = fn()
    except Exception as exc:  # noqa: BLE001 - persisted as daily evidence.
        step = {
            "name": name,
            "status": "error",
            "decision": "step_failed_research_only_fail_closed",
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "blockers": [f"{name}_failed"],
            "error": f"{type(exc).__name__}: {exc}",
            "traceback_tail": traceback.format_exc(limit=4),
        }
        steps.append(step)
        return {}

    step = {
        "name": name,
        "status": payload.get("status") or "complete",
        "decision": payload.get("decision"),
        "paper_queue_write_allowed": _mapping(payload.get("gate")).get("paper_queue_write_allowed", False),
        "live_unlock_allowed": _mapping(payload.get("gate")).get("live_unlock_allowed", False),
        "blockers": [str(item) for item in payload.get("blockers", []) if str(item)],
    }
    steps.append(step)
    return payload


def _evidence_snapshot(
    *,
    l2_payload: Mapping[str, Any],
    liquidation_payload: Mapping[str, Any],
    cost_model_payload: Mapping[str, Any],
    initial_cost_model_payload: Mapping[str, Any],
    fill_mapping_payload: Mapping[str, Any],
    depth_slippage_payload: Mapping[str, Any],
    paper_runtime_payload: Mapping[str, Any],
    runtime_gap_payload: Mapping[str, Any],
    perpetual_evidence_payload: Mapping[str, Any],
    gate_dashboard_payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "l2_status": l2_payload.get("status"),
        "depth_snapshot_coverage": _mapping(_mapping(l2_payload.get("evidence_snapshot")).get("depth_snapshot_coverage")),
        "liquidation_snapshot": {
            "status": liquidation_payload.get("status"),
            "new_row_count": _mapping(liquidation_payload.get("data")).get("new_row_count"),
            "merged_row_count": _mapping(liquidation_payload.get("data")).get("merged_row_count"),
            "gate_eligible": _mapping(liquidation_payload.get("gate_interpretation")).get("liquidation_snapshot_gate_eligible"),
        },
        "cost_model": {
            "status": cost_model_payload.get("status"),
            "initial_status_before_runtime_replay": initial_cost_model_payload.get("status"),
            "blockers": cost_model_payload.get("blockers", []),
            "liquidation_snapshot_status": _mapping(cost_model_payload.get("liquidation_data")).get("liquidation_snapshot_status"),
            "depth_aware_slippage_history_verified": _mapping(cost_model_payload.get("slippage_model")).get(
                "depth_aware_slippage_history_verified"
            ),
        },
        "depth_fill_mapping": {
            "status": fill_mapping_payload.get("status"),
            "decision": fill_mapping_payload.get("decision"),
            "fill_mapping_state": fill_mapping_payload.get("fill_mapping_state"),
            "strategy_fill_mapping_verified": fill_mapping_payload.get("strategy_fill_mapping_verified"),
            "gate_fill_count": _mapping(fill_mapping_payload.get("summary")).get("gate_fill_count"),
            "mapped_gate_fill_count": _mapping(fill_mapping_payload.get("summary")).get("mapped_gate_fill_count"),
            "gate_depth_not_visible_count": _mapping(fill_mapping_payload.get("summary")).get("gate_depth_not_visible_count"),
            "gate_mapping_logic_failure_count": _mapping(fill_mapping_payload.get("summary")).get(
                "gate_mapping_logic_failure_count"
            ),
            "blockers": fill_mapping_payload.get("blockers", []),
        },
        "depth_slippage": {
            "status": depth_slippage_payload.get("status"),
            "decision": depth_slippage_payload.get("decision"),
            "depth_aware_slippage_history_verified": depth_slippage_payload.get(
                "depth_aware_slippage_history_verified"
            ),
            "strategy_fill_mapping_verified": _mapping(depth_slippage_payload.get("selected_venue_depth_evidence")).get(
                "strategy_fill_mapping_verified"
            ),
            "blockers": depth_slippage_payload.get("blockers", []),
        },
        "paper_runtime_replay": {
            "status": paper_runtime_payload.get("status"),
            "decision": paper_runtime_payload.get("decision"),
            "theoretical_order_count": _mapping(paper_runtime_payload.get("summary")).get("theoretical_order_count"),
            "simulated_fill_count": _mapping(paper_runtime_payload.get("summary")).get("simulated_fill_count"),
            "gate_eligible_current_capture_count": _mapping(paper_runtime_payload.get("summary")).get(
                "gate_eligible_current_capture_count"
            ),
            "current_non_flat_sample_capture_status": _mapping(paper_runtime_payload.get("summary")).get(
                "current_non_flat_sample_capture_status"
            ),
            "current_non_flat_sample_capture_contract": _mapping(paper_runtime_payload.get("summary")).get(
                "current_non_flat_sample_capture_contract"
            ),
            "blockers": paper_runtime_payload.get("blockers", []),
        },
        "runtime_gap": {
            "status": runtime_gap_payload.get("status"),
            "decision": runtime_gap_payload.get("decision"),
            "blocker_count": _mapping(runtime_gap_payload.get("summary")).get("blocker_count"),
            "blockers": runtime_gap_payload.get("blockers", []),
        },
        "perpetual_execution_evidence": {
            "status": perpetual_evidence_payload.get("status"),
            "decision": perpetual_evidence_payload.get("decision"),
            "pass_count": _mapping(perpetual_evidence_payload.get("summary")).get("pass_count"),
            "fail_count": _mapping(perpetual_evidence_payload.get("summary")).get("fail_count"),
            "blocker_count": _mapping(perpetual_evidence_payload.get("summary")).get("blocker_count"),
            "blockers": perpetual_evidence_payload.get("blockers", []),
        },
        "gate_dashboard": {
            "status": gate_dashboard_payload.get("status"),
            "decision": gate_dashboard_payload.get("decision"),
            "blockers": gate_dashboard_payload.get("blockers", []),
        },
    }


def _cannot_clear_with_free_data(blockers: list[str]) -> list[str]:
    hard = {
        "btc_execution_latency_model_missing_rest_latency_is_not_execution_latency",
        "btc_queue_model_missing_visible_depth_is_proxy_only",
        "btc_perp_exec_liquidation_history_or_snapshots_available",
        "btc_perp_exec_exchange_runtime_real_or_paper_replay_ready",
        "btc_execution_latency_model_missing_public_ws_is_not_order_latency",
        "btc_queue_model_missing_public_l2_is_not_exchange_queue_position",
    }
    return [item for item in blockers if item in hard]


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
        "api_key_used": False,
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
        "schema_version": "btc_perpetual_evidence_observe_only_daily_safety_status_v1",
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
        "paid_data_source_used": False,
        "blockers": list(report.get("blockers", [])),
    }


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BTC perpetual execution-evidence observe-only daily pass.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--l2-sample-count", type=int, default=6)
    parser.add_argument("--l2-trade-limit", type=int, default=100)
    parser.add_argument("--l2-book-size", type=int, default=50)
    parser.add_argument("--l2-request-sleep-seconds", type=float, default=0.2)
    parser.add_argument("--liquidation-limit", type=int, default=100)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    report = run_btc_perpetual_evidence_observe_only_daily(
        repo_root=args.repo_root,
        output_root=args.output_root,
        execute_network=bool(args.execute_network),
        l2_sample_count=args.l2_sample_count,
        l2_trade_limit=args.l2_trade_limit,
        l2_book_size=args.l2_book_size,
        l2_request_sleep_seconds=args.l2_request_sleep_seconds,
        liquidation_limit=args.liquidation_limit,
        generated_at=args.generated_at or None,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "blocker_count": len(report["blockers"]),
                "paper_queue_write_allowed": report["gate"]["paper_queue_write_allowed"],
                "live_unlock_allowed": report["gate"]["live_unlock_allowed"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
