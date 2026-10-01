from __future__ import annotations

import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "btc_dirty_worktree_boundary_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_dirty_worktree_boundary/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_dirty_worktree_boundary_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_dirty_worktree_boundary_files.csv"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "btc_dirty_worktree_boundary_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

GROUP_ORDER = (
    "runtime_replay",
    "security_attestation",
    "gate_root_cause",
    "frontend_control_center",
    "research_labs",
    "generated_artifacts_data",
    "other",
)

SECRET_FIELD_RE = re.compile(
    r"(^|[_.\-\s\"'])(api[_-]?key|api[_-]?secret|secret[_-]?key|secret|passphrase|password|access[_-]?token|refresh[_-]?token|private[_-]?key)($|[_.\-\s\"'])",
    re.IGNORECASE,
)
NON_SECRET_FIELD_TOKENS = (
    "allowed",
    "audit",
    "blocker",
    "boundary",
    "count",
    "endpoint",
    "field",
    "findings",
    "header",
    "inspected",
    "like",
    "output",
    "permission",
    "present",
    "private_endpoint",
    "redacted",
    "scan",
    "status",
    "used",
    "verified",
    "violation",
)
TEXT_SUFFIXES = {
    ".csv",
    ".env",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_SECRET_SCAN_BYTES = 2_000_000


def build_btc_dirty_worktree_boundary_report(
    *,
    repo_root: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str = "",
    status_lines: Sequence[str] | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output = _resolve(root, output_dir)
    output.mkdir(parents=True, exist_ok=True)
    lines = list(status_lines) if status_lines is not None else _git_status_lines(root)
    rows = [_row_from_status_line(line) for line in lines if line.strip()]
    rows = [row for row in rows if row]
    for row in rows:
        path = str(row.get("path") or "")
        row["review_group"] = _classify_path(path)
        row["file_kind"] = _file_kind(path)
        row["commit_boundary"] = _commit_boundary(path)
        row["commit_policy"] = _commit_policy(path)
        row["secret_scan"] = _secret_scan_for_path(root, path)
        row["secret_like_field_count"] = row["secret_scan"]["secret_like_field_count"]
        row["secret_like_unredacted_count"] = row["secret_scan"]["secret_like_unredacted_count"]
    groups = _group_summary(rows)
    secret_scan = _secret_scan_summary(rows)
    report_path = output / DEFAULT_REPORT_PATH.name
    csv_path = output / DEFAULT_CSV_PATH.name
    summary_path = output / DEFAULT_SUMMARY_PATH.name
    safety_path = output / DEFAULT_SAFETY_PATH.name
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "aggregation_batch_id": aggregation_batch_id,
        "status": "dirty_worktree_present" if rows else "clean_worktree",
        "decision": (
            "btc_dirty_worktree_secret_boundary_violation_review_required"
            if secret_scan["unredacted_secret_like_count"]
            else "btc_dirty_worktree_grouped_for_review_no_file_revert_no_commit"
        ),
        "scope": "read_only_git_status_grouping_no_artifact_promotion",
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "dirty_state_summary": _dirty_state_summary_from_rows(rows),
        "file_count": len(rows),
        "group_count": len(groups),
        "groups": groups,
        "files": rows,
        "secret_scan": secret_scan,
        "boundary_counts": _boundary_counts(rows),
        "recommended_stabilization_order": list(GROUP_ORDER),
        "review_boundary_policy": {
            "do_not_revert_unrelated_user_changes": True,
            "generated_artifacts_default_not_committed": True,
            "real_local_attestation_never_committed": True,
            "configs_btc_security_never_committed": True,
            "redacted_templates_may_be_committed_after_review": True,
            "secret_like_values_must_be_redacted_before_git": True,
            "split_commits_by_review_group": True,
            "paper_live_state_unchanged": True,
        },
        "gate": _gate(),
        "guardrails": _guardrails(),
        "outputs": {
            "json": _portable_path(report_path, root),
            "csv": _portable_path(csv_path, root),
            "summary_cn": _portable_path(summary_path, root),
            "paper_live_safety_status": _portable_path(safety_path, root),
        },
    }
    _write_json(report_path, report)
    _write_rows_csv(csv_path, rows)
    _write_text(summary_path, render_summary_cn(report))
    _write_json(safety_path, _safety_status(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    lines = [
        "# BTC dirty worktree 审查边界",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 文件数：`{report.get('file_count')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- secret-like 未打码字段数：`{_mapping(report.get('secret_scan')).get('unredacted_secret_like_count')}`",
        "",
        "| 分组 | 文件数 | modified | untracked | 说明 |",
        "|---|---:|---:|---:|---|",
    ]
    for group in report.get("groups", []):
        lines.append(
            "| {group_id} | {file_count} | {modified_count} | {untracked_count} | {description_cn} |".format(
                **group
            )
        )
    lines.extend(
        [
            "",
            "## 建议处理顺序",
            "",
        ]
    )
    for group_id in report.get("recommended_stabilization_order", []):
        lines.append(f"- `{group_id}`")
    lines.extend(
        [
            "",
            "## 提交边界",
            "",
            "| 边界 | 文件数 | 含义 |",
            "|---|---:|---|",
        ]
    )
    for row in report.get("boundary_counts", []):
        lines.append(f"| `{row.get('commit_boundary')}` | {row.get('file_count')} | {row.get('description_cn')} |")
    lines.extend(
        [
            "",
            "## Secret / Redaction 扫描",
            "",
        ]
    )
    secret_scan = _mapping(report.get("secret_scan"))
    lines.append(f"- 扫描文件数：`{secret_scan.get('scanned_file_count')}`")
    lines.append(f"- secret-like 字段数：`{secret_scan.get('secret_like_field_count')}`")
    lines.append(f"- 未打码字段数：`{secret_scan.get('unredacted_secret_like_count')}`")
    if secret_scan.get("unredacted_secret_like_count"):
        lines.append("- 结论：存在未打码风险字段，相关文件禁止提交，必须先改成 redacted facts。")
    else:
        lines.append("- 结论：未发现未打码 secret-like 值；真实本地 attestation/security config 仍按 never commit 处理。")
    lines.extend(
        [
            "",
            "本报告只读 `git status`，不回滚、不移动文件、不提交 git，不改变 paper/live/broker/order 状态。",
        ]
    )
    return "\n".join(lines) + "\n"


def _row_from_status_line(line: str) -> dict[str, Any]:
    status = line[:2]
    path = line[3:].strip() if len(line) > 3 else ""
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    return {
        "raw_status": status,
        "path": path.replace("\\", "/"),
        "is_untracked": status == "??",
        "is_modified": "M" in status,
        "is_deleted": "D" in status,
        "is_renamed": "R" in status,
    }


def _classify_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    if lower.startswith("artifacts/") or lower.startswith("data/"):
        return "generated_artifacts_data"
    if lower.startswith("frontend/") or lower.startswith("backend/") or "btccontrolcenter" in lower:
        return "frontend_control_center"
    if "api_key" in lower or "attestation" in lower or lower.startswith("configs/btc/security") or lower.startswith(
        "configs/btc/paper_runtime"
    ):
        return "security_attestation"
    if "promotion_gate" in lower or "gate_dashboard" in lower or "root_cause" in lower:
        return "gate_root_cause"
    if (
        "runtime" in lower
        or "replay" in lower
        or "depth_slippage" in lower
        or "exchange/" in lower
        or "oms/" in lower
        or "kill_switch" in lower
        or "micro_live_preflight" in lower
        or "paper_exchange_rule" in lower
    ):
        return "runtime_replay"
    if (
        "lab" in lower
        or "attack" in lower
        or "rollover" in lower
        or "strategy_governance" in lower
        or "multi_timeframe" in lower
        or "high_octane" in lower
        or "ten_u" in lower
    ):
        return "research_labs"
    return "other"


def _file_kind(path: str) -> str:
    lower = path.replace("\\", "/").lower()
    name = Path(lower).name
    if lower.startswith("configs/btc/security/"):
        return "local_security_config"
    if lower == "configs/btc/paper_runtime/account_runtime_attestation.json":
        return "local_account_attestation"
    if name.endswith(".template.json") or ".template." in name:
        return "config_template"
    if lower.startswith("artifacts/"):
        return "generated_evidence_artifact"
    if lower.startswith("data/"):
        return "local_data"
    if lower.startswith("tests/"):
        return "test"
    if lower.startswith(("quant_crypto/", "scripts/", "frontend/", "backend/")):
        return "source"
    if lower.startswith("configs/"):
        return "config"
    return "other"


def _commit_boundary(path: str) -> str:
    kind = _file_kind(path)
    if kind in {"local_security_config", "local_account_attestation", "local_data"}:
        return "never_commit"
    if kind == "generated_evidence_artifact":
        return "generated_artifact_not_code"
    if kind == "config_template":
        return "committable_redacted_template"
    if kind in {"source", "test"}:
        return "committable_source_or_test"
    if kind == "config":
        return "review_before_commit_config"
    return "manual_review_required"


def _commit_policy(path: str) -> str:
    boundary = _commit_boundary(path)
    if boundary == "never_commit":
        return "do_not_commit_real_local_secret_or_data"
    if boundary == "generated_artifact_not_code":
        return "do_not_commit_by_default_evidence_output_only"
    if boundary == "committable_redacted_template":
        return "commit_only_if_redacted_template_no_real_values"
    if boundary == "committable_source_or_test":
        return "may_commit_in_grouped_review_after_tests"
    if boundary == "review_before_commit_config":
        return "manual_review_required_redacted_config_only"
    return "manual_review_required"


def _group_summary(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    descriptions = {
        "runtime_replay": "paper runtime/replay/OMS/depth/kill/micro-live 链路",
        "security_attestation": "API key 权限、account attestation、redacted config",
        "gate_root_cause": "promotion gate、root-cause DAG、gate dashboard",
        "frontend_control_center": "Crypto UI / operator control center",
        "research_labs": "策略研究实验室与复核包",
        "generated_artifacts_data": "生成物和本地数据，默认不作为代码提交主体",
        "other": "待人工归类的剩余改动",
    }
    for group_id in GROUP_ORDER:
        group_rows = [row for row in rows if row.get("review_group") == group_id]
        if not group_rows:
            continue
        result.append(
            {
                "group_id": group_id,
                "file_count": len(group_rows),
                "modified_count": sum(1 for row in group_rows if row.get("is_modified")),
                "untracked_count": sum(1 for row in group_rows if row.get("is_untracked")),
                "deleted_count": sum(1 for row in group_rows if row.get("is_deleted")),
                "never_commit_count": sum(1 for row in group_rows if row.get("commit_boundary") == "never_commit"),
                "secret_like_unredacted_count": sum(_int(row.get("secret_like_unredacted_count")) for row in group_rows),
                "description_cn": descriptions[group_id],
                "sample_paths": [str(row.get("path")) for row in group_rows[:12]],
            }
        )
    return result


def build_dirty_state_summary(repo_root: Path | None = None) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    if not _is_git_worktree_root(root):
        return _dirty_state_summary_from_rows([])
    lines = _git_status_lines(root)
    rows = [_row_from_status_line(line) for line in lines if line.strip()]
    for row in rows:
        path = str(row.get("path") or "")
        row["review_group"] = _classify_path(path)
        row["file_kind"] = _file_kind(path)
        row["commit_boundary"] = _commit_boundary(path)
    return _dirty_state_summary_from_rows(rows)


def _is_git_worktree_root(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-prefix"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip() == ""


def _dirty_state_summary_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    never_commit_paths = [str(row.get("path")) for row in rows if row.get("commit_boundary") == "never_commit"]
    generated_artifact_paths = [
        str(row.get("path")) for row in rows if row.get("commit_boundary") == "generated_artifact_not_code"
    ]
    committable_source_or_test_paths = [
        str(row.get("path")) for row in rows if row.get("commit_boundary") == "committable_source_or_test"
    ]
    return {
        "is_dirty": bool(rows),
        "file_count": len(rows),
        "modified_count": sum(1 for row in rows if row.get("is_modified")),
        "untracked_count": sum(1 for row in rows if row.get("is_untracked")),
        "never_commit_count": sum(1 for row in rows if row.get("commit_boundary") == "never_commit"),
        "generated_artifact_count": sum(1 for row in rows if row.get("commit_boundary") == "generated_artifact_not_code"),
        "committable_source_or_test_count": sum(
            1 for row in rows if row.get("commit_boundary") == "committable_source_or_test"
        ),
        "only_generated_or_never_commit_dirty": bool(rows)
        and not committable_source_or_test_paths
        and all(
            row.get("commit_boundary") in {"generated_artifact_not_code", "never_commit"}
            for row in rows
        ),
        "never_commit_paths": never_commit_paths[:40],
        "generated_artifact_paths": generated_artifact_paths[:40],
        "committable_source_or_test_paths": committable_source_or_test_paths[:40],
        "group_counts": {
            group_id: sum(1 for row in rows if row.get("review_group") == group_id) for group_id in GROUP_ORDER
        },
    }


def _boundary_counts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    descriptions = {
        "never_commit": "真实本地 attestation、安全配置或本地数据，永不提交。",
        "generated_artifact_not_code": "生成证据产物，默认不作为代码提交主体。",
        "committable_redacted_template": "可提交模板，但必须只包含 redacted facts / 占位符。",
        "committable_source_or_test": "源码或测试，可按主题分组提交。",
        "review_before_commit_config": "配置文件，提交前必须人工确认无真实密钥。",
        "manual_review_required": "未归类文件，需要人工决定提交边界。",
    }
    result = []
    for boundary, description in descriptions.items():
        count = sum(1 for row in rows if row.get("commit_boundary") == boundary)
        if count:
            result.append({"commit_boundary": boundary, "file_count": count, "description_cn": description})
    return result


def _secret_scan_for_path(root: Path, path: str) -> dict[str, Any]:
    normalized = path.replace("\\", "/")
    resolved = root / normalized
    base = {
        "scanned": False,
        "scan_skipped_reason": "",
        "secret_like_field_count": 0,
        "secret_like_redacted_count": 0,
        "secret_like_unredacted_count": 0,
        "secret_like_fields": [],
        "redaction_required": _commit_boundary(normalized) in {"never_commit", "review_before_commit_config", "committable_redacted_template"},
    }
    if not resolved.exists() or not resolved.is_file():
        base["scan_skipped_reason"] = "file_missing_or_not_regular"
        return base
    if resolved.suffix.lower() not in TEXT_SUFFIXES:
        base["scan_skipped_reason"] = "non_text_suffix_skipped"
        return base
    try:
        size = resolved.stat().st_size
    except OSError:
        base["scan_skipped_reason"] = "stat_failed"
        return base
    if size > MAX_SECRET_SCAN_BYTES:
        base["scan_skipped_reason"] = "file_too_large"
        return base
    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        base["scan_skipped_reason"] = "utf8_decode_failed"
        return base
    except OSError:
        base["scan_skipped_reason"] = "read_failed"
        return base
    findings = _secret_findings_from_text(text)
    base["scanned"] = True
    base["secret_like_field_count"] = len(findings)
    base["secret_like_redacted_count"] = sum(1 for item in findings if item["redacted"])
    base["secret_like_unredacted_count"] = sum(1 for item in findings if not item["redacted"])
    base["secret_like_fields"] = findings[:40]
    return base


def _secret_findings_from_text(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, (dict, list)):
        _collect_json_secret_findings(payload, findings=findings)
    else:
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not _line_has_secret_assignment(line):
                continue
            key = _line_secret_key(line)
            value = _line_secret_value(line)
            findings.append(
                {
                    "field": key,
                    "line": line_no,
                    "redacted": _looks_redacted(value),
                    "value_disclosed": False,
                }
            )
    return _dedupe_findings(findings)


def _collect_json_secret_findings(value: Any, *, findings: list[dict[str, Any]], prefix: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if _is_secret_field(str(key)):
                findings.append(
                    {
                        "field": path,
                        "line": None,
                        "redacted": _looks_redacted(child),
                        "value_disclosed": False,
                    }
                )
            _collect_json_secret_findings(child, findings=findings, prefix=path)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:500]):
            _collect_json_secret_findings(child, findings=findings, prefix=f"{prefix}[{idx}]")


def _line_secret_key(line: str) -> str:
    before = re.split(r"[:=]", line, maxsplit=1)[0].strip().strip('"').strip("'")
    return before[-80:] if before else "secret_like_line"


def _line_secret_value(line: str) -> str:
    parts = re.split(r"[:=]", line, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _line_has_secret_assignment(line: str) -> bool:
    if not SECRET_FIELD_RE.search(line):
        return False
    if ":" not in line and "=" not in line:
        return False
    key = _line_secret_key(line)
    if not _is_secret_field(key):
        return False
    value = _line_secret_value(line)
    if not value:
        return False
    lowered = value.lower().strip()
    if lowered in {"true", "false", "none", "null", "0", "1", "[]", "{}"}:
        return False
    ignored_prefixes = ("bool(", "str(", "int(", "float(", "dict(", "list(", "set(", "tuple(")
    if lowered.startswith(ignored_prefixes):
        return False
    ignored_fragments = (
        "os.environ",
        "getenv",
        "payload",
        "record.",
        "config.",
        "args.",
        "source.",
        "value",
        "summary",
        "assert ",
        "def ",
        "btc_api_key_",
    )
    if any(fragment in lowered for fragment in ignored_fragments):
        return False
    if not any(quote in value for quote in ("\"", "'")) and not SECRET_FIELD_RE.search(value):
        return False
    return True


def _is_secret_field(field: str) -> bool:
    text = field.strip().strip('"').strip("'").lower()
    if not text:
        return False
    if any(token in text for token in NON_SECRET_FIELD_TOKENS):
        return False
    return bool(SECRET_FIELD_RE.search(text))


def _looks_redacted(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (bool, int, float, list, dict)):
        return True
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return True
    lowered = text.lower()
    redacted_tokens = (
        "redacted",
        "placeholder",
        "example",
        "your_",
        "<",
        "***",
        "xxxx",
        "dummy",
        "not_set",
        "fake",
        "sample",
        "do-not",
        "not-store",
        "not-leak",
    )
    return any(token in lowered for token in redacted_tokens)


def _dedupe_findings(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, Any]] = set()
    result = []
    for item in findings:
        key = (str(item.get("field")), item.get("line"))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _secret_scan_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scans = [_mapping(row.get("secret_scan")) for row in rows]
    unredacted_paths = [
        str(row.get("path"))
        for row in rows
        if _int(_mapping(row.get("secret_scan")).get("secret_like_unredacted_count")) > 0
    ]
    never_commit_paths = [str(row.get("path")) for row in rows if row.get("commit_boundary") == "never_commit"]
    return {
        "schema_version": "btc_dirty_worktree_secret_scan_v1",
        "scanned_file_count": sum(1 for scan in scans if scan.get("scanned")),
        "skipped_file_count": sum(1 for scan in scans if not scan.get("scanned")),
        "secret_like_field_count": sum(_int(scan.get("secret_like_field_count")) for scan in scans),
        "redacted_secret_like_count": sum(_int(scan.get("secret_like_redacted_count")) for scan in scans),
        "unredacted_secret_like_count": sum(_int(scan.get("secret_like_unredacted_count")) for scan in scans),
        "unredacted_secret_like_paths": unredacted_paths,
        "never_commit_paths": never_commit_paths,
        "redaction_boundary_passed": not unredacted_paths,
    }


def _git_status_lines(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git(args: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = [
        "review_group",
        "raw_status",
        "path",
        "is_untracked",
        "is_modified",
        "is_deleted",
        "is_renamed",
        "file_kind",
        "commit_boundary",
        "commit_policy",
        "secret_like_field_count",
        "secret_like_unredacted_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def _gate() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
    }


def _guardrails() -> dict[str, bool]:
    return {
        "read_only_git_status": True,
        "file_revert_used": False,
        "git_commit_created": False,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "broker_access_allowed": False,
        "order_endpoint_used": False,
        "private_endpoint_used": False,
    }


def _safety_status(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_dirty_worktree_boundary_safety_status_v1",
        "status": "research_only",
        "paper_queue_write_allowed": False,
        "paper_allowed": False,
        "live_unlock_allowed": False,
        "broker_or_order_allowed": False,
        "file_revert_used": False,
        "git_commit_created": False,
        "secret_like_unredacted_count": _mapping(report.get("secret_scan")).get("unredacted_secret_like_count", 0),
        "redaction_boundary_passed": _mapping(report.get("secret_scan")).get("redaction_boundary_passed", True),
        "source_report": report.get("outputs", {}).get("json"),
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _portable_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
