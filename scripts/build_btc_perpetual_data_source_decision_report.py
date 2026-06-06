#!/usr/bin/env python3
"""Build a BTC perpetual data-source decision report.

This report separates current venue evidence from longer historical data used
only for research diagnostics. It does not call network, broker, account, or
order APIs.
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


DEFAULT_OUTPUT = Path("artifacts/btc_data_status/latest/btc_perpetual_data_source_decision_report.json")
BTC_SOURCE_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
MIN_HISTORY_DAYS = 365.0
MIN_1H_BARS = 365 * 24
MIN_FUNDING_EVENTS = 365 * 3
REQUIRED_RESEARCH_ROLES = {
    "klines_1h",
    "mark_price_klines_1h",
    "premium_index_klines_1h",
    "funding_rate",
}


def build_btc_perpetual_data_source_decision_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    current_bundle = _current_bundle(root)
    candidates = _candidate_sources(root, current_bundle=current_bundle)
    selected_overlay = _select_research_overlay(candidates)
    overlay_ready = bool(selected_overlay.get("research_history_sufficient", False))
    return {
        "schema_version": "btc_perpetual_data_source_decision_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "market_type": "usds_m_perpetual",
        "status": (
            "research_history_overlay_ready_execution_provider_not_switched"
            if overlay_ready
            else "research_history_source_blocked"
        ),
        "decision": "switch_research_history_source_keep_execution_locked",
        "next_required_action": (
            "run_research_only_funding_carry_distribution_on_history_overlay"
            if overlay_ready
            else "import_vendor_normalized_derivatives_history_or_extend_current_provider_history"
        ),
        "current_evidence_provider": current_bundle,
        "selected_research_history_source": selected_overlay,
        "candidate_data_sources": candidates,
        "better_data_source_recommendation": {
            "primary": "normalized_derivatives_history_vendor",
            "preferred_options": ["Tardis.dev", "CoinAPI"],
            "why": (
                "exchange public REST endpoints are optimized for recent market data; "
                "funding/carry research needs normalized long-history OHLC, mark/index/premium, and funding records"
            ),
            "requires_user_supplied_credential_or_files": True,
            "no_secret_present_in_repo": True,
        },
        "guardrails": {
            "research_only": True,
            "strategy_generation_allowed": False,
            "candidate_generation_allowed": False,
            "paper_review_pending_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "cross_venue_history_may_unlock_hypothesis_diagnostics_only": overlay_ready,
            "cross_venue_history_may_unlock_candidate_or_paper": False,
        },
        "interpretation": _interpretation(
            current_bundle=current_bundle,
            selected_overlay=selected_overlay,
            overlay_ready=overlay_ready,
        ),
        "blockers": _blockers(
            current_bundle=current_bundle,
            selected_overlay=selected_overlay,
            overlay_ready=overlay_ready,
        ),
    }


def write_btc_perpetual_data_source_decision_report(payload: Mapping[str, Any], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_perpetual_data_source_decision_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_perpetual_data_source_decision_report(payload, Path(args.output)))


def _current_bundle(root: Path) -> dict[str, Any]:
    bundle_dir = selected_btc_perpetual_bundle_dir(root, root / BTC_SOURCE_CONFIG)
    manifest_path = bundle_dir / "btc_perpetual_bundle_manifest.json" if bundle_dir else None
    manifest = _read_json(manifest_path) if manifest_path else {}
    return _bundle_status(root=root, manifest_path=manifest_path, manifest=manifest, role="current_evidence_provider")


def _candidate_sources(root: Path, *, current_bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted((root / "data/external/btc_perpetual").glob("*/bundles/*/btc_perpetual_bundle_manifest.json")):
        manifest = _read_json(manifest_path)
        role = "current_evidence_provider" if _same_path(manifest_path, current_bundle.get("manifest_path"), root) else "local_history_candidate"
        rows.append(_bundle_status(root=root, manifest_path=manifest_path, manifest=manifest, role=role))
    rows.extend(
        [
            _policy_source(
                provider="bybit_linear_public_rest",
                status="rejected_as_user_trading_provider",
                reason="official restricted-jurisdiction policy includes Chinese Mainland; do not use as execution venue for this user",
            ),
            _policy_source(
                provider="gate_futures_public_rest",
                status="rejected_as_user_trading_provider",
                reason="official restricted-location policy includes Mainland China; do not use as execution venue for this user",
            ),
            _policy_source(
                provider="mexc_futures_public_rest",
                status="rejected_as_user_trading_provider",
                reason="official prohibited-country policy includes Mainland China; do not use as execution venue for this user",
            ),
            _policy_source(
                provider="kucoin_futures_public_rest",
                status="rejected_as_user_trading_provider",
                reason="official restricted-location policy includes mainland China; do not use as execution venue for this user",
            ),
            _policy_source(
                provider="hyperliquid_public_api",
                status="separate_instrument_contract_required",
                reason="public BTC data exists, but the instrument is not BTCUSDT USD-M perpetual; do not merge into BTCUSDT evidence without a separate contract",
            ),
            _policy_source(
                provider="normalized_derivatives_history_vendor",
                status="recommended_requires_credential_or_files",
                reason="best fit for long-history funding, mark/index/premium, and OHLC research without using a restricted exchange as execution venue",
            ),
        ]
    )
    return rows


def _select_research_overlay(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        row
        for row in candidates
        if row.get("source_type") == "production"
        and row.get("symbol") == "BTCUSDT"
        and row.get("market_type") == "usds_m_perpetual"
        and row.get("research_history_sufficient") is True
    ]
    if not eligible:
        return {
            "provider": "",
            "bundle_id": "",
            "source_type": "",
            "source_role": "",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "manifest_path": "",
            "sample_start": "",
            "sample_end": "",
            "duration_days": 0.0,
            "klines_1h_record_count": 0,
            "funding_rate_record_count": 0,
            "required_roles_present": False,
            "research_history_sufficient": False,
            "status": "missing",
            "allowed_uses": [],
            "forbidden_uses": ["candidate_generation", "paper_review", "paper_or_live"],
            "blockers": ["btc_research_history_overlay_missing"],
        }
    eligible.sort(
        key=lambda row: (
            float(row.get("duration_days", 0.0) or 0.0),
            int(row.get("funding_rate_record_count", 0) or 0),
            int(row.get("klines_1h_record_count", 0) or 0),
        ),
        reverse=True,
    )
    selected = dict(eligible[0])
    selected["status"] = "selected_research_only_history_overlay"
    selected["allowed_uses"] = [
        "funding_carry_hypothesis_distribution_diagnostics",
        "data_quality_gap_detection",
        "cross_venue_sanity_check",
    ]
    selected["forbidden_uses"] = [
        "candidate_generation",
        "strategy_skeleton_generation",
        "paper_review",
        "paper_or_live_execution",
        "broker_or_order_routing",
    ]
    return selected


def _bundle_status(*, root: Path, manifest_path: Path | None, manifest: Mapping[str, Any], role: str) -> dict[str, Any]:
    files = [item for item in manifest.get("files", []) if isinstance(item, Mapping)]
    counts = {str(item.get("role", "")): int(item.get("record_count", 0) or 0) for item in files}
    roles = {str(item.get("role", "")) for item in files}
    start = _parse_utc(manifest.get("sample_start"))
    end = _parse_utc(manifest.get("sample_end"))
    duration_days = (end - start).total_seconds() / 86_400.0 if start and end and end >= start else 0.0
    missing_roles = sorted(REQUIRED_RESEARCH_ROLES.difference(roles))
    research_sufficient = (
        duration_days >= MIN_HISTORY_DAYS
        and counts.get("klines_1h", 0) >= MIN_1H_BARS
        and counts.get("funding_rate", 0) >= MIN_FUNDING_EVENTS
        and not missing_roles
    )
    provider = str(manifest.get("source_provider", ""))
    blockers = []
    if not manifest_path or not manifest_path.exists():
        blockers.append("btc_data_source_manifest_missing")
    if missing_roles:
        blockers.extend(f"btc_data_source_missing_role:{role_name}" for role_name in missing_roles)
    if duration_days < MIN_HISTORY_DAYS:
        blockers.append("btc_data_source_history_too_short")
    if counts.get("klines_1h", 0) < MIN_1H_BARS:
        blockers.append("btc_data_source_1h_klines_too_short")
    if counts.get("funding_rate", 0) < MIN_FUNDING_EVENTS:
        blockers.append("btc_data_source_funding_history_too_short")
    if provider == "binance_usdm":
        blockers.append("btc_data_source_binance_research_only_not_user_execution_provider")
    return {
        "provider": provider,
        "bundle_id": str(manifest.get("bundle_id", "")),
        "source_type": str(manifest.get("source_type", "")),
        "source_role": role,
        "symbol": str(manifest.get("symbol", "")),
        "market_type": str(manifest.get("market_type", "")),
        "manifest_path": _relpath(manifest_path, root) if manifest_path and manifest_path.exists() else "",
        "sample_start": str(manifest.get("sample_start", "")),
        "sample_end": str(manifest.get("sample_end", "")),
        "duration_days": round(duration_days, 6),
        "klines_1h_record_count": counts.get("klines_1h", 0),
        "funding_rate_record_count": counts.get("funding_rate", 0),
        "required_roles_present": not missing_roles,
        "research_history_sufficient": research_sufficient,
        "blockers": _dedupe(blockers),
    }


def _policy_source(*, provider: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "bundle_id": "",
        "source_type": "external_policy_or_vendor_option",
        "source_role": "external_candidate",
        "symbol": "BTCUSDT" if "hyperliquid" not in provider else "BTC",
        "market_type": "usds_m_perpetual" if "hyperliquid" not in provider else "non_btcusdt_perpetual",
        "manifest_path": "",
        "sample_start": "",
        "sample_end": "",
        "duration_days": 0.0,
        "klines_1h_record_count": 0,
        "funding_rate_record_count": 0,
        "required_roles_present": False,
        "research_history_sufficient": False,
        "status": status,
        "reason": reason,
        "blockers": [status],
    }


def _blockers(
    *,
    current_bundle: Mapping[str, Any],
    selected_overlay: Mapping[str, Any],
    overlay_ready: bool,
) -> list[str]:
    blockers = []
    if current_bundle.get("research_history_sufficient") is not True:
        blockers.append("btc_current_evidence_provider_history_too_short_for_research_distribution")
    if not overlay_ready:
        blockers.append("btc_research_history_overlay_not_ready")
    if selected_overlay.get("provider") == "binance_usdm":
        blockers.append("btc_selected_research_overlay_is_not_user_execution_provider")
    blockers.append("btc_data_source_decision_does_not_unlock_candidate_or_paper")
    return _dedupe(blockers)


def _interpretation(
    *,
    current_bundle: Mapping[str, Any],
    selected_overlay: Mapping[str, Any],
    overlay_ready: bool,
) -> list[str]:
    rows = [
        (
            "OKX remains the current public evidence provider, but its selected bundle covers only "
            f"{current_bundle.get('duration_days', 0.0)} days"
        ),
        "do not switch to Bybit/Gate/MEXC/KuCoin as execution providers for a mainland-China resident",
    ]
    if overlay_ready:
        rows.append("use the selected longer local history overlay for research-only funding/carry distribution diagnostics")
        rows.append("candidate generation and paper/live remain blocked until same-venue or approved vendor evidence passes")
    else:
        rows.append("import approved vendor history before funding/carry distribution diagnostics")
    return rows


def _same_path(manifest_path: Path, maybe_relpath: object, root: Path) -> bool:
    if not maybe_relpath:
        return False
    return (root / str(maybe_relpath)).resolve() == manifest_path.resolve()


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _relpath(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        if value and value not in seen:
            rows.append(value)
            seen.add(value)
    return rows


if __name__ == "__main__":
    main()
