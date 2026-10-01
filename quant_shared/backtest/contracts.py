from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.time import ensure_utc
from quant_shared.replay import ReplayEvent


@dataclass(frozen=True)
class BacktestIdentity:
    run_id: str
    strategy_version: str
    data_version: str
    params_hash: str
    code_commit: str
    contract_version: str = "shared_backtest_identity_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", validate_id(self.run_id, field_name="run_id"))
        for field_name in ("strategy_version", "data_version", "params_hash", "code_commit"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        validate_contract_version(self.contract_version, "shared_backtest_identity_v2")


@dataclass(frozen=True)
class BacktestRunInput:
    identity: BacktestIdentity
    fixed_clock_utc: datetime
    events: Sequence[ReplayEvent]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_backtest_run_input_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixed_clock_utc", ensure_utc(self.fixed_clock_utc))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "parameters", dict(self.parameters))
        validate_contract_version(self.contract_version, "shared_backtest_run_input_v2")


@dataclass(frozen=True)
class BacktestEvidence:
    cost_model: str
    slippage_model: str
    decision_time_rule: str
    execution_time_rule: str
    candidate_count: int
    trial_count: int
    walk_forward_valid: bool
    no_lookahead_valid: bool
    ledger_reconciled: bool
    pnl_source: str
    ledger_hash: str
    replay_hash: str
    current_head_match: bool
    blockers: tuple[str, ...] = ()
    contract_version: str = "shared_backtest_evidence_v2"

    def __post_init__(self) -> None:
        for field_name in ("cost_model", "slippage_model", "decision_time_rule", "execution_time_rule"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        for field_name in ("candidate_count", "trial_count"):
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        for field_name in ("ledger_hash", "replay_hash"):
            value = str(getattr(self, field_name))
            if len(value) != 64:
                raise ValueError(f"{field_name} must be sha256")
        object.__setattr__(self, "blockers", tuple(str(value) for value in self.blockers))
        validate_contract_version(self.contract_version, "shared_backtest_evidence_v2")


@dataclass(frozen=True)
class BacktestRunResult:
    identity: BacktestIdentity
    metrics: Mapping[str, Any]
    ledger_record_hashes: Sequence[str]
    evidence: BacktestEvidence
    contract_version: str = "shared_backtest_run_result_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", dict(self.metrics))
        hashes = tuple(str(value) for value in self.ledger_record_hashes)
        if any(len(value) != 64 for value in hashes):
            raise ValueError("ledger record hashes must be sha256")
        object.__setattr__(self, "ledger_record_hashes", hashes)
        validate_contract_version(self.contract_version, "shared_backtest_run_result_v2")


class BacktestEngine(Protocol):
    def run(self, run_input: BacktestRunInput) -> BacktestRunResult: ...


def validate_backtest_evidence(evidence: BacktestEvidence) -> tuple[str, ...]:
    blockers = list(evidence.blockers)
    if not evidence.walk_forward_valid:
        blockers.append("walk_forward_not_valid")
    if not evidence.no_lookahead_valid:
        blockers.append("no_lookahead_not_valid")
    if not evidence.ledger_reconciled:
        blockers.append("ledger_not_reconciled")
    if evidence.pnl_source != "ledger_derived":
        blockers.append("pnl_not_ledger_derived")
    if not evidence.current_head_match:
        blockers.append("current_head_mismatch")
    return tuple(dict.fromkeys(blockers))
