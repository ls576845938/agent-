from __future__ import annotations

from scripts.build_us_equity_data_status_report import evaluate_data_lineage_grade


def test_l1_sample_non_pit_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="derived_from_bars")

    assert grade["value"] == "L1_sample_non_pit"
    assert maturity["promotion_clean"] is False


def test_l2_static_snapshot_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="static_symbol_list")

    assert grade["value"] == "L2_static_snapshot"
    assert maturity["promotion_clean"] is False


def test_missing_point_in_time_universe_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True, corp=True, split=True, dividend=True, delisting=True, survivorship=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="static_symbol_list")

    assert grade["value"] != "L4_promotion_clean"
    assert maturity["point_in_time_universe_confirmed"] is False


def test_missing_corporate_action_source_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True, pit=True, split=True, dividend=True, delisting=True, survivorship=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="point_in_time_membership")

    assert grade["value"] == "L3_point_in_time_universe"
    assert maturity["corporate_action_event_source_available"] is False


def test_missing_delisting_coverage_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True, pit=True, corp=True, split=True, dividend=True, survivorship=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="point_in_time_membership")

    assert grade["value"] == "L3_point_in_time_universe"
    assert maturity["delisting_coverage_confirmed"] is False


def test_survivorship_not_clean_cannot_be_promotion_clean() -> None:
    maturity = _maturity(price=True, snapshot=True, pit=True, corp=True, split=True, dividend=True, delisting=True)

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="point_in_time_membership")

    assert grade["value"] == "L3_point_in_time_universe"
    assert maturity["survivorship_clean"] is False


def test_only_l4_allows_promotion_clean() -> None:
    maturity = _maturity(
        price=True,
        snapshot=True,
        pit=True,
        corp=True,
        split=True,
        dividend=True,
        delisting=True,
        identifier=True,
        adjustment=True,
        survivorship=True,
        promotion=True,
    )

    grade = evaluate_data_lineage_grade(maturity, universe_source_type="point_in_time_membership")

    assert grade["value"] == "L4_promotion_clean"
    assert maturity["promotion_clean"] is True


def _maturity(
    *,
    price: bool = False,
    snapshot: bool = False,
    pit: bool = False,
    corp: bool = False,
    split: bool = False,
    dividend: bool = False,
    delisting: bool = False,
    identifier: bool = False,
    adjustment: bool = False,
    survivorship: bool = False,
    promotion: bool = False,
) -> dict[str, bool]:
    return {
        "price_data_available": price,
        "universe_snapshot_available": snapshot,
        "point_in_time_universe_confirmed": pit,
        "corporate_action_event_source_available": corp,
        "split_adjustment_confirmed": split,
        "dividend_adjustment_confirmed": dividend,
        "delisting_coverage_confirmed": delisting,
        "identifier_mapping_available": identifier,
        "adjustment_reproducibility_confirmed": adjustment,
        "survivorship_clean": survivorship,
        "promotion_clean": promotion,
    }
