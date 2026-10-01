"""Fail-closed natural-time observation service for the frozen ETF26 candidate.

The service consumes only committed immutable data-steward evidence.  It owns
an append-only receipt store, never invokes a broker, and never writes a paper
or live ledger.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from quant_shared.core.serialization import canonical_payload_hash
from quant_us.core.calendar import USEquityCalendar
from quant_us.data.pit_dataready_consumer import consume_etf26_manifest


SCHEMA_VERSION = "us_equity_forward_observation_receipt_v1"
OUTCOME_SCHEMA_VERSION = "us_equity_forward_observation_run_outcome_v1"
MANIFEST_SCHEMA_VERSION = "us_equity_forward_observation_manifest_v1"
LATEST_SCHEMA_VERSION = "us_equity_forward_observation_latest_pointer_v1"
DEFAULT_CONFIG_PATH = Path("configs/monitoring/us_v3_forward_observation_v1.json")
REQUIRED_STATES = ("signal", "target", "fill", "ledger")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReceiptIntegrityError(RuntimeError):
    """Raised when an existing same-day receipt cannot be trusted."""


def run_current_day_forward_observation(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_root: Path | None = None,
    generated_at: str | None = None,
    state_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run at most one immutable receipt for the configured natural day."""

    root = repo_root.resolve()
    config = _read_object(_absolute(config_path, root))
    _validate_config(config)
    now_utc = _parse_aware(generated_at or _utc_now()).astimezone(timezone.utc)
    timezone_name = str(config["time_contract"]["timezone"])
    try:
        observation_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unsupported_observation_timezone:{timezone_name}") from exc
    now_local = now_utc.astimezone(observation_timezone)
    natural_day = now_local.date()
    receipt_root = _absolute(
        output_root or Path(str(config["receipt_store"]["root"])),
        root,
    )
    store = FileReceiptStore(root=receipt_root, repo_root=root)

    try:
        existing = store.read_same_day(natural_day)
    except ReceiptIntegrityError as exc:
        return _outcome(
            status="blocked_evidence_integrity",
            write_status="not_written_same_day_receipt_untrusted",
            receipt={},
            report_path="",
            blockers=[str(exc)],
        )
    if existing is not None:
        return _outcome(
            status=str(existing["status"]),
            write_status="reused_existing_same_day_receipt",
            receipt=existing,
            report_path=str(existing["outputs"]["report"]),
            blockers=list(existing["blockers"]),
        )

    recommended = time.fromisoformat(
        str(config["time_contract"]["recommended_local_time"])
    )
    if now_local.time().replace(tzinfo=None) < recommended:
        return _outcome(
            status="wait_until_recommended_local_time",
            write_status="not_written_before_schedule",
            receipt={},
            report_path="",
            blockers=["recommended_local_time_not_reached"],
        )

    candidate_path = _absolute(
        Path(str(config["candidate"]["config_path"])),
        root,
    )
    candidate = _read_object(candidate_path)
    pit_config = _read_object(
        _absolute(Path(str(config["data"]["pit_consumer_config_path"])), root)
    )
    manifest_state = consume_etf26_manifest(
        repo_root=root,
        config=pit_config,
        as_of=now_utc,
    )
    calendar = USEquityCalendar.with_holidays(
        years=(natural_day.year - 1, natural_day.year, natural_day.year + 1),
        calendar_provider=str(config["time_contract"]["calendar_provider"]),
    )
    expected_session = calendar.previous_trading_day(natural_day).isoformat()
    source_head = _git(root, ["rev-parse", "HEAD"])
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        raise ValueError("current_head_unavailable")
    code_tree_hash = _git_code_tree_hash(
        root=root,
        source_head=source_head,
        paths=[str(value) for value in config["identity"]["code_tree_paths"]],
    )
    configured_state_evidence = (
        dict(state_evidence)
        if state_evidence is not None
        else _load_configured_state_evidence(root=root, config=config)
    )
    history, integrity_issues = store.read_verified_history(before=natural_day)
    run_id = _run_id(
        natural_day=natural_day,
        source_head=source_head,
        code_tree_hash=code_tree_hash,
        strategy_version=str(candidate.get("strategy_version", "")),
        dataset_version=str(manifest_state.get("dataset_version", "")),
    )
    report_path, manifest_path = store.paths_for(
        natural_day=natural_day,
        run_id=run_id,
    )
    receipt = build_forward_observation_receipt(
        config=config,
        candidate=candidate,
        manifest_state=manifest_state,
        state_evidence=configured_state_evidence,
        history=history,
        integrity_issues=integrity_issues,
        generated_at_utc=now_utc,
        now_local=now_local,
        expected_finalized_session=expected_session,
        source_head=source_head,
        code_tree_hash=code_tree_hash,
        report_path=_relpath(report_path, root),
        manifest_path=_relpath(manifest_path, root),
        run_id=run_id,
    )
    written = store.write_once(receipt)
    return _outcome(
        status=str(written["status"]),
        write_status="written_new_immutable_receipt",
        receipt=written,
        report_path=str(written["outputs"]["report"]),
        blockers=list(written["blockers"]),
    )


