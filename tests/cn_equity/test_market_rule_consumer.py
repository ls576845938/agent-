from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from quant_cn.application.market_semantics_preflight import (
    run_market_semantics_preflight,
)
from quant_cn.data.market_rule_consumer import (
    BOARD_LOT,
    BUNDLE_FILE,
    BUNDLE_SCHEMA,
    CN_MARKET_RULE_FILE_EMPTY,
    CN_MARKET_RULE_HANDOFF_INVALID,
    CN_MARKET_RULE_HANDOFF_MISSING,
    CN_MARKET_RULE_MANIFEST_MISSING,
    CN_MARKET_RULE_PIT_BRIDGE_INCOMPLETE,
    CN_MARKET_RULE_SOURCE_NOT_FORMAL,
    DATASET_ID,
    FEE_SCHEDULE,
    PRICE_LIMIT,
    SELLABILITY,
    SESSION,
    SETTLEMENT,
    consume_cn_market_rule_bundle,
)
from quant_cn.market.rules import MarketDimensions
from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    aggregate_inventory_hash,
    build_manifest,
)


EVALUATED = datetime(2026, 7, 24, 2, 0, tzinfo=timezone.utc)
VERSION = "cn-market-rule-fixture-v1"
SHA = "a" * 64


def _dimensions() -> dict[str, object]:
    return {
        "board": "main",
        "instrument": "cash_equity",
        "security_id": None,
        "security_scope": "all_matching_listed_securities",
        "security_type": "common_stock",
        "venue": "XSHG",
    }


def _metadata(kind: str, path: str, raw: bytes) -> dict[str, object]:
    return {
        "available_time": "2026-07-23T00:00:00Z",
        "checksum": hashlib.sha256(f"record:{kind}".encode()).hexdigest(),
        "dimension_evidence_complete": True,
        "dimensions": _dimensions(),
        "effective_from": "2026-07-24T00:00:00Z",
        "effective_to": "2026-07-25T00:00:00Z",
        "evidence_bytes": len(raw),
        "evidence_path": path,
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "formal_evidence": True,
        "ingested_at": "2026-07-23T00:01:00Z",
        "pit_complete": True,
        "processed_at": "2026-07-23T00:02:00Z",
        "rule_version": f"{kind}-v1",
        "source": f"official-{kind}-source",
        "source_document_id": f"official-{kind}-document-v1",
        "source_type": (
            "broker_fee_schedule"
            if kind == FEE_SCHEDULE
            else "clearing_rulebook"
            if kind == SETTLEMENT
            else "exchange_rulebook"
        ),
    }


def _bundle_inputs(
    *,
    empty_kinds: tuple[str, ...] = (),
) -> tuple[dict[str, object], dict[str, bytes]]:
    evidence: dict[str, bytes] = {}
    metadata: dict[str, dict[str, object]] = {}
    for kind in (BOARD_LOT, PRICE_LIMIT, SELLABILITY, FEE_SCHEDULE, SETTLEMENT, SESSION):
        raw = (
            b""
            if kind in empty_kinds
            else json.dumps(
                {
                    "source_document_id": (
                        f"official-{kind}-document-v1"
                    )
                },
                sort_keys=True,
            ).encode()
        )
        path = f"evidence/{kind}.json"
        evidence[path] = raw
        metadata[kind] = _metadata(kind, path, raw)

    rules = [
        {
            **metadata[BOARD_LOT],
            "rule_kind": BOARD_LOT,
            "payload": {
                "buy_lot_size": 100,
                "odd_lot_sell_allowed": True,
                "odd_lot_sell_mode": "full_remainder_only",
                "sell_lot_size": 100,
            },
        },
        {
            **metadata[PRICE_LIMIT],
            "rule_kind": PRICE_LIMIT,
            "payload": {
                "has_price_limit": True,
                "lower_ratio": "0.10",
                "lower_rounding_mode": "floor",
                "upper_ratio": "0.10",
                "upper_rounding_mode": "ceiling",
            },
        },
        {
            **metadata[SELLABILITY],
            "rule_kind": SELLABILITY,
            "payload": {"sellable_after_sessions": 1},
        },
        {
            **metadata[FEE_SCHEDULE],
            "rule_kind": FEE_SCHEDULE,
            "tax_scope_complete": True,
            "payload": {
                "buy": [
                    {
                        "fixed_amount": "0",
                        "minimum_amount": "5",
                        "name": "commission",
                        "rate": "0.0003",
                        "rounding_mode": "ceiling",
                        "rounding_quantum": "0.01",
                    }
                ],
                "sell": [
                    {
                        "fixed_amount": "0",
                        "minimum_amount": "0",
                        "name": "stamp_tax",
                        "rate": "0.0005",
                        "rounding_mode": "ceiling",
                        "rounding_quantum": "0.01",
                    }
                ],
            },
        },
        {
            **metadata[SETTLEMENT],
            "rule_kind": SETTLEMENT,
            "payload": {
                "cash_settlement_sessions": 0,
                "position_settlement_sessions": 1,
                "same_day_sell_allowed": False,
            },
        },
    ]
    session = {
        **metadata[SESSION],
        "is_open": True,
        "phases": [
            {
                "accepts_orders": True,
                "ends_at": "2026-07-24T03:00:00Z",
                "name": "continuous",
                "starts_at": "2026-07-24T01:00:00Z",
            }
        ],
        "session_id": "2026-07-24-XSHG-main",
    }
    return (
        {
            "dataset_id": DATASET_ID,
            "dataset_version": VERSION,
            "pit_bridge": {
                "available_time": "2026-07-23T00:00:00Z",
                "complete": True,
                "dimension_mapping_complete": True,
                "event_time": "2026-07-22T00:00:00Z",
                "ingested_at": "2026-07-23T00:01:00Z",
                "processed_at": "2026-07-23T00:02:00Z",
                "version": "pit-bridge-v1",
            },
            "rules": rules,
            "schema_version": BUNDLE_SCHEMA,
            "sessions": [session],
        },
        evidence,
    )


