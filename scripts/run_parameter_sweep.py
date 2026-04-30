from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.sweeps import ResearchSweepRunner, SweepConfig


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_grid(grid_json: str, grid_file: str) -> dict[str, object]:
    if grid_file:
        return json.loads(Path(grid_file).read_text(encoding="utf-8"))
    return json.loads(grid_json or "{}")


def main() -> None:
    parser = ArgumentParser(description="Run a parameter sweep and register each run as a comparable experiment.")
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategy-id", default="trend_momentum")
    parser.add_argument("--grid-json", default='{"lookback_bars":[10,20],"entry_threshold":[0.01,0.03]}')
    parser.add_argument("--grid-file", default="")
    parser.add_argument("--portfolio-grid-json", default="{}")
    parser.add_argument("--portfolio-grid-file", default="")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--vendor", default="yfinance")
    parser.add_argument("--bar-size", default="1d")
    parser.add_argument("--feature-version", default="")
    parser.add_argument("--feature-universe", default="default")
    parser.add_argument("--feature-names", default="")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--max-symbol-weight", type=float, default=0.10)
    parser.add_argument("--max-order-notional-pct", type=float, default=0.10)
    parser.add_argument("--cash-reserve-weight", type=float, default=0.05)
    parser.add_argument("--default-strategy-weight", type=float, default=0.10)
    parser.add_argument("--min-trade-notional", type=float, default=25.0)
    parser.add_argument("--min-weight-change", type=float, default=0.0)
    parser.add_argument("--compare-metric", default="sharpe_ratio")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    config = SweepConfig(
        experiment_name=args.experiment_name,
        symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()],
        start=parse_utc(args.start),
        end=parse_utc(args.end),
        strategy_id=args.strategy_id,
        parameter_grid=load_grid(args.grid_json, args.grid_file),
        portfolio_grid=load_grid(args.portfolio_grid_json, args.portfolio_grid_file),
        data_root=args.data_root,
        vendor=args.vendor,
        bar_size=args.bar_size,
        feature_version=args.feature_version,
        feature_universe=args.feature_universe,
        feature_names=[item.strip() for item in args.feature_names.split(",") if item.strip()],
        capital=args.capital,
        max_symbol_weight=args.max_symbol_weight,
        max_order_notional_pct=args.max_order_notional_pct,
        cash_reserve_weight=args.cash_reserve_weight,
        default_strategy_weight=args.default_strategy_weight,
        min_trade_notional=args.min_trade_notional,
        min_weight_change=args.min_weight_change,
        tags=args.tag,
        notes=args.notes,
    )
    result = ResearchSweepRunner().run(config, compare_metric=args.compare_metric)
    print({"experiment_name": result.experiment_name, "runs": len(result.records), "best": result.best})


if __name__ == "__main__":
    main()
