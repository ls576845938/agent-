from __future__ import annotations

import ast
import json
from pathlib import Path


def test_api_integration_routes_do_not_expose_implicit_data_download_or_order_submit() -> None:
    path = Path("backend/app/api/app_factory.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_import_names = {
        "prepare_real_daily_data",
        "PaperRuntime",
        "LiveRuntime",
        "OrderManagementSystem",
    }
    forbidden_route_fragments = {
        "/integrations/qlib/prepare-real-daily-data",
        "/integrations/qlib/sync-yfinance",
        "/integrations/portfolio/submit",
        "/integrations/portfolio/orders",
    }

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in forbidden_import_names:
                    violations.append(f"{path}: imports {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_import_names:
                    violations.append(f"{path}: imports {alias.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in forbidden_route_fragments:
                violations.append(f"{path}: exposes route {node.value}")

    assert violations == []


def test_api_qlib_run_summary_does_not_treat_artifact_as_paper_or_live_ready(tmp_path: Path) -> None:
    from backend.app.api.app_factory import _run_directory_summaries
    qlib_run = tmp_path / "artifacts" / "qlib_runs" / "qlib_poisoned_ready"
    (qlib_run / "qlib_input").mkdir(parents=True)
    (qlib_run / "qlib_input" / "dataset_manifest.json").write_text(
        json.dumps({"status": "completed", "symbols_exported": ["AAPL"]}),
        encoding="utf-8",
    )
    (qlib_run / "workflow_run_result.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )
    (qlib_run / "qlib_strategy_manifest.json").write_text(
        json.dumps(
            {
                "source": "qlib",
                "status": "completed",
                "promotion_status": "paper_ready",
                "live_ready": True,
                "strategy_id": "qlib_direct_ready_should_not_escape",
            }
        ),
        encoding="utf-8",
    )

    summaries = _run_directory_summaries(str(tmp_path / "artifacts" / "qlib_runs"), "qlib")
    assert summaries
    latest = summaries[0]
    forbidden_ready_states = {"paper_ready", "live_ready", "ready_for_paper", "ready_for_live"}
    assert str(latest.get("promotion_status", "")).lower() not in forbidden_ready_states
    assert "live_ready" not in json.dumps(latest).lower()
