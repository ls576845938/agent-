from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from quant_crypto.adapters.btc_runtime_artifact_store import (
    BTCRuntimeArtifactStoreError,
    BTCRuntimeArtifactWriter,
)


SCHEMA_VERSION = "btc_strategy_history_api_v1"
SNAPSHOT_SCHEMA_VERSION = "btc_strategy_history_snapshot_index_v1"
POINTER_SCHEMA_VERSION = "btc_strategy_history_latest_pointer_v1"
PROVENANCE_SCHEMA_VERSION = "btc_strategy_history_provenance_v2"
DATA_LINEAGE_SCHEMA_VERSION = "btc_strategy_history_data_lineage_v1"
SOURCE_SCHEMA_VERSION = "btc_long_short_top5_review_v1"
SOURCE_STATUS = "complete_research_only"
SOURCE_DECISION = "btc_long_short_top5_review_research_only_no_paper_no_live"
STABLE_STRATEGY_ID = "long_short_donchian_top5"
OKX_NATIVE_STRATEGY_ID = "long_short_donchian_top5_okx_native"
OKX_NATIVE_PREFIX = "okx_native_"
SOURCE_REPORT_RELATIVE_PATH = Path(
    "artifacts/btc_long_short_top5_review/latest/"
    "btc_long_short_top5_review_report.json"
)
HISTORY_PREFIX = Path("artifacts/btc_strategy_history")
HISTORY_INDEX_PATH = HISTORY_PREFIX / "index.json"
HISTORY_POINTER_PATH = HISTORY_PREFIX / "latest_pointer.json"
MAX_HISTORY_RUNS = 50

_SAFETY_KEYS = (
    "paper_queue_write_allowed",
    "paper_allowed",
    "paper_order_intake_allowed",
    "live_unlock_allowed",
    "live_order_allowed",
    "broker_access_allowed",
    "broker_or_order_allowed",
    "oms_access_allowed",
    "order_endpoint_used",
    "private_endpoint_used",
    "real_order_submitted",
)
_SOURCE_FALSE_GUARDRAILS = (
    "broker_access_allowed",
    "live_order_allowed",
    "live_unlock_allowed",
    "oms_access_allowed",
    "order_endpoint_used",
    "paper_candidate_created",
    "paper_queue_write_allowed",
    "private_endpoint_used",
    "real_order_submitted",
)


class BTCStrategyHistoryNotFound(LookupError):
    pass


class BTCStrategyHistoryInvalid(ValueError):
    pass


class BTCStrategyHistoryUnavailable(RuntimeError):
    pass


_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
_DATA_LINEAGE_FIELDS = (
    "market_db_path",
    "derivatives_rows_path",
    "exchange",
    "symbol",
    "source_interval",
    "decision_interval",
    "bar_4h_start",
    "bar_4h_end",
    "market_1h_rows",
    "bar_4h_rows",
    "bar_1d_rows",
    "bar_1w_rows",
    "bar_1mo_rows",
)


def _git_revision(repo_root: Path, revision: str) -> str:
    """Resolve a caller/report revision to a full commit without shell parsing."""
    value = str(revision or "").strip().lower()
    if _COMMIT_RE.fullmatch(value) is None:
        raise BTCStrategyHistoryInvalid("BTC strategy history commit identity invalid")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history Git provenance unavailable"
        ) from exc
    resolved = result.stdout.strip().lower()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", resolved) is None:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history commit identity cannot be resolved"
        )
    return resolved


def _git_head(repo_root: Path) -> str:
    return _git_revision(repo_root, _git_text(repo_root, "rev-parse", "HEAD"))


def _git_text(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history Git provenance unavailable"
        ) from exc
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history Git provenance unavailable"
        )
    return value


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history Git provenance unavailable"
        ) from exc
    return result.returncode == 0


