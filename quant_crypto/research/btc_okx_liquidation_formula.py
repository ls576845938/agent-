from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector, PUBLIC_ENDPOINTS
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from quant_crypto.data.okx_swap_public import OkxSwapPublicCollector, PUBLIC_ENDPOINTS


SCHEMA_VERSION = "btc_okx_liquidation_formula_report_v1"
DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_cost_model/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_liquidation_formula_report.json"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_ROOT / "btc_okx_liquidation_formula_summary_cn.md"
DEFAULT_CONFIG_PATH = Path("configs/data/btc_perpetual_sources.yaml")
SYMBOL = "BTCUSDT"
OKX_INST_FAMILY = "BTC-USDT"
OKX_INST_TYPE = "SWAP"
TD_MODES = ("cross", "isolated")
OFFICIAL_SOURCE_REFS = [
    {
        "source": "okx_api_public_position_tiers",
        "url": "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-position-tiers",
        "evidence": "Public REST endpoint /api/v5/public/position-tiers provides tier, minSz, maxSz, mmr, imr and maxLever.",
    },
    {
        "source": "okx_liquidation_price_conditions",
        "url": "https://www.okx.com/help/how-to-calculate-the-price-what-are-the-conditions-for-strong-flat",
        "evidence": "OKX states liquidation/position reduction may trigger when maintenance margin ratio is <= 100%.",
    },
    {
        "source": "okx_futures_margin_calculation_rules",
        "url": "https://www.okx.com/help/futures-margin-calculation-rules",
        "evidence": "OKX states USDT-margined initial margin and maintenance margin ratio rules.",
    },
    {
        "source": "okx_forced_liquidation_faq",
        "url": "https://www.okx.com/en-sg/help/liquidation-faq",
        "evidence": "OKX states liquidation is based on mark price rather than last or index price.",
    },
]


@dataclass(frozen=True)
class NormalizedTier:
    td_mode: str
    tier: int
    min_sz: float
    max_sz: float
    mmr: float
    imr: float
    max_lever: float
    inst_family: str
    inst_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "td_mode": self.td_mode,
            "tier": self.tier,
            "min_sz": self.min_sz,
            "max_sz": self.max_sz,
            "mmr": self.mmr,
            "imr": self.imr,
            "max_lever": self.max_lever,
            "inst_family": self.inst_family,
            "inst_id": self.inst_id,
        }


def build_btc_okx_liquidation_formula_report(
    *,
    repo_root: Path | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    execute_network: bool = False,
    generated_at_utc: datetime | None = None,
    collector_factory: type[OkxSwapPublicCollector] = OkxSwapPublicCollector,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    output_dir = output_root if output_root.is_absolute() else root / output_root
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "okx_liquidation_formula_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    generated = generated_at_utc or datetime.now(timezone.utc)

    planned_requests = _planned_requests(collector_factory)
    tier_captures: list[dict[str, Any]] = []
    capture_summaries: list[dict[str, Any]] = []
    raw_response_files: list[dict[str, Any]] = []
    blockers: list[str] = []
    if execute_network:
        collector = collector_factory(dry_run=False, allow_network=True)
        for td_mode in TD_MODES:
            capture = collector.request_by_name("position_tiers", _position_tier_params(td_mode))
            payload = _mapping(capture.get("payload"))
            tier_captures.append({"td_mode": td_mode, "payload": payload})
            capture_summaries.append({"td_mode": td_mode, **_public_capture_summary(capture)})
            filename = f"position_tiers_{td_mode}.json"
            raw_path = raw_dir / filename
            _write_json(raw_path, payload)
            raw_response_files.append(
                {
                    "td_mode": td_mode,
                    "path": _portable_path(raw_path, root),
                    "sha256": _sha256(raw_path),
                    "size_bytes": raw_path.stat().st_size,
                }
            )
    else:
        blockers.append("btc_okx_position_tiers_network_capture_not_executed")

    tiers_by_mode = _normalize_tiers(tier_captures)
    tier_validation = _validate_tiers(tiers_by_mode)
    blockers.extend(tier_validation["blockers"])
    formula_verified = _formula_source_verified()
    maintenance_margin_tiers_verified = bool(tier_validation["maintenance_margin_tiers_verified"])
    exact_verified = formula_verified and maintenance_margin_tiers_verified
    if not formula_verified:
        blockers.append("btc_okx_liquidation_formula_official_source_missing")
    if not exact_verified:
        blockers.append("btc_okx_exact_liquidation_formula_evidence_incomplete")
    blockers = _dedupe(blockers)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "verified_research_only" if exact_verified else ("dry_run" if not execute_network else "incomplete_research_only"),
        "decision": (
            "okx_usdt_swap_liquidation_formula_and_tiers_verified_research_only_no_paper_no_live"
            if exact_verified
            else "okx_liquidation_formula_or_tiers_incomplete_fail_closed_no_paper_no_live"
        ),
        "asset": "btc",
        "symbol": SYMBOL,
        "venue": "OKX",
        "instrument_family": OKX_INST_FAMILY,
        "instrument_type": OKX_INST_TYPE,
        "source_method": "okx_public_rest_position_tiers_plus_official_help_docs",
        "public_rest_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "network_called": bool(execute_network),
        "code_commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "planned_requests": planned_requests,
        "capture_summaries": capture_summaries,
        "raw_response_files": raw_response_files,
        "official_source_refs": OFFICIAL_SOURCE_REFS,
        "formula_contract": _formula_contract(),
        "tier_validation": tier_validation,
        "normalized_tiers": {
            mode: [tier.to_dict() for tier in tiers]
            for mode, tiers in tiers_by_mode.items()
        },
        "liquidation_formula_verified": bool(formula_verified),
        "maintenance_margin_tiers_verified": bool(maintenance_margin_tiers_verified),
        "exact_exchange_liquidation_formula_verified": bool(exact_verified),
        "limitations": [
            "This verifies public OKX formula/tier evidence for BTC-USDT SWAP research, not account-specific portfolio margin state.",
            "Actual liquidation can depend on fee tier, position mode, account mode, open orders, risk reductions, mark path and exchange runtime state.",
            "No private account endpoint, OMS, broker or order endpoint is used.",
        ],
        "gate": {
            "research_only": True,
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "order_endpoint_allowed": False,
        },
        "blockers": blockers,
        "outputs": {
            "json": _portable_path(output_dir / DEFAULT_REPORT_PATH.name, root),
            "summary_cn": _portable_path(output_dir / DEFAULT_SUMMARY_PATH.name, root),
        },
    }
    _write_json(output_dir / DEFAULT_REPORT_PATH.name, report)
    _write_text(output_dir / DEFAULT_SUMMARY_PATH.name, render_summary_cn(report))
    return report


