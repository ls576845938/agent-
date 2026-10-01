"""Bounded Qlib candidate admission into the existing BTC offline authority chain.

This module is deliberately offline-only.  It resolves one immutable V2
package, replays the frozen candidate policy and provides exact BTC-to-contract
conversion.  The execution fixture below this boundary is explicitly separate
from candidate-effectiveness evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import pandas as pd

from integrations.qlib_adapter.candidate_policy import (
    CandidateExitObservation,
    CandidateExitPolicy,
    CandidateExitState,
    CandidatePolicyFacts,
    CandidatePolicyVersions,
    POLICY_VERSION,
    evaluate_candidate_policy,
)
from integrations.qlib_adapter.frozen_inference import run_frozen_inference
from integrations.qlib_adapter.schemas import load_yaml_file
from quant_crypto.portfolio.forecast import (
    BTCForecast,
    BTCForecastQuality,
    BTCRiskBudget,
    BTCRiskState,
)
from quant_crypto.portfolio.order_intent import BTCExecutionCostEstimate
from quant_crypto.risk import CombinedLossAssessment, RiskConstitution
from quant_crypto.risk.liquidation import BTCReferencePriceState
from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    SignalDirection,
    TargetPosition,
    TimeInForce,
)
from quant_crypto.application.btc_demo_production_composition import (
    BtcDemoProductionComposition,
    canonical_ledger_snapshot_sha256,
)
from quant_crypto.application.donchian_offline_replay import (
    _OfflineCapabilityAdapter,
    _OfflineVenue,
    _atomic_json,
    _sha,
    build_trend_frame,
)
from quant_crypto.application.donchian_offline_history_cache import OfflineLedgerHistoryCache
from quant_crypto.application.donchian_historical_venue import (
    ProtectionTriggerAmbiguous,
    classify_mark_protection_touch,
)
from quant_crypto.application.runtime_risk_guardian import (
    FileGuardianLatchStore,
    GuardianConfig,
    GuardianLatchRecord,
    RuntimeRiskGuardian,
    RuntimeRiskGuardianSupervisor,
)
from quant_crypto.oms.account_risk_facts import (
    ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
    ACCOUNT_DRAWDOWN_SCOPE,
    build_explicit_account_drawdown_baseline,
    build_okx_account_cashflow_evidence,
)
from quant_crypto.oms.okx_demo import OkxDemoResponse
from quant_crypto.oms.okx_demo_paper_runtime import (
    OKX_DEMO_TERMINAL_INTENT_STATUSES,
    OKX_DEMO_APPROVED_PROTECTION_POLICY,
    OKX_DEMO_PAPER_ORDER_TAG,
    OkxDemoPaperRuntimeConfig,
    OkxDemoPaperRuntimeController,
    OkxDemoPaperRuntimeError,
    ServerSideProtectionPolicy,
    _canonical_sha256,
)
from quant_crypto.oms.runtime_store import BTCRuntimeStore
from quant_crypto.runtime.control_plane import BTCDemoExecutionDispatcher
from tools.agent_governance.shared_data import (
    default_shared_data_root,
    load_manifest_from_git,
    resolve_manifest_payload,
)


CONTRACT_SCHEMA_VERSION = "strategy_v3_qlib_offline_contract_v1"
OFFLINE_EVENT_ORDERING = {
    "version": "qlib_offline_event_order_v1",
    "observation_step_ms": 1,
    "maximum_prior_boundary_offset_ms": 2,
    "phases": ["previous_fill_and_ledger", "market_observation", "next_decision"],
    "source_and_forecast_times": "unchanged",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FALSE_PERMISSIONS = {
    "promotion",
    "paper",
    "live",
    "private",
    "order",
    "real_order",
    "transfer",
    "withdraw",
    "execution_permission",
    "runtime_observed",
}


class _QlibOfflineRuntimeController(OkxDemoPaperRuntimeController):
    """Reuse verified offline history without caching risk or execution results."""

    def __init__(self, **kwargs: Any) -> None:
        self._offline_ledger_history = OfflineLedgerHistoryCache()
        try:
            super().__init__(**kwargs)
        except BaseException:
            if hasattr(self, "_runtime_store"):
                try:
                    self._runtime_store.close()
                except BaseException:
                    pass
            raise

    def _create_runtime_store(self) -> BTCRuntimeStore:
        return BTCRuntimeStore(Path(self.config.output_dir), offline_journal_session=True)

    def _replay_reconciled_ledger(self, **options: Any) -> dict[str, Any]:
        return self._offline_ledger_history.replay(**options)


class QlibOfflineReplayError(RuntimeError):
    pass


def _fail(reason: str) -> None:
    raise QlibOfflineReplayError(reason)


def _decision_observation_time(*, source_time: datetime, previous_time: datetime) -> datetime:
    """Order boundary events without rewriting the source candle/forecast time.

    The simulated venue timestamps a fill one millisecond after dispatch. A
    subsequent boundary observation needs its own processing slot; this is not
    permission to rejuvenate old data or to change a control acknowledgement.
    """
    if any(value.tzinfo is None or value.utcoffset() is None for value in (source_time, previous_time)):
        _fail("qlib_offline_event_order_timezone_missing")
    if previous_time - source_time > timedelta(milliseconds=2):
        _fail("qlib_offline_event_order_out_of_order")
    return source_time if source_time > previous_time else previous_time + timedelta(milliseconds=1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_research_digest(value: Any) -> str:
    """Match the immutable research decision identity without consuming it."""

    raw = json.dumps(value, sort_keys=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_v3_contract(path: str | Path, *, repo_root: str | Path) -> dict[str, Any]:
    contract_path = Path(path).resolve()
    root = Path(repo_root).resolve()
    try:
        contract_path.relative_to(root)
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QlibOfflineReplayError("v3_contract_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        _fail("v3_contract_schema_mismatch")
    if payload.get("usage") != "offline_acceptance_only":
        _fail("v3_contract_usage_mismatch")
    permissions = payload.get("permissions")
    if not isinstance(permissions, dict) or set(permissions) != _FALSE_PERMISSIONS:
        _fail("v3_contract_permissions_invalid")
    if any(value is not False for value in permissions.values()):
        _fail("v3_contract_permissions_invalid")
    if payload.get("offline_event_ordering") != OFFLINE_EVENT_ORDERING:
        _fail("v3_contract_event_order_mismatch")
    v2_path = (root / str(payload.get("v2_contract_path") or "")).resolve()
    try:
        v2_path.relative_to(root)
    except ValueError as exc:
        raise QlibOfflineReplayError("v2_contract_path_invalid") from exc
    expected_v2_hash = str(payload.get("v2_contract_sha256") or "")
    if _SHA256.fullmatch(expected_v2_hash) is None or not v2_path.is_file() or _sha256(v2_path) != expected_v2_hash:
        _fail("v2_contract_sha256_mismatch")
    v2 = json.loads(v2_path.read_text(encoding="utf-8"))
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        _fail("v3_candidate_binding_missing")
    checks = {
        "run_id": v2.get("run_id"),
        "candidate_id": v2.get("candidate_id"),
        "strategy_id": v2.get("strategy_id"),
        "strategy_version": v2.get("strategy_version"),
        "model_sha256": v2.get("artifact_sha256", {}).get("model.txt"),
        "data_version": v2.get("data_version"),
        "decision_count": v2.get("decision_count"),
    }
    mismatches = [name for name, expected in checks.items() if candidate.get(name) != expected]
    if mismatches:
        _fail("v3_candidate_binding_mismatch:" + ",".join(mismatches))
    if payload.get("fixture_namespace") in {candidate.get("run_id"), candidate.get("candidate_id")}:
        _fail("v3_fixture_namespace_collides_with_candidate")
    venue = payload.get("venue")
    if not isinstance(venue, dict) or venue.get("conversion_policy") != "exact_only_no_round_up_no_truncate":
        _fail("v3_venue_contract_invalid")
    payload["v2_contract"] = v2
    return payload


@dataclass(frozen=True)
class ContractConversion:
    btc_quantity_text: str
    contract_value_btc_text: str
    contracts_text: str
    lot_size_contracts_text: str
    minimum_size_contracts_text: str
    maximum_absolute_contracts_text: str
    exact: bool = True


@dataclass(frozen=True)
class CandidateStepDecision:
    policy: Any
    conversion: ContractConversion | None
    execution_blockers: tuple[str, ...]


@dataclass(frozen=True)
class _RecoveredCandidatePolicy:
    target: TargetPosition
    approved: bool
    reasons: tuple[str, ...]
    exit_reasons: tuple[str, ...]
    exit_state: CandidateExitState


def evaluate_candidate_step(
    facts: CandidatePolicyFacts,
    *,
    venue: Mapping[str, Any],
) -> CandidateStepDecision:
    """One shared forecast -> policy -> exact venue-conversion step."""

    policy = evaluate_candidate_policy(facts)
    try:
        conversion = btc_quantity_to_okx_contracts(
            btc_quantity=policy.target.target_quantity or 0.0,
            contract_value_btc=venue["contract_value_btc"],
            lot_size_contracts=venue["lot_size_contracts"],
            min_size_contracts=venue["minimum_size_contracts"],
            max_abs_contracts=venue["maximum_absolute_contracts"],
        )
    except (KeyError, QlibOfflineReplayError) as exc:
        return CandidateStepDecision(
            policy=policy,
            conversion=None,
            execution_blockers=(str(exc),),
        )
    return CandidateStepDecision(policy=policy, conversion=conversion, execution_blockers=())


def _finite_decimal(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise QlibOfflineReplayError(f"{field}_invalid") from exc
    if not result.is_finite():
        _fail(f"{field}_invalid")
    return result


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"", "-0"} else normalized


def btc_quantity_to_okx_contracts(
    *,
    btc_quantity: Any,
    contract_value_btc: Any,
    lot_size_contracts: Any,
    min_size_contracts: Any,
    max_abs_contracts: Any,
) -> ContractConversion:
    btc = _finite_decimal(btc_quantity, field="btc_quantity")
    ct_value = _finite_decimal(contract_value_btc, field="contract_value_btc")
    lot = _finite_decimal(lot_size_contracts, field="lot_size_contracts")
    minimum = _finite_decimal(min_size_contracts, field="min_size_contracts")
    cap = _finite_decimal(max_abs_contracts, field="max_abs_contracts")
    if ct_value <= 0 or lot <= 0 or minimum <= 0 or cap <= 0:
        _fail("venue_quantity_filter_nonpositive")
    contracts = btc / ct_value
    if contracts != 0 and abs(contracts) < minimum:
        _fail("target_contracts_below_minimum")
    if abs(contracts) > cap:
        _fail("target_contracts_cap_breached")
    if contracts % lot != 0:
        _fail("target_contracts_not_exact_lot")
    if contracts * ct_value != btc:
        _fail("target_contract_conversion_inexact")
    return ContractConversion(
        btc_quantity_text=_decimal_text(btc),
        contract_value_btc_text=_decimal_text(ct_value),
        contracts_text=_decimal_text(contracts),
        lot_size_contracts_text=_decimal_text(lot),
        minimum_size_contracts_text=_decimal_text(minimum),
        maximum_absolute_contracts_text=_decimal_text(cap),
    )


def _verified_archive_member(
    archive_root: Path,
    archive_manifest: Mapping[str, Any],
    relative_path: str,
    *,
    expected_sha256: str | None = None,
) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        _fail("archive_member_path_invalid")
    path = (archive_root / relative).resolve()
    try:
        path.relative_to(archive_root.resolve())
    except ValueError as exc:
        raise QlibOfflineReplayError("archive_member_path_escape") from exc
    entries = {
        str(row.get("path")): row
        for row in archive_manifest.get("files", [])
        if isinstance(row, Mapping)
    }
    entry = entries.get(relative.as_posix())
    if not entry or not path.is_file():
        _fail("archive_member_missing:" + relative.as_posix())
    observed = _sha256(path)
    if observed != str(entry.get("sha256") or ""):
        _fail("archive_member_sha256_mismatch:" + relative.as_posix())
    if expected_sha256 is not None and observed != str(expected_sha256):
        _fail("dataset_member_sha256_mismatch:" + relative.as_posix())
    return path


def _archive_input_paths(
    *,
    archive_root: Path,
    archive_manifest: Mapping[str, Any],
    run_id: str,
) -> tuple[Path, Mapping[str, Any], dict[str, Path]]:
    prefix = f"qlib_runs/{run_id}/qlib_input"
    manifest_path = _verified_archive_member(
        archive_root,
        archive_manifest,
        f"{prefix}/dataset_manifest.json",
    )
    try:
        input_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QlibOfflineReplayError("archive_dataset_manifest_unreadable") from exc
    hashes = input_manifest.get("file_hashes")
    if not isinstance(hashes, Mapping):
        _fail("archive_dataset_file_hashes_missing")
    names = {
        "daily_bars_parquet": "daily_bars.parquet",
        "mark": "mark.parquet",
        "premium": "premium.parquet",
        "funding": "funding.parquet",
    }
    paths = {
        key: _verified_archive_member(
            archive_root,
            archive_manifest,
            f"{prefix}/{filename}",
            expected_sha256=str(hashes.get(key) or ""),
        )
        for key, filename in names.items()
    }
    return manifest_path, input_manifest, paths


def _append_policy_evidence(
    state_dir: Path,
    rows: list[dict[str, Any]],
) -> Path:
    state_dir = state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "candidate_policy_evidence.jsonl"
    existing: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    existing[str(row["decision_id"])] = row
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            raise QlibOfflineReplayError("candidate_policy_evidence_corrupt") from exc
    additions: list[dict[str, Any]] = []
    for row in rows:
        decision_id = str(row["decision_id"])
        prior = existing.get(decision_id)
        if prior is not None:
            if prior != row:
                _fail("candidate_policy_evidence_identity_conflict:" + decision_id)
            continue
        additions.append(row)
        existing[decision_id] = row
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as target:
            for row in additions:
                target.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            target.flush()
    return path


def evaluate_frozen_candidate(
    contract: Mapping[str, Any],
    *,
    repo_root: str | Path,
    state_dir: str | Path,
    shared_root: str | Path | None = None,
) -> dict[str, Any]:
    """Own the replay lease across every success and failure exit."""

    owned: list[QlibFixtureOfflineReplay] = []
    try:
        return _evaluate_frozen_candidate_impl(
            contract, repo_root=repo_root, state_dir=state_dir,
            shared_root=shared_root, owned=owned,
        )
    finally:
        # Abnormal exits must release only this instance's lease.  Do not run
        # the normal close projection, which could mask the original failure.
        for replay in owned:
            replay.abort()


def _evaluate_frozen_candidate_impl(
    contract: Mapping[str, Any],
    *,
    repo_root: str | Path,
    state_dir: str | Path,
    shared_root: str | Path | None = None,
    owned: list[QlibFixtureOfflineReplay],
) -> dict[str, Any]:
    """Replay and persist every sealed forecast through the shared policy step."""

    root = Path(repo_root).resolve()
    evidence_root = Path(state_dir).resolve()
    if evidence_root == root or root in evidence_root.parents:
        _fail("candidate_policy_state_must_remain_outside_git")
    v2 = contract.get("v2_contract")
    if not isinstance(v2, Mapping):
        _fail("v3_contract_not_loaded")
    frozen = run_frozen_inference(
        v2,
        repo_root=root,
        shared_root=(None if shared_root is None else Path(shared_root).resolve()),
    )
    manifest = load_manifest_from_git(root, str(v2["archive_manifest_git_spec"]))
    archive = resolve_manifest_payload(
        manifest,
        shared_root=(Path(shared_root).resolve() if shared_root is not None else default_shared_data_root(root)),
        verify_files=True,
    )
    trace_path = _verified_archive_member(
        archive, manifest, f"qlib_runs/{v2['run_id']}/research_trace.json",
        expected_sha256=str(v2["artifact_sha256"]["research_trace.json"]),
    )
    decisions_path = _verified_archive_member(
        archive, manifest, f"qlib_runs/{v2['run_id']}/research_decisions.jsonl",
        expected_sha256=str(v2["artifact_sha256"]["research_decisions.jsonl"]),
    )
    workflow_path = _verified_archive_member(
        archive, manifest, f"qlib_runs/{v2['run_id']}/qlib_workflow_config.yaml",
        expected_sha256=str(v2["artifact_sha256"]["qlib_workflow_config.yaml"]),
    )
    _verified_archive_member(
        archive, manifest, f"qlib_runs/{v2['run_id']}/signal_evaluation.json",
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    workflow = load_yaml_file(workflow_path)
    simulation = workflow["research_simulation"]
    dataset_manifest_path, input_manifest, archive_inputs = _archive_input_paths(
        archive_root=archive,
        archive_manifest=manifest,
        run_id=str(v2["run_id"]),
    )
    bars = pd.read_parquet(archive_inputs["daily_bars_parquet"]).set_index("event_time")
    marks = pd.read_parquet(archive_inputs["mark"]).set_index("event_time")
    premiums = pd.read_parquet(archive_inputs["premium"]).set_index("event_time")
    funding = pd.read_parquet(archive_inputs["funding"]).set_index("event_time")
    decision_rows = [
        json.loads(line)
        for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(decision_rows) != len(frozen.rows) or len(decision_rows) != int(v2["decision_count"]):
        _fail("v3_candidate_decision_count_mismatch")
    calibration = trace.get("calibration", {})
    quality = calibration.get("quality", {})
    versions = CandidatePolicyVersions(
        policy_version=POLICY_VERSION,
        position_policy_sha256=frozen.policy_digests["position"],
        exit_policy_sha256=frozen.policy_digests["exit"],
        cost_policy_sha256=frozen.policy_digests["cost"],
    )
    mismatches: list[str] = []
    approvals = 0
    policy_rows: list[dict[str, Any]] = []
    # This is a new, isolated simulated account.  The historical decision file
    # below is an oracle only; it never provides position, cash, approval or
    # exit state to this replay.
    initial_equity = float(simulation["initial_equity"])
    first_event = pd.Timestamp(frozen.rows.iloc[0].event_time).to_pydatetime()
    replay_config = QlibFixtureReplayConfig(
        repo_root=root,
        state_dir=evidence_root / "candidate_runtime",
        run_id=str(v2["run_id"]),
        decision_time_utc=first_event + timedelta(hours=1),
        strategy_id=str(v2["strategy_id"]),
        strategy_version=str(v2["strategy_version"]),
        candidate_id=str(v2["candidate_id"]),
        model_sha256=str(v2["artifact_sha256"]["model.txt"]),
        data_version=str(v2["data_version"]),
        policy_sha256=_canonical_digest(frozen.policy_digests),
        truth_kind="sealed_candidate_research_only",
        verified_package_sha256=str(v2["archive_aggregate_sha256"]),
        initial_equity_usdt=initial_equity,
    )
    replay = QlibFixtureOfflineReplay(replay_config)
    owned.append(replay)
    replay._verified_sealed_source = True
    if not math.isclose(float(replay.venue.state["equity"]), initial_equity, abs_tol=1e-8):
        _fail("qlib_sealed_initial_account_mismatch")
    spread_bps = float(simulation["spread_bps"])
    impact_bps = float(simulation["impact_bps"])
    friction = (
        float(simulation["slippage_bps"]) + spread_bps / 2.0 + impact_bps
    ) / 10_000.0
    symbol = str(v2["venue_instrument"])
    for index, (prediction, historical) in enumerate(zip(frozen.rows.itertuples(index=False), decision_rows, strict=True)):
        account_equity = float(replay.venue.state["equity"])
        current_quantity = float(Decimal(str(replay.venue.state["position"])) * Decimal("0.01"))
        exit_state = replay._sealed_exit_state
        alpha = historical["layers"]["alpha"]
        allocation = historical["layers"]["allocation"]
        event_time = pd.Timestamp(prediction.event_time)
        decision_time = (event_time + pd.Timedelta(hours=1)).to_pydatetime()
        decision_id = _legacy_research_digest(
            [str(v2["run_id"]), symbol, decision_time.isoformat()]
        )
        if str(historical["decision_id"]) != decision_id:
            _fail(f"v3_candidate_oracle_decision_identity_mismatch:{index}")
        expected_bps = float(prediction.calibrated_prediction) * 10_000.0
        forecast = BTCForecast(
            timestamp_utc=decision_time,
            strategy_id=str(v2["strategy_id"]),
            symbol=symbol,
            direction=(SignalDirection.LONG if expected_bps > 0 else SignalDirection.SHORT),
            score=min(1.0, abs(float(prediction.calibrated_prediction)) / 0.01),
            horizon="12h",
            unit="bps",
            expected_return_bps=expected_bps,
            confidence=max(0.0, min(1.0, float(quality["direction_hit_rate"]))),
            expiry_utc=decision_time + timedelta(hours=12),
            source_signal_id=decision_id + ":signal",
            forecast_id=decision_id + ":forecast",
            quality=BTCForecastQuality(
                ic=float(quality["time_series_ic"]),
                hit_rate=float(quality["direction_hit_rate"]),
                sample_size=int(quality["sample_size"]),
                evidence_path=str(alpha["quality_evidence_path"]),
                evidence_hash=str(alpha["quality_evidence_sha256"]),
            ),
            metadata={"qlib_run_id": v2["run_id"], "research_only": True},
        )
        bar = bars.loc[event_time]
        mark = float(marks.loc[event_time, "close"])
        funding_known = funding[funding.available_time <= pd.Timestamp(decision_time)]
        known_rate = (
            None
            if funding_known.empty
            else float(funding_known.iloc[-1].fundingRate)
        )
        constitution = RiskConstitution(
            max_abs_position=initial_equity / mark,
            max_quantity=initial_equity / mark,
            max_notional=initial_equity * float(v2["policy_bindings"]["position"]["max_weight"]),
            max_leverage=1.0,
            min_liquidation_buffer_bps=1000.0,
            max_daily_loss=initial_equity * 0.03,
            max_drawdown=0.12,
            max_combined_loss=initial_equity * 0.12,
            protection_required=True,
        )
        blockers = (() if bool(calibration.get("quality_passed")) else ("validation_calibration_quality_failed",))
        facts = CandidatePolicyFacts(
            decision_id=decision_id,
            forecast=forecast,
            expected_source_signal_id=decision_id + ":signal",
            risk_budget=BTCRiskBudget(
                max_btc_exposure=float(v2["policy_bindings"]["position"]["max_weight"]),
                strategy_risk_budget=float(v2["policy_bindings"]["position"]["max_weight"]),
                target_volatility=float(v2["policy_bindings"]["position"]["volatility_target_annual_configured"]),
                current_weight=current_quantity * mark / account_equity,
                min_cash_fraction=0.75,
                max_turnover=0.25,
                max_daily_loss_pct=0.03,
                max_drawdown_pct=0.12,
                max_abs_funding_rate=1.0,
                require_funding_rate=True,
            ),
            risk_state=BTCRiskState(
                cash_fraction=1.0 - abs(current_quantity * mark / account_equity),
                daily_loss_pct=0.0,
                current_drawdown_pct=0.0,
                funding_rate=known_rate,
                data_anomaly=bool(blockers),
            ),
            account_equity=account_equity,
            mark_price=mark,
            current_quantity=current_quantity,
            reference_prices=lambda proposed, *, _bar=bar, _mark=mark, _event=event_time: BTCReferencePriceState(
                observed_at_utc=decision_time,
                signal_price=float(_bar.close),
                execution_price=float(_bar.close)
                * (
                    1.0
                    + math.copysign(
                        friction,
                        float(proposed.target_quantity or 0.0) - current_quantity,
                    )
                ),
                mark_price=_mark,
                index_price=float(premiums.loc[_event, "index_close"]),
                current_mark_price=_mark,
                primary_mid=float(_bar.close),
                spread_bps=spread_bps,
                data_age_ms=0,
                source="okx_historical_mark_index_plus_research_cost_assumption",
            ),
            constitution=constitution,
            combined_loss=CombinedLossAssessment(
                net_pnl=0.0,
                loss_amount=0.0,
                loss_ratio=0.0,
                blockers=(),
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                funding_cashflow=0.0,
                fees=0.0,
                slippage=0.0,
                impact=0.0,
            ),
            protection_before=None,
            protection_after=lambda quantity, price=mark: None if abs(quantity) < 1e-12 else {
                "present": True,
                "quantity": abs(quantity),
                "side": "sell" if quantity > 0 else "buy",
                "trigger_price": price * (0.96 if quantity > 0 else 1.04),
            },
            cost_estimate=BTCExecutionCostEstimate(
                fee_bps=2.0 * float(simulation["fee_bps"]),
                spread_bps=spread_bps,
                slippage_bps=2.0 * float(simulation["slippage_bps"]),
                funding_bps=None if known_rate is None else abs(known_rate) * 20_000.0,
                impact_bps=2.0 * impact_bps,
                source="frozen_research_cost_assumption",
            ),
            min_quantity=0.00001,
            blockers=blockers,
            exit_state=exit_state,
            exit_observation=CandidateExitObservation(
                close_price=float(bar.close),
                calibrated_prediction=float(prediction.calibrated_prediction),
                has_score=True,
                end_of_window=index == len(decision_rows) - 1,
            ),
            exit_policy=CandidateExitPolicy(
                hard_stop_fraction=float(v2["policy_bindings"]["exit"]["hard_stop_fraction"]),
                trailing_stop_fraction=float(v2["policy_bindings"]["exit"]["trailing_stop_fraction"]),
                maximum_holding_bars=int(v2["policy_bindings"]["exit"]["maximum_holding_bars"]),
            ),
            versions=versions,
        )
        step = evaluate_candidate_step(facts, venue=contract["venue"])
        policy = step.policy
        approvals += int(policy.approved)
        next_time = event_time + pd.Timedelta(hours=1)
        delayed_open = (
            float(bars.loc[next_time, "open"])
            if next_time in bars.index else None
        )
        observation = CandidateMarketObservation(
            event_time_utc=event_time.to_pydatetime(),
            close_price=float(bar.close),
            mark_price=mark,
            index_price=float(premiums.loc[event_time, "index_close"]),
            delayed_open_price=delayed_open,
            funding_rate=0.0 if known_rate is None else known_rate,
            blockers=blockers,
            end_of_window=index == len(decision_rows) - 1,
        )
        replay._sealed_expected_inputs[forecast.forecast_id] = replay._verified_input_digest(
            forecast=forecast, facts=facts, observation=observation,
        )
        runtime_result = replay.execute(
            forecast=forecast, observation=observation,
            phase=f"sealed_{index:04d}", verified_facts=facts,
        )
        if runtime_result["candidate_target_position_id"] != policy.target.target_position_id:
            _fail(f"v3_candidate_common_entry_policy_mismatch:{index}")
        if not math.isclose(float(policy.target.target_quantity or 0.0), float(allocation["target_quantity"]), abs_tol=1e-12):
            mismatches.append(f"target_quantity:{index}")
        if not math.isclose(float(policy.target.target_weight), float(allocation["target_weight"]), abs_tol=1e-12):
            mismatches.append(f"target_weight:{index}")
        if policy.approved or allocation["status"] != "blocked":
            mismatches.append(f"approval:{index}")
        evidence = {
            "schema_version": "strategy_v3_candidate_policy_decision_v2",
            "decision_id": historical["decision_id"],
            "event_time": event_time.isoformat(),
            "decision_time": decision_time.isoformat(),
            "forecast_id": forecast.forecast_id,
            "forecast_sha256": _canonical_digest({
                **forecast.__dict__,
                "timestamp_utc": forecast.timestamp_utc.isoformat(),
                "expiry_utc": forecast.expiry_utc.isoformat(),
            }),
            "target_position_id": policy.target.target_position_id,
            "target_quantity_btc": policy.target.target_quantity,
            "target_weight": policy.target.target_weight,
            "approved": policy.approved,
            "reasons": list(policy.reasons),
            "exit_reasons": list(policy.exit_reasons),
            "conversion": None if step.conversion is None else step.conversion.__dict__,
            "execution_blockers": list(step.execution_blockers),
            "outcome": "no_trade_rejected" if not policy.approved else "execution_admission_unexpected",
            "package_sha256": str(v2["archive_aggregate_sha256"]),
            "dataset_manifest_sha256": _sha256(dataset_manifest_path),
            "policy_versions": versions.to_dict(),
            "permissions": dict(contract["permissions"]),
        }
        policy_rows.append(evidence)
    if mismatches:
        _fail("v3_candidate_policy_parity_failed:" + ",".join(mismatches[:10]))
    expected = contract["candidate"]
    if trace.get("simulated_fill_count") != expected["expected_simulated_fill_count"]:
        _fail("v3_candidate_historical_fill_count_mismatch")
    if not set(expected["expected_blockers"]).issubset(set(trace.get("blockers", []))):
        _fail("v3_candidate_expected_blockers_missing")
    replay.flush_sealed_rejections()
    for index, row in enumerate(policy_rows):
        source_key = f"{row['forecast_id']}:sealed_{index:04d}"
        committed = replay._sealed_committed.get(source_key)
        if committed is None:
            _fail(f"v3_candidate_runtime_decision_link_missing:{index}")
        row["runtime_decision_event_id"] = committed["event_id"]
        row["runtime_decision_hash"] = committed["decision_hash"]
        row["runtime_batch_event_sequence"] = committed["batch_event_sequence"]
        row["runtime_batch_event_hash"] = committed["batch_event_hash"]
        row["runtime_batch_index"] = committed["batch_index"]
    runtime_events = replay.controller._runtime_store.recover().events
    runtime_policy_count = sum(
        len(event.get("payload", {}).get("decisions", []))
        for event in runtime_events
        if event.get("event_type") == "qlib_offline_rejected_batch"
    )
    if runtime_policy_count != len(policy_rows):
        _fail("v3_candidate_runtime_event_count_mismatch")
    replay.close()
    evidence_path = _append_policy_evidence(evidence_root, policy_rows)
    return {
        "schema_version": "strategy_v3_frozen_candidate_policy_evidence_v1",
        "usage": "offline_acceptance_only",
        "run_id": v2["run_id"],
        "candidate_id": v2["candidate_id"],
        "decision_count": len(policy_rows),
        "approved_decision_count": approvals,
        "simulated_fill_count": 0,
        "historical_research_trace_sha256": v2["artifact_sha256"]["research_trace.json"],
        "historical_research_decisions_sha256": v2["artifact_sha256"]["research_decisions.jsonl"],
        "frozen_prediction_digest": _canonical_digest([
            [row.event_time.isoformat(), row.raw_score, row.calibrated_prediction]
            for row in frozen.rows.itertuples(index=False)
        ]),
        "policy_decision_digest": _canonical_digest(policy_rows),
        "policy_evidence_path": str(evidence_path),
        "policy_evidence_sha256": _sha256(evidence_path),
        "runtime_state_dir": str(replay_config.state_dir),
        "runtime_policy_event_count": runtime_policy_count,
        "runtime_physical_batch_event_count": sum(
            event.get("event_type") == "qlib_offline_rejected_batch"
            for event in runtime_events
        ),
        "archive_input_paths": {
            key: str(path.relative_to(archive)) for key, path in archive_inputs.items()
        },
        "policy_versions": versions.to_dict(),
        "blockers": list(trace.get("blockers", [])),
        "candidate_effectiveness": "not_proven_negative_ic_zero_fill_preserved",
        "execution_permission": False,
        "runtime_observed": False,
        "permissions": dict(contract["permissions"]),
    }


@dataclass(frozen=True)
class QlibFixtureReplayConfig:
    repo_root: Path
    state_dir: Path
    run_id: str
    decision_time_utc: datetime
    strategy_id: str
    strategy_version: str
    candidate_id: str
    model_sha256: str
    data_version: str
    policy_sha256: str
    truth_kind: str = "explicit_fixture_not_candidate_effectiveness"
    verified_package_sha256: str = ""
    initial_equity_usdt: float = 5000.0

    def __post_init__(self) -> None:
        timestamp = self.decision_time_utc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("qlib_fixture_decision_time_must_be_utc")
        object.__setattr__(self, "decision_time_utc", timestamp.astimezone(timezone.utc))
        object.__setattr__(self, "repo_root", Path(self.repo_root).resolve())
        object.__setattr__(self, "state_dir", Path(self.state_dir).resolve())
        if self.repo_root == self.state_dir or self.repo_root in self.state_dir.parents:
            raise ValueError("qlib_fixture_state_must_remain_outside_git")
        for name in ("model_sha256", "policy_sha256"):
            if _SHA256.fullmatch(str(getattr(self, name))) is None:
                raise ValueError(f"qlib_fixture_{name}_invalid")
        if self.truth_kind not in {
            "explicit_fixture_not_candidate_effectiveness",
            "sealed_candidate_research_only",
            "registered_candidate_offline_only",
        }:
            raise ValueError("qlib_offline_truth_kind_invalid")
        if self.truth_kind in {"sealed_candidate_research_only", "registered_candidate_offline_only"} and _SHA256.fullmatch(self.verified_package_sha256) is None:
            raise ValueError("qlib_sealed_package_digest_required")
        if not math.isfinite(self.initial_equity_usdt) or self.initial_equity_usdt <= 0:
            raise ValueError("qlib_offline_initial_equity_invalid")


@dataclass(frozen=True)
class OfflineMaintenanceFact:
    observed_at_utc: datetime
    mark_price: float
    index_price: float

    def __post_init__(self) -> None:
        when = self.observed_at_utc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("offline_maintenance_time_must_be_utc")
        object.__setattr__(self, "observed_at_utc", when.astimezone(timezone.utc))
        if not all(math.isfinite(float(value)) and float(value) > 0 for value in (self.mark_price, self.index_price)):
            raise ValueError("offline_maintenance_price_invalid")


@dataclass(frozen=True)
class FundingSettlementFact:
    event_id: str
    event_time_utc: datetime
    rate: float
    source_record_id: str
    source_dataset: str
    source_version: str
    source_sha256: str
    valuation_policy: str = "minute_close_sampled_valuation_not_exchange_actual_settlement"

    def __post_init__(self) -> None:
        when = self.event_time_utc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("funding_settlement_time_must_be_utc")
        object.__setattr__(self, "event_time_utc", when.astimezone(timezone.utc))
        if (not self.event_id or not self.source_record_id or not self.source_dataset or not self.source_version
            or _SHA256.fullmatch(self.source_sha256) is None or not math.isfinite(float(self.rate))
            or self.valuation_policy != "minute_close_sampled_valuation_not_exchange_actual_settlement"):
            raise ValueError("funding_settlement_fact_invalid")


@dataclass(frozen=True)
class CandidateMarketObservation:
    event_time_utc: datetime
    close_price: float
    mark_price: float
    index_price: float
    delayed_open_price: float | None
    funding_rate: float
    funding_cashflow_usdt: float = 0.0
    blockers: tuple[str, ...] = ()
    end_of_window: bool = False
    maintenance_facts: tuple[OfflineMaintenanceFact, ...] = ()
    funding_settlements: tuple[FundingSettlementFact, ...] = ()

    def __post_init__(self) -> None:
        when = self.event_time_utc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("candidate_observation_time_must_be_utc")
        object.__setattr__(self, "event_time_utc", when.astimezone(timezone.utc))
        for name in ("close_price", "mark_price", "index_price", "delayed_open_price", "funding_rate", "funding_cashflow_usdt"):
            raw = getattr(self, name)
            if name == "delayed_open_price" and raw is None:
                continue
            value = float(raw)
            if not math.isfinite(value) or (name.endswith("price") and value <= 0):
                raise ValueError("candidate_observation_invalid:" + name)
        times = [fact.observed_at_utc for fact in self.maintenance_facts]
        if times != sorted(set(times)):
            raise ValueError("offline_maintenance_facts_not_ordered")
        settlement_times = [fact.event_time_utc for fact in self.funding_settlements]
        if settlement_times != sorted(set(settlement_times)) or any(value != when + timedelta(hours=1) for value in settlement_times):
            raise ValueError("funding_settlement_facts_not_ordered_or_not_decision_time")


class _QlibOfflineVenue(_OfflineVenue):
    """The V1 file-backed fake venue with explicit price/funding receipts."""

    def __init__(self, path: Path, *, now: datetime, initial_equity_usdt: float = 5000.0) -> None:
        new_account = not path.exists()
        super().__init__(path, now=now)
        if new_account:
            self.state["wallet_balance"] = str(initial_equity_usdt)
            self.state["equity"] = str(initial_equity_usdt)
        self.state.setdefault("wallet_balance", self.state.get("equity", "5000"))
        self.state.setdefault("average_price", "0")
        self.state.setdefault("bills", [])
        self.state.setdefault("funding_settlements", [])
        for field in ("last_observed_at_utc", "offline_clock_utc"):
            prior_time = self.state.get(field)
            if isinstance(prior_time, str) and prior_time:
                self.now = max(self.now, datetime.fromisoformat(prior_time))
        self.market_price = Decimal(str(self.state.get("market_price", "60000")))
        self.index_price = Decimal(str(self.state.get("index_price", "60000")))
        self.next_fill_price = Decimal(str(self.state.get("next_fill_price", "60000")))
        self._refresh_equity()

    def set_market(self, *, now: datetime, mark_price: Any, fill_price: Any, index_price: Any | None = None) -> None:
        self.now = now
        self.market_price = _finite_decimal(mark_price, field="fixture_mark_price")
        self.index_price = _finite_decimal(mark_price if index_price is None else index_price, field="fixture_index_price")
        self.next_fill_price = _finite_decimal(fill_price, field="fixture_fill_price")
        self._refresh_equity()

    def _refresh_equity(self, *, persist: bool = True) -> None:
        position = Decimal(str(self.state.get("position", "0")))
        average = Decimal(str(self.state.get("average_price", "0")))
        wallet = Decimal(str(self.state.get("wallet_balance", "5000")))
        unrealized = position * Decimal("0.01") * (self.market_price - average) if position else Decimal("0")
        self.state["equity"] = _decimal_text(wallet + unrealized)
        self.state["last_observed_at_utc"] = self.now.isoformat()
        self.state["market_price"] = _decimal_text(self.market_price)
        self.state["index_price"] = _decimal_text(self.index_price)
        self.state["next_fill_price"] = _decimal_text(self.next_fill_price)
        if persist:
            self._persist()

    def _apply_economic_fill(
        self,
        *,
        client_id: str,
        order_id: str,
        side: str,
        position_side: str,
        size: Decimal,
        price: Decimal,
        fill_id: str,
        execution_type: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        before = Decimal(str(self.state["position"]))
        delta = size if (position_side, side) == ("long", "buy") else -size if (position_side, side) == ("short", "sell") else -size if position_side == "long" else size
        average = Decimal(str(self.state.get("average_price", "0")))
        closed = min(abs(before), abs(delta)) if before * delta < 0 else Decimal("0")
        realized = closed * Decimal("0.01") * (price - average) * (Decimal("1") if before > 0 else Decimal("-1"))
        after = before + delta
        if after == 0:
            new_average = Decimal("0")
        elif before == 0:
            new_average = price
        elif before * delta > 0:
            new_average = (abs(before) * average + abs(delta) * price) / abs(after)
        else:
            new_average = average
        fee = -(size * Decimal("0.01") * price * Decimal("0.0005"))
        self.state["wallet_balance"] = _decimal_text(Decimal(str(self.state["wallet_balance"])) + realized + fee)
        self.state["position"] = _decimal_text(after)
        self.state["average_price"] = _decimal_text(new_average)
        fill = {
            "tradeId": fill_id,
            "ordId": order_id,
            "clOrdId": client_id,
            "instId": "BTC-USDT-SWAP",
            "side": side,
            "posSide": position_side,
            "fillPx": _decimal_text(price),
            "fillSz": _decimal_text(size),
            "fee": _decimal_text(fee),
            "feeCcy": "USDT",
            "pnl": _decimal_text(realized),
            "ts": str(int(self.now.timestamp() * 1000)),
            **dict(evidence or {}),
        }
        if execution_type is not None:
            fill["execType"] = execution_type
        self.state["fills"].append(fill)
        self._refresh_equity(persist=False)
        return fill

    def apply_funding(self, *, amount_usdt: Any, timestamp_utc: datetime) -> None:
        amount = _finite_decimal(amount_usdt, field="fixture_funding_cashflow")
        if amount == 0:
            return
        bill_id = str(int(timestamp_utc.timestamp() * 1000))
        if any(str(row.get("billId")) == bill_id for row in self.state["bills"]):
            return
        self.state["wallet_balance"] = _decimal_text(
            Decimal(str(self.state["wallet_balance"])) + amount
        )
        self.state["bills"].append({
            "billId": bill_id,
            "instId": "BTC-USDT-SWAP",
            "type": "8",
            "subType": "173",
            "ts": bill_id,
            "balChg": _decimal_text(amount),
            "ccy": "USDT",
            "pnl": _decimal_text(amount),
        })
        self.state["bills"].sort(key=lambda row: int(row["ts"]), reverse=True)
        self._refresh_equity()

    def apply_verified_funding_event(self, *, fact: FundingSettlementFact, mark_price: Any,
        contract_value_btc: Any) -> dict[str, Any]:
        existing = [row for row in self.state["funding_settlements"] if row.get("event_id") == fact.event_id]
        if existing:
            return dict(existing[0])
        position = _finite_decimal(self.state.get("position", "0"), field="reconciled_contract_position")
        mark = _finite_decimal(mark_price, field="funding_valuation_mark")
        contract_value = _finite_decimal(contract_value_btc, field="verified_contract_value_btc")
        rate = _finite_decimal(fact.rate, field="funding_rate")
        amount = -(position * contract_value * mark * rate)
        row = {"event_id": fact.event_id, "event_time_utc": fact.event_time_utc.isoformat(),
            "rate": _decimal_text(rate), "source_record_id": fact.source_record_id,
            "source_dataset": fact.source_dataset, "source_version": fact.source_version,
            "source_sha256": fact.source_sha256, "valuation_policy": fact.valuation_policy,
            "valuation_mark_price": _decimal_text(mark), "position_contracts": _decimal_text(position),
            "contract_value_btc": _decimal_text(contract_value), "calculated_cashflow_usdt": _decimal_text(amount),
            "cash_ledger_effect": "none_zero_position" if amount == 0 else "existing_funding_bill"}
        # Persist the verified zero-position event even though the original
        # ledger correctly has no zero cash bill. Nonzero amounts reuse the
        # existing funding bill and reconciliation path.
        self.state["funding_settlements"].append(row)
        self.state["funding_settlements"].sort(key=lambda value: value["event_time_utc"])
        if amount != 0:
            self.apply_funding(amount_usdt=amount, timestamp_utc=fact.event_time_utc)
        else:
            self._persist()
        return dict(row)

    def public_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        if path not in {"/api/v5/market/ticker", "/api/v5/public/mark-price", "/api/v5/market/index-tickers", "/api/v5/market/books"}:
            return super().public_get(path, params)
        timestamp = str(int(self.now.timestamp() * 1000))
        mark = _decimal_text(self.market_price)
        rows = {
            "/api/v5/market/ticker": [{"bidPx": mark, "askPx": _decimal_text(self.market_price + Decimal("0.1")), "ts": timestamp}],
            "/api/v5/public/mark-price": [{"markPx": mark, "ts": timestamp}],
            "/api/v5/market/index-tickers": [{"idxPx": _decimal_text(self.index_price), "ts": timestamp}],
            "/api/v5/market/books": [{"bids": [[mark, "1"]], "asks": [[_decimal_text(self.market_price + Decimal("0.1")), "1"]], "ts": timestamp}],
        }
        return OkxDemoResponse("GET", path, 200, "0", "", tuple(rows[path]))

    def _position_rows(self) -> list[dict[str, str]]:
        position = Decimal(str(self.state["position"]))
        average = Decimal(str(self.state.get("average_price", "0")))
        upl = position * Decimal("0.01") * (self.market_price - average) if position else Decimal("0")
        return [{
            "instId": "BTC-USDT-SWAP",
            "posSide": "long" if position >= 0 else "short",
            "mgnMode": "isolated",
            "pos": _decimal_text(abs(position)),
            "avgPx": _decimal_text(average if position else self.market_price),
            "markPx": _decimal_text(self.market_price),
            "upl": _decimal_text(upl),
            "realizedPnl": "0",
            "liqPx": "" if position == 0 else (_decimal_text(self.market_price / 2) if position > 0 else _decimal_text(self.market_price * Decimal("1.5"))),
            "lever": "1",
            "uTime": str(int(self.now.timestamp() * 1000)),
        }]

    def private_get(self, path: str, params: Mapping[str, Any] | None = None) -> OkxDemoResponse:
        if path == "/api/v5/account/bills":
            return OkxDemoResponse("GET", path, 200, "0", "", tuple(self.state["bills"]))
        return super().private_get(path, params)

    def cancel_all_after(self, *, timeout_seconds: int, tag: str) -> OkxDemoResponse:
        """Return a persisted, explicitly simulated transport ACK."""

        if tag != OKX_DEMO_PAPER_ORDER_TAG or timeout_seconds <= 0:
            return OkxDemoResponse("POST", "/api/v5/trade/cancel-all-after", 200, "1", "invalid offline CAA", ())
        now_ms = int(self.now.timestamp() * 1000)
        response = {
            "triggerTime": str(now_ms + timeout_seconds * 1000),
            "ts": str(now_ms),
            "tag": tag,
        }
        self.state.setdefault("offline_maintenance_acks", []).append(response)
        self._persist()
        return OkxDemoResponse("POST", "/api/v5/trade/cancel-all-after", 200, "0", "", (response,))

    def submit_order(self, payload: Mapping[str, Any]) -> OkxDemoResponse:
        order = dict(payload)
        client_id = str(order["clOrdId"])
        existing = next((row for row in self.state["orders"] if row["clOrdId"] == client_id), None)
        if existing is not None:
            return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": existing["ordId"], "clOrdId": client_id, "sCode": "0", "sMsg": ""},))
        self.now += timedelta(milliseconds=1)
        self.state["submit_count"] += 1
        order_id = f"qlib-offline-order-{self.state['submit_count']}"
        size = Decimal(str(order["sz"]))
        price = self.next_fill_price
        fill_id = f"qlib-offline-fill-{self.state['submit_count']}"
        self._apply_economic_fill(
            client_id=client_id,
            order_id=order_id,
            side=str(order["side"]),
            position_side=str(order["posSide"]),
            size=size,
            price=price,
            fill_id=fill_id,
        )
        attached = []
        for raw in order.get("attachAlgoOrds", []):
            algo_id = f"qlib-offline-algo-{self.state['submit_count']}"
            algo = {
                "algoId": algo_id, "algoClOrdId": raw["attachAlgoClOrdId"],
                "parentClOrdId": client_id, "instId": "BTC-USDT-SWAP",
                "side": "sell" if order["posSide"] == "long" else "buy",
                "posSide": order["posSide"], "sz": order["sz"], "state": "live",
                "ordType": "oco", "tpTriggerPx": raw["tpTriggerPx"],
                "tpTriggerPxType": raw["tpTriggerPxType"], "tpOrdPx": raw["tpOrdPx"],
                "slTriggerPx": raw["slTriggerPx"], "slTriggerPxType": raw["slTriggerPxType"],
                "slOrdPx": raw["slOrdPx"], "uTime": str(int(self.now.timestamp() * 1000)),
            }
            self.state["algos"] = [algo]
            attached.append({"attachAlgoId": algo_id, "attachAlgoClOrdId": algo["algoClOrdId"], "failCode": "0", "failReason": ""})
        final = {**order, "ordId": order_id, "state": "filled", "accFillSz": order["sz"], "avgPx": _decimal_text(price), "attachAlgoOrds": attached}
        self.state["orders"].append(final)
        # An execution price is not the exchange mark.  Keep the separately
        # observed mark across the fill and same-clock next decision; otherwise
        # restart creates a different account snapshot at an identical time.
        self._refresh_equity()
        return OkxDemoResponse("POST", "/api/v5/trade/order", 200, "0", "", ({"ordId": order_id, "clOrdId": client_id, "sCode": "0", "sMsg": ""},))

    def execute_registered_protection(
        self,
        *,
        algo_id: str,
        observed_at_utc: datetime,
        observed_mark: Any,
        observed_index: Any,
        trigger_kind: str,
        trigger_threshold: Any,
        trigger_reference: Any,
        adverse_fill_bps: Any,
    ) -> Mapping[str, Any]:
        """Apply one already-hosted OCO from an explicit sampled mark fact.

        The venue owns the exchange-shaped order/fill mutation.  The caller is
        still responsible for collecting the snapshot and committing it through
        the existing runtime ledger.
        """

        matches = [row for row in self.state["algos"] if str(row.get("algoId") or "") == algo_id]
        if len(matches) != 1:
            raise QlibOfflineReplayError("registered_protection_identity_missing_or_ambiguous")
        algo = matches[0]
        if trigger_kind not in {"stop_loss", "take_profit"}:
            raise QlibOfflineReplayError("registered_protection_trigger_kind_invalid")
        side = str(algo.get("side") or "")
        position_side = str(algo.get("posSide") or "")
        size = _finite_decimal(algo.get("sz"), field="registered_protection_size")
        position = Decimal(str(self.state["position"]))
        if (
            algo.get("state") != "live"
            or side not in {"buy", "sell"}
            or position_side not in {"long", "short"}
            or size != abs(position)
            or (position > 0) != (position_side == "long")
            or side != ("sell" if position > 0 else "buy")
        ):
            raise QlibOfflineReplayError("registered_protection_position_binding_invalid")
        parent_client_id = str(algo.get("parentClOrdId") or "")
        parents = [row for row in self.state["orders"] if row.get("clOrdId") == parent_client_id and row.get("state") == "filled"]
        if len(parents) != 1:
            raise QlibOfflineReplayError("registered_protection_parent_order_invalid")
        parent = parents[0]
        parent_fills = [row for row in self.state["fills"] if row.get("ordId") == parent.get("ordId") and row.get("clOrdId") == parent_client_id]
        attached = parent.get("attachAlgoOrds")
        if (
            len(parent_fills) != 1
            or not isinstance(attached, list)
            or len([row for row in attached if row.get("attachAlgoId") == algo_id and row.get("attachAlgoClOrdId") == algo.get("algoClOrdId") and row.get("failCode") == "0"]) != 1
        ):
            raise QlibOfflineReplayError("registered_protection_parent_fill_invalid")
        mark = _finite_decimal(observed_mark, field="registered_protection_observed_mark")
        index = _finite_decimal(observed_index, field="registered_protection_observed_index")
        threshold = _finite_decimal(
            trigger_threshold, field="registered_protection_trigger_threshold"
        )
        reference = _finite_decimal(
            trigger_reference, field="registered_protection_trigger_reference"
        )
        cost_bps = _finite_decimal(adverse_fill_bps, field="registered_protection_adverse_fill_bps")
        if cost_bps < 0 or cost_bps > Decimal("1000"):
            raise QlibOfflineReplayError("registered_protection_adverse_fill_bps_invalid")
        fill_price = mark * (Decimal("1") - cost_bps / Decimal("10000") if side == "sell" else Decimal("1") + cost_bps / Decimal("10000"))
        self.set_market(now=observed_at_utc, mark_price=mark, index_price=index, fill_price=fill_price)
        order_id = "qlib-protection-order-" + algo_id
        client_id = str(algo.get("algoClOrdId") or "")
        fill_id = "qlib-protection-fill-" + algo_id
        price_policy = {
            "version": "registered_offline_sampled_mark_protection_price_v1",
            "observation_source": "verified_registered_maintenance_fact",
            "reference_price": "explicit_sampled_mark_point",
            "adverse_non_fee_bps": _decimal_text(cost_bps),
            "fee_bps_per_side": "5",
            "intrainterval_path_inferred": False,
        }
        evidence = {
            "triggerKind": trigger_kind,
            "protectionAlgoId": algo_id,
            "parentClOrdId": parent_client_id,
            "parentOrdId": str(parent["ordId"]),
            "parentFillId": str(parent_fills[0]["tradeId"]),
            "observedAtUtc": observed_at_utc.isoformat(),
            "observedMarkPx": _decimal_text(mark),
            "observedIndexPx": _decimal_text(index),
            "triggerThresholdPx": _decimal_text(threshold),
            "triggerReferencePx": _decimal_text(reference),
            "observationSource": price_policy["observation_source"],
            "pricePolicy": price_policy["version"],
            "pricePolicySha256": _sha(price_policy),
            "adverseNonFeeBps": _decimal_text(cost_bps),
        }
        fill = self._apply_economic_fill(
            client_id=client_id,
            order_id=order_id,
            side=side,
            position_side=position_side,
            size=size,
            price=fill_price,
            fill_id=fill_id,
            execution_type="registered_offline_sampled_mark_oco_" + trigger_kind,
            evidence=evidence,
        )
        self.state["orders"].append({
            "ordId": order_id,
            "clOrdId": client_id,
            "instId": "BTC-USDT-SWAP",
            "side": side,
            "posSide": position_side,
            "ordType": "market",
            "sz": _decimal_text(size),
            "state": "filled",
            "accFillSz": _decimal_text(size),
            "avgPx": _decimal_text(fill_price),
            **evidence,
        })
        self.state["algo_history"].append({
            **dict(algo),
            "state": "effective",
            "triggerKind": trigger_kind,
            "protectionOrderId": order_id,
            "protectionFillId": fill_id,
            "uTime": str(int(observed_at_utc.timestamp() * 1000)),
            **evidence,
        })
        self.state["algos"] = [row for row in self.state["algos"] if str(row.get("algoId") or "") != algo_id]
        self._refresh_equity()
        return {"algo_id": algo_id, "order_id": order_id, "fill_id": fill_id, "fill": fill, **evidence}


class QlibFixtureOfflineReplay:
    """Explicit nonzero fixture through the existing BTC authority chain.

    This harness is not candidate evidence.  It accepts already-created domain
    objects, performs no inference, and owns no OMS implementation.
    """

    def __init__(self, config: QlibFixtureReplayConfig, *, registered_inputs=None) -> None:
        self.config = config
        self._closed = False
        self._now = config.decision_time_utc - timedelta(seconds=1)
        self.source_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=config.repo_root, text=True
        ).strip()
        self.registered_inputs = registered_inputs
        if config.truth_kind == "registered_candidate_offline_only":
            from .btc_registered_candidate import check_registered_inputs, registered_forecast, registered_offline_run_id, state_directory_digest
            row = check_registered_inputs(registered_inputs)
            p = row["package"]
            from quant_shared.strategy_delivery.models import digest
            if (row["consumer_head"] != self.source_head or registered_offline_run_id(row["id"]) != config.run_id
                or row["content_digest"] != config.verified_package_sha256
                or p["model"]["sha256"] != config.model_sha256
                or p["data_version"] != config.data_version
                or p["source"]["candidate_id"] != config.candidate_id
                or p["strategy_id"] != config.strategy_id or p["strategy_version"] != config.strategy_version
                or config.policy_sha256 != digest({k:p["contracts"][k] for k in ("position","exit","cost")})
                or config.initial_equity_usdt != row["binding"]["offline_runtime"]["initial_equity_usdt"]
                or state_directory_digest(config.state_dir) != row["binding"]["offline_runtime"]["state_directory_sha256"]
                or config.decision_time_utc != registered_forecast(registered_inputs,0).timestamp_utc):
                raise QlibOfflineReplayError("registered_config_identity_mismatch")
        elif registered_inputs is not None:
            raise QlibOfflineReplayError("registered_source_truth_kind_mismatch")
        self.identity = {
            "schema_version": "strategy_v3_offline_identity_v2",
            "truth_kind": config.truth_kind,
            "run_id": config.run_id,
            "strategy_id": config.strategy_id,
            "strategy_version": config.strategy_version,
            "candidate_id": config.candidate_id,
            "model_sha256": config.model_sha256,
            "policy_sha256": config.policy_sha256,
            "data_version": config.data_version,
            "initial_equity_usdt": config.initial_equity_usdt,
            "verified_package_sha256": config.verified_package_sha256,
            "code_version": self.source_head,
            "instrument_id": "BTC-USDT-SWAP",
        }
        if registered_inputs is not None:
            self.identity["registered_inputs_digest"] = registered_inputs.digest
            self.identity["account_binding_digest"] = registered_inputs.row["binding_digest"]
        self.identity["identity_digest"] = _sha(self.identity)
        self._verified_sealed_source = False
        self._sealed_expected_inputs: dict[str, str] = {}
        self._bootstrap_required = not any(
            candidate.exists()
            for candidate in (
                config.state_dir / "offline_venue.json",
                config.state_dir / "runtime",
                config.state_dir / "boundary",
            )
        )
        self._bind_identity()
        self._frame = build_trend_frame("flat", end=config.decision_time_utc)
        self.venue = _QlibOfflineVenue(
            config.state_dir / "offline_venue.json", now=self._now,
            initial_equity_usdt=config.initial_equity_usdt,
        )
        if not self._bootstrap_required:
            # The venue's persisted observation time is the offline clock's
            # lower bound. Never restart from the original first-bar clock.
            self._now = self.venue.now
        latch_path = (config.state_dir / "guardian_latch.json").resolve()
        if self._bootstrap_required:
            _atomic_json(
                latch_path,
                GuardianLatchRecord(
                    generation=1,
                    tripped=False,
                    owner_id="v3-qlib-offline",
                    fence_token="v3-qlib-offline",
                ).to_dict(),
            )
        latch = FileGuardianLatchStore(latch_path)
        self.guardian_supervisor = RuntimeRiskGuardianSupervisor(
            RuntimeRiskGuardian(
                GuardianConfig(
                    max_abs_exposure=10,
                    max_daily_loss=10,
                    max_drawdown=10,
                    max_drawdown_unit="usdt",
                    max_open_orders=1,
                )
            ),
            latch,
            owner_id="v3-qlib-offline",
            fence_token="v3-qlib-offline",
        )
        try:
            self._finish_initialization()
        except BaseException:
            # Only this instance owns the newly acquired lease. Preserve the
            # original construction error and every durable failure blocker.
            self._closed = True
            self._release_authorities(suppress_errors=True)
            raise

    def _finish_initialization(self) -> None:
        config = self.config
        self.composition = BtcDemoProductionComposition(
            source_head=self.source_head,
            max_configured_leverage=Decimal("1"),
            guardian_supervisor_factory=lambda: self.guardian_supervisor,
        )
        dispatcher = BTCDemoExecutionDispatcher(
            expected_source_head=self.source_head,
            state_directory=config.state_dir / "boundary",
            capability_adapter=_OfflineCapabilityAdapter(),
            credential_service="quant-system.okx-demo.offline",
            clock=lambda: self.venue.now,
        )
        runtime_config = OkxDemoPaperRuntimeConfig(
            repo_root=config.repo_root,
            data_db_path=config.state_dir / "never.sqlite",
            output_dir=config.state_dir / "runtime",
            credential_service="quant-system.okx-demo.offline",
            order_poll_interval_seconds=0.001,
            order_poll_attempts=1,
            max_configured_leverage=Decimal("1"),
            risk_profile="baseline_1x",
            runtime_identity="v3-qlib-offline",
            execution_dispatcher=dispatcher,
            authoritative_oms_bundle_provider=self.composition.build_order_submission_bundle,
            offline_completed_frame_provider=lambda: self._frame,
            account_cashflow_evidence_provider=self._cashflow_evidence,
        )
        self.controller = _QlibOfflineRuntimeController(
            config=runtime_config,
            credential_loader=lambda _name: (_ for _ in ()).throw(
                AssertionError("credentials prohibited")
            ),
            client_factory=lambda _cfg, _creds: self.venue,
            private_ws_factory=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("private ws prohibited")
            ),
            clock=lambda: self.venue.now,
            start_worker=False,
            start_capability_checker=lambda: {
                "ready": False,
                "blockers": ["offline_execution_only"],
            },
        )
        self.controller._protection_policy = ServerSideProtectionPolicy.from_mapping(
            OKX_DEMO_APPROVED_PROTECTION_POLICY
        )
        if self.registered_inputs is not None:
            from .btc_registered_candidate import registered_protection_policy
            self.controller._protection_policy = registered_protection_policy(self.registered_inputs.package)
        self.controller._client = self.venue
        recovered = self.controller._runtime_store.recover()
        if recovered.blockers or recovered.truncated_tail:
            raise QlibOfflineReplayError(
                "qlib_offline_runtime_recovery_blocked:" + ",".join(recovered.blockers)
            )
        self._sealed_exit_state = CandidateExitState(0.0, 0.0, None, 0)
        self._sealed_buffer: list[dict[str, Any]] = []
        self._sealed_committed: dict[str, dict[str, Any]] = {}
        self._sealed_last_hash = "0" * 64
        self._sealed_append_failed = False
        if config.truth_kind == "sealed_candidate_research_only":
            for event in recovered.events:
                if event.get("event_type") != "qlib_offline_rejected_batch":
                    continue
                if event.get("payload", {}).get("identity_digest") != self.identity["identity_digest"]:
                    raise QlibOfflineReplayError("qlib_sealed_batch_identity_mismatch")
                for index, row in enumerate(event["payload"].get("decisions", [])):
                    if row.get("previous_decision_hash") != self._sealed_last_hash:
                        raise QlibOfflineReplayError("qlib_sealed_batch_hash_chain_broken")
                    expected_hash = _canonical_digest({key: value for key, value in row.items() if key != "decision_hash"})
                    if row.get("decision_hash") != expected_hash:
                        raise QlibOfflineReplayError("qlib_sealed_batch_decision_hash_invalid")
                    source_key = str(row["source_key"])
                    if source_key in self._sealed_committed:
                        raise QlibOfflineReplayError("qlib_sealed_batch_duplicate_source")
                    self._sealed_committed[source_key] = {
                        **row,
                        "batch_event_sequence": event["sequence"],
                        "batch_event_hash": event["event_hash"],
                        "batch_index": index,
                    }
                    self._sealed_last_hash = row["decision_hash"]
        self._clean_stop_recovery_authorized = self._has_exact_clean_stop(recovered)
        self._clean_stop_projection_digest = (
            self._recovery_authority_digest(self.controller._durable_state_snapshot())
            if self._clean_stop_recovery_authorized
            else ""
        )
        self._activate_initial_state()

        if self.registered_inputs is not None:
            protection_blocks = [e for e in recovered.events if e.get("event_type") == "registered_protection_blocked"]
            if protection_blocks:
                blocker = protection_blocks[-1]["payload"]
                if blocker.get("input_digest") != self.registered_inputs.digest:
                    raise QlibOfflineReplayError("registered_protection_block_identity_mismatch")
                self.controller._state["registered_protection_blocker"] = blocker
                self.controller._state["runtime"].update(active=False, opening_allowed=False, status="registered_protection_blocked")
                self.controller._state["risk_control"].update(mode="FROZEN_UNKNOWN", write_path_trusted=False)
                self._clean_stop_recovery_authorized = False
                self.controller._persist_state()

    def _bind_identity(self) -> None:
        path = self.config.state_dir / "qlib_fixture_replay_identity.json"
        runtime_exists = any(
            candidate.exists()
            for candidate in (
                self.config.state_dir / "offline_venue.json",
                self.config.state_dir / "runtime",
                self.config.state_dir / "boundary",
            )
        )
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != self.identity:
                raise QlibOfflineReplayError("qlib_fixture_replay_identity_mismatch")
            return
        if runtime_exists:
            raise QlibOfflineReplayError("qlib_fixture_replay_identity_binding_missing")
        _atomic_json(path, self.identity)

    def _cashflow_evidence(self, **kwargs: Any) -> Mapping[str, Any]:
        begin = str(int(pd.Timestamp(kwargs["coverage_start_utc"]).timestamp() * 1000))
        end = str(int(pd.Timestamp(kwargs["coverage_end_utc"]).timestamp() * 1000))
        rows = [
            row for row in self.venue.state.get("bills", [])
            if int(begin) <= int(row["ts"]) <= int(end)
        ]
        if any(
            "balChg" not in row
            or not str(row.get("balChg") or "").strip()
            for row in rows
        ):
            raise QlibOfflineReplayError(
                "qlib_fixture_funding_cashflow_unknown"
            )
        return build_okx_account_cashflow_evidence(
            pages=[{"request": {"begin": begin, "end": end, "limit": "100"}, "rows": rows}],
            account_identity_hash=kwargs["account_identity_hash"],
            snapshot_sha256=kwargs["snapshot_sha256"],
            coverage_start_utc=kwargs["coverage_start_utc"],
            coverage_end_utc=kwargs["coverage_end_utc"],
            reference_time_utc=kwargs["reference_time_utc"],
        )

    def _set_explicit_offline_runtime_facts(
        self, *, active: bool, preserve_liveness: bool = False,
    ) -> None:
        state = self.controller._state
        state["strategy"] = {
            "strategy_id": self.config.strategy_id,
            "candidate_id": self.config.candidate_id,
            "strategy_version": self.config.strategy_version,
            "params_hash": self.config.policy_sha256,
        }
        state["limits"].update(
            {
                "order_contracts": "0.01",
                "max_net_contracts": "0.01",
                "max_notional_usdt": "10",
                "margin_mode": "isolated",
            }
        )
        runtime_facts = {
                "run_id": self.config.run_id,
                "active": active,
                "status": "offline_execution" if active else "offline_reconciling",
                "opening_allowed": active,
                "cancel_only": not active,
                "source_head": self.source_head,
                "authoritative_liveness_epoch": 1,
                "authoritative_liveness_required": False,
                "authoritative_liveness_worker_required": False,
                "credential_namespace": "quant-system.okx-demo.offline",
            }
        if not preserve_liveness:
            runtime_facts["last_heartbeat_utc"] = self._now.isoformat()
        state["runtime"].update(runtime_facts)
        state["risk_control"].update(
            {"mode": "RUNNING" if active else "FROZEN_UNKNOWN", "write_path_trusted": active}
        )
        if not preserve_liveness:
            state["risk_control"]["dead_man"].update(
                {"armed": True, "last_ack_utc": self._now.isoformat()}
            )
        state["private_ws"].update(
            {
                "status": "connected" if active else "reconciling",
                "connected": active,
                "listener_alive": active,
                "opening_allowed_after_reconciliation": active,
            }
        )

    def _assert_ledger(self, snapshot: Mapping[str, Any]) -> None:
        ledger = self.controller._state.get("ledger_reconciliation", {})
        if not (
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
            and ledger.get("exchange_snapshot_sha256")
            == canonical_ledger_snapshot_sha256(snapshot)
            and ledger.get("funding_cashflow_reconciled") is True
            and self.controller._state.get("account_risk_facts", {}).get("risk_eligible") is True
        ):
            raise OkxDemoPaperRuntimeError("qlib_fixture_ledger_not_current")

    def _renew_verified_offline_liveness(self) -> None:
        """Renew through the existing dispatcher and simulated CAA receipt."""

        state = self.controller._state
        if not (
            state.get("runtime", {}).get("active") is True
            and state.get("runtime", {}).get("opening_allowed") is True
            and state.get("risk_control", {}).get("mode") == "RUNNING"
            and state.get("risk_control", {}).get("write_path_trusted") is True
            and state.get("private_ws", {}).get("connected") is True
            and state.get("private_ws", {}).get("listener_alive") is True
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        ):
            raise QlibOfflineReplayError("qlib_offline_maintenance_authority_untrusted")
        if not self.controller._write_path_is_trusted():
            self.controller._enter_cancel_only("qlib_offline_maintenance_expired", active=True)
            self.controller._persist_state()
            raise QlibOfflineReplayError("qlib_offline_maintenance_expired")
        try:
            self.controller._renew_dead_man_once(self.venue)
        except Exception as exc:
            self.controller._enter_cancel_only("qlib_offline_maintenance_ack_failed", active=True)
            self.controller._persist_state()
            raise QlibOfflineReplayError("qlib_offline_maintenance_ack_failed") from exc
        acknowledgements = self.venue.state.get("offline_maintenance_acks", [])
        if not acknowledgements:
            raise QlibOfflineReplayError("qlib_offline_maintenance_ack_missing")
        state["runtime"]["last_heartbeat_utc"] = self._now.isoformat()
        state_after = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="qlib_offline_maintenance_tick",
            payload={
                "truth_kind": self.config.truth_kind,
                "simulated_transport_ack_sha256": _canonical_digest(acknowledgements[-1]),
                "exchange_snapshot_sha256": state.get("ledger_reconciliation", {}).get("exchange_snapshot_sha256"),
            },
            state_after=state_after,
            idempotency_key="qlib-offline-maintenance:" + self.identity["identity_digest"] + ":" + self._now.isoformat(),
            timestamp_utc=self._now.isoformat(),
            run_id=self.config.run_id,
            safety=dict(state_after["safety"]),
        )
        self.controller._persist_state()

    def _begin_decision_observation(
        self, *, event_id: str, source_time: datetime,
        facts: tuple[OfflineMaintenanceFact, ...],
        settlements: tuple[FundingSettlementFact, ...] = (),
    ) -> dict[str, Any]:
        """Persist one exact observation slot before changing the market facts.

        Recovery reuses this slot, never allocates a later one for the same
        decision. A different decision cannot consume an already used source
        boundary. The original account/ledger validation still follows it.
        """
        slots = [
            event["payload"] for event in self.controller._runtime_store.recover().events
            if event.get("event_type") == "qlib_offline_observation_scheduled"
        ]
        existing = [slot for slot in slots if slot.get("event_id") == event_id]
        if existing:
            slot = existing[-1]
            if (slot.get("source_decision_time_utc") != source_time.isoformat()
                    or slot.get("ordering_sha256") != _canonical_digest(OFFLINE_EVENT_ORDERING)):
                _fail("qlib_offline_event_order_binding_changed")
            processing_time = datetime.fromisoformat(slot["observation_processing_time_utc"])
            if self.venue.now > processing_time:
                execution_limit = source_time + timedelta(hours=1)
                if (self.venue.now > execution_limit
                    or not any(fact.observed_at_utc == self.venue.now for fact in facts)):
                    _fail("qlib_offline_event_order_recovery_advanced")
                # A crash may persist the venue funding event before the
                # matching ledger UOW. Re-run the exact same timestamp: the
                # venue event is idempotent, then reconciliation is committed
                # before any protection or order logic resumes.
                self._advance_offline_time(target_utc=self.venue.now, facts=facts, settlements=settlements)
                return dict(slot)
            self._advance_offline_time(target_utc=processing_time, facts=facts, settlements=settlements)
            return dict(slot)
        if any(datetime.fromisoformat(slot["source_decision_time_utc"]) >= source_time for slot in slots):
            _fail("qlib_offline_event_order_source_boundary_reused")
        previous_time = self.venue.now
        processing_time = _decision_observation_time(source_time=source_time, previous_time=previous_time)
        self._advance_offline_time(target_utc=processing_time, facts=facts, settlements=settlements)
        slot = {
            "event_id": event_id,
            "ordering_version": OFFLINE_EVENT_ORDERING["version"],
            "ordering_sha256": _canonical_digest(OFFLINE_EVENT_ORDERING),
            "source_decision_time_utc": source_time.isoformat(),
            "previous_processing_time_utc": previous_time.isoformat(),
            "observation_processing_time_utc": processing_time.isoformat(),
        }
        state = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="qlib_offline_observation_scheduled", payload=slot,
            state_after=state, idempotency_key="qlib-offline-observation:" + event_id,
            timestamp_utc=processing_time.isoformat(), run_id=self.config.run_id,
            safety=dict(state["safety"]),
        )
        return slot

    def _advance_offline_time(
        self, *, target_utc: datetime, facts: tuple[OfflineMaintenanceFact, ...],
        settlements: tuple[FundingSettlementFact, ...] = (),
    ) -> None:
        """Advance a fixture clock only with explicit facts and real control ACKs.

        Historical hourly bars do not provide these intrahour facts.  Their
        absence blocks the order branch rather than fabricating fresh quotes.
        """

        start = self.venue.now
        if target_utc < start and start - target_utc > timedelta(milliseconds=2):
            raise QlibOfflineReplayError("qlib_offline_event_clock_reversed")
        processed_funding_times: set[datetime] = set()
        def funding_before_protection(fact: OfflineMaintenanceFact) -> bool:
            matches = [row for row in settlements if row.event_time_utc == fact.observed_at_utc]
            if not matches or fact.observed_at_utc in processed_funding_times:
                return False
            if self.registered_inputs is None:
                raise QlibOfflineReplayError("funding_v2_requires_registered_input")
            contract = self._registered_venue_contract()
            self.venue.set_market(now=fact.observed_at_utc, mark_price=fact.mark_price,
                index_price=fact.index_price, fill_price=fact.mark_price)
            for row in matches:
                self.venue.apply_verified_funding_event(fact=row, mark_price=fact.mark_price,
                    contract_value_btc=contract["contract_value_btc"])
            snapshot = self.controller._collect_exchange_snapshot(self.venue)
            self.controller._apply_snapshot(snapshot)
            self.controller._commit_ledger_reconciliation(snapshot=snapshot,
                trigger="qlib_offline_verified_funding_event")
            self._assert_ledger(snapshot)
            processed_funding_times.add(fact.observed_at_utc)
            return True
        if target_utc <= start:
            for fact in facts:
                if fact.observed_at_utc == target_utc:
                    funding_before_protection(fact)
            self._now = start
            return
        self._now = start
        last_ack_text = self.controller._state.get("risk_control", {}).get("dead_man", {}).get("last_ack_utc")
        if isinstance(last_ack_text, str) and start - datetime.fromisoformat(last_ack_text) > timedelta(seconds=10):
            self._renew_verified_offline_liveness()
        cadence = timedelta(seconds=min(20, max(1, self.controller.config.dead_man_timeout_seconds // 2)))
        captured = self.controller._state.get("exchange", {}).get("captured_at_utc")
        snapshot_at = datetime.fromisoformat(captured) if isinstance(captured, str) and captured else start
        available = [fact for fact in facts if start < fact.observed_at_utc <= target_utc]
        cursor = start
        checked_through = start
        while cursor + cadence < target_utc:
            cursor += cadence
            if self.registered_inputs is not None:
                for fact in available:
                    if checked_through < fact.observed_at_utc <= cursor:
                        if funding_before_protection(fact):
                            snapshot_at = fact.observed_at_utc
                        self._registered_protection_guard(
                            fact.observed_at_utc, fact.mark_price, fact.index_price
                        )
                checked_through = cursor
            if cursor - snapshot_at >= timedelta(seconds=100):
                eligible = [fact for fact in available if snapshot_at < fact.observed_at_utc <= cursor]
                if not eligible:
                    raise QlibOfflineReplayError("qlib_offline_maintenance_market_fact_missing")
                fact = eligible[-1]
                self.venue.set_market(
                    now=fact.observed_at_utc, mark_price=fact.mark_price,
                    index_price=fact.index_price, fill_price=fact.mark_price,
                )
                self._now = fact.observed_at_utc
                snapshot = self.controller._collect_exchange_snapshot(self.venue)
                self.controller._apply_snapshot(snapshot)
                self.controller._commit_ledger_reconciliation(
                    snapshot=snapshot, trigger="qlib_offline_explicit_maintenance_fact"
                )
                self._assert_ledger(snapshot)
                snapshot_at = fact.observed_at_utc
            self.venue.now = cursor
            self._now = cursor
            self._renew_verified_offline_liveness()
        if self.registered_inputs is not None:
            for fact in available:
                if checked_through < fact.observed_at_utc <= target_utc:
                    if funding_before_protection(fact):
                        snapshot_at = fact.observed_at_utc
                    self._registered_protection_guard(
                        fact.observed_at_utc, fact.mark_price, fact.index_price
                    )
        self.venue.now = target_utc
        self._now = target_utc
        if not self.controller._write_path_is_trusted():
            raise QlibOfflineReplayError("qlib_offline_maintenance_expired")
        # Persist simulation time separately from market observation time. A
        # clock advance is not a new quote or a new dead-man acknowledgement.
        self.venue.state["offline_clock_utc"] = target_utc.isoformat()
        self.venue._persist()

    def _activate_initial_state(self) -> None:
        recovered = self.controller._runtime_store.recover()
        if recovered.events:
            return
        self._set_explicit_offline_runtime_facts(active=False)
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        baseline = build_explicit_account_drawdown_baseline(
            authority=ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
            account_identity_hash=snapshot["account"]["identity"]["hash"],
            account_scope=ACCOUNT_DRAWDOWN_SCOPE,
            currency="USDT",
            snapshot_sha256=_sha(
                {
                    "kind": "v3_qlib_fixture_pre_decision_baseline",
                    "run_id": self.config.run_id,
                    "observed_at_utc": (self._now - timedelta(seconds=1)).isoformat(),
                }
            ),
            observed_at_utc=self._now - timedelta(seconds=1),
            equity_usdt=snapshot["balance"]["equity_usdt"],
            history_complete=False,
            baseline_event_sequence=0,
        )
        self.controller._state["account_risk_facts"] = baseline
        self.controller._state["account_risk_last_valid_fact"] = baseline
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        self.controller._commit_ledger_reconciliation(
            snapshot=snapshot, trigger="qlib_fixture_activation"
        )
        self._assert_ledger(snapshot)
        self._set_explicit_offline_runtime_facts(active=True)
        self.controller._persist_state()

    def _has_exact_clean_stop(self, recovered: Any) -> bool:
        persisted = recovered.state or {}
        runtime = persisted.get("runtime", {})
        risk = persisted.get("risk_control", {})
        private_ws = persisted.get("private_ws", {})
        lifecycle = [
            event for event in recovered.events
            if event.get("event_type") in {"qlib_offline_clean_stopped", "qlib_offline_runtime_resumed"}
            and event.get("payload", {}).get("identity_digest") == self.identity["identity_digest"]
        ]
        latest = lifecycle[-1] if lifecycle else {}
        return bool(
            latest.get("event_type") == "qlib_offline_clean_stopped"
            and runtime.get("status") == "offline_clean_stopped"
            and runtime.get("active") is False
            and runtime.get("opening_allowed") is False
            and risk.get("mode") == "FROZEN_UNKNOWN"
            and risk.get("write_path_trusted") is False
            and private_ws.get("connected") is False
            and private_ws.get("listener_alive") is False
        )

    @staticmethod
    def _recovery_authority_digest(state: Mapping[str, Any]) -> str:
        return _sha({
            "runtime": {name: state.get("runtime", {}).get(name) for name in (
                "run_id", "source_head", "active", "opening_allowed", "cancel_only", "status", "blockers"
            )},
            "risk_control": {name: state.get("risk_control", {}).get(name) for name in (
                "mode", "write_path_trusted", "reason", "blockers", "pending_order_intents"
            )},
            "private_ws": {name: state.get("private_ws", {}).get(name) for name in (
                "status", "connected", "listener_alive", "opening_allowed_after_reconciliation"
            )},
        })

    def _resume_after_verified_recovery(self) -> None:
        clean = (
            self._clean_stop_recovery_authorized
            and self._clean_stop_projection_digest
            == self._recovery_authority_digest(self.controller._durable_state_snapshot())
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        )
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        # A clean restart may observe the *exact* previously committed account
        # snapshot. Re-submitting that UOW with a new trigger/context changes its
        # semantic payload under the same ledger idempotency key. Reuse only when
        # the stored ledger and drawdown fact already pass the original checks;
        # changed or missing facts still go through authoritative reconciliation.
        ledger = self.controller._state.get("ledger_reconciliation", {})
        already_reconciled = bool(
            ledger.get("status") == "reconciled"
            and ledger.get("current_state_exchange_snapshot_match") is True
            and ledger.get("exchange_snapshot_sha256")
                == canonical_ledger_snapshot_sha256(snapshot)
            and ledger.get("funding_cashflow_reconciled") is True
            and self.controller._state.get("account_risk_facts", {}).get("risk_eligible") is True
        )
        if not already_reconciled:
            self.controller._commit_ledger_reconciliation(
                snapshot=snapshot, trigger="qlib_offline_recovery_reconciliation"
            )
        self._assert_ledger(snapshot)
        if clean:
            dead_man = self.controller._state.get("risk_control", {}).get("dead_man", {})
            try:
                last_ack = datetime.fromisoformat(str(dead_man["last_ack_utc"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise QlibOfflineReplayError("qlib_offline_recovery_dead_man_ack_missing") from exc
            if (
                dead_man.get("armed") is not True
                or last_ack.tzinfo is None
                or last_ack > self._now
                or self._now - last_ack >= timedelta(seconds=self.controller.config.dead_man_timeout_seconds)
            ):
                raise QlibOfflineReplayError("qlib_offline_recovery_dead_man_expired")
            # Restore only the verified offline session projection, not the
            # persisted ACK or heartbeat. The original dispatcher must obtain
            # and durably record a new simulated transport receipt.
            self._set_explicit_offline_runtime_facts(active=True, preserve_liveness=True)
            try:
                self._renew_verified_offline_liveness()
            except BaseException:
                self.controller._enter_cancel_only("qlib_offline_recovery_maintenance_failed", active=True)
                self.controller._persist_state()
                raise
            self._clean_stop_recovery_authorized = False
            state_after = self.controller._durable_state_snapshot()
            self.controller._runtime_store.append(
                event_type="qlib_offline_runtime_resumed",
                payload={"identity_digest": self.identity["identity_digest"], "offline_execution_only": True},
                state_after=state_after,
                idempotency_key=f"qlib-offline-resume:{self.identity['identity_digest']}:{self._now.isoformat()}",
                timestamp_utc=self._now.isoformat(),
                run_id=self.config.run_id,
                safety=dict(state_after["safety"]),
            )
        self.controller._persist_state()

    @staticmethod
    def _object_payload(value: Any) -> dict[str, Any]:
        payload = dict(value.__dict__)
        for name in ("timestamp_utc", "expiry_utc"):
            if isinstance(payload.get(name), datetime):
                payload[name] = payload[name].isoformat()
        return payload

    def _registered_venue_contract(self) -> dict[str, str]:
        if self.registered_inputs is None:
            return {"contract_value_btc": "0.01", "lot_size_contracts": "0.01",
                "minimum_size_contracts": "0.01", "maximum_absolute_contracts": "0.01"}
        manifest = self.registered_inputs.manifest
        if manifest.get("schema_version") != "registered_offline_market_v2":
            return {"contract_value_btc": "0.01", "lot_size_contracts": "0.01",
                "minimum_size_contracts": "0.01", "maximum_absolute_contracts": "0.01"}
        contract = manifest.get("instrument_contract", {})
        exact = {"contract_value_btc": "0.01", "lot_size_contracts": "0.01",
            "minimum_size_contracts": "0.01", "maximum_market_size_contracts": "35000"}
        if ({key: _decimal_text(_finite_decimal(contract.get(key), field=key)) for key in exact} != exact
            or contract.get("instrument_id") != "BTC-USDT-SWAP"
            or contract.get("venue") != "OKX"
            or contract.get("historical_availability_assumption") != "frozen_engineering_contract_assumption_not_june_pit_proof"
            or _SHA256.fullmatch(str(contract.get("source_sha256") or "")) is None):
            raise QlibOfflineReplayError("registered_instrument_contract_not_existing_btc_simulator")
        # maxMktSz is exchange metadata only. Preserve the existing one-target
        # simulator cap; it is not a grant to enlarge the strategy risk budget.
        return {"contract_value_btc": exact["contract_value_btc"],
            "lot_size_contracts": exact["lot_size_contracts"],
            "minimum_size_contracts": exact["minimum_size_contracts"],
            "maximum_absolute_contracts": "0.01"}

    def _registered_funding_schedule(self) -> tuple[FundingSettlementFact, ...]:
        if (self.registered_inputs is None
            or self.registered_inputs.manifest.get("schema_version") != "registered_offline_market_v2"):
            return ()
        return tuple(sorted((fact for observation in self.registered_inputs.observations
            for fact in observation.funding_settlements), key=lambda fact: fact.event_time_utc))

    def _market_after_registered_advance(
        self, *, at: datetime, observation: CandidateMarketObservation,
        fallback_mark: Any, fallback_index: Any,
        require_current_fact: bool = False,
        require_applied_fact: bool = False,
    ) -> tuple[Decimal, Decimal]:
        """Keep a verified v2 settlement quote after the clock has advanced.

        A resumed decision remains bound to its original policy, but its later
        execution must not overwrite a current mark/index with the old decision
        observation.  Every v2 fill uses the exact maintenance fact at its fill
        time.  Settlement/recovery facts must also already be applied to the
        venue; no latest-value or future-value substitution is permitted.
        """
        if (self.registered_inputs is None
            or self.registered_inputs.manifest.get("schema_version") != "registered_offline_market_v2"):
            return (_finite_decimal(fallback_mark, field="fixture_mark_price"),
                _finite_decimal(fallback_index, field="fixture_index_price"))
        settlements = [fact for fact in self._registered_funding_schedule()
            if fact.event_time_utc == at]
        if not settlements and not require_current_fact:
            return (_finite_decimal(fallback_mark, field="fixture_mark_price"),
                _finite_decimal(fallback_index, field="fixture_index_price"))
        exact = [fact for fact in observation.maintenance_facts
            if fact.observed_at_utc == at]
        if len(exact) != 1 or len(settlements) > 1:
            raise QlibOfflineReplayError("registered_current_market_fact_missing_or_ambiguous")
        mark = _finite_decimal(exact[0].mark_price, field="fixture_mark_price")
        index = _finite_decimal(exact[0].index_price, field="fixture_index_price")
        if ((settlements or require_applied_fact)
            and (self.venue.now != at or self.venue.market_price != mark
                or self.venue.index_price != index)):
            raise QlibOfflineReplayError("registered_current_market_fact_not_applied")
        return mark, index

    def _apply_observation_funding(self, observation: CandidateMarketObservation, *, decision_time: datetime) -> None:
        if observation.funding_settlements:
            if self.registered_inputs is None or observation.funding_cashflow_usdt != 0:
                raise QlibOfflineReplayError("funding_v2_requires_registered_unpriced_events")
            for fact in observation.funding_settlements:
                if fact.event_time_utc != decision_time:
                    raise QlibOfflineReplayError("funding_event_not_current_decision")
                if not any(row.get("event_id") == fact.event_id for row in self.venue.state["funding_settlements"]):
                    raise QlibOfflineReplayError("funding_event_not_processed_in_maintenance_order")
            return
        self.venue.apply_funding(amount_usdt=observation.funding_cashflow_usdt, timestamp_utc=decision_time)

    def _cleanup_flat_protection(self) -> None:
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        if Decimal(str(self.venue.state["position"])) != 0 or not snapshot.get("pending_algo_orders"):
            return
        refreshed, _ = self.controller._cleanup_owned_flat_algos(self.venue, snapshot=snapshot)
        self.controller._apply_snapshot(refreshed)
        self.controller._commit_ledger_reconciliation(
            snapshot=refreshed, trigger="qlib_fixture_flat_protection_cleanup"
        )
        self._assert_ledger(refreshed)

    def _policy_state(self) -> CandidateExitState:
        path = self.config.state_dir / "qlib_policy_state.json"
        position_btc = float(Decimal(str(self.venue.state["position"])) * Decimal("0.01"))
        average = float(self.venue.state.get("average_price", "0"))
        if not path.exists():
            return CandidateExitState(position_btc, average, average if position_btc else None, 0)
        row = json.loads(path.read_text(encoding="utf-8"))
        if str(row.get("identity_digest")) != self.identity["identity_digest"]:
            raise QlibOfflineReplayError("qlib_policy_state_identity_mismatch")
        if not math.isclose(float(row.get("quantity", 0)), position_btc, abs_tol=1e-12):
            raise QlibOfflineReplayError("qlib_policy_state_position_mismatch")
        return CandidateExitState(
            position_btc,
            average,
            None if row.get("favorable_price") is None else float(row["favorable_price"]),
            int(row.get("holding_bars", 0)),
        )

    def _persist_policy_state(self, state: CandidateExitState) -> None:
        position_btc = float(Decimal(str(self.venue.state["position"])) * Decimal("0.01"))
        average = float(self.venue.state.get("average_price", "0"))
        if position_btc == 0:
            state = CandidateExitState(0.0, 0.0, None, 0)
        elif state.quantity == 0 or math.copysign(1, state.quantity) != math.copysign(1, position_btc):
            state = CandidateExitState(position_btc, average, average, 0)
        else:
            state = CandidateExitState(position_btc, average, state.favorable_price, state.holding_bars)
        _atomic_json(self.config.state_dir / "qlib_policy_state.json", {
            "identity_digest": self.identity["identity_digest"],
            "quantity": state.quantity,
            "average_price": state.average_price,
            "favorable_price": state.favorable_price,
            "holding_bars": state.holding_bars,
        })

    def _recover_result(self, *, event_id: str, phase: str) -> dict[str, Any] | None:
        recovered = self.controller._runtime_store.recover()
        policy_events = [
            event for event in recovered.events
            if event.get("event_type") == "qlib_policy_step_bound"
            and event.get("payload", {}).get("event_id") == event_id
        ]
        if len(policy_events) != 1:
            if policy_events:
                raise QlibOfflineReplayError("qlib_offline_policy_binding_ambiguous")
            return None
        lifecycle = [
            event for event in recovered.events
            if event.get("event_type") == "order_lifecycle"
            and event.get("payload", {}).get("sealed_strategy_binding", {}).get("event_id") == event_id
        ]
        if not lifecycle:
            return None
        if len(lifecycle) != 1:
            raise QlibOfflineReplayError("qlib_offline_lifecycle_ambiguous")
        order_event = lifecycle[0]
        audit = order_event["payload"]
        sequence = int(order_event.get("sequence") or 0)
        client_id = str(audit.get("oms", {}).get("client_order_id") or audit.get("order_plan", {}).get("client_order_id") or "")
        ledgers = [
            event for event in recovered.events
            if event.get("event_type") == "ledger_uow_committed"
            and int(event.get("sequence") or 0) > sequence
            and any(str(row.get("client_order_id") or "") == client_id for row in event.get("payload", {}).get("order_ledger", {}).get("orders", []))
        ]
        if not ledgers:
            return None
        # The first committed UOW which contains this order is its immutable
        # terminal snapshot.  Later reconciliations contain cumulative orders
        # and must never move a historical decision's evidence forward.
        ledger = ledgers[0]
        ledger_payload = ledger["payload"]
        order_rows = ledger_payload.get("order_ledger", {}).get("orders", [])
        fill_rows = ledger_payload.get("fill_ledger", [])
        exact_fills = [
            row for row in fill_rows
            if str(row.get("clOrdId") or row.get("client_order_id") or "") == client_id
        ]
        fill_ids = [str(row.get("tradeId") or row.get("fill_id") or "") for row in exact_fills]
        if not client_id or any(not value for value in fill_ids) or len(fill_ids) != len(set(fill_ids)):
            raise QlibOfflineReplayError("qlib_offline_terminal_fill_identity_invalid")
        order_ids = sorted({
            str(row.get("order_id") or row.get("ordId") or "")
            for row in order_rows
            if str(row.get("client_order_id") or row.get("clOrdId") or "") == client_id
        } - {""})
        return {
            "event_id": event_id,
            "phase": phase,
            "decision_outcome": "order_terminal",
            "position_contracts": str(ledger_payload["position_ledger"]["signed_contracts"]),
            "submit_count": len(order_rows),
            "fill_count": len(fill_rows),
            "forecast_id": audit["forecast"]["forecast_id"],
            "candidate_target_position_id": audit["candidate_target_position"]["target_position_id"],
            "execution_target_position_id": audit["target_position"]["target_position_id"],
            "order_intent_id": audit["oms"]["order_intent_id"],
            "client_order_id": client_id,
            "order_ids": order_ids,
            "fill_ids": fill_ids,
            "action": audit["order_plan"]["action"],
            "ledger_event_id": ledger["idempotency_key"],
            "ledger_event_hash": ledger["event_hash"],
            "policy_event_hash": policy_events[0]["event_hash"],
            "recovered_without_resubmit": True,
            "truth_kind": self.config.truth_kind,
            "permissions": {name: False for name in sorted(_FALSE_PERMISSIONS)},
        }

    def _recover_bound_policy(
        self, *, event_id: str, input_binding: Mapping[str, Any],
    ) -> tuple[_RecoveredCandidatePolicy, ContractConversion | None, tuple[str, ...], dict[str, Any]] | None:
        if (self.registered_inputs is None
            or self.registered_inputs.manifest.get("schema_version") != "registered_offline_market_v2"):
            return None
        recovered = self.controller._runtime_store.recover()
        bound = [event for event in recovered.events
            if event.get("event_type") == "qlib_policy_step_bound"
            and event.get("payload", {}).get("event_id") == event_id]
        if not bound:
            return None
        if len(bound) != 1:
            raise QlibOfflineReplayError("qlib_offline_policy_binding_ambiguous")
        lifecycle = [event for event in recovered.events
            if event.get("event_type") == "order_lifecycle"
            and event.get("payload", {}).get("sealed_strategy_binding", {}).get("event_id") == event_id]
        if lifecycle:
            raise QlibOfflineReplayError("qlib_offline_existing_lifecycle_incomplete")
        pending = self.controller._state.get("risk_control", {}).get("pending_order_intents", {})
        if any(not isinstance(row, Mapping)
            or str(row.get("status") or "") not in OKX_DEMO_TERMINAL_INTENT_STATUSES
            for row in (pending or {}).values()):
            raise QlibOfflineReplayError("qlib_offline_pending_intent_recovery_blocked")
        binding = bound[0].get("payload", {})
        if any(binding.get(key) != value for key, value in input_binding.items()):
            raise QlibOfflineReplayError("qlib_offline_policy_resume_input_mismatch")
        resume = binding.get("resume_policy")
        if not isinstance(resume, Mapping) or resume.get("schema_version") != "qlib_policy_resume_v1":
            raise QlibOfflineReplayError("qlib_offline_policy_resume_missing")
        core = {key: value for key, value in resume.items() if key != "sha256"}
        if resume.get("sha256") != _canonical_digest(core):
            raise QlibOfflineReplayError("qlib_offline_policy_resume_hash_mismatch")
        try:
            target_payload = dict(core["target"])
            target_payload["timestamp_utc"] = datetime.fromisoformat(target_payload["timestamp_utc"])
            target = TargetPosition(**target_payload)
            exit_state = CandidateExitState(**core["exit_state"])
            conversion_payload = core["conversion"]
            conversion = None if conversion_payload is None else ContractConversion(**conversion_payload)
            policy = _RecoveredCandidatePolicy(
                target=target, approved=core["approved"],
                reasons=tuple(core["policy_reasons"]), exit_reasons=tuple(core["exit_reasons"]),
                exit_state=exit_state,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise QlibOfflineReplayError("qlib_offline_policy_resume_invalid") from exc
        if (type(policy.approved) is not bool
            or _canonical_sha256(self._object_payload(target)) != binding.get("candidate_target_sha256")
            or target.target_position_id != binding.get("candidate_target_position_id")
            or str(self.venue.state["position"]) != str(core.get("position_contracts"))):
            raise QlibOfflineReplayError("qlib_offline_policy_resume_binding_mismatch")
        if conversion is not None:
            expected = btc_quantity_to_okx_contracts(
                btc_quantity=target.target_quantity or 0.0, **{
                    "contract_value_btc": self._registered_venue_contract()["contract_value_btc"],
                    "lot_size_contracts": self._registered_venue_contract()["lot_size_contracts"],
                    "min_size_contracts": self._registered_venue_contract()["minimum_size_contracts"],
                    "max_abs_contracts": self._registered_venue_contract()["maximum_absolute_contracts"],
                })
            if expected != conversion:
                raise QlibOfflineReplayError("qlib_offline_policy_resume_conversion_mismatch")
        blockers = core.get("execution_blockers")
        if not isinstance(blockers, list) or not all(isinstance(value, str) for value in blockers):
            raise QlibOfflineReplayError("qlib_offline_policy_resume_invalid")
        return policy, conversion, tuple(blockers), dict(binding)

    def _repair_policy_projection(self, *, event_id: str, result: Mapping[str, Any]) -> None:
        recovered = self.controller._runtime_store.recover()
        bound = [
            event for event in recovered.events
            if event.get("event_type") == "qlib_policy_step_bound"
            and event.get("payload", {}).get("event_id") == event_id
        ]
        if len(bound) != 1:
            raise QlibOfflineReplayError("qlib_offline_policy_binding_missing")
        projected = bound[0]["payload"].get("exit_state_after")
        if not isinstance(projected, Mapping):
            raise QlibOfflineReplayError("qlib_offline_exit_state_projection_missing")
        if str(result["position_contracts"]) != str(self.venue.state["position"]):
            # An older decision replayed after subsequent valid events is
            # read-only; rewriting its projection would roll state backwards.
            return
        state = CandidateExitState(
            float(projected["quantity"]),
            float(projected["average_price"]),
            None if projected["favorable_price"] is None else float(projected["favorable_price"]),
            int(projected["holding_bars"]),
        )
        self._persist_policy_state(state)

    def _append_decision_evidence(self, *, event_id: str, binding: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        state_after = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="qlib_offline_decision_evidence",
            payload={"binding": dict(binding), "result": dict(result)},
            state_after=state_after,
            idempotency_key="qlib-offline:" + event_id,
            timestamp_utc=self._now.isoformat(),
            run_id=self.config.run_id,
            safety=dict(state_after["safety"]),
        )
        self.controller._persist_state()

    def _verified_input_digest(
        self, *, forecast: BTCForecast, facts: CandidatePolicyFacts,
        observation: CandidateMarketObservation,
    ) -> str:
        return _canonical_digest({
            "forecast": self._object_payload(forecast),
            "facts": {
                "decision_id": facts.decision_id,
                "equity": facts.account_equity,
                "mark": facts.mark_price,
                "quantity": facts.current_quantity,
                "risk_budget": facts.risk_budget.__dict__,
                "risk_state": facts.risk_state.__dict__,
                "exit_state": facts.exit_state.__dict__,
                "exit_observation": facts.exit_observation.__dict__,
                "versions": facts.versions.to_dict(),
            },
            "observation": {
                "event_time": observation.event_time_utc.isoformat(),
                "close": observation.close_price,
                "mark": observation.mark_price,
                "index": observation.index_price,
                "funding_rate": observation.funding_rate,
                "blockers": list(observation.blockers),
            },
        })

    def flush_sealed_rejections(self) -> None:
        """Commit a bounded, ordered set of read-only denials in the existing fsync log.

        This is a log record, not an OMS/ledger transaction. A torn record stays
        fail-closed under the runtime store's existing recovery rules.
        """
        if self._sealed_append_failed:
            raise QlibOfflineReplayError("qlib_sealed_batch_append_failed")
        if not self._sealed_buffer:
            if self._sealed_committed:
                self._persist_policy_state(self._sealed_exit_state)
            return
        if self.config.truth_kind != "sealed_candidate_research_only" or len(self._sealed_buffer) > 64:
            raise QlibOfflineReplayError("qlib_sealed_batch_invalid")
        rows = tuple(self._sealed_buffer)
        state = self.controller._durable_state_snapshot()
        first, last = rows[0], rows[-1]
        try:
            event = self.controller._runtime_store.append(
                event_type="qlib_offline_rejected_batch",
            payload={
                "identity_digest": self.identity["identity_digest"],
                "first_decision_hash": first["decision_hash"],
                "last_decision_hash": last["decision_hash"],
                "decisions": list(rows),
                "logical_decision_count": len(rows),
                "execution_permission": False,
            },
            state_after=state,
            idempotency_key="qlib-rejected-batch:" + last["decision_hash"],
            timestamp_utc=last["decision_time_utc"],
            run_id=self.config.run_id,
                safety=dict(state["safety"]),
            )
        except Exception:
            self._sealed_append_failed = True
            raise
        for index, row in enumerate(rows):
            committed = {**row, "batch_event_sequence": event["sequence"], "batch_event_hash": event["event_hash"], "batch_index": index}
            self._sealed_committed[row["source_key"]] = committed
        self._sealed_buffer.clear()
        self._persist_policy_state(self._sealed_exit_state)

    def _execute_sealed_rejection(
        self, *, forecast: BTCForecast, facts: CandidatePolicyFacts,
        observation: CandidateMarketObservation, phase: str,
        source_key: str, event_id: str, input_binding: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if self.config.truth_kind != "sealed_candidate_research_only":
            return None
        if self._sealed_append_failed:
            raise QlibOfflineReplayError("qlib_sealed_batch_append_failed")
        prior = self._sealed_committed.get(source_key)
        if prior is None:
            prior = next((row for row in self._sealed_buffer if row["source_key"] == source_key), None)
        if prior is not None:
            if prior["input_binding"] != input_binding:
                raise QlibOfflineReplayError("qlib_fixture_sealed_input_changed")
            self._sealed_exit_state = CandidateExitState(**prior["exit_state_after"])
            return dict(prior["result"])
        if facts.exit_state != self._sealed_exit_state:
            raise QlibOfflineReplayError("qlib_sealed_exit_state_mismatch")
        if (
            Decimal(str(self.venue.state["position"])) != 0
            or self.venue.state.get("orders")
            or self.venue.state.get("fills")
            or self.venue.state.get("bills")
            or float(self.venue.state["equity"]) != self.config.initial_equity_usdt
            or observation.funding_cashflow_usdt != 0
            or facts.current_quantity != 0
            or not math.isclose(facts.account_equity, self.config.initial_equity_usdt, abs_tol=1e-8)
            or self.controller._state.get("risk_control", {}).get("pending_order_intents")
            or self.guardian_supervisor.tripped
            or self.guardian_supervisor.persistence_error
        ):
            self.flush_sealed_rejections()
            return None
        step = evaluate_candidate_step(facts, venue={
            "contract_value_btc": "0.01", "lot_size_contracts": "0.01",
            "minimum_size_contracts": "0.01", "maximum_absolute_contracts": "0.01",
        })
        if step.policy.approved:
            self.flush_sealed_rejections()
            return None
        result = {
            "event_id": event_id, "phase": phase,
            "decision_outcome": "policy_rejected_no_order",
            "position_contracts": "0", "submit_count": 0, "fill_count": 0,
            "forecast_id": forecast.forecast_id,
            "candidate_target_position_id": step.policy.target.target_position_id,
            "candidate_target_quantity_btc": step.policy.target.target_quantity,
            "policy_reasons": list(step.policy.reasons),
            "execution_blockers": list(step.execution_blockers),
            "truth_kind": self.config.truth_kind,
            "permissions": {name: False for name in sorted(_FALSE_PERMISSIONS)},
        }
        row = {
            "source_key": source_key,
            "event_id": event_id,
            "input_binding": dict(input_binding),
            "decision_time_utc": forecast.timestamp_utc.isoformat(),
            "target_position_id": step.policy.target.target_position_id,
            "policy_reasons": list(step.policy.reasons),
            "exit_reasons": list(step.policy.exit_reasons),
            "exit_state_before": self._sealed_exit_state.__dict__,
            "exit_state_after": step.policy.exit_state.__dict__,
            "result": result,
            "previous_decision_hash": self._sealed_last_hash,
        }
        row["decision_hash"] = _canonical_digest(row)
        self._sealed_buffer.append(row)
        self._sealed_last_hash = row["decision_hash"]
        self._sealed_exit_state = step.policy.exit_state
        if len(self._sealed_buffer) >= 64:
            self.flush_sealed_rejections()
        return result

    def execute_registered(self, index: int) -> dict[str, Any]:
        from .btc_registered_candidate import registered_forecast
        if self.registered_inputs is None:
            raise QlibOfflineReplayError("registered_verified_source_required")
        self._repair_registered_protection_evidence()
        if self.controller._state.get("registered_protection_blocker"):
            raise QlibOfflineReplayError("registered_protection_execution_unsupported")
        return self.execute(forecast=registered_forecast(self.registered_inputs,index),
            observation=self.registered_inputs.observations[index],phase="registered_candidate_step")

    def _commit_registered_protection_receipt(self, receipt: Mapping[str, Any]) -> None:
        """Bind an exchange-shaped protection fill to the existing ledger."""

        recovered = self.controller._runtime_store.recover()
        algo_id = str(receipt.get("algo_id") or "")
        prior = [
            event for event in recovered.events
            if event.get("event_type") == "registered_protection_executed"
            and event.get("payload", {}).get("algo_id") == algo_id
        ]
        if prior:
            if len(prior) != 1 or prior[0].get("payload") != dict(receipt):
                raise QlibOfflineReplayError("registered_protection_receipt_conflict")
            return
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        expected = canonical_ledger_snapshot_sha256(snapshot)
        ledger = self.controller._state.get("ledger_reconciliation", {})
        if ledger.get("exchange_snapshot_sha256") != expected:
            self.controller._commit_ledger_reconciliation(
                snapshot=snapshot, trigger="registered_sampled_mark_protection_fill"
            )
        self._assert_ledger(snapshot)
        durable = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(
            event_type="registered_protection_executed",
            payload=dict(receipt),
            state_after=durable,
            idempotency_key="registered-protection-executed:" + algo_id,
            timestamp_utc=str(receipt["observedAtUtc"]),
            run_id=self.config.run_id,
            safety=dict(durable["safety"]),
        )
        self.controller._persist_state()

    def _repair_registered_protection_evidence(self) -> None:
        """Repair only the ledger/evidence tail after an atomic venue fill."""

        if self.registered_inputs is None:
            return
        for algo in self.venue.state.get("algo_history", []):
            fill_id = str(algo.get("protectionFillId") or "")
            order_id = str(algo.get("protectionOrderId") or "")
            algo_id = str(algo.get("algoId") or "")
            if not (fill_id and order_id and algo_id):
                continue
            fills = [row for row in self.venue.state["fills"] if row.get("tradeId") == fill_id]
            orders = [row for row in self.venue.state["orders"] if row.get("ordId") == order_id]
            if len(fills) != 1 or len(orders) != 1:
                raise QlibOfflineReplayError("registered_protection_recovery_identity_invalid")
            fill = fills[0]
            order = orders[0]
            fields = {
                "algo_id": algo_id,
                "order_id": order_id,
                "fill_id": fill_id,
                "fill": fill,
                "triggerKind": fill.get("triggerKind"),
                "protectionAlgoId": fill.get("protectionAlgoId"),
                "parentClOrdId": fill.get("parentClOrdId"),
                "parentOrdId": fill.get("parentOrdId"),
                "parentFillId": fill.get("parentFillId"),
                "observedAtUtc": fill.get("observedAtUtc"),
                "observedMarkPx": fill.get("observedMarkPx"),
                "observedIndexPx": fill.get("observedIndexPx"),
                "triggerThresholdPx": fill.get("triggerThresholdPx"),
                "triggerReferencePx": fill.get("triggerReferencePx"),
                "observationSource": fill.get("observationSource"),
                "pricePolicy": fill.get("pricePolicy"),
                "pricePolicySha256": fill.get("pricePolicySha256"),
                "adverseNonFeeBps": fill.get("adverseNonFeeBps"),
            }
            if (
                any(value in {None, ""} for value in fields.values() if not isinstance(value, Mapping))
                or order.get("protectionAlgoId") != algo_id
                or order.get("parentOrdId") != fill.get("parentOrdId")
            ):
                raise QlibOfflineReplayError("registered_protection_recovery_evidence_invalid")
            self._commit_registered_protection_receipt(fields)

    def _registered_protection_guard(self, at, mark, index=None):
        """Execute only a proven hosted OCO at an explicit sampled mark point.

        This does not infer an intrainterval path. Missing ownership, ordering or
        mark facts still freeze the registered run before further economics.
        """
        if self.registered_inputs is None: return False
        self._repair_registered_protection_evidence()
        state = self.controller._state
        if state.get("registered_protection_blocker"):
            raise QlibOfflineReplayError("registered_protection_execution_unsupported")
        position = Decimal(str(self.venue.state["position"]))
        if position == 0: return False
        algos = self.venue.state.get("algos", [])
        reason = None
        if len(algos) != 1:
            reason = "effective_protection_missing_or_ambiguous"
        else:
            a = algos[0]
            try:
                if at.tzinfo is None or at.utcoffset() is None:
                    raise ValueError("sampled_mark_time_timezone_missing")
                at = at.astimezone(timezone.utc)
                visible = Decimal(str(mark))
                sl, tp = Decimal(a["slTriggerPx"]), Decimal(a["tpTriggerPx"])
                parent = [o for o in self.venue.state["orders"] if o["clOrdId"] == a["parentClOrdId"] and o["state"] == "filled"]
                if (a["state"] != "live" or a["slTriggerPxType"] != "mark" or a["tpTriggerPxType"] != "mark"
                    or a.get("tpOrdPx") != "-1" or a.get("slOrdPx") != "-1"
                    or len(parent) != 1 or int(a["uTime"]) >= int(at.timestamp() * 1000)):
                    reason = "protection_effective_evidence_missing"
                else:
                    touch = classify_mark_protection_touch(
                        position_side=str(a.get("posSide") or ""),
                        mark_open=visible,
                        mark_high=visible,
                        mark_low=visible,
                        stop_trigger=sl,
                        take_trigger=tp,
                    )
                    if touch.stop_hit and touch.take_hit:
                        reason = "sampled_mark_protection_double_touch_ambiguous"
                    elif touch.stop_hit or touch.take_hit:
                        trigger_kind = "stop_loss" if touch.stop_hit else "take_profit"
                        cost = self.registered_inputs.package["contracts"]["cost"]
                        adverse_bps = sum(
                            Decimal(str(cost[name]))
                            for name in (
                                "spread_bps_per_side",
                                "slippage_bps_per_side",
                                "impact_bps_per_side",
                            )
                        )
                        receipt = self.venue.execute_registered_protection(
                            algo_id=str(a["algoId"]),
                            observed_at_utc=at,
                            observed_mark=visible,
                            observed_index=visible if index is None else index,
                            trigger_kind=trigger_kind,
                            trigger_threshold=sl if touch.stop_hit else tp,
                            trigger_reference=(
                                touch.stop_reference_price
                                if touch.stop_hit
                                else touch.take_reference_price
                            ),
                            adverse_fill_bps=adverse_bps,
                        )
                        self._commit_registered_protection_receipt(receipt)
                        return True
            except (KeyError, ValueError, TypeError, ArithmeticError, ProtectionTriggerAmbiguous):
                reason = "protection_path_evidence_invalid"
        if reason is None: return False
        blocker = {"reason": reason, "observed_at_utc": at.isoformat(), "mark_price": str(mark),
                   "protection": algos, "position_contracts": str(position),
                   "input_digest": self.registered_inputs.digest,
                   "limitation": "sampled_mark_only_intrainterval_path_not_inferred"}
        state["registered_protection_blocker"] = blocker
        state["runtime"].update(active=False, opening_allowed=False, status="registered_protection_blocked")
        state["risk_control"].update(mode="FROZEN_UNKNOWN", write_path_trusted=False)
        durable = self.controller._durable_state_snapshot()
        self.controller._runtime_store.append(event_type="registered_protection_blocked", payload=blocker,
            state_after=durable, idempotency_key="registered-protection:" + _canonical_digest(blocker),
            timestamp_utc=at.isoformat(), run_id=self.config.run_id, safety=dict(durable["safety"]))
        self.controller._persist_state()
        raise QlibOfflineReplayError("registered_protection_execution_unsupported")

    def reconcile_registered(self):
        """Recover and reconcile existing economics; never submit or flatten."""
        if self.registered_inputs is None:
            raise QlibOfflineReplayError("registered_verified_source_required")
        from .btc_registered_candidate import check_registered_inputs
        check_registered_inputs(self.registered_inputs)
        snapshot=self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        ledger=self.controller._state.get("ledger_reconciliation",{})
        if (ledger.get("status")!="reconciled"
            or ledger.get("exchange_snapshot_sha256")!=canonical_ledger_snapshot_sha256(snapshot)):
            self.controller._commit_ledger_reconciliation(snapshot=snapshot,trigger="registered_safety_recovery")
        self._assert_ledger(snapshot)
        state=self.controller._state
        state["runtime"].update(active=False,opening_allowed=False,status="registered_safety_recovered")
        state["risk_control"].update(mode="FROZEN_UNKNOWN",write_path_trusted=False)
        self.controller._persist_state()
        return {"registration_id":self.registered_inputs.row["id"],"new_risk_allowed":False,
            "position_contracts":self.venue.state["position"],"fill_count":len(self.venue.state["fills"]),
            "account_ledger_replay":dict(state["ledger_reconciliation"]["account_ledger_replay"]),
            "protection_count":len(snapshot["pending_algo_orders"])}

    def build_registered_candidate_facts(self, template, observation):
        """Map the frozen candidate to facts from the same recovered account.

        Existing constitution, Guardian, OMS, protection and ledger retain their
        authority. No caller-supplied health/drawdown/PnL defaults are consumed.
        """
        from quant_crypto.risk.kernel import evaluate_combined_loss
        from quant_shared.strategy_delivery.models import digest
        from .btc_registered_candidate import offline_simulated_account_identity
        state = self.controller._state
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self._assert_ledger(snapshot)
        risk = state["account_risk_facts"]
        ledger = state["ledger_reconciliation"]["account_ledger_replay"]
        if (risk["account_identity_hash"] != offline_simulated_account_identity()
            or risk["account_identity_hash"] != self.registered_inputs.row["binding"]["offline_runtime"]["simulated_venue_identity_hash"]
            or ledger.get("status") != "reconciled" or ledger.get("reconciled") is not True
            or risk.get("external_cashflow_complete") is not True):
            raise QlibOfflineReplayError("registered_account_ledger_facts_unverified")
        equity = float(ledger["final_equity_usdt"])
        if not math.isclose(equity,template.account_equity,abs_tol=1e-8):
            raise QlibOfflineReplayError("registered_ledger_equity_mismatch")
        recovered = self.controller._runtime_store.recover()
        if recovered.blockers or recovered.truncated_tail:
            raise QlibOfflineReplayError("registered_ledger_recovery_blocked")
        day = self._now.replace(hour=0,minute=0,second=0,microsecond=0)
        prior = [e["payload"]["risk_context"]["account_ledger_replay"] for e in recovered.events
            if e.get("event_type")=="ledger_uow_committed"
            and e.get("payload",{}).get("risk_context",{}).get("account_ledger_replay",{}).get("status")=="reconciled"
            and pd.Timestamp(e["payload"]["risk_context"]["account_ledger_replay"]["final_observed_at_utc"]) <= day]
        # A freshly created simulation has no pre-inception history. Its explicit
        # funded baseline is the first day's denominator, not an assumed account.
        baseline = float(prior[-1]["final_equity_usdt"]) if prior else float(risk["baseline_equity_usdt"])
        daily_loss = max(0.,baseline-equity)
        fills = snapshot["fills"]
        if any(not f.get("pnl_observed") for f in fills):
            raise QlibOfflineReplayError("registered_fill_pnl_missing")
        realized = math.fsum(float(f["pnl"]) for f in fills)
        price_pnl = float(ledger["price_pnl_usdt"])
        combined = evaluate_combined_loss(realized,price_pnl-realized,
            float(ledger["funding_cashflow_usdt"]),fees=-float(ledger["fee_cashflow_usdt"]),
            account_equity=equity,constitution=template.constitution,daily_loss=daily_loss,
            drawdown=float(risk["drawdown_ratio"]))
        c = self.registered_inputs.package["contracts"]
        position, exit_policy, cost = c["position"],c["exit"],c["cost"]
        quantity = template.current_quantity
        protection_before = None
        if quantity:
            algos = snapshot["pending_algo_orders"]
            if len(algos)!=1: raise QlibOfflineReplayError("registered_actual_protection_missing")
            algo = algos[0]
            protection_before = {"present":True,"quantity":float(algo["size"])*.01,
                "side":algo["side"],"trigger_price":float(algo["stop_loss_trigger"])}
        # Proposed protection comes from the existing approved controller policy;
        # only actual venue receipts become protection_before on later decisions.
        return replace(template,
            risk_budget=replace(template.risk_budget,max_btc_exposure=position["max_weight"],
                strategy_risk_budget=position["risk_budget_fraction"],
                target_volatility=position["volatility_target_annual_configured"],
                min_cash_fraction=1-position["max_weight"],max_turnover=position["max_weight"]),
            risk_state=replace(template.risk_state,daily_loss_pct=daily_loss/baseline,
                current_drawdown_pct=float(risk["drawdown_ratio"]),
                exchange_available=state["runtime"].get("active") is True
                    and state["risk_control"].get("write_path_trusted") is True
                    and not self.guardian_supervisor.tripped),
            combined_loss=combined, protection_before=protection_before,
            protection_after=lambda q: None if abs(q)<1e-12 else {"present":True,"quantity":abs(q),
                "side":"sell" if q>0 else "buy", "trigger_price":observation.mark_price*(
                    1-float(self.controller._protection_policy.sl_distance_bps)/10000 if q>0 else
                    1+float(self.controller._protection_policy.sl_distance_bps)/10000)},
            cost_estimate=BTCExecutionCostEstimate(fee_bps=2*cost["fee_bps_per_side"],
                spread_bps=2*cost["spread_bps_per_side"],slippage_bps=2*cost["slippage_bps_per_side"],
                impact_bps=2*cost["impact_bps_per_side"],funding_bps=abs(observation.funding_rate)*20000,
                source="registered_frozen_cost_matches_offline_simulator"),
            exit_policy=CandidateExitPolicy(exit_policy["hard_stop_fraction"],exit_policy["trailing_stop_fraction"],exit_policy["maximum_holding_bars"]),
            versions=CandidatePolicyVersions(POLICY_VERSION,*(digest(c[n]) for n in ("position","exit","cost"))))

    def execute(
        self,
        *,
        forecast: BTCForecast,
        observation: CandidateMarketObservation,
        phase: str,
        verified_facts: CandidatePolicyFacts | None = None,
    ) -> dict[str, Any]:
        sealed = self.config.truth_kind == "sealed_candidate_research_only"
        registered = self.config.truth_kind == "registered_candidate_offline_only"
        if registered:
            from .btc_registered_candidate import check_registered_inputs, registered_forecast
            inputs = self.registered_inputs
            check_registered_inputs(inputs)
            if self.controller._state.get("registered_protection_blocker"):
                raise QlibOfflineReplayError("registered_protection_execution_unsupported")
            if inputs.recovery_only:
                raise QlibOfflineReplayError("registered_recovery_forbids_new_decisions")
            matches = [i for i,o in enumerate(inputs.observations) if o == observation]
            if (len(matches) != 1 or forecast != registered_forecast(inputs,matches[0])
                or phase != "registered_candidate_step" or verified_facts is not None):
                raise QlibOfflineReplayError("registered_source_input_mismatch")
        if sealed:
            if not (
                self._verified_sealed_source
                and verified_facts is not None
                and verified_facts.forecast == forecast
                and forecast.strategy_id == self.config.strategy_id
                and forecast.symbol == "BTC-USDT-SWAP"
                and forecast.metadata.get("qlib_run_id") == self.config.run_id
                and forecast.metadata.get("research_only") is True
                and self._sealed_expected_inputs.get(forecast.forecast_id)
                    == self._verified_input_digest(
                        forecast=forecast, facts=verified_facts, observation=observation,
                    )
            ):
                raise QlibOfflineReplayError("qlib_sealed_source_not_verified")
        elif not registered and not (
            verified_facts is None
            and forecast.strategy_id == self.config.strategy_id
            and forecast.symbol == "BTC-USDT-SWAP"
            and forecast.metadata.get("fixture_only") is True
            and forecast.metadata.get("model_sha256") == self.config.model_sha256
            and forecast.metadata.get("data_version") == self.config.data_version
        ):
            raise QlibOfflineReplayError("qlib_fixture_identity_binding_mismatch")
        if observation.event_time_utc + timedelta(hours=1) != forecast.timestamp_utc:
            raise QlibOfflineReplayError("qlib_fixture_event_decision_time_mismatch")
        if forecast.timestamp_utc >= forecast.expiry_utc:
            raise QlibOfflineReplayError("qlib_fixture_forecast_expired")
        visible_observation = {
            "event_time_utc": observation.event_time_utc.isoformat(),
            "close_price": observation.close_price,
            "mark_price": observation.mark_price,
            "index_price": observation.index_price,
            "funding_rate": observation.funding_rate,
            "funding_cashflow_usdt": observation.funding_cashflow_usdt,
            "funding_settlements": [{"event_id": fact.event_id,
                "event_time_utc": fact.event_time_utc.isoformat(), "rate": fact.rate,
                "source_record_id": fact.source_record_id, "source_dataset": fact.source_dataset,
                "source_version": fact.source_version, "source_sha256": fact.source_sha256,
                "valuation_policy": fact.valuation_policy} for fact in observation.funding_settlements],
            "blockers": list(observation.blockers),
            "end_of_window": observation.end_of_window,
        }
        input_binding = {
            "identity_digest": self.identity["identity_digest"],
            "offline_event_ordering_sha256": _canonical_digest(OFFLINE_EVENT_ORDERING),
            "truth_kind": self.config.truth_kind,
            "verified_package_sha256": self.config.verified_package_sha256,
            "phase": phase,
            "forecast_id": forecast.forecast_id,
            "forecast_sha256": _canonical_sha256(self._object_payload(forecast)),
            "observation": visible_observation,
        }
        if verified_facts is not None:
            input_binding["sealed_policy_facts"] = {
                "decision_id": verified_facts.decision_id,
                "account_equity": verified_facts.account_equity,
                "mark_price": verified_facts.mark_price,
                "current_quantity": verified_facts.current_quantity,
                "risk_budget": verified_facts.risk_budget.__dict__,
                "risk_state": verified_facts.risk_state.__dict__,
                "exit_state": verified_facts.exit_state.__dict__,
                "exit_observation": verified_facts.exit_observation.__dict__,
                "versions": verified_facts.versions.to_dict(),
                "blockers": list(verified_facts.blockers),
            }
        input_binding = json.loads(json.dumps(input_binding, default=str))
        event_id = _canonical_digest(input_binding)
        source_key = f"{forecast.forecast_id}:{phase}"
        if sealed:
            batched = self._execute_sealed_rejection(
                forecast=forecast, facts=verified_facts,
                observation=observation, phase=phase, source_key=source_key,
                event_id=event_id, input_binding=input_binding,
            )
            if batched is not None:
                return batched
        recovered = self.controller._runtime_store.recover()
        prior = [
            event for event in recovered.events
            if event.get("event_type") == "qlib_offline_input_bound"
            and event.get("payload", {}).get("source_key") == source_key
        ]
        if prior and prior[-1].get("payload", {}).get("binding") != input_binding:
            raise QlibOfflineReplayError("qlib_fixture_sealed_input_changed")
        existing = [
            event for event in recovered.events
            if event.get("event_type") == "qlib_offline_decision_evidence"
            and event.get("idempotency_key") == "qlib-offline:" + event_id
        ]
        if existing:
            return dict(existing[-1]["payload"]["result"])
        recovered_result = self._recover_result(event_id=event_id, phase=phase)
        if recovered_result is not None:
            self._repair_policy_projection(event_id=event_id, result=recovered_result)
            self._append_decision_evidence(event_id=event_id, binding=input_binding, result=recovered_result)
            return recovered_result
        if not prior:
            state_before = self.controller._durable_state_snapshot()
            self.controller._runtime_store.append(
                event_type="qlib_offline_input_bound",
                payload={"source_key": source_key, "binding": input_binding},
                state_after=state_before,
                idempotency_key="qlib-offline-input:" + _canonical_digest(source_key),
                timestamp_utc=self._now.isoformat(),
                run_id=self.config.run_id,
                safety=dict(state_before["safety"]),
            )

        decision_time = forecast.timestamp_utc
        if not sealed and self.controller._state.get("runtime", {}).get("active") is not True:
            if any(
                event.get("event_type") == "qlib_offline_observation_scheduled"
                and event.get("payload", {}).get("event_id") == event_id
                for event in recovered.events
            ):
                # A durable slot may precede the market write. Restore only
                # this exact, already-bound visible input before reconciliation
                # can stamp the old mark with the new observation time. This
                # does not replace the original recovery/ACK/ledger checks.
                recovery_slot = self._begin_decision_observation(
                    event_id=event_id, source_time=decision_time,
                    facts=observation.maintenance_facts,
                    settlements=self._registered_funding_schedule(),
                )
                recovery_processing_time = datetime.fromisoformat(
                    str(recovery_slot["observation_processing_time_utc"])
                )
                recovery_mark, recovery_index = self._market_after_registered_advance(
                    at=self._now, observation=observation,
                    fallback_mark=observation.mark_price,
                    fallback_index=observation.index_price,
                    require_current_fact=self._now > recovery_processing_time,
                    require_applied_fact=self._now > recovery_processing_time,
                )
                self._registered_protection_guard(
                    self._now, recovery_mark, recovery_index
                )
                self.venue.set_market(
                    now=self._now, mark_price=recovery_mark,
                    index_price=recovery_index, fill_price=observation.close_price,
                )
                self._apply_observation_funding(observation, decision_time=decision_time)
            self._resume_after_verified_recovery()
        if not sealed and self.controller._state.get("runtime", {}).get("active") is not True:
            raise QlibOfflineReplayError("qlib_offline_recovery_not_authorized")
        observation_slot = None
        if sealed:
            if decision_time < self.venue.now:
                raise QlibOfflineReplayError("qlib_sealed_event_clock_reversed")
            self._now = decision_time
        else:
            observation_slot = self._begin_decision_observation(
                event_id=event_id, source_time=decision_time, facts=observation.maintenance_facts,
                settlements=self._registered_funding_schedule(),
            )
        decision_processing_time = (
            datetime.fromisoformat(str(observation_slot["observation_processing_time_utc"]))
            if observation_slot is not None else self._now
        )
        decision_mark, decision_index = self._market_after_registered_advance(
            at=self._now, observation=observation,
            fallback_mark=observation.mark_price,
            fallback_index=observation.index_price,
            require_current_fact=(not sealed and self._now > decision_processing_time),
        )
        self._registered_protection_guard(
            self._now, decision_mark, decision_index
        )
        self.venue.set_market(
            now=self._now, mark_price=decision_mark,
            index_price=decision_index, fill_price=observation.close_price,
        )
        self._apply_observation_funding(observation, decision_time=decision_time)
        if not sealed:
            # This completed decision observation is an explicit current
            # market/account fact. Confirm it before the next hour's simulated
            # maintenance cadence; otherwise a stale pre-decision snapshot is
            # incorrectly used until the next 90-second synthetic observation.
            decision_snapshot = self.controller._collect_exchange_snapshot(self.venue)
            self.controller._apply_snapshot(decision_snapshot)
            current_ledger = self.controller._state.get("ledger_reconciliation", {})
            if current_ledger.get("exchange_snapshot_sha256") != canonical_ledger_snapshot_sha256(decision_snapshot):
                self.controller._commit_ledger_reconciliation(
                    snapshot=decision_snapshot, trigger="qlib_offline_decision_observation"
                )
            self._assert_ledger(decision_snapshot)
        current_contracts = Decimal(str(self.venue.state["position"]))
        venue_contract = self._registered_venue_contract() if registered else {
            "contract_value_btc": "0.01", "lot_size_contracts": "0.01",
            "minimum_size_contracts": "0.01", "maximum_absolute_contracts": "0.01"}
        current_btc = float(current_contracts * Decimal(venue_contract["contract_value_btc"]))
        equity = float(self.venue.state["equity"])
        versions = CandidatePolicyVersions(POLICY_VERSION, self.config.policy_sha256, self.config.policy_sha256, self.config.policy_sha256)
        constitution = RiskConstitution(
            max_abs_position=equity / observation.mark_price,
            max_quantity=equity / observation.mark_price,
            max_notional=equity * 0.25,
            max_leverage=1.0,
            min_liquidation_buffer_bps=1000,
            max_daily_loss=equity * 0.03,
            max_drawdown=0.12,
            max_combined_loss=equity * 0.12,
            protection_required=True,
        )
        exit_state = self._policy_state()
        facts = CandidatePolicyFacts(
            decision_id=event_id,
            forecast=forecast,
            expected_source_signal_id=forecast.source_signal_id,
            risk_budget=BTCRiskBudget(
                max_btc_exposure=0.25, strategy_risk_budget=0.25,
                target_volatility=0.20,
                current_weight=current_btc * observation.mark_price / equity,
                min_cash_fraction=0.75, max_turnover=0.25,
                max_daily_loss_pct=0.03, max_drawdown_pct=0.12,
                max_abs_funding_rate=1.0, require_funding_rate=True,
            ),
            risk_state=BTCRiskState(
                cash_fraction=1.0 - abs(current_btc * observation.mark_price / equity),
                daily_loss_pct=0.0, current_drawdown_pct=0.0,
                funding_rate=observation.funding_rate,
                data_anomaly=bool(observation.blockers),
            ),
            account_equity=equity,
            mark_price=observation.mark_price,
            current_quantity=current_btc,
            reference_prices=lambda proposed: BTCReferencePriceState(
                observed_at_utc=decision_time,
                signal_price=observation.close_price,
                execution_price=observation.close_price * (1 + math.copysign(0.0006, float(proposed.target_quantity or 0) - current_btc)),
                mark_price=observation.mark_price,
                index_price=observation.index_price,
                current_mark_price=observation.mark_price,
                primary_mid=observation.close_price,
                spread_bps=2.0, data_age_ms=0, source="v3_fixture_visible_observation",
            ),
            constitution=constitution,
            combined_loss=CombinedLossAssessment(0.0, 0.0, 0.0, (), 0.0, 0.0, observation.funding_cashflow_usdt, 0.0, 0.0, 0.0),
            protection_before=None if not current_btc else {"present": True, "quantity": abs(current_btc), "side": "sell" if current_btc > 0 else "buy", "trigger_price": observation.mark_price * (0.96 if current_btc > 0 else 1.04)},
            protection_after=lambda quantity: None if abs(quantity) < 1e-12 else {"present": True, "quantity": abs(quantity), "side": "sell" if quantity > 0 else "buy", "trigger_price": observation.mark_price * (0.96 if quantity > 0 else 1.04)},
            cost_estimate=BTCExecutionCostEstimate(fee_bps=10.0, spread_bps=2.0, slippage_bps=6.0, impact_bps=4.0, funding_bps=abs(observation.funding_rate) * 20_000, source="v3_fixture_frozen_cost"),
            min_quantity=0.00001,
            blockers=observation.blockers,
            exit_state=exit_state,
            exit_observation=CandidateExitObservation(observation.close_price, forecast.expected_return_bps / 10_000.0, True, observation.end_of_window),
            exit_policy=CandidateExitPolicy(0.04, 0.06, 72),
            versions=versions,
        )
        if verified_facts is not None:
            actual_quantity = float(Decimal(str(self.venue.state["position"])) * Decimal("0.01"))
            if not (
                math.isclose(verified_facts.current_quantity, actual_quantity, abs_tol=1e-12)
                and math.isclose(verified_facts.account_equity, equity, abs_tol=1e-8)
                and math.isclose(verified_facts.mark_price, observation.mark_price, abs_tol=1e-8)
            ):
                raise QlibOfflineReplayError("qlib_sealed_account_facts_mismatch")
            facts = verified_facts
        if registered:
            facts = self.build_registered_candidate_facts(facts, observation)
        recovered_policy = self._recover_bound_policy(event_id=event_id, input_binding=input_binding)
        if recovered_policy is not None:
            policy, conversion, execution_blockers, policy_binding = recovered_policy
            if policy_binding.get("exit_state_before") != exit_state.__dict__:
                raise QlibOfflineReplayError("qlib_offline_policy_resume_exit_state_mismatch")
        else:
            step = evaluate_candidate_step(facts, venue=venue_contract)
            policy = step.policy
            conversion = step.conversion
            execution_blockers = step.execution_blockers
            resume_core = {
                "schema_version": "qlib_policy_resume_v1",
                "target": self._object_payload(policy.target),
                "approved": policy.approved,
                "policy_reasons": list(policy.reasons),
                "exit_reasons": list(policy.exit_reasons),
                "exit_state": policy.exit_state.__dict__,
                "conversion": None if conversion is None else conversion.__dict__,
                "execution_blockers": list(execution_blockers),
                "position_contracts": str(current_contracts),
            }
            policy_binding = {
                **input_binding,
                "event_id": event_id,
                "offline_observation_slot": observation_slot,
                "candidate_target_sha256": _canonical_sha256(self._object_payload(policy.target)),
                "candidate_target_position_id": policy.target.target_position_id,
                "conversion": None if conversion is None else conversion.__dict__,
                "policy_reasons": list(policy.reasons),
                "exit_reasons": list(policy.exit_reasons),
                "execution_blockers": list(execution_blockers),
                "exit_state_before": exit_state.__dict__,
                "exit_state_after": policy.exit_state.__dict__,
            }
            if registered:
                policy_binding["registered_account_facts"] = {
                    "account_binding_digest":self.registered_inputs.row["binding_digest"],
                    "account_risk_facts":dict(self.controller._state["account_risk_facts"]),
                    "ledger_replay":dict(self.controller._state["ledger_reconciliation"]["account_ledger_replay"]),
                    "risk_state":facts.risk_state.__dict__,"risk_budget":facts.risk_budget.__dict__,
                    "policy_versions":facts.versions.to_dict()}
                if self.registered_inputs.manifest.get("schema_version") == "registered_offline_market_v2":
                    policy_binding["resume_policy"] = {
                        **resume_core, "sha256": _canonical_digest(resume_core)}
            state_before = self.controller._durable_state_snapshot()
            self.controller._runtime_store.append(
                event_type="qlib_policy_step_bound", payload=policy_binding,
                state_after=state_before,
                idempotency_key="qlib-policy:" + event_id,
                timestamp_utc=self._now.isoformat(), run_id=self.config.run_id,
                safety=dict(state_before["safety"]),
            )
        if sealed and policy.approved and (
            observation.delayed_open_price is None or not observation.maintenance_facts
        ):
            result = {
                "event_id": event_id, "phase": phase,
                "decision_outcome": "execution_blocked_missing_offline_facts",
                "position_contracts": str(self.venue.state["position"]),
                "submit_count": int(self.venue.state["submit_count"]),
                "fill_count": len(self.venue.state["fills"]),
                "forecast_id": forecast.forecast_id,
                "candidate_target_position_id": policy.target.target_position_id,
                "candidate_target_quantity_btc": policy.target.target_quantity,
                "execution_blockers": ["sealed_intrahour_market_or_next_open_missing"],
                "truth_kind": self.config.truth_kind,
                "permissions": {name: False for name in sorted(_FALSE_PERMISSIONS)},
            }
            self._persist_policy_state(policy.exit_state)
            self._append_decision_evidence(event_id=event_id, binding=policy_binding, result=result)
            return result
        if not policy.approved or conversion is None:
            result = {
                "event_id": event_id, "phase": phase,
                "decision_outcome": "policy_rejected_no_order",
                "position_contracts": str(self.venue.state["position"]),
                "submit_count": int(self.venue.state["submit_count"]),
                "fill_count": len(self.venue.state["fills"]),
                "forecast_id": forecast.forecast_id,
                "candidate_target_position_id": policy.target.target_position_id,
                "candidate_target_quantity_btc": policy.target.target_quantity,
                "policy_reasons": list(policy.reasons),
                "execution_blockers": list(execution_blockers),
                "truth_kind": self.config.truth_kind,
                "permissions": {name: False for name in sorted(_FALSE_PERMISSIONS)},
            }
            self._persist_policy_state(policy.exit_state)
            self._append_decision_evidence(event_id=event_id, binding=policy_binding, result=result)
            return result

        fill_time = observation.event_time_utc + timedelta(hours=2)
        if observation.delayed_open_price is None:
            raise QlibOfflineReplayError("qlib_offline_next_open_missing")
        desired = Decimal(conversion.contracts_text)
        direction_delta = desired - current_contracts
        fill_price = Decimal(str(observation.delayed_open_price)) * (Decimal("1.0006") if direction_delta > 0 else Decimal("0.9994"))
        self._advance_offline_time(
            target_utc=fill_time, facts=observation.maintenance_facts,
            settlements=self._registered_funding_schedule(),
        )
        execution_mark, execution_index = self._market_after_registered_advance(
            at=self._now, observation=observation,
            fallback_mark=observation.delayed_open_price,
            fallback_index=observation.index_price,
            require_current_fact=(registered
                and self.registered_inputs.manifest.get("schema_version")
                    == "registered_offline_market_v2"),
        )
        self._registered_protection_guard(
            self._now, execution_mark, execution_index
        )
        self.venue.set_market(
            now=self._now, mark_price=execution_mark,
            index_price=execution_index, fill_price=fill_price,
        )
        snapshot = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(snapshot)
        self.controller._commit_ledger_reconciliation(snapshot=snapshot, trigger="qlib_fixture_pre_execution")
        self._assert_ledger(snapshot)
        plan = self.controller._build_order_plan(snapshot, current_quantity=current_contracts, target_quantity=desired)
        if plan is None:
            result = {
                "event_id": event_id, "phase": phase, "decision_outcome": "hold_no_order",
                "position_contracts": str(self.venue.state["position"]), "submit_count": int(self.venue.state["submit_count"]),
                "fill_count": len(self.venue.state["fills"]), "forecast_id": forecast.forecast_id,
                "candidate_target_position_id": policy.target.target_position_id,
                "candidate_target_quantity_btc": policy.target.target_quantity,
                "truth_kind": self.config.truth_kind,
                "permissions": {name: False for name in sorted(_FALSE_PERMISSIONS)},
            }
            self._persist_policy_state(policy.exit_state)
            self._append_decision_evidence(event_id=event_id, binding=policy_binding, result=result)
            return result
        direction = forecast.direction
        signal = Signal(timestamp_utc=forecast.timestamp_utc, strategy_id=forecast.strategy_id, symbol=forecast.symbol, direction=direction, strength=forecast.score, horizon=forecast.horizon, reason="v3_forecast_through_frozen_policy", metadata={"source_kind": "forecast", "forecast_id": forecast.forecast_id}, signal_id=forecast.source_signal_id)
        execution_target = TargetPosition(
            timestamp_utc=forecast.timestamp_utc, strategy_id=forecast.strategy_id,
            symbol=forecast.symbol,
            target_weight=float(Decimal(str(plan["position_after_contracts"])) / Decimal("0.01")),
            target_quantity=float(Decimal(str(plan["position_after_contracts"]))),
            signal_id=forecast.source_signal_id,
            target_position_id=policy.target.target_position_id + ":okx-contracts:" + phase,
            metadata={**policy.target.metadata, "source_forecast_id": forecast.forecast_id,
                "candidate_target_position_id": policy.target.target_position_id,
                "candidate_target_quantity_btc": conversion.btc_quantity_text,
                "execution_target_quantity_contracts": plan["position_after_contracts"],
                "quantity_conversion": conversion.__dict__, "fixture_only": not sealed,
                "order_generation_allowed": plan.get("risk_reducing_only") is not True},
        )
        intent = OrderIntent(
            timestamp_utc=self._now, strategy_id=forecast.strategy_id, symbol=forecast.symbol,
            side=OrderSide.BUY if plan["side"] == "buy" else OrderSide.SELL,
            quantity=float(Decimal(str(plan["contracts"]))), order_type=OrderType.LIMIT,
            limit_price=float(Decimal(str(plan["limit_price"]))),
            time_in_force=TimeInForce.IOC if plan.get("risk_reducing_only") is True or plan.get("entry_order_type") == "ioc" else TimeInForce.FOK,
            run_id=self.config.run_id, signal_id=forecast.source_signal_id,
            target_position_id=execution_target.target_position_id,
            client_order_id=str(plan["client_order_id"]),
            metadata={"source_kind": "forecast", "source_forecast_id": forecast.forecast_id,
                "candidate_target_position_id": policy.target.target_position_id,
                "position_side": plan["position_side"], "action": plan["action"], "fixture_only": not sealed},
        )
        binding = {
            **policy_binding, "run_id": self.config.run_id,
            "model_sha256": self.config.model_sha256, "policy_sha256": self.config.policy_sha256,
            "data_version": self.config.data_version, "code_version": self.source_head,
            "signal_sha256": _canonical_sha256(self._object_payload(signal)),
            "candidate_target_sha256": _canonical_sha256(self._object_payload(policy.target)),
            "execution_target_sha256": _canonical_sha256(self._object_payload(execution_target)),
            "forecast_sha256": _canonical_sha256(self._object_payload(forecast)),
            "intent_sha256": _canonical_sha256(self._object_payload(intent)),
        }
        self.controller._submit_order_plan(
            self.venue, snapshot=snapshot,
            decision={"strategy_id": forecast.strategy_id, "direction": direction.value, "raw_signal": forecast.score},
            order_plan=plan,
            sealed_strategy_objects={"signal": signal, "forecast": forecast,
                "candidate_target": policy.target, "execution_target": execution_target,
                "intent": intent, "binding": binding},
        )
        post = self.controller._collect_exchange_snapshot(self.venue)
        self.controller._apply_snapshot(post)
        self._assert_ledger(post)
        self._cleanup_flat_protection()
        self._persist_policy_state(policy.exit_state)
        result = self._recover_result(event_id=event_id, phase=phase)
        if result is None:
            raise QlibOfflineReplayError("qlib_offline_terminal_ledger_link_missing")
        self._append_decision_evidence(event_id=event_id, binding=binding, result=result)
        return result

    def _record_clean_stop(self) -> None:
        state = self.controller._state
        pending = state.get("risk_control", {}).get("pending_order_intents", {})
        unresolved = any(
            isinstance(row, Mapping)
            and str(row.get("status") or "") in {"submit_pending", "unknown", "accepted", "reconciled_open"}
            for row in pending.values()
        )
        healthy = (
            state.get("runtime", {}).get("active") is True
            and state.get("runtime", {}).get("opening_allowed") is True
            and state.get("risk_control", {}).get("mode") == "RUNNING"
            and state.get("risk_control", {}).get("write_path_trusted") is True
            and state.get("private_ws", {}).get("connected") is True
            and state.get("private_ws", {}).get("listener_alive") is True
            and not unresolved
            and self.guardian_supervisor.tripped is False
            and not self.guardian_supervisor.persistence_error
        )
        if healthy:
            state["runtime"].update({"active": False, "opening_allowed": False, "cancel_only": False, "status": "offline_clean_stopped"})
            state["risk_control"].update({"mode": "FROZEN_UNKNOWN", "write_path_trusted": False})
            state["private_ws"].update({"status": "disconnected", "connected": False, "listener_alive": False, "opening_allowed_after_reconciliation": False})
            state_after = self.controller._durable_state_snapshot()
            self.controller._runtime_store.append(
                event_type="qlib_offline_clean_stopped",
                payload={"identity_digest": self.identity["identity_digest"], "offline_execution_only": True},
                state_after=state_after,
                idempotency_key="qlib-offline-clean-stop:" + self.identity["identity_digest"] + ":" + str(state["runtime"].get("last_processed_bar_close_utc") or len(self.venue.state.get("fills", []))),
                timestamp_utc=self._now.isoformat(), run_id=self.config.run_id,
                safety=dict(state_after["safety"]),
            )
        self.controller._persist_state()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._record_clean_stop()
        except BaseException:
            self._release_authorities(suppress_errors=True)
            raise
        self._release_authorities()

    def abort(self) -> None:
        """Release offline writer authorities without recording a clean stop."""
        if self._closed:
            return
        self._closed = True
        self._release_authorities(suppress_errors=True)

    def _release_authorities(self, *, suppress_errors: bool = False) -> None:
        failure: BaseException | None = None
        callbacks = [self.guardian_supervisor.close]
        controller = getattr(self, "controller", None)
        if controller is not None:
            callbacks.append(controller._runtime_store.close)
        for callback in callbacks:
            try:
                callback()
            except BaseException as exc:
                if failure is None:
                    failure = exc
        if failure is not None and not suppress_errors:
            raise failure

    def __enter__(self) -> "QlibFixtureOfflineReplay":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ContractConversion",
    "CandidateMarketObservation",
    "CandidateStepDecision",
    "QlibFixtureOfflineReplay",
    "QlibFixtureReplayConfig",
    "QlibOfflineReplayError",
    "btc_quantity_to_okx_contracts",
    "evaluate_frozen_candidate",
    "evaluate_candidate_step",
    "load_v3_contract",
]


def _offline_cli() -> int:
    parser = argparse.ArgumentParser(description="Fixed V3 Qlib offline read-only replay")
    parser.add_argument("--state-dir", type=Path, required=True, help="isolated directory outside this Git checkout")
    parser.add_argument("--shared-root", type=Path, help="existing immutable public-data root")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    contract = load_v3_contract(
        root / "tests/fixtures/strategy_v3/offline_contract.json", repo_root=root,
    )
    result = evaluate_frozen_candidate(
        contract, repo_root=root, state_dir=args.state_dir,
        shared_root=args.shared_root,
    )
    print(json.dumps({
        "usage": result["usage"],
        "decision_count": result["decision_count"],
        "approved_decision_count": result["approved_decision_count"],
        "simulated_fill_count": result["simulated_fill_count"],
        "runtime_policy_event_count": result["runtime_policy_event_count"],
        "runtime_physical_batch_event_count": result["runtime_physical_batch_event_count"],
        "policy_evidence_path": result["policy_evidence_path"],
        "policy_evidence_sha256": result["policy_evidence_sha256"],
        "runtime_state_dir": result["runtime_state_dir"],
        "permissions": result["permissions"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_offline_cli())

