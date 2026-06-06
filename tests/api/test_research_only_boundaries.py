from __future__ import annotations

import ast
import json
import re
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


def test_api_exposes_global_registry_as_read_only_research_summary() -> None:
    path = Path("backend/app/api/app_factory.py")
    source = path.read_text(encoding="utf-8")

    assert '@router.get("/research/global-registry")' in source
    assert "build_global_registry" in source
    assert "write_registry" not in source
    assert "write: bool" not in source
    assert "repo_root: str" not in source
    assert "repo_root=settings.repo_root" in source
    assert "/research/global-registry" not in {
        "/api/live",
        "/api/orders",
        "/api/trade",
    }


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


def test_research_and_integration_modules_do_not_import_or_call_order_submission_surfaces() -> None:
    banned_import_names = {
        "AlpacaBroker",
        "AlpacaPaperBrokerAdapter",
        "IBKRBroker",
        "LiveRuntime",
        "OrderManagementSystem",
        "PaperBroker",
        "PaperRuntime",
        "ReadOnlyLiveBrokerProxy",
    }
    banned_import_prefixes = (
        "quant_us.execution",
        "quant_us.live",
        "alpaca",
        "ib_insync",
    )
    banned_call_attrs = {
        "cancel_order",
        "close_all_positions",
        "close_position",
        "replace_order",
        "submit_order",
    }
    scanned_roots = [Path("quant_us/research"), Path("integrations")]
    violations: list[str] = []

    for root in scanned_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(banned_import_prefixes) or alias.name in banned_import_names:
                            violations.append(f"{path}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.startswith(banned_import_prefixes):
                        violations.append(f"{path}: imports from {module}")
                    for alias in node.names:
                        if alias.name in banned_import_names:
                            violations.append(f"{path}: imports {alias.name}")
                elif isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id in banned_import_names:
                        violations.append(f"{path}: constructs {func.id}")
                    elif isinstance(func, ast.Attribute) and func.attr in banned_call_attrs:
                        violations.append(f"{path}: calls .{func.attr}()")

    assert violations == []


def test_frontend_research_actions_do_not_target_paper_live_or_order_submit_api_paths() -> None:
    forbidden_fragments = {
        "/api/live",
        "/api/integrations/portfolio/submit",
        "/api/integrations/portfolio/orders",
        "/api/orders",
        "/api/trade",
    }
    forbidden_terms_in_paths = {"submit-order", "submit_order", "execute-live", "confirm-live"}
    api_path_pattern = re.compile(r"""api(?:Get|Post|PostRaw)<[^>]*>\(\s*['"`]([^'"`]+)['"`]|api(?:Get|Post|PostRaw)\(\s*['"`]([^'"`]+)['"`]""")
    violations: list[str] = []

    for path in sorted(Path("frontend/src").rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        api_paths = [
            group
            for match in api_path_pattern.findall(source)
            for group in match
            if group
        ]
        for api_path in api_paths:
            for fragment in forbidden_fragments:
                if fragment in api_path:
                    violations.append(f"{path}: calls {api_path}")
            for term in forbidden_terms_in_paths:
                if term in api_path:
                    violations.append(f"{path}: calls {api_path}")

    assert violations == []


def test_backend_research_task_endpoints_do_not_spawn_live_or_paper_submit_background_work() -> None:
    path = Path("backend/app/api/app_factory.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    task_endpoint_names = {
        "run_research_auto_cycle",
        "materialize_candidate_evidence",
        "save_candidate_evidence_pack",
        "rebuild_research_evidence_registry",
        "mine_research_factors",
        "mine_and_run_research_factors",
        "run_research_execution_pipeline_endpoint",
        "run_qlib_integration_workflow",
        "build_portfolio_expected_returns_endpoint",
        "build_portfolio_covariance_endpoint",
        "optimize_portfolio_weights_endpoint",
        "import_portfolio_target_weights_endpoint",
    }
    banned_names = {
        "BackgroundTasks",
        "PaperRuntime",
        "LiveRuntime",
        "OrderManagementSystem",
        "AlpacaBroker",
        "AlpacaPaperBrokerAdapter",
        "PaperBroker",
    }
    banned_call_attrs = {
        "add_task",
        "submit_order",
        "submit_orders",
        "route_order",
        "handle_intent",
        "cancel_order",
        "replace_order",
    }

    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations: list[str] = []
    missing = sorted(task_endpoint_names - set(functions))
    for name in missing:
        violations.append(f"{path}: expected task endpoint {name} not found")
    for name in sorted(task_endpoint_names & set(functions)):
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.arg) and node.annotation is not None:
                annotation = ast.unparse(node.annotation)
                if annotation in banned_names:
                    violations.append(f"{path}:{name}: accepts {annotation}")
            elif isinstance(node, ast.Name) and node.id in banned_names:
                violations.append(f"{path}:{name}: references {node.id}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in banned_names:
                    violations.append(f"{path}:{name}: constructs {func.id}")
                elif isinstance(func, ast.Attribute) and func.attr in banned_call_attrs:
                    violations.append(f"{path}:{name}: calls .{func.attr}()")

    assert violations == []


def test_portfolio_integration_summary_ignores_poisoned_live_or_order_ready_artifacts(tmp_path: Path) -> None:
    from backend.app.api.app_factory import _run_directory_summaries

    run_root = tmp_path / "artifacts" / "portfolio_runs" / "pf_poisoned_ready"
    run_root.mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "live_ready",
                "live_ready": True,
                "order_generation": "enabled",
                "submit_orders": True,
                "config": {"optimizer": "max_sharpe"},
            }
        ),
        encoding="utf-8",
    )
    (run_root / "target_positions.json").write_text(
        json.dumps(
            [
                {
                    "symbol": "AAPL",
                    "target_weight": 0.50,
                    "metadata": {"paper_ready": True, "live_ready": True},
                }
            ]
        ),
        encoding="utf-8",
    )

    summaries = _run_directory_summaries(str(tmp_path / "artifacts" / "portfolio_runs"), "portfolio")

    assert summaries
    latest = summaries[0]
    serialized = json.dumps(latest).lower()
    forbidden_ready_states = {"paper_ready", "live_ready", "ready_for_paper", "ready_for_live"}
    assert str(latest.get("status", "")).lower() not in forbidden_ready_states
    assert "live_ready" not in serialized
    assert "submit_orders" not in serialized
    assert "order_generation" not in serialized
    assert "paper_ready" not in serialized


