#!/usr/bin/env python3
"""Build read-only US equity data status artifacts from existing manifests."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/us_equity_data_status/latest")
DATA_MANIFEST_ROOT = Path("data/manifests")


def build_us_equity_data_status(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    manifest_items = _load_us_equity_manifests(root)
    manifests = [payload for _, payload in manifest_items]
    data_versions = [str(item.get("data_version", "")) for item in manifests if item.get("data_version")]
    symbols = sorted({str(item.get("symbol", "")).upper() for item in manifests if item.get("symbol")})
    latest_manifest = _latest_existing_path([path for path, _ in manifest_items])

    universe_manifest = _build_universe_manifest(
        manifests=manifests,
        data_versions=data_versions,
        symbols=symbols,
        latest_manifest=_relpath(latest_manifest, root) if latest_manifest else None,
        generated_at=generated,
    )
    corporate_action_report = _build_corporate_action_report(
        manifests=manifests,
        symbols=symbols,
        generated_at=generated,
    )
    blockers = _build_data_status_blockers(manifests, universe_manifest, corporate_action_report)
    quality_summary = _aggregate_quality_summary(manifests)
    data_status = {
        "schema_version": "us_equity_data_status_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": "missing" if not manifests else ("complete" if not blockers else "partial"),
        "manifest_count": len(manifests),
        "latest_data_manifest": _relpath(latest_manifest, root) if latest_manifest else None,
        "data_versions": data_versions[:200],
        "symbols": symbols,
        "sources": sorted({str(item.get("source", "")) for item in manifests if item.get("source")}),
        "intervals": sorted({str(item.get("interval", "")) for item in manifests if item.get("interval")}),
        "calendar_id": "XNYS",
        "timezone": "UTC",
        "timezone_status": _timezone_status(manifests),
        "adjustment_policies": _adjustment_policies(manifests),
        "survivorship_status": _survivorship_status(manifests),
        "quality_summary": quality_summary,
        "universe_manifest_path": str(DEFAULT_OUTPUT_ROOT / "universe_manifest.json"),
        "corporate_action_report_path": str(DEFAULT_OUTPUT_ROOT / "corporate_action_report.json"),
        "blockers": blockers,
        "promotion_ready": False,
        "paper_queue_status": "locked",
        "live_status": "frozen",
    }
    return {
        "data_status_report": data_status,
        "universe_manifest": universe_manifest,
        "corporate_action_report": corporate_action_report,
    }


def write_us_equity_data_status(payload: Mapping[str, Any], output_root: Path) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "data_status_report": output_root / "data_status_report.json",
        "universe_manifest": output_root / "universe_manifest.json",
        "corporate_action_report": output_root / "corporate_action_report.json",
    }
    payload_to_write = {key: dict(payload[key]) for key in paths}
    payload_to_write["data_status_report"]["universe_manifest_path"] = str(paths["universe_manifest"])
    payload_to_write["data_status_report"]["corporate_action_report_path"] = str(paths["corporate_action_report"])
    for key, path in paths.items():
        path.write_text(json.dumps(payload_to_write[key], indent=2, sort_keys=True), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    payload = build_us_equity_data_status(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    paths = write_us_equity_data_status(payload, Path(args.output_root))
    print(json.dumps(paths, indent=2, sort_keys=True))


def _load_us_equity_manifests(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((root / DATA_MANIFEST_ROOT).glob("*.json")):
        if path.stem.startswith("run_"):
            continue
        payload = _read_json(path)
        if _looks_like_us_equity_manifest(payload):
            result.append((path, payload))
    return result


def _build_universe_manifest(
    *,
    manifests: list[Mapping[str, Any]],
    data_versions: list[str],
    symbols: list[str],
    latest_manifest: str | None,
    generated_at: str,
) -> dict[str, Any]:
    ends = sorted(str(item.get("end", "")) for item in manifests if item.get("end"))
    return {
        "schema_version": "us_equity_universe_manifest_v1",
        "generated_at": generated_at,
        "status": "partial" if manifests else "missing",
        "universe_id": "us_equity_manifest_universe_v1",
        "universe_source": "data_manifests",
        "asset": "us_equity",
        "calendar_id": "XNYS",
        "as_of": ends[-1] if ends else "",
        "latest_data_manifest": latest_manifest,
        "manifest_count": len(manifests),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "data_versions": data_versions[:200],
        "adjustment_policies": _adjustment_policies(manifests),
        "selection_rule": "symbols observed in US equity data manifests",
        "survivorship_bias_risk": _survivorship_status(manifests),
        "point_in_time": False,
        "promotion_ready": False,
        "blockers": [
            "universe_snapshot_manifest_derived_only",
            "point_in_time_universe_not_confirmed",
        ],
        "repo_root_independent": True,
        "source_manifest_root": str(DATA_MANIFEST_ROOT),
    }


def _build_corporate_action_report(
    *,
    manifests: list[Mapping[str, Any]],
    symbols: list[str],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "us_equity_corporate_action_report_v1",
        "generated_at": generated_at,
        "asset": "us_equity",
        "status": "manifest_derived_only" if manifests else "missing",
        "symbol_count": len(symbols),
        "symbols": symbols,
        "adjustment_policies": _adjustment_policies(manifests),
        "promotion_ready": False,
        "blockers": ["corporate_action_event_source_missing"],
    }


def _build_data_status_blockers(
    manifests: list[Mapping[str, Any]],
    universe_manifest: Mapping[str, Any],
    corporate_action_report: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not manifests:
        blockers.append("us_equity_data_manifest_missing")
    if universe_manifest.get("blockers"):
        blockers.extend(str(item) for item in universe_manifest["blockers"])
    if corporate_action_report.get("blockers"):
        blockers.extend(str(item) for item in corporate_action_report["blockers"])
    if _survivorship_status(manifests) in {"unknown", "mixed"}:
        blockers.append("survivorship_status_not_clean")
    return _dedupe(blockers)


def _aggregate_quality_summary(manifests: list[Mapping[str, Any]]) -> dict[str, Any]:
    coverages = [_float(item.get("coverage_pct")) for item in manifests if item.get("coverage_pct") is not None]
    quality_scores = [_float(item.get("quality_score")) for item in manifests if item.get("quality_score") is not None]
    issue_keys = [
        "missing_bars",
        "duplicate_bars",
        "invalid_ohlc_rows",
        "non_positive_price_rows",
        "zero_volume_bars",
        "total_issue_count",
    ]
    issue_totals = {key: 0 for key in issue_keys}
    for item in manifests:
        summary = item.get("quality_summary", {})
        if not isinstance(summary, Mapping):
            continue
        for key in issue_keys:
            issue_totals[key] += int(summary.get(key, 0) or 0)
    return {
        "min_coverage_pct": min(coverages) if coverages else 0.0,
        "avg_coverage_pct": (sum(coverages) / len(coverages)) if coverages else 0.0,
        "min_quality_score": min(quality_scores) if quality_scores else 0.0,
        "avg_quality_score": (sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0,
        **issue_totals,
    }


def _timezone_status(manifests: list[Mapping[str, Any]]) -> str:
    values = {str(item.get("timezone", "") or "").upper() for item in manifests}
    values.discard("")
    if not manifests:
        return "missing"
    return "utc" if values == {"UTC"} else "mixed_or_non_utc"


def _adjustment_policies(manifests: list[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(
                item.get("adjustment_policy")
                or item.get("corporate_action_adjustment")
                or item.get("adjustment")
                or "unknown"
            )
            for item in manifests
        }
    )


def _survivorship_status(manifests: list[Mapping[str, Any]]) -> str:
    values = {
        str(item.get("survivorship_bias_risk", "unknown") or "unknown").lower()
        for item in manifests
    }
    if not values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _looks_like_us_equity_manifest(data: Mapping[str, Any]) -> bool:
    source = str(data.get("source", "")).lower()
    asset_class = str(data.get("asset_class", "equity")).lower()
    return (
        all(data.get(key) for key in ("data_version", "source", "symbol", "interval"))
        and source in {"yfinance", "alpaca"}
        and asset_class == "equity"
    )


def _latest_existing_path(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