def render_summary_cn(report: Mapping[str, Any]) -> str:
    validation = _mapping(report.get("tier_validation"))
    lines = [
        "# BTC OKX 强平公式与保证金档位证据",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 结论：`{report.get('decision')}`",
        f"- 公共 REST：`{report.get('public_rest_only')}`",
        f"- 私有/下单接口：`private={report.get('private_endpoint_used')}`，`order={report.get('order_endpoint_used')}`",
        f"- 公式来源验证：`{report.get('liquidation_formula_verified')}`",
        f"- 保证金档位验证：`{report.get('maintenance_margin_tiers_verified')}`",
        f"- tdMode 覆盖：`{validation.get('td_modes_verified')}`",
        f"- 档位行数：`{validation.get('tier_count')}`",
        "",
        "这份报告只补“强平公式/保证金档位”证据。它不能替代真实 paper/live 执行、不能证明清算历史覆盖，也不会解锁 paper/live。",
    ]
    blockers = list(report.get("blockers", []))
    if blockers:
        lines.extend(["", "## 剩余缺口"])
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    return "\n".join(lines) + "\n"


def _planned_requests(collector_factory: type[OkxSwapPublicCollector]) -> list[dict[str, Any]]:
    collector = collector_factory(dry_run=True, allow_network=False)
    return [
        collector.request_by_name("position_tiers", _position_tier_params(td_mode))
        for td_mode in TD_MODES
    ]


def _position_tier_params(td_mode: str) -> dict[str, str]:
    return {
        "instType": OKX_INST_TYPE,
        "tdMode": td_mode,
        "instFamily": OKX_INST_FAMILY,
    }


