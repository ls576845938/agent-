from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from quant_crypto.application.donchian_history_spec import HistorySpec
from quant_crypto.application.donchian_historical_replay import (
    build_market_policy_replay_plan,
)
from quant_crypto.application.donchian_historical_venue import (
    HistoricalBar,
    HistoricalOfflineVenue,
)
from quant_crypto.application import donchian_historical_replay as history_module
from quant_crypto.application import donchian_offline_replay as offline_module
from quant_crypto.application.donchian_offline_replay import (
    DonchianOfflineReplay,
    DonchianOfflineReplayConfig,
    build_trend_frame,
)
from quant_shared.strategy_delivery.market_policy_attachment import (
    MarketPolicyBaseBinding,
    build_market_policy_attachment,
)
from quant_shared.trend_environment.entry_policy import EntryOnlyPolicyV1
from quant_shared.trend_environment.model import digest
from quant_shared.trend_environment.state_v2 import (
    MarketStateV2,
    StateDefinitionV2,
    StateSourceBinding,
)


ANNUAL_SPEC = (
    "25c00b0c7004d4b02afb419f2fddaa90b1cab26c:"
    "docs/research/donchian-long-50usdt-20260921.json"
)
PROTOCOL_REF = (
    "97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02:"
    "docs/research/market-state-conditional-policy-protocol-20260927.json"
)
EVIDENCE_REF = "d" * 40 + ":.agent/market_state_evidence/fixture.json"


def _state(
    cutoff: datetime,
    *,
    definition: StateDefinitionV2,
    source: StateSourceBinding,
    efficiency: float,
) -> MarketStateV2:
    content = digest(
        {
            "cutoff": cutoff.isoformat(),
            "definition": definition.definition_hash,
            "source": source.binding_hash,
            "efficiency": efficiency,
        }
    )
    return MarketStateV2(
        asset="BTC-USDT-SWAP",
        decision_time=cutoff,
        cutoff_time=cutoff,
        status="observed",
        reasons=(),
        direction_score=efficiency,
        direction_label="up",
        normalized_trend_strength=efficiency,
        path_efficiency_by_horizon={"24": efficiency, "72": efficiency, "168": efficiency},
        multi_scale_agreement=1.0,
        bar_volatility=0.01,
        annualized_volatility=0.1,
        volatility_relative_position=0.5,
        volatility_expansion_ratio=1.0,
        volatility_regime="stable",
        shock_score=0.0,
        direction_persistence=1.0,
        switching_frequency=0.0,
        optional_inputs={},
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        source_binding_hash=source.binding_hash,
        input_hash=content,
        cache_key=content,
        content_hash=content,
    )


def _binding(enabled: bool):
    evidence_sha = "e" * 64
    definition = StateDefinitionV2()
    source = StateSourceBinding(
        data_version="market-policy-fixture-v1",
        manifest_git_spec="a" * 40 + ":.agent/data_manifests/fixture.json",
        manifest_sha256="b" * 64,
        aggregate_sha256="c" * 64,
        source_evidence_hash=evidence_sha,
    )
    policy = EntryOnlyPolicyV1(
        state_definition_hash=definition.definition_hash,
        source_binding_hash=source.binding_hash,
        source_evidence_hash=evidence_sha,
        enabled=enabled,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path.cwd(), text=True
    ).strip()
    base = MarketPolicyBaseBinding(
        strategy_id="long_short_donchian_top5_okx_native",
        strategy_version="btc_long_short_donchian_top5_okx_native@1.0.0",
        source_head=head,
        params_hash="1" * 64,
        data_version=source.data_version,
        instrument="BTC-USDT-SWAP",
        bar_size="1h",
        settlement_currency="USDT",
        base_package_hash="2" * 64,
        base_spec_hash="3" * 64,
        cost_contract_hash="4" * 64,
        time_contract_hash="5" * 64,
    )
    attachment = build_market_policy_attachment(
        base=base,
        definition=definition,
        policy=policy,
        source=source,
        evidence_ref=EVIDENCE_REF,
        evidence_sha256=evidence_sha,
    )
    return definition, source, policy, attachment


