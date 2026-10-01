from __future__ import annotations

import ast
import importlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "quant_cn"
FORBIDDEN_MODULE_ROOTS = {
    "aiohttp",
    "backend",
    "httpx",
    "integrations",
    "quant_crypto",
    "quant_us",
    "requests",
    "socket",
    "urllib",
}


def _quant_shared_import_is_allowed(path: Path) -> bool:
    relative_path = path.relative_to(PACKAGE_ROOT)
    return relative_path.parts[0] == "compat" or path.name == "shared_adapter.py"


def _is_boundary_violation(path: Path, module: str) -> bool:
    module_root = module.split(".", 1)[0].lower()
    if module_root == "quant_shared":
        return not _quant_shared_import_is_allowed(path)
    return module_root in FORBIDDEN_MODULE_ROOTS


def test_quant_cn_has_only_approved_shared_and_no_us_btc_backend_or_network_dependency() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            if _is_boundary_violation(path, module):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{module}")
    assert violations == []


def test_quant_shared_remains_forbidden_outside_approved_adapter_paths() -> None:
    assert _is_boundary_violation(
        PACKAGE_ROOT / "application" / "service.py",
        "quant_shared.core",
    )
    assert not _is_boundary_violation(
        PACKAGE_ROOT / "compat" / "shared_adapter.py",
        "quant_shared.core",
    )
    assert not _is_boundary_violation(
        PACKAGE_ROOT / "market" / "shared_adapter.py",
        "quant_shared.core",
    )


def test_namespace_package_imports_without_pyproject_change() -> None:
    modules = (
        "quant_cn.application.foundation_preflight",
        "quant_cn.data.contracts",
        "quant_cn.market.calendar",
        "quant_cn.market.eligibility",
        "quant_cn.market.rules",
    )
    assert [importlib.import_module(module).__name__ for module in modules] == list(modules)


def test_package_registration_is_completed_by_integrator() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"quant_cn*"' in pyproject
    request = (
        REPO_ROOT / "docs" / "cn_equity" / "shared_contract_change_request.md"
    ).read_text(encoding="utf-8")
    assert "quant_cn_package_registration_missing" in request
    assert "integrator" in request
