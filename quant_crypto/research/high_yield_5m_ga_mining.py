from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tools.agent_governance import shared_data
from quant_crypto.data import dataready_consumer

from quant_crypto.research.intraday_ga_strategy_mining import (
    FoldSpec,
    build_walk_forward_folds,
    load_data_manifest,
    load_manifest_bounded_market_frame,
)


SCHEMA_VERSION = "btc_high_yield_5m_ga_mining_v2"
ENGINE_VERSION = "high_yield_donchian_5m_ga_v2"
ORIGIN_STRATEGY_ID = "high_yield_donchian_v2"
ORIGIN_CANDIDATE_ID = "hy_v2_donchian_w240_d50_200_cd12_vt120_max2p5_dd25_liq1200_trendoff"
ORIGIN_BASE_VARIANT_ID = "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone"

DEFAULT_SELECTOR_PATH = Path(".agent/runtime_manifests/btc-market-data-v1.json")
DEFAULT_MARKET_DB: Path | None = None
DEFAULT_MANIFEST: Path | None = None
LEGACY_MARKET_DB = Path("data/market_data.sqlite")
LEGACY_MANIFEST = Path(
    "data/manifests/qs-sqlite-BTCUSDT-5m-20240101T000000-bd0200707eb9.json"
)
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_high_yield_5m_ga_mining/latest")
DEFAULT_SEED = 20260826
FROZEN_HOLDOUT_LOCK_SCHEMA_VERSION = "btc_high_yield_5m_frozen_holdout_lock_v1"
DEFAULT_EXPERIMENT_ID = "btc-high-yield-5m-ga"
MIN_UNSEEN_HOLDOUT_ROWS = 30 * 24 * 12

RESEARCH_ONLY_SELECTOR_BLOCKERS = frozenset(
    {
        "btc_execution_latency_model_missing",
        "btc_queue_model_missing",
        "btc_kline_dataready_not_promotion_evidence",
    }
)

ENTRY_WINDOWS = (24, 48, 72, 96, 144, 288)
EXIT_RATIOS = (0.25, 0.5, 0.75)
ATR_WINDOWS = (14, 20, 28, 48)
ATR_MULTS = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
COOLDOWN_BARS = (0, 6, 12, 24, 48)
FAILED_BREAKOUT_BARS = (0, 3, 6, 12)
BREAKOUT_BUFFER_ATR = (0.0, 0.1, 0.25, 0.5)
REGIME_PAIRS = ((288, 1152), (576, 2304), (864, 3456), (1440, 5760))
VOLATILITY_WINDOWS = (288, 576, 1152, 2016)
TARGET_VOLATILITY_PCT = (40.0, 60.0, 90.0, 120.0)
MAX_LEVERAGES = (1.0, 1.5, 2.0, 2.5)
DRAWDOWN_GATES_PCT = (10.0, 15.0, 20.0, 25.0)

ANNUAL_5M_BARS = 365.0 * 24.0 * 12.0
MIN_SELECTION_TRADES_PER_DAY = 0.35
MAX_SELECTION_TRADES_PER_DAY = 12.0
MIN_SELECTION_EXPOSURE = 0.01
MAX_SELECTION_EXPOSURE = 0.90


class HighYield5mGAMiningError(ValueError):
    pass


