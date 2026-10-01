from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.time import ensure_utc


@dataclass(frozen=True)
class ReplaySnapshot:
    snapshot_id: str
    as_of_utc: datetime
    data_version: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_replay_snapshot_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", validate_id(self.snapshot_id, field_name="snapshot_id"))
        object.__setattr__(self, "as_of_utc", ensure_utc(self.as_of_utc))
        if not str(self.data_version).strip():
            raise ValueError("data_version is required")
        object.__setattr__(self, "payload", dict(self.payload))
        validate_contract_version(self.contract_version, "shared_replay_snapshot_v2")


@dataclass(frozen=True)
class ReplayEvent:
    event_id: str
    occurred_at_utc: datetime
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_replay_event_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", validate_id(self.event_id, field_name="event_id"))
        object.__setattr__(self, "occurred_at_utc", ensure_utc(self.occurred_at_utc))
        if not str(self.event_type).strip():
            raise ValueError("event_type is required")
        object.__setattr__(self, "payload", dict(self.payload))
        validate_contract_version(self.contract_version, "shared_replay_event_v2")


@dataclass(frozen=True)
class ReplayInput:
    replay_id: str
    fixed_clock_utc: datetime
    random_seed: int
    snapshots: Sequence[ReplaySnapshot]
    events: Sequence[ReplayEvent]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    source_mode: str = "injected_history"
    contract_version: str = "shared_replay_input_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "replay_id", validate_id(self.replay_id, field_name="replay_id"))
        object.__setattr__(self, "fixed_clock_utc", ensure_utc(self.fixed_clock_utc))
        object.__setattr__(self, "random_seed", int(self.random_seed))
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "parameters", dict(self.parameters))
        if self.source_mode != "injected_history":
            raise ValueError("replay source_mode must be injected_history")
        validate_contract_version(self.contract_version, "shared_replay_input_v2")


@dataclass(frozen=True)
class ReplayResult:
    replay_id: str
    status: str
    output_hash: str
    blockers: tuple[str, ...] = ()
    differences: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_replay_result_v2"

    def __post_init__(self) -> None:
        validate_id(self.replay_id, field_name="replay_id")
        if self.status not in {"pass", "blocked", "failed"}:
            raise ValueError("unsupported replay status")
        if len(self.output_hash) != 64:
            raise ValueError("output_hash must be sha256")
        object.__setattr__(self, "blockers", tuple(str(value) for value in self.blockers))
        object.__setattr__(self, "differences", dict(self.differences))
        if self.status == "pass" and self.blockers:
            raise ValueError("passing replay result cannot contain blockers")
        validate_contract_version(self.contract_version, "shared_replay_result_v2")


class ReplayEngine(Protocol):
    def replay(self, replay_input: ReplayInput) -> ReplayResult: ...


def validate_replay_input(replay_input: ReplayInput) -> tuple[str, ...]:
    blockers: list[str] = []
    for snapshot in replay_input.snapshots:
        if snapshot.as_of_utc > replay_input.fixed_clock_utc:
            blockers.append(f"snapshot_after_fixed_clock:{snapshot.snapshot_id}")
    for event in replay_input.events:
        if event.occurred_at_utc > replay_input.fixed_clock_utc:
            blockers.append(f"event_after_fixed_clock:{event.event_id}")
    if tuple(sorted(replay_input.events, key=lambda value: (value.occurred_at_utc, value.event_id))) != tuple(
        replay_input.events
    ):
        blockers.append("events_not_deterministically_ordered")
    return tuple(blockers)