def build_forward_observation_receipt(
    *,
    config: Mapping[str, Any],
    candidate: Mapping[str, Any],
    manifest_state: Mapping[str, Any],
    state_evidence: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    integrity_issues: Sequence[str],
    generated_at_utc: datetime,
    now_local: datetime,
    expected_finalized_session: str,
    source_head: str,
    code_tree_hash: str,
    report_path: str,
    manifest_path: str,
    run_id: str,
) -> dict[str, Any]:
    """Build one receipt without performing any external or trading action."""

    _validate_config(config)
    candidate_id = str(candidate.get("candidate_id", ""))
    strategy_version = str(candidate.get("strategy_version", ""))
    params_hash = canonical_payload_hash(_mapping(candidate.get("parameters")))
    candidate_config_hash = canonical_payload_hash(dict(candidate))
    strategy_identity_hash = canonical_payload_hash(
        {
            "candidate_id": candidate_id,
            "strategy_version": strategy_version,
            "parameters_sha256": params_hash,
            "selection": _mapping(candidate.get("selection")),
            "signal_rule": _mapping(candidate.get("signal_rule")),
            "execution_rule": _mapping(candidate.get("execution_rule")),
        }
    )
    natural_day = now_local.date()
    configured_timezone = str(config["time_contract"]["timezone"])
    blockers: list[str] = []
    gaps: list[str] = []
    continuity_interrupts = list(integrity_issues)

    if configured_timezone != "Asia/Shanghai":
        blockers.append("observation_timezone_contract_mismatch")
    if now_local.tzinfo is None or getattr(now_local.tzinfo, "key", "") != configured_timezone:
        blockers.append("observation_runtime_timezone_mismatch")
    if str(candidate.get("status", "")) != "frozen_exploratory_research_only":
        blockers.append("candidate_not_frozen")
    if not candidate_id or not strategy_version:
        blockers.append("candidate_identity_missing")

    data = _data_snapshot(
        manifest_state=manifest_state,
        expected_finalized_session=expected_finalized_session,
    )
    if data["state"] != "research_ready":
        blockers.append(f"immutable_successor_{data['state']}")
    if not data["expected_finalized_session_covered"]:
        blockers.append(
            f"expected_finalized_session_missing:{expected_finalized_session}"
        )
    gaps.extend(str(value) for value in data["constraints"])
    gaps.extend(str(value) for value in data["errors"])

    normalized_states = _normalize_states(
        state_evidence=state_evidence,
        expected_session=expected_finalized_session,
        source_head=source_head,
        data_ready=not any(
            value.startswith("expected_finalized_session_missing")
            or value.startswith("immutable_successor_")
            for value in blockers
        ),
    )
    for state_name, state in normalized_states.items():
        if not state["verified"]:
            gaps.append(f"{state_name}_state_gap:{state['status']}")
    if data["expected_finalized_session_covered"] and any(
        not value["verified"] for value in normalized_states.values()
    ):
        blockers.append("observation_state_evidence_incomplete")

    if integrity_issues:
        blockers.append("receipt_history_integrity_failed")
    confirmation_window = _mapping(candidate.get("independent_confirmation_window"))
    confirmation_start = date.fromisoformat(str(confirmation_window["start"]))
    confirmation_end = date.fromisoformat(str(confirmation_window["end"]))
    expected_session_date = date.fromisoformat(expected_finalized_session)
    if expected_session_date > confirmation_end:
        blockers.append("independent_confirmation_window_closed")
    current_eligible = not blockers and all(
        value["verified"] for value in normalized_states.values()
    )
    continuity = _continuity(
        history=history,
        natural_day=natural_day,
        expected_session=expected_finalized_session,
        source_head=source_head,
        code_tree_hash=code_tree_hash,
        candidate_id=candidate_id,
        strategy_version=strategy_version,
        params_hash=params_hash,
        confirmation_start=confirmation_start,
        confirmation_end=confirmation_end,
        current_eligible=current_eligible,
        initial_interrupts=continuity_interrupts,
    )
    paper_required = int(config["windows"]["paper_review_natural_days"])
    confirmation_required = int(
        config["windows"]["independent_confirmation_trading_sessions"]
    )
    paper_complete = continuity["current_streak_natural_days"] >= paper_required
    confirmation_complete = (
        continuity["distinct_trading_session_count"] >= confirmation_required
    )

    if any(value.startswith("observation_timezone_") for value in blockers):
        status = "blocked_contract"
    elif "receipt_history_integrity_failed" in blockers:
        status = "blocked_evidence_integrity"
    elif any(
        value.startswith("expected_finalized_session_missing")
        or value.startswith("immutable_successor_")
        for value in blockers
    ):
        status = "blocked_external_data"
    elif blockers:
        status = "blocked_observation_evidence"
    elif paper_complete and confirmation_complete:
        status = "complete_for_manual_review_only"
    else:
        status = "in_progress_natural_time"

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _iso_utc(generated_at_utc),
        "status": status,
        "decision": "keep_promotion_paper_live_private_order_locked",
        "run_id": run_id,
        "observation": {
            "natural_day": natural_day.isoformat(),
            "timezone": configured_timezone,
            "recommended_local_time": str(
                config["time_contract"]["recommended_local_time"]
            ),
            "expected_finalized_session": expected_finalized_session,
            "expected_finalized_session_rule": str(
                config["time_contract"]["expected_finalized_session_rule"]
            ),
            "eligible_receipt": current_eligible,
        },
        "identity": {
            "source_head": source_head,
            "code_tree_hash": code_tree_hash,
            "candidate_id": candidate_id,
            "candidate_config_sha256": candidate_config_hash,
            "strategy_version": strategy_version,
            "strategy_identity_sha256": strategy_identity_hash,
            "parameters_sha256": params_hash,
            "parameters_frozen": True,
            "candidate_reselected": False,
        },
        "data": data,
        "states": normalized_states,
        "continuity": continuity,
        "windows": {
            "paper_review_natural_days": {
                "required": paper_required,
                "observed": continuity["current_streak_natural_days"],
                "complete": paper_complete,
                "semantics": "paper_review_prerequisite_only",
            },
            "independent_confirmation_trading_sessions": {
                "required": confirmation_required,
                "observed": continuity["distinct_trading_session_count"],
                "complete": confirmation_complete,
                "window_start": str(
                    confirmation_window["start"]
                ),
                "window_end": str(
                    confirmation_window["end"]
                ),
                "semantics": "distinct_xnys_sessions_no_early_evaluation",
            },
            "substitution_allowed": False,
        },
        "blockers": _dedupe(blockers),
        "gaps": _dedupe(gaps),
        "owners": _owners_for(blockers),
        "outputs": {
            "report": report_path.replace("\\", "/"),
            "manifest": manifest_path.replace("\\", "/"),
        },
        "guardrails": _guardrails(),
    }
    receipt["artifact_identity_sha256"] = canonical_payload_hash(receipt)
    return receipt


