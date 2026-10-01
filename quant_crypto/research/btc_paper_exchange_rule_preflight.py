from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping, Sequence

from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
from quant_crypto.research.small_account_high_yield_near_miss_review import _git_commit, _portable_path


SCHEMA_VERSION = "btc_paper_exchange_rule_preflight_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_exchange_runtime/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_report.json"
DEFAULT_ROWS_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_rows.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "btc_paper_exchange_rule_preflight_safety_status.json"

DEFAULT_CONFIG_PATH = Path("configs/data/btc_perpetual_sources.yaml")
DEFAULT_CURRENT_ROWS_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_rows.csv")
DEFAULT_DRILL_ROWS_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_rows.csv")
DEFAULT_CURRENT_REPLAY_REPORT_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_report.json")
DEFAULT_DRILL_REPORT_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_perpetual_paper_runtime_replay_drill_report.json")
DEFAULT_KILL_SWITCH_REPORT_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_paper_live_kill_switch_status_report.json")
DEFAULT_SERVER_TIME_PREFLIGHT_REPORT_PATH = Path("artifacts/btc_exchange_runtime/latest/btc_okx_server_time_preflight_report.json")
DEFAULT_ACCOUNT_RUNTIME_ATTESTATION_REPORT_PATH = Path(
    "artifacts/btc_exchange_runtime/latest/btc_paper_account_runtime_attestation_report.json"
)
DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT_PATH = Path(
    "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json"
)

DEFAULT_MAX_LEVERAGE = Decimal("10")
DEFAULT_MIN_LIQUIDATION_BUFFER_BPS = Decimal("800")