def _repo_data_path(repo_root: Path, value: Any) -> str:
    raw = str(value or "").strip()
    pure = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or Path(raw).is_absolute()
        or pure.as_posix() != raw
        or any(part in {"", ".", ".."} for part in pure.parts)
        or len(pure.parts) < 2
        or pure.parts[0] != "data"
    ):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history data lineage path invalid"
        )
    root = repo_root.resolve()
    resolved = (root / Path(*pure.parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history data lineage path escapes repository"
        ) from exc
    return pure.as_posix()


def _data_lineage(
    report: Mapping[str, Any],
    repo_root: Path,
    *,
    require_files: bool,
) -> dict[str, Any]:
    input_block = _mapping(report.get("input"))
    missing = [key for key in _DATA_LINEAGE_FIELDS if key not in input_block]
    if missing:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history data lineage fields missing: "
            + ", ".join(missing)
        )
    market_path = _repo_data_path(repo_root, input_block.get("market_db_path"))
    derivatives_path = _repo_data_path(
        repo_root,
        input_block.get("derivatives_rows_path"),
    )
    if require_files:
        for relative in (market_path, derivatives_path):
            if not (repo_root / Path(*PurePosixPath(relative).parts)).is_file():
                raise BTCStrategyHistoryInvalid(
                    f"BTC strategy history data lineage file unavailable: {relative}"
                )
    payload = {
        key: input_block.get(key)
        for key in _DATA_LINEAGE_FIELDS
    }
    return {
        "schema_version": DATA_LINEAGE_SCHEMA_VERSION,
        **payload,
        "market_db_path": market_path,
        "derivatives_rows_path": derivatives_path,
        "data_lineage_sha256": _stable_hash(payload),
    }


def _report_provenance(
    report: Mapping[str, Any],
    repo_root: Path,
    *,
    require_data_files: bool,
) -> dict[str, Any]:
    code_commit_raw = str(report.get("code_commit") or "").strip()
    source = _mapping(report.get("source"))
    source_code_commit_raw = str(source.get("source_code_commit") or "").strip()
    code_commit = _git_revision(repo_root, code_commit_raw)
    source_code_commit = _git_revision(repo_root, source_code_commit_raw)
    if not _git_is_ancestor(repo_root, source_code_commit, code_commit):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source code lineage is not an ancestor of report code"
        )
    return {
        "code_commit": code_commit,
        "source_code_commit": source_code_commit,
        "data_lineage": _data_lineage(
            report,
            repo_root,
            require_files=require_data_files,
        ),
    }


def _project_artifact_freshness(
    report: Mapping[str, Any],
    artifact_reader: Any,
) -> dict[str, Any]:
    code_commit_raw = str(report.get("code_commit") or "").strip()
    source_code_commit_raw = str(
        _mapping(report.get("source")).get("source_code_commit") or ""
    ).strip()
    result: dict[str, Any] = {
        "status": "historical_research_only_not_current_head",
        "current_head_match": False,
        "code_commit": code_commit_raw,
        "source_code_commit": source_code_commit_raw,
        "current_head": "",
        "source_code_lineage_valid": False,
        "data_lineage_valid": False,
        "data_lineage_sha256": "",
        "report_sha256": "",
        "generated_at_utc": str(report.get("generated_at_utc") or ""),
    }
    root = getattr(artifact_reader, "source_repo_root", None)
    if root is None:
        return result
    try:
        provenance = _report_provenance(
            report,
            Path(root),
            require_data_files=True,
        )
        current_head = _git_head(Path(root))
    except BTCStrategyHistoryInvalid:
        return result
    lineage = provenance["data_lineage"]
    result.update(
        {
            "code_commit": provenance["code_commit"],
            "source_code_commit": provenance["source_code_commit"],
            "current_head": current_head,
            "source_code_lineage_valid": True,
            "data_lineage_valid": True,
            "data_lineage_sha256": str(
                lineage.get("data_lineage_sha256") or ""
            ),
        }
    )
    if current_head == provenance["code_commit"]:
        result.update(
            {
                "status": "current_head_compatible_research_only",
                "current_head_match": True,
            }
        )
    return result


