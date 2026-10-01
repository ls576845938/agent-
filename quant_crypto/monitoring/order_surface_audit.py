from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Mapping

from .artifact_schema import apply_btc_artifact_schema
from .audit_dag import stable_payload_hash


BTC_ORDER_SURFACE_AUDIT_VERSION = "btc_order_surface_audit_v1"

OMS_ALLOWED_PREFIXES = ("quant_crypto/oms/",)
AUDIT_POLICY_PATHS = ("quant_crypto/monitoring/order_surface_audit.py",)

DIRECT_ORDER_CALL_RE = re.compile(
    r"\b("
    r"create_order|place_order|submit_order|send_order|cancel_order|replace_order|"
    r"batch_order|create_market_order|create_limit_order"
    r")\s*\(",
    re.IGNORECASE,
)
BROKER_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+("
    r"ccxt|alpaca|ib_insync|binance|okx|kucoin|coinbase|bybit|kraken"
    r")\b",
    re.IGNORECASE,
)
PRIVATE_ENDPOINT_LITERAL_RE = re.compile(
    r"[\"']([^\"']*(?:"
    r"/order|/batchOrders|/trade/order|/account|/position|/positionRisk|"
    r"/listenKey|/userDataStream|/leverage|/margin|/transfer|/income|/balance|/broker"
    r")[^\"']*)[\"']",
    re.IGNORECASE,
)
UNSAFE_FLAG_RE = re.compile(r"\b(live_order_allowed|allow_live_orders|order_endpoint_allowed)\s*[:=]\s*True\b")


@dataclass(frozen=True)
class BTCOrderSurfaceFinding:
    path: str
    line: int
    rule: str
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class BTCOrderSurfaceNonBlockingMatch:
    path: str
    line: int
    category: str
    snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "category": self.category,
            "snippet": self.snippet,
        }


def audit_btc_direct_order_call_surface(
    source_files: Mapping[str, str],
    *,
    oms_allowed_prefixes: tuple[str, ...] = OMS_ALLOWED_PREFIXES,
    generated_at_utc: datetime | None = None,
    aggregation_batch_id: str | None = None,
) -> dict[str, object]:
    findings: list[BTCOrderSurfaceFinding] = []
    non_blocking_matches: list[BTCOrderSurfaceNonBlockingMatch] = []
    scanned_paths = sorted(source_files)
    for raw_path in scanned_paths:
        path = _normalize_path(raw_path)
        if _is_allowed_oms_path(path, oms_allowed_prefixes):
            continue
        if path in AUDIT_POLICY_PATHS:
            continue
        path_findings, path_non_blocking = _scan_path(path, source_files[raw_path])
        findings.extend(path_findings)
        non_blocking_matches.extend(path_non_blocking)

    blockers = [f"btc_direct_order_surface_violation:{finding.path}:{finding.line}:{finding.rule}" for finding in findings]
    payload: dict[str, object] = {
        "order_surface_audit_version": BTC_ORDER_SURFACE_AUDIT_VERSION,
        "aggregation_batch_id": aggregation_batch_id or "",
        "status": "blocked" if findings else "complete",
        "decision": "freeze_or_wrap_non_oms_order_surface" if findings else "non_oms_order_surface_clean",
        "blockers": blockers,
        "warnings": [],
        "scanned_paths": scanned_paths,
        "allowed_order_boundary": list(oms_allowed_prefixes),
        "findings": [finding.to_dict() for finding in findings],
        "non_blocking_match_count": len(non_blocking_matches),
        "non_blocking_matches": [match.to_dict() for match in non_blocking_matches],
        "classification_policy": {
            "blocking": [
                "direct_order_call_outside_oms",
                "broker_sdk_import_outside_oms",
                "private_or_order_endpoint_literal",
                "unsafe_live_order_flag",
            ],
            "non_blocking": [
                "public_endpoint_literal",
                "safety_statement_text",
                "local_config_or_artifact_path",
                "formula_or_documentation_text",
            ],
        },
    }
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    return apply_btc_artifact_schema(
        payload,
        decision=str(payload["decision"]),
        generated_at_utc=generated_at,
        as_of_utc=generated_at,
        blockers=blockers,
        warnings=[],
        input_hashes={"source_files": stable_payload_hash(dict(source_files))},
    )


def _scan_path(path: str, source: str) -> tuple[list[BTCOrderSurfaceFinding], list[BTCOrderSurfaceNonBlockingMatch]]:
    findings: list[BTCOrderSurfaceFinding] = []
    non_blocking: list[BTCOrderSurfaceNonBlockingMatch] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if DIRECT_ORDER_CALL_RE.search(line):
            findings.append(_finding(path, line_number, "direct_order_call", line))
        if BROKER_IMPORT_RE.search(line):
            findings.append(_finding(path, line_number, "broker_sdk_import", line))
        for match in PRIVATE_ENDPOINT_LITERAL_RE.finditer(line):
            literal = match.group(1)
            category = _non_blocking_literal_category(literal)
            if category:
                non_blocking.append(_non_blocking_match(path, line_number, category, line))
            else:
                findings.append(_finding(path, line_number, "private_or_order_endpoint_literal", line))
        if UNSAFE_FLAG_RE.search(line):
            findings.append(_finding(path, line_number, "unsafe_live_order_flag", line))
    return findings, non_blocking


def _finding(path: str, line: int, rule: str, snippet: str) -> BTCOrderSurfaceFinding:
    return BTCOrderSurfaceFinding(path=path, line=line, rule=rule, snippet=snippet.strip()[:160])


def _non_blocking_match(path: str, line: int, category: str, snippet: str) -> BTCOrderSurfaceNonBlockingMatch:
    return BTCOrderSurfaceNonBlockingMatch(path=path, line=line, category=category, snippet=snippet.strip()[:160])


def _non_blocking_literal_category(literal: str) -> str:
    text = literal.strip()
    lower = text.lower()
    if "/api/v5/public/" in lower or "/api/v5/market/" in lower:
        return "public_endpoint_literal"
    if "private/order endpoint" in lower or "private/order endpoints" in lower:
        return "safety_statement_text"
    if (
        lower.startswith("configs/")
        or lower.startswith("artifacts/")
        or lower.startswith("data/")
        or lower.endswith(".json")
        or lower.endswith(".csv")
        or lower.endswith(".yaml")
        or lower.endswith(".yml")
    ):
        return "local_config_or_artifact_path"
    if " " in text or "1/leverage" in lower or "liquidation" in lower or "margin" in lower:
        return "formula_or_documentation_text"
    return ""


def _normalize_path(path: str) -> str:
    normalized = str(PurePosixPath(path.replace("\\", "/")))
    return normalized.lstrip("./")


def _is_allowed_oms_path(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)
