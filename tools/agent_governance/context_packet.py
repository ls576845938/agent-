from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

MODULE_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_REPO_ROOT))

from tools.agent_governance.git_metadata import GitMetadataError, current_branch_head
from tools.agent_governance.safe_status import scoped_status, status_paths
from tools.agent_governance.delivery_policy import (
    CHANGE_RISKS,
    canonical_change_risk,
    delivery_requirements,
    infer_change_risk,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / "docs" / "agent_playbooks" / "pitfall_catalog.json"

ROLE_ALIASES = {
    "all": "all",
    "auto": "auto",
    "default": "all",
    "worker": "all",
    "explorer": "all",
    "architect": "architect",
    "architecture": "architect",
    "quant_architect": "architect",
    "data": "data_steward",
    "data_engineer": "data_steward",
    "data_steward": "data_steward",
    "integrator": "integrator",
    "integration": "integrator",
    "super_developer": "super_developer",
    "quant_developer": "super_developer",
    "us_developer": "super_developer",
    "a_share": "a_share_developer",
    "a_share_developer": "a_share_developer",
    "cn_developer": "a_share_developer",
    "cn_equity_developer": "a_share_developer",
    "btc": "btc_developer",
    "btc_developer": "btc_developer",
    "research": "researcher",
    "researcher": "researcher",
}

ROLE_KEYWORDS = (
    (
        "a_share_developer",
        ("a股程序员", "a股 程序员", "a-share developer", "cn equity developer", "a_share_developer"),
    ),
    ("btc_developer", ("btc程序员", "btc 程序员", "btc developer", "btc_developer")),
    ("data_steward", ("数据师", "data steward", "data engineer", "data_steward")),
    ("super_developer", ("超级程序员", "super developer", "us developer", "super_developer")),
    ("researcher", ("研究员", "researcher", "策略研究")),
    ("integrator", ("集成任务", "integrator", "integration worktree")),
    ("architect", ("架构师", "architect", "architecture review")),
)

SCOPE_KEYWORDS = {
    "governance": ("agents.md", "agent", "工作流", "踩坑", "playbook", "hook", "skill"),
    "btc": ("btc", "bitcoin", "okx", "binance", "永续", "funding", "清算"),
    "us_equity": ("美股", "us equity", "ibkr", "etf", "fred", "tiingo"),
    "cn_equity": ("a股", "a-share", "a share", "cn equity", "沪深", "上交所", "深交所", "北交所"),
    "data": ("数据", "data", "schema", "manifest", "lineage", "freshness", "pit"),
    "research": ("研究", "research", "hypothesis", "holdout", "过拟合"),
    "backtest": ("回测", "backtest", "walk-forward", "walk forward", "slippage", "cost"),
    "risk": ("风控", "risk", "position", "portfolio", "仓位", "杠杆"),
    "execution": ("执行", "oms", "order", "fill", "broker", "exchange", "成交"),
    "monitoring": ("监控", "monitor", "replay", "incident", "audit", "dashboard"),
    "gate": ("gate", "promotion", "readiness", "paper", "live", "blocker"),
    "architecture": ("架构", "architecture", "boundary", "service layer"),
    "security": ("secret", "credential", "api key", "权限", "安全"),
    "strategy": ("策略", "strategy", "signal", "forecast", "alpha"),
}

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def _normalize(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def canonical_role(value: str | None) -> str:
    if not value:
        return "all"
    normalized = _normalize(value)
    if normalized not in ROLE_ALIASES:
        raise ValueError(f"unknown_role:{value}")
    return ROLE_ALIASES[normalized]


def infer_role(prompt: str) -> str:
    lowered = prompt.lower()
    for role, keywords in ROLE_KEYWORDS:
        if any(keyword.lower() in lowered for keyword in keywords):
            return role
    return "all"


def infer_scopes(text: str) -> set[str]:
    lowered = text.lower()
    return {
        scope
        for scope, keywords in SCOPE_KEYWORDS.items()
        if any(keyword.lower() in lowered for keyword in keywords)
    }


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError("pitfall_catalog_invalid")
    return payload


def catalog_hash(catalog: dict[str, Any]) -> str:
    canonical = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def select_rules(
    catalog: dict[str, Any],
    *,
    role: str,
    scopes: Iterable[str] = (),
    change_risk: str = "unclassified",
    max_rules: int | None = None,
) -> list[dict[str, Any]]:
    canonical = canonical_role(role)
    risk = canonical_change_risk(change_risk)
    requested_scopes = {scope.strip().lower() for scope in scopes if scope.strip()}
    selected: list[dict[str, Any]] = []

    for rule in catalog["rules"]:
        if rule.get("status") != "active":
            continue
        roles = set(rule.get("roles", []))
        if "all" not in roles and canonical not in roles:
            continue
        rule_scopes = set(rule.get("scopes", []))
        enforcement = str(rule.get("enforcement") or "conditional_guardrail")
        if risk == "unclassified":
            # Preserve the pre-policy conservative selector for prompts that
            # cannot yet be safely classified.
            if requested_scopes and not ({"shared", "governance"} & rule_scopes):
                if not requested_scopes.intersection(rule_scopes):
                    continue
        else:
            if enforcement == "conditional_guardrail":
                applicability = rule.get("applicability", {})
                applicable_risks = set(
                    applicability.get("change_risks", [])
                    if isinstance(applicability, dict)
                    else []
                )
                if risk not in applicable_risks:
                    continue
            if (
                "shared" not in rule_scopes
                and requested_scopes
                and not requested_scopes.intersection(rule_scopes)
            ):
                continue
        selected.append(rule)

    selected.sort(key=lambda item: (SEVERITY_ORDER.get(item.get("severity"), 9), item["id"]))
    limit = max_rules or int(catalog.get("selection_policy", {}).get("max_rules", 24))
    return selected[:limit]


def git_snapshot(repo_root: Path, *, include_dirty: bool = False) -> dict[str, Any]:
    try:
        _, head = current_branch_head(repo_root)
    except (OSError, GitMetadataError):
        head = "unavailable"
    if not include_dirty:
        return {
            "head": head,
            "dirty_count": -1,
            "dirty_paths": [],
            "dirty_paths_truncated": False,
            "dirty_rechecked": False,
        }
    try:
        paths = status_paths(scoped_status(repo_root))
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError):
        return {
            "head": head,
            "dirty_count": -1,
            "dirty_paths": [],
            "dirty_paths_truncated": False,
            "dirty_rechecked": False,
        }

    return {
        "head": head,
        "dirty_count": len(paths),
        "dirty_paths": paths[:25],
        "dirty_paths_truncated": len(paths) > 25,
        "dirty_rechecked": True,
    }


def build_packet(
    *,
    catalog: dict[str, Any],
    role: str,
    scopes: Iterable[str],
    change_risk: str = "unclassified",
    repo_root: Path = REPO_ROOT,
    max_rules: int | None = None,
    include_dirty: bool = False,
) -> dict[str, Any]:
    canonical = canonical_role(role)
    risk = canonical_change_risk(change_risk)
    scope_list = sorted(set(scopes))
    snapshot = git_snapshot(repo_root, include_dirty=include_dirty)
    rules = select_rules(
        catalog,
        role=canonical,
        scopes=scope_list,
        change_risk=risk,
        max_rules=max_rules,
    )
    return {
        "schema_version": "agent_context_packet_v1",
        "ruleset_version": catalog["ruleset_version"],
        "catalog_hash": catalog_hash(catalog),
        "role": canonical,
        "scopes": scope_list,
        "change_risk": risk,
        "delivery_requirements": delivery_requirements(risk),
        "repo_root": str(repo_root),
        **snapshot,
        "selected_rule_count": len(rules),
        "rules": [
            {
                "id": rule["id"],
                "severity": rule["severity"],
                "enforcement": rule.get(
                    "enforcement", "conditional_guardrail"
                ),
                "rule": rule["rule"],
                "sources": rule["sources"],
                "regression_tests": rule["regression_tests"],
            }
            for rule in rules
        ],
    }


def render_markdown(packet: dict[str, Any], *, max_chars: int | None = None) -> str:
    dirty = packet["dirty_count"]
    dirty_text = "not_rechecked" if not packet.get("dirty_rechecked") else str(dirty)
    lines = [
        "Quant agent context packet",
        f"- ruleset: {packet['ruleset_version']}",
        f"- catalog_hash: {packet['catalog_hash']}",
        f"- role: {packet['role']}",
        f"- scopes: {', '.join(packet['scopes']) or 'shared'}",
        f"- change_risk: {packet['change_risk']}",
        f"- head: {packet['head']}",
        f"- dirty_paths: {dirty_text}",
        "- delivery_requirements:",
        *[
            f"  - {key}: {value}"
            for key, value in packet["delivery_requirements"].items()
            if key
            in {
                "independent_integrator_required",
                "promotion_artifact_rebuild_required",
                "backend_restart_required",
                "fast_forward_main_allowed",
            }
            or (packet["change_risk"] == "research_readonly_release" and key in {
                "backend_evidence_profile", "readiness_ceiling", "required_checks", "required_false_flags",
            })
        ],
        "- active pitfalls:",
    ]
    lines.extend(
        f"  - [{rule['severity']}] [{rule['enforcement']}] "
        f"{rule['id']}: {rule['rule']}"
        for rule in packet["rules"]
    )
    lines.append("- before writes: declare touch set and preserve unrelated dirty changes")
    rendered = "\n".join(lines)
    if max_chars is None or len(rendered) <= max_chars:
        return rendered
    suffix = "\n".join(
        [
            "- context_truncated: true",
            f"- role: {packet['role']}",
            f"- change_risk: {packet['change_risk']}",
            f"- head: {packet['head']}",
            "- active_rule_ids: " + ",".join(rule["id"] for rule in packet["rules"]),
        ]
    )
    if packet["change_risk"] == "research_readonly_release":
        suffix += "\n- research_release_boundary: research_readonly; independent_review/current_main/sealed_evidence/browser required; demo/promotion/paper/live/private/order/transfer/withdraw=false"
    body_budget = max(0, max_chars - len(suffix) - 1)
    body = rendered[:body_budget].rstrip()
    return f"{body}\n{suffix}" if body else suffix[:max_chars]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a bounded agent governance context packet.")
    parser.add_argument("--role", default="auto")
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument(
        "--change-risk",
        choices=CHANGE_RISKS,
    )
    parser.add_argument("--prompt", default="")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--max-rules", type=int)
    parser.add_argument("--include-dirty", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    role = infer_role(args.prompt) if args.role == "auto" else canonical_role(args.role)
    inferred = infer_scopes(" ".join([args.prompt, *args.changed_file]))
    scopes = set(args.scope).union(inferred)
    change_risk = args.change_risk or infer_change_risk(args.prompt)
    catalog = load_catalog(args.catalog)
    packet = build_packet(
        catalog=catalog,
        role=role,
        scopes=scopes,
        change_risk=change_risk,
        repo_root=args.repo_root.resolve(),
        max_rules=args.max_rules,
        include_dirty=args.include_dirty,
    )
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.format == "markdown":
        print(render_markdown(packet))
    else:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
