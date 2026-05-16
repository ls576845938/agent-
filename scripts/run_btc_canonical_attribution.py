#!/usr/bin/env python3
"""Generate canonical BTC event-ledger evidence artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.services.market_data import load_market_frame
from quant_us.research.btc_alpha_hardening import btc_dual_trend_v2_signal
from quant_us.research.btc_canonical import (
    btc_perp_dual_trend_v3_signal,
    build_trade_attribution,
    build_canonical_report,
    cost_stress_for_signal,
    decide_paper_queue_from_canonical,
    evaluate_canonical_gate,
    fills_to_trade_ledger,
    registry_signal_builder,
    regime_report_from_trades,
    rolling_walk_forward_for_signal,
    run_event_with_signal,
    stable_hash,
    summarize_trade_attribution,
    write_json,
)


STRATEGIES: dict[str, tuple[str, dict[str, Any], Any]] = {
    "btc_perp_dual_trend": (
        "btc_perp_dual_trend:registry_baseline_v1",
        {},
        registry_signal_builder("btc_perp_dual_trend"),
    ),
    "btc_perp_dual_trend_v2": (
        "btc_perp_dual_trend_v2:alpha_hardening_v2",
        {
            "fast_ma": 96,
            "slow_ma": 336,
            "regime_ma": 720,
            "momentum_window": 168,
            "momentum_threshold": 0.025,
            "vol_window": 168,
            "max_volatility": 0.05,
            "buy_ratio_threshold": 0.54,
            "sell_ratio_threshold": 0.46,
            "pressure_threshold": 0.0075,
            "orderflow_window": 144,
            "activity_window": 144,
            "min_quote_intensity": 0.75,
            "min_trade_intensity": 0.70,
            "signal_persistence_bars": 3,
            "exit_hysteresis_bars": 4,
            "min_hold_bars": 120,
            "cooldown_bars": 72,
            "max_hold_bars": 720,
            "signal_scale": 0.20,
            "blocked_regimes": ["low_vol_chop", "mean_reverting_chop", "liquidation_shock"],
        },
        btc_dual_trend_v2_signal,
    ),
    "btc_perp_dual_trend_v3": (
        "btc_perp_dual_trend_v3:attribution_v1",
        {
            "fast_ma": 96,
            "slow_ma": 336,
            "regime_ma": 720,
            "momentum_window": 168,
            "momentum_threshold": 0.025,
            "vol_window": 168,
            "max_volatility": 0.055,
            "orderflow_window": 144,
            "orderflow_veto_threshold": 0.012,
            "allowed_long_regimes": ["trending_up", "expansion"],
            "allowed_short_regimes": [],
            "min_hold_bars": 120,
            "cooldown_bars": 72,
            "exit_hysteresis_bars": 4,
            "max_hold_bars": 720,
            "signal_scale": 0.20,
        },
        btc_perp_dual_trend_v3_signal,
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--output-root", default="artifacts/btc_canonical")
    parser.add_argument("--strategies", default="btc_perp_dual_trend,btc_perp_dual_trend_v2,btc_perp_dual_trend_v3")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 12, tzinfo=timezone.utc)
    frame = load_market_frame(
        source="sqlite",
        symbol="BTCUSDT",
        interval="1h",
        start=start,
        end=end,
        db_path="data/market_data.sqlite",
    )

    reports = []
    gate_inputs = []
    all_trade_rows = []
    all_attribution_rows = []
    selected = [item.strip() for item in args.strategies.split(",") if item.strip()]
    for strategy_id in selected:
        if strategy_id not in STRATEGIES:
            raise ValueError(f"unknown canonical strategy: {strategy_id}")
        strategy_version, params, signal_builder = STRATEGIES[strategy_id]
        signal, diagnostics = signal_builder(frame, dict(params))
        event = run_event_with_signal(
            frame=frame,
            signal=signal,
            strategy_id=strategy_id,
            params=params,
            start=start,
            end=end,
            run_dir=run_dir,
            scenario_name="base",
        )
        trades = fills_to_trade_ledger(
            event["fills"],
            run_id=args.run_id,
            strategy_id=strategy_id,
            symbol="BTCUSDT",
            slippage_bps=4.0,
        )
        cost = cost_stress_for_signal(
            frame=frame,
            signal=signal,
            strategy_id=strategy_id,
            params=params,
            start=start,
            end=end,
            run_dir=run_dir,
            max_scenarios=4,
        )
        wf = rolling_walk_forward_for_signal(
            frame=frame,
            signal_builder=signal_builder,
            strategy_id=strategy_id,
            params=params,
            run_dir=run_dir,
            windows=4,
        )
        regime = regime_report_from_trades(frame, trades)
        attribution = build_trade_attribution(
            run_id=args.run_id,
            strategy_id=strategy_id,
            frame=frame,
            trades=trades,
            signal=signal,
            diagnostics=diagnostics,
        )
        attribution_summary = summarize_trade_attribution(attribution)
        report = build_canonical_report(
            run_id=args.run_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            params=params,
            frame=frame,
            signal=signal,
            diagnostics=diagnostics,
            event=event,
            trades=trades,
            cost_stress=cost,
            walk_forward=wf,
            regime_report=regime,
            config_hash=stable_hash(params),
        )
        decision = evaluate_canonical_gate(report)
        strategy_dir = run_dir / strategy_id
        strategy_dir.mkdir(parents=True, exist_ok=True)
        trades.to_csv(strategy_dir / "trade_ledger.csv", index=False)
        trades.to_parquet(strategy_dir / "trade_ledger.parquet", index=False)
        attribution.to_csv(strategy_dir / "trade_attribution.csv", index=False)
        attribution.to_parquet(strategy_dir / "trade_attribution.parquet", index=False)
        write_json(strategy_dir / "trade_attribution_summary.json", attribution_summary)
        write_json(strategy_dir / "canonical_backtest_report.json", report)
        write_json(strategy_dir / "canonical_metrics.json", report["metrics"])
        write_json(strategy_dir / "gate_inputs.json", {"strategy_id": strategy_id, "report": report, "gate": decision.to_dict()})
        write_json(run_dir / f"{strategy_id}_results.json", report)
        write_json(run_dir / f"{strategy_id}_gate_decision.json", decision.to_dict())
        write_json(strategy_dir / "run_manifest.json", {
            "run_id": args.run_id,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "data_version": report["data_version"],
            "config_hash": report["config_hash"],
            "artifact_hash": report["artifact_hash"],
            "manifest_path": report["event_ledger_status"]["manifest_path"],
        })
        reports.append(report)
        gate_inputs.append(decision.to_dict())
        if not trades.empty:
            all_trade_rows.append(trades)
        if not attribution.empty:
            all_attribution_rows.append(attribution)

    aggregate = {
        "schema_version": "btc_canonical_aggregate_v1",
        "run_id": args.run_id,
        "strategies": reports,
        "gate_inputs": gate_inputs,
        "paper_review": decide_paper_queue_from_canonical(gate_inputs),
        "live_frozen": True,
        "paper_auto_start": False,
    }
    write_json(run_dir / "canonical_backtest_report.json", aggregate)
    write_json(run_dir / "canonical_metrics.json", {"run_id": args.run_id, "strategies": [row["metrics"] | {"strategy_id": row["strategy_id"]} for row in reports]})
    write_json(run_dir / "gate_inputs.json", {"run_id": args.run_id, "gate_inputs": gate_inputs})
    write_json(run_dir / "promotion_decision.json", {
        "run_id": args.run_id,
        "candidate_gate_results": gate_inputs,
        "paper_review": aggregate["paper_review"],
        "live_frozen": True,
        "paper_auto_start": False,
        "evidence_source": "canonical_gate_inputs",
    })
    if all_attribution_rows:
        import pandas as pd

        combined_attribution = pd.concat(all_attribution_rows, ignore_index=True)
        combined_attribution.to_csv(run_dir / "trade_attribution.csv", index=False)
        combined_attribution.to_parquet(run_dir / "trade_attribution.parquet", index=False)
        write_json(run_dir / "trade_attribution_summary.json", summarize_trade_attribution(combined_attribution))
    if all_trade_rows:
        import pandas as pd

        combined_trades = pd.concat(all_trade_rows, ignore_index=True)
        combined_trades.to_csv(run_dir / "trade_ledger.csv", index=False)
        combined_trades.to_parquet(run_dir / "trade_ledger.parquet", index=False)
    print(f"wrote {run_dir}")


if __name__ == "__main__":
    main()
