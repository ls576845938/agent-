"""Versioned, account-scoped BTC drawdown and ledger replay facts.

The module is deliberately pure.  It does not discover an account, read a
runtime directory, or authorize an initial high-water mark.  A caller must
provide an explicitly reviewed baseline and complete cash-flow evidence for
each subsequent observation; otherwise the returned fact remains fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION = "btc_account_drawdown_fact_v1"
ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY = "explicit_reviewed_account_baseline_v1"
ACCOUNT_DRAWDOWN_SCOPE = "dedicated_demo_account"
ACCOUNT_DRAWDOWN_CURRENCY = "USDT"
ACCOUNT_DRAWDOWN_CASHFLOW_POLICY = "external_cashflow_must_be_complete_and_zero_v1"
ACCOUNT_FACTS_APPROVAL_SCHEMA_VERSION = "btc_account_facts_approval_v1"
ACCOUNT_FACTS_APPROVAL_REGISTRY_SCHEMA_VERSION = (
    "btc_account_facts_approval_registry_v1"
)
ACCOUNT_CASHFLOW_EVIDENCE_SCHEMA_VERSION = "btc_account_cashflow_evidence_v1"
REVIEWED_DRAWDOWN_POLICY_SCHEMA_VERSION = "btc_reviewed_drawdown_policy_v1"
ACCOUNT_FACTS_BASELINE_FRESHNESS_TTL_SECONDS = 30.0

# Bill classification is an exact pair, never a subtype-only guess.  The
# runtime already consumes normal trade and funding rows.  Exceptional account
# events remain unknown until separately reviewed against the venue contract.
_OKX_KNOWN_INTERNAL_BILL_TYPES = frozenset(
    {
        ("2", "1"),
        ("2", "2"),
        ("2", "3"),
        ("2", "4"),
        ("2", "5"),
        ("2", "6"),
        ("8", "173"),
        ("8", "174"),
    }
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AccountRiskFactError(ValueError):
    """Raised when an explicit engineering/account fact cannot be trusted."""


def reviewed_account_facts_approval_digest(value: Mapping[str, Any]) -> str:
    """Return the integrity digest for one externally reviewed record.

    The digest is not an approval.  Trust comes from the server-configured,
    external registry resolver; this only detects record mutation.
    """

    body = {
        key: item
        for key, item in dict(value).items()
        if key != "approval_digest"
    }
    return _digest(body)


def _validate_reviewed_drawdown_policy(value: Any) -> dict[str, str]:
    row = dict(value) if isinstance(value, Mapping) else {}
    if row.get("schema_version") != REVIEWED_DRAWDOWN_POLICY_SCHEMA_VERSION:
        raise AccountRiskFactError("approval_drawdown_policy_schema_mismatch")
    unit = str(row.get("unit") or "").strip().lower()
    if unit not in {"usdt", "ratio"}:
        raise AccountRiskFactError("approval_drawdown_policy_unit_invalid")
    threshold = _decimal(row.get("value"), name="drawdown_policy_value", positive=True)
    if unit == "ratio" and threshold > Decimal("1"):
        raise AccountRiskFactError("approval_drawdown_policy_value_invalid")
    return {
        "schema_version": REVIEWED_DRAWDOWN_POLICY_SCHEMA_VERSION,
        "value": _text(threshold),
        "unit": unit,
    }


def validate_reviewed_account_facts_approval(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one record already selected by a trusted resolver."""

    row = dict(value or {})
    if row.get("schema_version") != ACCOUNT_FACTS_APPROVAL_SCHEMA_VERSION:
        raise AccountRiskFactError("approval_schema_mismatch")
    if row.get("status") != "approved":
        raise AccountRiskFactError("approval_status_invalid")
    approval_id = str(row.get("approval_id") or "").strip()
    reviewer = str(row.get("reviewer_identity") or "").strip()
    ticket = str(row.get("approval_ticket") or "").strip()
    runtime_identity = str(row.get("runtime_identity") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,159}", approval_id):
        raise AccountRiskFactError("approval_id_invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{2,159}", reviewer):
        raise AccountRiskFactError("approval_reviewer_invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,159}", ticket):
        raise AccountRiskFactError("approval_ticket_invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,159}", runtime_identity):
        raise AccountRiskFactError("approval_runtime_identity_invalid")
    reviewed_at = _utc(
        row.get("reviewed_at_utc"),
        name="approval_reviewed_at_utc",
    )
    observed_at = _utc(
        row.get("observed_at_utc"),
        name="approval_observed_at_utc",
    )
    if reviewed_at < observed_at:
        raise AccountRiskFactError("approval_reviewed_before_observation")
    _identity(row.get("account_identity_hash"))
    _identity(row.get("snapshot_sha256"), name="snapshot_sha256")
    source_head = str(row.get("source_head") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        raise AccountRiskFactError("approval_source_head_invalid")
    if row.get("account_scope") != ACCOUNT_DRAWDOWN_SCOPE:
        raise AccountRiskFactError("approval_account_scope_invalid")
    if str(row.get("currency") or "").upper() != ACCOUNT_DRAWDOWN_CURRENCY:
        raise AccountRiskFactError("approval_currency_invalid")
    if row.get("history_complete") is not False:
        raise AccountRiskFactError("approval_history_complete_must_be_false")
    if row.get("baseline_authority") != ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY:
        raise AccountRiskFactError("approval_baseline_authority_invalid")
    flatness = row.get("flatness_evidence")
    if not isinstance(flatness, Mapping):
        raise AccountRiskFactError("approval_account_wide_flatness_unproven")
    required_flatness = {
        "schema_version": "btc_reviewed_account_flatness_v1",
        "scope": "dedicated_trading_account_account_wide",
        "positions_complete": True,
        "pending_orders_complete": True,
        "pending_algo_orders_complete": True,
        "pending_intents_complete": True,
    }
    if any(flatness.get(key) != expected for key, expected in required_flatness.items()):
        raise AccountRiskFactError("approval_account_wide_flatness_unproven")
    if str(flatness.get("snapshot_sha256") or "").lower() != str(
        row.get("snapshot_sha256") or ""
    ).lower():
        raise AccountRiskFactError("approval_flatness_snapshot_mismatch")
    _decimal(row.get("equity_usdt"), name="approval_equity_usdt", positive=True)
    if str(row.get("approval_digest") or "") != reviewed_account_facts_approval_digest(row):
        raise AccountRiskFactError("approval_digest_mismatch")
    policy = _validate_reviewed_drawdown_policy(row.get("drawdown_policy"))
    return {
        **row,
        "account_identity_hash": str(row["account_identity_hash"]).lower(),
        "currency": ACCOUNT_DRAWDOWN_CURRENCY,
        "source_head": source_head,
        "drawdown_policy": policy,
    }


def load_reviewed_account_facts_approval(
    *,
    registry_path: Path | str,
    approval_id: str,
    repo_root: Path | str,
) -> dict[str, Any]:
    """Resolve a review record only from a server-owned external registry."""

    path = Path(registry_path).expanduser().resolve()
    root = Path(repo_root).resolve()
    if path == root or root in path.parents:
        raise AccountRiskFactError("approval_registry_must_be_external")
    if not path.is_file():
        raise AccountRiskFactError("approval_registry_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AccountRiskFactError("approval_registry_invalid") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != ACCOUNT_FACTS_APPROVAL_REGISTRY_SCHEMA_VERSION:
        raise AccountRiskFactError("approval_registry_invalid")
    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise AccountRiskFactError("approval_registry_invalid")
    matches = [
        item
        for item in records
        if isinstance(item, Mapping)
        and str(item.get("approval_id") or "") == str(approval_id or "")
    ]
    if len(matches) != 1:
        raise AccountRiskFactError("approval_not_found_or_ambiguous")
    return validate_reviewed_account_facts_approval(matches[0])


def reviewed_drawdown_policy_from_approval(
    value: Mapping[str, Any],
) -> dict[str, str]:
    """Return a threshold only from a complete reviewed approval record."""

    return dict(validate_reviewed_account_facts_approval(value)["drawdown_policy"])


def _cashflow_unknown(
    *,
    account_identity_hash: Any,
    snapshot_sha256: Any,
    coverage_start_utc: Any,
    coverage_end_utc: Any,
    blockers: Sequence[str],
    amount_usdt: Decimal | None = None,
    page_count: int = 0,
    bill_count: int = 0,
) -> dict[str, Any]:
    document = {
        "schema_version": ACCOUNT_CASHFLOW_EVIDENCE_SCHEMA_VERSION,
        "status": "unknown",
        "complete": False,
        "account_identity_hash": str(account_identity_hash or "").lower(),
        "account_scope": ACCOUNT_DRAWDOWN_SCOPE,
        "currency": ACCOUNT_DRAWDOWN_CURRENCY,
        "snapshot_sha256": str(snapshot_sha256 or "").lower(),
        "coverage_start_utc": str(coverage_start_utc or ""),
        "coverage_end_utc": str(coverage_end_utc or ""),
        "amount_usdt": _text(amount_usdt) if amount_usdt is not None else None,
        "page_count": int(page_count),
        "bill_count": int(bill_count),
        "source": "okx_trading_account_bills_last_7_days",
        "history_scope": "since_reviewed_baseline_not_full_account_history",
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
    }
    document["evidence_digest"] = _digest(document)
    return document


def build_okx_account_cashflow_evidence(
    *,
    pages: Sequence[Mapping[str, Any]],
    account_identity_hash: Any,
    snapshot_sha256: Any,
    coverage_start_utc: Any,
    coverage_end_utc: Any,
    reference_time_utc: Any,
) -> dict[str, Any]:
    """Validate a bounded, newest-first OKX trading-account bills walk.

    ``after`` must advance toward older bill IDs and a full 100-row page must
    be followed until a short (including empty) terminal page is observed.
    The endpoint is intentionally unfiltered by instrument/type so transfers
    cannot disappear behind a query filter.
    """

    blockers: list[str] = []
    identity = str(account_identity_hash or "").strip().lower()
    snapshot = str(snapshot_sha256 or "").strip().lower()
    try:
        _identity(identity)
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
    try:
        _identity(snapshot, name="snapshot_sha256")
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
    try:
        start = _utc(coverage_start_utc, name="cashflow_coverage_start_utc")
        end = _utc(coverage_end_utc, name="cashflow_coverage_end_utc")
        reference = _utc(reference_time_utc, name="cashflow_reference_time_utc")
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
        start = end = reference = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if start > end:
        blockers.append("account_cashflow_coverage_window_invalid")
    if end > reference:
        blockers.append("account_cashflow_observation_from_future")
    if end - start > timedelta(days=7):
        blockers.append("account_cashflow_coverage_exceeds_okx_7d_window")
    if reference - start > timedelta(days=7):
        blockers.append("account_cashflow_coverage_outside_okx_7d_retention")
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)) or not pages:
        blockers.append("account_cashflow_pages_missing")
        normalized_pages: list[Mapping[str, Any]] = []
    else:
        normalized_pages = [item for item in pages if isinstance(item, Mapping)]
        if len(normalized_pages) != len(pages) or len(normalized_pages) > 128:
            blockers.append("account_cashflow_pages_invalid")

    begin_ms = str(int(start.timestamp() * 1000))
    end_ms = str(int(end.timestamp() * 1000))
    expected_after = ""
    seen_ids: set[str] = set()
    previous_ts: int | None = None
    amount = Decimal("0")
    external_count = 0
    bill_count = 0
    terminal_seen = False
    for index, page in enumerate(normalized_pages):
        request = page.get("request")
        rows_value = page.get("rows")
        if not isinstance(request, Mapping) or not isinstance(rows_value, Sequence) or isinstance(rows_value, (str, bytes)):
            blockers.append("account_cashflow_page_shape_invalid")
            continue
        request_keys = set(str(key) for key in request)
        allowed = {"begin", "end", "limit"} | ({"after"} if index else set())
        if request_keys != allowed:
            blockers.append("account_cashflow_query_filter_invalid")
        if (
            str(request.get("begin") or "") != begin_ms
            or str(request.get("end") or "") != end_ms
            or str(request.get("limit") or "") != "100"
            or str(request.get("after") or "") != expected_after
        ):
            blockers.append("account_cashflow_cursor_or_window_mismatch")
        rows = [row for row in rows_value if isinstance(row, Mapping)]
        if len(rows) != len(rows_value) or len(rows) > 100:
            blockers.append("account_cashflow_page_rows_invalid")
        if index < len(normalized_pages) - 1 and len(rows) < 100:
            blockers.append("account_cashflow_page_after_terminal")
        if len(rows) < 100:
            terminal_seen = True
            if index != len(normalized_pages) - 1:
                blockers.append("account_cashflow_page_after_terminal")
        for row in rows:
            bill_count += 1
            bill_id = str(row.get("billId") or row.get("bill_id") or "").strip()
            bill_type = str(row.get("type") or "").strip()
            subtype = str(row.get("subType") or row.get("sub_type") or "").strip()
            currency = str(row.get("ccy") or row.get("currency") or "").upper()
            timestamp_text = str(row.get("ts") or row.get("timestamp_ms") or "").strip()
            balance_change = row.get("balChg") if "balChg" in row else row.get("balance_change")
            if not bill_id or not bill_id.isdigit():
                blockers.append("account_bill_id_invalid")
            elif bill_id in seen_ids:
                blockers.append("account_bill_duplicate")
            else:
                seen_ids.add(bill_id)
            try:
                timestamp_ms = int(timestamp_text)
            except (TypeError, ValueError):
                timestamp_ms = -1
                blockers.append("account_bill_timestamp_invalid")
            if timestamp_ms < int(start.timestamp() * 1000) or timestamp_ms > int(end.timestamp() * 1000):
                blockers.append("account_bill_timestamp_outside_coverage")
            if previous_ts is not None and timestamp_ms > previous_ts:
                blockers.append("account_bills_not_newest_first")
            previous_ts = timestamp_ms
            if currency != ACCOUNT_DRAWDOWN_CURRENCY:
                blockers.append("account_bill_currency_mismatch")
            if balance_change in (None, ""):
                blockers.append("account_bill_balance_change_missing")
                change = Decimal("0")
            else:
                try:
                    change = _decimal(balance_change, name="account_bill_balance_change")
                except AccountRiskFactError:
                    blockers.append("account_bill_balance_change_invalid")
                    change = Decimal("0")
            if bill_type == "1" and subtype in {"11", "12"}:
                external_count += 1
                amount += change
            elif (
                not bill_type
                or not subtype
                or (bill_type, subtype) not in _OKX_KNOWN_INTERNAL_BILL_TYPES
            ):
                blockers.append("account_bill_type_unknown")
        if rows:
            expected_after = str(
                rows[-1].get("billId") or rows[-1].get("bill_id") or ""
            )
    if normalized_pages and len(normalized_pages[-1].get("rows") or []) >= 100:
        blockers.append("account_cashflow_terminal_page_missing")
    if not terminal_seen:
        blockers.append("account_cashflow_terminal_page_missing")
    if external_count:
        blockers.append("external_cashflow_activity_detected")
    if blockers:
        return _cashflow_unknown(
            account_identity_hash=identity,
            snapshot_sha256=snapshot,
            coverage_start_utc=_iso(start),
            coverage_end_utc=_iso(end),
            blockers=blockers,
            amount_usdt=amount,
            page_count=len(normalized_pages),
            bill_count=bill_count,
        )
    document = {
        "schema_version": ACCOUNT_CASHFLOW_EVIDENCE_SCHEMA_VERSION,
        "status": "complete_zero_external_cashflow",
        "complete": True,
        "account_identity_hash": identity,
        "account_scope": ACCOUNT_DRAWDOWN_SCOPE,
        "currency": ACCOUNT_DRAWDOWN_CURRENCY,
        "snapshot_sha256": snapshot,
        "coverage_start_utc": _iso(start),
        "coverage_end_utc": _iso(end),
        "amount_usdt": "0",
        "page_count": len(normalized_pages),
        "bill_count": bill_count,
        "source": "okx_trading_account_bills_last_7_days",
        "history_scope": "since_reviewed_baseline_not_full_account_history",
        "blockers": [],
    }
    document["evidence_digest"] = _digest(document)
    return document


