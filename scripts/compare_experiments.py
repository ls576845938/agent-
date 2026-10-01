from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.experiments import ExperimentRegistry


def main() -> None:
    parser = ArgumentParser(description="Compare registered research experiments by a chosen metric.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--experiment-name", default="")
    parser.add_argument("--metric", default="sharpe_ratio")
    parser.add_argument("--ascending", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    registry = ExperimentRegistry(Path(args.data_root) / "experiments")
    rows = registry.compare(
        metric=args.metric,
        experiment_name=args.experiment_name or None,
        descending=not args.ascending,
    )
    for row in rows[: args.limit]:
        print(row)


if __name__ == "__main__":
    main()
