#!/usr/bin/env python3
"""Build US equity provider capability matrix without promotion verification."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.data.lineage.local_csv_provider import load_provider_sources_config  # noqa: E402


DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/provider_capability_matrix.json")
DEFAULT_CONFIG = Path("configs/data/us_equity_provider_sources.yaml")
PROVIDER_IDS = ["yfinance", "crsp", "sharadar", "polygon", "norgate", "local_csv"]


def build_provider_capability_matrix(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    config_ref = config_path if config_path.is_absolute() else root / config_path
    config = load_provider_sources_config(config_ref)
    providers_config = _mapping(config.get("providers"))
    us_equity_manifests = _load_us_equity_manifests(root)
    rows = [
        _provider_row(
            provider_id=provider_id,
            provider_config=_mapping(providers_config.get(provider_id)),
            us_equity_manifests=us_equity_manifests,
            repo_root=root,
        )
        for provider_id in PROVIDER_IDS
    ]
    verified = [row for row in rows if row["verified_for_promotion"] is True]
    blockers = []
    if not verified:
        blockers.append("promotion_clean_provider_not_verified")
    blockers.append("selected_provider_profile_missing")
    blockers.append("provider_verification_required")
    return {
        "schema_version": "us_equity_provider_capability_matrix_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "providers": rows,
        "selected_provider_profile": None,
        "promotion_clean_provider_available": bool(verified),
        "blockers": _dedupe(blockers),
    }


def write_provider_capability_matrix(payload: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_provider_capability_matrix(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
        config_path=Path(args.config_path),
    )
    print(write_provider_capability_matrix(payload, Path(args.output)))


def _provider_row(
    *,
    provider_id: str,
    provider_config: Mapping[str, Any],
    us_equity_manifests: list[Mapping[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    enabled = bool(provider_config.get("enabled", False))
    provider_names = {
        "yfinance": "Yahoo Finance / yfinance",
        "crsp": "CRSP",
        "sharadar": "Sharadar / Nasdaq Data Link",
        "polygon": "Polygon",
        "norgate": "Norgate",
        "local_csv": "Local CSV import",
    }
    roles = {
        "yfinance": ["price_bars"],
        "local_csv": ["lineage_import", "price_bars_optional"],
        "crsp": ["candidate_provider"],
        "sharadar": ["candidate_provider"],
        "polygon": ["candidate_provider"],
        "norgate": ["candidate_provider"],
    }
    blockers: list[str] = []
    local_data_available = False
    local_data_verified = False
    if provider_id == "yfinance":
        local_data_available = any(str(item.get("source", "")).lower() == "yfinance" for item in us_equity_manifests)
        local_data_verified = local_data_available
        blockers.extend(
            [
                "point_in_time_universe_not_supported",
                "delisting_coverage_not_supported",
                "corporate_action_event_source_not_verified",
                "identifier_mapping_missing",
                "provider_not_promotion_clean_capable",
            ]
        )
    elif provider_id == "local_csv":
        root = _local_csv_root(repo_root, provider_config)
        files = _mapping(provider_config.get("files"))
        local_data_available = enabled and any(
            (root / str(value)).exists()
            for value in files.values()
            if value not in (None, "")
        )
        local_data_verified = False
        if not enabled:
            blockers.append("local_csv_provider_disabled")
        if not local_data_available:
            blockers.append("local_csv_lineage_files_missing")
    else:
        blockers.append("provider_not_configured")
        blockers.append("provider_local_data_missing")
        blockers.append("provider_capability_not_locally_verified")

    configured = bool(enabled or provider_id == "yfinance")
    if not configured:
        local_data_available = False
        local_data_verified = False
    if not local_data_verified:
        blockers.append("provider_local_data_not_verified_for_promotion")

    return {
        "provider_id": provider_id,
        "provider_name": provider_names[provider_id],
        "provider_role": roles[provider_id],
        "configured": configured,
        "local_data_available": local_data_available,
        "local_data_verified": local_data_verified,
        "supports_price_bars": True if provider_id in {"yfinance", "local_csv"} else "unknown",
        "supports_point_in_time_universe": True if provider_id == "local_csv" else False if provider_id == "yfinance" else "unknown",
        "supports_historical_membership_events": True if provider_id == "local_csv" else False if provider_id == "yfinance" else "unknown",
        "supports_delisted_symbols": True if provider_id == "local_csv" else False if provider_id == "yfinance" else "unknown",
        "supports_split_events": True if provider_id == "local_csv" else "unknown",
        "supports_dividend_events": True if provider_id == "local_csv" else "unknown",
        "supports_adjustment_reproducibility": True if provider_id == "local_csv" else False if provider_id == "yfinance" else "unknown",
        "supports_symbol_mapping": True if provider_id == "local_csv" else False if provider_id == "yfinance" else "unknown",
        "promotion_clean_capable": False,
        "verified_for_promotion": False,
        "blockers": _dedupe(blockers),
    }


def _local_csv_root(repo_root: Path, provider_config: Mapping[str, Any]) -> Path:
    root = Path(str(provider_config.get("root") or "data/external/us_equity_lineage"))
    return root if root.is_absolute() else repo_root / root


def _load_us_equity_manifests(root: Path) -> list[dict[str, Any]]:
    manifests = []
    for path in sorted((root / "data" / "manifests").glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload = _read_json(path)
        if _looks_like_us_equity_manifest(payload):
            manifests.append(payload)
    return manifests


def _looks_like_us_equity_manifest(data: Mapping[str, Any]) -> bool:
    return (
        all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))
        and str(data.get("source", "")).lower() in {"yfinance", "alpaca"}
        and str(data.get("asset_class", "equity")).lower() == "equity"
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