def build_btc_paper_exchange_rule_preflight(
    *,
    repo_root: Path = Path("."),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    exchange_info_path: Path | None = None,
    current_rows_path: Path = DEFAULT_CURRENT_ROWS_PATH,
    drill_rows_path: Path = DEFAULT_DRILL_ROWS_PATH,
    current_replay_report_path: Path = DEFAULT_CURRENT_REPLAY_REPORT_PATH,
    drill_report_path: Path = DEFAULT_DRILL_REPORT_PATH,
    kill_switch_report_path: Path = DEFAULT_KILL_SWITCH_REPORT_PATH,
    server_time_preflight_report_path: Path = DEFAULT_SERVER_TIME_PREFLIGHT_REPORT_PATH,
    account_runtime_attestation_report_path: Path = DEFAULT_ACCOUNT_RUNTIME_ATTESTATION_REPORT_PATH,
    manual_paper_review_approval_report_path: Path = DEFAULT_MANUAL_PAPER_REVIEW_APPROVAL_REPORT_PATH,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated = _ensure_utc(generated_at_utc or datetime.now(timezone.utc))

    resolved_exchange_info_path = _resolve_exchange_info_path(
        root=root,
        config_path=config_path,
        exchange_info_path=exchange_info_path,
    )
    exchange_info = _read_json(resolved_exchange_info_path)
    symbol_info = _mapping(exchange_info.get("raw_symbol_info"))
    current_rows = _read_csv(_resolve(root, current_rows_path))
    drill_rows = _read_csv(_resolve(root, drill_rows_path))
    current_replay = _read_json(_resolve(root, current_replay_report_path))
    drill_report = _read_json(_resolve(root, drill_report_path))
    kill_switch = _read_json(_resolve(root, kill_switch_report_path))
    server_time_preflight = _read_json(_resolve(root, server_time_preflight_report_path))
    account_runtime_attestation = _read_json(_resolve(root, account_runtime_attestation_report_path))
    manual_paper_review_approval = _read_json(_resolve(root, manual_paper_review_approval_report_path))
    rules = _rules(symbol_info=symbol_info, exchange_info=exchange_info)
    rows = _preflight_rows(
        current_rows=current_rows,
        drill_rows=drill_rows,
        rules=rules,
        kill_switch=kill_switch,
    )
    report_blockers = _report_blockers(
        exchange_info=exchange_info,
        current_rows=current_rows,
        drill_rows=drill_rows,
        rows=rows,
        current_replay=current_replay,
        drill_report=drill_report,
        kill_switch=kill_switch,
        server_time_preflight=server_time_preflight,
        account_runtime_attestation=account_runtime_attestation,
        manual_paper_review_approval=manual_paper_review_approval,
        rules=rules,
    )
    report_path = output / DEFAULT_REPORT_PATH.name
    rows_path = output / DEFAULT_ROWS_CSV_PATH.name
    markdown_path = output / DEFAULT_MARKDOWN_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "incomplete_research_only" if report_blockers else "complete_research_only",
        "decision": (
            "btc_paper_exchange_rule_preflight_incomplete_fail_closed_no_paper_no_live"
            if report_blockers
            else "btc_paper_exchange_rule_preflight_complete_manual_review_required_no_auto_paper_no_live"
        ),
        "scope": "btc_paper_runtime_exchange_filter_preflight_no_order_no_broker",
        "code_commit": _git_commit(),
        "input": {
            "config_path": _portable_path(config_path),
            "exchange_info_path": _portable_path(resolved_exchange_info_path) if resolved_exchange_info_path else None,
            "current_rows_path": _portable_path(current_rows_path),
            "drill_rows_path": _portable_path(drill_rows_path),
            "current_replay_report_path": _portable_path(current_replay_report_path),
            "drill_report_path": _portable_path(drill_report_path),
            "kill_switch_report_path": _portable_path(kill_switch_report_path),
            "server_time_preflight_report_path": _portable_path(server_time_preflight_report_path),
            "account_runtime_attestation_report_path": _portable_path(account_runtime_attestation_report_path),
            "manual_paper_review_approval_report_path": _portable_path(manual_paper_review_approval_report_path),
        },
        "exchange_rules": rules,
        "account_runtime_evidence": _account_runtime_evidence(
            account_runtime_attestation=account_runtime_attestation,
            server_time_preflight=server_time_preflight,
        ),
        "current_runtime": _runtime_summary(current_replay),
        "historical_drill": _runtime_summary(drill_report),
        "kill_switch_state": _kill_switch_summary(kill_switch),
        "server_time_preflight": _server_time_summary(server_time_preflight),
        "account_runtime_attestation": _account_runtime_attestation_summary(account_runtime_attestation),
        "manual_paper_review_approval": _manual_paper_review_approval_summary(manual_paper_review_approval),
        "summary": _summary(rows=rows, blockers=report_blockers, current_replay=current_replay),
        "rows": rows[:100],
        "gate": _gate(),
        "guardrails": _guardrails(),
        "blockers": report_blockers,
        "warnings": _warnings(rows=rows, blockers=report_blockers),
        "outputs": {
            "json": _portable_repo_path(report_path, root),
            "rows_csv": _portable_repo_path(rows_path, root),
            "summary_cn": _portable_repo_path(markdown_path, root),
            "paper_live_safety_status": _portable_repo_path(safety_path, root),
        },
    }
    _write_json(report_path, report)
    _write_rows_csv(rows_path, rows)
    _write_text(markdown_path, render_btc_paper_exchange_rule_preflight_markdown(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_btc_paper_exchange_rule_preflight_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    rules = _mapping(report.get("exchange_rules"))
    gate = _mapping(report.get("gate"))
    lines = [
        "# BTC paper runtime 交易所规则预检",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 当前 replay 理论订单：`{summary.get('current_order_count')}`",
        f"- 历史 drill 理论订单：`{summary.get('drill_order_count')}`",
        f"- 过滤器违规订单：`{summary.get('order_filter_violation_count')}`",
        f"- cancel-only/kill-switch 拒绝订单：`{summary.get('kill_switch_reject_count')}`",
        f"- paper 接单：`{gate.get('paper_order_intake_allowed')}`",
        f"- live 解锁：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 使用的公开交易所规则",
        "",
        f"- 合约：`{rules.get('venue_symbol')}`，状态：`{rules.get('instrument_state')}`",
        f"- 价格 tick：`{rules.get('tick_size')}`",
        f"- 数量 lot：`{rules.get('lot_size_contracts')}` 合约",
        f"- 合约面值：`{rules.get('contract_value_btc')}` BTC/合约",
        f"- 最小数量：`{rules.get('min_size_contracts')}` 合约",
        f"- 市价最大数量：`{rules.get('max_market_size_contracts')}` 合约",
        "",
        "## 主要阻断项",
        "",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers[:80])
        if len(blockers) > 80:
            lines.append(f"- ... 其余 {len(blockers) - 80} 项见 JSON")
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "说明：当前 observe-only 没有理论订单时不能证明 paper 可接单；历史 drill 只能诊断字段链路和交易所过滤器，不能替代当前 paper gate。",
            "本报告不写 paper 队列，不连接 broker/OMS，不使用 private/order endpoint，不解锁 live。",
        ]
    )
    return "\n".join(lines) + "\n"