def publish_btc_strategy_history_snapshot(
    writer: BTCRuntimeArtifactWriter,
    *,
    source_path: Path,
    source_commit: str,
    producer_commit: str,
) -> dict[str, Any]:
    """Publish a content-addressed, research-only Top5 report snapshot."""
    try:
        source_bytes = source_path.resolve(strict=True).read_bytes()
    except OSError as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report is unavailable"
        ) from exc
    try:
        report = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report is invalid JSON"
        ) from exc
    if not isinstance(report, dict):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report must be a JSON object"
        )
    validate_btc_strategy_history_source_report(report)
    reviews = _candidate_reviews(report)
    candidate_ids = [_required_text(item, "candidate_id") for item in reviews]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report has duplicate candidate IDs"
        )
    repo_root = writer.source_repo_root.resolve()
    provenance = _report_provenance(
        report,
        repo_root,
        require_data_files=True,
    )
    current_head = _git_head(repo_root)
    requested_source_commit = _git_revision(repo_root, source_commit)
    requested_producer_commit = _git_revision(repo_root, producer_commit)
    if requested_source_commit != provenance["code_commit"]:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source_commit does not match report code_commit"
        )
    if requested_producer_commit != current_head:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history producer_commit must match current Git HEAD"
        )
    if not _git_is_ancestor(repo_root, requested_source_commit, current_head):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history report code is not an ancestor of producer HEAD"
        )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    report_path = HISTORY_PREFIX / "runs" / source_sha256 / "report.json"
    published_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "source_sha256": source_sha256,
        "report_path": report_path.as_posix(),
        "report_schema_version": str(report.get("schema_version") or ""),
        "generated_at_utc": str(report.get("generated_at_utc") or ""),
        "published_at_utc": published_at,
        "source_commit": requested_source_commit,
        "producer_commit": current_head,
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_code_commit": provenance["source_code_commit"],
        "data_lineage": provenance["data_lineage"],
        "candidate_ids": candidate_ids,
        "research_status": "research_only",
        "relationship_policy": {
            STABLE_STRATEGY_ID: "exact_candidate_historical_research_report",
            OKX_NATIVE_STRATEGY_ID: "same_formula_historical_research_baseline",
        },
        "safety": _false_safety(),
    }

    with writer.exclusive() as session:
        report_target = writer.resolve(report_path)
        if report_target.exists():
            if hashlib.sha256(writer.read_bytes(report_path)).hexdigest() != source_sha256:
                raise BTCStrategyHistoryInvalid(
                    "content-addressed BTC strategy history snapshot hash mismatch"
                )
        else:
            session.write_bytes_atomic(report_path, source_bytes)

        try:
            existing_index = writer.read_json(HISTORY_INDEX_PATH)
        except BTCRuntimeArtifactStoreError:
            existing_index = {}
        existing_runs = [
            item
            for item in _list(existing_index.get("runs"))
            if isinstance(item, dict)
            and str(item.get("source_sha256") or "") != source_sha256
        ]
        index = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "complete_research_only",
            "decision": "history_snapshot_index_read_only_no_paper_no_live",
            "updated_at_utc": published_at,
            "runs": [entry, *existing_runs][:MAX_HISTORY_RUNS],
            "safety": _false_safety(),
        }
        index_bytes = _encoded_json(index)
        index_sha256 = hashlib.sha256(index_bytes).hexdigest()
        session.write_bytes_atomic(HISTORY_INDEX_PATH, index_bytes)
        pointer = {
            "schema_version": POINTER_SCHEMA_VERSION,
            "status": "complete_research_only",
            "index_path": HISTORY_INDEX_PATH.as_posix(),
            "index_sha256": index_sha256,
            "latest_source_sha256": source_sha256,
            "latest_report_path": report_path.as_posix(),
            "candidate_ids": candidate_ids,
            "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
            "latest_source_commit": requested_source_commit,
            "latest_producer_commit": current_head,
            "data_lineage_sha256": provenance["data_lineage"][
                "data_lineage_sha256"
            ],
            "updated_at_utc": published_at,
            "safety": _false_safety(),
        }
        session.write_json_atomic(HISTORY_POINTER_PATH, pointer)

    return {
        "schema_version": "btc_strategy_history_publish_receipt_v1",
        "status": "published_research_only",
        "decision": "history_snapshot_published_no_paper_no_live",
        "source_sha256": source_sha256,
        "report_path": report_path.as_posix(),
        "index_path": HISTORY_INDEX_PATH.as_posix(),
        "latest_pointer_path": HISTORY_POINTER_PATH.as_posix(),
        "candidate_ids": candidate_ids,
        "source_commit": requested_source_commit,
        "producer_commit": current_head,
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "source_code_commit": provenance["source_code_commit"],
        "data_lineage": provenance["data_lineage"],
        "safety": _false_safety(),
    }