def test_entry_policy_only_filters_flat_reopen_after_original_reversal_close(tmp_path):
    definition, source, policy, attachment = _binding(True)
    opening = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    holder = {"state": _state(opening, definition=definition, source=source, efficiency=0.8)}

    def venue_factory(path, now):
        venue = HistoricalOfflineVenue(path, now=now)
        if not venue.state["historical_events"]:
            venue.now = opening + timedelta(seconds=1)
            venue.advance(
                completed_bar=HistoricalBar(
                    event_time_utc=opening - timedelta(hours=1),
                    available_time_utc=opening,
                    open=Decimal("60000"),
                    high=Decimal("60001"),
                    low=Decimal("59999"),
                    close=Decimal("60000"),
                    mark_open=Decimal("60000"),
                    mark_high=Decimal("60001"),
                    mark_low=Decimal("59999"),
                    mark_close=Decimal("60000"),
                    index_close=Decimal("60000"),
                ),
                next_bar_open=Decimal("60000"),
            )
        return venue

    config = DonchianOfflineReplayConfig(
        repo_root=Path.cwd(),
        state_dir=tmp_path / "state",
        run_id="market-entry-policy-fixture",
        decision_time_utc=opening,
        data_version=source.data_version,
        decision_time_provider=lambda event, ordinal, phase: event
        + timedelta(seconds=1, milliseconds=ordinal),
        venue_factory=venue_factory,
        market_entry_policy=policy,
        market_state_provider=lambda _frame: holder["state"],
        market_policy_attachment=attachment,
    )
    runner = DonchianOfflineReplay(config)
    try:
        runner.venue.now = opening + timedelta(seconds=1)
        opened = runner.run_frame(build_trend_frame("long", end=opening))
        assert opened["fill_count"] == 1
        assert runner.venue.state["position"] == "0.01"
        assert opened["event_id"]
        assert opened["evidence"]["links"]["decision_outcome"] == "order_terminal"
        assert opened["evidence"]["links"]["order_intent_id"]
        assert opened["evidence"]["links"]["fill_ids"]
        assert (
            opened["evidence"]["links"]["ledger_event_hash"]
            == opened["ledger"]["event_hash"]
        )

        reversal = opening + timedelta(hours=1)
        low = _state(reversal, definition=definition, source=source, efficiency=0.1)
        holder["state"] = low
        reverse_frame = build_trend_frame("short", end=reversal)
        runner.venue.now = reversal + timedelta(seconds=1)
        runner.venue.advance(
            completed_bar=HistoricalBar(
                event_time_utc=opening,
                available_time_utc=reversal,
                open=Decimal("60000"),
                high=Decimal("60001"),
                low=Decimal("59999"),
                close=Decimal("60000"),
                mark_open=Decimal("60000"),
                mark_high=Decimal("60001"),
                mark_low=Decimal("59999"),
                mark_close=Decimal("60000"),
                index_close=Decimal("60000"),
            ),
            next_bar_open=Decimal("60000"),
        )
        closed = runner.run_frame(reverse_frame)
        assert closed["phase"] == "reversal_close"
        assert Decimal(runner.venue.state["position"]) == 0
        assert closed["market_entry_policy"]["reason"] == (
            "existing_position_not_entry"
        )
        assert closed["event_id"] != opened["event_id"]
        assert closed["evidence"]["links"]["decision_outcome"] == "order_terminal"
        assert closed["evidence"]["links"]["order_intent_id"]
        assert closed["evidence"]["links"]["fill_ids"]
        assert (
            closed["evidence"]["links"]["ledger_event_hash"]
            == closed["ledger"]["event_hash"]
        )

        runner.close()
        runner = DonchianOfflineReplay(
            replace(config, decision_time_utc=reversal)
        )
        rejected = runner.run_frame(reverse_frame)
        assert rejected["fill_count"] == 2
        assert rejected["fills"] == []
        assert Decimal(runner.venue.state["position"]) == 0
        evidence = rejected["market_entry_policy"]
        assert evidence["reason"] == "path_efficiency_below_threshold"
        assert evidence["state_version"] == definition.definition_version
        assert evidence["state_definition_hash"] == definition.definition_hash
        assert evidence["state_source_binding_hash"] == source.binding_hash
        assert evidence["state_content_hash"] == low.content_hash
        assert evidence["policy_id"] == policy.policy_id
        assert evidence["policy_hash"] == policy.policy_hash
        assert evidence["original_target_contracts"] == "-0.01"
        assert evidence["effective_target_contracts"] == "0"
        assert rejected["event_id"]
        assert rejected["evidence"]["links"] == {
            "decision_outcome": "no_order",
            "decision_digest": rejected["evidence"]["links"]["decision_digest"],
            "raw_signal": "-1",
            "target_contracts": "0",
            "current_contracts": "0",
            "order_intent_id": None,
            "client_order_id": None,
            "exchange_order_id": None,
            "fill_ids": [],
            "ledger_event_id": None,
            "ledger_event_hash": None,
            "action": "hold",
        }
        assert rejected["ledger"] == {}
        assert rejected["safety"] == {
            "demo_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "runtime_observed": False,
            "network_accessed": False,
        }
        assert len(runner.venue.state["fills"]) == 2
        assert runner.run_frame(reverse_frame) == rejected
        assert len(runner.venue.state["fills"]) == 2
    finally:
        runner.close()


