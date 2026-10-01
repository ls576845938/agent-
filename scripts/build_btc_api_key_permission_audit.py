from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_crypto.security.api_key_audit import (
    BTCAPIKeyPermissionRecord,
    build_btc_api_key_permission_audit,
    build_btc_api_key_permission_records_template,
    find_secret_like_record_fields,
)


DEFAULT_OUTPUT = Path("artifacts/btc_security/latest/btc_api_key_permission_audit.json")
DEFAULT_RECORDS = Path("configs/btc/security/api_key_permission_records.redacted.json")


def build_btc_api_key_permission_audit_file(
    *,
    output: Path = DEFAULT_OUTPUT,
    records_path: Path | None = DEFAULT_RECORDS,
    generated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    records, preflight_blockers = _load_records(records_path) if records_path else ([], [])
    payload = build_btc_api_key_permission_audit(
        records=records,
        generated_at_utc=generated_at,
        preflight_blockers=preflight_blockers,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def write_btc_api_key_permission_records_template(path: Path) -> Path:
    payload = build_btc_api_key_permission_records_template()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _load_records(path: Path | None) -> tuple[list[BTCAPIKeyPermissionRecord], list[str]]:
    if path is None or not path.exists():
        return [], ["btc_api_key_permission_records_file_missing"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("records", [])
    records: list[BTCAPIKeyPermissionRecord] = []
    blockers: list[str] = []
    if not isinstance(rows, list):
        return [], ["btc_api_key_permission_records_not_list"]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            blockers.append(f"btc_api_key_permission_record_not_object:{index}")
            continue
        secret_fields = find_secret_like_record_fields(row)
        if secret_fields:
            blockers.append(f"btc_api_key_permission_record_contains_secret_like_field:{index}")
        try:
            records.append(BTCAPIKeyPermissionRecord(**row))
        except (TypeError, ValueError) as exc:
            blockers.append(f"btc_api_key_permission_record_invalid:{index}:{type(exc).__name__}")
    return records, blockers

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--write-template", type=Path, default=None)
    args = parser.parse_args()
    if args.write_template is not None:
        path = write_btc_api_key_permission_records_template(args.write_template)
        print(json.dumps({"template": str(path)}, ensure_ascii=False, indent=2))
        return 0
    payload = build_btc_api_key_permission_audit_file(output=args.output, records_path=args.records)
    print(json.dumps({"output": str(args.output), "status": payload["status"], "blockers": payload["blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
