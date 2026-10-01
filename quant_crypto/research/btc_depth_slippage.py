from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
from quant_crypto.research.btc_10s_microstructure_data_contract import resolve_source
from quant_crypto.research.btc_okx_native_promotion_gate import evaluate_btc_okx_native_promotion_blockers


SCHEMA_VERSION = "btc_depth_slippage_report_v1"
DEFAULT_CONFIG_PATH = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_cost_model/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "btc_depth_slippage_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_ROOT / "btc_depth_slippage_summary_cn.md"
DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT = DEFAULT_OUTPUT_ROOT / "btc_binance_vision_book_depth_diagnostic_report.json"
DEFAULT_STRATEGY_FILL_MAPPING_REPORT = DEFAULT_OUTPUT_ROOT / "btc_depth_slippage_fill_mapping_report.json"
DEFAULT_STRATEGY_FILL_MAPPING_ROWS = DEFAULT_OUTPUT_ROOT / "btc_depth_slippage_fill_mapping_rows.csv"
DEFAULT_L2_BATCH_REPORT = Path(
    "artifacts/btc_l2_depth_observation/latest/btc_okx_l2_depth_observation_batch_report.json"
)
DEFAULT_CURRENT_EVENT_LEDGER = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_event_ledger.csv")
DEFAULT_DRILL_EVENT_LEDGER = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_event_ledger.csv")
ORDER_NOTIONAL_USD = (100.0, 1_000.0, 5_000.0, 10_000.0)
MIN_POSITIVE_SLIPPAGE_FLOOR_BPS = 1.0
MIN_HISTORY_SNAPSHOT_COUNT = 48
MIN_HISTORY_COVERAGE_DAYS = 14.0
MAX_HISTORY_GAP_HOURS = 12.0
MAX_FILL_DEPTH_GAP_SECONDS = 3_600
DEFAULT_LATENCY_MS = 100
DEFAULT_QUEUE_AHEAD_FRACTION = 0.10
DEFAULT_IMPACT_BPS_AT_FULL_DEPTH = 2.0
DEFAULT_MIN_NOTIONAL_USDT = 10.0
DEFAULT_MIN_SIZE_BTC = 0.0001
DEFAULT_SIZE_STEP_BTC = 0.0001
DEFAULT_PRICE_TICK_USDT = 0.1
TARGET_DEPTH_INSTRUMENTS = {"BTCUSDT", "BTCUSDTSWAP"}
FILL_MAPPING_STATE_VERIFIED = "verified"
FILL_MAPPING_STATE_NO_GATE_ELIGIBLE_FILL = "no_gate_eligible_fill"
FILL_MAPPING_STATE_DEPTH_NOT_VISIBLE = "depth_not_visible"
FILL_MAPPING_STATE_MAPPING_LOGIC_FAILED = "mapping_logic_failed"
DEPTH_NOT_VISIBLE_MAPPING_STATUSES = {
    "no_visible_depth_at_or_before_fill",
    "nearest_depth_not_visible_by_fill_time",
    "nearest_visible_depth_too_stale",
}
DEPTH_INSTRUMENT_FIELDS = (
    "symbol",
    "venue_symbol",
    "instrument",
    "instrument_id",
    "instId",
    "inst_id",
    "pair",
    "contract",
    "contract_symbol",
)
DEPTH_SOURCE_FILES = (
    "order_book_depth.csv",
    "order_book_depth_aligned.csv",
    "order_book_depth_samples.csv",
)
EXACT_COMMITTED_MANIFEST_GIT_SPEC = re.compile(
    r"^[0-9a-f]{40}:[.]agent/data_manifests/[A-Za-z0-9._/-]+[.]json$"
)


class ImmutableEvidenceError(RuntimeError):
    """Raised when an official immutable evidence binding is not exact."""


@dataclass(frozen=True)
class DepthFillEvidenceDependencies:
    resolve_source: Callable[..., Mapping[str, Any]] = resolve_source


@dataclass(frozen=True)
class DepthLevel:
    side: str
    level: int
    price: float
    size: float
    visible_after: datetime


@dataclass(frozen=True)
class DepthFillModelParams:
    latency_ms: int = DEFAULT_LATENCY_MS
    queue_ahead_fraction: float = DEFAULT_QUEUE_AHEAD_FRACTION
    impact_bps_at_full_depth: float = DEFAULT_IMPACT_BPS_AT_FULL_DEPTH
    min_notional_usdt: float = DEFAULT_MIN_NOTIONAL_USDT
    min_size_btc: float = DEFAULT_MIN_SIZE_BTC
    size_step_btc: float = DEFAULT_SIZE_STEP_BTC
    price_tick_usdt: float = DEFAULT_PRICE_TICK_USDT

    def as_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "queue_ahead_fraction": self.queue_ahead_fraction,
            "impact_bps_at_full_depth": self.impact_bps_at_full_depth,
            "min_notional_usdt": self.min_notional_usdt,
            "min_size_btc": self.min_size_btc,
            "size_step_btc": self.size_step_btc,
            "price_tick_usdt": self.price_tick_usdt,
        }