def validate_account_cashflow_evidence(
    value: Mapping[str, Any],
    *,
    expected_account_identity_hash: str,
    expected_snapshot_sha256: str,
    expected_coverage_start_utc: Any,
    expected_coverage_end_utc: Any,
) -> dict[str, Any]:
    """Validate exact coverage binding before risk facts may consume it."""

    row = dict(value or {})
    if row.get("schema_version") != ACCOUNT_CASHFLOW_EVIDENCE_SCHEMA_VERSION:
        raise AccountRiskFactError("account_cashflow_evidence_schema_mismatch")
    if row.get("complete") is not True or row.get("status") != "complete_zero_external_cashflow":
        raise AccountRiskFactError("account_cashflow_evidence_incomplete")
    if row.get("blockers") != []:
        raise AccountRiskFactError("account_cashflow_evidence_blocked")
    supplied = str(row.get("evidence_digest") or "")
    body = {key: item for key, item in row.items() if key != "evidence_digest"}
    if supplied != _digest(body):
        raise AccountRiskFactError("account_cashflow_evidence_digest_mismatch")
    if str(row.get("account_identity_hash") or "") != str(expected_account_identity_hash or ""):
        raise AccountRiskFactError("account_cashflow_evidence_account_mismatch")
    if row.get("account_scope") != ACCOUNT_DRAWDOWN_SCOPE:
        raise AccountRiskFactError("account_cashflow_evidence_scope_mismatch")
    if str(row.get("currency") or "").upper() != ACCOUNT_DRAWDOWN_CURRENCY:
        raise AccountRiskFactError("account_cashflow_evidence_currency_mismatch")
    if str(row.get("snapshot_sha256") or "") != str(expected_snapshot_sha256 or ""):
        raise AccountRiskFactError("account_cashflow_evidence_snapshot_mismatch")
    if _iso(_utc(row.get("coverage_start_utc"), name="cashflow_coverage_start_utc")) != _iso(
        _utc(expected_coverage_start_utc, name="expected_cashflow_coverage_start_utc")
    ):
        raise AccountRiskFactError("account_cashflow_evidence_start_mismatch")
    if _iso(_utc(row.get("coverage_end_utc"), name="cashflow_coverage_end_utc")) != _iso(
        _utc(expected_coverage_end_utc, name="expected_cashflow_coverage_end_utc")
    ):
        raise AccountRiskFactError("account_cashflow_evidence_end_mismatch")
    if _decimal(row.get("amount_usdt"), name="external_cashflow_usdt") != 0:
        raise AccountRiskFactError("account_cashflow_evidence_nonzero")
    return row


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal(value: Any, *, name: str, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise AccountRiskFactError(f"{name}_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountRiskFactError(f"{name}_invalid") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise AccountRiskFactError(f"{name}_invalid")
    return number


def _text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _utc(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise AccountRiskFactError(f"{name}_invalid")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AccountRiskFactError(f"{name}_invalid") from exc
    if parsed.tzinfo is None:
        raise AccountRiskFactError(f"{name}_invalid")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _identity(value: Any, *, name: str = "account_identity_hash") -> str:
    text = str(value or "").strip().lower()
    if not _HEX64.fullmatch(text):
        raise AccountRiskFactError(f"{name}_invalid")
    return text


def _unknown(
    *,
    account_identity_hash: Any,
    account_scope: Any,
    currency: Any,
    snapshot_sha256: Any,
    observed_at_utc: Any,
    equity_usdt: Any,
    blockers: Sequence[str],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identity = str(account_identity_hash or "").strip().lower()
    snapshot = str(snapshot_sha256 or "").strip().lower()
    try:
        observed = _iso(_utc(observed_at_utc, name="observed_at_utc"))
    except AccountRiskFactError:
        observed = ""
    try:
        equity = _text(_decimal(equity_usdt, name="equity_usdt", positive=True))
    except AccountRiskFactError:
        equity = None
    prior = dict(previous or {})
    document = {
        "schema_version": ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION,
        "status": "unknown",
        "risk_eligible": False,
        "account_identity_hash": identity,
        "account_scope": str(account_scope or ""),
        "currency": str(currency or "").upper(),
        "snapshot_sha256": snapshot,
        "previous_snapshot_sha256": str(prior.get("snapshot_sha256") or ""),
        "observed_at_utc": observed,
        "coverage_start_utc": str(prior.get("coverage_start_utc") or ""),
        "baseline_authority": str(prior.get("baseline_authority") or ""),
        "baseline_event_sequence": prior.get("baseline_event_sequence"),
        "history_complete": False,
        "cashflow_policy": ACCOUNT_DRAWDOWN_CASHFLOW_POLICY,
        "external_cashflow_complete": False,
        "external_cashflow_usdt": None,
        "equity_usdt": equity,
        "baseline_equity_usdt": prior.get("baseline_equity_usdt"),
        "peak_equity_usdt": None,
        "drawdown_amount_usdt": None,
        "drawdown_ratio": None,
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
    }
    document["fact_digest"] = _digest(document)
    return document


def build_unknown_account_drawdown_fact(
    *,
    account_identity_hash: Any,
    account_scope: Any,
    currency: Any,
    snapshot_sha256: Any,
    observed_at_utc: Any,
    equity_usdt: Any,
    blockers: Sequence[str] = ("explicit_baseline_required",),
) -> dict[str, Any]:
    """Persist an observed-but-not-authoritative first account snapshot."""

    return _unknown(
        account_identity_hash=account_identity_hash,
        account_scope=account_scope,
        currency=currency,
        snapshot_sha256=snapshot_sha256,
        observed_at_utc=observed_at_utc,
        equity_usdt=equity_usdt,
        blockers=blockers,
    )


def build_explicit_account_drawdown_baseline(
    *,
    authority: Any,
    account_identity_hash: Any,
    account_scope: Any,
    currency: Any,
    snapshot_sha256: Any,
    observed_at_utc: Any,
    equity_usdt: Any,
    history_complete: bool,
    baseline_event_sequence: int = 0,
) -> dict[str, Any]:
    """Build the only accepted high-water baseline.

    This function does not grant runtime permission.  It encodes evidence that
    an external, reviewed process may later persist through the existing UOW.
    """

    if str(authority or "") != ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY:
        raise AccountRiskFactError("baseline_authority_invalid")
    if history_complete is not False:
        raise AccountRiskFactError("history_complete_must_be_false_for_since_baseline")
    if type(baseline_event_sequence) is not int or baseline_event_sequence < 0:
        raise AccountRiskFactError("baseline_event_sequence_invalid")
    identity = _identity(account_identity_hash)
    if str(account_scope or "") != ACCOUNT_DRAWDOWN_SCOPE:
        raise AccountRiskFactError("account_scope_invalid")
    if str(currency or "").upper() != ACCOUNT_DRAWDOWN_CURRENCY:
        raise AccountRiskFactError("currency_invalid")
    snapshot = _identity(snapshot_sha256, name="snapshot_sha256")
    observed = _utc(observed_at_utc, name="observed_at_utc")
    equity = _decimal(equity_usdt, name="equity_usdt", positive=True)
    document = {
        "schema_version": ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION,
        "status": "known_since_explicit_baseline",
        "risk_eligible": True,
        "account_identity_hash": identity,
        "account_scope": ACCOUNT_DRAWDOWN_SCOPE,
        "currency": ACCOUNT_DRAWDOWN_CURRENCY,
        "snapshot_sha256": snapshot,
        "previous_snapshot_sha256": "",
        "observed_at_utc": _iso(observed),
        "coverage_start_utc": _iso(observed),
        "baseline_authority": ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
        "baseline_event_sequence": baseline_event_sequence,
        "history_complete": False,
        "cashflow_policy": ACCOUNT_DRAWDOWN_CASHFLOW_POLICY,
        "external_cashflow_complete": True,
        "external_cashflow_usdt": "0",
        "equity_usdt": _text(equity),
        "baseline_equity_usdt": _text(equity),
        "peak_equity_usdt": _text(equity),
        "drawdown_amount_usdt": "0",
        "drawdown_ratio": "0",
        "blockers": [],
    }
    document["fact_digest"] = _digest(document)
    return document


def _valid_previous(previous: Mapping[str, Any]) -> bool:
    supplied = str(previous.get("fact_digest") or "")
    body = {key: value for key, value in previous.items() if key != "fact_digest"}
    return (
        previous.get("schema_version") == ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION
        and supplied == _digest(body)
        and previous.get("risk_eligible") is True
        and previous.get("baseline_authority") == ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY
    )


def advance_account_drawdown_fact(
    *,
    previous: Mapping[str, Any],
    account_identity_hash: Any,
    account_scope: Any,
    currency: Any,
    snapshot_sha256: Any,
    observed_at_utc: Any,
    reference_time_utc: Any,
    equity_usdt: Any,
    external_cashflow_complete: bool,
    external_cashflow_usdt: Any,
    freshness_ttl_seconds: float = 30.0,
) -> dict[str, Any]:
    """Advance a reviewed baseline without silently accepting cash flows."""

    blockers: list[str] = []
    prior = dict(previous or {})
    identity = str(account_identity_hash or "").strip().lower()
    scope = str(account_scope or "")
    resolved_currency = str(currency or "").upper()
    snapshot = str(snapshot_sha256 or "").strip().lower()
    if not _valid_previous(prior):
        blockers.append("previous_drawdown_fact_invalid")
    if identity != str(prior.get("account_identity_hash") or ""):
        blockers.append("account_identity_mismatch")
    if scope != str(prior.get("account_scope") or ""):
        blockers.append("account_scope_mismatch")
    if resolved_currency != str(prior.get("currency") or ""):
        blockers.append("currency_mismatch")
    if not _HEX64.fullmatch(snapshot):
        blockers.append("snapshot_sha256_invalid")
    try:
        observed = _utc(observed_at_utc, name="observed_at_utc")
        reference = _utc(reference_time_utc, name="reference_time_utc")
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
        observed = reference = datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        previous_observed = _utc(prior.get("observed_at_utc"), name="previous_observed_at_utc")
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
        previous_observed = observed
    if observed < previous_observed:
        blockers.append("observation_out_of_order")
    age = (reference - observed).total_seconds()
    if age < 0:
        blockers.append("observation_from_future")
    elif age > float(freshness_ttl_seconds):
        blockers.append("observation_stale")
    try:
        equity = _decimal(equity_usdt, name="equity_usdt", positive=True)
    except AccountRiskFactError as exc:
        blockers.append(str(exc))
        equity = Decimal("0")
    if external_cashflow_complete is not True:
        blockers.append("external_cashflow_unknown")
        external_flow = None
    else:
        try:
            external_flow = _decimal(
                external_cashflow_usdt,
                name="external_cashflow_usdt",
            )
        except AccountRiskFactError as exc:
            blockers.append(str(exc))
            external_flow = None
        if external_flow is not None and external_flow != 0:
            blockers.append("external_cashflow_nonzero")

    same_snapshot = snapshot == str(prior.get("snapshot_sha256") or "")
    same_timestamp = _iso(observed) == str(prior.get("observed_at_utc") or "")
    same_equity = _text(equity) == str(prior.get("equity_usdt") or "")
    same_observation = (
        same_snapshot
        and same_timestamp
        and same_equity
        and external_flow == Decimal("0")
    )
    if same_observation and not blockers:
        return prior
    # The canonical economic snapshot deliberately excludes capture time.  A
    # later poll may therefore have the same snapshot hash and equity.  It is
    # a new observation (and must get a new time-bound UOW), not a conflicting
    # reuse.  Same hash with changed economics, or same timestamp with changed
    # semantics, remains fail-closed.
    repeated_economics_at_later_time = (
        same_snapshot
        and observed > previous_observed
        and same_equity
        and external_flow == Decimal("0")
    )
    if same_snapshot and not repeated_economics_at_later_time:
        blockers.append("snapshot_idempotency_conflict")
    elif not same_snapshot and observed == previous_observed:
        blockers.append("observation_timestamp_conflict")
    if blockers:
        return _unknown(
            account_identity_hash=identity,
            account_scope=scope,
            currency=resolved_currency,
            snapshot_sha256=snapshot,
            observed_at_utc=observed,
            equity_usdt=equity,
            blockers=blockers,
            previous=prior,
        )

    peak = _decimal(prior.get("peak_equity_usdt"), name="peak_equity_usdt", positive=True)
    peak = max(peak, equity)
    amount = max(peak - equity, Decimal("0"))
    ratio = amount / peak
    document = {
        "schema_version": ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION,
        "status": "known_since_explicit_baseline",
        "risk_eligible": True,
        "account_identity_hash": identity,
        "account_scope": scope,
        "currency": resolved_currency,
        "snapshot_sha256": snapshot,
        "previous_snapshot_sha256": str(prior.get("snapshot_sha256") or ""),
        "observed_at_utc": _iso(observed),
        "coverage_start_utc": str(prior.get("coverage_start_utc") or ""),
        "baseline_authority": ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY,
        "baseline_event_sequence": prior.get("baseline_event_sequence"),
        "history_complete": False,
        "cashflow_policy": ACCOUNT_DRAWDOWN_CASHFLOW_POLICY,
        "external_cashflow_complete": True,
        "external_cashflow_usdt": "0",
        "equity_usdt": _text(equity),
        "baseline_equity_usdt": str(prior.get("baseline_equity_usdt") or ""),
        "peak_equity_usdt": _text(peak),
        "drawdown_amount_usdt": _text(amount),
        "drawdown_ratio": _text(ratio),
        "blockers": [],
    }
    document["fact_digest"] = _digest(document)
    return document


def resolve_drawdown_metric(
    fact: Mapping[str, Any],
    *,
    expected_account_identity_hash: str,
    expected_snapshot_sha256: str,
    expected_observed_at_utc: Any,
    unit: str,
) -> Decimal:
    """Resolve one explicitly selected metric from a fully bound fact."""

    if not _valid_previous(fact) or fact.get("risk_eligible") is not True:
        raise AccountRiskFactError("drawdown_fact_unknown")
    if str(fact.get("account_identity_hash") or "") != str(expected_account_identity_hash or ""):
        raise AccountRiskFactError("drawdown_fact_account_identity_mismatch")
    if str(fact.get("snapshot_sha256") or "") != str(expected_snapshot_sha256 or ""):
        raise AccountRiskFactError("drawdown_fact_snapshot_mismatch")
    try:
        fact_observed = _iso(
            _utc(fact.get("observed_at_utc"), name="fact_observed_at_utc")
        )
    except AccountRiskFactError as exc:
        raise AccountRiskFactError("drawdown_fact_observation_invalid") from exc
    try:
        expected_observed = _iso(
            _utc(expected_observed_at_utc, name="expected_observed_at_utc")
        )
    except AccountRiskFactError as exc:
        raise AccountRiskFactError("expected_drawdown_observation_invalid") from exc
    if fact_observed != expected_observed:
        raise AccountRiskFactError("drawdown_fact_observation_mismatch")
    selected = str(unit or "").lower()
    if selected == "usdt":
        return _decimal(fact.get("drawdown_amount_usdt"), name="drawdown_amount_usdt")
    if selected == "ratio":
        return _decimal(fact.get("drawdown_ratio"), name="drawdown_ratio")
    raise AccountRiskFactError("max_drawdown_unit_unknown")


def replay_account_ledger_uows(
    *,
    uow_payloads: Sequence[Mapping[str, Any]],
    baseline_equity_usdt: Any,
    baseline_observed_at_utc: Any,
    final_observed_at_utc: Any,
    final_exchange_snapshot: Mapping[str, Any],
    currency: str,
) -> dict[str, Any]:
    """Independently recompute a flat-baseline linear-perp ledger.

    The replay consumes committed UOW payloads, deduplicates fills/funding by
    their own IDs, includes only economics strictly after the reviewed
    baseline and through the final observation, converts contracts through
    ``ctVal``, and compares the result with a separately supplied final
    exchange snapshot.  Historical rows may remain in the raw venue snapshot;
    they are not rewritten and are not charged a second time.
    """

    if str(currency or "").upper() != ACCOUNT_DRAWDOWN_CURRENCY:
        raise AccountRiskFactError("currency_invalid")
    baseline = _decimal(baseline_equity_usdt, name="baseline_equity_usdt", positive=True)
    baseline_time = _utc(
        baseline_observed_at_utc,
        name="baseline_observed_at_utc",
    )
    final_time = _utc(final_observed_at_utc, name="final_observed_at_utc")
    if final_time < baseline_time:
        raise AccountRiskFactError("ledger_replay_window_invalid")
    baseline_ms = int(baseline_time.timestamp() * 1000)
    final_ms = int(final_time.timestamp() * 1000)

    def in_replay_window(row: Mapping[str, Any], *, kind: str) -> bool:
        raw = str(row.get("timestamp_ms") or "").strip()
        if not raw or not raw.isdigit():
            raise AccountRiskFactError(f"{kind}_timestamp_invalid")
        observed_ms = int(raw)
        if observed_ms > final_ms:
            raise AccountRiskFactError(f"{kind}_timestamp_after_observation")
        return observed_ms > baseline_ms

    fills: dict[str, dict[str, Any]] = {}
    bills: dict[str, dict[str, Any]] = {}
    contract_value: Decimal | None = None
    for raw in uow_payloads:
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
        risk = payload.get("risk_context") if isinstance(payload.get("risk_context"), Mapping) else {}
        venue = risk.get("venue_rules") if isinstance(risk.get("venue_rules"), Mapping) else {}
        candidate_ct = _decimal(venue.get("contract_value_btc"), name="contract_value_btc", positive=True)
        if contract_value is None:
            contract_value = candidate_ct
        elif contract_value != candidate_ct:
            raise AccountRiskFactError("contract_value_mismatch")
        for row in payload.get("fill_ledger", []):
            if not isinstance(row, Mapping):
                raise AccountRiskFactError("fill_row_invalid")
            if not in_replay_window(row, kind="fill"):
                continue
            fill_id = str(row.get("fill_id") or "")
            if not fill_id:
                raise AccountRiskFactError("fill_id_missing")
            normalized = dict(row)
            existing = fills.get(fill_id)
            if existing is not None and _digest(existing) != _digest(normalized):
                raise AccountRiskFactError("fill_idempotency_conflict")
            fills[fill_id] = normalized
        funding = payload.get("funding_ledger") if isinstance(payload.get("funding_ledger"), Mapping) else {}
        for row in funding.get("bills", []):
            if not isinstance(row, Mapping):
                raise AccountRiskFactError("funding_bill_invalid")
            if not in_replay_window(row, kind="funding_bill"):
                continue
            bill_id = str(row.get("bill_id") or "")
            if not bill_id:
                raise AccountRiskFactError("funding_bill_id_missing")
            normalized = dict(row)
            existing = bills.get(bill_id)
            if existing is not None and _digest(existing) != _digest(normalized):
                raise AccountRiskFactError("funding_bill_idempotency_conflict")
            bills[bill_id] = normalized
    if contract_value is None:
        raise AccountRiskFactError("contract_value_missing")

    position_btc = Decimal("0")
    trade_cashflow = Decimal("0")
    fee_cashflow = Decimal("0")
    for row in sorted(fills.values(), key=lambda item: (str(item.get("timestamp_ms") or ""), str(item.get("fill_id") or ""))):
        side = str(row.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            raise AccountRiskFactError("fill_side_invalid")
        contracts = _decimal(row.get("size"), name="fill_size", positive=True)
        price = _decimal(row.get("price"), name="fill_price", positive=True)
        quantity_btc = contracts * contract_value
        signed = quantity_btc if side == "buy" else -quantity_btc
        position_btc += signed
        trade_cashflow -= signed * price
        if str(row.get("fee_currency") or ACCOUNT_DRAWDOWN_CURRENCY).upper() != ACCOUNT_DRAWDOWN_CURRENCY:
            raise AccountRiskFactError("fill_fee_currency_mismatch")
        fee_cashflow += _decimal(row.get("fee"), name="fill_fee")

    funding_cashflow = Decimal("0")
    for row in bills.values():
        if row.get("balance_change_observed") is not True:
            raise AccountRiskFactError("funding_cashflow_unknown")
        if str(row.get("currency") or "").upper() != ACCOUNT_DRAWDOWN_CURRENCY:
            raise AccountRiskFactError("funding_currency_mismatch")
        funding_cashflow += _decimal(row.get("balance_change"), name="funding_cashflow")

    mark_container = final_exchange_snapshot.get("mark") if isinstance(final_exchange_snapshot.get("mark"), Mapping) else {}
    mark = _decimal(mark_container.get("mark_price"), name="valuation_mark_price", positive=True)
    position_value = position_btc * mark
    price_pnl = trade_cashflow + position_value
    final_equity = baseline + price_pnl + fee_cashflow + funding_cashflow
    balance = final_exchange_snapshot.get("balance") if isinstance(final_exchange_snapshot.get("balance"), Mapping) else {}
    observed_equity = _decimal(balance.get("equity_usdt"), name="final_equity_usdt", positive=True)
    if final_equity != observed_equity:
        raise AccountRiskFactError("equity_reconciliation_mismatch")
    observed_contracts = Decimal("0")
    for row in final_exchange_snapshot.get("positions", []):
        if not isinstance(row, Mapping):
            raise AccountRiskFactError("position_row_invalid")
        quantity = _decimal(row.get("contracts"), name="position_contracts")
        side = str(row.get("position_side") or "").lower()
        if side == "short":
            quantity = -abs(quantity)
        elif side == "long":
            quantity = abs(quantity)
        elif quantity != 0:
            raise AccountRiskFactError("position_side_invalid")
        observed_contracts += quantity
    replay_contracts = position_btc / contract_value
    if replay_contracts != observed_contracts:
        raise AccountRiskFactError("position_reconciliation_mismatch")
    return {
        "schema_version": "btc_account_ledger_replay_v1",
        "reconciled": True,
        "currency": ACCOUNT_DRAWDOWN_CURRENCY,
        "baseline_observed_at_utc": _iso(baseline_time),
        "final_observed_at_utc": _iso(final_time),
        "fill_count": len(fills),
        "funding_bill_count": len(bills),
        "contract_value_btc": _text(contract_value),
        "position_contracts": _text(replay_contracts),
        "position_btc": _text(position_btc),
        "price_pnl_usdt": _text(price_pnl),
        "fee_cashflow_usdt": _text(fee_cashflow),
        "funding_cashflow_usdt": _text(funding_cashflow),
        "final_equity_usdt": _text(final_equity),
        "observed_equity_usdt": _text(observed_equity),
        "source": "committed_ledger_uow_payloads_plus_independent_final_snapshot",
    }


__all__ = [
    "ACCOUNT_CASHFLOW_EVIDENCE_SCHEMA_VERSION",
    "ACCOUNT_DRAWDOWN_BASELINE_AUTHORITY",
    "ACCOUNT_DRAWDOWN_FACT_SCHEMA_VERSION",
    "ACCOUNT_FACTS_APPROVAL_REGISTRY_SCHEMA_VERSION",
    "ACCOUNT_FACTS_APPROVAL_SCHEMA_VERSION",
    "ACCOUNT_FACTS_BASELINE_FRESHNESS_TTL_SECONDS",
    "REVIEWED_DRAWDOWN_POLICY_SCHEMA_VERSION",
    "AccountRiskFactError",
    "advance_account_drawdown_fact",
    "build_explicit_account_drawdown_baseline",
    "build_okx_account_cashflow_evidence",
    "build_unknown_account_drawdown_fact",
    "load_reviewed_account_facts_approval",
    "replay_account_ledger_uows",
    "reviewed_account_facts_approval_digest",
    "reviewed_drawdown_policy_from_approval",
    "resolve_drawdown_metric",
    "validate_account_cashflow_evidence",
    "validate_reviewed_account_facts_approval",
]