class FileReceiptStore:
    """Append-only filesystem adapter for task-owned observation receipts."""

    def __init__(self, *, root: Path, repo_root: Path) -> None:
        self.root = root.resolve()
        self.repo_root = repo_root.resolve()

    def paths_for(self, *, natural_day: date, run_id: str) -> tuple[Path, Path]:
        run_root = self.root / "runs" / natural_day.isoformat() / run_id
        return run_root / "report.json", run_root / "manifest.json"

    def read_same_day(self, natural_day: date) -> dict[str, Any] | None:
        day_root = self.root / "runs" / natural_day.isoformat()
        manifests = sorted(day_root.glob("*/manifest.json")) if day_root.exists() else []
        if not manifests:
            return None
        if len(manifests) != 1:
            raise ReceiptIntegrityError(
                f"same_day_receipt_count_invalid:{natural_day.isoformat()}:{len(manifests)}"
            )
        receipt, issue = self._verify_manifest(manifests[0])
        if issue:
            raise ReceiptIntegrityError(
                f"same_day_receipt_tampered:{natural_day.isoformat()}:{issue}"
            )
        return receipt

    def read_verified_history(
        self, *, before: date
    ) -> tuple[list[dict[str, Any]], list[str]]:
        receipts: list[dict[str, Any]] = []
        issues: list[str] = []
        runs_root = self.root / "runs"
        if runs_root.exists():
            for day_root in sorted(path for path in runs_root.iterdir() if path.is_dir()):
                try:
                    day = date.fromisoformat(day_root.name)
                except ValueError:
                    issues.append(f"invalid_receipt_day:{day_root.name}")
                    continue
                if day >= before:
                    continue
                manifests = sorted(day_root.glob("*/manifest.json"))
                if len(manifests) != 1:
                    issues.append(
                        f"receipt_count_invalid:{day.isoformat()}:{len(manifests)}"
                    )
                    continue
                receipt, issue = self._verify_manifest(manifests[0])
                if issue:
                    issues.append(f"receipt_tamper:{day.isoformat()}:{issue}")
                elif receipt is not None:
                    receipts.append(receipt)
        latest_issue = self._verify_latest_pointer()
        if latest_issue:
            issues.append(latest_issue)
        return receipts, _dedupe(issues)

    def write_once(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        natural_day = date.fromisoformat(str(receipt["observation"]["natural_day"]))
        if self.read_same_day(natural_day) is not None:
            raise ReceiptIntegrityError(
                f"same_day_receipt_already_exists:{natural_day.isoformat()}"
            )
        report_path = _absolute(Path(str(receipt["outputs"]["report"])), self.repo_root)
        manifest_path = _absolute(
            Path(str(receipt["outputs"]["manifest"])),
            self.repo_root,
        )
        run_root = report_path.parent
        if run_root.exists():
            raise ReceiptIntegrityError(f"run_root_already_exists:{run_root.name}")
        run_root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{run_root.name}.", dir=str(run_root.parent))
        )
        try:
            staged_report = staging / "report.json"
            _write_json(staged_report, receipt)
            receipt_sha = _sha256_file(staged_report)
            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "generated_at_utc": receipt["generated_at_utc"],
                "natural_day": natural_day.isoformat(),
                "source_head": receipt["identity"]["source_head"],
                "report_path": _relpath(report_path, self.repo_root),
                "receipt_sha256": receipt_sha,
                "artifact_identity_sha256": receipt["artifact_identity_sha256"],
                "immutable": True,
            }
            staged_manifest = staging / "manifest.json"
            _write_json(staged_manifest, manifest)
            os.replace(staging, run_root)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        manifest_sha = _sha256_file(manifest_path)
        latest = {
            "schema_version": LATEST_SCHEMA_VERSION,
            "natural_day": natural_day.isoformat(),
            "source_head": receipt["identity"]["source_head"],
            "report_path": _relpath(report_path, self.repo_root),
            "manifest_path": _relpath(manifest_path, self.repo_root),
            "receipt_sha256": _sha256_file(report_path),
            "manifest_sha256": manifest_sha,
            "paper_or_live_unlock_allowed": False,
        }
        latest_path = self.root / "latest" / "latest_pointer.json"
        _write_json_atomic(latest_path, latest)
        return dict(receipt)

    def _verify_manifest(
        self, manifest_path: Path
    ) -> tuple[dict[str, Any] | None, str]:
        try:
            manifest = _read_object(manifest_path)
            report_path = _absolute(
                Path(str(manifest["report_path"])),
                self.repo_root,
            )
            if not _is_within(self.root, report_path) or not report_path.is_file():
                return None, "report_missing_or_outside_store"
            if _sha256_file(report_path) != manifest.get("receipt_sha256"):
                return None, "receipt_sha256_mismatch"
            receipt = _read_object(report_path)
            expected_identity = canonical_payload_hash(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "artifact_identity_sha256"
                }
            )
            if receipt.get("artifact_identity_sha256") != expected_identity:
                return None, "artifact_identity_sha256_mismatch"
            if (
                manifest.get("artifact_identity_sha256")
                != receipt.get("artifact_identity_sha256")
            ):
                return None, "manifest_identity_mismatch"
            return receipt, ""
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return None, f"invalid_manifest:{type(exc).__name__}"

    def _verify_latest_pointer(self) -> str:
        pointer_path = self.root / "latest" / "latest_pointer.json"
        if not pointer_path.exists():
            return ""
        try:
            pointer = _read_object(pointer_path)
            report_path = _absolute(
                Path(str(pointer["report_path"])),
                self.repo_root,
            )
            manifest_path = _absolute(
                Path(str(pointer["manifest_path"])),
                self.repo_root,
            )
            if not _is_within(self.root, report_path) or not _is_within(
                self.root, manifest_path
            ):
                return "dirty_latest_path_outside_store"
            if (
                _sha256_file(report_path) != pointer.get("receipt_sha256")
                or _sha256_file(manifest_path) != pointer.get("manifest_sha256")
            ):
                return "dirty_latest_identity_mismatch"
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return "dirty_latest_invalid"
        return ""