def build_btc_depth_slippage_report(
    *,
    repo_root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    binance_vision_book_depth_report_path: Path = DEFAULT_BINANCE_VISION_BOOK_DEPTH_REPORT,
    strategy_fill_mapping_report_path: Path = DEFAULT_STRATEGY_FILL_MAPPING_REPORT,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_root = output_root if output_root.is_absolute() else root / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = selected_btc_perpetual_bundle_dir(root, root / config_path if not config_path.is_absolute() else config_path)
    depth_paths = [bundle_dir / name for name in DEPTH_SOURCE_FILES if bundle_dir and (bundle_dir / name).exists()]

    rows: list[dict[str, str]] = []
    for depth_path in depth_paths:
        rows.extend(_read_depth_rows(depth_path, root=root, as_of=generated))
    snapshots = _group_snapshots(rows)
    latest_ts = max(snapshots) if snapshots else None
    latest = snapshots.get(latest_ts, []) if latest_ts else []
    asks = sorted([row for row in latest if row.side == "ask"], key=lambda row: (row.price, row.level))
    bids = sorted([row for row in latest if row.side == "bid"], key=lambda row: (-row.price, row.level))
    quote = _quote_summary(asks=asks, bids=bids)
    simulations = _market_order_simulations(asks=asks, bids=bids, mid_price=quote.get("mid_price"))
    coverage = _coverage_summary(snapshots)
    positive_floor = _positive_slippage_floor(quote=quote, simulations=simulations)
    history_coverage_verified = (
        coverage["two_sided_snapshot_count"] >= MIN_HISTORY_SNAPSHOT_COUNT
        and coverage["two_sided_coverage_days"] >= MIN_HISTORY_COVERAGE_DAYS
        and coverage["two_sided_continuity_satisfied"] is True
    )
    selected_venue_time_aligned = bool(depth_paths) and coverage["two_sided_snapshot_count"] > 0
    fill_mapping = _read_json(
        strategy_fill_mapping_report_path
        if strategy_fill_mapping_report_path.is_absolute()
        else root / strategy_fill_mapping_report_path
    )
    strategy_fill_mapping_verified = _strategy_fill_mapping_verified(fill_mapping)
    history_verified = history_coverage_verified and strategy_fill_mapping_verified
    blockers: list[str] = []
    if not latest:
        blockers.append("btc_order_book_depth_snapshot_missing")
    if positive_floor is None:
        blockers.append("btc_positive_slippage_floor_missing")
    if not history_coverage_verified:
        blockers.append("btc_depth_aware_slippage_history_insufficient")
    if coverage["two_sided_snapshot_count"] >= MIN_HISTORY_SNAPSHOT_COUNT and coverage["two_sided_continuity_satisfied"] is not True:
        blockers.append("btc_depth_aware_slippage_history_sparse")
    if not strategy_fill_mapping_verified:
        if fill_mapping:
            blockers.extend(
                str(item) for item in fill_mapping.get("blockers", ["btc_depth_strategy_fill_mapping_unverified"]) if str(item)
            )
        else:
            blockers.append("btc_depth_strategy_fill_mapping_missing")
    binance_book_depth = _read_json(
        binance_vision_book_depth_report_path
        if binance_vision_book_depth_report_path.is_absolute()
        else root / binance_vision_book_depth_report_path
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "partial_diagnostic_only" if blockers else "verified",
        "decision": (
            "depth_snapshot_positive_floor_available_history_incomplete_no_paper_no_live"
            if positive_floor is not None and not history_verified
            else "depth_aware_slippage_history_verified_manual_review_required_no_auto_paper_no_live"
            if history_verified
            else "depth_slippage_evidence_missing_fail_closed_no_paper_no_live"
        ),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "depth_instrument_filter": {
            "accepted_normalized_instruments": sorted(TARGET_DEPTH_INSTRUMENTS),
            "requires_explicit_instrument_field": True,
        },
        "selected_bundle_dir": _portable_path(bundle_dir, root) if bundle_dir else None,
        "depth_source_paths": [_portable_path(path, root) for path in depth_paths],
        "depth_source_row_counts": _source_row_counts(rows),
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "snapshot_coverage": coverage,
        "latest_snapshot": {
            "timestamp": latest_ts,
            "ask_level_count": len(asks),
            "bid_level_count": len(bids),
            **quote,
        },
        "market_order_simulations": simulations,
        "positive_slippage_floor_bps": positive_floor,
        "positive_slippage_floor_method": (
            "max(observed_half_spread_or_depth_impact, 1.0 bps policy floor) from latest visible L2 snapshot"
            if positive_floor is not None
            else None
        ),
        "depth_snapshot_available": bool(latest),
        "depth_aware": False,
        "depth_aware_slippage_history_verified": history_verified,
        "selected_venue_depth_evidence": {
            "selected_venue": "okx_swap",
            "same_venue_as_execution_gate": True,
            "time_aligned_depth_history_present": selected_venue_time_aligned,
            "time_aligned_depth_history_verified": history_coverage_verified,
            "history_coverage_verified": history_coverage_verified,
            "strategy_fill_mapping_verified": strategy_fill_mapping_verified,
            "strategy_fill_mapping_report": _portable_path(
                strategy_fill_mapping_report_path
                if strategy_fill_mapping_report_path.is_absolute()
                else root / strategy_fill_mapping_report_path,
                root,
            ),
            "required_for_gate": {
                "min_two_sided_snapshot_count": MIN_HISTORY_SNAPSHOT_COUNT,
                "min_two_sided_coverage_days": MIN_HISTORY_COVERAGE_DAYS,
                "max_two_sided_gap_hours": MAX_HISTORY_GAP_HOURS,
                "strategy_fills_mapped_to_depth": True,
            },
            "current_gap": (
                "OKX L2/depth must be same-venue, time-aligned, broad enough, "
                "and explicitly mapped to strategy fills before it can clear the gate."
            ),
        },
        "free_public_cross_venue_depth_diagnostic": _cross_venue_depth_diagnostic(binance_book_depth),
        "history_requirements": {
            "min_snapshot_count": MIN_HISTORY_SNAPSHOT_COUNT,
            "min_coverage_days": MIN_HISTORY_COVERAGE_DAYS,
            "max_gap_hours": MAX_HISTORY_GAP_HOURS,
            "requires_two_sided_snapshots": True,
        },
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_endpoint_allowed": False,
            "private_endpoint_allowed": False,
            "withdraw_allowed": False,
        },
        "blockers": blockers,
    }
    _write_json(output_root / DEFAULT_REPORT_PATH.name, report)
    _write_text(output_root / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    return report


def build_btc_depth_slippage_fill_mapping_report(
    *,
    repo_root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    current_event_ledger_path: Path = DEFAULT_CURRENT_EVENT_LEDGER,
    drill_event_ledger_path: Path = DEFAULT_DRILL_EVENT_LEDGER,
    l2_batch_report_path: Path = DEFAULT_L2_BATCH_REPORT,
    generated_at_utc: datetime | None = None,
    data_version: str = "unpublished",
    run_id: str | None = None,
    source_head: str | None = None,
    model_params: DepthFillModelParams | None = None,
    immutable_manifest_verified: bool = False,
    data_steward_attested: bool = False,
    immutable_l2_manifest_git_specs: Sequence[str] | None = None,
    natural_fill_ledger_manifest_git_spec: str | None = None,
    shared_root: Path | None = None,
    dependencies: DepthFillEvidenceDependencies | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_root = output_root if output_root.is_absolute() else root / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    params = model_params or DepthFillModelParams()
    resolved_head = source_head or _git(["rev-parse", "HEAD"], cwd=root)
    resolved_run_id = run_id or f"btc-l2-depth-fill-{generated.strftime('%Y%m%dT%H%M%SZ')}"
    deps = dependencies or DepthFillEvidenceDependencies()
    strict_immutable = bool(immutable_l2_manifest_git_specs or natural_fill_ledger_manifest_git_spec)
    immutable_bindings: list[dict[str, Any]] = []
    natural_fill_ledger_sha256: str | None = None
    if strict_immutable:
        official = _resolve_official_depth_fill_inputs(
            repo_root=root,
            shared_root=(shared_root or _default_shared_root(root)).resolve(),
            immutable_l2_manifest_git_specs=immutable_l2_manifest_git_specs or (),
            natural_fill_ledger_manifest_git_spec=natural_fill_ledger_manifest_git_spec,
            resolver=deps.resolve_source,
        )
        bundle_dir = None
        depth_paths = list(official["depth_paths"])
        current_event_ledger_path = Path(official["natural_fill_ledger_path"])
        drill_event_ledger_path = root / ".immutable-evidence-no-diagnostic-ledger"
        immutable_bindings = list(official["bindings"])
        natural_fill_ledger_sha256 = str(official["natural_fill_ledger_sha256"])
        immutable_manifest_verified = True
        data_steward_attested = True
        data_version = "btc-depth-fill-pool-" + _stable_hash(
            {"source_bindings": immutable_bindings}
        )[:24]
    else:
        bundle_dir = selected_btc_perpetual_bundle_dir(
            root,
            root / config_path if not config_path.is_absolute() else config_path,
        )
        depth_paths = [
            bundle_dir / name
            for name in DEPTH_SOURCE_FILES
            if bundle_dir and (bundle_dir / name).exists()
        ]

    depth_rows: list[dict[str, str]] = []
    for depth_path in depth_paths:
        depth_rows.extend(_read_depth_rows(depth_path, root=root, as_of=generated))
    depth_integrity = _depth_integrity(depth_rows)
    snapshots = _snapshot_books(_group_snapshots(depth_rows))
    fills = _read_fill_events(
        root=root,
        current_event_ledger_path=current_event_ledger_path,
        drill_event_ledger_path=drill_event_ledger_path,
    )
    mapping_rows = [_map_fill_to_depth(fill, snapshots=snapshots, params=params) for fill in fills]
    summary = _fill_mapping_summary(mapping_rows=mapping_rows, fills=fills, snapshots=snapshots)
    summary["depth_integrity"] = depth_integrity
    state_detail = _fill_mapping_state(mapping_rows=mapping_rows, summary=summary)
    summary.update(state_detail)
    blockers = _fill_mapping_blockers(summary=summary, depth_paths=depth_paths)
    verified = not blockers
    evidence_prerequisite_blockers = []
    if not immutable_manifest_verified:
        evidence_prerequisite_blockers.append("immutable_snapshot_not_published")
    if not data_steward_attested:
        evidence_prerequisite_blockers.append("data_steward_attestation_required")
    if data_version in {"", "unpublished", "fixture"}:
        evidence_prerequisite_blockers.append("okx_timestamp_aligned_l2_manifest_not_published")
    promotion_evidence_ready = verified and not evidence_prerequisite_blockers
    input_paths = [*depth_paths, _resolve(root, current_event_ledger_path), _resolve(root, drill_event_ledger_path)]
    input_hashes = {
        _portable_path(path, root) or path.as_posix(): _file_sha256(path)
        for path in input_paths
        if path.exists() and path.is_file()
    }
    params_payload = params.as_dict()

    report_path = output_root / DEFAULT_STRATEGY_FILL_MAPPING_REPORT.name
    rows_path = output_root / DEFAULT_STRATEGY_FILL_MAPPING_ROWS.name
    report = {
        "schema_version": "btc_depth_slippage_fill_mapping_report_v2",
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "verified_diagnostic_only" if verified else "incomplete_research_only",
        "decision": (
            "strategy_fills_mapped_to_same_venue_okx_depth_manual_review_required_no_auto_paper_no_live"
            if verified
            else "strategy_fill_to_okx_depth_mapping_incomplete_fail_closed_no_paper_no_live"
        ),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "data_version": data_version,
        "run_id": resolved_run_id,
        "source_head": resolved_head,
        "immutable_inputs_verified": strict_immutable and immutable_manifest_verified and data_steward_attested,
        "immutable_l2_manifest_git_specs": list(immutable_l2_manifest_git_specs or ()),
        "natural_fill_ledger_manifest_git_spec": natural_fill_ledger_manifest_git_spec,
        "natural_fill_ledger_sha256": natural_fill_ledger_sha256,
        "immutable_source_bindings": immutable_bindings,
        "params": params_payload,
        "params_hash": _stable_hash(params_payload),
        "input_hashes": input_hashes,
        "evidence_class": "promotion_evidence" if promotion_evidence_ready else "fixture_or_diagnostic_only",
        "quality_checked": verified,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": promotion_evidence_ready,
        "depth_instrument_filter": {
            "accepted_normalized_instruments": sorted(TARGET_DEPTH_INSTRUMENTS),
            "requires_explicit_instrument_field": True,
        },
        "selected_bundle_dir": _portable_path(bundle_dir, root) if bundle_dir else None,
        "same_venue_as_execution_gate": True,
        "strategy_fill_mapping_verified": verified,
        "fill_mapping_state": summary["fill_mapping_state"],
        "fill_mapping_state_detail": state_detail,
        "mapped_fill_count": summary["mapped_gate_fill_count"],
        "max_fill_depth_gap_seconds": MAX_FILL_DEPTH_GAP_SECONDS,
        "depth_source_paths": [_portable_path(path, root) for path in depth_paths],
        "depth_source_row_counts": _source_row_counts(depth_rows),
        "input_event_ledgers": {
            "current": _portable_path(_resolve(root, current_event_ledger_path), root),
            "diagnostic_drill": _portable_path(_resolve(root, drill_event_ledger_path), root),
        },
        "summary": summary,
        "depth_integrity": depth_integrity,
        "mapping_rows": mapping_rows[:200],
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_endpoint_allowed": False,
            "private_endpoint_allowed": False,
            "withdraw_allowed": False,
        },
        "safety": {
            "promotion": False,
            "paper": False,
            "live": False,
            "private": False,
            "order": False,
            "real_order": False,
            "transfer": False,
            "withdraw": False,
        },
        "blockers": _dedupe([*blockers, *evidence_prerequisite_blockers]),
        "engineering_blockers": blockers,
        "evidence_prerequisite_blockers": evidence_prerequisite_blockers,
        "outputs": {
            "json": _portable_path(report_path, root),
            "rows_csv": _portable_path(rows_path, root),
        },
        "code_commit": resolved_head,
    }
    report["output_hash"] = _stable_hash(report)
    l2_batch = _read_json(_resolve(root, l2_batch_report_path))
    promotion_evaluation = evaluate_btc_okx_native_promotion_blockers(
        l2_batch_report=l2_batch,
        fill_mapping_report=report,
        current_head=resolved_head,
        now_utc=generated,
    )
    report["promotion_blocker_evaluation"] = promotion_evaluation
    report["promotion_blockers"] = promotion_evaluation["promotion_blockers"]
    report["output_hash"] = _stable_hash({key: value for key, value in report.items() if key != "output_hash"})
    _write_json(report_path, report)
    _write_fill_mapping_rows(rows_path, mapping_rows)
    return report


def _default_shared_root(repo_root: Path) -> Path:
    return repo_root.parent / "shared-data"


def _validate_exact_manifest_git_spec(value: str) -> None:
    lowered = value.lower()
    forbidden = ("latest", "staging", "*", "?", "[", ".csv", ".sqlite", ".db")
    if not EXACT_COMMITTED_MANIFEST_GIT_SPEC.fullmatch(value) or any(token in lowered for token in forbidden):
        raise ImmutableEvidenceError(f"exact_committed_manifest_git_spec_required:{value}")


def _resolve_official_depth_fill_inputs(
    *,
    repo_root: Path,
    shared_root: Path,
    immutable_l2_manifest_git_specs: Sequence[str],
    natural_fill_ledger_manifest_git_spec: str | None,
    resolver: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    if not immutable_l2_manifest_git_specs or not natural_fill_ledger_manifest_git_spec:
        raise ImmutableEvidenceError("immutable_l2_and_natural_fill_manifest_specs_required")
    specs = [*immutable_l2_manifest_git_specs, natural_fill_ledger_manifest_git_spec]
    if len(set(specs)) != len(specs):
        raise ImmutableEvidenceError("immutable_manifest_git_specs_must_be_unique")
    for spec in specs:
        _validate_exact_manifest_git_spec(spec)

    bindings: list[dict[str, Any]] = []
    physical: dict[str, tuple[Path, list[dict[str, Any]]]] = {}
    for spec in specs:
        binding = dict(
            resolver(
                repo_root=repo_root,
                shared_root=shared_root,
                manifest_git_spec=spec,
            )
        )
        manifest = _mapping(binding.get("_manifest"))
        valid = (
            binding.get("manifest_git_spec") == spec
            and binding.get("resolution_status") == "resolved_verified"
            and binding.get("full_file_hash_verified") is True
            and binding.get("fallback_used") is False
            and not binding.get("blockers")
            and _is_sha256(str(binding.get("manifest_blob_sha256") or ""))
            and _is_sha256(str(binding.get("aggregate_sha256") or ""))
        )
        if not valid:
            raise ImmutableEvidenceError("immutable_manifest_or_file_hash_verification_failed")
        resolved_root = binding.get("_resolved_root")
        if not isinstance(resolved_root, Path):
            raise ImmutableEvidenceError("immutable_manifest_physical_version_missing")
        members = _verify_manifest_members(resolved_root, manifest)
        if str(manifest.get("producer_role") or "") != "data_steward":
            raise ImmutableEvidenceError("data_steward_attestation_required")
        attestation_members = [
            row for row in members if "attestation" in str(row["path"]).lower()
        ]
        if not attestation_members:
            raise ImmutableEvidenceError("data_steward_attestation_required")
        bindings.append(
            {
                "manifest_git_spec": spec,
                "manifest_blob_sha256": str(binding["manifest_blob_sha256"]),
                "dataset_id": str(binding.get("dataset_id") or ""),
                "dataset_version": str(binding.get("dataset_version") or ""),
                "aggregate_sha256": str(binding["aggregate_sha256"]),
                "file_hashes": {str(row["path"]): str(row["sha256"]) for row in members},
                "data_steward_attestation_sha256": str(attestation_members[0]["sha256"]),
                "full_file_hash_verified": True,
                "fallback_used": False,
            }
        )
        physical[spec] = (resolved_root, members)

    depth_paths: list[Path] = []
    for spec in immutable_l2_manifest_git_specs:
        resolved_root, members = physical[spec]
        candidates = [
            resolved_root / str(row["path"])
            for row in members
            if _is_ordered_l2_member(str(row["path"]))
        ]
        if not candidates:
            raise ImmutableEvidenceError("ordered_l2_payload_missing_from_manifest")
        depth_paths.extend(candidates)

    fill_root, fill_members = physical[natural_fill_ledger_manifest_git_spec]
    fill_candidates = [
        fill_root / str(row["path"])
        for row in fill_members
        if _is_natural_fill_ledger_member(str(row["path"]))
    ]
    if len(fill_candidates) != 1:
        raise ImmutableEvidenceError("authoritative_natural_fill_ledger_member_not_unique")
    ledger = fill_candidates[0]
    return {
        "depth_paths": depth_paths,
        "natural_fill_ledger_path": ledger,
        "natural_fill_ledger_sha256": _file_sha256(ledger),
        "bindings": bindings,
    }


def _verify_manifest_members(root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_members = manifest.get("files")
    if not isinstance(raw_members, list) or not raw_members:
        raise ImmutableEvidenceError("immutable_manifest_files_missing")
    verified: list[dict[str, Any]] = []
    for raw in raw_members:
        row = _mapping(raw)
        relative = Path(str(row.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ImmutableEvidenceError("immutable_manifest_member_path_invalid")
        path = root / relative
        expected = str(row.get("sha256") or "")
        if not path.is_file() or not _is_sha256(expected) or _file_sha256(path) != expected:
            raise ImmutableEvidenceError("immutable_manifest_or_file_hash_verification_failed")
        if row.get("bytes") is not None and int(row["bytes"]) != path.stat().st_size:
            raise ImmutableEvidenceError("immutable_manifest_or_file_hash_verification_failed")
        verified.append({"path": relative.as_posix(), "sha256": expected})
    return verified


def _is_ordered_l2_member(value: str) -> bool:
    lowered = value.lower().replace("\\", "/")
    return (
        ("ordered-l2/" in lowered and lowered.endswith(".jsonl") and "attestation" not in lowered)
        or lowered.endswith("order_book_depth_aligned.csv")
        or lowered.endswith("order_book_depth.csv")
    )


def _is_natural_fill_ledger_member(value: str) -> bool:
    lowered = value.lower().replace("\\", "/")
    return (
        (lowered.endswith(".csv") or lowered.endswith(".jsonl"))
        and "fill" in lowered
        and "ledger" in lowered
        and "diagnostic" not in lowered
        and "drill" not in lowered
    )


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def render_summary_cn(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("snapshot_coverage"))
    latest = _mapping(report.get("latest_snapshot"))
    lines = [
        "# BTC 深度滑点诊断",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 最新盘口时间：`{latest.get('timestamp')}`",
        f"- 正滑点下限：`{report.get('positive_slippage_floor_bps')}` bps",
        f"- 快照数量：`{coverage.get('snapshot_count')}`，两边盘口快照：`{coverage.get('two_sided_snapshot_count')}`",
        f"- 历史深度滑点验证：`{report.get('depth_aware_slippage_history_verified')}`",
        "",
        "本报告只用于 research-only 成本证据补强。当前如果只有少量 L2 快照，只能证明 0 bps 滑点不合理，不能证明历史深度滑点模型已经可用于 paper/live。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 剩余缺口"])
        for blocker in report.get("blockers", []):
            lines.append(f"- `{blocker}`")
    return "\n".join(lines) + "\n"


def _read_depth_rows(path: Path | None, *, root: Path, as_of: datetime) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    if path.suffix.lower() == ".jsonl":
        return _read_ordered_l2_jsonl(path, root=root, as_of=as_of)
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not _depth_row_matches_target_instrument(row):
                continue
            available_at = _depth_row_available_at(row)
            if available_at is None or available_at > as_of:
                continue
            normalized = {str(key): str(value) for key, value in row.items()}
            normalized["_source_file"] = _portable_path(path, root) or path.as_posix()
            normalized["_visible_after_utc"] = available_at.isoformat()
            rows.append(normalized)
    return rows


def _read_ordered_l2_jsonl(path: Path, *, root: Path, as_of: datetime) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ImmutableEvidenceError(
                    f"ordered_l2_jsonl_invalid:{path.name}:{line_number}"
                ) from exc
            available = _parse_utc(payload.get("available_time"))
            event = _parse_utc(
                payload.get("event_time") or payload.get("snapshot_time")
            )
            if available is None or event is None or available > as_of:
                continue
            instrument = str(payload.get("instrument_id") or payload.get("symbol") or "")
            capture_sequence = str(payload.get("capture_sequence") or line_number)
            for side_name, side in (("bids", "bid"), ("asks", "ask")):
                levels = payload.get(side_name)
                if not isinstance(levels, list):
                    continue
                for index, level in enumerate(levels, start=1):
                    if not isinstance(level, list) or len(level) < 2:
                        continue
                    rows.append(
                        {
                            "timestamp": event.isoformat(),
                            "event_time": event.isoformat(),
                            "available_time": available.isoformat(),
                            "_visible_after_utc": max(event, available).isoformat(),
                            "exchange_ts": event.isoformat(),
                            "local_receive_ts": available.isoformat(),
                            "instrument_id": instrument,
                            "venue_symbol": instrument,
                            "symbol": instrument,
                            "side": side,
                            "level": str(index),
                            "price": str(level[0]),
                            "size": str(level[1]),
                            "capture_sequence": capture_sequence,
                            "seq_id": str(payload.get("seq_id") or ""),
                            "prev_seq_id": str(payload.get("prev_seq_id") or ""),
                            "_source_file": _portable_path(path, root) or path.name,
                            "source_record_id": f"{capture_sequence}:{side}:{index}",
                        }
                    )
    return rows


def _depth_row_available_at(row: Mapping[str, str]) -> datetime | None:
    """Return the earliest safe PIT visibility timestamp for a depth row."""

    candidates = [
        _parse_utc(row.get("available_time")),
        _parse_utc(row.get("local_receive_ts")),
        _parse_utc(row.get("event_time")),
        _parse_utc(row.get("timestamp")),
        _parse_utc(row.get("exchange_ts")),
    ]
    parsed = [candidate for candidate in candidates if candidate is not None]
    if not parsed:
        return None
    return max(parsed)


def _depth_row_matches_target_instrument(row: Mapping[str, str]) -> bool:
    values = [
        str(row.get(field) or "").strip()
        for field in DEPTH_INSTRUMENT_FIELDS
        if str(row.get(field) or "").strip()
    ]
    if not values:
        return False
    return all(_normalize_instrument(value) in TARGET_DEPTH_INSTRUMENTS for value in values)


def _normalize_instrument(value: str) -> str:
    return (
        value.upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )


def _cross_venue_depth_diagnostic(payload: Mapping[str, Any]) -> dict[str, Any]:
    interpretation = _mapping(payload.get("execution_gate_interpretation"))
    coverage = _mapping(payload.get("coverage"))
    return {
        "present": bool(payload),
        "source_provider": payload.get("source_provider"),
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "row_count": payload.get("row_count"),
        "coverage_days": coverage.get("coverage_days"),
        "sample_start": coverage.get("sample_start"),
        "sample_end": coverage.get("sample_end"),
        "free_public_depth_diagnostic_available": interpretation.get("free_public_depth_diagnostic_available"),
        "gate_eligible_for_selected_venue": interpretation.get("gate_eligible_for_selected_venue", False),
        "depth_aware_slippage_history_verified_for_selected_venue": interpretation.get(
            "depth_aware_slippage_history_verified_for_selected_venue", False
        ),
        "reason": interpretation.get(
            "reason",
            "missing Binance Vision diagnostic report or not applicable to selected OKX venue",
        ),
    }


def _strategy_fill_mapping_verified(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if payload.get("strategy_fill_mapping_verified") is True:
        return True
    if payload.get("depth_aware_slippage_history_verified") is True and payload.get("mapped_fill_count"):
        return True
    summary = _mapping(payload.get("summary"))
    return bool(
        summary.get("strategy_fill_mapping_verified") is True
        and _float(summary.get("mapped_fill_count")) not in {None, 0.0}
    )


def _group_snapshots(rows: Iterable[Mapping[str, str]]) -> dict[str, list[DepthLevel]]:
    snapshots: dict[str, list[DepthLevel]] = {}
    for row in rows:
        ts = str(row.get("timestamp") or row.get("exchange_ts") or row.get("event_time") or row.get("local_receive_ts") or "").strip()
        side = str(row.get("side") or "").strip().lower()
        price = _float(row.get("price"))
        size = _float(row.get("size"))
        level = int(_float(row.get("level")) or 0)
        visible_after = _parse_utc(row.get("_visible_after_utc")) or _parse_utc(ts)
        if (
            not ts
            or side not in {"ask", "bid"}
            or price is None
            or size is None
            or price <= 0.0
            or size <= 0.0
            or visible_after is None
        ):
            continue
        snapshots.setdefault(ts, []).append(
            DepthLevel(side=side, level=level, price=price, size=size, visible_after=visible_after)
        )
    return snapshots


def _source_row_counts(rows: Iterable[Mapping[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("_source_file") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _quote_summary(*, asks: list[DepthLevel], bids: list[DepthLevel]) -> dict[str, Any]:
    if not asks or not bids:
        return {
            "best_bid": None,
            "best_ask": None,
            "mid_price": None,
            "spread_bps": None,
            "ask_depth_usd": None,
            "bid_depth_usd": None,
        }
    best_ask = asks[0].price
    best_bid = bids[0].price
    mid = (best_ask + best_bid) / 2.0
    return {
        "best_bid": round(best_bid, 8),
        "best_ask": round(best_ask, 8),
        "mid_price": round(mid, 8),
        "spread_bps": round((best_ask - best_bid) / mid * 10_000.0, 6),
        "ask_depth_usd": round(sum(row.price * row.size for row in asks), 6),
        "bid_depth_usd": round(sum(row.price * row.size for row in bids), 6),
    }


def _market_order_simulations(*, asks: list[DepthLevel], bids: list[DepthLevel], mid_price: object) -> list[dict[str, Any]]:
    mid = _float(mid_price)
    result: list[dict[str, Any]] = []
    for notional in ORDER_NOTIONAL_USD:
        buy = _simulate_market_order(levels=asks, side="buy", notional_usd=notional, mid_price=mid)
        sell = _simulate_market_order(levels=bids, side="sell", notional_usd=notional, mid_price=mid)
        result.extend([buy, sell])
    return result


def _simulate_market_order(
    *,
    levels: list[DepthLevel],
    side: str,
    notional_usd: float,
    mid_price: float | None,
) -> dict[str, Any]:
    remaining = notional_usd
    spent = 0.0
    qty = 0.0
    levels_used = 0
    for level in levels:
        level_notional = level.price * level.size
        take_notional = min(remaining, level_notional)
        if take_notional <= 0.0:
            continue
        spent += take_notional
        qty += take_notional / level.price
        remaining -= take_notional
        levels_used += 1
        if remaining <= 1e-9:
            break
    complete = remaining <= max(1e-6, notional_usd * 1e-9) and qty > 0.0 and mid_price is not None and mid_price > 0.0
    vwap = spent / qty if qty > 0.0 else None
    slippage_bps = None
    if complete and vwap is not None:
        if side == "buy":
            slippage_bps = max(0.0, (vwap - mid_price) / mid_price * 10_000.0)
        else:
            slippage_bps = max(0.0, (mid_price - vwap) / mid_price * 10_000.0)
    return {
        "side": side,
        "notional_usd": notional_usd,
        "complete": complete,
        "levels_used": levels_used,
        "filled_notional_usd": round(spent, 6),
        "vwap": round(vwap, 8) if vwap is not None else None,
        "slippage_bps_vs_mid": round(slippage_bps, 6) if slippage_bps is not None else None,
    }


def _simulate_depth_fill(
    *,
    levels: list[DepthLevel],
    side: str,
    notional_usd: float,
    mid_price: float | None,
    params: DepthFillModelParams,
) -> dict[str, Any]:
    queue_fraction = min(1.0, max(0.0, params.queue_ahead_fraction))
    remaining = max(0.0, notional_usd)
    spent = 0.0
    qty = 0.0
    levels_used = 0
    available_notional = sum(max(0.0, row.price * row.size * (1.0 - queue_fraction)) for row in levels)
    for level in levels:
        effective_size = max(0.0, level.size * (1.0 - queue_fraction))
        level_notional = max(0.0, level.price * effective_size)
        take_notional = min(remaining, level_notional)
        if take_notional <= 0.0:
            continue
        spent += take_notional
        qty += take_notional / level.price
        remaining -= take_notional
        levels_used += 1
        if remaining <= max(1e-6, notional_usd * 1e-9):
            break
    complete = remaining <= max(1e-6, notional_usd * 1e-9) and qty > 0.0
    vwap = spent / qty if qty > 0.0 else None
    participation = min(1.0, spent / available_notional) if available_notional > 0.0 else 0.0
    impact_bps = params.impact_bps_at_full_depth * participation if spent > 0.0 else 0.0
    spread_cost_bps = None
    slippage_bps = None
    if mid_price is not None and mid_price > 0.0 and vwap is not None:
        raw_bps = (
            (vwap - mid_price) / mid_price * 10_000.0
            if side == "buy"
            else (mid_price - vwap) / mid_price * 10_000.0
        )
        spread_cost_bps = max(0.0, raw_bps)
        slippage_bps = max(0.0, raw_bps + impact_bps)
    return {
        "side": side,
        "notional_usd": notional_usd,
        "complete": complete,
        "partial_fill": spent > 0.0 and not complete,
        "levels_used": levels_used,
        "filled_notional_usd": round(spent, 6),
        "unfilled_notional_usd": round(max(0.0, remaining), 6),
        "vwap": round(vwap, 8) if vwap is not None else None,
        "slippage_bps_vs_mid": round(slippage_bps, 6) if slippage_bps is not None else None,
        "spread_cost_bps": round(spread_cost_bps, 6) if spread_cost_bps is not None else None,
        "market_impact_bps": round(impact_bps, 6),
        "delay_cost_bps": round(max(0, params.latency_ms) / 1_000.0 * 0.01, 6),
        "queue_ahead_fraction": queue_fraction,
        "available_notional_after_queue_usd": round(available_notional, 6),
    }


def _venue_filter_status(
    *,
    notional: float,
    quantity: float | None,
    limit_price: float | None,
    params: DepthFillModelParams,
) -> str:
    if notional < params.min_notional_usdt:
        return "venue_filter_min_notional_rejected"
    if quantity is not None and quantity > 0.0:
        if quantity < params.min_size_btc:
            return "venue_filter_min_size_rejected"
        if not _multiple_of_step(quantity, params.size_step_btc):
            return "venue_filter_size_step_rejected"
    if limit_price is not None and limit_price > 0.0 and not _multiple_of_step(limit_price, params.price_tick_usdt):
        return "venue_filter_price_tick_rejected"
    return "pass"


def _multiple_of_step(value: float, step: float) -> bool:
    if step <= 0.0:
        return False
    units = value / step
    return abs(units - round(units)) <= 1e-8


def _coverage_summary(snapshots: Mapping[str, list[DepthLevel]]) -> dict[str, Any]:
    timestamps = sorted(snapshots)
    parsed = [_parse_utc(ts) for ts in timestamps]
    parsed = [ts for ts in parsed if ts is not None]
    coverage_days = 0.0
    if len(parsed) >= 2:
        coverage_days = (max(parsed) - min(parsed)).total_seconds() / 86_400.0
    two_sided = 0
    two_sided_timestamps: list[str] = []
    for timestamp, rows in snapshots.items():
        sides = {row.side for row in rows}
        if {"ask", "bid"}.issubset(sides):
            two_sided += 1
            two_sided_timestamps.append(timestamp)
    two_sided_parsed = [_parse_utc(ts) for ts in two_sided_timestamps]
    two_sided_parsed = [ts for ts in two_sided_parsed if ts is not None]
    two_sided_coverage_days = 0.0
    max_two_sided_gap_hours = None
    if len(two_sided_parsed) >= 2:
        two_sided_coverage_days = (max(two_sided_parsed) - min(two_sided_parsed)).total_seconds() / 86_400.0
        max_two_sided_gap_hours = max(
            (right - left).total_seconds() / 3_600.0
            for left, right in zip(sorted(two_sided_parsed), sorted(two_sided_parsed)[1:])
        )
    continuity_satisfied = (
        max_two_sided_gap_hours is not None
        and max_two_sided_gap_hours <= MAX_HISTORY_GAP_HOURS
    )
    return {
        "snapshot_count": len(timestamps),
        "two_sided_snapshot_count": two_sided,
        "sample_start": min(timestamps) if timestamps else None,
        "sample_end": max(timestamps) if timestamps else None,
        "coverage_days": round(coverage_days, 6),
        "two_sided_sample_start": min(two_sided_timestamps) if two_sided_timestamps else None,
        "two_sided_sample_end": max(two_sided_timestamps) if two_sided_timestamps else None,
        "two_sided_coverage_days": round(two_sided_coverage_days, 6),
        "max_two_sided_gap_hours": round(max_two_sided_gap_hours, 6) if max_two_sided_gap_hours is not None else None,
        "max_allowed_two_sided_gap_hours": MAX_HISTORY_GAP_HOURS,
        "two_sided_continuity_satisfied": continuity_satisfied,
    }


def _depth_integrity(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    observations: list[tuple[int | None, datetime | None]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        sequence_text = str(
            row.get("capture_sequence")
            or row.get("sequence")
            or row.get("seq")
            or row.get("update_id")
            or ""
        ).strip()
        timestamp_text = str(
            row.get("exchange_ts")
            or row.get("event_time")
            or row.get("timestamp")
            or ""
        ).strip()
        key = (sequence_text, timestamp_text)
        if key in seen:
            continue
        seen.add(key)
        try:
            sequence = int(sequence_text) if sequence_text else None
        except ValueError:
            sequence = None
        observations.append((sequence, _parse_utc(timestamp_text)))
    sequence_gap_count = 0
    out_of_order_count = 0
    previous_sequence: int | None = None
    previous_time: datetime | None = None
    for sequence, timestamp in observations:
        if previous_sequence is not None and sequence is not None:
            if sequence < previous_sequence:
                out_of_order_count += 1
            elif sequence > previous_sequence + 1:
                sequence_gap_count += 1
        if previous_time is not None and timestamp is not None and timestamp < previous_time:
            out_of_order_count += 1
        if sequence is not None:
            previous_sequence = sequence
        if timestamp is not None:
            previous_time = timestamp
    grouped = _group_snapshots(rows)
    one_sided_snapshot_count = sum(
        1 for levels in grouped.values() if {level.side for level in levels} != {"bid", "ask"}
    )
    zero_liquidity_level_count = sum(
        1 for row in rows if (_float(row.get("size")) is not None and float(row.get("size") or 0.0) <= 0.0)
    )
    return {
        "observation_count": len(observations),
        "sequence_gap_count": sequence_gap_count,
        "out_of_order_count": out_of_order_count,
        "one_sided_snapshot_count": one_sided_snapshot_count,
        "zero_liquidity_level_count": zero_liquidity_level_count,
        "sequence_checked": any(sequence is not None for sequence, _ in observations),
        "event_time_checked": any(timestamp is not None for _, timestamp in observations),
        "valid_for_mapping": (
            sequence_gap_count == 0
            and out_of_order_count == 0
            and one_sided_snapshot_count == 0
            and zero_liquidity_level_count == 0
        ),
    }


def _snapshot_books(snapshots: Mapping[str, list[DepthLevel]]) -> list[dict[str, Any]]:
    books: list[dict[str, Any]] = []
    for timestamp, rows in snapshots.items():
        parsed = _parse_utc(timestamp)
        if parsed is None:
            continue
        asks = sorted([row for row in rows if row.side == "ask"], key=lambda row: (row.price, row.level))
        bids = sorted([row for row in rows if row.side == "bid"], key=lambda row: (-row.price, row.level))
        if not asks or not bids:
            continue
        visible_after = max(row.visible_after for row in rows)
        quote = _quote_summary(asks=asks, bids=bids)
        books.append(
            {
                "timestamp": timestamp,
                "parsed": parsed,
                "visible_after": visible_after.isoformat(),
                "parsed_visible_after": visible_after,
                "asks": asks,
                "bids": bids,
                "quote": quote,
            }
        )
    books.sort(key=lambda item: item["parsed"])
    return books


def _read_fill_events(
    *,
    root: Path,
    current_event_ledger_path: Path,
    drill_event_ledger_path: Path,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path, ledger_kind in (
        (_resolve(root, current_event_ledger_path), "current"),
        (_resolve(root, drill_event_ledger_path), "diagnostic_drill"),
    ):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows: Iterable[Mapping[str, Any]]
            if path.suffix.lower() == ".jsonl":
                rows = (
                    json.loads(line)
                    for line in handle
                    if line.strip()
                )
            else:
                rows = csv.DictReader(handle)
            for row in rows:
                if str(row.get("event_type") or "").strip() != "simulated_fill":
                    continue
                event_time = _parse_utc(row.get("event_time"))
                if event_time is None:
                    continue
                diagnostic = _bool(row.get("diagnostic_drill_only")) or ledger_kind == "diagnostic_drill"
                gate_eligible = (not diagnostic) and _bool(row.get("paper_runtime_gate_eligible"))
                notional = _float(row.get("notional_usdt"))
                side = str(row.get("side") or "").strip().lower()
                if notional is None or notional <= 0.0 or side not in {"long", "short"}:
                    continue
                events.append(
                    {
                        "ledger_kind": ledger_kind,
                        "ledger_path": _portable_path(path, root),
                        "event_id": row.get("event_id"),
                        "event_time": event_time,
                        "event_time_text": event_time.isoformat(),
                        "strategy_line": row.get("strategy_line"),
                        "candidate_id": row.get("candidate_id"),
                        "decision_time": row.get("decision_time"),
                        "order_created_time": row.get("order_created_time"),
                        "side": side,
                        "order_side": "buy" if side == "long" else "sell",
                        "notional_usdt": notional,
                        "quantity_btc": _float(row.get("quantity_btc")),
                        "limit_price": _float(row.get("limit_price")),
                        "diagnostic_drill_only": diagnostic,
                        "paper_runtime_gate_eligible": gate_eligible,
                    }
                )
    events.sort(key=lambda item: item["event_time"])
    return events


def _map_fill_to_depth(
    fill: Mapping[str, Any],
    *,
    snapshots: list[Mapping[str, Any]],
    params: DepthFillModelParams,
) -> dict[str, Any]:
    event_time = fill.get("event_time")
    order_created_time = _parse_utc(fill.get("order_created_time"))
    arrival_time = (
        order_created_time + timedelta(milliseconds=max(0, params.latency_ms))
        if order_created_time is not None
        else event_time
    )
    base = {
        "ledger_kind": fill.get("ledger_kind"),
        "event_id": fill.get("event_id"),
        "strategy_line": fill.get("strategy_line"),
        "candidate_id": fill.get("candidate_id"),
        "decision_time": fill.get("decision_time"),
        "order_created_time": fill.get("order_created_time"),
        "arrival_time": arrival_time.isoformat() if isinstance(arrival_time, datetime) else None,
        "fill_time": fill.get("event_time_text"),
        "side": fill.get("side"),
        "order_side": fill.get("order_side"),
        "notional_usdt": _round_float(fill.get("notional_usdt")),
        "diagnostic_drill_only": bool(fill.get("diagnostic_drill_only")),
        "paper_runtime_gate_eligible": bool(fill.get("paper_runtime_gate_eligible")),
        "mapped": False,
        "mapping_status": "unmapped",
        "mapping_gap_seconds": None,
        "depth_timestamp": None,
        "depth_visible_after": None,
        "best_bid": None,
        "best_ask": None,
        "mid_price": None,
        "slippage_bps_vs_mid": None,
        "levels_used": None,
        "complete": False,
        "partial_fill": False,
        "filled_notional_usdt": 0.0,
        "unfilled_notional_usdt": _round_float(fill.get("notional_usdt")) or 0.0,
        "queue_ahead_fraction": params.queue_ahead_fraction,
        "latency_ms": params.latency_ms,
        "market_impact_bps": None,
        "spread_cost_bps": None,
        "delay_cost_bps": None,
        "venue_filter_status": "not_checked",
    }
    if not isinstance(event_time, datetime):
        base["mapping_status"] = "fill_time_missing"
        return base
    if not isinstance(arrival_time, datetime) or arrival_time > event_time:
        base["mapping_status"] = "arrival_after_fill"
        return base
    quantity = _float(fill.get("quantity_btc"))
    notional = float(fill.get("notional_usdt") or 0.0)
    venue_filter_status = _venue_filter_status(
        notional=notional,
        quantity=quantity,
        limit_price=_float(fill.get("limit_price")),
        params=params,
    )
    base["venue_filter_status"] = venue_filter_status
    if venue_filter_status != "pass":
        base["mapping_status"] = venue_filter_status
        return base
    timestamp_eligible = [snapshot for snapshot in snapshots if snapshot["parsed"] <= arrival_time]
    if not timestamp_eligible:
        base["mapping_status"] = "no_visible_depth_at_or_before_fill"
        return base
    eligible = [
        snapshot
        for snapshot in timestamp_eligible
        if snapshot.get("parsed_visible_after") is not None and snapshot["parsed_visible_after"] <= arrival_time
    ]
    if not eligible:
        snapshot = timestamp_eligible[-1]
        base["mapping_status"] = "nearest_depth_not_visible_by_fill_time"
        base["depth_timestamp"] = snapshot["timestamp"]
        base["depth_visible_after"] = snapshot.get("visible_after")
        return base
    snapshot = eligible[-1]
    gap_seconds = (arrival_time - snapshot["parsed"]).total_seconds()
    if gap_seconds > MAX_FILL_DEPTH_GAP_SECONDS:
        base["mapping_status"] = "nearest_visible_depth_too_stale"
        base["mapping_gap_seconds"] = round(gap_seconds, 6)
        base["depth_timestamp"] = snapshot["timestamp"]
        base["depth_visible_after"] = snapshot.get("visible_after")
        return base
    order_side = str(fill.get("order_side") or "")
    levels = snapshot["asks"] if order_side == "buy" else snapshot["bids"]
    sim = _simulate_depth_fill(
        levels=levels,
        side=order_side,
        notional_usd=notional,
        mid_price=_float(snapshot["quote"].get("mid_price")),
        params=params,
    )
    quote = _mapping(snapshot["quote"])
    base.update(
        {
            "mapped": bool(sim.get("complete")),
            "mapping_status": (
                "mapped"
                if sim.get("complete")
                else "partial_fill"
                if sim.get("filled_notional_usd", 0.0) > 0.0
                else "zero_liquidity"
            ),
            "mapping_gap_seconds": round(gap_seconds, 6),
            "depth_timestamp": snapshot["timestamp"],
            "depth_visible_after": snapshot.get("visible_after"),
            "best_bid": quote.get("best_bid"),
            "best_ask": quote.get("best_ask"),
            "mid_price": quote.get("mid_price"),
            "slippage_bps_vs_mid": sim.get("slippage_bps_vs_mid"),
            "levels_used": sim.get("levels_used"),
            "complete": bool(sim.get("complete")),
            "partial_fill": bool(sim.get("partial_fill")),
            "filled_notional_usdt": sim.get("filled_notional_usd"),
            "unfilled_notional_usdt": sim.get("unfilled_notional_usd"),
            "market_impact_bps": sim.get("market_impact_bps"),
            "spread_cost_bps": sim.get("spread_cost_bps"),
            "delay_cost_bps": sim.get("delay_cost_bps"),
        }
    )
    return base


def _fill_mapping_summary(
    *,
    mapping_rows: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    gate_rows = [row for row in mapping_rows if row.get("paper_runtime_gate_eligible") is True]
    mapped_gate_rows = [row for row in gate_rows if row.get("mapped") is True]
    mapped_rows = [row for row in mapping_rows if row.get("mapped") is True]
    gaps = [_float(row.get("mapping_gap_seconds")) for row in mapped_rows]
    gaps = [gap for gap in gaps if gap is not None]
    slippage = [_float(row.get("slippage_bps_vs_mid")) for row in mapped_rows]
    slippage = [value for value in slippage if value is not None]
    return {
        "fill_count": len(fills),
        "gate_fill_count": len(gate_rows),
        "diagnostic_fill_count": sum(1 for row in mapping_rows if row.get("diagnostic_drill_only") is True),
        "mapped_fill_count": len(mapped_rows),
        "partial_fill_count": sum(1 for row in mapping_rows if row.get("partial_fill") is True),
        "zero_liquidity_count": sum(1 for row in mapping_rows if row.get("mapping_status") == "zero_liquidity"),
        "unfilled_notional_usdt": round(
            sum(_float(row.get("unfilled_notional_usdt")) or 0.0 for row in mapping_rows),
            6,
        ),
        "mapped_gate_fill_count": len(mapped_gate_rows),
        "unmapped_gate_fill_count": len(gate_rows) - len(mapped_gate_rows),
        "depth_snapshot_count_for_mapping": len(snapshots),
        "max_mapping_gap_seconds": round(max(gaps), 6) if gaps else None,
        "median_mapping_gap_seconds": _median(gaps),
        "max_slippage_bps_vs_mid": round(max(slippage), 6) if slippage else None,
        "gate_fill_mapping_coverage": round(len(mapped_gate_rows) / len(gate_rows), 6) if gate_rows else 0.0,
        "paper_runtime_gate_eligible": bool(gate_rows),
        "strategy_fill_mapping_verified": bool(gate_rows) and len(mapped_gate_rows) == len(gate_rows),
        "mapping_status_counts": _count_values(row.get("mapping_status") for row in mapping_rows),
    }


def _fill_mapping_state(
    *,
    mapping_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    gate_rows = [row for row in mapping_rows if row.get("paper_runtime_gate_eligible") is True]
    mapped_gate_rows = [row for row in gate_rows if row.get("mapped") is True]
    unmapped_gate_rows = [row for row in gate_rows if row.get("mapped") is not True]
    depth_not_visible_rows = [
        row for row in unmapped_gate_rows if str(row.get("mapping_status") or "") in DEPTH_NOT_VISIBLE_MAPPING_STATUSES
    ]
    mapping_logic_failed_rows = [
        row for row in unmapped_gate_rows if str(row.get("mapping_status") or "") not in DEPTH_NOT_VISIBLE_MAPPING_STATUSES
    ]
    gate_depth_visible_count = len(gate_rows) - len(depth_not_visible_rows)
    if not gate_rows:
        state = FILL_MAPPING_STATE_NO_GATE_ELIGIBLE_FILL
        blocker = "btc_depth_strategy_fill_mapping_state_no_gate_eligible_fill"
        explanation = (
            "diagnostic fills may exist, but none are eligible for the promotion gate; "
            "this is sample insufficiency, not mapping logic failure."
        )
    elif not unmapped_gate_rows:
        state = FILL_MAPPING_STATE_VERIFIED
        blocker = None
        explanation = "all gate-eligible fills are mapped to visible depth."
    elif mapping_logic_failed_rows:
        state = FILL_MAPPING_STATE_MAPPING_LOGIC_FAILED
        blocker = "btc_depth_strategy_fill_mapping_state_mapping_logic_failed"
        explanation = (
            "gate-eligible fills and visible depth exist, but at least one fill did not map cleanly; "
            "review mapping logic, not just sample availability."
        )
    else:
        state = FILL_MAPPING_STATE_DEPTH_NOT_VISIBLE
        blocker = "btc_depth_strategy_fill_mapping_state_depth_not_visible"
        explanation = (
            "gate-eligible fills exist, but visible same-venue depth is missing, future-only, or too stale "
            "at the fill time."
        )
    return {
        "fill_mapping_state": state,
        "fill_mapping_state_blocker": blocker,
        "fill_mapping_state_explanation": explanation,
        "gate_depth_visible_count": gate_depth_visible_count,
        "gate_depth_not_visible_count": len(depth_not_visible_rows),
        "gate_mapping_logic_failure_count": len(mapping_logic_failed_rows),
        "gate_mapped_fill_count_for_state": len(mapped_gate_rows),
        "gate_unmapped_fill_count_for_state": len(unmapped_gate_rows),
        "diagnostic_fill_only_state": bool(summary.get("diagnostic_fill_count", 0)) and not gate_rows,
    }


def _fill_mapping_blockers(*, summary: Mapping[str, Any], depth_paths: Sequence[Path]) -> list[str]:
    blockers: list[str] = []
    if not depth_paths:
        blockers.append("btc_depth_strategy_fill_mapping_depth_source_missing")
    if summary.get("depth_snapshot_count_for_mapping", 0) == 0:
        blockers.append("btc_depth_strategy_fill_mapping_no_two_sided_depth_snapshots")
    state_blocker = summary.get("fill_mapping_state_blocker")
    if state_blocker:
        blockers.append(str(state_blocker))
    if summary.get("fill_mapping_state") == FILL_MAPPING_STATE_NO_GATE_ELIGIBLE_FILL:
        blockers.append("btc_depth_strategy_fill_mapping_no_gate_eligible_strategy_fills")
    if summary.get("strategy_fill_mapping_verified") is not True:
        blockers.append("btc_depth_strategy_fill_mapping_unverified")
    integrity = _mapping(summary.get("depth_integrity"))
    if _float(integrity.get("sequence_gap_count")):
        blockers.append("btc_depth_strategy_fill_mapping_sequence_gap")
    if _float(integrity.get("out_of_order_count")):
        blockers.append("btc_depth_strategy_fill_mapping_out_of_order")
    if _float(integrity.get("one_sided_snapshot_count")):
        blockers.append("btc_depth_strategy_fill_mapping_one_sided_book")
    if _float(integrity.get("zero_liquidity_level_count")):
        blockers.append("btc_depth_strategy_fill_mapping_zero_liquidity")
    return _dedupe(blockers)


def _write_fill_mapping_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "ledger_kind",
        "event_id",
        "strategy_line",
        "candidate_id",
        "decision_time",
        "order_created_time",
        "arrival_time",
        "fill_time",
        "side",
        "order_side",
        "notional_usdt",
        "diagnostic_drill_only",
        "paper_runtime_gate_eligible",
        "mapped",
        "mapping_status",
        "mapping_gap_seconds",
        "depth_timestamp",
        "depth_visible_after",
        "best_bid",
        "best_ask",
        "mid_price",
        "slippage_bps_vs_mid",
        "levels_used",
        "complete",
        "partial_fill",
        "filled_notional_usdt",
        "unfilled_notional_usdt",
        "queue_ahead_fraction",
        "latency_ms",
        "market_impact_bps",
        "spread_cost_bps",
        "delay_cost_bps",
        "venue_filter_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _positive_slippage_floor(*, quote: Mapping[str, Any], simulations: list[Mapping[str, Any]]) -> float | None:
    observed = [_float(quote.get("spread_bps"))]
    observed.extend(_float(row.get("slippage_bps_vs_mid")) for row in simulations if row.get("complete") is True)
    values = [value for value in observed if value is not None and value >= 0.0]
    if not values:
        return None
    return round(max(MIN_POSITIVE_SLIPPAGE_FLOOR_BPS, max(values)), 6)


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 6)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 6)


def _count_values(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _round_float(value: object, digits: int = 8) -> float | None:
    number = _float(value)
    return round(number, digits) if number is not None else None


def _csv_value(value: object) -> object:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _portable_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def render_summary_cn(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("snapshot_coverage"))
    latest = _mapping(report.get("latest_snapshot"))
    cross_venue = _mapping(report.get("free_public_cross_venue_depth_diagnostic"))
    lines = [
        "# BTC 深度滑点诊断",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 最新 OKX 盘口时间：`{latest.get('timestamp')}`",
        f"- 正滑点下限：`{report.get('positive_slippage_floor_bps')}` bps",
        f"- OKX 快照数量：`{coverage.get('snapshot_count')}`，两边盘口快照：`{coverage.get('two_sided_snapshot_count')}`",
        f"- OKX 历史深度滑点验证：`{report.get('depth_aware_slippage_history_verified')}`",
        f"- Binance Vision 免费跨交易所深度诊断：`{cross_venue.get('status')}`，可替代 OKX 门禁：`{cross_venue.get('gate_eligible_for_selected_venue')}`",
        "",
        "本报告只用于 research-only 成本证据补强。少量 OKX L2 快照可以证明 0 bps 滑点不合理，但不能证明历史深度滑点模型已经可用于 paper/live。",
        "Binance Vision bookDepth 是免费公开的跨交易所聚合深度诊断，不是 OKX 逐档盘口，也不是 paper fill replay，因此不能解除 OKX 深度滑点门禁。",
    ]
    if report.get("blockers"):
        lines.extend(["", "## 剩余缺口"])
        lines.extend(f"- `{blocker}`" for blocker in report.get("blockers", []))
    return "\n".join(lines) + "\n"