def _protocol_and_evidence(spec: HistorySpec):
    protocol_raw = Path(
        "docs/research/market-state-conditional-policy-protocol-20260927.json"
    ).read_bytes()
    protocol = json.loads(protocol_raw)
    definition_contract = protocol["state_definition"]
    definition = StateDefinitionV2(
        horizons=tuple(definition_contract["horizons"]),
        primary_horizon=definition_contract["primary_horizon"],
        volatility_history_bars=definition_contract["volatility_history_bars"],
        state_history_bars=definition_contract["state_history_bars"],
        minimum_history_observations=definition_contract[
            "minimum_history_observations"
        ],
        calendar=protocol["window"]["calendar"],
        periods_per_year=definition_contract["periods_per_year"],
        max_age_seconds=definition_contract["max_age_seconds"],
    )
    evidence = {
        "schema_version": "market_state_stage_diagnostic_v1",
        "status": "completed_exploratory_research_only",
        "protocol": {
            "path": PROTOCOL_REF.split(":", 1)[1],
            "commit": PROTOCOL_REF.split(":", 1)[0],
            "sha256": hashlib.sha256(protocol_raw).hexdigest(),
            "protocol_id": protocol["protocol_id"],
        },
        "source": {
            "manifest_git_spec": spec.payload["data"]["manifest_git_spec"],
            "manifest_sha256": spec.payload["data"]["manifest_sha256"],
            "aggregate_sha256": spec.payload["data"]["aggregate_sha256"],
            "data_version": spec.payload["data"]["dataset_version"],
        },
        "window": protocol["window"],
        "description": {
            "definition_version": definition.definition_version,
            "definition_hash": definition.definition_hash,
        },
        "policy_trial": {"status": "not_started", "effect_verified": False},
        "runtime_status": {
            "entry_policy_enabled": False,
            "attachment_consumed_by_btc_runtime": False,
            "execution_effect_observed": False,
        },
        **dict.fromkeys(
            (
                "demo_control_enabled",
                "execution_permission",
                "runtime_observed",
                "promotion",
                "paper",
                "live",
                "private",
                "order",
                "real_order",
                "transfer",
                "withdraw",
            ),
            False,
        ),
    }
    evidence["evidence_hash"] = digest(evidence)
    evidence_raw = json.dumps(
        evidence, sort_keys=True, separators=(",", ":")
    ).encode()
    return protocol_raw, evidence_raw