def load_btc_strategy_history_catalog(artifact_reader: Any) -> dict[str, Any]:
    pointer, index = _load_history_index(artifact_reader)
    snapshots = _load_indexed_reports(artifact_reader, index=index, pointer=pointer)
    latest_snapshot = next(
        (
            item
            for item in snapshots
            if item[1] == str(pointer.get("latest_source_sha256") or "")
        ),
        None,
    )
    artifact_freshness = (
        _project_artifact_freshness(latest_snapshot[0], artifact_reader)
        if latest_snapshot is not None
        else {
            "status": "historical_research_only_not_current_head",
            "current_head_match": False,
        }
    )
    if latest_snapshot is not None:
        artifact_freshness["report_sha256"] = latest_snapshot[1]
    candidates = []
    seen_candidate_ids: set[str] = set()
    for report, report_sha256, _ in snapshots:
        for review in _candidate_reviews(report):
            candidate_id = _required_text(review, "candidate_id")
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            stable_runs = _history_runs_for_candidate(
                snapshots,
                source_candidate_id=candidate_id,
                candidate_id=candidate_id,
                relationship="exact_candidate_historical_research_report",
                relationship_label="历史研究回测",
            )
            native_candidate_id = f"{OKX_NATIVE_PREFIX}{candidate_id}"
            native_runs = _history_runs_for_candidate(
                snapshots,
                source_candidate_id=candidate_id,
                candidate_id=native_candidate_id,
                relationship="same_formula_historical_research_baseline",
                relationship_label="同公式历史研究基线（非 OKX-native 原生回测）",
            )
            stable = _catalog_entry(
                report=report,
                report_sha256=report_sha256,
                strategy_id=STABLE_STRATEGY_ID,
                candidate_id=candidate_id,
                source_candidate_id=candidate_id,
                review=review,
                relationship="exact_candidate_historical_research_report",
                label="历史研究回测",
                history_runs=stable_runs,
            )
            native = _catalog_entry(
                report=report,
                report_sha256=report_sha256,
                strategy_id=OKX_NATIVE_STRATEGY_ID,
                candidate_id=native_candidate_id,
                source_candidate_id=candidate_id,
                review=review,
                relationship="same_formula_historical_research_baseline",
                label="同公式历史研究基线（非 OKX-native 原生回测）",
                history_runs=native_runs,
            )
            candidates.extend((stable, native))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_research_only",
        "decision": "history_catalog_read_only_no_paper_no_live",
        "candidates": candidates,
        "artifact_freshness": artifact_freshness,
        "safety": _false_safety(),
    }