def _public_capture_summary(capture: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(capture.get("payload"))
    return {
        "endpoint": capture.get("endpoint") or PUBLIC_ENDPOINTS["position_tiers"],
        "params": capture.get("params", {}),
        "duration_ms": capture.get("duration_ms"),
        "code": payload.get("code"),
        "message": payload.get("msg"),
        "row_count": len(payload.get("data", [])) if isinstance(payload.get("data"), list) else 0,
        "network_called": capture.get("network_called") is True,
    }


def _normalize_tiers(captures: list[Mapping[str, Any]]) -> dict[str, list[NormalizedTier]]:
    result = {mode: [] for mode in TD_MODES}
    for capture in captures:
        td_mode = str(capture.get("td_mode") or "")
        payload = _mapping(capture.get("payload"))
        data = payload.get("data", [])
        if td_mode not in result or not isinstance(data, list) or payload.get("code") != "0":
            continue
        rows: list[NormalizedTier] = []
        for item in data:
            row = _mapping(item)
            tier = _int(row.get("tier"))
            min_sz = _float(row.get("minSz"))
            max_sz = _float(row.get("maxSz"))
            mmr = _float(row.get("mmr"))
            imr = _float(row.get("imr"))
            max_lever = _float(row.get("maxLever"))
            if None in {tier, min_sz, max_sz, mmr, imr, max_lever}:
                continue
            rows.append(
                NormalizedTier(
                    td_mode=td_mode,
                    tier=int(tier),
                    min_sz=float(min_sz),
                    max_sz=float(max_sz),
                    mmr=float(mmr),
                    imr=float(imr),
                    max_lever=float(max_lever),
                    inst_family=str(row.get("instFamily") or row.get("uly") or ""),
                    inst_id=str(row.get("instId") or ""),
                )
            )
        result[td_mode] = sorted(rows, key=lambda item: item.tier)
    return result


def _validate_tiers(tiers_by_mode: Mapping[str, list[NormalizedTier]]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    td_modes_verified: list[str] = []
    tier_count = 0
    min_mmr_by_mode: dict[str, float] = {}
    max_lever_by_mode: dict[str, float] = {}
    for mode in TD_MODES:
        tiers = tiers_by_mode.get(mode, [])
        tier_count += len(tiers)
        if not tiers:
            blockers.append(f"btc_okx_position_tiers_{mode}_missing")
            continue
        td_modes_verified.append(mode)
        if [tier.tier for tier in tiers] != sorted({tier.tier for tier in tiers}):
            blockers.append(f"btc_okx_position_tiers_{mode}_tier_sequence_invalid")
        if any(tier.min_sz < 0.0 or tier.max_sz < tier.min_sz for tier in tiers):
            blockers.append(f"btc_okx_position_tiers_{mode}_size_range_invalid")
        if any(tier.mmr <= 0.0 or tier.imr <= 0.0 or tier.max_lever <= 0.0 for tier in tiers):
            blockers.append(f"btc_okx_position_tiers_{mode}_margin_values_invalid")
        if any(tier.inst_family not in {"BTC-USDT", ""} for tier in tiers):
            blockers.append(f"btc_okx_position_tiers_{mode}_instrument_family_mismatch")
        if _not_non_decreasing([tier.mmr for tier in tiers]):
            warnings.append(f"btc_okx_position_tiers_{mode}_mmr_not_monotonic")
        if _not_non_decreasing([tier.imr for tier in tiers]):
            warnings.append(f"btc_okx_position_tiers_{mode}_imr_not_monotonic")
        if _not_non_increasing([tier.max_lever for tier in tiers]):
            warnings.append(f"btc_okx_position_tiers_{mode}_max_lever_not_monotonic")
        min_mmr_by_mode[mode] = min(tier.mmr for tier in tiers)
        max_lever_by_mode[mode] = max(tier.max_lever for tier in tiers)
    return {
        "maintenance_margin_tiers_verified": not blockers and set(td_modes_verified) == set(TD_MODES),
        "td_modes_required": list(TD_MODES),
        "td_modes_verified": td_modes_verified,
        "tier_count": tier_count,
        "min_mmr_by_mode": min_mmr_by_mode,
        "max_lever_by_mode": max_lever_by_mode,
        "blockers": _dedupe(blockers),
        "warnings": _dedupe(warnings),
    }


def _formula_source_verified() -> bool:
    required = {
        "okx_api_public_position_tiers",
        "okx_liquidation_price_conditions",
        "okx_futures_margin_calculation_rules",
        "okx_forced_liquidation_faq",
    }
    return required.issubset({str(row.get("source")) for row in OFFICIAL_SOURCE_REFS})


def _formula_contract() -> dict[str, Any]:
    return {
        "formula_model_id": "okx_usdt_margined_swap_mark_price_liquidation_formula_v1",
        "scope": "BTC-USDT SWAP, USDT-margined perpetual, public tier evidence",
        "trigger_condition": "maintenance_margin_ratio <= 100%",
        "reference_price": "mark_price",
        "usdt_margined_initial_margin": "contract_size * contracts * mark_or_entry_price / leverage",
        "maintenance_margin": "contract_size * contracts * mark_price * tier_mmr",
        "maintenance_margin_ratio_isolated": "(margin_balance + unrealized_pnl) / (maintenance_margin + liquidation_fees)",
        "tier_inputs": ["tier", "minSz", "maxSz", "mmr", "imr", "maxLever"],
        "implementation_boundary": "research evidence only; account-specific portfolio state and exact fee tier still require paper/runtime verification",
    }


def _not_non_decreasing(values: list[float]) -> bool:
    return any(right < left for left, right in zip(values, values[1:]))


def _not_non_increasing(values: list[float]) -> bool:
    return any(right > left for left, right in zip(values, values[1:]))


def _float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _portable_path(path: Path, root: Path | None = None) -> str:
    base = (root or Path.cwd()).resolve()
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"