def _continuity(
    *,
    history: Sequence[Mapping[str, Any]],
    natural_day: date,
    expected_session: str,
    source_head: str,
    code_tree_hash: str,
    candidate_id: str,
    strategy_version: str,
    params_hash: str,
    confirmation_start: date,
    confirmation_end: date,
    current_eligible: bool,
    initial_interrupts: Sequence[str],
) -> dict[str, Any]:
    interrupts = list(initial_interrupts)
    sequence: list[Mapping[str, Any]] = []
    ordered = sorted(
        history,
        key=lambda item: str(_mapping(item.get("observation")).get("natural_day", "")),
    )
    previous = ordered[-1] if ordered else None
    if previous is not None:
        previous_observation = _mapping(previous.get("observation"))
        previous_identity = _mapping(previous.get("identity"))
        previous_day = date.fromisoformat(str(previous_observation["natural_day"]))
        if previous_day != natural_day - timedelta(days=1):
            interrupts.append(
                f"natural_day_gap:{previous_day.isoformat()}:{natural_day.isoformat()}"
            )
        if previous_identity.get("source_head") != source_head:
            interrupts.append("cross_head_continuity_interrupt")
        if previous_identity.get("code_tree_hash") != code_tree_hash:
            interrupts.append("code_tree_hash_drift")
        if (
            previous_identity.get("candidate_id") != candidate_id
            or previous_identity.get("strategy_version") != strategy_version
            or previous_identity.get("parameters_sha256") != params_hash
        ):
            interrupts.append("cross_strategy_continuity_interrupt")
        if previous_observation.get("eligible_receipt") is not True:
            interrupts.append("prior_receipt_ineligible")

    if current_eligible and not interrupts:
        expected_day = natural_day - timedelta(days=1)
        for receipt in reversed(ordered):
            observation = _mapping(receipt.get("observation"))
            identity = _mapping(receipt.get("identity"))
            day = date.fromisoformat(str(observation["natural_day"]))
            if (
                day != expected_day
                or observation.get("eligible_receipt") is not True
                or identity.get("source_head") != source_head
                or identity.get("code_tree_hash") != code_tree_hash
                or identity.get("candidate_id") != candidate_id
                or identity.get("strategy_version") != strategy_version
                or identity.get("parameters_sha256") != params_hash
            ):
                break
            sequence.append(receipt)
            expected_day -= timedelta(days=1)
        sequence.reverse()
    sessions = {
        str(_mapping(item.get("observation")).get("expected_finalized_session"))
        for item in sequence
        if _mapping(item.get("observation")).get("eligible_receipt") is True
        and confirmation_start
        <= date.fromisoformat(
            str(_mapping(item.get("observation")).get("expected_finalized_session"))
        )
        <= confirmation_end
    }
    if (
        current_eligible
        and confirmation_start
        <= date.fromisoformat(expected_session)
        <= confirmation_end
    ):
        sessions.add(expected_session)
    current_streak = len(sequence) + (1 if current_eligible else 0)
    return {
        "status": (
            "blocked"
            if not current_eligible
            else "restarted_after_interrupt"
            if interrupts
            else "continuous"
        ),
        "current_streak_natural_days": current_streak,
        "distinct_trading_session_count": len(sessions),
        "distinct_trading_sessions": sorted(sessions),
        "interrupts": _dedupe(interrupts),
        "backfill_used": False,
        "same_day_rerun_used": False,
    }


