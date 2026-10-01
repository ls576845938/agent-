from dataclasses import replace

import pytest

from quant_shared.strategy_delivery.market_policy_attachment import (
    MarketPolicyBaseBinding,
    build_market_policy_attachment,
    validate_market_policy_attachment,
)
from quant_shared.trend_environment.entry_policy import EntryOnlyPolicyV1
from quant_shared.trend_environment.state_v2 import StateDefinitionV2, StateSourceBinding


def source() -> StateSourceBinding:
    return StateSourceBinding("fixture-v1", "f" * 40 + ":.agent/data_manifests/fixture.json",
                              "1" * 64, "2" * 64, "3" * 64)


def definition() -> StateDefinitionV2:
    return StateDefinitionV2()


def policy(enabled=True) -> EntryOnlyPolicyV1:
    return EntryOnlyPolicyV1(
        enabled=enabled, state_definition_hash=definition().definition_hash,
        source_binding_hash=source().binding_hash, source_evidence_hash="4" * 64,
    )


def base() -> MarketPolicyBaseBinding:
    return MarketPolicyBaseBinding(
        strategy_id="long_short_donchian_top5_okx_native",
        strategy_version="btc_long_short_donchian_top5_okx_native@1.0.0",
        source_head="a" * 40, params_hash="b" * 64,
        data_version="fixture-v1", instrument="BTC-USDT-SWAP", bar_size="1h",
        settlement_currency="USDT", base_package_hash="c" * 64,
        base_spec_hash="d" * 64, cost_contract_hash="e" * 64,
        time_contract_hash="f" * 64,
    )


def attachment():
    return build_market_policy_attachment(
        base=base(), definition=definition(), policy=policy(), source=source(),
        evidence_ref="a" * 40 + ":.agent/market_state_evidence/fixture.json",
        evidence_sha256="4" * 64,
    )


def test_attachment_binds_complete_base_state_policy_data_cost_time_and_evidence():
    value = attachment()
    assert value["schema_version"] == "market_state_entry_policy_attachment_v1"
    assert value["base_strategy"]["base_package_hash"] == "c" * 64
    assert value["base_strategy"]["base_spec_hash"] == "d" * 64
    assert value["base_strategy"]["cost_contract_hash"] == "e" * 64
    assert value["base_strategy"]["time_contract_hash"] == "f" * 64
    assert value["market_state"]["definition_hash"] == definition().definition_hash
    assert value["entry_policy"]["policy_hash"] == policy().policy_hash
    assert value["source"]["binding_hash"] == source().binding_hash
    assert value["safety"] == {key: False for key in (
        "demo_control_enabled", "execution_permission", "runtime_observed", "promotion", "paper", "live",
        "private", "order", "real_order", "transfer", "withdraw")}
    assert validate_market_policy_attachment(value, base=base(), definition=definition(),
                                             policy=policy(), source=source()) == []


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "unknown_v9"),
    (("base_strategy", "base_spec_hash"), "0" * 64),
    (("base_strategy", "cost_contract_hash"), "0" * 64),
    (("base_strategy", "time_contract_hash"), "0" * 64),
    (("market_state", "definition_hash"), "0" * 64),
    (("entry_policy", "policy_hash"), "0" * 64),
    (("source", "binding_hash"), "0" * 64),
    (("evidence", "sha256"), "0" * 64),
    (("safety", "order"), True),
])
def test_unknown_version_or_any_binding_drift_is_rejected(path, value):
    candidate = attachment()
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert validate_market_policy_attachment(candidate, base=base(), definition=definition(),
                                             policy=policy(), source=source())


def test_old_package_without_attachment_remains_an_explicit_no_policy_path():
    assert validate_market_policy_attachment(None, base=base(), definition=definition(),
                                             policy=policy(enabled=False), source=source(),
                                             attachment_required=False) == []
    assert validate_market_policy_attachment(None, base=base(), definition=definition(),
                                             policy=policy(), source=source(),
                                             attachment_required=True) == ["market_policy_attachment_missing"]


@pytest.mark.parametrize("evidence_ref", [
    "commit:.agent/market_state_evidence/fixture.json",
    "latest:.agent/market_state_evidence/fixture.json",
    "a" * 40 + ":../fixture.json",
    "a" * 40 + ":docs/fixture.json",
])
def test_evidence_reference_must_be_immutable_and_scoped(evidence_ref):
    with pytest.raises(ValueError, match="market_policy_evidence_ref_invalid"):
        build_market_policy_attachment(
            base=base(), definition=definition(), policy=policy(), source=source(),
            evidence_ref=evidence_ref, evidence_sha256="4" * 64,
        )