def _publish_fixture(
    tmp_path: Path,
    bundle: dict[str, object] | bytes,
    evidence: dict[str, bytes],
    *,
    quality_status: str = "pass",
    blockers: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    shared_root = tmp_path / "shared"
    dataset = shared_root / "datasets" / DATASET_ID / VERSION
    dataset.mkdir(parents=True)
    bundle_bytes = (
        bundle
        if isinstance(bundle, bytes)
        else (
            json.dumps(bundle, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode()
    )
    all_files = {BUNDLE_FILE: bundle_bytes, **evidence}
    inventory = []
    for relative, raw in sorted(all_files.items()):
        path = dataset / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        inventory.append(
            {
                "bytes": len(raw),
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = build_manifest(
        dataset_id=DATASET_ID,
        dataset_version=VERSION,
        readiness_class="quality_checked",
        quality_status=quality_status,
        files=inventory,
        aggregate_sha256=aggregate_inventory_hash(inventory),
        total_bytes=sum(item["bytes"] for item in inventory),
        producer_commit="b" * 40,
        blockers=blockers,
        known_gaps=(),
        schema_name=BUNDLE_SCHEMA,
        published_at="2026-07-23T01:00:00Z",
    )
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (dataset / MANIFEST_NAME).write_text(serialized, encoding="utf-8")
    manifest_path = tmp_path / "committed-manifest.json"
    manifest_path.write_text(serialized, encoding="utf-8")
    return manifest_path, shared_root


def _consume(manifest: Path | None, shared_root: Path):
    return consume_cn_market_rule_bundle(
        manifest_path=manifest,
        shared_root=shared_root,
        handoff_event_id="published-current-main-cn-market-rule-fixture",
        handoff_validated=True,
        evaluated_at=EVALUATED,
        manifest_reference="HEAD:.agent/data_manifests/cn-market-rule.json",
    )


def _codes(result) -> set[str]:
    return {item.code for item in result.blockers}


def test_missing_or_invalid_current_main_handoff_fails_closed() -> None:
    missing = consume_cn_market_rule_bundle(
        manifest_path=None,
        shared_root=Path("unused"),
        handoff_event_id="",
        handoff_validated=False,
        evaluated_at=EVALUATED,
    )
    assert CN_MARKET_RULE_HANDOFF_MISSING in _codes(missing)
    assert {
        "board_lot_rule_missing",
        "price_limit_rule_missing",
        "sellability_rule_missing",
        "fee_schedule_rule_missing",
        "session_rule_missing",
        "settlement_rule_missing",
    }.issubset(_codes(missing))
    invalid = consume_cn_market_rule_bundle(
        manifest_path=None,
        shared_root=Path("unused"),
        handoff_event_id="unvalidated",
        handoff_validated=False,
        evaluated_at=EVALUATED,
    )
    assert CN_MARKET_RULE_HANDOFF_INVALID in _codes(invalid)
    assert all(value is False for value in invalid.safety_flags.values())


def test_complete_formal_bundle_binds_all_rules_and_is_read_only(tmp_path: Path) -> None:
    bundle, evidence = _bundle_inputs()
    manifest, shared_root = _publish_fixture(tmp_path, bundle, evidence)
    before = {
        path.relative_to(tmp_path).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    result = _consume(manifest, shared_root)
    after = {
        path.relative_to(tmp_path).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert result.status == "pass"
    assert result.decision == "research_only"
    assert {item.rule_kind for item in result.bindings} == {
        BOARD_LOT,
        PRICE_LIMIT,
        SELLABILITY,
        FEE_SCHEDULE,
        SESSION,
        SETTLEMENT,
    }
    assert all(item.source_document_id for item in result.bindings)
    assert all(value is False for value in result.safety_flags.values())

    preflight = run_market_semantics_preflight(
        consumption=result,
        dimensions=MarketDimensions(
            "XSHG",
            "main",
            "cash_equity",
            "common_stock",
            "CN.SECURITY.600000",
        ),
        as_of=EVALUATED,
    )
    assert preflight.status == "pass"
    assert preflight.decision == "research_only"
    assert set(dict(preflight.versions)) == {
        BOARD_LOT,
        PRICE_LIMIT,
        SELLABILITY,
        FEE_SCHEDULE,
        SESSION,
        SETTLEMENT,
    }
    assert all(value is False for value in preflight.safety_flags.values())


def test_unknown_security_dimensions_keep_every_rule_missing(tmp_path: Path) -> None:
    bundle, evidence = _bundle_inputs()
    manifest, shared_root = _publish_fixture(tmp_path, bundle, evidence)
    result = _consume(manifest, shared_root)
    preflight = run_market_semantics_preflight(
        consumption=result,
        dimensions=MarketDimensions(
            "XSHE",
            "unknown",
            "cash_equity",
            "common_stock",
            "CN.SECURITY.UNKNOWN",
        ),
        as_of=EVALUATED,
    )
    assert preflight.status == "blocked"
    assert {
        "board_lot_rule_missing",
        "price_limit_rule_missing",
        "sellability_rule_missing",
        "fee_schedule_rule_missing",
        "session_rule_missing",
        "settlement_rule_missing",
    }.issubset(preflight.blockers)
    assert preflight.versions == ()


def test_empty_fee_and_sellability_evidence_files_stay_missing(
    tmp_path: Path,
) -> None:
    bundle, evidence = _bundle_inputs(
        empty_kinds=(FEE_SCHEDULE, SELLABILITY)
    )
    manifest, shared_root = _publish_fixture(tmp_path, bundle, evidence)
    result = _consume(manifest, shared_root)
    assert result.status == "blocked"
    assert CN_MARKET_RULE_FILE_EMPTY in _codes(result)
    assert "fee_schedule_rule_missing" in _codes(result)
    assert "sellability_rule_missing" in _codes(result)
    assert FEE_SCHEDULE not in {item.rule_kind for item in result.bindings}
    assert SELLABILITY not in {item.rule_kind for item in result.bindings}


def test_web_source_and_incomplete_pit_bridge_never_resolve_rules(
    tmp_path: Path,
) -> None:
    bundle, evidence = _bundle_inputs()
    web_bundle = deepcopy(bundle)
    web_bundle["rules"][0]["source_type"] = "webpage"  # type: ignore[index]
    manifest, shared_root = _publish_fixture(
        tmp_path / "web",
        web_bundle,
        evidence,
    )
    web_result = _consume(manifest, shared_root)
    assert CN_MARKET_RULE_SOURCE_NOT_FORMAL in _codes(web_result)
    assert "board_lot_rule_missing" in _codes(web_result)

    pit_bundle = deepcopy(bundle)
    pit_bundle["pit_bridge"]["dimension_mapping_complete"] = False  # type: ignore[index]
    manifest, shared_root = _publish_fixture(
        tmp_path / "pit",
        pit_bundle,
        evidence,
    )
    pit_result = _consume(manifest, shared_root)
    assert CN_MARKET_RULE_PIT_BRIDGE_INCOMPLETE in _codes(pit_result)
    assert pit_result.bindings == ()
    assert len(
        {
            "board_lot_rule_missing",
            "price_limit_rule_missing",
            "sellability_rule_missing",
            "fee_schedule_rule_missing",
            "session_rule_missing",
            "settlement_rule_missing",
        }
        & _codes(pit_result)
    ) == 6


def test_future_rule_does_not_leak_version_or_retire_missing(
    tmp_path: Path,
) -> None:
    bundle, evidence = _bundle_inputs()
    future = deepcopy(bundle)
    future["rules"][0]["available_time"] = "2026-07-25T00:00:00Z"  # type: ignore[index]
    manifest, shared_root = _publish_fixture(tmp_path, future, evidence)
    result = _consume(manifest, shared_root)
    assert "board_lot_rule_not_available" in _codes(result)
    assert "board_lot_rule_missing" in _codes(result)
    assert BOARD_LOT not in {item.rule_kind for item in result.bindings}


def test_manifest_blockers_and_missing_manifest_remain_blocked(
    tmp_path: Path,
) -> None:
    bundle, evidence = _bundle_inputs()
    manifest, shared_root = _publish_fixture(
        tmp_path,
        bundle,
        evidence,
        quality_status="blocked",
        blockers=("formal_cn_market_rule_review_incomplete",),
    )
    blocked = _consume(manifest, shared_root)
    assert blocked.status == "blocked"
    assert "cn_market_rule_manifest_blocked" in _codes(blocked)
    assert len(blocked.bindings) == 0

    missing = _consume(tmp_path / "missing.json", shared_root)
    assert CN_MARKET_RULE_MANIFEST_MISSING in _codes(missing)


def test_consumer_and_preflight_have_no_network_or_write_surface() -> None:
    consumer_source = Path(
        "quant_cn/data/market_rule_consumer.py"
    ).read_text(encoding="utf-8")
    preflight_source = Path(
        "quant_cn/application/market_semantics_preflight.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "httpx",
        "urllib",
        "submit_order",
        "paper_start",
        "write_text(",
        "write_bytes(",
    )
    for token in forbidden:
        assert token not in consumer_source
        assert token not in preflight_source