def _preflight_rows(
    *,
    current_rows: Sequence[Mapping[str, str]],
    drill_rows: Sequence[Mapping[str, str]],
    rules: Mapping[str, Any],
    kill_switch: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_scope, source_rows in (
        ("current_observe_only_paper_runtime_replay", current_rows),
        ("historical_bar_replay_execution_drill", drill_rows),
    ):
        for row in source_rows:
            rows.append(_preflight_row(row, source_scope=source_scope, rules=rules, kill_switch=kill_switch))
    return rows


def _preflight_row(
    row: Mapping[str, str],
    *,
    source_scope: str,
    rules: Mapping[str, Any],
    kill_switch: Mapping[str, Any],
) -> dict[str, Any]:
    theoretical_order = _bool(row.get("theoretical_order_created"))
    simulated_fill = _bool(row.get("simulated_fill_created"))
    side = str(row.get("side") or "")
    exposure = _decimal(row.get("target_exposure"))
    notional = _decimal(row.get("notional_usdt"))
    qty_btc = abs(_decimal(row.get("quantity_btc")))
    execution_price = _decimal(row.get("execution_price"))
    mark_price = _decimal(row.get("mark_price"))
    index_price = _decimal(row.get("index_price"))
    contracts = _safe_ratio(qty_btc, _decimal(rules.get("contract_value_btc")))
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    if not theoretical_order:
        return {
            "source_scope": source_scope,
            "strategy_line": row.get("strategy_line", ""),
            "candidate_id": row.get("candidate_id", ""),
            "decision_time": row.get("decision_time", ""),
            "side": side,
            "target_exposure": _float(exposure),
            "theoretical_order_created": False,
            "simulated_fill_created": False,
            "preflight_status": "no_order_flat_or_heartbeat",
            "requested_contracts": 0.0,
            "rounded_contracts_down": 0.0,
            "blocker_count": 0,
            "blockers": [],
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
        }

    _add_check(checks, blockers, "instrument_live", rules.get("instrument_state") == "live", "instrument must be live")
    _add_check(checks, blockers, "instrument_enabled", bool(rules.get("instrument_enabled")), "instrument metadata must be enabled")
    _add_check(checks, blockers, "side_valid", side in {"long", "short"}, "side must be long or short for an order")
    _add_check(checks, blockers, "simulated_fill_present", simulated_fill, "paper preflight row must carry simulated fill fields")
    _add_check(checks, blockers, "reference_prices_present", execution_price > 0 and mark_price > 0 and index_price > 0, "execution/mark/index prices required")
    _add_check(checks, blockers, "price_tick_aligned", _is_multiple(execution_price, _decimal(rules.get("tick_size"))), "execution price must align to tick")
    _add_check(checks, blockers, "quantity_positive", contracts > 0, "requested contract quantity must be positive")
    _add_check(checks, blockers, "quantity_lot_aligned", _is_multiple(contracts, _decimal(rules.get("lot_size_contracts"))), "requested contracts must align to lot size")
    _add_check(checks, blockers, "min_size_satisfied", contracts >= _decimal(rules.get("min_size_contracts")), "requested contracts must satisfy min size")
    _add_check(checks, blockers, "max_market_size_satisfied", contracts <= _decimal(rules.get("max_market_size_contracts")), "market size must be under exchange max")
    min_notional = _min_notional(rules=rules, execution_price=execution_price)
    _add_check(checks, blockers, "min_notional_satisfied", notional >= min_notional, "notional must satisfy estimated exchange minimum")
    _add_check(checks, blockers, "leverage_within_paper_policy", abs(exposure) <= DEFAULT_MAX_LEVERAGE, "target exposure must stay within paper max leverage")
    _add_check(
        checks,
        blockers,
        "liquidation_buffer_satisfied",
        _decimal(row.get("liquidation_buffer_bps")) >= DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
        "liquidation buffer must satisfy policy",
    )
    _add_check(checks, blockers, "fee_cashflow_present", _decimal(row.get("fee_amount_usdt")) > 0, "fee cashflow required for simulated fill")
    _add_check(checks, blockers, "funding_cashflow_present", row.get("funding_rate") not in {"", None}, "funding rate required for simulated fill")
    kill_switch_engaged = bool(_mapping(kill_switch.get("policy_state")).get("kill_switch_engaged"))
    cancel_only = bool(_mapping(kill_switch.get("policy_state")).get("cancel_only_mode"))
    if kill_switch_engaged or cancel_only:
        blockers.append("current_kill_switch_cancel_only_blocks_position_increase")
        checks.append(
            {
                "check_id": "current_kill_switch_allows_position_increase",
                "status": "fail",
                "evidence": "kill_switch_engaged_or_cancel_only=true",
            }
        )

    exchange_blockers = [item for item in blockers if item != "current_kill_switch_cancel_only_blocks_position_increase"]
    if exchange_blockers:
        status = "fail_exchange_preflight"
    elif blockers:
        status = "blocked_by_kill_switch_cancel_only"
    else:
        status = "pass_exchange_filters"
    return {
        "source_scope": source_scope,
        "strategy_line": row.get("strategy_line", ""),
        "candidate_id": row.get("candidate_id", ""),
        "decision_time": row.get("decision_time", ""),
        "side": side,
        "target_exposure": _float(exposure),
        "theoretical_order_created": True,
        "simulated_fill_created": simulated_fill,
        "preflight_status": status,
        "order_intent": row.get("order_intent", ""),
        "execution_price": _float(execution_price),
        "notional_usdt": _float(notional),
        "quantity_btc": _float(qty_btc),
        "requested_contracts": _float(contracts),
        "rounded_contracts_down": _float(_round_down_to_step(contracts, _decimal(rules.get("lot_size_contracts")))),
        "min_notional_usdt": _float(min_notional),
        "liquidation_buffer_bps": _float(_decimal(row.get("liquidation_buffer_bps"))),
        "check_count": len(checks),
        "failed_check_count": sum(1 for check in checks if check["status"] != "pass"),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "checks": checks,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _report_blockers(
    *,
    exchange_info: Mapping[str, Any],
    current_rows: Sequence[Mapping[str, str]],
    drill_rows: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, Any]],
    current_replay: Mapping[str, Any],
    drill_report: Mapping[str, Any],
    kill_switch: Mapping[str, Any],
    server_time_preflight: Mapping[str, Any],
    account_runtime_attestation: Mapping[str, Any],
    manual_paper_review_approval: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not exchange_info:
        blockers.append("btc_paper_exchange_rule_exchange_info_missing")
    if not rules.get("instrument_enabled"):
        blockers.append("btc_paper_exchange_rule_instrument_not_enabled")
    if not current_rows:
        blockers.append("btc_paper_exchange_rule_current_replay_rows_missing")
    if not drill_rows:
        blockers.append("btc_paper_exchange_rule_drill_rows_missing")
    current_order_count = sum(1 for row in rows if row.get("source_scope") == "current_observe_only_paper_runtime_replay" and row.get("theoretical_order_created"))
    if current_order_count <= 0:
        blockers.append("btc_paper_exchange_rule_no_current_theoretical_orders_to_validate")
    order_failures = [row for row in rows if row.get("theoretical_order_created") and row.get("blockers")]
    if order_failures:
        blockers.append("btc_paper_exchange_rule_order_filter_or_kill_switch_failures_present")
    if current_replay.get("status") != "complete_research_only":
        blockers.append("btc_paper_exchange_rule_current_paper_runtime_not_ready")
    if _mapping(kill_switch.get("policy_state")).get("kill_switch_engaged") is not False:
        blockers.append("btc_paper_exchange_rule_kill_switch_currently_engaged")
    if _mapping(kill_switch.get("policy_state")).get("manual_approval_recorded") is not True:
        blockers.append("btc_paper_exchange_rule_manual_approval_missing")
    if manual_paper_review_approval.get("manual_approval_recorded") is not True:
        blockers.append("btc_paper_exchange_rule_manual_review_approval_record_missing")
    if manual_paper_review_approval.get("manual_review_missing_cleared") is not True:
        blockers.append("btc_paper_exchange_rule_manual_review_missing_not_cleared")
    blockers.extend(
        f"manual_paper_review_approval:{item}"
        for item in _list(manual_paper_review_approval.get("blockers"))
    )
    if manual_paper_review_approval.get("paper_queue_write_allowed") is True:
        blockers.append("btc_paper_exchange_rule_manual_approval_paper_queue_true")
    if manual_paper_review_approval.get("live_unlock_allowed") is True:
        blockers.append("btc_paper_exchange_rule_manual_approval_live_unlock_true")
    blockers.extend(
        _account_runtime_blockers(
            account_runtime_attestation=account_runtime_attestation,
            server_time_preflight=server_time_preflight,
        )
    )
    if _mapping(drill_report.get("summary")).get("paper_runtime_gate_evidence") is True:
        blockers.append("btc_paper_exchange_rule_drill_must_not_be_gate_evidence")
    return sorted(set(blockers))


def _account_runtime_blockers(
    *,
    account_runtime_attestation: Mapping[str, Any],
    server_time_preflight: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if account_runtime_attestation.get("account_mode_verified") is not True:
        blockers.append("btc_paper_exchange_rule_account_mode_not_verified")
    if account_runtime_attestation.get("position_mode_verified") is not True:
        blockers.append("btc_paper_exchange_rule_position_mode_not_verified")
    if account_runtime_attestation.get("margin_mode_verified") is not True:
        blockers.append("btc_paper_exchange_rule_margin_mode_not_verified")
    if account_runtime_attestation.get("rate_limit_budget_verified") is not True:
        blockers.append("btc_paper_exchange_rule_rate_limit_budget_not_verified")
    if account_runtime_attestation.get("credential_permissions_verified") is not True:
        blockers.append("btc_paper_exchange_rule_credential_permissions_not_verified")
    if account_runtime_attestation.get("manual_approval_recorded") is not True:
        blockers.append("btc_paper_exchange_rule_account_runtime_manual_approval_not_recorded")
    if account_runtime_attestation.get("private_endpoint_used") is True:
        blockers.append("btc_paper_exchange_rule_account_runtime_private_endpoint_used")
    if account_runtime_attestation.get("order_endpoint_used") is True:
        blockers.append("btc_paper_exchange_rule_account_runtime_order_endpoint_used")
    blockers.extend(f"account_runtime_attestation:{item}" for item in _list(account_runtime_attestation.get("blockers")))
    if not _server_time_verified(server_time_preflight):
        blockers.append("btc_paper_exchange_rule_server_time_offset_not_verified")
    return sorted(set(blockers))


def _summary(
    *,
    rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    current_replay: Mapping[str, Any],
) -> dict[str, Any]:
    current_replay_summary = _mapping(current_replay.get("summary"))
    order_rows = [row for row in rows if row.get("theoretical_order_created")]
    current_rows = [row for row in rows if row.get("source_scope") == "current_observe_only_paper_runtime_replay"]
    current_orders = [row for row in order_rows if row.get("source_scope") == "current_observe_only_paper_runtime_replay"]
    drill_orders = [row for row in order_rows if row.get("source_scope") == "historical_bar_replay_execution_drill"]
    current_flat_no_order_healthy = _current_flat_no_order_healthy(
        current_rows=current_rows,
        current_orders=current_orders,
        current_replay_summary=current_replay_summary,
    )
    return {
        "row_count": len(rows),
        "current_row_count": len(current_rows),
        "drill_row_count": sum(1 for row in rows if row.get("source_scope") == "historical_bar_replay_execution_drill"),
        "order_count": len(order_rows),
        "current_order_count": len(current_orders),
        "drill_order_count": len(drill_orders),
        "current_flat_heartbeat_count": sum(1 for row in current_rows if not row.get("theoretical_order_created")),
        "current_flat_no_order_healthy": current_flat_no_order_healthy,
        "current_order_sample_available": len(current_orders) > 0,
        "current_order_sample_status": _current_order_sample_status(
            current_rows=current_rows,
            current_orders=current_orders,
            current_flat_no_order_healthy=current_flat_no_order_healthy,
        ),
        "current_order_sample_pending_reason": (
            "current_observe_only_signal_flat_waiting_for_exchange_filter_sample"
            if current_flat_no_order_healthy
            else None
        ),
        "order_filter_violation_count": sum(1 for row in order_rows if _exchange_filter_blockers(row)),
        "quantity_lot_violation_count": sum(1 for row in order_rows if "quantity_lot_aligned" in _failed_check_ids(row)),
        "kill_switch_reject_count": sum(1 for row in order_rows if "current_kill_switch_cancel_only_blocks_position_increase" in _list(row.get("blockers"))),
        "blocker_count": len(blockers),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _current_flat_no_order_healthy(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    current_orders: Sequence[Mapping[str, Any]],
    current_replay_summary: Mapping[str, Any],
) -> bool:
    if not current_rows or current_orders:
        return False
    if current_replay_summary.get("current_flat_heartbeat_healthy") is True:
        return True
    return all(row.get("preflight_status") == "no_order_flat_or_heartbeat" for row in current_rows)


def _current_order_sample_status(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    current_orders: Sequence[Mapping[str, Any]],
    current_flat_no_order_healthy: bool,
) -> str:
    if current_orders:
        return "current_order_sample_present"
    if current_flat_no_order_healthy:
        return "current_flat_heartbeat_waiting_for_order_sample"
    if not current_rows:
        return "current_replay_rows_missing"
    return "current_order_sample_missing"


def _runtime_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(report.get("summary"))
    return {
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "theoretical_order_count": summary.get("theoretical_order_count"),
        "simulated_fill_count": summary.get("simulated_fill_count"),
        "current_flat_heartbeat_healthy": summary.get("current_flat_heartbeat_healthy"),
        "trade_execution_evidence_available": summary.get("trade_execution_evidence_available"),
        "trade_execution_evidence_pending_reason": summary.get("trade_execution_evidence_pending_reason"),
        "paper_runtime_health_status": summary.get("paper_runtime_health_status"),
        "paper_runtime_gate_evidence": summary.get("paper_runtime_gate_evidence"),
        "blocker_count": len(_list(report.get("blockers"))),
    }


def _kill_switch_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    policy = _mapping(report.get("policy_state"))
    return {
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "kill_switch_engaged": policy.get("kill_switch_engaged"),
        "cancel_only_mode": policy.get("cancel_only_mode"),
        "paper_order_intake_allowed": policy.get("paper_order_intake_allowed"),
        "position_increase_allowed": policy.get("position_increase_allowed"),
        "manual_approval_recorded": policy.get("manual_approval_recorded"),
    }


def _server_time_verified(report: Mapping[str, Any]) -> bool:
    if not report:
        return False
    if report.get("server_time_offset_verified") is not True:
        return False
    if report.get("private_endpoint_used") is True or report.get("order_endpoint_used") is True:
        return False
    return not _list(report.get("blockers"))


def _server_time_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _mapping(report.get("server_time_metrics"))
    validation = _mapping(report.get("validation"))
    return {
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "server_time_offset_verified": _server_time_verified(report),
        "offset_ms": metrics.get("offset_ms"),
        "abs_offset_ms": metrics.get("abs_offset_ms"),
        "round_trip_ms": metrics.get("round_trip_ms"),
        "max_abs_offset_ms": validation.get("max_abs_offset_ms"),
        "max_round_trip_ms": validation.get("max_round_trip_ms"),
        "public_rest_only": report.get("public_rest_only"),
        "private_endpoint_used": report.get("private_endpoint_used"),
        "order_endpoint_used": report.get("order_endpoint_used"),
        "blocker_count": len(_list(report.get("blockers"))),
    }


def _account_runtime_evidence(
    *,
    account_runtime_attestation: Mapping[str, Any],
    server_time_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "account_mode_verified": account_runtime_attestation.get("account_mode_verified") is True,
        "position_mode_verified": account_runtime_attestation.get("position_mode_verified") is True,
        "margin_mode_verified": account_runtime_attestation.get("margin_mode_verified") is True,
        "rate_limit_budget_verified": account_runtime_attestation.get("rate_limit_budget_verified") is True,
        "credential_permissions_verified": account_runtime_attestation.get("credential_permissions_verified") is True,
        "server_time_offset_verified": _server_time_verified(server_time_preflight),
        "manual_approval_recorded": account_runtime_attestation.get("manual_approval_recorded") is True,
        "attestation_current": account_runtime_attestation.get("attestation_current") is True,
    }


def _account_runtime_attestation_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "account_mode_verified": report.get("account_mode_verified") is True,
        "position_mode_verified": report.get("position_mode_verified") is True,
        "margin_mode_verified": report.get("margin_mode_verified") is True,
        "rate_limit_budget_verified": report.get("rate_limit_budget_verified") is True,
        "credential_permissions_verified": report.get("credential_permissions_verified") is True,
        "manual_approval_recorded": report.get("manual_approval_recorded") is True,
        "attestation_current": report.get("attestation_current") is True,
        "private_endpoint_used": report.get("private_endpoint_used") is True,
        "order_endpoint_used": report.get("order_endpoint_used") is True,
        "blocker_count": len(_list(report.get("blockers"))),
    }


def _manual_paper_review_approval_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(report),
        "status": report.get("status"),
        "decision": report.get("decision"),
        "manual_approval_recorded": report.get("manual_approval_recorded") is True,
        "manual_review_missing_cleared": report.get("manual_review_missing_cleared") is True,
        "paper_queue_write_allowed": report.get("paper_queue_write_allowed") is True,
        "paper_order_intake_allowed": report.get("paper_order_intake_allowed") is True,
        "live_unlock_allowed": report.get("live_unlock_allowed") is True,
        "reviewed_packet_sha256": _mapping(report.get("reviewed_packet")).get("sha256"),
        "blocker_count": len(_list(report.get("blockers"))),
    }


def _rules(*, symbol_info: Mapping[str, Any], exchange_info: Mapping[str, Any]) -> dict[str, Any]:
    state = str(symbol_info.get("state") or "")
    contract_value = _decimal(symbol_info.get("ctVal"))
    tick = _decimal(symbol_info.get("tickSz"))
    lot = _decimal(symbol_info.get("lotSz"))
    min_size = _decimal(symbol_info.get("minSz"))
    max_market = _decimal(symbol_info.get("maxMktSz"))
    return {
        "venue": "OKX",
        "venue_symbol": symbol_info.get("instId") or exchange_info.get("venue_symbol"),
        "instrument_type": symbol_info.get("instType"),
        "instrument_state": state,
        "instrument_enabled": state == "live" and str(symbol_info.get("instType") or "") == "SWAP",
        "contract_type": symbol_info.get("ctType"),
        "contract_value_btc": str(contract_value),
        "settle_currency": symbol_info.get("settleCcy"),
        "tick_size": str(tick),
        "lot_size_contracts": str(lot),
        "min_size_contracts": str(min_size),
        "max_market_size_contracts": str(max_market),
        "exchange_max_leverage": _float(_decimal(symbol_info.get("lever"))),
        "min_notional_estimate": _float(_decimal(exchange_info.get("min_notional_estimate"))),
        "metadata_available_time": exchange_info.get("available_time"),
        "private_endpoint_used": bool(exchange_info.get("private_endpoint_used")),
        "order_endpoint_used": bool(exchange_info.get("order_endpoint_used")),
        "api_key_used": bool(exchange_info.get("api_key_used")),
    }


def _resolve_exchange_info_path(*, root: Path, config_path: Path, exchange_info_path: Path | None) -> Path | None:
    if exchange_info_path is not None:
        return _resolve(root, exchange_info_path)
    bundle_dir = selected_btc_perpetual_bundle_dir(root, _resolve(root, config_path))
    if not bundle_dir:
        return None
    return bundle_dir / "exchange_info.json"


def _add_check(checks: list[dict[str, Any]], blockers: list[str], check_id: str, ok: bool, evidence: str) -> None:
    checks.append({"check_id": check_id, "status": "pass" if ok else "fail", "evidence": evidence})
    if not ok:
        blockers.append(check_id)


def _failed_check_ids(row: Mapping[str, Any]) -> list[str]:
    return [str(check.get("check_id")) for check in _list(row.get("checks")) if _mapping(check).get("status") != "pass"]


def _exchange_filter_blockers(row: Mapping[str, Any]) -> list[str]:
    return [
        str(item)
        for item in _list(row.get("blockers"))
        if str(item) != "current_kill_switch_cancel_only_blocks_position_increase"
    ]


def _min_notional(*, rules: Mapping[str, Any], execution_price: Decimal) -> Decimal:
    configured = _decimal(rules.get("min_notional_estimate"))
    derived = _decimal(rules.get("min_size_contracts")) * _decimal(rules.get("contract_value_btc")) * execution_price
    return max(configured, derived)


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    if value <= 0 or step <= 0:
        return False
    try:
        return value.remainder_near(step).copy_abs() <= Decimal("1e-12")
    except InvalidOperation:
        return False


def _round_down_to_step(value: Decimal, step: Decimal) -> Decimal:
    if value <= 0 or step <= 0:
        return Decimal("0")
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
        "reason": "Exchange-rule preflight is diagnostic and cannot promote paper/live by itself.",
    }


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "strategy_skeleton_generated": False,
    }


