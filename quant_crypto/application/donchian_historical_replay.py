"""Immutable-data driver for the existing Donchian V1 offline runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from quant_crypto.application.donchian_historical_venue import (
    HistoricalBar,
    HistoricalFundingEvent,
    HistoricalOfflineVenue,
    PROTECTION_TIME_POLICY,
    ProtectionTriggerAmbiguous,
    load_historical_venue_state,
)
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay,
    DonchianOfflineReplayConfig,
    _canonical_json,
)
from quant_crypto.oms.okx_demo_paper_runtime import OkxDemoPaperRuntimeError
from quant_shared.strategy_delivery.market_policy_attachment import (
    SAFETY_KEYS as MARKET_POLICY_SAFETY_KEYS,
    MarketPolicyBaseBinding,
    build_market_policy_attachment,
    validate_market_policy_attachment,
)
from quant_shared.strategy_runtime.decision_envelope import package_digest
from quant_shared.trend_environment.entry_policy import EntryOnlyPolicyV1
from quant_shared.trend_environment.model import Bar, digest as shared_digest
from quant_shared.trend_environment.state_v2 import (
    CausalStateStreamV2,
    MarketStateV2,
    StateDefinitionV2,
    StateSourceBinding,
)
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)


from quant_crypto.application.donchian_history_spec import (
    MANIFEST_GIT_SPEC, MANIFEST_SHA256, AGGREGATE_SHA256, DATASET_ID, DATASET_VERSION,
    SIGNAL_EVENT_START, SIGNAL_EVENT_END, WARMUP_ROWS, SIGNAL_ROWS, DATA_PREFIX,
    EXPECTED_FILES, MATCHING_POLICY, COST_POLICY, PROTECTION_POLICY,
    HistorySpec, legacy_spec, validate_tables,
)
SAFETY = {
    "demo_enabled": False,
    "paper_enabled": False,
    "live_enabled": False,
    "promotion_enabled": False,
    "runtime_observed": False,
    "network_accessed": False,
    "private_endpoint_accessed": False,
    "real_order_submitted": False,
}
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_PERSISTED_VENUE_BLOCKER = "historical_persistent_venue_state_missing_or_invalid"
_MARKET_POLICY_PROTOCOL = re.compile(
    r"^[0-9a-f]{40}:docs/research/[A-Za-z0-9_.-]+\.json$"
)
_MARKET_POLICY_EVIDENCE = re.compile(
    r"^[0-9a-f]{40}:\.agent/market_state_evidence/[A-Za-z0-9_.-]+\.json$"
)
_MARKET_POLICY_ARMS = {"baseline", "conditioned"}


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_canonical_json(payload), encoding="utf-8")
    temporary.replace(path)


def _resolve_run_root(output_root: Path, run_id: str) -> tuple[Path, Path]:
    if (
        not isinstance(run_id, str)
        or not _RUN_ID_PATTERN.fullmatch(run_id)
        or ".." in run_id
        or Path(run_id).is_absolute()
    ):
        raise ValueError("historical_run_id_invalid")
    root = Path(output_root).resolve()
    candidate = (root / run_id).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("historical_run_root_escape")
    return root, candidate


def _resolve_run_child(run_root: Path, *parts: str) -> Path:
    candidate = run_root.joinpath(*parts).resolve()
    if candidate == run_root or run_root not in candidate.parents:
        raise ValueError("historical_run_root_escape")
    return candidate


def _terminal_ledger_required(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> bool:
    """Return whether terminal advance mutated economics needing V1 ledger evidence."""

    for name in (
        "position",
        "cash",
        "avg_price",
        "realized_pnl",
        "fee_total",
        "funding_total",
    ):
        if before.get(name) != after.get(name):
            return True
    for name in ("orders", "fills"):
        if before.get(name) != after.get(name):
            return True
    before_position = Decimal(str(before.get("position") or "0"))
    after_position = Decimal(str(after.get("position") or "0"))
    if before_position != 0 or after_position != 0:
        for name in ("mark_price", "unrealized_pnl", "equity"):
            if before.get(name) != after.get(name):
                return True
    return False


@dataclass(frozen=True)
class HistoricalInput:
    manifest: Mapping[str, Any]
    manifest_sha256: str
    dataset_root: Path
    frame: pd.DataFrame
    signal_rows: pd.DataFrame
    mark_by_event: Mapping[datetime, Mapping[str, Any]]
    premium_by_event: Mapping[datetime, Mapping[str, Any]]
    funding_events: tuple[HistoricalFundingEvent, ...]


@dataclass(frozen=True)
class MarketPolicyReplayPlan:
    arm: str
    protocol_git_spec: str
    protocol_blob_sha256: str
    evidence_git_spec: str
    evidence_blob_sha256: str
    analysis_start: datetime
    analysis_end: datetime
    expected_analysis_bars: int
    definition: StateDefinitionV2
    source: StateSourceBinding
    policy: EntryOnlyPolicyV1
    attachment: Mapping[str, Any]


def _utc_hour(value: Any, *, reason: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if (
        result.tzinfo is None
        or result.utcoffset() != timedelta(0)
        or any((result.minute, result.second, result.microsecond))
    ):
        raise ValueError(reason)
    return result.astimezone(timezone.utc)


def build_market_policy_replay_plan(
    *,
    repo_root: Path,
    spec: HistorySpec,
    source_head: str,
    protocol_git_spec: str,
    evidence_git_spec: str,
    arm: str,
) -> MarketPolicyReplayPlan:
    """Reconstruct an entry-only policy binding from immutable authorities.

    Neither the protocol nor the diagnostic may self-declare the strategy,
    data, cost, or time identity.  Those values are rebuilt from the already
    validated HistorySpec and current committed source.
    """

    if not _MARKET_POLICY_PROTOCOL.fullmatch(str(protocol_git_spec or "")):
        raise ValueError("market_policy_protocol_exact_git_ref_required")
    if not _MARKET_POLICY_EVIDENCE.fullmatch(str(evidence_git_spec or "")):
        raise ValueError("market_policy_evidence_exact_git_ref_required")
    if arm not in _MARKET_POLICY_ARMS:
        raise ValueError("market_policy_arm_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source_head or "")):
        raise ValueError("market_policy_source_head_invalid")

    root = Path(repo_root).resolve()
    protocol_raw = _read_git_blob(root, protocol_git_spec)
    evidence_raw = _read_git_blob(root, evidence_git_spec)
    protocol_sha = hashlib.sha256(protocol_raw).hexdigest()
    evidence_sha = hashlib.sha256(evidence_raw).hexdigest()
    try:
        protocol = json.loads(protocol_raw)
        evidence = json.loads(evidence_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("market_policy_authority_json_invalid") from exc
    if (
        protocol.get("schema_version")
        != "market_state_conditional_policy_protocol_v1"
        or protocol.get("status") != "frozen_before_diagnostic"
    ):
        raise ValueError("market_policy_protocol_invalid")
    if (
        evidence.get("schema_version") != "market_state_stage_diagnostic_v1"
        or evidence.get("status")
        != "completed_exploratory_research_only"
    ):
        raise ValueError("market_policy_evidence_invalid")
    unsigned_evidence = dict(evidence)
    evidence_hash = unsigned_evidence.pop("evidence_hash", None)
    if evidence_hash != shared_digest(unsigned_evidence):
        raise ValueError("market_policy_evidence_content_hash_mismatch")

    protocol_commit, protocol_path = protocol_git_spec.split(":", 1)
    evidence_protocol = evidence.get("protocol") or {}
    if (
        evidence_protocol.get("path") != protocol_path
        or evidence_protocol.get("commit") != protocol_commit
        or evidence_protocol.get("sha256") != protocol_sha
        or evidence_protocol.get("protocol_id") != protocol.get("protocol_id")
    ):
        raise ValueError("market_policy_evidence_protocol_mismatch")

    data = spec.payload["data"]
    expected_source = {
        "manifest_git_spec": data["manifest_git_spec"],
        "manifest_sha256": data["manifest_sha256"],
        "aggregate_sha256": data["aggregate_sha256"],
    }
    protocol_source = protocol.get("source") or {}
    evidence_source = evidence.get("source") or {}
    if any(protocol_source.get(key) != value for key, value in expected_source.items()):
        raise ValueError("market_policy_protocol_data_binding_mismatch")
    if (
        any(evidence_source.get(key) != value for key, value in expected_source.items())
        or evidence_source.get("data_version") != data["dataset_version"]
    ):
        raise ValueError("market_policy_evidence_data_binding_mismatch")

    window = protocol.get("window") or {}
    if evidence.get("window") != window:
        raise ValueError("market_policy_evidence_window_mismatch")
    warmup = _utc_hour(
        window.get("warmup_start_utc"), reason="market_policy_window_invalid"
    )
    analysis_start = _utc_hour(
        window.get("analysis_start_utc"), reason="market_policy_window_invalid"
    )
    analysis_end = _utc_hour(
        window.get("analysis_end_exclusive_utc"),
        reason="market_policy_window_invalid",
    )
    expected_bars = window.get("expected_analysis_bars")
    if (
        warmup != spec.warmup_start
        or analysis_start != spec.start
        or not analysis_start < analysis_end <= spec.end
        or type(expected_bars) is not int
        or expected_bars <= 0
        or int((analysis_end - analysis_start).total_seconds() / 3600)
        != expected_bars
        or window.get("bar_size") != "1h"
        or window.get("calendar") != "UTC_24x7"
    ):
        raise ValueError("market_policy_window_not_bound_to_history_spec")

    state_contract = protocol.get("state_definition") or {}
    definition = StateDefinitionV2(
        horizons=tuple(state_contract.get("horizons") or ()),
        primary_horizon=state_contract.get("primary_horizon"),
        volatility_history_bars=state_contract.get("volatility_history_bars"),
        state_history_bars=state_contract.get("state_history_bars"),
        minimum_history_observations=state_contract.get(
            "minimum_history_observations"
        ),
        calendar=window.get("calendar"),
        periods_per_year=state_contract.get("periods_per_year"),
        max_age_seconds=state_contract.get("max_age_seconds"),
        definition_version=state_contract.get("definition_version"),
    )
    description = evidence.get("description") or {}
    if (
        description.get("definition_version") != definition.definition_version
        or description.get("definition_hash") != definition.definition_hash
    ):
        raise ValueError("market_policy_evidence_definition_mismatch")
    trial = evidence.get("policy_trial") or {}
    runtime_status = evidence.get("runtime_status") or {}
    if (
        trial.get("status") != "not_started"
        or trial.get("effect_verified") is not False
        or runtime_status.get("entry_policy_enabled") is not False
        or runtime_status.get("attachment_consumed_by_btc_runtime") is not False
        or runtime_status.get("execution_effect_observed") is not False
    ):
        raise ValueError("market_policy_evidence_not_pretrial")
    if any(evidence.get(key) is not False for key in MARKET_POLICY_SAFETY_KEYS):
        raise ValueError("market_policy_evidence_safety_invalid")

    source = StateSourceBinding(
        data_version=data["dataset_version"],
        manifest_git_spec=data["manifest_git_spec"],
        manifest_sha256=data["manifest_sha256"],
        aggregate_sha256=data["aggregate_sha256"],
        source_evidence_hash=evidence_sha,
    )
    hypothesis = protocol.get("entry_policy_hypothesis") or {}
    if (
        hypothesis.get("policy_version") != "entry_path_efficiency_72h_v1"
        or hypothesis.get("enabled_in_current_runtime") is not False
    ):
        raise ValueError("market_policy_hypothesis_invalid")
    policy = EntryOnlyPolicyV1(
        state_definition_hash=definition.definition_hash,
        source_binding_hash=source.binding_hash,
        source_evidence_hash=evidence_sha,
        enabled=arm == "conditioned",
    )
    strategy = spec.payload["strategy"]
    execution = spec.payload["execution"]
    base = MarketPolicyBaseBinding(
        strategy_id=strategy["strategy_id"],
        strategy_version=strategy["strategy_version"],
        source_head=source_head,
        params_hash=strategy["params_hash"],
        data_version=data["dataset_version"],
        instrument="BTC-USDT-SWAP",
        bar_size="1h",
        settlement_currency="USDT",
        base_package_hash=package_digest(
            strategy_id=strategy["strategy_id"],
            strategy_version=strategy["strategy_version"],
            params_hash=strategy["params_hash"],
            code_version=source_head,
        ),
        base_spec_hash=spec.digest,
        cost_contract_hash=_sha(
            {
                "matching": execution["matching"],
                "cost": execution["cost"],
                "protection": execution["protection"],
                "protection_time": PROTECTION_TIME_POLICY,
                "funding_interval_hours": execution["funding_interval_hours"],
                "funding_mark": execution["funding_mark"],
            }
        ),
        time_contract_hash=_sha(
            {
                "bar_size": "1h",
                "calendar": "UTC_24x7",
                "event_time": "bar_open_utc",
                "available_time": "event_time_plus_1h",
                "decision_time": "available_time",
                "warmup_start": warmup.isoformat(),
                "analysis_start": analysis_start.isoformat(),
                "analysis_end_exclusive": analysis_end.isoformat(),
                "expected_analysis_bars": expected_bars,
            }
        ),
    )
    attachment = build_market_policy_attachment(
        base=base,
        definition=definition,
        policy=policy,
        source=source,
        evidence_ref=evidence_git_spec,
        evidence_sha256=evidence_sha,
    )
    errors = validate_market_policy_attachment(
        attachment,
        base=base,
        definition=definition,
        policy=policy,
        source=source,
    )
    if errors:
        raise ValueError("market_policy_attachment_invalid:" + ",".join(errors))
    return MarketPolicyReplayPlan(
        arm=arm,
        protocol_git_spec=protocol_git_spec,
        protocol_blob_sha256=protocol_sha,
        evidence_git_spec=evidence_git_spec,
        evidence_blob_sha256=evidence_sha,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        expected_analysis_bars=expected_bars,
        definition=definition,
        source=source,
        policy=policy,
        attachment=attachment,
    )


def _read_git_blob(repo_root: Path, git_spec: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", git_spec], cwd=repo_root
    )


def load_historical_input(
    repo_root: Path, *, shared_root: Path | None = None, spec: HistorySpec | None = None
) -> HistoricalInput:
    root = Path(repo_root).resolve()
    spec = spec or legacy_spec()
    data = spec.payload["data"]
    raw_manifest = _read_git_blob(root, data["manifest_git_spec"])
    manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
    if manifest_sha != data["manifest_sha256"]:
        raise ValueError("historical_manifest_blob_sha256_mismatch")
    manifest = load_manifest_from_git(root, data["manifest_git_spec"])
    if (
        manifest.get("dataset_id") != data["dataset_id"]
        or manifest.get("dataset_version") != data["dataset_version"]
        or manifest.get("aggregate_sha256") != data["aggregate_sha256"]
    ):
        raise ValueError("historical_manifest_identity_mismatch")
    inventory = {str(row["path"]): str(row["sha256"]) for row in manifest["files"]}
    for name, expected in data["files"].items():
        if inventory.get(f"{data['prefix']}/{name}") != expected:
            raise ValueError(f"historical_manifest_file_hash_mismatch:{name}")
    physical = resolve_manifest_payload(
        manifest,
        shared_root=(Path(shared_root).resolve() if shared_root else default_shared_data_root(root)),
        verify_files=True,
    )
    source = (physical / data["prefix"]).resolve()
    if not source.is_relative_to(physical.resolve()):
        raise ValueError("historical_data_prefix_escape")
    bars = pd.read_parquet(source / "daily_bars.parquet")
    marks = pd.read_parquet(source / "mark.parquet")
    premium = pd.read_parquet(source / "premium.parquet")
    funding = pd.read_parquet(source / "funding.parquet")

    bars, marks, premium, funding = validate_tables(spec, bars, marks, premium, funding)
    selected = bars.loc[
        (bars["event_time"] >= spec.start)
        & (bars["event_time"] < spec.end)
    ].copy()
    if len(selected) != spec.signal_rows:
        raise ValueError("historical_signal_window_row_count_mismatch")
    first_index = int(selected.index[0])
    if first_index != spec.warmup_rows:
        raise ValueError("historical_warmup_row_count_mismatch")
    consumed = bars.iloc[: spec.warmup_rows + spec.signal_rows].copy()
    frame = pd.DataFrame(
        {
            "open_time": pd.to_datetime(consumed["event_time"], utc=True).to_numpy(),
            "open": consumed["open"].astype(float).to_numpy(),
            "high": consumed["high"].astype(float).to_numpy(),
            "low": consumed["low"].astype(float).to_numpy(),
            "close": consumed["close"].astype(float).to_numpy(),
            "volume": consumed["volume"].astype(float).to_numpy(),
        },
        index=pd.DatetimeIndex(pd.to_datetime(consumed["available_time"], utc=True)),
    )
    mark_by_event = {
        row.event_time.to_pydatetime(): row._asdict()
        for row in marks.itertuples(index=False)
    }
    premium_by_event = {
        row.event_time.to_pydatetime(): row._asdict()
        for row in premium.itertuples(index=False)
    }
    funding_rows: list[HistoricalFundingEvent] = []
    for row in funding.itertuples(index=False):
        settlement = row.event_time.to_pydatetime()
        # The settlement exactly at the signal-window boundary is observed
        # while the frozen account is still flat; it has no eligible position
        # and is not invented as a zero-value economic bill.  The following
        # scheduled settlements are replayed as first-class bills.
        if settlement <= spec.start or settlement > spec.end:
            continue
        reported = Decimal(str(row.markPrice))
        if reported.is_finite() and reported > 0:
            mark_price = reported
            policy = "reported_mark_price"
        else:
            prior = mark_by_event.get(settlement - timedelta(hours=1))
            if prior is None or pd.Timestamp(prior["available_time"]).to_pydatetime() > settlement:
                raise ValueError("historical_funding_visible_mark_missing")
            mark_price = Decimal(str(prior["close"]))
            policy = "funding_mark_sampling_approximation_t_minus_1h_close"
        funding_rows.append(
            HistoricalFundingEvent(
                settlement_time_utc=settlement,
                available_time_utc=row.available_time.to_pydatetime(),
                rate=Decimal(str(row.fundingRate)),
                mark_price=mark_price,
                source_record_id=str(row.source_record_id),
                mark_price_policy=policy,
            )
        )
    return HistoricalInput(
        manifest=dict(manifest),
        manifest_sha256=manifest_sha,
        dataset_root=physical,
        frame=frame,
        signal_rows=selected,
        mark_by_event=mark_by_event,
        premium_by_event=premium_by_event,
        funding_events=tuple(funding_rows),
    )


class DonchianHistoricalReplay:
    def __init__(
        self,
        *,
        repo_root: Path,
        output_root: Path,
        run_id: str,
        shared_root: Path | None = None,
        spec_git: str | None = None,
        market_policy_protocol_git: str | None = None,
        market_policy_evidence_git: str | None = None,
        market_policy_arm: str | None = None,
        spec: HistorySpec | None = None,
        historical_input: HistoricalInput | None = None,
        coordination_projection_enabled: bool = False,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.output_root, self.run_root = _resolve_run_root(output_root, run_id)
        if self.repo_root == self.output_root or self.repo_root in self.output_root.parents:
            raise ValueError("historical_output_root_must_be_outside_git")
        self.run_id = run_id
        self.coordination_projection_enabled = coordination_projection_enabled
        if spec is not None and spec_git is not None:
            raise ValueError("historical_spec_authority_ambiguous")
        self.spec = spec if spec is not None else (HistorySpec.from_git(self.repo_root, spec_git) if spec_git else legacy_spec())
        self.input = historical_input if historical_input is not None else load_historical_input(
            self.repo_root, shared_root=shared_root, spec=self.spec)
        self.source_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo_root, text=True
        ).strip()
        policy_parts = (
            market_policy_protocol_git,
            market_policy_evidence_git,
            market_policy_arm,
        )
        if any(value is not None for value in policy_parts):
            if not all(isinstance(value, str) and value for value in policy_parts):
                raise ValueError("market_policy_replay_binding_incomplete")
            self.market_policy_plan = build_market_policy_replay_plan(
                repo_root=self.repo_root,
                spec=self.spec,
                source_head=self.source_head,
                protocol_git_spec=str(market_policy_protocol_git),
                evidence_git_spec=str(market_policy_evidence_git),
                arm=str(market_policy_arm),
            )
        else:
            self.market_policy_plan = None
        data = self.spec.payload["data"]
        self.identity = {
            "schema_version": "btc_donchian_historical_identity_v1",
            "run_id": run_id,
            "code_version": self.source_head,
            "manifest_git_spec": data["manifest_git_spec"],
            "manifest_sha256": data["manifest_sha256"],
            "aggregate_sha256": data["aggregate_sha256"],
            "dataset_version": data["dataset_version"],
            "spec_digest": self.spec.digest,
            "spec_git": self.spec.git_spec,
            "spec_blob_sha256": self.spec.blob_sha256,
            "strategy": self.spec.payload["strategy"],
            "signal_event_start": self.spec.start.isoformat(),
            "signal_event_end": self.spec.end.isoformat(),
            "warmup_rows": self.spec.warmup_rows,
            "signal_rows": self.spec.signal_rows,
            "account_equity_usdt": "5000",
            "order_contracts": "0.01",
            "matching_policy_hash": _sha(MATCHING_POLICY),
            "cost_policy_hash": _sha(COST_POLICY),
            "protection_policy_hash": _sha(PROTECTION_POLICY),
            "protection_time_policy_hash": _sha(PROTECTION_TIME_POLICY),
        }
        if self.market_policy_plan is not None:
            plan = self.market_policy_plan
            self.identity["schema_version"] = (
                "btc_donchian_historical_identity_v2"
            )
            self.identity["market_entry_policy"] = {
                "arm": plan.arm,
                "protocol_git_spec": plan.protocol_git_spec,
                "protocol_blob_sha256": plan.protocol_blob_sha256,
                "evidence_git_spec": plan.evidence_git_spec,
                "evidence_blob_sha256": plan.evidence_blob_sha256,
                "attachment_hash": plan.attachment["attachment_hash"],
                "policy_hash": plan.policy.policy_hash,
                "analysis_end_exclusive": plan.analysis_end.isoformat(),
                "expected_analysis_bars": plan.expected_analysis_bars,
            }
        self.identity["identity_digest"] = _sha(self.identity)

    @property
    def evaluation_rows(self) -> pd.DataFrame:
        if self.market_policy_plan is None:
            return self.input.signal_rows
        return self.input.signal_rows.loc[
            self.input.signal_rows["event_time"]
            < self.market_policy_plan.analysis_end
        ].copy()

    @property
    def expected_event_count(self) -> int:
        if self.market_policy_plan is None:
            return self.spec.signal_rows
        return self.market_policy_plan.expected_analysis_bars

    @property
    def artifact_path(self) -> Path:
        return _resolve_run_child(self.run_root, "historical_replay.json")

    @property
    def identity_path(self) -> Path:
        return _resolve_run_child(self.run_root, "historical_identity.json")

    @property
    def lock_path(self) -> Path:
        return _resolve_run_child(self.run_root, "writer.lock")

    @property
    def coordination_projection_path(self) -> Path:
        return _resolve_run_child(self.run_root, "coordination_projection.json")

    def _decision_time(self, completed: datetime, ordinal: int, phase: str) -> datetime:
        del phase
        return completed.astimezone(timezone.utc) + timedelta(seconds=1, milliseconds=ordinal)

    def _event_bar(self, row: Any) -> HistoricalBar:
        event = row.event_time.to_pydatetime()
        mark = self.input.mark_by_event.get(event)
        premium = self.input.premium_by_event.get(event)
        if mark is None or premium is None:
            raise ValueError("historical_mark_or_index_bar_missing")
        if pd.Timestamp(mark["available_time"]).to_pydatetime() > row.available_time.to_pydatetime():
            raise ValueError("historical_mark_bar_from_future")
        return HistoricalBar(
            event_time_utc=event,
            available_time_utc=row.available_time.to_pydatetime(),
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            mark_open=Decimal(str(mark["open"])),
            mark_high=Decimal(str(mark["high"])),
            mark_low=Decimal(str(mark["low"])),
            mark_close=Decimal(str(mark["close"])),
            index_close=Decimal(str(premium["index_close"])),
        )

    def _funding_for_decision(self, decision: datetime, previous: datetime | None) -> tuple[HistoricalFundingEvent, ...]:
        lower = previous or (self.spec.start - timedelta(microseconds=1))
        return tuple(
            row
            for row in self.input.funding_events
            if lower < row.settlement_time_utc <= decision
        )

    def _new_market_state_stream(self) -> CausalStateStreamV2:
        if self.market_policy_plan is None:
            raise ValueError("market_policy_plan_missing")
        plan = self.market_policy_plan
        stream = CausalStateStreamV2(
            asset="BTC-USDT-SWAP",
            definition=plan.definition,
            source=plan.source,
        )
        warmup = self.input.frame.iloc[: self.spec.warmup_rows]
        if len(warmup) != self.spec.warmup_rows:
            raise ValueError("market_policy_warmup_rows_missing")
        for close_time, row in warmup.iterrows():
            close = pd.Timestamp(close_time).to_pydatetime().astimezone(timezone.utc)
            event = pd.Timestamp(row["open_time"]).to_pydatetime().astimezone(
                timezone.utc
            )
            stream.push(
                Bar(
                    asset="BTC-USDT-SWAP",
                    event_time=event,
                    close_time=close,
                    available_time=close,
                    close=float(row["close"]),
                    completed=True,
                ),
                expected_close_time=close,
                decision_time=close,
            )
        return stream

    def _market_state_stream_for_artifact(
        self, artifact: Mapping[str, Any]
    ) -> CausalStateStreamV2 | None:
        if self.market_policy_plan is None:
            return None
        state = artifact.get("market_state_replay")
        if state is None:
            if artifact.get("events"):
                raise ValueError("market_policy_state_snapshot_missing")
            return self._new_market_state_stream()
        if not isinstance(state, Mapping):
            raise ValueError("market_policy_state_snapshot_invalid")
        if state.get("event_count") != len(artifact.get("events") or []):
            raise ValueError("market_policy_state_snapshot_event_count_mismatch")
        frozen = state.get("stream_snapshot")
        if not isinstance(frozen, Mapping):
            raise ValueError("market_policy_state_snapshot_invalid")
        return CausalStateStreamV2.restore(
            frozen,
            definition=self.market_policy_plan.definition,
            source=self.market_policy_plan.source,
        )

    def _push_market_state(
        self, stream: CausalStateStreamV2, row: Any
    ) -> MarketStateV2:
        event = row.event_time.to_pydatetime().astimezone(timezone.utc)
        close = row.available_time.to_pydatetime().astimezone(timezone.utc)
        return stream.push(
            Bar(
                asset="BTC-USDT-SWAP",
                event_time=event,
                close_time=close,
                available_time=close,
                close=float(row.close),
                completed=True,
            ),
            expected_close_time=close,
            decision_time=close,
        )

    @staticmethod
    def _store_market_state_snapshot(
        artifact: dict[str, Any],
        *,
        stream: CausalStateStreamV2,
        observation: MarketStateV2 | None,
    ) -> None:
        artifact["market_state_replay"] = {
            "event_count": len(artifact.get("events") or []),
            "stream_snapshot": stream.freeze(),
            "last_observation": (
                observation.to_dict() if observation is not None else None
            ),
        }

    def _load_or_create_artifact(self) -> dict[str, Any]:
        if self.identity_path.exists():
            observed = json.loads(self.identity_path.read_text(encoding="utf-8"))
            if observed != self.identity:
                raise ValueError("historical_run_identity_mismatch")
        else:
            _atomic(self.identity_path, self.identity)
        if self.artifact_path.exists():
            artifact = json.loads(self.artifact_path.read_text(encoding="utf-8"))
            if artifact.get("identity_digest") != self.identity["identity_digest"]:
                raise ValueError("historical_artifact_identity_mismatch")
            return artifact
        artifact = {
            "schema_version": "btc_donchian_historical_replay_v1",
            "identity_digest": self.identity["identity_digest"],
            "evaluation_spec": self.spec.payload,
            "data": {
                **self.spec.payload["data"],
                "readiness": "historical_reconstructed_offline_only",
                "available_time_provenance": "post_hoc_reconstruction_not_exchange_receipt",
                "physical_root_redacted": True,
            },
            "policies": {
                "matching": MATCHING_POLICY,
                "cost": COST_POLICY,
                "protection": PROTECTION_POLICY,
                "protection_time": PROTECTION_TIME_POLICY,
                "funding": {
                    "same_timestamp_order": "settlement_before_new_fill",
                    "missing_mark": "t_minus_1h_visible_mark_close_approximation",
                    "window_start": "observed_flat_not_eligible_no_zero_bill_invented",
                },
            },
            "events": [],
            "blockers": [],
            "status": "running",
            "safety": SAFETY,
        }
        if self.market_policy_plan is not None:
            plan = self.market_policy_plan
            artifact["schema_version"] = "btc_donchian_historical_replay_v2"
            artifact["market_entry_policy"] = {
                "arm": plan.arm,
                "protocol_git_spec": plan.protocol_git_spec,
                "protocol_blob_sha256": plan.protocol_blob_sha256,
                "evidence_git_spec": plan.evidence_git_spec,
                "evidence_blob_sha256": plan.evidence_blob_sha256,
                "analysis_start_utc": plan.analysis_start.isoformat(),
                "analysis_end_exclusive_utc": plan.analysis_end.isoformat(),
                "expected_analysis_bars": plan.expected_analysis_bars,
                "attachment": dict(plan.attachment),
                "interpretation": "exploratory_entry_policy_ab_not_promotion",
            }
        return artifact

    def _acquire(self) -> int:
        self.run_root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.lseek(descriptor, 0, os.SEEK_SET)
            prior=os.read(descriptor,4096).decode("ascii",errors="strict")
            if prior and not prior.startswith("schema=historical_replay_os_lease_v1\n"):
                match=re.fullmatch(r"pid=([0-9]+)\n?",prior)
                if match is None or self._process_alive_conservative(int(match.group(1))):
                    raise RuntimeError("historical_replay_legacy_writer_lock_held_or_unknown")
        except (OSError, IOError) as exc:
            os.close(descriptor)
            raise RuntimeError("historical_replay_writer_lock_held") from exc
        except BaseException:
            os.close(descriptor)
            raise
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor,0,os.SEEK_SET)
        os.write(descriptor, f"schema=historical_replay_os_lease_v1\npid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        return descriptor

    @staticmethod
    def _process_alive_conservative(pid: int) -> bool:
        if pid <= 0: return True
        if os.name == "nt":
            import ctypes
            kernel=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle: return ctypes.get_last_error()!=87
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.CloseHandle(handle)
            return True
        try: os.kill(pid,0); return True
        except ProcessLookupError: return False
        except PermissionError: return True

    def _release(self, descriptor: int) -> None:
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def run(self, *, max_events: int | None = None,
            before_event: Callable[[int, Mapping[str, Any]], bool] | None = None,
            after_event: Callable[[int, Mapping[str, Any]], None] | None = None) -> Mapping[str, Any]:
        if after_event is not None and not self.coordination_projection_enabled:
            raise ValueError("historical_coordination_projection_not_enabled")
        preexisting_material = self.run_root.exists()
        descriptor = self._acquire()
        try:
            artifact = self._load_or_create_artifact()
            if artifact.get("status") == "blocked":
                return artifact
            if preexisting_material:
                venue_path = _resolve_run_child(
                    self.run_root, "state", "offline_venue.json"
                )
                venue, errors = load_historical_venue_state(venue_path)
                if venue is None or errors:
                    return self._finalize(artifact)
            market_stream = self._market_state_stream_for_artifact(artifact)
            market_state_holder: dict[str, MarketStateV2] = {}
            if market_stream is not None and "market_state_replay" not in artifact:
                self._store_market_state_snapshot(
                    artifact,
                    stream=market_stream,
                    observation=None,
                )
                _atomic(self.artifact_path, artifact)
            processed = {str(row["event_time_utc"]) for row in artifact["events"]}
            evaluation_rows = self.evaluation_rows
            if len(evaluation_rows) != self.expected_event_count:
                raise ValueError("historical_evaluation_row_count_mismatch")
            remaining = [row for row in evaluation_rows.itertuples(index=False) if row.event_time.to_pydatetime().isoformat() not in processed]
            if max_events is not None:
                if max_events <= 0:
                    raise ValueError("historical_max_events_invalid")
                remaining = remaining[:max_events]
            if not remaining:
                return self._finalize(artifact)

            first = remaining[0]
            first_bar = self._event_bar(first)
            first_decision = first.available_time.to_pydatetime()
            def venue_factory(path: Path, now: datetime) -> HistoricalOfflineVenue:
                is_new = not path.exists()
                seed = HistoricalOfflineVenue(path, now=now)
                if not is_new:
                    return seed
                seed.now = self._decision_time(first_decision, 0, "primary")
                next_row = evaluation_rows.loc[evaluation_rows["event_time"] == first.available_time]
                next_open = None if next_row.empty else Decimal(str(next_row.iloc[0]["open"]))
                seed.advance(
                    completed_bar=first_bar,
                    next_bar_open=next_open,
                    funding_events=self._funding_for_decision(first_decision, None),
                )
                return seed

            runner = DonchianOfflineReplay(
                DonchianOfflineReplayConfig(
                    repo_root=self.repo_root,
                    state_dir=_resolve_run_child(self.run_root, "state"),
                    run_id=self.run_id,
                    decision_time_utc=first_decision,
                    data_version=self.spec.payload["data"]["dataset_version"],
                    venue_factory=venue_factory,
                    decision_time_provider=self._decision_time,
                    max_notional_usdt=Decimal(self.spec.payload["execution"].get("max_notional_usdt", "10")),
                    market_entry_policy=(
                        self.market_policy_plan.policy
                        if self.market_policy_plan is not None
                        else None
                    ),
                    market_state_provider=(
                        (lambda _frame: market_state_holder["state"])
                        if self.market_policy_plan is not None
                        else None
                    ),
                    market_policy_attachment=(
                        self.market_policy_plan.attachment
                        if self.market_policy_plan is not None
                        else None
                    ),
                )
            )
            previous_decision = (
                datetime.fromisoformat(artifact["events"][-1]["decision_time_utc"])
                if artifact["events"]
                else None
            )
            try:
                for row in remaining:
                    next_cursor=len(artifact["events"])+1
                    if before_event is not None and before_event(next_cursor,row._asdict()) is False:
                        break
                    event = row.event_time.to_pydatetime()
                    decision = row.available_time.to_pydatetime()
                    next_row = evaluation_rows.loc[evaluation_rows["event_time"] == row.available_time]
                    next_open = None if next_row.empty else Decimal(str(next_row.iloc[0]["open"]))
                    runner.venue.now = self._decision_time(decision, len(artifact["events"]), "primary")
                    bar = self._event_bar(row)
                    funding = self._funding_for_decision(decision, previous_decision)
                    try:
                        market_observation = None
                        if market_stream is not None:
                            market_observation = self._push_market_state(
                                market_stream, row
                            )
                            market_state_holder["state"] = market_observation
                        venue_before_advance = deepcopy(runner.venue.state)
                        runner.venue.advance(completed_bar=bar, next_bar_open=next_open, funding_events=funding)
                        prefix = self.input.frame.loc[: pd.Timestamp(decision)].copy(deep=True)
                        phases: list[Mapping[str, Any]] = []
                        if next_open is None:
                            terminal_receipt = runner.reconcile_terminal_observation(
                                completed_bar=decision, observation_time=runner.venue.now
                            )
                            preview = runner.evaluate_frame(prefix)
                            phases.append(
                                {
                                    "phase": "no_next_bar",
                                    "decision_outcome": "unfilled_no_next_bar",
                                    "signal": dict(preview),
                                    "evidence_links": terminal_receipt,
                                }
                            )
                        else:
                            result = runner.run_frame(prefix)
                            phases.append(self._phase_evidence(result))
                            if result["phase"] == "reversal_close":
                                result = runner.run_frame(prefix)
                                phases.append(self._phase_evidence(result))
                        artifact["events"].append(
                            {
                                "event_time_utc": event.isoformat(),
                                "decision_time_utc": decision.isoformat(),
                                "next_bar_open_available": next_open is not None,
                                "funding_settlements": [
                                    {
                                        "source_record_id": item.source_record_id,
                                        "settlement_time_utc": item.settlement_time_utc.isoformat(),
                                        "mark_price_policy": item.mark_price_policy,
                                    }
                                    for item in funding
                                ],
                                "phases": phases,
                                "position_contracts": runner.venue.state["position"],
                                "cash_usdt": runner.venue.state["cash"],
                                "equity_usdt": runner.venue.state["equity"],
                                "fees_usdt": runner.venue.state["fee_total"],
                                "funding_usdt": runner.venue.state["funding_total"],
                            }
                        )
                        if market_stream is not None:
                            self._store_market_state_snapshot(
                                artifact,
                                stream=market_stream,
                                observation=market_observation,
                            )
                        previous_decision = decision
                        _atomic(self.artifact_path, artifact)
                        if self.coordination_projection_enabled:
                            committed={
                                "schema_version":"btc_donchian_coordination_projection_v1",
                                "cursor":len(artifact["events"]),
                                "event":deepcopy(artifact["events"][-1]),
                                "venue":deepcopy(runner.venue.state),
                                "ledger":deepcopy(runner.controller._state.get("ledger_reconciliation",{}).get("account_ledger_replay")),
                                "artifact_identity_digest":artifact["identity_digest"],
                            }
                            committed["sha256"]=_sha(committed)
                            _atomic(self.coordination_projection_path,committed)
                            if after_event is not None:
                                after_event(len(artifact["events"]),committed)
                    except (OkxDemoPaperRuntimeError, ProtectionTriggerAmbiguous, ValueError) as exc:
                        blocker = f"{type(exc).__name__}:{exc}"
                        if blocker not in artifact["blockers"]:
                            artifact["blockers"].append(blocker)
                        artifact["status"] = "blocked"
                        artifact["blocked_event_time_utc"] = event.isoformat()
                        if market_stream is not None:
                            self._store_market_state_snapshot(
                                artifact,
                                stream=market_stream,
                                observation=market_state_holder.get("state"),
                            )
                        _atomic(self.artifact_path, artifact)
                        break
            finally:
                runner.close()
            return self._finalize(artifact)
        finally:
            self._release(descriptor)

    @staticmethod
    def _phase_evidence(result: Mapping[str, Any]) -> Mapping[str, Any]:
        links = dict(result.get("evidence", {}).get("links", {}))
        signal = dict(result.get("signal", {}))
        return {
            "phase": result.get("phase"),
            "decision_outcome": links.get("decision_outcome") or result.get("decision_outcome"),
            "signal": {
                "raw_signal": signal.get("raw_signal"),
                "direction": signal.get("direction"),
                "target_contracts": signal.get("target_contracts"),
            },
            "market_entry_policy": result.get("market_entry_policy"),
            "evidence_links": {
                "signal_id": links.get("signal_id"),
                "target_position_id": links.get("target_position_id"),
                "risk_check_id": links.get("risk_check_id"),
                "order_intent_id": links.get("order_intent_id"),
                "client_order_id": links.get("client_order_id"),
                "exchange_order_id": links.get("exchange_order_id"),
                "fill_ids": list(links.get("fill_ids") or []),
                "ledger_event_id": links.get("ledger_event_id"),
                "ledger_event_hash": links.get("ledger_event_hash"),
            },
        }

    def _finalize(self, artifact: dict[str, Any]) -> Mapping[str, Any]:
        venue_path = _resolve_run_child(
            self.run_root, "state", "offline_venue.json"
        )
        venue, venue_errors = load_historical_venue_state(venue_path)
        phases = [phase for row in artifact["events"] for phase in row["phases"]]
        market_policy_decisions = [
            phase.get("market_entry_policy")
            for phase in phases
            if isinstance(
                phase.get("market_entry_policy"), Mapping
            )
        ]
        if venue is None or venue_errors:
            if _PERSISTED_VENUE_BLOCKER not in artifact["blockers"]:
                artifact["blockers"].append(_PERSISTED_VENUE_BLOCKER)
            artifact["persistent_venue_state_errors"] = list(venue_errors)
            artifact["status"] = "blocked"
            artifact["counts"] = {
                "processed_events": len(artifact["events"]),
                "decision_phases": len(phases),
                "directional_signal_decisions": sum(
                    1
                    for phase in phases
                    if str(phase.get("signal", {}).get("direction") or "")
                    in {"long", "short"}
                ),
                "hold_decisions": sum(
                    1 for phase in phases if phase.get("phase") == "hold"
                ),
                "order_terminal_decisions": sum(
                    1
                    for phase in phases
                    if phase.get("decision_outcome") == "order_terminal"
                ),
                "orders": None,
                "fills": None,
                "funding_bill_observations": None,
                "nonzero_funding_cashflow_bills": None,
                "blockers": len(artifact["blockers"]),
                "market_policy_decisions": len(market_policy_decisions),
                "new_entries_rejected": sum(
                    1
                    for row in market_policy_decisions
                    if row.get("applied") is True
                    and row.get("effective_target_contracts") == "0"
                    and row.get("original_target_contracts") not in {None, "0"}
                ),
            }
            artifact["marked_state"] = {"status": "unverified"}
            artifact["safety"] = SAFETY
            _atomic(self.artifact_path, artifact)
            return artifact
        bills = list(venue["bills"])
        artifact["counts"] = {
            "processed_events": len(artifact["events"]),
            "decision_phases": len(phases),
            "directional_signal_decisions": sum(
                1
                for phase in phases
                if str(phase.get("signal", {}).get("direction") or "")
                in {"long", "short"}
            ),
            "hold_decisions": sum(
                1 for phase in phases if phase.get("phase") == "hold"
            ),
            "order_terminal_decisions": sum(
                1
                for phase in phases
                if phase.get("decision_outcome") == "order_terminal"
            ),
            "orders": len(venue["orders"]),
            "fills": len(venue["fills"]),
            "funding_bill_observations": len(bills),
            "nonzero_funding_cashflow_bills": sum(
                1 for row in bills if Decimal(str(row.get("balChg") or "0")) != 0
            ),
            "blockers": len(artifact["blockers"]),
            "market_policy_decisions": len(market_policy_decisions),
            "new_entries_rejected": sum(
                1
                for row in market_policy_decisions
                if row.get("applied") is True
                and row.get("effective_target_contracts") == "0"
                and row.get("original_target_contracts") not in {None, "0"}
            ),
        }
        artifact["marked_state"] = {
            "position_contracts": venue["position"],
            "average_price": venue["avg_price"],
            "cash_usdt": venue["cash"],
            "unrealized_pnl_usdt": venue["unrealized_pnl"],
            "realized_pnl_usdt": venue["realized_pnl"],
            "equity_usdt": venue["equity"],
            "fees_usdt": venue["fee_total"],
            "funding_usdt": venue["funding_total"],
            "terminal_liquidation": False,
        }
        if artifact.get("status") != "blocked":
            expected_rows = (
                self.expected_event_count
                if hasattr(self, "spec")
                else SIGNAL_ROWS
            )
            artifact["status"] = "complete" if len(artifact["events"]) == expected_rows else "checkpoint"
        artifact["safety"] = SAFETY
        _atomic(self.artifact_path, artifact)
        return artifact

    @classmethod
    def status(cls, *, output_root: Path, run_id: str) -> Mapping[str, Any]:
        _, run_root = _resolve_run_root(output_root, run_id)
        path = _resolve_run_child(run_root, "historical_replay.json")
        if not path.is_file():
            return {"status": "not_started", "run_id": run_id, "safety": SAFETY}
        artifact = json.loads(path.read_text(encoding="utf-8"))
        venue, venue_errors = load_historical_venue_state(
            _resolve_run_child(run_root, "state", "offline_venue.json")
        )
        if venue is not None and not venue_errors:
            return artifact
        observed = deepcopy(artifact)
        blockers = list(observed.get("blockers") or [])
        if _PERSISTED_VENUE_BLOCKER not in blockers:
            blockers.append(_PERSISTED_VENUE_BLOCKER)
        observed["blockers"] = blockers
        observed["persistent_venue_state_errors"] = list(venue_errors)
        observed["status"] = "blocked"
        observed["marked_state"] = {"status": "unverified"}
        return observed


__all__ = [
    "DonchianHistoricalReplay",
    "HistoricalInput",
    "MarketPolicyReplayPlan",
    "_terminal_ledger_required",
    "build_market_policy_replay_plan",
    "load_historical_input",
]