def load_btc_strategy_history(
    artifact_reader: Any,
    *,
    strategy_id: str,
    candidate_id: str,
    run_id: str = "",
) -> dict[str, Any]:
    normalized_strategy_id, normalized_candidate_id = _validate_request_identity(
        strategy_id,
        candidate_id,
    )
    source_candidate_id, relationship, relationship_label = _source_identity(
        normalized_strategy_id,
        normalized_candidate_id,
    )
    pointer, index = _load_history_index(artifact_reader)
    snapshots = _load_indexed_reports(artifact_reader, index=index, pointer=pointer)
    matching_snapshots = _matching_candidate_snapshots(
        snapshots,
        source_candidate_id=source_candidate_id,
        candidate_id=normalized_candidate_id,
        relationship=relationship,
        relationship_label=relationship_label,
    )
    if not matching_snapshots:
        raise BTCStrategyHistoryNotFound(
            f"BTC strategy history candidate not found: "
            f"{normalized_strategy_id}/{normalized_candidate_id}"
        )
    selected = next(
        (
            item
            for item in matching_snapshots
            if not run_id or item[4]["run_id"] == run_id
        ),
        None,
    )
    if selected is None:
        raise BTCStrategyHistoryNotFound(
            f"BTC strategy history run not found for candidate: {run_id}"
        )
    report, report_sha256, report_path, review, history_run = selected
    history_runs = [item[4] for item in matching_snapshots]

    params = _mapping(review.get("params"))
    params_hash = _stable_hash(params)
    blockers = _blockers(report, review, relationship)
    artifact_freshness = _project_artifact_freshness(report, artifact_reader)
    artifact_freshness["report_sha256"] = report_sha256
    metrics = dict(_mapping(review.get("full_metrics")))
    source = _mapping(report.get("source"))
    report_input = _mapping(report.get("input"))
    generated_at = str(report.get("generated_at_utc") or "")
    code_commit = str(report.get("code_commit") or source.get("source_code_commit") or "")
    strategy_version = (
        "btc_long_short_donchian_top5_okx_native@1.0.0"
        if normalized_strategy_id == OKX_NATIVE_STRATEGY_ID
        else "btc_long_short_donchian_top5@1.0.0"
    )
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_research_only",
        "decision": str(
            report.get("decision")
            or "btc_strategy_history_research_only_no_paper_no_live"
        ),
        "run_id": history_run["run_id"],
        "strategy_identity": {
            "strategy_id": normalized_strategy_id,
            "candidate_id": normalized_candidate_id,
            "source_candidate_id": source_candidate_id,
            "strategy_version": strategy_version,
            "params_hash": params_hash,
            "timeframe": "completed_1h_to_4h",
            "signal_data_venue": str(report_input.get("exchange") or "binance_spot"),
            "signal_instrument": str(report_input.get("symbol") or "BTCUSDT"),
            "execution_venue": "research_simulation",
            "execution_instrument": "simulated_usdt_perpetual_research_only",
        },
        "metrics": metrics,
        "params": params,
        "cost_model": {
            "units": "return_pct",
            "trading_cost_return_pct": metrics.get("trading_cost_return_pct"),
            "fee_return_pct": metrics.get("fee_return_pct"),
            "funding_return_pct": metrics.get("funding_return_pct"),
            "cash_cost_components_available": False,
        },
        "checks": {
            "source_artifacts_present": True,
            "source_data_local_and_network_free": True,
            "source_no_lookahead_passed": False,
            "holdout_locked_for_this_review": bool(
                _mapping(report.get("review_design")).get(
                    "holdout_locked_for_this_review"
                )
            ),
            "clean_pre_selection_holdout": bool(
                _mapping(report.get("review_design")).get(
                    "clean_pre_selection_holdout"
                )
            ),
        },
        "artifact_freshness": {
            **artifact_freshness,
        },
        "manifest": {
            "path": report_path,
            "schema_version": str(report.get("schema_version") or ""),
            "sha256": report_sha256,
        },
        "mapping": {
            "relationship": relationship,
            "relationship_detail": (
                "same_frozen_formula_different_strategy_and_data_identity"
                if relationship == "same_formula_historical_research_baseline"
                else relationship
            ),
            "label": relationship_label,
            "requested_strategy_id": normalized_strategy_id,
            "requested_candidate_id": normalized_candidate_id,
            "source_candidate_id": source_candidate_id,
            "candidate_identity_match": True,
            "is_okx_native_backtest": False,
        },
        "blockers": blockers,
        "safety": _false_safety(),
    }
    canonical_report = {
        "schema_version": "btc_strategy_history_normalized_report_v1",
        "status": "complete_research_only",
        "decision": canonical["decision"],
        "run_id": history_run["run_id"],
        "source_run_id": history_run["source_run_id"],
        "artifact_binding": {
            "pointer_path": HISTORY_POINTER_PATH.as_posix(),
            "pointer_code_commit": code_commit,
            "manifest_sha256_verified": True,
            "evidence_pack_sha256_verified": False,
            "ledger_artifact_sha256_verified": False,
            "fills_hash_verified": False,
            "ledger_equity_consistent": False,
        },
        "series": {
            "equity": [],
            "drawdown": [],
            "monthly_returns": [],
            "trades": [],
            "costs": [],
        },
        "derived_metrics": {
            "trade_count": _mapping(review.get("return_concentration")).get(
                "trade_count"
            ),
            "winning_trade_count": _mapping(
                review.get("return_concentration")
            ).get("positive_trade_count"),
            "profit_factor": metrics.get("profit_factor"),
        },
        "source_counts": {
            "candidate_review_count": 1,
            "annual_segment_count": len(
                _list(_mapping(review.get("annual_attribution")).get("segments"))
            ),
            "trade_review_count": len(
                _list(_mapping(review.get("return_concentration")).get("best_trades"))
            )
            + len(
                _list(_mapping(review.get("return_concentration")).get("worst_trades"))
            ),
        },
        "safety": _false_safety(),
        "blockers": blockers,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete_research_only",
        "decision": "candidate_bound_history_read_only_no_paper_no_live",
        "strategy_id": normalized_strategy_id,
        "candidate_id": normalized_candidate_id,
        "source_candidate_id": source_candidate_id,
        "relationship": relationship,
        "relationship_label": relationship_label,
        "research_status": "research_only",
        "history_runs": history_runs,
        "selected_run_id": history_run["run_id"],
        "canonical": canonical,
        "canonical_report": canonical_report,
        "details": _compact_details(review, report),
        "source": {
            "report_path": report_path,
            "report_sha256": report_sha256,
            "report_schema_version": str(report.get("schema_version") or ""),
            "source_code_commit": code_commit,
            "generated_at_utc": generated_at,
            "data": report_input,
            "latest_pointer_path": HISTORY_POINTER_PATH.as_posix(),
            "index_sha256": str(pointer.get("index_sha256") or ""),
            "source_commit": str(pointer.get("latest_source_commit") or ""),
            "producer_commit": str(pointer.get("latest_producer_commit") or ""),
            "data_lineage_sha256": str(
                pointer.get("data_lineage_sha256") or ""
            ),
        },
        "blockers": blockers,
        "safety": _false_safety(),
    }


