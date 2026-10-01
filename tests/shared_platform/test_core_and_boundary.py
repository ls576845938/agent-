from __future__ import annotations

import ast
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_shared import SHARED_PLATFORM_V3_VERSION, SHARED_PLATFORM_VERSION
from quant_shared.core import (
    canonical_json_dumps,
    canonical_payload_hash,
    derive_identity,
    ensure_utc,
    isoformat_utc,
)


FORBIDDEN_IMPORT_ROOTS = {
    "backend",
    "frontend",
    "quant_crypto",
    "quant_cn",
    "quant_us",
    "ccxt",
    "ib_insync",
    "okx",
    "qmt",
    "akshare",
    "baostock",
    "tushare",
    "yfinance",
    "alpaca",
    "vnpy",
}
ASSET_TOKENS = {
    "assetclass",
    "btc",
    "crypto",
    "equity",
    "funding",
    "future",
    "liquidation",
    "perpetual",
    "spot",
    "venue",
}
CAPABILITY_TOKENS = {"broker", "cancel", "live", "order", "paper", "submit"}


def _python_files() -> list[Path]:
    return sorted(Path("quant_shared").rglob("*.py"))


def _import_roots(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_shared_platform_version_and_packages_are_discoverable() -> None:
    assert SHARED_PLATFORM_VERSION == "shared_platform_v2"
    assert SHARED_PLATFORM_V3_VERSION == "shared_platform_v3"
    for package in (
        "quant_shared.core",
        "quant_shared.evidence",
        "quant_shared.ledger",
        "quant_shared.replay",
        "quant_shared.backtest",
        "quant_shared.read_model",
        "quant_shared.forecasting",
        "quant_shared.runtime.contracts",
    ):
        assert importlib.import_module(package)


def test_v3_is_additive_and_exposes_capabilities_without_replacing_v2() -> None:
    from quant_shared import discover_shared_platform

    discovered = discover_shared_platform()
    assert discovered["versions"] == {
        "v2": "shared_platform_v2",
        "v3": "shared_platform_v3",
    }
    assert discovered["v3_capabilities"] == (
        "runtime_state",
        "action_authorization",
        "audit_event",
        "read_model_envelope",
    )


def test_utc_identity_serialization_and_hash_are_stable() -> None:
    shifted = datetime(2026, 7, 23, 16, tzinfo=timezone(timedelta(hours=8)))
    utc = datetime(2026, 7, 23, 8, tzinfo=timezone.utc)
    assert ensure_utc(shifted) == utc
    assert isoformat_utc(shifted) == "2026-07-23T08:00:00Z"
    left = {"at": shifted, "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "at": utc}
    assert canonical_json_dumps(left) == canonical_json_dumps(right)
    assert canonical_payload_hash(left) == canonical_payload_hash(right)
    identity = derive_identity("run", left)
    assert identity.qualified == f"run:{canonical_payload_hash(left)}"


def test_quant_shared_has_no_reverse_domain_or_sdk_imports() -> None:
    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _import_roots(tree):
            if module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                violations.append(f"{path}:{module}")
    assert violations == []


def test_cn_reverse_import_is_explicitly_caught_by_the_boundary_guard() -> None:
    assert "quant_cn" in FORBIDDEN_IMPORT_ROOTS
    synthetic = ast.parse("from quant_cn.compat import shared_adapter")
    modules = _import_roots(synthetic)
    assert [module for module in modules if module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS] == [
        "quant_cn.compat"
    ]


def test_asset_specific_enum_and_state_count_is_zero() -> None:
    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {
                base.id.lower()
                for base in node.bases
                if isinstance(base, ast.Name)
            }
            is_enum_or_state = "enum" in base_names or node.name.lower().endswith("state")
            if not is_enum_or_state:
                continue
            names = [node.name.lower()]
            names.extend(
                child.targets[0].id.lower()
                for child in node.body
                if isinstance(child, ast.Assign)
                and child.targets
                and isinstance(child.targets[0], ast.Name)
            )
            matched = sorted(token for token in ASSET_TOKENS if any(token in name for name in names))
            if matched:
                violations.append(f"{path}:{node.lineno}:{node.name}:{','.join(matched)}")
    assert violations == []


def test_shared_kernel_exposes_no_trading_capability() -> None:
    violations: list[str] = []
    roots = [
        Path("quant_shared/core"),
        Path("quant_shared/evidence"),
        Path("quant_shared/ledger"),
        Path("quant_shared/replay"),
        Path("quant_shared/backtest"),
        Path("quant_shared/read_model"),
    ]
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    lowered = node.name.lower()
                    matched = sorted(token for token in CAPABILITY_TOKENS if token in lowered)
                    if matched:
                        violations.append(f"{path}:{node.lineno}:{node.name}:{','.join(matched)}")
    assert violations == []
