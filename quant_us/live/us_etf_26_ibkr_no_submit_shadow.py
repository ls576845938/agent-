"""Fail-closed QQQ 1D IBKR no-submit shadow evidence service.

The service deliberately has no Gateway client factory and never calls
``connect()``, OMS, submit, cancel, or global-cancel surfaces.  Its only broker
input is an explicitly injected, already-connected fake client wrapped by the
current-main :class:`IBKRBroker` read-only foundation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping

import jsonschema
import pandas as pd

from quant_us.core.types import AccountState, Position
from quant_us.execution.ibkr_broker import ALLOWED_IBKR_PAPER_PORTS, IBKRBroker
from quant_us.portfolio.allocation import AllocationConfig, PortfolioAllocator
from quant_us.portfolio.rebalance import RebalanceConfig
from quant_us.risk.pre_trade import PortfolioRiskPolicy, PreTradeRiskEngine
from quant_us.strategies.us_etf_26_complete_return import (
    FrozenEtf26CompleteReturnStrategy,
)
from tools.agent_governance.shared_data import (
    SharedDataError,
    resolve_manifest_payload,
    sha256_file,
    validate_manifest,
)


SCHEMA_VERSION = "us_etf_26_ibkr_no_submit_shadow_v2"
ARTIFACT_TYPE = "us_etf_26_ibkr_no_submit_shadow"
STATUS = "injected_fake_no_submit_shadow_validated"
DATASET_ID = "us-equity-public-forward-snapshot"
MANIFEST_PREFIX = f".agent/data_manifests/{DATASET_ID}/"
QQQ_FILE = "yahoo/QQQ_1D.csv"
YAHOO_LINEAGE_FILE = "yahoo/lineage.json"
FRED_FILE = "fred_macro_latest_vintage.csv"
FREEZE_CONFIG = "configs/strategies/us_etf_26_candidate_freeze_v1.json"
EXPECTED_CANDIDATE_ID = "us-etf26-complete-return-qqq-1d-v1"
EXPECTED_STRATEGY_VERSION = "us_etf_complete_return_fixed_signal_v1"
EXPECTED_YAHOO_GAP = "yahoo_survivorship_bias_and_current_adjustment_vintage"
EXPECTED_FRED_GAP = "fred_latest_vintage_non_pit_without_realtime_bounds"
EXPECTED_ADJUSTMENT_POLICY = (
    "provider_adjusted_close_with_raw_ohlcv_and_policy_recorded"
)
EXPECTED_PRICE_SEMANTICS = "provider_adjusted_ohlc_via_session_ratio"
DEFAULT_MAX_STALENESS = timedelta(days=4)
SHADOW_REBALANCE_CONFIG = RebalanceConfig(min_weight_change=1e-12)
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ShadowEvidenceError(RuntimeError):
    """A fail-closed no-submit shadow evidence failure."""


@dataclass(frozen=True)
class _OfflineInputs:
    code_head: str
    observed_at_utc: datetime
    manifest_path: str
    manifest_sha256: str
    manifest: dict[str, Any]
    qqq_sha256: str
    lineage_sha256: str
    lineage: dict[str, Any]
    bars: pd.DataFrame
    strategy: FrozenEtf26CompleteReturnStrategy
    strategy_identity: dict[str, Any]
    latest_decision_time_utc: datetime
    stale_seconds: float


def account_sha256(account_id: str) -> str:
    value = str(account_id)
    if not value:
        raise ShadowEvidenceError("ibkr_shadow_account_id_missing")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_no_submit_shadow(
    *,
    broker_factory: Callable[[], IBKRBroker],
    repo_root: Path,
    shared_data_root: Path,
    expected_account_hash: str,
    observed_at_utc: datetime | None = None,
    max_staleness: timedelta = DEFAULT_MAX_STALENESS,
    code_head_resolver: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """Build evidence from committed data and an injected fake read client.

    Every offline data, strategy, manifest, lineage, freshness, and hash check
    runs before ``broker_factory`` is invoked.  The returned order intents stop
    at the risk evidence boundary and are never sent to OMS or a broker write
    surface.
    """

    _validate_account_hash(expected_account_hash)
    offline = _prepare_offline_inputs(
        repo_root=repo_root,
        shared_data_root=shared_data_root,
        observed_at_utc=observed_at_utc,
        max_staleness=max_staleness,
        code_head_resolver=code_head_resolver,
    )

    broker = broker_factory()
    if not isinstance(broker, IBKRBroker):
        raise ShadowEvidenceError("ibkr_shadow_broker_factory_contract_invalid")
    readiness = broker.readiness_report()
    if (
        readiness.get("readonly") is not True
        or readiness.get("paper_only") is not True
        or readiness.get("submit_capable") is not False
        or readiness.get("cancel_capable") is not False
        or int(readiness.get("port", 0)) not in ALLOWED_IBKR_PAPER_PORTS
    ):
        raise ShadowEvidenceError("ibkr_shadow_foundation_not_strictly_read_only")
    if not broker.is_connected():
        raise ShadowEvidenceError("ibkr_shadow_injected_fake_not_connected")

    before = _write_counters(broker)
    if any(before.values()):
        raise ShadowEvidenceError("ibkr_shadow_write_counter_nonzero_before")

    account = broker.sync_account()
    positions = broker.sync_positions()
    open_orders = broker.sync_open_orders()
    fills = broker.sync_fills()
    actual_account_hash = account_sha256(account.account_id)
    if actual_account_hash != expected_account_hash:
        raise ShadowEvidenceError("ibkr_shadow_account_hash_mismatch")
    account = replace(
        account,
        account_id=expected_account_hash,
        positions=positions,
    )

    strategy_decision = offline.strategy.generate(offline.bars)[-1]
    decision = _replay_portfolio_chain(
        strategy_decision=strategy_decision,
        bars=offline.bars,
        account=account,
    )
    after = _write_counters(broker)
    deltas = {f"{name}_delta": after[name] - before[name] for name in before}
    if any(after.values()) or any(deltas.values()):
        raise ShadowEvidenceError("ibkr_shadow_write_counter_nonzero_after")

    manifest = offline.manifest
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": STATUS,
        "code_head": offline.code_head,
        "observed_at_utc": _iso(offline.observed_at_utc),
        "identity": offline.strategy_identity,
        "bindings": {
            "dataset_id": manifest["dataset_id"],
            "dataset_version": manifest["dataset_version"],
            "dataset_aggregate_sha256": manifest["aggregate_sha256"],
            "manifest_git_spec": f"{offline.code_head}:{offline.manifest_path}",
            "manifest_path": offline.manifest_path,
            "manifest_sha256": offline.manifest_sha256,
            "storage_relative_path": manifest["storage_relative_path"],
            "yahoo_file_path": QQQ_FILE,
            "yahoo_file_sha256": offline.qqq_sha256,
            "yahoo_lineage_path": YAHOO_LINEAGE_FILE,
            "yahoo_lineage_sha256": offline.lineage_sha256,
            "fred_file_path": FRED_FILE,
            "source_code_head": str(offline.lineage["source_commit"]),
            "adjustment_policy": EXPECTED_ADJUSTMENT_POLICY,
            "strategy_price_semantics": EXPECTED_PRICE_SEMANTICS,
            "account_hash": expected_account_hash,
        },
        "freshness": {
            "latest_decision_time_utc": _iso(offline.latest_decision_time_utc),
            "stale_seconds": offline.stale_seconds,
            "max_staleness_seconds": max_staleness.total_seconds(),
            "stale": False,
        },
        "data_limitations": list(manifest.get("known_gaps", [])),
        "foundation": {
            "adapter": readiness["adapter"],
            "endpoint_kind": readiness["endpoint_kind"],
            "port": readiness["port"],
            "connected_injected_fake": True,
            "auto_connect_called": False,
            "readonly": True,
            "submit_capable": False,
            "cancel_capable": False,
        },
        "account_snapshot": {
            "timestamp_utc": _iso(account.timestamp_utc),
            "account_hash": expected_account_hash,
            "cash": account.cash,
            "equity": account.equity,
            "buying_power": account.buying_power,
            "positions": [_jsonable(positions[key]) for key in sorted(positions)],
            "open_orders": _jsonable(open_orders),
            "fills": _jsonable(fills),
        },
        "decision": decision,
        "write_counters": {**after, **deltas},
        "guardrails": {
            "injected_fake_client_only": True,
            "oms_handle_intent_called": False,
            "submit_order_called": False,
            "cancel_order_called": False,
            "global_cancel_called": False,
            "promotion_allowed": False,
            "paper_allowed": False,
            "live_allowed": False,
            "private_allowed": False,
            "order_allowed": False,
        },
        "blockers": [
            "injected_fake_client_not_real_gateway_evidence",
            "frozen_candidate_remains_exploratory_research_only",
            EXPECTED_YAHOO_GAP,
            EXPECTED_FRED_GAP,
            "no_real_ibkr_paper_order_fill_position_cash_ledger_evidence",
            "forward_paper_observation_not_started",
            "promotion_gate_not_rebuilt_and_all_trading_permissions_locked",
        ],
    }
    _reject_sensitive_fields(payload)
    _validate_decision_chain(payload["decision"])
    payload["artifact_sha256"] = _hash(payload)
    return payload


def validate_no_submit_shadow_artifact(
    *,
    repo_root: Path,
    artifact_path: Path,
    shared_data_root: Path,
    code_head_resolver: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ShadowEvidenceError("shadow_artifact_not_object")
        _reject_sensitive_fields(payload)
        schema = json.loads(
            (repo_root.resolve() / "schemas/us_etf_26_ibkr_no_submit_shadow.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())
    except ShadowEvidenceError:
        raise
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
        raise ShadowEvidenceError(
            f"shadow_artifact_schema_invalid:{getattr(exc, 'message', type(exc).__name__)}"
        ) from exc

    expected_head = (code_head_resolver or _git_head)(repo_root.resolve())
    if payload["code_head"] != expected_head:
        raise ShadowEvidenceError("shadow_code_head_mismatch")
    declared = dict(payload)
    artifact_hash = declared.pop("artifact_sha256")
    if artifact_hash != _hash(declared):
        raise ShadowEvidenceError("shadow_artifact_hash_mismatch")

    offline = _prepare_offline_inputs(
        repo_root=repo_root,
        shared_data_root=shared_data_root,
        observed_at_utc=_parse_utc(payload["observed_at_utc"]),
        max_staleness=timedelta(
            seconds=float(payload["freshness"]["max_staleness_seconds"])
        ),
        code_head_resolver=code_head_resolver,
    )
    expected_bindings = {
        "dataset_id": offline.manifest["dataset_id"],
        "dataset_version": offline.manifest["dataset_version"],
        "dataset_aggregate_sha256": offline.manifest["aggregate_sha256"],
        "manifest_git_spec": f"{offline.code_head}:{offline.manifest_path}",
        "manifest_path": offline.manifest_path,
        "manifest_sha256": offline.manifest_sha256,
        "storage_relative_path": offline.manifest["storage_relative_path"],
        "yahoo_file_path": QQQ_FILE,
        "yahoo_file_sha256": offline.qqq_sha256,
        "yahoo_lineage_path": YAHOO_LINEAGE_FILE,
        "yahoo_lineage_sha256": offline.lineage_sha256,
        "fred_file_path": FRED_FILE,
        "source_code_head": str(offline.lineage["source_commit"]),
        "adjustment_policy": EXPECTED_ADJUSTMENT_POLICY,
        "strategy_price_semantics": EXPECTED_PRICE_SEMANTICS,
        "account_hash": payload["bindings"]["account_hash"],
    }
    if payload["bindings"] != expected_bindings:
        raise ShadowEvidenceError("shadow_binding_mismatch")
    if payload["identity"] != offline.strategy_identity:
        raise ShadowEvidenceError("shadow_strategy_identity_mismatch")

    account = _account_from_snapshot(payload["account_snapshot"])
    strategy_decision = offline.strategy.generate(offline.bars)[-1]
    expected_decision = _replay_portfolio_chain(
        strategy_decision=strategy_decision,
        bars=offline.bars,
        account=account,
    )
    _validate_decision_chain(payload["decision"])
    if _semantic_decision(payload["decision"]) != _semantic_decision(expected_decision):
        raise ShadowEvidenceError("shadow_full_chain_replay_mismatch")
    return payload


def committed_frozen_strategy_identity(
    *, repo_root: Path, code_head: str | None = None
) -> dict[str, Any]:
    head = code_head or _git_head(repo_root.resolve())
    _, identity = _load_frozen_strategy(repo_root.resolve(), head)
    return identity


def _prepare_offline_inputs(
    *,
    repo_root: Path,
    shared_data_root: Path,
    observed_at_utc: datetime | None,
    max_staleness: timedelta,
    code_head_resolver: Callable[[Path], str] | None,
) -> _OfflineInputs:
    root = repo_root.resolve()
    observed = observed_at_utc or datetime.now(timezone.utc)
    observed = _ensure_utc(observed)
    if max_staleness <= timedelta(0):
        raise ShadowEvidenceError("shadow_max_staleness_invalid")
    try:
        code_head = (code_head_resolver or _git_head)(root)
    except Exception as exc:
        raise ShadowEvidenceError("shadow_consumer_head_unavailable") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", code_head):
        raise ShadowEvidenceError("ibkr_shadow_code_head_invalid")

    strategy, strategy_identity = _load_frozen_strategy(root, code_head)
    manifest_path, manifest_bytes, manifest = _latest_committed_manifest(root, code_head)
    errors = validate_manifest(manifest)
    if errors:
        raise ShadowEvidenceError("shadow_manifest_invalid:" + ";".join(errors))
    if manifest.get("dataset_id") != DATASET_ID:
        raise ShadowEvidenceError("shadow_manifest_dataset_id_mismatch")
    if manifest.get("quality_status") == "blocked" or manifest.get("blockers"):
        raise ShadowEvidenceError("shadow_manifest_quality_blocked")
    if manifest.get("readiness_class") != "quality_checked":
        raise ShadowEvidenceError("shadow_manifest_readiness_mismatch")
    known_gaps = set(manifest.get("known_gaps", []))
    if not {EXPECTED_YAHOO_GAP, EXPECTED_FRED_GAP}.issubset(known_gaps):
        raise ShadowEvidenceError("shadow_manifest_known_limit_missing")

    _validate_shared_root_owner(shared_data_root.resolve())
    try:
        dataset_root = resolve_manifest_payload(
            manifest,
            shared_root=shared_data_root.resolve(),
            verify_files=True,
        )
    except SharedDataError as exc:
        raise ShadowEvidenceError(f"shadow_shared_data_invalid:{exc}") from exc
    file_entries = {str(row["path"]): row for row in manifest["files"]}
    for required in (QQQ_FILE, YAHOO_LINEAGE_FILE, FRED_FILE):
        if required not in file_entries:
            raise ShadowEvidenceError(f"shadow_manifest_required_file_missing:{required}")

    qqq_path = _safe_dataset_path(dataset_root, QQQ_FILE)
    lineage_path = _safe_dataset_path(dataset_root, YAHOO_LINEAGE_FILE)
    qqq_sha = sha256_file(qqq_path)
    lineage_sha = sha256_file(lineage_path)
    if qqq_sha != file_entries[QQQ_FILE]["sha256"]:
        raise ShadowEvidenceError("shadow_yahoo_file_hash_mismatch")
    if lineage_sha != file_entries[YAHOO_LINEAGE_FILE]["sha256"]:
        raise ShadowEvidenceError("shadow_yahoo_lineage_hash_mismatch")

    try:
        lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowEvidenceError("shadow_yahoo_lineage_invalid") from exc
    _validate_lineage(lineage, qqq_sha)
    bars, latest, stale_seconds = _load_adjusted_bars(
        qqq_path,
        observed_at_utc=observed,
        max_staleness=max_staleness,
    )
    return _OfflineInputs(
        code_head=code_head,
        observed_at_utc=observed,
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest=manifest,
        qqq_sha256=qqq_sha,
        lineage_sha256=lineage_sha,
        lineage=lineage,
        bars=bars,
        strategy=strategy,
        strategy_identity=strategy_identity,
        latest_decision_time_utc=latest,
        stale_seconds=stale_seconds,
    )


def _validate_shared_root_owner(shared_root: Path) -> None:
    marker = shared_root / ".qs_shared_data_root_owner.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowEvidenceError("shadow_shared_root_owner_missing_or_invalid") from exc
    if (
        payload.get("schema_version") != "qs_shared_data_root_owner_v2"
        or payload.get("owner_domain") != "quant-system-agent"
        or payload.get("root_semantics") != "external_immutable_shared_data_root"
        or payload.get("logical_prefix") != "datasets/"
        or not HASH_PATTERN.fullmatch(str(payload.get("repository_identity", "")))
    ):
        raise ShadowEvidenceError("shadow_shared_root_owner_mismatch")


def _load_frozen_strategy(
    repo_root: Path, code_head: str
) -> tuple[FrozenEtf26CompleteReturnStrategy, dict[str, Any]]:
    raw = _git_show(repo_root, f"{code_head}:{FREEZE_CONFIG}")
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowEvidenceError("shadow_freeze_config_invalid") from exc
    selection = config.get("selection", {})
    parameters = config.get("parameters", {})
    prohibited = set(config.get("prohibited_uses", []))
    required_prohibitions = {
        "promotion_evidence",
        "paper_queue_write",
        "paper_or_live_unlock",
        "private_or_order_endpoint_access",
        "real_order_generation",
    }
    checks = (
        config.get("candidate_id") == EXPECTED_CANDIDATE_ID,
        config.get("strategy_version") == EXPECTED_STRATEGY_VERSION,
        config.get("status") == "frozen_exploratory_research_only",
        selection.get("symbol") == "QQQ",
        selection.get("timeframe") == "1D",
        float(selection.get("exposure_multiplier", 0.0)) == 3.0,
        isinstance(parameters, dict) and bool(parameters),
        required_prohibitions.issubset(prohibited),
    )
    if not all(checks):
        raise ShadowEvidenceError("shadow_frozen_strategy_identity_invalid")
    strategy = FrozenEtf26CompleteReturnStrategy(
        candidate_id=EXPECTED_CANDIDATE_ID,
        strategy_version=EXPECTED_STRATEGY_VERSION,
        symbol="QQQ",
        exposure_multiplier=3.0,
        params=parameters,
    )
    identity = {
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "strategy_version": EXPECTED_STRATEGY_VERSION,
        "symbol": "QQQ",
        "timeframe": "1D",
        "exposure_multiplier": 3.0,
        "status": "frozen_exploratory_research_only",
        "freeze_config_path": FREEZE_CONFIG,
        "freeze_config_sha256": hashlib.sha256(raw).hexdigest(),
        "params_sha256": _hash(parameters),
    }
    return strategy, identity


def _latest_committed_manifest(
    repo_root: Path, code_head: str
) -> tuple[str, bytes, dict[str, Any]]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", code_head, "--", MANIFEST_PREFIX],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ShadowEvidenceError("shadow_manifest_inventory_unavailable")
    paths = sorted(
        path.strip()
        for path in completed.stdout.splitlines()
        if path.strip().startswith(MANIFEST_PREFIX) and path.strip().endswith(".json")
    )
    if not paths:
        raise ShadowEvidenceError("shadow_committed_manifest_missing")
    candidates: list[tuple[datetime, str, bytes, dict[str, Any]]] = []
    for path in paths:
        raw = _git_show(repo_root, f"{code_head}:{path}")
        try:
            payload = json.loads(raw.decode("utf-8"))
            published = _parse_utc(str(payload["published_at"]))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ShadowEvidenceError(f"shadow_committed_manifest_unreadable:{path}") from exc
        candidates.append((published, path, raw, payload))
    candidates.sort(key=lambda row: (row[0], row[1]))
    latest_time = candidates[-1][0]
    latest = [row for row in candidates if row[0] == latest_time]
    if len(latest) != 1:
        raise ShadowEvidenceError("shadow_latest_manifest_ambiguous")
    _, path, raw, payload = latest[0]
    return path, raw, payload


def _validate_lineage(lineage: Mapping[str, Any], qqq_sha: str) -> None:
    adjustment = lineage.get("adjustment")
    guardrails = lineage.get("guardrails")
    if (
        lineage.get("schema_version") != "us_equity_yahoo_daily_snapshot_manifest_v1"
        or lineage.get("symbol") != "QQQ"
        or lineage.get("timeframe") != "1D"
        or lineage.get("data_file_path") != QQQ_FILE
        or lineage.get("data_file_sha256") != qqq_sha
        or not re.fullmatch(r"[0-9a-f]{40}", str(lineage.get("source_commit", "")))
        or not isinstance(adjustment, Mapping)
        or adjustment.get("policy") != EXPECTED_ADJUSTMENT_POLICY
        or adjustment.get("strategy_price_semantics") != EXPECTED_PRICE_SEMANTICS
        or not isinstance(guardrails, Mapping)
        or guardrails.get("immutable") is not True
        or guardrails.get("snapshot_complete") is not True
        or guardrails.get("consumer_network_access_allowed") is not False
        or guardrails.get("promotion_evidence_ready") is not False
    ):
        raise ShadowEvidenceError("shadow_yahoo_lineage_contract_mismatch")


def _load_adjusted_bars(
    path: Path,
    *,
    observed_at_utc: datetime,
    max_staleness: timedelta,
) -> tuple[pd.DataFrame, datetime, float]:
    try:
        raw = pd.read_csv(path)
    except Exception as exc:
        raise ShadowEvidenceError("shadow_yahoo_csv_unreadable") from exc
    required = {
        "symbol",
        "decision_time_utc",
        "available_time_utc",
        "Open",
        "High",
        "Low",
        "Close",
        "Adj Close",
        "Volume",
        "adjustment_ratio",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ShadowEvidenceError("shadow_yahoo_columns_missing:" + ",".join(missing))
    if raw.empty or set(raw["symbol"].astype(str).str.upper()) != {"QQQ"}:
        raise ShadowEvidenceError("shadow_yahoo_symbol_invalid")
    decision_times = pd.to_datetime(raw["decision_time_utc"], utc=True, errors="coerce")
    available_times = pd.to_datetime(raw["available_time_utc"], utc=True, errors="coerce")
    if decision_times.isna().any() or available_times.isna().any():
        raise ShadowEvidenceError("shadow_yahoo_timestamp_invalid")
    if decision_times.duplicated().any() or not decision_times.is_monotonic_increasing:
        raise ShadowEvidenceError("shadow_yahoo_timestamp_order_invalid")
    if (available_times > pd.Timestamp(observed_at_utc)).any():
        raise ShadowEvidenceError("shadow_yahoo_not_available_at_observation")

    numeric_columns = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "adjustment_ratio"]
    numeric = raw[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ShadowEvidenceError("shadow_yahoo_numeric_invalid")
    if (numeric[["Open", "High", "Low", "Close", "Adj Close", "adjustment_ratio"]] <= 0).any().any():
        raise ShadowEvidenceError("shadow_yahoo_non_positive_price")
    if (
        (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1)).any()
        or (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1)).any()
    ):
        raise ShadowEvidenceError("shadow_yahoo_ohlc_invalid")
    expected_close = numeric["Close"] * numeric["adjustment_ratio"]
    tolerance = 1e-10 * expected_close.abs().clip(lower=1.0)
    if ((expected_close - numeric["Adj Close"]).abs() > tolerance).any():
        raise ShadowEvidenceError("shadow_yahoo_adjusted_close_mismatch")

    latest = decision_times.iloc[-1].to_pydatetime()
    stale_seconds = (observed_at_utc - latest).total_seconds()
    if stale_seconds < 0:
        raise ShadowEvidenceError("shadow_yahoo_latest_decision_in_future")
    if stale_seconds > max_staleness.total_seconds():
        raise ShadowEvidenceError("shadow_yahoo_data_stale")
    ratio = numeric["adjustment_ratio"]
    bars = pd.DataFrame({
        "decision_time_utc": decision_times,
        "Open": numeric["Open"] * ratio,
        "High": numeric["High"] * ratio,
        "Low": numeric["Low"] * ratio,
        "Close": numeric["Close"] * ratio,
        "Volume": numeric["Volume"],
    })
    return bars, latest, stale_seconds


def _replay_portfolio_chain(
    *, strategy_decision: Any, bars: pd.DataFrame, account: AccountState
) -> dict[str, Any]:
    allocator = PortfolioAllocator(
        AllocationConfig(),
        risk_policy=PortfolioRiskPolicy(),
        rebalance_config=SHADOW_REBALANCE_CONFIG,
    )
    latest_price = float(bars.iloc[-1]["Close"])
    allocation = allocator.allocate_targets(
        [strategy_decision.target],
        account=account,
        prices={"QQQ": latest_price},
        run_id=f"shadow-{strategy_decision.target.target_position_id}",
    )
    risk_engine = PreTradeRiskEngine()
    risks = [
        risk_engine.evaluate(intent, account, latest_price, intent.timestamp_utc)
        for intent in allocation.intents
    ]
    suppressions = _rebalance_suppressions(
        targets=allocation.targets,
        intents=allocation.intents,
        account=account,
        prices={"QQQ": latest_price},
        config=SHADOW_REBALANCE_CONFIG,
    )
    if not allocation.intents and not suppressions:
        raise ShadowEvidenceError("shadow_zero_intent_without_suppression")
    noop_reason = suppressions[0]["reason"] if suppressions else ""
    return {
        "signal": _jsonable(strategy_decision.signal),
        "forecast": _jsonable(strategy_decision.forecast),
        "target_position": _jsonable(strategy_decision.target),
        "portfolio_targets": _jsonable(allocation.targets),
        "portfolio_target_decisions": _jsonable(allocation.target_decisions),
        "portfolio_intent_decisions": _jsonable(allocation.intent_decisions),
        "order_intents": _jsonable(allocation.intents),
        "risk_decisions": _jsonable(risks),
        "rebalance_suppressions": suppressions,
        "rebalance_noop_reason": noop_reason,
    }


def _rebalance_suppressions(
    *,
    targets: list[Any],
    intents: list[Any],
    account: AccountState,
    prices: Mapping[str, float],
    config: RebalanceConfig,
) -> list[dict[str, Any]]:
    intent_symbols = {intent.symbol for intent in intents}
    output: list[dict[str, Any]] = []
    for target in targets:
        if target.symbol in intent_symbols:
            continue
        price = float(prices.get(target.symbol, 0.0))
        current = account.positions.get(target.symbol)
        current_quantity = current.quantity if current else 0.0
        current_weight = current_quantity * price / max(account.equity, 1.0)
        target_quantity = target.target_quantity
        if target_quantity is None:
            target_quantity = account.equity * target.target_weight / price
        delta = float(target_quantity) - current_quantity
        notional = abs(delta) * price
        if abs(target.target_weight - current_weight) < config.min_weight_change:
            reason, threshold = "target_matches_current_position", config.min_weight_change
        elif abs(delta) < config.min_quantity:
            reason, threshold = "min_quantity", config.min_quantity
        elif notional < config.min_trade_notional:
            reason, threshold = "min_trade_notional", config.min_trade_notional
        else:
            raise ShadowEvidenceError(
                "shadow_rebalance_missing_intent_without_known_suppression"
            )
        output.append({
            "symbol": target.symbol,
            "reason": reason,
            "current_quantity": current_quantity,
            "current_weight": current_weight,
            "target_weight": target.target_weight,
            "target_quantity": float(target_quantity),
            "delta_quantity": delta,
            "notional": notional,
            "threshold": float(threshold),
        })
    return output


def _validate_decision_chain(decision: Mapping[str, Any]) -> None:
    signal = decision["signal"]
    forecast = decision["forecast"]
    target = decision["target_position"]
    portfolio_targets = decision["portfolio_targets"]
    intents = decision["order_intents"]
    risks = decision["risk_decisions"]
    common = (signal["strategy_id"], signal["symbol"], signal["timestamp_utc"])
    if any(
        (row["strategy_id"], row["symbol"], row["timestamp_utc"]) != common
        for row in (forecast, target)
    ):
        raise ShadowEvidenceError("shadow_identity_chain_mismatch")
    if signal["signal_id"] != forecast["signal_id"] or signal["signal_id"] != target["signal_id"]:
        raise ShadowEvidenceError("shadow_signal_id_chain_mismatch")
    if target["metadata"]["forecast_id"] != forecast["forecast_id"]:
        raise ShadowEvidenceError("shadow_forecast_id_chain_mismatch")
    if len(portfolio_targets) != 1 or len(intents) != len(risks):
        raise ShadowEvidenceError("shadow_decision_cardinality_invalid")
    if not intents:
        suppressions = decision["rebalance_suppressions"]
        if len(suppressions) != 1 or decision["rebalance_noop_reason"] != suppressions[0]["reason"]:
            raise ShadowEvidenceError("shadow_rebalance_suppression_invalid")
        return
    if decision["rebalance_noop_reason"] or decision["rebalance_suppressions"]:
        raise ShadowEvidenceError("shadow_rebalance_suppression_unexpected")
    for intent, risk in zip(intents, risks, strict=True):
        if intent["signal_id"] != signal["signal_id"]:
            raise ShadowEvidenceError("shadow_intent_signal_id_mismatch")
        if intent["target_position_id"] != portfolio_targets[0]["target_position_id"]:
            raise ShadowEvidenceError("shadow_intent_target_id_mismatch")
        if risk["order_intent_id"] != intent["order_intent_id"]:
            raise ShadowEvidenceError("shadow_risk_intent_id_mismatch")


def _write_counters(broker: IBKRBroker) -> dict[str, int]:
    client = getattr(broker, "_client", None)
    reader = getattr(client, "write_call_counters", None)
    if not callable(reader):
        raise ShadowEvidenceError("ibkr_shadow_fake_write_counter_surface_missing")
    raw = reader()
    if not isinstance(raw, Mapping):
        raise ShadowEvidenceError("ibkr_shadow_fake_write_counter_surface_invalid")
    try:
        client_submit = int(raw["submit"])
        client_cancel = int(raw["cancel"])
        client_global_cancel = int(raw["global_cancel"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ShadowEvidenceError("ibkr_shadow_fake_write_counter_surface_invalid") from exc
    return {
        "submit_call_count": int(broker.submit_call_count) + client_submit,
        "cancel_call_count": int(broker.cancel_call_count) + client_cancel,
        "global_cancel_call_count": client_global_cancel,
        "submit_attempt_count": int(broker.submit_attempt_count),
        "cancel_attempt_count": int(broker.cancel_attempt_count),
    }


def _account_from_snapshot(snapshot: Mapping[str, Any]) -> AccountState:
    positions = {
        str(row["symbol"]): Position(
            symbol=str(row["symbol"]),
            quantity=float(row["quantity"]),
            avg_price=float(row["avg_price"]),
            market_price=float(row["market_price"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
        )
        for row in snapshot["positions"]
    }
    return AccountState(
        timestamp_utc=_parse_utc(str(snapshot["timestamp_utc"])),
        account_id=str(snapshot["account_hash"]),
        cash=float(snapshot["cash"]),
        equity=float(snapshot["equity"]),
        buying_power=float(snapshot["buying_power"]),
        positions=positions,
    )


def _semantic_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(decision))
    for target in value["portfolio_targets"]:
        target.pop("target_position_id", None)
    for intent in value["order_intents"]:
        intent.pop("client_order_id", None)
        intent.pop("order_intent_id", None)
        intent.pop("target_position_id", None)
    for risk in value["risk_decisions"]:
        risk.pop("order_intent_id", None)
        risk.pop("checked_at", None)
        risk.pop("risk_check_id", None)
    return value


def _reject_sensitive_fields(value: Any) -> None:
    allowed = {"accounthash", "accountsnapshot"}
    account_aliases = {
        "account",
        "accountid",
        "accountnumber",
        "acctid",
        "ibaccount",
        "rawaccount",
    }
    secret_patterns = (
        "apikey",
        "passphrase",
        "credential",
        "authorization",
        "secret",
        "token",
        "password",
    )
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = "".join(char for char in str(key).lower() if char.isalnum())
            if normalized not in allowed and (
                normalized in account_aliases
                or any(pattern in normalized for pattern in secret_patterns)
            ):
                raise ShadowEvidenceError(f"shadow_sensitive_field_forbidden:{key}")
            _reject_sensitive_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_fields(item)


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ShadowEvidenceError("shadow_git_head_unavailable")
    return completed.stdout.strip()


def _git_show(repo_root: Path, git_spec: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "-p", git_spec],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ShadowEvidenceError(f"shadow_git_object_unavailable:{git_spec}")
    return completed.stdout


def _safe_dataset_path(dataset_root: Path, relative: str) -> Path:
    path = (dataset_root / relative).resolve()
    try:
        path.relative_to(dataset_root.resolve())
    except ValueError as exc:
        raise ShadowEvidenceError("shadow_dataset_path_escape") from exc
    if not path.is_file():
        raise ShadowEvidenceError(f"shadow_dataset_file_missing:{relative}")
    return path


def _validate_account_hash(value: str) -> None:
    if not HASH_PATTERN.fullmatch(str(value)):
        raise ShadowEvidenceError("ibkr_shadow_expected_account_hash_invalid")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ShadowEvidenceError("shadow_timestamp_timezone_missing")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _ensure_utc(parsed)


def _iso(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")
