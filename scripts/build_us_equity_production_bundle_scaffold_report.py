#!/usr/bin/env python3
"""Build a US equity production lineage bundle scaffold.

The scaffold writes templates only. It never writes vendor data and never
grants promotion-clean status.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES  # noqa: E402
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES  # noqa: E402


SCHEMA_VERSION = "us_equity_production_bundle_scaffold_report_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_scaffold_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 生产数据包接入模板.md")
DEFAULT_SCAFFOLD_ROOT = Path("artifacts/us_equity_data_lineage/latest/production_bundle_scaffold")
DEFAULT_BUNDLE_ID = "us_equity_production_bundle_TEMPLATE"


def build_us_equity_production_bundle_scaffold_report(
    *,
    repo_root: Path | None = None,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    scaffold_root: Path = DEFAULT_SCAFFOLD_ROOT,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    scaffold_dir = _resolve(root, scaffold_root) / bundle_id
    scaffold_dir.mkdir(parents=True, exist_ok=True)

    csv_templates = _write_csv_templates(scaffold_dir)
    manifest_template = _manifest_template(bundle_id=bundle_id, generated_at=generated)
    manifest_path = scaffold_dir / "provider_bundle_manifest.template.json"
    _write_json(manifest_path, manifest_template)
    config_patch_path = scaffold_dir / "us_equity_provider_sources.patch.yaml"
    _write_text(config_patch_path, _config_patch(bundle_id))
    readme_path = scaffold_dir / "README.md"
    _write_text(readme_path, _readme(bundle_id))

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "template_ready_not_provider_evidence",
        "asset": "us_equity",
        "bundle_id": bundle_id,
        "scaffold_dir": _relpath(scaffold_dir, root),
        "required_tables": _required_table_rows(csv_templates, root),
        "manifest_template": _relpath(manifest_path, root),
        "provider_config_patch": _relpath(config_patch_path, root),
        "readme": _relpath(readme_path, root),
        "activation_steps": [
            "Copy this scaffold to data/external/us_equity_lineage/bundles/<real_bundle_id>.",
            "Replace template CSVs with licensed provider data using the exact headers.",
            "Run scripts/build_us_equity_local_csv_bundle_manifest.py against the real bundle root to compute sha256 and record_count.",
            "Enable providers.local_csv and set selected_bundle_id in configs/data/us_equity_provider_sources.yaml.",
            "Run production bundle preflight, provider verification, data status, strategy validation, and production line reports.",
        ],
        "guardrails": {
            "template_contains_vendor_data": False,
            "template_is_not_provider_evidence": True,
            "promotion_clean_granted_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _write_csv_templates(scaffold_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        path = scaffold_dir / DEFAULT_FILENAMES[table]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
        paths[table] = path
    return paths


def _manifest_template(*, bundle_id: str, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": "us_equity_local_csv_provider_bundle_manifest_v1",
        "generated_at": generated_at,
        "bundle_id": bundle_id,
        "source_provider": "other",
        "source_type": "production",
        "created_at": generated_at,
        "as_of_date": "YYYY-MM-DD",
        "sample_start": "YYYY-MM-DD",
        "sample_end": "YYYY-MM-DD",
        "universe_name": "us_equity_production_universe",
        "price_data_reference": "data/external/us_equity_eod/tiingo or provider price bundle id",
        "license_note": "REPLACE_WITH_PROVIDER_LICENSE_SCOPE_AND_STORAGE_RULES",
        "promotion_clean_allowed": False,
        "files": {
            table: {
                "path": DEFAULT_FILENAMES[table],
                "sha256": "RUN_MANIFEST_BUILDER_TO_FILL",
                "record_count": 0,
            }
            for table in REQUIRED_LOCAL_CSV_FILES
        },
        "blockers": [
            "template_only_not_provider_evidence",
            "replace_template_files_with_licensed_provider_data",
            "run_manifest_builder_to_compute_sha256_and_record_count",
            "promotion_clean_allowed_must_be_reviewed_manually",
        ],
    }


def _config_patch(bundle_id: str) -> str:
    return "\n".join(
        [
            "providers:",
            "  local_csv:",
            "    enabled: true",
            "    root: data/external/us_equity_lineage/",
            f"    selected_bundle_id: {bundle_id}",
            "    require_explicit_bundle_selection: true",
            "    allow_sample_for_research: false",
            "    allow_fixture_for_tests_only: false",
            "    bundle_manifest: null",
            "    files: {}",
            "    promotion_clean_allowed: false  # set true only after manual license and evidence review",
            "",
        ]
    )


def _readme(bundle_id: str) -> str:
    tables = "\n".join(f"- `{table}` -> `{DEFAULT_FILENAMES[table]}`" for table in REQUIRED_LOCAL_CSV_FILES)
    return f"""# US Equity Production Bundle Scaffold