def test_plan_reconstructs_two_distinct_fixed_2960_arms(monkeypatch):
    spec = HistorySpec.from_git(Path.cwd(), ANNUAL_SPEC)
    protocol_raw, evidence_raw = _protocol_and_evidence(spec)

    def blob(_root, git_spec):
        if git_spec == PROTOCOL_REF:
            return protocol_raw
        if git_spec == EVIDENCE_REF:
            return evidence_raw
        raise AssertionError(git_spec)

    monkeypatch.setattr(history_module, "_read_git_blob", blob)
    common = dict(
        repo_root=Path.cwd(),
        spec=spec,
        source_head="f" * 40,
        protocol_git_spec=PROTOCOL_REF,
        evidence_git_spec=EVIDENCE_REF,
    )
    baseline = build_market_policy_replay_plan(**common, arm="baseline")
    conditioned = build_market_policy_replay_plan(**common, arm="conditioned")
    assert baseline.expected_analysis_bars == conditioned.expected_analysis_bars == 2960
    assert baseline.analysis_start == spec.start
    assert baseline.analysis_end < spec.end
    assert baseline.policy.enabled is False
    assert conditioned.policy.enabled is True
    assert baseline.attachment["attachment_hash"] != conditioned.attachment["attachment_hash"]
    assert baseline.attachment["base_strategy"]["source_head"] == "f" * 40
    assert baseline.attachment["safety"]["order"] is False


def test_plan_rejects_tampered_diagnostic_before_runtime(monkeypatch):
    spec = HistorySpec.from_git(Path.cwd(), ANNUAL_SPEC)
    protocol_raw, evidence_raw = _protocol_and_evidence(spec)
    evidence = json.loads(evidence_raw)
    evidence["runtime_status"]["entry_policy_enabled"] = True
    tampered = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    monkeypatch.setattr(
        history_module,
        "_read_git_blob",
        lambda _root, git_spec: protocol_raw if git_spec == PROTOCOL_REF else tampered,
    )
    with pytest.raises(ValueError, match="content_hash_mismatch"):
        build_market_policy_replay_plan(
            repo_root=Path.cwd(),
            spec=spec,
            source_head="f" * 40,
            protocol_git_spec=PROTOCOL_REF,
            evidence_git_spec=EVIDENCE_REF,
            arm="conditioned",
        )


def test_stale_market_state_is_rejected_before_economic_side_effect(tmp_path):
    definition, source, policy, attachment = _binding(True)
    opening = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    stale = _state(
        opening - timedelta(hours=1),
        definition=definition,
        source=source,
        efficiency=0.8,
    )
    runner = DonchianOfflineReplay(
        DonchianOfflineReplayConfig(
            repo_root=Path.cwd(),
            state_dir=tmp_path / "state",
            run_id="market-state-stale-fixture",
            decision_time_utc=opening,
            data_version=source.data_version,
            market_entry_policy=policy,
            market_state_provider=lambda _frame: stale,
            market_policy_attachment=attachment,
        )
    )
    try:
        runner.venue.now = opening + timedelta(seconds=1)
        with pytest.raises(Exception, match="offline_market_state_binding_mismatch"):
            runner.run_frame(build_trend_frame("long", end=opening))
        assert runner.venue.state["fills"] == []
        assert runner.venue.state["orders"] == []
    finally:
        runner.close()


