#!/usr/bin/env python3
"""Import a licensed local-CSV US equity production PIT bundle.

The script copies a provider drop into the gitignored production bundle area
only after the required CSV files and metadata are present. It does not create
or synthesize missing PIT evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_us_equity_local_csv_bundle_manifest import (  # noqa: E402
    DEFAULT_FILENAMES,
    build_local_csv_bundle_manifest,
    write_local_csv_bundle_manifest,
)
from quant_us.data.lineage.local_csv_provider import (  # noqa: E402
    CORPORATE_ACTION_EVENT_TYPES,
    DATE_FIELDS_BY_FILE,
    MEMBERSHIP_EVENT_TYPES,
    REQUIRED_LOCAL_CSV_FILES,
)


SCHEMA_VERSION = "us_equity_local_csv_production_bundle_import_report_v1"
DEFAULT_BUNDLE_ROOT = Path("data/external/us_equity_lineage/bundles")
DEFAULT_SOURCE_DIR = Path("data/external/us_equity_lineage/incoming/manual_vendor_drop")
DEFAULT_BUNDLE_ID = "manual_vendor_bundle_v1"
DEFAULT_SAMPLE_START = "2000-01-01"
DEFAULT_SAMPLE_END = "2026-06-24"
DEFAULT_LICENSE_NOTE = "manual licensed provider drop required"
DEFAULT_OUTPUT = Path("artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity Local CSV 生产数据包导入报告.md")


def import_us_equity_local_csv_production_bundle(
    *,
    repo_root: Path | None = None,
    source_dir: Path = DEFAULT_SOURCE_DIR,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    bundle_root: Path = DEFAULT_BUNDLE_ROOT,
    source_provider: str = "local_csv",
    source_type: str = "production",
    sample_start: str = DEFAULT_SAMPLE_START,
    sample_end: str = DEFAULT_SAMPLE_END,
    as_of_date: str = "",
    universe_name: str = "",
    price_data_reference: str = "",
    license_note: str = DEFAULT_LICENSE_NOTE,
    promotion_clean_allowed: bool = True,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    source = _resolve(root, source_dir)
    clean_bundle_id = _safe_bundle_id(bundle_id)
    target_root = _resolve(root, bundle_root)
    target = target_root / clean_bundle_id if clean_bundle_id else target_root / "__invalid_bundle_id__"
    blockers = _pre_copy_blockers(
        repo_root=root,
        source=source,
        target_root=target_root,
        target=target,
        bundle_id=clean_bundle_id,
        source_provider=source_provider,
        source_type=source_type,
        sample_start=sample_start,
        sample_end=sample_end,
        license_note=license_note,
        promotion_clean_allowed=promotion_clean_allowed,
    )
    copied_files: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    imported = False
    if not blockers:
        staging = target_root / f".{clean_bundle_id}.{uuid.uuid4().hex}.staging"
        try:
            staging.mkdir(parents=True, exist_ok=False)
            for key, filename in DEFAULT_FILENAMES.items():
                src = source / filename
                dst = staging / filename
                shutil.copy2(src, dst)
                copied_files.append({"table": key, "source": _relpath(src, root), "target": _relpath(dst, root)})
            manifest = build_local_csv_bundle_manifest(
                bundle_root=staging,
                bundle_id=clean_bundle_id,
                source_provider=source_provider,
                source_type=source_type,
                created_at=generated,
                as_of_date=as_of_date,
                sample_start=sample_start,
                sample_end=sample_end,
                universe_name=universe_name,
                price_data_reference=price_data_reference,
                license_note=license_note,
                promotion_clean_allowed=promotion_clean_allowed,
            )
            if manifest.get("blockers"):
                blockers.extend(f"manifest:{item}" for item in _list_of_str(manifest.get("blockers")))
            else:
                write_local_csv_bundle_manifest(manifest, staging / "provider_bundle_manifest.json")
                os.replace(staging, target)
                imported = True
                copied_files = [
                    {"table": key, "source": _relpath(source / filename, root), "target": _relpath(target / filename, root)}
                    for key, filename in DEFAULT_FILENAMES.items()
                ]
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    status = "production_bundle_imported" if imported else "production_bundle_import_blocked"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "bundle_id": clean_bundle_id or None,
        "source_dir": _relpath(source, root),
        "target_bundle_root": _relpath(target, root),
        "source_provider": source_provider,
        "source_type": source_type,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "as_of_date": as_of_date,
        "universe_name": universe_name,
        "price_data_reference": price_data_reference,
        "license_note_present": bool(license_note.strip()),
        "promotion_clean_allowed": bool(promotion_clean_allowed),
        "copied_files": copied_files if imported else [],
        "manifest_path": _relpath(target / "provider_bundle_manifest.json", root) if imported else None,
        "manifest_blockers": _list_of_str((manifest or {}).get("blockers")) if manifest else [],
        "blockers": _dedupe(blockers),
        "post_import_commands": _post_import_commands(clean_bundle_id),
        "guardrails": {
            "import_only": True,
            "missing_pit_evidence_synthesized": False,
            "source_vendor_data_modified": False,
            "configuration_mutated_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _pre_copy_blockers(
    *,
    repo_root: Path,
    source: Path,
    target_root: Path,
    target: Path,
    bundle_id: str,
    source_provider: str,
    source_type: str,
    sample_start: str,
    sample_end: str,
    license_note: str,
    promotion_clean_allowed: bool,
) -> list[str]:
    blockers: list[str] = []
    if not bundle_id:
        blockers.append("bundle_id_invalid_or_missing")
    if not source.exists():
        blockers.append("source_dir_missing")
    elif not source.is_dir():
        blockers.append("source_dir_not_directory")
    if source_provider not in {"local_csv", "crsp", "sharadar", "polygon", "norgate", "other"}:
        blockers.append("source_provider_invalid")
    if source_type != "production":
        blockers.append("source_type_must_be_production")
    if not sample_start:
        blockers.append("sample_start_missing")
    if not sample_end:
        blockers.append("sample_end_missing")
    if not license_note.strip():
        blockers.append("license_note_missing")
    if promotion_clean_allowed is not True:
        blockers.append("promotion_clean_allowed_must_be_true_for_import")
    if target.exists():
        blockers.append("target_bundle_already_exists")
    if not _gitignore_protection_confirmed(repo_root, target_root):
        blockers.append("target_bundle_gitignore_protection_missing")
    if source.exists() and source.is_dir():
        blockers.extend(_source_content_blockers(source))
        for key, filename in DEFAULT_FILENAMES.items():
            if key not in REQUIRED_LOCAL_CSV_FILES:
                continue
            path = source / filename
            if not path.exists():
                blockers.append(f"source_{key}_file_missing")
            elif path.stat().st_size == 0:
                blockers.append(f"source_{key}_file_empty")
    return _dedupe(blockers)


def _source_content_blockers(source: Path) -> list[str]:
    blockers: list[str] = []
    source_record_ids: set[str] = set()
    for key, fields in REQUIRED_LOCAL_CSV_FILES.items():
        path = source / DEFAULT_FILENAMES[key]
        if not path.exists() or path.stat().st_size == 0:
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                rows = [dict(row) for row in reader]
        except UnicodeDecodeError:
            blockers.append(f"source_{key}_file_not_utf8")
            continue
        except csv.Error:
            blockers.append(f"source_{key}_csv_parse_error")
            continue
        missing = [field for field in fields if field not in headers]
        blockers.extend(f"source_{key}_{field}_missing" for field in missing)
        if missing:
            continue
        blockers.extend(_row_blockers(key, rows, source_record_ids))
    return _dedupe(blockers)


def _row_blockers(table: str, rows: list[dict[str, str]], source_record_ids: set[str]) -> list[str]:
    blockers: list[str] = []
    date_fields = set(DATE_FIELDS_BY_FILE.get(table, []))
    for row in rows:
        source_record_id = str(row.get("source_record_id", "") or "").strip()
        if not source_record_id:
            blockers.append(f"source_{table}_source_record_id_missing")
        elif source_record_id in source_record_ids:
            blockers.append("source_record_id_duplicate")
        else:
            source_record_ids.add(source_record_id)
        for field in date_fields:
            value = str(row.get(field, "") or "").strip()
            if value and not _is_iso_date(value):
                blockers.append(f"source_{table}_{field}_invalid_date")
        if table == "universe_membership_events":
            event_type = str(row.get("event_type", "") or "").strip()
            if event_type not in MEMBERSHIP_EVENT_TYPES:
                blockers.append("source_universe_membership_events_event_type_invalid")
        if table == "corporate_actions":
            event_type = str(row.get("event_type", "") or "").strip()
            if event_type not in CORPORATE_ACTION_EVENT_TYPES:
                blockers.append("source_corporate_actions_event_type_invalid")
        if table == "macro_release_calendar":
            available_time = str(row.get("available_time_utc", "") or "").strip()
            if not available_time:
                blockers.append("source_macro_release_calendar_available_time_utc_missing")
            elif not _is_iso_utc_datetime(available_time):
                blockers.append("source_macro_release_calendar_available_time_utc_invalid")
    return _dedupe(blockers)


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
        return len(value) >= 10
    except ValueError:
        return False


def _is_iso_utc_datetime(value: str) -> bool:
    if not value.endswith("Z") or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _gitignore_protection_confirmed(repo_root: Path, bundle_root: Path) -> bool:
    probe = bundle_root / "__probe__" / "vendor.csv"
    try:
        probe_ref = probe.resolve().relative_to(repo_root.resolve()).as_posix()
        completed = subprocess.run(
            ["git", "check-ignore", "--quiet", probe_ref],
            cwd=repo_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return True
    except Exception:
        pass
    gitignore = repo_root / ".gitignore"
    if not gitignore.exists():
        return False
    text = gitignore.read_text(encoding="utf-8")
    return "data/external/us_equity_lineage/bundles/*" in text or "bundles/*" in text


def _post_import_commands(bundle_id: str) -> list[str]:
    selected = bundle_id or "<bundle_id>"
    return [
        f"python scripts/build_us_equity_production_bundle_activation_report.py --bundle-id {selected} --license-reviewed",
        "python scripts/build_us_equity_production_bundle_preflight_report.py --strict",
        "python scripts/build_us_equity_provider_verification_report.py",
        "python scripts/build_us_equity_data_status_report.py",
        "python scripts/run_us_equity_daily_production_line.py",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity Local CSV 生产数据包导入报告",
        "",
        f"生成时间：`{payload.get('generated_at')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- Bundle：`{payload.get('bundle_id')}`",
        f"- source：`{payload.get('source_dir')}`",
        f"- target：`{payload.get('target_bundle_root')}`",
        f"- manifest：`{payload.get('manifest_path')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = [str(item) for item in payload.get("blockers", [])]
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- `{key}` = `{value}`" for key, value in dict(payload.get("guardrails", {})).items())
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


def _safe_bundle_id(value: str) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_.-]+", text) else ""


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a licensed US equity local CSV production bundle.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR))
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    parser.add_argument("--source-provider", default="local_csv")
    parser.add_argument("--source-type", default="production")
    parser.add_argument("--sample-start", default=DEFAULT_SAMPLE_START)
    parser.add_argument("--sample-end", default=DEFAULT_SAMPLE_END)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--universe-name", default="")
    parser.add_argument("--price-data-reference", default="")
    parser.add_argument("--license-note", default=DEFAULT_LICENSE_NOTE)
    parser.add_argument("--promotion-clean-allowed", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = import_us_equity_local_csv_production_bundle(
        repo_root=Path(args.repo_root),
        source_dir=Path(args.source_dir),
        bundle_id=args.bundle_id,
        bundle_root=Path(args.bundle_root),
        source_provider=args.source_provider,
        source_type=args.source_type,
        sample_start=args.sample_start,
        sample_end=args.sample_end,
        as_of_date=args.as_of_date,
        universe_name=args.universe_name,
        price_data_reference=args.price_data_reference,
        license_note=args.license_note,
        promotion_clean_allowed=bool(args.promotion_clean_allowed),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