def _data_snapshot(
    *,
    manifest_state: Mapping[str, Any],
    expected_finalized_session: str,
) -> dict[str, Any]:
    coverage = _mapping(manifest_state.get("coverage"))
    coverage_end_text = str(coverage.get("end", ""))
    try:
        coverage_end = datetime.fromisoformat(
            coverage_end_text.replace("Z", "+00:00")
        ).date()
    except ValueError:
        coverage_end = None
    expected = date.fromisoformat(expected_finalized_session)
    return {
        "state": str(manifest_state.get("state", "missing")),
        "producer_role": str(manifest_state.get("producer_role", "")),
        "producer_commit": str(manifest_state.get("producer_commit", "")),
        "manifest_git_spec": str(manifest_state.get("manifest_git_spec", "")),
        "manifest_sha256": str(manifest_state.get("manifest_sha256", "")),
        "dataset_id": str(manifest_state.get("dataset_id", "")),
        "dataset_version": str(manifest_state.get("dataset_version", "")),
        "readiness_class": str(manifest_state.get("readiness_class", "")),
        "coverage": dict(coverage),
        "expected_finalized_session_covered": bool(
            coverage_end is not None and coverage_end >= expected
        ),
        "consumer_read_only": True,
        "constraints": [str(value) for value in manifest_state.get("constraints", [])],
        "errors": [str(value) for value in manifest_state.get("errors", [])],
    }


