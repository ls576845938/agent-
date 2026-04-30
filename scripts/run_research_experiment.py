from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.backtest.configuration import build_backtest_config
from quant_us.backtest.result_store import BacktestResultStore
from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.research.experiments import ArtifactRef, ExperimentRegistry, ExperimentSpec


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = ArgumentParser(description="Run a reproducible research backtest and register it as an experiment.")
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategy-id", default="trend_momentum")
    parser.add_argument("--strategy-params-json", default="{}")
    parser.add_argument("--feature-names", default="")
    parser.add_argument("--feature-universe", default="default")
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--vendor", default="yfinance")
    parser.add_argument("--feature-version", default="")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--max-symbol-weight", type=float, default=0.10)
    parser.add_argument("--max-order-notional-pct", type=float, default=0.10)
    parser.add_argument("--cash-reserve-weight", type=float, default=0.05)
    parser.add_argument("--default-strategy-weight", type=float, default=0.10)
    parser.add_argument("--min-trade-notional", type=float, default=25.0)
    parser.add_argument("--min-weight-change", type=float, default=0.0)
    parser.add_argument("--backtest-params-json", default="{}")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    strategy_params = json.loads(args.strategy_params_json)
    backtest_params = {
        **json.loads(args.backtest_params_json),
        "capital": args.capital,
        "max_symbol_weight": args.max_symbol_weight,
        "max_order_notional_pct": args.max_order_notional_pct,
        "cash_reserve_weight": args.cash_reserve_weight,
        "default_strategy_weight": args.default_strategy_weight,
        "min_trade_notional": args.min_trade_notional,
        "min_weight_change": args.min_weight_change,
    }
    config = build_backtest_config(parameters=backtest_params)
    result = run_event_backtest_from_lake(
        data_root=args.data_root,
        symbol=symbols[0],
        symbols=symbols,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        bar_size=args.bar_size,
        vendor=args.vendor,
        asset_class="equity",
        strategy_id=args.strategy_id,
        strategy_params=strategy_params,
        feature_names=[item.strip() for item in args.feature_names.split(",") if item.strip()],
        config=config,
        feature_version=args.feature_version or "v1",
        feature_universe=args.feature_universe,
    )
    persisted = BacktestResultStore(Path(args.data_root) / "backtest_results").write(result)
    registry = ExperimentRegistry(Path(args.data_root) / "experiments")
    spec = ExperimentSpec(
        experiment_name=args.experiment_name,
        run_type="event_backtest",
        symbols=symbols,
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        strategy_id=args.strategy_id,
        data_vendor=args.vendor,
        asset_class="equity",
        bar_size=args.bar_size,
        feature_version=args.feature_version,
        parameters={
            "strategy_params": strategy_params,
            "backtest_params": backtest_params,
            "feature_names": [item.strip() for item in args.feature_names.split(",") if item.strip()],
            "feature_universe": args.feature_universe,
        },
        tags=args.tag,
        notes=args.notes,
    )
    record = registry.create_record(
        run_id=result.run_id,
        spec=spec,
        metrics=result.summary,
        artifacts=[
            ArtifactRef("summary", persisted.summary_path, "json"),
            ArtifactRef("metadata", persisted.metadata_path, "json"),
            ArtifactRef("orders", persisted.orders_path, "parquet"),
            ArtifactRef("fills", persisted.fills_path, "parquet"),
            ArtifactRef("portfolio_snapshots", persisted.snapshots_path, "parquet"),
        ],
    )
    manifest_path = registry.register(record)
    print({"run_id": result.run_id, "summary": result.summary, "manifest_path": str(manifest_path)})


if __name__ == "__main__":
    main()
