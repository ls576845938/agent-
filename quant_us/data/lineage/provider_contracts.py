"""Provider-neutral contracts for US equity PIT lineage sources.

The contracts are deliberately local-file oriented. They do not fetch vendor
data and they do not treat provider capability as promotion evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PointInTimeMembershipEvent:
    provider_id: str
    security_id: str
    ticker: str
    event_type: str
    effective_date: str
    end_date: str | None = None
    index_name: str | None = None
    exchange: str | None = None
    reason: str | None = None
    source_record_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PointInTimeUniverseSnapshot:
    provider_id: str
    universe_name: str
    as_of_date: str
    symbols: list[str]
    securities: list[str]
    symbol_count: int
    membership_event_count: int
    delisted_symbol_count: int
    point_in_time_confirmed: bool
    survivorship_clean: bool
    source_hash: str
    blockers: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CorporateActionEvent:
    provider_id: str
    security_id: str
    ticker: str
    event_type: str
    ex_date: str
    effective_date: str | None = None
    ratio: float | None = None
    cash_amount: float | None = None
    old_symbol: str | None = None
    new_symbol: str | None = None
    source_record_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderVerificationReport:
    provider_id: str
    source_type: str
    promotion_clean_allowed: bool
    local_data_available: bool
    required_tables_available: bool
    required_fields_available: bool
    record_count: int
    date_range: dict[str, str | None]
    sample_validation_pass: bool
    identifier_mapping_available: bool
    point_in_time_universe_confirmed: bool
    delisting_coverage_confirmed: bool
    corporate_action_event_source_available: bool
    adjustment_reproducibility_confirmed: bool
    survivorship_clean: bool
    promotion_clean: bool
    blockers: list[str] = field(default_factory=list)
    bundle_id: str | None = None
    bundle_manifest_path: str | None = None
    bundle_hash: str | None = None
    source_provider: str | None = None
    license_note: str | None = None
    production_bundle_preflight_report_path: str | None = None
    production_bundle_preflight_pass: bool = True
    selected_bundle_id: str | None = None
    selected_bundle_source_type: str | None = None
    selected_bundle_manifest_path: str | None = None
    explicit_bundle_selection_confirmed: bool = True
    promotion_clean_allowed_by_config: bool = True
    promotion_clean_allowed_by_manifest: bool = True
    active_bundle_validation_status: str = "pass"
    verified_artifacts: list[dict[str, Any]] = field(default_factory=list)
    bundle_record_count_by_table: dict[str, int] = field(default_factory=dict)
    bundle_date_range_by_table: dict[str, dict[str, str | None]] = field(default_factory=dict)
    bundle_validation: dict[str, Any] = field(default_factory=dict)
    structural_validation: dict[str, Any] = field(default_factory=dict)
    pit_validation: dict[str, Any] = field(default_factory=dict)
    survivorship_validation: dict[str, Any] = field(default_factory=dict)
    corporate_action_validation: dict[str, Any] = field(default_factory=dict)
    adjustment_replay_validation: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_provider_verification(
    *,
    provider_id: str,
    source_type: str = "none",
    promotion_clean_allowed: bool = False,
    local_data_available: bool,
    required_tables_available: bool,
    required_fields_available: bool,
    record_count: int,
    date_range: dict[str, str | None] | None = None,
    sample_validation_pass: bool,
    identifier_mapping_available: bool,
    point_in_time_universe_confirmed: bool,
    delisting_coverage_confirmed: bool,
    corporate_action_event_source_available: bool,
    adjustment_reproducibility_confirmed: bool,
    survivorship_clean: bool,
    bundle_id: str | None = None,
    bundle_manifest_path: str | None = None,
    bundle_hash: str | None = None,
    source_provider: str | None = None,
    license_note: str | None = None,
    production_bundle_preflight_report_path: str | None = None,
    production_bundle_preflight_pass: bool = True,
    selected_bundle_id: str | None = None,
    selected_bundle_source_type: str | None = None,
    selected_bundle_manifest_path: str | None = None,
    explicit_bundle_selection_confirmed: bool = True,
    promotion_clean_allowed_by_config: bool = True,
    promotion_clean_allowed_by_manifest: bool = True,
    active_bundle_validation_status: str = "pass",
    verified_artifacts: list[dict[str, Any]] | None = None,
    bundle_record_count_by_table: dict[str, int] | None = None,
    bundle_date_range_by_table: dict[str, dict[str, str | None]] | None = None,
    bundle_validation: dict[str, Any] | None = None,
    structural_validation: dict[str, Any] | None = None,
    pit_validation: dict[str, Any] | None = None,
    survivorship_validation: dict[str, Any] | None = None,
    corporate_action_validation: dict[str, Any] | None = None,
    adjustment_replay_validation: dict[str, Any] | None = None,
    extra_blockers: list[str] | None = None,
) -> ProviderVerificationReport:
    """Evaluate local provider evidence with explicit fail-closed blockers."""

    blockers = list(extra_blockers or [])
    if not local_data_available:
        blockers.append("provider_local_data_missing")
    if not required_tables_available:
        blockers.append("provider_required_tables_missing")
    if not required_fields_available:
        blockers.append("provider_required_fields_missing")
    if record_count <= 0:
        blockers.append("provider_record_count_zero")
    if not sample_validation_pass:
        blockers.append("provider_sample_validation_failed")
    if not identifier_mapping_available:
        blockers.append("identifier_mapping_missing")
    if not point_in_time_universe_confirmed:
        blockers.append("point_in_time_universe_not_confirmed")
        blockers.append("membership_events_missing")
    if not delisting_coverage_confirmed:
        blockers.append("delisting_coverage_missing")
    if not corporate_action_event_source_available:
        blockers.append("corporate_action_event_source_missing")
    if not adjustment_reproducibility_confirmed:
        blockers.append("adjustment_reproducibility_missing")
    if not survivorship_clean:
        blockers.append("survivorship_status_not_clean")
    if source_type not in {"fixture", "sample", "production", "research_price_bars", "none"}:
        blockers.append("source_type_invalid")
    if source_type == "fixture":
        blockers.append("fixture_source_not_promotion_ready")
    elif source_type == "sample":
        blockers.append("sample_source_not_promotion_ready")
    elif source_type != "production":
        blockers.append("source_type_not_production")
    if not promotion_clean_allowed:
        blockers.append("promotion_clean_not_allowed")
    if source_type == "production":
        if not production_bundle_preflight_pass:
            blockers.append("production_bundle_preflight_failed")
        if not explicit_bundle_selection_confirmed:
            blockers.append("explicit_bundle_selection_missing")
        if not promotion_clean_allowed_by_config:
            blockers.append("config_promotion_clean_not_allowed")
        if not promotion_clean_allowed_by_manifest:
            blockers.append("bundle_promotion_clean_not_allowed")
        if active_bundle_validation_status != "pass":
            blockers.append("active_bundle_validation_failed")

    required_for_promotion = [
        provider_id in {"local_csv", "crsp", "sharadar", "polygon", "norgate"},
        source_type == "production",
        promotion_clean_allowed,
        production_bundle_preflight_pass,
        explicit_bundle_selection_confirmed,
        promotion_clean_allowed_by_config,
        promotion_clean_allowed_by_manifest,
        active_bundle_validation_status == "pass",
        local_data_available,
        required_tables_available,
        required_fields_available,
        record_count > 0,
        sample_validation_pass,
        identifier_mapping_available,
        point_in_time_universe_confirmed,
        delisting_coverage_confirmed,
        corporate_action_event_source_available,
        adjustment_reproducibility_confirmed,
        survivorship_clean,
    ]
    promotion_clean = all(required_for_promotion) and not blockers

    return ProviderVerificationReport(
        provider_id=provider_id,
        source_type=source_type,
        promotion_clean_allowed=promotion_clean_allowed,
        local_data_available=local_data_available,
        required_tables_available=required_tables_available,
        required_fields_available=required_fields_available,
        record_count=max(0, int(record_count)),
        date_range=date_range or {"start": None, "end": None},
        sample_validation_pass=sample_validation_pass,
        identifier_mapping_available=identifier_mapping_available,
        point_in_time_universe_confirmed=point_in_time_universe_confirmed,
        delisting_coverage_confirmed=delisting_coverage_confirmed,
        corporate_action_event_source_available=corporate_action_event_source_available,
        adjustment_reproducibility_confirmed=adjustment_reproducibility_confirmed,
        survivorship_clean=survivorship_clean,
        promotion_clean=promotion_clean,
        blockers=_dedupe(blockers),
        bundle_id=bundle_id,
        bundle_manifest_path=bundle_manifest_path,
        bundle_hash=bundle_hash,
        source_provider=source_provider,
        license_note=license_note,
        production_bundle_preflight_report_path=production_bundle_preflight_report_path,
        production_bundle_preflight_pass=production_bundle_preflight_pass,
        selected_bundle_id=selected_bundle_id,
        selected_bundle_source_type=selected_bundle_source_type,
        selected_bundle_manifest_path=selected_bundle_manifest_path,
        explicit_bundle_selection_confirmed=explicit_bundle_selection_confirmed,
        promotion_clean_allowed_by_config=promotion_clean_allowed_by_config,
        promotion_clean_allowed_by_manifest=promotion_clean_allowed_by_manifest,
        active_bundle_validation_status=active_bundle_validation_status,
        verified_artifacts=verified_artifacts or [],
        bundle_record_count_by_table=bundle_record_count_by_table or {},
        bundle_date_range_by_table=bundle_date_range_by_table or {},
        bundle_validation=bundle_validation or {},
        structural_validation=structural_validation or {},
        pit_validation=pit_validation or {},
        survivorship_validation=survivorship_validation or {},
        corporate_action_validation=corporate_action_validation or {},
        adjustment_replay_validation=adjustment_replay_validation or {},
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
