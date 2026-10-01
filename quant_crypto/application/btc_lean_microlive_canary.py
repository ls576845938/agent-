"""Validate the supervised 10 USDT micro-live envelope without side effects."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from quant_crypto.oms.supervised_micro_live import (
    FALSE_SAFETY,
    MicroLiveApprovalProof,
    SupervisedMicroLiveAuthorization,
)
from quant_crypto.oms.okx_demo_paper_runtime import BTCDemoRuntimeDataBudget


FORBIDDEN_FIELD_TOKENS = (
    "api_key",
    "secret",
    "passphrase",
    "token",
    "signature",
    "authorization_header",
)


def build_micro_live_authorization_plan(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    safe_budget = BTCDemoRuntimeDataBudget()
    secret_paths = _forbidden_paths(payload)
    if secret_paths:
        return {
            "schema_version": "btc_lean_microlive_authorization_v1",
            "status": "blocked_fail_closed",
            "decision": "authorization_envelope_rejected",
            "authorization": {},
            "runtime_data_budget": _budget_report(safe_budget),
            "safety": dict(FALSE_SAFETY),
            "blockers": [
                "btc_lean_microlive:secret_like_fields_forbidden"
            ],
        }
    try:
        budget_raw = dict(payload.get("runtime_data_budget") or {})
        budget = BTCDemoRuntimeDataBudget(
            market_ring_window_minutes=int(
                budget_raw.get("market_ring_window_minutes") or 0
            ),
            market_ring_hard_cap_bytes=int(
                budget_raw.get("market_ring_hard_cap_bytes") or 0
            ),
            l2_disk_persistence_enabled=bool(
                budget_raw.get("l2_disk_persistence_enabled", False)
            ),
            sampled_event_types=tuple(
                str(value)
                for value in budget_raw.get("sampled_event_types", ())
            ),
            sampled_event_rolling_hard_cap_bytes=int(
                budget_raw.get("sampled_event_rolling_hard_cap_bytes") or 0
            ),
            runtime_warning_bytes=int(
                budget_raw.get("runtime_warning_bytes") or 0
            ),
            runtime_stop_raw_market_writes_bytes=int(
                budget_raw.get("runtime_stop_raw_market_writes_bytes") or 0
            ),
        )
        proof_raw = dict(payload.get("proof") or {})
        proof = MicroLiveApprovalProof(
            account_hash=str(proof_raw.get("account_hash") or ""),
            venue=str(proof_raw.get("venue") or ""),
            reviewer=str(proof_raw.get("reviewer") or ""),
            reviewed_at_utc=_parse_time(proof_raw.get("reviewed_at_utc")),
            approval_ticket=str(proof_raw.get("approval_ticket") or ""),
            permission_conclusion=str(
                proof_raw.get("permission_conclusion") or ""
            ),
            external_proof_id=str(proof_raw.get("external_proof_id") or ""),
            credential_namespace=str(
                proof_raw.get("credential_namespace") or ""
            ),
            withdraw_permission=bool(
                proof_raw.get("withdraw_permission", False)
            ),
        )
        authorization = SupervisedMicroLiveAuthorization(
            instrument_id=str(payload.get("instrument_id") or ""),
            margin_mode=str(payload.get("margin_mode") or ""),
            leverage=float(payload.get("leverage") or 0),
            max_notional_usdt=float(payload.get("max_notional_usdt") or 0),
            max_positions=int(payload.get("max_positions") or 0),
            max_active_orders=int(payload.get("max_active_orders") or 0),
            max_daily_loss_usdt=float(
                payload.get("max_daily_loss_usdt") or 0
            ),
            max_daily_new_orders=int(
                payload.get("max_daily_new_orders") or 0
            ),
            auto_start=bool(payload.get("auto_start", False)),
            auto_scale=bool(payload.get("auto_scale", False)),
            single_strategy_id=str(payload.get("single_strategy_id") or ""),
            manual_supervision_required=bool(
                payload.get("manual_supervision_required", False)
            ),
            proof=proof,
        )
    except (TypeError, ValueError) as exc:
        return {
            "schema_version": "btc_lean_microlive_authorization_v1",
            "status": "blocked_fail_closed",
            "decision": "authorization_envelope_invalid",
            "authorization": {},
            "runtime_data_budget": _budget_report(safe_budget),
            "safety": dict(FALSE_SAFETY),
            "blockers": [
                f"btc_lean_microlive:authorization_parse_failed:{type(exc).__name__}"
            ],
        }
    blockers = authorization.blockers()
    return {
        "schema_version": "btc_lean_microlive_authorization_v1",
        "status": "quality_checked_candidate" if not blockers else "blocked_fail_closed",
        "decision": (
            "authorization_envelope_valid_recording_only_no_auto_start"
            if not blockers
            else "authorization_envelope_blocked_fail_closed"
        ),
        "authorization": authorization.to_dict(),
        "runtime_data_budget": _budget_report(budget),
        "safety": dict(FALSE_SAFETY),
        "blockers": blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("btc_lean_microlive:authorization_not_object")
    report = build_micro_live_authorization_plan(raw)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        output = args.output.resolve()
        repo_root = args.repo_root.resolve()
        if _is_relative_to(output, repo_root):
            raise SystemExit("btc_lean_microlive:repo_local_output_forbidden")
        if not output.parent.is_dir():
            raise SystemExit("btc_lean_microlive:output_parent_missing")
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def _budget_report(budget: BTCDemoRuntimeDataBudget) -> dict[str, Any]:
    return {
        **budget.to_dict(),
        "runtime_total_hard_cap_bytes": (
            budget.runtime_stop_raw_market_writes_bytes
        ),
        "quota_can_delete_protected_state": False,
        "protected_state": [
            "order",
            "fill",
            "position",
            "cash",
            "funding",
            "ledger",
            "audit",
            "error",
            "checkpoint",
        ],
    }


def _forbidden_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            if any(token in name.casefold() for token in FORBIDDEN_FIELD_TOKENS):
                paths.append(path)
            paths.extend(_forbidden_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, f"{prefix}[{index}]"))
    return paths


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    main()
