from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/governance/us_shared_platform_adoption_v1.json"
SCHEMA = ROOT / "schemas/us_shared_platform_adoption.schema.json"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def validate(config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(config, schema)

    adapter = ROOT / "quant_us/compat/shared_platform.py"
    imports = _imports(adapter)
    if not any(module.startswith("quant_shared") for module in imports):
        raise ValueError("quant_us_shared_adapter_missing_shared_import")
    if any(
        module.startswith(("quant_crypto", "quant_cn", "backend", "frontend"))
        for module in imports
    ):
        raise ValueError("quant_us_shared_adapter_cross_domain_dependency")

    reverse_dependencies: list[str] = []
    for path in sorted((ROOT / "quant_shared").rglob("*.py")):
        if any(module.startswith("quant_us") for module in _imports(path)):
            reverse_dependencies.append(path.relative_to(ROOT).as_posix())
    if reverse_dependencies:
        raise ValueError(
            "quant_shared_reverse_dependency:" + ",".join(reverse_dependencies)
        )

    required_symbols = {
        "quant_us.core.clock.ensure_utc",
        "quant_us.core.types.Signal",
        "quant_us.core.types.TargetPosition",
        "quant_us.core.types.OrderIntent",
        "quant_us.core.enums.OrderSide",
        "quant_us.core.enums.OrderType",
        "quant_us.core.enums.TimeInForce",
    }
    matrix_symbols = {
        row["legacy_symbol"] for row in config["migration_matrix"]
    }
    if not required_symbols.issubset(matrix_symbols):
        raise ValueError("migration_matrix_required_symbols_missing")
    if any(config["safety"].values()):
        raise ValueError("trading_safety_flag_must_remain_false")

    return {
        "status": "valid",
        "schema_version": config["schema_version"],
        "adapter_module": config["adapter_module"],
        "migration_rows": len(config["migration_matrix"]),
        "quant_shared_reverse_dependencies": 0,
        "safety_flags_all_false": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the US-only shared-platform adoption contract."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(validate(args.config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