def _catalog_entry(
    *,
    report: Mapping[str, Any],
    report_sha256: str,
    strategy_id: str,
    candidate_id: str,
    source_candidate_id: str,
    review: Mapping[str, Any],
    relationship: str,
    label: str,
    history_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = _mapping(review.get("full_metrics"))
    return {
        "strategy_id": strategy_id,
        "candidate_id": candidate_id,
        "source_candidate_id": source_candidate_id,
        "variant_id": str(review.get("variant_id") or ""),
        "display_name": str(review.get("label") or "Long/Short Donchian Top5"),
        "relationship": relationship,
        "relationship_label": label,
        "research_status": "research_only",
        "annual_return_pct": metrics.get("annual_return_pct"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "report_sha256": report_sha256,
        "generated_at_utc": str(report.get("generated_at_utc") or ""),
        "history_runs": history_runs,
        "history_run_count": len(history_runs),
    }


def _compact_details(
    review: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "full_metrics": _mapping(review.get("full_metrics")),
        "params": _mapping(review.get("params")),
        "annual_attribution": _mapping(review.get("annual_attribution")),
        "confirmation_holdout": _mapping(review.get("confirmation_holdout")),
        "walk_forward": _mapping(_mapping(review.get("source_row")).get("walk_forward")),
        "cost_stress": _mapping(_mapping(review.get("source_row")).get("cost_stress")),
        "market_regime_attribution": _mapping(
            review.get("market_regime_attribution")
        ),
        "max_drawdown_attribution": _mapping(
            review.get("max_drawdown_attribution")
        ),
        "return_concentration": _mapping(review.get("return_concentration")),
        "failure_review": _mapping(review.get("failure_review")),
        "forward_observation": _mapping(review.get("forward_observation")),
        "review_design": _mapping(report.get("review_design")),
        "warnings": _string_list(report.get("warnings")),
    }


def _history_run(
    *,
    report: Mapping[str, Any],
    report_sha256: str,
    candidate_id: str,
    review: Mapping[str, Any],
    relationship: str,
    relationship_label: str,
) -> dict[str, Any]:
    generated_at = str(report.get("generated_at_utc") or "")
    source_candidate_id = _required_text(review, "candidate_id")
    run_key = f"{source_candidate_id}:{generated_at}:{report_sha256}"
    run_id = f"btc-top5-{hashlib.sha256(run_key.encode('utf-8')).hexdigest()[:16]}"
    return {
        "run_id": run_id,
        "source_run_id": (
            f"btc_long_short_top5_review:{source_candidate_id}:"
            f"{generated_at or report_sha256[:12]}"
        ),
        "candidate_id": candidate_id,
        "source_candidate_id": source_candidate_id,
        "generated_at_utc": generated_at,
        "status": "complete_research_only",
        "relationship": relationship,
        "label": relationship_label,
        "report_sha256": report_sha256,
    }


def _blockers(
    report: Mapping[str, Any],
    review: Mapping[str, Any],
    relationship: str,
) -> list[str]:
    blockers = [
        "btc_strategy_history:research_only_no_paper_no_live",
        "btc_strategy_history:historical_report_not_current_head_promotion_evidence",
        *_string_list(report.get("blockers")),
        *_string_list(report.get("warnings")),
        *_string_list(_mapping(review.get("failure_review")).get("flags")),
    ]
    if relationship == "same_formula_historical_research_baseline":
        blockers.append(
            "btc_strategy_history:okx_native_original_backtest_missing_"
            "showing_same_formula_historical_research_baseline"
        )
    return list(dict.fromkeys(item for item in blockers if item))


def _source_identity(strategy_id: str, candidate_id: str) -> tuple[str, str, str]:
    if strategy_id == STABLE_STRATEGY_ID:
        return (
            candidate_id,
            "exact_candidate_historical_research_report",
            "历史研究回测",
        )
    return (
        candidate_id.removeprefix(OKX_NATIVE_PREFIX),
        "same_formula_historical_research_baseline",
        "同公式历史研究基线（Binance spot / simulated perpetual；"
        "不是 OKX-native 原生回测）",
    )


def _validate_request_identity(strategy_id: str, candidate_id: str) -> tuple[str, str]:
    strategy = strategy_id.strip()
    candidate = candidate_id.strip()
    if not strategy or not candidate:
        raise BTCStrategyHistoryInvalid("strategy_id and candidate_id are required")
    if any(token in strategy or token in candidate for token in ("/", "\\", "..", "\x00")):
        raise BTCStrategyHistoryInvalid("invalid BTC strategy history identity")
    if strategy == STABLE_STRATEGY_ID and candidate.startswith(OKX_NATIVE_PREFIX):
        raise BTCStrategyHistoryNotFound(
            "OKX-native candidate cannot impersonate the stable strategy line"
        )
    if strategy == OKX_NATIVE_STRATEGY_ID and not candidate.startswith(
        OKX_NATIVE_PREFIX
    ):
        raise BTCStrategyHistoryNotFound(
            "stable candidate cannot impersonate the OKX-native strategy line"
        )
    if strategy not in {STABLE_STRATEGY_ID, OKX_NATIVE_STRATEGY_ID}:
        raise BTCStrategyHistoryNotFound(
            f"BTC strategy history unavailable for strategy: {strategy}"
        )
    return strategy, candidate


def _load_history_index(
    artifact_reader: Any,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    try:
        pointer = artifact_reader.read_json(HISTORY_POINTER_PATH)
    except (OSError, RuntimeError) as exc:
        raise BTCStrategyHistoryUnavailable(
            "BTC strategy history immutable latest pointer is unavailable"
        ) from exc
    if pointer.get("schema_version") != POINTER_SCHEMA_VERSION:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history latest pointer schema mismatch"
        )
    index_path = str(pointer.get("index_path") or "")
    index_sha256 = str(pointer.get("index_sha256") or "")
    report_path = str(pointer.get("latest_report_path") or "")
    source_sha256 = str(pointer.get("latest_source_sha256") or "")
    if index_path != HISTORY_INDEX_PATH.as_posix():
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history latest pointer index path mismatch"
        )
    if not _valid_sha256(index_sha256) or not _valid_sha256(source_sha256):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history latest pointer hash invalid"
        )
    expected_report_path = (
        HISTORY_PREFIX / "runs" / source_sha256 / "report.json"
    ).as_posix()
    if report_path != expected_report_path:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history latest pointer report path mismatch"
        )
    try:
        index_bytes = artifact_reader.read_bytes(HISTORY_INDEX_PATH)
    except (OSError, RuntimeError) as exc:
        raise BTCStrategyHistoryUnavailable(
            "BTC strategy history immutable index is unavailable"
        ) from exc
    if hashlib.sha256(index_bytes).hexdigest() != index_sha256:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable index hash mismatch"
        )
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable index is invalid JSON"
        ) from exc
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
    ):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable index schema mismatch"
        )
    runs = [
        item
        for item in _list(index.get("runs"))
        if isinstance(item, dict)
    ]
    if not runs or len(runs) > MAX_HISTORY_RUNS:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable index run bound invalid"
        )
    matching = [
        item
        for item in runs
        if str(item.get("source_sha256") or "") == source_sha256
        and str(item.get("report_path") or "") == report_path
    ]
    if len(matching) != 1:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history latest snapshot is not uniquely indexed"
        )
    return pointer, index