def _normalize_states(
    *,
    state_evidence: Mapping[str, Any],
    expected_session: str,
    source_head: str,
    data_ready: bool,
) -> dict[str, Any]:
    states: dict[str, Any] = {}
    for name in REQUIRED_STATES:
        raw = _mapping(state_evidence.get(name))
        if not data_ready:
            states[name] = {
                "status": "not_run_missing_finalized_session",
                "session": expected_session,
                "source_head": source_head,
                "artifact_path": "",
                "sha256": "",
                "verified": False,
                "simulation_scope": "research_fixture_or_local_replay_only",
            }
            continue
        status = str(raw.get("status", "missing"))
        session = str(raw.get("session", ""))
        evidence_head = str(raw.get("source_head", ""))
        sha256 = str(raw.get("sha256", ""))
        artifact_path = str(raw.get("artifact_path", "")).replace("\\", "/")
        verified = (
            status in {"complete", "verified"}
            and session == expected_session
            and evidence_head == source_head
            and bool(SHA256_RE.fullmatch(sha256))
            and bool(artifact_path)
        )
        states[name] = {
            "status": status,
            "session": session,
            "source_head": evidence_head,
            "artifact_path": artifact_path,
            "sha256": sha256,
            "verified": verified,
            "simulation_scope": "research_fixture_or_local_replay_only",
        }
    return states


