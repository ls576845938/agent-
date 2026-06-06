#!/usr/bin/env python3
"""Build a machine-readable BTC manual public metadata capture packet."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.build_btc_manual_metadata_capture_readiness_report import (
        POST_CAPTURE_IMPORT_COMMAND,
        POST_CAPTURE_REBUILD_READINESS_COMMAND,
        POST_CAPTURE_STRICT_VALIDATE_COMMAND,
        POST_CAPTURE_VALIDATE_COMMAND,
        build_btc_manual_metadata_capture_readiness_report,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by direct script invocation
    from build_btc_manual_metadata_capture_readiness_report import (
        POST_CAPTURE_IMPORT_COMMAND,
        POST_CAPTURE_REBUILD_READINESS_COMMAND,
        POST_CAPTURE_STRICT_VALIDATE_COMMAND,
        POST_CAPTURE_VALIDATE_COMMAND,
        build_btc_manual_metadata_capture_readiness_report,
    )


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_data_status/latest")
DEFAULT_CAPTURE_ATTEMPT = Path("artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json")
DEFAULT_READINESS = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json")
DEFAULT_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
FEE_TIER_SOURCE = "manual_public_okx_swap_fee_schedule"
FEE_TIER_SOURCE_URL_OR_DOC = "https://www.okx.com/en-us/fees"
PAPER_GATE_MANUAL_INPUTS_DRY_RUN_COMMAND = (
    "make dry-run-btc-paper-gate-manual-inputs "
    "EXCHANGE_INFO_RAW=exchange_info_raw.json "
    "FUNDING_INFO_RAW=funding_info_raw.json "
    "EXCHANGE_INFO_HTTP_STATUS=exchange_info_http_status.txt "
    "FUNDING_INFO_HTTP_STATUS=funding_info_http_status.txt "
    "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_METADATA_CAPTURE_TIME> "
    "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS> "
    "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS> "
    f"BTC_FEE_TIER_SOURCE={FEE_TIER_SOURCE} "
    f"BTC_FEE_TIER_SOURCE_URL_OR_DOC={FEE_TIER_SOURCE_URL_OR_DOC} "
    "BTC_FEE_TIER_CAPTURED_AT=<UTC_FEE_CAPTURE_TIME>"
)
PAPER_GATE_MANUAL_INPUTS_APPLY_COMMAND = PAPER_GATE_MANUAL_INPUTS_DRY_RUN_COMMAND.replace(
    "make dry-run-btc-paper-gate-manual-inputs",
    "make apply-btc-paper-gate-manual-inputs",
    1,
)
PAPER_GATE_MANUAL_INPUTS_APPLY_AND_VALIDATE_COMMAND = PAPER_GATE_MANUAL_INPUTS_DRY_RUN_COMMAND.replace(
    "make dry-run-btc-paper-gate-manual-inputs",
    "make apply-and-validate-btc-paper-gate-manual-inputs",
    1,
)


def build_btc_manual_metadata_capture_operator_packet(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    attempt = _read_json(root / DEFAULT_CAPTURE_ATTEMPT)
    readiness = _read_json(root / DEFAULT_READINESS)
    cost_model = _read_json(root / DEFAULT_COST_MODEL)
    last_status = _mapping(readiness.get("last_public_metadata_capture_status"))
    exchange = _mapping(readiness.get("exchange_info"))
    funding = _mapping(readiness.get("funding_info"))
    exchange_url = str(exchange.get("source_url") or "https://fapi.binance.com/fapi/v1/exchangeInfo")
    funding_url = str(funding.get("source_url") or "https://fapi.binance.com/fapi/v1/fundingInfo")
    fee_tier_status = _fee_tier_status(cost_model, root=root)
    required_inputs = _required_manual_inputs(exchange=exchange, funding=funding, fee_tier_status=fee_tier_status)
    manual_inputs_complete = all(item["status"] == "verified" for item in required_inputs)
    blockers = _dedupe(
        [
            *([] if manual_inputs_complete else _list_of_strings(attempt.get("blockers"))),
            *_list_of_strings(readiness.get("blockers")),
            *_list_of_strings(fee_tier_status.get("fee_blockers")),
        ]
    )
    post_capture_commands = _operator_post_capture_commands(
        _list_of_strings(readiness.get("post_capture_commands")),
        blockers_present=bool(blockers),
        root=root,
    )
    import_command = post_capture_commands[0] if post_capture_commands else ""
    return {
        "schema_version": "btc_manual_metadata_capture_operator_packet_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "status": "awaiting_manual_capture" if blockers else "metadata_verified",
        "symbol": "BTCUSDT",
        "capture_attempt_report": _relpath(root / DEFAULT_CAPTURE_ATTEMPT, root)
        if (root / DEFAULT_CAPTURE_ATTEMPT).exists()
        else None,
        "readiness_report": _relpath(root / DEFAULT_READINESS, root) if (root / DEFAULT_READINESS).exists() else None,
        "last_public_metadata_capture_status": {
            "status": str(attempt.get("status") or last_status.get("status") or "missing"),
            "network_called": bool(attempt.get("network_called", last_status.get("network_called", False))),
            "exchange_info_http_status": _endpoint_http_status(attempt, "exchange_info", last_status),
            "funding_info_http_status": _endpoint_http_status(attempt, "funding_info", last_status),
            "next_required_action": str(
                attempt.get("next_required_action")
                or last_status.get("next_required_action")
                or "manual_capture_from_allowed_network"
            ),
        },
        "operator_action": "manual_capture_from_allowed_network" if blockers else "no_manual_capture_required",
        "manual_inputs_status": "manual_inputs_verified" if manual_inputs_complete else "awaiting_manual_inputs",
        "paper_gate_manual_inputs_complete": bool(manual_inputs_complete),
        "required_manual_inputs": required_inputs,
        "capture_requests": [
            {
                "name": "exchange_info",
                "required_for": "exchange_info_verification",
                "method": "GET",
                "endpoint": str(exchange.get("allowed_endpoint") or "GET /fapi/v1/exchangeInfo"),
                "url": exchange_url,
                "output_file": "exchange_info_raw.json",
                "http_status_file": "exchange_info_http_status.txt",
                "command": _curl_capture_command(
                    output_file="exchange_info_raw.json",
                    url=exchange_url,
                    status_file="exchange_info_http_status.txt",
                ),
                "sha256_command": "sha256sum exchange_info_raw.json",
                "size_command": "wc -c exchange_info_raw.json",
                "http_status_command": "cat exchange_info_http_status.txt",
                "required_http_status": 200,
                "empty_response_allowed": False,
            },
            {
                "name": "funding_info",
                "required_for": "funding_info_endpoint_verification",
                "method": "GET",
                "endpoint": str(funding.get("allowed_endpoint") or "GET /fapi/v1/fundingInfo"),
                "url": funding_url,
                "output_file": "funding_info_raw.json",
                "http_status_file": "funding_info_http_status.txt",
                "command": _curl_capture_command(
                    output_file="funding_info_raw.json",
                    url=funding_url,
                    status_file="funding_info_http_status.txt",
                ),
                "sha256_command": "sha256sum funding_info_raw.json",
                "size_command": "wc -c funding_info_raw.json",
                "http_status_command": "cat funding_info_http_status.txt",
                "required_http_status": 200,
                "empty_response_allowed": bool(funding.get("empty_response_allowed", True)),
            },
        ],
        "fee_tier_status": fee_tier_status,
        "fee_tier_overlay_request": {
            "name": "fee_tier_overlay",
            "required_for": "maker_taker_fee_tier_verification",
            "source_url_or_doc": FEE_TIER_SOURCE_URL_OR_DOC,
            "output_file": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json",
            "dry_run_report": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_dry_run_report.json",
            "import_report": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
            "dry_run_command": (
                "make dry-run-btc-fee-tier-overlay-import "
                "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS> "
                "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS> "
                f"BTC_FEE_TIER_SOURCE={FEE_TIER_SOURCE} "
                f"BTC_FEE_TIER_SOURCE_URL_OR_DOC={FEE_TIER_SOURCE_URL_OR_DOC} "
                "BTC_FEE_TIER_CAPTURED_AT=<UTC_CAPTURE_TIME>"
            ),
            "import_command": (
                "make apply-btc-fee-tier-overlay-import "
                "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS> "
                "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS> "
                f"BTC_FEE_TIER_SOURCE={FEE_TIER_SOURCE} "
                f"BTC_FEE_TIER_SOURCE_URL_OR_DOC={FEE_TIER_SOURCE_URL_OR_DOC} "
                "BTC_FEE_TIER_CAPTURED_AT=<UTC_CAPTURE_TIME>"
            ),
            "post_import_rebuild_command": POST_CAPTURE_REBUILD_READINESS_COMMAND,
            "post_import_validation_command": "make validate-btc-evidence",
        },
        "paper_gate_manual_inputs_request": {
            "name": "paper_gate_manual_inputs",
            "required_for": "btc_paper_readiness_manual_input_gate",
            "dry_run_command": PAPER_GATE_MANUAL_INPUTS_DRY_RUN_COMMAND,
            "apply_command": PAPER_GATE_MANUAL_INPUTS_APPLY_COMMAND,
            "apply_and_validate_command": PAPER_GATE_MANUAL_INPUTS_APPLY_AND_VALIDATE_COMMAND,
            "post_apply_rebuild_command": POST_CAPTURE_REBUILD_READINESS_COMMAND,
            "post_apply_validation_command": "make validate-btc-evidence",
            "post_apply_readiness_command": "make check-btc-paper-validation-readiness",
        },
        "post_capture_dry_run_import_command": _dry_run_import_command(import_command),
        "post_capture_import_command": import_command,
        "post_import_validation_commands": post_capture_commands[1:],
        "acceptance_checks": [
            "exchange_info_raw.json contains BTCUSDT PERPETUAL TRADING symbol metadata",
            "exchangeInfo includes PRICE_FILTER.tickSize, LOT_SIZE.stepSize, LOT_SIZE.minQty, and MIN_NOTIONAL",
            "funding_info_raw.json is the raw public endpoint array response; an empty array is allowed",
            "non-empty funding_info_raw.json arrays must contain JSON objects",
            "non-empty fundingInfo rows must include symbol; a BTCUSDT row must include fundingIntervalHours and adjusted cap/floor",
            "funding_info_raw.json must not be an error object with code/msg or error fields",
            "exchange_info_http_status.txt and funding_info_http_status.txt both contain 200",
            "BTC_MANUAL_METADATA_CAPTURED_AT is the actual UTC capture time and is not omitted",
            "BTC_MANUAL_METADATA_CAPTURED_AT must not be in the future relative to import time",
            "record sha256sum and byte size for exchange_info_raw.json and funding_info_raw.json before import",
            "exchange_info_raw.json and funding_info_raw.json are distinct files",
            "raw capture files are kept outside the selected bundle directory",
            "atomic importer writes no bundle metadata unless both contracts verify",
            "dry-run import report is written separately from artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
            "write-capable manual import report is written to artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
            "manual metadata import report exchange_info_output_sha256 must match selected bundle exchange_info.json",
            "manual metadata import report funding_info_output_sha256 must match selected bundle funding_info.json",
            "BTC_FEE_TIER_MAKER_BPS and BTC_FEE_TIER_TAKER_BPS must come from a public USD-M fee schedule capture",
            "BTC_FEE_TIER_CAPTURED_AT is the actual UTC fee schedule capture time and is not omitted",
            "dry-run fee tier import report is written separately from artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
            "write-capable fee tier import report is written to artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
            "fee tier import report overlay_payload_sha256 must match artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json",
        ],
        "safety": {
            "api_key_required": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "writes_bundle_files_during_capture": False,
            "strategy_retest_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "forbidden_endpoint_families": _forbidden_endpoint_families(),
        },
        "blockers": blockers,
    }


def write_btc_manual_metadata_capture_operator_packet(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_manual_metadata_capture_operator_packet.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_manual_metadata_capture_operator_packet(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_manual_metadata_capture_operator_packet(payload, Path(args.output_root)))


def _endpoint_http_status(payload: Mapping[str, Any], name: str, fallback: Mapping[str, Any]) -> object:
    endpoint_results = payload.get("endpoint_results", {}) if isinstance(payload.get("endpoint_results"), Mapping) else {}
    result = endpoint_results.get(name, {}) if isinstance(endpoint_results.get(name), Mapping) else {}
    key = f"{name}_http_status"
    return result.get("http_status", fallback.get(key))


def _dry_run_import_command(command: str) -> str:
    if not command:
        return ""
    if "make apply-btc-manual-metadata-import" in command:
        return command.replace("make apply-btc-manual-metadata-import", "make dry-run-btc-manual-metadata-import", 1)
    if " --dry-run" in command or command.endswith(" --dry-run"):
        return command
    marker = " --operator-note "
    if marker in command:
        return command.replace(marker, " --dry-run" + marker, 1)
    return command + " --dry-run"


def _fee_tier_status(cost_model: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    cost_model_report = root / DEFAULT_COST_MODEL
    fee_model = _mapping(cost_model.get("fee_model"))
    fee_blockers = _dedupe(
        [
            *(["btc_cost_model_report_missing"] if not cost_model_report.exists() else []),
            *_list_of_strings(fee_model.get("fee_blockers")),
            *[
                str(item)
                for item in _list_of_strings(cost_model.get("blockers"))
                if "fee_tier" in str(item) or "maker_taker_fee" in str(item)
            ],
        ]
    )
    verified = bool(fee_model.get("fee_tier_verified", False))
    return {
        "cost_model_report": _relpath(cost_model_report, root) if cost_model_report.exists() else None,
        "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
        "fee_tier_verified": verified,
        "manual_capture_required": not verified,
        "maker_fee_bps": _float_or_none(fee_model.get("maker_fee_bps")),
        "taker_fee_bps": _float_or_none(fee_model.get("taker_fee_bps")),
        "fee_tier_overlay": fee_model.get("fee_tier_overlay"),
        "fee_tier_import_report": fee_model.get("fee_tier_import_report"),
        "fee_tier_import_report_verified": bool(fee_model.get("fee_tier_import_report_verified", False)),
        "fee_blockers": fee_blockers,
    }


def _required_manual_inputs(
    *,
    exchange: Mapping[str, Any],
    funding: Mapping[str, Any],
    fee_tier_status: Mapping[str, Any],
) -> list[dict[str, Any]]:
    exchange_verified = bool(exchange.get("verified", False))
    funding_verified = bool(funding.get("verified", False))
    fee_verified = bool(fee_tier_status.get("fee_tier_verified", False))
    return [
        {
            "name": "exchange_info",
            "required_for": "exchange_info_verification",
            "status": "verified" if exchange_verified else "awaiting_capture",
            "action": "none" if exchange_verified else "manual_capture_from_allowed_network",
            "blockers": _list_of_strings(exchange.get("blockers")),
        },
        {
            "name": "funding_info",
            "required_for": "funding_info_endpoint_verification",
            "status": "verified" if funding_verified else "awaiting_capture",
            "action": "none" if funding_verified else "manual_capture_from_allowed_network",
            "blockers": _list_of_strings(funding.get("blockers")),
        },
        {
            "name": "fee_tier_overlay",
            "required_for": "maker_taker_fee_tier_verification",
            "status": "verified" if fee_verified else "awaiting_capture",
            "action": "none" if fee_verified else "capture_public_fee_schedule_and_import",
            "blockers": _list_of_strings(fee_tier_status.get("fee_blockers")),
        },
    ]


def _forbidden_endpoint_families() -> list[str]:
    return [
        "account",
        "order",
        "trade",
        "position",
        "listenKey",
        "userData",
        "leverage",
        "margin",
        "transfer",
        "broker",
        "income",
        "balance",
        "withdrawal",
    ]


def _operator_post_capture_commands(commands: list[str], *, blockers_present: bool, root: Path) -> list[str]:
    if not blockers_present and not commands:
        return []
    if not commands:
        return _canonical_post_capture_commands(root)
    if "EXCHANGE_INFO_HTTP_STATUS=" not in commands[0] or "FUNDING_INFO_HTTP_STATUS=" not in commands[0]:
        return _canonical_post_capture_commands(root)
    if len(commands) >= 5 and commands[1].startswith("python3 scripts/build_btc_perpetual_data_bundle_manifest.py"):
        return [
            commands[0],
            commands[1],
            POST_CAPTURE_VALIDATE_COMMAND,
            POST_CAPTURE_STRICT_VALIDATE_COMMAND,
            POST_CAPTURE_REBUILD_READINESS_COMMAND,
        ]
    return _canonical_post_capture_commands(root)


def _canonical_post_capture_commands(root: Path) -> list[str]:
    readiness = build_btc_manual_metadata_capture_readiness_report(repo_root=root)
    commands = _list_of_strings(readiness.get("post_capture_commands"))
    if len(commands) >= 5:
        return commands[:5]
    return [POST_CAPTURE_IMPORT_COMMAND, "", POST_CAPTURE_VALIDATE_COMMAND, POST_CAPTURE_STRICT_VALIDATE_COMMAND, POST_CAPTURE_REBUILD_READINESS_COMMAND]


def _curl_capture_command(*, output_file: str, url: str, status_file: str) -> str:
    return f'curl -sS -o {output_file} -w "%{{http_code}}\\n" "{url}" > {status_file}'


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
