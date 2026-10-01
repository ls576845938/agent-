from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping
import random

from quant_shared.core.time import ensure_utc
from quant_shared.replay import ReplayInput, validate_replay_input

from quant_crypto.adapters.shared_platform import build_btc_replay_input
from .artifact_schema import apply_btc_artifact_schema
from .audit_dag import stable_payload_hash


BTC_REPLAY_ENGINE_VERSION = "btc_replay_engine_v1"
REPLAY_OUTPUT_KEYS = ("signal", "forecast", "target", "risk_decision")


@dataclass(frozen=True)
class BTCReplayContext:
    fixed_clock_utc: datetime
    random_seed: int
    strategy_version: str
    params: dict[str, Any]
    data_snapshot: dict[str, Any]
    risk_config: dict[str, Any]
    current_position: dict[str, Any]
    historical_orders: list[dict[str, Any]] = field(default_factory=list)
    historical_fills: list[dict[str, Any]] = field(default_factory=list)
    live_data_accessed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixed_clock_utc", ensure_utc(self.fixed_clock_utc))
        if self.random_seed is None:
            raise ValueError("BTC replay requires fixed random_seed.")
        if not self.strategy_version:
            raise ValueError("BTC replay requires strategy_version.")

    def to_inputs(self) -> dict[str, Any]:
        return {
            "fixed_clock_utc": self.fixed_clock_utc.isoformat(),
            "random_seed": int(self.random_seed),
            "strategy_version": self.strategy_version,
            "params": dict(self.params),
            "data_snapshot": dict(self.data_snapshot),
            "risk_config": dict(self.risk_config),
            "current_position": dict(self.current_position),
            "historical_orders": list(self.historical_orders),
            "historical_fills": list(self.historical_fills),
            "live_data_accessed": bool(self.live_data_accessed),
        }

    def to_shared_replay_input(self) -> ReplayInput:
        return build_btc_replay_input(
            fixed_clock_utc=self.fixed_clock_utc,
            random_seed=self.random_seed,
            strategy_version=self.strategy_version,
            params=self.params,
            data_snapshot=self.data_snapshot,
            risk_config=self.risk_config,
            current_position=self.current_position,
            historical_orders=self.historical_orders,
            historical_fills=self.historical_fills,
        )


@dataclass(frozen=True)
class BTCReplayResult:
    status: str
    blockers: list[str]
    replayed_outputs: dict[str, Any]
    diffs: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "replay_engine_version": BTC_REPLAY_ENGINE_VERSION,
            "status": self.status,
            "blockers": list(self.blockers),
            "replayed_outputs": dict(self.replayed_outputs),
            "diffs": dict(self.diffs),
            "metadata": dict(self.metadata),
        }
        input_hashes = {
            "replayed_outputs": stable_payload_hash(payload["replayed_outputs"]),
            "diffs": stable_payload_hash(payload["diffs"]),
            "metadata": stable_payload_hash(payload["metadata"]),
        }
        fixed_clock = datetime.fromisoformat(str(self.metadata["fixed_clock_utc"]))
        return apply_btc_artifact_schema(
            payload,
            decision="replay_pass" if not self.blockers else "replay_blocked",
            generated_at_utc=fixed_clock,
            as_of_utc=fixed_clock,
            blockers=list(self.blockers),
            warnings=[],
            input_hashes=input_hashes,
        )


ReplayFn = Callable[[BTCReplayContext], Mapping[str, Any]]


def run_btc_replay(
    *,
    audit_dag_payload: Mapping[str, Any],
    context: BTCReplayContext,
    replay_fn: ReplayFn,
    original_outputs: Mapping[str, Any],
) -> BTCReplayResult:
    blockers: list[str] = []
    shared_replay_input = context.to_shared_replay_input()
    blockers.extend(f"btc_shared_replay:{value}" for value in validate_replay_input(shared_replay_input))
    if context.live_data_accessed:
        blockers.append("btc_replay_live_data_accessed")
    if not audit_dag_payload or audit_dag_payload.get("status") != "complete":
        blockers.append("btc_replay_audit_dag_not_complete")
    random.seed(context.random_seed)
    replayed = dict(replay_fn(context))
    missing_outputs = [key for key in REPLAY_OUTPUT_KEYS if key not in replayed]
    for key in missing_outputs:
        blockers.append(f"btc_replay_output_missing:{key}")
    diffs = diff_replay_outputs(original_outputs, replayed, keys=REPLAY_OUTPUT_KEYS)
    if any(item["changed"] for item in diffs.values()):
        blockers.append("btc_replay_diff_detected")
    metadata = {
        "fixed_clock_utc": context.fixed_clock_utc.isoformat(),
        "fixed_random_seed": int(context.random_seed),
        "current_realtime_data_accessed": bool(context.live_data_accessed),
        "strategy_version": context.strategy_version,
        "params_hash": stable_payload_hash(context.params),
        "data_snapshot_hash": stable_payload_hash(context.data_snapshot),
        "risk_config_hash": stable_payload_hash(context.risk_config),
        "audit_dag_hash": str(audit_dag_payload.get("artifact_hash", "")),
        "replay_failure_severity": "serious_auditability_issue",
        "required_outputs": list(REPLAY_OUTPUT_KEYS),
        "shared_replay_contract_version": shared_replay_input.contract_version,
        "shared_replay_id": shared_replay_input.replay_id,
        "shared_replay_source_mode": shared_replay_input.source_mode,
        "shared_replay_snapshot_count": len(shared_replay_input.snapshots),
        "shared_replay_event_count": len(shared_replay_input.events),
    }
    status = "replay_pass" if not blockers else "replay_blocked"
    return BTCReplayResult(
        status=status,
        blockers=_dedupe(blockers),
        replayed_outputs=replayed,
        diffs=diffs,
        metadata=metadata,
    )


def diff_replay_outputs(
    original_outputs: Mapping[str, Any],
    replayed_outputs: Mapping[str, Any],
    *,
    keys: tuple[str, ...] = REPLAY_OUTPUT_KEYS,
) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key in keys:
        original_value = original_outputs.get(key)
        replayed_value = replayed_outputs.get(key)
        original_hash = stable_payload_hash(_wrap(original_value))
        replayed_hash = stable_payload_hash(_wrap(replayed_value))
        diff[key] = {
            "changed": original_hash != replayed_hash,
            "original_hash": original_hash,
            "replayed_hash": replayed_hash,
            "original": original_value,
            "replayed": replayed_value,
        }
    return diff


def _wrap(value: Any) -> dict[str, Any]:
    return {"value": value}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