def test_integration_run_summaries_fail_closed_on_unreadable_manifests(tmp_path: Path) -> None:
    from backend.app.api.app_factory import _run_directory_summaries

    qlib_run = tmp_path / "artifacts" / "qlib_runs" / "qlib_bad_json"
    (qlib_run / "qlib_input").mkdir(parents=True)
    (qlib_run / "qlib_input" / "dataset_manifest.json").write_text("{not-json", encoding="utf-8")
    (qlib_run / "workflow_run_result.json").write_text("{not-json", encoding="utf-8")
    (qlib_run / "qlib_strategy_manifest.json").write_text(
        json.dumps({"promotion_status": "live_ready", "live_ready": True}),
        encoding="utf-8",
    )

    portfolio_run = tmp_path / "artifacts" / "portfolio_runs" / "pf_bad_json"
    portfolio_run.mkdir(parents=True)
    (portfolio_run / "run_manifest.json").write_text("{not-json", encoding="utf-8")

    qlib_summary = _run_directory_summaries(str(tmp_path / "artifacts" / "qlib_runs"), "qlib")[0]
    portfolio_summary = _run_directory_summaries(str(tmp_path / "artifacts" / "portfolio_runs"), "portfolio")[0]

    assert qlib_summary["dataset_status"] == "missing"
    assert qlib_summary["workflow_status"] == "missing"
    assert qlib_summary["promotion_status"] == "candidate"
    assert portfolio_summary["status"] == "missing"
    serialized = json.dumps([qlib_summary, portfolio_summary]).lower()
    assert "live_ready" not in serialized
    assert "paper_ready" not in serialized
