"""Real historical research QA. No mocks, downloads, private endpoints or approvals.

Outputs are exclusively task-owned and research-only. A completed run is NOT
strategy quality or promotion approval. Use a fresh output directory per attempt.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def jsonable(value):
    if is_dataclass(value):
        return asdict(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stage", choices=["rules", "qlib"], required=True)
    parser.add_argument("--confirm-task-owned-data-root", action="store_true", help="Confirm exclusive ownership: rules also writes data-root/features and data-root/research, not just output-root.")
    args = parser.parse_args()
    data = args.data_root.resolve(strict=True)
    if not args.confirm_task_owned_data_root:
        raise SystemExit("This runner also writes features/research under data-root. Explicit task-owned-root confirmation is required.")
    owner_path = data / ".research-workbench-owner.json"
    if not owner_path.is_file() or json.loads(owner_path.read_text(encoding="utf-8")).get("ticket") != "RESEARCH-WORKBENCH-REFACTOR-01":
        raise SystemExit("Task-owned data-root marker missing or mismatched. Do not use a shared or canonical data directory.")
    common_dir = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO, text=True).strip())
    if data == (common_dir.parent / "data").resolve():
        raise SystemExit("Canonical data is never a valid QA writer target.")
    output = args.output_root.resolve()
    if output.exists():
        raise SystemExit("Use a fresh output directory; prior evidence is never overwritten.")
    if not (data / "cleaned").is_dir() or not (data / "manifests").is_dir():
        raise SystemExit("An explicit historical cleaned-data root with manifests is required.")
    output.mkdir(parents=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    receipt = {
        "schema_version": "research_workbench_verification_v1",
        "code_head": head, "started_at": datetime.now(timezone.utc).isoformat(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "data_root": str(data), "output_root": str(output),
        "stage": args.stage, "research_only": True, "fixture_data_used": False,
        "promotion_eligible": False, "paper_enabled": False, "live_enabled": False,
        "private_endpoint_called": False, "order_endpoint_called": False,
        "real_order_submitted": False, "stages": {}, "packages": {},
        "source_manifest_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((data / "manifests").glob("*.json"))},
    }
    for name in ["pyqlib", "lightgbm", "PyPortfolioOpt", "numpy", "pandas"]:
        try:
            receipt["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            receipt["packages"][name] = None

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def stage(name, fn):
        print(f"START {name}", flush=True)
        try:
            result = jsonable(fn())
            payload = result if isinstance(result, dict) else {"result": result}
            status = str(payload.get("status", "completed"))
            receipt["stages"][name] = {"status": status, "result": payload}
        except Exception as exc:
            receipt["stages"][name] = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
        save()
        print(f"END {name}: {receipt['stages'][name]['status']}", flush=True)
        return receipt["stages"][name]

    save()
    try:
        symbols = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL"]
        if args.stage == "rules":
            from quant_us.factors.evaluation import FactorEvaluator
            from quant_us.factors.pipeline import FactorPipeline
            from quant_us.research.automation.pipeline import ResearchAutomationPipeline

            def factors():
                result = FactorEvaluator(str(data)).evaluate("momentum_60d", symbols, "2024-01-01", "2024-12-31", bar_size="1d")
                if result.n_observations <= 0:
                    raise RuntimeError("Factor evaluation produced no observations.")
                return asdict(result)
            stage("factor_evaluation", factors)

            def snapshot():
                pipeline = FactorPipeline(str(data), data_vendor="yfinance")
                frame = pipeline.compute(["momentum_60d"], symbols, "2024-01-01", "2024-12-31")
                path = pipeline.save_snapshot(frame, "momentum_60d", "2024-12-31")
                if not path or frame.empty:
                    raise RuntimeError("No feature snapshot was produced.")
                return {"rows": len(frame), "snapshot_path": path}
            stage("feature_snapshot", snapshot)

            config = {
                "experiment_name": "research_workbench_historical_qa",
                "strategy_id": "trend_momentum", "symbols": ["AAPL", "MSFT"],
                "params": {"lookback_bars": 20}, "param_grid": {"lookback_bars": [10, 20]},
                "start_date": "2024-01-01", "end_date": "2024-12-31", "bar_size": "1d",
            }
            receipt["rule_config"] = config
            stage("rule_research_cycle", lambda: ResearchAutomationPipeline(str(data)).run(config))
        else:
            import yaml
            from integrations.qlib_adapter.build_qlib_dataset import build_qlib_dataset
            from integrations.qlib_adapter.run_qlib_workflow import run_qlib_workflow
            from integrations.qlib_adapter.import_recorder_metrics import import_recorder_metrics
            from quant_us.research.orchestration.research_execution_pipeline import ResearchExecutionPipelineConfig, run_research_execution_pipeline

            os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"
            os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
            os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
            run_id = "historical_qa"
            qlib_root = output / "qlib_runs"
            config = yaml.safe_load((REPO / "configs/qlib/us_lgbm_alpha158_daily.yaml").read_text(encoding="utf-8"))
            config["qlib_init"]["kernels"] = 2
            config["qlib_init"]["exp_manager"]["kwargs"]["uri"] = "sqlite:///" + (output / "mlflow.db").as_posix()
            config["task"]["model"]["kwargs"]["num_threads"] = 2
            config_path = output / "qlib.yaml"
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            receipt["qlib_config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
            receipt["config_overrides"] = ["task-owned MLflow SQLite URI", "kernels=2", "num_threads=2"]
            built = stage("qlib_dataset", lambda: build_qlib_dataset(
                universe_path=REPO / "configs/universe/us_core_liquid.yaml",
                start_date="2020-01-01", end_date="2025-12-31", run_id=run_id,
                data_root=data, artifacts_root=qlib_root, dry_run=False,
            ))
            if built["status"] == "completed":
                trained = stage("qlib_training", lambda: run_qlib_workflow(config_path=config_path, run_id=run_id, artifacts_root=qlib_root, dry_run=False))
                if trained["status"] == "completed":
                    summary_path = qlib_root / run_id / "qlib_backtest_summary.json"
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    receipt["qlib_portfolio_analysis"] = summary
                    stage("qlib_metric_import", lambda: import_recorder_metrics(run_id=run_id, artifacts_root=qlib_root))
                    portfolio = yaml.safe_load((REPO / "configs/portfolio/pypfopt_long_only_max_sharpe.yaml").read_text(encoding="utf-8"))
                    portfolio["data_root"] = str(data)
                    portfolio_path = output / "portfolio.yaml"
                    portfolio_path.write_text(yaml.safe_dump(portfolio, sort_keys=False), encoding="utf-8")
                    stage("portfolio_risk_backtest", lambda: run_research_execution_pipeline(ResearchExecutionPipelineConfig(
                        qlib_run_id=run_id, qlib_config_path=config_path, portfolio_config_path=portfolio_path,
                        pipeline_run_id="historical_qa", qlib_runs_root=qlib_root,
                        portfolio_runs_root=output / "portfolio_runs", pipeline_runs_root=output / "pipeline_runs",
                        risk_max_order_notional_pct=0.25,
                    )))
    except Exception as exc:
        receipt["stages"]["setup"] = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    receipt["all_executed_stages_completed"] = all(value["status"] == "completed" for value in receipt["stages"].values())
    receipt["verification_complete"] = False  # Nested gates and artifacts require independent review.
    save()
    print(str(output / "receipt.json"), flush=True)
    return 0 if receipt["all_executed_stages_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