def _warnings(*, rows: Sequence[Mapping[str, Any]], blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_paper_exchange_rule_preflight_research_only_no_order_no_broker"]
    if blockers:
        warnings.append("exchange_rule_preflight_incomplete_fail_closed")
    if any(row.get("source_scope") == "historical_bar_replay_execution_drill" and row.get("theoretical_order_created") for row in rows):
        warnings.append("historical_drill_orders_are_diagnostic_not_current_paper_gate_evidence")
    return warnings


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_paper_exchange_rule_preflight_safety_status_v1",
        "status": report.get("status"),
        "decision": report.get("decision"),
        "paper_order_intake_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "position_increase_allowed": False,
        "strategy_skeleton_generated": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "micro_live_allowed": False,
        "oms_access_allowed": False,
        "broker_access_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "blockers": list(report.get("blockers", [])),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_scope",
        "strategy_line",
        "candidate_id",
        "decision_time",
        "side",
        "target_exposure",
        "theoretical_order_created",
        "simulated_fill_created",
        "preflight_status",
        "order_intent",
        "execution_price",
        "notional_usdt",
        "quantity_btc",
        "requested_contracts",
        "rounded_contracts_down",
        "min_notional_usdt",
        "liquidation_buffer_bps",
        "failed_check_count",
        "blocker_count",
        "blockers",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_repo_path(path: Path, root: Path) -> str:
    try:
        return _portable_path(path.relative_to(root))
    except ValueError:
        return _portable_path(path)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _decimal(value: Any) -> Decimal:
    try:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _float(value: Decimal) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
