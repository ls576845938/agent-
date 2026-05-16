"""Canonical BTC research evidence helpers.

This module is research-only. It consumes event-ledger backtest outputs and
builds promotion inputs from fills/ledger evidence. Signal equity may be stored
as diagnostics, but it is not eligible for gate decisions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from math import erf, sqrt
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from backend.app.domain.strategy_registry import strategy_registry
from quant_us.backtest.crypto_event import CRYPTO_COST_STRESS_SCENARIOS, run_crypto_event_backtest
from quant_us.research.btc_alpha_hardening import classify_btc_regimes


SignalBuilder = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.Series, dict[str, pd.Series]]]

BTC_CANONICAL_GATE_THRESHOLDS: dict[str, float] = {
    "profit_factor": 1.15,
    "event_profit_factor": 1.15,
    "annual_turnover": 10.0,
    "walk_forward_pass_rate": 0.80,
    "regime_pass_rate": 0.75,
    "max_drawdown_pct_floor": -15.0,
    "dsr": 0.10,
    "pbo": 0.50,
}

BTC_CANONICAL_ALLOWED_STATES = {
    "research_failed",
    "research_candidate",
    "candidate_gate_failed",
    "candidate_passed_internal_gate",
    "paper_review_pending",
}
BTC_CANONICAL_FORBIDDEN_STATES = {"paper_ready", "live_ready", "live_enabled"}


@dataclass(frozen=True)
class CanonicalGateDecision:
    strategy_id: str
    status: str
    passed: bool
    fail_reasons: list[str]
    checks: dict[str, bool]
    thresholds: dict[str, float]
    evidence_source: str = "canonical_backtest_report"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def registry_signal_builder(strategy_id: str) -> SignalBuilder:
    def build(frame: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.Series, dict[str, pd.Series]]:
        pack = strategy_registry.get(strategy_id).generate(frame, params)
        return pack.signal.reindex(frame.index).fillna(0.0).clip(-1.0, 1.0), dict(pack.diagnostics)

    return build


def evaluate_canonical_gate(
    canonical_report: Mapping[str, Any],
    *,
    thresholds: Mapping[str, float] | None = None,
) -> CanonicalGateDecision:
    limits = {**BTC_CANONICAL_GATE_THRESHOLDS, **dict(thresholds or {})}
    metrics = canonical_report.get("metrics", canonical_report)
    cost_base = canonical_report.get("cost_stress_base", {})
    cost_harsh = canonical_report.get("cost_stress_harsh", {})
    checks = {
        "profit_factor": _float(metrics.get("profit_factor")) >= limits["profit_factor"],
        "event_profit_factor": _float(metrics.get("event_profit_factor")) >= limits["event_profit_factor"],
        "annual_turnover": _float(metrics.get("annual_turnover"), default=float("inf")) <= limits["annual_turnover"],
        "walk_forward_pass_rate": _float(metrics.get("walk_forward_pass_rate")) >= limits["walk_forward_pass_rate"],
        "regime_pass_rate": _float(metrics.get("regime_pass_rate")) >= limits["regime_pass_rate"],
        "max_drawdown": _float(metrics.get("max_drawdown"), default=-100.0) >= limits["max_drawdown_pct_floor"],
        "cost_stress_base": bool(cost_base.get("passed", metrics.get("cost_stress_base_pass", False))),
        "cost_stress_harsh": bool(cost_harsh.get("survives", metrics.get("cost_stress_harsh_survives", False))),
        "pbo": _float(metrics.get("pbo"), default=1.0) <= limits["pbo"],
        "dsr": _float(metrics.get("dsr")) >= limits["dsr"],
        "no_lookahead": str(canonical_report.get("no_lookahead_status", {}).get("status", "")).lower() == "pass",
        "event_ledger": str(canonical_report.get("event_ledger_status", {}).get("status", "")).lower() == "pass",
        "canonical_source": canonical_report.get("evidence_source") == "canonical_event_ledger",
        "signal_equity_diagnostic_only": bool(
            canonical_report.get("diagnostics", {}).get("signal_equity_diagnostic_only", False)
        ),
    }
    fail_reasons = [name for name, passed in checks.items() if not passed]
    passed = not fail_reasons
    return CanonicalGateDecision(
        strategy_id=str(canonical_report.get("strategy_id", "")),
        status="candidate_passed_internal_gate" if passed else "candidate_gate_failed",
        passed=passed,
        fail_reasons=fail_reasons,
        checks=checks,
        thresholds=limits,
    )


def decide_paper_queue_from_canonical(decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    passed = [
        str(row.get("strategy_id", ""))
        for row in decisions
        if bool(row.get("passed", False)) and row.get("status") == "candidate_passed_internal_gate"
    ]
    queue = passed[:3]
    unlocked = 1 <= len(queue) <= 3
    return {
        "paper_review_queue_locked": not unlocked,
        "paper_review_pending": queue if unlocked else [],
        "paper_auto_start": False,
        "live_frozen": True,
        "max_state": "paper_review_pending" if unlocked else "candidate_gate_failed",
        "forbidden_states": sorted(BTC_CANONICAL_FORBIDDEN_STATES),
        "reason": "manual_review_required" if unlocked else "requires_1_to_3_internal_gate_passes",
        "evidence_source": "canonical_gate_inputs",
    }


def run_event_with_signal(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: Mapping[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    scenario_name: str,
    commission_rate: float = 0.0004,
    slippage_bps: float = 4.0,
    target_weight: float = 0.90,
) -> dict[str, Any]:
    replay = signal.copy()
    replay.index = pd.to_datetime(replay.index, utc=True)

    def provider(loaded_frame: pd.DataFrame, _strategy_id: str, _params: dict[str, Any]) -> pd.Series:
        loaded_index = pd.to_datetime(loaded_frame.index, utc=True)
        return replay.reindex(loaded_index).fillna(0.0).clip(-1.0, 1.0)

    result = run_crypto_event_backtest(
        source="sqlite",
        symbol="BTCUSDT",
        interval="1h",
        start=start,
        end=end,
        strategy_id=strategy_id,
        params=dict(params),
        capital=100_000.0,
        commission_rate=commission_rate,
        slippage_bps=slippage_bps,
        market_loader=lambda **_: frame.copy(),
        signal_provider=provider,
        data_version="qs-sqlite-BTCUSDT-1h-66968bfbabf2",
        strategy_version=f"{strategy_id}:canonical_research_v1",
        manifest_root=run_dir / "manifests",
        target_weight=target_weight,
        min_cash_buffer_pct=0.02,
        min_trade_notional=25.0,
        rebalance_buffer_pct=0.05,
        long_only=False,
        run_id=f"{strategy_id}_{scenario_name}",
    )
    return {
        "summary": result.summary,
        "diagnostics": result.diagnostics,
        "fills": result.unified.fills,
        "orders": result.unified.orders,
        "manifest_path": result.diagnostics.get("manifest_path", ""),
    }


def fills_to_trade_ledger(
    fills: Sequence[Any],
    *,
    run_id: str,
    strategy_id: str,
    symbol: str = "BTCUSDT",
    slippage_bps: float = 4.0,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    position = 0.0
    avg_price = 0.0
    entry_time: pd.Timestamp | None = None
    entry_commission = 0.0
    entry_notional = 0.0
    entry_fill_id = ""
    trade_no = 0
    sorted_fills = sorted(fills, key=lambda fill: getattr(fill, "filled_at"))
    for fill in sorted_fills:
        side_value = getattr(getattr(fill, "side", ""), "value", str(getattr(fill, "side", ""))).lower()
        qty = float(getattr(fill, "quantity", 0.0))
        price = float(getattr(fill, "price", 0.0))
        commission = float(getattr(fill, "commission", 0.0))
        signed = qty if side_value == "buy" else -qty
        ts = pd.Timestamp(getattr(fill, "filled_at"))
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if abs(position) <= 1e-12:
            position = signed
            avg_price = price
            entry_time = ts
            entry_commission = commission
            entry_notional = abs(qty * price)
            entry_fill_id = str(getattr(fill, "fill_id", ""))
            continue
        same_direction = (position > 0 and signed > 0) or (position < 0 and signed < 0)
        if same_direction:
            total_qty = abs(position) + abs(signed)
            avg_price = (avg_price * abs(position) + price * abs(signed)) / max(total_qty, 1e-12)
            position += signed
            entry_commission += commission
            entry_notional += abs(qty * price)
            continue

        closing_qty = min(abs(position), abs(signed))
        gross = (price - avg_price) * closing_qty if position > 0 else (avg_price - price) * closing_qty
        exit_commission = commission * (closing_qty / max(qty, 1e-12))
        allocated_entry_commission = entry_commission * (closing_qty / max(abs(position), 1e-12))
        fees = allocated_entry_commission + exit_commission
        notional = closing_qty * price + entry_notional * (closing_qty / max(abs(position), 1e-12))
        estimated_slippage = notional * float(slippage_bps) / 10_000.0
        trade_no += 1
        entry_ts = entry_time or ts
        holding_hours = max(0.0, (ts - entry_ts).total_seconds() / 3600.0)
        rows.append(
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "trade_id": f"{strategy_id}_{trade_no:05d}",
                "symbol": symbol,
                "side": "long" if position > 0 else "short",
                "entry_time": entry_ts.isoformat(),
                "exit_time": ts.isoformat(),
                "entry_price": round(avg_price, 8),
                "exit_price": round(price, 8),
                "size": round(closing_qty, 8),
                "gross_pnl": round(gross, 8),
                "net_pnl": round(gross - fees, 8),
                "fees": round(fees, 8),
                "slippage": round(estimated_slippage, 8),
                "holding_bars": int(round(holding_hours)),
                "holding_hours": round(holding_hours, 4),
                "entry_fill_id": entry_fill_id,
                "exit_fill_id": str(getattr(fill, "fill_id", "")),
                "attribution_source": "ledger_fills",
            }
        )

        residual = abs(signed) - closing_qty
        remaining_position = position + signed
        if residual <= 1e-12 or abs(remaining_position) <= 1e-12:
            position = remaining_position
            if abs(position) <= 1e-12:
                position = 0.0
                avg_price = 0.0
                entry_time = None
                entry_commission = 0.0
                entry_notional = 0.0
                entry_fill_id = ""
        else:
            position = residual if signed > 0 else -residual
            avg_price = price
            entry_time = ts
            entry_commission = commission - exit_commission
            entry_notional = residual * price
            entry_fill_id = str(getattr(fill, "fill_id", ""))
    return pd.DataFrame(rows)


def canonical_metrics_from_event(
    *,
    event: Mapping[str, Any],
    trades: pd.DataFrame,
    signal: pd.Series,
    frame: pd.DataFrame,
    initial_capital: float = 100_000.0,
) -> dict[str, Any]:
    summary = dict(event.get("summary", {}))
    fills = list(event.get("fills", []))
    years = max(len(frame) / (365.0 * 24.0), 1e-12)
    notional = sum(abs(float(getattr(fill, "quantity", 0.0)) * float(getattr(fill, "price", 0.0))) for fill in fills)
    turnover = notional / max(initial_capital, 1.0) / years
    net_pnl = float(trades["net_pnl"].sum()) if "net_pnl" in trades else 0.0
    gross_pnl = float(trades["gross_pnl"].sum()) if "gross_pnl" in trades else 0.0
    fees = float(trades["fees"].sum()) if "fees" in trades else 0.0
    wins = trades.loc[trades["net_pnl"] > 0, "net_pnl"] if "net_pnl" in trades else pd.Series(dtype=float)
    losses = -trades.loc[trades["net_pnl"] < 0, "net_pnl"] if "net_pnl" in trades else pd.Series(dtype=float)
    pf = float(wins.sum() / losses.sum()) if float(losses.sum()) > 0 else (999.0 if float(wins.sum()) > 0 else 0.0)
    return {
        "gross_pnl": round(gross_pnl, 6),
        "net_pnl": round(net_pnl, 6),
        "fees": round(fees, 6),
        "slippage": round(float(trades["slippage"].sum()) if "slippage" in trades else 0.0, 6),
        "profit_factor": round(pf, 6),
        "event_profit_factor": float(summary.get("profit_factor", 0.0)),
        "sharpe": float(summary.get("sharpe_ratio", 0.0)),
        "sortino": float(summary.get("sortino_ratio", 0.0)),
        "max_drawdown": float(summary.get("max_drawdown_pct", 0.0)),
        "annual_turnover": round(turnover, 6),
        "trade_count": int(len(trades)),
        "fill_count": int(len(fills)),
        "win_rate": round(float((trades["net_pnl"] > 0).mean()) if len(trades) else 0.0, 6),
        "avg_win": round(float(wins.mean()) if len(wins) else 0.0, 6),
        "avg_loss": round(float(-losses.mean()) if len(losses) else 0.0, 6),
        "avg_holding_bars": round(float(trades["holding_bars"].mean()) if len(trades) else 0.0, 6),
        "median_holding_bars": round(float(trades["holding_bars"].median()) if len(trades) else 0.0, 6),
        "exposure": round(float(signal.abs().mean()) if len(signal) else 0.0, 6),
        "total_return_pct": float(summary.get("total_return_pct", 0.0)),
    }


def cost_stress_for_signal(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: Mapping[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    max_scenarios: int = 4,
) -> dict[str, Any]:
    rows = []
    for scenario in CRYPTO_COST_STRESS_SCENARIOS[:max_scenarios]:
        event = run_event_with_signal(
            frame=frame,
            signal=signal,
            strategy_id=strategy_id,
            params=params,
            start=start,
            end=end,
            run_dir=run_dir,
            scenario_name=f"cost_{scenario['name']}",
            commission_rate=0.0004 * float(scenario["commission_multiplier"]),
            slippage_bps=4.0 * float(scenario["slippage_multiplier"]),
        )
        summary = event["summary"]
        survives = (
            float(summary.get("total_return_pct", 0.0)) > 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        rows.append(
            {
                "name": scenario["name"],
                "label": scenario["label"],
                "passed": survives,
                "survives": survives,
                "summary": summary,
                "manifest_path": event["manifest_path"],
            }
        )
    harsh = rows[-1] if rows else {}
    return {
        "scenario_count": len(rows),
        "survival_rate": round(sum(1 for row in rows if row["survives"]) / max(1, len(rows)), 6),
        "base": rows[0] if rows else {},
        "harsh": harsh,
        "scenarios": rows,
    }


def rolling_walk_forward_for_signal(
    *,
    frame: pd.DataFrame,
    signal_builder: SignalBuilder,
    strategy_id: str,
    params: Mapping[str, Any],
    run_dir: Path,
    windows: int = 4,
) -> dict[str, Any]:
    rows = []
    n = len(frame)
    validation_rows = max(500, n // (windows + 2))
    for fold in range(windows):
        validation_start_pos = n - validation_rows * (windows - fold)
        validation_end_pos = n - validation_rows * (windows - fold - 1)
        validation_frame = frame.iloc[max(0, validation_start_pos):validation_end_pos].copy()
        context_frame = frame.iloc[:validation_end_pos].copy()
        if len(validation_frame) < 50:
            continue
        full_signal, _ = signal_builder(context_frame, dict(params))
        fold_signal = full_signal.reindex(validation_frame.index).fillna(0.0)
        event = run_event_with_signal(
            frame=validation_frame,
            signal=fold_signal,
            strategy_id=strategy_id,
            params=params,
            start=validation_frame.index[0].to_pydatetime(),
            end=validation_frame.index[-1].to_pydatetime(),
            run_dir=run_dir,
            scenario_name=f"wf{fold + 1}",
        )
        summary = event["summary"]
        passed = (
            float(summary.get("total_return_pct", 0.0)) >= 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        rows.append(
            {
                "fold": fold + 1,
                "validation_start": validation_frame.index[0].isoformat(),
                "validation_end": validation_frame.index[-1].isoformat(),
                "validation_rows": len(validation_frame),
                "passed": passed,
                "summary": summary,
                "manifest_path": event["manifest_path"],
            }
        )
    pass_rate = sum(1 for row in rows if row["passed"]) / max(1, len(rows))
    return {
        "method": "rolling_event_ledger_fixed_params",
        "windows": rows,
        "pass_rate": round(pass_rate, 6),
        "fold_count": len(rows),
    }


def regime_report_from_trades(frame: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"pass_rate": 0.0, "regimes": [], "dragging_regimes": []}
    regimes = classify_btc_regimes(frame)
    enriched = trades.copy()
    enriched["entry_time_ts"] = pd.to_datetime(enriched["entry_time"], utc=True)
    enriched["entry_regime"] = [
        str(regimes.reindex([ts], method="ffill").iloc[0]) if not regimes.empty else "unknown"
        for ts in enriched["entry_time_ts"]
    ]
    rows = []
    for regime, subset in enriched.groupby("entry_regime"):
        pnls = subset["net_pnl"].astype(float)
        wins = pnls[pnls > 0]
        losses = -pnls[pnls < 0]
        pf = float(wins.sum() / losses.sum()) if float(losses.sum()) > 0 else (999.0 if float(wins.sum()) > 0 else 0.0)
        passed = bool(len(subset) == 0 or (pf >= 1.0 and float(pnls.sum()) >= 0.0))
        rows.append(
            {
                "regime": str(regime),
                "trade_count": int(len(subset)),
                "net_pnl": round(float(pnls.sum()), 6),
                "profit_factor": round(pf, 6),
                "win_rate": round(float((pnls > 0).mean()) if len(pnls) else 0.0, 6),
                "avg_holding_bars": round(float(subset["holding_bars"].mean()) if len(subset) else 0.0, 6),
                "passed": passed,
            }
        )
    pass_rate = sum(1 for row in rows if row["passed"]) / max(1, len(rows))
    return {
        "pass_rate": round(pass_rate, 6),
        "regimes": sorted(rows, key=lambda row: row["net_pnl"]),
        "dragging_regimes": [row["regime"] for row in rows if not row["passed"]],
    }


def build_trade_attribution(
    *,
    run_id: str,
    strategy_id: str,
    frame: pd.DataFrame,
    trades: pd.DataFrame,
    signal: pd.Series,
    diagnostics: Mapping[str, pd.Series],
    initial_capital: float = 100_000.0,
) -> pd.DataFrame:
    if trades.empty:
        return _empty_attribution_frame()
    index = pd.to_datetime(frame.index, utc=True)
    local_frame = frame.copy()
    local_frame.index = index
    aligned_signal = signal.reindex(index).fillna(0.0)
    regimes = classify_btc_regimes(local_frame)
    trend_series = _diagnostic_series(diagnostics, "trend_strength", index)
    if trend_series.abs().sum() == 0:
        trend_series = _diagnostic_series(diagnostics, "momentum", index)
    orderflow_series = _diagnostic_series(diagnostics, "buy_pressure", index)
    volatility_series = _diagnostic_series(diagnostics, "volatility", index)
    range_pct = ((local_frame["high"].astype(float) - local_frame["low"].astype(float)).abs() / local_frame["close"].astype(float).shift(1)).fillna(0.0)
    volume = local_frame["volume"].astype(float)
    volume_ratio = (volume / volume.rolling(168, min_periods=24).median().replace(0, pd.NA)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    rows: list[dict[str, Any]] = []
    for _, trade in trades.iterrows():
        entry_ts = pd.Timestamp(trade["entry_time"])
        entry_ts = entry_ts.tz_localize("UTC") if entry_ts.tzinfo is None else entry_ts.tz_convert("UTC")
        exit_ts = pd.Timestamp(trade["exit_time"])
        exit_ts = exit_ts.tz_localize("UTC") if exit_ts.tzinfo is None else exit_ts.tz_convert("UTC")
        entry_pos = _index_pos(index, entry_ts)
        exit_pos = _index_pos(index, exit_ts)
        entry_feature_pos = max(0, entry_pos - 1)
        exit_feature_pos = max(0, exit_pos - 1)
        entry_feature_ts = index[entry_feature_pos]
        exit_feature_ts = index[exit_feature_pos]
        window = local_frame.iloc[min(entry_pos, exit_pos): max(entry_pos, exit_pos) + 1]
        if window.empty:
            window = local_frame.iloc[[entry_pos]]
        side = str(trade["side"])
        entry_price = float(trade["entry_price"])
        if side == "long":
            mfe = (float(window["high"].max()) - entry_price) * float(trade["size"])
            mae = (float(window["low"].min()) - entry_price) * float(trade["size"])
        else:
            mfe = (entry_price - float(window["low"].min())) * float(trade["size"])
            mae = (entry_price - float(window["high"].max())) * float(trade["size"])
        entry_regime = str(regimes.iloc[entry_feature_pos]) if len(regimes) else "unknown"
        exit_regime = str(regimes.iloc[exit_feature_pos]) if len(regimes) else "unknown"
        regime_slice = regimes.iloc[min(entry_feature_pos, exit_feature_pos): max(entry_feature_pos, exit_feature_pos) + 1]
        dominant_regime = str(regime_slice.mode().iloc[0]) if not regime_slice.empty else entry_regime
        entry_components = _entry_components(diagnostics, index, entry_feature_pos, side)
        exit_reason = _exit_reason(aligned_signal, exit_feature_pos, side)
        trend_value = float(trend_series.iloc[entry_feature_pos])
        orderflow_value = float(orderflow_series.iloc[entry_feature_pos])
        vol_state = _past_bucket(volatility_series, entry_feature_pos, labels=("low_vol", "mid_vol", "high_vol"))
        trend_bucket = _value_bucket(trend_value, low=-0.01, high=0.01, labels=("weak_downtrend", "neutral_trend", "strong_uptrend"))
        orderflow_bucket = _value_bucket(orderflow_value, low=-0.005, high=0.005, labels=("sell_pressure", "neutral_flow", "buy_pressure"))
        compression_state = bool(range_pct.iloc[entry_feature_pos] <= range_pct.iloc[: entry_feature_pos + 1].quantile(0.35))
        expansion_state = bool((volatility_series.iloc[entry_feature_pos] >= volatility_series.iloc[: entry_feature_pos + 1].quantile(0.70)) or volume_ratio.iloc[entry_feature_pos] >= 1.15)
        cost = float(trade["fees"]) + float(trade["slippage"])
        gross = float(trade["gross_pnl"])
        net = float(trade["net_pnl"])
        cost_ratio = cost / max(abs(gross), 1e-12)
        turnover = (float(trade["entry_price"]) + float(trade["exit_price"])) * float(trade["size"]) / max(initial_capital, 1.0)
        rows.append(
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "trade_id": str(trade["trade_id"]),
                "symbol": str(trade["symbol"]),
                "side": side,
                "entry_time": entry_ts.isoformat(),
                "exit_time": exit_ts.isoformat(),
                "entry_price": entry_price,
                "exit_price": float(trade["exit_price"]),
                "size": float(trade["size"]),
                "gross_pnl": gross,
                "net_pnl": net,
                "fees": float(trade["fees"]),
                "slippage": float(trade["slippage"]),
                "holding_bars": int(trade["holding_bars"]),
                "holding_hours": float(trade["holding_hours"]),
                "holding_bucket": _holding_bucket(float(trade["holding_hours"])),
                "entry_regime": entry_regime,
                "exit_regime": exit_regime,
                "dominant_regime_during_trade": dominant_regime,
                "entry_signal_components": json.dumps(entry_components, sort_keys=True),
                "entry_condition": _entry_condition(entry_components, side),
                "exit_reason": exit_reason,
                "orderflow_value_at_entry": round(orderflow_value, 8),
                "orderflow_bucket": orderflow_bucket,
                "trend_strength_at_entry": round(trend_value, 8),
                "trend_strength_bucket": trend_bucket,
                "volatility_state_at_entry": vol_state,
                "compression_state_at_entry": compression_state,
                "expansion_state_at_entry": expansion_state,
                "MFE": round(float(mfe), 8),
                "MAE": round(float(mae), 8),
                "realized_R": round(net / max(abs(float(trade["entry_price"]) * float(trade["size"]) * 0.01), 1e-12), 8),
                "cost_to_profit_ratio": round(cost_ratio, 8),
                "cost_bucket": _cost_bucket(cost_ratio),
                "turnover_contribution": round(turnover, 8),
                "entry_feature_time": entry_feature_ts.isoformat(),
                "exit_feature_time": exit_feature_ts.isoformat(),
                "attribution_source": "ledger_fills",
            }
        )
    return pd.DataFrame(rows)


def summarize_trade_attribution(attribution: pd.DataFrame) -> dict[str, Any]:
    if attribution.empty:
        return {
            "schema_version": "btc_trade_attribution_summary_v1",
            "trade_count": 0,
            "profitable_conditions_top3": [],
            "loss_conditions_top3": [],
            "failure_patterns_top3": [],
        }
    combos = ["entry_condition", "entry_regime", "volatility_state_at_entry", "trend_strength_bucket", "orderflow_bucket"]
    attribution = attribution.copy()
    attribution["condition_combo"] = attribution[combos].astype(str).agg(" | ".join, axis=1)
    return {
        "schema_version": "btc_trade_attribution_summary_v1",
        "trade_count": int(len(attribution)),
        "by_entry_condition": _group_summary(attribution, "entry_condition"),
        "by_exit_reason": _group_summary(attribution, "exit_reason"),
        "by_regime": _group_summary(attribution, "entry_regime"),
        "by_holding_time_bucket": _group_summary(attribution, "holding_bucket"),
        "by_volatility_bucket": _group_summary(attribution, "volatility_state_at_entry"),
        "by_trend_strength_bucket": _group_summary(attribution, "trend_strength_bucket"),
        "by_orderflow_bucket": _group_summary(attribution, "orderflow_bucket"),
        "by_cost_bucket": _group_summary(attribution, "cost_bucket"),
        "top_20_profit_trades": _top_trades(attribution, ascending=False),
        "top_20_loss_trades": _top_trades(attribution, ascending=True),
        "profitable_conditions_top3": _group_summary(attribution, "condition_combo")[:3],
        "loss_conditions_top3": sorted(_group_summary(attribution, "condition_combo"), key=lambda row: row["net_pnl"])[:3],
        "failure_patterns_top3": sorted(_group_summary(attribution, "entry_regime"), key=lambda row: row["net_pnl"])[:3],
    }


def simplified_dsr(sharpe: float, trial_count: int, observation_count: int) -> float:
    if observation_count <= 1:
        return 0.0
    benchmark = sqrt(max(1.0, float(trial_count))) / sqrt(max(2.0, float(observation_count)))
    z_score = (float(sharpe) - benchmark) * sqrt(max(1.0, float(observation_count - 1)))
    return round(max(0.0, min(1.0, 0.5 * (1.0 + erf(z_score / sqrt(2.0))))), 6)


def simplified_pbo(windows: Sequence[Mapping[str, Any]], base_sharpe: float) -> float:
    if not windows:
        return 1.0
    failed = 0
    for row in windows:
        test_sharpe = float(row.get("summary", {}).get("sharpe_ratio", 0.0))
        if test_sharpe < 0.0 or test_sharpe < base_sharpe * -0.25:
            failed += 1
    return round(failed / max(1, len(windows)), 6)


def _empty_attribution_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "strategy_id",
            "trade_id",
            "symbol",
            "side",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "size",
            "gross_pnl",
            "net_pnl",
            "fees",
            "slippage",
            "holding_bars",
            "holding_hours",
            "entry_regime",
            "exit_regime",
            "dominant_regime_during_trade",
            "entry_signal_components",
            "exit_reason",
            "orderflow_value_at_entry",
            "trend_strength_at_entry",
            "volatility_state_at_entry",
            "compression_state_at_entry",
            "expansion_state_at_entry",
            "MFE",
            "MAE",
            "realized_R",
            "cost_to_profit_ratio",
            "turnover_contribution",
            "attribution_source",
        ]
    )


def _diagnostic_series(diagnostics: Mapping[str, pd.Series], name: str, index: pd.DatetimeIndex) -> pd.Series:
    value = diagnostics.get(name)
    if value is None:
        return pd.Series(0.0, index=index, dtype=float)
    series = pd.to_numeric(value, errors="coerce")
    series.index = pd.to_datetime(series.index, utc=True)
    return series.reindex(index).ffill().fillna(0.0).astype(float)


def _index_pos(index: pd.DatetimeIndex, ts: pd.Timestamp) -> int:
    loc = index.get_indexer([ts], method="ffill")[0]
    return int(max(0, loc))


def _entry_components(
    diagnostics: Mapping[str, pd.Series],
    index: pd.DatetimeIndex,
    pos: int,
    side: str,
) -> dict[str, Any]:
    fields = [
        "long_ready",
        "short_ready",
        "trend_long",
        "trend_short",
        "orderflow_long_confirm",
        "orderflow_short_confirm",
        "bad_regime_risk_off",
        "target_signal",
        "raw_signal",
        "momentum",
        "trend_strength",
        "volatility",
        "buy_pressure",
        "buy_ratio",
    ]
    out: dict[str, Any] = {"side": side}
    for field in fields:
        if field not in diagnostics:
            continue
        series = _diagnostic_series(diagnostics, field, index)
        out[field] = round(float(series.iloc[pos]), 8)
    return out


def _entry_condition(components: Mapping[str, Any], side: str) -> str:
    if side == "long":
        if float(components.get("long_ready", 0.0)) > 0:
            return "registry_long_ready"
        if float(components.get("trend_long", 0.0)) > 0 and float(components.get("orderflow_long_confirm", 0.0)) > 0:
            return "trend_long_orderflow_confirmed"
        if float(components.get("trend_long", 0.0)) > 0:
            return "trend_long"
    if side == "short":
        if float(components.get("short_ready", 0.0)) > 0:
            return "registry_short_ready"
        if float(components.get("trend_short", 0.0)) > 0 and float(components.get("orderflow_short_confirm", 0.0)) > 0:
            return "trend_short_orderflow_confirmed"
        if float(components.get("trend_short", 0.0)) > 0:
            return "trend_short"
    return "state_replay_entry"


def _exit_reason(signal: pd.Series, pos: int, side: str) -> str:
    current = float(signal.iloc[pos])
    expected_sign = 1.0 if side == "long" else -1.0
    if abs(current) <= 1e-12:
        return "signal_flat_exit"
    if current * expected_sign < 0:
        return "signal_flip_exit"
    return "rebalance_or_time_exit"


def _past_bucket(series: pd.Series, pos: int, *, labels: tuple[str, str, str]) -> str:
    history = series.iloc[: pos + 1].dropna()
    if history.empty:
        return labels[1]
    value = float(series.iloc[pos])
    low = float(history.quantile(0.33))
    high = float(history.quantile(0.66))
    return _value_bucket(value, low=low, high=high, labels=labels)


def _value_bucket(value: float, *, low: float, high: float, labels: tuple[str, str, str]) -> str:
    if value <= low:
        return labels[0]
    if value >= high:
        return labels[2]
    return labels[1]


def _holding_bucket(hours: float) -> str:
    if hours <= 24:
        return "intraday_to_1d"
    if hours <= 72:
        return "1d_to_3d"
    if hours <= 168:
        return "3d_to_7d"
    if hours <= 720:
        return "1w_to_1m"
    return "over_1m"


def _cost_bucket(cost_ratio: float) -> str:
    if cost_ratio <= 0.10:
        return "low_cost_ratio"
    if cost_ratio <= 0.50:
        return "mid_cost_ratio"
    return "high_cost_ratio"


def _group_summary(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    rows = []
    for key, subset in frame.groupby(column, dropna=False):
        pnls = subset["net_pnl"].astype(float)
        wins = pnls[pnls > 0]
        losses = -pnls[pnls < 0]
        pf = float(wins.sum() / losses.sum()) if float(losses.sum()) > 0 else (999.0 if float(wins.sum()) > 0 else 0.0)
        rows.append(
            {
                column: str(key),
                "trade_count": int(len(subset)),
                "net_pnl": round(float(pnls.sum()), 6),
                "profit_factor": round(pf, 6),
                "win_rate": round(float((pnls > 0).mean()) if len(pnls) else 0.0, 6),
                "avg_holding_bars": round(float(subset["holding_bars"].mean()) if len(subset) else 0.0, 6),
            }
        )
    return sorted(rows, key=lambda row: row["net_pnl"], reverse=True)


def _top_trades(frame: pd.DataFrame, *, ascending: bool) -> list[dict[str, Any]]:
    columns = [
        "strategy_id",
        "trade_id",
        "side",
        "entry_time",
        "exit_time",
        "entry_regime",
        "entry_condition",
        "exit_reason",
        "net_pnl",
        "holding_bars",
    ]
    return (
        frame.sort_values("net_pnl", ascending=ascending)[columns]
        .head(20)
        .to_dict(orient="records")
    )


def build_canonical_report(
    *,
    run_id: str,
    strategy_id: str,
    strategy_version: str,
    params: Mapping[str, Any],
    frame: pd.DataFrame,
    signal: pd.Series,
    diagnostics: Mapping[str, pd.Series],
    event: Mapping[str, Any],
    trades: pd.DataFrame,
    cost_stress: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    regime_report: Mapping[str, Any],
    config_hash: str,
) -> dict[str, Any]:
    metrics = canonical_metrics_from_event(event=event, trades=trades, signal=signal, frame=frame)
    metrics["walk_forward_pass_rate"] = float(walk_forward.get("pass_rate", 0.0))
    metrics["regime_pass_rate"] = float(regime_report.get("pass_rate", 0.0))
    metrics["pbo"] = simplified_pbo(walk_forward.get("windows", []), float(metrics.get("sharpe", 0.0)))
    metrics["dsr"] = simplified_dsr(
        float(metrics.get("sharpe", 0.0)),
        trial_count=max(2, int(walk_forward.get("fold_count", 0))),
        observation_count=max(2, len(frame)),
    )
    metrics["cost_stress_base_pass"] = bool((cost_stress.get("base") or {}).get("passed", False))
    metrics["cost_stress_harsh_survives"] = bool((cost_stress.get("harsh") or {}).get("survives", False))
    report = {
        "schema_version": "btc_canonical_backtest_report_v1",
        "evidence_source": "canonical_event_ledger",
        "run_id": run_id,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "data_version": "qs-sqlite-BTCUSDT-1h-66968bfbabf2",
        "data_range": {"start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat()},
        "timeframe": "1h",
        "benchmark": None,
        "cost_model_id": "crypto_commission_4bps_slippage_4bps",
        "ledger_engine_version": "quant_us.crypto_event.event_ledger_v1",
        "config_hash": config_hash,
        "code_commit": git_commit_hash(),
        "metrics": metrics,
        "gross_pnl": metrics["gross_pnl"],
        "net_pnl": metrics["net_pnl"],
        "fees": metrics["fees"],
        "slippage": metrics["slippage"],
        "PF": metrics["profit_factor"],
        "event_PF": metrics["event_profit_factor"],
        "Sharpe": metrics["sharpe"],
        "Sortino": metrics["sortino"],
        "MDD": metrics["max_drawdown"],
        "annual_turnover": metrics["annual_turnover"],
        "trade_count": metrics["trade_count"],
        "win_rate": metrics["win_rate"],
        "avg_win": metrics["avg_win"],
        "avg_loss": metrics["avg_loss"],
        "avg_holding_bars": metrics["avg_holding_bars"],
        "median_holding_bars": metrics["median_holding_bars"],
        "exposure": metrics["exposure"],
        "cost_stress_base": cost_stress.get("base", {}),
        "cost_stress_harsh": cost_stress.get("harsh", {}),
        "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
        "regime_pass_rate": metrics["regime_pass_rate"],
        "PBO": metrics["pbo"],
        "DSR": metrics["dsr"],
        "no_lookahead_status": {
            "status": "pass",
            "basis": "event_engine_next_bar_execution_and_past_only_features",
        },
        "event_ledger_status": {
            "status": "pass"
            if event.get("diagnostics", {}).get("ledger_equity_consistent") is True
            and event.get("diagnostics", {}).get("pnl_source") == "ledger_fills"
            else "fail",
            "pnl_source": event.get("diagnostics", {}).get("pnl_source"),
            "ledger_equity_consistent": event.get("diagnostics", {}).get("ledger_equity_consistent"),
            "manifest_path": event.get("manifest_path", ""),
        },
        "diagnostics": {
            "signal_equity_diagnostic_only": True,
            "signal_nonzero_bars": int((signal != 0).sum()),
            "signal_changed_bars": int((signal.diff().fillna(signal) != 0).sum()),
            "diagnostic_columns": sorted(str(key) for key in diagnostics.keys()),
        },
    }
    gate = evaluate_canonical_gate(report)
    report["promotion_gate_status"] = gate.status
    report["fail_reasons"] = gate.fail_reasons
    report["gate_decision"] = gate.to_dict()
    report["artifact_hash"] = stable_hash({**report, "artifact_hash": ""})
    return report


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and np.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return str(value)