def _load_indexed_reports(
    artifact_reader: Any,
    *,
    index: Mapping[str, Any],
    pointer: Mapping[str, Any],
) -> list[tuple[dict[str, Any], str, str]]:
    snapshots = [
        _load_indexed_report(
            artifact_reader,
            entry=item,
            pointer=pointer,
        )
        for item in _list(index.get("runs"))
        if isinstance(item, dict)
    ]
    if not snapshots:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable index has no readable snapshots"
        )
    return snapshots


def _load_indexed_report(
    artifact_reader: Any,
    *,
    entry: Mapping[str, Any],
    pointer: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    source_sha256 = str(entry.get("source_sha256") or "")
    report_path = str(entry.get("report_path") or "")
    if not _valid_sha256(source_sha256):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history indexed report hash invalid"
        )
    expected_report_path = (
        HISTORY_PREFIX / "runs" / source_sha256 / "report.json"
    ).as_posix()
    if report_path != expected_report_path:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history indexed report path mismatch"
        )
    try:
        raw = artifact_reader.read_bytes(report_path)
    except (OSError, RuntimeError) as exc:
        raise BTCStrategyHistoryUnavailable(
            "BTC strategy history immutable report is unavailable"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != source_sha256:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history immutable report hash mismatch"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history report is invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history report must be a JSON object"
        )
    validate_btc_strategy_history_source_report(payload)
    actual_candidates = {
        _required_text(item, "candidate_id")
        for item in _candidate_reviews(payload)
    }
    indexed_candidates = {
        str(item) for item in _list(entry.get("candidate_ids")) if str(item)
    }
    if not actual_candidates or actual_candidates != indexed_candidates:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history candidate index mismatch"
        )
    if source_sha256 == str(pointer.get("latest_source_sha256") or ""):
        pointer_candidates = {
            str(item) for item in _list(pointer.get("candidate_ids")) if str(item)
        }
        if (
            report_path != str(pointer.get("latest_report_path") or "")
            or actual_candidates != pointer_candidates
        ):
            raise BTCStrategyHistoryInvalid(
                "BTC strategy history latest pointer candidate mismatch"
            )
    return payload, source_sha256, report_path


