"""Asset-neutral, JSON-only delivery contracts. No broker or filesystem imports."""
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

SCHEMA = "strategy_delivery_package_v2"
VALIDATOR = "strategy_delivery_validator_v2"
FALSE_PERMISSIONS = ("demo_control_enabled", "execution_permission", "runtime_observed", "promotion",
                     "paper", "live", "private", "order", "real_order", "transfer", "withdraw")
CONTRACTS = ("features", "preprocessing", "output", "calibration", "position", "exit", "cost", "time", "state")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
HEAD = re.compile(r"^[0-9a-f]{40}$")
CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{1,15}$")


class DeliveryError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def permissions() -> dict:
    return dict.fromkeys(FALSE_PERMISSIONS, False)


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value) or value == "latest":
        raise DeliveryError("invalid_identifier", 422)
    return value


def source_ref(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"kind", "run_id", "candidate_id"}:
        raise DeliveryError("source_reference_fields_invalid", 422)
    if value["kind"] not in {"qlib", "factory", "registered_rule"}:
        raise DeliveryError("source_kind_unsupported", 422)
    return {key: identifier(value[key]) for key in ("kind", "run_id", "candidate_id")}


def utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None: raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise DeliveryError("timestamp_invalid", 422) from exc


def validate_package(package: dict, target: str) -> list[str]:
    blockers = []
    from .runtime_contract import PACKAGE_SCHEMA, validate_runtime_contract
    if package.get("schema_version") not in {SCHEMA, PACKAGE_SCHEMA}: blockers.append("package_schema_invalid")
    if package.get("schema_version") == PACKAGE_SCHEMA:
        blockers.extend(validate_runtime_contract(package))
    currency = package.get("settlement_currency")
    if not isinstance(currency, str) or not CURRENCY.fullmatch(currency):
        blockers.append("settlement_currency_invalid")
    try: source_ref(package.get("source"))
    except DeliveryError: blockers.append("source_reference_invalid")
    for key in ("strategy_id", "strategy_version", "market", "instrument", "bar_size", "data_version", "adapter_id"):
        if not isinstance(package.get(key), str) or not package[key].strip(): blockers.append("identity_missing:" + key)
    if not HEAD.fullmatch(str(package.get("source_head", ""))): blockers.append("source_head_invalid")
    if not HASH.fullmatch(str(package.get("params_hash", ""))): blockers.append("params_hash_invalid")
    artifacts = package.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts or any(
        not isinstance(k, str) or not HASH.fullmatch(str(v)) for k, v in artifacts.items()
    ): blockers.append("artifact_digests_invalid")
    contracts = package.get("contracts", {})
    if not isinstance(contracts, dict): contracts = {}
    for name in CONTRACTS:
        value = contracts.get(name)
        if not isinstance(value, dict) or not value.get("version"):
            blockers.append("contract_missing:" + name)
    output = contracts.get("output", {})
    if not isinstance(output, dict): output = {}
    if output.get("kind") not in {"direction_signal", "return_forecast", "target_position"}:
        blockers.append("output_kind_invalid")
    if output.get("unit") not in {"direction", "return_fraction", "bps", "contracts", "base_quantity", "equity_weight"}:
        blockers.append("output_unit_invalid")
    for name in ("horizon_bars", "valid_for_bars"):
        if type(output.get(name)) is not int or output[name] < 1: blockers.append("output_" + name + "_invalid")
    targets = package.get("supported_targets", [])
    if not isinstance(targets, list) or target not in targets: blockers.append("target_adapter_unsupported")
    if target not in {"offline", "okx_demo"}: blockers.append("target_not_supported")
    for flag in FALSE_PERMISSIONS:
        if flag in package and package[flag] is not False: blockers.append("package_permission_invalid")
    admission = package.get("admission_blockers", [])
    if not isinstance(admission, list) or any(not isinstance(v, str) for v in admission):
        blockers.append("admission_evidence_invalid")
    else: blockers.extend(admission)
    return sorted(set(blockers))


def validate_account(account: dict, package: dict, target: str, now: datetime) -> None:
    currency = package.get("settlement_currency")
    if (not isinstance(currency, str) or not CURRENCY.fullmatch(currency)
        or account.get("currency") != currency):
        raise DeliveryError("account_settlement_currency_mismatch")
    instruments = account.get("instruments", [])
    if (account.get("verified") is not True or account.get("environment") != target
        or account.get("market") != package["market"]
        or not isinstance(instruments, list) or not instruments
        or any(not isinstance(value, str) for value in instruments)
        or package["instrument"] not in instruments
        or not HASH.fullmatch(str(account.get("identity_hash", "")))
        or type(account.get("revision")) is not int or account["revision"] < 1
        or not account.get("evidence_ref") or not account.get("currency")):
        raise DeliveryError("account_binding_incompatible")
    if utc(account.get("expires_at", "")) <= now:
        raise DeliveryError("account_evidence_expired")
