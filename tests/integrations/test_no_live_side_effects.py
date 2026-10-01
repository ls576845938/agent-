from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_integrations_do_not_import_live_execution_or_broker_paths() -> None:
    integrations_root = Path("integrations")
    if not integrations_root.exists():
        pytest.xfail("pending adapter implementation: integrations/")

    banned_import_prefixes = (
        "quant_us.live",
        "quant_us.execution",
        "alpaca",
        "ib_insync",
    )
    banned_import_names = {
        "OrderManagementSystem",
        "PaperBroker",
        "BrokerBase",
        "AlpacaBroker",
        "AlpacaPaperBrokerAdapter",
    }
    banned_method_calls = {
        "submit_order",
        "handle_intent",
        "route_order",
        "cancel_order",
        "replace_order",
        "close_position",
        "close_all_positions",
    }

    violations: list[str] = []
    for path in sorted(integrations_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(banned_import_prefixes):
                        violations.append(f"{path}: imports {alias.name}")
                    if alias.name in banned_import_names:
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
                elif isinstance(func, ast.Attribute) and func.attr in banned_method_calls:
                    violations.append(f"{path}: calls .{func.attr}()")

    assert violations == []
def test_import_target_weights_module_has_no_submit_order_calls() -> None:
    module_path = Path("integrations/pypfopt_adapter/import_target_weights.py")
    if not module_path.exists():
        pytest.xfail("pending adapter implementation: integrations/pypfopt_adapter/import_target_weights.py")

    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    forbidden_calls = {"submit_order", "handle_intent", "route_order"}
    violations = [
        f"{module_path}: calls .{node.func.attr}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_calls
    ]
    assert violations == []


def test_qlib_adapter_sources_never_emit_paper_or_live_ready_states() -> None:
    qlib_root = Path("integrations/qlib_adapter")
    if not qlib_root.exists():
        pytest.xfail("pending adapter implementation: integrations/qlib_adapter")

    forbidden_values = {
        "paper_ready",
        "live_ready",
        "ready_for_paper",
        "ready_for_live",
        "paper_eligible",
        "live_eligible",
    }
    violations: list[str] = []
    for path in sorted(qlib_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                normalized = node.value.strip().lower()
                if normalized in forbidden_values:
                    violations.append(f"{path}: emits forbidden readiness state {node.value!r}")

    assert violations == []


def test_pypfopt_adapter_sources_never_emit_order_shaped_artifacts() -> None:
    pypfopt_root = Path("integrations/pypfopt_adapter")
    if not pypfopt_root.exists():
        pytest.xfail("pending adapter implementation: integrations/pypfopt_adapter")

    forbidden_imports = {
        "Order",
        "OrderIntent",
        "OrderManagementSystem",
        "PreTradeRiskEngine",
    }
    forbidden_calls = {
        "submit_order",
        "handle_intent",
        "route_order",
        "cancel_order",
        "replace_order",
    }
    forbidden_artifact_fields = {
        "broker_order_id",
        "client_order_id",
        "order_id",
        "order_type",
        "risk_check_id",
        "side",
    }

    violations: list[str] = []
    for path in sorted(pypfopt_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith(("quant_us.live", "quant_us.execution")):
                    violations.append(f"{path}: imports from {module}")
                if module == "quant_us.core.types":
                    for alias in node.names:
                        if alias.name in forbidden_imports:
                            violations.append(f"{path}: imports {alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("quant_us.live", "quant_us.execution")):
                        violations.append(f"{path}: imports {alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_calls:
                    violations.append(f"{path}: calls .{func.attr}()")
                elif isinstance(func, ast.Name) and func.id in forbidden_imports:
                    violations.append(f"{path}: constructs {func.id}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.strip().lower() in forbidden_artifact_fields:
                    violations.append(f"{path}: emits order-shaped field {node.value!r}")

    assert violations == []
