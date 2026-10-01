#!/usr/bin/env python3
"""Build a read-only BTC true-scalping microstructure readiness report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
DEFAULT_MANIFEST_ROOT = Path("data/manifests")


def build_btc_true_scalping_microstructure_readiness_report(
    *,
    repo_root: Path | None = None,
    data_status_path: Path | None = None,
    manifest_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    data_status = _read_json(_resolve(root, data_status_path or DEFAULT_DATA_STATUS))
    manifest_dir = _resolve(root, manifest_root or DEFAULT_MANIFEST_ROOT)
    one_minute = _one_minute_kline_evidence(root=root, manifest_root=manifest_dir)
    selected_provider = str(
        _mapping(data_status.get("perpetual_provider_verification")).get("selected_provider", "okx_swap")
        or "okx_swap"
    )
    selected_bundle_id = str(
        _mapping(data_status.get("perpetual_provider_verification")).get(
            "selected_bundle_id", "btc_okx_swap_btcusdt_history_365d_v1"
        )
        or "btc_okx_swap_btcusdt_history_365d_v1"
    )
    bundle_dir = root / "data" / "external" / "btc_perpetual" / selected_provider / "bundles" / selected_bundle_id
    tick_history = _bundle_file_evidence(
        root=root,
        bundle_dir=bundle_dir,
        evidence_id="tick_or_agg_trade_history",
        required_files=("agg_trades.csv", "aggTrades.csv", "trades.csv", "tick_trades.csv"),
    )
    order_book = _bundle_file_evidence(
        root=root,
        bundle_dir=bundle_dir,
        evidence_id="order_book_depth_history",
        required_files=("order_book_depth.csv", "depth_snapshots.csv", "book_ticker.csv", "orderbook.csv"),
    )
    spread_model = _model_file_evidence(
        root=root,
        evidence_id="spread_model",
        paths=(
            Path("artifacts/btc_scalping_readiness/latest/spread_model.json"),
            Path("configs/risk/btc_spread_model.json"),
            Path("configs/btc_spread_model.json"),
        ),
    )
    latency_model = _model_file_evidence(
        root=root,
        evidence_id="latency_model",
        paths=(
            Path("artifacts/btc_scalping_readiness/latest/latency_model.json"),
            Path("configs/risk/btc_latency_model.json"),
            Path("configs/btc_latency_model.json"),
        ),
    )
    queue_model = _model_file_evidence(
        root=root,
        evidence_id="queue_position_model",
        paths=(
            Path("artifacts/btc_scalping_readiness/latest/queue_position_model.json"),
            Path("configs/risk/btc_queue_position_model.json"),
            Path("configs/btc_queue_position_model.json"),
        ),
    )
    blockers = _blockers(
        one_minute=one_minute,
        tick_history=tick_history,
        order_book=order_book,
        spread_model=spread_model,
        latency_model=latency_model,
        queue_model=queue_model,
    )
    microstructure_ready = not blockers
    return {
        "schema_version": "btc_true_scalping_microstructure_readiness_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": "microstructure_evidence_ready_research_only"
        if microstructure_ready
        else "blocked_microstructure_evidence_missing",
        "decision": "manual_review_before_research_only_scalping_strategy_design"
        if microstructure_ready
        else "continue_microstructure_evidence_collection",
        "next_required_action": "manual_review_before_research_only_scalping_strategy_design"
        if microstructure_ready
        else "collect_or_import_tick_orderbook_spread_latency_queue_evidence",
        "source_data_status": _relpath(_resolve(root, data_status_path or DEFAULT_DATA_STATUS), root)
        if _resolve(root, data_status_path or DEFAULT_DATA_STATUS).exists()
        else None,
        "selected_provider": selected_provider,
        "selected_bundle_id": selected_bundle_id,
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "evidence": {
            "one_minute_klines": one_minute,
            "tick_or_agg_trade_history": tick_history,
            "order_book_depth_history": order_book,
            "spread_model": spread_model,
            "latency_model": latency_model,
            "queue_position_model": queue_model,
        },
        "blockers": blockers,
        "true_scalping_research_design_allowed": microstructure_ready,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "guardrails": {
            "read_only": True,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "broker_calls_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
        "allowed_next_actions": _allowed_next_actions(blockers),
    }


def write_btc_true_scalping_microstructure_readiness_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_true_scalping_microstructure_readiness_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-status-path", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_microstructure_readiness_report(
        repo_root=Path(args.repo_root),
        data_status_path=Path(args.data_status_path),
        manifest_root=Path(args.manifest_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_true_scalping_microstructure_readiness_report(payload, Path(args.output_root)))


def _one_minute_kline_evidence(*, root: Path, manifest_root: Path) -> dict[str, Any]:
    manifest = _latest_manifest(manifest_root, interval="1m")
    if not manifest:
        return {
            "status": "missing",
            "data_version": None,
            "manifest_path": None,
            "row_count": 0,
            "expected_rows": 0,
            "coverage_pct": 0.0,
            "quality_score": 0.0,
            "start": None,
            "end": None,
        }
    row_count = int(manifest.get("row_count", 0) or 0)
    expected_rows = int(manifest.get("expected_rows", row_count) or 0)
    coverage_pct = _float(manifest.get("coverage_pct"))
    quality_score = _float(manifest.get("quality_score"))
    status = "pass" if row_count > 0 and row_count == expected_rows and coverage_pct >= 99.0 and quality_score >= 80.0 else "fail"
    manifest_path = manifest_root / f"{manifest.get('data_version')}.json"
    return {
        "status": status,
        "data_version": str(manifest.get("data_version", "")),
        "manifest_path": _relpath(manifest_path, root),
        "row_count": row_count,
        "expected_rows": expected_rows,
        "coverage_pct": coverage_pct,
        "quality_score": quality_score,
        "start": str(manifest.get("start", "")),
        "end": str(manifest.get("end", "")),
    }


def _bundle_file_evidence(
    *,
    root: Path,
    bundle_dir: Path,
    evidence_id: str,
    required_files: Iterable[str],
) -> dict[str, Any]:
    present = [bundle_dir / name for name in required_files if (bundle_dir / name).exists()]
    return {
        "status": "pass" if present else "missing",
        "evidence_id": evidence_id,
        "bundle_dir": _relpath(bundle_dir, root),
        "required_any_of": list(required_files),
        "files": [_relpath(path, root) for path in present],
    }


def _model_file_evidence(*, root: Path, evidence_id: str, paths: Iterable[Path]) -> dict[str, Any]:
    resolved = [_resolve(root, path) for path in paths]
    present = [path for path in resolved if path.exists()]
    if not present:
        return {
            "status": "missing",
            "evidence_id": evidence_id,
            "required_any_of": [_relpath(path, root) for path in resolved],
            "files": [],
        }
    model_path = present[0]
    model = _read_json(model_path)
    model_status = str(model.get("status", "missing") or "missing")
    return {
        "status": "pass" if model_status == "pass" else "fail",
        "evidence_id": evidence_id,
        "required_any_of": [_relpath(path, root) for path in resolved],
        "files": [_relpath(path, root) for path in present],
        "model_status": model_status,
        "model_schema_version": str(model.get("schema_version", "")),
        "model_id": str(model.get("model_id", "")),
        "evidence_grade": str(model.get("evidence_grade", "")),
        "sample_count": int(model.get("sample_count", 0) or 0),
        "model_blockers": _list_of_strings(model.get("blockers")),
    }


def _blockers(
    *,
    one_minute: Mapping[str, Any],
    tick_history: Mapping[str, Any],
    order_book: Mapping[str, Any],
    spread_model: Mapping[str, Any],
    latency_model: Mapping[str, Any],
    queue_model: Mapping[str, Any],
) -> list[str]:
    blockers = []
    if one_minute.get("status") != "pass":
        blockers.append("btc_1m_kline_manifest_missing_or_not_pass")
    if tick_history.get("status") != "pass":
        blockers.append("btc_tick_or_agg_trade_history_missing")
    if order_book.get("status") != "pass":
        blockers.append("btc_order_book_depth_history_missing")
    if spread_model.get("status") != "pass":
        blockers.append("btc_spread_model_missing")
    if latency_model.get("status") != "pass":
        blockers.append("btc_latency_model_missing")
    if queue_model.get("status") != "pass":
        blockers.append("btc_queue_position_model_missing")
    return blockers


def _allowed_next_actions(blockers: list[str]) -> list[str]:
    actions = []
    if "btc_1m_kline_manifest_missing_or_not_pass" in blockers:
        actions.append("repair_or_regenerate_btc_1m_kline_manifest")
    if "btc_tick_or_agg_trade_history_missing" in blockers:
        actions.append("collect_or_import_public_tick_or_agg_trade_history")
    if "btc_order_book_depth_history_missing" in blockers:
        actions.append("collect_or_import_public_order_book_depth_history")
    if "btc_spread_model_missing" in blockers:
        actions.append("build_spread_model_from_trade_or_order_book_evidence")
    if "btc_latency_model_missing" in blockers:
        actions.append("define_research_latency_model_without_live_order_access")
    if "btc_queue_position_model_missing" in blockers:
        actions.append("define_queue_position_model_from_order_book_depth_evidence")
    return actions or ["manual_review_before_research_only_scalping_strategy_design"]


def _latest_manifest(manifest_root: Path, *, interval: str) -> dict[str, Any]:
    candidates: list[tuple[float, float, str, dict[str, Any]]] = []
    for path in sorted(manifest_root.glob(f"qs-sqlite-BTCUSDT-{interval}-*.json")):
        payload = _read_json(path)
        if (
            str(payload.get("source", "")) != "sqlite"
            or str(payload.get("symbol", "")).upper() != "BTCUSDT"
            or str(payload.get("interval", "")) != interval
        ):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((_timestamp_sort_value(payload.get("created_at")), mtime, path.name, payload))
    return max(candidates, key=lambda item: item[:3])[3] if candidates else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _timestamp_sort_value(value: object) -> float:
    text = str(value or "")
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
