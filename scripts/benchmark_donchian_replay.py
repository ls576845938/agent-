"""Offline engineering benchmark; not an additional strategy research trial.

Run this same harness against two committed source roots, then compare the
economic_projection. Version-bound evidence IDs are intentionally not compared
across source versions; each full result remains beside its original ledger.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--case", choices=("history", "continuous"), required=True)
    parser.add_argument("--events", type=int, default=24)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    sys.path.insert(0, str(root))
    def deny(*_args, **_kwargs):
        raise AssertionError("benchmark_network_prohibited")
    socket.create_connection = deny
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "quant_crypto", "quant_shared"], cwd=root, text=True)
    if dirty.strip():
        raise ValueError("benchmark_requires_committed_source")
    from quant_crypto.application.donchian_historical_replay import DonchianHistoricalReplay
    from quant_crypto.application.donchian_offline_replay import (
        DonchianOfflineReplay, DonchianOfflineReplayConfig, build_closeout_scenario,
    )
    phase_seconds = []
    original_run_frame = DonchianOfflineReplay.run_frame
    def timed_frame(self, *values, **options):
        started_phase = time.perf_counter()
        try:
            return original_run_frame(self, *values, **options)
        finally:
            phase_seconds.append(time.perf_counter() - started_phase)
    DonchianOfflineReplay.run_frame = timed_frame
    output = args.output_root.resolve()
    if output.exists():
        raise ValueError("benchmark_output_must_be_new")
    output.mkdir(parents=True)
    started = time.perf_counter()
    started_cpu = time.process_time()
    if args.case == "history":
        runner = DonchianHistoricalReplay(
            repo_root=root, output_root=output, run_id="performance-history-fixed",
            spec_git="25c00b0c7004d4b02afb419f2fddaa90b1cab26c:docs/research/donchian-long-50usdt-20260921.json",
        )
        result = runner.run(max_events=args.events)
        if result["status"] == "blocked" or len(result["events"]) != args.events:
            raise AssertionError(f"benchmark_history_incomplete:{result.get('blockers')}")
        events = []
        for row in result["events"]:
            event = {k: v for k, v in row.items() if k != "phases"}
            event["phases"] = [{k: v for k, v in phase.items() if k != "evidence_links"} for phase in row["phases"]]
            events.append(event)
        projection = {"events": events, "counts": result["counts"], "safety": result["safety"]}
    else:
        fixture = json.loads((root / "tests/fixtures/strategy_v1/offline_contract.json").read_text(encoding="utf-8"))
        frame = build_closeout_scenario(start=datetime.fromisoformat(fixture["scenario"]["start_utc"]))
        when = datetime.fromisoformat(fixture["scenario"]["observation_time_utc"])
        def new_runner():
            return DonchianOfflineReplay(DonchianOfflineReplayConfig(
                repo_root=root, state_dir=output / "state", run_id="performance-continuous-fixed",
                decision_time_utc=when, data_version="v1-closeout-continuous-ohlcv-v1",
                max_notional_usdt=Decimal("50"),
            ))
        runner = new_runner()
        rows = []
        for name in ("open_long", "hold_long", "reverse_to_short", "reverse_to_short", "exit_short"):
            prefix = frame.iloc[:fixture["scenario"]["checkpoint_offsets"][name] + 1].copy()
            result = runner.run_frame(prefix)
            rows.append({key: result.get(key) for key in (
                "phase", "decision_outcome", "signal", "position_contracts", "cash_usdt", "equity_usdt",
                "submit_count", "fill_count", "decision_evidence_count", "cancel_algo_count", "safety",
            )})
            # Signal's generated UUID is not a business decision. Its exact
            # linkage is checked within each run by the V1 contract tests.
            rows[-1]["signal"] = {key: value for key, value in rows[-1]["signal"].items() if key != "signal_id"}
            if result["phase"] != "reversal_close":
                duplicate = runner.run_frame(prefix)
                assert duplicate["submit_count"] == result["submit_count"]
                assert duplicate["fill_count"] == result["fill_count"]
            runner.close()
            runner = new_runner()
            if result["phase"] != "reversal_close":
                recovered = runner.run_frame(prefix)
                assert recovered["submit_count"] == result["submit_count"]
                assert recovered["fill_count"] == result["fill_count"]
        expected = fixture["expected"]
        assert result["submit_count"] == expected["submit_count"] == 4
        assert result["fill_count"] == expected["fill_count"] == 4
        assert Decimal(result["equity_usdt"]) == Decimal(expected["final_equity_usdt"])
        assert sum(Decimal(fill["fee"]) for fill in runner.venue.state["fills"]) == Decimal(expected["total_fees_usdt"])
        assert result["ledger"]["payload"]["risk_context"]["account_ledger_replay"]["status"] == "reconciled"
        projection = {"decisions": rows, "economics": {key: runner.venue.state[key] for key in ("position", "equity")},
                      "ledger": {key: result["ledger"]["payload"][key] for key in ("cash_ledger", "position_ledger", "funding_ledger")},
                      "fills": [{key: fill.get(key) for key in ("side", "posSide", "fillPx", "fillSz", "fee", "feeCcy")} for fill in runner.venue.state["fills"]]}
        runner.close()
    elapsed = time.perf_counter() - started
    report = {"kind": "engineering_performance_not_strategy_search", "source_head": head,
              "case": args.case, "elapsed_seconds": elapsed, "economic_projection": projection,
              "process_cpu_seconds": time.process_time() - started_cpu,
              "phase_seconds": phase_seconds,
              "network_accessed": False, "trading_authorized": False}
    (output / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps({"case": args.case, "elapsed_seconds": elapsed, "report": str(output / "benchmark.json")}))


if __name__ == "__main__":
    main()
