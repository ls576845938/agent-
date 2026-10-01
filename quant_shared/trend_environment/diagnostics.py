"""Pure grouping of sealed state observations and exact decision/fill links."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("diagnostic_amount_invalid") from exc
    if not result.is_finite():
        raise ValueError("diagnostic_amount_invalid")
    return result


def _label(state: Mapping[str, Any]) -> str:
    if state.get("status") != "observed":
        return "unknown"
    value = (state.get("path_efficiency_by_horizon") or {}).get("72")
    if value is None:
        return "unknown"
    efficiency = _decimal(value)
    if efficiency < Decimal("0.20"):
        return "low"
    if efficiency < Decimal("0.40"):
        return "mixed"
    return "directional"


def _money(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def build_stage_diagnostic(stage: Mapping[str, Any], states: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = list(states)
    if not ordered:
        raise ValueError("diagnostic_states_missing")
    by_event: dict[str, Mapping[str, Any]] = {}
    labels: list[str] = []
    for row in ordered:
        event = row.get("event_time_utc")
        if not isinstance(event, str) or not event or event in by_event:
            raise ValueError("diagnostic_state_event_duplicate_or_missing")
        by_event[event] = row
        labels.append(_label(row))
    links_by_fill: dict[str, Mapping[str, Any]] = {}
    for link in stage.get("decision_links") or []:
        for fill_id in link.get("fill_ids") or []:
            if fill_id in links_by_fill:
                raise ValueError("diagnostic_fill_link_duplicate")
            links_by_fill[fill_id] = link

    bar_groups: dict[str, dict[str, int]] = {
        name: {"bars": labels.count(name)} for name in ("low", "mixed", "directional", "unknown")
    }
    segment_count = 1 + sum(labels[index] != labels[index - 1] for index in range(1, len(labels)))
    group_values: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "roundtrips": 0, "long": 0, "short": 0,
        "price_pnl_usdt": Decimal("0"), "fees_usdt": Decimal("0"),
        "price_pnl_minus_fees_usdt": Decimal("0"), "funding_usdt": None,
    })
    entries: list[dict[str, Any]] = []
    reject_count = 0
    for trip in stage.get("roundtrips") or []:
        open_fill = trip.get("open_fill_id")
        link = links_by_fill.get(open_fill)
        if link is None:
            raise ValueError("diagnostic_open_fill_link_missing")
        event = link.get("event_time_utc")
        state = by_event.get(event)
        if state is None:
            raise ValueError("diagnostic_state_exact_match_missing")
        label = _label(state)
        price = _decimal(trip.get("price_pnl_usdt"))
        fee = _decimal(trip.get("fees_usdt"))
        economic = price - fee
        group = group_values[label]
        group["roundtrips"] += 1
        side = str(trip.get("side"))
        if side not in {"long", "short"}:
            raise ValueError("diagnostic_trade_side_invalid")
        group[side] += 1
        group["price_pnl_usdt"] += price
        group["fees_usdt"] += fee
        group["price_pnl_minus_fees_usdt"] += economic
        if label in {"low", "unknown"}:
            reject_count += 1
        entries.append({
            "open_fill_id": open_fill,
            "close_fill_id": trip.get("close_fill_id"),
            "side": side,
            "decision_event_time_utc": event,
            "state_cutoff_time_utc": state.get("decision_time"),
            "state_content_hash": state.get("content_hash"),
            "state_label": label,
            "path_efficiency_72h": (state.get("path_efficiency_by_horizon") or {}).get("72"),
            "price_pnl_usdt": _money(price),
            "fees_usdt": _money(fee),
            "price_pnl_minus_fees_usdt": _money(economic),
            "funding_usdt": None,
            "exit_type": trip.get("exit_type"),
        })
    trade_groups = {}
    for name in ("low", "mixed", "directional", "unknown"):
        row = group_values[name]
        trade_groups[name] = {
            **{key: row[key] for key in ("roundtrips", "long", "short")},
            "price_pnl_usdt": _money(row["price_pnl_usdt"]),
            "fees_usdt": _money(row["fees_usdt"]),
            "price_pnl_minus_fees_usdt": _money(row["price_pnl_minus_fees_usdt"]),
            "funding_usdt": None,
        }
    return {
        "sample_units": {
            "bars": len(ordered),
            "roundtrips": len(entries),
            "contiguous_state_segments": segment_count,
        },
        "bar_groups": bar_groups,
        "trade_groups": trade_groups,
        "entry_join": {
            "method": "open_fill_id_to_unique_decision_fill_id_then_exact_event_time",
            "nearest_time_matching": False,
            "matched_roundtrips": len(entries),
            "entries": entries,
        },
        "funding": {
            "allocation": "unavailable_per_trade",
            "total_only_usdt": str(stage.get("economics", {}).get("funding_cashflow_usdt")),
        },
        "prediction_metrics": {"ic": "not_applicable", "rank_ic": "not_applicable"},
        "policy_counterfactual": {
            "rule": "flat_entry_rejected_when_unknown_or_path_efficiency_72h_below_0.20",
            "would_reject_entries": reject_count,
            "effect_on_realized_trades_or_pnl": "not_evaluated",
        },
    }