def _load_configured_state_evidence(
    *, root: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for name, path_value in _mapping(config.get("state_evidence")).items():
        text = str(path_value)
        if not text:
            continue
        path = _absolute(Path(text), root)
        if path.is_file():
            evidence[str(name)] = _read_object(path)
    return evidence


def _owners_for(blockers: Sequence[str]) -> list[dict[str, str]]:
    owners: list[dict[str, str]] = []
    if any(
        value.startswith("immutable_successor_")
        or value.startswith("expected_finalized_session_missing")
        for value in blockers
    ):
        owners.append(
            {
                "owner": "data_steward",
                "next_action": (
                    "publish and integrate a validated immutable ETF26 successor "
                    "covering the expected finalized XNYS session"
                ),
            }
        )
    if "observation_state_evidence_incomplete" in blockers:
        owners.append(
            {
                "owner": "super_developer",
                "next_action": (
                    "on a later eligible natural day, consume committed local "
                    "signal/target/fill/ledger replay evidence without retuning"
                ),
            }
        )
    if "receipt_history_integrity_failed" in blockers:
        owners.append(
            {
                "owner": "quant_architect",
                "next_action": "review immutable receipt integrity before resuming continuity",
            }
        )
    if not owners:
        owners.append(
            {
                "owner": "natural_time",
                "next_action": "wait for the next eligible natural day; do not backfill",
            }
        )
    return owners


def _guardrails() -> dict[str, bool]:
    return {
        "candidate_frozen": True,
        "parameters_may_change": False,
        "candidate_reselection_allowed": False,
        "backfill_allowed": False,
        "network_used": False,
        "secret_accessed": False,
        "promotion_allowed": False,
        "paper_allowed": False,
        "paper_runner_allowed": False,
        "paper_runner_started": False,
        "paper_queue_write_allowed": False,
        "live_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "broker_access_allowed": False,
        "broker_calls_used": False,
        "withdraw_allowed": False,
        "demo_allowed": False,
        "real_order_submitted": False,
        "scheduler_modified": False,
        "data_manifest_written": False,
    }


def _outcome(
    *,
    status: str,
    write_status: str,
    receipt: Mapping[str, Any],
    report_path: str,
    blockers: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "status": status,
        "write_status": write_status,
        "report_path": report_path.replace("\\", "/"),
        "receipt": dict(receipt),
        "blockers": list(blockers),
        "guardrails": _guardrails(),
    }


def _validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != "us_v3_forward_observation_config_v1":
        raise ValueError("forward_observation_config_schema_mismatch")
    if int(config["windows"]["paper_review_natural_days"]) != 30:
        raise ValueError("paper_review_natural_day_contract_mismatch")
    if (
        int(config["windows"]["independent_confirmation_trading_sessions"])
        != 252
    ):
        raise ValueError("confirmation_session_contract_mismatch")
    if config["windows"].get("substitution_allowed") is not False:
        raise ValueError("observation_window_substitution_forbidden")
    if config["receipt_store"].get("one_receipt_per_natural_day") is not True:
        raise ValueError("same_day_idempotency_contract_missing")


def _git_code_tree_hash(
    *, root: Path, source_head: str, paths: Sequence[str]
) -> str:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", source_head, "--", *paths],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ValueError("code_tree_identity_unavailable")
    listed_paths = {
        line.split("\t", 1)[1]
        for line in completed.stdout.splitlines()
        if "\t" in line
    }
    missing = sorted(set(paths) - listed_paths)
    if missing:
        raise ValueError(f"code_tree_paths_missing:{','.join(missing)}")
    return hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest()


def _run_id(
    *,
    natural_day: date,
    source_head: str,
    code_tree_hash: str,
    strategy_version: str,
    dataset_version: str,
) -> str:
    digest = canonical_payload_hash(
        {
            "natural_day": natural_day.isoformat(),
            "source_head": source_head,
            "code_tree_hash": code_tree_hash,
            "strategy_version": strategy_version,
            "dataset_version": dataset_version,
        }
    )
    return f"us-forward-{digest[:16]}"


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    temp_path = Path(name)
    try:
        _write_json(temp_path, payload)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, args: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _absolute(path: Path, root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_datetime_required")
    return parsed


def _utc_now() -> str:
    return _iso_utc(datetime.now(timezone.utc))


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))