Bundle id: `{bundle_id}`

This folder is a template only. It contains CSV headers, a manifest template,
and a config patch. It does not contain provider data and cannot unlock
promotion, paper simulation, or live trading.

## Required Tables

{tables}

## Activation

1. Copy this folder to `data/external/us_equity_lineage/bundles/<real_bundle_id>`.
2. Replace every CSV template with licensed provider data.
3. Run `python scripts/build_us_equity_local_csv_bundle_manifest.py --bundle-root data/external/us_equity_lineage/bundles/<real_bundle_id> --bundle-id <real_bundle_id> --source-provider <provider> --source-type production --sample-start YYYY-MM-DD --sample-end YYYY-MM-DD --license-note "..."`
4. Set `providers.local_csv.enabled=true` and `selected_bundle_id=<real_bundle_id>`.
5. Rebuild preflight, provider verification, data status, strategy validation, and production line reports.
"""


def _required_table_rows(paths: Mapping[str, Path], root: Path) -> list[dict[str, Any]]:
    rows = []
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        rows.append(
            {
                "table": table,
                "filename": DEFAULT_FILENAMES[table],
                "template_path": _relpath(paths[table], root),
                "required_fields": list(fields),
            }
        )
    return rows


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产数据包接入模板",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 模板目录：`{payload.get('scaffold_dir', '')}`",
        f"- Manifest 模板：`{payload.get('manifest_template', '')}`",
        f"- 配置补丁：`{payload.get('provider_config_patch', '')}`",
        "",
        "## 必需表",
        "",
        "| table | filename | required fields |",
        "| --- | --- | --- |",
    ]
    for row in _list(payload.get("required_tables")):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| `{row.get('table')}` | `{row.get('filename')}` | {', '.join(f'`{field}`' for field in _list_of_str(row.get('required_fields')))} |"
        )
    lines.extend(["", "## 启用步骤", ""])
    lines.extend(f"- {item}" for item in _list_of_str(payload.get("activation_steps")))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 该模板不包含供应商数据。",
            "- 该模板不是 provider evidence。",
            "- 该模板不能解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 生产数据包接入模板",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 模板目录：`{payload.get('scaffold_dir', '')}`",
        f"- Manifest 模板：`{payload.get('manifest_template', '')}`",
        f"- 配置补丁：`{payload.get('provider_config_patch', '')}`",
        "",
        "## 必需表",
        "",
        "| table | filename | required fields |",
        "| --- | --- | --- |",
    ]
    for row in _list(payload.get("required_tables")):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| `{row.get('table')}` | `{row.get('filename')}` | {', '.join(f'`{field}`' for field in _list_of_str(row.get('required_fields')))} |"
        )
    lines.extend(["", "## 启用步骤", ""])
    lines.extend(f"- {item}" for item in _list_of_str(payload.get("activation_steps")))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 该模板不包含供应商数据。",
            "- 该模板不是 provider evidence。",
            "- 该模板不能解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity production bundle scaffold report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--scaffold-root", default=str(DEFAULT_SCAFFOLD_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_production_bundle_scaffold_report(
        repo_root=Path(args.repo_root),
        bundle_id=args.bundle_id,
        scaffold_root=Path(args.scaffold_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
