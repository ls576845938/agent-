"""JSON-file persistence for audit results."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

DEFAULT_DATA_DIR = Path("data") / "research_audit"


def ensure_data_dir(data_dir: Union[str, Path]) -> Path:
    """Create the data directory if it does not exist, return resolved path."""
    p = Path(data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_audit_result(
    result_dict: Dict[str, Any],
    data_dir: Union[str, Path, None] = None,
) -> Path:
    """Save an audit result dict as JSON under ``data_dir / {audit_id}.json``.

    Returns the path of the written file.
    """
    data_path = ensure_data_dir(data_dir or DEFAULT_DATA_DIR)
    audit_id = result_dict.get("audit_id", "")
    if not audit_id:
        raise ValueError("result_dict must contain a non-empty 'audit_id'")
    file_path = data_path / f"{audit_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, ensure_ascii=False, indent=2)
    return file_path


def load_audit_result(
    audit_id: str,
    data_dir: Union[str, Path, None] = None,
) -> Optional[Dict[str, Any]]:
    """Load an audit result by ID.  Returns ``None`` when the file is missing."""
    data_path = Path(data_dir or DEFAULT_DATA_DIR)
    file_path = data_path / f"{audit_id}.json"
    if not file_path.exists():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_audit_results_by_target(
    target_type: str,
    target_id: str,
    data_dir: Union[str, Path, None] = None,
) -> List[Dict[str, Any]]:
    """Find all audit results matching *target_type* and *target_id*.

    Scans the data directory for JSON files.  Malformed files are silently
    skipped.
    """
    data_path = Path(data_dir or DEFAULT_DATA_DIR)
    if not data_path.exists():
        return []

    results: List[Dict[str, Any]] = []
    for fpath in data_path.iterdir():
        if fpath.suffix != ".json":
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("target_type") == target_type and data.get("target_id") == target_id:
            results.append(data)
    return results
