"""Frozen history-only evaluation specification; never a trading authorization."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import pandas as pd

from integrations.qlib_adapter.market_data import (
    bind_instrument_identity, normalize_hourly_input, normalize_funding_input,
)
from integrations.qlib_adapter.schemas import QlibAdapterError
from quant_crypto.application.btc_strategy_registry import btc_strategy_registry

MANIFEST_GIT_SPEC = "165a446729f8c114748e1b20bbfcf0c91e75066e:.agent/data_manifests/m1-trend-environment-acceptance/m1-okx-59f5eb861-20260911.json"
MANIFEST_SHA256 = "2aab7e1e031acf094ce7a827d324102050344d27246443cac7acb574dd5c3f2a"
AGGREGATE_SHA256 = "593eb9f893c280703b26423f00a4eaff62542152110ebff1dd5b5ad69061bcde"
DATASET_ID = "m1-trend-environment-acceptance"
DATASET_VERSION = "m1-okx-59f5eb861-20260911"
SIGNAL_EVENT_START = datetime(2026, 7, 23, tzinfo=timezone.utc)
SIGNAL_EVENT_END = datetime(2026, 7, 30, tzinfo=timezone.utc)
WARMUP_ROWS = 5112
SIGNAL_ROWS = 168
DATA_PREFIX = "qlib_runs/m1-okx-factory-input/qlib_input"
EXPECTED_FILES = {
    "daily_bars.parquet": "1c170ba3d8daa448eb5d185db57dd557ec72da95aa3a4d72bf17540eb10e860b",
    "mark.parquet": "a6b738eb2b222bb01dd6071175c5d2708b9298ef73fb62fab9ab5af585f121dc",
    "premium.parquet": "e4d719c611bf104460f4d2afd5b00892567f13d9d24ac771331e63d332ee4498",
    "funding.parquet": "ed4856c11f6c28fa2394aced9a18a24840b99bb298694f101e23eb6e72d58f89",
}
MATCHING_POLICY = {
    "version": "historical_next_bar_open_spread_aware_v2",
    "execution": "marketable_limit_fok_ioc_full_fill_within_frozen_depth",
    "half_spread_bps": "0.5",
    "depth": "not_available_assumed_one_contract_each_side",
    "queue": "not_modeled",
    "market_impact": "not_modeled",
}
COST_POLICY = {"version": "fixed_taker_5bps_v1", "taker_fee_bps": "5"}
PROTECTION_POLICY = {
    "version": "existing_v1_mark_oco_100_200bps_v1",
    "stop_loss_bps": "100",
    "take_profit_bps": "200",
    "double_touch": "blocked_ambiguous",
}

STRATEGY_ID = "long_short_donchian_top5_okx_native"
PARAMS_HASH = "5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355"
EXECUTION = {
    "account_equity_usdt": "5000", "order_contracts": "0.01",
    "contract_value_btc": "0.01", "position_rule": "original_fixed_contracts_v1",
    "exit_rule": "original_registry_signal_and_existing_protection_v1",
    "terminal": "observe_and_reconcile_no_new_order_no_forced_close",
    "matching": MATCHING_POLICY, "cost": COST_POLICY, "protection": PROTECTION_POLICY,
    "funding_interval_hours": 8,
    "funding_mark": "t_minus_1h_visible_mark_close_approximation",
}
BUDGET = {"max_evaluation_hours": 8784, "experiments": 1, "search": False,
          "stop_on_ambiguity": True, "stop_on_ledger_mismatch": True}
_GIT_SPEC = re.compile(r"^[0-9a-f]{40}:[A-Za-z0-9_./-]+$")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _utc_hour(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("historical_spec_time_invalid")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0) or any((result.minute, result.second, result.microsecond)):
        raise ValueError("historical_spec_time_must_be_complete_utc_hour")
    return result.astimezone(timezone.utc)


def _relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value and not path.is_absolute() and ".." not in path.parts and ":" not in value and "\\" not in value)


def _git_spec_valid(value: str) -> bool:
    return bool(_GIT_SPEC.fullmatch(value) and _relative(value.split(":", 1)[1]))


@dataclass(frozen=True)
class HistorySpec:
    canonical_json: str
    git_spec: str = ""
    blob_sha256: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, git_spec: str = "", blob_sha256: str = "") -> "HistorySpec":
        value = json.loads(_json(payload))
        if set(value) != {"schema_version", "data", "window", "strategy", "execution", "budget", "evidence_class"}:
            raise ValueError("historical_spec_fields_invalid")
        if value["schema_version"] not in {"btc_donchian_history_spec_v1", "btc_donchian_history_spec_v2"} or value["evidence_class"] != "exploratory_historical_not_promotion":
            raise ValueError("historical_spec_schema_or_evidence_invalid")
        original = btc_strategy_registry.get(STRATEGY_ID)
        expected_strategy = {
            "strategy_id": STRATEGY_ID, "strategy_version": "btc_long_short_donchian_top5_okx_native@1.0.0",
            "params_hash": PARAMS_HASH, "params": dict(original.params),
            "candidate_id": original.candidate_id,
        }
        if original.params_hash != PARAMS_HASH or value["strategy"] != expected_strategy:
            raise ValueError("historical_spec_original_strategy_mismatch")
        expected_execution = EXECUTION if value["schema_version"] == "btc_donchian_history_spec_v1" else {
            **EXECUTION, "max_notional_usdt": "50", "max_loss_usdt": "10",
        }
        if value["execution"] != expected_execution or value["budget"] != BUDGET:
            raise ValueError("historical_spec_frozen_policy_mismatch")
        data = value["data"]
        if set(data) != {"manifest_git_spec", "manifest_sha256", "aggregate_sha256", "dataset_id", "dataset_version", "prefix", "files"}:
            raise ValueError("historical_spec_data_fields_invalid")
        if not _git_spec_valid(data["manifest_git_spec"]) or not _relative(data["prefix"]):
            raise ValueError("historical_spec_immutable_data_reference_required")
        hashes = [data["manifest_sha256"], data["aggregate_sha256"], *data["files"].values()]
        if any(not isinstance(h, str) or not re.fullmatch("[0-9a-f]{64}", h) for h in hashes):
            raise ValueError("historical_spec_data_hash_invalid")
        if set(data["files"]) != set(EXPECTED_FILES) or not data["dataset_id"] or not data["dataset_version"]:
            raise ValueError("historical_spec_data_identity_invalid")
        window = value["window"]
        if set(window) != {"warmup_start", "evaluation_start", "evaluation_end", "requested_months", "selection_reason"}:
            raise ValueError("historical_spec_window_fields_invalid")
        warmup, start, end = (_utc_hour(window[k]) for k in ("warmup_start", "evaluation_start", "evaluation_end"))
        # UTC-midnight boundaries ensure 200 COMPLETE daily candles, not 4800
        # rows crossing partial days. The 240 x 4h channel needs fewer bars.
        if warmup.hour or start.hour or (start-warmup) < timedelta(days=200):
            raise ValueError("historical_spec_warmup_requires_200_complete_utc_days")
        if not start < end or (end-start).total_seconds()/3600 > BUDGET["max_evaluation_hours"]:
            raise ValueError("historical_spec_evaluation_window_invalid")
        if window["requested_months"] != 12 or not isinstance(window["selection_reason"], str) or not window["selection_reason"]:
            raise ValueError("historical_spec_selection_reason_required")
        return cls(_json(value), git_spec=git_spec, blob_sha256=blob_sha256)

    @classmethod
    def from_git(cls, repo_root: Path, git_spec: str) -> "HistorySpec":
        if not _git_spec_valid(git_spec):
            raise ValueError("historical_spec_exact_commit_required")
        raw = subprocess.check_output(["git", "show", git_spec], cwd=repo_root)
        return cls.from_payload(json.loads(raw), git_spec=git_spec, blob_sha256=hashlib.sha256(raw).hexdigest())

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def warmup_start(self) -> datetime:
        return _utc_hour(self.payload["window"]["warmup_start"])

    @property
    def start(self) -> datetime:
        return _utc_hour(self.payload["window"]["evaluation_start"])

    @property
    def end(self) -> datetime:
        return _utc_hour(self.payload["window"]["evaluation_end"])

    @property
    def warmup_rows(self) -> int:
        return int((self.start-self.warmup_start).total_seconds()/3600)

    @property
    def signal_rows(self) -> int:
        return int((self.end-self.start).total_seconds()/3600)


def legacy_spec() -> HistorySpec:
    original = btc_strategy_registry.get(STRATEGY_ID)
    return HistorySpec.from_payload({
        "schema_version": "btc_donchian_history_spec_v1",
        "data": {"manifest_git_spec": MANIFEST_GIT_SPEC, "manifest_sha256": MANIFEST_SHA256,
                 "aggregate_sha256": AGGREGATE_SHA256, "dataset_id": DATASET_ID,
                 "dataset_version": DATASET_VERSION, "prefix": DATA_PREFIX, "files": EXPECTED_FILES},
        "window": {"warmup_start": "2025-12-22T00:00:00+00:00", "evaluation_start": SIGNAL_EVENT_START.isoformat(),
                   "evaluation_end": SIGNAL_EVENT_END.isoformat(), "requested_months": 12,
                   "selection_reason": "legacy_frozen_one_week_compatibility_only"},
        "strategy": {"strategy_id": STRATEGY_ID, "strategy_version": original.strategy_version,
                     "candidate_id": original.candidate_id, "params_hash": PARAMS_HASH, "params": dict(original.params)},
        "execution": EXECUTION, "budget": BUDGET,
        "evidence_class": "exploratory_historical_not_promotion",
    })


def validate_tables(spec: HistorySpec, bars: pd.DataFrame, marks: pd.DataFrame,
                    premium: pd.DataFrame, funding: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    result = []
    expected = pd.date_range(spec.warmup_start, spec.end-timedelta(hours=1), freq="h")
    for kind, table in (("bars", bars), ("mark", marks), ("premium", premium), ("funding", funding)):
        table = table.copy()
        for key in ("event_time", "available_time"):
            table[key] = pd.to_datetime(table[key], utc=True, errors="raise")
        lower = spec.start if kind == "funding" else spec.warmup_start
        mask = (table.event_time >= lower) & (table.event_time <= spec.end if kind == "funding" else table.event_time < spec.end)
        table = table.loc[mask].reset_index(drop=True)
        if "source_symbol" not in table or not table.symbol.eq("BTC-USDT-SWAP").all() or not table.source_symbol.eq("BTCUSDT").all():
            raise ValueError(f"historical_{kind}_source_identity_invalid")
        table["symbol"] = table.source_symbol
        try:
            table = bind_instrument_identity(table, canonical_symbol="BTCUSDT", instrument="BTC-USDT-SWAP", kind=kind)
            table = normalize_funding_input(table, symbol="BTC-USDT-SWAP") if kind == "funding" else normalize_hourly_input(table, symbol="BTC-USDT-SWAP", kind=kind)
        except QlibAdapterError as exc:
            raise ValueError(f"historical_{kind}_content_invalid:{exc}") from exc
        if kind == "funding":
            settlements = pd.date_range(pd.Timestamp(spec.start).ceil("8h"), spec.end, freq="8h")
            settlements = settlements[settlements > spec.start]
            observed = pd.DatetimeIndex(table.loc[table.event_time > spec.start, "event_time"])
            if not observed.equals(settlements) or not table.available_time.eq(table.event_time).all():
                raise ValueError("historical_funding_full_settlement_coverage_required")
        elif not pd.DatetimeIndex(table.event_time).equals(expected):
            raise ValueError(f"historical_{kind}_complete_hour_coverage_required")
        result.append(table)
    return tuple(result)