def load_committed_5m_market_frame(
    *,
    selector_path: Path = DEFAULT_SELECTOR_PATH,
    repo_root: Path | None = None,
    shared_root: Path | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Resolve and load the current immutable 5m research dataset.

    The selector and dataset manifest are read from the committed ``HEAD``
    object rather than from the worktree.  This deliberately has no SQLite or
    network fallback: a stale/mutated selector is a data-binding failure.
    """
    root = (repo_root or Path.cwd()).resolve()
    current_head = _git_commit_hash(root)
    if not _is_sha1(current_head):
        raise HighYield5mGAMiningError("high_yield_5m_selector_commit_unavailable")

    selector_rel = _repo_relative_path(selector_path, root)
    if selector_rel.as_posix() != DEFAULT_SELECTOR_PATH.as_posix():
        raise HighYield5mGAMiningError("high_yield_5m_selector_path_not_allowlisted")
    selector_spec = f"{current_head}:{selector_rel.as_posix()}"
    selector_raw = _git_show_bytes(root, selector_spec, "selector")
    selector_sha256 = hashlib.sha256(selector_raw).hexdigest()
    selector = _parse_json_mapping(selector_raw, "selector")
    publication = _validate_selector(selector)

    manifest_path = str(publication["manifest_path"])
    manifest_spec = f"{current_head}:{manifest_path}"
    manifest_raw = _git_show_bytes(root, manifest_spec, "manifest")
    manifest_git_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_git_sha256 != str(publication["manifest_sha256"]):
        raise HighYield5mGAMiningError("high_yield_5m_manifest_git_hash_mismatch")
    manifest = _parse_json_mapping(manifest_raw, "manifest")
    manifest_errors = shared_data.validate_manifest(manifest)
    if manifest_errors:
        raise HighYield5mGAMiningError(
            "high_yield_5m_manifest_invalid:" + ";".join(manifest_errors)
        )
    if (
        manifest.get("dataset_id") != publication["dataset_id"]
        or manifest.get("dataset_version") != publication["dataset_version"]
        or manifest.get("quality_status") != "pass"
    ):
        raise HighYield5mGAMiningError("high_yield_5m_manifest_identity_or_quality_mismatch")
    _validate_research_only_blockers(manifest.get("blockers"), "manifest")
    _validate_research_only_blockers(manifest.get("known_gaps"), "manifest_known_gaps")
    if set(publication.get("blockers", [])) != set(manifest.get("blockers", [])):
        raise HighYield5mGAMiningError("high_yield_5m_selector_manifest_blocker_set_mismatch")

    try:
        resolved_root = shared_data.resolve_manifest_payload(
            manifest,
            shared_root=(shared_root or shared_data.default_shared_data_root(root)).resolve(),
            verify_files=True,
        )
    except (shared_data.SharedDataError, OSError, ValueError) as exc:
        detail = str(exc).split(";")[0] or type(exc).__name__
        raise HighYield5mGAMiningError(
            f"high_yield_5m_physical_dataset_invalid:{detail}"
        ) from exc
    physical_manifest_path = resolved_root / shared_data.MANIFEST_NAME
    physical_manifest_sha256 = shared_data.sha256_file(physical_manifest_path)
    if physical_manifest_sha256 != str(publication["physical_manifest_sha256"]):
        raise HighYield5mGAMiningError("high_yield_5m_physical_manifest_hash_mismatch")
    if not _is_sha256(str(manifest.get("aggregate_sha256", ""))):
        raise HighYield5mGAMiningError("high_yield_5m_aggregate_hash_invalid")
    if not any(
        isinstance(item, Mapping)
        and item.get("path") == dataready_consumer.KLINE_ATTESTATION_PATH
        for item in manifest.get("files", [])
    ):
        raise HighYield5mGAMiningError("high_yield_5m_kline_attestation_not_manifest_declared")

    attestation_path = resolved_root / dataready_consumer.KLINE_ATTESTATION_PATH
    try:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HighYield5mGAMiningError("high_yield_5m_kline_attestation_unreadable") from exc
    if not isinstance(attestation, Mapping):
        raise HighYield5mGAMiningError("high_yield_5m_kline_attestation_not_mapping")
    _validate_research_only_blockers(attestation.get("promotion_blockers"), "attestation")
    if set(attestation.get("promotion_blockers", [])) != set(manifest.get("blockers", [])):
        raise HighYield5mGAMiningError("high_yield_5m_attestation_blocker_set_mismatch")
    check_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    attestation_check = dataready_consumer._validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=check_now,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        # The shared validator's resolved-root mode replays every published
        # partition (over 1.8M rows).  Its attestation/schema/readiness and
        # immutable inventory checks remain mandatory here; the selected 5m
        # payload is then streamed and validated below without replaying
        # unrelated intervals.
        resolved_root=None,
        commit_exists=lambda commit: _git_commit_exists(root, commit),
        current_head=current_head,
    )
    if attestation_check.get("status") != "pass" or attestation_check.get("blockers"):
        blockers = ",".join(str(item) for item in attestation_check.get("blockers", []))
        raise HighYield5mGAMiningError(
            "high_yield_5m_kline_attestation_blocked:" + (blockers or "unknown")
        )
    payload_contract = dataready_consumer._validate_immutable_table_payload(
        attestation,
        manifest=manifest,
        resolved_root=None,
        attestation_path=dataready_consumer.KLINE_ATTESTATION_PATH,
        kind="kline",
        checked_at=check_now,
    )
    if payload_contract.get("blockers"):
        blockers = ",".join(str(item) for item in payload_contract["blockers"])
        raise HighYield5mGAMiningError(
            "high_yield_5m_kline_payload_contract_blocked:" + blockers
        )

    partition = _select_5m_partition(manifest)
    partition_path = resolved_root / str(partition["path"])
    attestation_partition = _select_attestation_partition(attestation)
    if (
        attestation_partition.get("path") != partition["path"]
        or attestation_partition.get("sha256") != partition["sha256"]
        or attestation_partition.get("bytes") != partition["bytes"]
    ):
        raise HighYield5mGAMiningError("high_yield_5m_5m_partition_attestation_mismatch")
    attestation_interval = _select_attestation_interval(attestation)
    frame, payload = _load_5m_jsonl(
        partition_path,
        expected_data_version=str(manifest["dataset_version"]),
        expected_rows=int(attestation_interval["finalized_count"]),
        expected_coverage_start=str(attestation_interval.get("coverage_start", "")),
        expected_coverage_end=str(attestation_interval.get("coverage_end", "")),
        generated_at=_parse_utc_timestamp(attestation.get("generated_at")),
        checked_at=check_now,
    )

    coverage = manifest.get("coverage")
    attestation_lineage = attestation.get("lineage")
    source_sha256 = (
        attestation_lineage.get("source_sha256")
        if isinstance(attestation_lineage, Mapping)
        else None
    )
    if source_sha256 != publication.get("source_sha256"):
        raise HighYield5mGAMiningError("high_yield_5m_source_sha256_mismatch")
    if not isinstance(coverage, Mapping):
        raise HighYield5mGAMiningError("high_yield_5m_manifest_coverage_invalid")
    if str(publication["coverage_end"]) != str(coverage.get("end")):
        raise HighYield5mGAMiningError("high_yield_5m_selector_manifest_coverage_mismatch")

    first_event = payload["physical_close_time_start"]
    last_event = payload["physical_close_time_end"]
    first_available = payload["physical_available_time_start"]
    last_available = payload["physical_available_time_end"]
    first_open = frame.index[0]
    last_open = frame.index[-1]
    provenance: dict[str, Any] = {
        # Existing report aliases remain available to downstream consumers.
        "data_version": str(manifest["dataset_version"]),
        "manifest_checksum": manifest_git_sha256,
        "manifest_interval": "5m",
        "manifest_start": first_open.isoformat(),
        "manifest_end": last_open.isoformat(),
        "manifest_row_count": len(frame),
        "resolved_row_count": len(frame),
        "resolved_slice_sha256": str(partition["sha256"]),
        "physical_access_mode": "immutable_shared_data_jsonl",
        "access_mode": "immutable_shared_data_jsonl",
        "selector_path": selector_rel.as_posix(),
        "selector_commit": current_head,
        "selector_sha256": selector_sha256,
        "manifest_git_spec": manifest_spec,
        "manifest_git_sha256": manifest_git_sha256,
        "manifest_sha256": manifest_git_sha256,
        "dataset_id": str(manifest["dataset_id"]),
        "dataset_version": str(manifest["dataset_version"]),
        "physical_manifest_path": shared_data.MANIFEST_NAME,
        "physical_manifest_sha256": physical_manifest_sha256,
        "aggregate_sha256": str(manifest["aggregate_sha256"]),
        "five_minute_file_path": str(partition["path"]),
        "five_minute_file_sha256": str(partition["sha256"]),
        "five_minute_file_bytes": int(partition["bytes"]),
        "five_minute_row_count": len(frame),
        "coverage_start": str(coverage["start"]),
        "coverage_end": str(coverage["end"]),
        "physical_close_time_start": first_event,
        "physical_close_time_end": last_event,
        "physical_available_time_start": first_available,
        "physical_available_time_end": last_available,
        "derived_open_index_start": first_open.isoformat(),
        "derived_open_index_end": last_open.isoformat(),
        "derived_open_index_semantics": "event_time_minus_5m_plus_1ms",
        "physical_close_time_field": "event_time",
        "physical_available_time_field": "available_time",
        "quality_status": str(manifest["quality_status"]),
        "readiness_class": str(manifest["readiness_class"]),
        "attestation_schema_version": str(attestation["schema_version"]),
        "attestation_status": "pass",
        "attestation_blockers": [],
        "consumer_readiness": "blocked",
        "consumer_readiness_blockers": list(manifest.get("blockers", [])),
        "research_only": True,
        "public_network_called": False,
        "mutable_sqlite_consumed": False,
        "source_sha256": str(source_sha256),
        "attestation_common_end": str(attestation.get("common_end", "")),
        "attestation_freshness_age_hours": attestation_check.get("freshness_age_hours"),
    }
    return frame, provenance


def _validate_selector(selector: Mapping[str, Any]) -> Mapping[str, Any]:
    if selector.get("schema_version") != "mutable_runtime_storage_pointer_v1":
        raise HighYield5mGAMiningError("high_yield_5m_selector_schema_invalid")
    publication = selector.get("immutable_publication")
    if not isinstance(publication, Mapping):
        raise HighYield5mGAMiningError("high_yield_5m_selector_publication_missing")
    required = {
        "dataset_id",
        "status",
        "manifest_path",
        "dataset_version",
        "manifest_sha256",
        "physical_manifest_sha256",
        "coverage_end",
        "source_sha256",
        "consumer_readiness",
        "blockers",
    }
    if not required.issubset(publication):
        raise HighYield5mGAMiningError("high_yield_5m_selector_publication_invalid")
    if publication.get("status") != "published":
        raise HighYield5mGAMiningError("high_yield_5m_selector_not_published")
    if publication.get("consumer_readiness") != "blocked":
        raise HighYield5mGAMiningError("high_yield_5m_selector_readiness_invalid")
    _validate_research_only_blockers(publication.get("blockers"), "selector")
    manifest_path = str(publication.get("manifest_path", ""))
    if not manifest_path.startswith(".agent/data_manifests/") or not manifest_path.endswith(".json"):
        raise HighYield5mGAMiningError("high_yield_5m_selector_manifest_path_invalid")
    for key in ("manifest_sha256", "physical_manifest_sha256", "source_sha256"):
        if not _is_sha256(str(publication.get(key, ""))):
            raise HighYield5mGAMiningError(f"high_yield_5m_selector_{key}_invalid")
    guardrails = selector.get("guardrails")
    if not isinstance(guardrails, Mapping):
        raise HighYield5mGAMiningError("high_yield_5m_selector_guardrails_invalid")
    for key in (
        "runtime_database_is_promotion_evidence",
        "promotion_unlock_allowed",
        "paper_or_live_unlock_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
    ):
        if guardrails.get(key) is not False:
            raise HighYield5mGAMiningError(
                f"high_yield_5m_selector_guardrail_not_false:{key}"
            )
    return publication


def _validate_research_only_blockers(value: object, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HighYield5mGAMiningError(f"high_yield_5m_{label}_blockers_invalid")
    unknown = sorted(set(value) - RESEARCH_ONLY_SELECTOR_BLOCKERS)
    if unknown:
        raise HighYield5mGAMiningError(
            f"high_yield_5m_{label}_unknown_blocker:{','.join(unknown)}"
        )


def _select_5m_partition(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [
        item
        for item in manifest.get("files", [])
        if isinstance(item, Mapping)
        and str(item.get("path", "")).startswith(
            "exchange=binance_spot/symbol=BTCUSDT/interval=5m/"
        )
        and str(item.get("path", "")).endswith(".jsonl")
    ]
    if len(candidates) != 1:
        raise HighYield5mGAMiningError("high_yield_5m_5m_partition_not_unique")
    return candidates[0]


def _select_attestation_partition(attestation: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [
        item
        for item in attestation.get("files", [])
        if isinstance(item, Mapping)
        and str(item.get("path", "")).startswith(
            "exchange=binance_spot/symbol=BTCUSDT/interval=5m/"
        )
        and str(item.get("path", "")).endswith(".jsonl")
    ]
    if len(candidates) != 1:
        raise HighYield5mGAMiningError("high_yield_5m_attestation_5m_partition_not_unique")
    return candidates[0]


def _select_attestation_interval(attestation: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [
        item
        for item in attestation.get("intervals", [])
        if isinstance(item, Mapping)
        and item.get("venue") == "binance_spot"
        and item.get("instrument_id") == "BTCUSDT"
        and item.get("interval") == "5m"
    ]
    if len(candidates) != 1:
        raise HighYield5mGAMiningError("high_yield_5m_attestation_5m_interval_not_unique")
    return candidates[0]


def _load_5m_jsonl(
    path: Path,
    *,
    expected_data_version: str,
    expected_rows: int,
    expected_coverage_start: str,
    expected_coverage_end: str,
    generated_at: datetime | None,
    checked_at: datetime,
) -> tuple[pd.DataFrame, dict[str, str]]:
    records: list[dict[str, float]] = []
    open_times: list[datetime] = []
    events: list[datetime] = []
    available: list[datetime] = []
    previous_event: datetime | None = None
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise HighYield5mGAMiningError("high_yield_5m_5m_payload_unreadable") from exc
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_blank_row:{line_number}"
                )
            try:
                row = json.loads(line, parse_constant=_reject_json_constant)
            except (ValueError, json.JSONDecodeError) as exc:
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_json_invalid:{line_number}"
                ) from exc
            if not isinstance(row, Mapping):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_row_invalid:{line_number}"
                )
            required = {
                "available_time",
                "close",
                "data_version",
                "event_time",
                "exchange",
                "high",
                "interval",
                "is_finalized",
                "low",
                "open",
                "symbol",
                "volume",
            }
            if not required.issubset(row):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_fields_missing:{line_number}"
                )
            if (
                row.get("exchange") != "binance_spot"
                or row.get("symbol") != "BTCUSDT"
                or row.get("interval") != "5m"
                or row.get("data_version") != expected_data_version
                or row.get("is_finalized") is not True
            ):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_identity_invalid:{line_number}"
                )
            event = _parse_utc_timestamp(row.get("event_time"))
            available_time = _parse_utc_timestamp(row.get("available_time"))
            if event is None or available_time is None or event > available_time:
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_time_invalid:{line_number}"
                )
            if (
                generated_at is None
                or available_time > generated_at
                or generated_at > checked_at
            ):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_pit_invalid:{line_number}"
                )
            if previous_event is not None and event - previous_event != pd.Timedelta(minutes=5):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_gap_or_duplicate:{line_number}"
                )
            previous_event = event
            derived_open = event - pd.Timedelta(minutes=5) + pd.Timedelta(milliseconds=1)
            values: dict[str, float] = {}
            for field in ("open", "high", "low", "close", "volume"):
                value = row.get(field)
                if isinstance(value, bool):
                    raise HighYield5mGAMiningError(
                        f"high_yield_5m_5m_payload_ohlcv_invalid:{line_number}"
                    )
                try:
                    numeric = float(value)
                except (TypeError, ValueError) as exc:
                    raise HighYield5mGAMiningError(
                        f"high_yield_5m_5m_payload_ohlcv_invalid:{line_number}"
                    ) from exc
                if not math.isfinite(numeric):
                    raise HighYield5mGAMiningError(
                        f"high_yield_5m_5m_payload_ohlcv_nonfinite:{line_number}"
                    )
                values[field] = numeric
            if (
                min(values[field] for field in ("open", "high", "low", "close")) <= 0.0
                or values["volume"] < 0.0
                or values["high"] < max(values["open"], values["close"], values["low"])
                or values["low"] > min(values["open"], values["close"], values["high"])
            ):
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_ohlcv_range_invalid:{line_number}"
                )
            if open_times and derived_open <= open_times[-1]:
                raise HighYield5mGAMiningError(
                    f"high_yield_5m_5m_payload_open_index_invalid:{line_number}"
                )
            open_times.append(derived_open)
            events.append(event)
            available.append(available_time)
            records.append(values)
    if len(records) != expected_rows:
        raise HighYield5mGAMiningError("high_yield_5m_5m_payload_row_count_mismatch")
    if not records:
        raise HighYield5mGAMiningError("high_yield_5m_5m_payload_empty")
    if events[0].isoformat().replace("+00:00", "Z") != expected_coverage_start:
        raise HighYield5mGAMiningError("high_yield_5m_5m_payload_start_mismatch")
    if events[-1].isoformat().replace("+00:00", "Z") != expected_coverage_end:
        raise HighYield5mGAMiningError("high_yield_5m_5m_payload_end_mismatch")
    index = pd.DatetimeIndex(open_times)
    frame = pd.DataFrame(records, index=index)
    frame.insert(
        0,
        "open_time_ms",
        np.asarray([int(value.timestamp() * 1_000) for value in open_times], dtype="int64"),
    )
    return frame, {
        "physical_close_time_start": events[0].isoformat().replace("+00:00", "Z"),
        "physical_close_time_end": events[-1].isoformat().replace("+00:00", "Z"),
        "physical_available_time_start": available[0].isoformat().replace("+00:00", "Z"),
        "physical_available_time_end": available[-1].isoformat().replace("+00:00", "Z"),
    }


def _repo_relative_path(path: Path, repo_root: Path) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    try:
        return candidate.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise HighYield5mGAMiningError("high_yield_5m_selector_path_outside_repo") from exc


def _git_show_bytes(repo_root: Path, spec: str, label: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", spec],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HighYield5mGAMiningError(
            f"high_yield_5m_{label}_committed_object_unavailable"
        ) from exc


def _parse_json_mapping(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighYield5mGAMiningError(f"high_yield_5m_{label}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise HighYield5mGAMiningError(f"high_yield_5m_{label}_not_mapping")
    return dict(value)


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _as_utc_timestamp(value: datetime, label: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise HighYield5mGAMiningError(f"{label}_timezone_required")
    return timestamp.tz_convert("UTC")


def _is_sha1(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _git_commit_exists(repo_root: Path, commit: object) -> bool:
    value = str(commit)
    if not _is_sha1(value):
        return False
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{value}^{{commit}}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite_json_constant:{value}")


@dataclass(frozen=True)
class HighYield5mGenome:
    entry_window: int
    exit_ratio: float
    atr_window: int
    atr_mult: float
    cooldown_bars: int
    failed_breakout_bars: int
    breakout_buffer_atr: float
    regime_fast_bars: int
    regime_slow_bars: int
    volatility_window_bars: int
    target_volatility_pct: float
    max_leverage: float
    drawdown_gate_pct: float

    def __post_init__(self) -> None:
        allowed = {
            "entry_window": self.entry_window in ENTRY_WINDOWS,
            "exit_ratio": self.exit_ratio in EXIT_RATIOS,
            "atr_window": self.atr_window in ATR_WINDOWS,
            "atr_mult": self.atr_mult in ATR_MULTS,
            "cooldown_bars": self.cooldown_bars in COOLDOWN_BARS,
            "failed_breakout_bars": self.failed_breakout_bars in FAILED_BREAKOUT_BARS,
            "breakout_buffer_atr": self.breakout_buffer_atr in BREAKOUT_BUFFER_ATR,
            "regime_pair": (self.regime_fast_bars, self.regime_slow_bars) in REGIME_PAIRS,
            "volatility_window_bars": self.volatility_window_bars in VOLATILITY_WINDOWS,
            "target_volatility_pct": self.target_volatility_pct in TARGET_VOLATILITY_PCT,
            "max_leverage": self.max_leverage in MAX_LEVERAGES,
            "drawdown_gate_pct": self.drawdown_gate_pct in DRAWDOWN_GATES_PCT,
        }
        invalid = [name for name, valid in allowed.items() if not valid]
        if invalid:
            raise HighYield5mGAMiningError(f"genome_values_invalid:{','.join(invalid)}")

    @property
    def exit_window(self) -> int:
        return max(6, int(round(self.entry_window * self.exit_ratio)))

    @property
    def genome_hash(self) -> str:
        return hashlib.sha256(_stable_json(self.to_dict()).encode("utf-8")).hexdigest()

    @property
    def candidate_id(self) -> str:
        return f"btc_high_yield_5m_ga_{self.genome_hash[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_window": self.entry_window,
            "exit_ratio": self.exit_ratio,
            "exit_window": self.exit_window,
            "atr_window": self.atr_window,
            "atr_mult": self.atr_mult,
            "cooldown_bars": self.cooldown_bars,
            "failed_breakout_bars": self.failed_breakout_bars,
            "breakout_buffer_atr": self.breakout_buffer_atr,
            "regime_fast_bars": self.regime_fast_bars,
            "regime_slow_bars": self.regime_slow_bars,
            "volatility_window_bars": self.volatility_window_bars,
            "target_volatility_pct": self.target_volatility_pct,
            "max_leverage": self.max_leverage,
            "drawdown_gate_pct": self.drawdown_gate_pct,
            "direction_policy": "symmetric_long_short",
            "position_policy": "volatility_target_capped_synthetic_leverage",
        }


@dataclass(frozen=True)
class CostScenario:
    name: str
    fee_bps: float
    spread_bps: float
    slippage_bps: float

    @property
    def total_bps(self) -> float:
        return self.fee_bps + self.spread_bps + self.slippage_bps

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "fee_bps": self.fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "total_bps_per_unit_turnover": self.total_bps,
        }


COST_SCENARIOS = (
    CostScenario("base", fee_bps=5.0, spread_bps=2.0, slippage_bps=3.0),
    CostScenario("conservative", fee_bps=7.5, spread_bps=4.0, slippage_bps=5.0),
    CostScenario("stress", fee_bps=10.0, spread_bps=8.0, slippage_bps=12.0),
)


def build_high_yield_5m_target(frame: pd.DataFrame, genome: HighYield5mGenome) -> pd.Series:
    _require_ohlcv(frame)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    atr = _atr(frame, genome.atr_window)
    fast = close.ewm(
        span=genome.regime_fast_bars,
        adjust=False,
        min_periods=genome.regime_fast_bars,
    ).mean()
    slow = close.ewm(
        span=genome.regime_slow_bars,
        adjust=False,
        min_periods=genome.regime_slow_bars,
    ).mean()
    bull = (fast > slow) & (close > slow)
    bear = (fast < slow) & (close < slow)

    upper = high.shift(1).rolling(genome.entry_window, min_periods=genome.entry_window).max()
    lower = low.shift(1).rolling(genome.entry_window, min_periods=genome.entry_window).min()
    exit_low = low.shift(1).rolling(genome.exit_window, min_periods=genome.exit_window).min()
    exit_high = high.shift(1).rolling(genome.exit_window, min_periods=genome.exit_window).max()
    long_entry = bull & (close > upper + genome.breakout_buffer_atr * atr)
    short_entry = bear & (close < lower - genome.breakout_buffer_atr * atr)
    long_exit = (~bull) | (close < exit_low)
    short_exit = (~bear) | (close > exit_high)
    direction = _stateful_donchian_direction(
        close=close,
        atr=atr,
        long_entry=long_entry,
        long_exit=long_exit,
        short_entry=short_entry,
        short_exit=short_exit,
        long_failure_line=upper,
        short_failure_line=lower,
        atr_mult=genome.atr_mult,
        cooldown_bars=genome.cooldown_bars,
        failed_breakout_bars=genome.failed_breakout_bars,
    )

    log_returns = np.log(close).diff()
    realized_volatility = (
        log_returns.rolling(
            genome.volatility_window_bars,
            min_periods=genome.volatility_window_bars,
        ).std(ddof=0)
        * math.sqrt(ANNUAL_5M_BARS)
    )
    leverage = (genome.target_volatility_pct / 100.0) / realized_volatility.replace(0.0, np.nan)
    leverage = leverage.clip(lower=0.0, upper=genome.max_leverage).replace([np.inf, -np.inf], np.nan)
    target = direction * leverage.fillna(0.0)
    target = target.where(close.notna() & slow.notna() & atr.notna(), 0.0)
    target.name = "target_at_completed_5m_close"
    return target.astype(float)


def simulate_high_yield_5m_next_open(
    frame: pd.DataFrame,
    target_at_close: pd.Series,
    *,
    start: int = 0,
    end: int | None = None,
    cost_scenario: CostScenario = COST_SCENARIOS[0],
    drawdown_gate_pct: float = 25.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_ohlcv(frame)
    end = len(frame) if end is None else int(end)
    start = int(start)
    if start < 0 or end > len(frame) or end <= start:
        raise HighYield5mGAMiningError("simulation_slice_invalid")
    if drawdown_gate_pct <= 0.0 or drawdown_gate_pct > 100.0:
        raise HighYield5mGAMiningError("drawdown_gate_pct_invalid")

    index = frame.index
    opens = frame["open"].astype(float).to_numpy()
    closes = frame["close"].astype(float).to_numpy()
    target = target_at_close.reindex(index).fillna(0.0).astype(float).to_numpy()
    rows = end - start
    positions = np.zeros(rows, dtype=float)
    gross = np.zeros(rows, dtype=float)
    fee = np.zeros(rows, dtype=float)
    spread = np.zeros(rows, dtype=float)
    slippage = np.zeros(rows, dtype=float)
    net = np.zeros(rows, dtype=float)
    equity_curve = np.ones(rows, dtype=float)
    turnover_values = np.zeros(rows, dtype=float)

    previous_position = 0.0
    equity = 1.0
    peak = 1.0
    drawdown_locked = False
    drawdown_lock_count = 0
    fill_count = 0
    trade_count = 0
    bankruptcy = False
    fill_samples: list[dict[str, Any]] = []

    for local, pos in enumerate(range(start, end)):
        desired = float(target[pos - 1]) if pos > 0 else 0.0
        if drawdown_locked:
            desired = 0.0
        desired = float(np.clip(desired, -2.5, 2.5))
        turnover = abs(desired - previous_position)
        turnover_values[local] = turnover
        if turnover > 1e-12:
            fill_count += 1
            if abs(desired) > 1e-12 and (
                abs(previous_position) <= 1e-12
                or math.copysign(1.0, desired) != math.copysign(1.0, previous_position)
            ):
                trade_count += 1
            if len(fill_samples) < 3:
                fill_samples.append(
                    {
                        "execution_time": index[pos].isoformat(),
                        "decision_time": index[pos - 1].isoformat() if pos > 0 else None,
                        "execution_price": _round(opens[pos]),
                        "from_position": _round(previous_position),
                        "to_position": _round(desired),
                    }
                )
        positions[local] = desired
        fee[local] = turnover * cost_scenario.fee_bps / 10_000.0
        spread[local] = turnover * cost_scenario.spread_bps / 10_000.0
        slippage[local] = turnover * cost_scenario.slippage_bps / 10_000.0

        if pos < end - 1:
            price_return = opens[pos + 1] / opens[pos] - 1.0
        else:
            price_return = closes[pos] / opens[pos] - 1.0
        gross[local] = desired * price_return
        net[local] = gross[local] - fee[local] - spread[local] - slippage[local]

        if local == rows - 1 and abs(desired) > 1e-12:
            terminal_turnover = abs(desired)
            turnover_values[local] += terminal_turnover
            fee[local] += terminal_turnover * cost_scenario.fee_bps / 10_000.0
            spread[local] += terminal_turnover * cost_scenario.spread_bps / 10_000.0
            slippage[local] += terminal_turnover * cost_scenario.slippage_bps / 10_000.0
            net[local] -= terminal_turnover * cost_scenario.total_bps / 10_000.0
            fill_count += 1

        if net[local] <= -0.999999:
            equity = 0.0
            bankruptcy = True
        else:
            equity *= 1.0 + net[local]
        equity_curve[local] = equity
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0 if peak > 0.0 else -1.0
        if not drawdown_locked and drawdown <= -drawdown_gate_pct / 100.0:
            drawdown_locked = True
            drawdown_lock_count += 1
        previous_position = desired

    metrics = _metrics_from_simulation(
        index=index[start:end],
        positions=positions,
        net=net,
        equity=equity_curve,
        turnover=turnover_values,
        fee=fee,
        spread=spread,
        slippage=slippage,
        trade_count=trade_count,
        fill_count=fill_count,
        drawdown_lock_count=drawdown_lock_count,
        bankruptcy=bankruptcy,
    )
    ledger = _ledger_summary(
        index=index[start:end],
        positions=positions,
        gross=gross,
        net=net,
        equity=equity_curve,
        fee=fee,
        spread=spread,
        slippage=slippage,
        fill_count=fill_count,
        fill_samples=fill_samples,
    )
    return metrics, ledger


def _candidate_row(
    *,
    rank: int,
    selection: Mapping[str, Any],
    holdout_key: str,
    holdout: Mapping[str, Any],
    base_ledger: Mapping[str, Any],
    reasons: Sequence[str],
    retained_decision: str,
) -> dict[str, Any]:
    genome = selection["genome"]
    if not isinstance(genome, HighYield5mGenome):
        raise HighYield5mGAMiningError("selection_genome_invalid")
    return {
        "rank": rank,
        "candidate_id": genome.candidate_id,
        "genome_hash": genome.genome_hash,
        "genome": genome.to_dict(),
        "selection_fitness": _round(selection["selection_fitness"]),
        "walk_forward": {
            "fold_count": len(selection["folds"]),
            "passed_fold_count": selection["passed_fold_count"],
            "positive_fold_count": selection["positive_fold_count"],
            "folds": selection["folds"],
        },
        holdout_key: dict(holdout),
        "ledger_reconciliation": dict(base_ledger),
        "retention_decision": retained_decision,
        "retention_reasons": list(reasons),
    }


def _build_frozen_holdout_lock(
    *,
    experiment_id: str,
    generated: datetime,
    data_provenance: Mapping[str, Any],
    frame: pd.DataFrame,
    selection_end: int,
    prior_cutoff: pd.Timestamp | None,
    holdout_start: pd.Timestamp | None,
    folds: Sequence[FoldSpec],
    seed: int,
    population_size: int,
    generations: int,
    search_round_count: int,
    prior_search_population_slots: int,
    prior_search_unique_evaluations: int,
    selection: Mapping[str, Any],
    selection_reasons: Sequence[str],
) -> dict[str, Any]:
    if prior_cutoff is None or holdout_start is None:
        raise HighYield5mGAMiningError("frozen_holdout_lock_boundary_missing")
    genome = selection["genome"]
    if not isinstance(genome, HighYield5mGenome):
        raise HighYield5mGAMiningError("frozen_holdout_lock_genome_invalid")
    return {
        "schema_version": FROZEN_HOLDOUT_LOCK_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "locked_at": generated.isoformat(),
        "code_commit": _git_commit_hash(),
        "data_binding": {
            "dataset_version": data_provenance.get("dataset_version")
            or data_provenance.get("data_version"),
            "selector_commit": data_provenance.get("selector_commit"),
            "manifest_git_sha256": data_provenance.get("manifest_git_sha256")
            or data_provenance.get("manifest_checksum"),
            "physical_manifest_sha256": data_provenance.get(
                "physical_manifest_sha256"
            ),
            "aggregate_sha256": data_provenance.get("aggregate_sha256"),
            "five_minute_file_sha256": data_provenance.get(
                "five_minute_file_sha256"
            )
            or data_provenance.get("resolved_slice_sha256"),
        },
        "selection_window": {
            "start": frame.index[0].isoformat(),
            "end": frame.index[selection_end - 1].isoformat(),
            "row_count": selection_end,
            "prior_research_cutoff": prior_cutoff.isoformat(),
            "folds": [fold.to_dict(frame.index) for fold in folds],
        },
        "unseen_holdout_window": {
            "start": holdout_start.isoformat(),
            "end": frame.index[-1].isoformat(),
            "row_count": len(frame) - selection_end,
            "statistically_unseen_before_run": True,
            "values_or_metrics_in_lock": False,
            "reuse_for_parameter_selection_allowed": False,
        },
        "search_protocol": {
            "algorithm": "deterministic_tournament_elitism_genetic_search",
            "seed": int(seed),
            "population_size": int(population_size),
            "generations": int(generations),
            "population_slots_this_round": int(population_size * generations),
            "search_round_count": int(search_round_count),
            "prior_search_population_slots": int(prior_search_population_slots),
            "prior_search_unique_evaluations": int(prior_search_unique_evaluations),
            "gene_space_sha256": hashlib.sha256(
                _stable_json(_gene_space()).encode("utf-8")
            ).hexdigest(),
            "cost_scenarios_sha256": hashlib.sha256(
                _stable_json([scenario.to_dict() for scenario in COST_SCENARIOS]).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "champion_selection_rule": (
                "max_selection_fitness_then_genome_hash_single_candidate"
            ),
        },
        "locked_candidate": {
            "candidate_id": genome.candidate_id,
            "genome_hash": genome.genome_hash,
            "genome": genome.to_dict(),
            "selection_fitness": _round(selection["selection_fitness"]),
            "passed_fold_count": int(selection["passed_fold_count"]),
            "positive_fold_count": int(selection["positive_fold_count"]),
            "selection_gate_reasons": list(selection_reasons),
        },
        "reveal_authorized": not selection_reasons,
        "holdout_candidate_count_if_revealed": 1,
        "promotion_eligible": False,
        "paper_or_live_unlock_allowed": False,
    }


def run_high_yield_5m_ga_on_frame(
    *,
    frame: pd.DataFrame,
    data_provenance: Mapping[str, Any],
    output_root: Path,
    seed: int = DEFAULT_SEED,
    population_size: int = 48,
    generations: int = 12,
    fold_count: int = 4,
    holdout_fraction: float = 0.20,
    max_candidates: int = 8,
    prior_shared_tail_exposure: bool = True,
    search_round_count: int = 1,
    prior_search_population_slots: int = 0,
    prior_search_unique_evaluations: int = 0,
    frozen_unseen_holdout_start_utc: datetime | None = None,
    prior_research_cutoff_utc: datetime | None = None,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    _require_ohlcv(frame)
    if population_size < 8 or generations < 1 or fold_count < 2:
        raise HighYield5mGAMiningError("ga_configuration_too_small")
    if len(frame) < 8_000:
        raise HighYield5mGAMiningError("five_minute_rows_insufficient")
    if search_round_count < 1 or prior_search_population_slots < 0 or prior_search_unique_evaluations < 0:
        raise HighYield5mGAMiningError("search_history_invalid")
    if not experiment_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in experiment_id
    ):
        raise HighYield5mGAMiningError("experiment_id_invalid")

    frozen_unseen_mode = (
        frozen_unseen_holdout_start_utc is not None
        or prior_research_cutoff_utc is not None
    )
    if frozen_unseen_mode and (
        frozen_unseen_holdout_start_utc is None
        or prior_research_cutoff_utc is None
    ):
        raise HighYield5mGAMiningError("frozen_unseen_holdout_boundary_pair_required")

    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    holdout_lock_path: Path | None = None
    prior_cutoff: pd.Timestamp | None = None
    frozen_holdout_start: pd.Timestamp | None = None
    if frozen_unseen_mode:
        if prior_shared_tail_exposure:
            raise HighYield5mGAMiningError("frozen_unseen_holdout_prior_exposure_must_be_false")
        if max_candidates != 1:
            raise HighYield5mGAMiningError("frozen_unseen_holdout_requires_single_candidate")
        prior_cutoff = _as_utc_timestamp(
            prior_research_cutoff_utc,
            "prior_research_cutoff",
        )
        frozen_holdout_start = _as_utc_timestamp(
            frozen_unseen_holdout_start_utc,
            "frozen_unseen_holdout_start",
        )
        if frozen_holdout_start - prior_cutoff != pd.Timedelta(minutes=5):
            raise HighYield5mGAMiningError("frozen_unseen_holdout_boundary_not_contiguous")
        cutoff_hits = np.flatnonzero(frame.index == prior_cutoff)
        holdout_hits = np.flatnonzero(frame.index == frozen_holdout_start)
        if len(cutoff_hits) != 1 or len(holdout_hits) != 1:
            raise HighYield5mGAMiningError("frozen_unseen_holdout_boundary_missing")
        if int(holdout_hits[0]) != int(cutoff_hits[0]) + 1:
            raise HighYield5mGAMiningError("frozen_unseen_holdout_boundary_not_adjacent")
        selection_end = int(holdout_hits[0])
        if len(frame) - selection_end < MIN_UNSEEN_HOLDOUT_ROWS:
            raise HighYield5mGAMiningError("frozen_unseen_holdout_rows_insufficient")
        try:
            output_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise HighYield5mGAMiningError(
                "frozen_unseen_holdout_output_root_must_be_new"
            ) from exc
        holdout_lock_path = output_root / "btc_high_yield_5m_frozen_holdout_lock.json"
    else:
        if not 0.10 <= holdout_fraction <= 0.35:
            raise HighYield5mGAMiningError("holdout_fraction_invalid")
        selection_end = int(len(frame) * (1.0 - holdout_fraction))

    selection_frame = frame.iloc[:selection_end]
    embargo_bars = max(pair[1] for pair in REGIME_PAIRS)
    folds = build_walk_forward_folds(
        selection_end,
        fold_count=fold_count,
        embargo_bars=embargo_bars,
    )
    if len(folds) != fold_count:
        raise HighYield5mGAMiningError("walk_forward_fold_construction_failed")

    rng = random.Random(int(seed))
    population = _initial_population(rng, population_size)
    cache: dict[str, dict[str, Any]] = {}
    generation_trace: list[dict[str, Any]] = []
    for generation in range(1, generations + 1):
        evaluated = [
            _evaluate_selection_candidate(
                frame=selection_frame,
                genome=genome,
                folds=folds,
                cache=cache,
            )
            for genome in population
        ]
        evaluated.sort(key=lambda item: (float(item["selection_fitness"]), item["genome_hash"]), reverse=True)
        generation_trace.append(
            {
                "generation": generation,
                "best_fitness": _round(evaluated[0]["selection_fitness"]),
                "median_fitness": _round(float(np.median([row["selection_fitness"] for row in evaluated]))),
                "unique_evaluations": len(cache),
            }
        )
        elite_count = max(2, population_size // 8)
        next_population = [row["genome"] for row in evaluated[:elite_count]]
        while len(next_population) < population_size:
            left = _tournament(evaluated, rng)
            right = _tournament(evaluated, rng)
            child = _mutate(_crossover(left, right, rng), rng)
            next_population.append(child)
        population = _dedupe_and_fill(next_population, rng, population_size)

    evaluated_all = sorted(
        cache.values(),
        key=lambda item: (float(item["selection_fitness"]), item["genome_hash"]),
        reverse=True,
    )
    top_selection = evaluated_all[:max_candidates]
    candidate_rows: list[dict[str, Any]] = []
    holdout_revealed = False
    holdout_lock: dict[str, Any] | None = None
    holdout_lock_file_sha256: str | None = None
    if frozen_unseen_mode:
        selection = top_selection[0]
        genome = selection["genome"]
        selection_reasons = _selection_gate_reasons(
            selection=selection,
            fold_count=fold_count,
        )
        holdout_lock = _build_frozen_holdout_lock(
            experiment_id=experiment_id,
            generated=generated,
            data_provenance=data_provenance,
            frame=frame,
            selection_end=selection_end,
            prior_cutoff=prior_cutoff,
            holdout_start=frozen_holdout_start,
            folds=folds,
            seed=seed,
            population_size=population_size,
            generations=generations,
            search_round_count=search_round_count,
            prior_search_population_slots=prior_search_population_slots,
            prior_search_unique_evaluations=prior_search_unique_evaluations,
            selection=selection,
            selection_reasons=selection_reasons,
        )
        assert holdout_lock_path is not None
        _write_json(holdout_lock_path, holdout_lock)
        holdout_lock_file_sha256 = shared_data.sha256_file(holdout_lock_path)

        cost_stress: dict[str, Any] = {}
        base_ledger: dict[str, Any] = {}
        holdout_reasons: list[str] = []
        if not selection_reasons:
            target = build_high_yield_5m_target(frame, genome)
            for scenario in COST_SCENARIOS:
                metrics, ledger = simulate_high_yield_5m_next_open(
                    frame,
                    target,
                    start=selection_end,
                    end=len(frame),
                    cost_scenario=scenario,
                    drawdown_gate_pct=genome.drawdown_gate_pct,
                )
                cost_stress[scenario.name] = metrics
                if scenario.name == "base":
                    base_ledger = ledger
            holdout_revealed = True
            holdout_reasons = _holdout_metric_reasons(
                cost_stress=cost_stress,
                prefix="unseen_holdout",
            )
        else:
            holdout_reasons = ["unseen_holdout_not_revealed_selection_gate_failed"]
        reasons = [*selection_reasons, *holdout_reasons]
        candidate_rows.append(
            _candidate_row(
                rank=1,
                selection=selection,
                holdout_key="frozen_unseen_holdout",
                holdout={
                    "status": "consumed_once" if holdout_revealed else "preserved_unseen",
                    "start": frame.index[selection_end].isoformat(),
                    "end": frame.index[-1].isoformat(),
                    "row_count": len(frame) - selection_end,
                    "used_for_selection": False,
                    "statistically_unseen_before_run": True,
                    "promotion_eligible": False,
                    "candidate_count_revealed": 1 if holdout_revealed else 0,
                    "cost_stress": cost_stress if holdout_revealed else None,
                },
                base_ledger=base_ledger,
                reasons=reasons,
                retained_decision=(
                    "retain_research_hypothesis_unseen_holdout_passed_execution_evidence_required"
                    if holdout_revealed and not reasons
                    else "reject_or_defer_research_hypothesis"
                ),
            )
        )
    else:
        for rank, selection in enumerate(top_selection, start=1):
            genome = selection["genome"]
            target = build_high_yield_5m_target(frame, genome)
            cost_stress = {}
            base_ledger = {}
            for scenario in COST_SCENARIOS:
                metrics, ledger = simulate_high_yield_5m_next_open(
                    frame,
                    target,
                    start=selection_end,
                    end=len(frame),
                    cost_scenario=scenario,
                    drawdown_gate_pct=genome.drawdown_gate_pct,
                )
                cost_stress[scenario.name] = metrics
                if scenario.name == "base":
                    base_ledger = ledger
            reasons = _retention_reasons(selection=selection, cost_stress=cost_stress)
            candidate_rows.append(
                _candidate_row(
                    rank=rank,
                    selection=selection,
                    holdout_key="diagnostic_holdout",
                    holdout={
                        "start": frame.index[selection_end].isoformat(),
                        "end": frame.index[-1].isoformat(),
                        "row_count": len(frame) - selection_end,
                        "used_for_selection": False,
                        "prior_shared_tail_exposure": bool(prior_shared_tail_exposure),
                        "promotion_eligible": False,
                        "cost_stress": cost_stress,
                    },
                    base_ledger=base_ledger,
                    reasons=reasons,
                    retained_decision=(
                        "retain_research_hypothesis_requires_new_unseen_holdout"
                        if not reasons
                        else "reject_or_defer_research_hypothesis"
                    ),
                )
            )

    retained = [row for row in candidate_rows if not row["retention_reasons"]]
    blockers = [
        "btc_high_yield_5m_perpetual_mark_index_funding_parity_not_proven",
        "btc_high_yield_5m_l2_spread_depth_market_impact_not_proven",
        "btc_high_yield_5m_latency_queue_and_unfilled_order_model_not_proven",
        "btc_high_yield_5m_liquidation_buffer_is_not_mark_price_replay",
        "btc_high_yield_5m_paper_fill_position_cash_ledger_not_observed",
        "btc_high_yield_5m_runtime_adapter_not_implemented",
        "btc_high_yield_5m_manual_promotion_review_not_started",
    ]
    if frozen_unseen_mode:
        blockers.append(
            "btc_high_yield_5m_unseen_holdout_consumed_once_no_reuse_for_tuning"
            if holdout_revealed
            else "btc_high_yield_5m_unseen_holdout_preserved_not_revealed"
        )
    else:
        blockers.append(
            "btc_high_yield_5m_prior_shared_tail_exposure_requires_future_unseen_data"
        )
    if not retained:
        blockers.append("btc_high_yield_5m_no_candidate_passed_frozen_research_gates")

    if frozen_unseen_mode:
        if not holdout_revealed:
            decision = "reject_selection_batch_holdout_not_revealed"
        elif retained:
            decision = (
                "retain_research_hypothesis_unseen_holdout_passed_"
                "execution_evidence_required"
            )
        else:
            decision = "reject_candidate_after_unseen_holdout"
    else:
        decision = (
            "retain_research_hypothesis_requires_future_unseen_data"
            if retained
            else "reject_current_high_yield_5m_search_batch"
        )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "experiment_id": experiment_id,
        "status": "complete_research_only",
        "decision": decision,
        "scope": "offline_high_yield_donchian_to_5m_hypothesis_translation",
        "generated_at": generated.isoformat(),
        "code_commit": _git_commit_hash(),
        "asset": "BTC",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "research_question": (
            "Can the economic structure of high_yield_donchian_v2 survive a bounded 5m translation "
            "after next-open execution and intraday cost stress?"
        ),
        "economic_hypothesis": (
            "BTC intraday breakouts have conditional persistence only when a slower completed-bar trend permits "
            "direction; ATR exits, cooldown, volatility targeting and a sticky drawdown gate limit false-breakout damage."
        ),
        "origin_contract": {
            "strategy_id": ORIGIN_STRATEGY_ID,
            "candidate_id": ORIGIN_CANDIDATE_ID,
            "base_variant_id": ORIGIN_BASE_VARIANT_ID,
            "inherited_semantics": [
                "symmetric_donchian_long_short",
                "slower_trend_permission",
                "atr_trailing_exit",
                "cooldown_after_exit",
                "volatility_target_position",
                "max_leverage_cap_2p5x",
                "sticky_drawdown_gate",
            ],
            "not_inherited_as_evidence": [
                "historical_10000x_label",
                "4h_parameter_optimum",
                "same_window_leverage_return",
                "paper_or_live_readiness",
            ],
            "translation_rule": "preserve_economic_structure_not_literal_bar_count_scaling",
        },
        "data_provenance": dict(data_provenance),
        "data_consumption": {
            "access_mode": str(
                data_provenance.get("access_mode")
                or data_provenance.get("physical_access_mode")
                or "unknown"
            ),
            "selector_path": data_provenance.get("selector_path"),
            "selector_commit": data_provenance.get("selector_commit"),
            "selector_sha256": data_provenance.get("selector_sha256"),
            "manifest_git_spec": data_provenance.get("manifest_git_spec"),
            "dataset_id": data_provenance.get("dataset_id"),
            "dataset_version": (
                data_provenance.get("dataset_version")
                or data_provenance.get("data_version")
            ),
            "coverage_start": (
                data_provenance.get("coverage_start")
                or data_provenance.get("manifest_start")
            ),
            "coverage_end": (
                data_provenance.get("coverage_end")
                or data_provenance.get("manifest_end")
            ),
            "manifest_git_sha256": (
                data_provenance.get("manifest_git_sha256")
                or data_provenance.get("manifest_checksum")
            ),
            "manifest_sha256": data_provenance.get("manifest_sha256"),
            "physical_manifest_sha256": data_provenance.get("physical_manifest_sha256"),
            "aggregate_sha256": data_provenance.get("aggregate_sha256"),
            "five_minute_file_sha256": (
                data_provenance.get("five_minute_file_sha256")
                or data_provenance.get("resolved_slice_sha256")
            ),
            "five_minute_file_path": data_provenance.get("five_minute_file_path"),
            "research_only": bool(data_provenance.get("research_only", True)),
            "consumer_readiness": data_provenance.get("consumer_readiness"),
            "consumer_readiness_blockers": list(
                data_provenance.get("consumer_readiness_blockers", [])
            ),
            "public_network_called": bool(data_provenance.get("public_network_called", False)),
        },
        "feature_and_execution_policy": {
            "decision_time": "completed_5m_bar_close",
            "execution_time": "next_5m_bar_open",
            "pnl_price_path": "next_open_to_following_open_with_terminal_close",
            "channel_visibility": "high_low_shift_1_before_rolling",
            "trend_visibility": "causal_ema_on_completed_5m_bars",
            "position_policy": "symmetric_long_short_volatility_target_max_2p5x_synthetic_research",
            "drawdown_gate": "sticky_flat_after_threshold_for_each_validation_segment",
            "strategy_calls_broker": False,
        },
        "gene_space": _gene_space(),
        "validation_design": {
            "method": (
                "expanding_chronological_walk_forward_with_max_lookback_embargo_"
                "plus_single_locked_candidate_unseen_holdout"
                if frozen_unseen_mode
                else "expanding_chronological_walk_forward_with_max_lookback_"
                "embargo_plus_tail_diagnostic"
            ),
            "folds": [fold.to_dict(frame.index) for fold in folds],
            "fold_count": len(folds),
            "embargo_bars": embargo_bars,
            "holdout_fraction": None if frozen_unseen_mode else _round(holdout_fraction),
            "selection_rows": selection_end,
            "selection_start": frame.index[0].isoformat(),
            "selection_end": frame.index[selection_end - 1].isoformat(),
            "diagnostic_holdout_rows": 0 if frozen_unseen_mode else len(frame) - selection_end,
            "frozen_unseen_holdout_rows": len(frame) - selection_end if frozen_unseen_mode else 0,
            "prior_research_cutoff": prior_cutoff.isoformat() if prior_cutoff is not None else None,
            "holdout_start": frame.index[selection_end].isoformat(),
            "holdout_end": frame.index[-1].isoformat(),
            "holdout_used_for_selection": False,
            "prior_shared_tail_exposure": bool(prior_shared_tail_exposure),
            "promotion_eligible_holdout": False,
            "statistically_unseen_before_run": bool(frozen_unseen_mode),
            "holdout_revealed": holdout_revealed if frozen_unseen_mode else True,
            "holdout_exposure_after_run": (
                "consumed_once" if holdout_revealed else "preserved_unseen"
            )
            if frozen_unseen_mode
            else "diagnostic_previously_exposed",
            "holdout_candidate_count_revealed": (
                1 if holdout_revealed else 0
            )
            if frozen_unseen_mode
            else len(candidate_rows),
            "holdout_reuse_for_tuning_allowed": False,
            "future_unseen_holdout_required": (
                holdout_revealed if frozen_unseen_mode else True
            ),
        },
        "cost_model": {
            "scenarios": [scenario.to_dict() for scenario in COST_SCENARIOS],
            "funding": "missing_research_blocker",
            "market_impact": "missing_research_blocker",
            "queue_and_unfilled_orders": "missing_research_blocker",
        },
        "search_protocol": {
            "algorithm": "deterministic_tournament_elitism_genetic_search",
            "seed": int(seed),
            "population_size": population_size,
            "generations": generations,
            "population_slots_this_round": population_size * generations,
            "search_round_count": int(search_round_count),
            "prior_search_population_slots": int(prior_search_population_slots),
            "prior_search_unique_evaluations": int(prior_search_unique_evaluations),
            "cumulative_population_slots": (
                int(prior_search_population_slots) + population_size * generations
            ),
            "champion_selection_rule": (
                "max_selection_fitness_then_genome_hash_single_candidate"
            ),
            "unique_evaluation_count": len(cache),
            "reported_top_candidate_count": len(candidate_rows),
            "generation_trace": generation_trace,
        },
        "top_candidates": candidate_rows,
        "retained_research_candidate_count": len(retained),
        "retained_research_candidates": [row["candidate_id"] for row in retained],
        "frozen_holdout_lock": {
            "path": holdout_lock_path.name if holdout_lock_path is not None else None,
            "semantic_sha256": (
                hashlib.sha256(_stable_json(holdout_lock).encode("utf-8")).hexdigest()
                if holdout_lock is not None
                else None
            ),
            "file_sha256": holdout_lock_file_sha256,
            "reveal_authorized": (
                bool(holdout_lock.get("reveal_authorized"))
                if holdout_lock is not None
                else False
            ),
        },
        "blockers": sorted(set(blockers)),
        "promotion": {
            "recommendation": "reject_or_research_only",
            "demo_strategy_registration_allowed": False,
            "paper_candidate_generated": False,
            "paper_queue_status": "LOCKED",
            "paper_auto_start": False,
            "live_enabled": False,
            "live_status": "FROZEN",
        },
        "safety": {
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "public_network_called": False,
            "real_orders_created": False,
            "paper": False,
            "live": False,
            "private": False,
            "order": False,
            "real_order": False,
            "strategy_runtime_adapter_generated": False,
            "transfer_allowed": False,
            "withdraw_allowed": False,
            "transfer": False,
            "withdraw": False,
        },
    }
    report["artifact_hash"] = hashlib.sha256(_stable_json(report).encode("utf-8")).hexdigest()
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "btc_high_yield_5m_ga_mining_report.json"
    candidates_path = output_root / "btc_high_yield_5m_ga_candidate_definitions.json"
    summary_path = output_root / "btc_high_yield_5m_ga_mining_summary_cn.md"
    candidate_definitions = {
        "schema_version": "btc_high_yield_5m_ga_candidate_definitions_v1",
        "scope": "research_only_no_runtime_adapter",
        "source_artifact_hash": report["artifact_hash"],
        "candidates": [
            {
                "candidate_id": row["candidate_id"],
                "genome_hash": row["genome_hash"],
                "params": row["genome"],
                "readiness": (
                    "research_hypothesis_passed_single_unseen_holdout_"
                    "requires_execution_evidence"
                    if frozen_unseen_mode
                    else "research_hypothesis_requires_future_unseen_holdout"
                ),
            }
            for row in retained
        ],
        "demo_strategy_registration_allowed": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }
    _write_json(report_path, report)
    _write_json(candidates_path, candidate_definitions)
    _write_text(summary_path, render_high_yield_5m_summary(report))
    return report


def run_btc_high_yield_5m_ga_mining(
    *,
    market_db_path: Path | None = DEFAULT_MARKET_DB,
    manifest_path: Path | None = DEFAULT_MANIFEST,
    selector_path: Path = DEFAULT_SELECTOR_PATH,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    **kwargs: Any,
) -> dict[str, Any]:
    if (market_db_path is None) != (manifest_path is None):
        raise HighYield5mGAMiningError("high_yield_5m_legacy_pair_required")
    if market_db_path is None and manifest_path is None:
        frame, provenance = load_committed_5m_market_frame(
            selector_path=selector_path,
            repo_root=repo_root,
        )
    else:
        assert market_db_path is not None
        assert manifest_path is not None
        manifest = load_data_manifest(manifest_path)
        if str(manifest.get("interval")) != "5m":
            raise HighYield5mGAMiningError("high_yield_5m_manifest_interval_mismatch")
        frame, provenance = load_manifest_bounded_market_frame(
            db_path=market_db_path,
            manifest=manifest,
        )
        provenance = dict(provenance)
        provenance.update(
            {
                "access_mode": "legacy_sqlite_opt_in",
                "physical_access_mode": "legacy_sqlite_opt_in",
                "legacy_sqlite_opt_in": True,
                "mutable_sqlite_consumed": True,
                "public_network_called": False,
                "research_only": True,
            }
        )
    return run_high_yield_5m_ga_on_frame(
        frame=frame,
        data_provenance=provenance,
        output_root=output_root,
        **kwargs,
    )


def render_high_yield_5m_summary(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC high-yield Donchian 5m GA 研究摘要",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策：`{report.get('decision')}`",
        f"- 代码提交：`{report.get('code_commit')}`",
        f"- artifact hash：`{report.get('artifact_hash')}`",
        f"- 留存研究假设：`{report.get('retained_research_candidate_count')}`",
        f"- 数据访问模式：`{_mapping(report.get('data_consumption')).get('access_mode')}`",
        f"- 数据集版本：`{_mapping(report.get('data_consumption')).get('dataset_version')}`",
        f"- 数据消费就绪度：`{_mapping(report.get('data_consumption')).get('consumer_readiness')}`（仅研究读取）",
        f"- 留出状态：`{_mapping(report.get('validation_design')).get('holdout_exposure_after_run')}`",
        f"- 候选锁：`{_mapping(report.get('frozen_holdout_lock')).get('semantic_sha256')}`",
        "- Demo / paper / live：全部关闭",
        "",
        "## Top candidates",
        "",
        "| 排名 | candidate | fold通过 | base收益 | stress收益 | 交易/日 | 回撤 | 决策 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("top_candidates", []):
        holdout = _mapping(
            row.get("frozen_unseen_holdout") or row.get("diagnostic_holdout")
        )
        stress = _mapping(holdout.get("cost_stress"))
        base = _mapping(stress.get("base"))
        stressed = _mapping(stress.get("stress"))
        walk = _mapping(row.get("walk_forward"))
        lines.append(
            "| {rank} | `{candidate}` | {passed}/{folds} | {base_return} | {stress_return} | "
            "{trades} | {drawdown} | `{decision}` |".format(
                rank=row.get("rank"),
                candidate=row.get("candidate_id"),
                passed=walk.get("passed_fold_count"),
                folds=walk.get("fold_count"),
                base_return=_pct(base.get("total_return")),
                stress_return=_pct(stressed.get("total_return")),
                trades=_round(base.get("trades_per_day", 0.0), 3),
                drawdown=_pct(base.get("max_drawdown")),
                decision=row.get("retention_decision"),
            )
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "本实验继承 Donchian、趋势许可、ATR、冷却和波动目标的经济结构，不继承历史万倍标签。",
            (
                "未见留出仅在训练/验证门通过后对单个锁定候选揭盲；揭盲后该窗口永久禁止再次调参。"
                if bool(
                    _mapping(report.get("validation_design")).get(
                        "statistically_unseen_before_run"
                    )
                )
                else "尾部数据在项目历史研究中已经被查看，因此本轮结果仅是 diagnostic research；需要新的未见不可变数据确认。"
            ),
            "固定 bps 成本不能替代 L2、排队、不成交、mark/index、funding 和强平回放。",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_selection_candidate(
    *,
    frame: pd.DataFrame,
    genome: HighYield5mGenome,
    folds: Sequence[FoldSpec],
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if genome.genome_hash in cache:
        return cache[genome.genome_hash]
    target = build_high_yield_5m_target(frame, genome)
    fold_rows: list[dict[str, Any]] = []
    for fold in folds:
        metrics, _ = simulate_high_yield_5m_next_open(
            frame,
            target,
            start=fold.validation_start,
            end=fold.validation_end,
            cost_scenario=COST_SCENARIOS[0],
            drawdown_gate_pct=genome.drawdown_gate_pct,
        )
        passed = _selection_fold_passed(metrics)
        fold_rows.append(
            {
                "fold_id": fold.fold_id,
                "passed": passed,
                "metrics": metrics,
            }
        )
    score = _selection_fitness(fold_rows, genome)
    row = {
        "genome": genome,
        "genome_hash": genome.genome_hash,
        "selection_fitness": score,
        "folds": fold_rows,
        "passed_fold_count": sum(int(row["passed"]) for row in fold_rows),
        "positive_fold_count": sum(
            int(float(_mapping(row.get("metrics")).get("total_return", 0.0)) > 0.0)
            for row in fold_rows
        ),
    }
    cache[genome.genome_hash] = row
    return row


def _selection_fold_passed(metrics: Mapping[str, Any]) -> bool:
    return bool(
        float(metrics.get("total_return", 0.0)) > 0.0
        and float(metrics.get("profit_factor", 0.0)) >= 1.05
        and float(metrics.get("max_drawdown", -1.0)) >= -0.25
        and MIN_SELECTION_TRADES_PER_DAY
        <= float(metrics.get("trades_per_day", 0.0))
        <= MAX_SELECTION_TRADES_PER_DAY
        and MIN_SELECTION_EXPOSURE
        <= float(metrics.get("exposure_ratio", 0.0))
        <= MAX_SELECTION_EXPOSURE
        and not bool(metrics.get("bankruptcy"))
    )


def _selection_fitness(folds: Sequence[Mapping[str, Any]], genome: HighYield5mGenome) -> float:
    metrics = [_mapping(row.get("metrics")) for row in folds]
    passed = sum(int(bool(row.get("passed"))) for row in folds)
    positive = sum(int(float(row.get("total_return", 0.0)) > 0.0) for row in metrics)
    returns = [float(row.get("total_return", 0.0)) for row in metrics]
    sharpes = [float(row.get("sharpe", 0.0)) for row in metrics]
    profit_factors = [min(3.0, float(row.get("profit_factor", 0.0))) for row in metrics]
    drawdowns = [float(row.get("max_drawdown", -1.0)) for row in metrics]
    trades = [float(row.get("trades_per_day", 0.0)) for row in metrics]
    exposures = [float(row.get("exposure_ratio", 0.0)) for row in metrics]
    score = 12.0 * passed + 4.0 * positive
    score += 80.0 * float(np.median(returns))
    score += 1.5 * float(np.median(sharpes))
    score += 2.0 * (float(np.median(profit_factors)) - 1.0)
    score += 20.0 * min(drawdowns)
    score -= 2.0 * max(0.0, genome.max_leverage - 1.0)
    median_trades = float(np.median(trades))
    if median_trades < MIN_SELECTION_TRADES_PER_DAY:
        score -= 20.0 * (MIN_SELECTION_TRADES_PER_DAY - median_trades)
    if median_trades > MAX_SELECTION_TRADES_PER_DAY:
        score -= median_trades - MAX_SELECTION_TRADES_PER_DAY
    median_exposure = float(np.median(exposures))
    if median_exposure < MIN_SELECTION_EXPOSURE:
        score -= 100.0 * (MIN_SELECTION_EXPOSURE - median_exposure)
    if median_exposure > MAX_SELECTION_EXPOSURE:
        score -= 20.0 * (median_exposure - MAX_SELECTION_EXPOSURE)
    return float(score)


def _retention_reasons(
    *,
    selection: Mapping[str, Any],
    cost_stress: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    fold_count = len(selection.get("folds", [])) or 4
    return [
        *_selection_gate_reasons(selection=selection, fold_count=fold_count),
        *_holdout_metric_reasons(
            cost_stress=cost_stress,
            prefix="diagnostic_holdout",
        ),
    ]


def _selection_gate_reasons(
    *,
    selection: Mapping[str, Any],
    fold_count: int,
) -> list[str]:
    required_passed = max(1, fold_count - 1)
    reasons: list[str] = []
    if int(selection.get("passed_fold_count", 0)) < required_passed:
        reasons.append(
            f"walk_forward_passed_folds_below_{required_passed}_of_{fold_count}"
        )
    if int(selection.get("positive_fold_count", 0)) < fold_count:
        reasons.append(f"walk_forward_positive_folds_below_{fold_count}_of_{fold_count}")
    return reasons


def _holdout_metric_reasons(
    *,
    cost_stress: Mapping[str, Mapping[str, Any]],
    prefix: str,
) -> list[str]:
    reasons: list[str] = []
    base = _mapping(cost_stress.get("base"))
    conservative = _mapping(cost_stress.get("conservative"))
    stress = _mapping(cost_stress.get("stress"))
    if float(base.get("total_return", 0.0)) <= 0.0:
        reasons.append(f"{prefix}_base_total_return_non_positive")
    if float(base.get("profit_factor", 0.0)) < 1.10:
        reasons.append(f"{prefix}_base_profit_factor_below_1p10")
    if float(base.get("max_drawdown", -1.0)) < -0.20:
        reasons.append(f"{prefix}_base_drawdown_below_minus_20pct")
    if float(base.get("trades_per_day", 0.0)) < MIN_SELECTION_TRADES_PER_DAY:
        reasons.append(f"{prefix}_trades_per_day_below_0p35")
    if not MIN_SELECTION_EXPOSURE <= float(base.get("exposure_ratio", 0.0)) <= MAX_SELECTION_EXPOSURE:
        reasons.append(f"{prefix}_exposure_outside_1_to_90pct")
    if float(base.get("long_exposure_ratio", 0.0)) < 0.002:
        reasons.append(f"{prefix}_long_side_not_observed")
    if float(base.get("short_exposure_ratio", 0.0)) < 0.002:
        reasons.append(f"{prefix}_short_side_not_observed")
    if float(conservative.get("total_return", 0.0)) <= 0.0:
        reasons.append(f"{prefix}_conservative_cost_total_return_non_positive")
    if float(stress.get("total_return", 0.0)) <= 0.0:
        reasons.append(f"{prefix}_stress_cost_total_return_non_positive")
    if float(stress.get("profit_factor", 0.0)) < 1.0:
        reasons.append(f"{prefix}_stress_cost_profit_factor_below_1p0")
    if bool(base.get("bankruptcy")):
        reasons.append(f"{prefix}_bankruptcy")
    return reasons


def _initial_population(rng: random.Random, size: int) -> list[HighYield5mGenome]:
    anchors = [
        HighYield5mGenome(288, 0.5, 20, 2.0, 12, 0, 0.0, 288, 1152, 288, 120.0, 2.5, 25.0),
        HighYield5mGenome(144, 0.5, 20, 2.5, 12, 6, 0.1, 288, 1152, 576, 90.0, 2.0, 20.0),
        HighYield5mGenome(72, 0.5, 14, 2.0, 6, 3, 0.1, 576, 2304, 288, 60.0, 1.5, 15.0),
        HighYield5mGenome(48, 0.25, 14, 1.5, 6, 3, 0.25, 288, 1152, 288, 40.0, 1.0, 10.0),
    ]
    return _dedupe_and_fill(anchors, rng, size)


def _random_genome(rng: random.Random) -> HighYield5mGenome:
    regime_fast, regime_slow = rng.choice(REGIME_PAIRS)
    return HighYield5mGenome(
        entry_window=rng.choice(ENTRY_WINDOWS),
        exit_ratio=rng.choice(EXIT_RATIOS),
        atr_window=rng.choice(ATR_WINDOWS),
        atr_mult=rng.choice(ATR_MULTS),
        cooldown_bars=rng.choice(COOLDOWN_BARS),
        failed_breakout_bars=rng.choice(FAILED_BREAKOUT_BARS),
        breakout_buffer_atr=rng.choice(BREAKOUT_BUFFER_ATR),
        regime_fast_bars=regime_fast,
        regime_slow_bars=regime_slow,
        volatility_window_bars=rng.choice(VOLATILITY_WINDOWS),
        target_volatility_pct=rng.choice(TARGET_VOLATILITY_PCT),
        max_leverage=rng.choice(MAX_LEVERAGES),
        drawdown_gate_pct=rng.choice(DRAWDOWN_GATES_PCT),
    )


def _tournament(evaluated: Sequence[Mapping[str, Any]], rng: random.Random) -> HighYield5mGenome:
    sample = rng.sample(list(evaluated), k=min(4, len(evaluated)))
    winner = max(sample, key=lambda row: (float(row["selection_fitness"]), row["genome_hash"]))
    return winner["genome"]


def _crossover(
    left: HighYield5mGenome,
    right: HighYield5mGenome,
    rng: random.Random,
) -> HighYield5mGenome:
    values: dict[str, Any] = {}
    for field in (
        "entry_window",
        "exit_ratio",
        "atr_window",
        "atr_mult",
        "cooldown_bars",
        "failed_breakout_bars",
        "breakout_buffer_atr",
        "volatility_window_bars",
        "target_volatility_pct",
        "max_leverage",
        "drawdown_gate_pct",
    ):
        values[field] = getattr(left if rng.random() < 0.5 else right, field)
    regime = left if rng.random() < 0.5 else right
    values["regime_fast_bars"] = regime.regime_fast_bars
    values["regime_slow_bars"] = regime.regime_slow_bars
    return HighYield5mGenome(**values)


def _mutate(genome: HighYield5mGenome, rng: random.Random) -> HighYield5mGenome:
    fields = [
        "entry_window",
        "exit_ratio",
        "atr_window",
        "atr_mult",
        "cooldown_bars",
        "failed_breakout_bars",
        "breakout_buffer_atr",
        "regime_pair",
        "volatility_window_bars",
        "target_volatility_pct",
        "max_leverage",
        "drawdown_gate_pct",
    ]
    result = genome
    for field in rng.sample(fields, k=1 if rng.random() < 0.7 else 2):
        if field == "regime_pair":
            fast, slow = rng.choice(REGIME_PAIRS)
            result = replace(result, regime_fast_bars=fast, regime_slow_bars=slow)
        else:
            choices = {
                "entry_window": ENTRY_WINDOWS,
                "exit_ratio": EXIT_RATIOS,
                "atr_window": ATR_WINDOWS,
                "atr_mult": ATR_MULTS,
                "cooldown_bars": COOLDOWN_BARS,
                "failed_breakout_bars": FAILED_BREAKOUT_BARS,
                "breakout_buffer_atr": BREAKOUT_BUFFER_ATR,
                "volatility_window_bars": VOLATILITY_WINDOWS,
                "target_volatility_pct": TARGET_VOLATILITY_PCT,
                "max_leverage": MAX_LEVERAGES,
                "drawdown_gate_pct": DRAWDOWN_GATES_PCT,
            }[field]
            result = replace(result, **{field: rng.choice(choices)})
    return result


def _dedupe_and_fill(
    genomes: Sequence[HighYield5mGenome],
    rng: random.Random,
    size: int,
) -> list[HighYield5mGenome]:
    unique: dict[str, HighYield5mGenome] = {genome.genome_hash: genome for genome in genomes}
    attempts = 0
    while len(unique) < size and attempts < size * 100:
        genome = _random_genome(rng)
        unique.setdefault(genome.genome_hash, genome)
        attempts += 1
    if len(unique) < size:
        raise HighYield5mGAMiningError("ga_population_uniqueness_exhausted")
    return list(unique.values())[:size]


def _stateful_donchian_direction(
    *,
    close: pd.Series,
    atr: pd.Series,
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series,
    short_exit: pd.Series,
    long_failure_line: pd.Series,
    short_failure_line: pd.Series,
    atr_mult: float,
    cooldown_bars: int,
    failed_breakout_bars: int,
) -> pd.Series:
    prices = close.to_numpy(dtype=float)
    atr_values = atr.reindex(close.index).to_numpy(dtype=float)
    long_entries = long_entry.reindex(close.index).fillna(False).to_numpy(dtype=bool)
    long_exits = long_exit.reindex(close.index).fillna(False).to_numpy(dtype=bool)
    short_entries = short_entry.reindex(close.index).fillna(False).to_numpy(dtype=bool)
    short_exits = short_exit.reindex(close.index).fillna(False).to_numpy(dtype=bool)
    upper = long_failure_line.reindex(close.index).to_numpy(dtype=float)
    lower = short_failure_line.reindex(close.index).to_numpy(dtype=float)
    output = np.zeros(len(close), dtype=float)
    position = 0.0
    high_since_entry = math.nan
    low_since_entry = math.nan
    entry_age = 0
    cooldown_remaining = 0
    for pos, price in enumerate(prices):
        le = bool(long_entries[pos])
        lx = bool(long_exits[pos])
        se = bool(short_entries[pos])
        sx = bool(short_exits[pos])
        current_atr = atr_values[pos]
        if position > 0.0:
            entry_age += 1
            high_since_entry = max(high_since_entry, price) if math.isfinite(high_since_entry) else price
            if math.isfinite(current_atr) and price < high_since_entry - atr_mult * current_atr:
                lx = True
            if failed_breakout_bars > 0 and entry_age <= failed_breakout_bars:
                if math.isfinite(upper[pos]) and price < upper[pos]:
                    lx = True
        elif position < 0.0:
            entry_age += 1
            low_since_entry = min(low_since_entry, price) if math.isfinite(low_since_entry) else price
            if math.isfinite(current_atr) and price > low_since_entry + atr_mult * current_atr:
                sx = True
            if failed_breakout_bars > 0 and entry_age <= failed_breakout_bars:
                if math.isfinite(lower[pos]) and price > lower[pos]:
                    sx = True

        exited = False
        if position > 0.0 and (lx or se):
            position = 0.0
            high_since_entry = math.nan
            entry_age = 0
            exited = True
        elif position < 0.0 and (sx or le):
            position = 0.0
            low_since_entry = math.nan
            entry_age = 0
            exited = True
        if exited:
            cooldown_remaining = max(0, cooldown_bars)
        if position == 0.0 and not exited and cooldown_remaining <= 0:
            if le and not se:
                position = 1.0
                high_since_entry = price
                entry_age = 0
            elif se and not le:
                position = -1.0
                low_since_entry = price
                entry_age = 0
        output[pos] = position
        if position == 0.0 and cooldown_remaining > 0:
            cooldown_remaining -= 1
    return pd.Series(output, index=close.index, name="direction_at_completed_5m_close")


def _metrics_from_simulation(
    *,
    index: pd.DatetimeIndex,
    positions: np.ndarray,
    net: np.ndarray,
    equity: np.ndarray,
    turnover: np.ndarray,
    fee: np.ndarray,
    spread: np.ndarray,
    slippage: np.ndarray,
    trade_count: int,
    fill_count: int,
    drawdown_lock_count: int,
    bankruptcy: bool,
) -> dict[str, Any]:
    total_return = float(equity[-1] - 1.0) if len(equity) else 0.0
    years = len(index) / ANNUAL_5M_BARS
    annualized_return = 0.0
    if years > 0.0 and equity[-1] > 0.0:
        annualized_return = float(math.exp(np.clip(math.log(equity[-1]) / years, -20.0, 20.0)) - 1.0)
    annualized_volatility = float(np.std(net, ddof=0) * math.sqrt(ANNUAL_5M_BARS)) if len(net) else 0.0
    sharpe = (
        float(np.mean(net) / np.std(net, ddof=0) * math.sqrt(ANNUAL_5M_BARS))
        if len(net) and np.std(net, ddof=0) > 0.0
        else 0.0
    )
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    equity_with_start = np.concatenate(([1.0], equity))
    max_drawdown = float(np.min(equity_with_start / peaks - 1.0))
    positive = float(net[net > 0.0].sum())
    negative = float(-net[net < 0.0].sum())
    profit_factor = positive / negative if negative > 0.0 else (999.0 if positive > 0.0 else 0.0)
    days = max(len(index) / 288.0, 1.0 / 288.0)
    active = np.abs(positions) > 1e-12
    holding_lengths = _holding_lengths(positions)
    return {
        "start": index[0].isoformat() if len(index) else None,
        "end": index[-1].isoformat() if len(index) else None,
        "row_count": len(index),
        "total_return": _round(total_return),
        "annualized_return": _round(annualized_return),
        "annualized_volatility": _round(annualized_volatility),
        "sharpe": _round(sharpe),
        "profit_factor": _round(profit_factor),
        "max_drawdown": _round(max_drawdown),
        "turnover": _round(float(turnover.sum())),
        "fee_drag": _round(float(fee.sum())),
        "spread_drag": _round(float(spread.sum())),
        "slippage_drag": _round(float(slippage.sum())),
        "trade_count": int(trade_count),
        "fill_count": int(fill_count),
        "trades_per_day": _round(trade_count / days),
        "exposure_ratio": _round(float(active.mean()) if len(active) else 0.0),
        "long_exposure_ratio": _round(float((positions > 1e-12).mean()) if len(positions) else 0.0),
        "short_exposure_ratio": _round(float((positions < -1e-12).mean()) if len(positions) else 0.0),
        "average_absolute_leverage": _round(float(np.mean(np.abs(positions))) if len(positions) else 0.0),
        "max_absolute_leverage": _round(float(np.max(np.abs(positions))) if len(positions) else 0.0),
        "average_holding_bars": _round(float(np.mean(holding_lengths)) if holding_lengths else 0.0),
        "drawdown_lock_count": int(drawdown_lock_count),
        "bankruptcy": bool(bankruptcy),
    }


def _ledger_summary(
    *,
    index: pd.DatetimeIndex,
    positions: np.ndarray,
    gross: np.ndarray,
    net: np.ndarray,
    equity: np.ndarray,
    fee: np.ndarray,
    spread: np.ndarray,
    slippage: np.ndarray,
    fill_count: int,
    fill_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    digest_payload = {
        "start": index[0].isoformat() if len(index) else None,
        "end": index[-1].isoformat() if len(index) else None,
        "rows": len(index),
        "position_sha256": hashlib.sha256(np.asarray(positions, dtype="<f8").tobytes()).hexdigest(),
        "net_sha256": hashlib.sha256(np.asarray(net, dtype="<f8").tobytes()).hexdigest(),
        "equity_sha256": hashlib.sha256(np.asarray(equity, dtype="<f8").tobytes()).hexdigest(),
        "fill_count": int(fill_count),
    }
    return {
        "model": "event_fill_position_cash_normalized_equity_next_open_v1",
        "pnl_derived_from_fills_positions_cash": True,
        "signal_at_completed_close_execution_at_next_open": True,
        "reconciled": bool(
            len(positions) == len(net) == len(equity) == len(index)
            and np.isfinite(net).all()
            and np.isfinite(equity).all()
        ),
        "position_ledger_row_count": len(positions),
        "cash_ledger_row_count": len(equity),
        "fill_count": int(fill_count),
        "ending_equity": _round(float(equity[-1]) if len(equity) else 1.0),
        "gross_return_sum": _round(float(gross.sum())),
        "fee_return_sum": _round(float(fee.sum())),
        "spread_return_sum": _round(float(spread.sum())),
        "slippage_return_sum": _round(float(slippage.sum())),
        "fill_samples_first": [dict(row) for row in fill_samples],
        "full_ledger_committed": False,
        "full_ledger_omission_reason": "large_research_ledger_not_committed_hash_counts_and_samples_only",
        "ledger_sha256": hashlib.sha256(_stable_json(digest_payload).encode("utf-8")).hexdigest(),
    }


def _gene_space() -> dict[str, Any]:
    return {
        "entry_windows_5m_bars": list(ENTRY_WINDOWS),
        "entry_horizon_hours": [_round(value / 12.0, 2) for value in ENTRY_WINDOWS],
        "exit_ratios": list(EXIT_RATIOS),
        "atr_windows": list(ATR_WINDOWS),
        "atr_multipliers": list(ATR_MULTS),
        "cooldown_bars": list(COOLDOWN_BARS),
        "failed_breakout_bars_zero_is_disabled": list(FAILED_BREAKOUT_BARS),
        "breakout_buffer_atr": list(BREAKOUT_BUFFER_ATR),
        "regime_fast_slow_5m_bars": [list(pair) for pair in REGIME_PAIRS],
        "regime_horizon_days": [[_round(a / 288.0, 2), _round(b / 288.0, 2)] for a, b in REGIME_PAIRS],
        "volatility_windows": list(VOLATILITY_WINDOWS),
        "target_volatility_pct": list(TARGET_VOLATILITY_PCT),
        "max_leverage": list(MAX_LEVERAGES),
        "drawdown_gate_pct": list(DRAWDOWN_GATES_PCT),
    }


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window, min_periods=window).mean()


def _holding_lengths(positions: np.ndarray) -> list[int]:
    lengths: list[int] = []
    current = 0
    previous_side = 0.0
    for value in positions:
        side = 0.0 if abs(value) <= 1e-12 else math.copysign(1.0, value)
        if side == 0.0:
            if current:
                lengths.append(current)
            current = 0
        elif side == previous_side:
            current += 1
        else:
            if current:
                lengths.append(current)
            current = 1
        previous_side = side
    if current:
        lengths.append(current)
    return lengths


def _require_ohlcv(frame: pd.DataFrame) -> None:
    missing = [column for column in ("open", "high", "low", "close", "volume") if column not in frame]
    if missing:
        raise HighYield5mGAMiningError(f"ohlcv_columns_missing:{','.join(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise HighYield5mGAMiningError("ohlcv_datetime_index_must_be_timezone_aware")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise HighYield5mGAMiningError("ohlcv_index_not_strictly_increasing")


def _git_commit_hash(repo_root: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root or Path.cwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _round(value: Any, digits: int = 8) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(parsed, digits)


def _pct(value: Any) -> str:
    return f"{100.0 * _round(value):.2f}%"
