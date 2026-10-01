from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/governance/us_application_service_boundary_v1.json"
SCHEMA = ROOT / "schemas/us_application_service_boundary.schema.json"


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
    jsonschema.validate(
        config,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    application_root = ROOT / "quant_us/application"
    forbidden_modules = (
        "backend",
        "fastapi",
        "flask",
        "requests",
        "httpx",
        "alpaca",
        "ib_insync",
        "quant_crypto",
        "quant_cn",
    )
    violations: list[str] = []
    for path in sorted(application_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        modules = _imports(path)
        if "os.environ" in source or "Path(" in source:
            violations.append(path.relative_to(ROOT).as_posix())
        if any(
            module.startswith(forbidden_modules)
            for module in modules
        ):
            violations.append(path.relative_to(ROOT).as_posix())
    if violations:
        raise ValueError(
            "application_layer_dependency_violation:"
            + ",".join(sorted(set(violations)))
        )
    if any(config["safety"].values()):
        raise ValueError("trading_safety_flag_must_remain_false")
    if config["integrator_wiring"]["app_factory_modified"]:
        raise ValueError("app_factory_must_remain_integrator_owned")
    return {
        "status": "valid",
        "schema_version": config["schema_version"],
        "legacy_builder_rows": len(config["legacy_builder_matrix"]),
        "application_dependency_violations": 0,
        "app_factory_modified": False,
        "safety_flags_all_false": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the US application-service boundary contract."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(validate(args.config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