def test_stale_market_state_cannot_block_existing_position_or_flat_noop():
    definition, source, policy, attachment = _binding(True)
    opening = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    stale = _state(
        opening - timedelta(hours=1),
        definition=definition,
        source=source,
        efficiency=0.1,
    )
    controller = object.__new__(offline_module._OfflineSignalMemoController)
    controller._offline_market_entry_policy = policy
    controller._offline_market_state_provider = lambda _frame: stale
    controller._offline_market_policy_attachment = attachment
    frame = build_trend_frame("long", end=opening)

    exit_result = controller._apply_offline_market_entry_policy(
        result={"target_contracts": "0"},
        frame=frame,
        client=SimpleNamespace(state={"position": "0.01"}),
    )
    assert exit_result["target_contracts"] == "0"
    assert exit_result["market_entry_policy"]["applied"] is False
    assert (
        exit_result["market_entry_policy"]["reason"]
        == "existing_position_not_entry"
    )
    assert (
        exit_result["market_entry_policy"]["state_binding_status"]
        == "mismatch_non_entry_passthrough"
    )

    noop_result = controller._apply_offline_market_entry_policy(
        result={"target_contracts": "0"},
        frame=frame,
        client=SimpleNamespace(state={"position": "0"}),
    )
    assert noop_result["target_contracts"] == "0"
    assert noop_result["market_entry_policy"]["applied"] is False
    assert noop_result["market_entry_policy"]["reason"] == "no_new_entry"
    assert (
        noop_result["market_entry_policy"]["state_binding_status"]
        == "mismatch_non_entry_passthrough"
    )

    controller._offline_market_state_provider = lambda _frame: None
    missing_result = controller._apply_offline_market_entry_policy(
        result={"target_contracts": "0"},
        frame=frame,
        client=SimpleNamespace(state={"position": "0.01"}),
    )
    assert missing_result["target_contracts"] == "0"
    assert missing_result["market_entry_policy"]["applied"] is False
    assert (
        missing_result["market_entry_policy"]["reason"]
        == "existing_position_not_entry"
    )
    assert missing_result["market_entry_policy"]["state_status"] == "unavailable"
    assert (
        missing_result["market_entry_policy"]["state_binding_status"]
        == "unavailable_non_entry_passthrough"
    )

    def unavailable(_frame):
        raise RuntimeError("sidecar_unavailable")

    controller._offline_market_state_provider = unavailable
    error_result = controller._apply_offline_market_entry_policy(
        result={"target_contracts": "0"},
        frame=frame,
        client=SimpleNamespace(state={"position": "0.01"}),
    )
    assert error_result["target_contracts"] == "0"
    assert error_result["market_entry_policy"]["applied"] is False
    assert (
        error_result["market_entry_policy"]["state_binding_status"]
        == "unavailable_non_entry_passthrough"
    )
    with pytest.raises(
        Exception, match="offline_market_state_invalid"
    ):
        controller._apply_offline_market_entry_policy(
            result={"target_contracts": "0.01"},
            frame=frame,
            client=SimpleNamespace(state={"position": "0"}),
        )


def test_disabled_policy_never_turns_sidecar_mismatch_into_hidden_entry_gate():
    definition, source, policy, attachment = _binding(False)
    opening = datetime(2026, 7, 23, 7, tzinfo=timezone.utc)
    stale = _state(
        opening - timedelta(hours=1),
        definition=definition,
        source=source,
        efficiency=0.1,
    )
    controller = object.__new__(offline_module._OfflineSignalMemoController)
    controller._offline_market_entry_policy = policy
    controller._offline_market_state_provider = lambda _frame: stale
    controller._offline_market_policy_attachment = attachment

    result = controller._apply_offline_market_entry_policy(
        result={"target_contracts": "0.01"},
        frame=build_trend_frame("long", end=opening),
        client=SimpleNamespace(state={"position": "0"}),
    )
    assert result["target_contracts"] == "0.01"
    assert result["market_entry_policy"]["applied"] is False
    assert result["market_entry_policy"]["reason"] == "policy_disabled"
    assert (
        result["market_entry_policy"]["state_binding_status"]
        == "mismatch_non_entry_passthrough"
    )
