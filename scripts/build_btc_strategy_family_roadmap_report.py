#!/usr/bin/env python3
"""Build the fail-closed BTC strategy-family roadmap report.

This is a research governance artifact. It selects the next hypothesis family
after dual-trend micro-surgery failed, but it does not run a strategy, create a
candidate, touch paper/live ledgers, or call broker APIs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
BTC_SOURCE_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
BTC_RESEARCH_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
BTC_NEXT_HYPOTHESIS = Path("artifacts/btc_candidate_gate/latest/btc_next_hypothesis_decision_report.json")
BTC_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
MIN_HISTORY_DAYS = 365.0
MIN_1H_BARS = 365 * 24
MIN_FUNDING_EVENTS = 365 * 3
REQUIRED_SELECTED_BUNDLE_ROLES = {
    "klines_1h",
    "mark_price_klines_1h",
    "premium_index_klines_1h",
    "funding_rate",
    "exchange_info",
    "funding_info",
}


def build_btc_strategy_family_roadmap_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    next_hypothesis = _read_json(root / BTC_NEXT_HYPOTHESIS)
    registry = _read_json(root / BTC_RESEARCH_REGISTRY)
    data_status = _read_json(root / BTC_DATA_STATUS)
    provider = _read_json(root / BTC_PROVIDER_VERIFICATION)
    bundle = _selected_bundle_status(root)
    archived = _archived_or_rejected_families(registry)
    roles = _bundle_roles(bundle.get("manifest", {}))
    role_blockers = [
        f"missing_selected_bundle_role:{role}"
        for role in sorted(REQUIRED_SELECTED_BUNDLE_ROLES.difference(roles))
    ]
    duration_days = _float_or_none(bundle.get("duration_days")) or 0.0
    funding_events = int(bundle.get("funding_rate_record_count", 0) or 0)
    kline_1h_rows = int(bundle.get("klines_1h_record_count", 0) or 0)

    prerequisites = {
        "selected_provider": str(provider.get("selected_provider", bundle.get("source_provider", ""))),
        "selected_bundle_id": str(bundle.get("bundle_id", "")),
        "selected_bundle_manifest": str(bundle.get("manifest_path", "")),
        "selected_bundle_duration_days": round(duration_days, 6),
        "min_required_history_days": MIN_HISTORY_DAYS,
        "klines_1h_record_count": kline_1h_rows,
        "min_required_1h_bars": MIN_1H_BARS,
        "funding_rate_record_count": funding_events,
        "min_required_funding_events": MIN_FUNDING_EVENTS,
        "required_roles": sorted(REQUIRED_SELECTED_BUNDLE_ROLES),
        "present_roles": sorted(roles),
        "provider_perpetual_evidence_ready": bool(provider.get("perpetual_evidence_ready", False)),
        "provider_preflight_pass": bool(provider.get("preflight_pass", False)),
        "data_status": str(data_status.get("status", data_status.get("sample_status", "unknown"))),
    }
    data_ready = (
        bool(provider.get("perpetual_evidence_ready", False))
        and bool(provider.get("preflight_pass", False))
        and duration_days >= MIN_HISTORY_DAYS
        and kline_1h_rows >= MIN_1H_BARS
        and funding_events >= MIN_FUNDING_EVENTS
        and not role_blockers
    )
    selected_family = _selected_family(data_ready=data_ready)
    blockers = _blockers(
        next_hypothesis=next_hypothesis,
        bundle=bundle,
        duration_days=duration_days,
        kline_1h_rows=kline_1h_rows,
        funding_events=funding_events,
        role_blockers=role_blockers,
        data_ready=data_ready,
    )
    status = "family_design_ready_for_hypothesis_distribution" if data_ready else "family_design_data_blocked"
    return {
        "schema_version": "btc_strategy_family_roadmap_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_no_candidate_no_paper_no_live",
        "status": status,
        "decision": "select_funding_carry_reversion_hypothesis",
        "next_required_action": (
            "run_funding_carry_reversion_hypothesis_distribution_only"
            if data_ready
            else "extend_okx_public_history_before_hypothesis_or_candidate_generation"
        ),
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "hypothesis_distribution_allowed": data_ready,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "source_next_hypothesis_decision_report": _maybe_path(root, BTC_NEXT_HYPOTHESIS),
        "source_research_registry": _maybe_path(root, BTC_RESEARCH_REGISTRY),
        "source_data_status": _maybe_path(root, BTC_DATA_STATUS),
        "source_provider_verification": _maybe_path(root, BTC_PROVIDER_VERIFICATION),
        "next_hypothesis_status": str(next_hypothesis.get("status", "missing") or "missing"),
        "next_hypothesis_decision": str(next_hypothesis.get("decision", "")),
        "archived_or_rejected_family_count": len(archived),
        "archived_or_rejected_families": archived,
        "selected_next_family": selected_family,
        "candidate_families": _candidate_families(selected_family["family_id"]),
        "data_prerequisites": prerequisites,
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "hypothesis_distribution_allowed": data_ready,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "reuse_archived_price_action_families_allowed": False,
            "binance_disabled_for_current_provider_policy": True,
        },
        "interpretation": _interpretation(data_ready=data_ready, bundle=bundle, selected_family=selected_family),
        "blockers": blockers,
    }


def write_btc_strategy_family_roadmap_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_strategy_family_roadmap_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_strategy_family_roadmap_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_strategy_family_roadmap_report(payload, Path(args.output_root)))


def _selected_bundle_status(root: Path) -> dict[str, Any]:
    bundle_dir = selected_btc_perpetual_bundle_dir(root, root / BTC_SOURCE_CONFIG)
    manifest_path = bundle_dir / "btc_perpetual_bundle_manifest.json" if bundle_dir else None
    manifest = _read_json(manifest_path) if manifest_path else {}
    start = _parse_utc(manifest.get("sample_start"))
    end = _parse_utc(manifest.get("sample_end"))
    duration_days = (end - start).total_seconds() / 86_400.0 if start and end and end >= start else 0.0
    role_counts = {
        f"{role}_record_count": int(file_row.get("record_count", 0) or 0)
        for file_row in _manifest_files(manifest)
        for role in [str(file_row.get("role", ""))]
        if role
    }
    return {
        "bundle_dir": _relpath(bundle_dir, root) if bundle_dir else "",
        "manifest_path": _relpath(manifest_path, root) if manifest_path and manifest_path.exists() else "",
        "manifest": manifest,
        "bundle_id": str(manifest.get("bundle_id", "")),
        "source_provider": str(manifest.get("source_provider", manifest.get("exchange", ""))),
        "sample_start": str(manifest.get("sample_start", "")),
        "sample_end": str(manifest.get("sample_end", "")),
        "duration_days": duration_days,
        **role_counts,
    }


def _selected_family(*, data_ready: bool) -> dict[str, Any]:
    return {
        "family_id": "funding_carry_reversion_v0",
        "family": "funding_carry_reversion",
        "priority": 1,
        "status": "ready_for_hypothesis_distribution" if data_ready else "data_blocked",
        "core_hypothesis": (
            "extreme funding and premium can identify crowded perpetual positioning; "
            "the strategy should earn or avoid carry while trading only when lifecycle risk is bounded"
        ),
        "why_materially_different": (
            "uses funding, premium, and mark/index structure as primary inputs instead of price-trend continuation"
        ),
        "required_public_data": [
            "1h perpetual klines",
            "1h mark price klines",
            "1h premium/index proxy",
            "8h funding rate history",
            "exchange rules",
            "maker/taker fee tier",
        ],
        "forbidden_shortcuts": [
            "do not reuse dual-trend entry logic as the primary edge",
            "do not optimize Sharpe before event_PF, cost, and walk-forward pass",
            "do not use Binance-disabled provider data as OKX promotion evidence",
        ],
    }


def _candidate_families(selected_family_id: str) -> list[dict[str, Any]]:
    rows = [
        {
            "family_id": "funding_carry_reversion_v0",
            "family": "funding_carry_reversion",
            "priority": 1,
            "selection_status": "selected_next",
            "primary_edge_inputs": ["funding_rate", "premium_index", "mark_price", "perpetual_ohlcv"],
        },
        {
            "family_id": "basis_premium_convergence_v0",
            "family": "basis_premium_convergence",
            "priority": 2,
            "selection_status": "backlog",
            "primary_edge_inputs": ["premium_index", "mark_price", "index_price"],
        },
        {
            "family_id": "funding_window_flattening_v0",
            "family": "funding_window_execution_overlay",
            "priority": 3,
            "selection_status": "overlay_only_not_standalone_alpha",
            "primary_edge_inputs": ["funding_rate", "funding_interval", "position_lifecycle"],
        },
    ]
    for row in rows:
        if row["family_id"] == selected_family_id:
            row["selection_status"] = "selected_next"
    return rows


def _archived_or_rejected_families(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = _mapping(registry.get("items"))
    rows = []
    for family_id, item in sorted(items.items()):
        row = _mapping(item)
        status = str(row.get("status", ""))
        if status not in {"archived", "hypothesis_rejected"}:
            continue
        rows.append(
            {
                "family_id": str(family_id),
                "status": status,
                "last_run_id": str(row.get("last_run_id", "")),
                "next_action": str(row.get("next_action", "")),
                "reason": str(row.get("reason", "")),
            }
        )
    return rows


def _blockers(
    *,
    next_hypothesis: Mapping[str, Any],
    bundle: Mapping[str, Any],
    duration_days: float,
    kline_1h_rows: int,
    funding_events: int,
    role_blockers: list[str],
    data_ready: bool,
) -> list[str]:
    blockers: list[str] = []
    if str(next_hypothesis.get("status", "")) == "dual_trend_micro_surgery_rejected":
        blockers.append("btc_strategy_family_dual_trend_micro_surgery_rejected")
    if not bundle.get("manifest_path"):
        blockers.append("btc_strategy_family_selected_bundle_manifest_missing")
    if duration_days < MIN_HISTORY_DAYS:
        blockers.append("btc_strategy_family_selected_okx_bundle_history_too_short")
    if kline_1h_rows < MIN_1H_BARS:
        blockers.append("btc_strategy_family_selected_okx_1h_klines_too_short")
    if funding_events < MIN_FUNDING_EVENTS:
        blockers.append("btc_strategy_family_selected_okx_funding_history_too_short")
    blockers.extend(role_blockers)
    if not data_ready:
        blockers.append("btc_strategy_family_candidate_generation_blocked_until_okx_history_extended")
    return _dedupe(blockers)


def _interpretation(*, data_ready: bool, bundle: Mapping[str, Any], selected_family: Mapping[str, Any]) -> list[str]:
    if data_ready:
        return [
            f"selected next family {selected_family['family_id']} is materially different from dual-trend",
            "OKX selected bundle has enough public funding, premium, mark, and 1h OHLC history for hypothesis distribution work",
            "candidate generation remains separate from hypothesis distribution and paper/live stays locked",
        ]
    return [
        f"selected next family {selected_family['family_id']} is materially different from dual-trend",
        (
            "current selected OKX bundle "
            f"{bundle.get('bundle_id', '') or 'missing'} covers only "
            f"{round(float(bundle.get('duration_days', 0.0) or 0.0), 6)} days"
        ),
        "extend OKX public history before any funding/carry hypothesis distribution, candidate generation, or paper review",
    ]


def _bundle_roles(manifest: Mapping[str, Any]) -> set[str]:
    return {str(row.get("role", "")) for row in _manifest_files(manifest) if str(row.get("role", ""))}


def _manifest_files(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    files = manifest.get("files")
    return [row for row in files if isinstance(row, Mapping)] if isinstance(files, list) else []


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_path(root: Path, path: Path) -> str | None:
    full = root / path
    return _relpath(full, root) if full.exists() else None


def _relpath(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
