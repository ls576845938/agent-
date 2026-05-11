from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from .schemas import (
    QlibStrategyManifest,
    build_run_paths,
    load_yaml_file,
    make_run_id,
    read_json,
    render_templates,
    resolve_git_commit,
    resolve_run_id,
    utc_now_iso,
    write_json,
)


def compile_qlib_strategy_manifest(
    *,
    run_id: str,
    config_path: str | Path,
    artifacts_root: str | Path = "artifacts/qlib_runs",
) -> Path:
    resolved_run_id = resolve_run_id(run_id, artifacts_root)
    run_paths = build_run_paths(resolved_run_id, artifacts_root, create=False)
    config = render_templates(load_yaml_file(config_path), {"run_id": resolved_run_id})
    model_config = _model_config(config)
    lineage_config = config.get("lineage", {}) if isinstance(config.get("lineage", {}), dict) else {}
    dataset_manifest = read_json(run_paths.qlib_input_dir / "dataset_manifest.json")
    workflow_result = read_json(run_paths.run_root / "workflow_run_result.json") if (run_paths.run_root / "workflow_run_result.json").exists() else {}
    imported_metrics_path = run_paths.run_root / "imported_recorder_metrics.json"
    pred_score_import_path = run_paths.run_root / "pred_score_import_result.json"
    research_model_scores_path = run_paths.run_root / "research_model_scores.parquet"
    scores = pd.read_parquet(research_model_scores_path) if research_model_scores_path.exists() else pd.DataFrame()
    imported_metrics = read_json(imported_metrics_path) if imported_metrics_path.exists() else {}
    strategy_version = str(
        lineage_config.get(
            "strategy_version",
            model_config.get("strategy_version", config.get("run_id_prefix", "qlib_strategy")),
        )
    )

    manifest = QlibStrategyManifest(
        manifest_id=make_run_id("qlib_manifest"),
        run_id=resolved_run_id,
        source="qlib",
        status="candidate",
        promotion_status="candidate",
        mode=str(config.get("mode", "research_only")),
        timeframe="1d",
        created_at=utc_now_iso(),
        universe_id=str(dataset_manifest.get("universe", {}).get("universe_id", "")),
        symbols=list(dataset_manifest.get("symbols_exported", [])),
        strategy_version=strategy_version,
        model_id=str(model_config.get("name", workflow_result.get("model_id", "qlib_model"))),
        feature_set=str(model_config.get("feature_set", lineage_config.get("feature_set", ""))),
        label=str(model_config.get("label", lineage_config.get("label", ""))),
        data_versions=sorted(
            {
                str(item.get("data_version", ""))
                for item in dataset_manifest.get("source_manifests", [])
                if str(item.get("data_version", ""))
            }
        ),
        dataset_manifest_path=str((run_paths.qlib_input_dir / "dataset_manifest.json").resolve()),
        qlib_config_path=str(Path(config_path).resolve()),
        pred_score_path=str((run_paths.run_root / "pred_score.parquet").resolve()),
        research_model_scores_path=str(research_model_scores_path.resolve()),
        recorder_metrics_path=str((run_paths.run_root / "recorder_metrics.json").resolve()),
        imported_recorder_metrics_path=str(imported_metrics_path.resolve()),
        qlib_backtest_summary_path=str((run_paths.run_root / "qlib_backtest_summary.json").resolve()),
        params=dict(model_config.get("params", {})),
        cost_model=dict(lineage_config.get("cost_model", {})),
        slippage_model=dict(lineage_config.get("slippage_model", {})),
        commit_hash=resolve_git_commit("."),
        restrictions=[
            "research_only",
            "candidate_only",
            "requires_internal_event_driven_backtest",
            "requires_promotion_gate_before_paper_review",
        ],
        evidence={
            "workflow_status": workflow_result.get("status", ""),
            "pred_score_rows": int(len(scores)),
            "pred_score_import_result_path": str(pred_score_import_path.resolve()),
            "source_manifest_count": len(dataset_manifest.get("source_manifests", [])),
        },
    )
    output_path = run_paths.run_root / "qlib_strategy_manifest.json"
    payload = asdict(manifest)
    payload.update(
        {
            "strategy_id": strategy_version,
            "signal_freq": "1d",
            "execution_freq": "deferred_to_system",
            "model_type": "LightGBM",
            "validation_metrics": imported_metrics.get("metrics_payload", {}),
            "reason": "Qlib research completed; pending internal event-driven backtest, cost stress, walk-forward, paper review.",
            "risk_limits_placeholder": {
                "long_only": True,
                "max_symbol_weight": 0.15,
                "requires_internal_risk_gate": True,
            },
            "decommission_rules_placeholder": [
                "Disable if internal event-driven backtest fails.",
                "Disable if cost stress or walk-forward robustness fails.",
                "Disable if paper review reconciliation fails.",
            ],
        }
    )
    write_json(output_path, payload)
    return output_path


def _model_config(config: dict) -> dict:
    model = config.get("model", {})
    if isinstance(model, dict):
        return model
    if model is None:
        return {}
    return {"name": str(model)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile a candidate-only Qlib strategy manifest.")
    parser.add_argument("--run-id", required=True, help="Run id to compile.")
    parser.add_argument("--config", default="configs/qlib/us_lgbm_alpha158_daily.yaml", help="Path to Qlib workflow config.")
    parser.add_argument("--artifacts-root", default="artifacts/qlib_runs", help="Qlib artifacts root.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = compile_qlib_strategy_manifest(
        run_id=args.run_id,
        config_path=args.config,
        artifacts_root=args.artifacts_root,
    )
    print(json.dumps({"manifest_path": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