def _matching_candidate_snapshots(
    snapshots: list[tuple[dict[str, Any], str, str]],
    *,
    source_candidate_id: str,
    candidate_id: str,
    relationship: str,
    relationship_label: str,
) -> list[
    tuple[dict[str, Any], str, str, Mapping[str, Any], dict[str, Any]]
]:
    matches = []
    for report, report_sha256, report_path in snapshots:
        review = next(
            (
                item
                for item in _candidate_reviews(report)
                if _required_text(item, "candidate_id") == source_candidate_id
            ),
            None,
        )
        if review is None:
            continue
        history_run = _history_run(
            report=report,
            report_sha256=report_sha256,
            candidate_id=candidate_id,
            review=review,
            relationship=relationship,
            relationship_label=relationship_label,
        )
        matches.append(
            (report, report_sha256, report_path, review, history_run)
        )
    return matches


def _history_runs_for_candidate(
    snapshots: list[tuple[dict[str, Any], str, str]],
    *,
    source_candidate_id: str,
    candidate_id: str,
    relationship: str,
    relationship_label: str,
) -> list[dict[str, Any]]:
    return [
        item[4]
        for item in _matching_candidate_snapshots(
            snapshots,
            source_candidate_id=source_candidate_id,
            candidate_id=candidate_id,
            relationship=relationship,
            relationship_label=relationship_label,
        )
    ]


def _candidate_reviews(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    reviews = [
        item
        for item in _list(report.get("candidate_reviews"))
        if isinstance(item, dict)
    ]
    if not reviews:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history report has no candidate_reviews"
        )
    return reviews


def validate_btc_strategy_history_source_report(
    report: Mapping[str, Any],
) -> None:
    if report.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report schema mismatch"
        )
    if report.get("status") != SOURCE_STATUS:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report status mismatch"
        )
    if report.get("decision") != SOURCE_DECISION:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report decision mismatch"
        )
    guardrails = _mapping(report.get("guardrails"))
    if guardrails.get("research_only") is not True:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report research_only guardrail missing"
        )
    invalid = [
        key
        for key in _SOURCE_FALSE_GUARDRAILS
        if guardrails.get(key) is not False
    ]
    if invalid:
        raise BTCStrategyHistoryInvalid(
            "BTC strategy history source report guardrail mismatch: "
            + ", ".join(invalid)
        )


def _false_safety() -> dict[str, bool]:
    return {key: False for key in _SAFETY_KEYS}


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encoded_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise BTCStrategyHistoryInvalid(f"BTC strategy history missing {key}")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _list(value) if str(item)]
