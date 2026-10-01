"""Committed Donchian offline receipt; HTTP reads never execute a replay."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from quant_shared.strategy_runtime.decision_envelope import package_digest


SELECTOR = "donchian-v3-closeout-20260920"
SOURCE_HEAD = "e024f42468f4d0a7c39b83fe28ed86c5688459aa"
SUMMARY_SHA256 = "a83e6745d485c0ce2e90259f284128722c4ae744d0bd8212d6114b7d8ce89a9a"
REPORT_PATH = ".agent/offline_evidence/donchian-v3-closeout-20260920.json"
FIXTURE_PATH = "tests/fixtures/strategy_v1/offline_contract.json"
SCHEMA = "donchian_offline_closeout_v1"
SEAL_SCHEMA = "donchian_offline_closeout_seal_v1"
FLAGS = ("demo_control_enabled", "execution_permission", "live", "order", "paper",
         "private", "promotion", "real_order", "runtime_observed", "transfer", "withdraw")
PHASES = ("primary", "hold", "reversal_close", "reversal_open", "exit")
CHECKPOINTS = ("open_long", "hold_long", "reverse_to_short", "reverse_to_short", "exit_short")
PHASE_ACTIONS = {"primary": ("open_long", "buy", "long", 1),
                 "reversal_close": ("close_long", "sell", "long", -1),
                 "reversal_open": ("open_short", "sell", "short", -1),
                 "exit": ("close_short", "buy", "short", 1)}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def seal_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": SEAL_SCHEMA, "summary": summary, "sha256": digest(summary)}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _money(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("donchian_money_invalid") from exc
    _require(number.is_finite(), "donchian_money_invalid")
    return number


def _stage(result: Mapping[str, Any], runner: Any, checkpoint: str, completed_bar: str) -> dict[str, Any]:
    """Project only recorded events, after the original runtime has committed them."""
    evidence = dict(result["evidence"])
    links = evidence["links"]
    ordered = links["decision_outcome"] == "order_terminal"
    order = None
    ledger = None
    if ordered:
        matches = [row for row in runner.venue.state["orders"]
                   if row.get("clOrdId") == links["client_order_id"]
                   and row.get("ordId") == links["exchange_order_id"]]
        _require(len(matches) == 1, "donchian_order_source_not_exact")
        order = dict(matches[0])
        event = result["ledger"]
        _require(bool(event), "donchian_ledger_source_missing")
        raw = event["payload"]
        projection = {key: raw[key] for key in ("cash_ledger", "position_ledger",
                      "fill_ledger", "funding_ledger", "order_ledger")}
        ledger = {
            "event_id": event["idempotency_key"], "event_hash": event["event_hash"],
            "sequence": event["sequence"], "raw_payload_sha256": digest(raw),
            "projection": projection, "projection_sha256": digest(projection),
        }
    row = {
        "checkpoint": checkpoint, "phase": result["phase"],
        "completed_bar_close_utc": completed_bar,
        "evidence": evidence,
        "signal": dict(result.get("signal") or {}),
        "target_position": dict(result.get("target_position") or {}),
        "risk_decision": {key: result["risk_decision"].get(key)
                          for key in ("risk_check_id", "approved", "reason")}
                         if ordered else None,
        "order_plan": {key: result["order_plan"].get(key)
                       for key in ("action", "client_order_id", "contracts",
                                   "position_before_contracts", "position_after_contracts",
                                   "reversal_close_only", "risk_reducing_only")}
                      if ordered else None,
        "order": order, "fills": list(result["fills"]), "ledger": ledger,
        "after": {"position_contracts": result["position_contracts"],
                  "equity_usdt": result["equity_usdt"],
                  "submitted_orders": result["submit_count"], "fill_count": result["fill_count"]},
    }
    return {**row, "stage_sha256": digest(row)}


def build_donchian_summary(*, runner: Any, fixture: dict[str, Any],
                           fixture_bytes: bytes, results: list[tuple[str, str, Mapping[str, Any], Any]]) -> dict[str, Any]:
    stages = [_stage(result, source_runner, checkpoint, completed_bar)
              for checkpoint, completed_bar, result, source_runner in results]
    final = results[-1][2]
    summary = {
        "schema_version": SCHEMA, "selector": SELECTOR,
        "truth_kind": "offline_execution_simulation", "status": "sealed_offline_summary",
        "source_head": runner.source_head, "identity": dict(runner.identity),
        "fixture_path": FIXTURE_PATH, "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "scenario": {"market_data_usage": fixture["market_data_usage"],
                     "simulated_execution_price": fixture["simulated_execution_price"],
                     "mark_price": fixture["mark_price"], "index_price": fixture["index_price"],
                     "fee_rate": fixture["fee_rate"], "funding_rate": fixture["funding_rate"],
                     "account_id": "offline-account", "initial_equity_usdt": "5000"},
        "counts": {"decisions": len(stages), "orders": final["submit_count"],
                   "fills": final["fill_count"],
                   "ledger_events": sum(stage["ledger"] is not None for stage in stages)},
        "final": {"position_contracts": final["position_contracts"],
                  "equity_usdt": final["equity_usdt"],
                  "fee_cashflow_usdt": str(sum((_money(fill["fee"]) for stage in stages
                                                       for fill in stage["fills"]), Decimal(0))),
                  "funding_cashflow_usdt": stages[-1]["ledger"]["projection"]["funding_ledger"]["cashflow"]},
        "stages": stages, "permissions": {key: False for key in FLAGS},
    }
    return summary


def validate_donchian_summary(envelope: Mapping[str, Any], expected_identity: Mapping[str, Any],
                              current_head: str, fixture_bytes: bytes) -> dict[str, Any]:
    _require(envelope.get("schema_version") == SEAL_SCHEMA, "donchian_seal_schema_invalid")
    summary = envelope["summary"]
    _require(envelope.get("sha256") == digest(summary), "donchian_seal_digest_mismatch")
    _require(summary.get("schema_version") == SCHEMA and summary.get("selector") == SELECTOR,
             "donchian_summary_identity_invalid")
    _require(summary.get("truth_kind") == "offline_execution_simulation"
             and summary.get("status") == "sealed_offline_summary", "donchian_truth_kind_invalid")
    _require(all(summary.get("permissions", {}).get(flag) is False for flag in FLAGS),
             "donchian_permissions_invalid")
    identity = summary["identity"]
    _require(identity.get("run_id") == "v3donchian01"
             and identity.get("instrument_id") == "BTC-USDT-SWAP"
             and identity.get("data_version") == "v1-closeout-continuous-ohlcv-v1",
             "donchian_run_identity_invalid")
    for key in ("strategy_id", "strategy_version", "params_hash"):
        _require(identity.get(key) == expected_identity.get(key), f"donchian_{key}_mismatch")
    source_head = summary.get("source_head", "")
    _require(source_head == SOURCE_HEAD and identity.get("code_version") == source_head,
             "donchian_source_head_invalid")
    _require(identity.get("package_digest") == package_digest(
        strategy_id=identity["strategy_id"], strategy_version=identity["strategy_version"],
        params_hash=identity["params_hash"], code_version=source_head),
        "donchian_package_digest_mismatch")
    _require(identity.get("identity_digest") == digest({k: v for k, v in identity.items()
                                                       if k != "identity_digest"}),
             "donchian_identity_digest_mismatch")
    _require(summary.get("fixture_path") == FIXTURE_PATH
             and summary.get("fixture_sha256") == hashlib.sha256(fixture_bytes).hexdigest(),
             "donchian_fixture_mismatch")
    fixture = json.loads(fixture_bytes)
    contracts = _money(fixture["target_contracts"])
    lot = _money(fixture["lot_size_contracts"])
    contract_value = _money(fixture["contract_value_btc"])
    execution_price = _money(fixture["simulated_execution_price"])
    expected_fee = _money(fixture["expected"]["fee_per_fill_usdt"])
    _require(contracts > 0 and lot > 0 and contracts % lot == 0
             and contract_value > 0 and execution_price > 0
             and contracts * contract_value * execution_price * _money(fixture["fee_rate"]) == expected_fee,
             "donchian_fixture_units_invalid")
    scenario = summary["scenario"]
    _require(all(scenario.get(key) == fixture.get(key) for key in
                 ("market_data_usage", "simulated_execution_price", "mark_price", "index_price",
                  "fee_rate", "funding_rate"))
             and scenario.get("account_id") == "offline-account"
             and _money(scenario.get("initial_equity_usdt")) == Decimal("5000"),
             "donchian_scenario_mismatch")
    stages = summary.get("stages", [])
    _require(isinstance(stages, list) and len(stages) == 5,
             "donchian_stage_count_invalid")
    _require(tuple(row.get("phase") for row in stages) == PHASES
             and tuple(row.get("checkpoint") for row in stages) == CHECKPOINTS,
             "donchian_stage_sequence_invalid")
    last_orders = last_fills = last_sequence = 0
    previous_equity = Decimal("5000")
    previous_position = Decimal(0)
    total_fees = total_funding = Decimal(0)
    seen_decisions: set[str] = set()
    seen_orders: set[str] = set()
    seen_fills: set[str] = set()
    for row in stages:
        _require(row.get("stage_sha256") == digest({key: value for key, value in row.items()
                                                   if key != "stage_sha256"}),
                 "donchian_stage_digest_mismatch")
        evidence = row["evidence"]
        links = evidence["links"]
        _require(evidence.get("schema_version") == "strategy_decision_evidence_v2"
                 and evidence.get("evidence_kind") == "offline_execution"
                 and evidence.get("runtime_observed") is False
                 and all(evidence.get(key) == identity.get(binding) for key, binding in
                         (("run_id", "run_id"), ("strategy_id", "strategy_id"),
                          ("strategy_version", "strategy_version"), ("code_version", "code_version"),
                          ("data_version", "data_version"), ("package_digest", "package_digest")))
                 and evidence.get("phase") == row["phase"]
                 and bool(HEX64.fullmatch(evidence.get("event_id", "")))
                 and bool(HEX64.fullmatch(evidence.get("input_digest", "")))
                 and bool(HEX64.fullmatch(evidence.get("context_digest", ""))),
                 "donchian_decision_binding_invalid")
        expected_decision = digest({"package_digest": identity["package_digest"],
                                    "run_id": identity["run_id"], "event_id": evidence["event_id"],
                                    "phase": row["phase"], "input_digest": evidence["input_digest"]})
        _require(evidence.get("decision_id") == expected_decision
                 and expected_decision not in seen_decisions,
                 "donchian_decision_id_invalid")
        seen_decisions.add(expected_decision)
        expected_bar = fixture["scenario"]["checkpoint_offsets"][row["checkpoint"]]
        start = datetime.fromisoformat(fixture["scenario"]["start_utc"])
        observed_bar = datetime.fromisoformat(row["completed_bar_close_utc"])
        _require(observed_bar == start + timedelta(hours=expected_bar),
                 "donchian_bar_binding_invalid")
        ordered = row["phase"] != "hold"
        after = row["after"]
        _require(type(after.get("submitted_orders")) is int and type(after.get("fill_count")) is int,
                 "donchian_counts_invalid")
        if not ordered:
            _require(links.get("decision_outcome") == "no_order"
                     and all(links.get(key) is None for key in
                             ("order_intent_id", "client_order_id", "exchange_order_id",
                              "ledger_event_id", "ledger_event_hash"))
                     and links.get("fill_ids") == [] and row["order"] is None
                     and row["fills"] == [] and row["ledger"] is None
                     and row["risk_decision"] is None and row["order_plan"] is None
                     and after["submitted_orders"] == last_orders
                     and after["fill_count"] == last_fills
                     and _money(after["equity_usdt"]) == previous_equity
                     and _money(after["position_contracts"]) == previous_position,
                     "donchian_hold_has_economic_event")
        else:
            order, fills, ledger = row["order"], row["fills"], row["ledger"]
            plan, risk = row["order_plan"], row["risk_decision"]
            action, side, position_side, direction = PHASE_ACTIONS[row["phase"]]
            position_after = previous_position + contracts * direction
            target = _money(row["target_position"]["target_quantity"])
            # The reversal-close action may target flat or eventual short; it only closes long now.
            expected_targets = {"primary": {contracts}, "reversal_close": {Decimal(0), -contracts},
                                "reversal_open": {-contracts}, "exit": {Decimal(0)}}
            _require(target in expected_targets[row["phase"]]
                     and row["target_position"].get("symbol") == fixture["instrument_id"]
                     and row["target_position"].get("strategy_id") == identity["strategy_id"]
                     and plan.get("action") == action
                     and _money(plan.get("contracts")) == contracts
                     and _money(plan.get("position_before_contracts")) == previous_position
                     and _money(plan.get("position_after_contracts")) == position_after
                     and _money(after["position_contracts"]) == position_after
                     and plan.get("risk_reducing_only") is action.startswith("close_")
                     and plan.get("reversal_close_only") is (row["phase"] == "reversal_close"),
                     "donchian_plan_quantity_or_position_invalid")
            _require(links.get("decision_outcome") == "order_terminal"
                     and risk.get("approved") is True
                     and risk.get("risk_check_id") == links.get("risk_check_id")
                     and plan.get("action") == links.get("action")
                     and plan.get("client_order_id") == links.get("client_order_id")
                     and order.get("clOrdId") == links.get("client_order_id")
                     and order.get("ordId") == links.get("exchange_order_id")
                     and order.get("state") == "filled"
                     and row["signal"].get("signal_id") == links.get("signal_id")
                     and row["target_position"].get("target_position_id") == links.get("target_position_id"),
                     "donchian_order_join_invalid")
            _require(order.get("instId") == fixture["instrument_id"]
                     and order.get("side") == side and order.get("posSide") == position_side
                     and _money(order.get("sz")) == contracts
                     and _money(order.get("accFillSz")) == contracts
                     and _money(order.get("avgPx")) == execution_price,
                     "donchian_order_quantity_invalid")
            _require(order["ordId"] not in seen_orders and len(fills) == 1
                     and [fill.get("fill_id") for fill in fills] == links.get("fill_ids")
                     and all(fill.get("order_id") == order["ordId"]
                             and fill.get("client_order_id") == order["clOrdId"]
                             and fill["fill_id"] not in seen_fills for fill in fills),
                     "donchian_fill_join_invalid")
            _require(sum((_money(fill["size"]) for fill in fills), Decimal(0)) == contracts
                     and all(fill.get("instrument_id") == fixture["instrument_id"]
                             and fill.get("side") == side
                             and fill.get("position_side") == position_side
                             and _money(fill.get("price")) == execution_price
                             and _money(fill.get("fee")) == expected_fee
                             and _money(fill.get("pnl")) == 0 for fill in fills),
                     "donchian_fill_quantity_or_cost_invalid")
            seen_orders.add(order["ordId"])
            seen_fills.update(fill["fill_id"] for fill in fills)
            projection = ledger["projection"]
            _require(ledger.get("event_id") == links.get("ledger_event_id")
                     and ledger.get("event_hash") == links.get("ledger_event_hash")
                     and bool(HEX64.fullmatch(ledger.get("event_hash", "")))
                     and bool(HEX64.fullmatch(ledger.get("raw_payload_sha256", "")))
                     and ledger.get("projection_sha256") == digest(projection)
                     and type(ledger.get("sequence")) is int
                     and ledger["sequence"] > last_sequence,
                     "donchian_ledger_event_join_invalid")
            last_sequence = ledger["sequence"]
            _require(any(item.get("client_order_id") == order["clOrdId"]
                         and item.get("order_id") == order["ordId"]
                         and _money(item.get("size")) == contracts
                         and _money(item.get("filled_size")) == contracts
                         and item.get("side") == side
                         and item.get("position_side") == position_side
                         for item in projection["order_ledger"]["orders"])
                     and all(any(item == fill for item in projection["fill_ledger"])
                             for fill in fills)
                     and _money(projection["position_ledger"]["signed_contracts"]) == _money(after["position_contracts"])
                     and _money(projection["cash_ledger"]["equity_usdt"]) == _money(after["equity_usdt"])
                     and projection["funding_ledger"]["cashflow_reconciled"] is True,
                     "donchian_ledger_projection_invalid")
            fee = sum((_money(fill["fee"]) for fill in fills), Decimal(0))
            pnl = sum((_money(fill["pnl"]) for fill in fills), Decimal(0))
            funding = _money(projection["funding_ledger"]["cashflow"])
            total_fees += fee
            total_funding += funding
            _require(_money(after["equity_usdt"]) == previous_equity + fee + pnl + funding,
                     "donchian_equity_replay_invalid")
            _require(after["submitted_orders"] == last_orders + 1
                     and after["fill_count"] == last_fills + 1,
                     "donchian_order_count_invalid")
            last_orders += 1
            last_fills += 1
        previous_equity = _money(after["equity_usdt"])
        previous_position = _money(after["position_contracts"])
    final = summary["final"]
    counts = summary["counts"]
    expected = fixture["expected"]
    _require(counts == {"decisions": 5, "orders": 4, "fills": 4, "ledger_events": 4}
             and counts["orders"] == expected["submit_count"]
             and counts["fills"] == expected["fill_count"]
             and _money(final["equity_usdt"]) == _money(expected["final_equity_usdt"])
             and _money(final["position_contracts"]) == _money(expected["final_position_contracts"])
             and _money(final["fee_cashflow_usdt"]) == _money(expected["total_fees_usdt"])
             and _money(final["funding_cashflow_usdt"]) == _money(expected["actual_funding_cashflow_usdt"])
             and _money(final["fee_cashflow_usdt"]) == total_fees
             and _money(final["funding_cashflow_usdt"]) == total_funding
             and previous_position == _money(final["position_contracts"])
             and _money(stages[-1]["after"]["equity_usdt"]) == _money(final["equity_usdt"]),
             "donchian_final_economics_invalid")
    return {**summary, "read_only": True, "historical_source": source_head != current_head,
            "publication_head": current_head, "summary_sha256": envelope["sha256"],
            "manifest_ref": f"{current_head}:{REPORT_PATH}"}


def read_donchian_summary(repo_root: Path, selector: str,
                          expected_identity: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {"selector": selector, "status": "blocked", "read_only": True,
               "permissions": {flag: False for flag in FLAGS}}
    if selector != SELECTOR:
        return {**blocked, "status": "not_bound", "reason": "donchian_selector_not_bound"}
    try:
        def git(*args: str) -> bytes:
            return subprocess.run(["git", "-C", str(repo_root), *args], check=True,
                                  capture_output=True, timeout=5).stdout
        head = git("rev-parse", "HEAD").decode("ascii").strip()
        _require(bool(HEX40.fullmatch(head)), "donchian_publication_head_invalid")
        spec = f"{head}:{REPORT_PATH}"
        _require(int(git("cat-file", "-s", spec)) <= 262144,
                 "donchian_summary_size_invalid")
        fixture_spec = f"{head}:{FIXTURE_PATH}"
        _require(int(git("cat-file", "-s", fixture_spec)) <= 16384,
                 "donchian_fixture_size_invalid")
        sealed = json.loads(git("show", spec))
        # This selector identifies one independently reviewed receipt, not a mutable run family.
        # The validator below still checks its fixture-bound economic and stage semantics.
        _require(sealed.get("sha256") == SUMMARY_SHA256, "donchian_reviewed_seal_mismatch")
        return validate_donchian_summary(sealed, expected_identity,
                                         head, git("show", fixture_spec))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
        return {**blocked, "reason": "donchian_summary_missing_or_invalid"}
