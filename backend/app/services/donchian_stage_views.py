"""Committed, bounded read model for one paused Donchian historical stage."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping


SELECTOR = "donchian-stage-20260921"
SNAPSHOT_PATH = ".agent/offline_evidence/donchian-stage-20260921.json"
SNAPSHOT_DIGEST = "ff5d5ad93538a4b74a2b3da1c7f76cad963e4a25195ff56373ad83c7806cce01"
MARKET_STATE_PATH = ".agent/market_state_evidence/donchian-stage-market-state-v2-20260927.json"
MARKET_STATE_FILE_SHA256 = "2a4345a7d9a867cd1888addad00659583ea744911aa0b5b8486ad8c282c9c00b"
MARKET_STATE_EVIDENCE_HASH = "11f279d63b0b43cee0c3229dca90f80a2049de090de27c701b75f20b0fdd2b2c"
MARKET_POLICY_TRIAL_PATH = ".agent/market_state_evidence/donchian-stage-market-policy-trial-v1.json"
MARKET_POLICY_TRIAL_ID = "donchian-stage-market-policy-trial-20260927-v1"
MARKET_POLICY_CONSUMER_COMMIT = "f2455bfbcafd15404bb4ff98dd6bb925728d0339"
SOURCE_RECEIPT_SHA256 = "cc4158866b38c25c4d4d2314671642169bd87304844e1557d7df1dbcc823f647"
SOURCE_REPORT_SHA256 = "643ec8de296ba254efb67dee77750fe1c7313991cfc434410eaa6903090b936f"
SOURCE_HEAD = "897d5e99ebe4c898f71ac66cf33fb2d2420855d5"
RUN_ID = "donchian-effective-time-20250901-20260901"
FLAGS = ("demo_control_enabled", "execution_permission", "live", "order", "paper",
         "private", "promotion", "real_order", "runtime_observed", "transfer", "withdraw")
TRIAL_SAFETY_FLAGS = (*FLAGS, "network_accessed")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("donchian_stage_amount_invalid") from exc
    _require(result.is_finite(), "donchian_stage_amount_invalid")
    return result


def _utc(value: Any) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("donchian_stage_time_invalid") from exc
    _require(moment.tzinfo is not None and moment.utcoffset().total_seconds() == 0,
             "donchian_stage_time_invalid")
    return moment.astimezone(timezone.utc)


def validate_stage_snapshot(snapshot: Mapping[str, Any], publication_head: str) -> dict[str, Any]:
    """Reject any modified or incomplete projection, even if its JSON parses."""
    _require(bool(HEX40.fullmatch(publication_head)), "donchian_stage_publication_invalid")
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    _require(hashlib.sha256(encoded).hexdigest() == SNAPSHOT_DIGEST,
             "donchian_stage_snapshot_digest_mismatch")
    _require(snapshot.get("schema_version") == "donchian_paused_stage_snapshot_v1"
             and snapshot.get("selector") == SELECTOR
             and snapshot.get("truth_kind") == "offline_execution_simulation"
             and snapshot.get("status") == "stage_baseline_reconciled_research_only"
             and snapshot.get("source_receipt_sha256") == SOURCE_RECEIPT_SHA256
             and snapshot.get("source_report_sha256") == SOURCE_REPORT_SHA256
             and snapshot.get("source_head") == SOURCE_HEAD,
             "donchian_stage_provenance_invalid")
    identity = snapshot["identity"]
    _require(identity.get("run_id") == RUN_ID and identity.get("source_head") == SOURCE_HEAD
             and identity.get("strategy_id") == "long_short_donchian_top5_okx_native"
             and identity.get("strategy_version") == "btc_long_short_donchian_top5_okx_native@1.0.0"
             and identity.get("dataset_version") == "donchian-long-input-20260921-v2"
             and identity.get("params_hash") == "5941833b08a34e39c6893e0bb60ca8c7748224fb360dae528628bfbabd04d355"
             and identity.get("manifest_git_spec") == "02e85c7e035cf9fdd8becc8ea110c1bffef57964:.agent/data_manifests/donchian-long-input/donchian-long-input-20260921-v2.json"
             and identity.get("spec_git") == "25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json"
             and identity.get("planned_evaluation_end_utc") == "2026-09-01T00:00:00+00:00"
             and all(bool(HEX64.fullmatch(identity.get(key, ""))) for key in
                     ("manifest_sha256", "aggregate_sha256", "spec_blob_sha256", "spec_digest", "identity_digest",
                      "cost_policy_hash", "matching_policy_hash", "protection_policy_hash",
                      "protection_time_policy_hash"))
             and _decimal(identity.get("order_contracts")) == Decimal("0.01")
             and _decimal(identity.get("contract_value_btc")) == Decimal("0.01")
             and _decimal(identity.get("initial_equity_usdt")) == Decimal("5000")
             and _decimal(identity.get("nominal_cap_usdt")) == Decimal("50")
             and _decimal(identity.get("loss_threshold_usdt")) == Decimal("10"),
             "donchian_stage_identity_invalid")
    progress, counts = snapshot["progress"], snapshot["counts"]
    _require(progress.get("paused") is True and progress.get("processed_hours") == 2960
             and progress.get("planned_hours") == 8760
             and progress.get("historical_event_start_utc") == "2025-09-01T00:00:00+00:00"
             and progress.get("last_event_end_utc") == "2026-01-02T08:00:00+00:00"
             and _utc(progress.get("paused_at_utc")) > _utc(progress["last_event_end_utc"])
             and counts.get("decisions") == 2960 and counts.get("orders") == 56
             and counts.get("fills") == 56 and counts.get("primary_decisions") == 30
             and counts.get("protective_exits") == 26 and counts.get("roundtrips") == 28
             and counts.get("funding_bills") == 370 and counts.get("nonzero_funding_bills") == 24
             and counts.get("ledger_uows") == 2992 and counts.get("journal_events") == 14874,
             "donchian_stage_progress_or_counts_invalid")
    economics = snapshot["economics"]
    assumptions = snapshot["execution_assumptions"]
    _require(_decimal(assumptions.get("taker_fee_bps")) == 5
             and _decimal(assumptions.get("half_spread_bps")) == Decimal("0.5")
             and _decimal(assumptions.get("assumed_depth_contracts_each_side")) == 1
             and assumptions.get("funding_source") == "prior_visible_hour_mark_close_proxy"
             and assumptions.get("queue_and_market_impact") == "not_modeled"
             and assumptions.get("intrabar_exact_fill_time") == "not_verified"
             and assumptions.get("ambiguous_dual_touch_order") == "fail_closed",
             "donchian_stage_assumptions_invalid")
    price = _decimal(economics.get("price_pnl_usdt"))
    fee = _decimal(economics.get("fee_cashflow_usdt"))
    funding = _decimal(economics.get("funding_cashflow_usdt"))
    net = _decimal(economics.get("net_usdt"))
    cash = _decimal(economics.get("cash_usdt"))
    _require(price == Decimal("0.0346310615")
             and fee == Decimal("-0.26552203961525")
             and funding == Decimal("-0.012403344923245647991")
             and net == Decimal("-0.243294323038495647991")
             and price + fee + funding == net and Decimal("5000") + net == cash
             and _decimal(economics.get("equity_usdt")) == cash
             and _decimal(economics.get("position_contracts")) == 0
             and _decimal(economics.get("unrealized_pnl_usdt")) == 0,
             "donchian_stage_accounting_invalid")
    verification = snapshot["verification"]
    _require(verification.get("ledger_reconciled") is True
             and verification.get("checkpoint_matches_recovered") is True
             and verification.get("blockers") == []
             and verification.get("venue_ledger_value_mismatches") == 0
             and verification.get("batch_exit_zero_count") == 10
             and verification.get("checkpoint_verified_count") == 10
             and verification.get("inputs_unchanged") is True
             and verification.get("source_permissions_changed") is False
             and verification.get("source_strategy_run_or_resume_called") is False
             and set(snapshot.get("permissions", {})) == set(FLAGS)
             and all(snapshot["permissions"][flag] is False for flag in FLAGS),
             "donchian_stage_verification_or_permissions_invalid")
    links, trips = snapshot["decision_links"], snapshot["roundtrips"]
    _require(len(links) == 30 and len(trips) == 28,
             "donchian_stage_link_count_invalid")
    primary_fill_ids: set[str] = set()
    for row in links:
        fills = row.get("fill_ids")
        _require(isinstance(fills, list) and len(fills) == 1
                 and row.get("ledger_hash_and_fill_refs_resolved") is True
                 and row.get("ledger_id_matches_idempotency_key") is True
                 and bool(HEX64.fullmatch(row.get("ledger_event_hash", "")))
                 and all(isinstance(row.get(key), str) and row[key] for key in
                         ("signal_id", "target_position_id", "risk_check_id", "order_intent_id",
                          "client_order_id", "exchange_order_id", "ledger_event_id"))
                 and fills[0] not in primary_fill_ids,
                 "donchian_stage_primary_link_invalid")
        _utc(row.get("event_time_utc"))
        primary_fill_ids.add(fills[0])
    paired_ids = [fill_id for row in trips for fill_id in
                  (row.get("open_fill_id"), row.get("close_fill_id"))]
    exits = [row.get("exit_type") for row in trips]
    _require(len(paired_ids) == 56 and len(set(paired_ids)) == 56
             and primary_fill_ids.issubset(paired_ids)
             and exits.count("historical_oco_stop_loss") == 18
             and exits.count("historical_oco_take_profit") == 8
             and exits.count("historical_next_bar_open_spread_aware") == 2,
             "donchian_stage_roundtrip_join_invalid")
    _require({"annual_performance", "remaining_5800_hours", "formal_frontend_acceptance_of_this_stage_run",
              "live_or_demo_exchange_reconciliation"}.issubset(snapshot.get("not_verified", [])),
             "donchian_stage_limits_invalid")
    return {**snapshot, "publication_head": publication_head,
            "historical_source": publication_head != SOURCE_HEAD,
            "read_only": True, "snapshot_sha256": SNAPSHOT_DIGEST,
            "manifest_ref": f"{publication_head}:{SNAPSHOT_PATH}"}


def validate_market_state_evidence(evidence: Mapping[str, Any], publication_head: str) -> dict[str, Any]:
    """Validate the independent small diagnostic without changing stage facts."""
    _require(bool(HEX40.fullmatch(publication_head)), "market_state_publication_invalid")
    payload = dict(evidence)
    observed_hash = payload.pop("evidence_hash", None)
    calculated_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    _require(observed_hash == calculated_hash == MARKET_STATE_EVIDENCE_HASH,
             "market_state_evidence_hash_mismatch")
    _require(evidence.get("schema_version") == "market_state_stage_diagnostic_v1"
             and evidence.get("selector") == SELECTOR
             and evidence.get("status") == "completed_exploratory_research_only"
             and evidence.get("truth_kind") == "historical_market_state_diagnostic"
             and evidence.get("usage") == "description_and_precommitted_entry_policy_design_only",
             "market_state_evidence_identity_invalid")
    protocol, source = evidence["protocol"], evidence["source"]
    _require(protocol == {
        "commit": "97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02",
        "path": "docs/research/market-state-conditional-policy-protocol-20260927.json",
        "protocol_id": "donchian-stage-market-state-v2-20260927",
        "sha256": "7eca70e55aa40d1f2db6e4c72b79a326bf73bd54d583a50347d7f34364e8d85e",
    } and source.get("stage_snapshot") == SNAPSHOT_PATH
      and source.get("stage_source_head") == SOURCE_HEAD
      and source.get("data_version") == "donchian-long-input-20260921-v2"
      and source.get("manifest_sha256") == "349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d"
      and source.get("aggregate_sha256") == "62bed3a6efa945d8fa4f52917667dc44a276add7ed280bb45085ef52950d10af"
      and source.get("physical_root_redacted") is True
      and bool(HEX40.fullmatch(source.get("publication_head_at_build", ""))),
      "market_state_source_invalid")
    description = evidence["description"]
    _require(description.get("definition_version") == "market_state_descriptive_v2"
             and all(bool(HEX64.fullmatch(description.get(key, ""))) for key in
                     ("definition_hash", "series_content_hash", "source_binding_hash"))
             and description.get("observed_bars") == 2960
             and description.get("unknown_bars") == 0
             and description.get("unknown_reason_counts") == {}
             and set(description.get("optional_input_coverage", {})) == {"funding", "open_interest", "depth"}
             and all(value == "missing_from_state_input" for value in
                     description["optional_input_coverage"].values()),
             "market_state_description_invalid")
    stratification = evidence["stratification"]
    _require(stratification.get("sample_units") == {
        "bars": 2960, "roundtrips": 28, "contiguous_state_segments": 170}
        and stratification.get("bar_groups") == {
            "low": {"bars": 2282}, "mixed": {"bars": 662},
            "directional": {"bars": 16}, "unknown": {"bars": 0}}
        and stratification.get("entry_join", {}).get("matched_roundtrips") == 28
        and stratification.get("entry_join", {}).get("nearest_time_matching") is False
        and len(stratification.get("entry_join", {}).get("entries", [])) == 28
        and stratification.get("funding") == {
            "allocation": "unavailable_per_trade",
            "total_only_usdt": "-0.012403344923245647991"}
        and stratification.get("prediction_metrics") == {
            "ic": "not_applicable", "rank_ic": "not_applicable"},
        "market_state_stratification_invalid")
    _require(sum(group.get("roundtrips", 0) for group in stratification["trade_groups"].values()) == 28
             and all(group.get("funding_usdt") is None for group in stratification["trade_groups"].values())
             and all(entry.get("funding_usdt") is None and bool(HEX64.fullmatch(entry.get("state_content_hash", "")))
                     for entry in stratification["entry_join"]["entries"]),
             "market_state_trade_group_invalid")
    trial, runtime = evidence["policy_trial"], evidence["runtime_status"]
    _require(trial.get("status") == "not_started" and trial.get("effect_verified") is False
             and trial.get("counterfactual_entry_count_only") == 18
             and trial.get("budget", {}).get("fixed_replays") == 2
             and trial.get("budget", {}).get("training_runs") == 0
             and trial.get("budget", {}).get("parameter_searches") == 0
             and runtime == {"attachment_consumed_by_btc_runtime": False,
                             "entry_policy_enabled": False,
                             "execution_effect_observed": False},
             "market_state_policy_trial_or_runtime_invalid")
    _require(all(evidence.get(flag) is False for flag in FLAGS),
             "market_state_safety_invalid")
    return {**evidence, "read_only": True, "publication_head": publication_head,
            "artifact_sha256": MARKET_STATE_FILE_SHA256,
            "manifest_ref": f"{publication_head}:{MARKET_STATE_PATH}"}


def _trial_unavailable(status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "market_policy_trial_read_model_v1",
        "trial_id": MARKET_POLICY_TRIAL_ID,
        "status": status,
        "effect_verified": False,
        "read_only": True,
        "reason": reason,
        **{flag: False for flag in TRIAL_SAFETY_FLAGS},
    }


def _validate_trial_arm(arm: Mapping[str, Any], arm_id: str, consumer_commit: str) -> None:
    expected = {
        "arm_id", "run_id", "source_commit", "run_identity_hash", "processed_events",
        "source_artifact_sha256", "ledger_receipt_sha256", "writer_finished_at_utc",
        "ledger_reconciled_at_utc",
        "new_entries_proposed", "new_entries_rejected", "new_entries_executed", "roundtrips",
        "exposure_contract_hours", "holding_hours", "price_pnl_usdt", "fee_cashflow_usdt",
        "funding_cashflow_usdt", "net_usdt", "drawdown_status", "max_drawdown_usdt",
        "exit_count", "protective_exit_count", "ledger_reconciled", "duplicate_order_count",
        "duplicate_fill_count", "final_position_contracts", "blocker_count",
    }
    _require(set(arm) == expected and arm.get("arm_id") == arm_id,
             "market_policy_trial_arm_schema_invalid")
    _require(isinstance(arm.get("run_id"), str) and arm["run_id"]
             and arm.get("source_commit") == consumer_commit
             and bool(HEX64.fullmatch(arm.get("run_identity_hash", "")))
             and bool(HEX64.fullmatch(arm.get("source_artifact_sha256", "")))
             and bool(HEX64.fullmatch(arm.get("ledger_receipt_sha256", "")))
             and arm.get("processed_events") == 2960,
             "market_policy_trial_arm_identity_invalid")
    writer_finished = _utc(arm.get("writer_finished_at_utc"))
    reconciled_at = _utc(arm.get("ledger_reconciled_at_utc"))
    _require(reconciled_at >= writer_finished, "market_policy_trial_arm_receipt_time_invalid")
    for key in ("new_entries_proposed", "new_entries_rejected", "new_entries_executed",
                "roundtrips", "exit_count", "protective_exit_count", "duplicate_order_count",
                "duplicate_fill_count", "blocker_count"):
        _require(type(arm.get(key)) is int and arm[key] >= 0,
                 "market_policy_trial_arm_count_invalid")
    _require(arm["new_entries_proposed"] == arm["new_entries_rejected"] + arm["new_entries_executed"]
             and arm["ledger_reconciled"] is True
             and arm["duplicate_order_count"] == 0 and arm["duplicate_fill_count"] == 0
             and arm["blocker_count"] == 0 and _decimal(arm["final_position_contracts"]) == 0,
             "market_policy_trial_arm_reconciliation_invalid")
    exposure, holding = _decimal(arm["exposure_contract_hours"]), _decimal(arm["holding_hours"])
    price, fee = _decimal(arm["price_pnl_usdt"]), _decimal(arm["fee_cashflow_usdt"])
    funding, net = _decimal(arm["funding_cashflow_usdt"]), _decimal(arm["net_usdt"])
    _require(exposure >= 0 and holding >= 0 and price + fee + funding == net,
             "market_policy_trial_arm_economics_invalid")
    _require(arm["drawdown_status"] == "computed_from_ledger"
             and _decimal(arm["max_drawdown_usdt"]) >= 0,
             "market_policy_trial_drawdown_invalid")


def _validate_blocked_trial_arm(arm: Mapping[str, Any], arm_id: str) -> None:
    expected = {
        "arm_id", "run_id", "status", "source_commit", "run_identity_hash",
        "source_artifact_sha256", "processed_events", "expected_events", "counts",
        "ledger_receipt", "terminal_position", "blockers", "blocked_event_time_utc",
    }
    _require(set(arm) == expected and arm.get("arm_id") == arm_id
             and arm.get("source_commit") == MARKET_POLICY_CONSUMER_COMMIT
             and all(bool(HEX64.fullmatch(arm.get(key, ""))) for key in
                     ("run_identity_hash", "source_artifact_sha256"))
             and arm.get("expected_events") == 2960
             and type(arm.get("processed_events")) is int
             and 0 <= arm["processed_events"] <= arm["expected_events"],
             "market_policy_trial_blocked_arm_schema_invalid")
    counts, receipt, position = arm["counts"], arm["ledger_receipt"], arm["terminal_position"]
    _require(set(counts) == {"fills", "orders", "new_entries_rejected",
             "nonzero_funding_cashflow_bills"}
             and all(type(counts.get(key)) is int and counts[key] >= 0 for key in counts),
             "market_policy_trial_blocked_arm_counts_invalid")
    _require(set(receipt) == {"file_sha256", "receipt_sha256", "last_sequence",
             "last_event_hash", "reconciled"}
             and all(bool(HEX64.fullmatch(receipt.get(key, ""))) for key in
                     ("file_sha256", "receipt_sha256", "last_event_hash"))
             and type(receipt.get("last_sequence")) is int and receipt["last_sequence"] > 0
             and receipt.get("reconciled") is True,
             "market_policy_trial_blocked_arm_receipt_invalid")
    _require(set(position) == {"position_contracts", "average_price", "status"},
             "market_policy_trial_blocked_arm_position_invalid")
    if arm_id == "original_donchian":
        _require(arm.get("run_id") == "donchian-market-entry-baseline-20260927"
                 and arm.get("status") == "completed"
                 and arm.get("processed_events") == 2960
                 and counts == {"fills": 56, "orders": 56, "new_entries_rejected": 0,
                                "nonzero_funding_cashflow_bills": 24}
                 and receipt == {
                    "file_sha256": "3913b1706617d96e030b1e468699205bc8642a3518bbaecfdad071013b0d2d9c",
                    "receipt_sha256": "bc1f3041f517689f818d1b0f3a47f6c296567cd78e929f8303465b51892321d4",
                    "last_sequence": 14874,
                    "last_event_hash": "ce5d234628d03ca22edc9e0db36f32b06bd18a9631363b4bb438f78f6bfa2bab",
                    "reconciled": True,
                 }
                 and _decimal(position.get("position_contracts")) == 0
                 and _decimal(position.get("average_price")) == 0
                 and position.get("status") == "flat"
                 and arm.get("blockers") == []
                 and arm.get("blocked_event_time_utc") is None,
                 "market_policy_trial_blocked_baseline_invalid")
    else:
        _require(arm.get("run_id") == "donchian-market-entry-conditioned-20260927"
                 and arm.get("status") == "blocked_fail_closed"
                 and arm.get("processed_events") == 1956
                 and counts == {"fills": 17, "orders": 17, "new_entries_rejected": 48,
                                "nonzero_funding_cashflow_bills": 14}
                 and receipt == {
                    "file_sha256": "f1d98c214648595891f4d44bd9a90051c971eee73e62ea234f373df54e2f8fc3",
                    "receipt_sha256": "79423c9c6a3c9fe56b299ef92ff2c5316b715344effb2d70278a115385e94fcd",
                    "last_sequence": 9807,
                    "last_event_hash": "e799b5f8163473649e1df22a740e1486b60d2048259a3627b25ca954c2396b2c",
                    "reconciled": True,
                 }
                 and _decimal(position.get("position_contracts")) == Decimal("-0.01")
                 and _decimal(position.get("average_price")) == Decimal("82667.566415")
                 and position.get("status") == "nonflat_blocked_preserved"
                 and arm.get("blockers") == [
                    "ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous"]
                 and arm.get("blocked_event_time_utc") == "2025-11-21T20:00:00+08:00",
                 "market_policy_trial_blocked_conditioned_invalid")


def _metric(value: Any, *, minimum: Decimal | None = None,
            maximum: Decimal | None = None, nullable: bool = False) -> Decimal | None:
    if value is None:
        _require(nullable, "market_policy_trial_state_metric_invalid")
        return None
    result = _decimal(value)
    _require((minimum is None or result >= minimum)
             and (maximum is None or result <= maximum),
             "market_policy_trial_state_metric_invalid")
    return result


def _validate_selected_state(state: Mapping[str, Any], entry: Mapping[str, Any]) -> None:
    expected = {
        "projection_source", "projection_status", "missing_fields", "asset", "decision_time",
        "cutoff_time", "status", "reasons", "direction_score",
        "direction_label", "normalized_trend_strength", "path_efficiency_by_horizon",
        "multi_scale_agreement", "bar_volatility", "annualized_volatility",
        "volatility_relative_position", "volatility_expansion_ratio", "volatility_regime",
        "shock_score", "direction_persistence", "switching_frequency", "definition_version",
        "definition_hash", "source_binding_hash", "input_hash", "content_hash",
    }
    _require(set(state) == expected and state.get("asset") == "BTC-USDT-SWAP"
             and state.get("projection_source") in {"consumer_phase", "exact_state_hash_join"}
             and state.get("projection_status") in {"complete", "partial"}
             and state.get("definition_version") == entry["state_version"]
             and state.get("definition_hash") == entry["state_definition_hash"]
             and state.get("source_binding_hash") == entry["state_source_binding_hash"]
             and state.get("input_hash") == entry["state_input_hash"]
             and state.get("content_hash") == entry["state_content_hash"]
             and state.get("status") == entry["state_status"]
             and state.get("reasons") == entry["state_reasons"],
             "market_policy_trial_selected_state_identity_invalid")
    decision_time, cutoff_time = _utc(state.get("decision_time")), _utc(state.get("cutoff_time"))
    _require(cutoff_time <= decision_time and state.get("cutoff_time") == entry["state_cutoff_utc"],
             "market_policy_trial_selected_state_time_invalid")
    reasons = state.get("reasons")
    _require(isinstance(reasons, list) and all(isinstance(reason, str) and reason for reason in reasons),
             "market_policy_trial_selected_state_quality_invalid")
    horizons = state.get("path_efficiency_by_horizon")
    _require(isinstance(horizons, Mapping) and set(horizons) == {"24", "72", "168"},
             "market_policy_trial_selected_state_horizons_invalid")
    observed = state.get("status") == "observed"
    _require(state.get("status") in {"observed", "unknown"}
             and ((observed and reasons == []) or (not observed and bool(reasons))),
             "market_policy_trial_selected_state_quality_invalid")
    tracked = {
        "direction_score": state.get("direction_score"),
        "direction_label": state.get("direction_label"),
        "normalized_trend_strength": state.get("normalized_trend_strength"),
        "path_efficiency_by_horizon.24": horizons.get("24"),
        "path_efficiency_by_horizon.72": horizons.get("72"),
        "path_efficiency_by_horizon.168": horizons.get("168"),
        "multi_scale_agreement": state.get("multi_scale_agreement"),
        "bar_volatility": state.get("bar_volatility"),
        "annualized_volatility": state.get("annualized_volatility"),
        "volatility_relative_position": state.get("volatility_relative_position"),
        "volatility_expansion_ratio": state.get("volatility_expansion_ratio"),
        "volatility_regime": state.get("volatility_regime"),
        "shock_score": state.get("shock_score"),
        "direction_persistence": state.get("direction_persistence"),
        "switching_frequency": state.get("switching_frequency"),
    }
    missing = state.get("missing_fields")
    _require(isinstance(missing, list) and missing == sorted(set(missing))
             and set(missing) == {name for name, value in tracked.items() if value is None}
             and all(name in tracked for name in missing)
             and state.get("projection_status") == ("complete" if not missing else "partial")
             and (state.get("projection_source") != "consumer_phase" or bool(missing)),
             "market_policy_trial_selected_state_projection_invalid")
    _metric(state.get("direction_score"), minimum=Decimal("-1"), maximum=Decimal("1"), nullable=True)
    _require(state.get("direction_label") in {"up", "down", "flat", None},
             "market_policy_trial_selected_state_direction_invalid")
    _metric(state.get("normalized_trend_strength"), minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    for value in horizons.values():
        _metric(value, minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    _metric(state.get("multi_scale_agreement"), minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    _metric(state.get("bar_volatility"), minimum=Decimal("0"), nullable=True)
    _metric(state.get("annualized_volatility"), minimum=Decimal("0"), nullable=True)
    _metric(state.get("volatility_relative_position"), minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    _metric(state.get("volatility_expansion_ratio"), minimum=Decimal("0"), nullable=True)
    _require(state.get("volatility_regime") in {"contracting", "stable", "expanding", None},
             "market_policy_trial_selected_state_volatility_invalid")
    _metric(state.get("shock_score"), minimum=Decimal("0"), nullable=True)
    _metric(state.get("direction_persistence"), minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    _metric(state.get("switching_frequency"), minimum=Decimal("0"), maximum=Decimal("1"), nullable=True)
    if observed:
        _require(entry.get("reason") == "path_efficiency_below_threshold"
                 and (horizons["72"] is None
                      or _metric(horizons["72"], minimum=Decimal("0"), maximum=Decimal("1")) < Decimal("0.20")),
                 "market_policy_trial_selected_state_policy_mismatch")
    else:
        _require(entry.get("reason") == "state_unknown",
                 "market_policy_trial_selected_state_policy_mismatch")


def validate_market_policy_trial_evidence(evidence: Mapping[str, Any],
                                          publication_head: str) -> dict[str, Any]:
    """Validate one future sealed two-arm result without replaying either arm."""
    _require(bool(HEX40.fullmatch(publication_head)), "market_policy_trial_publication_invalid")
    expected_top = {
        "schema_version", "trial_id", "status", "truth_kind", "usage", "protocol", "source",
        "consumer_binding", "window", "arms", "comparison", "invariants", "decision_effects",
        "limitations", "report_hash", *TRIAL_SAFETY_FLAGS,
    }
    _require(set(evidence) == expected_top
             and evidence.get("schema_version") == "market_policy_trial_report_v1"
             and evidence.get("trial_id") == MARKET_POLICY_TRIAL_ID
             and evidence.get("status") == "completed_exploratory_research_only"
             and evidence.get("truth_kind") == "offline_policy_ab_replay"
             and evidence.get("usage") == "policy_effect_estimation_only_not_promotion",
             "market_policy_trial_identity_invalid")
    unsigned = dict(evidence)
    observed_hash = unsigned.pop("report_hash", None)
    calculated_hash = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    _require(observed_hash == calculated_hash, "market_policy_trial_report_hash_mismatch")
    _require(evidence.get("protocol") == {
        "protocol_id": "donchian-stage-market-state-v2-20260927",
        "commit": "97d8ad21dda3317afae0bfa7f1bf68ff0ce1ed02",
        "sha256": "7eca70e55aa40d1f2db6e4c72b79a326bf73bd54d583a50347d7f34364e8d85e",
    }, "market_policy_trial_protocol_invalid")
    _require(evidence.get("source") == {
        "stage_selector": SELECTOR,
        "stage_source_head": SOURCE_HEAD,
        "stage_snapshot_sha256": "48aaba75b02a2d257abf5196d9c4490c52f4f14356c17a64a41703fb3d6add14",
        "diagnostic_artifact_sha256": MARKET_STATE_FILE_SHA256,
        "diagnostic_evidence_hash": MARKET_STATE_EVIDENCE_HASH,
        "data_version": "donchian-long-input-20260921-v2",
        "manifest_sha256": "349bd130a769796a71877f48ab7aa597338303ece8b124d4b9e23a3759e3993d",
        "aggregate_sha256": "62bed3a6efa945d8fa4f52917667dc44a276add7ed280bb45085ef52950d10af",
    }, "market_policy_trial_source_invalid")
    consumer = evidence["consumer_binding"]
    _require(set(consumer) == {"source_commit", "attachment_hash", "base_strategy_binding_hash",
             "policy_hash", "state_definition_hash", "state_source_binding_hash"}
             and consumer.get("source_commit") == MARKET_POLICY_CONSUMER_COMMIT
             and all(bool(HEX64.fullmatch(consumer.get(key, ""))) for key in (
                 "attachment_hash", "base_strategy_binding_hash", "policy_hash",
                 "state_definition_hash", "state_source_binding_hash"))
             and consumer["state_definition_hash"] ==
                 "c3313cf3de4bf56e8edc918f73ead7e9f5e6ab2b9a43d45a0b64b8eb10ee4624"
             and consumer["state_source_binding_hash"] ==
                 "79de6c8c2ece98c17c813fa0003480c975e5cc933c69d511142872ea4fe4b54a"
             and consumer["policy_hash"] ==
                 "1a5cc01f906a4cf244fa0e8a18b9cd3f30130ccfa1b3fed7e125af5c490fbe2b",
             "market_policy_trial_consumer_binding_invalid")
    _require(evidence.get("window") == {
        "analysis_start_utc": "2025-09-01T00:00:00+00:00",
        "analysis_end_exclusive_utc": "2026-01-02T08:00:00+00:00",
        "expected_events": 2960, "warmup_hours": 4800, "bar_size": "1h",
    }, "market_policy_trial_window_invalid")
    arms = evidence["arms"]
    _require(set(arms) == {"original_donchian", "original_donchian_plus_frozen_entry_policy"},
             "market_policy_trial_arms_invalid")
    baseline, policy = arms["original_donchian"], arms["original_donchian_plus_frozen_entry_policy"]
    _validate_trial_arm(baseline, "original_donchian", consumer["source_commit"])
    _validate_trial_arm(policy, "original_donchian_plus_frozen_entry_policy", consumer["source_commit"])
    _require(baseline["run_id"] == "donchian-market-entry-baseline-20260927"
             and policy["run_id"] == "donchian-market-entry-conditioned-20260927"
             and baseline["new_entries_rejected"] == 0,
             "market_policy_trial_baseline_rejection_invalid")
    comparison = evidence["comparison"]
    _require(set(comparison) == {"new_entries_rejected_delta", "roundtrips_delta",
             "exposure_contract_hours_delta", "holding_hours_delta", "net_usdt_delta",
             "max_drawdown_usdt_delta", "effect_interpretation",
             "improvement_claim_supported", "promotion_supported"}
             and comparison["new_entries_rejected_delta"] ==
                 policy["new_entries_rejected"] - baseline["new_entries_rejected"]
             and comparison["roundtrips_delta"] == policy["roundtrips"] - baseline["roundtrips"]
             and _decimal(comparison["exposure_contract_hours_delta"]) ==
                 _decimal(policy["exposure_contract_hours"]) - _decimal(baseline["exposure_contract_hours"])
             and _decimal(comparison["holding_hours_delta"]) ==
                 _decimal(policy["holding_hours"]) - _decimal(baseline["holding_hours"])
             and _decimal(comparison["net_usdt_delta"]) ==
                 _decimal(policy["net_usdt"]) - _decimal(baseline["net_usdt"])
             and _decimal(comparison["max_drawdown_usdt_delta"]) ==
                 _decimal(policy["max_drawdown_usdt"]) - _decimal(baseline["max_drawdown_usdt"])
             and comparison["effect_interpretation"] == "exploratory_only"
             and comparison["improvement_claim_supported"] is False
             and comparison["promotion_supported"] is False,
             "market_policy_trial_comparison_invalid")
    _require(evidence.get("invariants") == {
        "same_base_strategy": True, "same_data": True, "same_cost": True,
        "same_time_contract": True, "same_simulated_account": True,
        "no_training": True, "no_parameter_search": True,
        "entry_policy_only_changed_new_entry": True,
        "existing_position_exit_and_protection_not_overridden": True,
    }, "market_policy_trial_invariants_invalid")
    effects = evidence["decision_effects"]
    _require(isinstance(effects, list) and len(effects) == policy["new_entries_rejected"],
             "market_policy_trial_effect_count_invalid")
    seen: set[str] = set()
    for effect in effects:
        _require(set(effect) == {"event_id", "phase", "market_entry_policy", "selected_state", "evidence_links"}
                 and isinstance(effect.get("event_id"), str) and effect["event_id"] not in seen
                 and effect.get("phase") == "market_entry_policy",
                 "market_policy_trial_effect_identity_invalid")
        seen.add(effect["event_id"])
        entry, links = effect["market_entry_policy"], effect["evidence_links"]
        _require(set(entry) == {"usage", "attachment_hash", "policy_id", "policy_version",
                 "policy_hash", "state_version", "state_definition_hash",
                 "state_source_binding_hash", "state_content_hash", "state_input_hash",
                 "state_status", "state_reasons", "state_cutoff_utc", "original_target_contracts",
                 "effective_target_contracts", "applied", "reason", "existing_position_contracts",
                 "state_binding_status"}
                 and entry["usage"] == "research_replay_entry_only"
                 and entry["attachment_hash"] == consumer["attachment_hash"]
                 and entry["policy_id"] == "market_state_entry_admission"
                 and entry["policy_version"] == "entry_path_efficiency_72h_v1"
                 and entry["policy_hash"] == consumer["policy_hash"]
                 and entry["state_version"] == "market_state_descriptive_v2"
                 and entry["state_definition_hash"] == consumer["state_definition_hash"]
                 and entry["state_source_binding_hash"] == consumer["state_source_binding_hash"]
                 and bool(HEX64.fullmatch(entry["state_content_hash"]))
                 and bool(HEX64.fullmatch(entry["state_input_hash"]))
                 and entry["state_status"] in {"observed", "unknown"}
                 and isinstance(entry["state_reasons"], list)
                 and entry["applied"] is True
                 and entry["reason"] in {"path_efficiency_below_threshold", "state_unknown"}
                 and entry["state_binding_status"] == "verified"
                 and _decimal(entry["original_target_contracts"]) != 0
                 and _decimal(entry["effective_target_contracts"]) == 0
                 and _decimal(entry["existing_position_contracts"]) == 0,
                 "market_policy_trial_effect_policy_invalid")
        _utc(entry["state_cutoff_utc"])
        _validate_selected_state(effect["selected_state"], entry)
        _require(set(links) == {"decision_outcome", "signal_id", "target_position_id",
                 "risk_check_id", "order_intent_id", "client_order_id", "exchange_order_id",
                 "fill_ids", "ledger_event_id", "ledger_event_hash", "action"}
                 and links["decision_outcome"] == "rejected_new_entry"
                 and isinstance(links["signal_id"], str) and links["signal_id"]
                 and isinstance(links["target_position_id"], str) and links["target_position_id"]
                 and links["risk_check_id"] is None and links["order_intent_id"] is None
                 and links["client_order_id"] is None and links["exchange_order_id"] is None
                 and links["fill_ids"] == [] and links["ledger_event_id"] is None
                 and links["ledger_event_hash"] is None and links["action"] == "no_order",
                 "market_policy_trial_effect_links_invalid")
    _require(isinstance(evidence.get("limitations"), list)
             and {"exploratory_28_roundtrip_source_sample", "not_promotion_evidence"}.issubset(
                 evidence["limitations"])
             and all(evidence.get(flag) is False for flag in TRIAL_SAFETY_FLAGS),
             "market_policy_trial_limits_or_safety_invalid")
    return {**evidence, "read_only": True, "effect_verified": True,
            "publication_head": publication_head,
            "manifest_ref": f"{publication_head}:{MARKET_POLICY_TRIAL_PATH}"}


def validate_market_policy_trial_blocked_evidence(evidence: Mapping[str, Any],
                                                  publication_head: str) -> dict[str, Any]:
    """Validate a sealed fail-closed partial trial without deriving an A/B effect."""
    _require(bool(HEX40.fullmatch(publication_head)), "market_policy_trial_publication_invalid")
    expected_top = {
        "schema_version", "trial_id", "status", "truth_kind", "usage", "source_evidence",
        "consumer_binding", "window", "arms", "comparison", "runtime_budget",
        "rejected_entry_phase_count", "limitations", "safety", "projection_hash",
    }
    _require(set(evidence) == expected_top
             and evidence.get("schema_version") == "market_policy_trial_blocked_read_model_v1"
             and evidence.get("trial_id") == MARKET_POLICY_TRIAL_ID
             and evidence.get("status") == "blocked_fail_closed"
             and evidence.get("truth_kind") == "sealed_blocked_stage_read_model"
             and evidence.get("usage") ==
                 "blocked_stage_diagnostic_only_not_effect_estimation_not_promotion",
             "market_policy_trial_blocked_identity_invalid")
    unsigned = dict(evidence)
    observed_hash = unsigned.pop("projection_hash", None)
    calculated_hash = hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    _require(observed_hash == calculated_hash ==
             "9ac585fde969c26c03bd46b9fefb2922add03005acd89faa31e03d2bb998eac9",
             "market_policy_trial_report_hash_mismatch")
    _require(evidence.get("source_evidence") == {
        "manifest_ref": "c26a6046f4a0412281b630b2f31a8ea77504d240:docs/research/donchian-market-policy-ab-blocked-stage-20260927.md",
        "manifest_sha256": "e9cac97788ccff223657174246bfcdd96e8e450683b700fd7a80b34335a1f9af",
        "summary_file_sha256": "5251cb9e11d3ff3160001a07a1e9d93ef1648334e09006bdbed66cc137a60084",
        "summary_report_hash": "9361be7e2bac7b58b940f4f02594a2a14d5f0d8d63722bf1508620acee1d9b79",
    }, "market_policy_trial_source_invalid")
    consumer = evidence["consumer_binding"]
    _require(consumer == {
             "source_commit": MARKET_POLICY_CONSUMER_COMMIT,
             "python_version": "3.11.15",
             "pandas_version": "3.0.4",
             "state_projection": "consumer_phase_partial_no_cross_environment_exact_join",
             "state_source_binding_hash":
                 "1141ae6bf0aa9d47a5250a37450ebde0b4859e93b890f1360ac21572a2591f20",
             }
             and consumer.get("source_commit") == MARKET_POLICY_CONSUMER_COMMIT
             and bool(HEX64.fullmatch(consumer["state_source_binding_hash"])),
             "market_policy_trial_consumer_binding_invalid")
    _require(evidence.get("window") == {
        "analysis_start_utc": "2025-09-01T08:00:00+08:00",
        "analysis_end_exclusive_utc": "2026-01-02T16:00:00+08:00",
        "expected_events": 2960, "warmup_hours": 4800, "bar_size": "1h",
    }, "market_policy_trial_window_invalid")
    arms = evidence["arms"]
    _require(set(arms) == {"original_donchian", "original_donchian_plus_frozen_entry_policy"},
             "market_policy_trial_arms_invalid")
    _validate_blocked_trial_arm(arms["original_donchian"], "original_donchian")
    _validate_blocked_trial_arm(arms["original_donchian_plus_frozen_entry_policy"],
                                "original_donchian_plus_frozen_entry_policy")
    _require(evidence.get("comparison") == {
        "status": "unavailable_incomplete_conditioned_arm", "effect_verified": False,
        "improvement_claim_supported": False, "promotion_supported": False,
    } and evidence.get("runtime_budget") == {
        "baseline_elapsed_seconds": "7259.479", "baseline_limit_seconds": "7200",
        "baseline_limit_exceeded_seconds": "59.479", "total_limit_seconds": "14400",
    } and evidence.get("rejected_entry_phase_count") == 48,
             "market_policy_trial_blocked_result_invalid")
    _require(evidence.get("limitations") == [
        "conditioned_arm_incomplete_1956_of_2960",
        "intrabar_protection_double_touch_order_unknown_fail_closed",
        "conditioned_arm_ended_with_open_short_minus_0_01_contracts",
        "no_complete_ab_effect_estimate",
        "no_authoritative_ledger_drawdown_comparison_published",
        "consumer_state_projection_partial",
        "python_3_11_pandas_3_0_4_hashes_not_interchangeable_with_historical_python_3_14_pandas_3_0_3_diagnostic",
        "baseline_arm_exceeded_120_minute_budget_by_59_479_seconds",
        "exploratory_only_not_promotion_evidence",
    ] and evidence.get("safety") == {
        "demo_enabled": False, "paper_enabled": False, "live_enabled": False,
        "promotion_enabled": False, "private_endpoint_accessed": False,
        "real_order_submitted": False, "network_accessed": False, "runtime_observed": False,
    },
             "market_policy_trial_limits_or_safety_invalid")
    return {**evidence, "read_only": True, "effect_verified": False,
            "publication_head": publication_head,
            "manifest_ref": f"{publication_head}:{MARKET_POLICY_TRIAL_PATH}"}


def _read_market_policy_trial(repo_root: Path, publication_head: str) -> dict[str, Any]:
    try:
        raw = subprocess.check_output(["git", "show", f"{publication_head}:{MARKET_POLICY_TRIAL_PATH}"],
                                      cwd=repo_root, timeout=5, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return _trial_unavailable("not_started", "sealed_policy_trial_report_not_found_or_invalid")
    try:
        _require(len(raw) < 250_000, "market_policy_trial_report_oversize")
        evidence = json.loads(raw)
        validated = (validate_market_policy_trial_blocked_evidence(evidence, publication_head)
                     if evidence.get("schema_version") == "market_policy_trial_blocked_read_model_v1"
                     else validate_market_policy_trial_evidence(evidence, publication_head))
        return {**validated, "artifact_sha256": hashlib.sha256(raw).hexdigest()}
    except (UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return _trial_unavailable("blocked", "sealed_policy_trial_report_invalid")


def _read_market_state_evidence(repo_root: Path, publication_head: str) -> dict[str, Any]:
    blocked = {"status": "blocked", "read_only": True,
               "reason": "market_state_diagnostic_missing_or_invalid",
               **{flag: False for flag in FLAGS}}
    try:
        raw = subprocess.check_output(["git", "show", f"{publication_head}:{MARKET_STATE_PATH}"],
                                      cwd=repo_root, timeout=5)
        _require(len(raw) < 100_000 and hashlib.sha256(raw).hexdigest() == MARKET_STATE_FILE_SHA256,
                 "market_state_artifact_file_invalid")
        evidence = validate_market_state_evidence(json.loads(raw), publication_head)
        return {**evidence, "policy_trial_evidence": _read_market_policy_trial(repo_root, publication_head)}
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return blocked


def read_stage_snapshot(repo_root: Path, selector: str) -> dict[str, Any]:
    blocked = {"selector": selector, "read_only": True, "truth_kind": "offline_execution_simulation",
               "permissions": {flag: False for flag in FLAGS}}
    if selector != SELECTOR:
        return {**blocked, "status": "not_bound", "reason": "donchian_stage_selector_not_registered"}
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root,
                                       timeout=5).decode("ascii").strip()
        raw = subprocess.check_output(["git", "show", f"{head}:{SNAPSHOT_PATH}"],
                                      cwd=repo_root, timeout=5)
        _require(len(raw) < 100_000, "donchian_stage_snapshot_oversize")
        stage = validate_stage_snapshot(json.loads(raw), head)
        return {**stage, "market_state_evidence": _read_market_state_evidence(repo_root, head)}
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError, TypeError, AttributeError):
        return {**blocked, "status": "blocked", "reason": "donchian_stage_snapshot_missing_or_invalid"}
