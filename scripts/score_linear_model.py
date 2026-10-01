from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quant_us.research.experiments import ExperimentRegistry
from quant_us.research.model_scores import LinearModelScoreBuilder, LinearModelSpec


def load_json_arg(value: str, path: str) -> dict:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(value or "{}")


def main() -> None:
    parser = ArgumentParser(description="Score an ML dataset with a linear model artifact and write scores to the feature store.")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--feature-names", required=True, help="Comma-separated feature columns used by the model.")
    parser.add_argument("--weights-json", default="{}")
    parser.add_argument("--weights-file", default="")
    parser.add_argument("--intercept", type=float, default=0.0)
    parser.add_argument("--score-name", default="model_score")
    parser.add_argument("--score-version", default="")
    parser.add_argument("--feature-version", default="")
    parser.add_argument("--dataset-run-id", default="")
    parser.add_argument("--universe", default="default")
    parser.add_argument("--split", default="")
    parser.add_argument("--data-root", default="data")
    args = parser.parse_args()

    spec = LinearModelSpec(
        model_id=args.model_id,
        feature_names=[item.strip() for item in args.feature_names.split(",") if item.strip()],
        weights={str(key): float(value) for key, value in load_json_arg(args.weights_json, args.weights_file).items()},
        intercept=args.intercept,
        score_name=args.score_name,
        score_version=args.score_version,
        feature_version=args.feature_version,
        dataset_run_id=args.dataset_run_id,
    )
    result = LinearModelScoreBuilder(
        feature_root=Path(args.data_root) / "features",
        model_root=Path(args.data_root) / "models",
        registry=ExperimentRegistry(Path(args.data_root) / "experiments"),
    ).score_dataset(args.dataset_path, spec, universe=args.universe, split=args.split)
    print(result)
    if result.status != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
